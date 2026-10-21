# 投资回测记忆能力圈（4 层模型）

> keeper 原生支持投资域（`KNOWN_DOMAINS` 含 `investment`）。本文件讲如何把 keeper 用作
> **量化投资回测的体系化记忆系统**——让做大量回测的人，把「数据/参数 → 因子 → 因子测试 → 组合系统」
> 四层对象都记下来、关联起来、可回溯、可比较。
>
> 全部用本技能内置命令即可。批量建 L0 有两层入口：统一桥接入口 `python scripts/investment_bridge.py seed --domain investment`（包装下面的实现并顺带对齐遗留 `sub:` 标签），或直接调实现脚本 `python scripts/investment_seed.py`。
> 命令参考见 `references/COMMANDS.md`；模板见 `references/investment_templates.md`；
> 分类树种子见 `references/investment_taxonomy.json`。

## 为什么是 4 层（你的原话提炼）

| 层 | 记忆对象 | 必须用记忆的原因 |
|---|---|---|
| **L0** | 数据库每个字段/参数/数据 | 随时可能成为某因子的原料；不登记就记不住「这因子吃了哪列、单位对不对、新鲜度」 |
| **L1** | 每个因子实体（定义/构造/吃哪些数据/验证结论） | 因子是回测最小可复用单元，独立成实体、可检索、可演进 |
| **L2** | 一个因子的若干轮测试（配置/指标/结论/通过与否） | 因子要迭代很多次，每轮留痕才能回溯「为什么 IC 从 0.05 改成 0.17」 |
| **L3** | 因子组合出的新系统（加权/正交/条件 + 回测结果） | 因子最终拼成系统，组合方式与系统级回测本身是高价值记忆 |

## 统一约定（务必遵守）

- **域**：一律 `--domain investment`（keeper 原生域，与文档/默认一致）。
- **子域**：用**原生 `--subdomain` 字段**（索引已修复，recall 精确召回可靠）：

  | 子域 | 层 | 含义 |
  |---|---|---|
  | `data_catalog` | L0 | 数据/参数注册表 |
  | `factor` | L1 | 因子实体 |
  | `factor_test` | L2 | 因子测试迭代 |
  | `system` | L3 | 组合/系统 |
  | `data_integrity` | 横切 | 数据正确性（前视/值域/单位/对账） |
  | `backtest_integrity` | 横切 | 回测正确性（滑点/手续费/权重敏感性/过拟合） |

  > 旧版用 `sub:` **标签**约定（如 `sub:risk_control`），现统一改用原生 `--subdomain` 字段。
  > 存量 `sub:` 标签已在适配时统一改名为 `topic:`（保留子主题信息，避免与保留字命名空间冲突）；新记忆直接用 `--subdomain` 即可——`deposit` 会自动把子域镜像成 `sub:<subdomain>` 标签，`mem_bridge seed` 负责遗留对齐。

- **数值指标**：用 `--attr`（正文里写「IC 0.17」也会被白名单自动抽取，见下）。可用指标名（白名单）分两类：
  - **通用基线**（keeper 原生）：`pe`/`pb`/`roe`/`eps`/`sharpe`/`maxdd`(最大回撤)/`turnover`(换手)/`momentum`/`vol`/`return`/`winrate`/`valuation`/`position`/`leverage` 等；
  - **因子测试核心量**（投资能力圈）：`ic`(信息系数)/`ir`(信息比率)/`alpha`/`cagr`(年化)/`sortino`(索提诺)/`exposure`(暴露)/`redundancy`(冗余)/`hitrate`(命中率)/`tvalue`(t 值)。
  - 自定义数值指标（如 `scale`/`w_A2`/`w_comp4`/`pass`/`ic_oos`/`sharpe_oos`）显式 `--attr` 可直接写（仅校验「键非纯数字/日期类」），但**不会**被正文自动抽取——自动抽取只认上面白名单。
  例：`--attr ic=0.17 ir=2.3 scale=0.06 sharpe=1.8`。正文里写「IC 0.17」也会被自动抽取。
  > ⚠️ `--attr` **只接受数值**；单位/频率/数据源等字符串维度请用标签（`unit:元`/`freq:日`/`mcp:ifind`），
  > 否则报「--attr 值需为数字」。标签支持 `key:value` 式，`recall --tag mcp:ifind` 可精确召回。

- **生命周期**（强制 `st:` 标签）：`draft`(设计) → `validating`(测试中) → `verified`(通过) → `deprecated`(推翻)。
  新测试推翻旧结论：`link <旧测试ID> superseded_by <新测试ID>`，旧测试自动标记 `superseded` 并进入回收计时。

