# 记忆类型分类法（TYPE_TAXONOMY）

> 📌 **功能变更以根目录 `CHANGELOG.md` 为唯一权威源**。

> 配套：`memory_ops.py` 的 `TYPE_CANON` / `TYPE_ALIASES` / `_normalize_type()` / `classify_type()`。
> 本文是**判定规则表 + 混淆矩阵 + 旧版映射**，作为验证基准（非纯代码）。

## 1. 封闭互斥清单（TYPE_CANON）

`type` 只能取以下 6 个值之一，AI 按第 2 节规则判定；未知/空归 `FACT`。

| 短码 | 语义 | 典型内容 |
|---|---|---|
| `BP` | best_practice：经验证可复用的方法/步骤 | "用 Edit 改文件、别用 sed" |
| `WF` | workflow：多步流程/顺序 | "发布 skill：本地改→selftest→publish" |
| `PF` | pitfall：踩过的坑/反例 | "rrf_weak=0.03 会放噪音" |
| `PREF` | preference：用户长期习惯/口味 | "回复用中文、表格呈现" |
| `FACT` | fact：客观事实/环境常量 | "Wind MCP key 静态长效" |
| `DOC` | document：长文/报告摘要 | "v3 方案摘要" |

## 2. 判定规则 + 混淆矩阵（classify_type 实现映射）

> 优先级自上而下；命中即停。confidence 为规则置信，LLM 路由在 Phase 2 会覆盖/增强。

| 判定序 | 触发信号（含其一） | → type | conf | 易混点（纠正规则） |
|---|---|---|---|---|
| ① | 用户习惯/永远/必须/不要/喜欢/讨厌/反感/拒绝/偏好/口味/每次都/别给我 | `PREF` | 0.7 | 含事实陈述→拆成 `FACT`（如"用户喜欢中文"是 PREF；"中文是默认语言"是 FACT） |
| ② | 坑/踩过/别做/反例/失败/报错/出错/禁忌/切忌/雪崩/击穿/阻塞 | `PF` | 0.7 | 与 BP 互补：BP 写"该做"、PF 写"别做"；同主题两条应并存 |
| ③ | （步骤/流程/→/顺序）且（先/再/然后/第一步） | `WF` | 0.6 | 单步技巧→`BP` 不是 WF；WF 强调"顺序" |
| ④ | 正文 > 400 字 | `DOC` | 0.5 | 非摘要的长叙述→`BP`/`WF`；DOC 是"浓缩后的摘要" |
| ⑤ | 事实/常量/路径/端口/版本/api key/配置/地址/年份 | `FACT` | 0.6 | 会变的→`PF`（记"曾发现 X"）而非 FACT |
| ⑥ | 兜底 | `BP` | 0.5 | 默认可复用方法 |

**LLM 路由兜底**：路由不确定时回退到 `FACT`+`BP` 全量候选（不丢信息），日志记"低置信路由"。

## 3. 旧版 category → 规范 type 映射（TYPE_ALIASES）

> 迁移与 deposit 时自动规范化；记忆原文不变，仅补 `type` 标签。

| 旧 category | → type | 说明 |
|---|---|---|
| best_practice | BP | 直映 |
| workflow | WF | 直映 |
| pitfall | PF | 直映 |
| preference | PREF | 直映 |
| fact | FACT | 直映 |
| document / doc | DOC | 直映 |
| architecture_decision | BP | 架构决策是可复用经验 |
| principle | BP | 原则即最佳实践 |
| correction | PF | 纠错记忆本质是"别这样做"的坑 |
| error / integration_error | PF | 报错经验即坑 |
| feature_request | FACT | 需求描述偏事实 |
| knowledge_gap | FACT | 知识缺口偏事实 |
| technical_constraint | PREF | 技术约束即长期约束/偏好 |
| workbuddy_memory | FACT | 系统自身事实 |

**未知/空 → `FACT`**（设计基线「未知归 FACT」）。

## 4. 与 scope / status 的关系

- `type` 管"是什么性质"；`scope` 管"适用范围"（universal/project/ephemeral）；`status` 管"生命周期"（active/superseded/archived）。三者正交，互不重叠。
- `correction` 不再是 type：旧记忆纠正关系由 `status=superseded` + `relations.superseded_by` 表达（线上已有），新经验用 `deposit --corrects` 建立该关系；映射表里 `correction→PF` 只针对**独立存在的旧纠错记忆**，不新建 correction 类。

## 5. 配额（Phase 2 路由用，见设计基线 §4.3）

> **当前实现**：热常驻上限对**所有 type 统一为 `CAP_HOT_PER_TYPE = 5`**，全局热 `CAP_HOT_GLOBAL = 25`（`memory_ops.py` 常量），不按类型区分。下表「热上限」列统一填 5；设计基线 §4.3 曾规划按类型区分（如 FACT=7），但发货版统一为 5。

| type | 热上限（实装） | 温上限（设计基线，当前作慢检兜底通道、未硬设独立上限） |
|---|---|---|
| BP / WF / PF / PREF / FACT / DOC | 5 | 15（FACT）/ 10（DOC）/ 15（其余），仅作参考配额，非硬门 |
| 全局热 | ≤25 | — |
