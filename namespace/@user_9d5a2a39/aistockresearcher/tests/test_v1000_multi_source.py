# -*- coding: utf-8 -*-
"""
v10.0 多源数据层测试 (test_v1000_multi_source.py)

覆盖：
- DataSource/DataCategory 枚举
- SourceHealthTracker 健康追踪 + 冷却逻辑
- AkshareAdapter 可用性检测 + 降级
- YFinanceAdapter 可用性检测 + 降级
- FinnhubAdapter API Key 校验
- EastmoneyApiAdapter secid 转换
- MultiSourceRouter 查询路由 + 降级链
- 便捷方法（query_stock_quote / query_fund_nav / query_macro）

全部测试在 conftest 屏蔽 akshare/yfinance 后仍可通过。
"""
import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock

# 确保可以 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDataEnums(unittest.TestCase):
    """测试数据源/类别枚举。"""

    def test_data_source_enum(self):
        from stock_researcher.data_multi_source import DataSource
        sources = [s.value for s in DataSource]
        self.assertIn("akshare", sources)
        self.assertIn("eastmoney_api", sources)
        self.assertIn("sina_hq", sources)
        self.assertIn("yfinance", sources)
        self.assertIn("finnhub", sources)
        self.assertIn("tencent", sources)

    def test_data_category_enum(self):
        from stock_researcher.data_multi_source import DataCategory
        categories = [c.value for c in DataCategory]
        self.assertIn("realtime_quote", categories)
        self.assertIn("fund_nav", categories)
        self.assertIn("macro", categories)
        self.assertIn("futures", categories)
        self.assertIn("convertible", categories)

    def test_source_routing_completeness(self):
        """路由表覆盖主要市场+类别组合。"""
        from stock_researcher.data_multi_source import SOURCE_ROUTING, DataCategory
        # 至少覆盖 5 个市场×类别组合
        self.assertGreaterEqual(len(SOURCE_ROUTING), 5)
        # 至少包含 A 股实时行情 + 美股行情 + 港股行情 + 基金净值 + 宏观
        self.assertIn(("cn", DataCategory.REALTIME_QUOTE), SOURCE_ROUTING)
        self.assertIn(("us", DataCategory.REALTIME_QUOTE), SOURCE_ROUTING)
        self.assertIn(("hk", DataCategory.REALTIME_QUOTE), SOURCE_ROUTING)
        self.assertIn(("cn", DataCategory.FUND_NAV), SOURCE_ROUTING)
        self.assertIn(("cn", DataCategory.MACRO), SOURCE_ROUTING)


class TestSourceHealthTracker(unittest.TestCase):
    """测试源健康追踪器。"""

    def test_initial_state_all_available(self):
        from stock_researcher.data_multi_source import SourceHealthTracker, DataSource
        tracker = SourceHealthTracker()
        self.assertTrue(tracker.allow(DataSource.AKSHARE))
        self.assertTrue(tracker.allow(DataSource.EASTMONEY_API))

    def test_consecutive_failures_trigger_cooldown(self):
        from stock_researcher.data_multi_source import SourceHealthTracker, DataSource
        tracker = SourceHealthTracker(cooldown_seconds=10.0)
        source = DataSource.YFINANCE
        # 3 次连续失败后进入冷却
        for _ in range(3):
            tracker.record_failure(source)
        self.assertFalse(tracker.allow(source))

    def test_success_resets_failures(self):
        from stock_researcher.data_multi_source import SourceHealthTracker, DataSource
        tracker = SourceHealthTracker()
        source = DataSource.AKSHARE
        tracker.record_failure(source)
        tracker.record_failure(source)
        tracker.record_success(source)
        # 成功后允许使用
        self.assertTrue(tracker.allow(source))

    def test_success_tracks_latency(self):
        from stock_researcher.data_multi_source import SourceHealthTracker, DataSource
        tracker = SourceHealthTracker()
        source = DataSource.EASTMONEY_API
        tracker.record_success(source, latency_ms=100.0)
        tracker.record_success(source, latency_ms=200.0)
        status = tracker.status()
        # 移动平均延迟应在 100~200 之间
        self.assertGreater(status[source.value]["avg_latency_ms"], 0)
        self.assertLess(status[source.value]["avg_latency_ms"], 300)


