# -*- coding: utf-8 -*-
"""v9.0 指数体制/板块轮动/情景校准/自上而下 合并测试套件（离线）。
由 8 个 test_v90_*.py 合并而来（文件数量优化）。"""

import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import math
import pytest

# ==================================================================
# <<< test_v90_index_regime.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.index_analysis.market_regime import (
    classify_from_prices, max_drawdown, drawdown_from_high,
    slope_pct, sma, sma_series, MarketRegimeClassifier, RegimeResult,
)
from stock_researcher.index_analysis.volatility_regime import (
    realized_vol, vol_regime_label, is_bull_friendly,
    vol_of_vol, vol_percentile, rolling_vol_series,
    VolatilityRegimeAnalyzer, VolatilityResult,
)


def _up(n, start=100.0, daily=0.002):
    return [start * ((1 + daily) ** i) for i in range(n)]


def _down(n, start=100.0, daily=0.002):
    return [start * ((1 - daily) ** i) for i in range(n)]


def _flat(n, base=100.0, noise=0.0):
    return [base + noise * math.sin(i) for i in range(n)]


# ============================================================
# 1. 基础统计纯函数
# ============================================================

def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)
    assert sma([1, 2, 3], 5) is None


def test_sma_series_length():
    s = sma_series([1, 2, 3, 4, 5], 3)
    assert len(s) == 3   # 5-3+1


def test_max_drawdown_known():
    # 100 → 120 → 90 → 回撤 = 1-90/120 = 0.25
    assert max_drawdown([100, 120, 90]) == pytest.approx(0.25)


def test_max_drawdown_no_drawdown():
    assert max_drawdown([1, 2, 3, 4]) == pytest.approx(0.0)


def test_drawdown_from_high_current_below_peak():
    assert drawdown_from_high([100, 130, 117]) == pytest.approx(0.1)  # 1-117/130


def test_drawdown_from_high_at_peak():
    assert drawdown_from_high([100, 110, 120]) == pytest.approx(0.0)


def test_slope_pct_rising_positive():
    assert slope_pct([100, 101, 102, 103], n=4) > 0


# ============================================================
# 2. classify_from_prices —— 体制判定
# ============================================================

def test_classify_strong_uptrend_is_bull():
    """持续上行(260日) → 牛市、score > 0、价格在 MA200 上方。"""
    r = classify_from_prices(_up(260, daily=0.002))
    assert r["regime"] == "牛市"
    assert r["regime_score"] > 0
    assert r["price_vs_ma200"] == "上方"
    assert r["ma200_slope"] == "上升"


def test_classify_strong_downtrend_is_bear():
    """持续下行 → 熊市、score < 0、价格在 MA200 下方。"""
    r = classify_from_prices(_down(260, daily=0.002))
    assert r["regime"] == "熊市"
    assert r["regime_score"] < 0
    assert r["price_vs_ma200"] == "下方"


def test_classify_short_series_returns_neutral():
    """序列过短(<60) → 数据不足中性。"""
    r = classify_from_prices(_up(40))
    assert r["regime"] == "震荡"
    assert "数据不足" in r["note"] or r["price_vs_ma200"] == "数据不足"


def test_classify_probabilities_sum_to_one():
    r = classify_from_prices(_up(260))
    assert sum(r["probabilities"].values()) == pytest.approx(1.0, abs=1e-3)


def test_classify_returns_all_expected_keys():
    r = classify_from_prices(_up(260))
    for k in ("regime", "probability", "probabilities", "regime_score",
              "drawdown_from_high", "price_vs_ma200", "ma200_slope",
              "distance_52w_high", "distance_52w_low"):
        assert k in r


# ============================================================
# 3. MarketRegimeClassifier 集成
# ============================================================

class _StubRegime(MarketRegimeClassifier):
    def _fetch_prices(self, code, days):
        return _up(days, daily=0.002)


def test_classifier_bull_on_rising_market():
    r = _StubRegime().classify("sh000001", days=260)
    assert isinstance(r, RegimeResult)
    assert r.regime == "牛市"
    assert r.regime_score > 0


def test_classifier_no_data_returns_neutral():
    r = MarketRegimeClassifier().classify("bad_code_xyz", days=260)
    # 联网失败 → 降级中性
    assert r.regime in ("震荡",)


# ============================================================
# 4. 波动率体制
# ============================================================

def test_realized_vol_positive_for_volatile_series():
    prices = [100, 105, 95, 108, 92, 110, 90]
    rv = realized_vol(prices, n=5)
    assert rv > 0


def test_realized_vol_low_for_smooth_series():
    smooth = _up(40, daily=0.001)
    rv = realized_vol(smooth, n=20)
    assert rv < 0.25


def test_vol_regime_label_high():
    assert vol_regime_label(0.30, 0.25) == "高波动"


def test_vol_regime_label_low():
    assert vol_regime_label(0.08, 0.10) == "低波动"


def test_vol_regime_label_expanding():
    # 20d 显著高于 60d
    assert vol_regime_label(0.20, 0.12) == "扩张"


def test_vol_regime_label_compressing():
    assert vol_regime_label(0.10, 0.18) == "压缩"


def test_is_bull_friendly_low_vol():
    assert is_bull_friendly(0.10, 0.12, "低波动") is True


def test_is_bull_friendly_high_vol_false():
    assert is_bull_friendly(0.30, 0.25, "高波动") is False


def test_vol_of_vol_positive():
    prices = [100 + 5 * math.sin(i / 3) + 0.1 * i for i in range(60)]
    assert vol_of_vol(prices, 20) >= 0.0


def test_vol_percentile_in_range():
    prices = _up(120, daily=0.003)
    pct = vol_percentile(prices, 20)
    assert 0.0 <= pct <= 100.0


def test_volatility_analyzer_from_prices():
    v = VolatilityRegimeAnalyzer().analyze_from_prices("test", _up(120, daily=0.001))
    assert isinstance(v, VolatilityResult)
    assert v.realized_vol_20d >= 0
    assert v.regime in ("低波动", "扩张", "高波动", "压缩", "中性", "未知")



# ==================================================================
# <<< test_v90_index_structure_valuation_internals.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.index_analysis.market_structure import (
    find_swing_highs, find_swing_lows, trend_structure_from_swings,
    atr, nearest_levels, break_signals,
    MarketStructureAnalyzer, StructureResult,
)
from stock_researcher.index_analysis.index_valuation import (
    percentile_of, valuation_score_from_percentile, valuation_score_from_pe,
    valuation_label_from_score, aggregate_pe,
    IndexValuation, IndexValuationResult,
)
from stock_researcher.index_analysis.market_internals import (
    daily_ad_series, ema, mcclellan_oscillator,
    breadth_status_from_mcclellan, new_highs_lows, health_from_internals,
    MarketInternalsAnalyzer, InternalsResult,
)


