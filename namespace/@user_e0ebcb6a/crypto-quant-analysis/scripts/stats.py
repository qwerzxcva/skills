"""
Statistical analysis script for cryptocurrency markets (v2.0).

Provides crypto-specific statistical analysis:
- Correlation matrix (inter-asset correlation)
- Volatility metrics (annualized, rolling)
- Linear regression trend analysis
- Return statistics (mean, std, skewness, kurtosis)

Uses statsmodels and scipy for statistically sound computations.
OHLCV data is fetched via ccxt with network-aware exchange selection.
"""

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats  # type: ignore[import-untyped]
from statsmodels.regression.linear_model import OLS  # type: ignore[import-untyped]
from statsmodels.tools.tools import add_constant  # type: ignore[import-untyped]

# ------------------------------------------------------------------- #
# Local imports
# ------------------------------------------------------------------- #
# pylint: disable=import-error, wrong-import-position
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbol,
    _normalize_symbols,
    _get_exchange,
    _fetch_df,
    _fetch_multi_df,
    _s,
    parse_common_args,
    get_network_env,
)


# ------------------------------------------------------------------- #
# Helpers
# ------------------------------------------------------------------- #
def _compute_returns(df: pd.DataFrame, method: str = "log") -> pd.Series:
    """Compute asset returns from close prices.

    Args:
        df: OHLCV DataFrame with 'close' column.
        method: "log" for log returns, "simple" for simple returns. Default "log".

    Returns:
        Series of returns (same length as df, first element is NaN).
    """
    if method == "log":
        return np.log(df["close"] / df["close"].shift(1))
    return df["close"].pct_change()


# ------------------------------------------------------------------- #
# Action functions
# ------------------------------------------------------------------- #
def action_correlation(symbols_raw: str,
                       timeframe: str = "1d",
                       limit: int = 100) -> str:
    """Compute correlation matrix between multiple crypto assets.

    Correlation measures how assets move relative to each other:
    - +1.0: perfect positive correlation (move together)
    -  0.0: no linear correlation
    - -1.0: perfect negative correlation (move oppositely)

    In crypto markets, most assets have high positive correlation (0.5-0.8)
    during normal conditions, and approach 1.0 during market-wide crashes.

    Args:
        symbols_raw: Comma-separated symbol string, e.g. "BTC,ETH,SOL,AVAX".
        timeframe: Candle interval. Default "1d".
        limit: Number of candles to use. Default 100.

    Returns:
        JSON string with keys: symbols, timeframe, limit, correlation_matrix (2D array).
    """
    symbols: List[str] = _normalize_symbols(symbols_raw)
    data = _fetch_multi_df(symbols, timeframe, limit)

    if len(data) < 2:
        raise ValueError(
            f"Need at least 2 valid symbols for correlation. "
            f"Got {len(data)} valid symbols from: {symbols}"
        )

    # Align all DataFrames by timestamp and compute returns
    returns_dict: Dict[str, pd.Series] = {}
    for sym, df in data.items():
        returns_dict[sym] = _compute_returns(df, method="log").dropna()

    # Align all return series to common timestamps
    aligned = pd.DataFrame(returns_dict)
    corr_matrix = aligned.corr()

    # Convert to serializable format
    matrix_list = corr_matrix.round(4).values.tolist()
    symbols_out = list(corr_matrix.columns)

    return json.dumps({
        "symbols": symbols_out,
        "timeframe": timeframe,
        "limit": limit,
        "data_points": int(aligned.shape[0]),
        "correlation_matrix": matrix_list,
        "interpretation": {
            "high_positive": "Correlation > 0.7: assets move strongly together. "
                             "Diversification benefit is limited.",
            "moderate": "Correlation 0.3-0.7: moderate co-movement. "
                        "Some diverssification benefit.",
            "low": "Correlation < 0.3: weak co-movement. "
                    "Good diverssification potential.",
        },
    }, indent=2, ensure_ascii=False)


