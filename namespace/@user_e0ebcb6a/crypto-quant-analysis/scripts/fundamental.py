"""
Category-specific fundamental analysis for cryptocurrency tokens (v2.0).

Provides differentiated analysis based on token category:
- DeFi: TVL, TVL/MC ratio, protocol revenue, fee generation, user growth
- Meme: Social volume, holder distribution, narrative strength, listing breadth
- L1/L2: Ecosystem TVL, active addresses, developer activity, fee generation
- Gaming: Active players, in-game volume, NFT floor prices
- AI: GitHub activity, narrative correlation, partnership ecosystem
- Infrastructure: Integration count, network revenue, developer activity
- Store of Value (BTC): Stock-to-flow, hash rate, realized cap, illiquid supply

Data sources: CoinGecko, DeFiLlama, exchange APIs.
All results are JSON-serializable for downstream consumption.
"""

import argparse
import json
import logging
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import numpy as np
import pandas as pd

# ------------------------------------------------------------------- #
# Local imports
# ------------------------------------------------------------------- #
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from utils import (  # noqa: E402
    logger,
    _normalize_symbol,
    _s,
    detect_category,
    get_category_analysis_dimensions,
    cg_get_coin_id,
    cg_get_coin_data,
    cg_get_market_chart,
    cg_get_simple_price,
    dl_get_protocol_tvl,
    dl_get_protocol_fees,
    dl_get_protocol_slug,
    dl_get_chain_tvl,
    get_network_env,
    _get_exchange_ticker_data,
    COINGECKO_ID_MAP,
)

# ------------------------------------------------------------------- #
# BaseCoinGecko market chart fetch for MC/TVL ratio calculations
# ------------------------------------------------------------------- #

def _get_market_chart(ticker: str, days: str = "90") -> Optional[Dict[str, Any]]:
    """Fetch CoinGecko market chart (prices, market caps, volumes)."""
    coin_id = cg_get_coin_id(ticker.upper().replace("/USDT", ""))
    if not coin_id:
        return None
    return cg_get_market_chart(coin_id, days)


def _get_current_market_data(ticker: str) -> Dict[str, Optional[float]]:
    """Get current market data (price, MC, volume) from CoinGecko, with exchange fallback."""
    base = ticker.upper().replace("/USDT", "").strip()
    coin_id = cg_get_coin_id(base)
    if coin_id:
        data = cg_get_simple_price([coin_id])
        if data and coin_id in data:
            return {
                "price": data[coin_id].get("usd"),
                "market_cap": data[coin_id].get("usd_market_cap"),
                "volume_24h": data[coin_id].get("usd_24h_vol"),
                "status": "success",
                "source": "coingecko",
                "message": "Market data retrieved from CoinGecko.",
            }

    # Fallback: use exchange ticker data for any listed token
    symbol = _normalize_symbol(base)
    exchange_data = _get_exchange_ticker_data(symbol)
    if exchange_data.get("status") == "success":
        return {
            "price": exchange_data.get("price"),
            "market_cap": None,  # Exchange tickers don't provide market cap
            "volume_24h": exchange_data.get("volume_24h"),
            "status": "partial",
            "source": exchange_data.get("source", "exchange"),
            "message": (
                f"CoinGecko unavailable for {base}. "
                f"Using {exchange_data.get('source')} exchange data. "
                f"Market cap not available from exchange tickers. "
                f"Basic price and volume data provided."
            ),
        }

    return {
        "price": None, "market_cap": None, "volume_24h": None,
        "status": "failed",
        "source": "none",
        "message": (
            f"Unable to retrieve market data for {base}. "
            "CoinGecko API is unreachable (likely due to China network restrictions) "
            "and the token is not found on supported exchanges. "
            "Please verify the symbol or try again with a different network."
        ),
    }


# =========================================================================
#  DeFi Fundamental Analysis
# =========================================================================

