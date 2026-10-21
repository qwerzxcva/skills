---
name: stock-researcher
version: 9.8.0
description: |
  全球智能投研工具 v9.8 — 主流知识库全覆盖（12 适配器双向交互），
  叠加 v9.6 标红限制固化 + v9.5 大佬圆桌，全资产量化 + 真实数据源。覆盖 12 个全球市场，零依赖核心（纯 stdlib）。

  🆕 v9.8 知识库 12 适配器（双向：存档 + 回读离线量化）：
    - 本地：本地兜底库/Obsidian/思源笔记/Logseq；云端：IMA/语雀/飞书知识库/Notion；RAG：Dify/RAGFlow/FastGPT/MaxKB
    - 存档 --kb-save <code>（内嵌机读 JSON），回读 --kb-quant <词> 离线量化预测；--kb-target 与语音均可指定适配器
    - 凭证走环境变量（RAGFLOW/FASTGPT/MAXKB/YUQUE/FEISHU/NOTION/SIYUAN/LOGSEQ 前缀），零新依赖零明文落盘；IMA/Dify 沿用 v9.7 变量名
  v9.6 标红限制固化：国内直连代理防护（导入即装直连 opener）+ 评分≠盈利保证免责声明；行情+K线并行提速
  v9.4 高级量化统计 + 语音交互：advanced_stats 一站式体检（滚动/回撤/仓位/统计检验/归因）+ 零依赖语音指令
  v9.3 量化预测增强：历史形态匹配预测（股票/基金/期货通用）+ 基金 NAV 预测 + 期货置信区间/仓位/展期收益
  v9.0 三大支柱：深度板块（RPS/宽度/离散度/主题/轮动周期）+ 深度指数（体制/波动率/结构/内含/真实PE-PB分位）
    + 体制感知预测（体制条件化权重/信号共识/宏观情景概率加权/校准），regime="auto" 一键开启

  数据源：腾讯 + 东方财富（免费无 Key）+ akshare（可选）。测试 691。

  触发词：股票、基金、行情、分析、预测、涨跌、指数、板块、商品、黄金、债券、可转债、
  货币基金、全球市场、量化、技术指标、组合优化、风险平价、夏普、回测、价值投资、蒙特卡洛、VaR、
  相对强度、RPS、市场体制、波动率体制、指数估值、情景分析、预测校准、自上而下、形态匹配、净值预测、
  语音交互、语音查询、语音预测、高级统计、Kelly仓位、回撤剖析、滚动夏普、跟踪误差、信息比率、JB检验、
  大佬、圆桌、大师共识、索罗斯、费雪、达利欧、马克斯、神奇公式、利弗莫尔、反身性、批量并行、
  知识库、IMA、Dify、Obsidian、RAGFlow、FastGPT、MaxKB、语雀、飞书、Notion、思源、Logseq、分析存档、回读量化、笔记同步