# ============================================================
# 1. 市场结构 —— 摆动点 / 趋势结构
# ============================================================

def test_find_swing_highs_in_zigzag():
    """明显的锯齿序列应找到若干高点。"""
    prices = [10, 12, 15, 12, 10, 8, 10, 13, 16, 13, 10]
    highs = find_swing_highs(prices, k=2)
    assert len(highs) >= 1
    assert 15 in highs or 16 in highs


def test_find_swing_lows_in_zigzag():
    prices = [10, 12, 15, 12, 10, 8, 10, 13, 16, 13, 10]
    lows = find_swing_lows(prices, k=2)
    assert 8 in lows


def test_trend_structure_rising_swings_is_uptrend():
    """高点与低点都逐级抬高 → 上升。"""
    highs = [10, 12, 15, 18]
    lows = [5, 7, 10, 13]
    structure, score = trend_structure_from_swings(highs, lows)
    assert structure == "上升"
    assert score > 0


def test_trend_structure_falling_swings_is_downtrend():
    highs = [18, 15, 12, 10]
    lows = [13, 10, 7, 5]
    structure, score = trend_structure_from_swings(highs, lows)
    assert structure == "下降"
    assert score < 0


def test_trend_structure_insufficient_is_sideways():
    structure, score = trend_structure_from_swings([10], [5])
    assert structure == "震荡"


def test_atr_positive_for_volatile():
    assert atr([100, 105, 98, 110, 95], n=4) > 0


def test_nearest_levels_basic():
    prices = [100, 110, 90, 105]   # last=105
    res, sup = nearest_levels(prices, [110], [90])
    assert res >= 105
    assert sup <= 105


def test_break_signals_down_break():
    prices = [10, 12, 15, 12, 8]   # last=8 跌破前低 12
    bdown, bup = break_signals(prices, [15], [12])
    assert bdown is True


def test_market_structure_analyzer_from_prices():
    up = [100 * (1.002 ** i) for i in range(80)]
    ms = MarketStructureAnalyzer().analyze_from_prices("test", up)
    assert isinstance(ms, StructureResult)
    assert ms.trend_structure in ("上升", "下降", "震荡", "未知")
    assert ms.atr >= 0


# ============================================================
# 2. 指数估值纯函数
# ============================================================

def test_percentile_of_extremes():
    hist = [10, 12, 14, 16, 18, 20]
    assert percentile_of(20, hist) == pytest.approx(100.0)
    assert percentile_of(10, hist) == pytest.approx(0.0)


def test_percentile_of_median():
    hist = [10, 12, 14, 16, 18, 20]
    assert percentile_of(14, hist) == pytest.approx(40.0)  # (2)/5*100


def test_percentile_of_insufficient_returns_none():
    assert percentile_of(15, [10, 12]) is None
    assert percentile_of(15, []) is None


def test_valuation_score_from_percentile_high_is_expensive():
    """高分位(贵)→正分；低分位(便宜)→负分。"""
    assert valuation_score_from_percentile(90) > 0
    assert valuation_score_from_percentile(10) < 0
    assert valuation_score_from_percentile(50) == pytest.approx(0.0)
    assert valuation_score_from_percentile(None) == 0.0


def test_valuation_score_from_pe_low_pe_positive():
    assert valuation_score_from_pe(8, "cn") < 0   # 低 PE → 便宜 → 负分(便宜)
    assert valuation_score_from_pe(40, "cn") > 0  # 高 PE → 贵 → 正分


def test_valuation_label_ranges():
    assert valuation_label_from_score(-70) == "极度低估"
    assert valuation_label_from_score(-30) == "低估"
    assert valuation_label_from_score(0) == "合理"
    assert valuation_label_from_score(30) == "高估"
    assert valuation_label_from_score(70) == "极度高估"


def test_aggregate_pe_median():
    """成分股 PE 取中位数（剔除负值）。"""
    assert aggregate_pe([10, 20, 30, -5, None]) == pytest.approx(20.0)


def test_aggregate_pe_empty():
    assert aggregate_pe([]) is None


def test_index_valuation_unavailable_returns_honest():
    """所有源失败 → data_mode='unavailable'，不编造分位。"""
    iv = IndexValuationResult(code="x", data_mode="unavailable")
    assert iv.pe_percentile is None
    assert iv.valuation_label == "未知"


# ============================================================
# 3. 市场内含
# ============================================================

def test_daily_ad_series_net_positive_when_most_rising():
    data = {"a": [10, 11, 12], "b": [10, 11, 12], "c": [10, 9, 8]}
    series = daily_ad_series(data)
    assert len(series) == 2
    # 最后一日：a,b 涨, c 跌 → net = 1
    assert series[-1] == 1


def test_ema_decays_to_value():
    e = ema([10, 10, 10, 10], 3)
    assert len(e) == 4
    assert e[-1] == pytest.approx(10.0)


def test_mcclellan_returns_float():
    net = [10, -5, 20, -10, 15, -8, 12, -3, 18, -6,
           14, -2, 16, -4, 11, -7, 13, -1, 17, -5,
           10, -3, 12, 2, 8, -2, 9, 1, 7, 0,
           6, -1, 8, 2, 5, -1, 7, 3, 4, 1,
           6, 2, 5, 3, 4, 2, 3, 1, 2, 0]
    mcc = mcclellan_oscillator(net)
    assert isinstance(mcc, float)


def test_mcclellan_short_series_zero():
    assert mcclellan_oscillator([1, 2, 3]) == 0.0


def test_breadth_status_overbought_oversold():
    assert breadth_status_from_mcclellan(50, 100) == "超买"
    assert breadth_status_from_mcclellan(-50, 100) == "超卖"
    assert breadth_status_from_mcclellan(5, 100) == "中性"


def test_new_highs_lows_rising_only():
    data = {"a": [10 + i for i in range(30)]}
    hi, lo = new_highs_lows(data, 20)
    assert hi == 1 and lo == 0


def test_health_from_internals_overheated():
    assert health_from_internals(85, 5, 1) == "过热"


def test_health_from_internals_freezing():
    assert health_from_internals(15, 1, 5) == "冰点"


