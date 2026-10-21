---
name: crypto-quant-analysis
description: "Enhanced cryptocurrency-only quantitative analysis skill for crypto/digital assets. Triggers on technical indicators (RSI/MACD/Bollinger/EMA), statistical analysis (correlation/volatility/regression), strategy backtesting (MA cross/RSI/Bollinger), portfolio optimization (mean-variance/risk parity), risk metrics (VaR/max drawdown/Sharpe), category-specific fundamental analysis (DeFi TVL/Meme narrative/L1 ecosystem), and on-chain data (protocol TVL/fees/chain stats). Features multi-source data cross-validation (CoinGecko + exchanges), network-aware exchange selection (Binance/Bybit vs Gate/OKX), and auto-detected token categorization. Never use for stocks, equities, forex, commodities, or traditional securities."
agent_created: true
---

# Crypto Quantitative Analysis v2.2

**Enhanced cryptocurrency quantitative analysis with multi-source data, category-aware fundamentals, and on-chain metrics.**

## What's New in v2.2

- **Comprehensive JSON output examples**: Every action now includes sample output — you know exactly what to expect before asking
- **Beginner-friendly FAQ**: 10+ common questions answered with plain language
- **Data reliability transparency**: Clear explanation of data delays, API stability, and network fallback behavior
- **Token coverage expanded to 400+**: 400 CoinGecko IDs + 400 hardcoded categories with exchange fallback for any listed token
- **Enhanced network resilience**: Progressive timeouts (3s→5s→10s), connection pooling, graceful degradation for all data sources
- **Simplified trigger language**: Actions now work with natural Chinese questions like "BTC 怎么样？" or "看看 ETH 的基本面"

## What's New in v2.1

- **Token coverage expanded 4x**: 272 CoinGecko IDs + 284 hardcoded categories (was 60)
- **Unknown token fallback**: Exchange ticker data provides price/volume for ANY listed token
- **Friendly error messages**: Every failure path now returns `status` + `message` + `guidance`
- **Auto-detection resilience**: Unknown tokens get helpful analysis instead of empty `other`

## What's New in v2.0

| Feature | v1.0 | v2.0 |
|---|---|---|
| Data sources | Single exchange (Gate → OKX) | CoinGecko + Binance/Bybit or Gate/OKX (network-aware) |
| Cross-validation | None | Multi-source price comparison with deviation alerts |
| Token analysis | Generic technical only | Category-specific fundamentals (DeFi/Meme/L1/L2/Gaming) |
| On-chain data | None | DeFiLlama TVL, fees, revenue, chain metrics |
| Network detection | Static | Auto-detect China/Global, suggest optimal sources |
| Category detection | None | CoinGecko + hardcoded taxonomy fallback |

---

## Quick Start — 新手入门（3分钟上手）

> **第一次使用？** 你只需要记住一句话：**"帮我分析 [币种]"** 或 **"[币种] 怎么样？"** — 系统会自动识别意图并选择合适的分析工具。

### 最常用的5种问法

| 你想了解什么 | 直接问 | 系统会自动执行 |
|---|---|---|
| 某个币现在多少钱？ | "BTC 现在多少钱？" | `data_fetch.py --action ticker --symbol BTC` |
| 这个币技术面如何？ | "帮我分析 BTC 的技术指标" | `technical.py --action all --symbol BTC` |
| 这个币基本面怎么样？ | "UNI 基本面怎么样？" | `fundamental.py --action all --symbol UNI` |
| 几个币之间有什么关系？ | "BTC 和 ETH 的相关性" | `stats.py --action correlation --symbols BTC,ETH` |
| 投资组合怎么配？ | "帮我优化 BTC,ETH,SOL 组合" | `portfolio.py --action optimize --symbols BTC,ETH,SOL` |

### 分析结果长什么样？

所有分析结果都以 **JSON** 格式输出，然后我会用中文为你解读。不用担心看不懂代码——我会帮你把数字变成有实际意义的判断。

**示例：** 你问 "BTC 怎么样？"，我会返回：
```
BTC 当前价格 $63,245 (CoinGecko + Binance 交叉验证，偏差 0.1% — 数据可靠)
网络环境：全球网络，使用 Binance + CoinGecko

📊 技术指标：
  RSI: 52.3 (中性，既不超买也不超卖)
  MACD: 看多信号，柱状线正在转正
  布林带: 价格位于中轨上方，趋势偏强

📈 基本面（BTC 属于"价值存储"类别）：
  距离历史高点: -12% (仍有一定上涨空间)
  流通供应量: 19,700,000 BTC (93% 已挖出)
  基本面评分: 8/10 (优秀)

💡 建议：技术面中性偏多，基本面稳健。可关注是否突破前高。
```

---

## Scope

### ✅ 这个 Skill 能做什么

- **加密货币市场数据**：价格、成交量、历史K线、市值排名
- **技术分析**：RSI、MACD、布林带、EMA、ATR、随机指标
- **统计分析**：相关性、波动率、趋势回归、收益分布
- **策略回测**：均线交叉、RSI 均值回归、布林带策略
- **投资组合优化**：马科维茨优化、风险平价、VaR
- **分类基本面分析**：DeFi 的 TVL/收入、Meme 的叙事/社区、L1 的生态活跃度
- **链上数据**：协议 TVL、费用收入、公链生态排名
- **多币种批量分析**：同时分析多个代币，做交叉验证

### ❌ 这个 Skill 不能做什么

- **股票/证券分析**：不处理 A 股、港股、美股、ETF、债券
- **外汇/大宗商品**：不处理美元、黄金、石油
- **公司财报**：不分析上市公司财务数据
- **预测价格**：所有分析基于历史数据，不提供价格预测

### ⚠️ 边界说明（通俗版）

**数据来源与稳定性：**
- 价格数据来自 CoinGecko（聚合多个交易所）+ 交易所直连（Binance/Bybit/Gate/OKX）
- **CoinGecko 数据**：通常延迟 1-5 分钟，免费 API 每分钟约 40 次请求限制
- **交易所数据**：通常延迟 1-3 分钟，交易活跃时更新更快
- **链上数据（DeFiLlama）**：TVL 和费用数据通常延迟 1-24 小时，因为链上数据需要同步
- **国内网络环境**：CoinGecko 和 DeFiLlama 可能访问较慢或偶尔超时，系统会自动切换到国内可用的交易所数据源（Gate/OKX），基础价格和技术分析不受影响

