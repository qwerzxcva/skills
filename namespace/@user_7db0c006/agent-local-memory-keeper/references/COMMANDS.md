# 命令参考（COMMANDS）

> 本文件是 `memory_ops` 全部子命令 + 关键参数的**单一权威表**（CLI 入口 `memory_ops.py` 为转发垫片，实际逻辑在 `scripts/memory_ops/__init__.py`；命令行敲 `python scripts/memory_ops/__init__.py <op>`），从 `SKILL.md` 概述中抽出，避免概述被命令表撑爆。
> 标记为 **[API]** 的是 Python 内部 API，不通过命令行调用（命令行敲会报 `invalid choice`），由 AI 在 Skill 机制内调用。
> 想先看清单：`python scripts/memory_ops/__init__.py commands`。

> 📌 **本文件 vs `COOKBOOK.md` 别搞混**：本 `COMMANDS.md` 是「命令参数权威表」——查某个命令怎么用、有哪些参数；`COOKBOOK.md` 是「高级操作实操手册」——讲怎么把钩子 / 守护进程 / 调度 / IMA 等**跑通、验证、回滚**，不重复列参数。两者互补。

> ⚠️ 本表**仅收录 `memory_ops` 命令**。mem_bridge 的桥接命令（含 `scan_dup`=近重复扫描，与 memory_ops 的 `audit`=功能推荐 **同名异义**）见 `references/MEM_BRIDGE.md`。

---

## 写入 / 沉淀

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `deposit` | 写记忆 + 登记索引；写前扫 secrets 一票否决 + 语义查重 | `--category/--summary/--tags/--body/--corrects/--scope/--project/--domain/--subdomain/--scene/--confidence/--importance`；**`--attr K=V`**（投资指标自动收敛）；**`--state/--priority/--area`**（状态机/优先级/领域，留空触发词典自动预填）；**`--about-axis user/self/relationship/world`**（四轴，留空触发词典/默认 None）；**`--why "<理由>"`**（记录决策理由，随 `recall` 暴露，便于复盘回溯推理链） |
| `harvest` | 自主沉积：从会话/现有记忆抽学习点；`--self-learn` 跨记忆自学习；`--from-conversations` 从 WB 历史会话沉淀（会话来源打 `wb_session` 标签 + 幂等去重） | `--text/--session/--self-learn/--with-workbuddy/--from-conversations` |
| `converse` | 对话内自主沉淀（按轮次阈值自动 harvest+reflect） | `--end`（立即收尾触发）/ `--set-threshold N` / `--rounds N` / `--with-workbuddy` |
| `feedback` | 置信度校准 | `--id <id> --signal good\|bad` |
| `overwrite` | 真覆盖同文件（version+1）。**任何写入都会自动留版本快照**（不只是 overwrite），故可回滚 | `--dry-run/--yes` |
| `archive` / `unarchive` | 搬入/搬出 `memories/archive/`（沉底不销毁，可找回） | `--yes` |
| `invalidate` | **软失效（双时序）**：把一条记忆标为「自某时点起不再为真」——**不删除、不搬文件**，置 `invalid_at` + `status=superseded`。与 `delete` 的区别：可随时 `uninvalidate` **无损撤销**；与 `archive` 的区别：归档是「冷数据沉淀」，失效是「结论被推翻」，两者语义不同，混在一个 status 上会互相掩盖。之后可回答「2026-08 那会儿这条还有效吗」这类**回溯问题** | `--id <id>`（必填）/`--by <id>`（被哪条取代，写入 `invalidated_by` + `superseded_by` 图边）/`--reason "<原因>"`（写入 `invalid_reason`）/`--invalid-at YYYY-MM-DD`（失效时点，缺省=今天；⚠️ 不是 `--at`，那是 schedule_reflect 的）/`--dry-run`（只预览不落盘） |
| `uninvalidate` | **撤销软失效**：清空 `invalid_at`/`invalidated_by`/`invalid_reason`，`status` 回到 `active`；`valid_at` 保留历史。这就是「置位不删」相对真删除的价值：误判可无损回滚 | `--id <id>`（必填）/`--dry-run` |
| `delete` | 物理删文件；**必须 `--yes`**（不可逆） | `--dry-run/--yes` |
| `rollback` / `versions` | 记忆版本链回滚 / 列历史版本（**任何写入都自动快照**，rollback 前也会先留档 → 回滚本身可 undo） | `--to-version/--yes` |
| `link` | 建关系链 | `--rel see_also/superseded_by/corrected_by --target <id>` |
| `promote` | 改 `tier`（working→curated→core） | `--tier` / `--auto`；**`--review`**（列出待晋升候选不修改任何记忆，加 `--apply --tier` 才真晋升） |
| `confirm` | **staging 人工放行**：auto_sourced 暂存记忆确认入库——置 `reviewed=True` + 清 `auto_sourced`（可选 `--tier` 顺带升级），文件与 index 同步；被暂存隔离的记忆（如 `workbuddy_sync` 画像同步）确认后进入默认召回，不再等 365 天 TTL 归档 | `--id <mid>` / 位置参数；`--tier`（可选） |
| `import` | **批量导入**：从 JSONL / JSON / CSV / Markdown 批量灌入记忆，复用 `deposit` 全流程（去重 / 分类 / 索引一致）；批量 `defer_index=True` + 末尾 `flush_memory_index` 一次落盘（大批量高性能）。兼容 `export --format jsonl` 整对象（round-trip 友好，默认新 id、`--keep-ids` 复用原 id）。⚠️ **默认仅 dry-run 预览、一条都不写**，必须加 `--execute` 才落盘（注意：`--dry-run` 是 delete/archive 等危险操作的参数，**对 import 无效**） | `--file <路径>`（必填）/`--import-format auto\|jsonl\|json\|csv\|md`/`--execute`（**落盘开关**）/`--keep-ids`/`--on-error skip\|abort`/`--report <json路径>` |

