# EVOLUTION · 智能进化与互补协同设计

> 维护者内部文档（开发者向）。用户向的能力说明见 `SKILL.md`「场景对话实操」⑥ 维护/进阶 与「投资记忆能力圈」段，及 `CHANGELOG.md` 对应条目。
>
> 本文件解释 **为什么这么设计**、**字段语义**、**幂等 / fail-open 关键不变量**，以及 **回归测试怎么验**。文中「早期 / 现已」等措辞指设计沿革，具体落在哪个版本以 `CHANGELOG.md` 为唯一权威源。

---

## 0. 用户核心诉求

> 「我需要它越用越聪明，也需要它能和 WorkBuddy 完全的相辅相成而不是谁做谁的镜像。」

拆成两件事：

1. **越用越聪明** = 自主形成原则（evolve）+ 信念校准 + 错误遗忘（belief/forget）+ 投资自动校验（verify-investment）。三支柱都落在 keeper 自身，不依赖外部。
2. **与 WB 互补而非镜像** = 清晰分工 + provenance 字段 + 幂等键消回声 + keeper→WB 单向蒸馏回流。

---

## 1. provenance 模型（互补的基石）

每条记忆落盘时带一组**结构化元数据**（按「是否参与召回硬过滤 / 审计」而非「是否敏感」划分，便于审计与去重比对）：

| 字段 | 语义 | 值例 |
|---|---|---|
| `provenance` | 来源类别 | `user` / `agent` / `wb` / `auto` |
| `provenance_key` | 幂等键（去重比对键） | WB 沉淀用 `<file>::<slug>`；auto 原则用信号 key |
| `src_origin` | 更细来源标记 | `self_evolve` / `workbuddy_harvest` |
| `auto_evolve` | 是否 evolve 自动生成 | `True` / 缺省 `False` |
| `belief_strength` | 信念强度 0–1 | 默认 `1.0`；`bad` 反馈下调 |
| `erroneous` | 是否被判错 | `forget` 置 `True` |
| `verified` | 投资校验结果 | `verify-investment` 写入 `True`/`False` |
| `review_by` | 限期复核截止 | evolve 原则 +30 天 |

**关键不变量**：`provenance` / `auto_evolve` / `belief_strength` / `erroneous` / `verified` 参与 L0 召回硬过滤与审计，**必须保持可直接读取的类型与值域**（改动即可能静默影响过滤与去重）；`provenance_key` / `src_origin` / `verified_source` / `review_by` 供 dedup 与复核链使用，取值规范同样不可随意变更；`summary` / `body` 为**自由文本**（唯一允许大块内容变更的两项）。⚠️ 早期曾把这组元数据划入「加密域」；**at-rest 加密能力现已整体移除**，故该划分不再适用——所有字段一律明文落盘，dedup 比对键仍是运行时内存值，不受影响。

---

## 2. evolve · 自我进化（自主形成原则）

**入口**：`evolve`（预览）/ `evolve --apply`（落盘）。
**引擎**：`scripts/memory_ops/_reflect.py::evolve`，经 `scripts/memory_ops/__init__.py` 别名导出。

### 2.1 流程
1. **synth 合成候选**：扫描「复发印证」经验（recurrence 候选 + 阈值命中），对每个信号生成一条原则 summary/body，附 `signal` 与 `key`（provenance_key）。
2. **幂等计数**：synth 阶段遇到「规则信号已存在 / LLM 信号重复」直接 `out["skipped_existing"] += 1`（**不在 apply 循环里重复计**，避免 `_existing_keys` 误计导致 applied 虚高）。
3. **apply 落盘**：对每条候选 `deposit(..., provenance="auto", provenance_key=key, src_origin="self_evolve", derives_from=<源记忆id>)`。`derives_from` 携带「刻意派生于该源」意图，写前查重守卫在派生情形下直接跳过近重复吞并，使原则作为**独立新节点**落盘（`derives_from` 取代早期 `skip_dedup=True` hack）。
4. **后置标记**：落盘记忆 `_load_mem` → 置 `auto_evolve=True` / `review_by=now+30d` → `_save_mem`；并据 `derives_from` 建溯源边（related edge）。