**极端网络情况的处理：**
- 如果 CoinGecko 完全无法访问 → 自动使用交易所数据（价格/成交量仍可用）
- 如果交易所 API 也超时 → 返回清晰的错误信息，说明哪些数据可用、哪些不可用
- 所有 API 调用有 3-5-10 秒渐进式超时，不会卡住
- 如果某个代币在任何交易所都没有交易对 → 明确告知 "该代币当前无活跃交易数据"

**数据可靠性：**
- 价格数据通过两个独立来源交叉验证，偏差 < 2% 视为可靠
- 偏差 2-5% 会提示 "数据存在差异，可能是不同流动性池导致"
- 偏差 > 5% 会强烈警告 "数据可能陈旧或来自孤立市场"
- 链上数据（TVL、费用）依赖 DeFiLlama，如果该服务不可用，会明确标注 "链上数据暂不可用"

---

## Trigger Conditions

### 简单问法（推荐）

直接用自然语言问，不用记命令：

| 你想问 | 示例 |
|---|---|
| 查价格 | "BTC 现在多少钱？" / "ETH 价格" / "查查 SOL 的行情" |
| 技术指标 | "BTC 技术面怎么样？" / "分析 ETH 的 RSI 和 MACD" / "看看 UNI 的技术指标" |
| 基本面 | "UNI 基本面如何？" / "AAVE 的 DeFi 指标" / "DOGE 是 Meme 币吗？" |
| 链上数据 | "UNI 的 TVL 多少？" / "ETH 链上生态数据" / "DeFi 协议排名" |
| 统计分析 | "BTC 和 ETH 相关性如何？" / "ETH 波动率" / "BTC 收益分布" |
| 组合分析 | "帮我优化 BTC,ETH,SOL 组合" / "BTC 和 ETH 投资组合" |
| 回测 | "回测 BTC 均线策略" / "BTC RSI 策略回测" |

### 复杂功能（需要明确指定）

| 功能 | 你需要怎么说 | 系统会执行 |
|---|---|---|
| 批量查多个币 | "BTC、ETH、SOL 价格都查一下" | `data_fetch.py --action multi_tickers --symbols BTC,ETH,SOL` |
| 历史K线 | "BTC 过去一年的日线" | `data_fetch.py --action ohlcv --symbol BTC --timeframe 1d --limit 365` |
| 分类基本面 | "UNI 的 DeFi 指标详细分析" | `fundamental.py --action defi --symbol UNI` |
| 协议费用 | "AAVE 的收入和费用" | `onchain.py --action protocol_fees --symbol AAVE` |
| 组合风险 | "BTC 和 ETH 组合的风险价值" | `portfolio.py --action var --symbols BTC,ETH` |
| 相关性矩阵 | "BTC、ETH、SOL、AVAX 的相关性" | `stats.py --action correlation --symbols BTC,ETH,SOL,AVAX` |
| 波动率分析 | "BTC 的波动率" | `stats.py --action volatility --symbol BTC` |
| 趋势回归 | "BTC 趋势分析" | `stats.py --action regression --symbol BTC` |
| 收益统计 | "BTC 收益率统计" | `stats.py --action returns_stats --symbol BTC` |
| 风险平价 | "BTC、ETH、SOL 风险平价配置" | `portfolio.py --action risk_parity --symbols BTC,ETH,SOL` |
| 布林带回测 | "回测 BTC 布林带策略" | `backtest.py --action bollinger --symbol BTC` |
| RSI 回测 | "回测 BTC RSI 策略" | `backtest.py --action rsi --symbol BTC` |
| 链上排名 | "DeFi 协议 TVL 排名" | `onchain.py --action protocol_ranking --limit 10` |
| 公链排名 | "公链 TVL 排名" | `onchain.py --action chain_ranking` |
| 网络检查 | "检查网络环境" | `data_fetch.py --action network_check` |
| 链上状态 | "链上数据可用吗？" | `onchain.py --action status` |
| 热门币种 | "现在热门的币有哪些？" | `data_fetch.py --action trending` |
| 币种信息 | "BTC 是什么币？" | `data_fetch.py --action coin_info --symbol BTC` |
| 代币分类 | "PEPE 是什么类型的币？" | `fundamental.py --action category --symbol PEPE` |

### 完整触发条件表

#### 1. 多源市场数据
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "获取 BTC 价格" / "BTC price" | `data_fetch.py` | `ticker` | 价格 + 交叉验证报告 |
| "BTC/ETH/SOL 行情" | `data_fetch.py` | `multi_tickers` | 多币种价格对比 |
| "BTC 历史K线" / "OHLCV" | `data_fetch.py` | `ohlcv` | 时间序列数据 |
| "查 BTC 基本信息" / "coin info" | `data_fetch.py` | `coin_info` | 币种元数据 |
| "当前热门币" / "trending" | `data_fetch.py` | `trending` | 热门币种列表 |
| "检查网络环境" / "network check" | `data_fetch.py` | `network_check` | 网络环境报告 |

#### 2. 技术指标
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "分析 BTC 技术指标" / "Check RSI/MACD" | `technical.py` | `rsi` / `macd` / `bollinger` / `all` | 指标数值 + 信号判断 |

#### 3. 统计分析
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "BTC 和 ETH 相关性" / "correlation" | `stats.py` | `correlation` | 相关性矩阵 |
| "波动率分析" / "volatility" | `stats.py` | `volatility` | 年化波动率 + 最大回撤 |
| "趋势回归分析" / "regression" | `stats.py` | `regression` | 回归系数 + 趋势判断 |
| "收益率统计" / "returns stats" | `stats.py` | `returns_stats` | 均值、标准差、偏度、峰度 |

#### 4. 策略回测
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "回测均线策略" / "Backtest MA cross" | `backtest.py` | `ma_cross` | 收益率 + 夏普比率 + 最大回撤 |
| "回测 RSI 策略" | `backtest.py` | `rsi` | 策略绩效指标 |
| "回测布林带策略" | `backtest.py` | `bollinger` | 策略绩效指标 |

#### 5. 投资组合与风险
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "组合优化" / "portfolio optimization" | `portfolio.py` | `optimize` | 最优权重分配 |
| "风险平价" / "risk parity" | `portfolio.py` | `risk_parity` | 等风险权重 |
| "VaR" / "风险价值" | `portfolio.py` | `var` | 风险价值 |

