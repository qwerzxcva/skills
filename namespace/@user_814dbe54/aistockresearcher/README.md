# 股票研究员 v9.8（全球零依赖版）

> 纯 Python 标准库，零 pip install，覆盖 12 个全球市场。
> 数据源：腾讯财经 + 东方财富（免费无 Key）+ akshare（可选增强），国内直连。
>
> v9.8：主流知识库全覆盖 —— 12 适配器双向交互（本地兜底库 / Obsidian / 腾讯 IMA / Dify / RAGFlow / FastGPT / MaxKB /
> 语雀 / 飞书知识库 / Notion / 思源笔记 / Logseq）：分析结果一键存档为知识笔记（内嵌机读 JSON），
> 也可从知识库回读价格序列直接离线量化体检 + 形态匹配预测；凭证全部走环境变量，零新依赖。
>
> v9.6：两条标红限制固化 —— ①国内直连防护：导入即安装无代理 opener，腾讯/东财接口开代理/VPN 反而会失败；
> ②评分≠盈利保证：预测评分仅代表历史相似条件下约 X% 上涨概率，输出自动携带免责声明。
>
> v9.5：大佬圆桌（索罗斯/费雪/达利欧/马克斯/格林布拉特/利弗莫尔 6 位大师策略，置信度加权共识）+
> 全面性能提速（行情+K线并行拉取、批量标的并发、ATR 去重、--timing 耗时统计）。
> v9.4：强化量化分析计算 + 语音交互 — advanced_stats（滚动指标/回撤剖析/Kelly 仓位/JB 正态性/
> Ljung-Box/跟踪误差/上下捕获率）+ voice_interface（Windows SAPI 零依赖 TTS/STT + 口语指令引擎）。
> v9.3：量化预测增强 — 历史形态匹配预测（股票/基金/期货通用）+ 基金尾部风险/回撤恢复/NAV 预测 +
> 期货置信区间预测/仓位建议/展期收益 + quant_analyze_asset 接线。
> v9.2：定期报告解读（年报/半年报/季报 同比环比 + 业绩亮点/风险 + 中文报告）。
> v9.0 三大支柱：深度板块（RPS 相对强度/宽度/离散度/主题概念/轮动周期）+
> 深度指数（市场体制/波动率体制/市场结构/市场内含/真实指数 PE 分位）+
> 体制感知预测（体制条件化权重/信号共识度/宏观情景/置信度校准）+ 自上而下全景。
> v8.0：真实 PE/PB 历史分位、组合优化、MC 增强、ML 接入、全资产量化入口、akshare。
> v7.x 历史：QuantMetrics 统一指标、数据质量四级标记、五维信息聚合、多资产涨跌推演。

## 30 秒上手

```bash
# 1. 离线自检（确认一切就绪）
python scripts/stock_predict.py --test

# 2. 查看一只股票
python scripts/stock_predict.py 600519 --simple

# 3. 快速模式（跳过耗时计算，适合批量使用）
python scripts/stock_predict.py 600519 --simple --quick
```

## 常用命令

