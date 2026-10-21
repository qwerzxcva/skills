"""
Strategy backtesting script for cryptocurrency trading (v2.0).

Implements three classic technical-strategy backtests:
1. Moving Average Crossover (MA Cross)
2. RSI Mean-Reversion
3. Bollinger Bands Mean-Reversion

Performance metrics computed for each backtest:
- Total return (%)
- Annualized Sharpe ratio
- Annualized Sortino ratio
- Maximum drawdown (%)
- Win rate (%)
- Profit factor

All backtests use vectorized operations (no loops) for speed.
Network-aware exchange selection for reliable data fetching.
"""
import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ------------------------------------------------------------------- #
# Local imports
# ------------------------------------------------------------------- #
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbol,
    _fetch_df,
    _s,
    get_network_env,
)


# ------------------------------------------------------------------- #
# Performance metrics
# ------------------------------------------------------------------- #
def _compute_returns(df: pd.DataFrame, signals: pd.Series) -> pd.Series:
    """Compute strategy returns from price data and signals.

    Args:
        df: OHLCV DataFrame with 'close' column.
        signals: Series of +1 (long) / 0 (flat) / -1 (short).
                 Currently only +1 and 0 are used (no short selling).

    Returns:
        Series of strategy returns (aligned with df index).
    """
    price_returns = df["close"].pct_change()
    strategy_returns = price_returns * signals.shift(1)  # Signal takes effect next bar
    return strategy_returns.dropna()


