# mem_bridge 命令参考（共进型桥接）

> 本文件是根 `mem_bridge.py` 全部子命令的权威表，补 `COMMANDS.md` 只收 `memory_ops` 的缺口。
> mem_bridge 负责 WorkBuddy 原生记忆(L2/L3) 与 agent-local-memory-keeper(L4) 的「共进型」桥接——媒介是 agent，两端永不直接互写（治自反馈死循环）。

---

## ⚠️ 同名异义说明 · `audit`

两个 CLI 都有 `audit` 子命令、含义却不同，是 footgun：

| 入口 | `audit` 含义 |
|---|---|
| `memory_ops` 的 `audit` | 按库规模推荐「该开哪些功能」（`audit_features`） |
| `mem_bridge` 的 `audit`（旧名） | 只读扫描内部近重复/矛盾（I5，成对 cosine） |

**mem_bridge 侧命令名为 `scan_dup`**（原名 `audit`），与 `memory_ops audit` 同名异义、互不冲突；`memory_ops audit` 是 commands 目录里的规范命令。调用时按入口区分即可。

---

## 一、桥接主链路（AI 最常用）

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `inject` | keeper→WB 只读注入活跃经验（不回写任何 WB 文件） | `--query/--top/--no-header/--reinforce/--explain/--budget-lines/--from-agent` |
| `distill` | WB→keeper 受控提炼（仅显式调用、带 source/rev 戳 + 去重，绝不整库抄） | `--text/--file/--category/--source/--summary/--body/--tags/--working/--decision/--subtype` |
| `feedback` | 闭环使用反馈，强化/弱化 keeper 经验 | `--mid X,Y --used\|--good\|--bad` 或 `--from-inject --used\|--good\|--bad` |
| `working` | I6 列出进行态记忆（半空接班，续上未竟工作） | — |
| `graph` | I12 关系图（以某 MID 为中心遍历关联/纠正链） | `--around <mid>` |
| `inject_stats` | inject 注入统计（命中/去重/计数） | — |
| `to-l2` | P2 跨系统晋升导出：筛选高价值 L4 经验生成草稿（MD/JSON），由用户/AI 经 WB 自身捕获落 L2/L3；**不直写 WB 文件** | `--min-importance/--min-access/--top/--export/--format md\|json` |

---

## 二、内部基础设施命令（COMMANDS.md 未收，此处补全）

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `rank` | 候选排序（路由前打分） | — |
| `route` | 路由判断（该走哪条记忆） | — |
| `retrieve` | 检索取回（桥接检索封装） | — |
| `capture` | 捕获/暂存（被动捕获入口） | — |
| `guard` | I10 发布前安全检查：扫描文本/文件泄露并报告 | `--text/--file` |
| `drift` | I13 版本漂移检查（记忆落库版本 vs 当前版本） | — |
| `seed` | I7 冷启动播种（按领域预载经验，供工作区钩子调用） | `--domain <项目领域>` |
| `compress` | I11 日志压缩（>N 天日志抽摘要并入 MEMORY.md） | `--stale 30/--apply` |
| `coach` | B 语义卫生教练（agent=零配置用 Agent 自身模型） | `--llm agent\|off` |
| `selftest` | 整改回归自测：隔离库自动化核心路径，发布前必跑 | — |
| `purge` | C3 受控真遗忘（委托 `memory_ops reclaim`）：默认 DRY-RUN 报告候选、绝不碰 active；`--apply` 才真删归档/被取代的软删记忆，带 `--older/--min-imp` 护栏与 core/保护标签护栏 | `--apply/--older 180/--min-imp 0.4` |
| `decay` | D2 确定性衰减（委托 `memory_ops decay_apply`）：重算 relevance_score（默认 dry-run 预览） | `--apply/--decay-lambda/--incremental` |
| `recurrence` | D3 重复模式簇报告（委托 `memory_ops recurrence_report`） | `--min-count`/`--auto-candidate` |
| `promote` | A1 晋升环（subprocess 调 `memory_ops promote`）：自主晋升/合并（--auto）或用户确认晋升（--review/--confirm） | `--tier`/`--auto`/`--review`/`--apply` |
| `reflect` | B1 双模式自检（规则 reflect + 可选 Agent 推理委托 / Ollama 离线增强） | `--auto/--llm/--undo` |
| `taxonomy` | 用户场景分类树管理（向导产物落地）：`apply`(持久化 taxonomy.json)/`show`(渲染)/`reclassify`(按自定义域重路由，advisory) | `--mode apply\|show\|reclassify --json <路径>` |
| `summary-index` | 索引摘要（桥接封装，同 memory_ops 同名命令） | — |
| `tree-view` | 记忆树状概览（桥接封装，同 memory_ops 同名命令） | — |
| `import` | 批量导入记忆（桥接封装转发 `memory_ops import`）：JSONL/JSON/CSV/MD → deposit 全流程（关闭自动连边 `auto_link=False`；仅支持 UTF-8/UTF-8-BOM/GBK；`--on-error abort` 不触发于隔离）。⚠️ **默认仅 dry-run 预览、零落盘，必须 `--execute`**（注意：无 `--dry-run` 参数） | `--file`(必填)/`--format auto\|jsonl\|json\|csv\|md`/`--root`(可选,默认真实库)/`--execute`(**落盘开关**)/`--keep-ids`/`--on-error skip\|abort`/`--report` |
| `benchmark` | 性能基准（桥接封装转发 `memory_ops benchmark`）：写入吞吐 + recall 时延。**必须显式 `--root <隔离目录>`**（禁止对默认真实库跑） | `--root`(必填,非默认)/`--n`/`--recall-times`/`--top-n`/`--ann`/`--topics`/`--out` |
| `mcp` | 把 keeper 暴露为 MCP 服务（桥接封装转发 `memory_ops mcp`，长驻 stdio；export 支持 `limit` 截断） | — |