> ⚠️ **`import` 行为边界（调用前必读）**：
> - **关闭自动连边**：导入走 `auto_link=False`，批量记忆之间**不建跨记忆关联**（keeper 的图谱/连边能力在导入场景被刻意关闭，避免大批量灌入产生噪声边；如需连边，导入后用 `graph --build` 显式建）。
> - **编码**：仅支持 **UTF-8 / UTF-8-BOM / GBK**（Excel「UTF-8 带 BOM」导出可被正确剥离 BOM；GBK 为 Excel 常见导出编码）。其他编码（UTF-16 / ISO-8859 等）直接报清晰编码错误并中止，**不会静默丢数据**。
> - **`--on-error abort` 语义**：仅对**真实写入错误**（deposit 抛异常）中止并保留已写入；命中 secrets 被**隔离（quarantine）**是成功的安全结果，**不触发 abort**，后续记录继续导入。
> - **丢弃可见**：非字典 / 缺 `summary` 且无 `body` 的记录无法归一化，计入 `dropped`（带 `dropped_reasons`），不再无感知丢弃；返回含 `total_parsed / normalized / dropped / imported / quarantined / errors`。

## 读取 / 召回

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `recall` | 语义召回（**`--max-tokens N`**·注入预算裁剪；**`--roots a,b`**·多库交叉召回带 source_root） | `--query/--tag/--category/--scope/--domain/--subdomain/--scene/--deep/--touch`；`--ann`(加速)/`--cluster-boost`；**`--include-auto`**（向后兼容，**默认已包含** auto_sourced 被动捕获暂存项）；**`--exclude-auto`**（显式排除，仅确需严格 staging 隔离时用）；**`--with-meta`**（返回 `meta`：`backend`/`configured_backend`/`fell_back_to_lexical`/`empty_hint`，让 AI 无需手动跑 `doctor` 即知语义后端是否降级）；**`--filter`**（DSL，字符串字段新增 `state/priority/area/about_axis` 支持 `=`/`!=`，如 `about_axis=user`、`priority=high`）；**`--max-age-days N`**（只返 ≤N 天条目，自动尊重 `until:` 标签过期；兼容 `2026Q4`/`2026.12.31`/`2026-12-31`）；**`--hops N`**（沿关系边图扩展召回，把相关联记忆补进结果，`score=0.3` 排末尾）；**`--answer`**（答案合成 RAG：HyDE 改写 + LLM 合成 + 来源引用；无 LLM/合成失败时优雅降级 → 返回 `{"ok":true,...,"answer_error":<原因>,"entries":[…]}`，仍带召回条目）；**`--as-of YYYY-MM-DD`**（**双时序回溯查询**：只返回「该时点上仍为真」的记忆，按 `valid_at`/`invalid_at` 判定、**绕过 status** —— 否则今天已 superseded 的记忆在过去时点永远查不到） |
| `tree-view` | 记忆树状概览 | — |
| `summary-index` | 索引摘要 | — |
| `dashboard` | 生成单文件可视化 HTML（记忆树 + 聚类 + 矛盾高亮 + 召回策略） | `--out` |
| `explain` | 调试：分解单条记忆的排序/召回 why 信号（importance/relevance/decay/召回频次/reason/元信息）；纯只读，缺失返回 `not_found` | `--id <id>` |
| `timeline` | 记忆时间线：`--id` 版本链+访问历史；`--query [--days/--limit]` 主题脉络 | — |
| `audit-log` | 变更审计：查看 store/audit.log 尾部写操作记录（deposit/delete/overwrite/archive/confirm/reclassify 等），追溯「谁在何时改了哪条」 | `--top N` / `--filter-op deposit` |
| `stats` | 可观测性：从 `recall_counts.json` 汇总召回热/温/冷分布（hot≥5 / warm 1-4 / cold 0）、Top 高频记忆（带 summary）、库活跃/归档规模；只读、零模型依赖 | `--top N`（默认 5） |

### timeline（记忆时间线）使用指引

`timeline` 回溯单条记忆的**版本演化链**与**访问脉络**，或按主题拉出时间排序的脉络线，适合复盘一个想法/结论的演化轨迹。

