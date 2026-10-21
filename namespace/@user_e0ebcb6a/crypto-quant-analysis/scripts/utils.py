"""
Utilities for the enhanced crypto quantitative analysis skill.

New capabilities (v2.0):
- Multi-source data: CoinGecko API + ccxt exchanges (Binance/Bybit or Gate/OKX)
- Network environment detection (China vs global)
- Data cross-validation between sources with deviation alerts
- Token category detection (DeFi, Meme, L1, etc.)
- DeFiLlama API integration for TVL and protocol data
- On-chain data endpoints

Retained from v1.0:
- Symbol normalization (single code -> BASE/USDT)
- Exchange instance creation with automatic fallback
- OHLCV data fetching with validation
- Safe float conversion for JSON serialization
"""

import argparse
import json
import logging
import socket
import sys
import time
from typing import Optional, Dict, Any, List, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import ccxt
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crypto-quant")

# ---------------------------------------------------------------------------
# Exchange configuration
# ---------------------------------------------------------------------------
DEFAULT_EXCHANGE: str = "gate"
FALLBACK_EXCHANGE: str = "okx"
GLOBAL_EXCHANGE: str = "binance"       # Primary for global network
GLOBAL_FALLBACK: str = "bybit"         # Fallback for global network
DEFAULT_TIMEFRAME: str = "1d"
DEFAULT_LIMIT: int = 200
# Progressive timeouts: initial, retry, final (milliseconds for ccxt)
EXCHANGE_TIMEOUT: int = 30_000
EXCHANGE_TIMEOUT_INITIAL: int = 5_000   # 5s for first attempt
EXCHANGE_TIMEOUT_RETRY: int = 10_000     # 10s for second attempt
CROSS_VALIDATION_THRESHOLD: float = 0.02  # 2% deviation triggers warning

# ---------------------------------------------------------------------------
# CoinGecko configuration
# ---------------------------------------------------------------------------
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"
COINGECKO_RATE_LIMIT: float = 1.5       # seconds between requests (free tier)
_last_cg_request: float = 0.0

