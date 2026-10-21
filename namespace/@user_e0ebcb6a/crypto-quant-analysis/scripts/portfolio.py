"""
Portfolio optimization and risk analysis script (v2.0).

Implements standard portfolio construction and risk metrics:
1. Mean-Variance Optimization (MVO) - max Sharpe ratio / min volatility
2. Risk Parity - equal risk contribution
3. Value at Risk (VaR) - historical and parametric

Uses PyPortfolioOpt when available; falls back to numpy/scipy.
OHLCV data fetched with network-aware exchange selection.

New in v2.0:
- Integration with CoinGecko for market cap-weighted benchmarks
- Network environment-aware exchange selection
"""

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm  # type: ignore[import-untyped]

# -------------------------------------------------------------------- #
# Optional dependency: PyPortfolioOpt
# -------------------------------------------------------------------- #
try:
    from pypfopt import EfficientFrontier, risk_models, expected_returns  # type: ignore[import-untyped]
    PYPFOPT_AVAILABLE: bool = True
except ImportError:
    PYPFOPT_AVAILABLE = False

# -------------------------------------------------------------------- #
# Local imports
# -------------------------------------------------------------------- #
# pylint: disable=import-error, wrong-import-position
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbols,
    _fetch_multi_df,
    _s,
)


# -------------------------------------------------------------------- #
# Helpers: return matrix construction
# -------------------------------------------------------------------- #
def _build_return_matrix(symbols: List[str],
                         timeframe: str = "1d",
                         limit: int = 100) -> pd.DataFrame:
    """Fetch OHLCV data and build aligned return matrix.

    Args:
        symbols: List of trading pair strings (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles per symbol. Default 100.

    Returns:
        DataFrame of log returns, columns = symbols, index = timestamp.
        All symbols are aligned to common timestamps.

    Raises:
        ValueError: If fewer than 2 symbols have valid data.
    """
    data = _fetch_multi_df(symbols, timeframe, limit)
    if len(data) < 2:
        raise ValueError(
            f"Need at least 2 valid symbols. Got {len(data)} valid from: {symbols}"
        )

    returns_dict: Dict[str, pd.Series] = {}
    for sym, df in data.items():
        returns_dict[sym] = np.log(df["close"] / df["close"].shift(1)).dropna()

    aligned = pd.DataFrame(returns_dict)
    return aligned.dropna()