def _analyze_defi(ticker: str) -> Dict[str, Any]:
    """Comprehensive DeFi token fundamental analysis.

    Metrics: TVL, TVL/MC ratio, protocol revenue, annualized fees,
    user growth trend, treasury value, competitor comparison.
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "defi", "ticker": base}

    # 1. Get TVL from DeFiLlama
    slug = dl_get_protocol_slug(base)
    tvl_data = dl_get_protocol_tvl(slug) if slug else None

    if tvl_data:
        tvl = tvl_data.get("tvl", 0)
        result["tvl_usd"] = tvl
        result["tvl_by_chain"] = {
            chain: float(val) for chain, val in sorted(
                tvl_data.get("chainTvls", {}).items(),
                key=lambda x: float(x[1]) if isinstance(x[1], (int, float)) else 0,
                reverse=True
            )[:5]
        }
        result["tvl_change_24h"] = tvl_data.get("change_1d")
        result["tvl_change_7d"] = tvl_data.get("change_7d")
        result["tvl_change_30d"] = tvl_data.get("change_1m")
    else:
        result["tvl_usd"] = None
        result["tvl_note"] = f"TVL data not available for {base} on DeFiLlama."

    # 2. Get market cap and compute TVL/MC ratio
    market_data = _get_current_market_data(base)
    mc = market_data.get("market_cap")
    result["market_cap_usd"] = mc

    if tvl_data and mc and mc > 0:
        tvl = tvl_data.get("tvl", 0)
        ratio = tvl / mc
        result["tvl_mc_ratio"] = round(ratio, 4)
        result["tvl_mc_interpretation"] = (
            "TVL/MC > 1.0: Protocol is potentially undervalued relative to TVL. "
            "TVL/MC 0.5-1.0: Fair valuation zone. "
            "TVL/MC < 0.3: Market cap exceeds TVL, potentially overvalued unless strong revenue."
        )
        if ratio > 2.0:
            result["tvl_mc_signal"] = "strongly_undervalued"
        elif ratio > 1.0:
            result["tvl_mc_signal"] = "undervalued"
        elif ratio > 0.5:
            result["tvl_mc_signal"] = "fair_value"
        elif ratio > 0.3:
            result["tvl_mc_signal"] = "slightly_overvalued"
        else:
            result["tvl_mc_signal"] = "overvalued"

    # 3. Protocol fees and revenue
    if slug:
        fees_data = dl_get_protocol_fees(slug, "dailyFees")
        if fees_data:
            total = fees_data.get("totalDataChart", {})
            if total and isinstance(total, list) and len(total) > 0:
                latest_fees = total[-1][1] if len(total[-1]) > 1 else 0
                result["daily_fees_usd"] = round(float(latest_fees), 2)
                # Estimate annualized fees
                if len(total) >= 30:
                    recent_30 = [t[1] for t in total[-30:] if len(t) > 1 and t[1] is not None]
                    if recent_30:
                        avg_daily = sum(recent_30) / len(recent_30)
                        result["annualized_fees_usd"] = round(float(avg_daily * 365), 2)
                        result["fees_trend"] = "increasing" if recent_30[-1] > recent_30[0] else "decreasing"

        revenue_data = dl_get_protocol_fees(slug, "dailyRevenue")
        if revenue_data:
            rev_total = revenue_data.get("totalDataChart", {})
            if rev_total and isinstance(rev_total, list) and len(rev_total) > 0:
                latest_rev = rev_total[-1][1] if len(rev_total[-1]) > 1 else 0
                result["daily_revenue_usd"] = round(float(latest_rev), 2)
                if len(rev_total) >= 30:
                    recent_30 = [t[1] for t in rev_total[-30:] if len(t) > 1 and t[1] is not None]
                    if recent_30:
                        avg_daily = sum(recent_30) / len(recent_30)
                        result["annualized_revenue_usd"] = round(float(avg_daily * 365), 2)

    # 4. Scoring
    score = 0
    score_details: List[str] = []

    tvl_mc_ratio = result.get("tvl_mc_ratio")
    if tvl_mc_ratio is not None:
        if tvl_mc_ratio > 1.0:
            score += 3
            score_details.append(f"TVL/MC ratio {tvl_mc_ratio:.2f}: strong (+3)")
        elif tvl_mc_ratio > 0.5:
            score += 2
            score_details.append(f"TVL/MC ratio {tvl_mc_ratio:.2f}: fair (+2)")
        elif tvl_mc_ratio > 0.3:
            score += 1
            score_details.append(f"TVL/MC ratio {tvl_mc_ratio:.2f}: moderate (+1)")
        else:
            score_details.append(f"TVL/MC ratio {tvl_mc_ratio:.2f}: low (0)")

    tvl_change = result.get("tvl_change_7d")
    if tvl_change is not None:
        if tvl_change > 0.1:
            score += 2
            score_details.append(f"TVL growth +{tvl_change*100:.1f}% 7d (+2)")
        elif tvl_change > 0:
            score += 1
            score_details.append(f"TVL growth +{tvl_change*100:.1f}% 7d (+1)")
        elif tvl_change < -0.2:
            score -= 1
            score_details.append(f"TVL decline {tvl_change*100:.1f}% 7d (-1)")

    if result.get("annualized_fees_usd") and result.get("market_cap_usd"):
        mc_val = result["market_cap_usd"]
        fee_val = result["annualized_fees_usd"]
        if mc_val and mc_val > 0:
            fee_ratio = fee_val / mc_val
            if fee_ratio > 1.0:
                score += 3
                score_details.append(f"Fees/MC ratio {fee_ratio:.2f}: excellent (+3)")
            elif fee_ratio > 0.1:
                score += 1
                score_details.append(f"Fees/MC ratio {fee_ratio:.2f}: good (+1)")

    result["fundamental_score"] = max(0, min(10, score))
    result["fundamental_score_details"] = score_details
    result["fundamental_rating"] = (
        "excellent" if score >= 7 else "good" if score >= 5 else
        "fair" if score >= 3 else "weak"
    )

    return result


# =========================================================================
#  Meme Coin Analysis
# =========================================================================

def _analyze_meme(ticker: str) -> Dict[str, Any]:
    """Meme coin fundamental and narrative analysis.

    Meme coins require different metrics than DeFi. Focus on:
    - Social volume and community growth
    - Holder distribution (concentration risk)
    - Exchange listing breadth
    - Market age (survival bias)
    - Narrative relevance score
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "meme", "ticker": base}

    # 1. Market data
    market_data = _get_current_market_data(base)
    result["price_usd"] = market_data.get("price")
    result["market_cap_usd"] = market_data.get("market_cap")
    result["volume_24h_usd"] = market_data.get("volume_24h")

    # 2. CoinGecko metadata (community, social signals)
    coin_id = cg_get_coin_id(base)
    if coin_id:
        coin_data = cg_get_coin_data(coin_id)
        if coin_data:
            # Age / survival metric
            genesis = coin_data.get("genesis_date")
            result["genesis_date"] = genesis

            # Community data
            community = coin_data.get("community_data", {})
            result["twitter_followers"] = community.get("twitter_followers")
            result["reddit_subscribers"] = community.get("reddit_subscribers")
            result["telegram_users"] = community.get("telegram_channel_user_count")

            # Market rank
            mcap_rank = coin_data.get("market_cap_rank")
            result["market_cap_rank"] = mcap_rank

            # Liquidity score
            market = coin_data.get("market_data", {})
            result["liquidity_score"] = market.get("liquidity_score")

            # Price change over time
            result["change_24h_pct"] = market.get("price_change_percentage_24h")
            result["change_7d_pct"] = market.get("price_change_percentage_7d")
            result["change_30d_pct"] = market.get("price_change_percentage_30d")

    # 3. Narrative assessment (qualitative based on category signals)
    category_info = detect_category(base)
    result["subcategory"] = category_info.get("subcategory", "")

    # 4. Scoring
    score = 0
    details: List[str] = []

    # Market cap score (higher MC = more established, but less upside)
    mc = result.get("market_cap_usd")
    if mc:
        if mc > 1e9:
            score += 2
            details.append(f"Large cap (${mc/1e9:.1f}B): established but less upside (+2)")
        elif mc > 100e6:
            score += 3
            details.append(f"Mid cap (${mc/1e6:.0f}M): good size + upside potential (+3)")
        elif mc > 10e6:
            score += 1
            details.append(f"Small cap (${mc/1e6:.0f}M): speculative (+1)")
        else:
            details.append(f"Micro cap: very high risk (0)")

    # Social following
    twitter = result.get("twitter_followers")
    if twitter:
        if twitter > 100000:
            score += 2
            details.append(f"Twitter: {twitter:,} followers - strong (+2)")
        elif twitter > 10000:
            score += 1
            details.append(f"Twitter: {twitter:,} followers - building (+1)")

    # Liquidity
    liquidity = result.get("liquidity_score")
    if liquidity:
        if liquidity > 80:
            score += 2
            details.append(f"Liquidity: {liquidity} - high (+2)")
        elif liquidity > 50:
            score += 1
            details.append(f"Liquidity: {liquidity} - moderate (+1)")
        else:
            score -= 1
            details.append(f"Liquidity: {liquidity} - low (-1)")

    # Recent momentum
    change_7d = result.get("change_7d_pct")
    if change_7d is not None:
        if change_7d > 20:
            score -= 1
            details.append(f"7d +{change_7d:.1f}%: overextended (-1)")
        elif change_7d < -20:
            score -= 1
            details.append(f"7d {change_7d:.1f}%: heavy decline (-1)")
        else:
            score += 1
            details.append(f"7d {change_7d:.1f}%: normal range (+1)")

    result["fundamental_score"] = max(0, min(10, score))
    result["fundamental_score_details"] = details
    result["fundamental_rating"] = (
        "strong" if score >= 7 else "good" if score >= 5 else "speculative" if score >= 3 else "high_risk"
    )

    # 5. Risk narrative
    result["risk_narrative"] = {
        "holder_concentration_warning": "Meme coins often have concentrated holdings. Top 10 wallets >50% supply = high rug risk.",
        "hype_cycle_risk": "Meme coins are narrative-driven. Community growth is the primary value driver.",
        "survival_bias_note": "Most meme tokens die within 6 months. Longevity is a quality signal.",
    }

    return result