auto_trigger:
  keywords: [股票, 基金, 行情, 分析, 预测, 涨跌, 指数, 板块, 商品, 黄金, 债券, 可转债,
    货币基金, 全球市场, 量化, 技术指标, 组合优化, 风险平价, 夏普, 回测, 价值投资,
    蒙特卡洛, VaR, Sharpe, 涨跌预测, 量化分析, 全资产, 因子库, 策略回测, 数据质量,
    相对强度, RPS, 板块宽度, 轮动周期, 市场体制, 牛熊, 波动率, 市场内含, 指数估值,
    PE分位, 情景, 软着陆, 硬着陆, 校准, 自上而下, 主题板块, AI算力, 人形机器人,
    语音, 语音交互, Kelly, 回撤剖析, 滚动夏普, 跟踪误差, 信息比率, JB检验,
    大佬, 圆桌, 大师策略, 索罗斯, 神奇公式, 反身性, 批量并行,
    知识库, IMA, Dify, Obsidian, RAGFlow, FastGPT, MaxKB, 语雀, 飞书, Notion, 思源, Logseq, 存档, 回读, 笔记]
  patterns:
    - "(分析|预测|查询|筛选|看下|看看).*(股票|基金|涨跌|行情|指数|板块|黄金|原油|债券|可转债)"
    - "(技术|指标|量化|基本面).*分析"
    - "(看涨|看跌|买入|卖出).*信号"
    - "(推荐|建议|排名).*(板块|个股|基金|投资|指数)"
    - "(护城河|DCF|内在价值|安全边际|财务健康).*(分析|评估)"
    - "(舆情|情绪|新闻|论坛).*(监控|分析|预警)"
    - "(港股|美股|日经|标普|纳斯达克|恒生|道琼斯).*(分析|预测|筛选|走势)"
    - "(全球|跨市场|海外).*(指数|市场|分析)"
    - "(黄金|原油|商品|债券).*(分析|预测|走势|期货)"
    - "(政策|监管|宏观).*(解读|分析|影响)"
    - "(未来|下个|短期).*(走势|趋势|涨跌)"
    - "(板块|行业).*(轮动|排名|推荐|趋势)"
    - "(相对强度|RPS|宽度|离散度|强弱).*(板块|行业)"
    - "(市场体制|牛熊|震荡市).*(判断|分析|分类|预测)"
    - "(波动率|波动).*(体制|扩张|压缩|高波动)"
    - "(情景|软着陆|硬着陆|衰退|通胀).*(分析|推演|预测)"
    - "(置信度|校准|可靠性).*(预测|评分)"
    - "(自上而下|市场全景|TopDown).*(分析|报告)"
    - "(五维|资金面|财经信息|社会舆情).*(分析|综合|评估)"
    - "(推演|涨跌预测|方向预测).*(股票|基金|期货|指数)"
    - "(PE|PB|估值).*(分位|历史|真实|估算)"
    - "(数据|财务|报表).*(质量|时效|准确|过时|新鲜)"
    - "(严格|宽松).*(模式|分析|校验)"
    - "(start_date|end_date|日期|时间).*(区间|范围|参数)"
    - "(组合|仓位|资产配置).*(优化|风险平价|马科维茨|夏普)"
    - "(货币基金|货基|余额宝类).*(评分|分析|收益)"
    - "(可转债|转债).*(分析|评分|转股|溢价)"
    - "(语音|语音指令|语音交互).*(预测|分析|查询|股票)"
    - "(Kelly|回撤剖析|滚动夏普|跟踪误差|信息比率|JB).*(计算|分析|检验)"
    - "(大佬|大师|圆桌|高手们).*(怎么看|分析|观点|共识|参考)"
    - "(知识库|笔记).*(保存|存档|检索|回读|量化|同步)"
slug: aistockresearcher
displayName: stock-researcher
---

# 股票研究员 v9.8 — 主流知识库全覆盖（12 适配器双向交互）

> 纯 Python 标准库核心，零 pip 依赖。覆盖 12 个全球市场 + 股票/基金/指数/债券/商品/期货/货币基金/可转债；数据源：腾讯 + 东方财富（免费无 Key）+ akshare（可选，未装自动降级）。

## ⚠️ 支持范围与限制（重要，请先读）

### 支持的市场

| 市场 | 代码格式 | 示例 | 数据源 |
|------|---------|------|--------|
| **A股** | 6 位数字 / `cn:` 前缀 | `600519` `cn:600519` | 腾讯/东财 |
| **港股** | `hk:` 前缀 / `.HK` 后缀 | `hk:00700` `00700.HK` | 腾讯 |
| **美股** | `us:` 前缀 / `.US` 后缀 | `us:AAPL` `AAPL.US` | 腾讯/东财 |
| **全球指数** | `idx:` 前缀 | `idx:N225` `idx:SPX` `idx:上证指数` | 腾讯 |
| **商品期货** | `品种:交易所` | `gold:comex` `crude:wti` | 腾讯 |
| **基金/ETF** | 6 位数字 / `fund:` 前缀 | `110022` `fund:510300` | 天天基金/akshare |
| **可转债** | 6 位数字（11/12 开头自动识别） | `128046` | 东财 |
| **债券** | 代码 / `bond:` 前缀 | `bond:国债` | akshare |

### 限制条件

| 限制 | 说明 |
|------|------|
| 🔴 **需国内直连** | 数据源为腾讯/东财国内接口，**开启代理反而会失败**（会走海外 IP 被拒）。v9.6 已固化：导入即自动安装无代理 opener 强制直连，无需手动处理 |
| 🔴 **非实时数据** | 腾讯/东财接口延迟约 3~5 秒，非交易时段返回收盘价 |
| 🟡 **评分≠盈利预测** | 预测评分表示历史上相似条件下约 X% 概率上涨，**不保证未来**。v9.6 已固化：完整输出/JSON 自动携带免责声明 |
| 🟡 **不构成投资建议** | 仅供学习参考，买卖决策自行负责 |
| 🟡 **akshare 可选** | 部分高级功能（基金净值/债券/可转债/宏观）需要 `pip install akshare`，未装自动降级 |

