# CHANGELOG · AI Agent 记忆系统

> 本文件为**唯一权威版本历史源**。`references/CHANGELOG.md` 已废弃并指向此处。版本选型说明见 `SKILL.md` 文件头。

---

## 5.2.0 · 2026-10-06

> **本轮主题：语义降级主动提示 + 主文档重构（对话实操化）+ 数据路径静默容错专项。**
> ✅ **更正（针对 5.1.0 线上条目）**：5.1.0 平台「变更说明」首行「本轮为本地开发版…（发布后补记）」是**发布前**的草稿措辞被原样快照上传，实际该版本**已于 2026-09-27 发布成功**（skillId=104506）。平台无编辑已发布版本说明的接口，特此在新条目公开更正。

> - **A1 · 语义降级提示升级（新增 feature）★★**：语义后端 fail-open 降级（fastembed→lexical）时，原提示受众写错（写给日志而非 AI 行动指令，stderr 在钩子子进程不进会话）。改为降级状态落盘 `.keeper_degraded.json` + 注入块升级为「⚠️【记忆系统状态·请转告用户】」醒目引用块，引导用户说「帮我一键配好」；未降级时清除状态。
> - **A2 · 降级开局提示（新增）**：session_start 钩子重写，开局读降级状态（7 天窗口），独立于注入开关注入降级提示。
> - **SKILL.md 重构（491→324 行）**：两主轴（万能导航表 + 场景对话实操 6 大类）+ 四入口；顶部新增「弹窗不是 BUG」科学说明块；正文命令/英文全中文化（命令只留在「给 AI 看的折叠表」）。
> - **文档断链修复（14 处）**：SKILL.md 重构删 §N 编号章节后，references 里 14 处旧编号引用未回扫，已全部改指新章节名。
> - **文档契约测试强化（2 盲区）**：`test_doc_section_refs.py` 正则漏抓「SKILL.md §N「X」」格式 + 不扫根目录 QUICKSTART.md，已修复；同时清理 4 条死豁免。
> - **降级提示测试（新增 6 用例）**：`test_degraded_prompt.py` 覆盖落盘 / 自动建目录 / 清理 / 无文件 / 近期提示 / 过期窗口。
> - **数据路径静默容错专项**：甄别 762 处 except / 591 处静默，确认核心读写（`_load_mem`/`_save_mem`/`load_index`/`save_index`）已带 fail-closed 守卫 + 告警；修复残留 2 处写主索引静默（`_sync_index` 倒排重建 + `export_rules` 目标登记），改为告警留痕，不阻断主流程。
> - **门禁**：458 → 464 用例，全绿。

---

## 5.1.0 · 2026-09-27

> ✅ **发布状态（2026-09-27 补记）**：本版本已于 **2026-09-27** 发布到平台（skillId=`104506`，状态=`pending`，同 slug 覆盖更新；发布器已回写 `_meta.json`→5.1.0）。平台 `latestVersion` 存在入库/扫描延迟（发布即刻核对仍是 5.0.0 属正常），过几分钟用 `--verify-only` 复查即可，**勿重发**（同 slug 同版本会 409）。

> **本轮主题：全面体检驱动的「召回失效 + 门禁假绿」修复 + 导入层根治 + 文档治理。**

> - **P0-1 · recall 默认召回失效（行为变更）★★**：真库 29 条 active 100% `auto_sourced=true`，`recall` 默认 `include_auto=False` 隔离全部 → AI 自治场景下「找一下」恒空。修复：`include_auto=not args.exclude_auto`（**默认已包含**），新增 `--exclude-auto` 显式隔离（`--include-auto` 向后兼容保留）。
> - **P0-2 · doctor hooks mode 恒 unknown**：读源码树 `hooks_config.json`（不存在），实际写在 `~/.workbuddy/hooks/`。改为新位置优先。
> - **P0-3 · 门禁假绿（本次最严重）★★**：`unittest.TextTestRunner` 默认 `stream=sys.stderr`，`run_gate.py` 主进程从 `p.stdout` 解析 `Ran N tests` → `ran/failures/errors` 恒 0，空解析仍判 PASS（v3 日志铁证「运行 0 个测试」却「结论 PASS」）。修复：`_GATE_RUNNER` 加 `stream=sys.stdout` + 主进程改用**子进程退出码**判失败。
> - **P1-1 · 模块耦合 NameError**：`from memory_ops import _api` 拿到未注入副本。补 `sys.modules` 注册，24 子模块同名导入统一指向同一实例。
> - **P1-3 · 覆盖损失**：`test_v4613_evolution_synergy.py` 为 pytest 顶层函数风格，`unittest.discover` 只认 TestCase → 0 测试静默跳过（5 用例）。包 TestCase 转发层 + 门禁加「匹配到 test_*.py 却 0 测试 = 判错」守卫。
> - **P3-2 · decay 双因子（访问次数维度）**：`relevance = importance · e^(-λ·Δdays) · (1+√access_count)`，加 `DECAY_HIGH_USAGE_FLOOR=2` 次数维度，缓解「长期不开机只按天数衰减」的偏颇。
> - **导入层根治（2 个 P1-1 同族 bug）**：`_SUBMODULES` 里 `_dsl_mod` 误写成 ModuleSpec（静默跳过注册）、`_self_heal_mod` 漏列（磁盘 24 子模块、列表仅 22）。修复列表 + `sys.modules.setdefault` 兜底。二者均自包含/动态解析设计，属一致性加固（非 NameError 级缺陷）。
> - **6 点技术趋势差距核实（实查非猜测）**：4 点已落地（双时序软失效 / access_count 单一热源 + 防复发锁 / rerank 便宜档 / 门禁 ran==0 守卫）、1 点（Qdrant 向量库 ANN）负收益不做、1 点（导入层重构）已根治。净结论：无新增待办代码。
> - **文档治理**：① 14 处文档与代码不一致修复（recall 默认行为滞后 3 处 / summary-index·tree-view 归属错 3 处 / filter 状态错 / 死引用 3 处 / 默认值过时 / 数字过时 2 处 / 措辞偏差）；② 用户向文档去版本号（唯一合法位置 = CHANGELOG + frontmatter `version`）；③ 简介页 frontmatter 重编（痛点前置）；④ 全量排版润色 + 过程叙述清理（8 处「此前/早期/已更名」改纯当前状态）。
> - **发布后补记 · 每周定时任务参数对账（第 15 处文档不一致，本地领先线上）**：用户问「每周定时任务配置参数是否需要同步更新」时实查发现——上一轮 14 处核实漏了「automation prompt」这个扫描面。keeper 每周维护自动化（automation-1786260914190）第 1 步仍引 `backup --print-key-hint`，该参数在 5.0.0 明文库改造中已从代码删除（`backup(root, dest=None, progress=False)` 无 key/加密参数，argparse 仅 `--zip`/`--progress`/`--keep`）。已修：① 自动化 prompt 删 `--print-key-hint` + 「整库加密备份」→「整库 ZIP 备份（含每文件 sha256 manifest）」；② `COMMANDS.md:159` 连带删该过时参数。投资库周六更新（automation-1784955157607）与 keeper 改动零交集，未动。注：automation 配置不在 skill 包内（无漂移）；COMMANDS.md 该行为发布后落盘、线上 5.1.0 仍为旧描述，属纯文档微调，攒下次发版一并带。

> **验证**：门禁 458 测试 PASS（失败 0 / 错误 0 / 跳过 6）；`verify_claims` 23/23 全绿；`gen_cookbook.py --strict` 一致无漂移。

---

## 5.0.0 · 2026-09-16

> ✅ **发布状态（2026-09-17 补记）**：本版本已于 **2026-09-17** 发布到平台（`_meta.json.version=5.0.0`、`platform_latest=5.0.0`，经 `release-audit` 联网对账一致）。下方首轮/第二轮正文中的「未发布」是**发布前时点**的状态记录、非最终状态；最终以本注记为准。

> **首轮「把已有能力做实」：修僵尸字段热源、加双时序软失效、接 cross-encoder rerank、定位并修掉 p95 真因，外加一次结构性根治（派生文件 GC）。** 本轮由一份全面体检报告驱动（`D:\skill设计\keeper5.0全面审计与方案_2026-09-16.md`），实施报告 7.3 节「若只能做 3 件事」+ 核实第八节三条未验证项，并按用户指令「**问题能根治的尽量根治**」把 4 处止血升级为除根。**本地开发版，未发布**（按本项目约定，未经用户要求不主动发布）。

> - **A1 · 热源单轨：`access_count` 僵尸字段与「双写」同时根治 ★★**：召回频次的权威存储是 `recall_counts.json`，但记忆文件里的 `access_count` **204/211 恒为 0**、两处可比对的 142 条 **100% 不一致** → 下游三条治理链（`_decay` 沉淀门槛、`_decay` 排序权重 `(1+√ac)`、`_doctor` 晋升筛选、`_reflect` 归档续命）**全部读错字段、同时失效**。新增 `_access_count_of()` 作**单一读取入口**接通全部下游。**根治（不止止血）**：删掉 `_api.py` 两处 `m["access_count"] += 1`（写记忆文件），改为 `_bump_recall_counts()` 只写权威热源 —— 代码注释自己写着「轻量、**不写记忆文件**」，写入侧却在写，这就是双写的病根；只改读侧等于把矛盾藏起来。真库热源同步 GC：`recall_counts.json` **1014 → 142 条**（872 个幽灵计数，且幽灵计数仅 2–7 而存活中位数 99，会把热度统计整体拉偏）、68KB → 8.1KB。这是本仓「**规则层期待的字段 ≠ 写入侧实际产生的字段**」根因族的**第四次**命中。
> - **A3 · 双时序软失效（对齐 Graphiti bi-temporal）★★**：新增 `valid_at` / `invalid_at` / `invalidated_by` / `invalid_reason` 四个字段 + `invalidate` / `uninvalidate` 两个 op + `recall --as-of <date>` 回溯查询。语义：`status` 表达「现在」，`as_of` 表达「某过去时点」；`invalid_at` 是**置位语义**（有值=已失效），随时可无损撤销 —— 这就是「置位不删」相对真删除的价值。CLI：新增 `--as-of` / `--by` / `--invalid-at`（原因复用既有 `--reason`）。
>   🔴 **根治（本轮自查发现并补齐的静默缺口）**：`recall --as-of` 的过滤循环遍历的是 **index entry（不读盘）**，而 `invalidate()` 原来**只把 `status` 同步进索引、从不写 `invalid_at`**，`_index_entry_from_mem()`（rebuild 路径）也没有这两个字段 → **失效之后的回溯查询会把已失效条目当可见，静默返回错误结果且不报错**。已补齐四处：`deposit` entry、`_index_entry_from_mem`、`invalidate` 索引同步、`uninvalidate` 索引复位。防复发锁 `tests/test_v50_a3_bitemporal_index.py`（3 用例，含「rebuild 不丢字段」）。
> - **B1 · cross-encoder rerank 接入（默认关）★**：新增 `scripts/memory_ops/_rerank.py`，用 fastembed 内置 `TextCrossEncoder`。三条设计原则：① **只调 RRF top-N 的内部顺序**（不改召回集合、不改外部语义）；② **区间映射**（rerank 分 min-max 归一后映射回 top-N 原有的 RRF 分区间，避免分数尺度断层）；③ **任何异常静默回退**（模型缺失/加载失败/编码异常一律退回原序，绝不阻断 recall）。默认模型 `BAAI/bge-reranker-base`，`RRF_DEFAULTS` 新增 `rerank_enabled=False` / `rerank_model` / `rerank_top=5` / `rerank_weight=0.6` / `rerank_doc_chars=200`（后两项默认值由同日网格实测定为「便宜档」，见下条）。**行为验证**：条数一致 200、**分数变化恰好 = `rerank_top`**（越界为 0，证明改动面被精确约束）、排序确实变化。
>   🔴 **成本更正 + 定论（同日消融，详见报告第十三节）**：早先记的「稳态 **745ms**」是**用 30 字合成短文本**测的，**低估约 20 倍**，已作废。用**真实记忆文本**实测，成本主项是**候选文档总字符数**（**≈1.2 ms/字符**，不是条数）：默认档 `top-20 × 1200 字` = **12~15 s/次**（76 条真实 query：p50 **11.65s** / p95 **14.60s**；同条件不开重排 **0.30s**）。模型 **1.04GB**（嵌入模型的 11×）。
>   ✅ **质量收益确凿**（同一批 76 条 query 开/关对照）：`hit@1` 0.566 → **0.829**、`hit@3` 0.789 → 0.868、`MRR` 0.686 → 0.849，**24 条排名上升 / 0 条下降**（"开着最差不等于没开"这条设计原则得到实测背书）。
>   ⇒ `rerank_enabled` **默认关仍是硬结论**（12s ≈ recall 自身的 38 倍；且 1.04GB 模型需用户知情下载），但**默认参数已换档**：把原本不可用的 `top=20/1200 字` 改成网格实测的**便宜档 `top=5/200 字`（1.83s/次，拿到 90% 质量增益）**，让"开了就能用"；要满配自己调大（最后 2.6 个点 ≈ 6.4 倍成本）。同时把成本主项做成可配项 `rerank_doc_chars`（原先**硬编码**在 `_rerank_doc_text(item, limit=1200)` 里，配置面拿不到 —— 又一次「代码里有成本参数、配置面不可达」，同一根因族）。
>   ⚠️ **踩坑记录**：HF 中文模型直连返回 `401 Unauthorized`（Xet/CAS 通道被拒），必须 `HF_HUB_DISABLE_XET=1` + `HF_ENDPOINT=https://hf-mirror.com` 才能下载。另：fastembed 支持列表**不含 `bge-reranker-v2-m3`**（体检报告原写此名，已更正为 `BAAI/bge-reranker-base`）。
> - **B2 · p95 真因定位并修复：**报告归因为「冷路径未优化」，实为**缓存写路径**。真因链：`store/.recall_cache.json` 是**单文件全量重写**，缓存值 = **完整召回结果**（含 body/relations，真库单条最大 **553KB**），且写入点在 token 裁剪**之前** → `recall(query)` 在天量返回下把「序列化整个文件」做成 O(文件总大小) 操作。cProfile 实锤：50 次 recall 累计 16.1s，其中 **5 次 `_recall_cache_set` 占 13.7s（92%）**、`json.dump` 13.3s。**改造**：磁盘后端 JSON → **SQLite**（`store/.recall_cache.db`，写入降为单行 `INSERT OR REPLACE`）+ **延迟合并写**（进程内多次 set 只登记脏 key，atexit 批量刷盘一次）+ **root 规范化**（缓存键走 `_root_key`，消除 `D:\X` 与 `D:/X` 把同一库劈成两套命名空间）。**实测**：p95 **964.8 → 352.4 ms**、max **3446.9 → 409.7 ms**、avg **249.7 → 38.3 ms**、≤1ms 命中 32/50、落盘由 5×2700ms 降为**一次 46.2ms**；干净库（20 条）复现 `p50 0.21 / p95 964.8`（比值 4595×）**证明与库规模无关**。剩余慢因转为「未命中 query 的 embedding 编码」（310–410ms，**合理成本**）。
> - **A7 · 派生文件 GC 接入 `rebuild()`（本轮新增的结构性根治）★**：`route_registry.json` **426 键 vs 真实记忆 226 条**、`recall_counts.json` **1014 键 vs 存活 142**、`maintenance_dirty.json` / `clusters.json` 同病。根因是**结构性**的：这些派生文件都按 id **增量写**，而**删除/归档路径从不回删键**，`rebuild()` 又只重建 `index.json` / `index.db`、**完全不碰派生文件** → 幽灵键只增不减、永不回收。新增 `prune_derived(root, alive_ids=None, dry_run=False)` 并以「磁盘真实 id 集合」为唯一口径做差集回收，**接入 `rebuild()` 收尾** → 跑过一次全量重建即与真源对齐，不再依赖手工脚本。🔴 **安全阀**：`alive` 为空（索引读失败/库空）时直接 `skipped`，**绝不因一次读取异常把派生文件整体清空**（本类清理最危险的失败模式，已用例锁定）。`rebuild(root, return_report=True)` 返回 `pruned` 明细，默认仍返回 int（老调用方零回归）。
> - **真库事故处置（本轮我自己造成的，如实记录）★**：跑 benchmark 时用了 `--root "<库路径>"`（**正斜杠**），而护栏是 `args.root == DEFAULT_ROOT` **字符串比较** → **护栏被绕过，200 条合成记忆写入真库**（memories 209 → 411，另 200 个 `versions/*.v1.json`、11.56MB 缓存、index.json / maintenance_dirty / route_registry 各 200 条污染）。识别用**三条件与门**（`category=benchmark` + `recorded_by=benchmark` + `summary` 前缀 `bench item`），**刻意不按 id 范围删** —— 同批的 `LRN-20260916-001/002` 是真实 pitfall 记忆。处置：**搬移隔离而非删除**（`<隔离目录>`，可逆）→ `rebuild` → `doctor --fix --no-cache`（`content_mismatch`/`orphan`/`missing`/`dangling`/`status_mismatch` 全 `[]`、embed 166/166、fingerprint_drift 0）→ 残留 **0**。**根治**：`_cli.py` 与 `keeper_benchmark.py` 两个护栏改用 `_root_key()` 规范化判等，正斜杠/相对路径再也不能绕过。
> - **CLI 参数冲突事故与根治（本轮我自己造成的，如实记录）★**：给 A3 加 CLI 入参时，在**扁平单 parser** 上重复定义了 `--reason`（deposit/reclassify 段已有）与 `--at`（schedule_reflect 已有，且默认 `"03:00"`）→ argparse 构建期抛 `conflicting option string`，**整条 CLI 起不来** → 门禁一次 **20 失败 / 1 错误**，失败点横跨 benchmark 护栏 / 导入 / inject gate / smoke / phase-a / phase-e，看起来像「大规模回归」。🔴 **为什么没早发现**：A3 的验证**只走了 Python API，没走 CLI 面** —— 这是**验证覆盖缺口**。**根治**：① 复用既有 `--reason`、`--at` 改独立名 `--invalid-at`；② 新增 `tests/test_cli_argparse_integrity.py`（3 用例）= **静态扫重复选项串**（argparse 只报第一个冲突，静态扫才能一次看全）+ **动态建 parser** + **CLI 面端到端实跑** `invalidate`/`uninvalidate`。
> - **文档/注释一致性**：`verify_claims` 的 `no_dead_symbol_refs` 逮住我在注释里点了 stdlib 内部符号 `_iterencode`（代码里不存在）→ 已改措辞。该 claim 有效，不是装饰。
> - **A8 · 召回配置「可达性」根治（本轮第二轮新增）★**：`_load_recall_config` 的覆盖循环是 `for kk in cfg:`（**只遍历 `RRF_DEFAULTS` 的键**）⇒ 任何没登记进该字典的配置项，在 `config.json` 里写多少遍都**不会生效**。而代码早就在读它们、文档甚至明确写了怎么配：`cache_ttl_seconds`（`_api.py` 读；`RECALL_CACHE_TTL_DEFAULT` 处注释写「可在 config.json 的 `recall.cache_ttl_seconds` 覆盖」）、`low_conf_downweight`（`_api.py:437` 读）、`ann_auto_large`（`_api.py:311` 读）—— 三处全是「文档/代码期待 ≠ 实现层可达」，仍是同一根因族。修法：把三键显式登记进 `RRF_DEFAULTS`（覆盖循环自然生效，无需改循环逻辑），并把 `RECALL_CACHE_TTL_DEFAULT` 改为取自 `RRF_DEFAULTS["cache_ttl_seconds"]`（原先两处各写一个 `60`，改一处就会出现默认值不一致）。
> - **A9 · 缓存键「配置签名」根治（本轮第二轮新增）★**：缓存键原先只含 `root/config.json` 的 mtime，两个真缺口：① `_load_recall_config` 是 **`store/config.json` 优先**（真库确实把 `semantic_gate` 写在 `store/config.json`）⇒ **改它不失效缓存**；② 5.0 新增的 `rerank_enabled`/`rerank_model`/`rerank_top`/`rerank_weight` **完全不在键里** ⇒ 开关切换后仍命中旧缓存（B1 消融实验会被它污染）。更关键的是 mtime 本身不可靠：**实测 NTFS `getmtime` 可见粒度约 15.6ms**，连续两次改配置可能落在同一粒度内 → 键完全不变。修法：新增 `_recall_cache_cfg_sig(root)`（对 `_load_recall_config` 结果做内容哈希，**唯一来源**，调用方与测试都调它、不得复刻）+ mtime 扩到两个 config 路径。**验证**：把 mtime 用 `os.utime` 人为还原成同一值后，签名仍能区分（`132cdc22…` vs `1cb928bb…`）—— 证明是根治而非补丁。防复发锁 `tests/test_v50_recall_cfg_reachability.py`（8 用例）。
### 5.0.0 · 第二轮追加（同日续修：全面复查抓到的 5 处真漏点 + 1 处误报排除）

> 触发：用户指令「**所有内容都要检查好**」。对 A1（热源单轨）做了全仓复查，发现上轮只清了 `_api.py` 两处，
> 仍有 **4 处文件侧自增 / 读取漏点**、**1 处重复计数**、**1 处串缓存**，并**排除 1 处误报**。
> 全部修复并新增 **10 个防复发用例**（静态锁 + 行为锁）。

> - **A10 · A1 彻底性续修：`access_count` 的「双写」只清了一半 ★★**：全仓复查（AST 定位每处读写的宿主函数）后确认：
>   · 🔴 **重复计数（上轮我引入的）**：`_api.py` 的 touch 块 bump 与函数末尾的批量 bump 覆盖同一批条目 ⇒ `recall --touch` 频次**翻倍**；
>   · `__init__.py::touch()` 仍在自增记忆文件字段（权威应在 `recall_counts.json`）；
>   · `__init__.py::_cross_type_associate` 从文件字段读 ⇒ 「跨 type 联想补入」项恒显示频次 0；
>   · `_deposit.py` 的**近重复吸收**路径（`dedup_keep_old`）仍在自增文件字段；
>   · `_doctor.py::dashboard` 读文件字段 ⇒ 真库 204/211 条恒 0，「最常召回」在仪表盘上全是 0；
>   · `__init__.py::_format_v30_entry` 里的自增 —— 静态锁逮住；该函数**全仓零调用点**（历史渲染入口），
>     留着就是「双写的活样板」，已删除自增并注明。
>   ✅ **排除一处误报**（按「三态定性」先排除开关/文档默认态/权限再判 bug）：`_reflect._recent_access_count`
>   统计的是 **`accessed_from` 审计条目**，与 `access_count` 字段无关 —— 不是漏点，未改。
>   **锁**：`tests/test_v50_access_count_single_source.py`（7 用例）= **静态扫「文件侧自增」模式**（`["access_count"] = … + 1`，
>   任何新增都会红）+ `touch`/`recall --touch`/`--outcome`/普通 recall 各自「只 +1」的行为断言。
> - **A11 · `--filter` 对频次恒失效 + `--filter` 串缓存 ★**：
>   · `recall --filter "access_count>N"` **恒返回空**：`_MEM_LEVEL_NUM_FIELDS` 声明可按该字段过滤，但它**不在 index entry 上**
>     （真库 entry 字段实测无此键），且过滤发生在 enrichment 补热源值**之前** ⇒ 静默漏筛。`promote_rules.py`
>     的同类路径（「被召回 N 次以上才晋升」）同病。修法：仅当 clauses 真用到该字段时，从**权威热源**按需补值
>     （`recall` 与 `promote_rules` 同一口径）。
>   · `filter_clauses` **不在召回缓存键里** ⇒ 同 query 配不同 `--filter` 的两次调用**互相返回对方结果**
>     （与 `as_of` 串缓存完全同类）。修法：新增 `filter_sig` 进缓存键。
>   ⚠️ 已知限制（如实标注，未改）：同名单中的 `age_days` / `thermal_weight` 同样不在 entry 上，需各自派生口径。
>
> - **本轮全量验证**：门禁 **409 用例 / 失败 0 / 错误 0 / 跳过 2**（380 → 391 → 399 → 409，本轮累计新增 29 用例）；
>   `verify_claims` **22/22**；发版端到端 `--dry-run-only` = **PASS 可发版**（仍未发布）。
>   新增用例：`test_v50_a3_bitemporal_index.py`（3）、`test_cli_argparse_integrity.py`（3）、
>   `test_v50_prune_derived.py`（5，含 2 条安全阀）、`test_v50_recall_cfg_reachability.py`（11）、
>   `test_v50_access_count_single_source.py`（7）。
> - **边界（诚实标注）**：① Rerank 的**质量收益**已由本轮消融实验量化（结论见下条 §B1 消融），但**默认值仍为关**——由使用方按需开启；② `recall(query)` 仍返回全库（约 200 条），这是 p95 被放大的**结构性因素**，其根治属**行为变更**（默认 top-N），**后移至 `5.1.0`**；③ 删除类动作一律走**搬移隔离**（可逆优先）—— 例外：本轮经用户明确指令，把已隔离的 benchmark 污染目录**物理删除**（删除前先落 manifest 存档，含 404 个文件的路径/大小/sha256，可追溯）；④ 版本号本轮定为 **`5.0.0`**（用户 2026-09-16 拍板）—— 定 major 的依据是**数据面/派生面 breaking**：`access_count` 双写根除（文件侧不再写频次，第三方脚本读 `memories/*.json` 取不到频次，改读 `recall_counts.json`）、缓存后端 `.recall_cache.json` → `.recall_cache.db`、`rebuild` 起会回收派生文件的幽灵键；**未完成项**（A2 词汇表统一 / A4 图边分级 / A6 index 单副本 / `recall` 默认 top-N）**后移至 `5.1.0`**，不在本版宣称范围内；⑤ 🔴 **未发布** —— `_meta.json` 仍为线上版 `4.9.25`（未改动），本轮仅跑 `--dry-run-only` 确认「可发版」。

---

### 5.0.0 · 第三轮追加（同日续修：%TEMP% 测试沙箱残渣根治）

> 触发：用户指令「**清**」（清理 `%TEMP%` 残渣）。清理中发现实际清理量远超预期（**989 项 / 238.52 MB**），
> 顺藤查出**门禁的沙箱回收一直在静默漏网**，并根治。

