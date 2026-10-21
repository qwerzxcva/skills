# -*- coding: utf-8 -*-
"""
p0_upgrade.py — keeper P0 升级（4.5.36 起，构思文档 keeper_upgrade_plan_v2.md 的落地）

四个杠杆（全部纯加性，不破坏既有行为）：
① 记忆图谱 + 矛盾自动仲裁（离线可用）
② 答案合成 RAG（recall --answer；HyDE + 合成，无 LLM 自动退回列表）
③ 原则蒸馏（distill --review 离线；--apply 需 LLM）
④ 主动施动 + 用户画像（deposit --why / profile；规则离线）

设计约束（来自方案）：
- 关系扩展复用现有 relations JSON（不建独立表）；新增 supports/refutes/is_a/part_of/derived_from。
- 自动动作全「只标不删、留版本链」（supersede/降权），绝不物理删除。
- LLM 用用户正在用的模型：Agent 调用时注入 KEEPER_LLM_* 环境变量即可（见 memory_ops._load_llm_config 的 env 覆盖）。
- 无 LLM 时：①仲裁/扩跳、④画像/--why、③--review、②降级列表，全部照常可用（零回归）。

本模块被 memory_ops.main() 的 graph/distill/profile/recall/dock 分支调用。
"""

import os
import sys
import json
import math

# ── 导入依赖（与 promote_rules.py 同模式：延迟 import，避免循环依赖）─────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import memory_ops as M


# ─────────────────────────────────────────────────────────────────────────────
# 关系类型（在既有 related_to/superseded_by/corrected_by/conflict 之上扩展）
# ─────────────────────────────────────────────────────────────────────────────
VALID_RELATIONS = (
    "related_to", "superseded_by", "corrected_by", "conflict",
    "supports", "refutes", "is_a", "part_of", "derived_from", "see_also",
)

# graph --build 离线规则阈值（与现有矛盾/去重阈值对齐，避免凭空拍数）
_REFUTES_SEM = 0.65      # 同 type + 语义≥0.65 + 对立信号 → 候选 refutes（对齐 CONTRADICTION_SEM_THRESHOLD）
_IS_A_SEM = 0.88         # 同 domain + 语义≥0.88 → 候选 is_a（对齐去重 supersede 0.88）
_PART_OF_SEM = 0.60      # 同 domain + 语义≥0.60 + 共享子域/标签 → 候选 part_of
_SUPPORTS_SEM = 0.70     # 同 type + 语义≥0.70 + 无对立信号 → 候选 supports
_MAX_EDGES_PER = 8       # 每条记忆每个关系类型最多连边数（防膨胀）

# 蒸馏门控（来自方案 3.3）
_DISTILL_MIN_SIZE = 3
_DISTILL_INTRA_COSINE = 0.85   # 簇内两两平均余弦≥0.85（贴近 supersede 0.88）
_DISTILL_INTRA_JAC = 0.55      # 词法后端下等价闸门（余弦不可得时）

# 图谱衍生边键（rebuild 时清空重算；区别于手动/doctor 边：related_to/superseded_by/
# corrected_by/conflict/derived_from 不参与图重建，rebuild 仅重算下面这 4 类）
_GRAPH_DERIVED_KEYS = ("supports", "refutes", "is_a", "part_of")


def _set_rel(mem, rel, target):
    """幂等地把 target 加入 mem.relations[rel]（纯 id 列表，兼容既有 related_to 风格）。"""
    if rel not in VALID_RELATIONS:
        return False
    rels = mem.setdefault("relations", {})
    lst = rels.setdefault(rel, [])
    if target not in lst:
        lst.append(target)
        return True
    return False


def _text_of(mem):
    return " ".join([mem.get("summary", ""), mem.get("body", ""),
                     " ".join(mem.get("tags", []))]).strip()


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆①：图谱自动建边（graph --build）
    # ─────────────────────────────────────────────────────────────────────────────