### 2.2 为什么 `derives_from` 取代 `skip_dedup`
早期用 `skip_dedup=True` 绕过写前 dedup 让 auto 原则落盘——但这是 hack：它**无差别跳过查重**，既放过「原则 vs 源记忆的近重复」也放过真正的重复。现改为显式 `derives_from`：**写前查重守卫仅在「本次 deposit 带 derives_from」时跳过近重复吞并**，其余情形仍正常去重。效果是——原则作为独立节点创建、同时留存指向源记忆的溯源边，源记忆保持 active 不被合并/取代；重复 `evolve --apply` 仍由 `_existing_keys` 幂等守护（`skipped_existing > 0`）。

> 教训：**不要为让某类记忆落盘而无差别跳过 dedup**；用「派生意图」语义化跳过，既保落盘又保去重。

### 2.3 回归不变量
- 落盘记忆 `provenance == "auto"`。
- `auto_evolve == True` 且 `review_by` 在未来。
- 重复 `evolve --apply` 后 `skipped_existing > 0`（不重复生成）。

---

## 3. belief_strength + forget · 错误遗忘

**入口**：`feedback --id <id> --signal good|bad`（引擎 `memory_ops/__init__.py::feedback`）；`forget --id <id> --forget-reason "..."`（引擎 `forget`）。

### 3.1 feedback 增强
- `good` → `belief_strength` 上调（封顶 1.0）。
- `bad` → 下调（每次 −0.3，地板 0.0）；低于 `_BELIEF_FLOOR=0.2` 时 `status=possibly_stale`（**不自动判错**，留人工）。
- 返回值 dict 现含 `belief_strength` / `utility_score` / `erroneous` / `status`（回归 `test_belief_and_forget` 曾因缺字段 KeyError）。

### 3.2 forget（显式遗忘）
- 置 `erroneous=True` + `belief_strength=0` + 归档（`recall` 默认不召回，可 `recall --deep` 找回）。
- **永不静默删内容**——符合 `SKILL.md`「红线与边界」A1「绝不批量硬删」。

---

## 4. verify-investment · 投资 DuckDB 校验（fail-open）

**入口**：`verify-investment --duckdb <路径> --sql-map <json>`。
**引擎**：`memory_ops/__init__.py::verify_investment(root, duckdb_path=None, sql_map=None, dry_run=True, max_items=50)`。

### 4.1 流程
- `sql_map`：每个 metric 对应一条**返回单值**的 SQL（如 `SELECT avg(pe) FROM holdings WHERE ticker=?`）。
- 对库内 `domain=investment` 记忆，逐条用 SQL 复算，与记忆中记的值比对。
- 不符 → `verified=False` 留待复核；相符 → `verified=True`。

### 4.2 fail-open 不变量（关键）
- DuckDB 不可达 / SQL 报错 → **只告警、不阻塞、不误判**（绝不把真结论标 `verified=False`）。
- 默认 `dry_run=True`；`--apply` 才写 `verified` 字段。
- **已消除静默 skip**：返回明确区分 `verified_true/false`（已复算）、`skipped`（已就绪但本记忆指标无可用 SQL，正常无需复算）、`needs_setup`（记忆本应校验却因缺 DuckDB / sql_map / DuckDB 不可用而**条件缺失未校验**，此前被静默吞掉）。存在 `needs_setup` 时附带 `default_sql_map_template`（bootstrap 模板）+ `setup_hint` 引导。
- 回归 `test_verify_investment_failopen`（更新）验证「库缺失时返回 ok、零写入、且计为 needs_setup 而非 skipped」；`test_v470_phase_e_verify.py` 锁死三种结局区分。

---

## 5. 与 WorkBuddy 互补（非镜像）

### 5·1 清晰分工
| 层 | 谁负责 | 落点 |
|---|---|---|
| 用户偏好 / 跨项目约定 | WorkBuddy | `~/.workbuddy/MEMORY.md`（user）+ `<ws>/.workbuddy/memory/`（workspace） |
| 可复用经验原则 + 证据链 | keeper | `AI_MEMORY_STORE`（`memories/` + `store/index.db`） |