> - **F1 · 门禁沙箱回收静默漏网（第三轮新增）★★**：`run_gate.py` 的 `_cleanup_temp_residue` 每轮只回收 **99 个 / 0.7 MB** —— 这是个**假象**。
>   · **证据链**：三轮全量门禁（**399 / 409 / 415** 个用例，各不相同）回收数**恒为 99 个 / 0.7 MB** —— 用例数变了、"99" 纹丝不动 ⇒ 不是「刚好回收这么多」，而是**大批删除失败没被计数**；
>     单跑 `test_md_roundtrip.py`：新建 **1** 个含 `index.db` 的沙箱，跑完日志**连「回收本轮临时目录」那行都没有**（该行仅 `_n>0` 时打印）⇒ 实际回收 **0** 个；
>     该目录在进程退出 **14.7s** 后 `shutil.rmtree`（不加 `ignore_errors`）**一次成功** ⇒ 占用者是**本进程的 sqlite 连接**，不是权限/只读问题。
>   · **根因**：`memory_ops` 的 per-root 连接池（`_persistence._DB_CACHE`，其 `_ConnProxy.close()` 是 no-op）**只在 atexit 关闭**，而门禁回收发生在 atexit **之前** ⇒ 沙箱里的 `store/index.db` 句柄仍被本进程持有 ⇒ Windows 抛共享冲突拒绝删除 ⇒ `shutil.rmtree(path, ignore_errors=True)` **静默吞掉**。
>   · **代价**：本机实测累积 **989 项 / 238.52 MB**（第一轮 904 项 218.91 MB + 第二轮 85 项 19.61 MB），全部已清（零失败）；`%TEMP%` 条目数 **6166 → 5176**。
>   · **修法（三处，均在 `run_gate.py`）**：① 新增 `_release_db_handles()` —— 回收前主动调 `memory_ops._persistence._db_close_all()` + `gc.collect()`，把连接池句柄放掉；
>     ② 新增 `_rmtree_retry()` + **两轮批量**（首轮全量删 → 一次等待 + 释放 → 只重试失败项），避免「每个目录一次 gc」在 900 个残留场景下把回收拖成几十秒；
>     ③ `_cleanup_temp_residue(with_stats=True)` 返回 **failed 计数**，跑前/跑后各打印一句失败提示 —— **不再静默**（这个 bug 能潜伏多轮，正是因为它长得像「一切正常」）。
>   · **对照实验（证明修复必需，不只是「改了」）**：monkeypatch 禁用 `_release_db_handles` = **removed=0 / failed=1 / 目录仍在**；启用 = **removed=1 / failed=0 / 已删**。
>   · **防复发锁** `tests/test_gate_temp_cleanup.py` 新增 5 用例：① **主验证** `test_pool_held_sandbox_is_reclaimed`（用 `memory_ops._db_conn()` 真实入池 → 断言必须能回收；修复前必红）；
>     ② `test_sqlite_held_dir_is_counted_not_silently_swallowed`（池外连接 → failed 必须 ≥1）；③ 向后兼容仍返回二元组；④ 静态锁（回收路径必须含 `_release_db_handles()`）；
>     ⑤ 失败数必须被打印（`with_stats=True` × 2 + 「未能回收」提示 × 2）。
>   · **踩坑记录（测试怎么模拟句柄占用）**：第一版用 `open()` 持句柄模拟 → **实测 `removed == 1`，断言直接失败** —— CPython 在 Windows 上打开文件时共享模式**含 `FILE_SHARE_DELETE`**，被 `open()` 持有的文件照样能删；
>     必须用 **sqlite3 连接**（其文件句柄不含 DELETE 共享位）才能复现 —— 这正是沙箱里躺着 `index.db` 的真实机制。
>   · 🔴 **教训**：`ignore_errors=True` 让「删不掉」与「没东西可删」在日志里**完全无法区分**；**磁盘卫生动作同样需要失败可见性**。
> - **F2 · 幽灵目录：延迟合并写的落盘点把「已删除的库」重建回来（第三轮新增）★★**：修完 F1 后端到端复验，发现门禁跑完**仍留 3 个 `keeper_sm_sync_*` 空壳**（内容只有 `store/.recall_cache.db`），且 mtime **晚于门禁结束时刻** ⇒ 说明是**门禁进程之外**的动作创建的。
>   · **取证**：前缀溯源到 `tests/test_save_mem_index_sync.py:39`（测试沙箱，不是 hook 运行时）；其 `tearDown` 本就写着 `rmtree(store, ignore_errors=True)` —— **它会自己删**，但删不掉（F1 的连接池占用，`ignore_errors` 又吞了）；更关键的是召回缓存是 **B2 引入的延迟合并写**（`_PENDING_DISK` 登记脏 key、**atexit 才批量落盘**），而落盘调 `_cache_db_conn(root)`（`create` 默认 **True**）→ `os.makedirs` 把**已删目录重新建出来**。
>   · **修法**：`_recall_cache_flush` 落盘前加 `if not os.path.isdir(root): continue` —— 丢弃该 root 的脏 key，**绝不重建目录**。
>   · **对照实验**：A（修复后的 flush 路径）→ `exists = False`（不复活）；B（直调 `_cache_db_conn`，即修复前行为）→ `exists = True`（复活）。**根因确认**。
>   · 🔴 **这不只是卫生问题（生产影响）**：用户删掉某个记忆库 / 清理过某一 root 后，**进程退出时会把它凭空建回来**（幽灵目录）；`tearDown`/脚本里的删除动作也因此在"看起来成功"之后被悄悄撤销。
>   · **防复发锁**：`tests/test_save_mem_index_sync.py` 新增 `test_flush_does_not_resurrect_deleted_root`（含"前置：目录必须真的被删掉"断言，避免第一因掩盖第二因）。
>   · ⚠️ **实验设计教训（第一次跑出 INCONCLUSIVE）**：对照脚本首版直接在 `recall()` 之后 `rmtree` → 「删除后 exists=True」，**删除本身就失败了**（连接池还在持有），后续结论无从谈起。必须**先释放句柄再删**，才能把「第一因（删不掉）」与「第二因（复活）」隔离观察 —— 两个病因叠在一起时，会互相伪装成对方的症状。

### 5.0.0 · 第四轮追加（同日续修：升级路径收口 —— 旧加密库 fail-closed 守卫）

> 触发：用户提问「**现在是不是还不能发大版本**」。核查结论：技术面三项全过（版本递增合法、
> 门禁 422/0/0、claims 22/22、发版端到端 PASS），但实锤**唯一真实阻塞项** ——
> **线上 4.9.25 自带 at-rest 加密能力，而 5.0.0 把它整体删除了**：存量加密库升级上来会
> **静默返回乱码，且没有任何自救通道**。用户拍板选项 **A**：检测到旧加密库特征即**拒绝按明文读写**
> 并给出可操作指引。这是本版**发版前提**，不是可选优化。

> - **G1 · 旧加密库 fail-closed 守卫（本轮新增）★★★**：新增 `scripts/memory_ops/_legacy.py`
>   （**不含任何加解密能力**，只拒绝、不解密）。
>   · **问题链**：4.9.25 的加密把 `summary` / `body` / `provenance_key` / `src_origin` /
>     `verified_source` / `review_by` 存成 Fernet 密文，并落 `store/salt.bin` + `store/enc_key.txt`。
>     密文**仍是合法 JSON** ⇒ 5.0.0 的 `json.load` 不报错 ⇒ 密文当明文用 ⇒
>     **召回出乱码、无异常、无日志**；且 5.0.0 已无解密命令 ⇒ 只能降级回 4.9.25。
>     更糟的是在 `salt.bin` 尚存的库上写入的是**明文** ⇒ **混库** ⇒ 此后降级回 4.9.25 时，
>     其「明文写 fail-closed」会让**整库读不出来**。
>   · 4.9.25 自己就有这道门（`_decrypt_fields`：字段像密文而当前无密钥即拒绝返回），
>     5.0.0 把保护与功能一起删掉了 —— 本守卫把门补回来。**判据逐字取自旧实现**：
>     标志层 `store/salt.bin`（+ `enc_key.txt`）、内容层 `startswith("gAAAAA") and len > 50`。
>   · **成本**：标志层 1~2 次 `os.path.exists`（微秒级）；内容层只嗅探**已在内存**的字段（零额外 IO）。
>     刻意**不做进程内 memo 缓存** —— 缓存只会引入「库状态在进程内改变后不生效」的陈旧窗口，而这里不需要。
>   · 🔴 **覆盖面靠实跑取证，不靠读码**（G1 矩阵：**48 条真实 CLI 命令**逐条判 rc/error）。
>     修前首轮只挡住 **21/41**，暴露出**四条真漏网 + 一条假 fail-closed**：
>     · ① `deposit` **写成功了** —— 它走的是 `_write_mem`（`__init__.py`，deposit 的**独立落盘真源**），
>       不是 `_save_mem`；只守 `_save_mem` 等于没守写路径；
>     · ② `recall`（**列表模式**）与 `stats` 返回密文 —— 它们只读**索引镜像**（`load_index`）、
>       不读记忆文件；而 4.9.25 的 `_enc_index_entry` 把索引里的 summary 一并加密了 ⇒
>       索引是**第二份用户数据副本**，必须同样设防；
>     · ③ `versions --id` 返回密文 —— 版本快照是**第三条独立读路径**（既不经过 `_load_mem`/`_all_mems`，
>       也不经过 `load_index`）；
>     · ④ `_load_mem` 的**缓存快路径**漏过 —— 命中进程内缓存时直接 `return`，守卫若只放在
>       「读盘之后」，同一个库会「第一次读被挡、第二次读漏过」（长驻 daemon 里就是必然漏）；
>     · ⑤ `stats` 用 `except Exception: pass` **把守卫错误吞了** ⇒ 从「拒绝服务」退化回
>       「静默返回 `total_memories=0` / `summary=""`」—— 恰好是本守卫要根治的假答案。
>     ⇒ 设防点从 4 个扩到 **9 个**（`_load_mem` / `_all_mems` / `_save_mem` / `_write_mem` /
>       `_iter_all_mems` / `load_index` / `_versions._list_versions` / `_versions.rollback` / `_api.stats`），
>       并新增两个**结构性收口点**：`@_with_deposit_lock` 包装器（一次覆盖全部 **18** 个状态变更入口）
>       与 `_cli.main` 的 dispatch 层（覆盖全部命令 —— 批处理型 `import` / `evolve` 会把逐条异常
>       吞成 `{"ok": false}` 却仍 `rc=0`，用户与自动化无法据此判断「整库不可用」，必须在此拦下）。
>     ✅ **修后复跑（第四轮）：挡住 44 / 48，其中 36 条全部 `rc=13` + `error=legacy_encrypted_store`**
>       （`graph --build/--rebuild`、`distill`、`evolve`、`import --execute` 从「rc=1 / rc=0」一并收敛为 rc=13）；
>       余下 **4 条为刻意放行**：`quickstart` / `commands` / `release-audit` / `backup`
>       —— 它们**不读本库记忆数据**，且迁移前正需要 `backup` 留档。对照组（明文库）7 条命令全 `rc=0` ✅。
>   · **G2 · 「被拒绝」必须零副作用（本轮抓到的真缺陷）★**：对 20 个状态变更命令做
>     **(相对路径, sha256) 全库前后快照**，要求「拒绝 + 逐字节零变化」。
>     🔴 实锤：**`delete` 在被拒之前就已经 `os.remove` 了记忆文件** —— `delete` 先删文件、
>     再做反向边整理，守卫只在后续的 `_all_mems` 处才触发 ⇒
>     **fail-closed 变成了「先破坏、再报错」**。修法：`@_with_deposit_lock` 在拿锁之前设防
>     + `delete` 就地设防（它是全库唯一**直接 `os.remove` 记忆文件**的地方）。
>     修后 **20/20 零副作用**。另说明：`.write_lock`（CLI 的跨进程锁文件，0 字节运行时产物）
>     与 `store/index.db-wal`（SQLite 边车）属**非数据性产物**，已在核验脚本里显式归类，
>     不冒充「数据未变」。
>   · **零回归**：明文库全链路照常（`_all_mems` / `_load_mem` / `recall` / `stats` / `deposit` 全过）；
>     `backup` / `quickstart` / `commands` / `release-audit` / `init` 在旧加密库上**刻意放行**
>     （不读本库记忆数据，且迁移前正需要 `backup` 留档）。
>   · **CLI 契约**：新增结构化错误档 `error = legacy_encrypted_store` / `error_code = LEG-001` /
>     **`exit code 13`**（0–7 已占用；11/12 是 4.9.25 的加密错误码，语义不同故不复用），
>     `next_steps` 给出三条**真实存在**的出路（换回 4.9.25 恢复密钥 / 在 4.9.25 下导出后建全新明文库 / 换新空目录）。
>     ⚠️ 措辞刻意核实过：4.9.25 的 `rekey --new-key` 帮助原文写明「**不支持轮换成明文库**」，
>     故文案不承诺「一键去加密」—— 不编造不存在的逃生通道。
>   · **防复发锁** `tests/test_v50_legacy_encrypted_guard.py`（14 用例）：标志层 / 内容层行为锁、
>     **缓存快路径锁**、**静态登记表锁**（用 AST 取函数体，核对 9 个读写原语都必须含守卫调用；
>     新增读原语即须登记）、「守卫模块不得夹带加解密能力」（AST 查 import/调用，**不查字符串** ——
>     首版用文本包含检查，被文件头注释里的「删 cryptography 依赖」误判过一次）、
>     以及**真实 CLI 覆盖率锁**（28 条命令逐条要求 `rc=13` + `legacy_encrypted_store`）。
>   · **方法论沉淀**：这是本仓「**规则层期待的字段 ≠ 写入侧实际产生的字段**」根因族的第 **8** 次命中，
>     但形态不同 —— 这次是「**守住了一处、漏掉了同一语义的其他入口**」（写有两处真源、读有三条路径、
>     外加一条缓存捷径与一处静默吞异常）。⇒ 新增铁律：**「设防」必须用真实入口矩阵验证覆盖面，
>     代码里看到守卫不等于覆盖**；并且**fail-closed 的定义包含「零副作用」**，必须做前后快照核验。
>   · **claims 闸门又逮到自己（本轮第 2 次，说明它真有效）**：新增的守卫模块在注释里刻意引用了
>     **6 个 4.9.25 已删除的函数名**（`_decrypt_fields` / `_store_was_encrypted` / `_enc_key_resolve` /
>     `_looks_like_fernet_token` / `_encrypt_fields` / `_enc_index_entry`）作**判据溯源对照** ⇒
>     `no_dead_symbol_refs` 判死引用 **8 处**（一次 21/22）。
>     🔴 修法**刻意不是模糊化措辞**——那会丢掉「判据抄自旧版哪个函数」的可追溯性。改走该闸门
>     **自身预留的逐行豁免通道 `deadref-ok`**（其 docstring 明载：「确有理由引用不存在的名字
>     （如描述重构前的旧名）时，在该行写 `deadref-ok` 显式豁免」），并在文件头集中说明这些引用
>     属**史料对照**而非死引用。修后 **22/22 全绿**。这是本闸门第 2 次逮到同类问题（首轮逮的是
>     注释里点名的 stdlib 内部符号 `_iterencode`）—— 印证它不是装饰，且**预留了正确的逃生通道**。
> - **验证**：全量门禁 **435 用例 / 失败 0 / 错误 0 / 跳过 2**（422 → 435；本轮新增 **13** 用例 =
>   `test_v50_legacy_encrypted_guard.py` 的 MarkerLayer 3 / CiphertextLayer 4 / CliCoverage 2 /
>   PlaintextUnaffected 2 / StaticGuardRegistry 2），`verify_claims` **22/22**，发布门禁端到端 **PASS 可发版**。
>   覆盖面实跑：G1 **44/48 挡住**、G2 **20/20 零副作用**、明文库对照组全绿。

### 5.0.0 · 第五轮追加（同日续修：版本字段语义分离 —— `local_version` vs `installed_version`）

> 触发：发版前例行核查 `release-audit`，发现它报 `local_version = 4.9.25`，而源码 `SKILL.md`
> 是 `5.0.0`。**这是真缺陷，且不在前四轮的视野内。**

#### 根因：把两个**不同概念**当成「同一概念的两种来源」

| 字段 | 真实语义 | 写入侧是谁 |
|---|---|---|
| `_meta.json.version` | **平台上次发布 / 本机已安装版本** | 发布器 `update_meta()` 在发布成功后回写；该文件不进发布包（`publish_skill.py` 的 `EXCLUDE_FILES`） |
| `SKILL.md` frontmatter `version:` | **本地源码当前版本** | 人写；本仓约定的「版本单一真源」（见 `_hooks._read_skill_version` 的 docstring） |

而 `release-audit` 写的是「**优先 `_meta.json`**，回退 SKILL.md frontmatter」——在**用户机**上
两者一致（无源码迭代）看不出问题；在**开发者机器**上源码必然领先，于是 `local_version`
**永远读到陈旧值**。

#### 危害：不是显示难看，是会给出**会毁掉本地改动**的指引

| 场景 | 修正前行为 |
|---|---|
| 本机（`lvp == plp`） | 两条版本对比分支都不走 ⇒ **长期静默**（所以此前一直没被发现） |
| 平台一旦发布任何新版本 | `lvp(4.9.25) < plp(4.9.26)` ⇒ **误报 `verdict="drift"`**，并提示「本地副本落后于线上——多机并行时这正是**「双主」的前兆**：先把线上包取回做基准，再动任何代码」⇒ **该指引会覆盖掉本地未发布的全部改动** |

#### 同根因第二处：`_verify_version_alignment`

把 `_meta.json` 当「同概念第三源」做三方比对 ⇒ 开发者机器上**必然** `aligned=False`，把
**常态**（源码领先）当**错位**告警；且该函数在此之前**零测试覆盖**。

#### 修法

- `local_version` ← **SKILL.md frontmatter**（本仓自定义的版本单一真源）；
- 新增 `installed_version` ← `_meta.json`，**如实暴露**供人核对；
- 「双主」告警改比 **`installed_version` ↔ `platform_latest`**（这才是**同语义**比较）；
- 「源码领先」降级为**信息项**（hint）——**不判 drift**、**不提示取回线上包**；
- `_verify_version_alignment` 分两层：**源码层**（SKILL.md ↔ CHANGELOG.md 顶部，必须一致 ⇒
  驱动 `aligned`）与**安装层**（`_meta.json`，允许落后 ⇒ 只记 `installed_lag` + `notes`）；
  并把告警文案从「版本四源未对齐」纠正为「版本**源码层**未对齐（SKILL.md ↔ CHANGELOG.md）」。

#### 🔴 为什么旧测试没抓到 —— 「测试全绿 ≠ 现实正确」

`test_release_audit.py` 的 `_mk_skill()` 把 `_meta.json` 与 `SKILL.md` 的版本写成**同值**，
恰好绕过了真机形态（`_meta.json` **落后**源码）⇒ 17 个用例全绿，真机行为却是错的。

#### 防复发锁（新增 8 用例）

`scripts/tests/test_v50_version_source_semantics.py`：

| 用例 | 锁什么 |
|---|---|
| `test_local_version_comes_from_skill_md_when_meta_lags` | 真机形态下 `local_version` 取**源码**版本 |
| `test_meta_lagging_does_not_trigger_double_master` | 🔴 **核心**：源码领先 + 安装版本与线上齐平 ⇒ 不得报 drift / 双主 / 「取回做基准」 |
| `test_installed_version_behind_platform_still_flags_double_master` | **反向锁**：安装版本**真**落后时双主告警仍须报（别把告警一并修没）；构造上令 `missing_log` 为空 ⇒ 精确命中「同语义比较」这一条路径 |
| `test_missing_meta_falls_back_to_source_and_leaves_installed_empty` | 无 `_meta.json` ⇒ 回退源码版本、`installed_version` 为空 |
| `test_source_code_keeps_the_separation` | **静态锁**：`local_version` 的赋值只能来自 frontmatter（防改回旧口径） |
| `test_source_layer_mismatch_is_flagged` | 源码层不一致 ⇒ `aligned=False` |
| `test_installed_lag_is_not_misalignment` | 安装版本落后 ⇒ `aligned` 仍 True + `installed_lag=True` |
| `test_all_three_agree_is_clean` | 三处一致（纯净发布态）⇒ 无告警、无 note |

#### 验证

- **真机** `release-audit`：`local_version` **4.9.25 → 5.0.0** ✅；新增 `installed_version: 4.9.25`；
  新增信息项 hint「本地源码版本（5.0.0）与本机安装版本（4.9.25）不同：源码领先 = 有未发布
  改动，属本仓常态。」；`verdict = ok`（**不误报**）；hints 里**无**「双主」/「取回做基准」✅
- 全量门禁 **443 用例 / 失败 0 / 错误 0 / 跳过 2 · PASS**（435 → 443，新增 8 用例）
- 旧 `test_release_audit.py` **17/17 仍绿**（其 fixture 三源同值 ⇒ 不受影响）

#### 顺带（同日 C 项）：真库遗留目录搬出

真库 `<库路径>` 顶层 3 个历史归档目录 → `<归档目录>`
（**只搬不删**）：

| 目录 | 文件数 | 大小 | 处置依据 |
|---|---|---|---|
| `_retired_backups_20260915` | 10 | 26.74 MB | `index.db` 的 4 份旧备份 + WAL/SHM 边车 |
| `_retired_tmp_20260909` | 1005 | 0.89 MB | 历史 `tmp` / `bak` 归档 |
| `memories_bak_20260831_告警验证` | 247 | 0.77 MB | 8/31 告警验证时的记忆体备份 |

- **引用核实（先证后动）**：keeper 侧对这三个名字**无硬引用**——`test_sync_copy_scope` 用
  **合成假库**自建同名目录取样；`test_sync_roundtrip` 按**前缀**（`_retired_tmp` / `memories_bak`）
  与目录名集合排除，**不要求目录存在** ⇒ 搬移零影响。
- **可逆性**：搬移前出只读 manifest（文件数 / 字节 / sha256），搬移后**双向比对**（源位置算 vs
  目标位置算）+ **第三方独立复验** ⇒ 三项 **3/3 一致** ✅。真库 `stats` 复跑正常（227 条 /
  212 active / 15 archived）。
- **保留** `quarantine/`（keeper 正式功能目录，非遗留）。
- **附带收益**：`_retired_backups_20260915`（26.74 MB）**不在** sync 测试的排除前缀内，每次门禁
  都被整锅复制；搬出后不再计入。
- 🔴 **本轮自造的一个小坑（如实记录）**：只读清单脚本把哈希 base 硬编码为真库根，搬移脚本用
  `base = 目录自身` ⇒ 两份指纹**口径不同**，搬移前比对时报出一串**假警报**「⚠️与清单不一致」。
  真伪判据只能是**同口径**的 `before == after`（本轮三项全等 ⇒ 搬移无损）。
  **教训：跨脚本比对指纹必须先统一 base 口径**；否则「不一致」既可能是数据变了、也可能只是
  算法差了（本轮实测 = 纯算法差异）。

#### 追加：测试临时目录自收口（收尾核查时发现的同类卫生缺口）

`%TEMP%` 残渣是上一轮刚根治过的主题，本轮收尾核查发现**同类缺口仍在**：

| 现象 | 实锤 |
|---|---|
| **新写的** `test_v50_version_source_semantics.py` 自己也带残渣 | 单独 `discover` 一次留 **7 个** `keeper_versrc_*` |
| 既有 `test_release_audit.py` 同缺陷 | 单独 `discover` 一次留 **16 个** `keeper_ra_skill_*` |

两者都**只靠门禁的 `keeper_` 前缀兜底回收**（`run_gate.py` 跑完清本轮）——**单独跑单个测试文件
就漏**。修法 = 各自加模块级 `tearDownModule()` 统一收口（`_TMPDIRS` + `rmtree`；
`test_release_audit.py` 同时补 `import shutil`）。

**实证对照**：清理前 23 个残渣 → 清理后 0 → 两文件各自单独跑（**8/8**、**17/17** 全绿）→ 跑完
**零残留** ✅；收尾时 `%TEMP%` 只剩门禁固定沙箱 `keeper_gate_daemon` / `keeper_gate_hooks`。

🔴 **顺带扫出的矩阵（记为待办，本轮不处理）**：全仓 **50 个**测试文件用了 `mkdtemp`，其中
**10 个无任何清理机制**（`tearDown` / `tearDownClass` / `tearDownModule` / `addCleanup` / `rmtree`
全无）：`test_audit_20260915_recall_and_hygiene` · `test_backup_prune` · `test_contract_observ` ·
`test_contract_router` · `test_cookbook_gate` · `test_import_mcp_fixes` · `test_mem_bridge_to_l2` ·
`test_recall_with_meta` · `test_runtime_state_gate` · `test_smoke_package`。

当前**未失控**（门禁前缀回收兜住），但「**单独跑即漏**」是结构性缺口 ⇒ 建议作**独立专项**逐文件
实锤（跑前跑后 `%TEMP%` 增量对照）后统一收口，不在本轮扩张范围。
### 5.0.0 · 第六轮追加（发布前复查：用户向文档版号回归 —— 补上一条迟到的闸门）

> 用户指令：「发布更新前再复查一下」。本轮**不预设上文结论**，从零重跑只读静态扫描 + 三闸实跑 + 包内容核对，
> 并在**发布前**逮到一处会随包出门的规则违规。