def graph_build(root, llm=None, dry_run=False, max_edges_per=_MAX_EDGES_PER):
    """全库扫描，基于「共享簇/标签/同型 + 规则阈值」推断 supports/refutes/is_a/part_of 边。

    离线为主：用 jaccard(_sim) + 共享标签/簇 + 同 type/domain 规则，零 LLM 依赖。
    有 LLM 时（llm=callable）对候选做轻量类型确认（best-effort，失败静默跳过，绝不影响离线结果）。
    返回 {built: 新增边数, by_type: {...}, dry_run: bool}。

    幂等：重复运行新增边集稳定（已存在的边不重复加）。
    安全：绝不删记忆、绝不改 status；只追加 relations JSON。
    """
    mems = {mid: m for mid, m in M._all_mems(root).items()
            if m.get("status") == "active"}
    ids = list(mems)
    # 离线相似度：优先复用落盘向量（余弦），否则 jaccard
    vecs = {}
    backend = M._emb_backend()
    use_cos = backend not in ("lexical", "none", "")
    embed_note = ""
    if use_cos:
        try:
            import embed as _emb
            vecs = M._emb_store_load_all(root) if hasattr(M, "_emb_store_load_all") else {}
        except Exception:
            vecs = {}
            # 回退一致性：声明用 cos 但向量空/加载失败 → 显式降级为 jaccard，
            # 否则会拿 jaccard 值去比对 cos 阈值（0.75/0.88…），几乎建不出边。
        if not vecs:
            use_cos = False
            embed_note = "（嵌入向量不可用，已降级为词法 jaccard 建边）"
    built = {"supports": 0, "refutes": 0, "is_a": 0, "part_of": 0}
    pending = {}  # mid -> {rel: set(targets)} 内存聚合，结束统一落盘

    def _sim_or_cos(a, b):
        ma, mb = mems.get(a), mems.get(b)
        if ma is None or mb is None:
            return 0.0
        if use_cos and vecs:
            va = vecs.get(a)
            vb = vecs.get(b)
            if va is not None and vb is not None:
                try:
                    import embed as _emb2
                    return _emb2.cosine(va[0], vb[0])
                except Exception:
                    pass
        return M._sim(_text_of(ma), _text_of(mb))

        # 预分组（标签，复用去重的大组跳过策略，避免 O(n²)）
    by_tag = {}
    for mid in ids:
        for t in (mems[mid].get("tags") or []):
            by_tag.setdefault(t, []).append(mid)

    cos_gate = _REFUTES_SEM if use_cos else _DISTILL_INTRA_JAC * 0.9
    # refutes 用更高精度闸门（该边最易误导，宁可漏不可错）：cosine 0.75 / jaccard 0.7
    refutes_gate = 0.75 if use_cos else 0.70
    for mid in ids:
        m = mems[mid]
        mtype = m.get("type", "") or m.get("category", "")
        mdomain = m.get("domain")
        # 候选：共享标签的记忆（小组合并，大组跳过）
        cand = set()
        for t in (m.get("tags") or []):
            grp = by_tag.get(t) or []
            if len(grp) <= 150:
                cand.update(grp)
        cand.discard(mid)
        for oid in cand:
            o = mems.get(oid)
            if o is None or o.get("status") != "active":
                continue
            otype = o.get("type", "") or o.get("category", "")
            odomain = o.get("domain")
            s = _sim_or_cos(mid, oid)
            # refutes：同 type + 高语义 + 对立信号（高精度闸门，避免误标矛盾）
            if otype and otype == mtype and s >= refutes_gate:
                if M._has_contradiction_signal(_text_of(m), _text_of(o)):
                    pending.setdefault(mid, {}).setdefault("refutes", set()).add(oid)
                    # 注意：此处不 continue —— 否则会跳过下方「同 domain 的 is_a/part_of
                    # 域块」，导致「同型同域且矛盾的记忆」漏建 part_of/is_a 边。
                    # refutes 与 part_of/is_a 语义正交，可并存。
                    # supports：同 type + 高语义 + 无对立信号（用 elif 避免与 refutes 重复建边）
                elif s >= (_SUPPORTS_SEM if use_cos else _DISTILL_INTRA_JAC):
                    pending.setdefault(mid, {}).setdefault("supports", set()).add(oid)
                    # is_a / part_of：同 domain（无论是否同 type/refutes，均参与建边）
            if odomain and odomain == mdomain:
                if s >= (_IS_A_SEM if use_cos else 0.9):
                    pending.setdefault(mid, {}).setdefault("is_a", set()).add(oid)
                elif s >= (_PART_OF_SEM if use_cos else _DISTILL_INTRA_JAC):
                    pending.setdefault(mid, {}).setdefault("part_of", set()).add(oid)

                    # 落盘（幂等，限制每类边数）。失败显式记录到 errors，绝不静默吞；
                    # built 计数以「成功落盘」为准——save 抛异常则不计入，避免 built≠磁盘。
    errors = []
    total = 0
    for mid, rels in pending.items():
        try:
            m, _ = M._load_mem(root, mid)
            if m.get("status") != "active":
                continue
            changed = False
            local_counts = {rel: 0 for rel in rels}
            for rel, tgts in rels.items():
                capped = list(tgts)[:max_edges_per]
                for t in capped:
                    if _set_rel(m, rel, t):
                        changed = True
                        local_counts[rel] += 1
            if changed and not dry_run:
                M._save_mem(root, mid, m)   # 可能抛异常 → 进入 except，不计入 built
            if changed:
                total += sum(local_counts.values())
                for rel, cnt in local_counts.items():
                    built[rel] = built.get(rel, 0) + cnt
        except Exception as e:
            errors.append({"mid": mid, "error": str(e)})

            # 可选 LLM 精化（best-effort）
    llm_note = ""
    if callable(llm) and total > 0:
        try:
            llm_note = "（LLM 精化：本版仅离线规则建边，LLM 精化在后续迭代启用）"
        except Exception:
            pass
    return {"ok": (len(errors) == 0), "built": total, "by_type": built,
            "dry_run": dry_run, "backend": backend,
            "note": (embed_note + llm_note).strip(),
            "embed_fallback": bool(embed_note), "errors": errors}


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆①：图谱清理与重建（graph --clean / graph --rebuild）
    # ─────────────────────────────────────────────────────────────────────────────