## ⚡ 快速上手

```bash
# 离线自检 / 单股预测 / 批量多市场
python scripts/stock_predict.py --test
python scripts/stock_predict.py 600519
python scripts/stock_predict.py "600519,hk:00700,us:AAPL" --json

# 统一全资产量化分析（任意金融产品）
python -c "from stock_researcher import quant_analyze_asset; print(quant_analyze_asset('600519'))"

# v9.0 深度板块/指数/体制感知预测
python scripts/stock_predict.py --sector-ranking cn      # 板块RPS相对强度排名
python scripts/stock_predict.py --index-regime sh000001  # 市场体制（牛/熊/震荡）
python scripts/stock_predict.py --scenario               # 宏观情景概率加权
python scripts/stock_predict.py --topdown cn             # 自上而下市场全景
python scripts/stock_predict.py --voice                  # v9.4 语音/文本交互循环（或 python run_voice.py）
python scripts/stock_predict.py --masters 600519         # v9.5 大佬圆桌（6 位大师策略共识）
python scripts/stock_predict.py --kb-save 600519         # v9.8 分析并保存到知识库（--kb-target 12 适配器）
python scripts/stock_predict.py --kb-quant 茅台            # v9.8 知识库回读离线量化预测
python scripts/stock_predict.py "600519,000858" --timing # v9.5 批量并行 + 耗时统计
```

### v9.0 深度分析速查

```python
# 板块：相对强度 + 宽度 + 离散度 + 主题 + 轮动周期
from stock_researcher import rps_ranking, analyze_breadth, analyze_dispersion, \
    list_themes, analyze_theme, detect_cycle_stage
ranking = rps_ranking("cn")                 # RPS 百分位排名（真实成分股 vs 沪深300）
b = analyze_breadth("电子")                  # 宽度：%在MA20/50/200、Zweig推动、背离
d = analyze_dispersion("电子")               # 离散度：横截面σ、龙头-落后差、齐涨/分化
themes = list_themes("cn")                  # AI算力/人形机器人/低空经济/固态电池...
t = analyze_theme("AI算力", "cn")            # 主题板块强度+宽度+离散度+资金
stage = detect_cycle_stage("cn")            # 美林时钟：早/中/晚周期/衰退概率

# 指数：体制 + 波动率 + 结构 + 内含 + 估值分位
from stock_researcher import classify_market_regime, analyze_volatility, \
    analyze_market_structure, analyze_market_internals, classify_index_valuation
reg = classify_market_regime("sh000001")    # 牛/熊/震荡 + 概率
vol = analyze_volatility("sh000001")        # 波动率体制（低/扩张/高/压缩）
ms = analyze_market_structure("sh000001")   # 高低点结构 + 阻力/支撑
mi = analyze_market_internals("sh000300")   # 涨跌家数 + McClellan（混合数据策略）
iv = classify_index_valuation("sh000300")   # 真实 PE 历史分位（多级降级不编造）

# 体制感知预测（regime="auto" 一键开启；默认 None 与 v8.0 行为一致）
from stock_researcher.fusion.multi_horizon_forecaster import MultiHorizonForecaster
fc = MultiHorizonForecaster().forecast_stock("600519", regime="auto")
print(fc.regime, fc.horizons["1M"].regime, fc.horizons["1M"].consensus)

# 宏观情景 + 校准
from stock_researcher import analyze_scenarios, calibrate_confidence
rep = analyze_scenarios(base_return=0.08, base_vol=0.20)   # 6情景概率加权+尾部
adj = calibrate_confidence(0.7, horizon="1M")               # 历史校准后置信度

# 自上而下全景（三支柱一条线）
from stock_researcher import build_topdown
print(build_topdown("cn").summary)

# v9.2 定期报告解读（年报/半年报/季报 同比环比 + 亮点风险 + 中文报告）
from stock_researcher import interpret_report, format_report
rep = interpret_report("600519", period="2024")     # "2024"=年报；"2025Q3"/"2025H1"/"2024-06-30" 亦可
print(rep.verdict, rep.metrics["revenue_yoy"], rep.metrics["net_profit_yoy"])
print(format_report(rep))

# v9.3 历史形态匹配预测 + 基金 NAV 预测 + 期货置信区间预测
from stock_researcher import quick_pattern_forecast
pf = quick_pattern_forecast(prices, horizon=5)      # 形态重演：预期涨跌+上涨概率+置信度
from stock_researcher.funds.fund_quant_analyzer import FundQuantAnalyzer
nav_fc = FundQuantAnalyzer().forecast_nav(nav, 5)   # 基金净值 5 日预测 + 80% 区间
from stock_researcher.quantitative.futures_analyzer import FuturesAnalyzer
fut = FuturesAnalyzer().predict_futures("IF9999", prices)  # 含预测区间+置信度+仓位建议

# v9.4 高级量化统计 + 语音交互（零依赖）
from stock_researcher import rolling_metrics, drawdown_report, kelly_fraction, quick_advanced_stats
rolling_metrics(prices, window=60)      # 滚动均值/波动/Sharpe/回撤；drawdown_report(prices) 回撤剖析
kelly_fraction(0.55, 1.8)               # Kelly 仓位分数；quick_advanced_stats(prices) 一站式体检
from stock_researcher import parse_voice_command          # 口语指令解析（run_voice.py/--voice 双入口）
parse_voice_command("预测茅台")           # {'intent':'predict','code':'600519'}

# v9.5 大佬圆桌（6 位大师策略共识参考面板）
from stock_researcher import MasterInput, MasterCouncil
inp = MasterInput.from_market(code="600519", price=1500, pe=22, roe=30, closes=prices)
rep = MasterCouncil().analyze(inp)      # 置信度加权共识 + 多空一致度 + 最乐观/最谨慎代表
print(MasterCouncil.format(rep))        # 中文圆桌报告

# v9.8 知识库双向交互（12 适配器，凭证走环境变量）
from stock_researcher import save_analysis_to_kb, kb_quant_forecast, kb_status
save_analysis_to_kb(code, result, prices, target="ragflow")  # 分析存档（内嵌机读 JSON）
rep = kb_quant_forecast("茅台")            # 回读价格序列→离线体检+形态匹配预测
```

