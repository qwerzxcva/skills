#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classifier.py — 记忆分类「自主学习器」（多信号判断 + 自我纠正）

设计目标（用户要求）：
- 不能只做「相关性分类」——要综合多种情况判断（规则底噪 + 标签先验 + 访问证据 + 纠正对齐）。
- 有自主的学习/分析/判断能力： deposit 初判、recall/touch 累积访问证据、reflect 复评。
- 有「整理/纠正」能力：当发现某记忆归类错误，能及时调整（高置信自动纠正，低置信标审）。

核心 API：
base_scope(category, tags, body, summary)        → 规则底噪（与旧 _classify_scope 行为一致，保证回归不破）
load_model(root) / save_model(root, model)       → classifier.json 持久化（独立于 index.json，免臃肿）
classify(model, category, tags, body, summary)    → (scope, confidence, reasons)  多信号融合初判
learn_explicit(model, tags, category, scope, w)   → 显式/高置信纠正时「强学习」
learn_deposit(model, ..., scope, explicit)        → deposit 时累积（显式覆盖即强学习）
learn_access(model, mem)                          → 从 accessed_from 累积项目先验
detect_misclass(model, mem, mems)                 → 多信号误分类检测，返回 {suggest, confidence, reasons} 或 None

误分类检测信号（不只相关性）：
① tag 先验冲突：记忆标签的「已学可信先验」多数类与存储 scope 冲突且足够强
② 访问证据：universal 记忆只在某项目上下文被用过 → 候选降级 project；project 记忆跨 ≥2 项目/通用上下文被用 → 候选晋升 universal
③ ephemeral 被晋升(curated/core)或长期反复引用 → 实为耐久记忆，候选转 project/universal
④ 纠正对齐：被一条 universal 纠正记忆推翻的「旧最佳实践」，其 scope 应同为 universal
置信度：多信号叠加；≥0.6 自动纠正，0.4–0.6 标 scope_review 待审；<0.4 不动。
"""
import json
import os
from datetime import date as _date

SCOPES = ("universal", "project", "ephemeral")
TYPES = ("BP", "WF", "PF", "PREF", "FACT", "DOC")
MODEL_FILE = "classifier.json"
RULES_FILE = "classifier_rules.json"


# ── #17：访问证据时间衰减 ──────────────────────────────────────────────────
def _access_weight(date_str, today=None):
    """访问证据的时间衰减权重。

    近期访问权重更高，避免半年前的一次项目访问永远锁定 scope。
    30天内=1.0, 90天内=0.5, 180天内=0.25, 更久=0.1, 无日期=0.5。"""
    if not date_str:
        return 0.5
    if today is None:
        today = _date.today()
    try:
        d = _date.fromisoformat(str(date_str)[:10])
    except Exception:
        return 0.5
    days = (today - d).days
    if days <= 30:
        return 1.0
    elif days <= 90:
        return 0.5
    elif days <= 180:
        return 0.25
    else:
        return 0.1

        # ── #2：内置关键词规则（可被 classifier_rules.json 扩展，不替换）──────────────────
        # #18 修复：补充英文关键词，支持多语言用户的 scope 分类
_UNIVERSAL_KW = ("我", "用户", "永远", "必须", "不要", "习惯", "喜欢", "讨厌", "反感",
                 "拒绝", "通用", "所有", "每次", "都按", "别给我", "别动", "别改", "人人", "空腹",
# English: universal preferences / imperatives
                 "always", "never", "must", "don't", "do not", "habit", "prefer", "hate",
                 "dislike", "refuse", "everyone", "every time", "all users", "by default")
_PROJECT_KW = ("本项目", "这个任务", "本次", "这项目", "案子", "案", "周会", "金蝶",
               "代码", "仓库", "repo", "d:/", "git", "ppt", "合同", "记账", "报税", "fmri", "补考",
# English: project-specific context
               "this project", "this task", "codebase", "repo", "sprint", "standup",
               "pull request", "commit", "deploy", "pipeline", "contract", "invoice")
_EPHEMERAL_KW = ("这次", "临时", "周末", "明天", "本周", "一次性", "别忘了提醒",
                 "交暖气费", "上诉期", "二阶段", "boss",
# English: temporary / time-limited
                 "today", "tomorrow", "this week", "temporary", "one-time", "one time",
                 "reminder", "urgent", "asap", "deadline")
_CATEGORY_SCOPE = {
    "preference": ("universal", 1.5),
    "technical_constraint": ("universal", 1.5),
    "architecture_decision": ("universal", 1.5),
    "correction": ("universal", 0.5),
    "error": ("project", 1.0), "integration_error": ("project", 1.0),
    "feature_request": ("project", 1.0), "workflow": ("project", 1.0),
    "best_practice": ("project", 1.0), "knowledge_gap": ("project", 1.0),
}


def load_rules(root):
    """加载用户自定义分类规则（classifier_rules.json）。

    格式：{"universal_keywords": [...], "project_keywords": [...],
    "ephemeral_keywords": [...], "category_overrides": {"cat": "scope"}}
    与内置规则合并（扩展不替换），文件不存在时返回空 dict（行为不变）。"""
    p = os.path.join(root, RULES_FILE)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        if isinstance(r, dict):
            return r
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return {}


def save_rules(root, rules):
    """保存自定义分类规则到 classifier_rules.json。"""
    p = os.path.join(root, RULES_FILE)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


    # ── 规则底噪（与旧 _classify_scope 完全一致，保证无学习模型时行为不变）────────────
def base_scope(category, tags=None, body="", summary="", custom_rules=None):
    """规则底噪 scope 判定。custom_rules（来自 load_rules）可扩展关键词和 category 映射。"""
    tags = tags or []
    hay = " ".join([summary or "", body or "", " ".join(tags)]).lower()
    score = {"universal": 0.0, "project": 0.0, "ephemeral": 0.0}

    # category → scope 映射（内置 + 用户覆盖）
    cat_map = dict(_CATEGORY_SCOPE)
    if custom_rules and custom_rules.get("category_overrides"):
        for cat, scope in custom_rules["category_overrides"].items():
            if scope in SCOPES:
                cat_map[cat] = (scope, 1.0)
    if category in cat_map:
        sc, w = cat_map[category]
        score[sc] += w

        # 关键词匹配（内置 + 用户扩展，合并去重）
    uni_kw = set(_UNIVERSAL_KW)
    proj_kw = set(_PROJECT_KW)
    ephem_kw = set(_EPHEMERAL_KW)
    if custom_rules:
        uni_kw |= set(custom_rules.get("universal_keywords", []))
        proj_kw |= set(custom_rules.get("project_keywords", []))
        ephem_kw |= set(custom_rules.get("ephemeral_keywords", []))

    for s in uni_kw:
        if s.lower() in hay:
            score["universal"] += 0.6
    for s in proj_kw:
        if s.lower() in hay:
            score["project"] += 0.6
    for s in ephem_kw:
        if s.lower() in hay:
            score["ephemeral"] += 0.8

    best = max(score, key=score.get)
    if score[best] == 0.0:
        best = "universal"  # 安全默认：宁可留着，不要误埋
    return best


    # ── 模型持久化 ────────────────────────────────────────────────────────────────
def _default_model():
    return {"version": 1, "tag_scope": {}, "tag_type": {}, "project_hints": {}, "explicit_log": []}


def load_model(root):
    p = os.path.join(root, MODEL_FILE)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                m.setdefault("tag_scope", {})
                m.setdefault("tag_type", {})
                m.setdefault("project_hints", {})
                m.setdefault("explicit_log", [])
                return m
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return _default_model()


def save_model(root, model):
    p = os.path.join(root, MODEL_FILE)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


    # ── 学习 ──────────────────────────────────────────────────────────────────────
def learn_explicit(model, tags, category, scope, weight=2):
    """显式/高置信纠正时强学习：把标签→scope 先验加重（可信标签来源）。"""
    if scope not in SCOPES:
        return
    ts = model.setdefault("tag_scope", {})
    for t in (tags or []):
        d = ts.setdefault(t, {"universal": 0, "project": 0, "ephemeral": 0})
        d[scope] = d.get(scope, 0) + weight
        # 项目线索：project 记忆的标签 ↔ 项目 id 映射（供 deposit 初判参考）
    if scope == "project" and category:
        ph = model.setdefault("project_hints", {})
        key = (category or "") + "|" + ((" ".join(tags or []))[:24])
        ph[key] = ph.get(key, 0) + 1
    model.setdefault("explicit_log", []).append(
        {"tags": tags or [], "category": category or "", "scope": scope})


def learn_deposit(model, category, tags, body, summary, scope, explicit):
    """deposit 时累积：显式给定 scope（用户/AI 兜底）→ 强学习；自动初判 → 弱学习(weight=1)。"""
    if explicit:
        learn_explicit(model, tags, category, scope, weight=2)
    else:
        # 自动初判也轻量累积，让常用标签逐渐成形（弱先验）
        if scope in SCOPES:
            ts = model.setdefault("tag_scope", {})
            for t in (tags or []):
                d = ts.setdefault(t, {"universal": 0, "project": 0, "ephemeral": 0})
                d[scope] = d.get(scope, 0) + 1


def learn_access(model, mem):
    """从记忆的 accessed_from 证据累积「标签→scope 先验」（usage 即正样本）。
    #17 修复：访问证据时间衰减——近期访问权重更高，避免陈旧访问永久影响先验。"""
    af = mem.get("accessed_from") or []
    if not af:
        return
    scope = mem.get("scope")
    if scope not in SCOPES:
        return
        # 只取「项目上下文」强证据：在某项目被用 → 该记忆标签偏向 project
        # #17：加权累积——近期访问贡献 1.0，90天前仅 0.5，180天前仅 0.25
    proj_ctx = [e for e in af if e.get("project")]
    if scope == "project" and proj_ctx:
        ts = model.setdefault("tag_scope", {})
        for t in mem.get("tags", []):
            d = ts.setdefault(t, {"universal": 0, "project": 0, "ephemeral": 0})
            for e in proj_ctx:
                d["project"] = d.get("project", 0) + _access_weight(e.get("date"))


                # ── type 学习（#19：classify_type 纯规则无学习 → 纠正不反哺）──────────────────