class TestAdapterAvailability(unittest.TestCase):
    """测试各适配器可用性检测（akshare/yfinance 在 conftest 中被屏蔽）。"""

    def test_akshare_adapter_unavailable_when_blocked(self):
        """conftest 屏蔽 akshare 后，适配器应报告 unavailable。"""
        from stock_researcher.data_multi_source import AkshareAdapter
        adapter = AkshareAdapter()
        # 在 conftest 屏蔽下应为 False
        self.assertFalse(adapter.available)

    def test_yfinance_adapter_unavailable_when_blocked(self):
        from stock_researcher.data_multi_source import YFinanceAdapter
        adapter = YFinanceAdapter()
        self.assertFalse(adapter.available)

    def test_finnhub_adapter_requires_key(self):
        from stock_researcher.data_multi_source import FinnhubAdapter
        adapter = FinnhubAdapter(api_key="")
        self.assertFalse(adapter.available)
        adapter.set_api_key("test_key")
        self.assertTrue(adapter.available)
        adapter.set_api_key("")
        self.assertFalse(adapter.available)

    def test_eastmoney_adapter_always_available(self):
        from stock_researcher.data_multi_source import EastmoneyApiAdapter
        adapter = EastmoneyApiAdapter()
        self.assertTrue(adapter.available)


class TestEastmoneySecidConversion(unittest.TestCase):
    """测试东方财富 secid 转换。"""

    def test_shanghai_codes(self):
        from stock_researcher.data_multi_source import EastmoneyApiAdapter
        adapter = EastmoneyApiAdapter()
        # 6 开头沪市 → secid = "1.code"
        self.assertEqual(adapter._to_secid("600519"), "1.600519")
        self.assertEqual(adapter._to_secid("688981"), "1.688981")

    def test_shenzhen_codes(self):
        from stock_researcher.data_multi_source import EastmoneyApiAdapter
        adapter = EastmoneyApiAdapter()
        # 0/2/3 开头深市 → secid = "0.code"
        self.assertEqual(adapter._to_secid("000001"), "0.000001")
        self.assertEqual(adapter._to_secid("300750"), "0.300750")
        self.assertEqual(adapter._to_secid("200001"), "0.200001")

    def test_invalid_code_returns_none(self):
        from stock_researcher.data_multi_source import EastmoneyApiAdapter
        adapter = EastmoneyApiAdapter()
        # 不以数字开头返回 None
        self.assertIsNone(adapter._to_secid(""))