> - **🔴 违规：用户向文档残留版本号 6 文件 / 10 处**。规则早写在 `references/EVOLUTION.md` 开头
>   （「本文件是『文档不留版本号』规则的唯一例外」），判据也在 4.9.9 定过（版本号只是「时间戳式的叙事前缀」，
>   去掉后原意一字未损）。实测残留：`QUICKSTART.md:26`「自 4.9.27 起」/ `QA.md:69`「自 4.9.27 起」/
>   `COMMANDS.md:23/42/109`「（双时序，5.0）」等 / `FEATURES.md:100`「（5.0 新增，默认关）」/
>   `FORMAT_ANALYSIS.md:37/56`「5.0 起」×3 / `recovery_runbook.md:86`「4.9.26 起降级」。
>   **其中 6 处是本轮新写文档时引入的**，且 `FORMAT_ANALYSIS.md` 的 2 处**正落在 4.9.9 清理过的地方** ⇒ **这是回归，不是历史遗留**。
> - **根因（三层，全部实锤）**：**R1 零闸门** —— `grep -rn "版号\|version_claim\|不写版号" verify_claims.py scripts/tests/`
>   **0 命中**，规则只在文档里、靠人自觉 ⇒ 必然回归。**R2 规则清单过时** —— `EVOLUTION.md` 只枚举 6 个
>   references 文件，实际 `references/` 下有 20+ 个会进包的 `.md`；本轮 4 处命中（FEATURES / FORMAT_ANALYSIS /
>   recovery_runbook）**全在旧清单之外**。**R3 扫描盲区** —— `references/_design/*.md` 从未纳入任何扫描。
> - **口径设计（为什么不用形态正则）★**：先按直觉写「三段式 + `v` 前缀双段式 + `N.M 起/新增`」的形态口径，
>   全仓实测 **12 处命中**里混着 **2 类误报**（`127.0.0.1` 是 IP、`versions/3.13.12` 是 Python 版本路径），
>   又**漏掉 2 处**（「（双时序，5.0）」不带「起/新增」）。改用「**本仓真实版本号集合**」判定：
>   ① 从 `CHANGELOG.md` 的 `##/###` 标题收集全部历史版本号；② 每个版本登记**前缀形式**（`5.0.0` → `5.0`，
>   因文档惯用两段式简称）；③ 再补 `SKILL.md` frontmatter 当前版本；④ 只认落在集合里的 token。
>   实测 **10 处命中 / 零误报 / 零漏报** —— `127.0.0.1`、`3.13.12`、`2.92s`、外部服务 `v1.2` 天然不在集合里。
>   🔴 **更一般的教训**：判断「某段文本是不是版本号」，靠**形态**猜一定两头不讨好；靠**本仓已登记的事实**
>   （版本记账本）判定，才收敛且可解释。
> - **修法（三层）**：**L1 清存量** 10 处按判据改写（「自 4.9.27 起不再提供」→「**已不再提供**」）；
>   **L2 补闸门** 新增静态检查 `no_version_claims_in_user_docs`（claims 第 **23** 条，**在发版三闸里**）
>   + **10 用例防复发锁** `scripts/tests/test_v50_no_version_claims.py`（隔离假库 + 真仓实况，进全量门禁）；
>   **L3 修规则文字** `EVOLUTION.md` 清单由「枚举 6 个」改为「`references/` 下所有会进包的 `.md`」并写明闸门与豁免面。
>   豁免面刻意最小：整文件 `EVOLUTION.md`（规则明载唯一例外）与 `_design/changelog_archive.md`（已被
>   `.skillhubignore` 排除）；行级 `SKILL.md` frontmatter 的 `version:`（版本单一真源）。
> - **反向验证 7/7（隔离假库实跑）**：只证明「现在 OK」不够，必须证明**它会抓且不乱抓** ——
>   干净库 ok ｜ 噪声零误报 ok ｜ `自 4.9.27 起` **FAIL**（命中 `QUICKSTART.md:1 -> 4.9.27`）｜
>   `（双时序，5.0）` **FAIL**（命中 `COMMANDS.md:1 -> 5.0`）｜ frontmatter 豁免 ok ｜ 豁免文件 ok ｜
>   **基线缺失 FAIL + 明确报错**（不得静默 ok，否则闸门会永远 OK）。真仓实况：扫 **23 个用户向文档 / 0 处版本号**。
> - **包内容核对（用发布器真实 `_should_exclude()`，非注释推断）**：`_legacy.py` / 新测试 = 排除 False（**会进包**）；
>   `_meta.json` / `.skillhubignore` / `hooks_config.json` / `_design/changelog_archive.md` = 排除 True。
>   ⚠️ **取证陷阱（本轮踩到）**：`_should_exclude(root, rel)` 对**不存在的文件**返回 `False` ——
>   首次取证传入两个不存在的文件名，得到「排除=False」的假结论；改用 `os.walk` 取真实文件重测才有效。
>   **凡调判定函数，先确认入参在磁盘上真的存在。**
> - **根因族第 9 次命中**，新亚型 = **「规则写进了文档，却没有写进闸门」** ——
>   前 8 次是「读错字段 / 供给不足」的契约对账缺失，本次是它的**元层形态**：连规则本身都没被机器校验。
>   建议提为仓内新约定：**任何写进文档的硬规则，必须在 claims 或测试里有对应闸门。**
> - **验收**：全量门禁 **453 / 0 / 0 / 跳过 2 · PASS ✅**（443 → 453，新增 10 用例完全对上）｜claims **23 / 23 ✅**｜
>   发版端到端 **PASS 可发版 ✅**（cookbook / tests / claims 三闸全绿）｜真机 `release-audit` 在 CHANGELOG 插入本段后
>   **语义不变**（`local_version=5.0.0` / `installed_version=4.9.25` / `verdict=ok`）。
> - **顺带实锤（取证陷阱，已记入长期记忆）**：`_should_exclude(root, rel)` 对**不存在的文件**返回 `False` ——
>   首次取证传入两个不存在的文件名，得到「排除=False」的假结论；改用 `os.walk` 取真实文件重测才有效。
>   **凡调判定函数，先确认入参在磁盘上真的存在。**
> - **CRLF 坑（已记入长期记忆）**：本文件与报告都是**纯 CRLF**。拼接脚本若用默认文本模式读写会把整文件转成 LF
>   ⇒ 无意义巨量 diff。修法 = 全程 `newline=""` + 把片段规范成 `\r\n`；拼接后自校验
>   **CRLF 1411 → 1453（精确 +42 行）/ LF=0**，报告 1388 → 1508 / LF=0。

## 4.9.28 · 2026-09-16

> **发版门禁被自己的仓库级声明文件卡死（真回归）+ 批次快照后缀越过两道排除网（真泄漏面）**——起因：一次「是否具备发大版本条件」的全量体检，用**发布器自身函数**与**干净副本复刻**两种实跑取证，而非读码推断。两条都不是新写坏的功能，而是**此前从未按发版路径跑过**才没暴露的收口缺口。

> - **A · `PackHygieneTest` 在发布干净副本上整体 ERROR，把发版门禁卡死（真回归）★**：症状是**同一份代码两种结论**——源码树 379/0/0 全绿，`publish_skill.py --dry-run-only` 却 `[tests] FAIL(rc=1)`。误报排查逐一否证：① 环境变量假设 → `env -u KEEPER_RECALL_MODE` 手跑仍 `rc=0`（否证）；② 复刻发布器干净副本（`copytree` 排除 `.skillhubignore`）后重跑 → **复现 rc=1**，报错路径落在 `%TEMP%\skillhub_pub_*\scripts\tests\...` → 根因锁定。真因：该测试类 `setUp` **硬读**技能根 `.skillhubignore`，而发布器 `EXCLUDE_NAMES = (".gitignore", ".skillhubignore", "daemon.log")` 刻意不带它（注释明言「SkillHub 直接拒绝」）→ 干净副本上 `FileNotFoundError` × 3 用例 ERROR。**修法**：缺文件时 `skipTest(带可见理由)` 整类跳过，并在 docstring 记录契约边界 —— 这与发布器自身 `pack_excludes_runtime_state` 在无该文件时的口径（返回「本项不适用」）一致。**验收**：复刻干净副本重跑 `rc=0 / 379 用例 / FAILED=0 / ERROR=0`、`skipped={2,3}`（3 = 该组用例整类跳过），端到端 `--dry-run-only` 由 `BLOCKED 已拦截发版` → **`PASS 可发版`**。
> - **B · 批次快照 `*.p32bak` 会被打进发布包（真泄漏面）★**：4 个文件（`keeper_setup.py` / `_doctor.py` / `_recall_cache.py` / `__init__.py`，合计 380KB）是改造期按批次留的**改动前整文件快照**，含旧版源码。**两道排除网同时漏掉**：① 发布器 `EXCLUDE_SUFFIX` 只含 `.bak` / `.bak.`，而 `"x.py.p32bak".endswith(".bak")` = **False**；② 技能清单旧规则是 `*.bak_*`（要求「点+bak+**下划线**」），`x.py.p32bak` 亦不匹配。**取证方式**：直接 `import` 发布器并调其真实 `_should_exclude(root, rel)`，4 项全返 `False`（=会进包）——不复刻规则、不靠肉眼比对清单。**修法两层**：① 4 个文件同卷 move 出技能树（逐项校验字节数一致，可逆）；② `.skillhubignore` 增 `*bak` / `*bak.*` / `*.bak*` 三条**通用回退**——用「star+bak」而非写死批次号，因为这类命名是批次快照的惯用后缀、将来还会出现。**误伤验证**：11 项判定矩阵实测全过，包括 `bak_config.json`（以 bak **开头**的合法文件名）**不被误伤**、正常源码不被排除。
> - **C · 新增契约回归 `test_generic_bak_suffix_covered`（1 用例）**：守住三条通用回退不被后人当冗余删掉；只断言「规则在清单里」，不 import 发布器（发布器不属本技能、测试环境不保证可导入），行为验证配方写在 docstring。
> - **D · 技能树卫生（根因处置，非搬家）**：技能树内 `.workbuddy/`（3 个文件 / 12.8KB，含本机路径与 IMA KB id）此前被判为「一次性脏文件」，本版追到**真正来源**——WorkBuddy 自动化任务「Keeper 每周记忆维护+健康体检」的 `cwds[0]` 指向技能树，故每次运行（含每周五定时）都在那里重写运行记录，**搬走即再生**。已把该任务 `cwds` 改为工作区目录（任务名 / prompt / rrule / 状态均未动），从源头断掉再生。另清运行态 `__pycache__` 33 个 pyc。
> - **验证**：全量门禁 **380 用例 / 失败 0 / 错误 0 / 跳过 2（duckdb 环境性）**，`verify_claims` **22/22**；发布门禁端到端 **PASS 可发版**（`cookbook`/`tests`/`claims` 三闸全绿）。
> - **边界（诚实标注）**：本轮为**收口与卫生修复**，无功能变更、无数据格式变更、无需迁移。**本地未发布**——按本项目约定，未经用户要求不主动发布。

---

## 4.9.27 · 2026-09-15

> **at-rest 加密能力整体下线（功能移除）+ 连带的方向性修正**——起因：用户明确决定「不要这个功能了」。移除范围覆盖代码 / 命令面 / 测试 / 全部用户文档。**本地未发布**（按本项目约定，未经用户要求不主动发布）。

> - **A · 代码移除（两条悬空接线靠门禁逮住，不是靠肉眼）★**：删 `memory_ops/_crypto.py`（555 行）与 `_crypto` 装载块；`_core` / `_persistence` / `_quarantine` / `_versions` / `_deposit` / `_recall_cache` / `_doctor` / `_cli` / `__init__` / `keeper_setup.py` / `mem_bridge.py` / `verify_claims.py` 共 12 个文件的调用点全部收口为**明文直读直写**；同时删 3 个异常类、`_KDF_ITERATIONS` / `_SALT_CACHE` / `_CIPHER_CACHE`、`keys_gc()` / `action_encrypt()` / `_load_enc_key()`、`rekey` / `keys-gc` / `recovery-code` / `recover-key` 四个 op，以及 `--encrypt` / `--keys-dir` / `--new-key` / `--code` / `--write` / `--show-key` / `--print-key-hint` 等参数。
>   ⚠️ **教训（已固化为流程）**：`__init__.py` 的两条装载接线 `keys_gc = _doctor_mod.keys_gc` 与 `_cryptography_available = _doctor_mod._cryptography_available` 在删除被指向的函数后**漏删**，其中前者使 `import memory_ops` 直接 `AttributeError`。它没被早先的冒烟发现，原因是**冒烟跑在删函数那一批之前**——「删函数」与「删接线」分属不同批次时，中间那次冒烟是**假绿**。规则：**跨文件删除必须在最后一批之后重跑 import 冒烟**。
> - **B · `_doctor` 能力体检里的整套加密审计**：可读输出删「加密：…」行；`environment` 删 `encryption` 键；features 删 `encryption` 条目与 `# 6. 加密` 整块（后续编号 7/8/9 顺延为 6/7/8）；dashboard 删 `encrypted` 字段、`__ENC__` 占位与替换调用；`backup` 清单不再含 `salt.bin`；`restore` 不再清 salt 缓存。
> - **C · 测试层**：5 个加密专测（`test_v470_phase_d_encryption` / `test_encrypt_cache_failclosed` / `test_crypto_hotpath` / `test_keys_gc` / `test_plaintext_deposit_no_cryptography`）同卷 rename 至 `_retired_tmp_*` 归档；删 `I3RekeyRotationTest` 类与「解不开的旧内容原样快照」用例；`test_uninstall.py` 的 3 个 keyfile 安全门用例退役、`_run_action` 去掉 key/key_path 注桩、env 清单断言改为 `("AI_MEMORY_STORE", "IMA_KB_ID")`；多份用例里防御性的 `env.pop("AI_MEM_ENCRYPTION_KEY")` 一并清除。
> - **D · 红线编号重排（设计决策，附被否方案）**：原 **A1**（开加密先备兜底）随功能消失而作废，**A2/A3/A4 重编号为 A1/A2/A3**，并同步全库 7 个文件的引用（`QA.md` ×2 / `SKILL.md` ×2 / `keeper_setup.py` / `_cli.py` / `_doctor.py` / `test_backup_prune.py`）。**被否方案**：保留 A1 空位标注「已废止」——零引用风险，但会给一个不存在的功能永久留一条红线，属死文档。**A4 引用归零**已由全库 grep + 门禁复核确认。
> - **E · 文档全面对齐（17 个文件 / 73 处）**：`SKILL.md`（43 处：文首红线 3 条→2 条、删「开加密三步门」「开加密硬门」「静态加密」开关行、doctor 七项→六项、反模式清单 11 条→10 条）、`COMMANDS.md`（11）、`QA.md`（12，含删 §10 并把 §11–§14 重编号）、`TUTORIAL.md`（11）、`LIMITS.md`（5）、`FEATURES.md`（5：删 §6 并把原 §7–§10 重编号为 §6–§9）、`COOKBOOK.md`（5）、`GLOSSARY.md`（4）、`ENABLEMENT.md`（3）、`EVOLUTION.md`（3）、`QUICKSTART.md` / `INSTALL.md` / `CAPABILITY_MAP.md` / `FORMAT_ANALYSIS.md` / `references/_design/DEV_TESTING.md`。另修 2 处代码内的文档交叉引用（`_doctor.py` / `_api.py` 的 `FEATURES.md §N`）。`references/_design/changelog_archive.md` **不改**——历史档案改写即造假。
> - **F · 门禁抓出的两处真回归（均为测试侧欠账，非生产缺陷）★**：① `test_reexports` 的 AST 扫描会走到 `_retired_*` / `_bak_*` 里的**旧版源码副本**，对着历史文件报出 9 处「悬空引用」；实测生产代码**零命中**（9 处全在 `_retired_..._210647/_core.py` 等改造前副本），修法是给扫描器补归档目录排除并在 docstring 写明原因；② `test_cookbook_gate` 仍期望已被删除的 `--keys-dir`。两处都属「断言必须随功能一起演进」。
> - **G · 卫生（发布包外泄面）**：13 个改造期备份目录（`_bak_stage2_*`）**复制出技能树**并逐项校验文件数 / 字节数一致后，原地改 `_retired_stage2_*` 前缀（同卷 rename 可逆）；`.skillhubignore` 补 **`_bak_*` 前缀规则**——此前只有 `*.bak_*`，而前缀式命名**会被打进包、外泄旧版源码**。实测跨盘 `os.rename` 报 `WinError 17`，故走「复制 → 逐项校验 → 同卷改名」三步。同时清掉 6 个文档/代码里「加密能力已于 2026-09-15 移除」的过渡期注解，避免留下已过时的中间态描述。
> - **H · 诚实标注（不假装安全能力还在）**：文档不再宣传加密，但**显式写明「记忆正文以明文落盘」**，并给出替代做法——把记忆库目录（`AI_MEMORY_STORE`）放进用户自己的加密盘 / 加密容器。**移除一个安全功能却不让用户知道当前是明文，才是真的危险。**
> - **I · 安装器新增「已退役钩子」主动清理（修一处真缺陷）★**：`install_hooks.py` 原只**幂等追加**、从不清理既有条目，而第 2 步「移除模式禁止的钩子」只在事件**未启用**时生效——`bash_error_capture.py`（I13 已从技能删除）恰注册在 **silent 模式仍启用的 `PostToolUse`**，故**永远清不掉**，每次 PostToolUse 都去执行一个不存在的文件（静默失败，且是「Bash 错误疑似双份捕获」的候选来源）。新增 `RETIRED_HOOK_FILES` 清单 + 第 3 步「跨所有事件、不受模式限制」清理（只摘退役条目，同组其他 hook 原样保留），`--status` 同步报告残留。本机已实跑清理（`移除(已退役):PostToolUse/bash_error_capture.py`），复核残留归零；`settings.json` 写入前自动备份。
> - **J · `accessed_from` 写入幂等（真库净冗余 368 条）★**：真库（207 条记忆，只读统计）发现 `auto_flag_conflict` 出现 **404 次、净冗余 368 条**，多条记忆已顶满 12 条上限且内容**全是同一对矛盾**（仅 `date` 不同），把真正有用的访问证据挤出去。根因：`_reflect.py` 该分支**无条件 append**，而同一对矛盾在每次 `reflect --auto` 都会被重新检出。修法：按「对手 id」永久去重（新增结构化 `with` 字段；旧条目用 `reason` 前缀兜底匹配），`calibrated_up` 同日去重。
> - **K · 死文件归档（4 个，含一次误报拦截）**：`card_schema.py` / `memory_graph.py` / `check_env.py` / `sync_inner.py` 经**全类型无过滤扫描**（py/md/sh/json/tcl + 测试断言）外部引用 **0** → 同卷 move 至 `_retired_tmp_20260915/`（附 README 记录原路径与理由）。⚠️ 同批候选里的 **`p0_upgrade.py` 复核后保留**：原判「去扩展名仅 2 处、需确认是注释还是调用」，实测为 `_api.py` 1 处 + `_cli.py` 5 处 **`from p0_upgrade import ...` 真调用**（承载 `graph --rebuild` / `distill` / `doctor --arbitrate`）——照搬结论归档会删掉在用的命令实现。
> - **L · `_deposit_impl` 拆分：只抽 3 个内聚块，不抽 dict 字面量（纠正原方案）★**：用 **AST 重新推导**而非沿用原报告结论——原方案点名的 `L277`(73 行) 与 `L462`(30 行) 实为**纯 dict 字面量、无控制流**，读出 25–40 个局部量，抽出来会得到 **25–40 参签名 = 可维护性倒退**，故**不抽**；真正干净的是原方案**漏掉**的 `L351`(复发计数) / `L440`(向量落盘排队)，连同 `L365`(推翻旧记忆) 一起抽出 `_apply_recurrence_counts` / `_supersede_corrected` / `_persist_embeddings_or_queue` 三个具名函数（入参 3–7 个；516 → 约 444 行）。行为零变更，三条路径（复发计数 / `corrects=` / `defer_index=True` 排队）已实跑冒烟验证。
> - **M · 卫生二则**：① hooks 模式偏好原先只存**技能根 legacy `hooks_config.json`**（用户域文件不存在）→ 技能被更新 / 重装即丢，已按 4.9.19 的设计意图迁入用户配置域 `~/.workbuddy/hooks/hooks_config.json`（纯新增，零行为变化）；② 本机 `~/.workbuddy/hooks/bash_error_capture.py` 按该目录既有约定改名为 `_retired_20260915_*`（已无任何引用）。
> - **验证**：`import memory_ops`（`MEMORY_OPS_STRICT=1`）通过、20 个子模块装载、全部加密属性 `hasattr` 为 False；全库加密符号残留扫描 **0 命中**（排除归档与历史档案）；`compileall` 全通过；`test_uninstall` 8/8、`test_reexports` + `test_cookbook_gate` 6/6；**本轮新增 2 个回归测试文件（10 用例）**；全量门禁最终 **376 用例 / 失败 0 / 错误 0 / 跳过 2（duckdb 环境性）**，`verify_claims` **22/22**。
> - **边界**：这是**功能移除**，不是安全加固——**库内已有数据的可用性不受影响**（本机真库此前已迁移为明文）。若你曾用加密库，升级后**不再需要**任何 key；`store/enc_key.txt` / 库外 keyfile / `~/.ai-memory-keys/` 已无用途，可自行删除（本 skill 不再提供 `keys-gc`）。

## 4.9.26 · 2026-09-15

> **深度审计对症版：跨域召回被长文本 hubness 霸榜（β 实测归零）+ 加密密钥落盘静默失败 + 发布包本机私有数据外泄面**——起因：一次覆盖「文档 / 代码 / 结构 / 功能 / 能力 + 外部技术对标」的全方位审计，所有结论均以**真库实跑与消融实验**取证，非读码推断。
> - **A · 召回排序：`sem_magnitude_blend` 默认 `0.5 → 0.0`（真库消融实测，本版核心）★**：该参数是 4.7.9 为修「RRF 把语义信号压平导致换说法搜不到」而引入的**余弦 magnitude 回注**。实测发现其副作用远大于收益：原始余弦与 RRF 分**差一个数量级**（cos 0.3~0.5 vs RRF 1/(60+rank) ≈ 0.006~0.033），β=0.5 时 `(1-β)·rrf + β·cos ≈ β·cos`，多信号 RRF 的**实际权重不足 5%** —— 「RRF 多信号融合」名存实亡，退化为纯余弦排序。**症状（真库 199 条实测）**：查询「git-bash 路径被原生Python解析错位」的 top3 **全部**是与该查询无关的投资域长文本（`LRN-20260730-021/022/024`），正确答案 `LRN-20260729-007`（cygpath 路径规范）被压到第 5；根因是长文本摘要向量落在语义空间中心区、对任意查询都给出虚高余弦（**hubness 假阳性**：词法零重叠、仅靠余弦上位）。**消融对照**：β=0.0 后同一查询 top3 全部变为强相关技术记忆（审计方法/测试铁律/环境坑），而域内查询（84日均线、加密恢复码、IMA 同步、小说 POV 共 7 组）排序**基本不退化**。改后真库复测：跨域三类查询的 top8 已无任何投资域误召回。参数仍可经 `config.json` 的 `recall` 块覆盖回 0.5（无需改码），依据已写入 `RRF_DEFAULTS` 上方注释。
> - **B · 加密密钥落盘从「静默 pass」改为真 fail-closed（A1 红线同族）★**：`rekey` 原实现把「写库内 keyfile + 库外兜底」排在**全库重加密之后**，且 `except Exception: pass`，失败仍返回 `ok=True` + 恢复码 —— 用户会据此认为「兜底已就位」，而实际上库已换成新密钥却**没有任何新密钥落盘**；更糟的是解析优先级是 `env > 库内 > 库外`，库内 keyfile 若仍是旧 key，下次未设 env 时将解析到**旧 key 而解不开全部新密文**。修法两处：① **把库外兜底前置到动数据之前**（`_ensure_key_backup(..., strict=True)`），失败即中止——此刻数据尚未重加密，属干净退出，**杜绝不可恢复窗口**；② 成功后写库内 keyfile 若失败则**记入 `errors` + stderr 红字告警**（含影响说明与恢复动作），不再静默。另为 `_ensure_key_backup` 增 `strict` 形参：常规加密路径仍 fail-open（不阻断主流程），但**必须告警**——写库外兜底失败却无人知道，正是 A1 红线的触发场景。
> - **C · 召回参数误写进 `keeper` 块导致静默失效（实测已发生）**：本机 `store/config.json` 把 `semantic_gate` 写在 `keeper` 块，而 `_load_recall_config` 只读 `recall` 块 → 该配置**从未生效**（用户以为关了语义门控，实际仍走默认 0.42）且无任何提示。修法：`_load_recall_config` 增加 **`keeper` 块兜底**（`recall` 块同名键仍优先），向后兼容、老配置行为不变。实测确认 `keeper` 块写法现已生效。
> - **D · 发布包排除面补齐（体积 + 私有数据）**：`.skillhubignore` 增三项——① **`.workbuddy/`**：本机自动化记录与运行记忆（含会话痕迹），属**使用者私有数据**，此前未被排除、会随包分发；② **`*.log`** 兜底显式声明；③ **`references/_design/changelog_archive.md`**（223KB 纯历史档案，对使用者零价值却随每次安装下载，需要时用 `release-audit` 的 `archive_versions` 索引即可）。
> - **E · 门禁不再依赖调用方「记得声明」**：`run_gate.py` 顶层 `os.environ.setdefault("KEEPER_RECALL_MODE", "inprocess")`。背景是既有铁律——凡 spawn 钩子或走 recall 的用例，若落到**跨模块共享的 daemon** 上会因生命周期/状态残留产生「顺序依赖型间歇假红」（受害者每次不同、单跑必过），而该前提原先只写在文档与经验里靠人记。用 `setdefault` 而非写进 `_SAFE_ENV_BASELINE`：**尊重调用方的显式覆盖**，只在无人声明时兜底。
> - **F · 新增契约回归 `test_audit_20260915_recall_and_hygiene.py`（8 用例）**：守住本次三项修复不被误改回——① `sem_magnitude_blend` 默认必须为 `0.0` 且**实测依据必须留在代码注释里**（含 `hubness` 与日期，防止后人当成随手值改回去）；② `keeper` 块兜底生效且 `recall` 块仍优先；③ `.workbuddy/`、`changelog_archive` 必在排除清单，同时**负向守护**既有规则（`.write_lock` / `*.bak_*` / `_retired_*` / `hooks_config.json`）不被误删。⚠️ 该测试**只守契约、不测排序行为**：β 的问题仅在 neural 语义后端显现，而门禁基线固定 `lexical`（不拉 90MB 模型），故行为验证配方写在该文件 docstring 里供人工复核。
> - **G · 分层路由从「恒空」救活：接上 `scope` 字段（根因=读错字段，非缺信号）★**：`doctor` 的 `route_distribution` 长期恒为 `{L2:0, L3:0, L4:N}`、晋升候选恒 0，此前记为「设计闲置 / 需产品决策」。本版追到根因并修复——**不是标签体系没落地，而是 `decide_home` 读错了字段**：它只查 tags 里 5 个钥匙词 + 2 个 category，而真库 216 条 tag 普查显示**钥匙词命中 L2=0 / L3=1**（474 个去重标签、1629 次出现）；真正表达分层的是 **`scope` 字段**（实测 `universal:142 / project:70 / ephemeral:4`，100% 覆盖），语义与 `L2/L3/L4` 一一对应，但 `decide_home` **从不读它**、`_deposit.py` 调用点**也从不传它**。修法三处：① `router.py` 增 `RULE_SCOPE_TO_LAYER`（universal→L2 / project→L3 / ephemeral→L4），`decide_home` 新优先级 **tag > scope > category > 默认 L4**（tag 仍最高：用户显式动作 > 可能由分类器推断的 scope，保持既有语义与测试向后兼容）；② `RouteRegistry.decide_and_record` 透传 `scope`；③ `_deposit.py` 调用点补 `scope=…`。**只读验证（真库 216 条重算，不写盘）**：`{L4:219}` → **`{L2:142, L3:70, L4:4}`**，scope→层 **100% 一一对应零例外**，晋升候选 `0 → 212`。**顺带修一处用户可感知的文案错误**：`_deposit.py` 的 scope 报错提示原写「常用：universal / project / **private**（仅自己）」，而 `SCOPES=("universal","project","ephemeral")`——**`private` 非法、合法值 `ephemeral` 反而漏写**，照提示填必然报错；已与 `SCOPES` 对齐。新增 6 个合约用例（`test_contract_router.py` 8→14，覆盖三值映射 / tag>scope / scope>category / 未知 scope 不静默判层 / 登记册透传 / 分布分流）。⚠️ **边界**：keeper 无权写 WorkBuddy 原生库，「晋升」仅产出**候选提示**，不自动搬运；且 212 这个裸数字是否该进一步按域聚合，留待观察真实输出后再定（避免过度工程）。
> - **H · 投资域证据链 lint 从「违规」降级为「提示」（治本，而非加抑制机制）★**：`doctor` 的 `investment_invariants` 每次固定报 **16 条**同因"违规"（`verified * 缺少 validated_by 出边`），构成**告警疲劳**（真信号会被恒定噪音淹没）。上一轮审计曾建议「加 ack 抑制」——本版诊断后**主动纠正为治本方案**：抑制只是把噪音藏起来，根因在规则本身。**真库取证（216 条 index 实读）**：① 全库 26 类关系边均在正常产生，唯独 `validated_by` 仅 **2 条**（占比 0.9%），本 lint 命中 18 条中只有 2 条带该边 → **16 条违规与 doctor 完全吻合**；② 18 条中 `status` 实为 **active 15 / archived 2 / superseded 1**——要求**已失效**条目持有"当前证据"逻辑不通。修法两处：① **排除非 active**（archived/superseded）条目，计入新字段 `excluded_inactive`；② 结果从 `violations` **降级为 `hints`（`severity:info`）**——保留为可选改进建议，不再是"错误"；`violations` 键保留且恒空（向后兼容）。**这是本轮审计第三次命中同一模式**——「**规则层期待的字段 ≠ 写入侧实际产生的字段**」（另两例：分层路由读 tags 钥匙词而真信号在 `scope`；`semantic_gate` 写在 `keeper` 块而代码只读 `recall` 块）。文档同步 `references/recovery_runbook.md` §6 与 `references/GLOSSARY.md`。**只读验证（真库实跑）**：`checked=15 / excluded_inactive=3 / violations=0 / hints=13`（旧为 `checked=18 / violations=16`）。
> - **I · 审计发现但本版**未**改动的项（如实记录，避免「报告即闭环」的错觉）**：① **263 处 `except: pass`** 未逐条分类，本版只处理了安全关键的那几处；② **巨型函数**（AST 实测，非文本切片）：`_cli.py::main` **1219 行** / `_deposit.py::_deposit_impl` **516 行** / `_doctor.py::doctor` **452 行** / `_api.py::recall` **343 行**（`memory_ops/__init__.py` 3890 行、`_doctor.py` 2905 行是文件级体量）；⚠️ **更正**：此前记的「`init_store` 单函数 567 行」是**测量误报**——`init_store` 实为 **11 行**薄包装（文本切片从 `def init_store` 一路量到注解/再导出行所致，AST 口径才准）；③ `_api.py` 等子模块靠 `__init__` **运行时全局灌入**解析依赖（无 import 语句）→ 静态分析器无法解析、易造成「孤儿脚本」类误判（本次审计即误报过 3 个实际有文档/CLI 引用的脚本）；④ **`doctor` 其余建议项仍无 ack/抑制机制**（type 漂移 2 条 + link 候选 5 条长期挂起）——留待大版本统一设计**状态持久化**。以上均建议按独立版本 / 大版本处理。