def learn_type(model, tags, mem_type, weight=2):
    """显式/高置信纠正时强学习：把标签→type 先验加重。

    与 learn_explicit（scope）对称：用户纠正过 type 的标签组合，
    后续同标签新记忆初判即对齐，避免反复误分类。
    weight=3 用于显式 reclassify，weight=2 用于 reflect 自动纠正。"""
    if mem_type not in TYPES:
        return
    tt = model.setdefault("tag_type", {})
    for t in (tags or []):
        d = tt.setdefault(t, {ty: 0 for ty in TYPES})
        d[mem_type] = d.get(mem_type, 0) + weight


def learn_type_deposit(model, tags, mem_type, explicit):
    """deposit 时累积 type 先验：显式给定 → 强学习；自动初判 → 弱学习(weight=1)。"""
    if mem_type not in TYPES:
        return
    w = 2 if explicit else 1
    learn_type(model, tags, mem_type, weight=w)


def type_prior(model, tags):
    """返回 (best_type, confidence, margin) 或 None。

    聚合所有标签的 type 先验投票，取多数类。
    confidence 随 margin 增长（Δ2→0.6，Δ6+→0.85），不低于规则高置信 0.7 时才有覆盖价值。
    margin = 多数类票数 - 次多数类票数。"""
    tt = model.get("tag_type", {})
    if not tt:
        return None
    agg = {ty: 0 for ty in TYPES}
    found = False
    for t in (tags or []):
        d = tt.get(t)
        if d:
            found = True
            for ty in TYPES:
                agg[ty] += d.get(ty, 0)
    if not found:
        return None
    tot = sum(agg.values())
    if tot < 3:
        return None
    ranked = sorted(agg.items(), key=lambda x: -x[1])
    best, best_v = ranked[0]
    second_v = ranked[1][1] if len(ranked) > 1 else 0
    margin = best_v - second_v
    if best_v < 2 or margin < 2:
        return None
    conf = min(0.85, 0.55 + margin / 12.0)
    return best, round(conf, 2), margin