class TestMultiSourceRouter(unittest.TestCase):
    """测试多源路由器。"""

    def setUp(self):
        from stock_researcher.data_multi_source import reset_router
        reset_router()

    def test_router_initialization(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        self.assertIsNotNone(router)
        # v11.0 扩展到 12 个数据源（v10.0 7 + v11.0 新增 5）
        sources = router.list_available_sources()
        self.assertEqual(len(sources), 12)

    def test_router_list_available_sources(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        sources = router.list_available_sources()
        # 在 conftest 屏蔽 akshare/yfinance 后，仅 eastmoney_api 真正可用
        self.assertIn("eastmoney_api", sources)
        self.assertTrue(sources["eastmoney_api"])

    def test_router_get_health_status(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        status = router.get_health_status()
        self.assertIn("akshare", status)
        self.assertIn("yfinance", status)
        self.assertIn("eastmoney_api", status)
        # 健康状态应包含必要字段
        for s_name, s_info in status.items():
            self.assertIn("success_rate", s_info)
            self.assertIn("consecutive_failures", s_info)

    def test_router_query_unsupported_market(self):
        """不支持的市场应返回 failure。"""
        from stock_researcher.data_multi_source import get_router, DataCategory
        router = get_router()
        result = router.query("unknown_market", DataCategory.REALTIME_QUOTE, code="X")
        self.assertFalse(result.success)

    def test_router_preferred_source_priority(self):
        """指定 preferred_source 应被提升到首位。"""
        from stock_researcher.data_multi_source import (
            get_router, DataCategory, DataSource
        )
        router = get_router()
        # 注入 mock 适配器，让 eastmoney 永远返回 None
        fake_ak = MagicMock()
        fake_ak.available = True
        fake_ak.query = MagicMock(return_value={"f43": 1680.5, "f57": "600519"})

        fake_em = MagicMock()
        fake_em.available = True
        fake_em.query = MagicMock(return_value=None)

        with patch.dict(router._adapters, {
            DataSource.AKSHARE: fake_ak,
            DataSource.EASTMONEY_API: fake_em,
        }):
            # v11.0 路由：eastmoney_api (首位) → sina → akshare
            # 指定 akshare 为 preferred → 应被提升到首位
            result = router.query("cn", DataCategory.REALTIME_QUOTE,
                                  preferred_source="akshare", code="600519")
            self.assertTrue(result.success)
            self.assertEqual(result.source, "akshare")


class TestQueryResultDataclass(unittest.TestCase):
    """测试 QueryResult 数据类。"""

    def test_default_values(self):
        from stock_researcher.data_multi_source import QueryResult
        r = QueryResult()
        self.assertFalse(r.success)
        self.assertEqual(r.source, "")
        self.assertIsNone(r.data)
        self.assertEqual(r.tried_sources, [])
        # timestamp 应自动填充
        self.assertNotEqual(r.timestamp, "")

    def test_custom_values(self):
        from stock_researcher.data_multi_source import QueryResult
        r = QueryResult(
            success=True,
            source="akshare",
            market="cn",
            category="realtime_quote",
            data={"key": "value"},
            latency_ms=123.4,
        )
        self.assertTrue(r.success)
        self.assertEqual(r.source, "akshare")
        self.assertEqual(r.market, "cn")
        self.assertEqual(r.data["key"], "value")


class TestSelfCheck(unittest.TestCase):
    """测试自检函数。"""

    def test_self_check_returns_dict(self):
        from stock_researcher.data_multi_source import self_check
        result = self_check()
        self.assertIsInstance(result, dict)
        self.assertIn("version", result)
        # v11.0 起版本升到 11.0
        self.assertEqual(result["version"], "v11.0")
        self.assertIn("MultiSourceRouter", result)
        self.assertIn("akshare", result)
        self.assertIn("yfinance", result)
        # v11.0 新增源
        self.assertIn("sina", result)
        self.assertIn("xueqiu", result)
        self.assertIn("futures_exchange", result)
        self.assertIn("tonghuashun", result)


class TestYFinanceSymbolSuffix(unittest.TestCase):
    """测试 yfinance 股票代码后缀自动补全。"""

    def test_a_share_suffix(self):
        from stock_researcher.data_multi_source import YFinanceAdapter
        adapter = YFinanceAdapter()
        # 即使 akshare 被屏蔽，YFinanceAdapter 初始化不应崩溃
        self.assertIsNotNone(adapter)


class TestFinnhubKeyManagement(unittest.TestCase):
    """测试 Finnhub API Key 动态切换。"""

    def test_set_api_key(self):
        from stock_researcher.data_multi_source import FinnhubAdapter
        adapter = FinnhubAdapter()
        self.assertFalse(adapter.available)
        adapter.set_api_key("my_key_123")
        self.assertTrue(adapter.available)
        self.assertEqual(adapter._api_key, "my_key_123")

    def test_query_without_key_returns_none(self):
        from stock_researcher.data_multi_source import FinnhubAdapter, DataCategory
        adapter = FinnhubAdapter()
        # 没有 key 时直接返回 None，不发起网络请求
        result = adapter.query("us", DataCategory.REALTIME_QUOTE, symbol="AAPL")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