## 4.9.25 · 2026-09-13

> **发版门禁被环境拖垮的根因修复（加密热路径性能回归 / 同步测试耦合真库体量 / 超时窗口一刀切 / 注入测试依赖共享 daemon）+ 测试临时目录磁盘卫生**——起因：4.9.24 收尾跑 `publish_gate.py` 连续两次 `FAIL(rc=124)`，第二次**全程零并发**仍超时；而同一套 `run_gate.py` 此前单跑 17.5 分钟全绿。逐层实测定位到四个**互相独立**的成因（A / B / C / F，见下），本版全部落地（经用户明确要求发版，三道发版门禁全过）。
> - **A · 加密热路径的重复一次性 IO（本侧 4.9.24 引入的回归）★**：`_fernet_cipher()` 每次取密码器都会走到 `_ensure_key_backup()`，而后者是**一次性**语义（幂等备份密钥到库外 + 打印恢复码警告 + 归属登记）。4.9.24 把归属登记挂在它开头，于是逐条批量导入会**按条**重写整个库外 `registry.json`（读 + 写临时文件 + `os.replace` + `chmod`）；而备份本身也排在 cipher 缓存查读**之前**，缓存命中根本挡不住它。实测（30 条 × 5 组对照）：加密下单条 deposit **0.111s → 0.018s（6.2 倍）**，整组合计 5.70s → 0.57s（10 倍）——修后加密几乎不额外花钱（明文基线 0.011s）。修法两处：① 备份移到「缓存未命中」之后——只有本进程首次用这组 (库, 密钥) 才做；② 登记改用既有的带进程内去重版本（`_keys_registry_record_once`）。**语义不变**：备份与警告本来就只该发生一次；「曾加密却拿不到密钥」的 fail-closed 判定在 `_encrypt_fields`，不经此处。新增 `test_crypto_hotpath.py`（6 用例，含「换一个库必须再登记一次」的防恒绿负向对照 + 「库外 keyfile 必须真的落盘」对照）。
> - **B · 同步测试耦合真库体量 ★**：`test_sync_roundtrip` 直接 `copytree(真库)`，于是用例耗时**线性绑定真库体量**：① 历史归档（`_retired_tmp_*` / `memories_bak_*` / `quarantine/`）与同步无关却整锅复制；② `store/index.db`（真库 41MB）是召回加速镜像，而同步走的是**文件层**（`export_memories → _iter_all_mems`），A 机作为同步源并不需要它；③ 逐条全流程往返，真库 196 条 × 多轮 × 每条 0.1~3s。修法：`_copy_ignore()` 回调排除无关归档、`memories` 根目录只留最近 N 条（`AI_MEM_SYNC_TEST_MAX`，默认 60，设 0 退回全量）、不带 `index.db`；`memories/archive/` **全保留**（状态收敛依赖它）。裁剪发生时打印一行说明（不静默改变验证范围）。新增 `test_sync_copy_scope.py`（8 用例，用合成假真库逐项正反断言保留/排除范围）。
> - **C · 发版门禁超时按闸门分档 ★**：`publish_gate.py` 原把三道闸门的超时**一刀切**（统一 1800s），但三道耗时量级差两个数量级（文档一致性约 0.3s / 静态断言约 20s / 全量集成测试十几分钟）：对前两道是巨大浪费余量、对 tests 只剩 1.7 倍。实测跑满 1800s 被强杀（`rc=124`），门禁报 BLOCKED 却**与代码质量无关**——假红灯会让人对真红灯脱敏。现每道自带分档超时（`cookbook 300` / `tests 3600` / `claims 900`），显式 `--timeout` 仍可统一覆盖；每道开跑时打印自己生效的超时值。新增 `test_publish_gate_timeout.py`（7 用例，含「`--timeout` 的 argparse 默认值必须是 `None`，否则分档永远不生效」的负向对照）。
> - **D · 顺带修一处文档漂移**：`references/recovery_runbook.md` §7 写「`python scripts/publish_gate.py --version <预期版本>`」用于校验线上 `latestVersion`，但 `publish_gate.py` **从来没有** `--version` 参数（只有 `--skip-tests` / `--only` / `--timeout`）——照文档敲会直接报错。改为本 skill 自带的 `python scripts/memory_ops.py release-audit`（本地日志 ↔ 平台真实版本对账，退出码 `0` 一致 / `2` 漂移 / `3` 未知），与发布账本能力对齐、不再依赖发布器版本。
> - **E · 文档同步**：`references/COOKBOOK.md` §6 增「发版门禁 `tests` 超时」排查条目（含 `--timeout` 分档与 `AI_MEM_SYNC_TEST_MAX`）；`references/_design/DEV_TESTING.md` 补分档说明。
> - **F · `test_inject_gate` 的「共享 daemon」依赖型间歇假红 ★**：收尾跑发布器 dry-run 时又被自家门禁拦下（`[gate] 运行 354 个测试 · 失败 1`），红灯是 `test_inject_gate.test_config_true_enables`（「开关已开却拿到空上下文」），而**单跑该模块 3/3 全绿** —— 典型顺序依赖型假红。取证链：① `hook_audit.log` 在失败那一秒记的是 `empty no entries`，即**守门已放行、是召回为空**，不是开关拦下；② `keeper_hook_common.recall_mode()` 的**默认值是 `daemon`**，而 daemon 是**跨模块共享**的常驻进程（门禁把 `KEEPER_DAEMON_DIR` 钉到共用沙箱、`idle 45s` 不退出）；③ `keeper_recall_client.recall_proxy()` 在 daemon 不可用时 `except: pass` → `_fallback_skip()` **静默返回空 entries**——生产语义是「宁可不注入也不阻塞会话」，在测试里却把「daemon 没就绪」伪装成「召回为空」；④ daemon 日志实测首次 `warmup` 耗时 **2.93s / 3.29s / 4.94s**，而客户端 `urlopen(timeout=5)` —— **正好顶在超时线上**。修法：**与同仓库既有先例对齐** —— 姊妹模块 `test_inject_include_auto.py` 早已声明 `KEEPER_RECALL_MODE=inprocess`（注释原文「免 daemon，确定性」），本模块漏了同一前提。现 `_run_hook` 与 `setUpClass` 的预置 deposit **两处都声明**，并给预置 deposit 补**返回码校验**（原先静默忽略失败，会让「没东西可注入」伪装成断言失败，把环境问题误报成功能缺陷）。**为什么不改门禁基线**：daemon 是产品功能、有专项测试需要真实 daemon 语义，故把前提**下沉到用例** —— 这正是「测试必须自己声明前提」的落地：依赖共享资源而不声明，就会得到顺序依赖型的间歇假红。**验证**：全量门禁**连跑 3 次 3/3 全绿**（单次绿不足以定论——修复前是约 50% 概率红），发版门禁三道全过（`cookbook 0.4s / tests 165.3s / claims 27.1s`）。
> - **G · 边界说明**：本版各项均属**内部质量基建**（门禁与测试），无用户可见命令/配置变更；`test_sync_roundtrip` 默认只取真库最近 60 条属**有意的验证范围收窄**（为让用例耗时与真库体量脱钩），需要全量验证时显式设 `AI_MEM_SYNC_TEST_MAX=0`。
> - **H · 测试临时目录回收（磁盘卫生）★**：`scripts/tests/` 下 50+ 个用例各自 `tempfile.mkdtemp()` 建沙箱、**从不回收**，门禁每跑一轮就多留一批，且**没有任何机器判据**会提示这件事。本机实测 `%TEMP%` 已积 **1459 MB**：`keeper_sync_*`（同步用例整库 `copytree`，91 个目录 / 36601 文件 / **1.4 GB**，大头）、`keeper_gate_*`（898 个）、`keeper_daemon_scope_*`（198 个），合计一千多个目录。修法：门禁**跑前清超龄残留**（`mtime` 早于 6 小时前——兜历史存量与上次崩溃留下的）、**跑完清本轮产生的**（`mtime >= 本次门禁启动时刻`），两档任一命中即回收；`--keep-temp` 可保留以复现排查。**三条安全边界都不省**：① 白名单前缀（只认 `keeper_` / `plain_` / `mem_demo_`，绝不扫别的目录）；② 固定共享沙箱（`keeper_gate_hooks` / `keeper_gate_daemon`）始终排除（daemon 可能仍活着）；③ 跑前那档传「当前时刻」，判据 `mtime >= since_ts` 天然不命中 → **绝不会误伤并发进程刚建的沙箱**。回收全程 **fail-open**——磁盘卫生动作不能反过来把门禁判红。新增 `test_gate_temp_cleanup.py`（6 用例，三条防恒绿负向对照：非白名单前缀必须保留、固定沙箱必须保留、早于本次启动的新目录必须保留）。

## 4.9.24 · 2026-09-13

> **生命周期两端补口（发布端账本 / 退役端清理）+ 历史账补齐**——起因：9 月 13 日实测发现线上已到 4.9.22，而本机权威副本还停在 4.9.13：另一台机器连发了 9 个版本，本机**毫不知情**。复盘指向四类「没有机器判据」的缺口，本版逐条补上。**已并入 4.9.25 发布**（本地未单独发版）。
> - **A · 新增 `release-audit`：发布账本核对（本次事故的根因工具）★**：此前「线上到底发到几版」只存在于人的记忆里——全库搜 `latestVersion` / `api/v1/skills` **零命中**。新命令把 `CHANGELOG.md` 记录的版本集与平台 `/versions` 真实版本集做对账，**机器可查**。三条口径专治误报：① **权威窗口**——历史 CHANGELOG 会轮转归档、早年版本常被合并成摘要条目，故只比对「主 `CHANGELOG.md` 最早版本」之后的区间，更早的平台独有版本归 `legacy_missing`（信息项，不影响结论）；② **区间标题**——`## 4.8.2–4.8.7` 这类连续迭代的合并条目按区间覆盖处理，不要求逐版单列；③ **本地未发布 ≠ 漂移**——本地版本高于线上（可累积**多个**未发布版本）是「改完没发」的正常态，记 `unreleased_local` 提示、不算 drift。输出分桶：`missing_log`（窗口内平台有、日志无）/ `bundled`（日志有、平台无、且平台已越过它）/ `unreleased_local`（本地已记录但未上线）/ `legacy_missing`（窗口外早年缺口）。⚠️ **口径经实测纠正**：v2 首版把「日志有、平台无、且不等于 `local_version`」判成 `pending`→drift，本机因累积了 4.9.23 / 4.9.24 两个未发布版本而**在正常状态下报红灯**——那正是本项目「未经要求不主动发布」的日常态。现 drift **只认两类**：平台有日志无、本地落后线上。退出码：`0` 一致 / `2` 漂移 / `3` 未知。
> - **A′ · 「不知道」绝不当作「有问题」**：拿不到平台数据（断网、超时、平台返回空）时 `verdict="unknown"` + 退出码 3，而**不是**报 drift；`--offline` 只做本地自检，明确输出「**无法判定一致性**」。理由：假红灯会让人对真红灯脱敏。另：本地版本**落后**于线上时额外提示「多机并行时这正是『双主』的前兆，先把线上包取回做基准」。
> - **B · 新增 `keys-gc`：库外 keyfile 生命周期治理**：`~/.ai-memory-keys/` 只按路径哈希命名（`sha1(abspath(root))[:16]`）、**不含归属**，本机实测 800+ 份；库删了或搬了它就成无法反查的垃圾——而它同时是加密库「忘 env key」时的**唯一现场兜底**，所以只能**证明**是孤儿才动。新增 `registry.json` 登记归属（写 keyfile 时自动登记，幂等），每份 keyfile 落**唯一**一档：`live`（归属库仍在）/ `unreachable`（归属库所在**卷**当前不可见，如移动盘没插）/ `orphan`（路径不存在且**卷**可见）/ `unregistered`（无归属记录，旧版写下的）。🔴 **默认 dry-run；`--apply` 才搬，且只搬 `orphan`、只做同卷 `rename`**（不删除、可逆）。**卷级判据是关键**：把「库真删了」与「盘没插」混为一谈 = 清掉加密库的唯一兜底 = 数据永久不可读。
> - **C · 备份补齐「可被自动化调用」与「可恢复性抽检」**：`backup` 新增 `--keep N`（只保留最近 N 份，超出的**同卷搬离**而非删除，`protect` 名单不入选），把「手动跑一次」变成**幂等**步骤、可交给周维护；配合既有 `restore --dry-run --verify` 形成「备份 → 抽检可恢复」闭环。
> - **D · 新增 `keeper_setup.py uninstall`：一条收口的卸载 ★**：此前「退出」是散的——`setup_scheduler.py --uninstall` 只管计划任务、`hooks --mode off` 只管钩子，其余（守护进程、钩子注册、环境变量、库外 keyfile）散落各处、无人负责。新命令**默认 dry-run**、逐项列出将要做的事（`--yes` 才执行，`--purge-env` 才清环境变量）。🔴 **安全门**：库已加密但库外 keyfile 缺失时**拒绝**执行——否则「卸载」等于把加密库变成永久不可读。
> - **E · 历史账补齐（对账的「预期结果」）**：① 补 `## 4.9.15 · 2026-09-12`——该版**确已发布**（2026-09-12 14:55），内容为「发布门禁修复：`QA.md` 章节锚点修正 + 全量门禁复跑（251 测试 0 失败 0 错误）」，当时本地日志把它的内容并进了 4.9.16 条目、标题却漏了；② 补 `## 4.8.2–4.8.7 · 2026-08-31` 区间条目——这六个版本于 08-31 19:48~22:44 连发，**任何文档都无对应记录**；③ 去重：`## 4.9.1 · 2026-09-05` 在权威源里出现**两次**（发布器自动生成的标题混入），合并为单条。①② 均为**事后补记**，正文注明「原文取自平台版本元数据」。
> - **F · 配套**：`OP_NAMES` 增 `release-audit` / `keys-gc`（CLI 与命令表同步）；文档同步（`references/COMMANDS.md` 补行、`references/COOKBOOK.md` §5 加「升级后核对线上账」/ §10 加卸载、`SKILL.md` 功能开关表加一行）；新增回归测试（`test_release_audit.py` / `test_keys_gc.py` / `test_backup_prune.py` / `test_uninstall.py`）。

## 4.9.23 · 2026-09-13

> **发版前整理：用户向文档去版号 + 发布洁净度门禁误红修复 + 边界/开关可见性**——本版无新能力，只修「文档与判据」三类问题，均为评审反馈的直接对症项。
> - **A · 用户向文档清除版本号残留（7 处）**：`SKILL.md` 5 处 + `references/COMMANDS.md` 2 处。约定：用户向文档只讲「现在是什么行为」，不写版本号（带版号的「自 X.Y.Z 起」会随迭代立刻过期）；版本沿革统一看本文件与 `references/EVOLUTION.md`。
> - **B · CHANGELOG 状态措辞改事实口径**：`4.9.17`–`4.9.21` 条目原写「本地修复，未发布（同待发版）」——这五个迭代的改动**已全部并入 4.9.22 发布**，旧措辞既不准确、也易被读成「长期积压未修」。现改为「已并入 4.9.22 发布」。
> - **C · 发布洁净度门禁修误红（`pack_excludes_runtime_state`）**：该闸门原以「目录里有 `_meta.json`」判「这是源码树」，于是**平台下发的下载/安装副本**（含平台注入的 `_meta.json`、却没有仓库级 `.skillhubignore`）被误判成源码树 → 在自家发布产物上恒报假红。改为：**缺 `.skillhubignore` 即无从校验，本项跳过**（不再拿 `_meta.json` 当「源码树」标志）。
> - **D · 边界与开关可见性（对症 boundary / usability 评审项）**：`SKILL.md` 顶部新增「🧭 其余边界速查」（清理命令怎么选 / 归档≠真删 / 衰减只降权 / 域落空是设计 / 加密字段级，各一行 + 指针）、新增「🔀 可选功能开关表」（能力 → 收益 → 命令 → 红线，含「开加密三步门」）；把原先埋在 §九 深处的次要边界上提到读者第一屏，并在 §九 开头加指针。
> - **E · `.skillhubignore` 补两项**：`keeper_daemon/daemon.log`、`hooks_config.json`（钩子模式偏好已迁出源码树，旧位置仅只读兜底，**不得随包分发**）。

## 4.9.22 · 2026-09-13

> **发布洁净度门禁补一条「声明了却没人验」的缺口 + 工具层竞态定性**——源自 4.9.21 收尾时上报的两条知会项（用户追问「这两个能修复吗」）。**已随本版发布**（4.9.17–4.9.21 的改动一并并入本版）。
> - **A · `.bak_*` 排除纳入发布洁净度门禁（真缺口）**：`.skillhubignore` 自 4.9.19 起写着 `*.bak_*`，但 `scripts/tests/test_pack_ignore_gate.py` 里**搜不到 "bak"** —— 即「**有人声明、没人验证**」，属本 skill 反复踩的「声明与生效脱节」同族。实测三处证据：① `verify_claims._PACK_IGNORE_PROBES` 无 `.bak` 探针；② 两个开发期回滚基线 `mem_bridge.py.bak_20260913`（138938 B）与 `hooks/post_tool_use_error_capture.py.bak_20260913`（5955 B）与本体 **md5 均不同** → 确为真实的**改动前快照**，保留正确；③ 但「保证它不随包外泄」此前**无任何机器判据**。修法：探针清单增 `mem_bridge.py.bak_20260913` 一条；`test_pack_ignore_gate.py` 的 `_REQUIRED_LINES` 增 `*.bak_*`、等价通配用例改用**窄写法** `mem_bridge.py.bak_*`（继续证明「判据是语义覆盖而非逐字匹配」）、新增负向用例 `test_missing_bak_snapshot_exclude_fails`（删该行必须 FAIL）。模块 **9/9 OK**（原 8）。
> - **B · 同一文件并发 `Edit` 静默丢改动 —— 受控实测定性（宿主工具层，非本 skill 代码缺陷）**：在一条消息里对**同一文件**发多条 `Edit`，工具**每条都回 `Successfully edited`**，但落盘**静默丢 40~60% 且非确定性** —— 实测 3 条只落 1 条、5 条只落 3 条、4 条只落 2 条。**对照**：对**不同文件**各发一条（3 条）**3/3 全落** → 并发本身不是问题，**同一文件的并发「读-改-写」才是**。
> - **C · 规避物落地**：新增 `_tools/atomic_patch.py`（工作区开发工具，**不进发布包**）—— 按 `spec.json` 把「同一文件的多处替换」放进**一次进程**内完成并**回读自校验**；同文件任一处失败则该文件**整体不写**（原子）。实测 4 处改动 **4/4 全落**（对比并发 `Edit` 丢 2/4），支持 `--dry-run`。
> - **D · 落进纪律**：① 同文件多处改动 → **一条消息只发一条 `Edit`**，或改用**单次整文件 `Write`**（本次改 `test_pack_ignore_gate.py` 即用此法），或走 `atomic_patch.py`；② **改完必须回读核验** —— 「工具报成功」≠「改动落盘」；③ **不同文件仍可安全并行**。

## 4.9.21 · 2026-09-13

> **交接单三项建议落地（清理命令边界 / 冲突告警降误报 / 兜底域开关）**——源自并发会话《keeper 问题交接单》§5.3/§5.4/§5.5，本侧逐条实测核验后实施。**已并入 4.9.22 发布**。
> - **A · §5.3 清理命令边界入文档（治「误用 `purge` 清当天噪音」复发面）**：三个落点同时补 —— ① `SKILL.md` §九新增「清理类命令怎么选」边界段，点明 `purge` **只真删「已归档 / 已被取代」且超龄（默认 180 天）+ 低重要度（默认 <0.4）**的软删件，`active`（含今天刚记的）**永不在候选内**，跑出「0 条候选」属正常；给出五行对照（`reflect --auto` 去重纠错归档不删 / `archive --id` 单条软归档 / `decay --apply` 只降权 / `reclaim --apply` 批量软归档 / `purge --apply` 受控真删）；② 路由表 `archive` 与 `purge` 两行各补边界与指针；③ `mem_bridge.py` 的 `purge` 子命令补 `description`（`RawDescriptionHelpFormatter`，**`--help` 里真正可见**，非仅顶层列表）+ `--older` 说明。
> - **B · §5.4 `--check-conflict` 降误报（方案① 零行为变更：只改文案，不动判据）**：矛盾侧判据是启发式（`cos≥0.6` **且** 两侧正/负情感关键词相反），**不等同结论相互矛盾**（描述同一件事正反两面的经验、以及自然语句里同时出现「要/不要」的条目都会命中；交接单实测 3/3 假阳性）。四个出口统一补「**须人工读正文裁定，勿直接隔离**」：`deposit` 的两条运行时 note、`--check-conflict` / `--quarantine-conflict` 的 `--help`、`audit_b` / `coach_wb` 的审计输出标题，以及 `_b_conflict_check` 的 docstring 契约（明写「不得据此自动隔离或删除」）。**判据换成「结论极性」属行为变更，留作独立版本，本次不做。**
> - **C · §5.5 `domain` 缺省回填 = 显式开关（默认关）★ 口径经实测改写**：交接单原提案为「直接回填」，本侧查证后**否决改默认** —— `domain=None` 是**有意设计**：`_doctor.py` 明文「`fallback_domain` 是兜底筐，**未匹配记忆存为 `domain=None`**，其覆盖由『域分布』的 none 桶体现」，且 `reclassify_by_taxonomy` 明文拒绝「强行推到 fallback」。按既有判据「**默认值是『不够灵活』→ 加开关；『语义上就是错的』→ 才改默认**」，此处属前者 → 实现为 `KEEPER_DOMAIN_FALLBACK=<域>`（如 `general`）**opt-in，默认关 = 行为与旧版逐字一致**。落点选在 **`deposit`（单一咽喉点，在 taxonomy 路由与 tags 推断之后）**——不做在 `distill` 层，因为桥接层提前填域会**覆盖掉 `deposit` 更聪明的自动路由**（`distill` 拿不到路由结果）。落域同时打 `domain:fallback` 标签：与用户**显式**指定的同名域区分，并让 `reclassify --pending` 仍能捞出待人工归类。
> - **D · 配套防「静默滤掉」**：`reclassify_pending` 把 `domain:fallback` 视为**仍缺 domain**（其余轴照旧）——否则一开开关这些条目就从数据质量队列**静默消失**，正是本 skill 反复踩过的「静默恒空」同族形态。`SKILL.md` §九同步声明「域分类落空 = `domain=None` 是设计不是缺陷」并给出开关名。
> - **E · 回归测试**：新增 `scripts/tests/test_domain_fallback_and_doc_contract.py`（9 用例）——`DomainFallbackSwitchTest` 5 条：默认关仍为 `None`（关键回归点）/ 开启后落域并打标签 / `off|none|0|false` 视为关闭 / **既有路由优先于兜底**（tags 已判域时不得抢占）/ 兜底条目仍在 `reclassify --pending` 队列；`CleaningAndConflictDocContractTest` 4 条：`SKILL.md` purge 边界段、`domain=None` 语义段、`mem_bridge` 源码含禁止性契约，以及**真实跑 `purge --help` / `distill --help`** 断言文案对用户可见。
> - ⚠️ **实测教训（工具层，非代码缺陷）**：同一文件的多条 `Edit` 在**一条消息里并行提交会互相丢改动**（本次 3 条并行 Edit 到 `mem_bridge.py`，仅前 2 条落盘、第 3 条静默丢失）。凡改同一文件必须**逐条串行**，改完**回读/回查核验**，不可凭工具返回的「成功」下结论。