def action_volatility(symbol: str,
                      timeframe: str = "1d",
                      limit: int = 100,
                      annualize: bool = True) -> str:
    """Compute volatility metrics for a single asset.

    Volatility is the standard deviation of returns, annualized by default.
    Higher volatility = higher risk (and potentially higher return).

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 100.
        annualize: Whether to annualize volatility. Default True.
                  1d candles -> multiply by sqrt(365); 4h -> sqrt(2190).

    Returns:
        JSON string with keys: symbol, volatility (annualized and rolling),
        max_drawdown, sharpe_approx (return/vol ratio).
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    returns = _compute_returns(df, method="log").dropna()

    if len(returns) < 10:
        raise ValueError(f"Need at least 10 data points; got {len(returns)}.")

    # Annualization factor
    ann_factor: float = 1.0
    if annualize:
        tf_to_ann: Dict[str, float] = {
            "1m": 525_600.0, "5m": 105_120.0, "15m": 35_040.0,
            "1h": 8_760.0, "4h": 2_190.0, "1d": 365.0,
        }
        ann_factor = tf_to_ann.get(timeframe, 365.0)

    vol_daily = float(returns.std())
    vol_annualized = vol_daily * np.sqrt(ann_factor) if annualize else vol_daily

    # Rolling volatility (21-period = ~3 weeks for daily)
    rolling_vol = returns.rolling(window=21).std() * np.sqrt(ann_factor) if annualize else returns.rolling(window=21).std()
    current_rolling = _s(rolling_vol.iloc[-1])

    # Max drawdown
    cumulative = (1 + returns).cumprod()
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak) / peak
    max_dd = float(drawdown.min())

    return json.dumps({
        "symbol": symbol,
        "timeframe": timeframe,
        "annualized_volatility_pct": round(vol_annualized * 100, 2),
        "daily_volatility_pct": round(vol_daily * 100, 4),
        "current_rolling_vol_pct": round(current_rolling * 100, 2) if current_rolling else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "annualization_factor": ann_factor if annualize else None,
        "interpretation": {
            "low_vol": "Volatility < 50% (annualized): relatively stable for crypto.",
            "medium_vol": "Volatility 50-100%: standard crypto volatility.",
            "high_vol": "Volatility > 100%: high-risk asset. Position size with caution.",
        }.get(
            "low_vol" if vol_annualized < 0.5 else "medium_vol" if vol_annualized < 1.0 else "high_vol",
            "",
        ),
    }, indent=2, ensure_ascii=False)


def action_regression(symbol: str,
                      timeframe: str = "1d",
                      limit: int = 200) -> str:
    """Perform linear regression trend analysis on price data.

    Fits a linear trend line to closing prices over time:
    - Positive slope: upward trend
    - Negative slope: downward trend
    - R-squared: how well the line fits (0-1; higher = stronger trend)

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 200.

    Returns:
        JSON string with keys: symbol, slope, r_squared, p_value, trend
        (strong_uptrend/weak_uptrend/no_trend/weak_downtrend/strong_downtrend).
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)

    # Use integer time index (0, 1, 2, ...) for regression
    y = df["close"].values
    x = np.arange(len(y))
    x_with_const = add_constant(x)  # type: ignore[no-untyped-call]

    model = OLS(y, x_with_const).fit()  # type: ignore[no-untyped-call]

    slope = float(model.params[1])
    r_squared = float(model.rsquared)
    p_value = float(model.pvalues[1])
    std_err = float(model.bse[1])

    # Determine trend strength
    if p_value < 0.05:  # Statistically significant
        if slope > 0:
            trend = "strong_uptrend" if r_squared > 0.3 else "weak_uptrend"
        else:
            trend = "strong_downtrend" if r_squared > 0.3 else "weak_downtrend"
    else:
        trend = "no_significant_trend"

    return json.dumps({
        "symbol": symbol,
        "timeframe": timeframe,
        "slope": round(slope, 6),
        "r_squared": round(r_squared, 4),
        "p_value": round(p_value, 6),
        "std_error": round(std_err, 6),
        "trend": trend,
        "interpretation": {
            "strong_uptrend": f"Strong statistically significant uptrend (R²={r_squared:.2f}).",
            "weak_uptrend": f"Weak uptrend, not a strong trend (R²={r_squared:.2f}).",
            "strong_downtrend": f"Strong statistically significant downtrend (R²={r_squared:.2f}).",
            "weak_downtrend": f"Weak downtrend, not a strong trend (R²={r_squared:.2f}).",
            "no_significant_trend": "No statistically significant price trend detected.",
        }.get(trend, ""),
    }, indent=2, ensure_ascii=False)