## 🚀 Agent 执行指南（先探测环境，再分析，最后按模板输出）

### Step 1: 运行时检测（不要假设环境，先探测再决策）

```bash
# ① Python 解释器（Windows 优先用 py launcher 定位）
python --version 2>/dev/null || py --version 2>/dev/null || echo "NO_PYTHON"

# ② 可选依赖探测（决定降级路径）
python -c "import akshare" 2>/dev/null && echo "AKSHARE_OK" || echo "AKSHARE_MISSING"
python -c "import numpy, sklearn" 2>/dev/null && echo "ML_OK" || echo "ML_MISSING"

# ③ 数据源连通性（腾讯/东财需国内直连，开代理会失败）
python scripts/stock_predict.py --test
```

| 检测结果 | 决策 |
|---|---|
| `NO_PYTHON` | Windows 用 `py -3.11`；Linux/macOS 用 `python3`；`py --list` 查看可用版本 |
| `AKSHARE_MISSING` | 基金净值/债券/可转债/宏观走降级路径（自动跳过，不崩溃）；其余功能不受影响 |
| `ML_MISSING` | 短期(1d/3d/5d) ML 概率叠加自动跳过（no-op），主预测链路仍可用 |
| `--test` 失败/超时 | 疑似开了代理/VPN → 提示用户关闭代理后重试；或用纯离线函数（不联网的量化/回测/组合优化） |

### Step 2: 按需求选择入口（参数默认值见下表）

