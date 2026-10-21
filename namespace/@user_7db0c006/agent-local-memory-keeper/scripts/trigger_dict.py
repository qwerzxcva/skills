# -*- coding: utf-8 -*-
"""
trigger_dict.py — 触发词典（自然语言线索 → 预填 area/priority）

当用户用自然语言 deposit 时，
命中关键词自动给出 area/priority hint，减少 AI 漏填。仅作 hint，不强制——
若用户显式指定 --area/--priority，显式优先；hint 未命中则用 schema 默认值。

词典可用户覆盖：在 <root>/trigger.json 或 ~/.workbuddy/memory/keeper_trigger.json
放置 [{"pattern": "...", "area": "bugfix", "priority": "high", "reason": "..."}] 列表，
优先级高于内置默认词典。

安全：pattern 走 re 编译缓存，避免每次 deposit 重编译；匹配失败静默降级。
"""

import json
import os
import re

# 内置默认词典：(pattern, area, priority, importance, about_axis, reason)
# 顺序即优先级：先命中者生效（critical 类放前面优先）。
# （P2）：扩展为 6 元组——新增 importance(0~1 或 None) 与 about_axis(四轴或 None)。
# - "记住/记一下/千万别忘" → importance 0.9（用户强调要记）
# - "我偏好/我喜欢/我习惯/我讨厌/我反感" → about_axis=user + importance 0.7
# - "我们/咱俩/以后协作/约定" → about_axis=relationship
# - "市场/外部/行业/世界/大盘" → about_axis=world
_DEFAULT_TRIGGERS = [
    (r"严重|紧急|事故|线上|生产|崩溃|数据丢失|宕机|p0|p1", "bugfix", "critical", None, None,
     "严重事故类关键词"),
    (r"踩坑|踩过坑|坑位|翻车|bug|错误|报错|异常|失败|fix|修复|缺陷", "bugfix", "high", None, None,
     "错误/修复类关键词"),
    (r"记住|记一下|千万别忘|牢记|务必记住", None, None, 0.9, None,
     "用户强调要记（高重要性）"),
    (r"我偏好|我喜欢|我习惯|我讨厌|我反感|我拒绝|我口味|我每次都|我的偏好", None, None, 0.7, "user",
     "用户个人偏好/习惯（关于 user 轴）"),
    (r"我们|咱俩|以后协作|协作约定|咱俩的约定|合作方式", None, None, None, "relationship",
     "双方协作关系/约定（关于 relationship 轴）"),
    (r"市场|外部|行业|世界|大盘|宏观|外部世界|大环境", None, None, None, "world",
     "外部市场/世界事实（关于 world 轴）"),
    (r"决策|决定|拍板|选型|选择|结论|权衡|取舍", "decision", "high", None, None,
     "决策类关键词"),
    (r"需求|功能|feature|新增|实现|开发|上线|迭代", "feature", "normal", None, None,
     "功能类关键词"),
    (r"经验|学会|总结|规律|最佳实践|技巧|心得|教训|方法", "learning", "normal", None, None,
     "经验类关键词"),
]

# compiled cache
_cache = None


def _first(v, default):
    """返回 v 若非空（非 None 且非空字符串），否则 default。用于用户词典单命中。"""
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    return v


def _compiled():
    """返回 [(regex, area, priority, importance, about_axis, reason), ...]（含用户覆盖）。"""
    global _cache
    if _cache is not None:
        return _cache
    items = [(re.compile(p, re.IGNORECASE), a, p_, imp, ax, r)
             for (p, a, p_, imp, ax, r) in _DEFAULT_TRIGGERS]
    _cache = items
    return _cache


def load_user_triggers(roots=None):
    """加载用户级 / 项目级覆盖词典（合并到内置之前优先）。返回 list of dict。"""
    found = []
    candidates = []
    if roots:
        for r in roots:
            if r:
                candidates.append(os.path.join(r, "trigger.json"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".workbuddy",
                                   "memory", "keeper_trigger.json"))
    for c in candidates:
        try:
            if os.path.exists(c):
                with open(c, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    found.extend(data)
        except Exception:
            pass
    return found


def infer_trigger_hints(text, roots=None):
    """给定 summary+body 文本，返回 (area_hint, priority_hint, importance_hint, about_axis_hint, reason)。

    命中用户词典优先，否则内置默认词典；均未命中返回 (None, None, None, None, "")。
    hint 仅作建议，调用方决定如何使用（通常：显式优先 → hint → default）。
    importance_hint 为 0~1 浮点或 None；about_axis_hint 为四轴或 None。

    语义：领域类(area/priority)与「重要性/四轴」类互相独立——一条记忆可同时命中
    （如"记住这个坑"既是 bugfix 又高重要性）。采用「分类命中取首个 + 重要性/四轴取最高/首个」
    的合并策略，避免领域规则覆盖掉重要性/四轴 hint。
    """
    if not text:
        return (None, None, None, None, "")
    user_items = load_user_triggers(roots)
    # 用户词典优先（编译并匹配，多命中合并）
    for it in user_items:
        pat = it.get("pattern")
        if not pat:
            continue
        try:
            if re.search(pat, text, re.IGNORECASE):
                return (_first(it.get("area"), None), _first(it.get("priority"), None),
                        _first(it.get("importance"), None), _first(it.get("about_axis"), None),
                        it.get("reason", "user_trigger"))
        except re.error:
            continue
            # 内置默认：遍历所有规则，分类取首个命中、重要性取最高、四轴取首个命中
    area_h = prio_h = axis_h = None
    imp_h = None
    reasons = []
    for (rx, area, prio, imp, axis, reason) in _compiled():
        if rx.search(text):
            if area_h is None and area:
                area_h = area
            if prio_h is None and prio:
                prio_h = prio
            if axis_h is None and axis:
                axis_h = axis
            if imp is not None:
                imp_h = imp if imp_h is None else max(imp_h, imp)
            reasons.append(reason)
    if area_h is None and prio_h is None and imp_h is None and axis_h is None:
        return (None, None, None, None, "")
    return (area_h, prio_h, imp_h, axis_h, " / ".join(reasons) if reasons else "")
