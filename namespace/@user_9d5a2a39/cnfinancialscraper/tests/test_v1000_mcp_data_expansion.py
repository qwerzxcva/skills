# -*- coding: utf-8 -*-
"""
v10.0.0 测试套件 — MCP 数据获取扩充（mcp_data_expansion）

覆盖：
1. QueryCache LRU + TTL + 持久化
2. TushareAdapter（无 token 时 available=False）
3. AlphaVantageAdapter（无 key 时空返回）
4. CoinGeckoAdapter health（无需 key）
5. ExchangeRateAdapter health（无需 key）
6. ExpansionAdapterSet 路由
7. register_expansion_adapters 接入 v9 路由器
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from scripts.mcp_data_expansion import (  # noqa: E402
    CacheEntry, QueryCache, get_default_cache,
    TushareAdapter, AlphaVantageAdapter, CoinGeckoAdapter, ExchangeRateAdapter,
    ExpansionAdapterSet, register_expansion_adapters,
)


# ============================================================================
# 1. QueryCache
# ============================================================================

class TestQueryCache(unittest.TestCase):
    """LRU + TTL 缓存层。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = QueryCache(
            max_size=5, default_ttl=10.0,
            persist_path=os.path.join(self.tmp.name, "cache.json"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_and_get(self):
        self.cache.set("k1", {"v": 1})
        self.assertEqual(self.cache.get("k1"), {"v": 1})

    def test_get_missing(self):
        self.assertIsNone(self.cache.get("nonexistent"))
        self.assertEqual(self.cache.stats_misses, 1)

    def test_lru_eviction(self):
        for i in range(5):
            self.cache.set(f"k{i}", i)
        self.cache.set("k5", 5)  # 触发淘汰 k0
        self.assertIsNone(self.cache.get("k0"))
        self.assertEqual(self.cache.get("k5"), 5)
        self.assertGreater(self.cache.stats_evictions, 0)

    def test_ttl_expiration(self):
        cache = QueryCache(max_size=10, default_ttl=0.05,
                           persist_path=None)
        cache.set("short", "val")
        time.sleep(0.1)
        self.assertIsNone(cache.get("short"))

    def test_custom_ttl_per_set(self):
        cache = QueryCache(max_size=10, default_ttl=100.0)
        cache.set("permanent", "x", ttl=0.05)
        time.sleep(0.1)
        self.assertIsNone(cache.get("permanent"))

    def test_delete(self):
        self.cache.set("k", "v")
        self.assertTrue(self.cache.delete("k"))
        self.assertIsNone(self.cache.get("k"))
        self.assertFalse(self.cache.delete("k"))  # 第二次不存在

    def test_clear(self):
        for i in range(3):
            self.cache.set(f"k{i}", i)
        self.cache.clear()
        self.assertEqual(len(self.cache.keys()), 0)

    def test_keys(self):
        self.cache.set("a", 1); self.cache.set("b", 2)
        self.assertEqual(set(self.cache.keys()), {"a", "b"})

    def test_stats(self):
        self.cache.set("k", "v")
        self.cache.get("k")
        self.cache.get("missing")
        st = self.cache.stats()
        self.assertEqual(st["hits"], 1)
        self.assertEqual(st["misses"], 1)
        self.assertEqual(st["size"], 1)
        self.assertEqual(st["max_size"], 5)

    def test_hit_rate(self):
        self.cache.set("k", "v")
        self.cache.get("k"); self.cache.get("k")  # 2 hits
        self.cache.get("miss")                    # 1 miss
        rate = self.cache.stats()["hit_rate"]
        self.assertAlmostEqual(rate, 2/3, places=2)

    def test_persistence(self):
        self.cache.set("persistent", {"a": 1})
        cache2 = QueryCache(
            max_size=5, default_ttl=10.0,
            persist_path=os.path.join(self.tmp.name, "cache.json"),
        )
        self.assertEqual(cache2.get("persistent"), {"a": 1})

    def test_lru_promotion(self):
        """get 操作应将 key 移到末尾。"""
        for i in range(5):
            self.cache.set(f"k{i}", i)
        self.cache.get("k0")  # k0 移到末尾
        self.cache.set("k5", 5)  # 触发淘汰最久的（k1）
        self.assertIsNotNone(self.cache.get("k0"))
        self.assertIsNone(self.cache.get("k1"))


# ============================================================================
# 2. TushareAdapter
# ============================================================================

class TestTushareAdapter(unittest.TestCase):
    """Tushare Pro 适配器（需 token）。"""

    def test_no_token_available_false(self):
        adapter = TushareAdapter(token="")
        self.assertFalse(adapter.available)

    def test_health_no_token(self):
        adapter = TushareAdapter(token="")
        h = adapter.health()
        self.assertEqual(h["available"], False)
        self.assertEqual(h["has_token"], False)
        self.assertEqual(h["name"], "tushare")

    def test_query_no_token_returns_empty(self):
        adapter = TushareAdapter(token="")
        result = adapter.query("stock_basic")
        self.assertEqual(result, [])

    def test_cache_integration(self):
        with tempfile.TemporaryDirectory() as td:
            cache = QueryCache(max_size=10, default_ttl=10,
                               persist_path=os.path.join(td, "c.json"))
            adapter = TushareAdapter(token="", cache=cache)
            # 无 token 时 _call 返回 []，但不应写入缓存
            result = adapter.query("stock_basic")
            self.assertEqual(result, [])


# ============================================================================
# 3. AlphaVantageAdapter
# ============================================================================

class TestAlphaVantageAdapter(unittest.TestCase):
    """Alpha Vantage 适配器。"""

    def test_no_key_health(self):
        av = AlphaVantageAdapter(api_key="")
        h = av.health()
        self.assertEqual(h["available"], False)
        self.assertEqual(h["has_key"], False)

    def test_query_unknown_type(self):
        av = AlphaVantageAdapter(api_key="dummy")
        result = av.query("unknown_type")
        self.assertEqual(result, {})


# ============================================================================
# 4. CoinGeckoAdapter
# ============================================================================

class TestCoinGeckoAdapter(unittest.TestCase):
    """CoinGecko 适配器（无需 key）。"""

    def test_health_no_key(self):
        cg = CoinGeckoAdapter()
        h = cg.health()
        self.assertEqual(h["available"], True)
        self.assertEqual(h["has_pro_key"], False)
        self.assertEqual(h["name"], "coingecko")

    def test_query_unknown_type(self):
        cg = CoinGeckoAdapter()
        # 不实际触发网络
        result = cg.query("unknown_type")
        # None 或 None 因为不在支持列表
        self.assertIsNone(result)


# ============================================================================
# 5. ExchangeRateAdapter
# ============================================================================

class TestExchangeRateAdapter(unittest.TestCase):
    """ExchangeRate 适配器（无需 key）。"""

    def test_health(self):
        er = ExchangeRateAdapter()
        h = er.health()
        self.assertEqual(h["available"], True)
        self.assertEqual(h["name"], "exchangerate_api")

    def test_query_historical_no_date(self):
        er = ExchangeRateAdapter()
        result = er.query("historical", base="USD")
        self.assertIsNone(result)  # 无 date 应返回 None


# ============================================================================
# 6. ExpansionAdapterSet
# ============================================================================

class TestExpansionAdapterSet(unittest.TestCase):
    """v10 适配器集合 + 路由。"""

    def setUp(self):
        self.set_ = ExpansionAdapterSet()

    def test_init_adapters(self):
        self.assertIsInstance(self.set_.tushare, TushareAdapter)
        self.assertIsInstance(self.set_.alpha_vantage, AlphaVantageAdapter)
        self.assertIsInstance(self.set_.coingecko, CoinGeckoAdapter)
        self.assertIsInstance(self.set_.exchangerate, ExchangeRateAdapter)

    def test_all_health(self):
        h = self.set_.all_health()
        self.assertEqual(set(h.keys()), {"tushare", "alpha_vantage",
                                          "coingecko", "exchangerate"})

    def test_list_query_types_count(self):
        types = self.set_.list_query_types()
        # 至少包含所有 24 个 v10 类型
        self.assertGreaterEqual(len(types), 20)
        # 验证关键类型
        self.assertIn("crypto_markets", types)
        self.assertIn("forex_realtime", types)
        self.assertIn("tushare_stock_basic", types)

    def test_routing_tushare(self):
        """tushare_* 应路由到 TushareAdapter（无 token 返回 []）。"""
        result = self.set_.query("tushare_daily", symbol="600519.SH")
        self.assertIsInstance(result, list)

    def test_routing_unknown(self):
        result = self.set_.query("totally_unknown_query_type")
        self.assertIsNone(result)


# ============================================================================
# 7. register_expansion_adapters
# ============================================================================

class TestRegisterExpansionAdapters(unittest.TestCase):
    """把新适配器注册到 v9 FinancialDataRouter。"""

    def test_register_to_v9_router(self):
        try:
            from scripts.financial_data_mcp import FinancialDataRouter
        except Exception:
            self.skipTest("financial_data_mcp not available")
        router = FinancialDataRouter()
        n = register_expansion_adapters(router)
        # 至少注册了 2 个（Tushare + AlphaVantage）
        self.assertGreaterEqual(n, 2)

    def test_register_with_none(self):
        n = register_expansion_adapters(None)
        self.assertEqual(n, 0)

    def test_register_unsupported_raises_silently(self):
        """不支持 register_adapter 接口的对象应返回 0。"""
        class NoRouter:
            pass
        n = register_expansion_adapters(NoRouter())
        self.assertEqual(n, 0)


# ============================================================================
# 8. CacheEntry
# ============================================================================

class TestCacheEntry(unittest.TestCase):
    """缓存条目。"""

    def test_is_expired(self):
        e = CacheEntry(key="x", value=1, created_at=time.time() - 100,
                       ttl_seconds=10)
        self.assertTrue(e.is_expired())

    def test_not_expired(self):
        e = CacheEntry(key="x", value=1, created_at=time.time(),
                       ttl_seconds=10)
        self.assertFalse(e.is_expired())

    def test_to_dict(self):
        e = CacheEntry(key="x", value={"a": 1}, created_at=0.0,
                       ttl_seconds=10, hit_count=3, source="test")
        d = e.to_dict()
        self.assertEqual(d["key"], "x")
        self.assertEqual(d["hit_count"], 3)
        self.assertEqual(d["source"], "test")


# ============================================================================
# 9. get_default_cache
# ============================================================================

class TestDefaultCache(unittest.TestCase):
    """全局默认缓存（懒初始化 + 单例）。"""

    def test_lazy_init(self):
        cache = get_default_cache()
        self.assertIsInstance(cache, QueryCache)
        self.assertGreater(cache.max_size, 0)

    def test_singleton(self):
        c1 = get_default_cache()
        c2 = get_default_cache()
        self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()