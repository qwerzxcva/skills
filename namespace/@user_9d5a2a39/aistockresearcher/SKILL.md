---
name: stock-researcher
display_name: 全球智能投研
display_name_en: Global Stock Researcher
description_zh: "全球智能投研综合工具：A股/港股/美股/基金/ETF/期货/黄金/债券全资产量化分析与涨跌预测，覆盖 12 个全球市场。深度板块 RPS 排名、市场体制识别（牛/熊/震荡）、五维信息聚合、六位投资大师圆桌共识、多周期情景概率加权预测、历史形态匹配、定期报告解读、AI 深度解读（DeepSeek/OpenAI/Ollama，11 类模板：股票/基金/市场体制/大师圆桌/宏观/风险/板块轮动/期货/资金流/指数预测/组合诊断）、多源数据统一查询（akshare/东方财富API/新浪/雪球/同花顺/期货所/yfinance/Finnhub 自动降级 + ETag 缓存 + 时效分级 + 多源交叉验证 + 3σ 异常检测）、金融六日外部 MCP 桥接（环境变量配置）、MCP Server 20 工具（Claude Code 直接调用），并可双向同步 12 类知识库。纯 Python 标准库核心零依赖，数据源 akshare+东方财富+新浪+雪球+同花顺+yfinance 免费无 Key。"
description_en: "Global investment research toolkit v11.0: quantitative analysis and directional forecasting for A-shares, HK/US stocks, funds, ETFs, futures, gold and bonds. Sector RPS ranking, market regime detection, five-dimension analysis, six-investor council consensus, multi-horizon scenario forecasts, historical pattern matching, AI deep analysis (DeepSeek/OpenAI/Ollama, 11 templates), multi-source data (akshare/Eastmoney API/Sina/Xueqiu/Tonghuashun/Futures Exchange/yfinance/Finnhub with ETag cache + freshness grading + multi-source cross-validation + 3σ anomaly detection), External MCP bridge for 金融六日 (env-var config), MCP Server with 20 tools, and two-way sync with 12 knowledge-base platforms. Pure-stdlib core."
version: 11.0.0
description: |
  全球智能投研工具 v11.0 — 多源数据强化 + AI 期货/资金流/指数/组合深度分析 + 金融六日 MCP 桥接。
  叠加 v10.0 多源金融数据 + v9.8 知识库 12 适配器 + v9.5 大佬圆桌。
  全资产量化 + 真实数据源，覆盖 12 个全球市场，零依赖核心（纯 stdlib）。

  🆕 v11.0 量化锋刃（11 大变更）：
    数据：data_multi_source.py 新增 4 数据源适配器
      + SinaFinanceAdapter（新浪财经：A股/港股/美股实时行情+K线，免费无 Key）
      + XueqiuAdapter（雪球：A股行情+情绪，免费无 Key）
      + FuturesExchangeAdapter（上期所/大商所/郑商所：期货快照+历史K线+夜盘，免费无 Key）
      + TonghuashunAdapter（同花顺：A股行情+资金流，免费无 Key）
      + ExternalMCPAdapter（占位：金融六日外部 MCP，通过 stdio 桥接）
      + DataCategory 新增 3 类（FUTURES_HISTORY/MONEY_FLOW/SENTIMENT）
      + ETag/If-Modified-Since 缓存 + 时效分级 (realtime/delayed_15m/closing/estimated/stale)
      + 多源交叉验证 (cross_validate, 字段中位数融合 + 偏差容忍度)
      + 3σ + IQR 二阶段异常值检测 (detect_anomaly)
      + query_with_validation 一站式：查询+验证+置信度

    AI：ai_analysis_engine.py 7 → 11 模板（新增 4 + 强化 4）
      + 新增 futures_analysis（期货：持仓/基差/龙虎榜/展期收益）
      + 新增 money_flow_analysis（资金流：主力/北向/融资/ETF/聪明钱）
      + 新增 index_forecast（指数：PE分位/RS评分/多周期方向）
      + 新增 portfolio_diagnosis（组合：业绩归因/再平衡/风格漂移）
      + 强化 market_regime（新增 PCR/AH 折溢价/科创50/AD 比率）
      + 强化 macro_outlook（新增 房地产/社零/出口/DR007/Fed Funds）
      + 强化 risk_report（新增 流动性风险/通胀冲击/相关性矩阵）
      + 强化 sector_rotation（新增 聪明钱动向/ETF 申赎方向）

    预测：prediction_v1100.py 多周期预测器（新文件）
      + predict_multi_horizon: 1d/5d/1M/3M/6M 多周期统一预测
      + 股票/基金/期货/指数四类资产通用
      + calibrate_probability: 历史概率校准（5 桶分桶）

    MCP：mcp_server.py 14 → 20 工具
      + ai_analyze_futures / ai_analyze_money_flow / ai_analyze_index_forecast / ai_analyze_portfolio
      + get_futures_quote（含夜盘）
      + predict_multi_horizon（多周期预测）

    桥接：mcp_external_bridge.py（新文件）
      + ExternalMCPSession：subprocess + JSON-RPC 协议
      + ExternalMCPBridge：单例管理，工具发现与调用
      + 配置：环境变量 STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND/NAME/ENV_*

    测试：5 新增测试文件，~110 新测试，全量 845 测试
    依赖：零新增

  v10.0 AI 解读 + 多源 MCP 桥接（已包含）
  v9.8 知识库 12 适配器（已包含）
  v9.5 大佬圆桌（已包含）

  数据源：腾讯 + 东方财富 + akshare + 新浪 + 雪球 + 同花顺 + yfinance（均免费无 Key）。

  触发词：股票、基金、行情、分析、预测、涨跌、指数、板块、商品、黄金、债券、可转债、
  货币基金、全球市场、量化、技术指标、组合优化、风险平价、夏普、回测、价值投资、蒙特卡洛、VaR、
  相对强度、RPS、市场体制、波动率体制、指数估值、情景分析、预测校准、自上而下、形态匹配、净值预测、
  语音交互、Kelly仓位、回撤剖析、滚动夏普、跟踪误差、信息比率、JB检验、
  大佬、圆桌、大师共识、索罗斯、费雪、达利欧、马克斯、神奇公式、利弗莫尔、反身性、批量并行、
  知识库、IMA、Dify、Obsidian、RAGFlow、FastGPT、MaxKB、语雀、飞书、Notion、思源、Logseq、分析存档、回读量化、笔记同步、
  AI解读、DeepSeek、OpenAI、Ollama、LLM、智能分析、AI深度解读、机器学习预测、多源数据、数据源切换、自动降级、yfinance、Finnhub、
  期货、资金流、聪明钱、ETF申赎、龙虎榜、基差、跨期套利、展期收益、组合诊断、再平衡、业绩归因、
  金融六日、外部MCP、MCP桥接、桥接、多周期预测、多周期、指数预测、ETF流向