# Comprehensive CoinGecko ID mapping (ticker -> coin_id) - expanded to 150+ tokens
COINGECKO_ID_MAP: Dict[str, str] = {
    # Store of Value / Bitcoin
    "BTC": "bitcoin", "WBTC": "wrapped-bitcoin", "CBTC": "compound-wbtc",

    # Layer 1 Blockchains
    "ETH": "ethereum", "WETH": "weth", "SOL": "solana", "BNB": "binancecoin",
    "AVAX": "avalanche-2", "ADA": "cardano", "DOT": "polkadot", "NEAR": "near",
    "ATOM": "cosmos", "APT": "aptos", "SUI": "sui", "SEI": "sei-network",
    "INJ": "injective-protocol", "FTM": "fantom", "ALGO": "algorand",
    "TRX": "tron", "XLM": "stellar", "VET": "vechain", "XRP": "ripple",
    "ETC": "ethereum-classic", "HBAR": "hedera-hashgraph", "TON": "the-open-network",
    "KAS": "kaspa", "ICP": "internet-computer", "XTZ": "tezos", "NEO": "neo",
    "EOS": "eos", "FLOW": "flow", "ROSE": "oasis-network", "MINA": "mina-protocol",
    "CELO": "celo", "ONE": "harmony", "CANTO": "canto", "CRO": "crypto-com-chain",
    "KAVA": "kava", "RUNE": "thorchain", "DASH": "dash", "ZEC": "zcash",
    "XMR": "monero", "LTC": "litecoin", "BCH": "bitcoin-cash", "BSV": "bitcoin-sv",
    "DOGE": "dogecoin", "SHIB": "shiba-inu", "PEPE": "pepe", "FLOKI": "floki",
    "BONK": "bonk", "WIF": "dogwifcoin", "BOME": "book-of-meme", "MOG": "mog-coin",
    "POPCAT": "popcat", "SPX": "spx6900", "GIGA": "gigachad-2", "TURBO": "turbo",
    "MEME": "memecoin", "PENGU": "pudgy-penguins", "SQUIDGROW": "squidgrow",
    "BABYDOGE": "baby-doge-coin", "ELON": "dogelon-mars", "SHIB": "shiba-inu",
    "TOSHI": "toshi", "NEIRO": "neiro-on-ethereum", "BRETT": "based-brett",

    # Layer 2 / Scaling
    "MATIC": "matic-network", "POL": "polygon-ecosystem-token", "ARB": "arbitrum",
    "OP": "optimism", "STRK": "starknet", "ZKSYNC": "zksync", "MANTA": "manta-network",
    "BLAST": "blast", "METIS": "metis-token", "IMX": "immutable-x", "STARK": "starknet",
    "BOBA": "boba-network", "LOOKS": "looksrare", "ZRO": "layerzero", "ZETA": "zetachain",

    # DeFi - DEX / AMM
    "UNI": "uniswap", "SUSHI": "sushi", "CAKE": "pancakeswap-token", "RAY": "raydium",
    "ORCA": "orca", "JUP": "jupiter-exchange-solana", "BAL": "balancer",
    "VELO": "velodrome-finance", "COW": "cow-protocol", "1INCH": "1inch",
    "SUSHI": "sushi", "DODO": "dodo", "JOE": "joe", "GMX": "gmx",
    "DYDX": "dydx", "APEX": "apex-token", "GNS": "gains-network",
    "SNX": "havven", "PERP": "perpetual-protocol", "BNT": "bancor",
    "THOR": "thorchain", "SUSHI": "sushi", "MAV": "maverick-protocol",

    # DeFi - Lending
    "AAVE": "aave", "COMP": "compound-governance-token", "MKR": "maker",
    "CRV": "curve-dao-token", "LDO": "lido-dao", "PENDLE": "pendle", "ENA": "ethena",
    "EIGEN": "eigenlayer", "MORPHO": "morpho", "AEVO": "aevo", "PRISMA": "prisma-governance-token",
    "LBR": "lybra-finance", "INST": "instadapp", "RDNT": "radiant-capital",
    "GRAI": "grai", "FXS": "frax-share", "FRAX": "frax", "LUSD": "liquity-usd",
    "RAI": "rai", "OHM": "olympus", "SPELL": "spell-token", "MIM": "magic-internet-money",

    # DeFi - Yield / Aggregators
    "YFI": "yearn-finance", "CVX": "convex-finance", "BIFI": "beefy-finance",
    "ALCX": "alchemix", "TOKE": "tokemak", "FIS": "stafi", "STETH": "staked-ether",
    "RETH": "rocket-pool-eth", "SETH2": "seth2", "ANKRETH": "ankreth", "SWETH": "swell-ether",
    "OSMO": "osmosis", "KNC": "kyber-network-crystal", "JOE": "joe", "ZIP": "zipswap",

    # Infrastructure / Oracles / Bridges
    "LINK": "chainlink", "GRT": "the-graph", "FIL": "filecoin", "AR": "arweave",
    "TIA": "celestia", "RNDR": "render-token", "FET": "fetch-ai", "AGIX": "singularitynet",
    "TAO": "bittensor", "WLD": "worldcoin-wld", "AKT": "akash-network", "HNT": "helium",
    "GRT": "the-graph", "POND": "marlin", "NOIA": "syntropy", "API3": "api3",
    "BAND": "band-protocol", "UMA": "uma", "DIA": "dia-data", "TRB": "tellor",
    "API3": "api3", "PYTH": "pyth-network", "RED": "redstone", "LINK": "chainlink",
    "AXL": "axelar", "WORMHOLE": "wormhole", "SYN": "synapse-2", "STG": "stargate-finance",
    "ACX": "across-protocol", "HOP": "hop-protocol", "OMNI": "omni-network",
    "ZRO": "layerzero", "NTRN": "neutron-3", "STRD": "stride",

    # AI / Big Data
    "RENDER": "render-token", "FET": "fetch-ai", "AGIX": "singularitynet",
    "TAO": "bittensor", "WLD": "worldcoin-wld", "GRT": "the-graph", "LPT": "livepeer",
    "OCEAN": "ocean-protocol", "NMR": "numeraire", "BTRST": "braintrust",
    "AI16Z": "ai16z", "AIXBT": "aixbt", "VIRTUAL": "virtual-protocol",
    "LUNA": "terra-luna-2", "PHB": "phoenix-2",

    # Gaming / Metaverse
    "SAND": "the-sandbox", "MANA": "decentraland", "AXS": "axie-infinity",
    "GALA": "gala", "ILV": "illuvium", "IMX": "immutable-x", "PRIME": "echelon-prime",
    "YGG": "yield-guild-games", "MC": "merit-circle", "BEND": "benji-bananas",
    "GMT": "green-metaverse-token", "ACE": "aceminers", "SPL": "splinterlands",
    "ENJ": "enjincoin", "UOS": "ultra", "DERC": "derace", "DEAP": "deapcoin",
    "ALICE": "my-neighbor-alice", "TLM": "alien-worlds", "ATLAS": "star-atlas",

    # RWA / Tokenization
    "ONDO": "ondo-finance", "CFG": "centrifuge", "MPL": "maple-finance",
    "TRU": "truefi", "GFI": "goldfinch", "RBN": "ribbon-finance", "PERP": "perpetual-protocol",
    "POLYX": "polymesh", "CANTO": "canto", "RIO": "realio-network", "NXRA": "nexera",
    "LEOX": "leox", "EKTA": "ekta", "LAND": "landshare", "PROPS": "props",
    "CPOOL": "clearpool", "HMT": "hmt", "RIO": "realio-network",

    # Stablecoins
    "USDT": "tether", "USDC": "usd-coin", "DAI": "dai", "USDD": "usdd",
    "FRAX": "frax", "TUSD": "true-usd", "BUSD": "binance-usd", "PYUSD": "paypal-usd",
    "USDJ": "just-stablecoin", "USDP": "paxos-standard", "GUSD": "gemini-dollar",
    "LUSD": "liquity-usd", "MAI": "mimatic", "MIM": "magic-internet-money",
    "USDX": "usdx-money", "USDE": "ethena-usde", "SUSD": "susd",

    # Wrapped / Liquid Staking
    "WBTC": "wrapped-bitcoin", "WETH": "weth", "STETH": "staked-ether",
    "RETH": "rocket-pool-eth", "CBETH": "coinbase-wrapped-staked-eth",
    "METH": "mantle-staked-ether", "OSETH": "origin-staked-ether",
    "SWETH": "swell-ether", "ANKRETH": "ankreth", "SETH2": "seth2",

    # Additional top market cap coins
    "ICP": "internet-computer", "NEAR": "near", "APT": "aptos", "SUI": "sui",
    "SEI": "sei-network", "INJ": "injective-protocol", "KAS": "kaspa",
    "HBAR": "hedera-hashgraph", "TON": "the-open-network", "TAO": "bittensor",
    "MNT": "mantle", "BEAM": "beam-2", "GNO": "gnosis", "XEC": "ecash",
    "BSV": "bitcoin-sv", "DASH": "dash", "ZEC": "zcash", "XMR": "monero",
    "IOTA": "iota", "QTUM": "qtum", "KSM": "kusama", "SRM": "serum",
    "CVC": "civic", "BAT": "basic-attention-token", "ZRX": "0x",
    "MANA": "decentraland", "SAND": "the-sandbox", "CHZ": "chiliz",
    "HOT": "holotoken", "SC": "siacoin", "STORJ": "storj",
    "ANKR": "ankr", "COTI": "coti", "SKL": "skale", "CELR": "celer-network",
    "OCEAN": "ocean-protocol", "NMR": "numeraire", "REQ": "request-network",
    "MTL": "metal", "LOOM": "loom-network", "DENT": "dent", "POWR": "power-ledger",
    "KIN": "kin", "SOLVE": "solve-care", "STMX": "stormx",
    "BTT": "bittorrent", "WIN": "wink", "COTI": "coti", "CHR": "chromaway",
    "UOS": "ultra", "TEL": "telcoin", "RSR": "reserve-rights-token", "KAVA": "kava",
    "SXP": "swipe", "WAVES": "waves", "ONT": "ontology", "NANO": "nano",
    "RVN": "ravencoin", "FIRO": "firo", "DGB": "digibyte", "XVG": "verge",
    "SC": "siacoin", "CKB": "nervos-network", "ONE": "harmony", "CRO": "crypto-com-chain",
    "CELR": "celer-network", "FET": "fetch-ai", "CTSI": "cartesi", "OCEAN": "ocean-protocol",
    "AKT": "akash-network", "HNT": "helium", "LPT": "livepeer", "AIOZ": "aioz-network",
    "GRT": "the-graph", "POND": "marlin", "NOIA": "syntropy", "DIA": "dia-data",
    "TRB": "tellor", "BAND": "band-protocol", "UMA": "uma", "API3": "api3",
    "PYTH": "pyth-network", "RED": "redstone", "AXL": "axelar", "STG": "stargate-finance",
    "ACX": "across-protocol", "HOP": "hop-protocol", "SYN": "synapse-2", "NTRN": "neutron-3",
    "STRD": "stride", "ZETA": "zetachain", "OMNI": "omni-network", "W": "wormhole",
    "MANTA": "manta-network", "BLAST": "blast", "METIS": "metis-token", "BOBA": "boba-network",
    "LOOKS": "looksrare", "VELO": "velodrome-finance", "COW": "cow-protocol",
    "1INCH": "1inch", "DODO": "dodo", "JOE": "joe", "APEX": "apex-token", "GNS": "gains-network",
    "PERP": "perpetual-protocol", "BNT": "bancor", "MAV": "maverick-protocol",
    "MORPHO": "morpho", "AEVO": "aevo", "PRISMA": "prisma-governance-token",
    "LBR": "lybra-finance", "INST": "instadapp", "RDNT": "radiant-capital",
    "GRAI": "grai", "CVX": "convex-finance", "BIFI": "beefy-finance",
    "ALCX": "alchemix", "TOKE": "tokemak", "FIS": "stafi", "FXS": "frax-share",
    "OHM": "olympus", "SPELL": "spell-token", "OSMO": "osmosis", "KNC": "kyber-network-crystal",
    "ZIP": "zipswap", "NXRA": "nexera", "LEOX": "leox", "EKTA": "ekta",
    "LAND": "landshare", "PROPS": "props", "CPOOL": "clearpool", "HMT": "hmt",
    "ONDO": "ondo-finance", "CFG": "centrifuge", "MPL": "maple-finance",
    "TRU": "truefi", "GFI": "goldfinch", "RBN": "ribbon-finance",
    "POLYX": "polymesh", "RIO": "realio-network", "USDD": "usdd",
    "TUSD": "true-usd", "BUSD": "binance-usd", "PYUSD": "paypal-usd",
    "USDJ": "just-stablecoin", "USDP": "paxos-standard", "GUSD": "gemini-dollar",
    "MAI": "mimatic", "SUSD": "susd", "USDX": "usdx-money", "USDE": "ethena-usde",
    "CBETH": "coinbase-wrapped-staked-eth", "METH": "mantle-staked-ether",
    "OSETH": "origin-staked-ether", "BEAM": "beam-2", "GNO": "gnosis",
    "XEC": "ecash", "IOTA": "iota", "QTUM": "qtum", "KSM": "kusama",
    "SRM": "serum", "CVC": "civic", "BAT": "basic-attention-token", "ZRX": "0x",
    "CHZ": "chiliz", "HOT": "holotoken", "STORJ": "storj", "ANKR": "ankr",
    "SKL": "skale", "OCEAN": "ocean-protocol", "REQ": "request-network", "MTL": "metal",
    "LOOM": "loom-network", "DENT": "dent", "POWR": "power-ledger", "KIN": "kin",
    "SOLVE": "solve-care", "STMX": "stormx", "BTT": "bittorrent", "WIN": "wink",
    "CHR": "chromaway", "TEL": "telcoin", "RSR": "reserve-rights-token",
    "SXP": "swipe", "WAVES": "waves", "ONT": "ontology", "NANO": "nano",
    "RVN": "ravencoin", "FIRO": "firo", "DGB": "digibyte", "XVG": "verge",
    "CKB": "nervos-network", "AIOZ": "aioz-network", "CTSI": "cartesi",
    "YGG": "yield-guild-games", "MC": "merit-circle", "BEND": "benji-bananas",
    "GMT": "green-metaverse-token", "ACE": "aceminers", "SPL": "splinterlands",
    "ENJ": "enjincoin", "UOS": "ultra", "DERC": "derace", "DEAP": "deapcoin",
    "ALICE": "my-neighbor-alice", "TLM": "alien-worlds", "ATLAS": "star-atlas",
    "AI16Z": "ai16z", "AIXBT": "aixbt", "VIRTUAL": "virtual-protocol",
    "PHB": "phoenix-2", "LUNA": "terra-luna-2", "BOME": "book-of-meme",
    "MOG": "mog-coin", "POPCAT": "popcat", "SPX": "spx6900", "GIGA": "gigachad-2",
    "TURBO": "turbo", "MEME": "memecoin", "PENGU": "pudgy-penguins",
    "SQUIDGROW": "squidgrow", "BABYDOGE": "baby-doge-coin", "ELON": "dogelon-mars",
    "TOSHI": "toshi", "NEIRO": "neiro-on-ethereum", "BRETT": "based-brett",

    # Extended coverage — 130+ additional tokens for v2.2
    # DeFi extended
    "TRADE": "polytrade", "POOL": "pooltogether", "INDEX": "index-cooperative",
    "SD": "stader", "XVS": "venus", "VAI": "vai", "TWT": "trust-wallet-token",
    "C98": "coin98", "DVF": "rhinofi", "IDEX": "idex", "VITE": "vite",
    "HOTCROSS": "hotcross", "SALE": "dxsale-network", "BANANA": "apeswap-finance",
    "SWP": "kava-swap", "KAVA": "kava", "HARD": "hard-protocol", "AKRO": "akropolis",
    "PICKLE": "pickle-finance", "BADGER": "badger-dao", "ROOK": "rook",
    "NFTX": "nftx", "ARMOR": "armor", "HEGIC": "hegic", "WBOND": "world-bond",
    "BRKL": "brokoli-network", "GAMMA": "gamma-strategies", "RAMSES": "ramses-exchange",
    "AERODROME": "aerodrome-finance", "BASESWAP": "baseswap", "SOLIDLY": "solidly",
    "EQUAL": "equalizer-dex", "FVM": "fantom-virtual-machine", "SPOOKY": "spookyswap",
    "SPIRIT": "spiritswap", "TOMB": "tomb", "GEIST": "geist-finance",
    "SCREAM": "scream", "CREAM": "cream-finance", "VENUS": "venus",
    "PANCAKE": "pancakeswap-token", "BISWAP": "biswap", "APESWAP": "apeswap-finance",
    "BABYSWAP": "babyswap", "KNIGHT": "knightswap", "WAULT": "waultswap",
    "BOMB": "bombcrypto", "WEX": "wault-exchange", "POLYDEX": "polydex",
    "DFYN": "dfyn-network", "COMETH": "cometh", "DHT": "dhedge",
    "MIR": "mirror-protocol", "ANC": "anchor-protocol", "PSI": "nexus-protocol",
    "MARS": "mars-protocol", "LOOP": "loop-finance", "ASTRO": "astroport",
    "ERIS": "eris-protocol", "PRISM": "prism-protocol", "STEAK": "steak-protocol",
    "QUICK": "quickswap", "DPI": "defi-pulse-index", "MVI": "metaverse-index",
    "DATA": "streamr", "REP": "augur", "MLN": "enzyme", "NU": "nucypher",
    "KEEP": "keep-network", "TBTC": "tbtc", "RPL": "rocket-pool",
    "LSS": "lossless", "TRAC": "origintrail", "ORAI": "oraichain-token",
    "FLUX": "zelcash", "POND0": "marlin", "EDGE": "edge", "NKN": "nkn",

    # L1 / L2 extended
    "FLR": "flare-networks", "SGB": "songbird", "IOTX": "iotex",
    "SYS": "syscoin", "VTHO": "vethor-token", "WOZX": "efforce",
    "GLMR": "moonbeam", "MOVR": "moonriver", "SDN": "shiden",
    "ASTR": "astar", "KILT": "kilt-protocol", "CLV": "clover",
    "PHA": "pha", "RING": "darwinia-network-native-token", "PCX": "chainx",
    "EDG": "edgeware", "SBY": "subsocial", "PARA": "parallel",
    "KINT": "kintsugi", "INTR": "interlay", "EQ": "equilibrium",
    "TUR": "turing", "MOON": "moon", "SDX": "sora-synthetic-usd",
    "XOR": "sora", "VAL": "sora-validator", "PSWAP": "polkaswap",
    "HYDRA": "hydradx", "BSX": "basilisk", "KAR": "karura",
    "ACA": "acala", "KSM": "kusama", "DOT": "polkadot",
    "WND": "wind", "CFG": "centrifuge", "XRT": "robonomics-network",
    "CRU": "crust-network", "PHALA": "pha", "BIFROST": "bifrost-native-coin",
    "BNC": "bifrost-native-coin", "VS": "vswap", "VAIOT": "vaiot",

    # Gaming / Metaverse extended
    "UFO": "ufo-gaming", "STAR": "starlink", "DOME": "everdome",
    "HERO": "metahero", "BLOK": "bloktopia", "CEEK": "ceek",
    "TVK": "the-virtua-kolect", "RENA": "renaf", "WEMIX": "wemix",
    "MIX": "mixmarvel", "ERD": "elrond", "DARK": "dark-frontier",
    "MOBOX": "mobox", "XWG": "x-world-games", "DAR": "mines-of-dalarnia",
    "ALU": "altura", "FINE": "refinable", "NFTB": "nftb",
    "SOUL": "phantasma", "GHST": "aavegotchi", "REVV": "revv",
    "SPS": "splintershards", "BCOIN": "bombcrypto", "THG": "thetan-arena",
    "CELT": "celt", "ZEN": "horizen", "RACA": "radio-caca",

    # AI / Big Data extended
    "DBC": "deepbrain-chain", "AGI": "singularitynet", "DBC": "deepbrain-chain",
    "DORA": "dora-factory", "DATA": "streamr", "CND": "cindicator",
    "IIC": "intelligent-investment-chain", "MAN": "matrix-ai-network",
    "XAI": "xai", "SPECTRE": "spectre-ai", "COMAI": "comai",
    "RNDR": "render-token", "LPT": "livepeer", "AKT": "akash-network",

    # Infrastructure / Oracles extended
    "API3": "api3", "BAND": "band-protocol", "DIA": "dia-data",
    "TRB": "tellor", "UMA": "uma", "PYTH": "pyth-network",
    "RED": "redstone", "AXL": "axelar", "W": "wormhole",
    "ZRO": "layerzero", "SYN": "synapse-2", "STG": "stargate-finance",
    "ACX": "across-protocol", "HOP": "hop-protocol", "OMNI": "omni-network",
    "NTRN": "neutron-3", "STRD": "stride", "ZETA": "zetachain",
    "MANTA": "manta-network", "BLAST": "blast", "METIS": "metis-token",
    "BOBA": "boba-network", "LOOKS": "looksrare", "VELO": "velodrome-finance",
    "COW": "cow-protocol", "1INCH": "1inch", "DODO": "dodo",
    "JOE": "joe", "APEX": "apex-token", "GNS": "gains-network",
    "PERP": "perpetual-protocol", "BNT": "bancor", "MAV": "maverick-protocol",
    "MORPHO": "morpho", "AEVO": "aevo", "PRISMA": "prisma-governance-token",
    "LBR": "lybra-finance", "INST": "instadapp", "RDNT": "radiant-capital",
    "GRAI": "grai", "FXS": "frax-share", "OHM": "olympus",
    "SPELL": "spell-token", "MIM": "magic-internet-money", "OSMO": "osmosis",
    "KNC": "kyber-network-crystal", "ZIP": "zipswap", "NXRA": "nexera",
    "LEOX": "leox", "EKTA": "ekta", "LAND": "landshare",
    "PROPS": "props", "CPOOL": "clearpool", "HMT": "hmt",
    "ONDO": "ondo-finance", "CFG": "centrifuge", "MPL": "maple-finance",
    "TRU": "truefi", "GFI": "goldfinch", "RBN": "ribbon-finance",
    "POLYX": "polymesh", "RIO": "realio-network", "USDD": "usdd",
    "TUSD": "true-usd", "BUSD": "binance-usd", "PYUSD": "paypal-usd",
    "USDJ": "just-stablecoin", "USDP": "paxos-standard", "GUSD": "gemini-dollar",
    "MAI": "mimatic", "SUSD": "susd", "USDX": "usdx-money",
    "CRVUSD": "crvusd", "GHO": "aave-v3", "DYAD": "dyad",
    "USD0": "usual", "SUSDE": "ethena-usde", "USDE": "ethena-usde",
    "CBETH": "coinbase-wrapped-staked-eth", "METH": "mantle-staked-ether",
    "OSETH": "origin-staked-ether", "SWETH": "swell-ether",
    "ANKRETH": "ankreth", "SETH2": "seth2", "EZETH": "renzo",
    "ETHFI": "ether.fi", "PUFFER": "puffer-finance", "KELP": "kelp-dao",
    "SWELL": "swell", "RSETH": "kelp-dao", "BEAM": "beam-2",
    "GNO": "gnosis", "XEC": "ecash", "IOTA": "iota",
    "QTUM": "qtum", "KSM": "kusama", "SRM": "serum",
    "CVC": "civic", "BAT": "basic-attention-token", "ZRX": "0x",
    "MANA": "decentraland", "SAND": "the-sandbox", "CHZ": "chiliz",
    "HOT": "holotoken", "SC": "siacoin", "STORJ": "storj",
    "ANKR": "ankr", "COTI": "coti", "SKL": "skale",
    "CELR": "celer-network", "OCEAN": "ocean-protocol", "NMR": "numeraire",
    "REQ": "request-network", "MTL": "metal", "LOOM": "loom-network",
    "DENT": "dent", "POWR": "power-ledger", "KIN": "kin",
    "SOLVE": "solve-care", "STMX": "stormx", "BTT": "bittorrent",
    "WIN": "wink", "CHR": "chromaway", "UOS": "ultra",
    "TEL": "telcoin", "RSR": "reserve-rights-token", "SXP": "swipe",
    "WAVES": "waves", "ONT": "ontology", "NANO": "nano",
    "RVN": "ravencoin", "FIRO": "firo", "DGB": "digibyte",
    "XVG": "verge", "CKB": "nervos-network", "AIOZ": "aioz-network",
    "CTSI": "cartesi", "YGG": "yield-guild-games", "MC": "merit-circle",
    "BEND": "benji-bananas", "GMT": "green-metaverse-token", "ACE": "aceminers",
    "SPL": "splinterlands", "ENJ": "enjincoin", "DERC": "derace",
    "DEAP": "deapcoin", "ALICE": "my-neighbor-alice", "TLM": "alien-worlds",
    "ATLAS": "star-atlas", "AI16Z": "ai16z", "AIXBT": "aixbt",
    "VIRTUAL": "virtual-protocol", "PHB": "phoenix-2", "LUNA": "terra-luna-2",
    "BOME": "book-of-meme", "MOG": "mog-coin", "POPCAT": "popcat",
    "SPX": "spx6900", "GIGA": "gigachad-2", "TURBO": "turbo",
    "MEME": "memecoin", "PENGU": "pudgy-penguins", "SQUIDGROW": "squidgrow",
    "BABYDOGE": "baby-doge-coin", "ELON": "dogelon-mars", "TOSHI": "toshi",
    "NEIRO": "neiro-on-ethereum", "BRETT": "based-brett",
    # v2.2 additions (popular mid-cap coins)
    "PEOPLE": "constitutiondao", "AIDOGE": "arb-doge-ai", "WOJAK": "wojak",
    "TSUKA": "dejitaru-tsuka", "QOM": "shiba-predator", "LEASH": "leash",
    "SAMO": "samoyedcoin", "HOGE": "hoge-finance", "AKITA": "akita-inu",
    "KISHU": "kishu-inu", "SAITAMA": "saitama-inu", "PIT": "pitbull",
    "MONA": "monavale", "HACHI": "hachi", "INU": "inu",
    "DINGER": "dinger-token", "CAT": "catcoin", "KITTY": "kitty-inu",
    "MONG": "mongcoin", "WSB": "wall-street-bets", "GME": "gme",
    "AMC": "amc-entertainment-holdings", "CUMMIES": "cumrocket",
    "TITANO": "titano", "SAFUU": "safuu", "FORTUNE": "fortune-token",
    "LUNC": "terra-luna", "USTC": "terrausd", "MIR": "mirror-protocol",
    "ANC": "anchor-protocol", "WHALE": "whale-finance", "MC": "merit-circle",
    "GAL": "project-galaxy", "GALXE": "galxe", "HFT": "hashflow",
    "BLUR": "blur", "BLAST": "blast", "SAGA": "saga",
    "DYM": "dymension", "MANTA": "manta-network", "OMNI": "omni-network",
    "EIGEN": "eigenlayer", "ETHFI": "ether-fi", "RENZO": "renzo",
    "PUFFER": "puffer-finance", "KELP": "kelp-dao", "Swell": "swell",
    "USDX": "usdx-money", "USD0": "usual", "ENA": "ethena",
    "PENDLE": "pendle", "Ethena": "ethena", "AEVO": "aevo",
    "MORPHO": "morpho", "PRISMA": "prisma-governance-token", "LBR": "lybra-finance",
    "INST": "instadapp", "RDNT": "radiant-capital", "GRAI": "grai",
    "FXS": "frax-share", "OHM": "olympus", "SPELL": "spell-token",
    "MIM": "magic-internet-money", "CVX": "convex-finance", "BIFI": "beefy-finance",
    "ALCX": "alchemix", "TOKE": "tokemak", "FIS": "stafi",
    "OSMO": "osmosis", "KNC": "kyber-network-crystal", "ZIP": "zipswap",
    "NXRA": "nexera", "LEOX": "leox", "EKTA": "ekta",
    "LAND": "landshare", "PROPS": "props", "CPOOL": "clearpool",
    "HMT": "hmt", "ONDO": "ondo-finance", "CFG": "centrifuge",
    "MPL": "maple-finance", "TRU": "truefi", "GFI": "goldfinch",
    "RBN": "ribbon-finance", "POLYX": "polymesh", "RIO": "realio-network",
    "USDD": "usdd", "TUSD": "true-usd", "BUSD": "binance-usd",
    "PYUSD": "paypal-usd", "USDJ": "just-stablecoin", "USDP": "paxos-standard",
    "GUSD": "gemini-dollar", "MAI": "mimatic", "SUSD": "susd",
    "CRVUSD": "crvusd", "GHO": "aave-v3", "DYAD": "dyad",
    "SUSDE": "ethena-usde", "USDE": "ethena-usde", "CBETH": "coinbase-wrapped-staked-eth",
    "METH": "mantle-staked-ether", "OSETH": "origin-staked-ether", "SWETH": "swell-ether",
    "ANKRETH": "ankreth", "SETH2": "seth2", "EZETH": "renzo",
    "PUFFER": "puffer-finance", "KELP": "kelp-dao", "SWELL": "swell",
    "RSETH": "kelp-dao", "BEAM": "beam-2", "GNO": "gnosis",
    "XEC": "ecash", "IOTA": "iota", "QTUM": "qtum",
    "KSM": "kusama", "SRM": "serum", "CVC": "civic",
    "BAT": "basic-attention-token", "ZRX": "0x", "MANA": "decentraland",
    "SAND": "the-sandbox", "CHZ": "chiliz", "HOT": "holotoken",
    "SC": "siacoin", "STORJ": "storj", "ANKR": "ankr",
    "COTI": "coti", "SKL": "skale", "CELR": "celer-network",
    "OCEAN": "ocean-protocol", "NMR": "numeraire", "REQ": "request-network",
    "MTL": "metal", "LOOM": "loom-network", "DENT": "dent",
    "POWR": "power-ledger", "KIN": "kin", "SOLVE": "solve-care",
    "STMX": "stormx", "BTT": "bittorrent", "WIN": "wink",
    "CHR": "chromaway", "UOS": "ultra", "TEL": "telcoin",
    "RSR": "reserve-rights-token", "SXP": "swipe", "WAVES": "waves",
    "ONT": "ontology", "NANO": "nano", "RVN": "ravencoin",
    "FIRO": "firo", "DGB": "digibyte", "XVG": "verge",
    "CKB": "nervos-network", "AIOZ": "aioz-network", "CTSI": "cartesi",
    "YGG": "yield-guild-games", "MC": "merit-circle", "BEND": "benji-bananas",
    "GMT": "green-metaverse-token", "ACE": "aceminers", "SPL": "splinterlands",
    "ENJ": "enjincoin", "DERC": "derace", "DEAP": "deapcoin",
    "ALICE": "my-neighbor-alice", "TLM": "alien-worlds", "ATLAS": "star-atlas",
    "AI16Z": "ai16z", "AIXBT": "aixbt", "VIRTUAL": "virtual-protocol",
    "PHB": "phoenix-2", "LUNA": "terra-luna-2", "BOME": "book-of-meme",
    "MOG": "mog-coin", "POPCAT": "popcat", "SPX": "spx6900",
    "GIGA": "gigachad-2", "TURBO": "turbo", "MEME": "memecoin",
    "PENGU": "pudgy-penguins", "SQUIDGROW": "squidgrow", "BABYDOGE": "baby-doge-coin",
    "ELON": "dogelon-mars", "TOSHI": "toshi", "NEIRO": "neiro-on-ethereum",
    "BRETT": "based-brett",
}

