# -*- coding: utf-8 -*-
"""_self_heal.py — 统一自治循环（unified self-heal，

把原本散在 3 处的维护/进化/产物调度合并成单一真相源：
- dirty-mark 基础设施：记忆变更入口（deposit/forget/link 纠正）打标，self-heal 只读脏、
合并多次变更为一次重算。
- self_heal()：编排 reflect --auto / evolve 规则信号 / decay --apply / doctor --fix /
doctor --contradictions / skill-sync / export-rules --sync。
- skill_sync()：manifest 驱动，围栏内自动重写，纠正标 needs_review，绝不碰人类精炼区。
- export_rules_sync()：行为规则层围栏内自动重写（dirty 驱动 + .bak）。
- _verify_version_alignment()：版本一致性自检，分两层——**源码层**（SKILL.md frontmatter
  ↔ CHANGELOG.md 顶部，必须一致）与**安装层**（_meta.json = 平台上次发布版本，允许落后）。

设计原则（对齐用户硬方法论）：
- 全部离线（无 LLM 依赖），可安全每日定时跑；
- 加性、向后兼容：不破坏既有命令；self-heal 只是把已有能力串成一条默认全开的循环；
- 安全护栏：覆盖前 .bak（skill 文件 / AGENTS.md）、doctor --fix 自带整库 zip 备份；
- 受保护区（fenced region）：skill 的人类精炼层（frontmatter/示例/钩子/前言）永不被触碰。
"""
import os
import sys
import json
import hashlib
import datetime

# ── 路径工具 ────────────────────────────────────────────────
def _root_store(root):
    return os.path.join(root, "store")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _eng(attr):
    """运行时从引擎全局取符号（scripts/memory_ops/ 不在 sys.path，不能 `from _x import`）。

    __init__ 把 reflect/doctor/decay_apply/load_index 等注入到 __main__ / memory_ops 全局，
    这里按需取，避免子模块加载顺序耦合，也不依赖 sys.path（与既有兄弟模块取用方式一致）。
    """
    import sys as _s
    for _m in (_s.modules.get("__main__"), _s.modules.get("memory_ops")):
        if _m is not None and hasattr(_m, attr):
            return getattr(_m, attr)
    raise RuntimeError("engine symbol missing: %s" % attr)


    # ── dirty-mark 基础设施 ─────────────────────────────────────
    # 内存缓存：root_abspath -> set(mids)，避免每次 deposit 频繁读盘。
_DIRTY_CACHE = {}


def _dirty_path(root):
    return os.path.join(_root_store(root), "maintenance_dirty.json")


def mark_dirty(root, mid):
    """标记某记忆自上次 self-heal 后已变更。失败静默（标脏是辅助优化，绝不阻断主流程）。"""
    if not mid:
        return
    rab = os.path.abspath(root)
    s = _DIRTY_CACHE.get(rab)
    if s is None:
        s = set()
        p = _dirty_path(root)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    s = set(json.load(f).get("dirty_mids", []))
            except Exception:
                s = set()
        _DIRTY_CACHE[rab] = s
    if mid in s:
        return
    s.add(mid)
    _flush_dirty(root, s)


def _flush_dirty(root, s):
    try:
        os.makedirs(_root_store(root), exist_ok=True)
        with open(_dirty_path(root), "w", encoding="utf-8") as f:
            json.dump({"dirty_mids": sorted(s), "updated_at": _now()},
                      f, ensure_ascii=False, indent=2)
    except Exception as _e:
        # 2026-09-15 审计：dirty 标记落盘失败原先静默 → 维护循环可能整轮跳过却无迹可循。
        import sys as _sys
        _sys.stderr.write("[⚠ self-heal] dirty 标记落盘失败（本轮维护可能被跳过）：%s\n" % _e)


