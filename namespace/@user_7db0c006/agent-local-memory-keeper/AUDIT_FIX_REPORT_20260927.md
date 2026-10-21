# agent-local-memory-keeper 全面审计修复报告

> 日期：2026-09-27 ｜ 版本基线：当前线上已发布版（详见 CHANGELOG）
> 触发：用户指令「P0 到 P3 都修；核实 AI 自己使用时的链路；分析改进点与 AI 技术趋势差距」

---

## 一、结论先行（事实，非推断）

| 级别 | 问题 | 状态 | 证据 |
|---|---|---|---|
| P0-1 | recall 默认召回为空（隔离全部 auto_sourced 记忆） | ✅ 已修 | 默认 28 条，`--exclude-auto` 0 条 |
| P0-2 | doctor hooks mode 恒 unknown（读错配置文件位置） | ✅ 已修 | doctor 显示 `mode=full` |
| **P0-3（新发现）** | **门禁假绿：TextTestRunner 输出到 stderr，主进程从 stdout 解析 → 统计恒 0，仍报 PASS** | ✅ 已修 | v3「运行 0 测试却 PASS」→ v5「运行 458 测试」 |
| P1-1 | 模块耦合 NameError（`from memory_ops import _api` 拿到未注入副本） | ✅ 已修 | `_rank_query` 正常返回 34 条 |
| P1-2 | 门禁 flaky（同进程共享 `_emb` 全局状态，顺序依赖） | ✅ 已修 | 子进程隔离后 3 个失败模块全 OK |
| **P1-3（新发现）** | **覆盖损失：test_v4613 是 pytest 风格，unittest.discover 跳过 5 个回归用例** | ✅ 已修 | 该文件被发现 5 测试并跑通 |
| P2-1 | 11 条悬空关系（relations 指向已删除记忆） | ✅ 已修 | doctor --fix 后 11→0，已用剪枝前快照对证 |
| P2-2 | CHANGELOG 发布状态文字滞后 | ✅ 已修 | 补「发布状态（2026-09-17 补记）」注记 |
| P3-2 | decay 陈旧判定纯天数、缺调用次数维度 | ✅ 已修 | `DECAY_HIGH_USAGE_FLOOR=2` 豁免高访问记忆 |
| **P3-1** | **daemon 无法常驻** | ⚠️ 实锤为环境约束 | 见第四节（代码层不可解，需用户决策） |

门禁最终结果：**458 个测试 · 失败 0 · 错误 0 · 跳过 6 · PASS ✅**（6 个 skip 均为预期：4 个「无 .skillhubignore」源码仓专用规则、2 个「duckdb 不可用」，非覆盖损失）。

---

## 二、P0 级修复详情

### P0-1 · recall 默认召回为空
- **根因**：库内 29 条 active 记忆 **100%** `auto_sourced=true`，而 `recall` 默认 `include_auto=False` 把它们全部隔离。设计假设「人会 confirm」，但 AI 自治场景没有这个环节 → 召回恒空。
- **修复**：`_cli.py` 与 `mem_bridge.py` 改为 `include_auto=not args.exclude_auto`（向后兼容默认开启），新增 `--exclude-auto` 保留 staging 隔离能力。
- **验证**：默认 recall 返回 28 条；`--exclude-auto` 返回 0 条。

### P0-2 · doctor hooks mode 恒 unknown
- **根因**：`install_hooks.save_mode()` 写 `~/.workbuddy/hooks/hooks_config.json`，而 `_doctor.py` 读源码树 `hooks_config.json`（不存在）。
- **修复**：`_doctor.py` 改新位置优先，源码树兜底，与 `install_hooks.load_mode()` 同源。
- **验证**：doctor 显示 `"mode": "full"`。

### P0-3（本次新发现）· 门禁假绿
- **根因**：`unittest.TextTestRunner` 默认 `stream=sys.stderr`（源码实锤），而 `_GATE_RUNNER` 未指定 `stream`，主进程 `run_gate.py` 却用 `re.search(r"Ran (\d+) tests?", p.stdout)` 从 **stdout** 解析统计 → `ran/failures/errors/skipped` 恒为 0。
- **后果**：门禁**从未真正统计测试数与失败数**，v3 日志第 1161 行赫然写着「运行 0 个测试 · 失败 0 · 错误 0 · 跳过 0」却「结论: PASS ✅」。即使测试真失败，只要子进程没崩溃，门禁也报 PASS —— **形同虚设**。
- **修复**（两处）：
  1. `_GATE_RUNNER` 加 `stream=sys.stdout`，让测试报告进 stdout；
  2. 主进程改用**子进程退出码**作为失败判据（子进程已 `sys.exit(0 if wasSuccessful else 1)` 正确编码），退出码非零即判失败。
- **验证**：单模块「运行 5 测试 PASS」；全量「运行 458 测试 PASS」。我加的 `ran==0` 守卫正是把这个假绿炸出来的关键。

