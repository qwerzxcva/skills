# -*- coding: utf-8 -*-
"""
memory_schema.py — v4.0.0 状态机 / 优先级 / 领域枚举（纯加性设计）

设计原则：
- 所有字段都有安全默认值，旧记忆库（缺这些字段）recall 时降级返回默认值，不报错。
- 非法值不抛异常，落到 default（防御性，避免外部 / CLI 误用污染库）。
- 本模块被 memory_ops 包与 promote_rules.py / flat_mode.py 共用。

字段语义：
- state    : pending(待办/待验证) / confirmed(已确认) / resolved(已解决) / wont_fix(不修)
- priority : low / normal / high / critical
- area     : bugfix / feature / learning / decision
"""

STATE_ENUM = ("pending", "confirmed", "resolved", "wont_fix")
PRIORITY_ENUM = ("low", "normal", "high", "critical")
AREA_ENUM = ("bugfix", "feature", "learning", "decision")

# （新版协同方案 P1/C1）：「关于谁」四轴——让 keeper 从经验库升级为
# 「经验 + 个人事实库」。与 category（内容类型）/ area（工程区域）正交：
# - user : 关于用户本人的偏好/习惯/画像
# - self : 关于 AI 自身的能力边界/角色
# - relationship : 关于双方协作关系/约定
# - world : 关于外部市场/行业/世界的事实
DEFAULT_AXIS = None  # about_axis 默认无轴（纯经验，不是个人事实）

ABOUT_AXIS_ENUM = ("user", "self", "relationship", "world")

DEFAULT_STATE = "pending"
DEFAULT_PRIORITY = "normal"
DEFAULT_AREA = "learning"


def normalize_state(v, default=DEFAULT_STATE):
    """校验并归一 state；非法/None 落到 default。"""
    if v is None:
        return default
    v = str(v).strip().lower()
    return v if v in STATE_ENUM else default


def normalize_priority(v, default=DEFAULT_PRIORITY):
    if v is None:
        return default
    v = str(v).strip().lower()
    return v if v in PRIORITY_ENUM else default


def normalize_area(v, default=DEFAULT_AREA):
    if v is None:
        return default
    v = str(v).strip().lower()
    return v if v in AREA_ENUM else default


def normalize_about_axis(v, default=DEFAULT_AXIS):
    """校验并归一 about_axis；非法/None 落到 default（默认 None，表示纯经验非个人事实）。"""
    if v is None:
        return default
    v = str(v).strip().lower()
    return v if v in ABOUT_AXIS_ENUM else default


def safe_fields(state=None, priority=None, area=None, about_axis=None):
    """一次性归一字段，返回 dict（供 deposit / 迁移 / 导出统一使用）。"""
    return {
        "state": normalize_state(state),
        "priority": normalize_priority(priority),
        "area": normalize_area(area),
        "about_axis": normalize_about_axis(about_axis),
    }