| 需求 | 入口 | 命令/调用 |
|---|---|---|
| 单股/多市场预测 | CLI | `python scripts/stock_predict.py 600519` |
| 全资产量化 | `quant_analyze_asset(code)` | 股票/基金/指数/债券/商品/可转债统一收口 |
| 板块深度 | `rps_ranking`/`analyze_breadth`/`analyze_dispersion`/`analyze_theme` | v9.0 深度板块 |
| 指数深度 | `classify_market_regime`/`analyze_volatility`/`analyze_market_internals`/`classify_index_valuation` | v9.0 深度指数 |
| 价值投资 | `ValueInvestingDecision().analyze(code)` | DCF/护城河/财务健康/管理层/行业 |
| 基金评分 | `score_fund_v3(code)` | 基金十维评分 |
| 组合优化/回测 | `allocate_portfolio`/`BacktestEngine` | 纯 stdlib MVO/风险平价/VaR |
| 定期报告解读 | `interpret_report(code, period)` | 年报/半年报/季报 同比环比+亮点风险（v9.2） |
| 历史形态预测 | `quick_pattern_forecast(prices)` | 形态匹配推断涨跌，股票/基金/期货通用（v9.3） |
| 高级量化统计 | `quick_advanced_stats(prices)` | 滚动指标/回撤剖析/仓位计算/统计检验/业绩归因（v9.4） |
| 语音交互 | `python run_voice.py` / `--voice` | 口语指令驱动预测/体检/板块/体制/情景/全景（v9.4） |
| 大佬圆桌 | `MasterCouncil().analyze(inp)` / `--masters <code>` | 6 位大佬策略置信度加权共识参考（v9.5） |

> 批量/快速场景优先加 `--simple --quick`（跳过蒙特卡洛 + 全球风险偏好，提速约 60%）。

### 参数默认值

| 参数 | 默认值 | 说明 |
|---|---|---|
| `market` | `cn` | 可选 cn/hk/us；港股美股需 `hk:`/`us:` 前缀 |
| `asset_type` | 自动识别 | 可转债 11/12 开头、6 位数字=基金/股票、`gold`=商品 |
| `top_n` | 20（筛选）/ 5（板块） | 返回前 N 条 |
| `horizon` | 1d~6M 全周期 | `MultiHorizonForecaster` 默认输出 1d/3d/5d/1M/3M/6M |
| `regime` | `None`（=v8.0 行为） | 传 `"auto"` 开启体制感知预测（熊市动量折扣+共识度校准） |
| `strict` | `False` | `True` 拒绝估算值（estimated）只保留 actual/derived |
| `distribution` | `normal` | 蒙特卡洛可选 `t`（肥尾）+ `use_jumps=True`（跳跃扩散） |
| `track` | `False` | `True` 写入 PredictionTracker（进化闭环） |
| 缓存 TTL | 300 秒 | `config/settings.json` 的 `cache.ttl` |

### Step 3: 输出报告（结构化模板，编号分节）

每次分析按以下模板输出，数据缺失时如实标注，不编造：

1. **标的概览** — 代码 / 名称 / 市场 / 最新价 / 涨跌幅 / 数据时效（`data_freshness`）
2. **核心指标** — 评分、方向、置信度、关键量化指标（Sharpe/最大回撤/PE 分位等）
3. **多周期预测** — 1d/5d/1M/3M/6M 方向 + 概率 + 共识度（`regime` 开启时附体制标签）
4. **风险提示** — VaR/最大回撤/情景尾部风险 + 数据质量标记（actual/derived/estimated/unavailable）
5. **结论** — 一句话结论 + 免责声明（仅供学习参考，不构成投资建议）

## 核心能力总览

