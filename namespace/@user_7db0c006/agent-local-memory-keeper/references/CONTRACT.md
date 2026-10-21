# 契约层（contract/）· 接线点与单一真源

> **受众**：keeper 的维护者 / 二次开发者。普通用户无需读。
> **定位**：契约层是「单一可测试实现」的集合——所有需要被钩子/doctor/门禁共用的核心逻辑，
> 都收口到 `scripts/contract/` 下的纯函数，钩子与命令**只做委托**，不内联重复逻辑。

---

## 一、四件套（scripts/contract/）

| 模块 | 职责 | 关键 API |
|---|---|---|
| `contract/__init__.py` | **注入闸门 `PreInjector`**：召回结果的相关性门控、预算裁剪、PII 护栏、注入指令护栏、优雅降级；纯函数，可单测。 | `PreInjector.inject(...)` → `InjectResult`；`tokenize` / `containment`（分词单一真源）；`is_injection`（注入指令检测） |
| `contract/router.py` | **路由登记 `RouteRegistry`**：记录每条记忆落地的 canonical 层（L2/L3/L4），跨层冲突检测，fail-open 持久化。 | `decide_and_record(mid, tags)`；`layers_of` / `all_conflicts` / `distribution` |
| `contract/consistency.py` | **矛盾只读扫描 `scan_contradictions`**：同语义轴显式极性相反检测（刻意窄覆盖，低误报）。 | `scan_contradictions(statements)` → 冲突列表 |
| `contract/observ.py` | **可观测 `doctor_contract` / `emit_inject_record` / `InjectLog`**：注入日志（JSONL 原子追加、有界轮转）与 doctor 健康聚合。 | `doctor_contract(...)`；`emit_inject_record(...)`；`InjectLog.append(...)` |

---

## 二、接线点（生产路径，非只单测）

深度体检曾指出「契约层工具测了却没接进生产」。现契约能力已接入生产路径：

| 生产入口 | 接的契约能力 | 行为 |
|---|---|---|
| `hooks/user_prompt_recall.py` | `PreInjector.inject` + `emit_inject_record` | 钩子委托注入闸门；每次注入写 `inject_log.jsonl`（fail-open） |
| `scripts/memory_ops/_deposit.py` | `RouteRegistry.decide_and_record` | 每条 deposit 登记 canonical 层（fact_key=mid），fail-open |
| `scripts/memory_ops/_doctor.py` | `doctor_contract` + `scan_contradictions` | doctor 聚合契约健康（门控阈值 / 路由分布 / 晋升候选 / 注入统计）；`--contradictions` 跑显式极性矛盾扫描 |
| `scripts/run_gate.py` | 全量随包单测 | 发布前必跑，断言契约层行为 |

---

## 三、单一真源约定

- **分词 `tokenize` / `containment`**：唯一真源在 `contract/__init__.py`。钩子 `keeper_hook_common.py`
  通过 `from contract import tokenize, containment` 引用（contract 不可导入时回退本地等价实现，fail-open）。
  **禁止**在钩子/命令里再写一份副本。
- **注入闸门**：唯一真源在 `PreInjector`。钩子不得内联自己的相关性/PII 判定。

---

## 四、缓存立场（重要，避免重复造轮子）

> **PreInjector 不做召回结果缓存。**

- 召回结果的真实缓存由 `memory_ops._recall_cache` 负责：**落盘、跨进程、TTL + 写失效**。
  钩子是每条消息一个独立进程，重复 query 会命中该磁盘缓存，无需在 PreInjector 层再建一份。
- PreInjector 只做**会话内注入去重**（`session_injected_ids`：同会话不重复注入同一条记忆），
  那是注入去重，不是召回结果缓存。
- 在 PreInjector 再加一层 `(session_id, query_hash)` 缓存，要么纯内存（进程结束即失效，钩子用不到），
  要么又落盘一份 → 等于第二个同数据缓存，引入失效/一致性复杂度。**刻意不建**，与「过度设计」红线相悖。

如需调整召回缓存行为，改 `memory_ops` 的 `_recall_cache`，不要动 PreInjector。