# =========================================================================
#  Layer 1 / Layer 2 Analysis
# =========================================================================

def _analyze_l1(ticker: str) -> Dict[str, Any]:
    """Layer 1 blockchain fundamental analysis.

    Metrics: Ecosystem TVL, daily active addresses, transaction count,
    developer activity, fee generation, validator decentralization.
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "l1", "ticker": base}

    # 1. Market data
    market_data = _get_current_market_data(base)
    result["price_usd"] = market_data.get("price")
    result["market_cap_usd"] = market_data.get("market_cap")
    result["volume_24h_usd"] = market_data.get("volume_24h")

    # 2. Chain name mapping for DeFiLlama
    CHAIN_MAP: Dict[str, str] = {
        "ETH": "ethereum", "SOL": "solana", "BNB": "bsc", "AVAX": "avalanche",
        "MATIC": "polygon", "POL": "polygon", "ADA": "cardano", "DOT": "polkadot",
        "NEAR": "near", "FTM": "fantom", "ATOM": "cosmos", "TRX": "tron",
        "APT": "aptos", "SUI": "sui", "SEI": "sei", "INJ": "injective",
        "ALGO": "algorand", "XLM": "stellar",
    }
    chain_name = CHAIN_MAP.get(base, base.lower())

    # 3. Ecosystem TVL
    chain_tvl = dl_get_chain_tvl(chain_name)
    if chain_tvl:
        result["ecosystem_tvl_usd"] = chain_tvl

    # 4. TVL/MC ratio
    mc = market_data.get("market_cap")
    if chain_tvl and mc and mc > 0:
        ratio = chain_tvl / mc
        result["tvl_mc_ratio"] = round(ratio, 4)
        result["tvl_mc_interpretation"] = (
            "TVL/MC ratio for L1 compares ecosystem locked value to native token market cap. "
            "Higher values suggest more economic activity per unit of market cap."
        )

    # 5. CoinGecko metadata (developer activity, community)
    coin_id = cg_get_coin_id(base)
    if coin_id:
        coin_data = cg_get_coin_data(coin_id)
        if coin_data:
            dev = coin_data.get("developer_data", {})
            result["github_stars"] = dev.get("stars")
            result["github_forks"] = dev.get("forks")
            result["commit_count_4w"] = dev.get("commit_count_4_weeks")

            community = coin_data.get("community_data", {})
            result["twitter_followers"] = community.get("twitter_followers")

            market = coin_data.get("market_data", {})
            result["market_cap_rank"] = coin_data.get("market_cap_rank")
            result["change_7d_pct"] = market.get("price_change_percentage_7d")
            result["change_30d_pct"] = market.get("price_change_percentage_30d")

    # 6. Scoring
    score = 0
    details: List[str] = []

    # TVL score
    if chain_tvl:
        if chain_tvl > 10e9:
            score += 3
            details.append(f"Ecosystem TVL ${chain_tvl/1e9:.1f}B: massive (+3)")
        elif chain_tvl > 1e9:
            score += 2
            details.append(f"Ecosystem TVL ${chain_tvl/1e9:.1f}B: large (+2)")
        elif chain_tvl > 100e6:
            score += 1
            details.append(f"Ecosystem TVL ${chain_tvl/1e6:.0f}M: growing (+1)")
        else:
            details.append(f"Ecosystem TVL ${chain_tvl/1e6:.0f}M: small (0)")

    # TVL/MC ratio
    tvl_mc = result.get("tvl_mc_ratio")
    if tvl_mc is not None:
        if tvl_mc > 1.0:
            score += 3
            details.append(f"TVL/MC {tvl_mc:.2f}: excellent (+3)")
        elif tvl_mc > 0.5:
            score += 2
            details.append(f"TVL/MC {tvl_mc:.2f}: good (+2)")
        elif tvl_mc > 0.2:
            score += 1
            details.append(f"TVL/MC {tvl_mc:.2f}: moderate (+1)")
        else:
            details.append(f"TVL/MC {tvl_mc:.2f}: low (0)")

    # Developer activity
    commits = result.get("commit_count_4w")
    if commits:
        if commits > 200:
            score += 2
            details.append(f"Dev activity: {commits} commits/4w - high (+2)")
        elif commits > 50:
            score += 1
            details.append(f"Dev activity: {commits} commits/4w - active (+1)")
        else:
            details.append(f"Dev activity: {commits} commits/4w - low (0)")

    result["fundamental_score"] = max(0, min(10, score))
    result["fundamental_score_details"] = details
    result["fundamental_rating"] = (
        "excellent" if score >= 7 else "good" if score >= 5 else "fair" if score >= 3 else "weak"
    )

    return result


def _analyze_l2(ticker: str) -> Dict[str, Any]:
    """Layer 2 fundamental analysis (similar to L1 but L2-focused metrics)."""
    data = _analyze_l1(ticker)
    data["category"] = "l2"
    data["l2_specific_notes"] = {
        "settlement_layer": "L2 value depends on L1 security and fee compression.",
        "sequencer_revenue": "L2 sequencer revenue is a key fundamental metric.",
        "blob_fees": "L2s using blobs compete on data availability costs.",
    }
    return data


# =========================================================================
#  Gaming / Metaverse Token Analysis
# =========================================================================

def _analyze_gaming(ticker: str) -> Dict[str, Any]:
    """Gaming token fundamental analysis.

    Metrics: Active player proxy, CoinGecko market data,
    community signals, token utility assessment.
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "gaming", "ticker": base}

    market_data = _get_current_market_data(base)
    result["price_usd"] = market_data.get("price")
    result["market_cap_usd"] = market_data.get("market_cap")
    result["volume_24h_usd"] = market_data.get("volume_24h")

    coin_id = cg_get_coin_id(base)
    if coin_id:
        coin_data = cg_get_coin_data(coin_id)
        if coin_data:
            community = coin_data.get("community_data", {})
            result["twitter_followers"] = community.get("twitter_followers")
            market = coin_data.get("market_data", {})
            result["market_cap_rank"] = coin_data.get("market_cap_rank")
            result["change_30d_pct"] = market.get("price_change_percentage_30d")
            result["liquidity_score"] = market.get("liquidity_score")

    # Scoring (simplified for gaming - would be enhanced with actual game metrics)
    score = 5  # neutral baseline
    details: List[str] = []

    mc = result.get("market_cap_usd")
    if mc:
        if mc > 1e9:
            score += 2
            details.append(f"Market cap ${mc/1e9:.1f}B: large (+2)")
        elif mc > 100e6:
            score += 1
            details.append(f"Market cap ${mc/1e6:.0f}M: mid (+1)")

    twitter = result.get("twitter_followers")
    if twitter:
        if twitter > 200000:
            score += 2
            details.append(f"Community: {twitter:,} followers - strong (+2)")
        elif twitter > 50000:
            score += 1
            details.append(f"Community: {twitter:,} followers - building (+1)")

    result["fundamental_score"] = max(0, min(10, score))
    result["fundamental_score_details"] = details
    result["fundamental_rating"] = (
        "strong" if score >= 7 else "good" if score >= 5 else "speculative"
    )
    result["gaming_note"] = "Gaming token analysis is limited by off-chain player data availability. "
    "Active player counts and in-game metrics require project-specific data sources."

    return result