def graph_clean(root, dry_run=False):
    """清理所有关系键中指向「已不存在记忆」的悬空引用（如被 delete 的记忆留下的反向边）。

    安全：只删除无效的 id 字符串，绝不删记忆文件、绝不改 status。
    返回 {cleaned: 移除引用数, by_key: {关系键: 移除数}, dry_run}。
    """
    mems = M._all_mems(root)
    ids = set(mems.keys())
    by_key = {}
    total = 0
    for mid, m in mems.items():
        rel = m.get("relations") or {}
        changed = False
        for k in VALID_RELATIONS:
            v = rel.get(k)
            if not v:
                continue
            lst = v if isinstance(v, list) else [v]
            new_lst = [t for t in lst if t in ids]
            if len(new_lst) != len(lst):
                rel[k] = new_lst
                removed = len(lst) - len(new_lst)
                by_key[k] = by_key.get(k, 0) + removed
                total += removed
                changed = True
        if changed and not dry_run:
            M._save_mem(root, mid, m)
    return {"ok": True, "cleaned": total, "by_key": by_key, "dry_run": dry_run}


def graph_rebuild(root, llm=None, dry_run=False):
    """图谱重建 = 干净重算：①清理悬空引用 → ②清空图衍生边（supports/refutes/is_a/part_of）
    → ③graph_build 重算。用于消除历史 noise 边（如早期未经授权的 graph --build 累积）。

    安全：只动 relations JSON（清空重算图衍生边），绝不删记忆、绝不改 status。
    返回 {cleaned, cleared_memos, rebuilt, by_type, dry_run}。
    """
    clean = graph_clean(root, dry_run=dry_run)
    # 统计/清空图衍生边
    would_clear = 0
    for mid, m in M._all_mems(root).items():
        if m.get("status") != "active":
            continue
        rel = m.get("relations") or {}
        if any(rel.get(k) for k in _GRAPH_DERIVED_KEYS):
            would_clear += 1
    if not dry_run:
        for mid, m in M._all_mems(root).items():
            if m.get("status") != "active":
                continue
            rel = m.get("relations") or {}
            if any(rel.get(k) for k in _GRAPH_DERIVED_KEYS):
                for k in _GRAPH_DERIVED_KEYS:
                    rel.pop(k, None)
                M._save_mem(root, mid, m)
    built = graph_build(root, llm=llm, dry_run=dry_run)
    return {"ok": True, "cleaned": clean.get("cleaned", 0),
            "cleared_memos": 0 if dry_run else would_clear,
            "rebuilt": built.get("built", 0),
            "by_type": built.get("by_type", {}), "dry_run": dry_run}


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆①：recall 图谱扩跳（recall --hops N）
    # ─────────────────────────────────────────────────────────────────────────────
def _reverse_part_of_index(root):
    """构建 part_of 反向索引：parent_id -> [child_id,...]。

    正向 part_of 只覆盖「子→父」；召回扩跳时若当前节点是父，需找回其子记忆，
    用此反向索引实现「父→子」扩跳。仅收录 active 记忆，避免把已失效节点当锚点。
    """
    idx = {}
    try:
        mems = M._all_mems(root)
    except Exception:
        return idx
    for mid, m in mems.items():
        if (m.get("status") or "active") != "active":
            continue
        for p in ((m.get("relations") or {}).get("part_of") or []):
            if isinstance(p, str) and p:
                idx.setdefault(p, []).append(mid)
    return idx