- **类型化关联**（跨层串链路，`link` 允许类型）：
  - `consumes`：因子 → 它依赖的 L0 数据/参数（`link <因子ID> consumes <L0字段ID>`）
  - `test_of`：测试 → 被测因子（`link <测试ID> test_of <因子ID>`）
  - `composed_of`：系统 → 组成因子（`link <系统ID> composed_of <因子ID>`）
  - `validated_by`：系统/因子 → 支撑它的已通过测试（L3→L2 闭环证据；建议 verified 因子/系统都挂 ≥1 条 `validated_by` 的通过测试，避免「经验证」无证据链）。
  - `audits`：正确性结论 → 被审计的具体因子/系统/数据（横切域 data_integrity/backtest_integrity 用此挂回具体层，使正确性结论可溯源）。
  - 已有：`see_also` / `superseded_by` / `corrected_by`
  - 可视化：`python scripts/investment_bridge.py graph --around <ID>` 画出「数据→因子→测试→系统」全链路。
  - 注：`composed_of` 允许跨层引用因子（如系统直接由因子组成、跳过 L2），属有意设计；链路可视化同样呈现。

## 召回路由须知（重要）

投资记忆的「精确路由」靠 `--subdomain` **标志**，不是 `--filter` DSL 的子域写法：

- **语义召回（日常用）**：`recall --domain investment "<query>"`
  `--domain` 是**软优先级**（投资域被提权），但仍会带少量语义相近的跨域记忆（work/skill 等）——这是设计行为，不是 bug，召回结果按相关性排序，投资记忆排在前面。
- **严格按子域枚举**（两种写法等价，均已实测 0 泄漏）：
  - 标志路径（推荐，最直观）：`recall --subdomain factor "<query>"`
  - 等价的 DSL 写法：`recall --filter "subdomain=factor"`（与 `--subdomain` 标志返回完全相同的集合）
- **严格按域过滤**：`recall --filter "domain=investment"`（硬过滤，0 违反），但仍是相关性 top-k 召回，**不是全量枚举**；要拿全集请用导出或直查 `store/index.db`。

> 一句话：日常语义用 `--domain`；要干净地按子域捞，用 `--subdomain` 标志（或等价的 `--filter "subdomain=..."`）。

## 自然语言示例

说"记一条因子 A2，均线斜率，scale 0.06 时 IC 0.17，吃 unified_market 的日行情表，状态已验证"，AI 走：
```bash
python scripts/memory_ops/__init__.py deposit \
  --domain investment --subdomain factor --type FACT \
  --summary "因子 A2：均线斜率（scale 0.06 时 IC 0.17）" \
  --body "构造：20日MA斜率截面z-score标准化；吃 unified_market.audit_est_daily_market。" \
  --attr ic=0.17 scale=0.06 sharpe=1.8 \
  --tags "st:verified" --root <记忆库>
```

## L0 自动化（关键）

`scripts/investment_seed.py` **只读**你的投资数据库 catalog 表（`field_catalog`/`dim_metric`/
`unit_standard`/`mcp_code_map`/`metric_freshness`），批量 deposit 成 `--subdomain data_catalog` 记忆，
每条带字符串维度标签（`mcp:*` 数据源 / `unit:*` 单位 / `freq:*` 频率，因 `--attr` 仅收数值）。
提供 `resync` 增量补登——加表/加列后跑一次即可，
**根治「手搓快照过期、加表不登记」的痛点**。详见该脚本 `--help`。

## 冷启动（给他人：装上即用）

```
python scripts/investment_bridge.py seed --domain investment
```
会把 `investment_taxonomy.json` 的 6 子域合并进你的 `store/taxonomy.json`（保留你原有域，
使 `heat_budget(22)` 真正生效）——**但不导入模板**（模板在 `references/investment_templates.md`，
手动复制填空即可），也**不会自动建 L0 种子**（需另跑 `python scripts/investment_seed.py` 从 duckdb 播种，
或 `seed` 时传 `--db/--discover`）。分类树无需手动配。

## 确定性衰减与重复检测（D2/D3）

- `decay --apply`：基于重要度/时间衰减/访问频率/类型权重的确定性公式算相关性分（默认 dry-run）。
- `recurrence --min-count 3`：识别相似经验模式，报告 ≥N 次重复簇。
- 与 `recall --domain investment --subdomain factor` 组合，构成投资记忆的新鲜度治理闭环。

> 投资能力圈已发布；模板见 `references/investment_templates.md`，
> 分类树种子见 `references/investment_taxonomy.json`，L0 自动建见 `scripts/investment_seed.py`。