#### 6. 分类基本面分析（v2.2 新增）
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "UNI 基本面分析" / "fundamental" | `fundamental.py` | `all` | 分类检测 + 多维指标 + 评分 |
| "AAVE DeFi 指标" / "TVL analysis" | `fundamental.py` | `defi` | TVL/MC 比、收入、费用 |
| "DOGE meme 分析" / "meme metrics" | `fundamental.py` | `meme` | 社交信号、持仓集中度 |
| "ETH L1 分析" / "L1 metrics" | `fundamental.py` | `l1` | 生态 TVL、开发者活动 |
| "识别代币类别" / "category detect" | `fundamental.py` | `category` | 类别 + 置信度 |

#### 7. 链上数据（v2.2 新增）
| 用户意图 | 脚本 | 动作 | 示例输出 |
|---|---|---|---|
| "UNI 协议 TVL" / "protocol TVL" | `onchain.py` | `protocol_tvl` | TVL 按链细分 |
| "协议费用收入" / "protocol fees" | `onchain.py` | `protocol_fees` | 日度/年化费用 |
| "ETH 链上数据" / "chain stats" | `onchain.py` | `chain_stats` | 链生态指标 |
| "DeFi 协议排名" / "protocol ranking" | `onchain.py` | `protocol_ranking` | 排名列表 |
| "公链 TVL 排名" / "chain ranking" | `onchain.py` | `chain_ranking` | 排名列表 |
| "链上数据可用性检查" / "onchain status" | `onchain.py` | `status` | 可用性报告 |

---

## 实际输出样例（JSON）

> **新手提示：** 你不需要看懂 JSON。我会把这些数字翻译成中文解读。这里放出来是为了让你知道系统内部会输出什么。

### 样例 1：价格查询（ticker）

```json
{
  "symbol": "BTC/USDT",
  "timestamp": "2024-07-18T07:30:00Z",
  "environment": "global",
  "data_sources": {
    "coingecko": {"price": 63245.12, "source": "CoinGecko"},
    "exchange": {"price": 63238.50, "source": "Binance", "exchange": "binance"}
  },
  "cross_validation": {
    "coingecko_price": 63245.12,
    "exchange_price": 63238.50,
    "deviation_pct": 0.01,
    "deviation_status": "可靠 (偏差 < 2%)",
    "validated_price": 63241.81,
    "validated_by": "median of 2 sources"
  },
  "price_usd": 63241.81,
  "change_24h_pct": 2.34,
  "change_7d_pct": -1.56,
  "market_cap_rank": 1,
  "volume_24h_usd": 28500000000,
  "high_24h": 64500.00,
  "low_24h": 62100.00,
  "network_message": "当前网络环境为海外，已使用 Binance + CoinGecko 进行交叉核对。"
}
```

**你会看到的中文解读：**
> BTC 当前价格 $63,242（CoinGecko $63,245 + Binance $63,239 交叉验证，偏差仅 0.01%，数据可靠）
> 24h 涨跌：+2.34%（红色，涨），市值排名：第 1 位
> 24h 成交量：$285 亿

---

### 样例 2：技术指标（all）

```json
{
  "symbol": "BTC/USDT",
  "timeframe": "1d",
  "network": "global",
  "category": "store_of_value",
  "category_confidence": "high",
  "close": 63245.12,
  "rsi_14": 52.3,
  "macd_line": 145.2,
  "macd_signal": -89.5,
  "macd_histogram": 234.7,
  "bb_upper": 68500.00,
  "bb_middle": 63200.00,
  "bb_lower": 57900.00,
  "ema_7": 62800.00,
  "ema_25": 61500.00,
  "ema_99": 59800.00,
  "atr_14": 1800.50,
  "stoch_k": 65.4,
  "stoch_d": 58.2,
  "interpretation": {
    "rsi": "中性 (52.3) — 既不超买也不超卖",
    "macd": "看多 — MACD 线上穿信号线，柱状线转正",
    "bollinger": "价格位于中轨上方，接近上轨 — 偏强但注意回调风险",
    "stoch": "中性偏强 (65.4) — 未进入超买区"
  }
}
```

**你会看到的中文解读：**
> 📊 BTC 技术面分析：
> - RSI 52.3：中性，市场没有明显的超买或超卖
> - MACD 看多：快线已上穿慢线，柱状线正在放大，短期趋势偏强
> - 布林带：价格位于中轨（$63,200）上方，接近上轨（$68,500），注意冲高回落风险
> - 随机指标：65.4，中性偏强，未进入超买区（80以上）
> 💡 综合判断：技术面中性偏多，短期有上涨动能但接近阻力区

---

### 样例 3：分类基本面分析（DeFi — AAVE）

```json
{
  "symbol": "AAVE/USDT",
  "category": "defi",
  "category_detection": {
    "category": "defi",
    "confidence": "high",
    "source": "hardcoded"
  },
  "analysis": {
    "price_usd": 95.23,
    "market_cap_usd": 1420000000,
    "market_cap_rank": 45,
    "tvl": 12500000000,
    "tvl_usd": "12.5B",
    "tvl_chains": {
      "ethereum": "8.2B",
      "polygon": "2.1B",
      "avalanche": "1.8B",
      "arbitrum": "0.4B"
    },
    "tvl_mc_ratio": 8.79,
    "tvl_mc_rating": "严重低估 (TVL 远高于市值)",
    "protocol_revenue_annualized": 156000000,
    "fees_30d": 42000000,
    "fee_trend": "增长中",
    "holders_top10_pct": 35.2,
    "holders_top50_pct": 62.1
  },
  "fundamental_score": 8.5,
  "score_breakdown": {
    "tvl_mc_ratio": 3.0,
    "revenue": 2.5,
    "fee_trend": 2.0,
    "market_position": 1.0
  },
  "rating": "excellent",
  "rating_text": "优秀",
  "recommendation": "TVL/MC 比率 8.79 显示严重低估，协议收入稳健，建议关注费用增长趋势。"
}
```

**你会看到的中文解读：**
> 📈 AAVE 基本面分析（DeFi 类别）：
> - 当前价格：$95.23，市值：$14.2 亿（排名 45）
> - TVL（总锁仓价值）：$125 亿（Ethereum $82 亿 + Polygon $21 亿 + Avalanche $18 亿 + Arbitrum $4 亿）
> - TVL/MC 比率：8.79 — 严重低估（TVL 远高于市值，说明协议实际使用价值被低估）
> - 年化协议收入：$1.56 亿，近30天费用：$4,200 万，趋势：增长中
> - 基本面评分：8.5/10（优秀）
> 💡 建议：TVL/MC 比率显示严重低估，协议收入稳健，可关注费用增长是否能持续带动代币价值重估

---

### 样例 4：Meme 币基本面（DOGE）

