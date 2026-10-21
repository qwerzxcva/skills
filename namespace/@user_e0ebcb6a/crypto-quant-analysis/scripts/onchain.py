"""
On-chain data analysis script for cryptocurrency markets (v2.0).

Provides blockchain-level metrics and protocol data through:
1. DeFiLlama API - TVL, fees, revenue (free, no API key)
2. CoinGecko - metadata, exchange listings (complementary)
3. Blockchain explorer APIs (optional, API key needed for full access)

All endpoints gracefully degrade when data sources are unavailable.
Network-unavailable services are skipped with clear status messages.

Primary data dimensions:
- Protocol TVL by chain with historical trends
- Protocol fees and revenue (daily, total, cumulative)
- Chain-level ecosystem metrics (TVL, active protocols, dominance)
- Cross-chain TVL comparison and ranking
"""

import argparse
import json
import logging
import sys
import socket
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import numpy as np

# ------------------------------------------------------------------- #
# Local imports
# ------------------------------------------------------------------- #
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbol,
    _s,
    get_network_env,
    dl_get_protocol_tvl,
    dl_get_protocol_fees,
    dl_get_protocol_slug,
    dl_get_chain_tvl,
    detect_category,
    cg_get_coin_id,
    cg_get_coin_data,
)

DEFILLAMA_BASE: str = "https://api.llama.fi"


# =========================================================================
#  DeFiLlama API Helpers
# =========================================================================