auto_trigger:
  keywords: [股票, 基金, 行情, 分析, 预测, 涨跌, 指数, 板块, 商品, 黄金, 债券, 可转债, 货币基金, 全球市场, 量化, 技术指标, 组合优化, 风险平价, 夏普, 回测, 价值投资, 蒙特卡洛, VaR, Sharpe, 涨跌预测, 量化分析, 全资产, 因子库, 策略回测, 数据质量, 相对强度, RPS, 板块宽度, 轮动周期, 市场体制, 牛熊, 波动率, 市场内含, 指数估值, PE分位, 情景, 软着陆, 硬着陆, 衰退, 通胀, 校准, 自上而下, 主题板块, AI算力, 人形机器人, 语音, 语音交互, Kelly, 回撤剖析, 滚动夏普, 跟踪误差, 信息比率, JB检验, 大佬, 圆桌, 大师策略, 索罗斯, 神奇公式, 反身性, 批量并行, 知识库, IMA, Dify, Obsidian, RAGFlow, FastGPT, MaxKB, 语雀, 飞书, Notion, 思源, Logseq, 存档, 回读, 笔记, AI解读, DeepSeek, OpenAI, Ollama, LLM, AI深度解读, 智能分析, 多源数据, 数据源切换, 自动降级, yfinance, Finnhub, MCP工具, MCP服务, 期货, 资金流, 主力资金, 北向资金, 融资融券, ETF申赎, 聪明钱, 龙虎榜, 基差, 跨期套利, 展期收益, 升贴水, 持仓量, 组合诊断, 再平衡, 业绩归因, 风格漂移, 金融六日, 外部MCP, MCP桥接, 多周期预测, 指数预测, 新浪, 雪球, 同花顺, 期货所, 交叉验证, 异常检测, ETag缓存, 时效分级]
  patterns:
    - "(分析|预测|查询|筛选|看下|看看).*(股票|基金|涨跌|行情|指数|板块|黄金|原油|债券|可转债)"
    - "(技术|指标|量化|基本面).*分析"
    - "(看涨|看跌|买入|卖出).*信号"
    - "(推荐|建议|排名).*(板块|个股|基金|投资|指数)"
    - "(护城河|DCF|内在价值|安全边际|财务健康).*(分析|评估)"
    - "(港股|美股|日经|标普|纳斯达克|恒生|道琼斯).*(分析|预测|筛选|走势)"
    - "(全球|跨市场|海外).*(指数|市场|分析)"
    - "(黄金|原油|商品|债券|期货).*(分析|预测|走势)"
    - "(政策|监管|宏观).*(解读|分析|影响)"
    - "(未来|下个|短期|长期).*(走势|趋势|涨跌)"
    - "(板块|行业).*(轮动|排名|推荐|趋势)"
    - "(市场体制|牛熊|震荡市).*(判断|分析|分类)"
    - "(情景|软着陆|硬着陆|衰退|通胀).*(分析|推演|预测)"
    - "(置信度|校准|可靠性).*(预测|评分)"
    - "(自上而下|市场全景|TopDown).*(分析|报告)"
    - "(五维|资金面|财经信息|社会舆情).*(分析|综合|评估)"
    - "(推演|涨跌预测|方向预测).*(股票|基金|期货|指数)"
    - "(PE|PB|估值).*(分位|历史|真实|估算)"
    - "(组合|仓位|资产配置).*(优化|风险平价|马科维茨|夏普)"
    - "(可转债|转债).*(分析|评分|转股|溢价)"
    - "(Kelly|回撤剖析|滚动夏普|跟踪误差|JB).*(计算|分析|检验)"
    - "(大佬|大师|圆桌).*(怎么看|观点|共识|参考)"
    - "(知识库|笔记).*(保存|存档|检索|回读|量化|同步)"
    - "(期货|合约|主力合约|升贴水|基差|龙虎榜).*(分析|预测|行情)"
    - "(资金流|主力|北向|融资融券|聪明钱|ETF).*(分析|流向|异动)"
    - "(组合|持仓|再平衡|业绩归因|风格漂移).*(诊断|分析|建议)"
    - "(多周期|1d|5d|1M|3M|6M).*(预测|方向|概率)"
    - "(指数|沪深300|上证指数|创业板).*(预测|PE|分位|方向)"
    - "(金融六日|外部MCP|桥接|MCP).*(配置|启动|连接)"