def detect_type_misclass(model, mem):
    """返回 None 或 {suggest, confidence, reasons}。

    信号：标签 type 先验多数类与现存 type 冲突且足够强。
    confidence ≥0.6 触发 reflect 自动纠正；<0.6 标审。"""
    cur = mem.get("type") or mem.get("category", "")
    if cur in TYPES:
        cur_type = cur
    else:
        return None  # 非规范 type 不检测
    tags = mem.get("tags", [])
    prior = type_prior(model, tags)
    if not prior:
        return None
    best_type, conf, margin = prior
    if best_type == cur_type:
        return None
        # 保守闸门：纯多数类先验(BP 主导)不足以翻转 type。
        # 仅当「存储类型在其标签上的先验支撑极弱(≤1)」且「建议类型支撑较强(≥3)」时才报，
        # 避免 BP 主导语料把 PF/PREF 记忆批量误推为 BP（popularity bias）。
    tt = model.get("tag_type", {})
    cur_support = sum(tt.get(t, {}).get(cur_type, 0) for t in tags)
    best_support = sum(tt.get(t, {}).get(best_type, 0) for t in tags)
    if cur_support >= 2 or best_support < 3:
        return None
    return {"suggest": best_type, "confidence": conf,
            "reasons": ["tag_type_prior->%s(Δ%d)" % (best_type, margin)]}


    # ── 分类（多信号融合初判）─────────────────────────────────────────────────────