def _dl_request(endpoint: str) -> Optional[Any]:
    """Make a request to DeFiLlama API."""
    url = f"{DEFILLAMA_BASE}{endpoint}"
    try:
        req = Request(url, headers={"User-Agent": "CryptoQuant/2.0", "Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, socket.timeout, json.JSONDecodeError, HTTPError) as e:
        logger.warning("DeFiLlama request failed: %s", e)
        return None


# =========================================================================
#  Protocol TVL Analysis
# =========================================================================

def action_protocol_tvl(symbol: str) -> str:
    """Get detailed TVL breakdown for a DeFi protocol.

    When the token is a DeFi governance/utility token, maps it to
    its underlying protocol on DeFiLlama and fetches:
    - Total TVL and chain-level breakdown
    - Historical TVL changes (24h, 7d, 30d)
    - Token holdings within the protocol
    - Protocol category and description

    Args:
        symbol: Trading pair (e.g. "UNI", "AAVE/USDT"). Auto-normalized.

    Returns:
        JSON with comprehensive TVL data.
    """
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()

    slug = dl_get_protocol_slug(base)
    if not slug:
        # Try searching by name
        coin_id = cg_get_coin_id(base)
        if coin_id:
            coin_data = cg_get_coin_data(coin_id)
            if coin_data:
                name = coin_data.get("name", "").lower().replace(" ", "-")
                # Try a few slug variants
                for candidate in [name, name + "-finance", name + "-protocol", name + "-exchange"]:
                    test = dl_get_protocol_tvl(candidate)
                    if test and test.get("tvl", 0) > 0:
                        slug = candidate
                        break

    if not slug:
        return json.dumps({
            "symbol": symbol,
            "status": "not_found",
            "message": f"No DeFiLlama protocol found for {base}. "
                       f"This token may not be a protocol governance token, "
                       f"or it may not be tracked by DeFiLlama.",
        }, indent=2, ensure_ascii=False)

    # Fetch protocol data
    protocol = dl_get_protocol_tvl(slug)
    if not protocol:
        return json.dumps({
            "symbol": symbol,
            "slug": slug,
            "status": "fetch_failed",
            "message": f"Failed to fetch TVL data for protocol '{slug}'.",
        }, indent=2, ensure_ascii=False)

    # Build response
    tvl = protocol.get("tvl", 0)
    chain_tvls = protocol.get("chainTvls", {})

    # Sort chains by TVL
    sorted_chains = sorted(
        chain_tvls.items(),
        key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0,
        reverse=True
    )[:10]

    return json.dumps({
        "symbol": symbol,
        "protocol_slug": slug,
        "protocol_name": protocol.get("name"),
        "protocol_category": protocol.get("category"),
        "description": protocol.get("description", "")[:300],
        "url": protocol.get("url"),
        "total_tvl_usd": tvl,
        "tvl_changes": {
            "change_1d_pct": protocol.get("change_1d"),
            "change_7d_pct": protocol.get("change_7d"),
            "change_1m_pct": protocol.get("change_1m"),
        },
        "tvl_by_chain": [
            {"chain": chain, "tvl_usd": float(val) if isinstance(val, (int, float)) else 0}
            for chain, val in sorted_chains
        ],
        "chain_count": len(chain_tvls),
        "dominant_chain": sorted_chains[0][0] if sorted_chains else "N/A",
        "token_details": {
            "tokens_in_tvl": protocol.get("tokensInUsd", []),
            "tokens_excluded": protocol.get("tokensExcludedInUsd", []),
        },
        "methodology": protocol.get("methodology", ""),
        "data_source": "DeFiLlama",
        "data_timestamp": int(np.floor(float(protocol.get("gecko_id", "0") or "0"))),
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Protocol Fees & Revenue
# =========================================================================

def action_protocol_fees(symbol: str) -> str:
    """Get fee and revenue data for a protocol.

    DeFiLlama tracks multiple fee types:
    - dailyFees: Total fees paid by users (protocol revenue + token holder rev)
    - dailyRevenue: Fees that go to the protocol treasury
    - totalFees: Cumulative fees since inception
    - totalRevenue: Cumulative revenue since inception

    Args:
        symbol: Trading pair (e.g. "UNI", "CRV/USDT").

    Returns:
        JSON with fee breakdown and annualized estimates.
    """
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()

    slug = dl_get_protocol_slug(base)
    if not slug:
        return json.dumps({
            "symbol": symbol, "status": "not_found",
            "message": f"No DeFiLlama protocol found for {base}.",
        }, indent=2, ensure_ascii=False)

    # Fetch multiple fee types
    fee_types = ["dailyFees", "dailyRevenue", "totalFees", "totalRevenue"]
    results: Dict[str, Any] = {"symbol": symbol, "protocol_slug": slug}

    for fee_type in fee_types:
        data = dl_get_protocol_fees(slug, fee_type)
        if data:
            chart = data.get("totalDataChart", [])
            if chart and isinstance(chart, list):
                # Extract recent data points
                values = [pt[1] for pt in chart if len(pt) > 1 and pt[1] is not None]
                if values:
                    latest = values[-1]
                    results[fee_type] = {
                        "latest": round(float(latest), 2),
                        "avg_30d": round(float(np.mean(values[-30:])) if len(values) >= 30 else float(np.mean(values)), 2),
                        "trend": "up" if len(values) >= 7 and values[-1] > values[0] else "down",
                        "data_points": len(values),
                    }

    # Compute derived metrics
    daily_fees = (results.get("dailyFees", {}).get("latest") or
                  results.get("dailyFees", {}).get("avg_30d"))
    daily_revenue = (results.get("dailyRevenue", {}).get("latest") or
                     results.get("dailyRevenue", {}).get("avg_30d"))

    if daily_fees:
        results["annualized_fees_usd"] = round(float(daily_fees) * 365, 2)
    if daily_revenue:
        results["annualized_revenue_usd"] = round(float(daily_revenue) * 365, 2)
    if daily_fees and daily_fees > 0 and daily_revenue:
        results["revenue_share_pct"] = round(float(daily_revenue) / float(daily_fees) * 100, 2)

    # Protocol metadata
    protocol = dl_get_protocol_tvl(slug)
    if protocol:
        results["protocol_name"] = protocol.get("name")
        results["total_tvl_usd"] = protocol.get("tvl")
        if results.get("total_tvl_usd") and results.get("annualized_fees_usd"):
            results["fees_to_tvl_ratio"] = round(
                results["annualized_fees_usd"] / results["total_tvl_usd"], 4
            )

    results["data_source"] = "DeFiLlama"

    return json.dumps(results, indent=2, ensure_ascii=False)


# =========================================================================
#  Chain-Level Metrics
# =========================================================================

def action_chain_stats(symbol: Optional[str] = None,
                       chain: Optional[str] = None) -> str:
    """Get blockchain ecosystem stats.

    Can be called with a token symbol (auto-maps to its chain) or
    directly with a chain name.

    Args:
        symbol: Token ticker to infer chain from.
        chain: Direct chain name (e.g. "ethereum", "solana").

    Returns:
        JSON with chain TVL, protocol count, and dominance.
    """
    if symbol and not chain:
        symbol = _normalize_symbol(symbol)
        base = symbol.replace("/USDT", "").upper()
        CHAIN_MAP: Dict[str, str] = {
            "ETH": "ethereum", "SOL": "solana", "BNB": "bsc", "AVAX": "avalanche",
            "MATIC": "polygon", "POL": "polygon", "ADA": "cardano", "DOT": "polkadot",
            "NEAR": "near", "FTM": "fantom", "ATOM": "cosmos", "TRX": "tron",
            "APT": "aptos", "SUI": "sui", "SEI": "sei", "ALGO": "algorand",
        }
        chain = CHAIN_MAP.get(base, base.lower())

    if not chain:
        return json.dumps({"error": "No chain specified."}, indent=2)

    # Fetch all chains data
    chains_data = _dl_request("/v2/chains")
    if not chains_data:
        return json.dumps({"error": "Failed to fetch DeFiLlama chain data."}, indent=2)

    total_tvl = sum(float(c.get("tvl", 0)) for c in chains_data)

    # Find the target chain
    target = None
    for c in chains_data:
        if c.get("name", "").lower() == chain.lower():
            target = c
            break

    if not target:
        # Try partial match
        for c in chains_data:
            if chain.lower() in c.get("name", "").lower():
                target = c
                break

    if not target:
        return json.dumps({
            "chain": chain,
            "status": "not_found",
            "available_chains": [c.get("name") for c in chains_data[:20]],
        }, indent=2, ensure_ascii=False)

    chain_tvl = float(target.get("tvl", 0))
    dominance = chain_tvl / total_tvl * 100 if total_tvl > 0 else 0

    return json.dumps({
        "chain": target.get("name"),
        "gecko_id": target.get("gecko_id"),
        "chain_id": target.get("chainId"),
        "tvl_usd": chain_tvl,
        "tvl_dominance_pct": round(dominance, 2),
        "protocol_count": target.get("protocols", 0),
        "rank": target.get("tvl", 0),
        "total_defi_tvl_usd": total_tvl,
        "data_source": "DeFiLlama",
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Protocol Ranking
# =========================================================================

def action_protocol_ranking(limit: int = 20) -> str:
    """Get top protocols ranked by TVL.

    Args:
        limit: Number of top protocols to return. Default 20.

    Returns:
        JSON array of top protocols with TVL and changes.
    """
    protocols = _dl_request("/protocols")
    if not protocols:
        return json.dumps({"error": "Failed to fetch protocol list."}, indent=2)

    # Filter and sort by TVL
    valid = [p for p in protocols if isinstance(p, dict) and p.get("tvl", 0) > 0]
    sorted_protocols = sorted(valid, key=lambda x: float(x.get("tvl", 0)), reverse=True)[:limit]

    results = []
    for i, p in enumerate(sorted_protocols, 1):
        results.append({
            "rank": i,
            "name": p.get("name"),
            "slug": p.get("slug"),
            "category": p.get("category"),
            "tvl_usd": p.get("tvl"),
            "change_1d_pct": p.get("change_1d"),
            "change_7d_pct": p.get("change_7d"),
            "chain": p.get("chain"),
        })

    return json.dumps({
        "type": "protocol_ranking",
        "count": len(results),
        "data_source": "DeFiLlama",
        "protocols": results,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Chain Ranking
# =========================================================================

def action_chain_ranking(limit: int = 15) -> str:
    """Get top chains ranked by TVL.

    Args:
        limit: Number of chains. Default 15.

    Returns:
        JSON array of chains with TVL and protocol counts.
    """
    chains = _dl_request("/v2/chains")
    if not chains:
        return json.dumps({"error": "Failed to fetch chain data."}, indent=2)

    total_tvl = sum(float(c.get("tvl", 0)) for c in chains)
    sorted_chains = sorted(chains, key=lambda x: float(x.get("tvl", 0)), reverse=True)[:limit]

    results = []
    for i, c in enumerate(sorted_chains, 1):
        chain_tvl = float(c.get("tvl", 0))
        results.append({
            "rank": i,
            "name": c.get("name"),
            "tvl_usd": chain_tvl,
            "dominance_pct": round(chain_tvl / total_tvl * 100, 2) if total_tvl > 0 else 0,
            "protocols": c.get("protocols", 0),
            "change_1d_pct": c.get("change_1d"),
            "change_7d_pct": c.get("change_7d"),
        })

    return json.dumps({
        "type": "chain_ranking",
        "count": len(results),
        "total_defi_tvl_usd": total_tvl,
        "data_source": "DeFiLlama",
        "chains": results,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  Network-Adaptive Health Check
# =========================================================================

def action_onchain_status() -> str:
    """Check which on-chain data sources are accessible from current network.

    Tests DeFiLlama API and CoinGecko API availability.
    Returns a clear status report with recommendations.
    """
    env = get_network_env()

    # Test DeFiLlama
    dl_ok = _dl_request("/protocols") is not None

    # Test CoinGecko
    from utils import cg_get_coin_id
    cg_ok = cg_get_coin_id("BTC") is not None

    services = {
        "defillama_tvl": {"available": dl_ok, "description": "Protocol & chain TVL data"},
        "defillama_fees": {"available": dl_ok, "description": "Protocol fee & revenue data"},
        "coingecko": {"available": cg_ok, "description": "Market data & metadata"},
    }

    available_count = sum(1 for s in services.values() if s["available"])
    total_count = len(services)

    return json.dumps({
        "network_environment": env,
        "timestamp": int(__import__("time").time()),
        "services": services,
        "summary": {
            "available": available_count,
            "total": total_count,
            "status": "full" if available_count == total_count else (
                "partial" if available_count > 0 else "none"),
        },
        "note": (
            "当前为国内网络环境，部分链上数据API可能受限。DeFiLlama API在国内通常可用。"
            if env == "china" else
            "Global network. All on-chain data services should be accessible."
        ),
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  CLI Entry Point
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="On-chain data analysis (DeFiLlama + explorers)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action protocol_tvl --symbol UNI
  %(prog)s --action protocol_fees --symbol AAVE
  %(prog)s --action chain_stats --symbol ETH
  %(prog)s --action chain_stats --chain ethereum
  %(prog)s --action protocol_ranking --limit 10
  %(prog)s --action chain_ranking
  %(prog)s --action status
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["protocol_tvl", "protocol_fees", "chain_stats",
                 "protocol_ranking", "chain_ranking", "status"],
        help="On-chain analysis action.",
    )
    parser.add_argument("--symbol", type=str, default=None,
                        help="Token symbol (e.g. UNI, ETH).")
    parser.add_argument("--chain", type=str, default=None,
                        help="Chain name (e.g. ethereum, solana).")
    parser.add_argument("--limit", type=int, default=20,
                        help="Result limit for rankings (default: 20).")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "protocol_tvl":
            if not args.symbol:
                parser.error("--symbol is required for protocol_tvl")
            print(action_protocol_tvl(args.symbol))
        elif args.action == "protocol_fees":
            if not args.symbol:
                parser.error("--symbol is required for protocol_fees")
            print(action_protocol_fees(args.symbol))
        elif args.action == "chain_stats":
            print(action_chain_stats(args.symbol, args.chain))
        elif args.action == "protocol_ranking":
            print(action_protocol_ranking(args.limit))
        elif args.action == "chain_ranking":
            print(action_chain_ranking(args.limit))
        elif args.action == "status":
            print(action_onchain_status())
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