---

# 股票研究员 v11.0 — 多源强化 + AI 期货/资金流/指数/组合 + 金融六日 MCP 桥接

> 纯 Python 标准库核心，零 pip 依赖。覆盖 12 个全球市场 + 股票/基金/指数/债券/商品/期货/货币基金/可转债；数据源：腾讯 + 东方财富 + akshare + 新浪 + 雪球 + 同花顺 + yfinance（均免费无 Key）。

## ⚠️ 支持范围与限制（重要，请先读）

### v11.0 数据源（12 个）

| 数据源 | 标识 | 覆盖 | Key |
|------|------|------|-----|
| 东方财富 API | `eastmoney_api` | A 股/指数/资金流 | ❌ |
| 新浪财经 | `sina` 🆕 | A 股/港股/美股/K线 | ❌ |
| 雪球 | `xueqiu` 🆕 | A 股行情+情绪 | ❌ |
| 同花顺 | `tonghuashun` 🆕 | A 股行情+资金流 | ❌ |
| 期货交易所 | `futures_exchange` 🆕 | 上期所/大商所/郑商所 | ❌ |
| akshare | `akshare` | A 股/基金/期货/宏观/可转债 | ❌ |
| yfinance | `yfinance` | 全球市场 | ❌ |
| Finnhub | `finnhub` | 美股深度 | ✅ 可选 |
| 腾讯 | `tencent` | A 股/港股/美股 | ❌ |
| 外部 MCP | `external_mcp` 🆕 | 金融六日桥接 | 视子 MCP |