def action_returns_stats(symbol: str,
                         timeframe: str = "1d",
                         limit: int = 200) -> str:
    """Compute descriptive statistics for asset returns.

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 200.

    Returns:
        JSON string with keys: mean_return, std_return, sharpe_approx,
        skewness, kurtosis, jarque_bera_pvalue.
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    returns = _compute_returns(df, method="log").dropna()

    mean_ret = float(returns.mean())
    std_ret = float(returns.std())
    skew = float(scipy_stats.skew(returns.dropna()))
    kurt = float(scipy_stats.kurtosis(returns.dropna()))

    # Approximate Sharpe (assuming 0 risk-free rate for crypto)
    sharpe = mean_ret / std_ret * np.sqrt(365) if std_ret != 0 else 0.0

    # Jarque-Bera test for normality (p < 0.05 means non-normal)
    jb_stat, jb_pvalue = scipy_stats.jarque_bera(returns.dropna())

    return json.dumps({
        "symbol": symbol,
        "timeframe": timeframe,
        "data_points": len(returns),
        "mean_daily_return_pct": round(mean_ret * 100, 4),
        "annualized_return_pct": round(mean_ret * 365 * 100, 2),
        "std_daily_return_pct": round(std_ret * 100, 4),
        "annualized_sharpe_ratio": round(sharpe, 4),
        "skewness": round(skew, 4),
        "excess_kurtosis": round(kurt, 4),
        "jarque_bera_pvalue": round(float(jb_pvalue), 6),
        "is_normal": float(jb_pvalue) > 0.05,
        "interpretation": {
            "skewness": "Skewness > 0: right-tailed (more upside spikes). "
                         "Skewness < 0: left-tailed (more downside spikes). "
                         "Crypto typically has negative skewness (crash risk).",
            "kurtosis": "Kurtosis > 0: fat-tailed (extreme events more likely than normal distribution). "
                         "Crypto typically has high kurtosis.",
        },
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------- #
# CLI entry point
# ------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Crypto statistical analysis (Gate/OKX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action correlation --symbols BTC,ETH,SOL,AVAX
  %(prog)s --action volatility --symbol BTC --timeframe 4h
  %(prog)s --action regression --symbol ETH
  %(prog)s --action returns_stats --symbol SOL
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["correlation", "volatility", "regression", "returns_stats"],
        help="Statistical analysis to perform.",
    )
    parser.add_argument("--symbol", type=str, default="BTC",
                        help="Single symbol for volatility/regression/returns (default: BTC)")
    parser.add_argument("--symbols", type=str, default="BTC,ETH,SOL,AVAX",
                        help="Comma-separated symbols for correlation (default: BTC,ETH,SOL,AVAX)")
    parser.add_argument("--timeframe", type=str, default="1d",
                        help="Candle interval (default: 1d)")
    parser.add_argument("--limit", type=int, default=200,
                        help="Number of candles (default: 200)")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "correlation":
            print(action_correlation(args.symbols, args.timeframe, args.limit))
        elif args.action == "volatility":
            print(action_volatility(args.symbol, args.timeframe, args.limit))
        elif args.action == "regression":
            print(action_regression(args.symbol, args.timeframe, args.limit))
        elif args.action == "returns_stats":
            print(action_returns_stats(args.symbol, args.timeframe, args.limit))
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