---

## 三、与 memory_ops 的关系（委托，非重复实现）

经代码核查，**mem_bridge 与 memory_ops 不存在逻辑重复**——前者是「WB↔keeper 共进型桥」独立子系统，对核心 keeper 引擎以**委托/封装**方式复用，绝不各写一份：

| mem_bridge 命令 | 实现方式 | 证据 |
|---|---|---|
| `decay`（`decay_k`） | 委托 `_m.decay_apply()` | `mem_bridge.py` 1731-1748 |
| `recurrence`（`recurrence_k`） | 委托 `_m.recurrence_report()` | `mem_bridge.py` 1751-1770 |
| `promote` | subprocess 调 `memory_ops promote` | `mem_bridge.py` 2150-2161 |
| `scan_dup`（`audit_b`） | **独立算法**：成对 cosine 近重复+矛盾扫描 | `mem_bridge.py` 1008-1056 |
| `graph`（`graph_around`） | 中心遍历（≠ memory_ops `graph` 的 build/clean/rebuild） | `mem_bridge.py` 1464 |
| `feedback`（`feedback_batch`） | batch/from_inject 的 WB 专属 API（≠ memory_ops 单条 `feedback()`） | `mem_bridge.py` 861 |
| `reflect`（`reflect_wb`） | WB 子系统自检（含 agent/ollama 推理委托模式） | `mem_bridge.py` 431 |
| `distill`（`distill_to_keeper`） | 受控落 keeper（source/rev 戳 + 去重） | `mem_bridge.py` 1059 |

> 结论：「双份实现漂移」不成立——真正重复的 `decay/recurrence/promote` 均为委托；唯一同名异义的 `audit` 在 mem_bridge 侧为 `scan_dup`。WB 子系统的 `inject/coach/rank/route/retrieve/capture/working/summary-index/tree-view/seed/compress/drift` 等是**独立价值**，不应合并进 memory_ops（合并反而破坏共进型边界）。

---

## 四、调用前提

- `mem_bridge.py` 在模块加载前把 `scripts/` 注入 `sys.path`，AI 以 `python mem_bridge.py <op>` 调用**无需再设 `PYTHONPATH`**。
- 核心自动召回/沉淀钩子不受影响——它们自带 `sys.path.insert(0, scripts)`，与被调用路径无关。
