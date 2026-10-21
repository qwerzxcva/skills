# 投资回测记忆模板（4 层模型）

> 配套 `references/investment_taxonomy.json`（投资域 6 子域）与 `references/INVESTMENT.md`（总览）。
> 所有记忆统一 `--domain investment`；数值指标用 `--attr`（自动归一 ic/ir/sharpe/...）；
> 跨层关联用 `link --rel consumes|test_of|composed_of`（见 INVESTMENT.md「类型化关联」）。
>
> 模板里的 **A2 / comp4 / B2** 是你库里已存在的真实因子，作为样例；新因子照此结构填空即可。

---

## L0 · 数据/参数注册表（`--subdomain data_catalog`）

**目的**：数据库的每一个字段、每一个参数、每一份数据都可被记忆定位——因为它们随时可能成为某个因子的原料。建议用 `scripts/investment_seed.py` 从 duckdb catalog 自动批量建，不要手搓。

```bash
python scripts/memory_ops/__init__.py deposit \
  --domain investment --subdomain data_catalog --type FACT \
  --summary "字段 unified_market.audit_est_daily_market: 审计口径日行情" \
  --body "来源 MCP=ifind；单位=元；频率=日；复权=前复权；取数工具=get_fund_data。
          口径陷阱：该表含退市标的（幸存者偏差），因子取数需 LEFT JOIN 可交易标的过滤。" \
  --tags "mcp:ifind,unit:元,freq:日" \
  --root <你的记忆库>
```

> ⚠️ `--attr` **只接受数值**（IC/sharpe/scale 等因子指标）；单位/频率/数据源是**字符串维度**，必须走标签（`unit:元`/`freq:日`/`mcp:ifind`，keeper 支持 `key:value` 式标签，`recall --tag mcp:ifind` 可精确召回）。跨源同名异码查 `mcp_code_map`。

关键标签：`mcp:*`(数据源) / `unit:*`(单位，跨源对账) / `freq:*`(频率)。

---

## L1 · 因子实体（`--subdomain factor`）

**目的**：每个因子是独立可复用实体——定义、构造、吃哪些 L0 数据、验证结论。

```bash
python scripts/memory_ops/__init__.py deposit \
  --domain investment --subdomain factor --type FACT \
  --summary "因子 A2：均线斜率（20日MA斜率标准化）" \
  --body "构造：对 20 日 MA 取斜率，再按截面 z-score 标准化（中性化行业+市值）。
          吃数据：unified_market.audit_est_daily_market（L0 注册见 LRN-xxxx）。
          结论：scale=0.06 时 IC 最稳；单标的 IC 0.170，生产 IC 偏低需谨慎。" \
  --attr ic=0.170 ic_prod=0.120 scale=0.06 sharpe=1.8 maxdd=0.15 turnover=0.35 \
  --tags "st:verified" \
  --root <你的记忆库>
# 关联：本因子消费了哪些 L0 数据
python scripts/memory_ops/__init__.py link <本因子ID> consumes <L0字段ID>
```

`--attr` 关键点：`ic`（信息系数，原始）、`ic_prod`（生产口径 IC）、`scale`（标度）、`sharpe`/`maxdd`/`turnover`。IC/IR 现在会被自动结构化（已补白名单）。

---

## L2 · 因子测试迭代（`--subdomain factor_test`）

**目的**：一个因子要经历若干轮测试，每轮配置/指标/结论/通过与否都留痕、可回溯。

```bash
python scripts/memory_ops/__init__.py deposit \
  --domain investment --subdomain factor_test --type PREF \
  --summary "A2 第3轮测试：scale 扫描 0.03→0.12" \
  --body "配置：窗口=20日，标度扫描=[0.03,0.06,0.09,0.12]，中性化=行业+市值。
          结果：scale=0.06 时 IC 0.170 最稳，scale=0.12 过拟合（样本外 IC 跌到 0.04）。
          结论：采纳 scale=0.06；拒绝更大标度。" \
  --attr ic=0.170 ic_oos=0.110 scale=0.06 pass=1 \
  --tags "st:verified" \
  --root <你的记忆库>
# 关联：本轮测试被测的是哪个因子
python scripts/memory_ops/__init__.py link <本轮测试ID> test_of <L1因子ID>
```

生命周期（强制 `st:`）：`draft`（刚设计）→ `validating`（测试中）→ `verified`（通过）→ `deprecated`（被推翻）。新测试推翻旧结论时，用 `link <旧测试ID> superseded_by <新测试ID>` 标记旧测试为 `superseded`（引擎自动回收）。L1 因子的 `--attr` 收敛到**最新通过的**测试指标。

---

## L3 · 组合/系统（`--subdomain system`）

**目的**：因子以不同方式（加权/正交/条件）组合出新的系统，系统本身记录组合方式与回测结果。

```bash
python scripts/memory_ops/__init__.py deposit \
  --domain investment --subdomain system --type BP \
  --summary "系统 S1：A2(均线斜率) + comp4(估值) 等权正交组合" \
  --body "组合方式：先对 A2/comp4 做市值中性化，再对因子收益正交化去冗余，
          等权合成综合因子。权重 w_A2=0.5 w_comp4=0.5。
          回测：样本内 sharpe 2.1，样本外 sharpe 1.4（衰减可接受）；最大回撤 18%。
          过拟合标记：样本外/样本内 sharpe 比 0.67，未触发过拟合红线(>0.5)。" \
  --attr sharpe=2.1 sharpe_oos=1.4 maxdd=0.18 w_A2=0.5 w_comp4=0.5 \
  --tags "st:verified" \
  --root <你的记忆库>
# 关联：系统由哪些因子组成
python scripts/memory_ops/__init__.py link <系统ID> composed_of <因子A2的ID>
python scripts/memory_ops/__init__.py link <系统ID> composed_of <因子comp4的ID>
```

组合方式维度：`weighted`（加权）/ `orthogonal`（正交去冗余）/ `conditional`（条件）。系统级回测必须带 `sharpe_oos`（样本外）与过拟合比，否则视为未经验证。

---

## 横切纪律（任何层都要记）

回测正确性两条命门，单独成记忆（`--subdomain backtest_integrity` / `data_integrity`）：

- **前视泄漏 L1/L2/L3**：标签要用未来信息？排序用当日收盘价？分母含当日值？任一命中即结果作废。
- **脚本也会算错**：数值结论必须独立重算/对账，不轻信取数脚本输出（你的 LRN-20260731-002~009 已沉淀）。

> 模板随投资能力圈发布；新因子/新系统直接复制填空，关联用 `link` 串成「数据→因子→测试→系统」链路，`python scripts/investment_bridge.py graph --around <ID>` 可可视化。