- **版本链（单条记忆演进）**：
  `python scripts/memory_ops/__init__.py timeline --id LRN-20260730-006`
  返回该记忆历次 `overwrite`/`rollback` 的版本节点 + 最近访问时间，定位「何时被改、改成啥」。
- **主题脉络（按 query 拉时间线）**：
  `python scripts/memory_ops/__init__.py timeline --query "84日均线仓位" --days 180 --limit 20`
  按相关度+时间排序返回该主题下记忆的创建/修改脉络。
- **参数**：`--id`（版本链）｜`--query`（主题脉络，配合 `--days N` 限制时间窗、`--limit N` 限制条数）。
- ⚠️ `--query` 模式依赖语义后端（fastembed/online）；lexical 下退化为按时间排序的粗召回。

### recall（语义召回）使用指引 + `--filter` 实战示例

`recall` 是核心读入口；`--filter` 是**硬过滤 DSL**（在相关性 top-k 之后裁剪，0 违反语义），适合「只捞某类」而非「全量枚举」——要拿全集请用 `export` 或直查 `store/index.db`。

**`--filter` 字段与算子（已落地，禁用 eval/exec，字段白名单）**
- 字符串字段（仅 `=` / `!=`）：`scene` `domain` `subdomain` `tag` `type` `state` `priority` `area` `about_axis`
- 记忆级数值字段（`> >= < <= = !=`）：`importance` `confidence` `access_count` `age_days` `relevance_score` `thermal_weight`
- 投资结构化 attrs 数值（`> >= < <= = !=`，含中文别名归一：`夏普→sharpe`、`回撤/最大回撤→maxdrawdown`、`动量→momentum`）
- 连接符：`AND` / `OR`（左结合、无括号优先级）；非法字段/语法**报错不静默**

**可复制示例**
```bash
# 1) 四轴硬过滤：只召回「关于用户本人」的记忆
python scripts/memory_ops/__init__.py recall --query "召回排序" --filter "about_axis=user"

# 2) 状态机 + 优先级组合
python scripts/memory_ops/__init__.py recall --filter "state=active AND priority=high"

# 3) 记忆级数值阈值：只返重要性 ≥ 0.7 的
python scripts/memory_ops/__init__.py recall --filter "importance>=0.7"

# 4) 投资因子（中文别名自动归一）：夏普≥1.5 且 最大回撤≤-10%
python scripts/memory_ops/__init__.py recall --filter "夏普>=1.5 AND 最大回撤<=-0.1"

# 5) OR 多域：投资或金融域都捞
python scripts/memory_ops/__init__.py recall --filter "domain=investment OR domain=finance"

# 6) tag 包含判定（未引号值可含冒号）
python scripts/memory_ops/__init__.py recall --filter "tag=st:verified"

# 7) 新鲜度 + 子域硬过滤组合
python scripts/memory_ops/__init__.py recall --query "调仓" --max-age-days 30 --filter "subdomain=rebalance"
```
> 注：`tag` 走「包含判定」（如 `tag=st:verified` 命中任何含该 tag 的条目）；其余字符串字段走顶层相等。数值字段缺省即该子句 False（不报错）。