| 能力 | 入口 | 说明 |
|---|---|---|
| **统一全资产量化** 🆕 | `quant_analyze_asset(code)` | 一个 API 量化股票/基金/指数/债券/商品/可转债，输出指标+场景+预测+专属分析 |
| **组合优化** 🆕 | `allocate_portfolio` / `mean_variance_optimize` | MVO（Frank-Wolfe）/ 最大Sharpe / 风险平价 / 组合 VaR-ES，纯 stdlib |
| **蒙特卡洛增强** 🆕 | `quick_scenario_forecast(..., distribution='t', use_jumps=True)` | 跳跃扩散 + 肥尾 t 分布（默认保持 GBM） |
| **ML 预测叠加** 🆕 | `MultiHorizonForecaster.forecast_stock(track=True)` | 短期(1d/3d/5d) ML 概率叠加 + 进化闭环记录 |
| **债券量化** 🆕 | `analyze_bond` / `bond_price` | 定价/久期/凸性/YTM/信用利差/收益率曲线形态 |
| **货币基金** 🆕 | `MoneyFundAnalyzer` | 7 日年化水平+稳定性+规模评分 |
| **可转债** 🆕 | `ConvertibleBondAnalyzer` | 转股价值/溢价率/双低指数/股性/强赎 |
| **板块相对强度 RPS** 🆕 | `SectorRelativeStrength` / `rps_ranking(market)` | 成分股构造板块代理指数 → 相对基准 5/20/60/120d RS + Mansfield RPS 百分位排名 + RS 趋势 |
| **板块宽度** 🆕 | `SectorBreadth` / `analyze_breadth(sector)` | %在MA20/50/200之上、新高新低、Zweig 宽度推动、价格-宽度背离、健康度 |
| **板块离散度** 🆕 | `SectorDispersion` / `analyze_dispersion(sector)` | 横截面σ、龙头-落后差、集中度、偏度、齐涨/齐跌/分化 |
| **主题概念板块** 🆕 | `list_themes` / `analyze_theme` / `rank_themes` | AI算力/人形机器人/低空经济/固态电池/氢能/创新药等跨行业概念（cn/hk/us） |
| **轮动周期阶段** 🆕 | `RotationCycleDetector` / `detect_cycle_stage` | 美林时钟：早/中/晚周期/衰退概率 + 受益/回避板块 |
| **市场体制分类** 🆕 | `MarketRegimeClassifier` / `classify_market_regime(code)` | 牛/熊/震荡 + 概率（MA200斜率+回撤+52周位置），体制切换信号 |
| **波动率体制** 🆕 | `VolatilityRegimeAnalyzer` | 20/60d 年化已实现波动、低/扩张/高/压缩标签、vol-of-vol、历史分位 |
| **市场结构** 🆕 | `MarketStructureAnalyzer` | 摆动高低点、HH-HL趋势结构、阻力/支撑关键位、破位信号、ATR |
| **市场内含** 🆕 | `MarketInternalsAnalyzer` | 涨跌家数、新高新低、McClellan 震荡子、宽度超买超卖（混合数据策略） |
| **指数估值分位** 🆕 | `IndexValuation` / `classify_index_valuation(code)` | 指数级 PE/PB 真实历史分位（多级降级，无分位不编造） |
| **体制感知预测** 🆕 | `MultiHorizonForecaster.forecast_stock(regime="auto")` | 体制条件化权重 + 熊市动量折扣 + 信号共识度置信调整 |
| **宏观情景** 🆕 | `MacroScenarioEngine` / `analyze_scenarios` | 6 命名情景（软着陆/硬着陆/通胀/地缘/刺激/衰退）概率加权 + 尾部 VaR |
| **预测校准** 🆕 | `PredictionCalibrator` / `calibrate_confidence` | 历史命中率分桶可靠性曲线 + Brier + 保序回归置信度校准 |
| **自上而下全景** 🆕 | `TopDownReport` / `build_topdown(market)` | 宏观体制→受益板块(RPS)→指数健康→仓位倾向+风险提示，三支柱串成一条 |
| **定期报告解读** 🆕 | `interpret_report(code, period)` / `FinancialReportInterpreter` | 年报/半年报/季报 同比(YoY)/环比(QoQ) + 业绩亮点/风险（增收不增利/经营杠杆/盈利质量/杠杆变化）+ 中文解读报告 |
| **历史形态匹配预测** 🆕 | `quick_pattern_forecast` / `HistoricalPatternPredictor` | 检索历史相似形态窗口 → 预期涨跌/上涨概率/分位区间/置信度，股票/基金/期货通用，纯离线 |
| **基金量化增强** 🆕 | `FundQuantAnalyzer` | 新增偏度/峰度/VaR/回撤恢复期/滚动稳定性/Treynor + `forecast_nav` NAV 短期预测 |
| **期货量化增强** 🆕 | `FuturesAnalyzer` | 置信区间预测 + 波动率预测（扩张/压缩）+ ATR 风险预算仓位 + 展期收益估算 |
| **高级量化统计** 🆕 | `rolling_metrics` / `drawdown_report` / `quick_advanced_stats` | 滚动指标 + 回撤剖析 + Kelly/固定分数/波动率目标仓位 + JB 正态性 + Ljung-Box + 跟踪误差/上下捕获率 |
| **语音交互** 🆕 | `run_voice.py` / `stock_predict.py --voice` | Windows SAPI 零依赖 TTS/STT + 口语指令解析 8 类意图（预测/体检/板块/体制/情景/全景/帮助/退出） |
| **大佬圆桌** 🆕 | `MasterCouncil` / `quick_master_council` / `--masters <code>` | 索罗斯/费雪/达利欧/马克斯/格林布拉特/利弗莫尔 6 策略统一快照评分，置信度×权重共识 + 多空一致度 + 极端代表 |
| **性能提速** 🆕 | `stock_predict.py` | 行情+K线并行拉取（墙钟减半）+ 批量标的 4 并发 + ATR 去重 + `--timing` 耗时统计 |
| **知识库双向交互** 🆕 | `save_analysis_to_kb` / `kb_quant_forecast` / `--kb*` | 12 适配器覆盖主流知识库（本地/Obsidian/IMA/Dify/RAGFlow/FastGPT/MaxKB/语雀/飞书/Notion/思源/Logseq）：存档 + 回读离线量化（v9.8） |
| 多周期涨跌预测 | `MultiHorizonForecaster` | 1d~6M 十维信号融合（技术/资金/政策/舆情/宏观等） |
| 因子库 | `FactorLibrary` / `EnhancedFactorLibrary` | 5 类基础因子 + v7.6 四因子（动量反转/资金流/波动率/日历） |
| 策略回测 | `Backtester` / `BacktestEngine` | RSI/MACD/双均线 P&L 模拟 + 漫步前向命中率 |
| 价值投资 | `ValueInvestingDecision` | DCF/护城河/财务健康/管理层/行业五维 |
| 五维聚合 | `FiveDimAnalyzer` | 政策+资金+财经+论坛+舆情 |