def recall_expand_hops(root, entries, hops=1, max_per=4, max_total_extra=20):
    """沿 relations 把关联记忆加权追加到召回列表。

    遍历范围（决定图谱价值是否落地）：
    - 正向 对等/佐证/反驳：related_to / supports / refutes
    - 正向 整体→部分（向上）：part_of（子→父）
    - 正向 概念→实例（向上）：is_a
    - 反向 父→子：当前节点作为 parent 时，找回 part_of 指向它的子记忆
    不改变主 RRF 序；扩跳结果标记 associated_via=<边类型>，按距离降权追加到尾部。
    幂等：已命中的记忆不重复加。
    """
    if not hops or hops < 1 or not entries:
        return entries
    seen = {e.get("id") for e in entries if e.get("id")}
    extra = []
    frontier = [e.get("id") for e in entries if e.get("id")]
    reverse_part_of = _reverse_part_of_index(root)  # parent_id -> [child_id]

    def _mk_item(tm, rtype, step):
        return {
            "id": tm.get("id"),
            "category": tm.get("category", ""),
            "summary": tm.get("summary", ""),
            "tags": tm.get("tags", []),
            "tier": tm.get("tier", "working"),
            "scope": tm.get("scope", "universal"),
            "status": "active",
            "relations": tm.get("relations", {}),
            "version": tm.get("version", 1),
            "body": tm.get("body", ""),
            "confidence": tm.get("confidence", 1.0),
            "type": tm.get("type", ""),
            "domain": tm.get("domain"),
            "associated_via": rtype,
            "hops": step,
            "score": round(0.3 / step, 4),
        }

    for step in range(1, hops + 1):
        nxt = []
        for mid in frontier:
            try:
                mem, _ = M._load_mem(root, mid)
            except Exception:
                continue
            rels = (mem or {}).get("relations", {}) or {}
            # 正向：对等/佐证/反驳/整体-部分(向上)/概念-实例(向上)
            for rtype in ("related_to", "supports", "refutes", "part_of", "is_a"):
                for tgt in (rels.get(rtype) or []):
                    if tgt in seen:
                        continue
                    try:
                        tm, _ = M._load_mem(root, tgt)
                    except Exception:
                        continue
                    if not tm or tm.get("status") != "active":
                        continue
                    seen.add(tgt)
                    extra.append(_mk_item(tm, rtype, step))
                    nxt.append(tgt)
                    if len(extra) >= max_total_extra:
                        break
                if len(extra) >= max_total_extra:
                    break
                    # 反向：当前节点是父，找回其子（part_of 指向它的记忆）
            for child_id in (reverse_part_of.get(mid) or []):
                if child_id in seen:
                    continue
                try:
                    cm, _ = M._load_mem(root, child_id)
                except Exception:
                    continue
                if not cm or cm.get("status") != "active":
                    continue
                seen.add(child_id)
                extra.append(_mk_item(cm, "part_of", step))
                nxt.append(child_id)
                if len(extra) >= max_total_extra:
                    break
            if len(extra) >= max_total_extra:
                break
        frontier = nxt
        if len(extra) >= max_total_extra:
            break
    return entries + extra[:max_total_extra]


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆③：原则蒸馏（distill --review / --apply）
    # ─────────────────────────────────────────────────────────────────────────────
def _group_key(mem):
    """蒸馏硬门槛：同 domain + 同 type（绝不跨域——防污染核心闸）。"""
    dom = mem.get("domain") or ""
    typ = mem.get("type", "") or mem.get("category", "") or ""
    return (dom, typ)


def _intra_sim(a, b, use_cos, vecs):
    """a/b 为记忆 dict（非 id）。"""
    if use_cos and vecs:
        va = vecs.get(a.get("id"))
        vb = vecs.get(b.get("id"))
        if va is not None and vb is not None:
            try:
                import embed as _eb
                return _eb.cosine(va[0], vb[0])
            except Exception:
                pass
    return M._sim(_text_of(a), _text_of(b))


def distill_candidates(root):
    """离线发现蒸馏候选簇：同 domain+同 type（硬）+ 规模≥3 + 簇内两两平均相似≥门控。

    返回 [{"domain","type","members":[ids],"intra_sim":float,"size":int}]（按 intra_sim 降序）。
    纯离线、只读，不写盘。
    """
    mems = {mid: m for mid, m in M._all_mems(root).items()
            if m.get("status") == "active"}
    backend = M._emb_backend()
    use_cos = backend not in ("lexical", "none", "")
    vecs = {}
    if use_cos:
        try:
            vecs = M._emb_store_load_all(root) if hasattr(M, "_emb_store_load_all") else {}
        except Exception:
            vecs = {}
            # 与 graph_build 同款回退一致性：向量不可用 → 降级 jaccard（阈值随之切换）
        if not vecs:
            use_cos = False
            # 按 (domain,type) 分组 → 组内按 jaccard≥0.6 贪心成子簇
    groups = {}
    for mid, m in mems.items():
        groups.setdefault(_group_key(m), []).append(mid)
    candidates = []
    for (dom, typ), gids in groups.items():
        if dom == "" and typ == "":
            continue  # 无域无型不蒸馏（信息不足，防臆造）
            # 贪心聚类
        clusters = []
        for mid in gids:
            placed = False
            for cl in clusters:
                # 与簇内任一代表足够相似则并入
                rep = cl[0]
                if _intra_sim(mems[mid], mems[rep], use_cos, vecs) >= (_DISTILL_INTRA_COSINE if use_cos else _DISTILL_INTRA_JAC):
                    cl.append(mid)
                    placed = True
                    break
            if not placed:
                clusters.append([mid])
        for cl in clusters:
            if len(cl) < _DISTILL_MIN_SIZE:
                continue
                # 簇内两两平均相似
            sims = []
            for i in range(len(cl)):
                for j in range(i + 1, len(cl)):
                    sims.append(_intra_sim(mems[cl[i]], mems[cl[j]], use_cos, vecs))
            intra = sum(sims) / len(sims) if sims else 0.0
            gate = _DISTILL_INTRA_COSINE if use_cos else _DISTILL_INTRA_JAC
            if intra < gate:
                continue
            candidates.append({
                "domain": dom, "type": typ, "size": len(cl),
                "members": cl, "intra_sim": round(intra, 4),
            })
    candidates.sort(key=lambda c: c["intra_sim"], reverse=True)
    return candidates


