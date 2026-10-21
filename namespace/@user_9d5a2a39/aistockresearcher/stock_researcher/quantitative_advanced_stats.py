# -*- coding: utf-8 -*-
"""
高级量化统计与计算模块 v9.4.0 (advanced_stats.py)

强化量化分析与计算能力：在 QuantMetrics 基础指标之上补充
滚动窗口指标、回撤深度剖析、仓位管理计算、统计检验、
业绩归因与相关性矩阵。纯 Python 标准库，零 pip 依赖，全部纯函数。

能力：
  - rolling_metrics          : 滚动年化收益/波动/Sharpe/回撤序列
  - drawdown_report          : Top-N 回撤剖析（深度/持续期/恢复期）
  - kelly_fraction           : 凯利公式仓位（含分数凯利与上限）
  - fixed_fractional_size    : 固定风险金额仓位法
  - vol_target_weight        : 波动率目标仓位
  - skewness / kurtosis      : 高阶矩（偏度/超额峰度）
  - jarque_bera              : JB 正态性检验（df=2 精确 p 值）
  - autocorrelation          : 收益自相关（动量/反转结构）
  - ljung_box                : Ljung-Box 自相关联合检验
  - tracking_error / information_ratio / up_down_capture : 业绩归因
  - correlation_matrix       : 多序列 Pearson 相关矩阵
  - quick_advanced_stats      : 一站式高级量化体检
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

TRADING_DAYS = 252


# ── 基础工具 ───────────────────────────────────────────────────

def _clean(values: Sequence) -> List[float]:
    out: List[float] = []
    for v in values or []:
        try:
            f = float(v)
            if math.isfinite(f):
                out.append(f)
        except (TypeError, ValueError):
            continue
    return out


def _returns(prices: Sequence[float]) -> List[float]:
    p = _clean(prices)
    return [(p[i] / p[i - 1] - 1.0) for i in range(1, len(p)) if p[i - 1] > 0]


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


# ── 滚动窗口指标 ───────────────────────────────────────────────

def rolling_metrics(prices: Sequence[float], window: int = 60,
                    risk_free: float = 0.02) -> List[Dict[str, Optional[float]]]:
    """滚动窗口指标序列（长度 = len(prices) - window）。

    每个窗口输出：年化收益 / 年化波动 / 年化 Sharpe / 窗口内最大回撤。
    """
    p = _clean(prices)
    if len(p) < window + 1 or window < 5:
        return []
    out: List[Dict[str, Optional[float]]] = []
    for end in range(window, len(p)):
        seg = p[end - window:end + 1]
        rets = _returns(seg)
        if not rets:
            continue
        mu, sd = _mean(rets), _std(rets)
        ann_ret = mu * TRADING_DAYS
        ann_vol = sd * math.sqrt(TRADING_DAYS)
        sharpe = ((ann_ret - risk_free) / ann_vol) if ann_vol > 1e-12 else None
        peak, mdd = seg[0], 0.0
        for v in seg:
            peak = max(peak, v)
            if peak > 0:
                mdd = min(mdd, v / peak - 1.0)
        out.append({
            "index": end,
            "ann_return": ann_ret,
            "ann_vol": ann_vol,
            "sharpe": sharpe,
            "max_drawdown": mdd,
        })
    return out


def rolling_stability(rolling_series: List[Dict], key: str = "sharpe") -> Dict:
    """滚动序列的稳定性评估：均值/标准差/为正占比。"""
    vals = [r.get(key) for r in rolling_series if r.get(key) is not None]
    if len(vals) < 3:
        return {"available": False, "n": len(vals)}
    mu, sd = _mean(vals), _std(vals)
    return {
        "available": True,
        "n": len(vals),
        "mean": mu,
        "std": sd,
        "positive_ratio": sum(1 for v in vals if v > 0) / len(vals),
        "stable": sd < max(abs(mu), 1e-9),   # 波动小于均值量级视为稳定
    }


# ── 回撤深度剖析 ───────────────────────────────────────────────

def drawdown_report(prices: Sequence[float],
                    top_n: int = 5) -> Dict:
    """Top-N 回撤剖析：每段回撤的深度/起点/谷底/恢复点/持续与恢复天数。"""
    p = _clean(prices)
    if len(p) < 2:
        return {"drawdowns": [], "max_drawdown": 0.0,
                "longest_duration": 0, "n_drawdowns": 0}
    episodes: List[Dict] = []
    peak_i = 0
    trough_i = 0
    peak_v = p[0]
    trough_v = p[0]
    in_dd = False
    for i, v in enumerate(p):
        if v >= peak_v:
            if in_dd:
                episodes.append(_finish_episode(peak_i, trough_i, i,
                                                peak_v, trough_v))
                in_dd = False
            peak_i, peak_v = i, v
            trough_i, trough_v = i, v
        elif v < trough_v:
            trough_i, trough_v = i, v
            in_dd = True
    if in_dd:   # 仍在回撤中（未恢复）
        ep = _finish_episode(peak_i, trough_i, None, peak_v, trough_v)
        ep["recovered"] = False
        episodes.append(ep)
    episodes.sort(key=lambda e: e["depth"])
    dd_list = episodes[:max(1, int(top_n))]
    return {
        "drawdowns": dd_list,
        "max_drawdown": dd_list[0]["depth"] if dd_list else 0.0,
        "longest_duration": max((e["duration"] for e in episodes), default=0),
        "n_drawdowns": len(episodes),
    }


def _finish_episode(peak_i: int, trough_i: int,
                    recovery_i: Optional[int],
                    peak_v: float, trough_v: float) -> Dict:
    depth = (trough_v / peak_v - 1.0) if peak_v > 0 else 0.0
    return {
        "depth": depth,
        "start_index": peak_i,
        "trough_index": trough_i,
        "recovery_index": recovery_i,
        "duration": trough_i - peak_i,
        "recovery_days": (recovery_i - trough_i) if recovery_i is not None else None,
        "recovered": recovery_i is not None,
    }


# ── 仓位管理计算 ───────────────────────────────────────────────

def kelly_fraction(win_rate: float, win_loss_ratio: float,
                   fraction: float = 0.5, cap: float = 0.25) -> Dict:
    """凯利公式仓位：f* = p - (1-p)/b；默认半凯利并封顶 25%。

    win_rate: 历史胜率 (0-1)；win_loss_ratio: 平均盈利/平均亏损。
    """
    p = max(0.0, min(1.0, float(win_rate or 0)))
    b = max(1e-9, float(win_loss_ratio or 0))
    full = p - (1.0 - p) / b
    frac = max(0.0, min(cap, full * max(0.0, float(fraction))))
    return {
        "full_kelly": full,
        "fraction": fraction,
        "suggested": frac,
        "capped": full * max(0.0, float(fraction)) > cap,
        "edge": p * b - (1.0 - p),   # 期望净优势，<=0 时不应下注
    }


def fixed_fractional_size(capital: float, risk_per_trade: float,
                          entry: float, stop: float) -> Dict:
    """固定风险金额仓位法：单笔风险 = 资金 × risk_per_trade，除以每股止损距离。"""
    capital, risk = float(capital or 0), max(0.0, float(risk_per_trade or 0))
    entry, stop = float(entry or 0), float(stop or 0)
    risk_amount = capital * risk
    per_share = abs(entry - stop)
    if per_share <= 1e-12 or capital <= 0:
        return {"shares": 0, "risk_amount": risk_amount, "position_value": 0.0,
                "position_ratio": 0.0}
    shares = risk_amount / per_share
    value = shares * entry
    return {
        "shares": shares,
        "lots_a_share": int(shares // 100),   # A股整手（100股）
        "risk_amount": risk_amount,
        "position_value": value,
        "position_ratio": min(1.0, value / capital) if capital > 0 else 0.0,
    }


def vol_target_weight(returns: Sequence[float], target_vol: float = 0.15,
                      window: int = 60, periods: int = TRADING_DAYS,
                      cap: float = 1.0) -> Dict:
    """波动率目标仓位：w = 目标年化波动 / 标的年化波动（近 window 期）。"""
    rets = _clean(returns)
    if len(rets) < max(5, window // 2):
        return {"weight": 0.0, "ann_vol": None, "target_vol": target_vol}
    recent = rets[-window:]
    ann_vol = _std(recent) * math.sqrt(periods)
    if ann_vol <= 1e-12:
        return {"weight": cap, "ann_vol": 0.0, "target_vol": target_vol}
    w = min(cap, max(0.0, float(target_vol) / ann_vol))
    return {"weight": w, "ann_vol": ann_vol, "target_vol": float(target_vol)}


# ── 统计检验 ───────────────────────────────────────────────────

def skewness(values: Sequence[float]) -> Optional[float]:
    """样本偏度（调整无偏估计），负值=左尾更肥。"""
    xs = _clean(values)
    n = len(xs)
    if n < 3:
        return None
    mu, sd = _mean(xs), _std(xs)
    if sd <= 1e-12:
        return 0.0
    m3 = sum(((x - mu) / sd) ** 3 for x in xs) / n
    return m3 * math.sqrt(n * (n - 1)) / (n - 2)


def kurtosis(values: Sequence[float]) -> Optional[float]:
    """超额峰度（>0 肥尾），金融收益通常为正。"""
    xs = _clean(values)
    n = len(xs)
    if n < 4:
        return None
    mu, sd = _mean(xs), _std(xs)
    if sd <= 1e-12:
        return 0.0
    m4 = sum(((x - mu) / sd) ** 4 for x in xs) / n
    # 样本超额峰度（正态=0）
    return ((n + 1) * m4 - 3 * (n - 1)) * (n - 1) / ((n - 2) * (n - 3)) + 0.0


def jarque_bera(returns: Sequence[float]) -> Dict:
    """Jarque-Bera 正态性检验。df=2 卡方精确 p 值 = exp(-JB/2)。"""
    rets = _clean(returns)
    n = len(rets)
    s, k = skewness(rets), kurtosis(rets)
    if n < 8 or s is None or k is None:
        return {"available": False, "n": n}
    jb = n / 6.0 * (s ** 2 + (k ** 2) / 4.0)
    p = math.exp(-jb / 2.0)   # chi2(df=2) 生存函数
    return {
        "available": True, "n": n, "statistic": jb, "p_value": p,
        "skewness": s, "excess_kurtosis": k,
        "normal": p > 0.05,
        "verdict": "接近正态" if p > 0.05 else "显著非正态（肥尾/偏斜）",
    }


def autocorrelation(returns: Sequence[float], lag: int = 1) -> Optional[float]:
    """收益自相关系数：>0 动量延续，<0 短期反转。"""
    rets = _clean(returns)
    n = len(rets)
    if lag < 1 or n <= lag + 2:
        return None
    mu = _mean(rets)
    num = sum((rets[i] - mu) * (rets[i - lag] - mu) for i in range(lag, n))
    den = sum((x - mu) ** 2 for x in rets)
    return num / den if den > 1e-18 else 0.0


def ljung_box(returns: Sequence[float], lags: int = 10) -> Dict:
    """Ljung-Box 自相关联合检验。p 值用 Wilson-Hilferty 卡方近似。"""
    rets = _clean(returns)
    n = len(rets)
    if n < max(20, lags + 5):
        return {"available": False, "n": n}
    q = 0.0
    acf_detail: List[float] = []
    for h in range(1, lags + 1):
        ac = autocorrelation(rets, h)
        if ac is None:
            break
        acf_detail.append(ac)
        q += ac * ac / (n - h)
    q *= n * (n + 2)
    h = len(acf_detail)
    if h == 0:
        return {"available": False, "n": n}
    p = _chi2_sf(q, df=h)
    return {
        "available": True, "n": n, "lags": h,
        "statistic": q, "p_value": p,
        "acf": acf_detail,
        "independent": p > 0.05,
        "verdict": "序列近似独立（无显著自相关）" if p > 0.05
                   else "存在显著自相关（动量/反转结构）",
    }


def _chi2_sf(x: float, df: int) -> float:
    """卡方分布生存函数近似（Wilson-Hilferty），df≥1。"""
    if x <= 0:
        return 1.0
    if df <= 0:
        return 1.0
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    # 标准正态生存函数近似（Abramowitz-Stegun）
    return _normal_sf(z)


def _normal_sf(z: float) -> float:
    """标准正态生存函数 P(Z > z)，误差 < 7.5e-8。"""
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989423 * math.exp(-z * z / 2.0)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (
        1.781478 + t * (-1.821256 + t * 1.330274))))
    return p if z > 0 else 1.0 - p


# ── 业绩归因 ───────────────────────────────────────────────────

def _aligned(a: Sequence[float], b: Sequence[float]) -> Tuple[List[float], List[float]]:
    xa, xb = _clean(a), _clean(b)
    n = min(len(xa), len(xb))
    return xa[-n:], xb[-n:]


def tracking_error(returns: Sequence[float],
                   benchmark_returns: Sequence[float],
                   periods: int = TRADING_DAYS) -> Optional[float]:
    """跟踪误差：超额收益的年化标准差。"""
    ra, rb = _aligned(returns, benchmark_returns)
    if len(ra) < 5:
        return None
    ex = [x - y for x, y in zip(ra, rb)]
    return _std(ex) * math.sqrt(periods)


def information_ratio(returns: Sequence[float],
                      benchmark_returns: Sequence[float],
                      periods: int = TRADING_DAYS) -> Optional[float]:
    """信息比率 = 年化超额收益 / 跟踪误差。"""
    ra, rb = _aligned(returns, benchmark_returns)
    if len(ra) < 5:
        return None
    ex = [x - y for x, y in zip(ra, rb)]
    te = _std(ex) * math.sqrt(periods)
    if te <= 1e-12:
        return None
    return _mean(ex) * periods / te


def up_down_capture(returns: Sequence[float],
                    benchmark_returns: Sequence[float]) -> Dict:
    """上行/下行捕获率：牛市跟涨能力与熊市抗跌能力。"""
    ra, rb = _aligned(returns, benchmark_returns)
    up = [i for i, b in enumerate(rb) if b > 0]
    down = [i for i, b in enumerate(rb) if b < 0]

    def _capture(idx):
        if len(idx) < 5:
            return None
        br = _mean([rb[i] for i in idx])
        ar = _mean([ra[i] for i in idx])
        return ar / br if abs(br) > 1e-12 else None

    up_c, down_c = _capture(up), _capture(down)
    ratio = (up_c / down_c) if (up_c is not None and down_c
                                and abs(down_c) > 1e-12) else None
    return {"up_capture": up_c, "down_capture": down_c,
            "capture_ratio": ratio,
            "verdict": _capture_verdict(up_c, down_c)}


def _capture_verdict(up_c: Optional[float], down_c: Optional[float]) -> str:
    if up_c is None or down_c is None:
        return "样本不足"
    if up_c >= 1.0 and down_c < 1.0:
        return "攻守兼备（跟涨且抗跌）"
    if up_c >= 1.0:
        return "进攻型（跟涨强，回撤也大）"
    if down_c < 1.0:
        return "防御型（抗跌但跟涨弱）"
    return "弱于基准"


# ── 相关性矩阵 ─────────────────────────────────────────────────

def correlation_matrix(named_series: Dict[str, Sequence[float]]) -> Dict:
    """多序列 Pearson 相关矩阵（尾部对齐）。返回 {pairs: {(a,b): corr}, matrix}。"""
    names = list(named_series.keys())
    cleaned = {k: _clean(v) for k, v in named_series.items()}
    pairs: Dict[Tuple[str, str], Optional[float]] = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = cleaned[names[i]], cleaned[names[j]]
            n = min(len(a), len(b))
            if n < 5:
                pairs[(names[i], names[j])] = None
                continue
            xa, xb = a[-n:], b[-n:]
            ma, mb = _mean(xa), _mean(xb)
            num = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
            da = math.sqrt(sum((x - ma) ** 2 for x in xa))
            db = math.sqrt(sum((y - mb) ** 2 for y in xb))
            pairs[(names[i], names[j])] = num / (da * db) if da * db > 1e-18 else 0.0
    return {"names": names, "pairs": pairs, "n_series": len(names)}


# ── 一站式体检 ─────────────────────────────────────────────────

def quick_advanced_stats(prices: Sequence[float],
                         benchmark: Optional[Sequence[float]] = None,
                         window: int = 60) -> Dict:
    """一站式高级量化体检（纯离线确定性）。

    输出：滚动指标稳定性 / 回撤剖析 / 凯利仓位参考 / 统计检验 /
          业绩归因（有基准时）/ 仓位建议（波动率目标）。
    """
    p = _clean(prices)
    rets = _returns(p)
    result: Dict = {
        "n_prices": len(p),
        "n_returns": len(rets),
        "available": len(rets) >= 20,
    }
    if not result["available"]:
        return result
    roll = rolling_metrics(p, window=window)
    result["rolling"] = {
        "window": window,
        "n_windows": len(roll),
        "stability": rolling_stability(roll, "sharpe"),
        "latest": roll[-1] if roll else None,
    }
    result["drawdown"] = drawdown_report(p, top_n=3)
    # 基于历史日收益的胜率/盈亏比 → 凯利参考
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    win_rate = len(wins) / len(rets) if rets else 0.0
    payoff = (_mean(wins) / abs(_mean(losses))) if losses and wins else 1.0
    result["kelly"] = kelly_fraction(win_rate, payoff)
    result["stats_tests"] = {
        "jarque_bera": jarque_bera(rets),
        "ljung_box": ljung_box(rets, lags=min(10, max(1, len(rets) // 20))),
        "acf1": autocorrelation(rets, 1),
        "skewness": skewness(rets),
        "excess_kurtosis": kurtosis(rets),
    }
    result["position"] = vol_target_weight(rets)
    if benchmark is not None:
        bench_rets = _returns(_clean(benchmark))
        if len(bench_rets) >= 20:
            result["attribution"] = {
                "tracking_error": tracking_error(rets, bench_rets),
                "information_ratio": information_ratio(rets, bench_rets),
                "up_down_capture": up_down_capture(rets, bench_rets),
            }
    return result