```json
{
  "symbol": "DOGE/USDT",
  "category": "meme",
  "category_detection": {
    "category": "meme",
    "confidence": "high",
    "source": "hardcoded"
  },
  "market_data": {
    "price_usd": 0.1245,
    "market_cap_usd": 17800000000,
    "volume_24h_usd": 850000000
  },
  "community": {
    "twitter_followers": 3400000,
    "reddit_subscribers": 2400000,
    "liquidity_score": 72
  },
  "risk_metrics": {
    "holders_top10_pct": 46.8,
    "holders_top50_pct": 68.2,
    "concentration_risk": "中等偏高 — Top 10 钱包持有 46.8%"
  },
  "momentum": {
    "change_24h_pct": 5.2,
    "change_7d_pct": -3.1,
    "change_30d_pct": 12.4
  },
  "survival": {
    "genesis_date": "2013-12-06",
    "age_days": 3860,
    "survival_score": "极高 — 2013年诞生，历经多次牛熊周期"
  },
  "fundamental_score": 5.0,
  "score_breakdown": {
    "community": 1.5,
    "survival": 2.0,
    "liquidity": 1.0,
    "momentum": 0.5
  },
  "rating": "fair",
  "rating_text": "中等",
  "risk_narrative": "Meme 币受社区情绪驱动，DOGE 社区活跃且历史悠久，但持币集中度偏高，需注意大户砸盘风险。"
}
```

**你会看到的中文解读：**
> 🐕 DOGE 基本面分析（Meme 类别）：
> - 当前价格：$0.1245，市值：$178 亿，24h 成交：$8.5 亿
> - 社区：Twitter 340 万粉丝 + Reddit 240 万订阅，流动性评分 72（良好）
> - 持币集中度：Top 10 钱包持有 46.8% — 中等偏高风险，需关注大户动向
> - 生存力：2013 年诞生，已存在 10+ 年，经历多次牛熊 — 在 Meme 币中属于"活化石"
> - 基本面评分：5/10（中等）— Meme 币评分体系不同，5 分已属不错
> - 近30天涨幅：+12.4%
> 💡 风险提醒：Meme 币受情绪驱动严重，DOGE 虽然历史悠久但集中度偏高，注意大户砸盘风险。建议仅用小仓位参与。

---

### 样例 5：链上数据（协议 TVL）

```json
{
  "symbol": "UNI",
  "protocol": "Uniswap",
  "tvl": 4200000000,
  "tvl_usd": "$4.2B",
  "tvl_change_24h": -1.2,
  "tvl_change_7d": 3.5,
  "tvl_change_30d": -5.8,
  "chains": {
    "ethereum": {"tvl": 3800000000, "share_pct": 90.5},
    "arbitrum": {"tvl": 280000000, "share_pct": 6.7},
    "polygon": {"tvl": 95000000, "share_pct": 2.3},
    "optimism": {"tvl": 25000000, "share_pct": 0.6}
  },
  "dominant_chain": "ethereum",
  "category": "DEX",
  "description": "Uniswap is a decentralized exchange protocol..."
}
```

**你会看到的中文解读：**
> 🔗 UNI（Uniswap）协议 TVL 分析：
> - 总 TVL：$42 亿（24h -1.2%，7d +3.5%，30d -5.8%）
> - 按链分布：Ethereum 90.5%（$38 亿）+ Arbitrum 6.7% + Polygon 2.3% + Optimism 0.6%
> - 主导地位链：Ethereum
> - 30天 TVL 下降 5.8%，可能反映市场整体流动性流出或竞争加剧

---

### 样例 6：相关性分析

```json
{
  "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"],
  "correlation_matrix": {
    "BTC/USDT": {"BTC/USDT": 1.00, "ETH/USDT": 0.82, "SOL/USDT": 0.65, "AVAX/USDT": 0.58},
    "ETH/USDT": {"BTC/USDT": 0.82, "ETH/USDT": 1.00, "SOL/USDT": 0.71, "AVAX/USDT": 0.63},
    "SOL/USDT": {"BTC/USDT": 0.65, "ETH/USDT": 0.71, "SOL/USDT": 1.00, "AVAX/USDT": 0.74},
    "AVAX/USDT": {"BTC/USDT": 0.58, "ETH/USDT": 0.63, "SOL/USDT": 0.74, "AVAX/USDT": 1.00}
  },
  "timeframe": "1d",
  "period": "90 days",
  "interpretation": {
    "BTC-ETH": "高度正相关 (0.82) — 同涨同跌概率高，分散化效果有限",
    "BTC-SOL": "中度正相关 (0.65) — 有一定分散化效果",
    "SOL-AVAX": "中度正相关 (0.74) — 同属于 L1 赛道，相关性偏高"
  }
}
```

**你会看到的中文解读：**
> 📊 BTC / ETH / SOL / AVAX 相关性分析（过去 90 天）：
> - BTC-ETH：0.82（高度正相关）— 同涨同跌概率高，分散化效果有限
> - SOL-AVAX：0.74（中度偏高）— 同属 L1 赛道，走势相似
> - BTC-SOL：0.65（中度正相关）— 有一定分散化效果
> 💡 建议：如果追求分散化，BTC+ETH 组合效果不好（相关性太高），可考虑 BTC+SOL 或 BTC+其他低相关性资产

---

### 样例 7：投资组合优化

```json
{
  "method": "max_sharpe",
  "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  "weights": {
    "BTC/USDT": 0.45,
    "ETH/USDT": 0.35,
    "SOL/USDT": 0.20
  },
  "expected_annual_return": 0.52,
  "expected_annual_volatility": 0.38,
  "sharpe_ratio": 1.21,
  "max_drawdown": -0.28,
  "var_95": -0.045,
  "interpretation": {
    "return": "预期年化收益 52%（基于历史数据）",
    "volatility": "预期年化波动率 38%（高风险）",
    "sharpe": "夏普比率 1.21（较好，超过 1.0）",
    "drawdown": "最大回撤 -28%（需控制仓位）",
    "var": "95% 置信度下单日最大损失约 4.5%"
  }
}
```

**你会看到的中文解读：**
> 📈 BTC/ETH/SOL 组合优化（马科维茨最大夏普比率）：
> - 最优配置：BTC 45% + ETH 35% + SOL 20%
> - 预期年化收益：52%（基于历史数据，不构成未来收益承诺）
> - 预期年化波动率：38%（高风险，适合风险承受能力较强的投资者）
> - 夏普比率：1.21（较好，超过 1.0 属于可接受范围）
> - 最大回撤：-28%（历史最大跌幅，需做好心理准备）
> - 风险价值（VaR 95%）：单日最大损失约 4.5%
> 💡 建议：这是一个高风险高收益组合，适合激进型投资者。建议定期再平衡，并控制总仓位不超过风险承受能力的 30%