## 4.9.20 · 2026-09-13

> **`PostToolUse` 错误捕获「空壳落库」根因修复 + 存量清理**——前两次修复（2026-09-05 退出码字段名读错 / 2026-09-12 summary 取成整个 JSON 结构）均未覆盖本类缺陷。**已并入 4.9.22 发布**。
> - **A · 空壳门（核心）**：`hooks/post_tool_use_error_capture.py` 在「判定为失败」与「写库」之间补一道 `if not err_text.strip(): return`。原实现只要 `code != 0` 就令 `err_sig=True` 并照写，而错误文本取不到时 body 落成「命令:…\n\n错误输出:\n（空）」—— 零信息量空壳。**实测铁证**：库内 5 条 `auto-captured` 记忆的「错误输出」全空；`hooks/_errcap_state.json` 的错误指纹恒为 `d41d8cd98f00b204e9800998ecf8427e`（= `md5("")`）→ **10 分钟去重冷却被彻底架空**（所有失败共用一个坑位）。空壳又因 `tier=working + state=pending + priority=high` 混入 `list_working` 进行态列表，污染「半空接班」视图。
> - **B · 兼容字符串型 `tool_response`**：原 `tr = resp if isinstance(resp, dict) else {}` 在事件把 `tool_response` 给成**字符串**时 `tr` 恒为空 dict → `stderr`/`stdout` 皆空（A 的成因之一）。改为：字符串响应先 `json.loads` 尝试（成功即走 dict 路径），失败则整体视为纯文本 `stdout`。两种事件形态双向兼容。
> - **C · 存量清理（软删可回滚）**：`LRN-20260913-001/002/003/004/008/011` 共 **6 条**空壳经 `memory_ops.archive` 沉入 `memories/archive/`（`status=archived`，`unarchive` 可回滚），`mem_bridge working` 复核已清净。判据三重收敛：tags 含 `auto-captured` + body 含 hook 固定格式「错误输出:」+ 该字段后为空。⚠️ 方法更正：`purge` 对此**无效**（只按「超龄 ≥180 天 + 低重要度」筛，删不到当天新写的条目）。
> - **D · 回归验证（A/B 对撞，6 用例全过）**：以模拟 PostToolUse 事件喂隔离 store，备份文件（修复前）与现文件（修复后）并跑 —— `修复前|空输出(dict)` 落库 1 条（**复现 bug**）→ `修复后|空输出(dict)` 0 条、`修复后|空输出(字符串)` 0 条、`修复后|有错误文本(dict)` 1 条（不误伤真错误）、`修复后|有错误文本(字符串)` 1 条（兼容生效）、`修复后|成功命令(exit=0)` 0 条（回归 2026-09-05 修复）。总体 ALL PASS。
> - **E · 部署副本同步（关键 —— 不做则本修复完全不生效）★**：本 skill 的钩子在 `<WB_HOME>/hooks/` 另有一份**部署副本**（WorkBuddy 实际调用的就是它），与源码树 `skills/agent-local-memory-keeper/hooks/` 是**两份独立文件**（inode 不同）。改完源码后实测两份 md5 不一致（源码 7557 B / `58aaabdb07de` vs 部署 5955 B / `287cbc4fb492`）→ 修复**尚未生效**。已备份旧部署副本后同步，两份 md5 归一，并用**部署副本**重跑 3 用例（空输出-dict / 空输出-字符串 / 有错误文本）全 PASS。顺带全量比对 6 个钩子：**仅本文件不一致**，其余 5 个与源码一致（4.9.19 等修复此前均已正确部署）。
> - 备份：`hooks/post_tool_use_error_capture.py.bak_20260913`（源码改动前快照）、`<WB_HOME>/hooks/post_tool_use_error_capture.py.bak_20260913`（部署副本旧版快照）。
> - **F · 复核补记（备份可用性对齐 + 源码树备份不可存活，2026-09-13 事后核实）**：收尾复核发现 **4.9.18·E / 4.9.19 两处引用的 `mem_bridge.py.bak_20260913` 已不在源码树**（同期 `_audit_20260913/backup_runtime/` 亦消失）。原备份语义 = `notes` 修复前整文件快照，已**重建**：源取 WorkBuddy 会话级自动备份 `<WB_HOME>/workspace/sessions/<sid>/modify_backup/*.mem_bridge.py`（138938 B / md5 `e6b9fdbe1100`），校验其 `notes = []`（L1337）确在首个 `notes.append`（L1317）**之后** → 确为含 bug 的改动前版本。
> - **⚠️ 关键实测（含 ctime 铁证）：源码树内文件的存活状态不受本会话控制 —— 会消失，也会被外部流程重建**。① 10:45 重建到源码树的 `mem_bridge.py.bak_20260913`，10:49 复核时**不存在**，10:50 又**在**（138938 B）；② 10:34 建的 `hooks/post_tool_use_error_capture.py.bak_20260913` 同样：10:42 在 → 10:49 不在 → 10:50 又在；③ **ctime 铁证**：两文件的 `st_ctime` **同为 `10:49:33`**，而 mtime 保留原值（08:56:57 / 14:16:18，说明是 `copy2` 式复制）→ 它们在 10:49:33 被**一并重建**，而该时刻本会话未做任何创建操作；④ 对照：项目归档区副本 ctime 恒为 `10:44:36`（本会话创建时），全程稳定。旁证：`.keeper_deploy_state.json` 显示 **10:42:48 有一次部署同步**（version=4.9.19）、`keeper_daemon/daemon.py` mtime=10:41:47，均非本会话所为 → 存在**并发维护流程**在操作该 skill 目录。→ **结论：`skills/<skill>/` 源码树内的 `.bak` / `_` 前缀文件存活状态不可控**（随时可能被并发流程移除或重建），**绝不能作为可回滚源**；**备份只放源码树外**（本次存于 `<你的归档区>\keeper备份_20260913\mem_bridge.py.bak_20260913_pre_notes_fix`，全程稳定）。
> - **已排除的嫌疑**（逐项实测）：`keeper_daemon/daemon.log` 无清理记录（仅 warmup/listening）；`<WB_HOME>/hooks/` 下全部 hook **无目录清理逻辑**；`verify_claims.py` 第 6 条「发布包洁净度」**只做静态校验、不删文件**（其注释明示"钩子一跑就会重新生成…故改为检查 .skillhubignore 是否声明排除项"）；`_self_heal._backup_pair` 与 `install_hooks._backup_settings` 清理的是 `<file>.bak.<点号时间戳>` / `settings.json.bak*`，与本文件名（`.bak_` 下划线）**不匹配**。

> - **G · 归属回填（并发一侧核实后补记）**：F 记的「来源不明的外部流程」**归属已明确** —— ① `10:49:33` 两份 `.bak` 被一并重建，是并发侧会话在清理源码树非标准文件时**先把两份 `.bak` 移出**、随后发现 4.9.20 已声明它们是**有意保留的回滚基线**、再用 `shutil.copy2` **原位还原**（同秒、mtime 保留 → 与观测到的 ctime 铁证逐字吻合），**不是未知自动化流程**；② 旁证里的 `10:42:48` 部署同步（version=4.9.19）、`daemon.py` mtime `10:41:47` 亦出自该会话。**F 的纪律结论（源码树内 `.bak` 不可作唯一回滚源）依然成立**，但成因改写为「**人为清理误判**」而非「不受控外部流程」；正解 = **源码树保留（可回滚）+ `.skillhubignore` 排除入包（不外泄）**，不是二选一（见 4.9.19② 已加的 `*.bak_*`）。
> - **H · 复核补记（备份落点澄清）**：F 称「同期 `_audit_20260913/backup_runtime/` 亦消失」**不准确** —— 该目录自始就在**工作区** `<工作区>\_audit_20260913\backup_runtime\`（**不在 skill 树内**），核验时 **9 个文件齐全**（含 4.9.19② 引用的 4 个运行态备份 + 2 份 `.bak` 副本）。故 §5.6③「是否重建」**答：无需重建**，仅需修正检索范围 —— 正是本文件 §9.3 已立的纪律「**「未找到」先怀疑搜索词，再怀疑写入**」。

## 4.9.19 · 2026-09-13

> **全库审计 7 项整改（运行态外泄 / 假绿灯 / 文档契约漂移）**——对 `guard_full_audit` 报告 7 项建议的逐条落地，**含第 7 项「启动即注入生效」的根因修复**。**已并入 4.9.22 发布**。
> - **① · 修 SKILL.md 文档契约漂移（`link` 参数名全错）**：路由表原写 `link --from <id> --to <id> --relation <r>`，与真实 CLI 完全不符。实测 `--help` 与 `_graph.py` 源码校正为 `link --id <源id> --target <目标id> --rel see_also`，并补全 `--rel` 合法枚举（`see_also/superseded_by/corrected_by/consumes/test_of/composed_of/validated_by/audits`，出自 `_graph.py:_LINK_ALLOWED`）。治「照文档敲命令必报错」。
> - **② · 清理源码树 4 个运行态文件（治发布包外泄）**：`hooks/_session_inject.json`、`hooks/_auto_cap.json`、`hooks/_errcap_state.json`、`keeper_daemon/.daemon*.json` 为钩子/守护进程运行产物，**不应常驻源码树**。已先备份至 `_audit_20260913/backup_runtime/` 再硬删（沙箱 safe-delete 拦截时回退 `ctypes DeleteFileW`），源码树复检洁净。这些路径的**兜底排除**本就在 `.skillhubignore`（4.9.16 已立），本次是「源头不留」而非「只靠排除」。
> - **③ · 修守护进程默认落点（根因：运行态写进源码树）**：`keeper_daemon/daemon.py` 与 `keeper_recall_client.py` 的 `HOME` 缺省原为 `_HERE`（= 源码树）。改为 `os.environ["KEEPER_DAEMON_DIR"] or <WB_HOME>/keeper_daemon`。**部署不变性**：使用者处 `_HERE` 恰好等于新缺省，行为等价；但**开发/发布机上不再把 STATE 落进源码树**，从根上杜绝 ② 类外泄复发。
> - **④ · `HOOKS_CONFIG` 迁出源码树（治用户偏好随包分发）**：`install_hooks.py` 的钩子模式偏好文件原存技能根。新增用户配置域落点 `<WB_HOME>/hooks/hooks_config.json`（`HOOKS_CONFIG`），旧位置保留为 `LEGACY_HOOKS_CONFIG` 只读兜底；`load_mode()` 新址优先、旧址回退，`save_mode()` 自动 `makedirs`。`scripts/memory_ops/_hooks.py:_keeper_hook_mode()` 同步：`KEEPER_HOOKS_DIR` env 优先 → `<WB_HOME>/hooks/` → 旧址 → 缺省 `full`。`.skillhubignore` 追加 `keeper_daemon/daemon.log` + `hooks_config.json` 双兜底。
> - **⑤ · 路由表标注 CLI 入口（治「两入口同名但能力不同」误用）**：SKILL.md 路由表 12 行逐条标注入口归属（`仅 mem_bridge` / `两入口同名`），并在 💡 行前新增「🧭 CLI 入口」说明块——`memory_ops`（`scripts/memory_ops.py <cmd>`）与 `mem_bridge`（`mem_bridge.py <cmd>`）**子命令集不等价**，此前读者无从判断该敲哪个。
> - **⑥ · 守护进程陈旧 STATE 自失效（客户端侧）**：`keeper_recall_client._reuse_state()` 原在 `_ping_info` 失败（进程已死）时**仅 `return None`**，把死 STATE 文件留在磁盘（下轮仍尝试、拖慢并刷噪音）。新增 `_try_remove()`（`os.remove` → `ctypes DeleteFileW` 兜底）主动清理陈旧 STATE。
> - **⑦ · 修「启动即注入」形同虚设（真 bug，本机实测复现 + 端到端验证）★核心**：SessionStart 钩子**已注册、已过门控、确实在跑**，却注入为空——根因是 `recall` 缺省**隔离 `auto_sourced=True` 的记忆**（被动捕获、未经确认），而本机真实库 `<你的记忆库目录>` 25 条**全部**是 auto_sourced → 召回恒为 0，注入自然为空。修复：`hooks/keeper_hook_common.py` 新增 `inject_include_auto()`，**缺省 `True`**（优先级：env `KEEPER_INJECT_INCLUDE_AUTO` > 配置块 `inject_include_auto` > `True`）；`session_start_keeper_inject.py` 与 `user_prompt_recall.py` 的召回调用均改传 `include_auto=C.inject_include_auto()`。**端到端实证**：审计日志由 `SessionStart | empty | no entries` → `SessionStart | inject | entries=5`；真实运行注入 **1701 字符**；`UserPromptSubmit` 注入 **511 字符**。
> - **⑧ · 回归测试**：新增 `scripts/tests/test_inject_include_auto.py`（8 用例：优先级门控 4 / 钩子静态契约 2 / SessionStart 端到端注入非空 1 / 客户端运行目录不在源码树 1）；改造 `test_runtime_state_gate.py`（`test_daemon_state_default_falls_back_to_tree` → `test_daemon_state_default_goes_to_user_runtime_dir`，断言缺省落点 = `<WB_HOME>/keeper_daemon`）；`test_daemon_root_scope.py` 增补 `test_dead_state_is_cleaned_up` / `test_live_foreign_root_state_not_deleted`。
> - **⑨ · 修 ⑥ 引入的回归：客户端自毁 daemon 会合点（★ 真 bug，本机实测导致用户提问被拦）**：
>   ⑥ 把「ping 失败」直接当成「进程已死」就删 STATE。但 daemon 是**先 `listening`、后 `warmup`**
>   （实测 warmup 0.8~1.0s，见 `daemon.log` 两行），warmup 窗口内端口已听、handler 阻塞在模型
>   加载上 → **0.5s 的 ping 必然超时**。于是客户端**亲手删掉自己刚 spawn 的 daemon 的 STATE**；
>   客户端删完**不补写**（daemon 侧会补写，故 daemon 侧无此害）→ **不自愈**：之后每轮轮询都读到
>   「文件不存在」→ 白等满 `DAEMON_START_TIMEOUT`(30s) → 钩子超 30s 被 WorkBuddy 掐死。**实测**：
>   `UserPromptSubmit` 31.1s、`SessionStart` 60.7s，**用户的提问直接被拦掉**（`hook timed out`）。
>   日志实证：每次新起一个 daemon、各绑新端口（`:50970`/`:61031`/`:61052` …）。
>   **正确判据**：ping 失败 ≠ 进程已死 —— 必须回落到 STATE 里记的 `pid` 是否真存活
>   （`daemon.py` 写 STATE 时本就带 `pid`）。修法：新增 `_pid_alive()`（Windows 走
>   `OpenProcess`+`GetExitCodeProcess` 判 `STILL_ACTIVE`；POSIX 走 `os.kill(pid,0)`），
>   `_reuse_state` 仅在 **PID 确已消失** 时才清理；`daemon._already_running` 同步改成同一把尺
>   （防两侧语义漂移）。另两处配套：`_reuse_state` 的 ping 超时 0.5s → **1.5s**（给 warmup 余量，
>   健康 daemon 仍毫秒级返回）；`DAEMON_START_TIMEOUT` 30.0 → **12.0**（原值与钩子
>   `timeout: 30` **完全相等 = 零余量**，任何冷启动必踩线；健康路径实测仅需 ~1.5s）。
>   **修后实测**：`SessionStart` 冷启动 **1.6s / 注入 1666 字符**、`UserPromptSubmit`
>   **4.2s / 143 字符**、热态 **5.0s** —— 全部落在 30s 预算内，阻塞解除；STATE 能持久留存。
> - **⑩ · 回归测试**：`test_daemon_root_scope.py` 新增 `BusyDaemonStateGuardTest`（5 用例）：
>   ①★ 端口不可达但 **pid 存活** → STATE 必须保留（**这条挂了就说明自毁会合点复发**）；
>   ② pid 确已消失 → 才清理；③ `_pid_alive` 自身（本进程真/已退出子进程假/None 假/非法串假）；
>   ④ `DAEMON_START_TIMEOUT` 必须 < 钩子 30s 且余量 ≥10s（**预算余量门禁**）；
>   ⑤ 两侧都定义 `_pid_alive` 且 `daemon._already_running` 确实调用它（AST 静态校验）。
> - 备份：`_audit_20260913/backup_runtime/`（4 个运行态文件）、`mem_bridge.py.bak_20260913`（改动前整文件快照）。 ⚠️ 该备份已不在源码树（源码树内 `.bak` 无法存活，见 4.9.20·F 实测），**已重建至源码树外**（`<你的归档区>\keeper备份_20260913\`，md5 `e6b9fdbe1100`）。

## 4.9.18 · 2026-09-13

> **同族缺陷排查（fail-silent / 假绿灯 / 值与真实态脱节）**——user 要求「继续查类似问题」后的第二轮。**已并入 4.9.22 发布**。
> - **A · 修 `neural_recall_active()` 读到假值（真 bug，本机实测复现）**：钩子门控的「语义后端是否活跃」判定**只读 `store/config.json` 一处**，而 memory_ops 认「env > store > root > 默认」。当 `embed_backend` 只配在 `<root>/config.json`（兼容位）时 → **恒返回 False**。本机实测：`root` 配 `fastembed`、真实后端 `fastembed`，函数却返回 `False`（钩子 score 门控 vs 词法门控与真实后端不一致）。修复：新增 `_keeper_cfg_block()`（store 优先 + root 兜底）统一配置源，`recall_mode()`/`inject_enabled()`/`neural_recall_active()` 三者共用；`neural_recall_active()` 优先级改为 **env `AI_MEM_EMBED_BACKEND` > 配置块 > 默认 fastembed**，白名单补齐真实取值（`auto`/`fastembed`/`neural`/`sentence_transformers`/`online`），修后本机实测由 `False` → **`True`**。
> - **B · 修 `doctor` 硬编码 `neural_active=False`（真 bug）**：`doctor()` 的 contract 摘要原为**常量** `False`，使 `contract.neural_recall_active` 与真实后端永久脱节（恒量冒充实测）。改为复用上方 `_doctor_embed_backend` 的权威探测：真实后端非 `lexical` 即 `True`。实证：`embed_backend=lexical → false`、`=online → true`。
> - **C · 三处「静默吞」补告警（同族：静默数据完整性/可见性退化）**：① `_persistence._db_checkpoint_truncate` 备份前 WAL checkpoint 失败**静默 pass**（会让单文件备份缺席最新数据、restore 出幽灵记忆）→ 改为 stderr 告警；② `_persistence._load_index_json_only` index.json 损坏时**静默返回空** → 告警；③ `_config.user_store_override` `~/.keeper/store_root` 存在却读不了时**静默回退默认库**（用户「记忆消失」）→ 告警。
> - **D · 回归测试**：新增 `scripts/tests/test_neural_recall_active.py`（7 用例：root 兜底 / store 优先 / env 最高优先 / 合并语义 / 显式 lexical），全用 `online`/`lexical` 取值 → 零第三方依赖、零模型加载、确定性。
> - **E · 修 `distill` 传白名单外 `--subdomain` / 非法 `--status` 时直接崩溃（真 bug，本机实测复现）**：`distill_to_keeper` 中 `notes = []` 的初始化位置在 **G1(subdomain) 与 G4(status) 两个校验分支之后**（原 1355 行 vs 分支在 1335/1350 行）。于是只要传入不在 `INVESTMENT_SUBDOMAINS` 白名单里的 subdomain（实测用「数据修复」「文件归档」），或非法 status，就会 `notes.append(...)` → `UnboundLocalError: cannot access local variable 'notes' where it is not associated with a value`，把「优雅降级并提示允许值」的设计意图变成硬崩。修复：把 `notes = []` 提前到 `base_tags = list(tags or [])` 之后（所有使用点之前），删除原位置的重复初始化。**实证**：修复前传 `--subdomain 文件归档` → 崩溃；修复后 → `deposited=1 | G1 忽略未知 subdomain='文件归档'（允许：risk_control,position_mgmt,industry_analysis,stock_analysis,data_pipeline,backtest,strategy,execution）`。
> - 备份：`mem_bridge.py.bak_20260913`（改动前整文件快照）。 ⚠️ 该备份已不在源码树（源码树内 `.bak` 无法存活，见 4.9.20·F 实测），**已重建至源码树外**（`<你的归档区>\keeper备份_20260913\`，md5 `e6b9fdbe1100`）。

## 4.9.17 · 2026-09-13

> **召回可观测性运行时闭环**（治「降级了但没人知道」）+ 修两处真实缺陷。**已并入 4.9.22 发布**。
> - **A · `recall` 随带 meta（可观测性闭环）**：`recall()` 新增 `with_meta=False` 参数——**缺省返回形状不变**（仍为裸 list，旧调用方零回归）；`recall --query --with-meta` 返回 `{"results":[...],"meta":{backend, configured_backend, fell_back_to_lexical, count, empty_hint}}`。**空结果 + 后端降级**时 `empty_hint` 直接给出可执行修复命令（`pip install fastembed` / 设 `AI_MEM_EMBED_BACKEND=online` / `doctor --fix`）。`--id` 路径仅在 `--with-meta` 时附 `backend_state`（`loaded`/`degraded`/`unprobed`）——**诚实标注进程内真实态，未 probe 时标 `unprobed`，绝不用配置值冒充 live 后端**（避免强制 probe 触发 pip 自动安装的 420s 卡死风险）。`_can_cache` 排除 `with_meta`，防缓存串形。
> - **B · `mem_bridge` 消费 meta（B1 红线运行时落地）**：`inject_active` 的 recall 子命令加 `--with-meta`，捕获 `meta.fell_back_to_lexical`；降级时**同时**向 stderr 告警 + 在注入上下文追加「⚠️ 已降级」标注，健康时零输出（不误报）。至此 4.5.61 立的 **🔴 B1 红线**（「静默质量退化必须显式可见」）在**运行时**闭环——AI 常规 inject/retrieve 即知降级，**不必手动跑 doctor**。
> - **C · 修 `doctor`/`report()` 假绿灯（真 bug）**：`report()` 原仅凭 `HF_ENDPOINT` 含 `hf-mirror` 子串就显示「已走国内镜像」（绿），**不校验实际后端是否降级**——裸域名命中 + 实际降级 = 假绿灯（验收显示绿灯、实则已降级）。新增独立 `fell_back_to_lexical` 判定：配置神经/auto 却落到 lexical 时，**即便同时显示「已走镜像」也一并亮降级告警**；`embed` 字典补 `configured_backend` / `fell_back_to_lexical`。
> - **D · 文档（降低「重要边界藏深文档」门槛）**：SKILL.md 新手雷区第 5 条 / 隐藏条件① / 体检第 4 项 / §九 B1 红线四处同步说明「4.9.17 起降级已自动回显」，把原先埋在深层的「静默降级」边界前置到决策入口。
> - **E · 回归测试**：新增 `scripts/tests/test_recall_with_meta.py`（4 用例：缺省无 meta 后向兼容 / query meta 字段 / 空结果 empty_hint / `--id` 诚实 state）。

## 4.9.16 · 2026-09-12

> 文档易用性根治（仅文档层，零行为变更；发布门禁全绿）：
> - **A · 新手 5 大雷区合并框**：SKILL.md「先读这3条」下方新增「🔰 新手 5 大雷区」指针框，把"默认就在自动记 / 反模式清单在哪 / **开加密前必备恢复码（不可逆）** / 命令真实返回在 TUTORIAL / 召回变差先跑 doctor"集中到决策入口，解决"重要限制藏在深层文档"的可发现性问题。
> - **B · 开加密强制门禁（治高危数据丢失）**：对话路由契约新增第 4 条——"开加密"列为**门禁动作**，AI 必须 ①完整复述 🔴 A1 红线 ②收到用户"我已知风险，继续"才动手 ③先跑 `recovery-code --write` 并确认库外 keyfile 落盘后才设 `AI_MEM_ENCRYPTION_KEY`。能力映射表（§4.1）同步标注加密为门禁动作，**修复了"§4.1 把开加密列为普通触发"与契约硬门的旧矛盾**。
> - **C · 命令真实返回样例**：`references/COMMANDS.md` 末尾新增「常见命令真实返回样例」节，贴 `deposit`/`recall`/`audit`/`doctor` 的**实跑 JSON**（脱敏），补"单命令完整输入输出示例难找"的缺口。
> - **D · 反模式总索引**：文末「📌 反模式清单」下方加指针"完整 14 个避坑 → `QA.md §四`"，提升"不该怎么做"完整清单的可发现性。
> - 发布门禁前置修复：QA.md 章节锚点修正（指向现存 4.3 可选能力·性能·高级功能 合并总表），消除文档断链，`test_all_skill_md_section_refs_exist` 通过；251 测试 0 失败 0 错误，3 道发版闸门全绿。
> - **发布包洁净度补强（治真机信息泄露）**：补回缺失的 `.skillhubignore`，声明排除 `hooks/_*.json`、`keeper_daemon/.daemon*.json`、`_retired_*`、`memories/.write_lock` 等运行态产物，消除 `test_pack_ignore_gate.test_real_skillignore_passes` 与 `verify_claims.pack_excludes_runtime_state` 两道红灯（此前缺该文件会让上一台机器的端口/pid/token 随包发给使用者）。门禁至此三道全绿（cookbook/tests/claims→PASS，结论「可发版」）。
> - **全量文档审计（链接/版本/命令三层）**：脚本扫描全部 26 个 .md，修正 1 处断锚——`references/QA.md` 表格链接 `#七会话钩子` 指向的标题原为 `## 七、会话钩子（装完 skill 即生效，无需手跑脚本）`（带后缀导致 slug 不匹配），已将标题精简为 `## 七、会话钩子`（后缀移入正文 note），`#七会话钩子` 现可正确跳转。版本号全库一致（当前 4.9.16，无 4.9.15/4.9.17 残留）。逐一核对文档命令与代码 `OP_NAMES`（`memory_ops/__init__.py`）：`audit`/`cluster`/`converse`/`doctor` 等均为真实子命令，`error_hook` 按文档明确为独立脚本（非子命令），命令面与代码零幽灵。
> - **补齐 `memory_ops.py` 转发垫片（愈合文档契约）**：文档多处（含 `COMMANDS.md` 第 3 行与 changelog 既定契约）声明 CLI 入口为 `memory_ops.py` 转发垫片、实际逻辑在 `scripts/memory_ops/__init__.py`，但根目录长期缺失该文件，导致 `TUTORIAL.md` 等处的 `python memory_ops.py doctor` 实跑报"找不到文件"。新增根 `memory_ops.py`（3 行 `runpy.run_path` 转发），自测 `python memory_ops.py commands` 正常返回命令清单、`memory_ops.py <op>` 与 `python scripts/memory_ops/__init__.py <op>` 等价；所有 `memory_ops.py` 引用（35 处）自此成立。

