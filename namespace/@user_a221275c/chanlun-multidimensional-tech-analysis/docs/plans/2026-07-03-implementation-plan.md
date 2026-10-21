# 缠论多维技术分析 — 实施计划

> **For implementer:** Use TDD throughout. Write failing test first. Watch it fail. Then implement.

**Goal:** 构建融合缠论+K线形态+资金流向+成交量的多维技术分析SKILL，输出ECharts驱动的HTML交互报告

**Architecture:** 分层架构：TDX数据层 → 四维分析引擎（缠论/K线/资金/量）→ 信号融合 → HTML报告模板

**Tech Stack:** Python 3.11+, pandas, numpy, ECharts (CDN), TDX MCP Connector

---

## 模块依赖图

```
tdx_fetcher.py (数据层)
    ↓
chan_engine.py ─┬─ candlestick_recognizer.py ─┬─ fund_flow_analyzer.py ─┬─ volume_analyzer.py
    ↓            ↓                              ↓                         ↓
    └────────────┴──────────────────────────────┴─────────────────────────┘
                                      ↓
                              signal_fusion.py
                                      ↓
                    report_template.html
                                      ↓
                                  SKILL.md
```

## 接口契约

### 所有分析模块的输入输出标准

**输入**: `pd.DataFrame` with columns:
- date (datetime), open, high, low, close, volume (float)

**输出**: `dict` with keys:
- signal: float (-1.0 ~ +1.0)
- confidence: float (0.0 ~ 1.0)
- details: dict (模块特定的详细分析结果)

---

### Task 1: 项目骨架

**Files:**
- Create: `engine/__init__.py`, `data/__init__.py`
- Create: `tests/__init__.py`

**实现:**
- 空 `__init__.py` 文件，设置包结构

---

### Task 2: TDX数据获取层 (data/tdx_fetcher.py)

**实现:**
- `fetch_ohlcv(symbol, period, start_date, end_date)` → DataFrame
- `fetch_fund_flow(symbol, start_date, end_date)` → DataFrame
- 调用TDX MCP connector的 `tdx_kline` 和 `tdx_quotes`
- 数据标准化：统一列名、处理缺失值

**测试:** `tests/test_tdx_fetcher.py`
- test_fetch_ohlcv_returns_dataframe
- test_fetch_ohlcv_has_required_columns
- test_empty_data_handling

---

### Task 3: 缠论核心引擎 (engine/chan_engine.py)

**实现类:**
1. `InclusionProcessor` — 包含关系处理
   - `process(klines)` → 处理后的K线列表
   - 规则: 向上处理(高高取高,低高取低), 向下处理(高低取低,低低取低)

2. `FractalIdentifier` — 分型识别
   - `identify(processed_klines)` → 顶分型/底分型列表
   - 规则: 连续3根K线, 中间最高/最低

3. `StrokeIdentifier` — 笔识别
   - `identify(fractals, processed_klines)` → 笔列表
   - 规则: 顶底分型之间≥5根K线, 不能有包含关系

4. `SegmentIdentifier` — 线段识别
   - `identify(strokes)` → 线段列表
   - 使用特征序列方法

5. `PivotIdentifier` — 中枢识别
   - `identify(segments)` → 中枢列表
   - 规则: 连续3段重叠区间

6. `TradingSignalIdentifier` — 买卖点识别
   - `identify(pivots, segments)` → 买卖点列表
   - 一买: 趋势背驰后的第一类买点
   - 二买: 回踩中枢不破
   - 三买: 离开中枢后回踩不破
   - 一卖/二卖/三卖: 对应做空

7. `ChanEngine` — 主入口
   - `analyze(df)` → dict{signal, confidence, details}

**测试:** `tests/test_chan_engine.py`
- test_inclusion_processor_upward
- test_inclusion_processor_downward
- test_fractal_identification
- test_stroke_min_kline_count
- test_pivot_overlap_detection
- test_buy_point_classification
- test_chan_engine_end_to_end (使用样本数据)

---

### Task 4: K线形态识别 (engine/candlestick_recognizer.py)

**实现类:**
`CandlestickRecognizer`
- 单线形态: 锤子线、上吊线、流星线、倒锤子、十字星、长脚十字星
- 双线形态: 看涨吞没、看跌吞没、孕线、刺透形态、乌云盖顶
- 三线+形态: 三只乌鸦、三白兵、早晨之星、黄昏之星
- `recognize(df)` → dict{signal, confidence, patterns: [...], markers: [...]}

**测试:** `tests/test_candlestick.py`
- test_hammer_detection
- test_engulfing_bullish
- test_doji_detection
- test_morning_star
- test_multiple_patterns_same_candle

---

### Task 5: 资金流分析 (engine/fund_flow_analyzer.py)

**实现类:**
`FundFlowAnalyzer`
- 主力净流入趋势分析
- 资金强度指标 (N日净流入均值)
- 流入流出背离检测
- `analyze(df, fund_flow_df)` → dict{signal, confidence, details}

**测试:** `tests/test_fund_flow.py`

---

### Task 6: 成交量分析 (engine/volume_analyzer.py)

**实现类:**
`VolumeAnalyzer`
- 量价关系: 价升量增/价跌量缩/价升量缩/价跌量增
- 放量/缩量判断 (基于N日均量)
- 地量/天量检测
- 量比分析
- `analyze(df)` → dict{signal, confidence, details}

**测试:** `tests/test_volume.py`

---

### Task 7: 信号融合引擎 (engine/signal_fusion.py)

**实现类:**
`SignalFusion`
- 加权投票: 缠论40% + K线20% + 资金20% + 量20%
- 权重可配置
- 冲突解决规则: 缠论强信号优先
- 信号等级: 强买(>0.6) / 中买(0.3~0.6) / 观望(-0.3~0.3) / 中卖(-0.6~-0.3) / 强卖(<-0.6)
- `fuse(chan_result, candle_result, fund_result, volume_result)` → dict

**测试:** `tests/test_fusion.py`

---

### Task 9: HTML模板

**Files:**
- `templates/report_template.html` — 当前分析报告

**内容:**
- K线图 (ECharts candlestick) + 缠论标注 (笔、线段、中枢、买卖点)
- 成交量柱状图 (红涨绿跌)
- 资金流折线图
- 信号仪表盘

---

### Task 10: SKILL.md 主文件

**功能:**
- 触发词: 缠论分析、技术分析、多维分析、缠论形态等
- 编排流程: 获取数据 → 四维分析 → 信号融合 → 生成HTML
- 参数: symbol, period, start_date, end_date