## 数据层与量化模型（v8.0）

真实数据修复：PE/PB 真实历史分位 / 财务时效 report_date / 东财 f62 真实资金流 / DCF 债务利息真实字段 / 腾讯+新浪+东财多源冗余降级 / akshare 可选未装自动降级；量化模型：`mean_variance_optimize`（MVO 纯 stdlib）/ `allocate_portfolio`（最大Sharpe/风险平价）/ `quick_scenario_forecast`（跳跃扩散+肥尾 t）。

## 全资产统一入口

`quant_analyze_asset(code)`：一个 API 量化股票/可转债（11/12 开头自动识别）/ETF 基金/指数/债券/商品，返回 metrics + 蒙特卡洛情景 + 多周期预测 + 资产专属分析。

## 预测链路（三栈关系）

- **`scripts/stock_predict.py`**：CLI 七维评分 + 蒙特卡洛，零依赖单股快速预测（v9.4 --voice；v9.5 --masters/--timing + 批量并行）
- **`fusion/multi_horizon_forecaster`**：主链路十维信号融合 1d~6M + ML 短期叠加 + 进化闭环
- **`core/prediction_engine`**：三维预测（情绪/估值/历史/技术）+ GBM；三栈可并用，`quant_analyze_asset` 统一收口

## 核心模块 API

| 模块 | import | 关键函数 |
|---|---|---|
| 数据 | `stock_researcher.data` | `MarketData` / `FundamentalData` / `MoneyFlowData` / `source_manager` / `akshare_provider` |
| 量化 | `stock_researcher.quantitative` | `compute_quant_metrics` / `quant_analyze_asset` / `allocate_portfolio` / `analyze_bond` / `MoneyFundAnalyzer` / `ConvertibleBondAnalyzer` / `quick_scenario_forecast` |
| 预测 | `stock_researcher.fusion` | `MultiHorizonForecaster` |
| 价值 | `stock_researcher.value_investing` | `ValueInvestingDecision` |
| 基金 | `pkg.fund_analyzer` | `score_fund_v3` / `fetch_fund_nav` / `predict_fund_multi_horizon` |

## 版本历史

<details>
<summary>📜 展开查看历史版本</summary>

| 版本 | 要点 |
|---|---|
| v9.8 | 主流知识库全覆盖：12 适配器（新增 RAGFlow/FastGPT/MaxKB/语雀/飞书/Notion/思源/Logseq）+ CLI/语音指定适配器 |
| v9.7 | 知识库双向交互（IMA/Dify/Obsidian/本地）：分析存档机读 JSON + 回读离线量化预测 |
| v9.6 | 标红限制固化（国内直连代理防护 + 评分免责声明）+ source_manager 缓存键 bug 修复 |
| v9.5 | 大佬圆桌（索罗斯/费雪/达利欧/马克斯/格林布拉特/利弗莫尔 6 策略 + 置信度加权共识）+ 性能提速（行情K线并行/批量并发/ATR去重/--timing） |
| v9.4 | 高级量化统计（滚动指标/回撤剖析/仓位计算/JB检验/Ljung-Box/业绩归因）+ 语音交互（SAPI 零依赖 TTS/STT + 口语指令引擎 + 双入口） |
| v9.3 | 量化预测增强：历史形态匹配预测（股票/基金/期货通用）+ 基金尾部风险/回撤恢复/稳定性/NAV预测 + 期货置信区间/仓位/展期收益 + quant_analyze_asset 接线 |
| v9.2 | 定期报告解读（年报/半年报/季报 同比环比 + 亮点风险 + 中文报告） |