## 整理 / 进化

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `reflect` | 自我改进引擎 `--auto`：去重/纠错/分类复评/晋升/衰减归档；**绝不删除**。`--undo`反向还原自动重分类：扫描 `accessed_from` 的 `auto_reclassify_type` 改动并回滚 category/type 到原值（dry-run 不落盘） | `--auto/--llm(可选)/--no-auto-archive/--undo` |
| `doctor` | 体检 + `--fix` 自动修；`--contradictions` 主动矛盾扫描（**需神经后端**）；`--arbitrate` 强矛盾自动仲裁 | `--fix/--contradictions`；**`--arbitrate`**（须同时带 `--contradictions --fix`：对 score≥0.78 的强矛盾对自动把旧/低置信条标 `superseded`，**只标不删可 rollback**；配 `--dry-run` 仅预览）。⚠️ **离线（无 LLM）真实仲裁被禁止**：无 `KEEPER_LLM_*` 时 `doctor --arbitrate`（非 dry-run）直接拒绝返回错误提示，仅 `--dry-run` 可预览候选；注入 LLM 后须**逐对确认真矛盾**才标旧（非矛盾候选一律跳过） |
| `decay` | 基于重要度/时间/访问/类型权重的确定性衰减（默认 dry-run 预览）。`--incremental`（大库触发）仅重算自上次 decay 以来被访问（accessed 字段）的记忆，冷记忆保持原值；无基线自动退化为全量 | `--apply/--decay-lambda/--incremental` |
| `recurrence` | 确定性重复模式簇（category+summary 归一化，可复现） | `--min-count`；**`--auto-candidate`**（额外标「跨≥2任务+30天」组为晋升候选 `promotion_candidate=True`） |
| `evolve` | 自主进化：把反复印证（recurrence≥阈值）的经验提炼成可复用原则（`provenance=auto`、限期复核 `review_by=+30天`）；LLM 信号保持 review-only | `--dry-run`（预览候选，默认）/ `--apply`（落盘，生成 `type=principle` 记忆并 `derived_from` 溯源；原记忆只降权不删） |
| `forget` | 显式判错并归档：把某条记忆标 `erroneous=True`、`belief_strength=0`，停止召回、永不静默删内容（区别于 `delete` 物理删除） | `--id <id> --forget-reason "<原因>"` |
| `rebuild` | 索引损坏时扫两处目录重建。**顺带回收派生文件幽灵键**（`route_registry.json` / `recall_counts.json` / `maintenance_dirty.json` / `clusters.json` 里指向已删除记忆的残留键——这些派生文件只增不减，真库实测 426 键 vs 真实 226 条）→ 返回体含 `pruned` 明细。🔴 安全阀：真实 id 集合为空（索引不可读/库空）时跳过回收，**绝不误清空** | — |
| `reclassify` | 显式重分类 + 强学习进分类器 | `--type/--scene/--reason/--yes`；**`--pending`**（数据质量队列：列出缺 scene/about_axis/domain 标注的活跃记忆，只读；配 `--suggest` 给保守场景建议，仅提示不写盘） |
| `export-rules` | 行为规则层：选已确认/高频条目 → 固化进目标规则文件（自动生成区块+备份回滚）。可选目标：`project` (./AGENTS.md，WB 生态) / `user` (~/.workbuddy/AGENTS.md，全局) / `copilot` (./.github/copilot-instructions.md，GitHub 官方 Copilot 指令自动加载位置) / `claude` (./CLAUDE.md，Anthropic 官方约定) / `text`（--out 任意路径，标题中性 `# Agent Instructions`，零平台耦合） | `--rules-target project\|user\|copilot\|claude\|text` / `--out <路径>`（text 必填，其它可选）/ `--dry-run`；`--filter` 仅支持 `state/priority/area/about_axis/domain/scene/subdomain/tag/type` 及投资数值 attr（**不支持 `category`/`tier`**） |
| `export` | 标准格式导出：除 zip 备份外，提供 Markdown / JSONL / learnings 导出，增强跨工具可移植性。learnings 为标准化可读条目（date/trigger/lesson/recurrence_count/status），`--out <目录>` 时每条记忆一个文件便于 git diff。⚠️ **默认仅导出 `active`**（superseded / archived 静默跳过，会在 stderr 打印 HINT 并在返回值给出 `filtered_out` / `hidden_superseded` / `hidden_archived`） | `--format md\|jsonl\|learnings`（默认 md）/`--out <路径>`（不指定则 stdout；learnings 建议给目录）/`--include-superseded`（追加被取代项）/`--include-archived`（全量：archived+superseded） |
| `hot-rules` | 列出 recurrence≥阈值 的高频条目（候选固化） | `--min-count` |
| `import-rules` | 规则文件自动区块逆向回灌 SQLite（仅新条目） | `--rules-target project\|user\|copilot\|claude\|text` / `--out <路径>`（text 必填） / `--dry-run` |
| `extract-skill` | 把高频/已确认经验萃取为可复用 skill 脚手架（SKILL.md + references/patterns.md + hooks/ + README.md），每条 pattern 反向带源记忆 id 便于溯源；复用 `promote_rules` 规则聚合，默认不调 LLM | `--min-count`（默认 3）/`--out-dir`（默认 `auto_skill`）/`--llm`（可选） |
| `quickstart` | 极简上手指引：返回「三句话触发 + 新能力一句话触发」文本，给不想读长文档的用户 | —（无参数，直接打印） |

> ⚠️ **`error_hook` 仍是独立脚本**（位于 `scripts/error_hook.py`，需 `python scripts/error_hook.py --dry-run --sample "..."`），不是 `memory_ops.py` 子命令——敲 `memory_ops.py error_hook` 会报 `invalid choice`。而 **`skill_extract` 已接入为 `extract-skill` 子命令**（也可直接 `python scripts/skill_extract.py --root <store> --min-count 3 --out-dir auto_skill`），二者等价，推荐走 `extract-skill`。

## 高级能力（图谱 / 蒸馏 / 画像 / 矛盾仲裁）