| 场景 | 命令 |
|------|------|
| A股单股 | `python scripts/stock_predict.py 600519` |
| 港股 | `python scripts/stock_predict.py hk:00700 --simple` |
| 美股 | `python scripts/stock_predict.py us:AAPL --simple` |
| 全球指数 | `python scripts/stock_predict.py idx:N225 --simple` |
| 黄金期货 | `python scripts/stock_predict.py gold:comex --simple` |
| 批量多市场 | `python scripts/stock_predict.py "600519,hk:00700,us:AAPL"` |
| JSON 输出 | `python scripts/stock_predict.py 600519 --json` |
| 板块RPS排名 (v9.0) | `python scripts/stock_predict.py --sector-ranking cn` |
| 市场体制 (v9.0) | `python scripts/stock_predict.py --index-regime sh000001` |
| 宏观情景 (v9.0) | `python scripts/stock_predict.py --scenario` |
| 自上而下全景 (v9.0) | `python scripts/stock_predict.py --topdown cn` |
| 语音交互 (v9.4) | `python run_voice.py` 或 `python scripts/stock_predict.py --voice` |
| 量化一站式体检 (v9.4) | `python -c "from stock_researcher import quick_advanced_stats; print(quick_advanced_stats([100,101,103,102,105]))"` |
| 大佬圆桌 (v9.5) | `python scripts/stock_predict.py --masters 600519` |
| 批量并行+耗时 (v9.5) | `python scripts/stock_predict.py "600519,000858" --timing` |
| 知识库状态 (v9.8) | `python scripts/stock_predict.py --kb` |
| 保存到知识库 (v9.8) | `python scripts/stock_predict.py --kb-save 600519` （可加 `--kb-target` 指定 12 适配器） |
| 知识库检索 (v9.8) | `python scripts/stock_predict.py --kb-search 茅台` |
| 知识库回读量化 (v9.8) | `python scripts/stock_predict.py --kb-quant 茅台`（离线体检+形态预测） |
| 语音存档知识库 (v9.8) | `python run_voice.py` 后说：“把茅台保存到 ragflow 知识库” / “查一下语雀知识库里的茅台” |

## 知识库交互（v9.8，12 适配器）

| 适配器 | 说明 | 凭证 |
|---|---|---|
| `local` | 本地兜底库 `data/knowledge_base/`，MD5 幂等 | 无需 |
| `obsidian` | 直写 Vault 目录（Markdown + frontmatter） | `OBSIDIAN_VAULT_PATH` 或 `config/knowledge_config.json` |
| `ima` | 腾讯 IMA OpenAPI（笔记创建→知识库关联→检索） | `IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY` |
| `dify` | Dify Knowledge API（create/update/retrieve） | `DIFY_API_KEY`（可选 `DIFY_BASE_URL`/`DIFY_DATASET_ID`） |
| `ragflow` | RAGFlow 开源 RAG（dataset 定位/创建 + multipart 上传 + 语义检索） | `RAGFLOW_API_KEY`（可选 `RAGFLOW_BASE_URL`） |
| `fastgpt` | FastGPT（虚拟集合 + pushData 全文入库 + 语义检索） | `FASTGPT_API_KEY`（可选 `FASTGPT_BASE_URL`） |
| `maxkb` | MaxKB（web 文档入库 + hit_test 命中检索） | `MAXKB_API_KEY`（可选 `MAXKB_BASE_URL`） |
| `yuque` | 语雀（同名文档新建/PUT 更新 + 全站检索） | `YUQUE_TOKEN` + `YUQUE_REPO`（或 `YUQUE_LOGIN`+`YUQUE_REPO_NAME`） |
| `feishu` | 飞书知识库（租户令牌 + wiki 建节点 + 正文写入） | `FEISHU_APP_ID` / `FEISHU_APP_SECRET`（可选 `FEISHU_WIKI_SPACE_ID`） |
| `notion` | Notion（新建页面，同名幂等追加） | `NOTION_API_KEY` + `NOTION_PARENT_PAGE_ID` |
| `siyuan` | 思源笔记（本地内核 API，笔记本定位 + Markdown 直写 + 全文检索） | 无需（可选 `SIYUAN_URL`/`SIYUAN_TOKEN`/`SIYUAN_NOTEBOOK`） |
| `logseq` | Logseq 图谱（直写 `pages/*.md`，索引外置不污染图谱） | `LOGSEQ_GRAPH_PATH` |

保存的笔记内嵌机读 JSON（价格序列/评分/蒙特卡洛），`--kb-quant` 据此离线跑 QuantMetrics 体检 +
历史形态匹配预测，无需重新联网拉行情。同步日志存 `data/knowledge_sync_log.json`（保留 200 条）。

## 代码格式速查

| 市场 | 格式 | 示例 |
|------|------|------|
| A股 | 6 位数字 | `600519` `cn:600519` |
| 港股 | hk: + 代码 | `hk:00700` `00700.HK` |
| 美股 | us: + 代码 | `us:AAPL` `AAPL.US` |
| 全球指数 | idx: + 指数码 | `idx:N225` `idx:SPX` `idx:上证指数` |
| 商品期货 | 品种:交易所 | `gold:comex` `crude:wti` |