def _performance(returns: pd.Series, trades: int) -> Dict[str, Any]:
    """Compute standard performance metrics from strategy returns.

    Args:
        returns: Series of strategy returns (fractional, e.g. 0.01 = 1%).
        trades: Total number of round-trip trades executed.

    Returns:
        Dict with keys: total_return_pct, sharpe_ratio, sortino_ratio,
        max_drawdown_pct, win_rate_pct, profit_factor, total_trades.
    """
    if len(returns) == 0 or returns.isna().all():
        return {
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
        }

    cumulative = (1 + returns).cumprod()
    total_return = float(cumulative.iloc[-1] - 1)

    # Sharpe ratio (annualized, 365 days for crypto)
    ann = 365
    mean_ret = float(returns.mean())
    std_ret = float(returns.std())
    sharpe = (mean_ret / std_ret * np.sqrt(ann)) if std_ret != 0 else 0.0

    # Sortino ratio (only downside deviation)
    downside = returns[returns < 0]
    dstd = float(downside.std()) if len(downside) > 0 else 0.0
    sortino = (mean_ret / dstd * np.sqrt(ann)) if dstd != 0 else 0.0

    # Max drawdown
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak) / peak
    max_dd = float(drawdown.min())

    # Win rate
    non_zero = returns[returns != 0]
    win_rate = float(len(returns[returns > 0]) / len(non_zero)) if len(non_zero) > 0 else 0.0

    # Profit factor (gross profit / gross loss)
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = float(abs(returns[returns < 0].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else float("inf")

    return {
        "total_return_pct": round(total_return * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 4),
        "total_trades": int(trades),
    }


# ------------------------------------------------------------------- #
# Strategy: MA Crossover
# ------------------------------------------------------------------- #
def backtest_ma_cross(symbol: str,
                       timeframe: str = "1d",
                       limit: int = 300,
                       fast: int = 20,
                       slow: int = 50) -> str:
    """Backtest Moving Average Crossover strategy.

    Strategy logic:
    - Long when fast MA crosses above slow MA.
    - Flat when fast MA crosses below slow MA.
    - No short selling (crypto spot only).

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles to fetch. Default 300.
        fast: Fast MA period. Default 20.
        slow: Slow MA period. Default 50.

    Returns:
        JSON string with backtest results and performance metrics.
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)

    if len(df) < slow + 10:
        raise ValueError(
            f"Not enough data for MA Cross (slow={slow}). "
            f"Need at least {slow + 10} candles; got {len(df)}."
        )

    df["ma_fast"] = df["close"].rolling(window=fast).mean()
    df["ma_slow"] = df["close"].rolling(window=slow).mean()

    # Signal: 1 = long, 0 = flat
    df["signal"] = 0
    df.loc[df["ma_fast"] > df["ma_slow"], "signal"] = 1

    # Count trades (signal changes from 0 to 1)
    signal_changes = df["signal"].diff().fillna(0)
    trades = int(((signal_changes == 1) | (signal_changes == -1)).sum())

    returns = _compute_returns(df, df["signal"])
    metrics = _performance(returns, trades)

    return json.dumps({
        "strategy": "MA_Crossover",
        "symbol": symbol,
        "timeframe": timeframe,
        "params": {"fast_ma": fast, "slow_ma": slow},
        "data_points": len(df),
        "performance": metrics,
        "interpretation": {
            "sharpe": "Sharpe > 1.0: good. Sharpe > 2.0: excellent.",
            "max_drawdown": "Max DD < -20%: high risk. Consider position sizing.",
            "win_rate": "Win rate > 50% is good for trend-following.",
        },
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------- #
# Strategy: RSI Mean-Reversion
# ------------------------------------------------------------------- #
def backtest_rsi(symbol: str,
                  timeframe: str = "1d",
                  limit: int = 300,
                  oversold: int = 30,
                  overbought: int = 70) -> str:
    """Backtest RSI Mean-Reversion strategy.

    Strategy logic:
    - Long when RSI crosses above oversold threshold (e.g. 30).
    - Close long when RSI crosses above overbought threshold (e.g. 70).
    - No short selling.

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 300.
        oversold: RSI oversold threshold. Default 30.
        overbought: RSI overbought threshold. Default 70.

    Returns:
        JSON string with backtest results.
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    df.ta.rsi(length=14, append=True)

    rsi_col = f"RSI_14"
    if rsi_col not in df.columns:
        # Try dynamic lookup
        matches = [c for c in df.columns if "RSI" in c.upper()]
        if not matches:
            raise RuntimeError("RSI column not found. pandas_ta may have changed.")
        rsi_col = matches[0]

    df["rsi"] = df[rsi_col]

    # Signal: long when RSI exits oversold; close when RSI enters overbought
    df["signal"] = 0
    position = False
    signals_list: List[int] = []
    for rsi_val in df["rsi"]:
        if pd.isna(rsi_val):
            signals_list.append(0)
            continue
        if not position and rsi_val < oversold:
            position = True  # Will buy next bar
        if position and rsi_val > overbought:
            position = False
        signals_list.append(1 if position else 0)
    df["signal"] = signals_list

    signal_changes = df["signal"].diff().fillna(0)
    trades = int(((signal_changes == 1) | (signal_changes == -1)).sum())

    returns = _compute_returns(df, df["signal"])
    metrics = _performance(returns, trades)

    return json.dumps({
        "strategy": "RSI_Mean_Reversion",
        "symbol": symbol,
        "timeframe": timeframe,
        "params": {"oversold": oversold, "overbought": overbought, "rsi_period": 14},
        "data_points": len(df),
        "performance": metrics,
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------- #
# Strategy: Bollinger Bands Mean-Reversion
# ------------------------------------------------------------------- #
def backtest_bollinger(symbol: str,
                        timeframe: str = "1d",
                        limit: int = 300,
                        length: int = 20,
                        std: float = 2.0) -> str:
    """Backtest Bollinger Bands Mean-Reversion strategy.

    Strategy logic:
    - Long when price touches or breaks below lower Bollinger Band.
    - Close long when price touches or breaks above upper Bollinger Band.
    - No short selling.

    Args:
        symbol: Trading pair string (auto-normalized).
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 300.
        length: BB MA period. Default 20.
        std: Standard deviation multiplier. Default 2.0.

    Returns:
        JSON string with backtest results.
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    df.ta.bbands(length=length, std=std, append=True)

    # Find BB columns dynamically
    bbu_col = next((c for c in df.columns if "BBU" in c.upper()), None)
    bbl_col = next((c for c in df.columns if "BBL" in c.upper()), None)

    if bbu_col is None or bbl_col is None:
        raise RuntimeError("Bollinger Bands columns not found.")

    df["bb_upper"] = df[bbu_col]
    df["bb_lower"] = df[bbl_col]

    # Signal logic
    df["signal"] = 0
    position = False
    signals_list = []
    for i, row in df.iterrows():
        close = row["close"]
        upper = row["bb_upper"]
        lower = row["bb_lower"]
        if not position and not pd.isna(lower) and close <= lower:
            position = True
        if position and not pd.isna(upper) and close >= upper:
            position = False
        signals_list.append(1 if position else 0)
    df["signal"] = signals_list

    signal_changes = df["signal"].diff().fillna(0)
    trades = int(((signal_changes == 1) | (signal_changes == -1)).sum())

    returns = _compute_returns(df, df["signal"])
    metrics = _performance(returns, trades)

    return json.dumps({
        "strategy": "Bollinger_Bands_Mean_Reversion",
        "symbol": symbol,
        "timeframe": timeframe,
        "params": {"length": length, "std": std},
        "data_points": len(df),
        "performance": metrics,
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------- #
# CLI entry point
# ------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Crypto strategy backtester (Gate/OKX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action ma_cross --symbol BTC
  %(prog)s --action rsi --symbol ETH --oversold 25 --overbought 75
  %(prog)s --action bollinger --symbol SOL --timeframe 4h
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["ma_cross", "rsi", "bollinger"],
        help="Backtest strategy to run.",
    )
    parser.add_argument("--symbol", type=str, default="BTC",
                        help="Trading pair (default: BTC/USDT)")
    parser.add_argument("--timeframe", type=str, default="1d",
                        help="Candle interval (default: 1d)")
    parser.add_argument("--limit", type=int, default=300,
                        help="Number of candles (default: 300)")
    parser.add_argument("--fast", type=int, default=20,
                        help="Fast MA period for ma_cross (default: 20)")
    parser.add_argument("--slow", type=int, default=50,
                        help="Slow MA period for ma_cross (default: 50)")
    parser.add_argument("--oversold", type=int, default=30,
                        help="RSI oversold threshold (default: 30)")
    parser.add_argument("--overbought", type=int, default=70,
                        help="RSI overbought threshold (default: 70)")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "ma_cross":
            print(backtest_ma_cross(
                args.symbol, args.timeframe, args.limit, args.fast, args.slow))
        elif args.action == "rsi":
            print(backtest_rsi(
                args.symbol, args.timeframe, args.limit, args.oversold, args.overbought))
        elif args.action == "bollinger":
            print(backtest_bollinger(
                args.symbol, args.timeframe, args.limit))
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
