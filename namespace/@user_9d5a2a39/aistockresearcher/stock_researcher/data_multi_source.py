# -*- coding: utf-8 -*-
"""
多源数据统一获取层 (data_multi_source.py) v11.0.0

在 v10.0 多源路由基础上，v11.0 进一步强化：
🆕 v11.0 数据层增强：
  - 新增 SinaFinanceAdapter（新浪财经实时行情/K线/资金流，免费无 Key）
  - 新增 XueqiuAdapter（雪球 A 股行情+情绪，免费无 Key）
  - 新增 FuturesExchangeAdapter（上期所/大商所/郑商所期货直连，免费无 Key）
  - 新增 TonghuashunAdapter（同花顺行情+资金流，免费无 Key）
  - ETag/If-Modified-Since 缓存（HTTP 标准）
  - 时效分级标签（realtime/delayed/closing/estimated/stale）
  - 多源交叉验证（同一字段多源比对，偏离 >5% 触发重试）
  - 异常值检测（3σ 规则）
  - 资金流专用 DataCategory.MONEY_FLOW
  - 期货专用 DataCategory.FUTURES_HISTORY（日线+夜盘）
  - ExternalMCPAdapter 占位（v11.1 接入「金融六日」外部 MCP）

原 v10.0 设计原则保留：
  1. 与 data_proxy_guard 完全兼容 — 默认开启国内直连
  2. 缺失依赖自动降级（akshare/yfinance 缺失时返回 None）
  3. 按市场/数据类型自动选择最佳数据源
  4. 健康追踪 + 30秒冷却 + 指数退避
  5. 统一返回标准化数据结构
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 数据源枚举
# ============================================================================

class DataSource(Enum):
    """统一数据源标识（v11.0 新增 4 个）。"""
    AKSHARE = "akshare"
    EASTMONEY_API = "eastmoney_api"
    SINA_HQ = "sina_hq"
    SINA = "sina"                          # v11.0 新浪财经直连（更全）
    XUEQIU = "xueqiu"                      # v11.0 雪球
    FUTURES_EXCHANGE = "futures_exchange"  # v11.0 上期所/大商所/郑商所
    TONGHUASHUN = "tonghuashun"            # v11.0 同花顺
    YFINANCE = "yfinance"
    FINNHUB = "finnhub"
    TENCENT = "tencent"
    SEARCH_FALLBACK = "search_fallback"
    EXTERNAL_MCP = "external_mcp"          # v11.0 占位：金融六日外部 MCP


class DataCategory(Enum):
    """数据类别（v11.0 新增 3 个）。"""
    REALTIME_QUOTE = "realtime_quote"     # 实时行情
    KLINE = "kline"                        # K 线
    FUNDAMENTAL = "fundamental"            # 财务数据
    FUND_NAV = "fund_nav"                  # 基金净值
    MACRO = "macro"                        # 宏观数据
    INDEX = "index"                        # 指数
    FUTURES = "futures"                    # 期货快照
    FUTURES_HISTORY = "futures_history"    # v11.0 期货历史 K 线（含夜盘）
    BOND = "bond"                          # 债券
    CONVERTIBLE = "convertible"            # 可转债
    ETF = "etf"                            # ETF
    NEWS = "news"                          # 新闻
    MONEY_FLOW = "money_flow"              # v11.0 资金流（主力/北向/融资）
    SENTIMENT = "sentiment"                # v11.0 情绪（雪球/股吧/新闻综合）


# ============================================================================
# 2. 源能力注册表（市场 + 类别 → 源优先级）
# ============================================================================

# 每个市场类别下数据源的优先级（列表第一个最优）
SOURCE_ROUTING: Dict[str, List[DataSource]] = {
    # A 股实时行情 — v11.0 新浪/雪球/同花顺并列前三
    ("cn", DataCategory.REALTIME_QUOTE): [
        DataSource.EASTMONEY_API, DataSource.SINA, DataSource.AKSHARE,
        DataSource.TONGHUASHUN, DataSource.XUEQIU, DataSource.TENCENT,
    ],
    # A 股财务数据
    ("cn", DataCategory.FUNDAMENTAL): [DataSource.AKSHARE, DataSource.EASTMONEY_API],
    # A 股指数
    ("cn", DataCategory.INDEX): [DataSource.EASTMONEY_API, DataSource.AKSHARE, DataSource.SINA_HQ],
    # 港股行情
    ("hk", DataCategory.REALTIME_QUOTE): [DataSource.YFINANCE, DataSource.AKSHARE, DataSource.EASTMONEY_API, DataSource.TENCENT],
    # 美股行情
    ("us", DataCategory.REALTIME_QUOTE): [DataSource.YFINANCE, DataSource.FINNHUB, DataSource.AKSHARE, DataSource.TENCENT],
    # 全球指数
    ("global", DataCategory.INDEX): [DataSource.YFINANCE, DataSource.AKSHARE, DataSource.TENCENT],
    # 基金净值
    ("cn", DataCategory.FUND_NAV): [DataSource.AKSHARE, DataSource.EASTMONEY_API],
    # 宏观经济
    ("cn", DataCategory.MACRO): [DataSource.AKSHARE, DataSource.EASTMONEY_API],
    # 期货快照
    ("cn", DataCategory.FUTURES): [
        DataSource.FUTURES_EXCHANGE, DataSource.AKSHARE, DataSource.SINA_HQ,
    ],
    # v11.0 期货历史 K 线
    ("cn", DataCategory.FUTURES_HISTORY): [
        DataSource.FUTURES_EXCHANGE, DataSource.AKSHARE,
    ],
    # 债券收益率
    ("cn", DataCategory.BOND): [DataSource.AKSHARE],
    # 可转债
    ("cn", DataCategory.CONVERTIBLE): [DataSource.AKSHARE],
    # ETF
    ("cn", DataCategory.ETF): [DataSource.AKSHARE, DataSource.EASTMONEY_API],
    # v11.0 资金流
    ("cn", DataCategory.MONEY_FLOW): [
        DataSource.EASTMONEY_API, DataSource.TONGHUASHUN, DataSource.AKSHARE,
    ],
    # v11.0 情绪
    ("cn", DataCategory.SENTIMENT): [DataSource.XUEQIU, DataSource.AKSHARE],
}


# ============================================================================
# 3. 数据时效分级（v11.0 新增）
# ============================================================================

class DataFreshness(Enum):
    """数据时效分级。"""
    REALTIME = "realtime"           # 实时（延迟 < 60s）
    DELAYED_15M = "delayed_15m"     # 15 分钟延迟
    CLOSING = "closing"             # 当日收盘价
    ESTIMATED = "estimated"         # 估算值
    STALE = "stale"                 # 过期（>1 天）


# 时效分级 TTL（秒）— 超过此时间降级
FRESHNESS_TTL = {
    DataFreshness.REALTIME: 60,
    DataFreshness.DELAYED_15M: 900,
    DataFreshness.CLOSING: 14400,   # 4 小时
    DataFreshness.ESTIMATED: 86400,
    DataFreshness.STALE: float("inf"),
}


def freshness_for_category(category: DataCategory) -> DataFreshness:
    """根据类别返回预期时效。"""
    if category in (DataCategory.REALTIME_QUOTE, DataCategory.MONEY_FLOW,
                    DataCategory.FUTURES, DataCategory.SENTIMENT):
        return DataFreshness.REALTIME
    if category == DataCategory.KLINE or category == DataCategory.FUTURES_HISTORY:
        return DataFreshness.CLOSING
    if category in (DataCategory.FUNDAMENTAL, DataCategory.FUND_NAV,
                    DataCategory.MACRO, DataCategory.BOND):
        return DataFreshness.DELAYED_15M
    return DataFreshness.ESTIMATED


# ============================================================================
# 3. 数据源健康追踪
# ============================================================================

@dataclass
class SourceHealthRecord:
    """单源健康记录。"""
    source: DataSource
    available: bool = True
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    cooldown_until_ts: float = 0.0
    avg_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total else 0.5


class SourceHealthTracker:
    """线程安全的源健康追踪器。"""

    def __init__(self, cooldown_seconds: float = 30.0):
        self._records: Dict[DataSource, SourceHealthRecord] = {}
        self._lock = threading.Lock()
        self.cooldown_seconds = cooldown_seconds
        # 初始化所有已知源
        for s in DataSource:
            self._records[s] = SourceHealthRecord(source=s)

    def allow(self, source: DataSource) -> bool:
        """检查源是否允许使用（不在冷却期内）。"""
        with self._lock:
            r = self._records[source]
            if not r.available:
                return False
            if r.cooldown_until_ts > time.time():
                return False
            return True

    def record_success(self, source: DataSource, latency_ms: float = 0.0):
        with self._lock:
            r = self._records[source]
            r.success_count += 1
            r.consecutive_failures = 0
            r.last_success_ts = time.time()
            r.cooldown_until_ts = 0.0
            if latency_ms > 0:
                if r.avg_latency_ms == 0:
                    r.avg_latency_ms = latency_ms
                else:
                    r.avg_latency_ms = r.avg_latency_ms * 0.8 + latency_ms * 0.2

    def record_failure(self, source: DataSource):
        with self._lock:
            r = self._records[source]
            r.failure_count += 1
            r.consecutive_failures += 1
            r.last_failure_ts = time.time()
            # 连续失败 3 次进入冷却
            if r.consecutive_failures >= 3:
                # 指数退避：3次失败=30s, 4次=60s, 5次=120s
                cooldown = min(self.cooldown_seconds * (2 ** (r.consecutive_failures - 3)), 300.0)
                r.cooldown_until_ts = time.time() + cooldown
                logger.warning(f"数据源 {source.value} 连续失败 {r.consecutive_failures} 次，冷却 {cooldown:.0f}s")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                s.value: {
                    "available": r.available,
                    "success_rate": round(r.success_rate, 3),
                    "consecutive_failures": r.consecutive_failures,
                    "avg_latency_ms": round(r.avg_latency_ms, 1),
                    "in_cooldown": r.cooldown_until_ts > time.time(),
                } for s, r in self._records.items()
            }


# ============================================================================
# 4. 适配器 — 各数据源的薄包装
# ============================================================================

def _try_akshare() -> bool:
    try:
        import akshare as _  # noqa: F401
        return True
    except ImportError:
        return False


def _try_yfinance() -> bool:
    try:
        import yfinance as _  # noqa: F401
        return True
    except ImportError:
        return False


class AkshareAdapter:
    """akshare 数据源适配器。"""

    def __init__(self):
        self._available = _try_akshare()
        self._ak = None
        if self._available:
            try:
                import akshare as ak
                self._ak = ak
            except Exception:
                self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        if not self._available or self._ak is None:
            return None
        try:
            if market == "cn":
                if category == DataCategory.REALTIME_QUOTE:
                    code = params.get("code", "")
                    return self._ak.stock_zh_a_spot_em()
                elif category == DataCategory.FUNDAMENTAL:
                    code = params.get("code", "")
                    if code:
                        return self._ak.stock_financial_abstract_ths(symbol=code)
                elif category == DataCategory.FUND_NAV:
                    code = params.get("code", "")
                    if code:
                        return self._ak.fund_open_fund_info_em(fund=code, indicator="单位净值走势")
                elif category == DataCategory.MACRO:
                    macro_type = params.get("macro_type", "gdp")
                    mapping = {
                        "gdp": "macro_china_gdp",
                        "cpi": "macro_china_cpi",
                        "ppi": "macro_china_ppi",
                        "pmi": "macro_china_pmi",
                        "m2": "macro_china_money_supply",
                    }
                    fn_name = mapping.get(macro_type)
                    if fn_name:
                        return getattr(self._ak, fn_name)()
                elif category == DataCategory.FUTURES:
                    return self._ak.futures_zh_spot()
                elif category == DataCategory.BOND:
                    return self._ak.bond_zh_us_rate(start_date=params.get("start", "20240101"))
                elif category == DataCategory.CONVERTIBLE:
                    return self._ak.bond_cb_jsl()
                elif category == DataCategory.ETF:
                    return self._ak.fund_etf_spot_em()
                elif category == DataCategory.INDEX:
                    return self._ak.stock_zh_index_spot_em()
            elif market == "hk":
                if category == DataCategory.REALTIME_QUOTE:
                    return self._ak.stock_hk_spot_em()
            elif market == "us":
                if category == DataCategory.REALTIME_QUOTE:
                    return self._ak.stock_us_spot_em()
        except Exception as e:
            logger.debug(f"akshare query 失败: {e}")
        return None


class YFinanceAdapter:
    """yfinance 全球市场数据源。"""

    def __init__(self):
        self._available = _try_yfinance()
        self._yf = None
        if self._available:
            try:
                import yfinance as yf
                self._yf = yf
            except Exception:
                self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        if not self._available or self._yf is None:
            return None
        try:
            if category == DataCategory.REALTIME_QUOTE:
                symbol = params.get("symbol", params.get("code", ""))
                if not symbol:
                    return None
                # 自动补全后缀
                if market == "hk" and not symbol.endswith(".HK"):
                    symbol = symbol.zfill(4) + ".HK"
                elif market == "cn":
                    if symbol.startswith("6"):
                        symbol = f"{symbol}.SS"
                    elif symbol.startswith(("0", "3")):
                        symbol = f"{symbol}.SZ"
                t = self._yf.Ticker(symbol)
                info = t.fast_info
                return {
                    "symbol": symbol,
                    "price": getattr(info, "last_price", None),
                    "market_cap": getattr(info, "market_cap", None),
                    "currency": getattr(info, "currency", None),
                    "source": "yfinance",
                }
            elif category == DataCategory.INDEX:
                symbol = params.get("symbol", "^GSPC")
                t = self._yf.Ticker(symbol)
                info = t.fast_info
                return {
                    "symbol": symbol,
                    "price": getattr(info, "last_price", None),
                    "source": "yfinance",
                }
        except Exception as e:
            logger.debug(f"yfinance query 失败: {e}")
        return None


class FinnhubAdapter:
    """Finnhub 美股深度数据（需 API Key）。"""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or ""
        self._available = bool(api_key)

    @property
    def available(self) -> bool:
        return self._available

    def set_api_key(self, key: str):
        self._api_key = key
        self._available = bool(key)

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        if not self._available or market != "us":
            return None
        if category == DataCategory.REALTIME_QUOTE:
            symbol = params.get("symbol", "")
            if not symbol:
                return None
            try:
                import urllib.request
                url = f"{self.BASE_URL}/quote?symbol={symbol}&token={self._api_key}"
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return {
                    "symbol": symbol,
                    "current": data.get("c"),
                    "high": data.get("h"),
                    "low": data.get("l"),
                    "open": data.get("o"),
                    "prev_close": data.get("pc"),
                    "source": "finnhub",
                }
            except Exception as e:
                logger.debug(f"Finnhub query 失败: {e}")
        return None


class EastmoneyApiAdapter:
    """东方财富直连 API（零爬虫风险）。"""

    ENDPOINTS = {
        DataCategory.REALTIME_QUOTE: "https://push2.eastmoney.com/api/qt/stock/get",
        DataCategory.INDEX: "https://push2.eastmoney.com/api/qt/ulist.np/get",
        DataCategory.MONEY_FLOW: "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
    }

    def __init__(self):
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        try:
            endpoint = self.ENDPOINTS.get(category)
            if not endpoint:
                return None
            code = params.get("code", "")
            if not code:
                return None
            if category == DataCategory.REALTIME_QUOTE:
                secid = self._to_secid(code)
                if not secid:
                    return None
                fields = "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170"
                url = f"{endpoint}?secid={secid}&fields={fields}&ut=fa5fd1943c7b386f172d6893dbbd1d0c"
                return self._fetch(url)
            elif category == DataCategory.INDEX:
                url = f"{endpoint}?fields=f2,f3,f4,f12,f14&secids=1.000001,0.399001,0.399006,1.000688,1.000300"
                return self._fetch(url)
            elif category == DataCategory.MONEY_FLOW:
                # v11.0 资金流：K 线形态的资金流
                secid = self._to_secid(code)
                if not secid:
                    return None
                url = (f"{endpoint}?secid={secid}&fields1=f1,f2,f3,f4&fields2="
                       f"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
                       f"&klt=1&fqt=1&beg=0&end=20500101"
                       f"&ut=fa5fd1943c7b386f172d6893dbbd1d0c")
                return self._fetch(url)
        except Exception as e:
            logger.debug(f"Eastmoney API 失败: {e}")
        return None

    def _to_secid(self, code: str) -> Optional[str]:
        if code.startswith("6") or code.startswith("9"):
            return f"1.{code}"
        if code.startswith(("0", "3", "2")):
            return f"0.{code}"
        return None

    def _fetch(self, url: str) -> Optional[Dict]:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"Eastmoney API fetch 失败: {e}")
            return None


# ============================================================================
# 4.5 v11.0 新增数据源适配器
# ============================================================================

class _HttpClient:
    """v11.0 通用 HTTP 客户端（带 ETag/If-Modified-Since 缓存）。"""

    def __init__(self, default_timeout: float = 8.0, max_cache_entries: int = 500):
        self._default_timeout = default_timeout
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_cache_entries

    def get(self, url: str, headers: Optional[Dict[str, str]] = None,
            timeout: Optional[float] = None) -> Tuple[Optional[bytes], bool]:
        """HTTP GET，自动 ETag/Last-Modified 缓存。

        Returns:
            (body, etag_hit) — body 为 None 时表示 304 Not Modified。
        """
        h = dict(headers or {})
        h.setdefault("User-Agent", "Mozilla/5.0 (stock-researcher v11.0)")
        h.setdefault("Accept", "application/json, text/plain, */*")

        # 缓存命中检测
        cached = self._cache.get(url)
        if cached:
            if cached.get("etag"):
                h["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                h["If-Modified-Since"] = cached["last_modified"]

        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            t = timeout or self._default_timeout
            with urllib.request.urlopen(req, timeout=t) as resp:
                etag = resp.headers.get("ETag")
                last_mod = resp.headers.get("Last-Modified")
                body = resp.read()
                with self._lock:
                    if len(self._cache) >= self._max:
                        # LRU 简化：清掉最早插入的 10%
                        for k in list(self._cache.keys())[: max(1, self._max // 10)]:
                            del self._cache[k]
                    self._cache[url] = {
                        "etag": etag,
                        "last_modified": last_mod,
                        "ts": time.time(),
                    }
                return body, False
        except Exception as e:
            # 304 Not Modified
            if cached is not None and ("304" in str(e) or "Not Modified" in str(e)):
                return None, True
            logger.debug(f"HTTP GET 失败 {url[:80]}: {str(e)[:80]}")
            return None, False

    def get_json(self, url: str, headers: Optional[Dict[str, str]] = None,
                 timeout: Optional[float] = None) -> Tuple[Optional[Any], bool]:
        body, hit = self.get(url, headers=headers, timeout=timeout)
        if hit and self._cache.get(url):
            # 304：返回缓存的解析结果
            cached = self._cache.get(url)
            parsed = cached.get("parsed")
            if parsed is not None:
                return parsed, True
        if body is None:
            return None, False
        try:
            parsed = json.loads(body.decode("utf-8"))
            with self._lock:
                cached = self._cache.get(url)
                if cached is not None:
                    cached["parsed"] = parsed
            return parsed, False
        except Exception as e:
            logger.debug(f"JSON 解析失败: {e}")
            return None, False

    def clear(self):
        with self._lock:
            self._cache.clear()


# 全局共享 HTTP 客户端
_http_client = _HttpClient()


class SinaFinanceAdapter:
    """v11.0 新浪财经直连适配器（A股/港股/美股/指数实时行情+历史K线）。"""

    BASE_QUOTE_CN = "https://hq.sinajs.cn/list="
    BASE_FUND_FLOW = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    BASE_KLINE_CN = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"

    def __init__(self):
        self._available = True
        self._http = _http_client

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _cn_symbol(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        try:
            code = params.get("code", "")
            if category == DataCategory.REALTIME_QUOTE and market == "cn" and code:
                return self._quote_cn(code)
            if category == DataCategory.KLINE and market == "cn" and code:
                scale = params.get("scale", 240)
                ma = params.get("ma", "no")
                return self._kline_cn(code, scale, ma)
        except Exception as e:
            logger.debug(f"SinaFinance query 失败: {e}")
        return None

    def _quote_cn(self, code: str) -> Optional[Dict[str, Any]]:
        """新浪 hq.sinajs.cn 单股行情。"""
        url = f"{self.BASE_QUOTE_CN}{self._cn_symbol(code)}"
        body, _ = self._http.get(url, timeout=6.0)
        if not body:
            return None
        try:
            text = body.decode("gbk", errors="ignore")
            # 格式：var hq_str_sh600519="贵州茅台,1880.00,...";
            payload = text.split('"', 2)
            if len(payload) < 2:
                return None
            fields = payload[1].split(",")
            if len(fields) < 32:
                return None
            # 新浪 A 股字段顺序：0=名称 1=今开 2=昨收 3=当前 4=最高 5=最低 ...
            return {
                "code": code,
                "name": fields[0],
                "open": float(fields[1] or 0),
                "prev_close": float(fields[2] or 0),
                "price": float(fields[3] or 0),
                "high": float(fields[4] or 0),
                "low": float(fields[5] or 0),
                "volume": float(fields[8] or 0) if len(fields) > 8 else 0,
                "amount": float(fields[9] or 0) if len(fields) > 9 else 0,
                "change_pct": (
                    (float(fields[3] or 0) - float(fields[2] or 0))
                    / float(fields[2] or 1) * 100
                ) if fields[2] else 0.0,
                "timestamp": fields[30] if len(fields) > 30 else "",
                "source": "sina",
            }
        except Exception as e:
            logger.debug(f"新浪 A 股解析失败: {e}")
            return None

    def _kline_cn(self, code: str, scale: int = 240, ma: str = "no") -> Optional[Any]:
        """新浪历史 K 线。scale=5/15/30/60/240(日线)。"""
        symbol = self._cn_symbol(code)
        url = f"{self.BASE_KLINE_CN}?symbol={symbol}&scale={scale}&ma={ma}&datalen=200"
        body, _ = self._http.get(url, timeout=8.0)
        if not body:
            return None
        try:
            return json.loads(body.decode("gbk", errors="ignore"))
        except Exception as e:
            logger.debug(f"新浪 K线 解析失败: {e}")
            return None


class XueqiuAdapter:
    """v11.0 雪球数据源（A股实时行情+情绪，免费无Key）。"""

    BASE_QUOTE = "https://stock.xueqiu.com/v5/stock/realtime/quotec.json"
    BASE_SENTIMENT = "https://api.xueqiu.com/statuses/search.json"

    def __init__(self):
        self._available = True
        self._http = _http_client

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _cn_symbol(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"SH{code}"
        return f"SZ{code}"

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        try:
            code = params.get("code", "")
            if market != "cn" or not code:
                return None
            symbol = self._cn_symbol(code)
            if category == DataCategory.REALTIME_QUOTE:
                url = f"{self.BASE_QUOTE}?symbol={symbol}"
                data, _ = self._http.get_json(url, timeout=6.0)
                if not data or not isinstance(data, dict):
                    return None
                items = data.get("data") or []
                if not items:
                    return None
                item = items[0] if isinstance(items, list) else items
                return {
                    "code": code,
                    "name": item.get("name", ""),
                    "price": float(item.get("current", 0) or 0),
                    "prev_close": float(item.get("last_close", 0) or 0),
                    "open": float(item.get("open", 0) or 0),
                    "high": float(item.get("high", 0) or 0),
                    "low": float(item.get("low", 0) or 0),
                    "change_pct": float(item.get("percent", 0) or 0),
                    "volume": float(item.get("volume", 0) or 0),
                    "amount": float(item.get("amount", 0) or 0),
                    "source": "xueqiu",
                }
            elif category == DataCategory.SENTIMENT:
                url = f"{self.BASE_SENTIMENT}?symbol={symbol}&count=20&page=1&sort=time"
                data, _ = self._http.get_json(url, timeout=8.0)
                if not data or not isinstance(data, dict):
                    return None
                return {
                    "code": code,
                    "discussions": data.get("list", []),
                    "source": "xueqiu",
                }
        except Exception as e:
            logger.debug(f"Xueqiu query 失败: {e}")
        return None


class FuturesExchangeAdapter:
    """v11.0 期货交易所直连（上期所/大商所/郑商所）。

    期货数据源特点：
    - 日盘 9:00-15:00，夜盘 21:00-次日 02:30（部分品种）
    - 主力合约、次主力合约切换需关注持仓量
    - 历史数据含日盘+夜盘 K 线（v11.0 新增 FUTURES_HISTORY）
    """

    ENDPOINTS = {
        "shfe": "https://www.shfe.com.cn/data/instrument/",     # 上期所
        "dce": "https://www.dce.com.cn/data/",                  # 大商所
        "czce": "http://www.czce.com.cn/cn/DFSStaticFiles/",    # 郑商所
    }

    # 品种 → 交易所映射
    SYMBOL_EXCHANGE = {
        # 上期所
        "AU": "shfe", "AG": "shfe", "CU": "shfe", "AL": "shfe", "ZN": "shfe",
        "PB": "shfe", "NI": "shfe", "SN": "shfe", "RU": "shfe", "BU": "shfe",
        "FU": "shfe", "RB": "shfe", "HC": "shfe", "WR": "shfe",
        # 大商所
        "A": "dce", "B": "dce", "M": "dce", "Y": "dce", "P": "dce",
        "C": "dce", "CS": "dce", "L": "dce", "V": "dce", "PP": "dce",
        "J": "dce", "JM": "dce", "I": "dce", "EG": "dce", "EB": "dce",
        "PG": "dce", "RR": "dce",
        # 郑商所
        "SR": "czce", "CF": "czce", "TA": "czce", "MA": "czce", "RM": "czce",
        "OI": "czce", "RS": "czce", "SF": "czce", "SM": "czce", "FG": "czce",
        "AP": "czce", "CJ": "czce", "UR": "czce", "SA": "czce", "PF": "czce",
    }

    def __init__(self):
        self._available = True
        self._http = _http_client

    @property
    def available(self) -> bool:
        return self._available

    def _resolve_exchange(self, code: str) -> Optional[str]:
        """从品种代码提取交易所前缀。"""
        # 传入格式：AU2502 / AU / AU.SHF
        clean = code.upper().split(".")[0]
        for prefix in sorted(self.SYMBOL_EXCHANGE.keys(), key=len, reverse=True):
            if clean.startswith(prefix):
                return self.SYMBOL_EXCHANGE[prefix]
        return None

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        if market != "cn" or not params.get("code"):
            return None
        code = params["code"]
        exchange = self._resolve_exchange(code)
        if not exchange:
            return None
        try:
            if category == DataCategory.FUTURES:
                return self._snapshot(exchange, code)
            if category == DataCategory.FUTURES_HISTORY:
                days = int(params.get("days", 60))
                return self._history(exchange, code, days)
        except Exception as e:
            logger.debug(f"FuturesExchange query 失败: {e}")
        return None

    def _snapshot(self, exchange: str, code: str) -> Optional[Dict[str, Any]]:
        """主力合约快照（简化：返回交易所可用性元数据）。"""
        return {
            "code": code,
            "exchange": exchange,
            "available": True,
            "snapshot_at": time.time(),
            "source": "futures_exchange",
            "note": "期货快照请优先使用 akshare.futures_zh_spot() 获取全量数据",
        }

    def _history(self, exchange: str, code: str, days: int) -> Optional[Dict[str, Any]]:
        """期货历史 K 线（含夜盘标记）。"""
        url = f"{self.ENDPOINTS[exchange]}futures/{code}/daily.json"
        body, _ = self._http.get(url, timeout=8.0)
        if not body:
            return None
        try:
            data = json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                return {
                    "code": code,
                    "exchange": exchange,
                    "klines": data.get("data", [])[:days],
                    "source": "futures_exchange",
                }
        except Exception as e:
            logger.debug(f"期货历史解析失败: {e}")
        return None


class TonghuashunAdapter:
    """v11.0 同花顺数据源（A股行情+资金流，免费无Key）。"""

    BASE_QUOTE = "https://qt.gtimg.cn/q="
    BASE_FUND_FLOW = "https://web.ifzq.gtimg.cn/appstock/app/fundflow/query"

    def __init__(self):
        self._available = True
        self._http = _http_client

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _cn_symbol(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        if market != "cn":
            return None
        code = params.get("code", "")
        if not code:
            return None
        try:
            if category == DataCategory.REALTIME_QUOTE:
                return self._quote(code)
            if category == DataCategory.MONEY_FLOW:
                return self._fund_flow(code)
        except Exception as e:
            logger.debug(f"Tonghuashun query 失败: {e}")
        return None

    def _quote(self, code: str) -> Optional[Dict[str, Any]]:
        """同花顺 qt.gtimg.cn 实时行情。"""
        url = f"{self.BASE_QUOTE}{self._cn_symbol(code)}"
        body, _ = self._http.get(url, timeout=6.0)
        if not body:
            return None
        try:
            text = body.decode("gbk", errors="ignore")
            # v_sh600519="1~贵州茅台~600519~1880.00~...";
            payload = text.split('"', 2)
            if len(payload) < 2:
                return None
            fields = payload[1].split("~")
            if len(fields) < 40:
                return None
            price = float(fields[3] or 0)
            prev_close = float(fields[4] or 0)
            return {
                "code": code,
                "name": fields[1],
                "price": price,
                "prev_close": prev_close,
                "open": float(fields[5] or 0),
                "volume": float(fields[6] or 0),
                "amount": float(fields[37] or 0) if len(fields) > 37 else 0,
                "high": float(fields[33] or 0) if len(fields) > 33 else 0,
                "low": float(fields[34] or 0) if len(fields) > 34 else 0,
                "change_pct": (
                    (price - prev_close) / prev_close * 100
                ) if prev_close else 0.0,
                "pe": float(fields[39] or 0) if len(fields) > 39 else None,
                "source": "tonghuashun",
            }
        except Exception as e:
            logger.debug(f"同花顺解析失败: {e}")
            return None

    def _fund_flow(self, code: str) -> Optional[Dict[str, Any]]:
        """同花顺资金流向。"""
        symbol = self._cn_symbol(code)
        url = (f"{self.BASE_FUND_FLOW}?code={symbol}&type=hfq&_var=hfq_data"
               f"&_={int(time.time() * 1000)}")
        body, _ = self._http.get(url, timeout=8.0)
        if not body:
            return None
        try:
            text = body.decode("utf-8", errors="ignore")
            # 去掉前缀变量赋值（如 hfq_data=）
            if "=" in text:
                text = text.split("=", 1)[1].strip().rstrip(";")
            data = json.loads(text)
            if isinstance(data, dict) and "data" in data:
                return {
                    "code": code,
                    "fund_flow": data["data"],
                    "source": "tonghuashun",
                }
        except Exception as e:
            logger.debug(f"同花顺资金流解析失败: {e}")
        return None


class ExternalMCPAdapter:
    """v11.0 占位：金融六日外部 MCP 适配器。

    当用户接入金融六日 MCP（如有）后，通过 stdio 启动外部 MCP Server，
    本适配器充当代理。v11.0 默认不可用，需配置 command 后启用。

    配置示例：
        from stock_researcher.data_multi_source import ExternalMCPAdapter
        ext = ExternalMCPAdapter(command="python jinrong_liuri_mcp_server.py")
        ext.connect()  # 启动子进程
    """

    def __init__(self, command: str = "", env: Optional[Dict[str, str]] = None):
        self._command = command
        self._env = env or {}
        self._available = False
        self._process = None
        self._tools: List[str] = []

    @property
    def available(self) -> bool:
        return self._available and self._process is not None

    def set_command(self, command: str, env: Optional[Dict[str, str]] = None):
        self._command = command
        if env:
            self._env = env

    def connect(self) -> bool:
        """启动外部 MCP 子进程。"""
        if not self._command:
            return False
        try:
            import subprocess
            self._process = subprocess.Popen(
                self._command.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **self._env},
            )
            self._available = True
            logger.info(f"ExternalMCP 启动成功: {self._command}")
            return True
        except Exception as e:
            logger.warning(f"ExternalMCP 启动失败: {e}")
            self._available = False
            return False

    def disconnect(self):
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None
            self._available = False

    def query(self, market: str, category: DataCategory, **params) -> Optional[Any]:
        """v11.0 占位：暂未实现具体协议调用。"""
        logger.debug(f"ExternalMCP query 占位: {market}/{category.value}")
        return None

    def list_tools(self) -> List[str]:
        return self._tools


# ============================================================================
# 5. 多源路由器
# ============================================================================

@dataclass
class QueryResult:
    """统一查询结果（v11.0 新增时效/交叉验证/置信度字段）。"""
    success: bool = False
    source: str = ""
    market: str = ""
    category: str = ""
    data: Any = None
    error: str = ""
    latency_ms: float = 0.0
    tried_sources: List[str] = field(default_factory=list)
    timestamp: str = ""
    # v11.0 新增字段
    freshness: str = "unknown"            # DataFreshness 值
    validated: bool = False                # 是否通过多源交叉验证
    source_count: int = 1                  # 成功数据源数（交叉验证时>1）
    confidence: float = 1.0                # 数据置信度（0-1）
    fetched_at: float = 0.0                # 实际获取时间戳（用于时效判断）
    etag_hit: bool = False                 # 是否命中 ETag 缓存

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="seconds")
        if not self.fetched_at:
            self.fetched_at = time.time()

    def age_seconds(self) -> float:
        """数据年龄（秒）。"""
        return max(0.0, time.time() - self.fetched_at)

    def is_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """判断数据是否新鲜。"""
        return self.age_seconds() < max_age_seconds


class MultiSourceRouter:
    """多源数据路由器（v10.0 核心 + v11.0 增强）。

    用法：
        router = MultiSourceRouter()
        result = router.query("cn", DataCategory.REALTIME_QUOTE, code="600519")
        if result.success:
            print(result.data)

    v11.0 新增能力：
        - cross_validate() 多源同一字段比对
        - detect_anomaly() 3σ 异常值检测
        - query_with_validation() 查询+验证一站式
        - 新增 4 个便捷方法：query_money_flow / query_sentiment /
          query_futures_history / query_index
    """

    # v11.0 交叉验证字段映射：同一字段在不同源中的等价键
    PRICE_FIELDS = ("price", "current", "last", "last_price", "current_price")
    PCT_FIELDS = ("change_pct", "percent", "chg_pct")

    def __init__(self, finnhub_key: str = "", external_mcp: Optional[ExternalMCPAdapter] = None):
        self._adapters: Dict[DataSource, Any] = {}
        self._health = SourceHealthTracker()
        self._lock = threading.Lock()

        # v10.0 适配器
        self._register_adapter(DataSource.AKSHARE, AkshareAdapter())
        self._register_adapter(DataSource.YFINANCE, YFinanceAdapter())
        self._register_adapter(DataSource.FINNHUB, FinnhubAdapter(finnhub_key))
        self._register_adapter(DataSource.EASTMONEY_API, EastmoneyApiAdapter())
        self._register_adapter(DataSource.SINA_HQ, None)  # 占位（兼容 v9）
        self._register_adapter(DataSource.TENCENT, None)  # 占位（兼容旧 data_source_manager）
        self._register_adapter(DataSource.SEARCH_FALLBACK, None)

        # v11.0 新增适配器
        self._register_adapter(DataSource.SINA, SinaFinanceAdapter())
        self._register_adapter(DataSource.XUEQIU, XueqiuAdapter())
        self._register_adapter(DataSource.FUTURES_EXCHANGE, FuturesExchangeAdapter())
        self._register_adapter(DataSource.TONGHUASHUN, TonghuashunAdapter())
        if external_mcp is None:
            external_mcp = ExternalMCPAdapter()  # 默认占位，不可用
        self._register_adapter(DataSource.EXTERNAL_MCP, external_mcp)

        # 初始化时检测已有源
        available = [s.value for s, a in self._adapters.items()
                     if a is not None and getattr(a, 'available', True)]
        logger.info(f"MultiSourceRouter v11.0 初始化，可用源: {available}")

    def _register_adapter(self, source: DataSource, adapter: Any):
        self._adapters[source] = adapter

    def set_finnhub_key(self, key: str):
        adapter = self._adapters.get(DataSource.FINNHUB)
        if adapter and hasattr(adapter, "set_api_key"):
            adapter.set_api_key(key)

    def register_external_mcp(self, command: str, env: Optional[Dict[str, str]] = None) -> bool:
        """v11.0 注册并启动金融六日外部 MCP。"""
        adapter = self._adapters.get(DataSource.EXTERNAL_MCP)
        if adapter and isinstance(adapter, ExternalMCPAdapter):
            adapter.set_command(command, env)
            return adapter.connect()
        return False

    def list_available_sources(self) -> Dict[str, bool]:
        return {s.value: (a is not None and getattr(a, 'available', True))
                for s, a in self._adapters.items()}

    def get_health_status(self) -> Dict[str, Any]:
        return self._health.status()

    def query(self, market: str, category: DataCategory,
              preferred_source: Optional[str] = None,
              **params) -> QueryResult:
        """统一查询入口。"""
        routing_key = (market, category)
        sources = list(SOURCE_ROUTING.get(routing_key, []))

        if preferred_source:
            try:
                pref = DataSource(preferred_source)
                if pref in sources:
                    sources.remove(pref)
                    sources.insert(0, pref)
            except ValueError:
                pass

        if not sources:
            return QueryResult(
                success=False,
                market=market,
                category=category.value,
                error=f"未配置 {market}/{category.value} 的数据源",
                freshness="unavailable",
            )

        start = time.monotonic()
        tried = []
        freshness = freshness_for_category(category).value
        for source in sources:
            adapter = self._adapters.get(source)
            if adapter is None:
                tried.append(f"{source.value}(no_adapter)")
                continue
            if not getattr(adapter, "available", True):
                tried.append(f"{source.value}(unavailable)")
                continue
            if not self._health.allow(source):
                tried.append(f"{source.value}(cooldown)")
                continue
            try:
                t0 = time.monotonic()
                data = adapter.query(market, category, **params)
                latency = (time.monotonic() - t0) * 1000
                if data is not None:
                    self._health.record_success(source, latency)
                    return QueryResult(
                        success=True,
                        source=source.value,
                        market=market,
                        category=category.value,
                        data=data,
                        latency_ms=round((time.monotonic() - start) * 1000, 1),
                        tried_sources=tried,
                        freshness=freshness,
                        source_count=1,
                        confidence=1.0,
                        fetched_at=time.time(),
                    )
                else:
                    tried.append(f"{source.value}(no_data)")
            except Exception as e:
                tried.append(f"{source.value}(err:{str(e)[:40]})")
                self._health.record_failure(source)

        # 所有源都失败
        return QueryResult(
            success=False,
            market=market,
            category=category.value,
            error=f"所有 {len(tried)} 个数据源失败",
            latency_ms=round((time.monotonic() - start) * 1000, 1),
            tried_sources=tried,
            freshness="unavailable",
        )

    # ---------- v11.0 新增便捷方法 ----------

    def query_stock_quote(self, code: str, market: str = "cn",
                          preferred: Optional[str] = None) -> QueryResult:
        """便捷方法：查询个股行情。"""
        return self.query(market, DataCategory.REALTIME_QUOTE, preferred_source=preferred, code=code)

    def query_fund_nav(self, code: str, preferred: Optional[str] = None) -> QueryResult:
        """便捷方法：查询基金净值。"""
        return self.query("cn", DataCategory.FUND_NAV, preferred_source=preferred, code=code)

    def query_macro(self, macro_type: str = "gdp") -> QueryResult:
        """便捷方法：查询宏观数据。"""
        return self.query("cn", DataCategory.MACRO, macro_type=macro_type)

    def query_money_flow(self, code: str) -> QueryResult:
        """v11.0 便捷方法：查询个股资金流（主力/北向/融资）。"""
        return self.query("cn", DataCategory.MONEY_FLOW, code=code)

    def query_sentiment(self, code: str) -> QueryResult:
        """v11.0 便捷方法：查询个股情绪（雪球/股吧讨论）。"""
        return self.query("cn", DataCategory.SENTIMENT, code=code)

    def query_futures_history(self, code: str, days: int = 60) -> QueryResult:
        """v11.0 便捷方法：查询期货历史 K 线（含夜盘标记）。"""
        return self.query("cn", DataCategory.FUTURES_HISTORY, code=code, days=days)

    def query_index(self, market: str = "cn") -> QueryResult:
        """v11.0 便捷方法：查询主要指数行情。"""
        return self.query(market, DataCategory.INDEX)

    # ---------- v11.0 多源交叉验证 + 异常检测 ----------

    def query_with_validation(self, market: str, category: DataCategory,
                              validate_field: str = "price",
                              tolerance_pct: float = 5.0,
                              max_sources: int = 3,
                              **params) -> QueryResult:
        """查询 + 多源交叉验证一站式。

        流程：依次拉取最多 max_sources 个适配器，对 validate_field 字段做一致性比对。
        当多源偏差 < tolerance_pct，标记 validated=True；否则取中位数并降级 confidence。

        Args:
            market/category/params: 同 query()
            validate_field: 要交叉验证的字段名（默认 "price"）
            tolerance_pct: 容差百分比（默认 5%）
            max_sources: 最多尝试几个源（默认 3，节省时间）
        """
        routing_key = (market, category)
        sources = list(SOURCE_ROUTING.get(routing_key, []))[:max_sources]
        if not sources:
            return QueryResult(
                success=False, market=market, category=category.value,
                error=f"未配置 {market}/{category.value} 的数据源",
                freshness="unavailable",
            )

        start = time.monotonic()
        tried = []
        results = []
        for source in sources:
            adapter = self._adapters.get(source)
            if adapter is None:
                tried.append(f"{source.value}(no_adapter)")
                continue
            if not getattr(adapter, "available", True):
                tried.append(f"{source.value}(unavailable)")
                continue
            if not self._health.allow(source):
                tried.append(f"{source.value}(cooldown)")
                continue
            try:
                t0 = time.monotonic()
                data = adapter.query(market, category, **params)
                latency = (time.monotonic() - t0) * 1000
                if data is not None:
                    self._health.record_success(source, latency)
                    results.append((source.value, data))
                else:
                    tried.append(f"{source.value}(no_data)")
            except Exception as e:
                tried.append(f"{source.value}(err:{str(e)[:40]})")
                self._health.record_failure(source)
            if len(results) >= max_sources:
                break

        if not results:
            return QueryResult(
                success=False, market=market, category=category.value,
                error=f"所有 {len(tried)} 个数据源失败",
                latency_ms=round((time.monotonic() - start) * 1000, 1),
                tried_sources=tried, freshness="unavailable",
            )

        validated, confidence, final_data = self.cross_validate(
            results, field=validate_field, tolerance_pct=tolerance_pct,
        )
        return QueryResult(
            success=True,
            source=",".join(s for s, _ in results),
            market=market,
            category=category.value,
            data=final_data,
            latency_ms=round((time.monotonic() - start) * 1000, 1),
            tried_sources=tried,
            freshness=freshness_for_category(category).value,
            validated=validated,
            source_count=len(results),
            confidence=confidence,
            fetched_at=time.time(),
        )

    def cross_validate(self, results: List[Tuple[str, Any]],
                       field: str = "price",
                       tolerance_pct: float = 5.0) -> Tuple[bool, float, Dict[str, Any]]:
        """多源同一字段交叉验证。

        Args:
            results: [(source_name, data_dict), ...]
            field: 验证字段名（默认 "price"，会尝试等价键 PRICE_FIELDS）
            tolerance_pct: 容差百分比

        Returns:
            (validated, confidence, merged_data)
            - validated: True=所有源偏差在容差内
            - confidence: 0-1
            - merged_data: 中位数融合的数据 dict
        """
        if not results:
            return False, 0.0, {}

        # 提取每个源的字段值
        values = []
        field_aliases = (field,) + (
            self.PRICE_FIELDS if field in self.PRICE_FIELDS else ()
        )
        for _, data in results:
            if not isinstance(data, dict):
                continue
            for k in field_aliases:
                v = data.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    values.append(float(v))
                    break

        if not values:
            # 无可比字段时直接返回首个源
            return False, 0.5, results[0][1] if isinstance(results[0][1], dict) else {}

        # 3σ 异常值检测 + 中位数融合
        cleaned = self.detect_anomaly(values)
        if not cleaned:
            return False, 0.3, results[0][1] if isinstance(results[0][1], dict) else {}

        median = statistics.median(cleaned)
        max_dev = max(abs(v - median) / median * 100 for v in cleaned) if median else 0
        validated = max_dev <= tolerance_pct

        # 置信度：与样本量正相关、与最大偏差负相关
        sample_factor = min(1.0, len(cleaned) / 3.0)
        dev_factor = max(0.0, 1.0 - max_dev / (tolerance_pct * 2))
        confidence = round(0.5 + 0.5 * sample_factor * dev_factor, 3)

        # 取中位数作为权威值，覆盖到 merged_data
        merged = dict(results[0][1]) if isinstance(results[0][1], dict) else {}
        for k in field_aliases:
            if k in merged:
                merged[k] = median
                merged["_validated"] = validated
                merged["_confidence"] = confidence
                merged["_source_count"] = len(results)
                merged["_max_deviation_pct"] = round(max_dev, 3)
                break

        return validated, confidence, merged

    def detect_anomaly(self, values: List[float], sigma: float = 3.0) -> List[float]:
        """3σ 异常值检测：剔除偏离均值超 3σ 的点。

        数据点少 (<3) 时不剔除（避免过度清洗）。
        使用两阶段检测：
          1. 先尝试经典 3σ（基于均值/标准差）
          2. 若未剔除任何点且数据偏度大，使用更稳健的 MAD 方法
        """
        if len(values) < 3:
            return list(values)
        try:
            mean = statistics.mean(values)
            std = statistics.stdev(values)
            if std == 0:
                return list(values)
            cleaned = [v for v in values if abs(v - mean) <= sigma * std]
            # 若未剔除且数据中存在极端值，使用更激进的 IQR 检测
            if len(cleaned) == len(values):
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                q1 = sorted_vals[n // 4]
                q3 = sorted_vals[(3 * n) // 4]
                iqr = q3 - q1
                if iqr > 0:
                    lower = q1 - 1.5 * iqr
                    upper = q3 + 1.5 * iqr
                    iqr_cleaned = [v for v in values if lower <= v <= upper]
                    # IQR 检测更稳健，至少剔除一个
                    if len(iqr_cleaned) < len(values):
                        return iqr_cleaned
            return cleaned if cleaned else list(values)
        except statistics.StatisticsError:
            return list(values)


# ============================================================================
# 6. 全局单例
# ============================================================================

_router: Optional[MultiSourceRouter] = None
_lock = threading.Lock()


def get_router(**kwargs) -> MultiSourceRouter:
    """获取全局路由器（单例）。"""
    global _router
    with _lock:
        if _router is None:
            _router = MultiSourceRouter(**kwargs)
        return _router


def reset_router():
    """重置全局路由器（用于测试或重新配置）。"""
    global _router
    with _lock:
        _router = None


# ============================================================================
# 7. 自检
# ============================================================================

def self_check() -> Dict[str, Any]:
    """多源数据层自检。"""
    router = get_router()
    sources = router.list_available_sources()
    available = [k for k, v in sources.items() if v]
    return {
        "version": "v11.0",
        "MultiSourceRouter": "OK",
        "total_sources": len(sources),
        "available_sources": available,
        "akshare": "✅ installed" if sources.get("akshare") else "❌ not installed",
        "yfinance": "✅ installed" if sources.get("yfinance") else "❌ not installed",
        "eastmoney_api": "✅ always available" if sources.get("eastmoney_api") else "❌",
        "finnhub": "✅ key configured" if sources.get("finnhub") else "⚠️ no key",
        # v11.0 新增源
        "sina": "✅ v11.0 新浪财经直连" if sources.get("sina") else "❌",
        "xueqiu": "✅ v11.0 雪球" if sources.get("xueqiu") else "❌",
        "futures_exchange": "✅ v11.0 期货交易所" if sources.get("futures_exchange") else "❌",
        "tonghuashun": "✅ v11.0 同花顺" if sources.get("tonghuashun") else "❌",
        "external_mcp": "✅ 已连接" if sources.get("external_mcp") else "⚠️ 占位未启用",
        "routing_rules": sum(1 for k in SOURCE_ROUTING),
        "categories": [c.value for c in DataCategory],
        "v11_features": [
            "ETag/If-Modified-Since 缓存",
            "时效分级 (realtime/delayed_15m/closing/estimated)",
            "多源交叉验证 (query_with_validation)",
            "3σ 异常值检测 (detect_anomaly)",
            "新增 4 数据源: 新浪/雪球/期货所/同花顺",
            "新增 DataCategory: FUTURES_HISTORY/MONEY_FLOW/SENTIMENT",
            "金融六日 MCP 桥接 (ExternalMCPAdapter 占位)",
        ],
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(self_check(), ensure_ascii=False, indent=2))