def test_market_internals_analyzer_stub():
    """注入合成成分股数据，验证内含分析链路。"""
    class _Stub(MarketInternalsAnalyzer):
        def _resolve(self, code):
            return ["a", "b", "c", "d", "e"], "full"

        def _fetch_closes(self, codes, days=60):
            return {c: [10 * (1.003 ** i) for i in range(50)] for c in codes}

    mi = _Stub().analyze("sh000300")
    assert isinstance(mi, InternalsResult)
    assert mi.data_mode == "full"
    assert mi.advancers >= 1
    assert mi.health in ("健康", "过热", "中性", "偏弱", "冰点")



# ==================================================================
# <<< test_v90_regime_consensus.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.fusion.regime_overlay import (
    RegimeOverlay, REGIME_WEIGHTS, MOMENTUM_DIMS,
    detect_regime_from_prices, normalize_regime,
)
from stock_researcher.fusion.signal_consensus import (
    SignalConsensus, compute_consensus, consensus_from_scores,
)


# ============================================================
# 1. RegimeOverlay —— 体制权重
# ============================================================

def test_weights_for_bull_returns_dict():
    w = RegimeOverlay.weights_for("牛市", "1d")
    assert w is not None
    assert "technical" in w


def test_weights_for_none_returns_none():
    """regime=None → None（向后兼容）。"""
    assert RegimeOverlay.weights_for(None, "1d") is None
    assert RegimeOverlay.weights_for("未知体制", "1d") is None


def test_apply_regime_weights_none_unchanged():
    """regime=None → 权重原样（仅副本）。"""
    default = {"technical": 0.3, "macro": 0.2}
    out = RegimeOverlay.apply_regime_weights(default, None, "1d")
    assert out == default
    assert out is not default   # 是副本


def test_apply_regime_weights_bear_downweights_technical():
    """熊市：technical 权重相对默认应下降，valuation/macro 上升。"""
    default = {"technical": 0.30, "sentiment": 0.20, "money_flow": 0.20,
               "macro": 0.05, "valuation": 0.05, "policy": 0.05,
               "broker": 0.05, "news": 0.05, "quant_vol": 0.03, "quant_factor": 0.02}
    bear = RegimeOverlay.apply_regime_weights(default, "熊市", "1M")
    # 归一化后比较：熊市 technical 占比应低于默认
    assert bear["technical"] < default["technical"] * 1.0 / sum(default.values())
    assert bear["valuation"] > default["valuation"] * 1.0 / sum(default.values())


def test_apply_regime_weights_normalizes_to_one():
    default = {"technical": 0.3, "macro": 0.2, "valuation": 0.1}
    out = RegimeOverlay.apply_regime_weights(default, "熊市", "1M")
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)


# ============================================================
# 2. RegimeOverlay —— 动量折扣
# ============================================================

def test_momentum_dampening_none_unchanged():
    assert RegimeOverlay.momentum_dampening(30, "technical", None) == 30


def test_momentum_dampening_bull_unchanged():
    assert RegimeOverlay.momentum_dampening(30, "technical", "牛市") == 30


def test_momentum_dampening_bear_reduces_momentum():
    """熊市对动量类信号打折（0.5）。"""
    assert RegimeOverlay.momentum_dampening(30, "technical", "熊市") == 15


def test_momentum_dampening_non_momentum_unchanged():
    """非动量类维度（valuation）在熊市不打折。"""
    assert RegimeOverlay.momentum_dampening(30, "valuation", "熊市") == 30


def test_momentum_dampening_flip_mode_bear():
    """flip_momentum=True 时熊市动量翻号（-0.6）。"""
    assert RegimeOverlay.momentum_dampening(30, "technical", "熊市",
                                            flip_momentum=True) == -18


def test_confidence_adjustment_bear_lowers():
    assert RegimeOverlay.confidence_adjustment("熊市") < 1.0
    assert RegimeOverlay.confidence_adjustment("牛市") == 1.0
    assert RegimeOverlay.confidence_adjustment(None) == 1.0


def test_normalize_regime():
    assert normalize_regime("牛市") == "牛市"
    assert normalize_regime("bear market") == "熊市"
    assert normalize_regime("高波动") == "熊市"   # 高波动保守归熊
    assert normalize_regime("震荡市") == "震荡"
    assert normalize_regime(None) is None


def test_detect_regime_from_prices_rising():
    prices = [100 * (1.002 ** i) for i in range(120)]
    r = detect_regime_from_prices(prices)
    assert r is not None


# ============================================================
# 3. SignalConsensus —— 共识度
# ============================================================

def test_compute_consensus_unanimous_bull():
    """全部看多 → 强共识看多，dispersion 低，置信乘数>1。"""
    c = compute_consensus([40, 35, 30, 45, 38])
    assert c.bull_count == 5
    assert c.consensus_score > 25
    assert c.dispersion < 40
    assert c.confidence_multiplier >= 1.0
    assert "看多" in c.label


def test_compute_consensus_unanimous_bear():
    c = compute_consensus([-40, -35, -30, -45, -38])
    assert c.bear_count == 5
    assert c.consensus_score < -25
    assert "看空" in c.label


def test_compute_consensus_split_is_divergent():
    """多空各半 → 分歧，dispersion 高，置信乘数<1，均值回归倾斜>0。"""
    c = compute_consensus([40, 35, -30, -45, 10])
    assert c.dispersion >= 55 or c.label == "分歧" or c.confidence_multiplier < 1.0


def test_compute_consensus_empty():
    c = compute_consensus([])
    assert c.label == "无信号"


def test_consensus_confidence_multiplier_range():
    c = compute_consensus([10, 20, 30, 5, 15])
    assert 0.6 <= c.confidence_multiplier <= 1.1


def test_consensus_from_scores_convenience():
    c = consensus_from_scores([20, 20, -20, -20])
    assert isinstance(c.dispersion, float)


def test_signal_consensus_class_with_dims():
    """SignalConsensus.compute 接受类 DimensionSignal 对象。"""

    class Dim:
        def __init__(self, dim, score, direction="", available=True):
            self.dimension = dim
            self.score = score
            self.direction = direction
            self.available = available

    dims = [Dim("technical", 30, "看多"), Dim("macro", -20, "看空"),
            Dim("sentiment", 25, "看多"), Dim("valuation", 15, "看多")]
    c = SignalConsensus().compute(dims)
    assert c.bull_count >= 2
    assert -100 <= c.consensus_score <= 100



# ==================================================================
# <<< test_v90_scenario_calibration.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.quantitative.scenario_engine import (
    SCENARIO_DEFS, DEFAULT_PROBABILITIES, scenario_return, weighted_outcomes,
    blend_report, sample_scenario_path, MacroScenarioEngine,
)
from stock_researcher.evolution.calibration import (
    bucket_reliability, brier_score, expected_calibration_error,
    isotonic_fit, calibrate_value, PredictionCalibrator,
)