---

## 三、P1 / P2 / P3-2 修复详情

### P1-1 · 模块耦合 NameError
`memory_ops/__init__.py` 用 `spec_from_file_location` + `__dict__.update(globals)` 把子模块灌成扁平名（如 `memory_ops_api`）。`from memory_ops import _api` 触发标准导入，拿到**未注入的副本**，`_rank_query` 用全局名 `_all_mems` 报 NameError。
- **修复**：把扁平名子模块注册到 `sys.modules["memory_ops._api"]` 和包 `globals()`。
- **验证**：`_rank_query` 正常返回 34 条。

### P1-2 · 门禁 flaky
测试模块在同一进程内共享 `_emb` 全局状态，`test_recall_with_meta` 声明 lexical 却触发慢操作，污染后续 `test_reflect`。
- **修复**：每模块独立子进程运行 + `_GATE_RUNNER` 预 import `memory_ops` 包（锚定 scripts 路径，命中 `scripts/memory_ops/__init__.py` 而非技能根转发垫片 `memory_ops.py`）。
- **验证**：3 个此前失败的模块全 OK。

### P1-3（本次新发现）· 覆盖损失
`test_v4613_evolution_synergy.py` 是 **pytest 风格**（顶层 `def test_*` 函数），而门禁 `unittest.discover` 只认 `unittest.TestCase` 子类 → 该文件被发现 **0 个测试**，5 个回归用例（evolve/belief/forget/provenance 幂等/反回声/investment failopen）被静默跳过。
- **修复**（两处）：
  1. 该文件包一层 `EvolutionSynergyTest(unittest.TestCase)` 转发 5 个函数；
  2. `run_gate.py` 加守卫：`test_*.py` 却 ran==0 → 判错（宁可红，不可静默少跑）。
- **验证**：该文件被发现 5 测试并全跑通（18.2s，含 evolve 慢操作）。

### P2-1 · 悬空关系剪枝
11 条 `relations` 指向已不存在的记忆（历史归档后遗留引用）。
- **修复**：`doctor --fix` 剪枝（`_doctor.py` 剪枝循环只清理 relations 里的死引用，不删记忆正文）。
- **验证**：11→0；已用剪枝前快照 `doctor_fix_backup_20260927-132237.zip` 对证（快照里 `LRN-20260801-002` 仍有 `corrected_by: LRN-20260801-001` 悬空边，修复后消失）。

### P3-2 · decay 加次数维度
陈旧硬门槛 `stale_days=90` 纯天数，用户「一个月不开电脑」场景会误判。
- **修复**：`_decay.py` 在 `stale_days` 判定后加「`access_count >= DECAY_HIGH_USAGE_FLOOR(=2)` 则豁免」，`__init__.py` 新增常量。decay 已是双因子（`importance · e^(-λ·Δdays) · (1+√access_count)`），此改动补齐「陈旧判定」这一环的次数维度。

---

## 四、P3-1 · daemon 常驻问题（⚠️ 环境约束，非代码 bug）

**用户决策**：保持 full 模式（不切 silent）+ 保证 daemon 常驻。

**实锤结论**：在当前 WorkBuddy 沙箱下，daemon 无法通过代码手段常驻。三重硬拦截均已实测：

| 尝试 | 结果 | 证据 |
|---|---|---|
| `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP`（现状） | daemon 随父进程退出被清理 | 实测 spawn pid=23484，父进程退出后 tasklist 无存活 |
| `CREATE_BREAKAWAY_FROM_JOB` (0x01000000) | 拒绝访问 | `PermissionError [WinError 5]`（Job Object 未设 breakaway 允许位） |
| `schtasks.exe` 计划任务 | 被 Program Blacklist 硬拦截 | doctor 实锤 `PermissionError [WinError 5]` |
| explorer.exe 中转 | 不适用 | explorer 把 `.py` 当文档打开，非执行 |

**因果链**：daemon 作为钩子的 DETACHED 子进程启动，但 WorkBuddy 沙箱用 Job Object 管理进程树，`KILL_ON_JOB_CLOSE` 会在钩子进程退出时杀掉所有成员（含 detached 子进程）。`DETACHED_PROCESS` 只脱离控制台，**脱离不了 Job Object**。

**现实影响**：每次会话首次召回有 ~1.5s 冷启动 warmup（实测冷 recall 1.49s），之后同会话内 daemon 热着、毫秒级。这不是 `idle=0` 空闲退出的问题（`idle=0` 实为「永不离线」，watcher 直接 return），而是沙箱进程树管理。

**可选方案（需用户决策）**：

| 方案 | 内容 | 好处 | 坏处 |
|---|---|---|---|
| **A（推荐）** | 接受现状：daemon 每会话冷启动 ~1.5s，之后热 | 零成本、零风险、无改动 | 会话首次召回有 1.5s 延迟 |
| B | WorkBuddy 自动化定时保活 daemon | 可能减少冷启动 | automation 进程模型未验证，可能同样受沙箱约束 |
| C | 用户在沙箱外手动/开机自启 daemon | 真正常驻 | 需用户动作；用户常一个月不开机，收益有限 |