## 4.9.15 · 2026-09-12

> **发布门禁修复 + 全量复跑**（零行为变更，仅文档一致性 + 发布元数据）。
> - `references/QA.md` 章节锚点修正（指向现存的「4.3 可选能力·性能·高级功能」合并总表），消除文档断链，`test_all_skill_md_section_refs_exist` 通过。
> - 发布前全量门禁复跑：251 测试 0 失败 0 错误（跳过 2 个需 DB 用例），3 道发版闸门全绿。
> - ⚠️ **本条目为事后补记（2026-09-13）**：该版本**确实发布于 2026-09-12 14:55**，但当时本地 `CHANGELOG.md` 漏掉了它的标题、内容被并入了随后的 4.9.16 条目，于是形成「平台有、日志无」。正文原文取自平台版本元数据（`GET /api/v1/skills/<slug>/versions` 的 `changelog` 字段）。

## 4.9.14 · 2026-09-12

> 发布前文档维护（仅文档层，零行为变更）：
> - CHANGELOG 轮转：主文件仅留最近 20 版（4.9.13 起）；更早版本归档至 `references/_design/changelog_archive.md`。
> - 脱敏：全库真实路径占位符化（`<你的记忆库目录>` 替代原绝对路径），消除 SkillHub 发布前的真机路径泄露。
> - 发布前安全检查通过：无邮箱 / token / 凭证真实值 / 内部信息泄露；`displayName` 驼峰规范。
> - **钩子 bug 修复（行为变更）**：`post_tool_use_error_capture.py` 原逻辑把 Bash 返回的整个 JSON 结构 `json.dumps` 压成单行、`splitlines` 取末行当 `summary`，导致把 `{"exitCode":...}` 结构当经验灌库（已污染 11 条）。改为从 `stderr`/`stdout` 真实文本提取错误行，`summary` 形如 `cmd -> 真实错误末行`。已 monkeypatch 测试验证。

## 4.9.13 · 2026-09-11

本版主线：**让测试不再把运行态文件写回源码树**——附带几处同源小修。
起因：上一版加的洁净度断言只能查"声明文件有没有写"，不敢查"源码树里到底有没有"。
因为钩子一跑就会重新生成那些文件，而门禁是先跑测试、再跑断言，扫了必然假红。
**要敢开这条断言，得先把污染源堵掉。**

顺着这条线还挖出一个**会静默读错库**的真 bug（第八节），并补掉一处门禁基线缺口（第九节）。

### 〇 · 文档维护（2026-09-12，无行为变更）
> 仅整理文档，不改任何代码 / 配置语义；版本号保持 4.9.13。回滚点已存本地整库备份（155 文件，含原始 CHANGELOG）。

- **`references/_design/` 去重**（与根 `references/` 的重复文件）：删 `_design/taxonomy_wizard.md`（与根版 md5 完全一致）、`_design/TYPE_TAXONOMY.md` 与 `_design/FORMAT_ANALYSIS.md`（根版为权威源，被 SKILL.md 引用 3/5 次，_design 版为 Phase1 陈旧副本）、`_design/回收与软删治理设计方案.md`（与 `recycle_softdelete_governance.md` 同内容两文件名，统一保留 ASCII 命名版）。`_design/` 现仅含 `DEV_TESTING.md` / `recycle_softdelete_governance.md` / `压测方法论.md`（开发者内部稿，普通用户无需看）。
- **`SKILL.md` 去重瘦身**：632 → 445 行（↓30%）。3 套文档导航表并 1 套；`4.3/4.4/4.5/`「高级功能」4 张重叠表并为一节「4.3 可选能力·性能·高级功能」；加密兜底 / reflect不删 / 语义降级 / ANN / IMA脱敏 5 大主题各只留 §九红线真源 + 一处指针，去掉多节重复 prose。**全部 env 名 / 命令名 / 13 配置键 / 红线语义零改动**（已脚本核对）。
- 背景：CHANGELOG 4.9.x 曾号称做过同类 `_design` 清理但发生回归（副本重现），本次用哈希比对确认根版为权威源后再删，避免再次回归。

### 一 · 污染源：状态目录取自文件自身位置，环境隔离救不了

钩子状态文件（审计日志 / 注入去重 / 异步落库临时件）的落点，由钩子公共模块里的
目录常量决定，而它取自模块自身路径——**与 HOME / USERPROFILE 无关**。于是"把 HOME
设到临时目录"这类隔离对它完全无效；而测试确实会真的 spawn 源码树里的钩子脚本
（`test_inject_gate` 就跑 `session_start_keeper_inject.py`）→ 运行态文件必然写回源码树。

这不是洁癖问题：守护进程状态文件里带着**本机端口与 daemon token**，它曾因同类路径
躺进待发布清单。

修法：该目录常量支持 env `KEEPER_HOOKS_DIR` 覆盖（与 `_hooks.py` 的部署目录开关
**同语义、同一把开关**），未设时行为与旧版逐字一致。

🔴 **一个必须写进注释的边界**：`_DAEMON_HOME`（`sys.path` 锚点）**不跟随**该 env。
跟随会把一个不存在的路径插进 `sys.path`，直接打断召回客户端的 import。
即"**状态目录可重定向，代码目录不可**"——已用子进程端到端断言锁住这条边界。

`hooks/_async_deposit.py` 的 `failed/` 落点属同一类，共用该开关。

**daemon 侧是同一类病（同轮发现）**：`keeper_daemon/daemon.py` 与 `keeper_recall_client.py`
里的 `HOME = dirname(__file__)` 同时充当"代码目录"与"状态落点"，于是守护进程的
`.daemon.json`（**含本机端口与 token**）与 `daemon.log` 一样会写回源码树。修法同样是
把两者拆开：`HOME`（状态落点）可被 env `KEEPER_DAEMON_DIR` 重定向，`DAEMON`（代码
定位）锚 `_HERE`——隔离开启后仍要能找到 `daemon.py`。

> ⚠️ 顺带修一处"一重定向就会踩"的坑：daemon 写 STATE 前**不建目录**。隔离目录不存在
> 时 STATE 落不了盘 → 客户端轮询到 30s 超时 → 表现为注入失败。实测对照：目录不存在
> 时 `test_inject_gate` 跑 **124.8s 且 2 个用例失败**；目录存在时 **8.8s 全过**。

### 二 · 门禁层一处收口

`run_gate.py` 把 hooks / daemon 两个落点的 env 一并写进安全基线（做成**模块级常量**
而非 `main()` 里临时算——否则换个入口跑测试就又开始污染），并把越权检测收窄到
嵌入后端的那个键（隔离键允许模块临时改写，不该计入告警）。

### 三 · 新增断言 `no_runtime_state_in_tree`（第 24 条）

既然污染源堵住了，"实扫源码树"就从 flaky 变成**确定可判**。本条即那次修复的可验证
判据：扫 6 个已知运行态产物，命中即 FAIL 并给出搬离提示。

> 断言上线后**第一次运行就抓到真货**：注入去重状态与守护进程状态——正是上述那一类。

### 四 · doctor 调度自检：降噪 + 可诊断

本机 `schtasks.exe` 被安全中心程序黑名单拦（不可绕过）。改前每次 `doctor` 都白撞一次，
且提示写死「无法查询」——分不清"没这个程序"还是"有但被拦"。

- 探测结果缓存 24h（落部署目录，**不随包分发**；读写在任何异常下一律 fail-open）；
- 提示带成因分类 + **原始异常原文**，并给出解除路径；
- 🔴 顺带修一处真 bug：`/NH`（不出表头）与 `splitlines()[1:]`（跳过首行）**互相矛盾**
  → 会**漏掉第一条** keeper 任务。改为按名过滤表头。

实测（本机）：首次探测返回 `PermissionError: [WinError 5] 拒绝访问`；第二次 `cached: true`，
不再触发拦截。

### 五 · 调度自检的两处补强

上面第四节加的 24h 缓存本身是对的（**只对负向结果短路**，可用时每次仍实查任务列表，
所以不会掩盖新装的调度任务）。但它带来一个副作用：**改了系统限制却看不到变化**——
缓存里存着"被拦"的旧结论，解除限制后跑 `doctor` 看到的还是它，只会以为修改没生效。

- **加 `--no-cache`**（`doctor` CLI 与 MCP `doctor` 工具同步支持）：跳过缓存直连探测，
  给"我刚改了限制、要立刻看真结果"留一条路；
- **缓存命中自曝年龄 + 逃生口**：提示末尾追加"此为约 N 分钟前的探测缓存；若已改过
  相关限制，加 `--no-cache` 或删除 `<缓存文件>` 可强制重探"。🔴 该后缀**只拼在展示层、
  绝不写回缓存**——否则每读一次尾巴就再滚一圈（已加断言锁住）。

### 六 · 一处措辞诚实性修正

调度探测失败的提示原先把**单机经验当成了通用结论**：只要拿到调用失败，就直接断言
"本机安全中心的程序黑名单会拦它"，并只给这一条解除路径。

但同一个错误码（`WinError 5`）至少有四类来源：程序黑名单 / 权限不足 / 组策略与
企业管控（AppLocker、WDAC）/ 组件损坏或被替换。本机确实是第 ① 条，**换一台机器却可能
是第 ②~④ 条**——照原提示排查，就会去改一个跟自己无关的设置，白折腾还可能改坏环境。

改为按常见度列候选成因，并补一句"keeper 的定时维护走 WorkBuddy 自动化、不依赖
`schtasks`，本项不可用不影响功能"，避免使用者为一条不影响功能的告警耗时间。

### 七 · 回归测试：本版新增三个测试文件（全库实测 **251** 用例）

- `test_runtime_state_gate.py`（新，**14** 用例）：env 生效面 / 默认回退 / **锚点不跟随** /
  门禁基线注入点 / daemon 侧状态可重定向而代码定位固定 / 断言正反双向（含"真源码文件
  不得被误判"、按库命名的 STATE 也必须被逮住）；
- `test_sched_probe.py`（新，**16** 用例；本版由 8 补到 16）：缓存往返 / 过期强制重探 /
  损坏 fail-open / 写失败被吞 / 成因**按候选列举**（不得唯一断言）/ 原始错误必须透出 /
  `--no-cache` 绕过缓存且**连读都不读** / 缓存命中自曝年龄与逃生口 /
  年龄提示不得写回缓存 / CLI help 里必须能看到该参数；
- `test_daemon_root_scope.py`（新，**11** 用例）：两侧指纹算法一致（**直接跑两份源码里的
  真实实现比对**，而不是各抄一份自证）/ 同一目录的书写别名归一 / 不同库不同状态文件名 /
  复用判据正反双向（同库复用、他库拒用、旧版不回 root 拒用、死端口拒用、坏文件不抛异常）/
  库按**当次** env 现算；
- `test_daemon_residual_cleanup.py`（2 → **9** 用例）：除原残留清理外，补"复用前核对库归属"
  与"升级回收"两组，每条负向都配**正向对照**（同库必须复用——否则负向断言可能恒真）。

---

### 八 · 🔴 daemon 复用不校验记忆库（本版挖出的真 bug）

起因：把本版放进**发布器的干净副本**里跑门禁，必红——`test_inject_gate` 卡 128s 后拿到空注入；
同一套代码在源码树里却 PASS。追下去，问题不在测试：

`_ensure_daemon()` 与守护进程的 `_already_running()` 复用已有实例时**只探活，不核对它服务
的是哪个库**。于是"已有 daemon 在服务库 A"时，对库 B 的请求会直接复用同一个 →
召回与写入全打到库 A。双库探针实测：两次请求拿到**同一个 port**，而状态文件里的 `root` 仍是 A。

> 源码树为什么 PASS：沙箱里残留的 daemon 恰好不冲突——**纯属运气**。这也解释了长期存在的
> 门禁偶发失败：不是测试不稳，是踩没踩到那个残留实例。

修法两条**必须一起上**（只做一条都不够）：

- **状态文件按库分隔**：名字带库指纹（`.daemon-<12 位指纹>.json`），每个库各持一份。
  只加"校验 root"不行——两个库的客户端会反复覆盖同一份文件，谁也认不下对方，于是互相拒绝、
  反复重启（抖动），总有一方读不到自己的库；
- **复用前向活进程核对**：`/ping` 增报 `root`，客户端比对**活进程自述**而非状态文件里的
  纸面记录（端口被别人占用时，纸面记录恰恰是错的那方）；旧版不回 `root` → **fail-closed 拒用**；
- 顺带收掉一处同源隐患：库按**当次** env 现算。若状态文件走 import 期快照、子进程走 env
  现值，两侧指纹就打架 → 客户端永远认不出自己刚起的 daemon，一路轮询到超时再静默跳过注入。

**升级收尾**：旧版那个"全库共用一个状态文件"的 daemon 此后无人复用，却因默认永不离线一直
占着端口与内存（用户会在任务管理器里看到两个 keeper 进程）→ 启动时一次性回收，且**仅当它
自报的 root 与本库一致**才请它退出；他库或无法确认则原样留着——不替别的库做决定。

### 九 · 门禁与用例的环境前提（本版踩到）

本机 shell 里带着 `AI_MEM_ENCRYPTION_KEY` → 所有直接读磁盘断言"明文"的用例（写入门禁、
版本快照）**整片翻红**：磁盘上变成 `gAAAAA…` 密文，而代码一个字没改（实测 7 个失败）。

修法刻意**不放在门禁基线的统一钉住**上——试过，代价是静默的：门禁基线若统一把加密钉成
"无 key"，那个"复制真实记忆库做同步验证"的用例（真库是加密的）会读成空库而**整类跳过**，
用例数从 **251 掉到 248 却照样报 PASS**。**绿得不明不白比红灯更危险。** 故：

- 加密前提由**各用例自己声明**（本库既有惯例，已有 3 个模块这么做）：这两个模块在
  `import memory_ops` **之前**注明并钉住"无 key"，并写清为什么；
- 门禁只做一件相关的事——**把跳过项说出来**：汇总行加入"跳过 N"，并在有跳过时列出用例名
  与提醒。跳过不判 FAIL，但不许它悄悄吞掉覆盖。

> 一句话：这一版没有新能力——它让"测试跑完不留痕"从约定变成机制（一~三），
> 让"改完限制立刻看结果"从等 24 小时变成一条命令（四~六），
> 顺手挖出并修掉一个**会静默读错库**的真 bug（八）。

---

## 4.9.12 · 2026-09-11

本版处理"**文档说的和代码做的不一致**"这一类问题——它们不报错、不影响单机跑通，
却让人**按文档操作反而走错路**。起因是一次外部反馈："自动记忆和手动模式怎么选，还得猜。"
顺线查下去，问题不在"没说清"，而在**同一件事有多处互相打架的说法**。

### 一、收敛三组「文档 ↔ 代码」矛盾
| 矛盾 | 曾经的多种说法 | 代码真相 |
|---|---|---|
| 自动沉淀默认开不开 | LIMITS §7「默认**不自动运行**，须说『记一下』」 ↔ SKILL §4.2「✅开（20 轮）」 | `auto_capture=True` |
| 钩子要不要手动开 | SKILL / CAPABILITY_MAP「🔧需先开」 ↔ ENABLEMENT / INSTALL / TUTORIAL「✅自动注册」 | `KEEPER_AUTO_INSTALL_HOOKS` 默认开 |
| 库规模表现 | LIMITS §12「>10k 仍可用」 ↔ 自家压测「1w 冷召回 197.6s」 | 实测超线性 |

改法：口径一律收口到代码真值。LIMITS §7 首句拆成**两件事**（捕获默认开 / 注入默认关）；
钩子统一为「安装后**首次跑任意命令**自动注册 → **重启 WorkBuddy 生效**，`keeper_setup` 为显式可靠路径」；
"自动记忆（钩子）"从「🔧需先开」桶移入「✅默认就有」桶。

### 二、库规模边界提到主入口
SKILL.md 新增 §4.6 规模边界表（含"≈1 万条已是**分钟级**"的实测结论）；**精确数字仍只在
LIMITS §12 一处**（数字单一来源，避免再次双源漂移）。LIMITS §12 删掉"仍可用"的乐观措辞，
补入 `1k≈7.4s / 1w≈197.6s` 实测与复现方法。

### 三、红线按危害重排为两组
原「五条不可破红线」→ 按**危害类型**分两组：
- **A · 数据类**（不可逆 / 会丢会泄）：A1 开加密先备兜底、A2 绝不批量硬删、A3 删必须 `--yes`、A4 IMA 强制脱敏
- **B · 质量类**（数据没丢，但你会被误导）：B1 **静默质量退化必须显式可见**（原只标 🟡，危害被低估）、B2 重要记忆分类强制

### 四、补三个对话交互缺口
- **对话路由契约**（SKILL §七）：模糊动词（清理 / 清空 / 删掉）**必须消歧**；破坏性操作先 `--dry-run`
  摆出影响面再确认；意图不在能力表内**先回问**。附"最容易踩的四个"消歧对照表。
- **记忆可见性**：「你最近自动记了什么？给我看看」成为一等入口（`working` / `confirm` / `list_quarantine`）。
- **卸载 / 退出 / 迁移**：COOKBOOK 新增 §10，讲清钩子 / 守护 / 调度 / skill 各自怎么摘、怎么验证。

### 五、更新与重装后的「部署同步」（本版最重要）
钩子副本（`~/.workbuddy/hooks/`）、守护副本（`keeper_daemon/`）、调度项都**独立于技能目录**，
而旧逻辑只在"settings.json 里还没注册钩子"时才安装 → **技能升级后副本永远停在旧版，且完全静默**。
这正是"更新完感觉没生效"的根因。现改为：
- 部署时写「部署指纹」（版本 + 各文件 sha256，含 helper）；
- 每次启动自检：版本或哈希不符 → **后台自动刷新**（`CREATE_NO_WINDOW`，绝不弹窗），并提示"重启 WorkBuddy 生效"；
- 同一版本 6 小时内只尝试一次（防"刷新失败 → 每条命令都重试"的静默风暴）；
- `doctor` 新增 `deployment` 字段，直接回答"我更新了 keeper，到底生效没有"；
- `install_hooks.py` 备份去重（内容相同不再新增 `settings.json.bak_*`）；
- `INSTALL.md` 新增「更新后：部署同步与引导」，含首次下载（新装）该做什么。

### 六、修一个静默很久的真 bug + 两处加固
- 🔴 `_keeper_hook_mode()` 按 `<skill>/scripts/hooks_config.json` 探测，而真实文件在**技能根**
  → 恒返回兜底 `full`，用户持久化的 `silent` / `off` **被静默忽略**（连 `off` 的短路保护也失效）。
  实测：配置写 `silent`，函数返回 `full`。现改为逐级上溯定位技能根。
- `_ensure_hooks` 派发安装器用的是 `CREATE_NEW_PROCESS_GROUP`——**同样不静默**，已改 `CREATE_NO_WINDOW`。
- `doctor` 的 `hooks` 检查此前 `except` 不记根因，与 `scheduler` 统一为带 `detail`。

### 七、给上面这些加防复发闸门（均在发版门禁链路内）
- `config_doc_matches_code` **升级为值级比对**（旧版只比键名 → 文档把 `auto_capture` 写成 `false` 也放行）；
- `default_claims_consistent`（新）：把"代码默认值 → 禁止的相反说法"成对固化，
  且**代码默认值一旦翻转，禁令自动失效**（闸门不会比代码更旧）；
- 回归测试 +28：默认值声明 +5、钩子模式/部署漂移/首次注册 +10、发布包洁净度 +7、弹窗闸门 +6。

### 八、发布包洁净度：3 个运行态/遗留文件差点被打包
发版前全量体检时，用发布器**自己的排除语义**跑了一遍真实打包清单（`collect_files`，不是靠眼看），
发现待发文件里躺着三个不该在的东西：

| 文件 | 问题 |
|---|---|
| `keeper_daemon/.daemon.json` | 守护进程**运行态**：带着上一台机器的端口、pid，以及本机 daemon token |
| `hooks/_session_inject.json` | 注入钩子**运行态**：测试跑出来的"已注入 id"记录 |
| `hooks/_retired_2026-08-11_bash_error_capture.py` | 已退休件（职责早由 `post_tool_use_error_capture.py` 承担） |

根因两条，都修了：
- **发布器只按后缀排除**（`.log/.lock/.pid/.jsonl`…），**不覆盖 `.json` 状态文件**；
  而测试在源码树内跑钩子/守护进程时会把状态写回源码目录。→ 在**技能级 `.skillhubignore`**
  显式声明排除（可审计、可移植，正是发布器留给每个技能的口子）。
- `install_hooks.py` 的 `DAEMON_FILES` **把 `.daemon.json` 当源码复制** → 会把陈旧端口/pid
  带到新部署目录。已从表中移除（该文件本就自建、自清、自愈）。

清理一律用**同卷 `rename` 搬入 `_retired_tmp_<日期>/`**（可逆、不触发删除护栏），
并把 `_retired_*` 一并纳入排除声明，避免"搬离活跃路径但仍在磁盘"的文件再次混入。

### 九、给发布包洁净度加闸门（防复发）
- `pack_excludes_runtime_state`（新）：**不扫**"源码树里有没有状态文件"——钩子一跑就重生，
  而门禁是"先跑 tests、后跑 claims"，扫了必然 flaky 红。改扫**`.skillhubignore` 是否声明了
  排除项、且语义真能命中**；并反向校验**真源码没被误排除**（防"排除写太宽 → 漏发"）。
  匹配语义与发布器 `_glob_to_regex` / `_is_ignored` 对齐。
- 回归测试 +6：漏一行 / 行被注释掉 / 缺文件 / 排除过宽 → 必 FAIL；
  真实声明与**通配等价写法** → 必 PASS（防误杀）。
- 🔴 **这条闸门第一版把发版自己拦住了**（真实发生）：发布器的上传载荷**必须**排除 `.skillhubignore`
  （SkillHub 拒收该文件类型），而它恰恰是在「干净副本」里跑本技能自带的门禁 →
  副本里永远看不到这个文件 → 新断言恒红 → 发版被自己拦下。教训是：
  **闸门要在"它真正运行的那个环境"里验证，而不是只在源码树里验证。**
  现改为**两态**：干净副本（既无 `.skillhubignore` 也无 `_meta.json`）→ **显式说明后放行**；
  源码目录（有 `_meta.json`）缺该文件 → **必须 FAIL**。
  判别依据是"两份同属不随包分发的发布元数据"。两态各有回归测试锁死（防"放行太宽"退化成静默跳过）。
- 顺带一提：这条闸门装上后，**第一次跑就把自己抓了**——我在注释里反引号点名了发布器那边的
  函数名，而它们不在本技能代码里，被既有的 `no_dead_symbol_refs` 判成死引用并拦住发版。
  已改成不带反引号的措辞。闸门互相咬合、不认人情，这正是想要的。

### 十、发版前全量体检又逮到两个「修了一处漏一处」的静默 bug
两条都是本轮体检（不是设计阶段）新发现的，且在发版前被门禁拦住：

1. 🔴 **「装完首次跑命令自动注册钩子」这条路径从未生效**。
   `_ensure_hooks()` 每次命令都会被 `_cli.py` 调到，它用
   `os.path.dirname(os.path.abspath(__file__))` 定位安装器 → 本模块在
   `<skill>/scripts/memory_ops/`，于是它去找 `<skill>/scripts/memory_ops/install_hooks.py`
   ——**这个文件不存在** → `if not os.path.exists: return` 静默吞掉。
   实探对照：旧值 = `...\scripts\memory_ops\install_hooks.py`（不存在）；
   `_skill_root()` = `...\agent-local-memory-keeper\install_hooks.py`（存在）。
   后果：**新装用户若不手动跑 `keeper_setup`，一个钩子都不会注册**——自动记忆、错误捕获
   全部静默不工作，而文档写的是"✅ 开箱默认"。这与 §六 的 `hooks_config.json` 路径错位
   **是同一类错误**（都数错了上溯层数），只是它藏在"未注册分支"里一直没人走到。

2. 🔴 **后台拉起守护进程会弹黑窗**。`install_hooks.py` 用的是
   `CREATE_NEW_PROCESS_GROUP (0x00000200)`。受控实验（父 pythonw + 子 python.exe +
   DEVNULL 重定向，即该处真实形态）：

   | creationflags | `GetConsoleWindow()` | 窗口可见 |
   |---|---|---|
   | 不设 | 722416 | **是** |
   | `CREATE_NEW_PROCESS_GROUP` (0x00000200) | 984144 | **是** |
   | `DETACHED_PROCESS` (0x8) | 0 | 否 |
   | `0x8 \| 0x200` | 0 | 否 |
   | `CREATE_NO_WINDOW` (0x08000000) | 0 | 否 |

   → 4.9.11 修了钩子那处、本版 §六 修了"派发安装器"那处，**唯独漏了安装器自己拉 daemon 这处**。
   已改 `CREATE_NO_WINDOW`。同时把 `_lifecycle.py` 里一处无旗标的 `subprocess.run` 也补上（同一类隐患）。

### 十一、再补一条闸门：后台子进程不得弹窗
- `no_popup_spawn`（新）：扫**钩子/守护进程执行路径**（`hooks/`、`scripts/memory_ops/`、
  `keeper_daemon/`，外加唯一由钩子派发的根脚本 `install_hooks.py`）里的每个 spawn 点，
  要求带静默旗标之一（`CREATE_NO_WINDOW` / `DETACHED_PROCESS` / POSIX `start_new_session`）。
  当前 35 个文件 / 10 处 spawn 点全绿。
  局限也写进注释了：它只能证明"调用点附近写了旗标"，**不能**证明旗标真的生效，
  也覆盖不了"完全不传旗标且确实会弹窗"的极端写法——这类得靠上面的实测表兜底。
