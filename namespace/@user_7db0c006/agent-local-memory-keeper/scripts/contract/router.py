# -*- coding: utf-8 -*-
"""契约层：单一真源路由（RouteRegistry）—— 防跨层重复沉积。

设计目标（稳固优先）：
- 记忆分布在 L2（跨项目站立惯例）/ L3（本项目）/ L4（keeper 语义长库）三层。
同一条事实若在各层各存一份、各自演化 → 漂移、召回时"该信哪个"不清。
- 本模块提供**规则优先（非模型猜测）**的路由判定 + 去重登记册：
- `decide_home(tags, category, summary)`：按标签/分类把事实判到 canonical 层；
- `RouteRegistry`：记录"某事实已落在哪些层"，检测跨层重复（冲突只报告不自动改）。
- 纯逻辑、零副作用（持久化可选、fail-open），可单测；钩子 deposit 时查册防重复。

硬约束：本模块**不读 L2/L3 原生记忆**（keeper 无权直接读 WorkBuddy 原生库），
只维护 keeper 视角下的"已记录层"登记；跨系统真实去重由 doctor/矛盾扫描只读比对。
"""
import json
import os
import tempfile

LAYERS = ("L2", "L3", "L4")
DEFAULT_HOME = "L4"

# 规则：标签 → canonical 层（显式站立惯例/跨项目事实归 L2；项目相关归 L3；其余 L4）。
# 顺序即优先级；命中即返回，不叠加。
RULE_TAG_TO_LAYER = {
    "cross_project": "L2",
    "standing_convention": "L2",
    "whoami": "L2",
    "project": "L3",
    "this_project": "L3",
}
RULE_CAT_TO_LAYER = {
    "standing_convention": "L2",
    "project_context": "L3",
}
# A（4.9.26）：scope 字段 → canonical 层（让路由真正分流的主信号）。
# 背景（2026-09-15 真库实读）：RULE_TAG_TO_LAYER 的 5 个钥匙词在 216 条真库记忆中
# **命中 L2=0 / L3=1**（474 个去重标签、1629 次出现）—— 写成规则却从未被配发使用，
# 故 route_distribution 恒为 {L2:0, L3:0, L4:N}。而 `scope` 是本库 **100% 覆盖**的结构化字段
# （实测 universal 142 / project 70 / ephemeral 4），其语义与 L2/L3/L4 一一对应。
# 故在 tag 未命中时用 scope 兜底判定 —— 信号一直都在，只是原先读错了字段。
# 优先级：tag（用户显式动作）> scope（可能由分类器推断）> category > 默认 L4。
RULE_SCOPE_TO_LAYER = {
    "universal": "L2",   # 跨项目通用经验（谁都能用）→ 跨项目层
    "project": "L3",     # 限某个项目 → 本项目层
    "ephemeral": "L4",   # 临时/易过期 → 语义长库（默认家）
}


def decide_home(tags=None, category=None, summary=None, scope=None):
    """规则优先的 canonical 层判定（非模型）。

    优先级：**tag 钥匙词 > scope 字段 > category > 默认 L4**。
    - tag 最高：它是用户显式写下的意图（显式 > 推断）；
    - scope 次之：本库 100% 覆盖的结构化字段（universal/project/ephemeral），
      语义与 L2/L3/L4 一一对应，是 4.9.26 起让路由真正分流的主信号；
    - category 再次；全不命中回退 DEFAULT_HOME（"L4"）。
    """
    tags = [t for t in (tags or []) if t]
    for t in tags:
        if t in RULE_TAG_TO_LAYER:
            return RULE_TAG_TO_LAYER[t]
    if scope and scope in RULE_SCOPE_TO_LAYER:
        return RULE_SCOPE_TO_LAYER[scope]
    if category and category in RULE_CAT_TO_LAYER:
        return RULE_CAT_TO_LAYER[category]
    return DEFAULT_HOME


class RouteRegistry:
    """跨层去重登记册（内存为主，可选 JSON 持久化）。

    用法（钩子 deposit 时）：
    reg = RouteRegistry(path)
    home, conflicts = reg.decide_and_record(fact_key, tags, category, summary)
    if conflicts:  # 该事实已落在多个层 → 提示/合并，不自动改
    ...
    """

    def __init__(self, store_path=None):
        self.store_path = store_path
        self._data = {}  # fact_key -> set(layer)
        if store_path and os.path.exists(store_path):
            try:
                with open(store_path, encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in (raw or {}).items():
                    self._data[k] = set(v)
            except Exception:
                self._data = {}

    def record(self, fact_key, layer):
        if layer not in LAYERS:
            raise ValueError("unknown layer: %r" % layer)
        self._data.setdefault(fact_key, set()).add(layer)

    def layers_of(self, fact_key):
        return sorted(self._data.get(fact_key, set()))

    def conflicts(self, fact_key):
        """返回该事实落地的层列表；若 >1 层即视为跨层重复冲突。"""
        return self.layers_of(fact_key)

    def is_duplicate(self, fact_key):
        return len(self._data.get(fact_key, set())) > 1

    def all_conflicts(self):
        return {k: sorted(v) for k, v in self._data.items() if len(v) > 1}

    def distribution(self):
        """各 canonical 层落地计数（L2/L3/L4）。doctor 用来展示「事实按标签/分类应归哪层」的分布，
        并据此给出晋升候选（canonical 为 L2/L3 但物理只存在 L4 的事实）。"""
        d = {k: 0 for k in LAYERS}
        for layers in self._data.values():
            for l in layers:
                if l in d:
                    d[l] += 1
        return d

    def promotion_candidates(self, limit=None):
        """「可晋升/跨项目」事实清单（附 canonical 层与依据）——替代原先的裸计数。

        背景（2026-09-15 审计）：`distribution()` 只给计数，doctor 显示
        `route_promotion_candidates: 212` 时**无法据此行动**（不知道是哪 212 条、该做什么）。
        改为返回可操作清单：每条给出 `fact_key` 与 canonical 层；`limit` 只截断返回长度，
        `count` 仍由调用方从 distribution 取全量。

        ⚠️ 诚实边界：本方法只反映 **keeper 视角**的 canonical 层判定；keeper 无权读
        L2/L3 原生记忆（见模块头硬约束），故它**不是**「跨系统重复检测器」，
        不要据此宣称为跨层去重。
        """
        items = []
        for k, layers in self._data.items():
            home = None
            if "L2" in layers:
                home = "L2"
            elif "L3" in layers:
                home = "L3"
            if home:
                items.append({"id": k, "layer": home})
        items.sort(key=lambda x: (x["layer"], x["id"]))
        return items[:limit] if limit is not None else items

    def decide_and_record(self, fact_key, tags=None, category=None, summary=None,
                          scope=None):
        home = decide_home(tags, category, summary, scope=scope)
        self.record(fact_key, home)
        return home, self.conflicts(fact_key)

    def save(self):
        if not self.store_path:
            return
        try:
            d = os.path.dirname(os.path.abspath(self.store_path))
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix="._tmp_", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({k: sorted(v) for k, v in self._data.items()},
                              f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.store_path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
        except Exception:
            pass  # fail-open：持久化失败不影响 deposit
