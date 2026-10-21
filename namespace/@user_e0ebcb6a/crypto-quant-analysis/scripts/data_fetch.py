"""
Multi-source cryptocurrency market data fetching script (v2.0).

Provides CLI access to:
- Multi-source ticker with cross-validation (CoinGecko + exchange)
- Multi-source OHLCV with price deviation checking
- Network-aware exchange selection (Binance/Bybit vs Gate/OKX)
- Available trading markets listing
- CoinGecko ID lookup and metadata

All symbols are auto-normalized to BASE/USDT format.
Data is cross-validated between sources when possible.
"""

import argparse
import json
import logging
import sys
from typing import List, Dict, Any, Optional

import ccxt

# ------------------------------------------------------------------- #
# Local imports
# ------------------------------------------------------------------- #
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbol,
    _normalize_symbols,
    _get_exchange,
    _fetch_df,
    _s,
    get_network_env,
    cg_get_coin_id,
    cg_get_simple_price,
    cg_get_coin_data,
    cg_get_trending,
    cross_validate_price,
    detect_category,
    _get_exchange_ticker_data,
)


# =========================================================================
#  Multi-Source Ticker
# =========================================================================

def action_ticker(symbol: str) -> str:
    """Fetch current price from multiple sources with cross-validation.

    Data sources:
    1. CoinGecko (primary - market aggregation)
    2. Exchange API (Binance/Bybit or Gate/OKX based on network)

    Args:
        symbol: Trading pair string (auto-normalized to BASE/USDT).

    Returns:
        JSON string with validated price, source breakdown, and deviation report.
    """
    symbol = _normalize_symbol(symbol)
    base_ticker = symbol.replace("/USDT", "")

    sources: Dict[str, Optional[float]] = {}
    source_details: Dict[str, Any] = {}
    env = get_network_env()

    # Source 1: CoinGecko
    cg_id = cg_get_coin_id(base_ticker)
    if cg_id:
        cg_price_data = cg_get_simple_price([cg_id])
        if cg_price_data and cg_id in cg_price_data:
            cg_price = cg_price_data[cg_id].get("usd")
            sources["coingecko"] = cg_price
            source_details["coingecko"] = {
                "price_usd": cg_price,
                "change_24h_pct": cg_price_data[cg_id].get("usd_24h_change"),
                "market_cap_usd": cg_price_data[cg_id].get("usd_market_cap"),
                "volume_24h_usd": cg_price_data[cg_id].get("usd_24h_vol"),
            }
        else:
            logger.warning("CoinGecko returned no price for %s", cg_id)
    else:
        logger.warning("CoinGecko ID not found for %s", base_ticker)

    # Source 2: Exchange
    try:
        exchange = _get_exchange()
        if symbol in exchange.markets:
            ticker = exchange.fetch_ticker(symbol)
            exchange_price = ticker.get("last")
            sources[exchange.id] = exchange_price
            source_details[exchange.id] = {
                "price_usd": exchange_price,
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "high_24h": ticker.get("high"),
                "low_24h": ticker.get("low"),
                "change_24h": ticker.get("change"),
                "change_pct_24h": ticker.get("percentage"),
                "volume_24h": ticker.get("baseVolume"),
            }
        else:
            logger.warning("%s not available on %s", symbol, exchange.id)
    except (ccxt.NetworkError, ccxt.ExchangeError, RuntimeError) as e:
        logger.warning("Exchange ticker failed: %s", e)

    # Cross-validate
    validation = cross_validate_price(sources)

    # Category detection
    category_info = detect_category(base_ticker)

    # Environment info
    env_info = {
        "network_environment": env,
        "recommended_exchanges": "Gate/OKX" if env == "china" else "Binance/Bybit",
        "note": ("当前网络环境为中国大陆，已使用Gate/OKX交易所数据。"
                 if env == "china" else "Global network detected. Using Binance/Bybit + CoinGecko."),
    }

    return json.dumps({
        "symbol": symbol,
        "base_ticker": base_ticker,
        "timestamp": ccxt.Exchange.milliseconds(),
        "environment": env_info,
        "validated_price": validation["validated_price"],
        "cross_validation": {
            "is_reliable": validation["is_reliable"],
            "max_deviation_pct": validation["max_deviation_pct"],
            "source_count": validation["source_count"],
            "deviations": validation["deviations"],
            "warning": validation["warning"],
        },
        "sources": source_details,
        "category": category_info,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Multi-Ticker Batch Query
# =========================================================================

def action_multi_tickers(symbols_raw: str) -> str:
    """Fetch ticker data for multiple symbols with cross-validation.

    Args:
        symbols_raw: Comma-separated, e.g. "BTC,ETH,SOL".

    Returns:
        JSON array with ticker data for each valid symbol.
    """
    symbols: List[str] = _normalize_symbols(symbols_raw)
    env = get_network_env()

    # Try CoinGecko batch first (efficient)
    cg_ids: Dict[str, str] = {}
    for sym in symbols:
        ticker = sym.replace("/USDT", "").upper()
        cg_id = cg_get_coin_id(ticker)
        if cg_id:
            cg_ids[cg_id] = sym

    cg_prices: Dict[str, Any] = {}
    if cg_ids:
        cg_data = cg_get_simple_price(list(cg_ids.keys()))
        if cg_data:
            for cg_id, sym in cg_ids.items():
                if cg_id in cg_data:
                    cg_prices[sym] = cg_data[cg_id]

    # Exchange batch
    exchange = _get_exchange()
    results: List[Dict[str, Any]] = []

    for sym in symbols:
        entry: Dict[str, Any] = {"symbol": sym, "exchange": exchange.id}

        # CoinGecko price
        cg_entry = cg_prices.get(sym, {})
        cg_price = cg_entry.get("usd")

        # Exchange price
        exchange_price = None
        if sym in exchange.markets:
            try:
                t = exchange.fetch_ticker(sym)
                exchange_price = t.get("last")
                entry["change_pct_24h"] = t.get("percentage")
                entry["volume_24h"] = t.get("baseVolume")
            except ccxt.NetworkError:
                pass

        # Cross-validate
        price_sources: Dict[str, Optional[float]] = {}
        if cg_price is not None:
            price_sources["coingecko"] = cg_price
        if exchange_price is not None:
            price_sources[exchange.id] = exchange_price

        validation = cross_validate_price(price_sources)
        entry["validated_price"] = validation["validated_price"]
        entry["deviation_pct"] = validation["max_deviation_pct"]
        entry["is_reliable"] = validation["is_reliable"]
        entry["warning"] = validation["warning"] if validation["warning"] else None
        entry["category"] = detect_category(sym.replace("/USDT", "").upper())["category"]

        results.append(entry)

    if not results:
        raise ValueError(f"No valid symbols from: {symbols_raw}")

    return json.dumps({
        "environment": {
            "network": env,
            "recommended_exchanges": "Gate/OKX" if env == "china" else "Binance/Bybit",
            "note": ("当前为中国大陆网络环境，使用Gate/OKX+CoinGecko交叉核对。"
                     if env == "china" else "Global network. Using Binance/Bybit + CoinGecko."),
        },
        "count": len(results),
        "results": results,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  OHLCV Historical Data
# =========================================================================

def action_ohlcv(symbol: str,
                  timeframe: str = "1d",
                  limit: int = 200,
                  output: Optional[str] = None) -> str:
    """Fetch historical OHLCV candlestick data.

    Enriched with network environment info and symbol metadata.

    Args:
        symbol: Trading pair (auto-normalized).
        timeframe: Candle interval (1d, 4h, 1h, etc.). Default "1d".
        limit: Number of candles. Default 200.
        output: Optional file path for JSON output.

    Returns:
        JSON string with OHLCV data and metadata.
    """
    symbol = _normalize_symbol(symbol)
    df = _fetch_df(symbol, timeframe, limit)
    env = get_network_env()
    exchange = _get_exchange()

    data = []
    for _, row in df.iterrows():
        data.append({
            "timestamp": int(row["timestamp"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    result = json.dumps({
        "symbol": symbol,
        "exchange": exchange.id,
        "environment": {
            "network": env,
            "note": ("国内网络·使用Gate/OKX" if env == "china" else "Global network·Binance/Bybit"),
        },
        "timeframe": timeframe,
        "limit": limit,
        "count": len(data),
        "data": data,
    }, indent=2, ensure_ascii=False)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(result)
        logger.info("OHLCV saved to %s", output)
        return json.dumps({"status": "saved", "file": output, "rows": len(data)})
    return result


# =========================================================================
#  CoinGecko Metadata / Trending
# =========================================================================

def action_coin_info(symbol: str) -> str:
    """Fetch detailed CoinGecko metadata for a coin.

    Includes: description, categories, market data, community stats,
    developer activity, and links.

    Args:
        symbol: Ticker (e.g. "BTC", "ETH").

    Returns:
        JSON with comprehensive coin metadata.
    """
    base = symbol.upper().replace("/USDT", "").strip()
    coin_id = cg_get_coin_id(base)

    if not coin_id:
        # Even without CoinGecko ID, try to provide exchange data
        symbol = _normalize_symbol(base)
        exchange_fallback = _get_exchange_ticker_data(symbol)
        if exchange_fallback.get("status") == "success":
            return json.dumps({
                "symbol": base,
                "status": "partial",
                "message": (
                    f"'{base}' is not in our CoinGecko database, but exchange data is available. "
                    "Basic price and volume metrics provided. For deeper analysis, "
                    "the token may need to be added to our mapping."
                ),
                "exchange_data": exchange_fallback,
            }, indent=2, ensure_ascii=False)
        return json.dumps({
            "error": f"'{base}' not found in our database of 200+ tokens. "
                     f"Please verify the symbol (e.g., 'BTC' not 'Bitcoin'). "
                     f"If the token is new or niche, it may not be on supported exchanges yet.",
        }, indent=2, ensure_ascii=False)

    data = cg_get_coin_data(coin_id)
    if not data:
        return json.dumps({
            "error": f"CoinGecko API is currently unreachable for {base}. "
                     f"This is common in China network environments. "
                     f"Use exchange data (price/volume) instead."
        }, indent=2)

    market = data.get("market_data", {})
    community = data.get("community_data", {})
    dev = data.get("developer_data", {})

    return json.dumps({
        "symbol": base,
        "coingecko_id": coin_id,
        "name": data.get("name"),
        "categories": data.get("categories", []),
        "description": (data.get("description", {}).get("en", "")[:500] + "..."
                        if data.get("description", {}).get("en") else ""),
        "market_data": {
            "current_price_usd": market.get("current_price", {}).get("usd"),
            "market_cap_usd": market.get("market_cap", {}).get("usd"),
            "market_cap_rank": market.get("market_cap_rank"),
            "total_volume_usd": market.get("total_volume", {}).get("usd"),
            "high_24h_usd": market.get("high_24h", {}).get("usd"),
            "low_24h_usd": market.get("low_24h", {}).get("usd"),
            "price_change_pct_24h": market.get("price_change_percentage_24h"),
            "price_change_pct_7d": market.get("price_change_percentage_7d"),
            "price_change_pct_30d": market.get("price_change_percentage_30d"),
            "circulating_supply": market.get("circulating_supply"),
            "total_supply": market.get("total_supply"),
            "max_supply": market.get("max_supply"),
            "ath_usd": market.get("ath", {}).get("usd"),
            "ath_date": market.get("ath_date", {}).get("usd"),
            "atl_usd": market.get("atl", {}).get("usd"),
        },
        "community": {
            "twitter_followers": community.get("twitter_followers"),
            "reddit_subscribers": community.get("reddit_subscribers"),
            "telegram_channel_count": community.get("telegram_channel_user_count"),
        },
        "developer": {
            "stars": dev.get("stars"),
            "forks": dev.get("forks"),
            "subscribers": dev.get("subscribers"),
            "total_issues": dev.get("total_issues"),
            "closed_issues": dev.get("closed_issues"),
            "commit_count_4w": dev.get("commit_count_4_weeks"),
        },
        "sentiment": {
            "upvotes_pct": data.get("sentiment_votes_up_percentage"),
            "downvotes_pct": data.get("sentiment_votes_down_percentage"),
        },
        "links": {
            "homepage": (data.get("links", {}).get("homepage", []) or [None])[0],
            "twitter": data.get("links", {}).get("twitter_screen_name"),
        },
    }, indent=2, ensure_ascii=False)


def action_trending() -> str:
    """Fetch trending coins from CoinGecko.

    Returns:
        JSON with trending coins (top 7), including market data.
    """
    data = cg_get_trending()
    if not data:
        return json.dumps({"error": "Failed to fetch trending data from CoinGecko."}, indent=2)

    coins = data.get("coins", [])
    results = []
    for item in coins[:15]:
        coin = item.get("item", {})
        results.append({
            "name": coin.get("name"),
            "symbol": (coin.get("symbol", "")).upper(),
            "coingecko_id": coin.get("id"),
            "market_cap_rank": coin.get("market_cap_rank"),
            "thumb": coin.get("thumb"),
            "score": coin.get("score"),
        })

    return json.dumps({
        "source": "CoinGecko Trending",
        "count": len(results),
        "coins": results,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Network Environment Check
# =========================================================================

def action_network_check() -> str:
    """Check current network environment and recommend data sources.

    Returns:
        JSON with network status and source recommendations.
    """
    env = get_network_env()
    primary, fallback = ("gate", "okx") if env == "china" else ("binance", "bybit")

    recommendations = {
        "china": {
            "status": "中国大陆网络环境",
            "primary_exchange": "Gate",
            "fallback_exchange": "OKX",
            "coingecko_accessible": True,
            "note": "Binance/Bybit 可能被屏蔽，已自动切换为 Gate/OKX。数据通过 CoinGecko + Gate/OKX 交叉核对。",
        },
        "global": {
            "status": "国际网络环境",
            "primary_exchange": "Binance",
            "fallback_exchange": "Bybit",
            "coingecko_accessible": True,
            "note": "使用 Binance + CoinGecko 双源数据交叉核对。",
        },
    }

    return json.dumps({
        "environment": env,
        "recommendation": recommendations.get(env, recommendations["global"]),
        "data_sources": ["CoinGecko", primary.capitalize(), f"{fallback.capitalize()} (fallback)"],
        "cross_validation": "enabled",
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  CLI Entry Point
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Multi-source crypto market data fetcher (CoinGecko + Exchanges)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action ticker --symbol BTC
  %(prog)s --action multi_tickers --symbols BTC,ETH,SOL
  %(prog)s --action ohlcv --symbol ETH --timeframe 4h --limit 100
  %(prog)s --action coin_info --symbol UNI
  %(prog)s --action trending
  %(prog)s --action network_check
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["ticker", "multi_tickers", "ohlcv", "coin_info", "trending", "network_check"],
        help="Action to perform.",
    )
    parser.add_argument("--symbol", type=str, default="BTC",
                        help="Single symbol, e.g. BTC, ETH/USDT (default: BTC)")
    parser.add_argument("--symbols", type=str, default="BTC,ETH,SOL",
                        help="Comma-separated symbols (default: BTC,ETH,SOL)")
    parser.add_argument("--timeframe", type=str, default="1d",
                        help="Candle timeframe: 1d, 4h, 1h (default: 1d)")
    parser.add_argument("--limit", type=int, default=200,
                        help="Number of candles (default: 200)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path for OHLCV (JSON).")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "ticker":
            print(action_ticker(args.symbol))
        elif args.action == "multi_tickers":
            print(action_multi_tickers(args.symbols))
        elif args.action == "ohlcv":
            print(action_ohlcv(args.symbol, args.timeframe, args.limit, args.output))
        elif args.action == "coin_info":
            print(action_coin_info(args.symbol))
        elif args.action == "trending":
            print(action_trending())
        elif args.action == "network_check":
            print(action_network_check())
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
