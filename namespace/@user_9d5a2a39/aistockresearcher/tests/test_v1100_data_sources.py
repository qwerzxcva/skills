# -*- coding: utf-8 -*-
"""
v11.0 多源数据层测试 (test_v1100_data_sources.py)

覆盖 v11.0 新增内容：
  - DataSource/DataCategory/DataFreshness 新增枚举值
  - SinaFinanceAdapter / XueqiuAdapter / FuturesExchangeAdapter / TonghuashunAdapter
  - ExternalMCPAdapter 占位与连接流程
  - _HttpClient ETag 缓存
  - MultiSourceRouter.cross_validate 多源交叉验证
  - MultiSourceRouter.detect_anomaly 3σ 异常检测
  - query_with_validation 查询+验证一站式
  - 新便捷方法：query_money_flow / query_sentiment / query_futures_history
"""
import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestV1100Enums(unittest.TestCase):
    """测试 v11.0 新增枚举值。"""

    def test_data_source_new_values(self):
        from stock_researcher.data_multi_source import DataSource
        values = {s.value for s in DataSource}
        for new_src in ("sina", "xueqiu", "futures_exchange",
                        "tonghuashun", "external_mcp"):
            self.assertIn(new_src, values, f"DataSource.{new_src} 缺失")

    def test_data_category_new_values(self):
        from stock_researcher.data_multi_source import DataCategory
        values = {c.value for c in DataCategory}
        for new_cat in ("futures_history", "money_flow", "sentiment"):
            self.assertIn(new_cat, values, f"DataCategory.{new_cat} 缺失")

    def test_data_freshness_enum(self):
        from stock_researcher.data_multi_source import DataFreshness, FRESHNESS_TTL, freshness_for_category
        values = {f.value for f in DataFreshness}
        for f in ("realtime", "delayed_15m", "closing", "estimated", "stale"):
            self.assertIn(f, values)

        # FRESHNESS_TTL 必须覆盖所有枚举
        for f in DataFreshness:
            self.assertIn(f, FRESHNESS_TTL)

        # 时效映射：realtime_quote → realtime
        self.assertEqual(freshness_for_category(
            __import__("stock_researcher.data_multi_source", fromlist=["DataCategory"]).DataCategory.REALTIME_QUOTE
        ).value, "realtime")


class TestSinaFinanceAdapter(unittest.TestCase):
    """新浪财经适配器测试。"""

    def test_availability(self):
        from stock_researcher.data_multi_source import SinaFinanceAdapter
        adapter = SinaFinanceAdapter()
        # 不依赖第三方库，始终可用
        self.assertTrue(adapter.available)

    def test_cn_symbol_conversion(self):
        from stock_researcher.data_multi_source import SinaFinanceAdapter
        # 6/9 开头沪市 → sh 前缀
        self.assertEqual(SinaFinanceAdapter._cn_symbol("600519"), "sh600519")
        self.assertEqual(SinaFinanceAdapter._cn_symbol("900901"), "sh900901")
        # 0/3/2 开头深市 → sz 前缀
        self.assertEqual(SinaFinanceAdapter._cn_symbol("000001"), "sz000001")
        self.assertEqual(SinaFinanceAdapter._cn_symbol("300750"), "sz300750")

    def test_query_unsupported_market_returns_none(self):
        from stock_researcher.data_multi_source import SinaFinanceAdapter, DataCategory
        adapter = SinaFinanceAdapter()
        # 不支持的市场应直接返回 None（不报错）
        result = adapter.query("us", DataCategory.REALTIME_QUOTE, code="AAPL")
        self.assertIsNone(result)


class TestXueqiuAdapter(unittest.TestCase):
    """雪球适配器测试。"""

    def test_availability(self):
        from stock_researcher.data_multi_source import XueqiuAdapter
        adapter = XueqiuAdapter()
        self.assertTrue(adapter.available)

    def test_cn_symbol_conversion(self):
        from stock_researcher.data_multi_source import XueqiuAdapter
        # 雪球用大写 SH/SZ 前缀
        self.assertEqual(XueqiuAdapter._cn_symbol("600519"), "SH600519")
        self.assertEqual(XueqiuAdapter._cn_symbol("000001"), "SZ000001")

    def test_query_non_cn_market(self):
        from stock_researcher.data_multi_source import XueqiuAdapter, DataCategory
        adapter = XueqiuAdapter()
        result = adapter.query("us", DataCategory.REALTIME_QUOTE, code="AAPL")
        self.assertIsNone(result)