def distill_apply(root, llm=None, dry_run=False):
    """对蒸馏候选簇生成 principle 记忆（需 LLM）。

    - LLM 读候选簇成员正文 → 生成 1 条 type=principle 记忆（带 domain/type 标签）。
    - relations.derived_from 链回成员 id。
    - 原记忆降权（importance/confidence 下调，不删、可 --expand 找回）。
    - 无 LLM（callable 为 None）→ 返回 {ok:False, error:"no_llm"}，原库不变。
    """
    cands = distill_candidates(root)
    if not cands:
        return {"ok": True, "applied": 0, "principles": [], "note": "无满足条件的蒸馏候选"}
    if not callable(llm):
        return {"ok": False, "error": "no_llm",
                "msg": "distill --apply 需要 LLM（用你正在用的模型：Agent 调用时注入 "
                       "KEEPER_LLM_BASE_URL/MODEL/API_KEY 即可）。可先跑 distill --review 看候选。",
                "candidates": len(cands)}
    made = []
    errors = []
    for c in cands:
        members = [m for m in (M._all_mems(root).get(x) for x in c["members"]) if m]
        if not members:
            continue
        sys_p = ("你是记忆蒸馏器。把一组「同领域同类型、高度相似」的记忆提炼成"
                 "一条更高层的【原则】记忆。原则必须：1) 用第一人称/陈述句；2) 只提炼"
                 "成员都支持的共性结论，不臆造成员没有的新事实；3) 中文，≤120字。")
        user_p = "领域=%s 类型=%s\n成员：\n" % (c["domain"] or "通用", c["type"] or "通用")
        for m in members:
            user_p += "- %s\n" % ((m.get("summary", "") or "")[:200])
        try:
            principle_text = llm(system=sys_p, user=user_p, max_tokens=200).strip()
        except Exception as e:
            principle_text = ""
        if not principle_text:
            continue
        if dry_run:
            made.append({"domain": c["domain"], "type": c["type"],
                         "principle": principle_text, "derived_from": c["members"]})
            continue
            # 落盘 principle 记忆（任一环节失败都显式记录，绝不静默吞）
        try:
            pid = M.deposit(root, c["type"] or "principle",
                            principle_text[:120],
                            "principle,%s,%s" % (c["domain"] or "通用", c["type"] or "通用"),
                            principle_text,
                            tier="core", scope="universal",
                            mem_type="principle",
                            domain=c["domain"] or None)
        except Exception as e:
            errors.append({"cluster": c["members"], "domain": c["domain"],
                           "type": c["type"], "stage": "deposit", "error": str(e)})
            continue
        if not isinstance(pid, str):
            errors.append({"cluster": c["members"], "domain": c["domain"],
                           "type": c["type"], "stage": "deposit",
                           "error": "deposit 未返回 id（返回 %r）" % (pid,)})
            continue
            # 链回 derived_from（失败即记录，不静默吞）
        try:
            pm, _ = M._load_mem(root, pid)
            pm.setdefault("relations", {})
            pm["relations"]["derived_from"] = list(c["members"])
            pm["derived_from"] = list(c["members"])
            M._save_mem(root, pid, pm)
        except Exception as e:
            errors.append({"cluster": c["members"], "pid": pid, "stage": "link_derived_from",
                           "error": str(e)})
            # 原则已创建但 derived_from 未挂上：仍计入 made，但带 warning 暴露不一致
            made.append({"id": pid, "domain": c["domain"], "type": c["type"],
                         "principle": principle_text, "derived_from": c["members"],
                         "warning": "derived_from 链回失败: %s" % e})
            continue
            # 原成员降权（不删，可 --expand 找回）；任一成员失败都显式记录
        member_errors = []
        for mid in c["members"]:
            try:
                om, _ = M._load_mem(root, mid)
                om["importance"] = round(max(0.1, float(om.get("importance", 0.5)) * 0.7), 4)
                om["confidence"] = round(max(0.1, float(om.get("confidence", 1.0)) * 0.85), 4)
                om["_distilled_into"] = pid
                M._save_mem(root, mid, om)
            except Exception as e:
                member_errors.append({"mid": mid, "error": str(e)})
        if member_errors:
            errors.append({"cluster": c["members"], "pid": pid,
                           "stage": "downweight_members", "member_errors": member_errors})
        made.append({"id": pid, "domain": c["domain"], "type": c["type"],
                     "principle": principle_text, "derived_from": c["members"]})
    return {"ok": (len(errors) == 0), "applied": len(made), "principles": made,
            "errors": errors, "dry_run": dry_run}


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆④：用户画像（profile）
    # ─────────────────────────────────────────────────────────────────────────────