## 功能速查

```python
# 价值投资分析
from stock_researcher.value_investing import ValueInvestingDecision
print(ValueInvestingDecision.format_report(ValueInvestingDecision().analyze('600519')))

# 基金十维评分
from pkg.fund_analyzer import score_fund_v3
print(score_fund_v3('110022'))

# 多资产推演（股票/基金/期货/指数）
from stock_researcher import quick_forecast, detect_asset_type
print(detect_asset_type('fund:110022'))     # → fund
print(detect_asset_type('etf:510300'))      # → fund
print(quick_forecast('fund:110022')['direction'])

# 统一量化体检（纯标准库）
from stock_researcher import compute_quant_metrics, format_quant_metrics
metrics = compute_quant_metrics(
    [100, 101, 103, 102, 105, 104, 106],
    benchmark_prices=[100, 100.5, 101, 101.5, 102, 102.5, 103],
)
print(format_quant_metrics(metrics))

# 投资筛选（PE<20 且 ROE>15 的港股）
from stock_researcher.screening import UnifiedScreener
r = UnifiedScreener().screen_stocks({'pe_max': 20, 'roe_min': 15}, market='hk')
print(r[:5])

# 舆情监控
from stock_researcher.sentiment import UnifiedSentimentEngine
print(UnifiedSentimentEngine().analyze_stock('00700', 'hk'))

# 回测验证
from stock_researcher.evolution import BacktestEngine
print(BacktestEngine('00700', 'hk').run_and_report())

# ── v9.0 深度板块 / 深度指数 / 体制感知预测 ──

# 板块相对强度 RPS 排名（真实成分股 vs 沪深300，含百分位）
from stock_researcher import rps_ranking
ranking = rps_ranking("cn")
print([(r.sector, r.rps_score, r.rps_percentile, r.rs_trend) for r in ranking[:5]])

# 板块宽度（%在MA20/50/200、新高新低、Zweig推动、背离）
from stock_researcher import analyze_breadth
b = analyze_breadth("电子")
print(b.pct_above_ma20, b.health, b.breadth_thrust, b.divergence)

# 主题概念板块（AI算力/人形机器人/低空经济/固态电池/氢能/创新药...）
from stock_researcher import list_themes, analyze_theme
print(list_themes("cn"))
print(analyze_theme("AI算力", "cn")["strength"].rps_score)

# 轮动周期阶段（美林时钟）
from stock_researcher import detect_cycle_stage
stage = detect_cycle_stage("cn")
print(stage.stage, stage.favored_sectors)

# 指数市场体制（牛/熊/震荡+概率）
from stock_researcher import classify_market_regime
reg = classify_market_regime("sh000001")
print(reg.regime, reg.probabilities, reg.regime_score)

# 波动率体制 / 市场结构 / 市场内含
from stock_researcher import analyze_volatility, analyze_market_structure, \
    analyze_market_internals
print(analyze_volatility("sh000001").regime)
print(analyze_market_structure("sh000001").trend_structure)
print(analyze_market_internals("sh000300").mcclellan)

# 指数真实 PE 历史分位（多级降级，无分位不编造）
from stock_researcher import classify_index_valuation
iv = classify_index_valuation("sh000300")
print(iv.pe, iv.pe_percentile, iv.valuation_label, iv.data_mode)

# 体制感知预测（regime="auto" 一键开启；默认 None 与 v8.0 一致）
from stock_researcher.fusion.multi_horizon_forecaster import MultiHorizonForecaster
fc = MultiHorizonForecaster().forecast_stock("600519", regime="auto")
print(fc.regime, fc.horizons["1M"].direction, fc.horizons["1M"].confidence)

# 宏观情景概率加权 + 预测校准
from stock_researcher import analyze_scenarios, calibrate_confidence
rep = analyze_scenarios(0.08, 0.20)
print(rep.weighted_return, rep.tail_risk, rep.upside_probability)
print(calibrate_confidence(0.7, horizon="1M"))

# 自上而下市场全景（宏观→板块→指数 一条线）
from stock_researcher import build_topdown
print(build_topdown("cn").summary)

# ── v9.2 定期报告解读（年报/半年报/季报 同比环比+亮点风险）──
from stock_researcher import interpret_report, format_report
rep = interpret_report("600519", period="2024")   # "2024"=年报；"2025Q3"/"2025H1" 亦可
print(rep.verdict, rep.metrics["revenue_yoy"], rep.metrics["net_profit_yoy"])
print(format_report(rep))

# ── v9.4 高级量化统计 + 语音交互（零依赖）──
from stock_researcher import rolling_metrics, drawdown_report, kelly_fraction, quick_advanced_stats
rolling_metrics(prices, window=60)     # 滚动年化收益/波动/Sharpe/回撤
drawdown_report(prices)                # Top-N 回撤剖析：深度/谷底/恢复期
kelly_fraction(0.55, 1.8)              # 凯利仓位（默认半凯利封顶 25%）
quick_advanced_stats(prices)           # 一站式体检：统计检验+仓位建议+业绩归因

from stock_researcher import parse_voice_command, VoiceResearchChat
parse_voice_command("预测茅台")          # {'intent':'predict','code':'600519',...}
# 语音循环：python run_voice.py（或 stock_predict.py --voice；STT 不可用自动降级文本输入）
# 语音说“大佬们怎么看茅台” → intent='masters' 直接进入圆桌（v9.5）

# ── v9.5 大佬圆桌（6 位大师策略共识参考面板）──
from stock_researcher import MasterInput, MasterCouncil
inp = MasterInput.from_market(code="600519", price=1500, pe=22, roe=30, closes=prices)
rep = MasterCouncil().analyze(inp)      # 置信度×权重共识分 + 多空一致度 + 最乐观/最谨慎代表
print(MasterCouncil.format(rep))        # 中文圆桌报告（数据缺失诚实降级不编造）
```