### 限制

| 限制 | 说明 |
|------|------|
| 🔴 需国内直连 | 腾讯/东财/新浪/雪球/同花顺为国内接口，开代理反而失败。v9.6 已固化导入即自动安装无代理 opener |
| 🔴 非实时数据 | 国内接口延迟约 3~5 秒，非交易时段返回收盘价 |
| 🔴 评分≠盈利 | 预测评分表示历史上相似条件下约 X% 概率上涨，不保证未来 |
| 🟡 不构成投资建议 | 仅供学习参考 |
| 🟡 akshare 可选 | 部分高级功能（基金净值/债券/可转债/宏观）需 `pip install akshare` |
| 🟡 金融六日 MCP | 配置 `STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND` 环境变量启用 |

## ⚡ 快速上手

```bash
# v11.0 新增功能
python -c "from stock_researcher import predict_multi_horizon; print(predict_multi_horizon('600519').overall_signal)"
python -c "from stock_researcher import get_router; r=get_router(); print(r.query_money_flow('600519').source)"
python -c "from stock_researcher import analyze; print(analyze('futures_analysis', {'contract':'AU2502', ...}).content[:200])"

# v10.0 + v9.x（兼容）
python scripts/stock_predict.py 600519
python scripts/stock_predict.py --masters 600519
python scripts/stock_predict.py --topdown cn
```

## MCP Server 20 工具（v11.0）

```bash
# 配置 Claude Code mcpServers
{
  "mcpServers": {
    "stock-researcher": {
      "command": "python",
      "args": ["./mcp_server.py"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-...",
        "PYTHONDONTWRITEBYTECODE": "1",
        # v11.0 可选：金融六日外部 MCP
        "STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND": "python jinrong_liuri.py",
        "STOCK_RESEARCHER_EXTERNAL_MCP_NAME": "金融六日",
        "STOCK_RESEARCHER_EXTERNAL_MCP_ENV_TOKEN": "your_token"
      }
    }
  }
}
```

工具分类：

| 类别 | 工具数 | 工具 |
|------|--------|------|
| 数据查询 | 5 | get_stock_quote / get_fund_nav / get_macro_data / **get_futures_quote** 🆕 / list_data_sources |
| AI 分析 | 11 | ai_analyze_stock / ai_analyze_fund / ai_analyze_market_regime / ai_analyze_master_council / ai_analyze_macro_outlook / ai_analyze_risk_report / ai_analyze_sector_rotation / **ai_analyze_futures** 🆕 / **ai_analyze_money_flow** 🆕 / **ai_analyze_index_forecast** 🆕 / **ai_analyze_portfolio** 🆕 |
| 量化分析 | 3 | run_master_council / quick_predict / **predict_multi_horizon** 🆕 |
| 系统 | 1 | get_skill_status |

## 🆕 v11.0 核心 API