def _is_substantive(m):
    """仲裁质量门：记忆是否「有实质内容」，可参与矛盾仲裁。

    排除测试/占位垃圾（如 body='x'、summary='vtest-*'），避免它们凭
    「更新即胜」规则把真实记忆顶成 superseded。判定：
    - body 存在且去空白后 ≥8 字符
    - summary 存在且去空白后 ≥4 字符
    - summary 不含 test/fixture/demo/mock/placeholder/vtest 等占位词
    """
    if not isinstance(m, dict):
        return False
    body = (m.get("body") or "").strip()
    summ = (m.get("summary") or "").strip()
    if len(body) < 8 or len(summ) < 4:
        return False
    low = summ.lower()
    for kw in ("vtest", "test-", "fixture", "demo", "mock", "placeholder", "__test"):
        if kw in low:
            return False
    return True


def _is_mechanical(m):
    """仲裁精度门②：记忆是否「机械自动捕获内容」（命令回放 / JSON 日志等）。

    这类内容（如 PF/skill 的 summary 是一坨 `{'exitCode':0,...}` JSON）会因其正文
    含『需要/不用/避免』等词误触发矛盾信号，但它们不是人类建议、彼此不构成真矛盾。
    仲裁应跳过它们，避免误标旧命令历史。
    判定：summary 去空白后以 { 或 [ 开头（JSON 块），或 recorded_by 属自动捕获。
    """
    if not isinstance(m, dict):
        return False
    summ = (m.get("summary") or "").strip()
    if summ[:1] in ("{", "["):
        return True
    rb = str(m.get("recorded_by") or "").lower()
    if rb in ("auto", "system", "daemon", "harvest", "converse", "auto_capture", "skill_extract"):
        return True
    return False


def _norm_ts(s):
    """把 created 时间归一化为可比较的浮点时间戳；无法解析返回 0.0。

    兼容：ISO 日期 '2026-07-28' / 带 T 的完整时间 '2026-07-28T13:11:48' /
    尾随 Z '2026-07-28T13:11:48Z' / Unix 秒戳字符串。解析失败 → 0.0（不参与排序）。
    避免不同格式的 created 直接字符串比较（'2026-07-28' >= '2026-07-28T13:11:48'
    会误判）导致仲裁胜者选错。
    """
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0
    if s.isdigit():                      # Unix 秒戳
        try:
            return float(s)
        except Exception:
            return 0.0
    t = s.replace("Z", "").replace(" ", "T")
    import datetime as _dt
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d",
                "%Y/%m/%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(t, fmt).timestamp()
        except Exception:
            continue
    return 0.0