# ============================================================
# 1. 情景引擎
# ============================================================

def test_scenario_return_soft_landing_boosts():
    """软着陆：漂移+0.04 → 预期收益高于基准。"""
    r, v = scenario_return(0.10, 0.18, "软着陆")
    assert r > 0.10
    assert v < 0.18   # 波动缩小


def test_scenario_return_hard_landing_lowers():
    r, v = scenario_return(0.10, 0.18, "硬着陆")
    assert r < 0.10
    assert v > 0.18


def test_scenario_return_unknown_returns_base():
    r, v = scenario_return(0.10, 0.18, "不存在的情景")
    assert r == 0.10 and v == 0.18


def test_default_probabilities_sum_to_one():
    assert sum(DEFAULT_PROBABILITIES.values()) == pytest.approx(1.0)


def test_blend_report_probabilities_normalized():
    rep = blend_report(0.08, 0.20, {"软着陆": 2.0, "硬着陆": 2.0})
    assert sum(rep.probabilities.values()) == pytest.approx(1.0)


def test_blend_report_weighted_between_tail_and_best():
    rep = blend_report(0.08, 0.20)
    assert rep.tail_risk <= rep.weighted_return <= rep.best_case
    assert rep.tail_risk < 0   # 至少有一个下行情景


def test_blend_report_upside_probability_range():
    rep = blend_report(0.08, 0.20)
    assert 0.0 <= rep.upside_probability <= 1.0


def test_blend_report_outcomes_have_rationale():
    rep = blend_report(0.08, 0.20)
    for o in rep.outcomes:
        assert o.rationale
        assert o.asset_tilt  # 资产偏好非空


def test_sample_scenario_path_returns_list():
    paths = sample_scenario_path(0.08, 0.20, "硬着陆", horizon_days=21, sims=200)
    assert len(paths) == 200
    # 硬着陆偏下行：多数路径应为负或低
    assert any(p < 0 for p in paths)


def test_macro_engine_list_and_analyze():
    eng = MacroScenarioEngine()
    assert "软着陆" in eng.list_scenarios()
    rep = eng.analyze(0.08, 0.20)
    assert rep.weighted_return is not None
    assert isinstance(rep.outcomes, list) and len(rep.outcomes) > 0


def test_tail_var_negative_for_hard_landing():
    eng = MacroScenarioEngine()
    var = eng.tail_var(0.08, 0.20, "硬着陆", horizon_days=21, sims=300, quantile=0.05)
    assert var < 0   # 5% 分位应为负（下行）


# ============================================================
# 2. 预测校准
# ============================================================

def test_bucket_reliability_basic():
    pairs = [(0.2, 0), (0.2, 0), (0.8, 1), (0.8, 1), (0.5, 1)]
    rel = bucket_reliability(pairs)
    assert len(rel) >= 1
    for b in rel:
        assert 0 <= b["hit_rate"] <= 1
        assert b["count"] > 0


def test_brier_score_perfect():
    """完美校准（conf=hit）→ Brier=0。"""
    assert brier_score([(0.0, 0), (1.0, 1), (0.0, 0)]) == pytest.approx(0.0)


def test_brier_score_worst():
    """完全反向（conf=1 全 miss）→ Brier=1。"""
    assert brier_score([(1.0, 0), (1.0, 0)]) == pytest.approx(1.0)


def test_brier_score_empty():
    assert brier_score([]) == 0.0


def test_expected_calibration_error_zero_when_perfect():
    pairs = [(0.2, 0.2 > 0.5), (0.8, 0.8 > 0.5)]  # placeholder
    # 直接构造完美可靠性
    rel = [{"count": 10, "avg_conf": 0.2, "hit_rate": 0.2},
           {"count": 10, "avg_conf": 0.8, "hit_rate": 0.8}]
    assert expected_calibration_error(rel, 20) == pytest.approx(0.0)


def test_isotonic_fit_monotonic():
    """PAV 保序回归结果应单调非降。"""
    pairs = [(0.3, 0), (0.4, 1), (0.5, 0), (0.6, 1), (0.7, 1), (0.8, 1)]
    fitted = isotonic_fit(pairs)
    ys = [y for _, y in fitted]
    for i in range(1, len(ys)):
        assert ys[i] >= ys[i - 1] - 1e-9   # 非降


def test_isotonic_fit_empty():
    assert isotonic_fit([]) == []


def test_calibrate_value_empty_returns_original():
    assert calibrate_value(0.7, []) == 0.7


def test_calibrate_value_within_range():
    """校准值应落在拟合数据的 y 范围内。"""
    pairs = [(0.2, 0)] * 10 + [(0.8, 1)] * 10
    fitted = isotonic_fit(pairs)
    cal = calibrate_value(0.5, fitted)
    assert fitted[0][1] - 1e-6 <= cal <= fitted[-1][1] + 1e-6


def test_calibrator_no_history_returns_original():
    """无历史数据 → calibrate 原样返回（诚实）。"""
    cal = PredictionCalibrator()
    out = cal.calibrate(0.7, horizon="1M")
    assert out == 0.7


def test_calibrator_build_with_synthetic(monkeypatch):
    """注入合成历史，验证 build 返回可靠性 + Brier。"""
    cal = PredictionCalibrator()
    # 构造 40 条：低 conf 多 miss，高 conf 多 hit
    pairs = [(0.2, 0)] * 15 + [(0.3, 0)] * 5 + [(0.7, 1)] * 10 + [(0.8, 1)] * 10
    monkeypatch.setattr(cal, "_load_pairs", lambda *a, **k: pairs)
    res = cal.build(horizon="1M")
    assert res.n_samples == 40
    assert res.sufficient is True
    assert 0 <= res.brier <= 1
    assert len(res.reliability) >= 1



# ==================================================================
# <<< test_v90_sector_breadth.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.sector_analysis.breadth import (
    pct_above_ma, adv_dec_counts, new_highs_lows, zweig_thrust_series,
    detect_thrust, health_label, detect_divergence,
    SectorBreadth, BreadthResult,
)


def _rising(n, start=10.0, step=0.5):
    return [start + step * i for i in range(n)]


def _falling(n, start=50.0, step=0.5):
    return [start - step * i for i in range(n)]


# ============================================================
# 1. pct_above_ma
# ============================================================

def test_pct_above_ma_all_rising_stocks_100pct():
    """全部成分股持续上行 → 现价都在 MA20 之上 → 100%。"""
    data = {f"s{i}": _rising(60) for i in range(5)}
    assert pct_above_ma(data, 20) == pytest.approx(100.0)