> 全部走「只标不删」铁律：图谱/蒸馏/仲裁只新增关系边、降权或标 `superseded`，**绝不物理删除记忆**；所有写操作支持 `--dry-run` 预览。

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `graph --build` | 记忆图谱自动建边（离线规则 + 可选 LLM 精化）：扫描共享标签/域/类型自动推断 `supports/refutes/is_a/part_of` 关系边，幂等、只标不删 | `--dry-run`（仅预览会动哪些边，不写）；LLM 走 `KEEPER_LLM_*` 注入（无则纯规则） |
| `graph --clean` | 清理关系键中指向**已删除记忆**的悬空引用（如被 `delete` 的记忆留下的反向边）；只删无效 id 字符串，**不删记忆文件、不改 status** | `--dry-run`（仅预览会清哪些引用，不写） |
| `graph --rebuild` | 图谱**干净重算**：先 `graph --clean` 清悬空 + 清空图衍生边（supports/refutes/is_a/part_of）+ 重新推断；用于消除历史 noise 边（如未经授权的 `graph --build` 累积） | `--dry-run`（仅预览，不写） |
| `distill --review` | 原则蒸馏候选**离线预览**（按 (domain,type) 硬门 + 簇内相似度≥0.85 + 簇规模≥3 选候选簇），不写任何记忆 | —（默认即 review；`--apply` 才真写） |
| `distill --apply` | 原则蒸馏落盘：沉淀 `type=principle` 记忆并 `relations.derived_from` 溯源；原记忆**只降权不删**（`importance*0.7`、`confidence*0.85`） | 需 LLM（走 `KEEPER_LLM_*`）；`--dry-run` 仅预览 |
| `profile` | 离线用户画像：类型/域/轴分布 + 近 30 天重心 + 擅长/薄弱 Top（不跨域泄漏，画像项标 domain） | — |
| `distill-to-wb` | 把 keeper 高层原则**单向蒸馏回流**到 WorkBuddy 记忆（互补而非镜像）：幂等去重 + 反回声守卫（`KEEPER_DISTILLED_SENTINEL`），已回流的不重复写 | `--dry-run`（预览候选，默认）/ `--apply`（落盘回流） |
| 🔀 **`distill-to-wb` vs `to-l2` 怎么选**（二者常混淆，命名相近但流向完全不同） | | |
| → `distill-to-wb` | **keeper → WorkBuddy 记忆「直写回流」**：把沉淀好的高层原则直接写进 WB 用户级记忆，使其变成 AI 的「长期人设/偏好」，下次对话自动注入。**单向、幂等、带反回声守卫**，已回流的不重复写。适合「让 AI 真正记住这条原则并主动遵循」。 | `--dry-run`（预览候选，默认）/ `--apply`（落盘回流） |
| → `to-l2` | **keeper → Layer2「草稿导出」**：只生成一份高价值经验草稿（默认不写盘，仅预览），供你审阅后再决定是否并入 WB/项目记忆。**不直写任何外部记忆**，纯导出。适合「我先看看哪些值得带走，再手动定夺」。⚠️ **属 `mem_bridge.py` 子命令，不是 `memory_ops.py` 的 op**：`python mem_bridge.py to-l2 ...` | `--min-importance`（默认 **0.7**）/ `--min-access`（默认 3）/ `--export <库内路径>`（写盘，禁写库外） |
| 一句话区分 | `distill-to-wb`=「自动把原则塞进 AI 脑子（直写）」；`to-l2`=「把经验打包成草稿给你看（导出）」。前者改 WB、后者不改任何外部文件。 | |
| `recall --hops N` | 图扩展召回：沿关系边把相关联记忆补进结果（`score=0.3` 排末尾，保留 RRF 排序） | 配合 `--query` |
| `recall --answer` | 答案合成 RAG：HyDE 改写 + LLM 合成 + 来源引用；无 LLM/合成失败时优雅降级，返回 `{"ok":true,...,"answer_error":<原因>,"entries":[…]}`（answer_error 非 None 即降级，仍带召回条目） | 配合 `--query`；需 LLM 时走 `KEEPER_LLM_*` |
| `deposit --why "<理由>"` | 记录决策理由，随 `recall` 暴露（字段 `reason`），便于复盘回溯推理链 | — |
| `doctor --arbitrate` | 强矛盾自动仲裁：须同时带 `--contradictions --fix`，对 score≥0.78 的强矛盾对把旧/低置信条标 `superseded`（只标不删可 rollback） | `--dry-run` 仅预览 |

## 分析 / 体检

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `report` | 健康摘要：衰减 λ / 校准计数 / 分层概览 / 类型·域分布·覆盖盲区·有效热度 + 召回策略 | — |
| `audit` | 能力体检 + 开关顾问（只读）：按库规模/环境给每个可选功能的开启/关闭建议 | — |
| `cluster` | k-means 主题聚类 + 建议标签（**需神经后端，且 ≥8 条已嵌入记忆**） | `--apply/--max-k` |
| `token-report` | 全库 token 用量盘点 | `--top-n` |
| `benchmark` | **性能基准**：隔离库上批量 deposit N 条测写入吞吐 + 随机 recall M 次测 p50/p95/avg 时延与空召回率，输出 JSON 报告。默认 `ann=False` 全量扫描基线（确定可复现），`--ann` 走 ANN 加速测大库提速比。**必须显式 `--root <隔离目录>`**（禁止对默认真实记忆库跑，否则写入合成记忆污染召回） | `--root <隔离目录>`（必填，非默认）/`--n`（默认 200）/`--recall-times`（默认 50）/`--top-n`/`--ann`/`--topics`（默认 20）/`--out <json路径>` |
| ⚠️ `working`（**mem_bridge 命令，非 memory_ops**） | 查看 working 层待蒸馏记忆：列出尚未回流到 L2 的活跃经验（只读，辅助决定是否 `distill`）。**经 `python mem_bridge.py working` 调用**（不放 `--root`，改用 `AI_MEMORY_STORE` 环境变量 / 注册表指向目标库），不进 `memory_ops.py commands` 清单 | `--top N`（默认 20） |
| `verify-investment` | 投资记忆闭环校验：从 DuckDB 复算数值校验投资记忆（fail-open：库不可用时只告警不阻塞）；`needs_setup` 显式引导 bootstrap（返回 `default_sql_map_template` + `setup_hint`） | `--duckdb <路径>` / `--sql-map <json>`（每条 metric 对应一条返回单值的 SQL） |

