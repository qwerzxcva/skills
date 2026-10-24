# stock-selecter 选股引擎（实现层）

来源：qwerzxcva/skills → stock-selecter v3.2。判定条件提取自 `strategies/*.py`，全局默认取自 `config.json`（本次会话实际拉取源码）。

## 一、定位

- **本技能 = 实现层**：跑筛选、出候选清单。
- `stock-selection-engine` = 决策层：给置信度、失效条件、包装输出。
- 流程：先跑本引擎出候选 → 再按决策层规范输出。

## 二、12 个策略的判定逻辑（源码提取）

| 策略 | 剔除/入选条件（`params[key]` 为阈值参数名） |
|---|---|
| roe | `roe < roe_threshold` 剔除；`include_roa` 为真时 `roa < roa_threshold` 也剔除；ROE 序列需 ≥3 期 |
| dividend | `dv_ratio < min_dv_ratio` 剔除；`pe_ttm > max_pe` 剔除；`roe < min_roe` 剔除 |
| valuation | `pe ≤ 0` 或 `pe > max_pe`；`pb ≤ 0` 或 `pb > max_pb`；`roe < min_roe`；内置 `DEFAULT_PE_BENCHMARK=22` 与 `INDUSTRY_PE_BENCHMARK` 行业分档 |
| growth | 财务记录 <2 期剔除；`roe < min_roe`；`gross_margin < min_gross_margin`；`revenue_gr < min_revenue_growth` |
| cashflow_quality | 利润表期数 < `min_match_quarters`；`roe < min_roe`；`match_count < min_match_quarters`；要求 `net_asset > 0` |
| macd | 日线 <80 根剔除；`trend_slope ≤ 0` 剔除；`trend_r2 < trend_r2_min` 剔除；再判 MACD 柱与 K 线斜率 |
| trend | 日线 <30 根剔除；`avg_vol ≤ 0` 剔除；用 `adx_min`、`trend_r`、`rsi_oversold` 判趋势强度与超卖 |
| bollinger | 日线 < `bb_window + 5` 剔除；`|price_change| > price_change_max` 剔除（防异动）；再判下轨 |
| volume_surge | 日线 <30 根剔除；`avg_vol ≤ 0` 剔除；用 `volume_surge_ratio` 判放量倍数 |
| pattern | 日线 <60 根剔除；核心是 **ma5 上穿 ma20（金叉）**；`min_pattern_score` 过滤形态分 |
| shareholder_concentration | 股东户数期数 < `min_consecutive_quarters` 剔除；`roe < min_roe`；`latest_holders ≤ 0` 剔除 |
| low_position | 日线 <60 根剔除；**`pct_rank > low_position_pct` 剔除**（只留历史低位分位以下） |

## 三、全局默认值（config.json 实值）

```
strategy=roe  mode=and  top_n=0  save=true  report=false
exclude_st=true  workers=1
```

**注意：`workers` 默认是 1，不是 8。** SKILL.md 里的 `--workers 8` 只是示例参数，不是默认并发。

## 四、策略参数名清单（CLI 直接用）

`roe_threshold` `roa_threshold` `include_roa` `min_roe` `min_dv_ratio` `max_pe` `max_pb` `max_peg` `min_gross_margin` `min_revenue_growth` `min_profit_growth` `min_consecutive_years` `min_match_quarters` `min_consecutive_quarters` `k_slope_max` `k_r2_min` `trend_r2_min` `bb_window` `price_change_max` `low_position_pct` `min_data_points` `min_pattern_score` `volume_surge_ratio` `rsi_oversold` `adx_min` `trend_r`

## 五、运行

```
python main.py --strategy low_position --mode and --top 30 --report
python main.py --strategy "roe,dividend" --mode and
python main.py --strategy all --mode score --report
```

- 组合：`and` 交集（最严）/ `or` 并集 / `score` 综合评分（配 `--strategy all`）
- 依赖：tushare≥1.4.0、requests、pandas、numpy、scipy
- **`config.json` 的 token 是占位符 `YOUR_TUSHARE_TOKEN_HERE`，必须换成真实 token**
- 核心函数：`_load_config / _parse_strategies / _extract_strategy_params / _run_single_strategy / _combine_and / _combine_or / _combine_score / _save_results / execute`

## 六、纪律

- 只筛股票 + ETF；转债/期权/期货/融资融券不进候选。
- `low_position` 是低位池主力：出「今天买明天涨、尚未涨停」的票，不用涨停股充数。
- 无票说"今日无票"，不放宽阈值凑数。
- 阈值改动必须记录（改前/改后/原因）。

## 七、验证状态（如实标注）

- **已核对**：12 个策略的判定条件骨架、参数名清单、全局默认值、CLI 参数、依赖清单、token 占位符（均来自本次实际拉取的源码）
- **未提取到**：各策略阈值的**显式默认数值**（`params.get(k, default)` 与 `self.params` 均无，数值应在运行时由 CLI/调用方传入）；引用具体数字前必须先实跑一次打印 params 确认
- **未运行**：无 tushare token、依赖未安装，未实际执行过筛选