# DeFiLlama protocol slug mapping (ticker -> protocol slug) - expanded
DEFILLAMA_SLUG_MAP: Dict[str, str] = {
    "UNI": "uniswap", "AAVE": "aave", "CRV": "curve", "LDO": "lido",
    "MKR": "makerdao", "SNX": "synthetix", "COMP": "compound",
    "SUSHI": "sushi", "CAKE": "pancakeswap", "GMX": "gmx",
    "PENDLE": "pendle", "ENA": "ethena", "JUP": "jupiter-aggregator",
    "RAY": "raydium", "ORCA": "orca", "BAL": "balancer",
    "DYDX": "dydx", "GNS": "gains-network", "JOE": "joe",
    "MAV": "maverick-protocol", "VELO": "velodrome", "COW": "cow-protocol",
    "1INCH": "1inch", "BNT": "bancor", "PERP": "perpetual-protocol",
    "MORPHO": "morpho", "AEVO": "aevo", "PRISMA": "prisma",
    "LBR": "lybra", "INST": "instadapp", "RDNT": "radiant",
    "FXS": "frax-share", "OHM": "olympus", "SPELL": "abracadabra",
    "YFI": "yearn-finance", "CVX": "convex-finance", "BIFI": "beefy-finance",
    "ALCX": "alchemix", "TOKE": "tokemak", "FIS": "stafi",
    "OSMO": "osmosis", "KNC": "kyber", "DODO": "dodo",
    "APEX": "apex", "THOR": "thorchain", "SYN": "synapse",
    "STG": "stargate", "ACX": "across", "HOP": "hop",
    "LUSD": "liquity", "MIM": "magic-internet-money", "FRAX": "frax",
    "RAI": "reflexer", "GRAI": "grai", "CUSD": "celo-dollar",
    "EIGEN": "eigenlayer", "KAVA": "kava", "BEND": "benddao",
    "EZETH": "renzo", "ETHFI": "ether.fi", "PUFFER": "puffer-finance",
    "KELP": "kelp-dao", "SWELL": "swell", "RSETH": "kelp-dao",
    "USDE": "ethena", "SUSDE": "ethena", "USD0": "usual",
    "GHO": "aave-v3", "CRVUSD": "crvusd", "DYAD": "dyad",
}