## 主要功能模块

| 模块 | 说明 | 依赖 |
|------|------|------|
| **stock_predict.py** | CLI 预测引擎（12项指标+蒙特卡洛+七维评分） | 零依赖 |
| **value_investing/** | DCF估值+护城河+财务健康+管理层+行业分析 | 零依赖 |
| **fund_analyzer** | 基金十维评分+VaR+风格漂移检测 | 零依赖 |
| **fusion/** | 多周期预测（1d~6M，10维信号融合） | 零依赖 |
| **screening.py** | 多市场多条件筛选+6套预设策略 | 零依赖 |
| **sentiment/** | 新闻+论坛+研报舆情监控 | 零依赖 |
| **agents/** | 巴菲特/格雷厄姆/林奇 + v9.5 索罗斯/费雪/达利欧/马克斯/格林布拉特/利弗莫尔圆桌共识 | 零依赖 |
| **quantitative/** | GARCH/10因子/配对交易/ML预测 + v9.0 宏观情景引擎 | 可选 numpy |
| **sector_analysis/** (v9.0) | RPS相对强度/宽度/离散度/主题概念/轮动周期 | 零依赖 |
| **index_analysis/** (v9.0) | 市场体制/波动率体制/市场结构/内含/McClellan/真实PE分位 | 零依赖 |
| **fusion/regime_overlay** (v9.0) | 体制条件化权重+熊市动量折扣（regime="auto"） | 零依赖 |
| **evolution/calibration** (v9.0) | 预测置信度校准（可靠性曲线+Brier） | 零依赖 |
| **analysis/top_down** (v9.0) | 自上而下市场全景报告 | 零依赖 |
| **research/financial_report** (v9.2) | 定期报告解读（年报/半年报/季报 同比环比+亮点风险） | 零依赖 |
| **quantitative/pattern_predictor** (v9.3) | 历史形态匹配预测（股票/基金/期货通用） | 零依赖 |
| **quantitative/advanced_stats** (v9.4) | 滚动指标/回撤剖析/仓位计算/统计检验/业绩归因 | 零依赖 |
| **voice_interface** (v9.4) | 语音交互（SAPI 零依赖 TTS/STT + 口语指令引擎，可选 vosk/pyttsx3 升级） | 零依赖 |
| **agents/master_council** (v9.5) | 大佬圆桌：6 策略统一快照评分 + 置信度加权共识 + 多空一致度 | 零依赖 |
| **性能优化** (v9.5) | 行情+K线并行拉取/批量标的并发/ATR 去重/--timing | 零依赖 |

## ⚠️ 重要提示（必读）

| 限制 | 说明 |
|------|------|
| 🔴 **需国内直连** | 数据源为腾讯/东财国内接口，**开启代理反而会失败**（会走海外 IP 被拒） |
| 🔴 **非实时数据** | 腾讯/东财接口延迟约 3~5 秒，非交易时段返回收盘价 |
| 🟡 **评分≠盈利预测** | 预测评分表示历史上相似条件下约 X% 概率上涨，**不保证未来** |
| 🟡 **不构成投资建议** | 仅供学习参考，买卖决策自行负责 |
| 🟡 **akshare 可选** | 部分高级功能需要 `pip install akshare`，未装自动降级 |

## ❓ 常见问题与避坑指南

### Q1: 开了代理（VPN）后数据获取失败？
**A**: 腾讯/东财数据源只接受国内 IP，**开启代理反而会失败**。解决方案：关闭代理后再运行，或设置代理绕过国内地址。

### Q2: 港股/美股代码怎么写？
**A**: 必须加市场前缀：
```bash
python scripts/stock_predict.py hk:00700      # 港股腾讯
python scripts/stock_predict.py us:AAPL        # 美股苹果
python scripts/stock_predict.py "600519,hk:00700,us:AAPL"  # 批量
```

### Q3: 全球指数代码怎么写？
**A**: 用 `idx:` 前缀 + 指数代码：
```bash
python scripts/stock_predict.py idx:N225       # 日经225
python scripts/stock_predict.py idx:SPX        # 标普500
python scripts/stock_predict.py idx:上证指数    # 中文名也行
```

### Q4: 预测评分 70 分是不是一定会涨？
**A**: **不是。** 评分 70 表示历史上相似条件下约 70% 的情况上涨，不保证未来。请结合基本面、政策、市场情绪综合判断。

### Q5: 返回的数据是实时的吗？
**A**: 不是。腾讯/东财接口延迟约 3~5 秒，非交易时段返回上一交易日收盘价。不适合做高频交易参考。

### Q6: akshare 相关功能报错？
**A**: akshare 是可选依赖，未安装时自动降级。如需使用：`pip install akshare`

### Q7: 速度太慢怎么办？
**A**: 使用 `--quick` 模式跳过蒙特卡洛模拟和全球风险偏好获取，速度提升约 60%：
```bash
python scripts/stock_predict.py 600519 --simple --quick
```

### Q8: 如何判断工具是否正常工作？
**A**: 运行离线自检：`python scripts/stock_predict.py --test`

### Q9: 为什么有些股票分析结果为空？
**A**: 可能原因：1）代码格式错误（港股/美股需加前缀）；2）该股票在腾讯/东财无数据；3）网络问题。先用 `--test` 确认环境正常。

### Q10: 能分析期货/期权吗？
**A**: 支持商品期货（`gold:comex` `crude:wti`），不支持金融期货和期权。

## 目录结构

```
stock-researcher/
├── SKILL.md              # Agent 触发指南
├── README.md             # 本文件
├── run_voice.py          # v9.4 语音交互入口（--text/--no-tts）
├── scripts/
│   ├── stock_predict.py  # ★ CLI 预测引擎（零依赖，v9.4 --voice；v9.5 --masters/--timing + 批量并行）
│   └── stock_researcher/ # ★ 核心模块库（含 v9.4 voice_interface + v9.5 大佬圆桌）
├── pkg/                  # 基金分析 + HTTP 工具
├── config/               # 配置文件
└── tests/                # 691 个测试用例
```

## 免责声明

> ⚠️ **本工具仅供学习参考，不构成任何形式的投资建议。** 股市有风险，投资需谨慎。