def get_dirty(root):
    rab = os.path.abspath(root)
    s = _DIRTY_CACHE.get(rab)
    if s is None:
        s = set()
        p = _dirty_path(root)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    s = set(json.load(f).get("dirty_mids", []))
            except Exception:
                s = set()
        _DIRTY_CACHE[rab] = s
    return set(s)


def clear_dirty(root):
    rab = os.path.abspath(root)
    _DIRTY_CACHE[rab] = set()
    p = _dirty_path(root)
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass
            # 兜底：若删除被环境拦截（如沙箱 safe-delete FAIL_CLOSED / 回收站不可用），
            # 仍把文件重写为空脏集，保证 get_dirty 返回空——否则下次 self-heal 会误判仍有脏工作、
            # 重复跑 reflect/doctor_fix/skill_sync（幂等但冗余）。真实环境 os.remove 成功则无此分支。
        if os.path.exists(p):
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump({"dirty_mids": [], "updated_at": _now()}, f)
            except Exception as _e:
                import sys as _sys
                _sys.stderr.write("[⚠ self-heal] 清空脏标记失败（下次 self-heal 会误判仍有脏工作、幂等重跑）：%s\n" % _e)


def mark_dirty_safe(root, mid):
    """变更入口调用的安全包装（deposit/forget/link 等），异常绝不外抛。"""
    try:
        mark_dirty(root, mid)
    except Exception:
        pass


        # ── 选择签名 ───────────────────────────────────────────────