- 为什么范围只到这几个目录：其余脚本（`mem_bridge.py` / `setup_scheduler.py` / `keeper_setup.py`…）
  跑在 Agent 或用户终端里，**本来就有控制台**，子进程继承它、不会新开窗；
  若把范围放宽，会得到 29 处假阳性（实测过）。

> 一句话：本版不添新能力，只让已有能力**说到做到**、让发出去的包**干净**，
> 并顺手把两个"看起来在跑、其实从没跑过"的静默路径接上。

---

## 4.9.11 · 2026-09-10

上一版发完后继续在真机上验证，逮到两个**只在 Windows 暴露、且都不报错**的失效点：
一个让弹窗天天打扰人，一个让自检永远显示"失败"。共同点是——它们都长得像环境问题，
所以没人会去查。本版一并根治，并给后者补上防复发测试。

### 一、修 Windows 钩子弹控制台窗口（影响所有 Windows 用户）
Stop / PreCompact 钩子每次触发都弹一个黑窗口，得手动关。受控实验（pythonw 当父进程，
探针自报 `GetConsoleWindow` 可见性）：

| creationflags | 控制台窗口 | 会弹窗 |
|---|---|---|
| 不设 (0) | hwnd=329242 | 是 |
| DETACHED_PROCESS (0x8) ← 曾用 | hwnd=2754064 | **是** |
| CREATE_NO_WINDOW (0x08000000) | hwnd=0 | **否** |
| 两者并存 (0x08000008) | hwnd=853536 | **是** |

结论：**DETACHED_PROCESS 不等于静默**——它会给控制台子进程新开一个可见控制台；
必须单独用 `CREATE_NO_WINDOW`。已改 `memory_auto_capture.py` 两处与 `keeper_hook_common.py`
的进程内召回分支。`doctor` 现会报告钩子运行模式（`hooks.mode`）。

### 二、补齐漏发的 `hooks/_async_deposit.py`
技能包里漏了这个文件 → 在**新装机器**上 Stop/PreCompact 的异步蒸馏会静默失效：
钩子以为自己派发了，载荷却永远落不了盘。已从技能目录同步到 `~/.workbuddy/hooks/`
（老机器若手动拷过则不受影响，这也正是它难以被发现的原因）。

### 三、修 doctor 调度自检「从未执行过」
`doctor` 的 `scheduler` 字段长期是 `{"error": "scheduler status check failed"}`，
一直被当成"本机 schtasks 被安全策略拦了"。实跑取证后根因是：`_doctor.py` 是零 import
文件（符号靠运行期注入），而 `subprocess` 从不在注入集合里 → `_check_scheduler_status()`
每次都抛 `NameError`，被上层 `except Exception` 吞成一句**没有根因**的"检查失败"。
也就是说 `schtasks` 一次都没被调用过。现在：真跑 + 失败必须带 `detail`（暴露异常类型
与原文），不再让代码 bug 伪装成环境问题。新增回归测试
`scripts/tests/test_doctor_selfcheck_fields.py`（5 用例）。

> 顺带澄清一个**非问题项**：`doctor` 里的 `fingerprint_drift=143` 是「存量向量键带模型
> 指纹后缀」的统计值（覆盖率已 1.0，无需重嵌），不是漂移告警。

## 4.9.10 · 2026-09-10

一次外部审核反馈（「能力边界警示分散」「高级功能得读说明」）引发的**深挖式修复**：
顺着"分散"查下去，真正的问题不是重复，而是**文档与代码已经漂移**。本版把三道
闸门接成发版硬门禁，让此类漂移**再也发不出去**。

### 一、修一个真 bug：向量 model 键双轨（影响所有已装用户）
写入向量库用带模型指纹的键，比对时用的却是不带指纹的键 → 字符串**永不相等**：
- `doctor` 的覆盖率恒为 0.0（假红灯），而实测 126/126 条记忆都有向量；
- 每次召回都会重嵌上百条向量**且不落盘**，永不收敛（实测 0.418s → 修后 0.0001s）。

新增兼容判定（剥指纹比前缀）后：覆盖率恢复为 1.0，收敛到 0 条需重嵌。

### 二、能力边界收敛为单一真源（方案 B）
- 立真源：`SKILL.md` §九「安全护栏 · 红线与边界（唯一真源）」，其余文档只留指针；
- **四条红线 → 五条**：新增「开加密必须先备兜底」，把散落 33 处的软警示升级为硬约束；
- 修 **表述失真** 7 处：「忘 key = 永久丢失」→「忘 key **且无恢复码** = 永久丢失」
  （有恢复码可自救，原写法把生路抹掉了）；
- 修 **事实矛盾** 1 处：能力映射表曾写「真删（**可找回**）」，与红线冲突 → 改「不可逆」；
- 加密实为**字段级**（摘要/正文密文，id/分类明文），原措辞易误解为整文件加密；
- 新增 `references/GLOSSARY.md` 术语大白话表，治「术语难懂」。

### 三、跨设备同步：5 个静默坑升级为代码级硬拦截
此前文档写「脚本强制，勿绕过」，代码里其实是**只警告不拦**。现在 `--execute` 前直接拒绝：

| 场景 | 退出码 | 逃生 flag |
|---|---|---|
| 包缺完整性校验文件 | 7 | `--allow-unverified` |
| 未确认 id 膨胀 | 8 | `--i-know-id-bloat` |
| 部分导入失败 | 5 | — |
| 幂等校验失败 | 6 | — |

预演（不带 `--execute`）不受任何拦截，永远可以先看数字再决定。新增 7 个回归测试锁死。

### 四、两道防复发闸门（静态断言）
1. `redline_single_source`：红线表述失真 / 与红线矛盾的说法 → FAIL；
2. `no_dead_symbol_refs`：文档或注释点名的符号在代码里不存在 → FAIL。
   本次就抓到一例：注释声称的敏感扫描函数**根本不存在**，真名是另一个。

另修正「加密是整文件加密」「门禁脚本不能在已安装目录跑」等 4 处文档与现实不符。

### 五、发版链路：三道闸串成硬门禁
`scripts/publish_gate.py` 从「只跑 1 项」扩到「文档一致性 + 全量集成测试 + 文档声称校验」
三道全跑，任一红灯即拦截发版；发布器会在 dry-run 前自动发现并执行技能自带的这道门禁
（无门禁的技能不受影响，另有 `--no-gate` 逃生）。

### 验证
集成测试 **169 例 / 0 失败**；文档声称校验 **20/20**；门禁反向验证（注入死引用）
确认会亮红灯并精确报出文件行号。

---

## 4.9.9 · 2026-09-09



用户向文档去版本号的**例外收窄**：`references/_design/` 里的 13 处历史版本声称也清了，

现在唯一例外只剩 `references/EVOLUTION.md`。



### 例外收窄（为什么会留着 _design/）

上一版把 `_design/` 当例外，理由是「历史设计方案存档，版本号是内容本身」。

复核后这个理由**站不住**：那些版本号只是**时间戳式的叙事前缀**

（「v3.0 已发货」「v4.5.17 已修复」「自 v2.12.0 起改用 SQLite」），

去掉版本号、改成「现已发货」「现已修复」「现已改用」后**原意一字未损**，

反而不再需要读者去猜「v3.0 是多久以前」。



改动明细（4 份文档 / 13 处）：

- `FORMAT_ANALYSIS.md` 6 处（v2.5 / v2.12.0 / v3.0 ×4）

- `TYPE_TAXONOMY.md` 3 处（v3.0 / v3.1 ×2）

- `回收与软删治理设计方案.md` 3 处（v4.5.17 ×3）

- `压测方法论.md` 1 处（v2.1）



**保留不动**的 4 处（它们不是版本号，是数值，删了文档就错）：

`rrf_weak=0.03`（阈值）、`1.66×`（杠杆倍数）、`2.92s` / `197.6s`（实测耗时）。

⚠️ 扫描器容易把这类小数误判成版本号——**「看着像版本号」和「真是版本声称」是两回事**。



**仍为例外**：`references/EVOLUTION.md`——它是维护者演进史，

每条记录讲的本来就是「某版本发生了什么」，删掉版本号文档就失去意义。



---



## 4.9.8 · 2026-09-09

### 测试门禁长期 flaky 根治（修的是「测试基建」，不修业务代码）

组合跑门禁时**偶发 1 个用例失败、且每次失败的模块都不一样**——查下来是既有缺陷：
多个测试模块在 **import 期**就改 `os.environ`（把 `AI_MEM_EMBED_BACKEND` 注入成 `fastembed` 或 `None`），
而 import 期污染在模块内**无法安全撤销**（没有对应的 import 结束钩子），于是跨模块泄漏，
谁跑在后面谁倒霉。

`scripts/run_gate.py` 改为：
- **逐模块发现 + 逐模块运行**（原来一次性 discover 全量）；
- **模块间 env 隔离**：每个模块跑前存快照、跑后整体还原；
- **统一安全基线**：跑前强制 `AI_MEM_EMBED_BACKEND=lexical`，杜绝测试把门禁拖进真实 embedding；
- **越权检测**：基线被改即记为失败并点名模块（`%s 把 %s 改成了 ...`），让泄漏源无处可藏——
  正是它当场抓出 4 个污染源。

副产物：门禁耗时 **127s → 7.5s**。

### 新增 `scripts/tests/test_reexports.py`（进门禁）

用 **AST 精确扫描** `memory_ops.X` 引用（不是正则，正则会把注释里的 `memory_ops.X`、
文件路径 `memory_ops.py` 当成引用而误报）。

⚠️ 它的能力边界，文档里如实写明了：**不防「漏重导出」**——`memory_ops/__init__.py` 末尾有
PEP 562 模块级 `__getattr__` 兜底，漏了重导出运行时也不会 AttributeError，会被动态捞出来。
它真正防的是**「名字压根不存在」**（拼错、改名后调用方没跟改）。负向自测用「拼错名」构造，
实测能按预期失败。

### 文档清理

- **用户向文档去版本号**：共 **34 处**「某版本起…」「某版本校正…」「4.5.x 新增」这类历史版本
  声称全部清零，覆盖 `SKILL.md` / `COMMANDS` / `COOKBOOK` / `INSTALL` / `LIMITS` /
  `MEM_BRIDGE` / `QA` / `INVESTMENT` / `investment_templates` 九份——
  版本号是维护者自己修过的过去，用户不需要知道，留着只会让文档显得陈旧且难以维护。
  例外两处（版本号本身就是内容，删了就读不懂）：`references/EVOLUTION.md`（维护者演进史）
  与 `references/_design/`（历史设计方案存档）。
  ⚠️ 教训：第一轮只扫了「主版本.次版本.修订号」三位数形态，漏掉 `4.5.x` 这类「两位数 + x」
  写法，复核补扫才抓到 6 处——**扫描正则必须同时覆盖 `\d+\.\d+\.[xX]`**，别只认三位数。
- **反模式提醒前置**：`SKILL.md` 顶部新增**不可折叠**的「🔴 先读这 3 条（不读可能丢数据）」警示条
  （原先的 30 秒速览是 `<details>` 折叠块，新手根本不会展开）。`QUICKSTART.md` 加直达指针，
  但**不重列全表**——反模式清单保持**单一真源**在 SKILL.md 文末。
- `_review_check_reexports.py` 补上覆盖边界说明：它扫不到包内调用（包内不写 `import memory_ops`，
  依赖属性注入），**报 MISSING 0 不等于没问题**；自动化检查已由上面的新测试接管。
- **发布预检误报清零**：`gen_cookbook.py` 的 flag 漂移检查原先只读**单个**脚本文件，
  而 `memory_ops` 拆包后参数声明落在 `memory_ops/_cli.py`，于是 `--contradictions` /
  `--arbitrate` 被误报成「文档宣称但代码里没有」（4 处，实锤跑 `doctor --help` 确认二者真实存在）。
  已改为：若目标脚本是包的 `__init__.py`，则把同目录子模块一并纳入搜索。
  现在 `gen_cookbook.py --strict` 输出「✅ COOKBOOK.md 与代码一致，无漂移」——
  噪音清零之后，真漂移才不会被淹没。


---

## 4.9.7 · 2026-09-09

**keeper 代码零改动**，仅为修交付包的一个可见缺陷：

4.9.5 / 4.9.6 的包内 `CHANGELOG.md` 顶部出现**两个一模一样的 `## X.Y.Z` 标题**——上面那条是发布器自动生成的「更新 xxx 等 N 个（近期改动）」，下面才是手写条目。
根因在发布器 `skillhub-cli-publish`：它在打包时无条件 prepend 自动条目，即使 CHANGELOG 里已有同版本的手写条目。
已在 `skillhub-cli-publish 1.4.2` 修掉（先查重再 prepend；平台展示字段也改为优先取手写条目），本版用修好的发布器重发，包内 CHANGELOG 恢复单一标题。

---

## 4.9.6 · 2026-09-09

文档口径补齐（4.9.5 已封版、平台不允许同版重发，故单独出一版）：

- `SKILL.md` 能力表「回滚 / 版本链」一行，由「任何写入都自动快照」补为「**由写入门禁强制**：覆盖前留不下快照就中止写入」——4.9.5 的门禁改变了这条保证的性质（从「尽力快照」变成「留不下就不许写」），能力表应如实反映，否则用户会以为快照失败仍能写入。
- 4.9.5 的其余内容（写入门禁 `_gate_prewrite_snapshot` + 第 13 键 `write_gate` + 配置路径统一 + 8 个回归用例 + 4 处文档漂移订正）均已在 4.9.5 包内，本版仅此文档一行。

---

## 4.9.5 · 2026-09-09

### 补齐「写入门禁」——最后一个架构级缺口（对齐恒忆 commit_task 的同名原则）

恒忆 `commit_task.py` 有一条 keeper 此前没有的门禁：快照 → 覆盖 → manifest → daily → 索引，
**任一步失败即中止，绝不出现「没快照就覆盖」的路径**。keeper 4.9.3 把版本快照收口进
`_save_mem` / `_write_mem` 两个写入真源（覆盖率 2%→100%），但快照发生在**写完之后**且异常被吞
——一旦快照失败（磁盘满 / 权限 / 加密错），旧内容已被覆盖、永久丢失，用户只看到一行 stderr 警告。
这仍然是一条「没快照就覆盖」的路径。

修法（`hooks` 无关，落在 `scripts/memory_ops/_versions.py` 的 `_gate_prewrite_snapshot`）：
- 覆盖前先确认「即将被覆盖的旧内容」已有版本快照；**留不下快照就抛 `MemoryWriteGateError` 中止写入**
  （fail-closed，旧内容一字未改）。
- 判定三分支：文件不存在（新建）→ 放行；旧版本快照已存在 → 放行；快照缺失 → 立即补建，
  补建失败 → 中止。绝大多数写入只多两次 `os.path.exists`，无额外 IO。
- ⚠️ 关键边界：旧内容**解不开**时（典型是密钥轮换 `rekey`——磁盘上是旧密钥密文、当前进程已是新密钥）
  **不中止**，改为把密文**原样快照**（`_snapshot_version(..., raw=True)`，绝不二次加密）再放行。
  否则"写入门禁"会反过来锁死换密钥这一合法操作（实跑回归 `I3RekeyRotationTest` 时暴露）。
- 新增第 13 个运行时开关 `write_gate`（默认 `true`），env `KEEPER_WRITE_GATE=0` 为逃生通道。

### P1 · 修「keeper 块两个事实源」的配置分裂

`_load_keeper_config` / `_load_recall_config` 一直读 `<记忆根>/config.json`，而 `keeper_setup.py` 写的、
钩子 `recall_mode()` 读的是 `<记忆根>/store/config.json` —— 同一个 keeper 块有两个事实源，
导致 `keeper_setup --set-mode ...` 等设置被 memory_ops **静默忽略**（代码 docstring 自己写的都是
store/config.json，与实现不符）。

修法：新增 `_keeper_config_paths(root)`，按「store 优先、root 兼容兜底」逐键合并；两个读取器统一走它。
（本机实测：真库 `<你的记忆库目录>\config.json` 只放 `ima_kb_id`、`store/config.json` 放运行时开关，
本次改动不改变现有取值，但从此两边都认。）

### 回归锁

新增 `scripts/tests/test_write_gate.py` 8 个用例：新建不拦 / 快照缺失时门禁补建（内容=被覆盖的那份）/
快照失败即中止且**原文件一字未改** / 逃生通道 env=0 放行 / 默认值与 env 优先级 / 配置文件可关 /
第二个写入真源 `_write_mem` 同样受保护 / 解不开时原样快照密文不锁死 rekey。
全量 **158 个测试通过（4 skipped / 0 失败）**；`verify_claims.py` 19/19，其中
`config_doc_matches_code` 报「13 keys symmetric」。

### 文档漂移订正（同版，随全量复查发现）

4.9.3 把 `inject_enabled` 从「文档上写着、钩子实际无视」改成真正生效的开关（默认不注入），
但 `references/` 下 4 处仍按旧行为描述「开新会话会看到 `## 🧠 当前生效的 AI 经验` 段落」，
会让用户把「默认不注入」误判成「钩子没装」——这恰恰是排障时最贵的误判方向。
已订正 `INSTALL.md` / `COOKBOOK.md` / `QA.md` / `LIMITS.md`：明确「没看到注入段落 ≠ 钩子没生效」，
判定钩子是否 fire 的**唯一可靠依据是 `hook_audit.log`**；并各自标注恢复自动注入的两条路径。

---

## 4.9.4 · 2026-09-09

4.9.4: 强化 4.9.3 的半代理码点消毒 —— 从「读进来再洗」升级为「读字节自己解码」，覆盖两种失败模式。

4.9.3 只在 `json.load(sys.stdin)` **之后**消毒，但 stdin 的解码行为随 PYTHONUTF8 / locale 变化，存在两种模式：
① surrogateescape：非法字节解成半代理码点，json.load 通过，消毒生效（4.9.3 已修，生产 502 次 deposit_error 属此类）；
② strict：json.load **当场抛** UnicodeDecodeError，钩子直接 return，消毒根本没机会执行 —— 4.9.3 覆盖不到。
实测构造载荷复现：旧钩子（含 4.9.3）在模式②下 stdout 只有 {"continue": true}、沉积 0 条；新实现沉积 1 条成功，落盘内容无裸代理字符。

修法：`read_event()` 直接读 `sys.stdin.buffer` 字节流 → `decode('utf-8','surrogateescape')`（对任何字节都不抛）→ `json.loads` → `sanitize_obj` 统一替换为 U+FFFD；四个钩子（memory_auto_capture / post_tool_use_error_capture / session_start_keeper_inject / user_prompt_recall）全部改用 `read_event()`，边界收口到一处。
⚠️ 实现约束（踩坑）：源码里**不能**出现 "\ud800" 这类转义字面量 —— CPython 3.13 **编译期**就抛 UnicodeEncodeError（surrogates not allowed），模块直接 import 不了，故一律用 chr() 运行期构造。

验证：全量 150 个测试通过（4 skipped / 0 失败）｜新增 10 个回归用例（含"真实非法字节流"用例）｜A/B 端到端实测通过｜SKILL.md / _meta.json / CHANGELOG 三源版本对齐。

## 4.9.3 · 2026-09-08

### P1 · 半代理码点消毒（自动捕获静默失效，实测 502 次）

`hook_audit.log` 实测：**502 条 `deposit_error`**，全部是
`'utf-8' codec can't encode character '\udcXX'`（真实库统计，非推断）。

根因：Python UTF-8 模式下 `sys.stdin` 用 `errors='surrogateescape'`，Bash 输出里的非法字节
（git-bash 中文/GBK 混排最常见）被解成半代理码点 `\udcXX`；`json.load` **不报错**（它是合法 str 字符），
但后续 `json.dump` / 写文件 / 编码 HTTP 一律抛 `UnicodeEncodeError`——
于是「自动捕获 Bash 踩坑」**静默失效**：用户只看到没沉淀，看不到任何报错。

修法：在**读 stdin 这一层**就地消毒，而不是在每个写盘点打补丁。
`hooks/keeper_hook_common.py` 新增 `sanitize_text` / `sanitize_obj` / `read_event`，
四个钩子（`memory_auto_capture` / `post_tool_use_error_capture` / `session_start_keeper_inject` /
`user_prompt_recall`）读事件时统一消毒，半代理码点替换为 U+FFFD。

- ⚠️ 实现约束（踩坑）：源码里**不能**出现 `"\ud800"` 这类转义字面量——CPython 3.13 **编译期**就抛
  `UnicodeEncodeError`（surrogates not allowed），模块直接 import 不了。故一律用 `chr()` 运行期构造。
- 回归锁：新增 `scripts/tests/test_surrogate_sanitize.py` 9 个用例（替换/干净文本不变/非 str 透传/
  消毒后可编码 / 嵌套 dict-list / dict 键 / 整事件可 dump / `read_event` 消毒 / 读失败 fail-open）。

### P1 · 让会话启动钩子真正遵守 `inject_enabled`（方案 A）
`hooks/session_start_keeper_inject.py` **完全不读** `inject_enabled` / `inject_daily_cap` / `inject_dedup`
（这三个键的检查点只在 `mem_bridge.py`），而 SKILL.md 又承诺「默认关，靠显式 `retrieve`」——
文档承诺与实现不符：只要钩子模式不是 `off`，每会话启动都无条件注入至多 `TOP_N=5` 条 / `CHAR_BUDGET=1600` 字符。

修法：`keeper_hook_common` 新增 `inject_enabled()`（与既有 `recall_mode()`/`neural_recall_active()` 同范式：
env `KEEPER_INJECT_ENABLED` > `store/config.json` 的 `keeper.inject_enabled` > 默认 `False`，解析异常 fail-closed），
钩子 `main()` 在 source 判定后守门，未开启时直接 `_emit()` 空上下文并写 audit。

**⚠️ 行为变更（升级者必读）**：默认从「每会话自动注入」变为「**不注入**」。
想恢复自动注入：在 `store/config.json` 设 `keeper.inject_enabled=true`，或设 env `KEEPER_INJECT_ENABLED=1`。
另：`hooks --mode off` 仍是彻底停钩子的手段（与开关互不冲突）。

- 回归锁：新增 `scripts/tests/test_inject_gate.py` 5 个用例（默认无配置不注入 / 显式 false 不注入 /
  文件 true 注入 / env=1 覆盖文件 false / env=0 覆盖文件 true）。

**文档核对订正（同版）**：① `references/LIMITS.md` LLM 配置路径由 `store/config.json` 更正为
`<记忆根>/config.json`（实跑 `_llm_config_path()` 验证，照旧文档配 LLM 会静默不生效）；
② `COMMANDS.md`/`QA.md` 三处「overwrite 自动快照」更新为 4.9.3 的「任何写入都自动快照」；
③ `to-l2` 的 `--min-importance` 默认值 0.8→**0.7**（`mem_bridge.py:2278`），并标注其属
`mem_bridge.py` 子命令而非 `memory_ops.py` 的 op（`CAPABILITY_MAP.md` 同步）；
④ `SKILL.md` harvest 段补「无 LLM 时 self_learn 只产 corrections、candidates 恒空」的降级语义。

---


### P0 · 版本快照收口（覆盖率 2% → 100%）

`_snapshot_version` 原先只有 `overwrite`/`rollback` 两个**命令层**调用点，而真正的写入真源是 `_save_mem`（~55 处调用 / 15 个模块）与 `_write_mem`（deposit 落盘入口）。结果：除显式 `overwrite` 外的一切修改都**静默丢失历史**——实测真实库 147 条记忆仅 3 条有版本（覆盖率 **2.0%**），`timeline`/`rollback` 沦为「有命令、无数据」。

修法：**把版本快照收口进两个写入真源**（`_save_mem` 与 `_write_mem`），复用 keeper 2026-08-12 根治索引双写漂移的同一手法——单一真源点，覆盖率 2%→100%，不再依赖调用方记得手动快照。
- 语义：`versions/<mid>.v<n>.json` = 版本 n 的完整内容快照，供 `timeline` 回放、`rollback` 恢复。
- 幂等：同版本快照文件已存在则直接返回，故 `touch`/高频访问更新（version 不变）**不产生**新文件，杜绝磁盘爆炸（实测连跑 5 次 touch 版本数不增长）。
- 安全：快照走 `_encrypt_fields` 加密路径不留明文缺口；快照只写 `versions/` 不回调 `_save_mem`，无递归风险；异常一律吞掉，绝不阻断写文件主路径。
- 回归锁：新增 `scripts/tests/test_version_snapshot_coverage.py` 5 个用例（deposit 留 v1 / overwrite 追加 v2 且可列 / 同版本重复写幂等 / rollback 可恢复且可撤销 / 快照为合法 JSON）。**全量 135 测试通过（4 skip，0 失败）**，零回归。

---

## 4.9.2 · 2026-09-08

4.9.2: **P0 修复 md 往返炸碎记忆**——`keeper_import._parse_md` 旧实现把任何 `## ` 行都当新条目，记忆正文里的 markdown 小标题（`## 工作流`、`## 反模式`）被解析成独立记忆，一次 export→import 往返把 1 条长记忆炸成多条碎片并写入新 id 污染库。真实库实测：156 条记忆的 md 含 220 个 `## `（64 个是正文标题）→ 修复前解析出 216 条（多 60 条幽灵）、摘要一致率 67.1%；修复后 156 条、幽灵 0、一致率 **100%**。修法为「双锚点判定」`_is_entry_head`：A1 标题首段是 id 且至少含一个字母（挡住 `## 2026-09-08` 这类日期标题），A2 紧随其后是 `> ` meta 行且含 keeper 特征键（兜住手写 md）；代码围栏内的 `## ` 一律视为正文。新增 `scripts/tests/test_md_entry_head.py` 7 个回归用例锁死。

**P1 修复「索引僵尸清不掉」**——`save_index` 用 scoped DELETE（只删本次传入的 id），于是 `rebuild` 这类「磁盘文件才是事实源」的全量重建也删不掉「索引有、文件已没有」的陈旧条目。实测本库 index 272 条 vs 文件 156 条，rebuild 后**仍是 272**（116 条僵尸纹丝不动）；`_sync_index` 同理（文件缺失时 `continue` 跳过）。修法：`save_index` 新增 `full_replace` 参数，`rebuild` 调用时传 True 先 `DELETE FROM entries`。修复后 entries=文件数、僵尸 0、漏索引 0，`stats.total_memories` 从虚高 272 回到真实 156。