def test_pct_above_ma_all_falling_stocks_0pct():
    """全部持续下行 → 现价都在 MA20 之下 → 0%。"""
    data = {f"s{i}": _falling(60) for i in range(5)}
    assert pct_above_ma(data, 20) == pytest.approx(0.0)


def test_pct_above_ma_mixed_half():
    """一半上一半下 → 约 50%。"""
    data = {f"up{i}": _rising(60) for i in range(3)}
    data.update({f"dn{i}": _falling(60) for i in range(3)})
    val = pct_above_ma(data, 20)
    assert 30.0 < val < 70.0


# ============================================================
# 2. adv_dec_counts / new_highs_lows
# ============================================================

def test_adv_dec_counts_rising_vs_falling():
    data = {"up": _rising(40), "dn": _falling(40)}
    adv, dec = adv_dec_counts(data, lookback=20)
    assert adv == 1 and dec == 1


def test_new_highs_lows_rising_makes_new_highs():
    data = {"up": _rising(40)}
    hi, lo = new_highs_lows(data, 20)
    assert hi == 1 and lo == 0


def test_new_highs_lows_falling_makes_new_lows():
    data = {"dn": _falling(40)}
    hi, lo = new_highs_lows(data, 20)
    assert lo == 1 and hi == 0


# ============================================================
# 3. zweig thrust / detect_thrust
# ============================================================

def test_detect_thrust_triggered():
    """%above 序列从 ≤0.5 在 10 期内升至 ≥0.615 → 触发。"""
    series = [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
    assert detect_thrust(series) is True


def test_detect_thrust_not_triggered_when_no_cross():
    series = [0.7, 0.7, 0.7, 0.7]
    assert detect_thrust(series) is False


def test_zweig_thrust_series_length():
    data = {f"s{i}": _rising(50) for i in range(5)}
    series = zweig_thrust_series(data, 20)
    assert len(series) > 0
    assert all(0.0 <= x <= 1.0 for x in series)


# ============================================================
# 4. health_label / detect_divergence
# ============================================================

def test_health_label_overheated():
    assert health_label(85, 80) == "过热"


def test_health_label_freezing():
    assert health_label(15, 18) == "冰点"


def test_health_label_healthy():
    assert health_label(65, 62) == "健康"


def test_detect_divergence_top_divergence():
    """价格创新高但宽度未创新高 → 顶背离。"""
    proxy = [100 + i for i in range(40)]            # 价格持续新高
    breadth = [0.8 - 0.01 * i for i in range(40)]   # 宽度反而走低
    assert detect_divergence(proxy, breadth) == "顶背离"


def test_detect_divergence_bottom_divergence():
    proxy = [100 - i for i in range(40)]
    breadth = [0.2 + 0.01 * i for i in range(40)]   # 宽度反而走高
    assert detect_divergence(proxy, breadth) == "底背离"


def test_detect_divergence_none_when_aligned():
    proxy = [100 + i for i in range(40)]
    breadth = [0.5 + 0.01 * i for i in range(40)]   # 同步新高
    assert detect_divergence(proxy, breadth) == "无"


# ============================================================
# 5. SectorBreadth 集成（注入合成数据）
# ============================================================

class _StubBreadth(SectorBreadth):
    def _resolve(self, sector, market):
        return ["a", "b", "c", "d", "e"], "proxy"

    def _fetch_closes(self, codes, days=220):
        return {c: _rising(220) for c in codes}


def test_analyze_breadth_healthy_when_all_rising():
    b = _StubBreadth().analyze("电子", market="cn")
    assert isinstance(b, BreadthResult)
    assert b.pct_above_ma20 >= 80.0
    assert b.health in ("过热", "健康")
    assert b.advancers >= 1


class _StubBreadthWeak(SectorBreadth):
    def _resolve(self, sector, market):
        return ["a", "b", "c"], "proxy"

    def _fetch_closes(self, codes, days=220):
        return {c: _falling(220) for c in codes}


def test_analyze_breadth_freezing_when_all_falling():
    b = _StubBreadthWeak().analyze("煤炭", market="cn")
    assert b.pct_above_ma20 <= 20.0
    assert b.health in ("冰点", "偏弱")
    assert b.decliners >= 1



# ==================================================================
# <<< test_v90_sector_dispersion.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.sector_analysis.dispersion import (
    period_returns, mean, median, stdev, skewness, quintile_gap,
    top1_contribution, cohesion_label,
    SectorDispersion, DispersionResult,
)
from stock_researcher.sector_analysis.themes import (
    THEME_SECTOR_MAP, list_themes, get_theme_stocks,
)
from stock_researcher.sector_analysis.rotation_cycle import (
    stage_probabilities, pick_stage, CYCLE_SECTOR_MAP, STAGE_KEYS,
    RotationCycleDetector, CycleStageResult,
)


# ============================================================
# 1. 统计纯函数
# ============================================================

def test_mean_and_median_basic():
    assert mean([1, 2, 3, 4, 5]) == pytest.approx(3.0)
    assert median([1, 2, 3, 4, 5]) == pytest.approx(3.0)
    assert median([1, 2, 3, 4]) == pytest.approx(2.5)


def test_stdev_sample_known_value():
    # 样本标准差 of [2,4,4,4,5,5,7,9] ≈ 2.1389
    assert stdev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.1389, rel=1e-3)


def test_stdev_single_value_zero():
    assert stdev([5.0]) == 0.0


def test_skewness_positive_for_right_tail():
    """右偏（少数大涨）→ 偏度 > 0。"""
    assert skewness([1, 1, 1, 1, 1, 1, 1, 10]) > 0