def doctor_arbitrate(root, dry_run=False, strong_score=0.78, llm=None):
    """矛盾自动仲裁（doctor --contradictions --fix --arbitrate）：对强矛盾对自动 supersede 旧/低置信条。

    安全约束（来自方案 + 2026-08-04 精度修复）：
    - 只标 superseded，**绝物理删除**，记忆文件保留（可经 rollback 找回）。
    - 三重门防误杀：
    ① 质量门 `_is_substantive`：排除测试/占位垃圾（body=x、vtest-*）。
    ② 机械门 `_is_mechanical`：排除命令回放/JSON 日志等自动捕获内容（易误触发矛盾信号）。
    ③ LLM 确认门（有 LLM 时）：必须 LLM 确认『真矛盾（互斥）』才仲裁；
    离线且无 LLM 时**禁止真实写**（返回需 LLM 提示），仅 --dry-run 可预览。
    - 仲裁规则：较新 created + 较高 confidence 的记为胜者，另一条标 superseded。
    返回 {arbitrated:[{winner,loser,score}], count, skipped_mechanical, skipped_llm}。
    """
    try:
        cands = M._find_contradiction_candidates(root, threshold=strong_score)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    would, skipped_mechanical, skipped_llm = [], 0, 0
    for c in cands:
        a, b, sc = c.get("a"), c.get("b"), c.get("score", 0.0)
        if sc < strong_score:
            continue
        try:
            ma, _ = M._load_mem(root, a)
            mb, _ = M._load_mem(root, b)
        except Exception:
            continue
        if ma.get("status") != "active" or mb.get("status") != "active":
            continue
            # 门①：测试/占位垃圾不参与
        if not _is_substantive(ma) or not _is_substantive(mb):
            continue
            # 门②：机械自动捕获内容不参与（命令回放 JSON 易误触发矛盾信号）
        if _is_mechanical(ma) or _is_mechanical(mb):
            skipped_mechanical += 1
            continue
            # 选胜者：confidence 优先；平局时按 created 时间（归一化为可比较时间戳，
            # 兼容 ISO 日期 / 带 T 的完整时间 / Unix 秒戳；均解析不出 → 保持原序避免空串误判）。
        ca = float(ma.get("confidence", 1.0) or 1.0)
        cb = float(mb.get("confidence", 1.0) or 1.0)
        winner, loser = (a, b) if (ca >= cb) else (b, a)
        if ca == cb:
            da = _norm_ts(ma.get("created") or ma.get("created_at") or "")
            db = _norm_ts(mb.get("created") or mb.get("created_at") or "")
            if da or db:                       # 至少一方能解析出时间才比较
                winner, loser = (a, b) if da >= db else (b, a)
                # 门③：LLM 确认真矛盾（有 LLM 时强制；离线时仅预览、禁写实写）
        llm_verdict = None
        if callable(llm):
            try:
                verdict = (llm(system="判断两条记忆是否构成真矛盾（事实或建议互斥）。只回复 yes 或 no。",
                               user="A: %s\nB: %s" % (_text_of(ma)[:400], _text_of(mb)[:400]),
                               max_tokens=4) or "").strip().lower()
                llm_verdict = verdict or "(empty)"
                if not verdict.startswith("yes"):
                    skipped_llm += 1
                    continue
            except Exception as _le:
                llm_verdict = "error:%s" % type(_le).__name__
                skipped_llm += 1
                continue
        would.append((winner, loser, round(sc, 4)))
        # 离线真实写：禁止（矛盾判断需语义确认，避免误标旧真实记忆）
    if not dry_run and not callable(llm):
        return {"ok": False,
                "error": "离线 arbitrate 需 LLM 确认真矛盾（Agent 注入 KEEPER_LLM_* 即启用）；或先 --dry-run 预览",
                "would_arbitrate": [{"winner": w, "loser": l, "score": s} for w, l, s in would],
                "skipped_mechanical": skipped_mechanical, "skipped_llm": skipped_llm}
        # 去重：同一 loser 只接受首个 winner。避免标量 superseded_by 被 last-wins 覆盖，
        # 也避免各 winner 的 corrected_by 列表重复挂同一 loser 造成跨引用不一致。
    seen_loser = set()
    would_dedup = []
    for w, l, s in would:
        if l in seen_loser:
            continue
        seen_loser.add(l)
        would_dedup.append((w, l, s))

    done = []
    now = M.today() if hasattr(M, "today") else ""
    for winner, loser, sc in would_dedup:
        if dry_run:
            done.append({"winner": winner, "loser": loser, "score": sc})
            continue
            # 执行前复查：loser 或 winner 若已非 active（被本批次更早项 supersede，或状态已变），
            # 跳过，避免重复标 / 覆盖正确的 superseded_by。
        lo, _ = M._load_mem(root, loser)
        wi, _ = M._load_mem(root, winner)
        if lo.get("status") != "active" or wi.get("status") != "active":
            continue
            # 执行 supersede（镜像 deposit --corrects 的反向）
        lo.setdefault("relations", {})
        lo["relations"]["superseded_by"] = winner
        lo["status"] = "superseded"
        lo["superseded_at"] = now
        lo["settled"] = False
        # 审计痕迹：保留裁决依据，便于回滚与解释（score/verdict/by/at/winner/rule）
        lo["arbitration"] = {
            "score": round(sc, 4),
            "verdict": "contradiction",
            "by": "llm" if callable(llm) else "rule",
            "at": now,
            "winner": winner,
            "llm_verdict": llm_verdict,   # A1(4.5.45)：真实 LLM 裁决可追溯（离线/规则门则为 None）
            "rule": "rule: newer+confidence>lower (type/domain aligned)"
                    if not callable(llm) else "llm-confirmed contradiction",
        }
        M._save_mem(root, loser, lo)
        wi.setdefault("relations", {})
        wi["relations"].setdefault("corrected_by", [])
        if loser not in wi["relations"]["corrected_by"]:
            wi["relations"]["corrected_by"].append(loser)
        M._save_mem(root, winner, wi)
        done.append({"winner": winner, "loser": loser, "score": sc})
    return {"ok": True, "arbitrated": done, "count": len(done), "dry_run": dry_run,
            "skipped_mechanical": skipped_mechanical, "skipped_llm": skipped_llm}


