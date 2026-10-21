# -*- coding: utf-8 -*-
"""
v10.0 AI 分析引擎测试 (test_v1000_ai_engine.py)

覆盖：
- LLMConfig 数据类
- LLMClient HTTP 调用（mock）
- AIAnalysisEngine.analyze 缓存/降级/正常路径
- 7 类分析模板的提示词格式化
- 配置加载（环境变量 + settings.json）

不依赖真实 LLM API（通过 mock 或 fallback 路径测试）。
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLLMConfig(unittest.TestCase):
    """测试 LLMConfig 数据类。"""

    def test_default_values(self):
        from stock_researcher.ai_analysis_engine import LLMConfig
        config = LLMConfig()
        self.assertEqual(config.provider, "deepseek")
        self.assertIn("deepseek", config.base_url)
        self.assertEqual(config.temperature, 0.3)
        self.assertEqual(config.max_tokens, 2000)

    def test_custom_values(self):
        from stock_researcher.ai_analysis_engine import LLMConfig
        config = LLMConfig(
            provider="openai",
            base_url="https://api.openai.com",
            model="gpt-4",
            api_key="sk-test",
            temperature=0.5,
            max_tokens=4000,
            timeout=120,
        )
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-4")
        self.assertEqual(config.api_key, "sk-test")
        self.assertEqual(config.timeout, 120)


class TestConfigLoading(unittest.TestCase):
    """测试配置加载逻辑。"""

    def test_env_var_overrides_settings(self):
        """环境变量应覆盖 settings.json 中的配置。"""
        from stock_researcher.ai_analysis_engine import LLMConfig, load_llm_config
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key-123", "LLM_PROVIDER": "deepseek"}):
            config = load_llm_config(settings_path="nonexistent.json")
            self.assertEqual(config.api_key, "env-key-123")

    def test_default_when_no_settings(self):
        """无 settings.json 时使用默认值。"""
        from stock_researcher.ai_analysis_engine import load_llm_config
        config = load_llm_config(settings_path="/nonexistent/path/settings.json")
        # 默认 deepseek provider
        self.assertEqual(config.provider, "deepseek")
        self.assertIn("deepseek.com", config.base_url)

    def test_provider_specific_base_url(self):
        """不同 provider 应有正确的 base_url 兜底。"""
        from stock_researcher.ai_analysis_engine import load_llm_config
        # 在测试中显式清除 DEEPSEEK_API_KEY，避免被默认 provider 优先读取
        env = {k: v for k, v in os.environ.items()
               if k not in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY", "LLM_PROVIDER")}
        env["OPENAI_API_KEY"] = "sk-test"
        env["LLM_PROVIDER"] = "openai"
        with patch.dict(os.environ, env, clear=True):
            config = load_llm_config(settings_path="/nonexistent.json")
            self.assertEqual(config.provider, "openai")
            self.assertIn("openai.com", config.base_url)


class TestPromptTemplates(unittest.TestCase):
    """测试提示词模板。"""

    def test_all_templates_defined(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        expected = [
            "stock_analysis", "fund_analysis", "market_regime",
            "master_council", "macro_outlook", "risk_report", "sector_rotation",
        ]
        for name in expected:
            self.assertIn(name, PROMPT_TEMPLATES)
            self.assertIn("{", PROMPT_TEMPLATES[name])

    def test_stock_analysis_template(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        template = PROMPT_TEMPLATES["stock_analysis"]
        self.assertIn("code", template)
        self.assertIn("price", template)
        self.assertIn("ROE", template)
        # 必须包含免责声明提示
        self.assertIn("投资建议", template)

    def test_fund_analysis_template(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        template = PROMPT_TEMPLATES["fund_analysis"]
        self.assertIn("fund_type", template)
        self.assertIn("夏普", template)

    def test_market_regime_template(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        template = PROMPT_TEMPLATES["market_regime"]
        self.assertIn("sh_close", template)
        # 必须涵盖市场体制判断词汇
        self.assertTrue("震荡" in template or "体制" in template)


class TestLLMClient(unittest.TestCase):
    """测试 LLM 客户端 HTTP 调用。"""

    def test_unavailable_without_api_key(self):
        from stock_researcher.ai_analysis_engine import LLMClient, LLMConfig
        config = LLMConfig(provider="deepseek", api_key="")
        client = LLMClient(config)
        self.assertFalse(client.is_available())
        result = client.chat([{"role": "user", "content": "hi"}])
        self.assertFalse(result["success"])
        self.assertIn("API Key", result["error"])

    def test_chat_success(self):
        from stock_researcher.ai_analysis_engine import LLMClient, LLMConfig
        config = LLMConfig(provider="deepseek", api_key="sk-test", base_url="https://example.com")
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.read = MagicMock(return_value=json.dumps({
            "choices": [{"message": {"content": "AI 回复内容"}}],
            "model": "deepseek-chat",
            "usage": {"total_tokens": 100},
        }).encode("utf-8"))
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        # ai_analysis_engine 直接 import 了 urlopen，需 patch 模块内的引用
        with patch("stock_researcher.ai_analysis_engine.urlopen", return_value=mock_response):
            result = client.chat([{"role": "user", "content": "分析 600519"}])
            self.assertTrue(result["success"])
            self.assertEqual(result["content"], "AI 回复内容")
            self.assertEqual(result["usage"]["total_tokens"], 100)

    def test_chat_http_error(self):
        from stock_researcher.ai_analysis_engine import LLMClient, LLMConfig
        from urllib.error import HTTPError
        config = LLMConfig(provider="deepseek", api_key="sk-test")
        client = LLMClient(config)

        err = HTTPError(url="http://x", code=401, msg="Unauthorized", hdrs={}, fp=None)
        with patch("stock_researcher.ai_analysis_engine.urlopen", side_effect=err):
            result = client.chat([{"role": "user", "content": "x"}])
            self.assertFalse(result["success"])
            self.assertIn("401", result["error"])

    def test_chat_network_error(self):
        from stock_researcher.ai_analysis_engine import LLMClient, LLMConfig
        from urllib.error import URLError
        config = LLMConfig(provider="deepseek", api_key="sk-test")
        client = LLMClient(config)

        with patch("stock_researcher.ai_analysis_engine.urlopen",
                   side_effect=URLError("connection refused")):
            result = client.chat([{"role": "user", "content": "x"}])
            self.assertFalse(result["success"])
            self.assertIn("网络", result["error"])


class TestAIEngineFallback(unittest.TestCase):
    """测试 LLM 不可用时的降级路径。"""

    def test_unavailable_uses_fallback_template(self):
        """无 API Key 时应返回模板化输出。"""
        from stock_researcher.ai_analysis_engine import LLMConfig, AIAnalysisEngine
        config = LLMConfig(provider="deepseek", api_key="")
        engine = AIAnalysisEngine(config)
        self.assertFalse(engine.is_available())

        result = engine.analyze("stock_analysis", {
            "code": "600519", "name": "贵州茅台", "market": "A股",
            "price": "1680", "change_pct": "+1.0",
            "high": "1690", "low": "1670", "volume": "1万", "amount": "10亿",
            "pe_ttm": "28", "pb": "9", "div_yield": "1.5",
            "roe": "32", "gross_margin": "91", "net_margin": "52",
            "revenue_yoy": "15", "profit_yoy": "18",
            "ma_status": "多头", "macd": "金叉", "rsi": "55", "trend": "偏强",
            "score": "70", "short_term_view": "看多", "medium_term_view": "中性",
            "bull_count": "3", "bear_count": "2", "neutral_count": "1",
        }, use_cache=False)
        self.assertTrue(result.success)
        self.assertTrue(result.is_fallback)
        self.assertIn("规则引擎版", result.content)


class TestAIEngineSuccess(unittest.TestCase):
    """测试 LLM 可用时的成功路径。"""

    def test_successful_analysis(self):
        from stock_researcher.ai_analysis_engine import (
            AIAnalysisEngine, LLMConfig, AnalysisResult
        )
        config = LLMConfig(provider="deepseek", api_key="sk-test")
        engine = AIAnalysisEngine(config)
        self.assertTrue(engine.is_available())

        mock_response = MagicMock()
        mock_response.read = MagicMock(return_value=json.dumps({
            "choices": [{"message": {"content": "AI 分析结果"}}],
            "model": "deepseek-chat",
            "usage": {"total_tokens": 200},
        }).encode("utf-8"))
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("stock_researcher.ai_analysis_engine.urlopen", return_value=mock_response):
            result = engine.analyze("stock_analysis", {
                "code": "600519", "name": "贵州茅台", "market": "A股",
                "price": "1680", "change_pct": "+1.0",
                "high": "1690", "low": "1670", "volume": "1万", "amount": "10亿",
                "pe_ttm": "28", "pb": "9", "div_yield": "1.5",
                "roe": "32", "gross_margin": "91", "net_margin": "52",
                "revenue_yoy": "15", "profit_yoy": "18",
                "ma_status": "多头", "macd": "金叉", "rsi": "55", "trend": "偏强",
                "score": "70", "short_term_view": "看多", "medium_term_view": "中性",
                "bull_count": "3", "bear_count": "2", "neutral_count": "1",
            }, use_cache=False)
            self.assertTrue(result.success)
            self.assertFalse(result.is_fallback)
            self.assertEqual(result.tokens_used, 200)
            self.assertIn("AI 分析结果", result.content)
            # 应包含免责声明
            self.assertIn("免责声明", result.content)


class TestCache(unittest.TestCase):
    """测试缓存机制。"""

    def test_cache_hit_returns_same_result(self):
        from stock_researcher.ai_analysis_engine import (
            AIAnalysisEngine, LLMConfig
        )
        config = LLMConfig(provider="deepseek", api_key="sk-test")
        engine = AIAnalysisEngine(config)

        mock_response = MagicMock()
        mock_response.read = MagicMock(return_value=json.dumps({
            "choices": [{"message": {"content": "cached content"}}],
            "model": "test-model",
            "usage": {"total_tokens": 50},
        }).encode("utf-8"))
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        context = {"code": "600519", "name": "测试", "market": "A股",
                   "price": "100", "change_pct": "0", "high": "100",
                   "low": "100", "volume": "0", "amount": "0",
                   "pe_ttm": "0", "pb": "0", "div_yield": "0",
                   "roe": "0", "gross_margin": "0", "net_margin": "0",
                   "revenue_yoy": "0", "profit_yoy": "0",
                   "ma_status": "N/A", "macd": "N/A", "rsi": "N/A",
                   "trend": "N/A", "score": "0", "short_term_view": "N/A",
                   "medium_term_view": "N/A", "bull_count": "0",
                   "bear_count": "0", "neutral_count": "0"}

        with patch("stock_researcher.ai_analysis_engine.urlopen", return_value=mock_response) as m:
            r1 = engine.analyze("stock_analysis", context, use_cache=True)
            r2 = engine.analyze("stock_analysis", context, use_cache=True)
            # 缓存命中，只调用一次 HTTP
            self.assertEqual(m.call_count, 1)
            self.assertEqual(r1.content, r2.content)

    def test_clear_cache(self):
        from stock_researcher.ai_analysis_engine import (
            AIAnalysisEngine, LLMConfig
        )
        config = LLMConfig(provider="deepseek", api_key="")
        engine = AIAnalysisEngine(config)
        # 触发一次 fallback 路径填充缓存
        engine.analyze("market_regime", {"sh_close": "3000"}, use_cache=True)
        self.assertGreater(len(engine._cache), 0)
        engine.clear_cache()
        self.assertEqual(len(engine._cache), 0)


class TestUnknownTaskType(unittest.TestCase):
    """测试未知任务类型。"""

    def test_unknown_task_raises(self):
        """未知任务类型应返回失败（format_prompt 抛 ValueError）。"""
        from stock_researcher.ai_analysis_engine import AIAnalysisEngine, LLMConfig
        # 需要 api_key 才走 format_prompt 路径
        engine = AIAnalysisEngine(LLMConfig(api_key="sk-test"))
        result = engine.analyze("nonexistent_task", {}, use_cache=False)
        self.assertFalse(result.success)
        self.assertIn("提示词", result.error)


class TestSelfCheck(unittest.TestCase):
    """测试自检函数。"""

    def test_self_check(self):
        from stock_researcher.ai_analysis_engine import self_check
        result = self_check()
        # v11.0 起版本升到 11.0，模板数 7→11
        self.assertEqual(result["version"], "v11.0")
        self.assertEqual(result["template_count"], 11)
        self.assertIn("stock_analysis", result["prompt_templates"])
        self.assertIn("fund_analysis", result["prompt_templates"])
        # v11.0 新增模板
        self.assertIn("futures_analysis", result["prompt_templates"])
        self.assertIn("money_flow_analysis", result["prompt_templates"])


if __name__ == "__main__":
    unittest.main()