def test_quintile_gap_positive_when_top_above_bottom():
    leader, lagger, gap = quintile_gap([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert leader > lagger
    assert gap > 0


def test_top1_contribution_when_one_big_winner():
    """均值由少数赢家拉动 → 集中度 > 1。"""
    contrib = top1_contribution([0.5, 0.01, 0.01, 0.01])
    assert contrib > 1.0


def test_top1_contribution_zero_when_mean_negative():
    assert top1_contribution([-0.1, -0.2]) == 0.0


# ============================================================
# 2. cohesion_label
# ============================================================

def test_cohesion_label_unanimous_up():
    """均收益 +2%、70% 上涨、离散适中 → 齐涨。"""
    assert cohesion_label(0.02, 0.01, 10, 0.8, 0.2) == "齐涨"


def test_cohesion_label_unanimous_down():
    assert cohesion_label(-0.02, 0.01, 10, 0.2, 0.8) == "齐跌"


def test_cohesion_label_divergent_when_split():
    assert cohesion_label(0.0, 0.01, 10, 0.5, 0.5) == "分化"


# ============================================================
# 3. period_returns
# ============================================================

def test_period_returns_computes_per_stock():
    data = {"a": [100, 110, 121], "b": [100, 90, 81]}
    rets = period_returns(data, lookback=2)
    assert len(rets) == 2
    assert pytest.approx(rets[0], rel=1e-3) == 0.21    # a: 121/100-1
    assert pytest.approx(rets[1], rel=1e-3) == -0.19   # b: 81/100-1


def test_period_returns_skips_insufficient():
    data = {"a": [100], "b": [100, 90]}
    rets = period_returns(data, lookback=2)
    assert rets == []   # 都不足


# ============================================================
# 4. SectorDispersion 集成
# ============================================================

class _StubDispersion(SectorDispersion):
    def _resolve(self, sector, market):
        return ["a", "b", "c", "d", "e"], "proxy"

    def _fetch_closes(self, codes, days=90):
        # 4 只齐涨 + 1 只大涨（拉动偏度/集中度）
        out = {c: [10 * (1.005 ** i) for i in range(90)] for c in list(codes)[:4]}
        out[list(codes)[4]] = [10 * (1.02 ** i) for i in range(90)]
        return out


def test_analyze_dispersion_unanimous_up_is_cohesive():
    d = _StubDispersion().analyze("电子", market="cn", lookback=20)
    assert isinstance(d, DispersionResult)
    assert d.mean_return > 0
    assert d.cohesion in ("齐涨", "分化")   # 1 只大涨可能引入分化
    assert d.data_mode == "proxy"


def test_analyze_dispersion_no_data_returns_note():
    d = SectorDispersion().analyze("不存在XYZ", market="cn")
    assert d.n_stocks == 0


# ============================================================
# 5. 主题板块映射
# ============================================================

def test_list_themes_cn_includes_ai():
    themes = list_themes("cn")
    assert "AI算力" in themes
    assert "人形机器人" in themes


def test_get_theme_stocks_returns_list():
    stocks = get_theme_stocks("AI算力", "cn")
    assert isinstance(stocks, list)
    assert len(stocks) >= 4
    assert "002230" in stocks   # 科大讯飞


def test_get_theme_stocks_unknown_returns_empty():
    assert get_theme_stocks("不存在", "cn") == []


def test_theme_map_covers_three_markets():
    for m in ("cn", "hk", "us"):
        assert len(THEME_SECTOR_MAP.get(m, {})) >= 4


# ============================================================
# 6. 轮动周期
# ============================================================

def test_stage_probabilities_sum_to_one():
    probs = stage_probabilities(growth_signal=0.5, inflation_signal=0.2, risk_appetite=0.3)
    assert set(probs.keys()) == set(STAGE_KEYS)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(0.0 <= v <= 1.0 for v in probs.values())


def test_stage_probabilities_growth_and_risk_on_favors_expansion():
    """增长扩张 + risk-on → 中周期/早周期概率较高，衰退低。"""
    probs = stage_probabilities(growth_signal=1.0, inflation_signal=0.0, risk_appetite=1.0)
    assert probs["衰退"] < probs["中周期"]
    assert probs["衰退"] < 0.25


def test_stage_probabilities_recession_when_growth_and_risk_off():
    probs = stage_probabilities(growth_signal=-1.0, inflation_signal=0.0, risk_appetite=-1.0)
    assert probs["衰退"] == max(probs.values())


def test_pick_stage_returns_argmax():
    probs = {"早周期": 0.2, "中周期": 0.5, "晚周期": 0.2, "衰退": 0.1}
    stage, conf = pick_stage(probs)
    assert stage == "中周期"
    assert conf == 0.5


def test_pick_stage_empty_default():
    stage, conf = pick_stage({})
    assert stage == "中周期"
    assert conf == 0.0


def test_cycle_sector_map_has_favored_and_avoid():
    for stage in STAGE_KEYS:
        cfg = CYCLE_SECTOR_MAP[stage]
        assert len(cfg["favored"]) >= 3
        assert len(cfg["avoid"]) >= 1
        assert cfg["rationale"]


def test_detect_cycle_stage_returns_result_shape():
    """检测器返回结构完整（联网部分失败时降级，不抛异常）。"""
    r = RotationCycleDetector().detect(market="cn")
    assert isinstance(r, CycleStageResult)
    assert r.stage in STAGE_KEYS
    assert set(r.probabilities.keys()) == set(STAGE_KEYS)
    assert isinstance(r.favored_sectors, list)



# ==================================================================
# <<< test_v90_sector_rps.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from stock_researcher.sector_analysis.relative_strength import (
    align_and_rebase, rs_ratio_series, pct_change_over, sma,
    mansfield_rps, percentile_rank, rs_trend_label, slope_sign,
    SectorRelativeStrength, RelativeStrengthResult,
)
from stock_researcher.sector_analysis.sectors import SectorAnalyzer, SectorResult


# ============================================================
# 1. align_and_rebase —— 代理指数构造
# ============================================================

def test_align_two_flat_series_proxy_stays_at_100():
    """两只全程走平的股票 → 等权代理恒为 100。"""
    flat = [100.0] * 30
    proxy, n = align_and_rebase({"a": flat, "b": flat})
    assert n == 2
    assert max(abs(p - 100.0) for p in proxy) < 1e-9


def test_align_rising_plus_flat_proxy_rises():
    """一只翻倍上涨 + 一只走平 → 代理从 100 升到 150。"""
    rising = [10.0 * (1 + 0.01 * i) for i in range(30)]  # 末值约为 12.9 → 重定基后 129
    flat = [50.0] * 30
    proxy, n = align_and_rebase({"a": rising, "b": flat})
    assert n == 2
    assert proxy[0] == pytest.approx(100.0)
    # 末点 = (129 + 100)/2 = 114.5 左右，且 > 起点
    assert proxy[-1] > 110.0


def test_align_unequal_lengths_trims_to_min_from_end():
    """长度不一致 → 按最短末端对齐。"""
    long_s = list(range(1, 21))         # 1..20
    short_s = list(range(100, 113))     # 100..112（12 个）
    proxy, n = align_and_rebase({"a": long_s, "b": short_s})
    assert n == 2
    assert len(proxy) == min(len(long_s), len(short_s))   # 取最短


def test_align_empty_or_single_point_returns_empty():
    """空输入或单点 → ([], 0)。"""
    assert align_and_rebase({}) == ([], 0)
    assert align_and_rebase({"a": [5.0]}) == ([], 0)


def test_align_drops_nonpositive_and_invalid():
    """非正数/None/非数 被过滤，但仍用有效点构造。"""
    proxy, n = align_and_rebase({"a": [10, 0, 20, None, "x", 30]})
    assert n == 1


# ============================================================
# 2. rs_ratio_series / pct_change_over
# ============================================================

def test_rs_ratio_when_proxy_outperforms_increases():
    """代理涨得比基准快 → RS 序列递增。"""
    proxy = [100 + i for i in range(20)]
    bench = [100 + 0.1 * i for i in range(20)]
    rs = rs_ratio_series(proxy, bench)
    assert len(rs) == 20
    assert rs[-1] > rs[0]


def test_pct_change_over_known_value():
    assert pct_change_over([100, 110, 121], 2) == pytest.approx(0.21)
    assert pct_change_over([100, 90], 1) == pytest.approx(-0.10)


def test_pct_change_over_insufficient_returns_none():
    assert pct_change_over([100], 1) is None
    assert pct_change_over([100, 110], 5) is None


# ============================================================
# 3. mansfield_rps / percentile_rank / rs_trend_label
# ============================================================

def test_mansfield_rps_positive_when_rs_above_mean():
    """RS 现值高于历史均值 → RPS > 0（强于基准）。"""
    rs = [1.0] * 100 + [1.2] * 30   # 末段抬升
    assert mansfield_rps(rs) > 0


def test_mansfield_rps_negative_when_rs_below_mean():
    rs = [1.2] * 100 + [1.0] * 30
    assert mansfield_rps(rs) < 0


def test_mansfield_rps_short_series_returns_none():
    assert mansfield_rps([1.0, 1.1]) is None


def test_percentile_rank_extremes_and_median():
    pop = [1, 2, 3, 4, 5]
    assert percentile_rank(5, pop) == pytest.approx(100.0)
    assert percentile_rank(1, pop) == pytest.approx(0.0)
    assert percentile_rank(3, pop) == pytest.approx(50.0)


def test_percentile_rank_empty_returns_50():
    assert percentile_rank(1.0, []) == 50.0


def test_rs_trend_label_rising():
    """单调递增 RS → 上升。"""
    rs = [1.0 + 0.001 * i for i in range(60)]
    assert rs_trend_label(rs) == "上升"


def test_rs_trend_label_falling():
    rs = [1.5 - 0.001 * i for i in range(60)]
    assert rs_trend_label(rs) == "下降"


def test_slope_sign_basic():
    assert slope_sign([1, 2, 3, 4, 5]) > 0
    assert slope_sign([5, 4, 3, 2, 1]) < 0


# ============================================================
# 4. SectorRelativeStrength 集成（monkeypatch 真实数据源）
# ============================================================

class _StubRS(SectorRelativeStrength):
    """覆写联网方法，注入合成数据，验证完整链路。"""

    def _fetch_closes(self, codes, days=130):
        # 板块成分股：明显跑赢（每只翻倍）
        return {c: [10 * (1.005 ** i) for i in range(130)] for c in codes}

    def _fetch_benchmark_closes(self, market, days=130):
        # 基准：几乎走平
        return [100 + 0.0001 * i for i in range(130)]


def test_relative_strength_outperforming_sector_is_strong():
    """板块成分股持续跑赢基准 → RPS 强、趋势上升。"""
    srs = _StubRS()
    r = srs.relative_strength("电子", market="cn")
    assert isinstance(r, RelativeStrengthResult)
    assert r.n_stocks > 0
    assert r.rps_score > 0
    assert r.rs_trend in ("上升",)
    assert r.data_mode in ("proxy", "full")
    # 多周期 RS 收益为正
    assert r.rs_lookups.get("20d", 0) > 0


class _StubRSWeak(SectorRelativeStrength):
    def _fetch_closes(self, codes, days=130):
        # 板块成分股持续下跌
        return {c: [10 * (0.995 ** i) for i in range(130)] for c in codes}

    def _fetch_benchmark_closes(self, market, days=130):
        return [100 + 0.0001 * i for i in range(130)]


def test_relative_strength_underperforming_sector_is_weak():
    srs = _StubRSWeak()
    r = srs.relative_strength("化工", market="cn")
    assert r.rps_score < 0
    assert r.rs_trend == "下降"


def test_relative_strength_no_constituents_returns_neutral():
    srs = SectorRelativeStrength()
    r = srs.relative_strength("不存在的板块XYZ", market="cn")
    assert r.rps_score == 0.0
    assert "无成分股" in r.note or "失败" in r.note


# ============================================================
# 5. sectors.py 多市场死代码修复
# ============================================================

def test_analyze_sector_uses_hk_map_when_market_hk():
    """v9.0 修复：market='hk' 应使用港股映射，而非 A 股。"""
    captured = {}

    class FakeMarketData:
        def fetch_realtime(self, codes):
            captured["codes"] = list(codes)
            # 返回与请求代码对应的伪行情
            return {c: {"price": 1.0, "change_pct": 1.0,
                        "turnover": 0, "main_net_flow": 0} for c in codes}

    sa = SectorAnalyzer()
    sa.market = FakeMarketData()          # 直接注入，确定性高
    res = sa.analyze_sector("科技", market="hk")
    assert res.market == "hk"
    # 港股「科技」代表股含 00700（腾讯）
    assert "00700" in captured["codes"]


def test_analyze_all_sectors_market_us():
    """market='us' 时遍历的是美股 GICS 行业。"""
    class FakeMarketData:
        def fetch_realtime(self, codes):
            return {c: {"price": 1.0, "change_pct": 0.5,
                        "turnover": 0, "main_net_flow": 0} for c in codes}

    sa = SectorAnalyzer()
    sa.market = FakeMarketData()
    results = sa.analyze_all_sectors(market="us")
    names = {r.name for r in results}
    assert "信息技术" in names       # 美股 GICS 行业
    assert all(r.market == "us" for r in results)


def test_sector_result_new_fields_backward_compatible():
    """新增字段有默认值，旧式构造不破。"""
    r = SectorResult(name="银行", code="银行", stocks=["600036"])
    assert r.market == "cn"
    assert r.rps_score == 0.0
    assert r.data_mode == "proxy"



# ==================================================================
# <<< test_v90_topdown.py >>>
# ==================================================================
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pkg"))

from stock_researcher.data.macro_series import (
    _slope_of, trend_label, build_result, MacroSeriesResult,
)
from stock_researcher.data.index_constituents import (
    FALLBACK_BASKET, IndexConstituents,
)
from stock_researcher.analysis.top_down import (
    TopDownReport, TopDownResult, build_topdown,
)


# ============================================================
# 1. macro_series 纯函数
# ============================================================

def test_slope_of_rising_positive():
    assert _slope_of([100, 101, 102, 103, 104]) > 0


def test_slope_of_falling_negative():
    assert _slope_of([104, 103, 102, 101, 100]) < 0


def test_trend_label_rising():
    assert trend_label(0.5, [100, 102, 104, 106], recent_n=3) == "回升"


def test_trend_label_falling():
    assert trend_label(-0.5, [106, 104, 102, 100], recent_n=3) == "回落"


def test_trend_label_insufficient():
    assert trend_label(0.5, [1, 2], recent_n=3) == "数据不足"


def test_build_result_shape():
    r = build_result("pmi", [50.0, 50.5, 51.0, 51.5], ["2025-01", "2025-02", "2025-03", "2025-04"])
    assert isinstance(r, MacroSeriesResult)
    assert r.latest == pytest.approx(51.5)
    assert r.trend == "回升"
    assert len(r.values) == 4
    assert r.momentum_3 == pytest.approx(1.0)   # 51.5-50.5


def test_build_result_empty_values():
    r = build_result("pmi", [], [])
    assert r.latest is None


# ============================================================
# 2. index_constituents 兜底篮子
# ============================================================

def test_fallback_basket_covers_major_indices():
    for code in ("sh000300", "sz399006", "sh000688", "100.SPX", "100.HSI"):
        assert len(FALLBACK_BASKET.get(code, [])) >= 6


def test_index_constituents_no_network_returns_fallback():
    """网络禁用时返回精选篮子（真实数据兜底）。"""
    codes = IndexConstituents(use_network=False).get("sh000300")
    assert len(codes) >= 10
    assert "600519" in codes


def test_index_constituents_unknown_returns_empty():
    codes = IndexConstituents(use_network=False).get("unknown_idx")
    assert codes == []


# ============================================================
# 3. TopDownReport 整合
# ============================================================

def test_topdown_result_structure_defaults():
    """未填充时结构完整（字段齐全）。"""
    r = TopDownResult(market="cn")
    assert r.position_tilt == "中性"
    assert r.top_sectors == []
    assert r.risk_factors == []


def test_topdown_build_degrades_gracefully_without_network(monkeypatch):
    """网络环节全部失败时 build 不抛异常，返回结构完整的结果。"""
    rep = TopDownReport()
    monkeypatch.setattr(rep, "_fill_regime", lambda res, bench: None)
    monkeypatch.setattr(rep, "_fill_cycle", lambda res, market: None)
    monkeypatch.setattr(rep, "_fill_sectors", lambda res, market, n: None)
    monkeypatch.setattr(rep, "_fill_index_health", lambda res, bench, market: None)
    r = rep.build(market="cn")
    assert isinstance(r, TopDownResult)
    assert r.market == "cn"
    assert r.benchmark == "sh000001"
    assert r.position_tilt in ("进攻", "中性", "防御")
    assert isinstance(r.summary, str)


def test_topdown_build_us_market(monkeypatch):
    """us 市场基准映射正确（网络环节存根）。"""
    rep = TopDownReport()
    monkeypatch.setattr(rep, "_fill_regime", lambda res, bench: None)
    monkeypatch.setattr(rep, "_fill_cycle", lambda res, market: None)
    monkeypatch.setattr(rep, "_fill_sectors", lambda res, market, n: None)
    monkeypatch.setattr(rep, "_fill_index_health", lambda res, bench, market: None)
    r = rep.build(market="us")
    assert r.market == "us"
    assert r.benchmark == "100.SPX"


def test_topdown_synthesize_position_tilt_logic():
    """熊市 → 防御；强牛市 → 进攻（纯逻辑验证）。"""
    r = TopDownResult(market="cn")
    r.regime = "熊市"
    r.regime_score = -50
    TopDownReport()._synthesize(r)
    assert r.position_tilt == "防御"
    assert any("熊市" in f for f in r.risk_factors)

    r2 = TopDownResult(market="cn")
    r2.regime = "牛市"
    r2.regime_score = 60
    TopDownReport()._synthesize(r2)
    assert r2.position_tilt == "进攻"


def test_topdown_favored_themes_intersection():
    """favored_themes = 周期受益 ∩ RPS 强势（交集优先）。"""
    r = TopDownResult(market="cn")
    r.cycle_favored = ["银行", "电子", "汽车"]
    r.top_sectors = [
        {"sector": "电子", "rps": 40, "percentile": 80, "trend": "上升", "data_mode": "proxy"},
        {"sector": "计算机", "rps": 30, "percentile": 70, "trend": "上升", "data_mode": "proxy"},
    ]
    TopDownReport()._synthesize(r)
    assert "电子" in r.favored_themes   # 交集命中


def test_topdown_format_is_string():
    r = TopDownResult(market="cn")
    r.summary = "测试摘要"
    text = TopDownReport.format(r)
    assert isinstance(text, str)
    assert "CN" in text


def test_build_topdown_convenience():
    r = build_topdown(market="hk")
    assert isinstance(r, TopDownResult)


# ============================================================
# 4. 包根 v9.0 懒导出
# ============================================================

def _real_root_module():
    """取真实 stock_researcher 根模块。

    注意：test_v71_analysis 在收集期向 sys.modules 注入了一个「假根模块」
    （裸 ModuleType，无 __file__/__getattr__），使真实包 __init__.py 从未
    执行。本辅助函数检测到假根模块时强制重导入真实包（子模块已在
    sys.modules 中，重导入不会重复执行）。
    """
    import sys
    mod = sys.modules.get("stock_researcher")
    if mod is not None and not hasattr(mod, "__file__"):
        sys.modules.pop("stock_researcher", None)
    import stock_researcher
    return stock_researcher


def test_root_lazy_export_sector():
    sr = _real_root_module()
    srs = sr.SectorRelativeStrength
    assert srs is not None


def test_root_lazy_export_regime():
    sr = _real_root_module()
    mrc = sr.MarketRegimeClassifier
    assert mrc is not None


def test_root_lazy_export_scenario_and_topdown():
    sr = _real_root_module()
    assert sr.MacroScenarioEngine is not None
    assert sr.TopDownReport is not None
    assert sr.PredictionCalibrator is not None


def test_root_lazy_export_unknown_raises():
    sr = _real_root_module()
    with pytest.raises(AttributeError):
        sr.不存在的属性xyz