# =========================================================================
#  Store of Value (BTC) Analysis
# =========================================================================

def _analyze_sov(ticker: str) -> Dict[str, Any]:
    """Bitcoin / Store of Value fundamental analysis.

    Metrics: Stock-to-flow, hash rate, realized cap,
    illiquid supply, exchange balances, mining metrics.
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "store_of_value", "ticker": base}

    market_data = _get_current_market_data(base)
    result["price_usd"] = market_data.get("price")
    result["market_cap_usd"] = market_data.get("market_cap")

    coin_id = cg_get_coin_id(base)
    if coin_id:
        coin_data = cg_get_coin_data(coin_id)
        if coin_data:
            market = coin_data.get("market_data", {})
            result["market_cap_rank"] = market.get("market_cap_rank")
            result["circulating_supply"] = market.get("circulating_supply")
            result["max_supply"] = market.get("max_supply")
            result["total_supply"] = market.get("total_supply")
            result["ath_usd"] = market.get("ath", {}).get("usd")
            result["change_30d_pct"] = market.get("price_change_percentage_30d")

            # Supply metrics
            circ = market.get("circulating_supply")
            max_sup = market.get("max_supply")
            if circ and max_sup and max_sup > 0:
                result["supply_mined_pct"] = round(circ / max_sup * 100, 2)

    # Scoring
    score = 0
    details: List[str] = []

    mc = result.get("market_cap_usd")
    if mc and mc > 500e9:
        score += 3
        details.append(f"Market cap ${mc/1e9:.1f}B: dominant (+3)")

    ath = result.get("ath_usd")
    price = result.get("price_usd")
    if ath and price and price > 0:
        ath_ratio = price / ath
        if ath_ratio > 0.8:
            score += 2
            details.append(f"Near ATH ({ath_ratio*100:.0f}%): strong momentum (+2)")
        elif ath_ratio > 0.5:
            score += 1
            details.append(f"Mid-cycle ({ath_ratio*100:.0f}% from ATH): accumulation zone (+1)")
        else:
            score -= 1
            details.append(f"Deep from ATH ({ath_ratio*100:.0f}%): bear zone (-1)")

    change_30 = result.get("change_30d_pct")
    if change_30 is not None:
        if 0 < change_30 < 30:
            score += 1
            details.append(f"30d +{change_30:.1f}%: healthy uptrend (+1)")
        elif change_30 > 50:
            score -= 1
            details.append(f"30d +{change_30:.1f}%: overheated (-1)")

    result["fundamental_score"] = max(0, min(10, score))
    result["fundamental_score_details"] = details
    result["fundamental_rating"] = (
        "excellent" if score >= 7 else "good" if score >= 5 else "fair" if score >= 3 else "weak"
    )

    result["sov_narrative"] = {
        "stock_to_flow_note": "S2F model: BTC halving reduces new supply. Next halving ~2028.",
        "institutional_adoption": "ETF flows and institutional treasury allocations are key price drivers.",
        "hash_rate_importance": "Hash rate reflects network security. Rising hash rate = growing miner conviction.",
    }

    return result


# =========================================================================
#  Other / Generic Analysis
# =========================================================================

def _analyze_other(ticker: str) -> Dict[str, Any]:
    """Generic fundamental analysis for uncategorized or unknown tokens.

    When a token is not in our database, we still provide:
    - Exchange ticker data (price, volume, 24h change) if available
    - Helpful guidance on why the token is uncategorized
    - Suggestions for what analysis can still be performed
    """
    base = ticker.upper().replace("/USDT", "").strip()
    result: Dict[str, Any] = {"category": "unknown", "ticker": base}

    market_data = _get_current_market_data(base)
    result["price_usd"] = market_data.get("price")
    result["market_cap_usd"] = market_data.get("market_cap")
    result["volume_24h_usd"] = market_data.get("volume_24h")
    result["data_status"] = market_data.get("status", "unknown")
    result["data_source"] = market_data.get("source", "unknown")
    result["data_message"] = market_data.get("message", "")

    # Try CoinGecko for any additional metadata
    coin_id = cg_get_coin_id(base)
    if coin_id:
        coin_data = cg_get_coin_data(coin_id)
        if coin_data:
            market = coin_data.get("market_data", {})
            result["market_cap_rank"] = coin_data.get("market_cap_rank")
            result["change_24h_pct"] = market.get("price_change_percentage_24h")
            result["change_7d_pct"] = market.get("price_change_percentage_7d")
            result["change_30d_pct"] = market.get("price_change_percentage_30d")
            result["liquidity_score"] = market.get("liquidity_score")
            community = coin_data.get("community_data", {})
            result["twitter_followers"] = community.get("twitter_followers")
            result["data_status"] = "enhanced"
            result["data_message"] = "CoinGecko metadata successfully retrieved."

    # Provide helpful context when data is limited
    if result.get("data_status") == "failed":
        result["guidance"] = (
            f"'{base}' could not be analyzed. This usually means: (1) the symbol is misspelled, "
            "(2) the token is not listed on supported exchanges, or (3) network restrictions "
            "prevent data access. Please check the symbol and try again."
        )
    elif result.get("data_status") == "partial":
        result["guidance"] = (
            f"'{base}' is not in our category database, but basic exchange data is available. "
            "Technical analysis (RSI, MACD, Bollinger) can still be performed. "
            "Fundamental analysis is limited to price and volume only."
        )
    else:
        result["guidance"] = (
            f"'{base}' has basic market data. For deeper fundamental analysis, "
            "run category-specific analysis if the token type is known."
        )

    return result


# =========================================================================
#  Main: All-Fundamentals (auto-detect category)
# =========================================================================

CATEGORY_DISPATCHER = {
    "defi": _analyze_defi,
    "meme": _analyze_meme,
    "l1": _analyze_l1,
    "l2": _analyze_l2,
    "gaming": _analyze_gaming,
    "store_of_value": _analyze_sov,
    "ai": _analyze_other,
    "infra": _analyze_other,
    "stablecoin": _analyze_other,
    "rwa": _analyze_other,
    "wrapped": _analyze_other,
    "other": _analyze_other,
    "unknown": _analyze_other,  # NEW: handle tokens not in database
}


def action_all_fundamentals(symbol: str) -> str:
    """Run comprehensive fundamental analysis based on auto-detected category.

    This is the recommended entry point for fundamental analysis.
    Automatically detects the token category and applies the appropriate
    analysis framework.

    Args:
        symbol: Trading pair string (auto-normalized).

    Returns:
        JSON string with category-specific fundamental analysis results.
    """
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()

    # 1. Detect category
    category_info = detect_category(base)
    category = category_info["category"]

    # 2. Get analysis dimensions
    dimensions = get_category_analysis_dimensions(category)

    # 3. Run category-specific analysis
    analyzer = CATEGORY_DISPATCHER.get(category, _analyze_other)
    result = analyzer(base)

    # 4. Enrich with dimension guidance
    env = get_network_env()
    result["symbol"] = symbol
    result["category_detection"] = category_info
    result["recommended_dimensions"] = dimensions
    result["environment"] = {
        "network": env,
        "coingecko_available": cg_get_coin_id(base) is not None,
        "defillama_available": dl_get_protocol_slug(base) is not None,
    }

    # Friendly analysis note based on category confidence
    if category_info.get("confidence") == "low":
        result["analysis_note"] = (
            f"Token '{base}' is not in our database of 200+ mapped tokens. "
            "Basic exchange data (price, volume) is provided. "
            "For deeper analysis, the token may need to be added to our mapping or "
            "CoinGecko API must be accessible for auto-categorization."
        )
    else:
        result["analysis_note"] = (
            f"Analysis tailored for {category} tokens. {dimensions.get('narrative_check', '')}"
        )

    return json.dumps(result, indent=2, ensure_ascii=False)


def action_defi_metrics(symbol: str) -> str:
    """Run DeFi-specific fundamental analysis.

    Uses: DeFiLlama TVL + CoinGecko market data.
    """
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()
    return json.dumps(_analyze_defi(base), indent=2, ensure_ascii=False)


def action_meme_metrics(symbol: str) -> str:
    """Run Meme-specific fundamental and narrative analysis."""
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()
    return json.dumps(_analyze_meme(base), indent=2, ensure_ascii=False)


def action_l1_metrics(symbol: str) -> str:
    """Run Layer 1 fundamental analysis."""
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()
    return json.dumps(_analyze_l1(base), indent=2, ensure_ascii=False)


def action_l2_metrics(symbol: str) -> str:
    """Run Layer 2 fundamental analysis."""
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()
    return json.dumps(_analyze_l2(base), indent=2, ensure_ascii=False)


def action_category_detect(symbol: str) -> str:
    """Detect token category with detailed explanation."""
    symbol = _normalize_symbol(symbol)
    base = symbol.replace("/USDT", "").upper()
    info = detect_category(base)
    dims = get_category_analysis_dimensions(info["category"])
    return json.dumps({
        "symbol": symbol,
        "detection": info,
        "recommended_analysis": dims,
    }, indent=2, ensure_ascii=False)


# =========================================================================
#  CLI Entry Point
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="Category-specific crypto fundamental analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --action all --symbol UNI      (auto-detect as DeFi)
  %(prog)s --action all --symbol DOGE     (auto-detect as Meme)
  %(prog)s --action all --symbol ETH      (auto-detect as L1)
  %(prog)s --action defi --symbol AAVE
  %(prog)s --action meme --symbol PEPE
  %(prog)s --action l1 --symbol SOL
  %(prog)s --action category --symbol CRV
""",
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["all", "defi", "meme", "l1", "l2", "gaming", "sov", "category"],
        help="Analysis action.",
    )
    parser.add_argument("--symbol", type=str, default="BTC",
                        help="Trading pair (default: BTC).")
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.action == "all":
            print(action_all_fundamentals(args.symbol))
        elif args.action == "defi":
            print(action_defi_metrics(args.symbol))
        elif args.action == "meme":
            print(action_meme_metrics(args.symbol))
        elif args.action == "l1":
            print(action_l1_metrics(args.symbol))
        elif args.action == "l2":
            print(action_l2_metrics(args.symbol))
        elif args.action == "sov":
            symbol = _normalize_symbol(args.symbol)
            print(json.dumps(_analyze_sov(symbol.replace("/USDT", "").upper()),
                             indent=2, ensure_ascii=False))
        elif args.action == "category":
            print(action_category_detect(args.symbol))
        else:
            parser.error(f"Unknown action: {args.action}")
    except (ValueError, RuntimeError) as e:
        logger.error("Execution failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