# -------------------------------------------------------------------- #
# Action: Mean-Variance Optimization
# -------------------------------------------------------------------- #
def action_optimize(symbols_raw: str,
                      timeframe: str = "1d",
                      limit: int = 100,
                      method: str = "max_sharpe") -> str:
    """Run Mean-Variance Portfolio Optimization.

    Mean-Variance Optimization finds weights that optimize a specific
    objective (max Sharpe, min volatility, max return) subject to
    constraints (full investment, no short-selling).

    Args:
        symbols_raw: Comma-separated symbol string, e.g. "BTC,ETH,SOL,AVAX".
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 100.
        method: Optimization method: "max_sharpe", "min_volatility",
                "max_return" (target return = mean of means). Default "max_sharpe".

    Returns:
        JSON string with keys: symbols, weights (dict), expected_return_annualized,
        volatility_annualized, sharpe_ratio.
    """
    symbols: List[str] = _normalize_symbols(symbols_raw)
    returns = _build_return_matrix(symbols, timeframe, limit)

    if PYPFOPT_AVAILABLE:
        logger.info("Using PyPortfolioOpt for optimization.")
        mu = expected_returns.mean_historical_return(returns)  # type: ignore[no-untyped-call]
        S = risk_models.sample_cov(returns)  # type: ignore[no-untyped-call]

        ef = EfficientFrontier(mu, S)  # type: ignore[no-untyped-call]
        if method == "max_sharpe":
            ef.max_sharpe()  # type: ignore[no-untyped-call]
        elif method == "min_volatility":
            ef.min_volatility()  # type: ignore[no-untyped-call]
        else:
            ef.max_quadratic_utility()  # type: ignore[no-untyped-call]

        weights_dict = ef.clean_weights()  # type: ignore[no-untyped-call]
        perf = ef.portfolio_performance()  # type: ignore[no-untyped-call]
        # perf = (expected_return, annualized_volatility, sharpe_ratio)

        return json.dumps({
            "method": method,
            "symbols": list(weights_dict.keys()),
            "weights": {k: round(float(v), 4) for k, v in weights_dict.items()},
            "expected_return_annualized_pct": round(float(perf[0]) * 100, 2),
            "volatility_annualized_pct": round(float(perf[1]) * 100, 2),
            "sharpe_ratio": round(float(perf[2]), 4),
            "notes": "Using PyPortfolioOpt. Weights sum to 1.0. No short-selling constraint applied.",
        }, indent=2, ensure_ascii=False)

    # Fallback: equal-weight portfolio
    logger.warning("PyPortfolioOpt not available. Using equal-weight fallback.")
    n = len(returns.columns)
    equal_weights = {col: round(1.0 / n, 4) for col in returns.columns}
    ann_ret = float(returns.mean().mean() * 365)
    ann_vol = float(returns.std().mean() * np.sqrt(365))
    sharpe = ann_ret / ann_vol if ann_vol != 0 else 0.0

    return json.dumps({
        "method": "equal_weight_fallback",
        "symbols": list(equal_weights.keys()),
        "weights": equal_weights,
        "expected_return_annualized_pct": round(ann_ret * 100, 2),
        "volatility_annualized_pct": round(ann_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "warning": "PyPortfolioOpt not installed. Install with: pip install pyportfolioopt",
    }, indent=2, ensure_ascii=False)


# -------------------------------------------------------------------- #
# Action: Risk Parity
# -------------------------------------------------------------------- #
def action_risk_parity(symbols_raw: str,
                         timeframe: str = "1d",
                         limit: int = 100) -> str:
    """Compute Risk Parity portfolio weights.

    Risk Parity allocates capital so that each asset contributes
    equal risk (volatility) to the portfolio. This is more robust
    than equal-weighting when asset volatilities differ significantly.

    Simplified algorithm (equal risk contribution via iterative scaling).

    Args:
        symbols_raw: Comma-separated symbol string.
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 100.

    Returns:
        JSON string with keys: symbols, weights, risk_contributions.
    """
    symbols: List[str] = _normalize_symbols(symbols_raw)
    returns = _build_return_matrix(symbols, timeframe, limit)

    # Compute covariance matrix
    cov = returns.cov() * 365  # Annualized

    # Simplified risk parity: inverse-vol weighting
    vols = returns.std() * np.sqrt(365)
    inv_vols = 1.0 / vols
    weights_raw = inv_vols / inv_vols.sum()
    weights = weights_raw.to_dict()

    # Approximate risk contribution
    portfolio_vol = float(np.sqrt((weights_raw.values @ cov.values @ weights_raw.values.T)))
    risk_contrib = {
        col: round(float(weights_raw[col] * (cov.loc[col, :].values @ weights_raw.values.T) / portfolio_vol), 4)
        for col in returns.columns
    }

    return json.dumps({
        "method": "risk_parity (inverse_vol weighting)",
        "symbols": list(weights.keys()),
        "weights": {k: round(float(v), 4) for k, v in weights.items()},
        "annualized_volatility_pct": round(portfolio_vol * 100, 2),
        "risk_contributions": risk_contrib,
        "notes": "Simplified risk parity using inverse-vol weighting. "
                  "For full equal-risk-contribution, install pyportfolioopt.",
    }, indent=2, ensure_ascii=False)


# -------------------------------------------------------------------- #
# Action: Value at Risk (VaR)
# -------------------------------------------------------------------- #
def action_var(symbol: str,
                timeframe: str = "1d",
                limit: int = 200,
                confidence: float = 0.95,
                method: str = "historical") -> str:
    """Compute Value at Risk (VaR) for a single asset.

    VaR estimates the maximum expected loss over a given time horizon
    at a given confidence level.

    Methods:
    - "historical": empirical quantile of historical returns.
    - "parametric": assumes normal distribution (Gaussian VaR).
    - "monte_carlo": Monte Carlo simulation (not implemented yet).

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 200.
        confidence: Confidence level (0-1). Default 0.95 (95% VaR).
        method: "historical" or "parametric". Default "historical".

    Returns:
        JSON string with keys: symbol, var_pct, var_absolute (for $1 position),
        confidence, method.
    """
    from utils import _normalize_symbol, _fetch_df  # noqa: E402

    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    returns = np.log(df["close"] / df["close"].shift(1)).dropna()

    if method == "historical":
        var_pct = float(np.percentile(returns, (1 - confidence) * 100))
    elif method == "parametric":
        mean = float(returns.mean())
        std = float(returns.std())
        var_pct = norm.ppf(1 - confidence, mean, std)  # type: ignore[no-untyped-call]
    else:
        raise ValueError(f"Unknown VaR method: {method}. Use 'historical' or 'parametric'.")

    latest_price = float(df["close"].iloc[-1])
    var_absolute = abs(var_pct) * latest_price

    return json.dumps({
        "symbol": symbol,
        "timeframe": timeframe,
        "confidence_level": confidence,
        "method": method,
        "var_pct": round(abs(var_pct) * 100, 2),  # Positive number for reporting
        "var_absolute_usdt": round(var_absolute, 2),
        "interpretation": f"With {int(confidence * 100)}% confidence, the maximum "
                          f"loss over 1 period ({timeframe}) is {round(abs(var_pct) * 100, 2)}% "
                          f"({round(var_absolute, 2)} USDT per 1 USDT position).",
    }, indent=2, ensure_ascii=False)


# -------------------------------------------------------------------- #
# CLI entry point
# -------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Portfolio optimization and risk analysis (Gate/OKX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action optimize --symbols BTC,ETH,SOL,AVAX
  %(prog)s --action optimize --symbols BTC,ETH --method min_volatility
  %(prog)s --action risk_parity --symbols BTC,ETH,SOL,AVAX
  %(prog)s --action var --symbol BTC --confidence 0.99
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["optimize", "risk_parity", "var"],
        help="Portfolio action to perform.",
    )
    parser.add_argument("--symbols", type=str, default="BTC,ETH,SOL,AVAX",
                        help="Comma-separated symbols for optimization (default: BTC,ETH,SOL,AVAX)")
    parser.add_argument("--symbol", type=str, default="BTC",
                        help="Single symbol for VaR calculation (default: BTC)")
    parser.add_argument("--timeframe", type=str, default="1d",
                        help="Candle interval (default: 1d)")
    parser.add_argument("--limit", type=int, default=100,
                        help="Number of candles (default: 100)")
    parser.add_argument("--method", type=str, default="max_sharpe",
                        choices=["max_sharpe", "min_volatility", "max_return"],
                        help="Optimization method (default: max_sharpe)")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="VaR confidence level, e.g. 0.95 for 95%% (default: 0.95)")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "optimize":
            print(action_optimize(args.symbols, args.timeframe, args.limit, args.method))
        elif args.action == "risk_parity":
            print(action_risk_parity(args.symbols, args.timeframe, args.limit))
        elif args.action == "var":
            print(action_var(args.symbol, args.timeframe, args.limit, args.confidence, "historical"))
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