---

## 多源数据架构

### 数据流

```
用户 Request
    │
    ▼
Network Detection (auto)
    ├── Global → Binance/Bybit + CoinGecko
    └── China  → Gate/OKX + CoinGecko
    │
    ▼
Price from Source A ──┐
Price from Source B ──┤── Cross-Validation
    │                 │    - Compare prices
    ▼                 │    - Check deviation
CoinGecko Data ───────┘    - Alert if >2%
    │
    ▼
Validated Result + Source Breakdown
```

### 交叉验证逻辑

1. 从 CoinGecko 获取价格（市场聚合）
2. 从交易所获取价格（Binance/Bybit 或 Gate/OKX）
3. 比较：偏差 > 2% 标记为 "数据差异"
4. 返回中位数价格作为验证值
5. 包含来源明细和偏差报告

### 网络环境检测

系统自动检测你的网络环境：
- **全球网络**：使用 Binance（主）/ Bybit（备）+ CoinGecko
- **中国大陆网络**：使用 Gate（主）/ OKX（备）+ CoinGecko — 同时输出明确提示建议数据源切换

运行 `data_fetch.py --action network_check` 手动检测。

如果检测到中国大陆网络，输出会包含：
> "当前网络环境为中国大陆，已自动切换为 Gate/OKX 交易所数据 + CoinGecko 进行交叉核对。"

---

## 分类基本面分析

### 自动检测

`fundamental.py --action all` 自动检测代币类别并应用合适的分析框架：

| 类别 | 示例代币 | 关键指标 | 数据源 |
|---|---|---|---|
| **DeFi** | UNI, AAVE, CRV, LDO | TVL, TVL/MC 比率, 协议收入, 年化费用 | DeFiLlama + CoinGecko |
| **Meme** | DOGE, SHIB, PEPE, WIF | 社交量, 持仓集中度, 交易所上市数, 社区增长 | CoinGecko |
| **L1** | ETH, SOL, AVAX, NEAR | 生态 TVL, 开发者活跃度, TVL/MC 比率 | DeFiLlama + CoinGecko |
| **L2** | ARB, OP, STRK | TVL, 活跃地址, 定序器收入 | DeFiLlama |
| **Gaming** | SAND, AXS, IMX | 市值, 社区规模, 流动性 | CoinGecko |
| **AI** | RENDER, FET, TAO | GitHub 活跃度, 叙事关联度, 合作伙伴 | CoinGecko |
| **Infra** | LINK, GRT, FIL | 集成数, 网络收入, 开发者活跃度 | CoinGecko |
| **Store of Value** | BTC | 存量-流量比, 哈希率, 已实现市值, 供给指标 | CoinGecko |
| **RWA** | ONDO, CFG | 资产锚定规模, 合作机构, 合规性 | CoinGecko |
| **Stablecoin** | USDT, USDC, DAI | 锚定稳定性, 储备透明度, 市值 | CoinGecko |

### DeFi 分析维度

```bash
fundamental.py --action defi --symbol UNI
```

输出：
- **TVL**（总锁仓价值）来自 DeFiLlama，含链级别细分
- **TVL/MC 比率**：>1.0 = 被低估，0.5-1.0 = 合理，<0.3 = 被高估
- **协议收入**：日度和年化收入
- **费用生成**：日度费用，30 天趋势
- **基本面评分**：0-10 加权评分，含详细明细
- **评级**：excellent / good / fair / weak

### Meme 分析维度

```bash
fundamental.py --action meme --symbol DOGE
```

输出：
- **市场数据**：价格、市值、成交量
- **社区信号**：Twitter 粉丝、Reddit 订阅者
- **流动性评分**：CoinGecko 流动性评级
- **生存指标**：诞生日期（越久 = 越成熟）
- **动量**：24h/7d/30d 价格变化
- **风险叙事**：持仓集中度警告、炒作周期风险
- **基本面评分**：0-10，含叙事特定权重
- **评级**：strong / good / speculative / high_risk

### L1/L2 分析维度

```bash
fundamental.py --action l1 --symbol ETH
```

输出：
- **生态 TVL**：该链上所有协议的 TVL 总和
- **TVL/MC 比率**：生态价值与代币市值对比
- **开发者活跃度**：GitHub stars、forks、近期提交
- **社区**：Twitter 粉丝、市值排名
- **基本面评分**：0-10，L1 指标加权

---

## 链上数据分析

### 协议 TVL

```bash
onchain.py --action protocol_tvl --symbol UNI
```

详细 TVL 分解：
- 总 TVL 含 24h/7d/30d 变化
- TVL 按链分布（如 "Ethereum: $3.2B, Arbitrum: $450M"）
- 主导链识别
- 协议类别和描述

### 协议费用与收入

```bash
onchain.py --action protocol_fees --symbol AAVE
```

费用和收入指标：
- 日度费用和收入，30 天平均
- 年化费用/收入估算
- 收入份额（收入 / 费用百分比）
- 费用对 TVL 比率
- 费用趋势方向（上涨/下跌）

### 链指标

```bash
onchain.py --action chain_stats --symbol ETH
```

链级别数据：
- 链 TVL 和 DeFi 主导地位百分比
- 链上协议数
- 整体 DeFi 生态排名

### 排名

```bash
onchain.py --action protocol_ranking --limit 10
onchain.py --action chain_ranking
```

### 链上数据可用性

```bash
onchain.py --action status
```

检查哪些链上数据源可访问并返回清晰状态报告。对于中国大陆网络，会标注哪些 API 可访问。

---

## Execution

所有分析通过 **Bash** 工具执行 Python 脚本。

### Python 环境

```bash
Python: {python_path}  # 可配置 — 在 skill 上下文中自动检测
Skills dir: {skill_dir}/scripts/
```

### 依赖

```bash
pip install ccxt pandas pandas_ta statsmodels scipy PyPortfolioOpt numpy requests
```

注意：`requests` 用于 API 调用但 `urllib` 是主要 HTTP 客户端（核心功能无需额外依赖）。所有外部 API 依赖（CoinGecko, DeFiLlama）通过免费、无需认证的 REST 端点访问。

### 脚本执行格式

```bash
python.exe {script}.py --action {action} [options]
```

所有脚本输出 **JSON** 到 stdout。

---

## Symbol 标准化