**P1 修复「自动捕获写错库」**——`~/.keeper/store_root` 不存在且 env 被净化时，hooks/daemon 回退到 `~/.ai-memory`，与用户真库（如 `<你的记忆库目录>`）不是同一个，自动捕获的踩坑经验全部进了空库。已对齐各模块默认路径（`keeper_hook_common` / `daemon` / `keeper_recall_client` / `ima_bridge` 的 `~/.ai-memory` 改为与 `memory_ops._config` 一致：Windows `~/AI记忆`），并修复 `setup_scheduler._resolve_keeper_root` 只认 env 的问题（非交互安装的 schtasks/systemd 任务因此不带 `AI_MEMORY_STORE`，跑起来落到默认库）——现补齐回退链 env → `~/.keeper/store_root` → 默认。

**P2 修复 tmp 残留**——`_save_mem` 原子写的临时文件固定为 `<id>.json.tmp`（不带 pid，并发写同一记忆会互相截断）且写入失败时不清理，实测累积 347 个残留（占 115KB，均为自动捕获写入中断的半成品）。修法：临时文件名带 pid；写入异常时删除临时文件后重抛。

## 4.9.1 · 2026-09-05

4.9.1: 修复跨设备同步 5 个缺陷（md 往返丢摘要 0%->100%、export 静默少导、import 默认不落盘、同步后状态丢失+双份副本），新增 keeper_sync.py 合并式同步工具；发布前体检清零 7 处机器特定路径硬编码（改为 AI_MEMORY_STORE / ~/.keeper/store_root 回退链）；修正 4 处 import --dry-run 文档错误、13 处过时路径描述、开发文档 4 条死链命令、3 处 shell=True 拼接；补齐 9 个零提及的配置项文档；新增 9 个回归测试（123 全绿）。

> 主题：**跨设备同步闭环**。起因是「多台电脑、一周用一次」场景下实测 export/import 链路，
> 挖出 5 个坑（其中 4 个只在跨设备同步时暴露），逐个修掉并新增 `keeper_sync.py` 把铁律固化进代码。
> 全部条目带「修复前 / 修复后」实测对照，非推断。

### ① md 往返丢摘要（**P0，实测摘要一致率 0% → 100%**）
`export --format md` 的标题只写 `## <id>`，不写摘要；而 `import` 的 `_parse_md`
直接把标题当 summary → **导入后每条记忆的摘要都变成 `LRN-20260801-001` 这类 id**，
正文虽在，但摘要语义全丢（召回排序、inject 展示、去重全受影响）。

修法（双向兼顾，兼容旧文件）：
- **export 侧**：`_render_md` 的 meta 行首位写入 `摘要: <summary>`（单行化，防换行截断后续字段）。
- **import 侧**：`_parse_md` 按优先级取摘要 —— ① meta 行的 `摘要:`（正则非贪婪取值，
  允许摘要内含 `·`，此前按 `·` 裸 split 会截断）② 标题 `<id> · <summary>` 拆分出的右侧
  ③ 正文前 120 字兜底。同时修 `_normalize`：**summary 缺失时不再把整个 body 当摘要**
  （旧行为会让摘要变成几千字正文）。
- 标题识别三类形态：整串是 id（旧版 md）/ `<id> · <summary>`（learnings）/ 普通中文标题（不误拆）。

实测对照（同一真实库 19 条，走 md 往返）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 摘要仍是 ID 的条数 | 19 / 19 | 0 / 19 |
| 摘要与源库一致率 | 0% | **100%（19/19）** |

单元 + 端到端回归 **14/14 通过**。

### ② export 静默少导（**P0，19 条只出 7 条**）
`export_memories` 过滤条件为 `include_archived or status == "active"`，
于是 **superseded / archived 全部被静默丢弃**；更坑的是 CLI 上有 `--include-superseded`
参数（原本只服务 recall），传给 export **不报错也不生效**（静默无效）。

修法：新增 `include_superseded` 参数，状态过滤改为三态（active / superseded / archived 分别受控，
未知状态一律保留，宁可多导不可静默丢）；返回值增加 `filtered_out` /
`hidden_superseded` / `hidden_archived`，并在有跳过时向 stderr 打印显式 HINT。

实测（本机库：active 7 / superseded 6 / archived 6 = 19）：

| 命令 | 条数 | filtered_out |
|---|---|---|
| 默认 | 7 | 12（附 HINT 提示） |
| `--include-superseded` | 13 | 6 |
| `--include-archived` | 19 | 0 |

### ③ import 默认 dry-run 容易误判成功
跑完打印 `imported: 19` 其实**一条都没写**（默认 dry-run 是防手滑设计，本身不改）。
修法：保持安全默认不动，但在返回值与 stderr 双向输出醒目 HINT，
说明「未写入任何记忆，加 `--execute` 才落盘」。

### ④ 新脚本 `scripts/keeper_sync.py` —— 跨设备同步（新增）
把上面几条的教训 + 同步语义固化成一条命令：
- `out`：导出全量包（两个开关全开）+ `meta.json`（条数 / sha256 / 源机 / 时间），
- `in`：sha256 完整性校验（损坏即中止，不写任何数据）→ 预演新增/覆盖条数 →
  **强制 `--keep-ids`**（`--no-keep-ids` 逃生时红字警告）→ 落盘前自动备份 → 导入。

### ⑤ 同步后状态丢失 + 重复副本（**P0，19 条导入后变 26 条**）
实测 A 机（19 条：active 7 / superseded 6 / archived 6）导入 20 条包后变成 **26 条**：
- `deposit` 导入一律写 active 到 `memories/`，**superseded / archived 状态全丢**（6 条"复活"）；
- archived 记忆住在 `memories/archive/`，导入时**不会被同 id 覆盖** → root 与 archive 各一份
  （19 + 6 = 26 双份脏数据）。

修法：`keeper_sync.py in` 导入后加 **状态收敛（reconcile）** ——
① 同 id 双份时删除与包状态不符的那份（沙箱用 Win32 `DeleteFileW` 兜底真删）
② 包里是 archived → `archive()` 搬回 archive 目录 ③ 包里是 superseded → 置 status 并同步 index。
端到端实测 **13/13 通过**，收敛后：状态 20/20 一致、摘要 20/20 一致、条数 20 = 包内 20（零漂移）。

### ⑥ 天数机制结论（**不改动，写入文档**）
从真实使用数据反推间隔（35 天内仅 3 天有活动、间隔中位 **28 天**）后逐机制模拟：
`recurrence`（30 天窗口 ≥3 次）在间隔 **>15 天**时数学不可达（**真失效**），
但 `heat`（半衰 14 天）的 `heat_recent()` 全库**零调用 = 死代码**，对实际召回无影响（**伪问题**）。
结论：**低频场景不必改天数参数**，改了也是动死代码；真要根治需把"天数窗口"换成"会话数窗口"（留作后续）。

### ⑦ 文档一致性修正（发布前全库体检发现，6 处）

按「发布前对整个 skill 检查有无不符合/过时内容」逐项核对，修掉以下文档漂移
（均为**文档与代码实测不符**，会直接误导使用者）：

| 位置 | 原文（错） | 修正 |
|---|---|---|
| `SKILL.md` 能力表 import | "`--dry-run` 先试" | **默认仅 dry-run 预览，必须 `--execute` 才落盘**（import 无 `--dry-run` 参数） |
| `SKILL.md` 能力表 export | 只说"增强可移植" | 补：**默认仅导 active**，全量需 `--include-archived` / `--include-superseded`，见 `filtered_out` |
| `references/COMMANDS.md` import | 参数列 `--dry-run` | 改为 `--execute`（并注明 `--dry-run` 属 delete/archive 等危险操作，对 import 无效） |
| `references/COMMANDS.md` export | 参数只列 `--include-archived` | 补 `--include-superseded` + 默认仅导 active 的告警 |
| `references/FEATURES.md` 批量导入 | "`--dry-run` 预览" | 改为"默认预览、必须 `--execute` 才落盘" |
| `references/MEM_BRIDGE.md` import | 参数列 `--dry-run` | 改为 `--execute` |

**另修一处「不完整」而非「错误」**：`QA.md` Q12「能跨设备同步吗」原先只推荐
`backup`→ZIP→`restore`（**覆盖式，会丢掉目标机自己的新记忆**），未覆盖 4.9.1 新增的
`keeper_sync.py`（**合并式，保留双方新增**）。已改为选择矩阵，明确两种方式的语义差别：
整库克隆/换机用 backup/restore，两台电脑各干各活用 keeper_sync。
`CAPABILITY_MAP.md` 同步补上「搬到另一台电脑」能力行。

**新增引用**：`COMMANDS.md` 增「独立脚本 `keeper_sync.py`」小节（此前 SKILL.md 有引用、
命令总表无收录，属孤儿文件——功能在但无人知道）。

### 🔒 发布前体检：机器特定路径清零（P1·脱敏）
源码 **7 处写死 `<你的记忆库目录>` 绝对路径**（`hooks/keeper_hook_common.py` / `keeper_daemon/daemon.py` /
`keeper_recall_client.py` / `scripts/ima_bridge.py` / `_keeper_ima_push.py` / `memory_ops/_config.py` /
`memory_ops/_reflect.py`）——在「有 D 盘的别的电脑」上会误建 / 误读库，且违反发布脱敏规则。
- **改法**：统一回退链 `AI_MEMORY_STORE` → **`~/.keeper/store_root`**（新增，一行路径的纯文本
  文件，不想设环境变量时用这个）→ 平台默认（Windows `~/AI记忆`、mac/Linux `~/.ai-memory`）。
  机器特定路径从此不进代码。
- **行为零变化**：已在本机写入 `~/.keeper/store_root`，四个入口（`memory_ops` / hook / daemon /
  recall client）**实测在 env 未设时均正确解析到原库**。
- 附带修正 **13 处过时描述**（注释 / CLI help / docstring 仍在讲「有 D 盘用 <你的记忆库目录>」，与改后
  行为不符）；`_reflect.py` 的 `store_root` **死变量**（赋值后从未使用）一并删除。
- `_keeper_ima_push.py` 顺带修一个真 bug：注释写「env 优先」，代码却只读硬编码、从未读 env。
- `SKILL.md` 「如何配置」节补 **记忆库位置回退链** 说明。

### 🧪 开发文档死链修复（P2）
`references/_design/DEV_TESTING.md` 发版前清单 6 条命令有 **4 条指向已删除的脚本**
（`regression_v390.py` / `test_op_consistency.py` / `deep_sim_test.py` / `p1p2_tests.py`；
7 个被引用脚本全部缺失且 `tests/` 下无替代品）→ 改为当前真实入口：
`unittest discover -s scripts/tests`、`verify_claims.py`、`mem_bridge selftest`、`keeper_daemon/_selftest.py`。

### 🔧 安全性 / 测试引导 / 自检脚本修复（P2）
- **3 处 `shell=True` 拼接命令**（`ima_sync.py`、`_lifecycle.py`）→ 改列表式调用。当前
  `sys.executable` 无空格侥幸没炸，**装到 `C:\Program Files\` 下必炸**。
- **`test_save_mem_index_sync.py` 缺 `sys.path` 引导**：`unittest discover` 下靠 discover 注入
  路径能过，**单独跑必报 `ModuleNotFoundError`**。已补引导，单独跑通过。
- **`verify_claims.py` 两处假失败**：①`KEEPER_DEFAULTS` 重构后已搬进包内 `__init__.py`，检查
  脚本还在 shim `memory_ops.py` 里找 → 改为两处都找；②配置项检查假设 SKILL.md 有 json 配置块，
  而文档早已改成表格 → 改为直接比对键名。修完 **18/18 通过**（此前 17/18，rc=1）。
- **配置项文档补齐（真问题）**：`KEEPER_DEFAULTS` 12 个键，SKILL.md 只提及 1 个、**9 个全库
  零提及** → 在「如何配置」节补齐全量 12 键表格 + env 映射（补文档而非放宽检查）。
- **C3 / SEC3 判定为误报**：`base64(b"0"*32)` / `secret-body-XYZ` 是测试 fixture 假值（改成
  读环境变量反而破坏测试确定性）；`mem_bridge.py:365` 读自己的加密 keyfile 是设计功能。

### 回归
| 项 | 结果 |
|---|---|
| `unittest discover -s scripts/tests` | **117 通过 / 1 skip / 0 失败** |
| `mem_bridge selftest` | **18/18 通过** |
| `verify_claims`（keeper 自检文档一致性） | **18/18 通过**（rc=0） |
| md 往返单元 + 端到端 | **14/14** |
| 跨设备同步端到端 | **13/13** |
| 同步后三层数据一致性 | **6/6**（`memories/*.json` ↔ `memories/archive/` ↔ `store/index.db`） |
| SKILL.md 引用文件死链 | **23 个零死链** |
| 语义 / 显式检索 | 模型正常加载未降级；连续命中 |

---

## 4.9.0 · 2026-09-05

> 本版经**与 SkillHub 线上 4.8.7 逐项对照**后产出：先比对确认哪些已由上游修掉（不重复造轮子），
> 再针对两边都缺失的缺口补修。全部条目带实测复现与回归验证。

### ① 自动捕获钩子误判 —— 融合上游 A6 修法，7/7 全过（原 4.8.2 版 5/7）
原实现双缺陷叠加：退出码读 snake_case `exit_code`，而 WorkBuddy 事件实为 camelCase `exitCode`
（判定恒失效）；且 `ERR_KEYS` 对**整段响应 JSON** 裸匹配，而响应恒含字段名 `tool_error_code`
（内含子串 "error"）→ **每次 bash（含 exitCode=0 的成功命令）都被判为错误入库**。
实测本机记忆库 30 条中 17 条为此类垃圾，真经验仅剩 13 条。

与线上 4.8.7（A6 修复，2026-08-31）逐用例对照后发现两版各有漏网，且**互补**：

| 用例 | 4.8.2 | 线上 4.8.7 | 本版 |
|---|---|---|---|
| exitCode=0 但 stdout 含 `[error]` 日志字样 | ❌ 误捕获 | ✅ | ✅ |
| exitCode=0 但 stderr 含 Traceback | ✅ | ❌ 漏捕获 | ✅ |
| exitCode=0 但 stderr 含 `failed` | ✅ | ❌ 漏捕获 | ✅ |

最终修法（取两版之长）：拿到退出码即**以退出码为准**——非 0 必捕获；为 0 时**只查 stderr**
（不查 stdout，因正常日志常含 error/failed 字样）；无退出码可依时才退回全量真实输出匹配，
且匹配对象只含 stdout/stderr/output 的**内容**、不含带字段名的元数据 JSON。spy 回归 **7/7 通过**。

### ② `HF_ENDPOINT` 缺协议前缀 → 静默降级（**线上 4.8.7 同样缺失，P0**）
`_ensure_hf_mirror()` 对显式配置的 `HF_ENDPOINT` 直接「尊重用户选择」返回，但**不校验协议前缀**。
裸域名（如 `hf-mirror.com`）会让 httpx 抛 `UnsupportedProtocol: Request URL is missing an
'http://' or 'https://' protocol` → 模型下载失败 → 静默降级词法级。

更隐蔽的是验收侧的**假绿灯**：`_doctor.py` 的判据是 `using_mirror = "hf-mirror" in hf_endpoint`，
只查子串 —— 裸域名同样命中 → **doctor 显示「已启用镜像」绿灯，实际已降级**。
这是本机长达数月处于降级态却无人发现的根本原因。

修复：缺 `http(s)://` 时自动补全并向 stderr 显式告警。实测：
`hf-mirror.com` → `https://hf-mirror.com`（线上 4.8.7 同输入下保持不变，仍会降级）。

### ③ 探测通道与下载通道不一致 → 新增镜像重试自愈
`_ensure_hf_mirror()` 用 **urllib** HEAD `huggingface.co` 探测，2 秒内「成功」便不切镜像；
但真实下载走 **httpx**（沙箱 TLS 拦截 / 代理 / 协议缺失均只影响 httpx）→ 探测说可达、下载必失败。
修复：首次加载失败且尚未用镜像时，强制切 `hf-mirror` 重试一次（`ImportError` 属缺包，不重试）。

### ④ 模型缓存 env 被强制覆盖（升级丢模型根因）
`mem_bridge` 两处对 `FASTEMBED_CACHE_PATH` 由**强制覆盖**改为**尊重已配置**（仅未设时回退
`~/.cache/fastembed`），与 `embed.py`「缓存放 skill 目录外」的设计意图对齐。
注：线上 4.8.7 已将默认路径改为 skill 外，故升级不再丢模型；但**仍强制覆盖用户配置**，此项保留。

### ⑤ 去重门误伤「显式检索」—— 存了却找不到（**线上 4.8.7 同样缺失**）
`inject_active()` 被 `inject`（自动注入）与 `retrieve`（显式检索）共用，而 P1-2 去重门
（同记忆 14 天内最多注入一次）不区分二者。但该门的设计意图是切断**自动注入**的自反馈回路；
`retrieve` 是用户/AI 显式发起的查询，语义相反，理应「问必答」。

实测后果：一条经验被召回过一次后，**14 天内所有显式检索均返回空**。本机
`.inject_surfaced.json` 累计 `__suppressed__ = 117`，正是「存了 30 条、能用 0 条」的直接原因。
（注意：代码此前已为 daily-cap 闸门做过同类区分 —— 引入 `respect_inject_gate=False` 让
retrieve 绕过，**但漏了 dedup 门**，属一致性遗漏。）

修复：dedup 门的读（抑制）与写（记录 surfaced）均以 `respect_inject_gate` 为条件，
显式检索不受自动注入策略约束。验证：surfaced 记录保留（含 117 次抑制历史）的前提下，
连续 3 次 `retrieve` 稳定命中。

### ⑥ 新增「安装/更新后体检清单」（SKILL.md）
初次配置 / 升级后 5 项体检：selftest 全过 / retrieve 无降级字样 / doctor
`fell_back_to_lexical=false` 且 `coverage.rate=1.0` / `HF_ENDPOINT` 带协议 / 成功命令不入库。
补齐 requirements「显式提示而非静默降级」承诺的可执行验证路径。

## 4.8.2–4.8.7 · 2026-08-31

> **连续迭代六连发（区间条目）**——这六个版本于 2026-08-31 19:48 ~ 22:44 集中发布，**任何文档当时都没有留下对应条目**（其中 4.8.2 只有文件清单、无摘要）。本条目为**事后补记（2026-09-13）**，用于让「发布账本核对」不再把这六个版本报成缺失。
> - **4.8.2**（19:48）：`CHANGELOG.md` / `SKILL.md` / `_meta.json` / `COMMANDS.md` / `keeper_setup.py` / `_harvest.py` 更新。
> - **4.8.3**（20:20）、**4.8.4**（20:28）、**4.8.5**（20:34）、**4.8.6**（20:43）：`_reflect.py` / `_decay.py` / `__init__.py` / `post_tool_use_error_capture.py` 等随迭代更新（平台元数据只留存文件清单，摘要未保留）。
> - **4.8.7**（22:44）：**修复后复查产物**——`settle` 门槛恢复区分度（`SETTLE_MIN_USAGE=20`）、收紧 `recent_use` 窗口（90 → 30 天）、引入 A5 非衰减豁免 `usage_exempt`、修复 seed 死锁、修 bash 侧错误捕获。
> - ⚠️ **口径提醒**：本条为区间标题（`## X–Y`），`release-audit` 会按**区间覆盖**处理——即视 `4.8.2`~`4.8.7` 六版均已记录，不要求逐版单列。原文取自平台版本元数据（`GET /api/v1/skills/<slug>/versions`）。

## 4.8.1 · 2026-08-12

4.8.1 体验优化（针对高级功能边界与错误提示反馈）：守护进程残留清理四重保障（/quit 优雅删 .daemon.json、SIGTERM/SIGINT 信号处理、atexit 兜底、启动时检测死端口自动清理陈旧 STATE，根治手动 kill 残留）；daemon.log 超 1MB 自动轮转；deposit 的 tier/scene 校验报错去专业化（不再吐内部元组，改为人话可选值+引导）；新增 references/CAPABILITY_MAP.md 能力总图（含「帮我把记忆系统整体保养一遍」等高级触发一句话索引），SKILL/QUICKSTART 加指针；补齐边界测试（守护进程残留清理 + 云端 IMA 同步零测试→有覆盖）；全量 121 测试通过零回归。

## 4.8.0 · 2026-08-12

4.8.0 累积修复：根治 claim B 双写漂移（索引+倒排同步收口进 _save_mem，不再依赖各 op 手动纪律）；修复 taxonomy 活跃召回断点（--tag/--subdomain 真正可用于 recall，并加回归测试锁死）；文档体系补全（QUICKSTART 默认能力/红线表、SKILL 三个隐藏条件 callout、LIMITS 召回质量边界、COOKBOOK 示例）；修 forget 的 erraneous 错拼字段；修 COMMANDS.md 两处归属笔误（working/to-l2 正确归位 mem_bridge）；全量 115 测试通过零回归。

## 4.7.13 · 2026-08-12

补齐文档缺口：COMMANDS.md 补全 evolve/forget/distill-to-wb/to-l2/working/verify-investment 共 6 个命令表格行；QA.md 新增『遇到问题先跑谁』速查表与 §14 索引漂移致 recall 漏过滤/误杀排查（doctor --fix 回填）；SKILL.md/QUICKSTART.md 补充 keeper-conversational-guide 对话式导览指针与强化『出问题了』callout。

## 4.7.12 · 2026-08-12

合并原本散落的 3 条维护/进化/产物调度为**单一默认全开的统一自治循环 `self-heal`**，并修复一处线上静默死路（高频经验 recurrence 固化路径）。

### ① 统一自治循环 `self-heal`（P0/P1/P2 合并落地）
- 把 `reflect --auto` / `evolve 规则信号` / `decay --apply` / `doctor --fix` / `skill-sync` / `export-rules --sync` / `doctor --contradictions` 串成一条循环：
  - **dirty 驱动**：deposit/forget/link 纠正等变更入口打标，self-heal 只读脏、合并多次变更为一次重算；收尾清空脏标（沙箱删除被拦截时回退重写为空脏集，保证下次不误判脏）。
  - **节奏**：每日/脏时跑 reflect+evolve+doctor+skill-sync+export-rules；每月1号或 `--force` 跑 decay；每周日或 `--force` 跑矛盾扫描；全部离线、加性、向后兼容。
  - `evolve` 默认仅应用**规则信号**（recurrence≥3，免 LLM、幂等、限期复核 review_by=+30天），LLM 信号保持 review-only。
  - `--discover` 可选：自动发现已达标但未被覆盖的 area 集群并建新 skill 脚手架。
- 四源版本对齐自检：`self-heal` 收尾比对 SKILL.md frontmatter / _meta.json / CHANGELOG.md 顶部版本号，不一致仅告警不致命。

### ② 修复 `select_entries` / `hot_rules` 走被裁剪的 SQLite 镜像（线上静默死路）
- 原 `recurrence≥阈值` 分支读 `load_index`（SQLite 派生镜像 `data` 列），该列落盘时被 `_index_entry_from_mem` 裁剪，缺失 `recurrence_count`/`pattern_key` 等 D3/进化字段 → 高频经验永远命中不了 recurrence 路径，extract-skill / skill-sync / export-rules 的 recurrence 固化实为死路（仅 `state=confirmed` 可用）。
- 修复：新增 `_active_entries()` 改读权威源 `_all_mems`（直接读记忆 JSON 文件，与 `evolve` 一致），仅在异常时回退 `load_index`。`select_entries`/`hot_rules` 现已与生产行为一致（同一 recurrence≥3 经验，三处选择集一致）。

### ③ 文档与对话式指引同步
- SKILL.md / QUICKSTART.md / COMMANDS.md 增加 `self-heal` 命令；对话式导览（keeper-conversational-guide）补充统一自治循环说明。
- 命令总数 61 → 62。

---

## 4.7.11 · 2026-08-11

回应「想要完全自有、不依赖特定平台」的反馈：在保留既有平台目标的基础上，新增**完全自有的 `text` 目标**，并把平台目标的存在理由讲清楚。

### ① 新增 `--rules-target text`（完全自有，零平台耦合）
- `export-rules --rules-target text --out <任意路径>`：写入用户指定路径，首行标题为中性 `# Agent Instructions`，文件路径+文件名+标题全部由用户决定。
- `import-rules --rules-target text --out <路径>`：从同路径回灌。
- **使用场景**：项目合规禁止 `.github/` 写文件 / 不想被 Copilot 自动加载 / 自有 harness（Cursor/Continue.dev/Aider 等）/ 调试隔离。
- 实操：缺 `--out` 时 fail-fast 报 `missing_arg` + 退出码 2，不静默落到 `cwd/agent_instructions.md`（避免意外覆盖）。

### ② 文档「平台标准」边界澄清（平台标准路径）
- `.github/copilot-instructions.md` = Microsoft/GitHub 官方为 Copilot 定义的指令自动加载位置（[官方文档](https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot)）。
- `CLAUDE.md` = Anthropic 官方为 Claude Code 定义的约定（[官方文档](https://docs.anthropic.com/en/docs/claude-code/memory)）。
- 这两个**路径名是平台强制的**——如果想被 Copilot/Claude 自动加载，路径必须长这样。
- **SkillHub 没有等价规则文件约定**，因为 SkillHub 是技能分发/包注册平台（不是 AI 助手运行时）——这是架构差异不是偷懒。

### 联动文档
- `references/COMMANDS.md`：`export-rules`/`import-rules` 行新增 `text` 选项与 `--out` 说明。
- `SKILL.md`：导航行新增 "把规则写到任意自定义路径（零平台耦合）"；② 行为规则层补充 `text` 提法。
- `_cli.py::quickstart_text`：极简指引补 `text` 一行。

### 与 4.7.10 的兼容
- **完全向后兼容**：原有 `project`/`user`/`copilot`/`claude` 选项行为完全不变，只是多了一个新选项。新增 `text` 是加性能力，不影响既有调用。
- `# AGENTS.md` 标题（`project` 目标）保持不变；`# GitHub Copilot Instructions`/`# Claude` 也保持不变；新增 `# Agent Instructions` 仅用于 `text` 目标。

---

---

> 📦 **历史版本已归档**：`4.7.10` 及更早（共 120 个版本条目）已移至 `references/_design/changelog_archive.md`。最近 20 版见本文件。