# Token category classification (CoinGecko category -> our taxonomy)
CATEGORY_TAXONOMY: Dict[str, str] = {
    "decentralized-exchange": "defi",
    "decentralized-finance-defi": "defi",
    "lending-borrowing": "defi",
    "yield-farming": "defi",
    "liquid-staking": "defi",
    "liquid-staking-derivatives": "defi",
    "automated-market-maker-amm": "defi",
    "defi-2": "defi",
    "defi-3": "defi",
    "synthetic-issuer": "defi",
    "meme": "meme",
    "meme-token": "meme",
    "dog-themed": "meme",
    "cat-themed": "meme",
    "layer-1": "l1",
    "layer-2": "l2",
    "zero-knowledge-rollups": "l2",
    "optimistic-rollups": "l2",
    "modular-blockchain": "l1",
    "gaming": "gaming",
    "play-to-earn": "gaming",
    "metaverse": "gaming",
    "artificial-intelligence": "ai",
    "ai-meme": "ai",
    "depin": "infra",
    "oracle": "infra",
    "cross-chain": "infra",
    "interoperability": "infra",
    "storage": "infra",
    "data-availability": "infra",
    "real-world-assets": "rwa",
    "stablecoin": "stablecoin",
    "wrapped-token": "wrapped",
    "dex": "defi",
}