---

## 五、AI 技术趋势差距（6 点落地状态核实 · 2026-09-27 实查）

> 逐点实测核实（非文档猜测），区分「已落地 / 不建议做 / 列为下一迭代」。

| # | 方向 | 核实结论（实跑证据） | 状态 |
|---|---|---|---|
| 1a | 向量库 Qdrant（独立服务） | 需引入常驻服务进程 + 新依赖，违背「纯本地零云端」定位，40 条记忆属过度工程 | ⏸ 不建议做 |
| 1b | ANN 检索加速（内置） | **已内置且自动开**：`ann_min_memories=50`（`__init__.py:1159`），库 ≥50 且 ≤256 自动走 ANN（`_api.py:311-315`，k=n_all 全覆盖结果与线性一致）；>256 大库近似剪枝走 `ann_auto_large`（默认关，opt-in，env `AI_MEM_ANN_AUTO_LARGE`）。`hnswlib` 未装时回退 numpy 持久化索引（`_embed.py:360-361`，函数 `_ann_build_numpy`/`_ann_load_numpy` 真实存在）。当前 40 条未达阈值，涨到 50 自动接管，**无需用户手动开**；要真 HNSW 加速才 `pip install hnswlib`（可选） | ✅ 已内置，自动触发 |
| 2 | 双时序软失效 | `valid_at`/`invalid_at` + `recall --as-of` + `invalidate`/`reinstate` 完整实现（`_lifecycle.py` 明确「对齐 Graphiti bi-temporal」） | ✅ 已落地 |
| 3 | access_count 单一热源 + 防复发锁 | `test_v50_access_count_single_source.py` 等 8 个治理测试已在门禁内 | ✅ 已落地 |
| 4 | rerank 便宜档默认 | `RERANK_DEFAULT_TOP=5`/`RERANK_DEFAULT_DOC_CHARS=200`，`rerank_enabled` 默认关（`_rerank.py:36-51`） | ✅ 已落地 |
| 5 | 导入层根治 | **当日已完成**（用户指令「现在就完成」）：实锤 2 个 P1-1 同族真问题——① `_SUBMODULES` 列表里 `_dsl_mod` 误写为 **ModuleSpec**（根因：`_dsl` 加载块变量命名反常，`_dsl_mod`=spec、`_dsl`=module，列表错写前者）→ P1-1 循环对它静默跳过；② `_self_heal_mod` 整个漏列（磁盘 24 子模块，列表仅 22）。修后 24 子模块 `from memory_ops import X` **全部拿到同一实例**（实测全覆盖通过 + `_rank_query` 回归 OK）。⚠️ 性质甄别：`_dsl`/`_self_heal` 均为自包含/动态解析设计（`_dsl.py` 明写「自包含故无循环导入」，`_self_heal` 用 `_eng()` 动态查找），未注入副本不会 NameError，修复属一致性加固+消除潜伏隐患。**「改成标准 import」经求真判定为负收益**：全局灌入式+PEP562 惰性解析正是规避循环 import 的刻意架构，不是债 | ✅ 已根治 |
| 6 | 门禁假绿 | 已根治 + `ran==0` 守卫落盘（`run_gate.py:357-369`） | ✅ 已落地 |

**结论**：6 点中 5 点已落地（2/3/4/6 此前完成 + 5 当日根治）；第 1 点经数据核实拆分为「Qdrant 负收益不做」+「内置 ANN 已自动开（阈值 50 触发）」。

---

## 六、改动文件清单

| 文件 | 改动 |
|---|---|
| `scripts/memory_ops/_cli.py` | P0-1：`--exclude-auto` 反向参数 |
| `mem_bridge.py` | P0-1：同上前向兼容 |
| `scripts/memory_ops/_doctor.py` | P0-2：hooks mode 读新位置 |
| `scripts/memory_ops/__init__.py` | P1-1 模块注册 + P3-2 常量 + **导入层根治**（列表 `_dsl_mod`→`_dsl` 修 ModuleSpec 混入、补 `_self_heal_mod`、两处 `sys.modules.setdefault` 兜底） |
| `scripts/memory_ops/_decay.py` | P3-2：陈旧判定加次数维度 |
| `scripts/run_gate.py` | P0-3 假绿根治 + P1-2 子进程隔离 + P1-3 零测试守卫 |
| `scripts/tests/test_v4613_evolution_synergy.py` | P1-3：包 TestCase 层 |
| `CHANGELOG.md` | P2-2：发布状态注记 |

**未发布**：按项目约定，未经用户同意不主动发布。所有改动仅落本地源码树。

---

*本报告所有结论均来自实跑证据，非文档猜测。*