def _hash_text(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(("" if p is None else str(p)).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def selection_signature(sel):
    """基于选中条目 id + 内容哈希生成稳定签名（成员变 / 内容变 → 签名变）。"""
    items = []
    for e in sel:
        items.append(_hash_text(
            e.get("id"), e.get("summary"), e.get("body"),
            ",".join(e.get("tags") or []), e.get("state"),
            e.get("priority"), e.get("status")))
    items.sort()
    return _hash_text(*items) if items else "empty"


    # ── skill 注册表 + 围栏 ────────────────────────────────────
_FENCE_BEGIN = "<!-- keeper-auto-begin (自动维护，勿手改) -->"
_FENCE_END = "<!-- keeper-auto-end -->"


def _registry_path(root):
    return os.path.join(_root_store(root), "skill_registry.json")


def _load_registry(root):
    p = _registry_path(root)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("skills", []) if isinstance(d, dict) else (d or [])
    except Exception:
        return []


def _save_registry(root, skills):
    try:
        os.makedirs(_root_store(root), exist_ok=True)
        with open(_registry_path(root), "w", encoding="utf-8") as f:
            json.dump({"skills": skills}, f, ensure_ascii=False, indent=2)
    except Exception as _e:
        # 2026-09-15 审计：注册表落盘失败原先静默 → 已注册 skill 会「看似注册了却丢了」。
        import sys as _sys
        _sys.stderr.write("[⚠ self-heal] skill 注册表落盘失败：%s\n" % _e)


def register_skill(root, manifest_path):
    skills = _load_registry(root)
    ap = os.path.abspath(manifest_path)
    if not any(os.path.abspath(s.get("manifest", "")) == ap for s in skills):
        skills.append({"manifest": ap, "registered_at": _now()})
        _save_registry(root, skills)


def _write_skill_fenced(skill_md_path, block):
    """重写 SKILL.md 中 keeper-auto 围栏内的内容；围栏外（frontmatter/人类区）保持不变。"""
    if os.path.exists(skill_md_path):
        with open(skill_md_path, encoding="utf-8") as f:
            content = f.read()
    else:
        content = ""
    new_block = "%s\n%s\n%s" % (_FENCE_BEGIN, block.strip("\n"), _FENCE_END)
    if _FENCE_BEGIN in content and _FENCE_END in content:
        pre = content.split(_FENCE_BEGIN, 1)[0]
        post = content.split(_FENCE_END, 1)[1]
        return pre + new_block + post
        # 无围栏（旧脚手架）：追加到末尾，用户可手动移到合适位置
    return content.rstrip() + "\n\n" + new_block + "\n"


def _backup_pair(files, keep=5):
    """覆盖前对受保护文件写 .bak.<ts>（保留最近 keep 个）。"""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for fp in files:
        if not os.path.exists(fp):
            continue
        try:
            bak = "%s.bak.%s" % (fp, ts)
            with open(fp, "rb") as src, open(bak, "wb") as dst:
                dst.write(src.read())
                # 仅保留最近 keep 个 .bak
            dirn = os.path.dirname(fp)
            base = os.path.basename(fp) + ".bak."
            olds = sorted([os.path.join(dirn, x) for x in os.listdir(dirn)
                           if x.startswith(base)]) if dirn else []
            for old in olds[:-keep]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass


            # ── skill-sync ─────────────────────────────────────────────
def skill_sync(root, dry_run=False, discover=False, force=False):
    """manifest 驱动，重算每个已注册 skill 的选择集；签名变化则重写围栏内区块 + patterns.md。

    行为（对齐用户拍板）：
    - 只读脏优化：dirty 为空且非 force → 所有 skill 选择集必不变，整体跳过（正确性成立：
    选择集仅由 deposit/forget/link 纠正改变，而这些入口都打了 dirty）。
    - 纠正（correct）：某源记忆 status=superseded → 标 needs_review=True 并在围栏内加注释行，
    但只改事实区，不碰 frontmatter/示例/钩子/前言。
    - 安全：覆盖前 .bak；patterns.md 是纯机器产物，整体重写；SKILL.md 仅改围栏内。
    """
    out = {"ok": True, "checked": 0, "updated": 0, "skipped": 0,
           "needs_review": [], "errors": [], "discovered": []}
    dirty = get_dirty(root)
    skills = _load_registry(root)
    if not skills:
        out["note"] = "无已注册 skill（先跑 extract-skill 生成脚手架）"
        # discover 仍可能发现新集群
    if not dirty and not force and not discover:
        out["skipped_all"] = True
        return out

    try:
        from promote_rules import select_entries
    except Exception as e:
        out["errors"].append("import select_entries failed: %s" % e)
        return out

        # 重新加载最新记忆（已 superseded 等状态），供纠正检测
        # 用 load_index 直接读索引（避免依赖 _deposit 注入名；scripts/memory_ops/ 不在 sys.path）
    try:
        load_index = _eng("load_index")
    except Exception:
        load_index = None

    for reg in skills:
        mpath = reg.get("manifest")
        if not mpath or not os.path.exists(mpath):
            out["errors"].append("manifest 缺失或已被移走: %s" % mpath)
            continue
        try:
            with open(mpath, encoding="utf-8") as f:
                man = json.load(f)
        except Exception as e:
            out["errors"].append("manifest 解析失败 %s: %s" % (mpath, e))
            continue
        flt = man.get("filter", {}) or {}
        try:
            sel = select_entries(
                root,
                area=flt.get("area"),
                state=flt.get("state"),
                priority=flt.get("priority"),
                filter_str=flt.get("filter_str"),
                min_count=flt.get("min_count", 3),
            )
        except Exception as e:
            out["errors"].append("select_entries 失败 %s: %s" % (mpath, e))
            continue
        out["checked"] += 1
        new_sig = selection_signature(sel)
        old_sig = man.get("signature")
        old_ids = set(man.get("source_ids") or [])
        new_ids = [e.get("id") for e in sel]
        if new_sig == old_sig and not force:
            out["skipped"] += 1
            continue

            # 漂移：检测纠正（源被 superseded）
        needs_review = bool(man.get("needs_review", False))
        review_notes = list(man.get("review_notes", []))
        corrected = []
        if load_index is not None:
            try:
                idx = load_index(root)
                by_id = {e.get("id"): e for e in idx.get("entries", [])}
                for sid in old_ids:
                    m = by_id.get(sid)
                    if m and m.get("status") == "superseded":
                        corrected.append(sid)
            except Exception:
                pass
        if corrected and not needs_review:
            needs_review = True
            review_notes.append("%s: 源记忆 %s 已被 superseded，请复核本 skill 的事实表述"
                                 % (_now(), ", ".join(corrected)))

        skill_dir = os.path.dirname(mpath)
        # 重写 patterns.md（纯机器产物，整体覆盖）
        pat_path = os.path.join(skill_dir, "references", "patterns.md")
        block = _render_pattern_block(sel)
        if not dry_run:
            _backup_pair([os.path.join(skill_dir, "SKILL.md"), pat_path])
            os.makedirs(os.path.dirname(pat_path), exist_ok=True)
            with open(pat_path, "w", encoding="utf-8") as f:
                f.write("# 萃取模式明细（references/patterns.md）\n\n"
                        "> 由 extract-skill 自动生成；每条来自 keeper 记忆库，id 可回溯源库。\n\n"
                        + block + "\n")
                # 重写 SKILL.md 围栏内
            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            new_md = _write_skill_fenced(skill_md_path, block)
            with open(skill_md_path, "w", encoding="utf-8") as f:
                f.write(new_md)
                # 更新 manifest
        man["signature"] = new_sig
        man["source_ids"] = new_ids
        man["needs_review"] = needs_review
        man["review_notes"] = review_notes
        man["last_synced_at"] = _now()
        if not dry_run:
            with open(mpath, "w", encoding="utf-8") as f:
                json.dump(man, f, ensure_ascii=False, indent=2)
        out["updated"] += 1
        if needs_review:
            out["needs_review"].append({"skill": os.path.basename(skill_dir),
                                         "manifest": mpath, "corrected": corrected})

            # 可选：发现已达标但未被任何 skill 覆盖的集群 → 自动建新 skill
    if discover:
        try:
            out["discovered"] = _discover_skills(root, select_entries, skills)
        except Exception as e:
            out["errors"].append("discover 失败: %s" % e)
    return out


def _render_pattern_block(sel):
    """生成围栏内模式清单（与 extract 同源，保证重生成一致）。"""
    groups = {}
    for e in sel:
        groups.setdefault(e.get("area", "learning"), []).append(e)
    lines = ["## 模式清单（自动维护区 · 由 extract-skill 生成，勿手改本块）", ""]
    for area, items in groups.items():
        lines.append("## %s\n" % area)
        for e in items:
            lines.append(
                "- **%s**（recurrence=%d, priority=%s, id=%s）：%s"
                % (e.get("summary", ""), e.get("recurrence_count", 1),
                   e.get("priority", "normal"), e.get("id", ""),
                   (e.get("body") or e.get("summary") or "")[:80]))
        lines.append("")
    return "\n".join(lines)


def _discover_skills(root, select_entries, existing_skills):
    """发现已达标（达到 min_count）但未被任何已有 skill 覆盖的 area 集群 → 自动建新 skill。

    保守策略：仅在 --discover 显式开启时运行；新 skill 落在 <root>/skills/auto/<area>-patterns，
    并登记进 registry；不会覆盖用户已 refine 的 skill。返回新建列表。
    """
    from skill_extract import extract
    discovered = []
    try:
        sel = select_entries(root, min_count=3)
    except Exception:
        return discovered
    if not sel:
        return discovered
    covered_ids = set()
    for reg in existing_skills:
        try:
            with open(reg.get("manifest"), encoding="utf-8") as f:
                covered_ids.update(json.load(f).get("source_ids", []))
        except Exception:
            pass
    uncovered = [e for e in sel if e.get("id") not in covered_ids]
    if not uncovered:
        return discovered
    areas = {}
    for e in uncovered:
        areas.setdefault(e.get("area", "learning"), []).append(e)
    base = os.path.join(root, "skills", "auto")
    for area, items in areas.items():
        if len(items) < 3:
            continue
        out_dir = os.path.join(base, "%s-patterns" % area)
        try:
            r = extract(root, min_count=3, out_dir=out_dir, llm=False, area=area)
            if r.get("ok") and r.get("count"):
                discovered.append({"area": area, "out_dir": out_dir, "count": r.get("count")})
        except Exception:
            pass
    return discovered


    # ── export-rules 自动 sync ──────────────────────────────────
def export_rules_sync(root, dry_run=False):
    """行为规则层围栏内自动重写：仅当选择集签名变化（记忆变更导致）才重写 + .bak。

    - 尊重 KEEPER_AUTO_EXPORT_RULES=0（关闭自动写，保留手动）。
    - 仅对「已初始化」的目标（用户先跑过一次 export-rules）生效；未初始化的不静默创建。
    """
    out = {"ok": True, "skipped": [], "updated": [], "disabled": False, "errors": []}
    if os.environ.get("KEEPER_AUTO_EXPORT_RULES") == "0":
        out["disabled"] = True
        return out
    sig_path = os.path.join(_root_store(root), "export_rules_sig.json")
    targets_path = os.path.join(_root_store(root), "export_rules_targets.json")
    if not os.path.exists(targets_path):
        out["note"] = "无已初始化的行为规则目标（先跑一次 export-rules 开启自动同步）"
        return out
    try:
        with open(targets_path, encoding="utf-8") as f:
            targets = json.load(f).get("targets", [])
    except Exception:
        targets = []
    if not targets:
        return out
    try:
        from promote_rules import export_rules
    except Exception as e:
        out["errors"].append("import export_rules failed: %s" % e)
        return out
    last_sig = {}
    if os.path.exists(sig_path):
        try:
            with open(sig_path, encoding="utf-8") as f:
                last_sig = json.load(f)
        except Exception:
            last_sig = {}
    new_sig = dict(last_sig)
    for target in targets:
        # text 目标路径由用户自定义，不可自动管理 → 跳过
        if target == "text":
            continue
        try:
            r = export_rules(root, target=target, sync=True,
                            last_sig=last_sig.get(target), dry_run=dry_run)
        except Exception as e:
            out["errors"].append("export_rules %s 失败: %s" % (target, e))
            continue
        if r.get("skipped"):
            out["skipped"].append(target)
        elif r.get("changed"):
            out["updated"].append(target)
            if not dry_run and r.get("signature") is not None:
                new_sig[target] = r["signature"]
    if not dry_run:
        try:
            with open(sig_path, "w", encoding="utf-8") as f:
                json.dump(new_sig, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return out


    # ── 四源版本对齐自检 ───────────────────────────────────────
def _skill_dir_of():
    """_self_heal.py 位于 <skill>/scripts/memory_ops/，上三级即 skill 根。

    4.7.12 修复：原先只上两级（到 scripts/），导致 SKILL.md/_meta.json/CHANGELOG.md
    全部读不到 → 三源均为 None → 被 `len(set) > 1` 判为「aligned=True」的**假绿**。
    修正为三级，真正读 skill 根的三处版本号做对齐自检。
    """
    p = os.path.abspath(__file__)
    for _ in range(3):
        p = os.path.dirname(p)
    return p


def _read_frontmatter_version(skill_md):
    try:
        with open(skill_md, encoding="utf-8") as f:
            txt = f.read()
        if not txt.startswith("---"):
            return None
        end = txt.find("\n---", 3)
        if end < 0:
            return None
        fm = txt[3:end]
        for line in fm.splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def _verify_version_alignment(skill_dir=None):
    """版本一致性自检 —— 分**两个语义层**（5.0.0 修正字段错配）：

    · **源码层（必须一致）**：SKILL.md frontmatter ↔ CHANGELOG.md 顶部。二者都是
      「本仓源码当前版本」，不一致 = 真错位 ⇒ `aligned=False`。
    · **安装层（允许落后）**：`_meta.json` = **平台上次发布 / 本机已安装版本**（发布器
      `update_meta()` 发布成功后回写）。开发者机器上它**必然落后**于源码（有未发布改动），  deadref-ok
      是常态 ⇒ 只报 `installed_lag`，**不判 `aligned=False`**。

    🔴 此前把三源混作「同一概念的三个来源」比对：开发者机器上必然 `aligned=False`，
    把**常态**当**错位**告警（同一错配在 `_doctor.release_audit` 里被当成
    「本地落后线上 ⇒ 双主前兆」，会引导人用线上包覆盖本地未发布改动）。

    返回 {aligned, sources:{...}, mismatch:[...], installed_lag:bool, notes:[...]}。
    仅告警、不致命（self-heal 用它自检）。
    """
    sd = skill_dir or _skill_dir_of()
    res = {"aligned": True, "sources": {}, "mismatch": [],
           "installed_lag": False, "notes": []}
    # 1) SKILL.md frontmatter —— 源码真源（本仓约定的版本单一真源）
    v_skill = _read_frontmatter_version(os.path.join(sd, "SKILL.md"))
    # 2) CHANGELOG.md 顶部 ## X.Y.Z —— 源码层第二源
    v_changelog = None
    cp = os.path.join(sd, "CHANGELOG.md")
    if os.path.exists(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("## "):
                        v_changelog = line[3:].strip().split()[0].lstrip("vV")
                        break
        except Exception:
            v_changelog = None
    # 3) _meta.json —— 安装层（平台上次发布 / 本机已安装版本）
    v_meta = None
    mp = os.path.join(sd, "_meta.json")
    if os.path.exists(mp):
        try:
            with open(mp, encoding="utf-8") as f:
                v_meta = (json.load(f) or {}).get("version")
        except Exception:
            v_meta = None
    res["sources"] = {"skill_md": v_skill, "changelog": v_changelog, "meta": v_meta}
    # 源码层比对（同一概念的两个源）
    src_vers = [v for v in (v_skill, v_changelog) if v]
    if len(set(src_vers)) > 1:
        res["aligned"] = False
        res["mismatch"] = [{"skill_md": v_skill, "changelog": v_changelog}]
    # 安装层：落后 = 有未发布改动 = 常态，只记录、不判错
    if v_meta and v_skill and v_meta != v_skill:
        res["installed_lag"] = True
        res["notes"].append(
            "本机安装版本（%s，取自 _meta.json）与源码版本（%s）不同 —— 源码领先表示有"
            "未发布改动，属开发者机器常态。" % (v_meta, v_skill))
    return res


    # ── 统一 self-heal 编排 ─────────────────────────────────────
def self_heal(root, force=False, dry_run=False, discover=False):
    """统一自治循环：把 reflect/evolve/decay/doctor/skill-sync/export-rules 串成默认全开的维护。

    节奏（避免抖动 + 长会话兜底）：
    - 即时新鲜度由会话结束钩子 converse --end 负责（已有）；本循环是「长会话/调度兜底」。
    - 每日（或 dirty 非空）：reflect --auto + evolve 规则信号 + doctor --fix + skill-sync + export-rules --sync。
    - 每月1日 / force：decay --apply（冷记忆降级）。
    - 每周日 / force：doctor --contradictions --fix（矛盾候选软标记，离线安全）。
    全部离线；evolve 仅应用「规则信号」（recurrence≥3，免 LLM、幂等、限期复核），LLM 信号保持 review-only。
    """
    out = {"ok": True, "root": root, "force": force, "dry_run": dry_run,
           "steps": {}, "version_alignment": None, "errors": []}
    today = datetime.date.today()
    is_sunday = today.weekday() == 6
    is_first = today.day == 1
    dirty = get_dirty(root)

    # 0) 版本四源对齐自检（仅告警）
    try:
        out["version_alignment"] = _verify_version_alignment()
        if not out["version_alignment"]["aligned"]:
            out["warnings"] = out.get("warnings", [])
            out["warnings"].append(
                "版本**源码层**未对齐（SKILL.md frontmatter ↔ CHANGELOG.md 顶部）: %s"
                % out["version_alignment"]["sources"])
    except Exception as e:
        out["errors"].append("version_alignment 自检失败: %s" % e)

        # 1) reflect --auto（去重/纠错/晋升/归档，0 删除）
    if dirty or force or is_sunday:
        try:
            reflect = _eng("reflect")
            f = reflect(root, auto=True)
            out["steps"]["reflect"] = {"ok": True, "findings": _safe_len(f)}
        except Exception as e:
            out["errors"].append("reflect 失败: %s" % e)

            # 2) evolve 规则信号（免 LLM、幂等、限期复核）默认 apply
    try:
        evolve = _eng("evolve")
        r = evolve(root, dry_run=dry_run, auto_apply=not dry_run, rule_signal_only=True)
        out["steps"]["evolve"] = {"applied": r.get("applied", 0),
                                  "skipped_existing": r.get("skipped_existing", 0)}
    except Exception as e:
        out["errors"].append("evolve 失败: %s" % e)

        # 3) decay --apply（每月 / force）：冷记忆确定性降级
    if is_first or force:
        try:
            decay_apply = _eng("decay_apply")
            r = decay_apply(root, dry_run=dry_run)
            out["steps"]["decay"] = {"ok": True, "changed": _safe_len(r)}
        except Exception as e:
            out["errors"].append("decay 失败: %s" % e)

            # 4) doctor --fix（索引↔文件自愈，自带整库 zip 备份）
    if dirty or force:
        try:
            doctor = _eng("doctor")
            d = doctor(root, fix=not dry_run)
            out["steps"]["doctor_fix"] = {
                "fixed": d.get("fixed"),
                "content_resynced": d.get("content_resynced", 0),
                "added": d.get("added", 0),
                "backup": d.get("fixed_backup"),
            }
        except Exception as e:
            out["errors"].append("doctor --fix 失败: %s" % e)

            # 5) skill-sync（manifest 驱动，围栏内自动重写）
    try:
        ss = skill_sync(root, dry_run=dry_run, discover=discover, force=force)
        out["steps"]["skill_sync"] = {k: ss[k] for k in
                                      ("checked", "updated", "skipped", "needs_review", "errors", "discovered")
                                      if k in ss}
    except Exception as e:
        out["errors"].append("skill_sync 失败: %s" % e)

        # 6) export-rules --sync（行为规则层围栏内自动重写）
    if os.environ.get("KEEPER_AUTO_EXPORT_RULES") != "0":
        try:
            ers = export_rules_sync(root, dry_run=dry_run)
            out["steps"]["export_rules_sync"] = {k: ers[k] for k in
                                                 ("updated", "skipped", "disabled", "errors")
                                                 if k in ers}
        except Exception as e:
            out["errors"].append("export_rules_sync 失败: %s" % e)

            # 7) doctor --contradictions --fix（每周日 / force；离线安全，仅软标记）
    if is_sunday or force:
        try:
            doctor = _eng("doctor")
            d = doctor(root, fix=not dry_run, contradictions=True)
            out["steps"]["contradictions"] = {
                "fixed": d.get("fixed"),
                "conflict_marked": d.get("conflict_marked", 0),
            }
        except Exception as e:
            out["errors"].append("contradictions 失败: %s" % e)

            # 收尾：清空 dirty（无论是否 force，本次已处理）
    if not dry_run:
        clear_dirty(root)
    return out


def _safe_len(x):
    if x is None:
        return 0
    if isinstance(x, (list, dict, tuple, set)):
        return len(x)
    if isinstance(x, str):
        return len(x)
    return 1