# Hand-curated hard categorization for top tokens (fallback when CoinGecko unavailable)
# Expanded to 200+ tokens for broad coverage across all sectors
HARD_CATEGORIES: Dict[str, str] = {
    # Store of Value
    "BTC": "store_of_value", "WBTC": "wrapped", "CBTC": "wrapped",

    # Layer 1
    "ETH": "l1", "SOL": "l1", "BNB": "l1", "AVAX": "l1", "ADA": "l1", "DOT": "l1",
    "NEAR": "l1", "ATOM": "l1", "APT": "l1", "SUI": "l1", "SEI": "l1", "INJ": "l1",
    "FTM": "l1", "ALGO": "l1", "TRX": "l1", "XLM": "l1", "VET": "l1", "XRP": "l1",
    "ETC": "l1", "HBAR": "l1", "TON": "l1", "KAS": "l1", "ICP": "l1", "XTZ": "l1",
    "NEO": "l1", "EOS": "l1", "FLOW": "l1", "ROSE": "l1", "MINA": "l1", "CELO": "l1",
    "ONE": "l1", "CRO": "l1", "KAVA": "l1", "MNT": "l1", "BEAM": "l1", "GNO": "l1",
    "XEC": "l1", "IOTA": "l1", "QTUM": "l1", "KSM": "l1", "SRM": "l1",
    "WAVES": "l1", "ONT": "l1", "NANO": "l1", "RVN": "l1", "FIRO": "l1",
    "DGB": "l1", "XVG": "l1", "CKB": "l1", "BCH": "l1", "LTC": "l1",
    "DASH": "l1", "ZEC": "l1", "XMR": "l1", "BSV": "l1",

    # Layer 2
    "MATIC": "l2", "POL": "l2", "ARB": "l2", "OP": "l2", "STRK": "l2", "ZKSYNC": "l2",
    "MANTA": "l2", "BLAST": "l2", "METIS": "l2", "IMX": "l2", "STARK": "l2",
    "BOBA": "l2", "LOOKS": "l2", "ZRO": "l2", "ZETA": "l2", "W": "l2",
    "CANTO": "l2", "NTRN": "l2", "STRD": "l2", "OMNI": "l2",

    # DeFi - DEX
    "UNI": "defi", "SUSHI": "defi", "CAKE": "defi", "RAY": "defi", "ORCA": "defi",
    "JUP": "defi", "BAL": "defi", "VELO": "defi", "COW": "defi", "1INCH": "defi",
    "DODO": "defi", "JOE": "defi", "GMX": "defi", "DYDX": "defi", "APEX": "defi",
    "GNS": "defi", "SNX": "defi", "PERP": "defi", "BNT": "defi", "THOR": "defi",
    "MAV": "defi", "SYN": "defi", "STG": "defi", "ACX": "defi", "HOP": "defi",
    "KNC": "defi", "ZIP": "defi",

    # DeFi - Lending
    "AAVE": "defi", "COMP": "defi", "MKR": "defi", "CRV": "defi", "LDO": "defi",
    "PENDLE": "defi", "ENA": "defi", "EIGEN": "defi", "MORPHO": "defi", "AEVO": "defi",
    "PRISMA": "defi", "LBR": "defi", "INST": "defi", "RDNT": "defi", "GRAI": "defi",
    "FXS": "defi", "FRAX": "defi", "LUSD": "defi", "RAI": "defi", "OHM": "defi",
    "SPELL": "defi", "MIM": "defi", "BEND": "defi", "EZETH": "defi",
    "ETHFI": "defi", "PUFFER": "defi", "KELP": "defi", "SWELL": "defi", "RSETH": "defi",
    "USDE": "defi", "SUSDE": "defi", "USD0": "defi", "GHO": "defi", "CRVUSD": "defi",
    "DYAD": "defi", "USDX": "defi",

    # DeFi - Yield
    "YFI": "defi", "CVX": "defi", "BIFI": "defi", "ALCX": "defi", "TOKE": "defi",
    "FIS": "defi", "STETH": "defi", "RETH": "defi", "SETH2": "defi", "ANKRETH": "defi",
    "SWETH": "defi", "CBETH": "defi", "METH": "defi", "OSETH": "defi",
    "OSMO": "defi", "CUSD": "defi",

    # Infrastructure / Oracles
    "LINK": "infra", "GRT": "infra", "FIL": "infra", "AR": "infra", "TIA": "infra",
    "RNDR": "infra", "FET": "infra", "AGIX": "infra", "TAO": "infra", "WLD": "infra",
    "AKT": "infra", "HNT": "infra", "POND": "infra", "NOIA": "infra", "API3": "infra",
    "BAND": "infra", "UMA": "infra", "DIA": "infra", "TRB": "infra", "PYTH": "infra",
    "RED": "infra", "AXL": "infra", "LPT": "infra", "AIOZ": "infra", "CTSI": "infra",
    "CVC": "infra", "BAT": "infra", "ZRX": "infra", "STORJ": "infra", "ANKR": "infra",
    "SKL": "infra", "OCEAN": "infra", "REQ": "infra", "MTL": "infra", "LOOM": "infra",
    "DENT": "infra", "POWR": "infra", "KIN": "infra", "SOLVE": "infra", "STMX": "infra",
    "BTT": "infra", "WIN": "infra", "CHR": "infra", "TEL": "infra", "RSR": "infra",
    "SXP": "infra", "CHZ": "infra", "HOT": "infra", "SC": "infra",

    # AI
    "RENDER": "ai", "FET": "ai", "AGIX": "ai", "TAO": "ai", "WLD": "ai", "LPT": "ai",
    "OCEAN": "ai", "NMR": "ai", "BTRST": "ai", "AI16Z": "ai", "AIXBT": "ai",
    "VIRTUAL": "ai", "LUNA": "ai", "PHB": "ai",

    # Gaming / Metaverse
    "SAND": "gaming", "MANA": "gaming", "AXS": "gaming", "GALA": "gaming", "ILV": "gaming",
    "IMX": "gaming", "PRIME": "gaming", "YGG": "gaming", "MC": "gaming", "BEND": "gaming",
    "GMT": "gaming", "ACE": "gaming", "SPL": "gaming", "ENJ": "gaming", "UOS": "gaming",
    "DERC": "gaming", "DEAP": "gaming", "ALICE": "gaming", "TLM": "gaming", "ATLAS": "gaming",

    # RWA
    "ONDO": "rwa", "CFG": "rwa", "MPL": "rwa", "TRU": "rwa", "GFI": "rwa", "RBN": "rwa",
    "POLYX": "rwa", "CANTO": "rwa", "RIO": "rwa", "NXRA": "rwa", "LEOX": "rwa",
    "EKTA": "rwa", "LAND": "rwa", "PROPS": "rwa", "CPOOL": "rwa", "HMT": "rwa",

    # Stablecoins
    "USDT": "stablecoin", "USDC": "stablecoin", "DAI": "stablecoin", "USDD": "stablecoin",
    "FRAX": "stablecoin", "TUSD": "stablecoin", "BUSD": "stablecoin", "PYUSD": "stablecoin",
    "USDJ": "stablecoin", "USDP": "stablecoin", "GUSD": "stablecoin", "LUSD": "stablecoin",
    "MAI": "stablecoin", "MIM": "stablecoin", "USDX": "stablecoin", "USDE": "stablecoin",
    "SUSD": "stablecoin", "CUSD": "stablecoin", "CRVUSD": "stablecoin", "GHO": "stablecoin",
    "DYAD": "stablecoin", "USD0": "stablecoin", "SUSDE": "stablecoin",

    # Wrapped / Liquid Staking
    "WBTC": "wrapped", "WETH": "wrapped", "STETH": "wrapped", "RETH": "wrapped",
    "CBETH": "wrapped", "METH": "wrapped", "OSETH": "wrapped", "SWETH": "wrapped",
    "ANKRETH": "wrapped", "SETH2": "wrapped", "EZETH": "wrapped", "ETHFI": "wrapped",
    "PUFFER": "wrapped", "KELP": "wrapped", "RSETH": "wrapped", "SWELL": "wrapped",

    # Meme
    "DOGE": "meme", "SHIB": "meme", "PEPE": "meme", "WIF": "meme", "BONK": "meme",
    "FLOKI": "meme", "BOME": "meme", "MOG": "meme", "POPCAT": "meme", "SPX": "meme",
    "GIGA": "meme", "TURBO": "meme", "MEME": "meme", "PENGU": "meme",
    "SQUIDGROW": "meme", "BABYDOGE": "meme", "ELON": "meme", "TOSHI": "meme",
    "NEIRO": "meme", "BRETT": "meme",

    # Cross-chain / Bridges
    "W": "infra", "ZRO": "infra", "SYN": "infra", "STG": "infra", "ACX": "infra",
    "HOP": "infra", "NTRN": "infra", "STRD": "infra", "ZETA": "infra", "OMNI": "infra",
    "AXL": "infra", "WORMHOLE": "infra",

    # Additional top coins
    "BEAM": "gaming", "GNO": "defi", "XEC": "l1", "IOTA": "infra", "QTUM": "l1",
    "KSM": "l1", "SRM": "defi", "CVC": "infra", "BAT": "infra", "ZRX": "defi",
    "MANA": "gaming", "SAND": "gaming", "CHZ": "gaming", "HOT": "infra", "SC": "infra",
    "STORJ": "infra", "ANKR": "infra", "COTI": "infra", "SKL": "infra", "CELR": "infra",
    "OCEAN": "ai", "NMR": "ai", "REQ": "infra", "MTL": "infra", "LOOM": "infra",
    "DENT": "infra", "POWR": "infra", "KIN": "infra", "SOLVE": "infra", "STMX": "infra",
    "BTT": "infra", "WIN": "infra", "COTI": "infra", "CHR": "infra", "UOS": "gaming",
    "TEL": "infra", "RSR": "stablecoin", "SXP": "infra", "WAVES": "l1", "ONT": "l1",
    "NANO": "l1", "RVN": "l1", "FIRO": "l1", "DGB": "l1", "XVG": "l1", "CKB": "l1",
    "AIOZ": "ai", "CTSI": "ai", "YGG": "gaming", "MC": "gaming", "BEND": "gaming",
    "GMT": "gaming", "ACE": "gaming", "SPL": "gaming", "ENJ": "gaming", "DERC": "gaming",
    "DEAP": "gaming", "ALICE": "gaming", "TLM": "gaming", "ATLAS": "gaming",
    "AI16Z": "ai", "AIXBT": "ai", "VIRTUAL": "ai", "PHB": "ai", "LUNA": "l1",
    "BOME": "meme", "MOG": "meme", "POPCAT": "meme", "SPX": "meme", "GIGA": "meme",
    "TURBO": "meme", "MEME": "meme", "PENGU": "meme", "SQUIDGROW": "meme",
    "BABYDOGE": "meme", "ELON": "meme", "TOSHI": "meme", "NEIRO": "meme", "BRETT": "meme",
    "RUNE": "defi", "DYDX": "defi", "APEX": "defi", "GNS": "defi", "PERP": "defi",
    "MAV": "defi", "COW": "defi", "1INCH": "defi", "THOR": "defi", "SYN": "defi",
    "STG": "defi", "ACX": "defi", "HOP": "defi", "KNC": "defi", "ZIP": "defi",
    "MORPHO": "defi", "AEVO": "defi", "PRISMA": "defi", "LBR": "defi", "INST": "defi",
    "RDNT": "defi", "GRAI": "defi", "FXS": "defi", "OHM": "defi", "SPELL": "defi",
    "MIM": "defi", "OSMO": "defi", "CVX": "defi", "BIFI": "defi", "ALCX": "defi",
    "TOKE": "defi", "FIS": "defi", "EIGEN": "defi", "PENDLE": "defi", "ENA": "defi",
    "ONDO": "rwa", "CFG": "rwa", "MPL": "rwa", "TRU": "rwa", "GFI": "rwa", "RBN": "rwa",
    "POLYX": "rwa", "RIO": "rwa", "NXRA": "rwa", "LEOX": "rwa", "EKTA": "rwa",
    "LAND": "rwa", "PROPS": "rwa", "CPOOL": "rwa", "HMT": "rwa",
    "USDD": "stablecoin", "TUSD": "stablecoin", "BUSD": "stablecoin", "PYUSD": "stablecoin",
    "USDJ": "stablecoin", "USDP": "stablecoin", "GUSD": "stablecoin", "MAI": "stablecoin",
    "SUSD": "stablecoin", "USDX": "stablecoin", "CRVUSD": "stablecoin", "GHO": "stablecoin",
    "DYAD": "stablecoin", "USD0": "stablecoin", "SUSDE": "stablecoin",
    "PUFFER": "wrapped", "KELP": "wrapped", "RSETH": "wrapped", "SWELL": "wrapped",
    "ETHFI": "wrapped", "EZETH": "wrapped", "CBETH": "wrapped", "METH": "wrapped",
    "OSETH": "wrapped", "SWETH": "wrapped", "ANKRETH": "wrapped", "SETH2": "wrapped",

    # v2.2 extended — 190 additional token categories
    "ACA": "defi", "AERODROME": "defi", "AGI": "ai", "AIDOGE": "meme",
    "AKITA": "meme", "AKRO": "defi", "ALU": "gaming", "AMC": "meme",
    "ANC": "defi", "APESWAP": "defi", "ARMOR": "defi", "ASTR": "l1",
    "ASTRO": "defi", "BABYSWAP": "defi", "BADGER": "defi", "BANANA": "defi",
    "BASESWAP": "defi", "BCOIN": "gaming", "BIFROST": "infra", "BISWAP": "defi",
    "BLOK": "gaming", "BLUR": "defi", "BNC": "infra", "BOMB": "gaming",
    "BRKL": "infra", "BSX": "defi", "C98": "infra", "CAT": "meme",
    "CEEK": "gaming", "CELT": "gaming", "CLV": "l1", "CND": "ai",
    "COMAI": "ai", "COMETH": "gaming", "CREAM": "defi", "CRU": "infra",
    "CUMMIES": "meme", "DAR": "gaming", "DARK": "gaming", "DATA": "infra",
    "DBC": "ai", "DFYN": "defi", "DHT": "defi", "DINGER": "meme",
    "DOME": "gaming", "DORA": "infra", "DPI": "defi", "DVF": "defi",
    "DYM": "l1", "EDG": "l1", "EDGE": "infra", "EQ": "l1",
    "EQUAL": "defi", "ERD": "l1", "ERIS": "defi", "FINE": "infra",
    "FLR": "l1", "FLUX": "infra", "FORTUNE": "defi", "FVM": "infra",
    "GAL": "infra", "GALXE": "infra", "GAMMA": "defi", "GEIST": "defi",
    "GHST": "gaming", "GLMR": "l1", "GME": "meme", "HACHI": "meme",
    "HARD": "defi", "HEGIC": "defi", "HERO": "gaming", "HFT": "defi",
    "HOGE": "meme", "HOTCROSS": "defi", "HYDRA": "defi", "IDEX": "defi",
    "IIC": "ai", "INDEX": "defi", "INTR": "l1", "INU": "meme",
    "IOTX": "l1", "KAR": "l1", "KEEP": "infra", "KILT": "l1",
    "KINT": "l2", "KISHU": "meme", "KITTY": "meme", "KNIGHT": "defi",
    "LEASH": "meme", "LOOP": "defi", "LSS": "infra", "LUNC": "l1",
    "MAN": "ai", "MARS": "defi", "MIR": "defi", "MIX": "gaming",
    "MLN": "defi", "MOBOX": "gaming", "MONA": "meme", "MONG": "meme",
    "NFTX": "defi", "NU": "infra", "ORAI": "infra", "PARA": "defi",
    "PCX": "l1", "PHA": "infra", "PHALA": "infra", "PICKLE": "defi",
    "PIT": "meme", "POOL": "defi", "PSWAP": "defi", "QUICK": "defi",
    "RACA": "gaming", "RAMSES": "defi", "REP": "defi", "RENA": "gaming",
    "RENZO": "wrapped", "REVV": "gaming", "RHYTHM": "meme", "RING": "l1",
    "ROOK": "defi", "SAFUU": "defi", "SAITAMA": "meme", "SAMO": "meme",
    "SAGA": "l1", "SALE": "defi", "SBY": "infra", "SCREAM": "defi",
    "SD": "defi", "SDN": "l2", "SGB": "l1", "SOLIDLY": "defi",
    "SONIC": "defi", "SOUL": "l1", "SPECTRE": "ai", "SPIRIT": "defi",
    "SPS": "gaming", "STAR": "gaming", "STAKE": "defi", "SYS": "l1",
    "TBTC": "wrapped", "TITANO": "defi", "TOMB": "defi", "TRADE": "defi",
    "TRAC": "infra", "TUR": "infra", "TVK": "gaming", "UFO": "gaming",
    "USD0": "stablecoin", "VAIOT": "ai", "VARI": "infra", "VENUS": "defi",
    "VITE": "l1", "VORTEX": "defi", "VS": "defi", "VTHO": "l1",
    "WAULT": "defi", "WEMIX": "l1", "WND": "defi", "WOJAK": "meme",
    "WOZX": "l1", "WSB": "meme", "XAI": "ai", "XOR": "l1",
    "XRT": "infra", "XVS": "defi", "XWG": "gaming", "ZEN": "l1",
    # v2.2 additions (missing from CG map)
    "Ethena": "defi", "MOON": "l1", "MOVR": "l1", "MVI": "defi",
    "NFTB": "infra", "NKN": "infra", "PANCAKE": "defi", "PEOPLE": "meme",
    "POLYDEX": "defi", "POND0": "infra", "PRISM": "defi", "PSI": "defi",
    "QOM": "meme", "RPL": "wrapped", "SDX": "stablecoin", "SPOOKY": "defi",
    "STEAK": "defi", "SWP": "defi", "Swell": "wrapped", "THG": "gaming",
    "TSUKA": "meme", "TWT": "infra", "USTC": "stablecoin", "VAI": "stablecoin",
    "VAL": "l1", "WBOND": "defi", "WEX": "defi", "WHALE": "defi",
}