def classify(model, category, tags, body, summary, custom_rules=None):
    """返回 (scope, confidence, reasons)。
    无学习模型时退化为 base_scope（与旧行为一致，回归安全）。
    custom_rules（来自 load_rules）可扩展规则底噪的关键词和 category 映射。"""
    base = base_scope(category, tags, body, summary, custom_rules=custom_rules)
    reasons = ["rule:%s" % base]
    scope = base
    conf = 0.5
    # 信号①：已学标签先验（可信来源，强于规则底噪）
    ts = model.get("tag_scope", {})
    agg = {"universal": 0, "project": 0, "ephemeral": 0}
    for t in (tags or []):
        d = ts.get(t)
        if d:
            for k, v in d.items():
                if k in agg:
                    agg[k] += v
    tot = sum(agg.values())
    if tot >= 3:
        maj = max(agg, key=agg.get)
        if maj != base and agg[maj] >= 2 and (agg[maj] - agg.get(base, 0)) >= 2:
            scope = maj
            conf = min(0.9, 0.6 + (agg[maj] - agg.get(base, 0)) / 20.0)
            reasons.append("tag_prior:%s(%d)" % (maj, agg[maj]))
    return scope, round(conf, 2), reasons


    # ── 误分类检测（多信号，不只是相关性）────────────────────────────────────────