## 系统 / 运维

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `init` | 建目录 + 空索引（幂等） | — |
| `backup` / `restore` | 整库 ZIP 备份 / 恢复；`restore` 接受 `--zip <路径>` 或位置参数 `<zip路径>` | `backup --zip <路径>`；`backup --keep N`（**只保留最近 N 份**，更旧的**同卷搬离**到同级 `_retired_*` 目录——不删除、可逆）；`restore <zip路径> --yes`（可选 `--verify`：恢复后校验条目数与索引/文件一致性，不一致则报错退出） |
| `release-audit` | **发布账本核对**：把 `CHANGELOG.md` 记录的版本集与 SkillHub 平台真实发布的版本集对账，回答「**线上到底发到几版**」——多机并行时防「双主」（另一台机器发了版、本机不知情）。drift **只认两类**：平台有日志无 / 本地落后线上；`bundled`、`unreleased_local` 仅提示 | `--offline`（只做本地自检，输出「无法判定一致性」）。退出码：`0` 一致 / `2` 漂移 / `3` **未知**（断网、超时就是 3，**不是**出错） |
| `schedule_reflect` | 输出每日/每周 reflect 自动化配置（不偷偷建任务） | `--freq/--at` |
| `llm-setup` | 可选 LLM 自进化配置（默认关，本地 Ollama 优先） | `--enable-llm`（配 `--backend/--model/--base-url`；`--disable-llm` 关闭） |
| `list_quarantine` | 列出 `deposit` 命中 secrets 被自动隔离的待复审候选（含 qid） | — |
| `review_quarantine` | 隔离复审：`--action release`(脱敏放行入活跃库)/`purge`(删除隔离文件)/`keep`(标记已复审保留)；`--no-redact` 关脱敏 | `--id <qid> --action release` |
| `archive`（单条软删归档，`memory_ops`） | 把**指定 id** 的记忆软删为已归档（沉到 archive/，永不删除，可 unarchive 找回）；取代物理删除。**非批处理、无 IMA 镜像参数** | `archive --id <id>`（指定归档）；`archive`（缺 --id 仅预览）；`archive --dry-run`/`--yes` |
| `reclaim`（批处理归档清理+IMA镜像，`memory_ops` **独立 op**） | 180 天沉淀/超额记忆**批量软删为已归档** + 重生成 IMA 导出（带【归档】标记）；**两次运行冷却**防手滑。**`reclaim` 是独立 op，并非 `archive` 别名**（二者底层同 `archive_sweep`，但命令名各自注册）。一键批处理封装见 `keeper_setup.py archive` | `reclaim`（默认只读预览）；`reclaim --apply`（仅归档冷却候选，绝不删）；`reclaim --no-mirror`（归档后不重生成 IMA 导出）；`reclaim --include-quarantine`（纳入未复审隔离，默认关）。一键：`python scripts/keeper_setup.py archive [--apply\|--review]` |
| `schedule_self_heal` | 脱离 WorkBuddy 的自调度：输出 systemd service+timer 与 crontab 片段（每日 reflect / 周日矛盾扫描 / 每月1号 decay / 可选每月2号 rebuild），非 WB 环境也能低频自愈 | `--at HH:MM` / `--with-rebuild` / `--cron`（导出片段，不偷偷建任务） |
| `self-heal` | 统一自治循环：合并 reflect/evolve/decay/doctor/skill-sync/export-rules 的默认全开维护（dirty 驱动，脏时/每日跑；每月1号 decay、周日矛盾扫描；`--force` 全量；`--discover` 自动发现新集群建 skill）；收尾清空脏标 + 四源版本对齐自检 | `--force`（强制全量）/ `--discover`（自动建未覆盖集群的 skill）/ `--dry-run` |
| `mcp` | **MCP 服务**：把 keeper 暴露为标准 MCP 服务（JSON-RPC 2.0 over stdio，零外部依赖），供任意标准 MCP 客户端连接；暴露工具 `deposit / recall / doctor / stats / export`（export 支持 `limit` 截断防大库撑爆缓冲）。长驻进程，**在 `_store_lock` 之外拉起**，避免服务内部 deposit/recall 自锁死；由 MCP 客户端拉起（父子管道通信），非交互命令 | `--root`（客户端配置里指向本服务即可，无需手敲） |