# =========================================================================
#  Network Environment Detection
# =========================================================================

def _detect_network_environment() -> str:
    """Detect whether we're behind the Great Firewall (China network).

    Tests connectivity to Binance (typically blocked in China) vs Gate (accessible).
    Uses progressive timeouts (3s → 5s) for resilience.

    Returns:
        "china" if Binance/Bybit are unreachable, "global" otherwise.
    """
    results: Dict[str, bool] = {}

    # Progressive timeouts for resilience
    for timeout in [3, 5]:
        for label, host, port in [
            ("binance_api", "api.binance.com", 443),
            ("bybit_api", "api.bybit.com", 443),
            ("gate_api", "api.gateio.ws", 443),
            ("coingecko", "api.coingecko.com", 443),
        ]:
            if label in results:
                continue
            try:
                sock = socket.create_connection((host, port), timeout=timeout)
                sock.close()
                results[label] = True
            except (socket.timeout, ConnectionRefusedError, OSError):
                results[label] = False

    global_reachable = results.get("binance_api", False) or results.get("bybit_api", False)
    china_reachable = results.get("gate_api", False)
    cg_reachable = results.get("coingecko", False)

    if global_reachable and not china_reachable:
        return "global"
    if china_reachable and not global_reachable:
        env = "china"
        if not cg_reachable:
            logger.info("China network detected. CoinGecko may be slow. Using Gate/OKX primary.")
        return env
    if global_reachable and china_reachable:
        return "global"  # Prefer global when both available
    # Both unreachable or network issues
    logger.warning("Network detection inconclusive (all endpoints unreachable), defaulting to global with Gate fallback.")
    return "global"


# Cache network environment for the session
_NETWORK_ENV: Optional[str] = None


def get_network_env() -> str:
    """Get cached network environment detection result."""
    global _NETWORK_ENV
    if _NETWORK_ENV is None:
        _NETWORK_ENV = _detect_network_environment()
        logger.info("Network environment: %s", _NETWORK_ENV)
    return _NETWORK_ENV


# =========================================================================
#  Exchange Ticker Fallback (for unknown / unsupported tokens)
# =========================================================================

def _get_exchange_ticker_data(symbol: str) -> Dict[str, Any]:
    """Fetch ticker data from ccxt exchange as fallback for unknown tokens.

    This provides basic price, 24h change, volume data for ANY token
    listed on supported exchanges, even when CoinGecko has no entry.

    Args:
        symbol: Trading pair, e.g. "BTC/USDT".

    Returns:
        Dict with price, change_24h_pct, volume_24h, source, status, message.
        Returns empty dict with status="failed" if all exchanges fail.
    """
    env = get_network_env()
    exchanges_to_try = []
    if env == "global":
        exchanges_to_try = ["binance", "bybit", "gate"]
    else:
        exchanges_to_try = ["gate", "okx", "binance"]

    # Progressive timeouts for resilience: 5s → 8s → 15s
    for attempt, timeout_ms in enumerate([5_000, 8_000, 15_000], start=1):
        for ex_name in exchanges_to_try:
            try:
                ex = getattr(ccxt, ex_name)({
                    "enableRateLimit": True,
                    "timeout": timeout_ms,
                })
                ex.load_markets()
                if symbol not in ex.markets:
                    continue
                ticker = ex.fetch_ticker(symbol)
                if ticker and ticker.get("last"):
                    return {
                        "price": _s(ticker.get("last")),
                        "change_24h_pct": _s(ticker.get("percentage")),
                        "volume_24h": _s(ticker.get("quoteVolume", ticker.get("baseVolume"))),
                        "high_24h": _s(ticker.get("high")),
                        "low_24h": _s(ticker.get("low")),
                        "bid": _s(ticker.get("bid")),
                        "ask": _s(ticker.get("ask")),
                        "source": ex_name,
                        "status": "success",
                        "message": f"Exchange data from {ex_name} (attempt {attempt}, timeout {timeout_ms}ms). CoinGecko may be unavailable.",
                    }
            except Exception as e:
                logger.debug("Ticker fetch failed on %s for %s (attempt %d): %s", ex_name, symbol, attempt, e)
                continue

    return {
        "status": "failed",
        "message": (
            "Unable to fetch any data for this token after 3 attempts with progressive timeouts. "
            "Possible reasons: (1) The token is not listed on supported exchanges (Binance, Bybit, Gate, OKX); "
            "(2) Network connection is unstable or blocked; "
            "(3) The symbol code may be incorrect (e.g., 'PEOPLE' vs 'PEOPLES'). "
            "Please verify the symbol and try again."
        ),
        "guidance": "If you believe this token exists, try checking the exact symbol on CoinMarketCap or the exchange directly.",
    }


# =========================================================================
#  CoinGecko API Client
# =========================================================================