### 5·2 幂等键消回声
- `harvest --with-workbuddy` 读 WB 三类记忆源：① `~/.workbuddy/MEMORY.md` ② cwd 向上回溯的 `.workbuddy/memory`（可 `WORKBUDDY_WORKSPACE` 短路）③ `~/.workbuddy/memory`（cloud）。
- 每条 WB 记忆落盘带 `provenance="wb"` + `provenance_key=<file>::<slug>`；重复 harvest 命中 `provenance_key` 即跳过（幂等键对照，不依赖 `skip_dedup`）。
- **反回声哨兵（anti-echo）**：落盘前对照 keeper 已有记忆，不把 WB 已记的再回声进 WB。

### 5.3 Windows 环境隔离盲区（测试必读）
managed Windows python 的 `os.path.expanduser("~")` 走 **`USERPROFILE` 而非 `HOME`**。回归测试 `test_wb_provenance_idempotent_and_antiecho` 早期仍读到真实 `MEMORY.md`，根因是只重定向 `HOME`。**必须三重重定向**：`HOME` + `USERPROFILE` + `WORKBUDDY_WORKSPACE`，并 `pop("AI_MEMORY_STORE")` 防误写真库。

### 5.4 distill-to-wb 单向蒸馏
- `distill-to-wb --apply` 把 keeper 高层原则**单向**回流到 `~/.workbuddy/MEMORY.md`；幂等去重 + 反回声，已回流不重复写。
- 这是「互补」而非「镜像」：keeper 是经验的**上游蒸馏源**，WB 是**下游沉淀**，方向单一、不回环。

---

## 6. 回归测试地图

`scripts/tests/test_v4613_evolution_synergy.py`（隔离环境助手 `run()`，三重重定向 + `pop AI_MEMORY_STORE`）及以下相位回归（`test_v470_phase_a/b/c/d/e_*`）均为 `unittest.TestCase`，随 `run_gate.py` 自动发现：

| 测试 | 验什么 |
|---|---|
| `test_evolve_and_schema` | evolve 落盘 `provenance=auto` + `auto_evolve` + `review_by`；原则带 `derives_from` 且为独立新节点（`derives_from` 取代 skip_dedup） |
| `test_belief_and_forget` | feedback 返回 belief_strength；forget 置 erroneous/belief_strength=0 + 归档 |
| `test_wb_provenance_idempotent_and_antiecho` | WB harvest 幂等（不重复沉淀）+ 反回声；隔离真实 `MEMORY.md` |
| `test_distill_to_wb_review` | distill-to-wb 预览/回流路径可用、幂等 |
| `test_verify_investment_failopen` | DuckDB 缺失时 fail-open、零写入、且计为 `needs_setup` 而非 `skipped` |
| `test_v470_phase_a_dedup_promotion.py` | 派生机制（derives_from 独立节点 + 幂等）/ 晋升评分门控（陈旧不晋升） |
| `test_v470_phase_b_storage.py` | scoped DELETE 无漂移 / 大库分批 chunk 不超 999 参数上限 |
| `test_v470_phase_c_cli.py` | `CAPABILITY_ZONES` 的 bridge_module/seed_fn 引用文件必须存在（防死引用漂移） |
| `test_v470_phase_e_verify.py` | verify-investment 三种结局区分（needs_setup / skipped / verified）；default_sql_map_template 引导 |

---

## 7. CLI 接线（门禁守护）

- `OP_NAMES`（`memory_ops/__init__.py`）登记 `evolve` / `distill-to-wb` / `verify-investment` / `forget`（共 62 op），与 `_cli.py` dispatch 分支、`argparse choices=OP_NAMES` 三处对齐。
- 一致性由 `test_op_consistency.py` 守护（不随发布包，`.skillhubignore` 排除）。
- `run_gate.py` 458 测试全绿（含 op-consistency），`gen_cookbook --strict` 无漂移。