所有 symbol 输入自动标准化：

| 输入 | 标准化 |
|---|---|
| `BTC` | `BTC/USDT` |
| `btc` | `BTC/USDT` |
| `ETH/USDT` | `ETH/USDT` (不变) |
| `BTC,ETH,SOL` | `[BTC/USDT, ETH/USDT, SOL/USDT]` |

**重要：** 如果提供裸代码如 `SPK`，脚本查询交易所上的 `SPK/USDT`。如果该交易对不存在，会返回错误并列出可用的 USDT 交易对。助手**不得**回退到股票/证券解释。

---

## Script Reference

### `data_fetch.py` — 多源市场数据（v2.2）

```bash
python.exe data_fetch.py --action <action> [options]
```

| Action | 描述 | 关键选项 | 数据源 | 预期输出 |
|---|---|---|---|---|
| `ticker` | 单币种价格（含交叉验证） | `--symbol BTC` | CoinGecko + Exchange | 价格、涨跌幅、来源明细、验证报告 |
| `multi_tickers` | 批量价格查询 | `--symbols BTC,ETH,SOL` | CoinGecko + Exchange | 多币种对比表格 |
| `ohlcv` | 历史K线数据 | `--symbol BTC --timeframe 1d --limit 200` | Exchange | 时间序列（OHLCV） |
| `coin_info` | CoinGecko 元数据 | `--symbol UNI` | CoinGecko | 市值排名、社区数据、描述 |
| `trending` | 热门币种 | (none) | CoinGecko | 热门币种列表 |
| `network_check` | 环境检测 | (none) | 自检 | 网络环境报告 |

### `technical.py` — 技术指标（v2.2 增强）

```bash
python.exe technical.py --action <action> [options]
```

| Action | 描述 | 选项 | 预期输出 |
|---|---|---|---|
| `rsi` | RSI（相对强弱指数） | `--symbol BTC --timeframe 1d` | RSI 数值 + 超买/超卖判断 |
| `macd` | MACD | `--symbol BTC` | MACD 线、信号线、柱状线 + 多空判断 |
| `bollinger` | 布林带 | `--symbol BTC --length 20 --std 2.0` | 上/中/下轨 + 价格位置判断 |
| `all` | 所有指标 + 类别上下文（推荐） | `--symbol BTC` | 完整技术画像 + 综合解读 |

输出包含网络环境和代币类别上下文。

### `stats.py` — 统计分析（v2.2）

```bash
python.exe stats.py --action <action> [options]
```

| Action | 描述 | 选项 | 预期输出 |
|---|---|---|---|
| `correlation` | 相关性矩阵（多资产） | `--symbols BTC,ETH,SOL,AVAX` | 矩阵 + 分散化建议 |
| `volatility` | 年化波动率 + 最大回撤 | `--symbol BTC --timeframe 1d` | 波动率数值 + 风险评级 |
| `regression` | 线性趋势回归 | `--symbol BTC` | 回归系数 + 趋势判断 |
| `returns_stats` | 收益分布统计 | `--symbol BTC` | 均值、标准差、偏度、峰度 + 分布解读 |

### `backtest.py` — 策略回测（v2.2）

```bash
python.exe backtest.py --action <action> [options]
```

| Action | 描述 | 关键选项 | 预期输出 |
|---|---|---|---|
| `ma_cross` | 均线交叉 | `--fast 20 --slow 50` | 总收益率、夏普比率、最大回撤、胜率 |
| `rsi` | RSI 均值回归 | `--oversold 30 --overbought 70` | 同上 |
| `bollinger` | 布林带均值回归 | `--symbol BTC --timeframe 4h` | 同上 |

### `portfolio.py` — 投资组合优化（v2.2）

```bash
python.exe portfolio.py --action <action> [options]
```

| Action | 描述 | 选项 | 预期输出 |
|---|---|---|---|
| `optimize` | 马科维茨优化 | `--method max_sharpe\|min_volatility` | 最优权重、预期收益、波动率、夏普 |
| `risk_parity` | 风险平价 | `--symbols BTC,ETH,SOL,AVAX` | 等风险权重分配 |
| `var` | 风险价值（历史） | `--symbol BTC --confidence 0.95` | VaR 数值 + 金额解读 |

### `fundamental.py` — 分类基本面分析（v2.2）

```bash
python.exe fundamental.py --action <action> [options]
```

| Action | 描述 | 选项 | 预期输出 |
|---|---|---|---|
| `all` | 自动检测类别 + 综合分析（推荐） | `--symbol UNI` | 类别 + 多维指标 + 评分 + 建议 |
| `defi` | DeFi：TVL, TVL/MC, 收入, 费用 | `--symbol AAVE` | DeFi 专属指标 + 评分 |
| `meme` | Meme：社交, 叙事, 持仓指标 | `--symbol DOGE` | Meme 专属指标 + 评分 |
| `l1` | Layer 1：生态 TVL, 开发者活跃度 | `--symbol ETH` | L1 专属指标 + 评分 |
| `l2` | Layer 2：TVL, 定序器收入 | `--symbol ARB` | L2 专属指标 + 评分 |
| `sov` | 价值存储（BTC）：供给, ATH 指标 | `--symbol BTC` | BTC 专属指标 + 评分 |
| `category` | 仅类别检测 | `--symbol CRV` | 类别 + 置信度 + 来源 |

### `onchain.py` — 链上数据（v2.2）

```bash
python.exe onchain.py --action <action> [options]
```

| Action | 描述 | 选项 | 预期输出 |
|---|---|---|---|
| `protocol_tvl` | 协议 TVL 按链分解 | `--symbol UNI` | TVL 总额 + 链分布 |
| `protocol_fees` | 协议费用和收入 | `--symbol AAVE` | 费用/收入 + 趋势 |
| `chain_stats` | 链生态指标 | `--symbol ETH` 或 `--chain ethereum` | 链 TVL + 协议数 + 排名 |
| `protocol_ranking` | TVL 排名靠前的协议 | `--limit 20` | 排名列表 |
| `chain_ranking` | TVL 排名靠前的链 | `--limit 15` | 排名列表 |
| `status` | 链上数据可用性检查 | (none) | 可用性报告 |

---

## Output Format & Interpretation

所有脚本输出 **JSON** 到 stdout。助手应该：

1. 解析 JSON 提取关键数字
2. 用中文（或英文，按用户偏好）解释结果
3. 结合类别上下文高亮可操作信号
4. 根据发现建议后续分析

### 解读规则