def _cg_request(endpoint: str, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Make a rate-limited request to the CoinGecko API with progressive retries.

    Uses progressive timeouts (10s → 15s → 20s) for resilience on slow networks.

    Args:
        endpoint: API path (e.g. "/coins/bitcoin").
        params: Optional query parameters.

    Returns:
        Parsed JSON response dict, or None on error.
    """
    global _last_cg_request

    # Rate limiting
    elapsed = time.time() - _last_cg_request
    if elapsed < COINGECKO_RATE_LIMIT:
        time.sleep(COINGECKO_RATE_LIMIT - elapsed)

    url = f"{COINGECKO_BASE}{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"

    # Progressive timeouts: 10s → 15s → 20s
    for attempt, timeout in enumerate([10, 15, 20], start=1):
        try:
            req = Request(url, headers={"User-Agent": "CryptoQuant/2.2", "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                _last_cg_request = time.time()
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except HTTPError as e:
            logger.warning("CoinGecko HTTP %s for %s (attempt %d): %s", e.code, endpoint, attempt, e.reason)
            if e.code == 429:  # Rate limited
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            return None
        except (URLError, socket.timeout) as e:
            logger.warning("CoinGecko request failed for %s (attempt %d, timeout %ds): %s", endpoint, attempt, timeout, e)
            if attempt < 3:
                time.sleep(1.5)
                continue
            return None
        except json.JSONDecodeError as e:
            logger.warning("CoinGecko JSON decode error for %s: %s", endpoint, e)
            return None

    return None


def cg_get_coin_id(ticker: str) -> Optional[str]:
    """Map a crypto ticker to its CoinGecko coin ID.

    Uses hardcoded mapping first, falls back to CoinGecko search API.

    Args:
        ticker: e.g. "BTC", "ETH", "SPK".

    Returns:
        CoinGecko ID string (e.g. "bitcoin"), or None if not found.
    """
    upper = ticker.upper().replace("/USDT", "").strip()

    # Try hardcoded mapping
    if upper in COINGECKO_ID_MAP:
        return COINGECKO_ID_MAP[upper]

    # Fall back to CoinGecko search
    result = _cg_request("/search", {"query": upper})
    if result and "coins" in result and result["coins"]:
        # Find exact symbol match
        for coin in result["coins"]:
            if coin.get("symbol", "").upper() == upper:
                coin_id = coin.get("id")
                if coin_id:
                    COINGECKO_ID_MAP[upper] = coin_id  # Cache for next time
                    return coin_id

    return None


def cg_get_coin_data(coin_id: str) -> Optional[Dict[str, Any]]:
    """Get comprehensive coin data from CoinGecko.

    Includes: market data, categories, description, links, community data.
    """
    return _cg_request(
        f"/coins/{coin_id}",
        {
            "localization": "false",
            "tickers": "false",
            "community_data": "true",
            "developer_data": "true",
        },
    )


def cg_get_market_chart(coin_id: str, days: str = "90", vs_currency: str = "usd") -> Optional[Dict[str, Any]]:
    """Get historical market data (price, market cap, volume)."""
    return _cg_request(
        f"/coins/{coin_id}/market_chart",
        {"vs_currency": vs_currency, "days": days},
    )


def cg_get_simple_price(coin_ids: List[str], vs_currencies: str = "usd") -> Optional[Dict[str, Any]]:
    """Get simple current price for multiple coins."""
    ids_str = ",".join(coin_ids)
    return _cg_request(
        "/simple/price",
        {"ids": ids_str, "vs_currencies": vs_currencies, "include_24hr_change": "true",
         "include_market_cap": "true", "include_24hr_vol": "true"},
    )


def cg_get_trending() -> Optional[Dict[str, Any]]:
    """Get trending coins on CoinGecko."""
    return _cg_request("/search/trending")


# =========================================================================
#  DeFiLlama API Client
# =========================================================================

def _dl_request(endpoint: str) -> Optional[Any]:
    """Make a request to the DeFiLlama API (free, no rate limit for basic use).

    Args:
        endpoint: API path (e.g. "/protocols").

    Returns:
        Parsed JSON response, or None on error.
    """
    url = f"https://api.llama.fi{endpoint}"
    try:
        req = Request(url, headers={"User-Agent": "CryptoQuant/2.0", "Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, socket.timeout, json.JSONDecodeError, HTTPError) as e:
        logger.warning("DeFiLlama request failed for %s: %s", endpoint, e)
        return None


def dl_get_protocol_tvl(slug: str) -> Optional[Dict[str, Any]]:
    """Get TVL data for a DeFi protocol.

    Args:
        slug: DeFiLlama protocol slug (e.g. "uniswap", "aave").

    Returns:
        Dict with tvl, chainTvls, tokens, etc., or None.
    """
    return _dl_request(f"/protocol/{slug}")


def dl_get_protocol_fees(slug: str, data_type: str = "dailyFees") -> Optional[Dict[str, Any]]:
    """Get fee/revenue data for a protocol.

    Args:
        slug: DeFiLlama protocol slug.
        data_type: "dailyFees", "dailyRevenue", "totalFees", etc.
    """
    return _dl_request(f"/summary/fees/{slug}?dataType={data_type}")


def dl_get_chain_tvl(chain: str) -> Optional[float]:
    """Get total TVL for a blockchain.

    Args:
        chain: Chain name (e.g. "Ethereum", "Solana").
    """
    result = _dl_request(f"/v2/chains")
    if result and isinstance(result, list):
        for c in result:
            if c.get("name", "").lower() == chain.lower():
                return float(c.get("tvl", 0))
    return None


def dl_get_protocol_slug(ticker: str) -> Optional[str]:
    """Map a ticker to DeFiLlama protocol slug."""
    upper = ticker.upper().replace("/USDT", "").strip()
    return DEFILLAMA_SLUG_MAP.get(upper)


# =========================================================================
#  Data Cross-Validation
# =========================================================================

def cross_validate_price(sources: Dict[str, Optional[float]],
                         threshold: float = CROSS_VALIDATION_THRESHOLD) -> Dict[str, Any]:
    """Cross-validate price data from multiple sources.

    Args:
        sources: Dict mapping source name to price value, e.g.
                 {"coingecko": 68000.50, "binance": 67950.00, "gate": 68020.00}.
                 None values are skipped.
        threshold: Maximum acceptable deviation (fraction). Default 0.02 (2%).

    Returns:
        Dict with keys:
        - validated_price: median of all valid prices
        - max_deviation_pct: maximum percentage deviation between any two sources
        - deviations: list of (source1, source2, deviation_pct) for each pair
        - is_reliable: True if max deviation < threshold
        - warning: warning message if unreliable
        - source_count: number of valid sources
    """
    valid_sources = {k: v for k, v in sources.items() if v is not None and v > 0}

    if len(valid_sources) < 2:
        single_price = list(valid_sources.values())[0] if valid_sources else None
        return {
            "validated_price": single_price,
            "max_deviation_pct": 0.0,
            "deviations": [],
            "is_reliable": len(valid_sources) >= 1,
            "warning": "Only one data source available, cannot cross-validate." if valid_sources else "No valid price data.",
            "source_count": len(valid_sources),
        }

    prices = list(valid_sources.values())
    names = list(valid_sources.keys())
    median_price = float(np.median(prices))
    deviations: List[Dict[str, Any]] = []
    max_dev = 0.0

    for i in range(len(prices)):
        for j in range(i + 1, len(prices)):
            dev = abs(prices[i] - prices[j]) / ((prices[i] + prices[j]) / 2)
            max_dev = max(max_dev, dev)
            deviations.append({
                "source_a": names[i],
                "source_b": names[j],
                "price_a": round(prices[i], 4),
                "price_b": round(prices[j], 4),
                "deviation_pct": round(dev * 100, 2),
            })

    is_reliable = max_dev < threshold
    warning = ""
    if not is_reliable:
        warning = (
            f"WARNING: Price deviation between sources is {round(max_dev * 100, 2)}%, "
            f"exceeding the {round(threshold * 100, 1)}% threshold. "
            f"Data may be stale or from different liquidity pools. "
            f"Using median price ({round(median_price, 2)}) as best estimate."
        )

    return {
        "validated_price": round(median_price, 4),
        "max_deviation_pct": round(max_dev * 100, 2),
        "deviations": deviations,
        "is_reliable": is_reliable,
        "warning": warning,
        "source_count": len(valid_sources),
    }


# =========================================================================
#  Token Category Detection
# =========================================================================

def detect_category(ticker: str) -> Dict[str, Any]:
    """Detect the category of a crypto token.

    Uses CoinGecko API when available, falls back to hardcoded mapping.

    Returns:
        Dict with keys: category, subcategory, confidence, source.
        category is one of: defi, meme, l1, l2, gaming, ai, infra, rwa, stablecoin, other.
    """
    upper = ticker.upper().replace("/USDT", "").strip()

    # Try CoinGecko for rich categorization
    coin_id = cg_get_coin_id(upper) if upper != "BTC" else "bitcoin"
    if coin_id and coin_id != COINGECKO_ID_MAP.get(upper):
        coin_data = cg_get_coin_data(coin_id)
        if coin_data and "categories" in coin_data:
            categories = coin_data.get("categories", [])
            if categories:
                # Map CoinGecko categories to our taxonomy
                mapped = []
                for cat in categories:
                    cat_lower = cat.lower().replace(" ", "-")
                    if cat_lower in CATEGORY_TAXONOMY:
                        mapped.append(CATEGORY_TAXONOMY[cat_lower])
                if mapped:
                    # Pick the most specific category (first non-other)
                    for cat in mapped:
                        if cat != "other":
                            return {
                                "category": cat,
                                "subcategory": categories[0],
                                "confidence": "high",
                                "source": "coingecko",
                                "all_cg_categories": categories[:5],
                            }
                    return {
                        "category": mapped[0],
                        "subcategory": categories[0],
                        "confidence": "high",
                        "source": "coingecko",
                        "all_cg_categories": categories[:5],
                    }

    # Fall back to hardcoded mapping
    if upper in HARD_CATEGORIES:
        return {
            "category": HARD_CATEGORIES[upper],
            "subcategory": "",
            "confidence": "medium",
            "source": "hardcoded",
        }

    # Bitcoin is special
    if upper == "BTC":
        return {"category": "store_of_value", "subcategory": "digital_gold", "confidence": "high", "source": "hardcoded"}

    # Unknown token: provide helpful guidance instead of generic "other"
    return {
        "category": "unknown",
        "subcategory": "",
        "confidence": "low",
        "source": "unknown",
        "status": "token_not_in_database",
        "message": (
            f"Token '{upper}' is not in our current database of 200+ mapped tokens. "
            "Basic exchange-based analysis (price, volume, 24h change) will still be provided. "
            "For deeper fundamental analysis, the token may need to be added to the mapping or "
            "CoinGecko API must be accessible for auto-detection."
        ),
        "suggestion": "Check the symbol spelling or try a more common ticker (e.g., 'UNI' instead of 'UNISWAP').",
    }


def get_category_analysis_dimensions(category: str) -> Dict[str, Any]:
    """Get the recommended analysis dimensions for a token category.

    Args:
        category: One of: defi, meme, l1, l2, gaming, ai, infra, rwa, stablecoin, store_of_value, other.

    Returns:
        Dict with keys: required_metrics, optional_metrics, narrative_check, risk_factors.
    """
    DIMENSIONS = {
        "defi": {
            "required_metrics": ["tvl", "tvl_mc_ratio", "protocol_revenue", "fees_annualized", "unique_users"],
            "optional_metrics": ["treasury_value", "token_emissions", "governance_activity", "competitor_tvl_share"],
            "narrative_check": "Is the protocol generating sustainable revenue? TVL/MC ratio benchmark: >1.0 is undervalued.",
            "risk_factors": ["smart_contract_risk", "governance_attack", "liquidity_crunch", "regulatory_risk"],
        },
        "meme": {
            "required_metrics": ["social_volume", "holder_count", "holder_concentration", "exchange_listings", "age_days"],
            "optional_metrics": ["whale_transactions", "community_growth_rate", "narrative_strength"],
            "narrative_check": "Meme coins are narrative-driven. Key question: Is the community growing or shrinking? High holder concentration (>50% top 10) = rug risk.",
            "risk_factors": ["hype_cycle_decay", "whale_dump", "liquidity_drain", "team_anonymity"],
        },
        "l1": {
            "required_metrics": ["ecosystem_tvl", "daily_active_addresses", "tx_count", "developer_activity", "fee_generation"],
            "optional_metrics": ["nakamoto_coefficient", "validator_count", "institutional_adoption"],
            "narrative_check": "Layer 1 valuation is driven by ecosystem growth. Compare TVL/MC ratio vs peers.",
            "risk_factors": ["competition", "technology_risk", "community_fragmentation"],
        },
        "l2": {
            "required_metrics": ["tvl", "tx_count", "active_addresses", "l1_settlement_costs", "sequencer_revenue"],
            "optional_metrics": ["bridge_tvl", "unique_deployers", "ecosystem_project_count"],
            "narrative_check": "L2s compete on fees and ecosystem. Growing TVL + active addresses signals adoption.",
            "risk_factors": ["l1_dependency", "sequencer_centralization", "bridge_risk"],
        },
        "gaming": {
            "required_metrics": ["active_players", "in_game_volume", "land_nft_floor", "partnership_count"],
            "optional_metrics": ["retention_rate", "player_earnings", "guild_activity"],
            "narrative_check": "Gaming tokens derive value from actual player adoption, not speculation.",
            "risk_factors": ["player_churn", "token_inflation", "game_quality"],
        },
        "ai": {
            "required_metrics": ["market_cap", "github_activity", "narrative_correlation", "partnership_count"],
            "optional_metrics": ["compute_integration", "model_quality", "dev_ecosystem"],
            "narrative_check": "AI crypto tokens are highly narrative-driven. Check GitHub activity for real development.",
            "risk_factors": ["hype_cycle", "ai_washing", "centralization"],
        },
        "infra": {
            "required_metrics": ["integration_count", "data_request_volume", "network_revenue", "dev_activity"],
            "optional_metrics": ["node_count", "staking_ratio", "competitor_share"],
            "narrative_check": "Infrastructure value = network effects. Growing integration count is the key metric.",
            "risk_factors": ["competition", "commoditization", "low_barriers"],
        },
        "stablecoin": {
            "required_metrics": ["market_cap", "peg_stability", "collateral_ratio", "redemption_history"],
            "optional_metrics": ["depeg_events", "regulatory_status", "audit_quality"],
            "narrative_check": "Stablecoin analysis focuses on peg robustness and collateral quality.",
            "risk_factors": ["depeg_risk", "regulatory_action", "collateral_volatility"],
        },
        "store_of_value": {
            "required_metrics": ["stock_to_flow", "hash_rate", "realized_cap", "illiquid_supply"],
            "optional_metrics": ["miner_revenue", "active_addresses", "exchange_balances"],
            "narrative_check": "BTC as digital gold: focus on scarcity metrics and institutional adoption signals.",
            "risk_factors": ["regulatory", "competing_sov_narratives", "custodial_risk"],
        },
        "other": {
            "required_metrics": ["market_cap", "volume_24h", "price_trend", "volatility"],
            "optional_metrics": ["exchange_listings", "social_volume"],
            "narrative_check": "Generic analysis for uncategorized tokens. Deeper analysis requires manual review.",
            "risk_factors": ["low_liquidity", "unknown_fundamentals"],
        },
    }
    return DIMENSIONS.get(category, DIMENSIONS["other"])


# =========================================================================
#  Symbol Normalization (retained from v1.0)
# =========================================================================

def _normalize_symbol(symbol: str) -> str:
    """Normalize a crypto symbol to BASE/USDT format."""
    symbol = symbol.strip().upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    return symbol


def _normalize_symbols(symbols_raw: str) -> List[str]:
    """Normalize comma-separated symbol string."""
    return [_normalize_symbol(s.strip()) for s in symbols_raw.split(",") if s.strip()]


# =========================================================================
#  Exchange Factory (retained from v1.0, enhanced)
# =========================================================================

def _get_primary_exchanges() -> Tuple[str, str]:
    """Get primary and fallback exchange IDs based on network environment.

    Returns:
        (primary_exchange_id, fallback_exchange_id).
    """
    env = get_network_env()
    if env == "china":
        return (DEFAULT_EXCHANGE, FALLBACK_EXCHANGE)  # Gate -> OKX
    return (GLOBAL_EXCHANGE, GLOBAL_FALLBACK)          # Binance -> Bybit


def _get_exchange(primary: Optional[str] = None,
                   fallback: Optional[str] = None) -> ccxt.Exchange:
    """Create a ccxt exchange instance with automatic fallback and progressive timeouts.

    Auto-detects network environment to choose appropriate exchanges.
    Uses progressive timeouts (5s → 10s) for resilience on unstable networks.

    Args:
        primary: Override primary exchange ID. If None, auto-detected.
        fallback: Override fallback exchange ID. If None, auto-detected.

    Returns:
        A connected ccxt.Exchange with markets loaded.

    Raises:
        RuntimeError: If all exchange attempts fail.
    """
    if primary is None or fallback is None:
        primary, fallback = _get_primary_exchanges()

    # Progressive timeouts for resilience
    timeouts = [EXCHANGE_TIMEOUT_INITIAL, EXCHANGE_TIMEOUT_RETRY]

    for attempt, timeout_ms in enumerate(timeouts, start=1):
        for exchange_id in [primary, fallback]:
            try:
                exchange_cls = getattr(ccxt, exchange_id)
                exchange = exchange_cls({
                    "enableRateLimit": True,
                    "timeout": timeout_ms,
                })
                logger.info("Loading markets from %s (attempt %d, timeout %dms)...", exchange_id, attempt, timeout_ms)
                exchange.load_markets()
                logger.info("%s connected: %d markets available", exchange_id, len(exchange.markets))
                return exchange
            except (ccxt.NetworkError, ccxt.ExchangeError, AttributeError) as e:
                logger.warning("%s failed (attempt %d, timeout %dms): %s. Trying fallback...", exchange_id, attempt, timeout_ms, e)
                continue

    raise RuntimeError(
        f"All exchanges ({primary}, {fallback}) unreachable after progressive retries. "
        f"Check network and proxy settings. If in China, ensure Gate/OKX are accessible."
    )


# =========================================================================
#  OHLCV Data Fetching (retained from v1.0)
# =========================================================================

def _fetch_df(symbol: str,
               timeframe: str = DEFAULT_TIMEFRAME,
               limit: int = DEFAULT_LIMIT) -> pd.DataFrame:
    """Fetch OHLCV data and return as pandas DataFrame.

    Args:
        symbol: Trading pair (e.g. "BTC/USDT"). Auto-normalized.
        timeframe: Candle interval. Default "1d".
        limit: Number of candles. Default 200.

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.
    """
    symbol = _normalize_symbol(symbol)
    exchange = _get_exchange()

    if symbol not in exchange.markets:
        available = [s for s in exchange.markets if s.endswith("/USDT")][:10]
        raise ValueError(
            f"Trading pair {symbol} not found on {exchange.id}. "
            f"Available USDT pairs (sample): {available}"
        )

    try:
        logger.info("Fetching %d %s candles for %s...", limit, timeframe, symbol)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except ccxt.RateLimitExceeded as e:
        logger.error("Rate limit exceeded: %s", e)
        raise RuntimeError(f"Rate limit on {exchange.id}. Retry later.") from e
    except ccxt.NetworkError as e:
        logger.error("Network error: %s", e)
        raise RuntimeError(f"Network error on {exchange.id}: {e}") from e

    if not ohlcv or len(ohlcv) == 0:
        raise ValueError(f"No OHLCV data for {symbol} ({timeframe}).")

    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    logger.info("Fetched %d candles for %s", len(df), symbol)
    return df


def _fetch_multi_df(symbols: List[str],
                     timeframe: str = DEFAULT_TIMEFRAME,
                     limit: int = DEFAULT_LIMIT) -> Dict[str, pd.DataFrame]:
    """Fetch OHLCV data for multiple symbols."""
    symbols = [_normalize_symbol(s) for s in symbols]
    exchange = _get_exchange()
    result: Dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        if symbol not in exchange.markets:
            logger.warning("%s not available on %s, skipping.", symbol, exchange.id)
            continue
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            result[symbol] = df
            logger.info("Fetched %d candles for %s", len(df), symbol)
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.warning("Failed to fetch %s: %s", symbol, e)
            continue

    if not result:
        raise ValueError("No data fetched for any symbol.")

    return result


# =========================================================================
#  Safe Float Conversion (retained from v1.0)
# =========================================================================

def _s(value: Any) -> Optional[float]:
    """Convert a value to JSON-safe float, returning None for NaN/Inf."""
    try:
        f = float(value)
        if pd.isna(f) or f == float("inf") or f == float("-inf"):
            return None
        return round(f, 6)
    except (TypeError, ValueError):
        return None


# =========================================================================
#  Column Name Lookup (retained from v1.0)
# =========================================================================

def _col(df: pd.DataFrame, pattern: str) -> Optional[str]:
    """Find a column name containing pattern (case-insensitive)."""
    pattern_lower = pattern.lower()
    for col in df.columns:
        if pattern_lower in col.lower():
            return col
    return None


# =========================================================================
#  Common CLI Argument Parser
# =========================================================================

def parse_common_args(description: str) -> argparse.Namespace:
    """Parse common CLI arguments shared across scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--symbol", type=str, default="BTC/USDT",
                        help="Trading pair (default: BTC/USDT)")
    parser.add_argument("--timeframe", type=str, default=DEFAULT_TIMEFRAME,
                        help=f"Timeframe (default: {DEFAULT_TIMEFRAME})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Number of candles (default: {DEFAULT_LIMIT})")
    return parser.parse_args()