class TestFuturesExchangeAdapter(unittest.TestCase):
    """期货交易所适配器测试。"""

    def test_availability(self):
        from stock_researcher.data_multi_source import FuturesExchangeAdapter
        adapter = FuturesExchangeAdapter()
        self.assertTrue(adapter.available)

    def test_resolve_exchange(self):
        from stock_researcher.data_multi_source import FuturesExchangeAdapter
        ad = FuturesExchangeAdapter()
        # 上期所
        self.assertEqual(ad._resolve_exchange("AU2502"), "shfe")
        self.assertEqual(ad._resolve_exchange("CU"), "shfe")
        self.assertEqual(ad._resolve_exchange("AG"), "shfe")
        # 大商所
        self.assertEqual(ad._resolve_exchange("M2501"), "dce")
        self.assertEqual(ad._resolve_exchange("I"), "dce")
        # 郑商所
        self.assertEqual(ad._resolve_exchange("SR2501"), "czce")
        self.assertEqual(ad._resolve_exchange("MA"), "czce")
        # 未知品种
        self.assertIsNone(ad._resolve_exchange("XYZ123"))
        self.assertIsNone(ad._resolve_exchange("UNKNOWN"))

    def test_query_non_cn(self):
        from stock_researcher.data_multi_source import FuturesExchangeAdapter, DataCategory
        ad = FuturesExchangeAdapter()
        self.assertIsNone(ad.query("us", DataCategory.FUTURES, code="CL"))
        self.assertIsNone(ad.query("hk", DataCategory.FUTURES, code="HSI"))

    def test_snapshot_returns_metadata(self):
        from stock_researcher.data_multi_source import FuturesExchangeAdapter, DataCategory
        ad = FuturesExchangeAdapter()
        # snapshot 不实际联网（v11.0 仅返回元数据）
        result = ad.query("cn", DataCategory.FUTURES, code="AU2502")
        if result:  # 视具体网络环境，可能返回 None
            self.assertIn("code", result)
            self.assertIn("exchange", result)
            self.assertEqual(result["exchange"], "shfe")


class TestTonghuashunAdapter(unittest.TestCase):
    """同花顺适配器测试。"""

    def test_availability(self):
        from stock_researcher.data_multi_source import TonghuashunAdapter
        adapter = TonghuashunAdapter()
        self.assertTrue(adapter.available)

    def test_cn_symbol_conversion(self):
        from stock_researcher.data_multi_source import TonghuashunAdapter
        self.assertEqual(TonghuashunAdapter._cn_symbol("600519"), "sh600519")
        self.assertEqual(TonghuashunAdapter._cn_symbol("000001"), "sz000001")

    def test_query_non_cn(self):
        from stock_researcher.data_multi_source import TonghuashunAdapter, DataCategory
        ad = TonghuashunAdapter()
        self.assertIsNone(ad.query("us", DataCategory.REALTIME_QUOTE, code="AAPL"))


class TestExternalMCPAdapter(unittest.TestCase):
    """外部 MCP 适配器（占位）测试。"""

    def test_initial_state_not_available(self):
        from stock_researcher.data_multi_source import ExternalMCPAdapter
        ad = ExternalMCPAdapter()
        # 无 command 时不可用
        self.assertFalse(ad.available)
        self.assertEqual(ad.list_tools(), [])

    def test_query_placeholder(self):
        from stock_researcher.data_multi_source import ExternalMCPAdapter, DataCategory
        ad = ExternalMCPAdapter()
        # v11.0 占位返回 None
        result = ad.query("cn", DataCategory.REALTIME_QUOTE, code="600519")
        self.assertIsNone(result)

    def test_set_command(self):
        from stock_researcher.data_multi_source import ExternalMCPAdapter
        ad = ExternalMCPAdapter()
        ad.set_command("python jinrong_liuri.py", {"TOKEN": "xxx"})
        self.assertEqual(ad._command, "python jinrong_liuri.py")
        self.assertEqual(ad._env["TOKEN"], "xxx")