def detect_misclass(model, mem, mems):
    """返回 None 或 {suggest, confidence, reasons}。
    综合：标签可信先验 / 访问证据 / ephemeral 晋升 / 纠正对齐。
    confidence 多信号取最强（独立证据），reflect 以 >=0.6 阈值自动纠正、否则标审。
    """
    cur = mem.get("scope", "universal")
    if cur not in SCOPES:
        cur = "universal"
    tags = mem.get("tags", [])
    reasons = []
    score = {"universal": 0.0, "project": 0.0, "ephemeral": 0.0}
    # ：独立证据累加器。signal①(语料先验)不算独立证据；只有
    # signal②(使用上下文)/③(晋升)/④(纠正对齐)计入，用于翻转前的硬性佐证闸门。
    indep = {"universal": 0.0, "project": 0.0, "ephemeral": 0.0}

    # 信号①：标签可信先验冲突（来自显式/高置信纠正的强学习，而非自举当前 scope）
    ts = model.get("tag_scope", {})
    agg = {"universal": 0, "project": 0, "ephemeral": 0}
    for t in tags:
        d = ts.get(t)
        if d:
            for k, v in d.items():
                if k in agg:
                    agg[k] += v
    tot = sum(agg.values())
    if tot >= 3:
        maj = max(agg, key=agg.get)
        if maj != cur and agg[maj] >= 2 and (agg[maj] - agg.get(cur, 0)) >= 2:
            margin = agg[maj] - agg.get(cur, 0)
            # 先验冲突越强，置信越高（Δ2→0.4，Δ6+→0.9），足以触发自动纠正
            strength = 0.4 + min(0.5, margin / 10.0)
            score[maj] += strength
            reasons.append("tag_prior->%s(%d,Δ%d)" % (maj, agg[maj], margin))

            # 信号②：访问证据（accessed_from）——真实的「在哪被用」
            # #17 修复：访问证据时间衰减——近期访问权重更高，避免半年前的一次项目访问
            # 永远锁定 scope。权重：30d=1.0, 90d=0.5, 180d=0.25, 更久=0.1。
    af = mem.get("accessed_from") or []
    scope_counts = {"universal": 0.0, "project": 0.0, "ephemeral": 0.0}
    proj_counts = {}
    for e in af:
        _w = _access_weight(e.get("date"))
        sc = e.get("scope")
        pr = e.get("project")
        if sc in scope_counts:
            scope_counts[sc] += _w
        if pr:
            proj_counts[pr] = proj_counts.get(pr, 0.0) + _w
    if cur == "universal" and scope_counts.get("universal", 0) == 0 and len(af) >= 3:
        # universal 记忆却从没在「通用上下文」被用过，只在某项目被用 → 候选降级（中置信，标审）
        top_proj = max(proj_counts, key=proj_counts.get) if proj_counts else None
        if top_proj and proj_counts[top_proj] >= 3:
            n = proj_counts[top_proj]
            score["project"] += 0.35 + min(0.15, n / 40.0)
            indep["project"] += 0.35 + min(0.15, n / 40.0)
            reasons.append("access->project:%s(%d)" % (top_proj, n))
    if cur == "project":
        distinct_projs = set(p for p in proj_counts if p != mem.get("project"))
        univ_ctx = scope_counts.get("universal", 0)
        if len(distinct_projs) >= 2:
            # 在 ≥2 个不同项目被用 → 确属跨项目通用经验（高置信，自动晋升 universal）
            score["universal"] += 0.6
            indep["universal"] += 0.6
            reasons.append("access->universal(%d跨项目)" % len(distinct_projs))
        elif univ_ctx >= 2:
            score["universal"] += 0.6
            indep["universal"] += 0.6
            reasons.append("access->universal(%d通用上下文)" % univ_ctx)

            # 信号③：ephemeral 被晋升或长期反复引用 → 实为耐久记忆
    if cur == "ephemeral" and (mem.get("tier") in ("curated", "core") or len(af) >= 4):
        score["project"] += 0.3
        indep["project"] += 0.3
        reasons.append("ephemeral_promoted")

        # 信号④：纠正对齐——被 universal 纠正记忆推翻的旧记忆，scope 应同为 universal
    cb = (mem.get("relations") or {}).get("corrected_by")
    if cb and cb in mems:
        cscope = mems[cb].get("scope", "universal")
        if cscope == "universal" and cur != "universal":
            score["universal"] += 0.3
            indep["universal"] += 0.3
            reasons.append("corrected_by_universal")

    if not reasons:
        return None
    best = max(score, key=score.get)
    if score[best] <= 0 or best == cur:
        return None
        # 保守闸门：纯多数类先验(signal①)不足以翻转 scope。
        # 必须经独立证据(使用上下文 signal② / 晋升 signal③ / 纠正对齐 signal④)佐证才报，
        # 否则在多数类主导语料上会系统性把少数类记忆误推为多数类(popularity bias)。
        # 例：project 记忆的标签多出现在 universal 记忆上 → 先验建议 universal，但无使用上下文佐证 → 不报。
    if indep[best] <= 0:
        return None
    conf = min(0.95, score[best])
    return {"suggest": best, "confidence": round(conf, 2), "reasons": reasons}


if __name__ == "__main__":
    # 自测：无模型时退化为规则底噪
    m = _default_model()
    print("base(preference):", base_scope("preference", [], "", "用户永远必须饭前服药"))
    print("classify(fresh):", classify(m, "error", ["git"], "本次提交失败", ""))
    # 学习后：error+git 多次为 project
    for _ in range(5):
        learn_explicit(m, ["git"], "error", "project", weight=2)
    print("classify(learned git->project):", classify(m, "error", ["git"], "本次提交失败", ""))
    print("detect(forced universal w/ project access ev):",
          detect_misclass(m,
                         {"scope": "universal", "tags": ["git"],
                          "accessed_from": [{"scope": "project", "project": "PROJ_A"} for _ in range(3)]},
                         {}))
    # type 学习自测
    m2 = _default_model()
    print("type_prior(fresh):", type_prior(m2, ["金蝶", "导出"]))
    # 学习：金蝶+导出 标签多次为 PF
    for _ in range(3):
        learn_type(m2, ["金蝶", "导出"], "PF", weight=3)
    print("type_prior(learned):", type_prior(m2, ["金蝶", "导出"]))
    print("detect_type(BP stored, prior PF):",
          detect_type_misclass(m2, {"type": "BP", "tags": ["金蝶", "导出"]}))
    print("detect_type(PF stored, prior PF):",
          detect_type_misclass(m2, {"type": "PF", "tags": ["金蝶", "导出"]}))