```python
# 多周期预测（股票/基金/期货/指数通用）
from stock_researcher import predict_multi_horizon, calibrate_probability
result = predict_multi_horizon("600519", prices=[100, 101, ...])
print(result.overall_signal, result.overall_confidence)  # bullish, 0.85
for h, pred in result.horizons.items():
    print(f"{h}: {pred.direction} ({pred.probability*100:.0f}%) [{pred.range_low:.1f}%, {pred.range_high:.1f}%]")

# 多源数据 + 交叉验证
from stock_researcher import get_router, DataCategory
router = get_router()
result = router.query_with_validation("cn", DataCategory.REALTIME_QUOTE,
                                      validate_field="price", code="600519")
print(f"validated={result.validated}, confidence={result.confidence}, source_count={result.source_count}")

# 资金流 / 情绪 / 期货历史（v11.0 便捷方法）
flow = router.query_money_flow("600519")
sent = router.query_sentiment("600519")
hist = router.query_futures_history("AU2502", days=60)

# 概率校准
calibrated = calibrate_probability(0.7, history=[(0.7, True), (0.7, False), ...])
print(f"raw={calibrated.raw_probability}, calibrated={calibrated.calibrated_probability}")

# 外部 MCP 桥接（金融六日）
from stock_researcher import get_bridge
bridge = get_bridge()
bridge.auto_connect()  # 自动读取 STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND
status = bridge.status()
tools = bridge.list_sessions()
```

## 🆕 v11.0 AI 模板（11 类）

| 类别 | 模板 | 用途 |
|------|------|------|
| 现有 v10.0 | stock_analysis | 股票深度解读（财务+技术+情绪+预测） |
| | fund_analysis | 基金深度解读（业绩归因+风格+经理） |
| | market_regime 🆕增强 | 市场体制（新增 PCR/AH 折溢价/科创50/AD 比率） |
| | master_council | 大师圆桌综合（6 位大师观点汇总） |
| | macro_outlook 🆕增强 | 宏观环境（新增 房地产/社零/出口/DR007/Fed Funds） |
| | risk_report 🆕增强 | 风险评估（新增 流动性风险/通胀冲击/相关性矩阵） |
| | sector_rotation 🆕增强 | 板块轮动（新增 聪明钱动向/ETF 申赎方向） |
| 新增 v11.0 | **futures_analysis** | 期货专项（持仓/基差/龙虎榜/展期收益） |
| | **money_flow_analysis** | 资金流分析（主力/北向/融资/ETF/聪明钱） |
| | **index_forecast** | 指数预测（PE分位/RS评分/多周期方向） |
| | **portfolio_diagnosis** | 组合诊断（业绩归因/再平衡/风格漂移） |

## 📊 数据层 v11.0 增强

```python
# ETag 缓存（v11.0）
# 自动应用：http 客户端请求时附带 If-None-Match / If-Modified-Since
# 304 响应直接复用上次结果

# 时效分级
from stock_researcher.data_multi_source import DataFreshness, freshness_for_category
print(freshness_for_category(DataCategory.REALTIME_QUOTE))  # realtime (TTL 60s)

# 多源交叉验证
router = get_router()
results = router.query_with_validation("cn", DataCategory.REALTIME_QUOTE,
                                       validate_field="price", code="600519")
# 返回: QueryResult(validated, confidence, source_count, freshness, etag_hit)

# 异常值检测
from stock_researcher.data_multi_source import MultiSourceRouter
router2 = MultiSourceRouter()
cleaned = router2.detect_anomaly([100, 101, 99, 102, 100, 500])
# 返回剔除 500 后的列表
```

## 🎯 期货 v11.0 专项

```python
# 期货交易所路由
from stock_researcher.data_multi_source import FuturesExchangeAdapter
ad = FuturesExchangeAdapter()
print(ad._resolve_exchange("AU2502"))   # shfe (上期所)
print(ad._resolve_exchange("M2501"))    # dce (大商所)
print(ad._resolve_exchange("SR2501"))   # czce (郑商所)

# AI 期货分析
from stock_researcher import analyze
result = analyze("futures_analysis", {
    "contract": "AU2502", "symbol": "AU", "exchange": "SHFE",
    "price": "500", "change_pct": "1.0",
    "open_interest": "100000", "volume": "50000",
    "basis": "5", "roll_yield": "3.5",
    "top5_long": "...", "top5_short": "...",
    "forecast_5d": "[495, 505]",
})
print(result.content)
```

## 🤖 预测算法 v11.0