def profile_build(root):
    """从记忆库离线推断用户画像（擅长/薄弱/当前重心），用于个性化注入与 recall 加权。

    纯规则（类型分布 + 域分布 + 访问/反馈模式），零 LLM 依赖。
    不跨域泄漏（画像项标 domain）。返回 dict（结构化，可 JSON 直出）。
    """
    mems = {mid: m for mid, m in M._all_mems(root).items()
            if m.get("status") == "active"}
    by_type = {}
    by_domain = {}
    by_axis = {}
    weak, strong = [], []
    for m in mems.values():
        t = m.get("type", "") or m.get("category", "") or "unknown"
        d = m.get("domain") or "通用"
        ax = m.get("about_axis") or "经验"
        by_type[t] = by_type.get(t, 0) + 1
        by_domain[d] = by_domain.get(d, 0) + 1
        by_axis[ax] = by_axis.get(ax, 0) + 1
        conf = float(m.get("confidence", 1.0) or 1.0)
        ac = int(m.get("access_count", 0) or 0)
        # 薄弱：低置信 或 多次被 bad 反馈（conf_beta 高）
        beta = float(m.get("conf_beta", 0) or 0)
        if conf < 0.5 or beta >= 2:
            weak.append({"id": m.get("id"), "summary": (m.get("summary", "") or "")[:60],
                         "confidence": conf, "neg_feedback": beta})
        elif ac >= 5 and conf >= 0.8:
            strong.append({"id": m.get("id"), "summary": (m.get("summary", "") or "")[:60],
                           "access_count": ac, "confidence": conf})
            # 当前重心：近 30 天 created 最多的域
    focus = {}
    try:
        from datetime import date, timedelta
        cut = (date.today() - timedelta(days=30)).isoformat()
        for m in mems.values():
            ca = m.get("created") or m.get("created_at") or ""
            if isinstance(ca, str) and ca[:10] >= cut:
                d = m.get("domain") or "通用"
                focus[d] = focus.get(d, 0) + 1
    except Exception:
        pass
    return {
        "ok": True,
        "total_active": len(mems),
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_domain": dict(sorted(by_domain.items(), key=lambda x: -x[1])),
        "by_axis": by_axis,
        "current_focus_30d": dict(sorted(focus.items(), key=lambda x: -x[1])),
        "strength_top": strong[:10],
        "weakness_top": weak[:10],
    }


    # ─────────────────────────────────────────────────────────────────────────────
    # 杠杆②：答案合成 RAG（recall --answer）
    # ─────────────────────────────────────────────────────────────────────────────
def answer_synthesis(root, query, llm=None, hops=1, entries=None):
    """recall --answer：HyDE 改写 → 召回 → LLM 带引用合成。

    降级：无 LLM（callable 为 None）→ 返回 {ok:False, degraded:True, entries: 列表}，
    调用方退回普通列表模式（零回归）。
    有 LLM → 返回 {ok:True, answer, sources:[{id,summary}]}。
    entries 可传入已召回列表（含 hops 扩跳结果），避免重复召回/递归。
    """
    # 主召回（含图谱扩跳）；entries 已提供则复用
    if entries is None:
        entries = M.recall(root, query=query, hops=hops, domain=None)
    if not callable(llm):
        return {"ok": False, "degraded": True,
                "msg": "无 LLM（用你正在用的模型：Agent 注入 KEEPER_LLM_* 即可启用答案合成）",
                "entries": entries[:10]}
        # HyDE：让 LLM 写一条「假想记忆」再 embed 召回（专治表述差异）
    try:
        hyde = llm(system="写一条可能回答用户问题的假想记忆（中文，≤80字，只输出正文）。",
                   user="用户问题：%s" % query, max_tokens=120).strip()
    except Exception:
        hyde = ""
    if hyde:
        hyde_entries = M.recall(root, query=hyde, hops=hops, domain=None)
        seen = {e.get("id") for e in entries}
        for e in hyde_entries:
            if e.get("id") not in seen:
                entries.append(e)
                seen.add(e.get("id"))
                # HyDE 命中与原查询命中按 score 降序重排，让 HyDE 命中的高相关记忆有机会进入 top-K
                # （原实现仅 append 到尾部，entries[:8] 永远取原查询前 8 条 → HyDE 几乎不被采用）。
    try:
        entries.sort(key=lambda e: float(e.get("score", 0) or 0), reverse=True)
    except Exception:
        pass
        # 取 top-K 原文
    top = entries[:8]
    ctx = "\n\n".join("[%s] %s\n%s" % (e.get("id"), e.get("summary", ""), (e.get("body", "") or "")[:300])
                      for e in top)
    sys_p = ("你是记忆问答助手。依据【给定记忆】回答用户问题，必须【逐条标注引用来源 id】"
             "（如 [LRN-001]），不得编造记忆之外的信息；若记忆不足以回答，明确说明'依据现有记忆'的边界。")
    user_p = "用户问题：%s\n\n【给定记忆】\n%s" % (query, ctx)
    try:
        answer = llm(system=sys_p, user=user_p, max_tokens=400).strip()
    except Exception as e:
        return {"ok": False, "degraded": True, "error": str(e), "entries": top}
    sources = [{"id": e.get("id"), "summary": (e.get("summary", "") or "")[:80]} for e in top]
    return {"ok": True, "answer": answer, "sources": sources, "hybrid_recall_count": len(entries)}