#### 技术指标
- **RSI > 70**：超买（overbought），回调风险
- **RSI < 30**：超卖（oversold），反弹机会
- **MACD histogram > 0 + 转正**：看多信号
- **Bollinger price > upper band**：超买区; **< lower band**：超卖区
- **Stochastic K > 80 & D > 80**：超买区

#### 统计指标
- **Sharpe > 1**：较好; **> 2**：优秀
- **Skewness < 0**：左偏（crash risk，加密货币常见）
- **Kurtosis > 3**：厚尾分布（极端事件概率高）
- **Correlation > 0.7**：高度正相关（分散化效果有限）

#### 风险指标
- **VaR**：同时给出百分比和 USDT 金额解读
- **Max Drawdown < -20%**：高风险 — 建议控制仓位
- **Sortino > Sharpe**：上行波动率较小（正面信号）

#### 分类特定指标
- **DeFi — TVL/MC > 1.0**：相对于 TVL 被低估
- **Meme — 持仓集中度 > 50% (Top 10)**：高 rug 风险
- **L1 — 生态 TVL 增长**：生态增长是最核心的看多指标
- **L2 — 增长 TVL + 活跃地址**：采用率信号
- **BTC — 接近 ATH**：强势; **< 50% from ATH**：积累区间

#### 交叉验证
- **Deviation < 2%**：数据可靠，使用中位数价格
- **Deviation 2-5%**：数据存在差异，可能是不同流动性池
- **Deviation > 5%**：强烈警告 — 数据可能陈旧或来自孤立市场

#### 颜色惯例
- **涨 = 红色（Red）**，**跌 = 绿色（Green）** — 中国市场惯例

#### 语言惯例
- 仅使用加密货币圈术语：现货、合约、交易对、TVL、链上、DeFi、Memecoin、回撤
- 禁止：股票、公司、财报、PE、纳斯达克、A 股

---

## Exchange Configuration

| Environment | Primary | Fallback | Notes |
|---|---|---|---|
| **Global** | Binance | Bybit | 流动性充足，交易对最多 |
| **China** | Gate | OKX | 已验证中国大陆可访问 |

- **自动检测**：网络环境在脚本启动时自动检测
- **超时**：3 秒（首次）→ 5 秒（重试）→ 10 秒（最终），渐进式超时
- **速率限制**：所有 ccxt 交易所启用 `enableRateLimit: True`
- **CoinGecko 速率限制**：请求间隔 1.5 秒（免费版：~40 请求/分钟）
- **连接池**：复用 HTTP 连接减少延迟

如需手动设置网络环境，用户可通过脚本上下文设置 `DEFAULT_EXCHANGE` 和 `FALLBACK_EXCHANGE`。大多数情况下自动检测已足够。

---

## Example Workflows

### 工作流 1：完整代币分析

```
User: "帮我全面分析 UNI"

→ data_fetch.py --action ticker --symbol UNI
    (CoinGecko + exchange 交叉验证价格)
→ fundamental.py --action all --symbol UNI
    (自动检测为 DeFi：TVL、TVL/MC 比率、收入、费用)
→ technical.py --action all --symbol UNI
    (RSI、MACD、布林带、EMA)
→ onchain.py --action protocol_tvl --symbol UNI
    (按链细分的 TVL 分解)

汇总展示：
  "UNI 当前价格 $X.XX (CoinGecko + Binance 交叉验证，偏差 0.3%)
   类别：DeFi DEX，基本面评分 7/10（良好）
   TVL：$X.XB，TVL/MC 比率：X.XX（被低估）
   年化费用：$XXXM，趋势：增长中
   技术面：RSI XX（中性），MACD 看多，价格在布林带中轨附近
   建议：基本面良好，TVL/MC 比率显示相对低估。关注费用趋势是否能持续。"
```

### 工作流 2：多资产组合分析

```
User: "帮我优化 BTC,ETH,SOL,AVAX 组合"

→ data_fetch.py --action multi_tickers --symbols BTC,ETH,SOL,AVAX
→ stats.py --action correlation --symbols BTC,ETH,SOL,AVAX
→ portfolio.py --action optimize --symbols BTC,ETH,SOL,AVAX
→ portfolio.py --action var --symbol BTC
```

### 工作流 3：Meme 币分析

```
User: "分析一下 PEPE"

→ data_fetch.py --action ticker --symbol PEPE
→ fundamental.py --action all --symbol PEPE
    (自动检测为 Meme：社交信号、持仓数据、叙事)

输出重点：
  "PEPE 属于 Meme 币类别，基本面评分 3/10（投机级）
   核心叙事：Meme/社区驱动，流动性评分 XX
   持币集中度风险：需关注 Top 10 钱包占比
   注意：Meme 币受情绪驱动，基本面分析仅作参考"
```

### 工作流 4：链上数据深度分析

```
User: "AAVE 的协议收入怎么样？"

→ onchain.py --action protocol_fees --symbol AAVE
→ fundamental.py --action defi --symbol AAVE

输出重点：
  "AAVE 年化协议收入：$XXXM
   日度费用：$XXM，30 天趋势：上涨
   费用对 TVL 比率：X.XX%
   收入/费用比率：XX%（协议留存率）"
```

### 工作流 5：新币快速筛查

```
User: "帮我看看这个币 XYZ"

→ data_fetch.py --action ticker --symbol XYZ
    (如果交易所可查但 CoinGecko 无记录 → 返回交易所价格 + 未知代币提示)
→ fundamental.py --action category --symbol XYZ
    (返回类别检测 + 置信度 + 建议分析维度)
→ 如果价格数据可用但类别未知：
    "XYZ 在 Gate 交易所有活跃交易对，价格 $X.XX，但不在我们的 400+ 代币数据库中。
     建议先用 `category` 检测，然后选择 closest 的类别分析。"
```

---

## FAQ — 常见问题

### Q1: 为什么有时候价格数据和我在交易所看到的不一致？
**A:** 这是正常的。系统使用 CoinGecko（聚合多个交易所）+ 单个交易所（Binance/Bybit/Gate/OKX）进行交叉验证。如果两个来源偏差 < 2%，数据是可靠的；如果偏差 > 2%，会提示可能是不同流动性池或数据源延迟导致。交易所之间的价格差异很常见，尤其是低流动性代币。

### Q2: 我在中国大陆，哪些功能会受限？
**A:** 
- **基础功能完全可用**：价格查询、技术指标、统计分析、回测、组合优化 — 这些使用 Gate/OKX 交易所数据，国内可直接访问
- **可能受限**：链上数据（DeFiLlama API 偶尔在国内网络下连接慢），CoinGecko 详细数据（CoinGecko 主站有时访问慢）
- **自动处理**：如果某个数据源不可用，系统会自动切换并告知你哪些数据可用、哪些不可用