```python
from stock_researcher.prediction_v1100 import (
    predict_horizon, predict_multi_horizon,
    detect_asset_type, calibrate_probability,
    HORIZON_DAYS, HORIZON_WEIGHTS,
)

# 资产类型自动识别
print(detect_asset_type("600519"))      # stock
print(detect_asset_type("110022"))      # fund
print(detect_asset_type("AU2502"))      # futures
print(detect_asset_type("idx:000300"))  # index

# 多周期预测（权重：1d 10% + 5d 20% + 1M 30% + 3M 25% + 6M 15%）
result = predict_multi_horizon("600519", prices=[100, 101, 102, ...])
print(f"综合: {result.overall_signal}, 置信度: {result.overall_confidence}")

# 单周期
from stock_researcher.prediction_v1100 import predict_horizon
pred = predict_horizon(prices, horizon="1M", regime="bullish")
print(pred.direction, pred.expected_return, pred.range_low, pred.range_high)

# 概率校准
cal = calibrate_probability(0.7, history=[(0.65, True), (0.7, False), ...])
print(f"校准: {cal.raw_probability} → {cal.calibrated_probability}")
```

## 🧠 AI 深度解读配置

```bash
# 设置环境变量启用 LLM（推荐 DeepSeek，国内直连友好）
export DEEPSEEK_API_KEY=sk-xxx

# 或在 config/settings.json 填写 llm.api_key（不推荐）
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "temperature": 0.3,
    "max_tokens": 2000
  }
}
```

无 API Key 时自动降级到规则化模板输出。

## 📦 目录速查

```
stock_researcher/
├── data_multi_source.py        # v11.0 多源数据层（4 新适配器 + 交叉验证 + 异常检测）
├── ai_analysis_engine.py       # v11.0 AI 模板（7→11 类）
├── prediction_v1100.py         # v11.0 多周期预测器（新文件）
├── mcp_external_bridge.py      # v11.0 外部 MCP 桥接（新文件）
├── data_*.py                   # 数据源（akshare/东方财富/新浪/雪球/同花顺/期货所）
├── quantitative_*.py           # 量化（指标/因子/组合优化/MC/回测/债券/货基/可转债）
├── fusion_*.py                 # 十维信号融合多周期预测
├── core_*.py                   # 分析器/预测引擎/技术/估值
├── value_investing_*.py        # DCF/护城河/财务健康/管理层/行业
├── funds.py / index_analysis_*.py / sector_analysis_*.py / agents_*/ ...
├── constants.py                # v11.0 VERSION="11.0.0"
```

## ❓ 常见问题

### Q1: 金融六日 MCP 怎么接入？
**A**: 设置环境变量：
```bash
export STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND="python jinrong_liuri_mcp_server.py"
export STOCK_RESEARCHER_EXTERNAL_MCP_NAME="金融六日"  # 可选
export STOCK_RESEARCHER_EXTERNAL_MCP_ENV_TOKEN="xxx"  # 可选透传环境变量
```
然后调用 `bridge.auto_connect()` 或 `router.register_external_mcp(command)`。

### Q2: v11.0 数据获取更及时了吗？
**A**: 是的。v11.0 引入：
- ETag/If-Modified-Since 缓存（304 直接复用）
- 时效分级标签（数据获取时间戳 + freshness 字段）
- 多源交叉验证（同一字段多源比对）
- 3σ + IQR 二阶段异常值检测

### Q3: 新增数据源需要 Key 吗？
**A**: 新浪/雪球/同花顺/期货所都不需要 Key。Finnhub 需要 API Key。

### Q4: 预测评分 70 分是不是一定会涨？
**A**: **不是**。评分 70 表示历史上相似条件下约 70% 上涨，不保证未来。

### Q5: 期货分析支持哪些交易所？
**A**: v11.0 支持上期所（SHFE）/ 大商所（DCE）/ 郑商所（CZCE）。中金所（CFFEX）可通过 akshare 补充。

### Q6: 如何使用多周期预测？
**A**: `predict_multi_horizon(code, prices=...)，返回 1d/5d/1M/3M/6M 五个周期的方向+概率+置信度+区间。`

## 免责声明

> ⚠️ **本工具仅供学习参考，不构成任何形式的投资建议。** 股市有风险，投资需谨慎。