> ⚠️ **`mcp` 服务行为边界（接入前必读）**：
> - **`export` 截断语义**：`fmt=jsonl` 按行截断（每行独立 JSON 记录，安全）；`fmt=md` 按 `## ` 记忆块截断，**不会切断单条记忆中间**破坏格式。大库建议显式传 `limit`，避免整库 dump 撑爆客户端缓冲（O4）。
> - **secrets 处理差异**：MCP `deposit` 命中 secrets 默认 **`raise`（拒绝写盘，fail-closed）**——比批量 `import` 的 `quarantine`（隔离落盘）更严；客户端收到结构化错误而非静默隔离。
> - **错误形态**：所有工具异常返回**结构化 JSON** `{"ok":false,"error":<异常类型>,"message":<文本>}`，便于客户端程序化判断，不再 cryptic `error: <e>`（O3/C5）。
> - **暴露面**：服务可读写目标库全部记忆；仅应在可信本地/本机客户端（Claude Desktop / Cursor）连接，勿对不可信网络暴露。

> 守护进程（`keeper_daemon/daemon.py`，`python -m keeper_daemon` 启动）：已提供 `/health`、`/stats`（无 token，仅 127.0.0.1 本机）、`/recall`、`/quit`（token 校验）。`POST /deposit`受认证端点默认关闭，需 `KEEPER_DAEMON_ALLOW_DEPOSIT=1` 且请求头 `X-Token` 与守护 token 一致，支持程序化捕获。

> ⚡ 性能（opt-in）：设 `KEEPER_EMBED_DISK_CACHE=1` 开启用户级 SQLite 嵌入向量缓存，跨 CLI 进程 / 跨 store 复用、省去重复模型加载（尤其 fastembed 首次需加载约 90MB 模型权重）；默认关闭，用户默认路径零风险。`KEEPER_EMBED_DISK_CACHE_DIR` 可自定义缓存目录。⚠️ 缓存落「记忆文本派生的向量」于用户目录（明文），仅建议本地可信环境开启。

> 📦 归属提示：`inject_stats`（查看自反馈注入闸门状态：每日上限/已用、去重开关/窗口、已追踪条数）以及 `taxonomy`（分类体系校验/重分类）**不属于 `memory_ops` CLI**，而是根目录 `mem_bridge.py` 的独立子命令，需经 `python mem_bridge.py <cmd>` 调用（同样不入 `memory_ops commands` 清单）。mem_bridge 族命令在此仅列 `inject_stats` 作为引子，完整用法见 `mem_bridge.py --help` 与 `references/MEM_BRIDGE.md`。

> 🧹 **一条收口卸载**：`python scripts/keeper_setup.py uninstall`——一次性停钩子 + 停守护进程 + 移除定时调度。**默认 dry-run**，逐项列出将要做的事，加 `--yes` 才执行；`--purge-env` 才清环境变量（`KEEPER_*` / `AI_MEMORY_*`）。详见 `references/COOKBOOK.md` §10。

### 🔄 独立脚本：`scripts/keeper_sync.py`（跨设备同步）

> **不属于 `memory_ops` CLI**，需 `python scripts/keeper_sync.py <op>` 调用。
> 用途：多台电脑各有一份本地记忆库时搬库。**不要裸用 `export` + `import`**——后者有 5 个静默坑（**详见 CHANGELOG 相关条目**），本脚本已全部封死。

| op | 作用 | 关键参数 |
|---|---|---|
| `out` | 导出**全量**同步包（active+superseded+archived，jsonl 保真）+ `meta.json`（条数 / sha256 / 源机 / 时间） | `--dest <目录>`（必填）/`--root`（默认真实库） |
| `in` | 导入同步包：sha256 校验 → 预演新增/覆盖条数 → 落盘前自动备份 → 导入 → **状态收敛** → 幂等自校验 | `--file <jsonl>` 或 `--dir <目录>`（自动取最新包）/`--execute`（**默认仅预演**）/`--no-keep-ids`（危险：配 `--execute` 会 rc=8 拒绝，须再加 `--i-know-id-bloat`）/`--allow-unverified`（缺 meta 时的逃生）/`--no-backup`/`--on-error` |

**三条铁律（脚本强制）**：
1. **必须 `--keep-ids`** —— 不带时每次导入都生成新 id，库会 19→38→57 无限膨胀（实测）。
2. **同步是单向的**（包 → 目标库，后导入者为准）。同一轮里 A→B 又 B→A 会互相回滚；要双向就在 B 机干完活 `out` 后回 A 机 `in`（环形可行，实测 20 条零漂移）。
3. **落盘前自动备份**目标库为 `<store>_bak_<时间戳>`。

**为什么导入后还要「状态收敛」**：`deposit` 一律写 active 到 `memories/`，而 archived 住在 `memories/archive/` 且不被同 id 覆盖 → 会同时产生**状态丢失**（superseded/archived 复活）与**双份副本**（实测 19 条库导入 20 条包后变 26 条）。收敛逻辑会删重复副本、把 archived 归档回去、把 superseded 标回去。