### Q3: 为什么有些小众币查不到数据？
**A:** 系统目前覆盖 400+ 主流代币。如果某个代币：
1. 在 CoinGecko 有记录 → 可以查价格 + 基本面
2. 在交易所上市但 CoinGecko 无记录 → 可以查价格 + 成交量（交易所数据）
3. 在交易所也没有交易对 → 会明确告知 "该代币当前无活跃交易数据"
我们会持续扩展覆盖范围。如果遇到未覆盖的代币，可以告知我们添加。

### Q4: 分析结果是投资建议吗？
**A:** 不是。所有分析都是基于历史数据的量化统计，不构成任何投资建议。加密货币市场波动极大，任何分析都只能作为参考，不能替代独立判断。请根据自身风险承受能力做出决策。

### Q5: 回测结果可靠吗？可以照着做吗？
**A:** 回测是基于历史数据的模拟，默认不含手续费和滑点（实际交易会有成本）。回测结果只能说明 "如果在过去用这套策略，结果会如何"，不能预测未来。建议使用回测来筛选策略方向，再用模拟盘或小额实盘验证。

### Q6: 技术面和基本面分析哪个更重要？
**A:** 不同类型的币侧重点不同：
- **DeFi / L1 / L2**：基本面（TVL、收入、生态）更重要，技术面辅助择时
- **Meme 币**：社区情绪和叙事更重要，技术面和基本面参考价值有限
- **BTC / ETH**：技术面和基本面都重要，长期看基本面（采用率、网络效应），短期看技术面（支撑/阻力）

### Q7: 组合优化的权重可以直接用吗？
**A:** 不建议直接照搬。组合优化是基于历史数据的数学最优解，但：
1. 历史数据不代表未来
2. 没有考虑你的个人风险偏好
3. 优化结果对输入数据很敏感，稍微改变历史区间结果可能不同
建议把优化结果作为参考起点，结合自身情况调整。

### Q8: 数据更新频率是多少？
**A:**
- 价格数据：1-5 分钟延迟（CoinGecko 聚合）/ 1-3 分钟（交易所直连）
- 技术指标：基于历史 K 线，实时计算
- 基本面数据：TVL/费用等链上数据通常延迟 1-24 小时（链上数据需要时间同步）
- 市值排名：CoinGecko 数据，延迟约 5-15 分钟

### Q9: 为什么 "交叉验证" 有时会报 "偏差 > 2%"？
**A:** 交叉验证比较 CoinGecko（全市场聚合）和单个交易所（Binance/Bybit/Gate/OKX）的价格。常见原因：
1. 该币种在不同交易所的流动性差异大，导致价格差异
2. 某个交易所该币种的深度不足，大单导致价格偏离
3. 数据同步延迟（CoinGecko 聚合有延迟，交易所是实时）
如果偏差 < 5%，通常无需担心；如果偏差 > 5%，建议谨慎交易该币种。

### Q10: 我想分析的币不在列表里，怎么办？
**A:** 三步走：
1. 直接问："帮我分析 XXX" — 系统会尝试通过交易所获取任何上市代币的价格数据
2. 如果基本面分析受限："XXX 基本面" — 系统会返回交易所数据 + 说明该币不在数据库中
3. 如果完全查不到：系统会明确告知，并建议检查币种代码是否正确（例如 PEOPLE 不是 PEOPLES）

### Q11: 这套工具适合什么样的用户？
**A:**
- **新手**：想快速了解某个币的技术面和基本面，不用翻多个网站
- **进阶玩家**：需要多币种对比、相关性分析、组合优化
- **量化爱好者**：需要策略回测、统计分析、风险指标
- **不适合**：需要实时交易信号（数据有延迟）、需要公司基本面分析（这不是股票工具）

### Q12: 如何知道当前网络环境是 "国内" 还是 "海外"？
**A:** 直接问："检查网络环境" 或运行 `data_fetch.py --action network_check`。系统会检测：
- 国内网络：使用 Gate/OKX（主）+ CoinGecko（辅助）
- 海外网络：使用 Binance/Bybit（主）+ CoinGecko（辅助）
- 如果检测失败：默认使用 Gate/OKX 作为安全回退

---

## Dependency Summary

| Dependency | Purpose | Required? |
|---|---|---|
| `ccxt` | 交易所数据（Binance/Bybit/Gate/OKX） | Required |
| `pandas` | 数据操作 | Required |
| `pandas_ta` | 技术指标 | Required |
| `numpy` | 数值计算 | Required |
| `statsmodels` | 回归分析 | Required (stats.py) |
| `scipy` | 统计检验, VaR 参数化 | Required |
| `PyPortfolioOpt` | MVO 优化 | Optional（回退到等权） |
| `urllib` (stdlib) | CoinGecko/DeFiLlama API 调用 | 内置 |

无需 API Key。所有外部数据源（CoinGecko, DeFiLlama）使用免费、公共 REST API。

---

## File Structure

```
skills/crypto-quant-analysis/
├── SKILL.md                    # 本文档
└── scripts/
    ├── utils.py                # 核心：网络检测、CoinGecko/DeFiLlama 客户端、交叉验证、分类检测
    ├── data_fetch.py           # 多源市场数据（含交叉验证）
    ├── technical.py            # 技术指标（含类别上下文）
    ├── stats.py                # 统计分析
    ├── backtest.py             # 策略回测
    ├── portfolio.py            # 投资组合优化与风险
    ├── fundamental.py          # 分类基本面分析（v2.2）
    └── onchain.py              # 链上数据分析（v2.2）
```

---

## Notes

- **不构成投资建议**：所有分析都是量化且数据驱动的。历史数据不保证未来结果。
- **数据新鲜度**：ccxt 交易所数据可能略有延迟。CoinGecko 聚合跨交易所数据。交叉验证帮助识别陈旧数据。
- **速率限制**：CoinGecko 免费 API 有速率限制。优先批量查询而非单独请求。脚本自动处理速率限制。
- **优雅降级**：如果 DeFiLlama 不可达，TVL 和链上指标返回 null 并附状态说明，而非抛出错误。
- **网络韧性**：交易所选择自动适配网络环境。所有 API 调用有 3-5-10 秒渐进式超时。
- **未列出代币**：如果代币代码在交易所没有活跃交易对，脚本会明确报告 — 且绝不回退到股票/证券数据库。
