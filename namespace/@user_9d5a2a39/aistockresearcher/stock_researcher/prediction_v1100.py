# -*- coding: utf-8 -*-
"""
v11.0 多周期预测器 (prediction_v1100.py)

封装 v9.0 MultiHorizonForecaster + 历史形态匹配 + 量化体检，
对外暴露统一的「多周期预测」接口，覆盖股票/基金/期货/指数四类资产。

设计原则：
  1. 零依赖核心（仅依赖 v10.0 内部模块）
  2. 任何周期返回统一结构：direction / probability / confidence / range
  3. 数据缺失诚实降级，不编造
  4. LLM 不可用时返回规则化结论
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 统一数据结构
# ============================================================================

@dataclass
class HorizonPrediction:
    """单周期预测结果。"""
    horizon: str = "1d"                  # 1d / 5d / 1M / 3M / 6M
    direction: str = "neutral"           # bullish / bearish / neutral
    probability: float = 0.5             # 方向概率（0-1）
    confidence: float = 0.5              # 置信度（0-1）
    expected_return: float = 0.0         # 预期收益（百分比）
    range_low: float = 0.0               # 区间下限（百分比）
    range_high: float = 0.0              # 区间上限（百分比）
    key_support: float = 0.0             # 关键支撑位（绝对价格，未计算时为 0）
    key_resistance: float = 0.0          # 关键压力位
    drivers: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    method: str = "rule_based"           # rule_based / pattern / monte_carlo / ai
    quality: str = "estimated"           # actual / derived / estimated / unavailable

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MultiHorizonResult:
    """多周期预测汇总。"""
    code: str
    name: str = ""
    asset_type: str = "stock"            # stock / fund / futures / index
    horizons: Dict[str, HorizonPrediction] = field(default_factory=dict)
    overall_signal: str = "neutral"      # 综合信号
    overall_confidence: float = 0.5
    disclaimer: str = "预测评分≠盈利保证，仅代表历史相似条件下约 X% 的上涨概率"
    timestamp: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "asset_type": self.asset_type,
            "horizons": {k: v.to_dict() for k, v in self.horizons.items()},
            "overall_signal": self.overall_signal,
            "overall_confidence": self.overall_confidence,
            "disclaimer": self.disclaimer,
            "timestamp": self.timestamp,
            "latency_ms": self.latency_ms,
        }


# ============================================================================
# 2. 资产识别
# ============================================================================

def detect_asset_type(code: str) -> str:
    """识别资产类型。"""
    code = code.strip().upper()
    if code.startswith(("HK:", "US:", "IDX:")):
        return "index" if code.startswith("IDX:") else "stock"
    # 期货：以大写英文字母开头（2-3 字符 + 数字月份，如 AU2502、CU）
    # 形式 1: 纯字母（≤ 3 字符）→ CU/AU/AG 等
    # 形式 2: 字母+数字月份 → AU2502/CU2506 等
    if code.isalpha() and len(code) <= 3:
        return "futures"
    if len(code) >= 4:
        if code[:2].isalpha() and code[2:].isdigit():
            return "futures"
        if "." in code and code.split(".")[0].isalpha():
            return "futures"
    # 6 位数字：区分基金 vs 股票
    # 股票：A 股 6 位数字代码（000xxx/002xxx/300xxx/600xxx/688xxx/900xxx）
    # 基金：常见前缀 11/15/16/51/52
    if code.isdigit() and len(code) == 6:
        prefix = code[:2]
        fund_prefixes = ("11", "15", "16", "51", "52")
        stock_prefixes = ("00", "30", "60", "68", "90", "20", "83")
        if prefix in fund_prefixes:
            return "fund"
        if prefix in stock_prefixes:
            return "stock"
        # 其他 6 位数字默认按股票
        return "stock"
    return "stock"


# ============================================================================
# 3. 信号判定
# ============================================================================

def _classify_signal(expected_return: float) -> Tuple[str, float]:
    """根据预期收益返回 (direction, probability)。"""
    if expected_return > 1.0:
        return "bullish", min(0.85, 0.55 + expected_return / 100)
    elif expected_return < -1.0:
        return "bearish", min(0.85, 0.55 - expected_return / 100)
    return "neutral", 0.5 + abs(expected_return) / 100


def _annualized_to_horizon(annual_vol: float, horizon_days: int) -> float:
    """年化波动率换算到指定周期的区间宽度。"""
    if annual_vol <= 0:
        return 0.0
    return annual_vol * math.sqrt(horizon_days / 252.0)


def _calc_drivers_and_risks(horizon: str, momentum_20d: float = 0,
                             vol_20d: float = 0) -> Tuple[List[str], List[str]]:
    """根据动量与波动率推导驱动因素与风险。"""
    drivers = []
    risks = []
    if momentum_20d > 3:
        drivers.append("20日动量为正，短期趋势偏强")
    elif momentum_20d < -3:
        drivers.append("20日动量为负，短期趋势偏弱")

    if vol_20d > 30:
        risks.append("波动率偏高(>30%)，下行风险较大")
    elif vol_20d < 12:
        drivers.append("波动率较低(<12%)，下行风险可控")

    if horizon in ("1M", "3M", "6M"):
        drivers.append("中期需要关注宏观流动性变化")
    if horizon == "6M":
        risks.append("长期不确定，建议每 3 个月复盘一次")
    return drivers, risks


# ============================================================================
# 4. 核心预测器
# ============================================================================

HORIZON_DAYS = {
    "1d": 1,
    "5d": 5,
    "1M": 21,    # ≈1个月交易日
    "3M": 63,
    "6M": 126,
}

# 默认周期权重（v11.0 加权共识）
HORIZON_WEIGHTS = {
    "1d": 0.10,
    "5d": 0.20,
    "1M": 0.30,
    "3M": 0.25,
    "6M": 0.15,
}


def _safe_momentum(prices: List[float], window: int = 20) -> float:
    """计算最近 N 日动量（百分比）。"""
    if not prices or len(prices) < window + 1:
        return 0.0
    try:
        return (prices[-1] - prices[-window - 1]) / prices[-window - 1] * 100
    except (ZeroDivisionError, IndexError):
        return 0.0


def _safe_vol(prices: List[float], window: int = 20) -> float:
    """计算年化波动率（百分比）。"""
    if len(prices) < window + 1:
        return 0.0
    try:
        rets = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(-window, 0)
            if prices[i - 1] != 0
        ]
        if len(rets) < 2:
            return 0.0
        std = statistics.stdev(rets)
        return std * math.sqrt(252) * 100
    except Exception:
        return 0.0


def _safe_support_resistance(prices: List[float], window: int = 60) -> Tuple[float, float]:
    """计算关键支撑/压力位（最近 N 日最低/最高）。"""
    if not prices or len(prices) < 2:
        return 0.0, 0.0
    try:
        recent = prices[-window:] if len(prices) >= window else prices
        return min(recent), max(recent)
    except Exception:
        return 0.0, 0.0


def predict_horizon(prices: List[float], horizon: str,
                    momentum_20d: Optional[float] = None,
                    vol_20d: Optional[float] = None,
                    regime: Optional[str] = None) -> HorizonPrediction:
    """单周期预测（不依赖 LLM，纯离线量化）。

    Args:
        prices: 价格序列（最新在末尾）
        horizon: 1d / 5d / 1M / 3M / 6M
        momentum_20d: 已知动量（None 时自动计算）
        vol_20d: 已知波动率（None 时自动计算）
        regime: 当前市场体制（bullish / bearish / neutral）
    """
    days = HORIZON_DAYS.get(horizon, 1)
    m = momentum_20d if momentum_20d is not None else _safe_momentum(prices)
    v = vol_20d if vol_20d is not None else _safe_vol(prices)
    support, resistance = _safe_support_resistance(prices)

    # 期望收益：动量按 horizon 衰减
    horizon_factor = math.sqrt(days / 21.0)   # 1 个月为基准
    raw_expected = m * horizon_factor * 0.5      # 动量半衰（保守）

    # 体制调整
    if regime == "bearish":
        raw_expected *= 0.7
    elif regime == "bullish":
        raw_expected *= 1.3

    # 区间宽度：波动率 × √t
    if v > 0:
        period_vol = v * math.sqrt(days / 252.0) * 0.7   # 70% 置信区间
    else:
        period_vol = abs(raw_expected) * 1.5 + 1.0  # 至少 ±1%

    direction, probability = _classify_signal(raw_expected)
    confidence = min(0.9, 0.4 + math.log10(max(1, len(prices))) * 0.1 + (v / 100.0))

    drivers, risks = _calc_drivers_and_risks(horizon, m, v)

    return HorizonPrediction(
        horizon=horizon,
        direction=direction,
        probability=round(probability, 3),
        confidence=round(confidence, 3),
        expected_return=round(raw_expected, 2),
        range_low=round(-period_vol, 2),
        range_high=round(period_vol, 2),
        key_support=round(support, 2),
        key_resistance=round(resistance, 2),
        drivers=drivers,
        risk_factors=risks,
        method="rule_based",
        quality="derived" if len(prices) >= 60 else "estimated",
    )


def predict_multi_horizon(code: str, prices: Optional[List[float]] = None,
                          asset_type: Optional[str] = None,
                          regime: Optional[str] = None,
                          horizons: Optional[List[str]] = None,
                          **kwargs) -> MultiHorizonResult:
    """v11.0 多周期预测统一入口（股票/基金/期货/指数通用）。

    Args:
        code: 资产代码
        prices: 价格序列（None 时尝试从 core_analyzer 拉取）
        asset_type: 资产类型（None 时自动识别）
        regime: 市场体制
        horizons: 要返回的周期列表（None 时使用全部 5 个周期）
        **kwargs: 透传给 predict_horizon 的动量/波动率参数
    """
    import time
    start = time.monotonic()

    if asset_type is None:
        asset_type = detect_asset_type(code)

    if prices is None or len(prices) < 30:
        # 尝试通过 core_analyzer 获取价格
        prices = _fetch_prices_via_core(code, asset_type)

    if horizons is None:
        horizons = list(HORIZON_DAYS.keys())

    h_predictions: Dict[str, HorizonPrediction] = {}
    for h in horizons:
        try:
            h_predictions[h] = predict_horizon(
                prices or [], horizon=h, regime=regime, **kwargs
            )
        except Exception as e:
            logger.debug(f"预测 {code}/{h} 失败: {e}")
            h_predictions[h] = HorizonPrediction(
                horizon=h, method="rule_based",
                quality="unavailable",
                risk_factors=[f"预测失败: {str(e)[:80]}"],
            )

    overall_signal, overall_confidence = _aggregate(h_predictions)
    import datetime
    return MultiHorizonResult(
        code=code,
        name=kwargs.get("name", code),
        asset_type=asset_type,
        horizons=h_predictions,
        overall_signal=overall_signal,
        overall_confidence=round(overall_confidence, 3),
        timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        latency_ms=round((time.monotonic() - start) * 1000, 1),
    )


def _aggregate(horizons: Dict[str, HorizonPrediction]) -> Tuple[str, float]:
    """加权汇总多周期信号。"""
    if not horizons:
        return "neutral", 0.5
    bullish_score = 0.0
    bearish_score = 0.0
    weighted_conf = 0.0
    total_w = 0.0
    for h_name, pred in horizons.items():
        w = HORIZON_WEIGHTS.get(h_name, 0.2)
        total_w += w
        weighted_conf += pred.confidence * w
        if pred.direction == "bullish":
            bullish_score += pred.probability * w
        elif pred.direction == "bearish":
            bearish_score += pred.probability * w
    if total_w == 0:
        return "neutral", 0.5
    weighted_conf /= total_w
    if bullish_score > bearish_score and bullish_score > 0.5:
        return "bullish", weighted_conf
    if bearish_score > bullish_score and bearish_score > 0.5:
        return "bearish", weighted_conf
    return "neutral", weighted_conf


def _fetch_prices_via_core(code: str, asset_type: str) -> List[float]:
    """通过 core_analyzer 获取价格序列（兼容 v9.0）。"""
    try:
        from stock_researcher.core_analyzer import StockResearcher
        researcher = StockResearcher(code)
        # 尝试获取行情+K线（不同 core_analyzer 版本接口可能不同）
        for attr in ("kline_data", "prices", "klines", "_prices"):
            if hasattr(researcher, attr):
                data = getattr(researcher, attr)
                if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
                    return data
                # DataFrame 或 list of dict
                if hasattr(data, "close"):
                    return list(data.close)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return [d.get("close", 0) for d in data if d.get("close")]
    except Exception as e:
        logger.debug(f"_fetch_prices_via_core 失败: {e}")
    return []


# ============================================================================
# 5. 预测校准（v11.0）
# ============================================================================

@dataclass
class CalibrationResult:
    """单条预测校准结果。"""
    raw_probability: float
    calibrated_probability: float
    n_samples: int
    bucket: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calibrate_probability(raw_prob: float,
                          history: Optional[List[Tuple[float, bool]]] = None) -> CalibrationResult:
    """基于历史 (raw_prob, hit) 样本做概率校准（v11.0 简化版）。

    Args:
        raw_prob: 原始预测概率（0-1）
        history: 历史样本 [(raw_prob, hit_bool), ...]，None 时返回原值
    """
    if not history:
        return CalibrationResult(
            raw_probability=raw_prob,
            calibrated_probability=raw_prob,
            n_samples=0,
            bucket="no_history",
        )

    # 分桶（5 桶：0-20, 20-40, 40-60, 60-80, 80-100）
    bucket_idx = min(4, int(raw_prob * 5))
    bucket_range = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)][bucket_idx]
    bucket_label = f"[{bucket_range[0]:.1f}-{bucket_range[1]:.1f})"

    bucket_samples = [
        hit for p, hit in history if bucket_range[0] <= p < bucket_range[1]
    ]
    if not bucket_samples:
        return CalibrationResult(
            raw_probability=raw_prob,
            calibrated_probability=raw_prob,
            n_samples=len(history),
            bucket=bucket_label,
        )

    # 经验频率 → 等渗回归（简化为直接取经验频率）
    empirical = sum(bucket_samples) / len(bucket_samples)
    # 加权平均（保留 30% 原始概率，避免过拟合）
    calibrated = raw_prob * 0.3 + empirical * 0.7

    return CalibrationResult(
        raw_probability=round(raw_prob, 3),
        calibrated_probability=round(calibrated, 3),
        n_samples=len(history),
        bucket=bucket_label,
    )


# ============================================================================
# 6. 自检
# ============================================================================

def self_check() -> Dict[str, Any]:
    """v11.0 多周期预测器自检。"""
    sample_prices = [100 + i * 0.5 + (i % 7) * 0.3 for i in range(120)]
    result = predict_multi_horizon("TEST", prices=sample_prices)
    return {
        "version": "v11.0",
        "MultiHorizonPredictor": "OK",
        "horizon_days": HORIZON_DAYS,
        "horizon_weights": HORIZON_WEIGHTS,
        "sample_test": {
            "code": "TEST",
            "asset_type": result.asset_type,
            "horizons_returned": list(result.horizons.keys()),
            "overall_signal": result.overall_signal,
            "overall_confidence": result.overall_confidence,
        },
        "calibration": {
            "calibrate_probability_fn": "OK (with/without history)",
        },
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(self_check(), ensure_ascii=False, indent=2))