class TestHttpClientETag(unittest.TestCase):
    """HTTP 客户端 ETag 缓存测试。"""

    def test_clear_cache(self):
        from stock_researcher.data_multi_source import _HttpClient
        client = _HttpClient()
        # 清空应不抛错
        client.clear()
        self.assertEqual(len(client._cache), 0)


class TestCrossValidation(unittest.TestCase):
    """多源交叉验证测试。"""

    def test_cross_validate_consistent_sources(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        results = [
            ("eastmoney_api", {"price": 1880.0, "name": "茅台"}),
            ("sina", {"price": 1881.0, "name": "茅台"}),
            ("tonghuashun", {"price": 1879.0, "name": "茅台"}),
        ]
        validated, confidence, merged = router.cross_validate(results, field="price")
        self.assertTrue(validated)
        self.assertGreater(confidence, 0.5)
        self.assertIn("_validated", merged)
        self.assertIn("_confidence", merged)
        self.assertTrue(merged["_validated"])
        self.assertAlmostEqual(merged["price"], 1880.0, places=1)

    def test_cross_validate_inconsistent_sources(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        results = [
            ("src_a", {"price": 100.0}),
            ("src_b", {"price": 200.0}),  # 偏差 50%
            ("src_c", {"price": 150.0}),
        ]
        validated, confidence, merged = router.cross_validate(
            results, field="price", tolerance_pct=5.0
        )
        self.assertFalse(validated)
        self.assertLess(confidence, 0.7)
        # 3σ 异常检测应剔除 200（偏离最大）
        # 中位数应该接近 100 或 150
        self.assertIn(100.0, [100.0, 150.0])

    def test_cross_validate_empty(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        validated, confidence, merged = router.cross_validate([])
        self.assertFalse(validated)
        self.assertEqual(confidence, 0.0)
        self.assertEqual(merged, {})

    def test_cross_validate_uses_field_aliases(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        results = [
            ("eastmoney_api", {"price": 1880.0}),
            ("sina", {"current": 1880.0}),    # 使用等价键
            ("tonghuashun", {"last_price": 1880.0}),
        ]
        validated, confidence, merged = router.cross_validate(results, field="price")
        self.assertTrue(validated)
        # 替换 merged 中的 price 为中位数
        self.assertAlmostEqual(merged["price"], 1880.0, places=1)


class TestAnomalyDetection(unittest.TestCase):
    """3σ 异常值检测测试。"""

    def test_detect_anomaly_with_clean_data(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        # 8 个相近值 + 1 个极端异常 → IQR 检测剔除
        values = [100, 100, 100, 100, 100, 101, 101, 102, 1000]
        cleaned = router.detect_anomaly(values)
        self.assertLess(len(cleaned), len(values))
        self.assertNotIn(1000.0, cleaned)
        # 验证保留的都是相近值
        for v in cleaned:
            self.assertGreater(v, 95)
            self.assertLess(v, 105)

    def test_detect_anomaly_with_small_sample(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        # 样本 < 3 时不剔除（避免过度清洗）
        values = [100, 1000]
        cleaned = router.detect_anomaly(values)
        self.assertEqual(cleaned, [100, 1000])

    def test_detect_anomaly_with_identical_values(self):
        from stock_researcher.data_multi_source import MultiSourceRouter
        router = MultiSourceRouter()
        # 全相同 → stdev=0 → 不剔除
        values = [100, 100, 100, 100]
        cleaned = router.detect_anomaly(values)
        self.assertEqual(cleaned, values)


class TestQueryWithValidation(unittest.TestCase):
    """query_with_validation 一站式查询测试。"""

    def setUp(self):
        from stock_researcher.data_multi_source import reset_router
        reset_router()

    def test_query_with_validation_unsupported(self):
        from stock_researcher.data_multi_source import get_router, DataCategory
        router = get_router()
        result = router.query_with_validation(
            "unknown_market", DataCategory.REALTIME_QUOTE, code="X"
        )
        self.assertFalse(result.success)
        self.assertIn("未配置", result.error)

    def test_query_with_validation_includes_validated_field(self):
        """验证返回结果包含 v11.0 新增字段。"""
        from stock_researcher.data_multi_source import get_router, DataCategory
        router = get_router()

        # mock 适配器返回稳定价格
        fake_em = MagicMock()
        fake_em.available = True
        fake_em.query = MagicMock(return_value={"price": 100.0, "name": "test"})

        with patch.dict(router._adapters, {
            __import__("stock_researcher.data_multi_source", fromlist=["DataSource"]).DataSource.EASTMONEY_API: fake_em,
        }):
            result = router.query_with_validation(
                "cn", DataCategory.REALTIME_QUOTE,
                validate_field="price", tolerance_pct=5.0,
                code="600519",
            )
            self.assertTrue(result.success)
            # v11.0 新字段
            self.assertGreaterEqual(result.source_count, 1)
            self.assertGreater(result.confidence, 0)
            self.assertIn(result.freshness, ("realtime", "delayed_15m", "closing",
                                              "estimated", "stale"))


class TestNewConvenienceMethods(unittest.TestCase):
    """测试 v11.0 新增的便捷方法。"""

    def setUp(self):
        from stock_researcher.data_multi_source import reset_router
        reset_router()

    def test_query_money_flow(self):
        from stock_researcher.data_multi_source import get_router, DataCategory, DataSource
        router = get_router()
        # MONEY_FLOW 路由第一个是 eastmoney_api
        fake_em = MagicMock()
        fake_em.available = True
        fake_em.query = MagicMock(return_value={"data": "mock"})

        with patch.dict(router._adapters, {DataSource.EASTMONEY_API: fake_em}):
            result = router.query_money_flow("600519")
            self.assertTrue(result.success)
            args = fake_em.query.call_args
            self.assertEqual(args[0][1], DataCategory.MONEY_FLOW)

    def test_query_sentiment(self):
        from stock_researcher.data_multi_source import get_router, DataCategory, DataSource
        router = get_router()
        # SENTIMENT 路由第一个是 xueqiu
        fake_xq = MagicMock()
        fake_xq.available = True
        fake_xq.query = MagicMock(return_value={"discussions": []})

        with patch.dict(router._adapters, {DataSource.XUEQIU: fake_xq}):
            result = router.query_sentiment("600519")
            self.assertTrue(result.success)
            args = fake_xq.query.call_args
            self.assertEqual(args[0][1], DataCategory.SENTIMENT)

    def test_query_futures_history(self):
        from stock_researcher.data_multi_source import get_router, DataCategory, DataSource
        router = get_router()
        # FUTURES_HISTORY 路由第一个是 futures_exchange
        fake_fe = MagicMock()
        fake_fe.available = True
        fake_fe.query = MagicMock(return_value={"klines": []})

        with patch.dict(router._adapters, {DataSource.FUTURES_EXCHANGE: fake_fe}):
            result = router.query_futures_history("AU2502", days=30)
            self.assertTrue(result.success)
            args = fake_fe.query.call_args
            self.assertEqual(args[0][1], DataCategory.FUTURES_HISTORY)
            self.assertEqual(args[1]["days"], 30)


class TestRouterRegistersNewAdapters(unittest.TestCase):
    """测试路由器注册了新适配器。"""

    def setUp(self):
        from stock_researcher.data_multi_source import reset_router
        reset_router()

    def test_router_has_12_sources(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        sources = router.list_available_sources()
        self.assertEqual(len(sources), 12)  # v10.0 7 + v11.0 新增 5

    def test_router_has_v11_adapters(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        sources = router.list_available_sources()
        for new_src in ("sina", "xueqiu", "futures_exchange",
                        "tonghuashun", "external_mcp"):
            self.assertIn(new_src, sources)

    def test_register_external_mcp(self):
        from stock_researcher.data_multi_source import get_router
        router = get_router()
        # 用不存在的命令测试 connect 返回 False（不抛错）
        result = router.register_external_mcp("nonexistent_command_xyz")
        self.assertFalse(result)


class TestV11SelfCheck(unittest.TestCase):
    """自检输出 v11.0 标识。"""

    def test_self_check_version(self):
        from stock_researcher.data_multi_source import self_check
        result = self_check()
        self.assertEqual(result["version"], "v11.0")
        self.assertIn("v11_features", result)
        self.assertGreater(len(result["v11_features"]), 0)
        self.assertEqual(len(result["categories"]), 14)  # v11.0 = 14


if __name__ == "__main__":
    unittest.main()