</details>

## 目录速查

```
scripts/stock_researcher/
├── data/            # 数据源（腾讯/东财/新浪/akshare 可选）+ 多源管理器 + 数据质量
│                    #   + v9.0: macro_series 宏观序列 / index_constituents 指数成分
├── quantitative/    # 量化（指标/因子/组合优化/MC/回测/债券/货基/可转债/全资产入口）
│                    #   + v9.0: scenario_engine + v9.4: advanced_stats 高级统计
├── fusion/          # 十维信号融合多周期预测（含 ML overlay + 进化闭环）
│                    #   + v9.0: regime_overlay 体制权重 / signal_consensus 共识度
├── core/            # 分析器/预测引擎/技术/估值
├── value_investing/ # DCF/护城河/财务健康
├── funds.py          # 基金量化（fund_quant + fund_sentiment 合并）
├── index_analysis/  # 指数：IndexAnalyzer + v9.0: 体制/波动率/结构/内含/估值分位
├── sector_analysis/ # 板块：Analyzer/Rotation + v9.0: RPS/宽度/离散度/主题/轮动周期
├── evolution/       # 回测 + 预测追踪（进化闭环）+ v9.0: calibration 预测校准
├── analysis/        # 五维聚合/资产推演 + v9.0: top_down 自上而下全景
├── sentiment/ agents/ advisor/ tracker/ # 舆情/大师圆桌（v9.5：6 大佬+共识）/投顾/跟踪
├── screening.py + knowledge_sync.py  # 筛选 / v9.8 知识库（12 适配器）双向交互
├── research/        # 券商研报/宏观信号 + v9.2: financial_report + v9.4: voice_interface 语音交互
scripts/stock_predict.py   # CLI 预测引擎（零依赖，--sector-ranking/--masters/--timing 等）
pkg/fund_analyzer.py       # 基金深度分析
tests/                     # 691 测试（python runtests.py）
```

## ❓ 常见问题与避坑指南（FAQ）

### Q1: 开了代理（VPN）后数据获取失败？
**A**: 腾讯/东财数据源只接受国内 IP，**开启代理反而会失败**。解决方案：关闭代理后再运行，或设置代理绕过国内地址。

### Q2: 港股/美股代码怎么写？
**A**: 必须加市场前缀：

    python scripts/stock_predict.py hk:00700      # 港股腾讯
    python scripts/stock_predict.py us:AAPL        # 美股苹果
    python scripts/stock_predict.py "600519,hk:00700,us:AAPL"  # 批量

### Q3: 全球指数代码怎么写？
**A**: 用 `idx:` 前缀 + 指数代码：

    python scripts/stock_predict.py idx:N225       # 日经225
    python scripts/stock_predict.py idx:SPX        # 标普500
    python scripts/stock_predict.py idx:上证指数    # 中文名也行

### Q4: 预测评分 70 分是不是一定会涨？
**A**: **不是。** 评分 70 表示历史上相似条件下约 70% 的情况上涨，不保证未来。请结合基本面、政策、市场情绪综合判断。

### Q5: 返回的数据是实时的吗？
**A**: 不是。腾讯/东财接口延迟约 3~5 秒，非交易时段返回上一交易日收盘价。不适合做高频交易参考。

### Q6: akshare 相关功能报错？
**A**: akshare 是可选依赖，未安装时自动降级；如需启用执行 `pip install akshare`。

### Q7: 速度太慢怎么办？
**A**: 用 `--simple --quick` 跳过蒙特卡洛与全球风险偏好（提速约 60%）；v9.5 起行情+K线已并行拉取、批量标的自动并发，可加 `--timing` 查看耗时定位瓶颈。

> 📘 更多问题请查看 [README.md](README.md) 或运行 `python runtests.py` 验证环境。

---

## 免责声明

> ⚠️ **本工具仅供学习参考，不构成任何形式的投资建议。** 股市有风险，投资需谨慎。