**同步后三层数据一致性**（实测 6/6 通过）：`memories/*.json` ↔ `memories/archive/` ↔ `store/index.db`(SQLite) 条数与 id 完全一致，目标库语义召回与 `doctor` 均正常。

## Python API（非 CLI，AI 内部调用）

`settle_probe` / `render_cold` / `touch` —— 这些是对话/检索管线的内部 API，命令行不可直接调用。`touch`（显式刷新某条记忆的 accessed 时间戳，记录「被真正使用」的上下文证据；由 `recall --touch` 触发，读操作默认不写盘）即内部 op，不进 `memory_ops.py commands` 清单，也无需用户手动调用。

> ⚠️ 历史 `recall_v30` / `reflect_v30` / `classify_type_v30` / `purge_forgotten` 等旧引擎函数已清理（从未接入 CLI，纯死代码），**请勿在文档/脚本中再引用**。真遗忘路径统一为 `decay`（降权）+ `reflect --auto`（归档），不提供批量硬删命令。

---

## 常见命令真实返回样例（实跑抓取，非编造）

> 下面是**真实命令行输出**（对隔离临时库实跑抓取）。为可读做了**截断标注 `…`**；凡涉及密钥 / 凭证均**脱敏为占位符**。本机若设了 `AI_MEM_EMBED_BACKEND=lexical`，`embedding_status` 会是 `lexical_degraded`，属正常（详见 `SKILL.md`「红线与边界」B1）。
> 想看每步怎么跑：`python scripts/memory_ops/__init__.py <op> --help`。

### `init` — 首次建库
```json
{"ok": true, "store": "<记忆库根目录>", "note": "记忆目录已就绪，零配置开箱即用。你不用手动敲命令——用自然语言告诉 AI「记一下…/整理一下今天记的」即可……"}
```

### `deposit` — 写一条记忆
```json
{"ok": true, "id": "LRN-20260912-001", "embedding_status": "lexical_degraded"}
```
```
⚠️ [classify_review] 高重要度记忆经自动分类且置信偏低（scope_via=auto conf=0.50 / scene_via=rule conf=0.65 / type_explicit=False conf=0.80），建议显式指定 --scope/--scene/--type/--domain 以固化分类，避免重要经验被错分。

```
### `recall --query "…"` — 召回
```json
{"ok": true, "count": 1, "entries": [
  {"id": "LRN-20260912-001", "category": "best_practice",
   "summary": "示例经验：发布前先跑门禁再上传",
   "tier": "working", "status": "active", "importance": 0.7,
   "scene": "release", "domain": null, "body": "发布 skill 前务必先 --dry-run 复跑全量门禁……",
   "score": 0.3134,
   "why": {"sem": 0.4772, "rec": 1.0, "conf": 1.0, "final": 0.3134}}
]}
```
> 返回里 `score` / `why` 是召回打分拆解（与 `explain --id` 同源）；`embedding_status` 会在 stderr 一并给出（降级时不报错，需主动看）。

### `audit` — 能力体检（只读）
```json
{"ok": true, "audit": {"ok": true, "root": "<记忆库根目录>",
  "environment": {"n_memories": 1, "embedding_backend": "lexical",
    "llm_enabled": false, "ima_kb_configured": false},
  "features": [
    {"id": "neural", "name": "神经语义召回（真·同义/改写理解）",
     "status": "off", "recommendation": "enable", "priority": "high",
     "reason": "检测到已装 fastembed 但未启用；开启后中文换个说法也能召回。",
     "how": "设 AI_MEM_EMBED_BACKEND=fastembed 后重开进程即可。"},
    {"id": "ann", "name": "ANN 近邻加速", "status": "off",
     "recommendation": "keep", "priority": "low",
     "reason": "记忆仅 1 条（<阈值 50），线性扫描更快更准。"}
    // … 其余 feature（cluster/dashboard/contradiction/meta 等）依库规模给 keep/optional
  ]}}
```

### `doctor` — 就绪自检（只读）
```json
{"ok": true, "doctor": {
  "entries": 1, "files": 1, "corrupt_files": [], "orphan_files": [],
  "index_without_file": [], "missing_files": [], "status_mismatch": [],
  "embed_backend": {"backend": "lexical", "configured": "lexical",
    "fell_back_to_lexical": false,
    "model_detail": "lexical 模式无模型依赖",
    "coverage": {"active": 1, "with_embedding": 1, "rate": 1.0}},
  "hooks": {"registered": ["PostToolUse/post_tool_use_error_capture.py",
    "Stop/memory_auto_capture.py", "PreCompact/memory_auto_capture.py"],
    "missing": [], "mode": "silent"},
  "scheduler": {"platform": "win32", "tasks": [ /* … */ ]}
  // … 其余字段（recommendations / contract / investment_invariants 等）略
}}
```
> 🔴 排查召回变差就看这里：`embed_backend.fell_back_to_lexical` 为 `true` = 语义后端挂了、已静默降级（B1 红线）；`coverage.rate` 应为 `1.0`。
