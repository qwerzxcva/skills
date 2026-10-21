# -*- coding: utf-8 -*-
"""
v11.0 AI 模板测试 (test_v1100_ai_templates.py)

覆盖：
  - 4 个 v11.0 新增模板（futures_analysis / money_flow_analysis / index_forecast / portfolio_diagnosis）
  - 现有 7 模板增强字段的兼容性
  - PROMPT_TEMPLATES 包含全部 11 类
  - AIAnalysisEngine.analyze 对新模板的调用与降级
  - 模板版本号与 v11.0 标识
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestV11PromptTemplates(unittest.TestCase):
    """v11.0 提示词模板测试。"""

    def test_template_count_is_11(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        self.assertEqual(len(PROMPT_TEMPLATES), 11)

    def test_v11_new_templates_exist(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        for t in ("futures_analysis", "money_flow_analysis",
                  "index_forecast", "portfolio_diagnosis"):
            self.assertIn(t, PROMPT_TEMPLATES)
            # 模板应非空
            self.assertGreater(len(PROMPT_TEMPLATES[t]), 100)

    def test_v10_templates_still_exist(self):
        """v10.0 原有 7 个模板应保留。"""
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        for t in ("stock_analysis", "fund_analysis", "market_regime",
                  "master_council", "macro_outlook", "risk_report",
                  "sector_rotation"):
            self.assertIn(t, PROMPT_TEMPLATES)

    def test_futures_template_includes_basics(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["futures_analysis"]
        for key in ("{contract}", "{symbol}", "{exchange}",
                    "{price}", "{change_pct}",
                    "{open_interest}", "{volume}",
                    "{basis}", "{roll_yield}",
                    "{forecast_5d}", "{forecast_20d}"):
            self.assertIn(key, tpl)

    def test_money_flow_template_includes_north_bound(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["money_flow_analysis"]
        for key in ("{code}", "{name}",
                    "{main_net_inflow}", "{north_1d}", "{north_5d}",
                    "{margin_balance}", "{smart_money_score}",
                    "{limit_up_count}"):
            self.assertIn(key, tpl)

    def test_index_forecast_template_includes_multi_horizon(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["index_forecast"]
        for key in ("{code}", "{pe_ttm}", "{pe_pct_10y}",
                    "{rps_pct}", "{forecast_1m_direction}",
                    "{forecast_3m_direction}", "{forecast_6m_direction}"):
            self.assertIn(key, tpl)

    def test_portfolio_template_includes_attribution(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["portfolio_diagnosis"]
        for key in ("{total_value}", "{alpha}",
                    "{allocation_contribution}", "{selection_contribution}",
                    "{style_drift}", "{industry_hhi}"):
            self.assertIn(key, tpl)


class TestV11TemplateEnhancements(unittest.TestCase):
    """v11.0 现有模板增强字段测试。"""

    def test_market_regime_v11_fields(self):
        """market_regime 应包含 v11.0 新增字段。"""
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["market_regime"]
        for key in ("{star50_close}", "{ad_ratio}",
                    "{vol_skew}", "{pcr}", "{etf_flow}",
                    "{ah_premium}", "{hsi_chg}", "{regime_label}"):
            self.assertIn(key, tpl)

    def test_macro_outlook_v11_fields(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["macro_outlook"]
        for key in ("{industrial_yoy}", "{real_estate_yoy}",
                    "{retail_yoy}", "{export_yoy}",
                    "{core_cpi_yoy}", "{dr007}",
                    "{fed_funds}"):
            self.assertIn(key, tpl)

    def test_risk_report_v11_fields(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["risk_report"]
        for key in ("{last_rebalance_days}", "{style_drift}",
                    "{inflation_shock}",
                    "{avg_daily_turnover}", "{days_to_liquidate}",
                    "{limit_up_holding_pct}",
                    "{highest_corr_pair}"):
            self.assertIn(key, tpl)

    def test_sector_rotation_v11_fields(self):
        from stock_researcher.ai_analysis_engine import PROMPT_TEMPLATES
        tpl = PROMPT_TEMPLATES["sector_rotation"]
        for key in ("{smart_money_inflow_top3}",
                    "{smart_money_outflow_top3}",
                    "{etf_inflow_top3}",
                    "{etf_outflow_top3}"):
            self.assertIn(key, tpl)


class TestAIAnalysisEngineV11(unittest.TestCase):
    """AIAnalysisEngine v11.0 行为测试。"""

    def test_engine_status(self):
        from stock_researcher.ai_analysis_engine import get_engine
        engine = get_engine()
        status = engine.status()
        self.assertIn("provider", status)
        self.assertIn("model", status)

    def test_analyze_futures_uses_fallback(self):
        """未配置 API Key 时应使用模板降级。"""
        from stock_researcher.ai_analysis_engine import get_engine, LLMClient
        engine = get_engine()
        engine.clear_cache()
        context = {
            "contract": "AU2502", "symbol": "AU", "exchange": "SHFE",
            "delivery_month": "2025-02", "price": "500", "change": "5",
            "change_pct": "1.0", "open": "495", "high": "510", "low": "490",
            "prev_settlement": "495", "open_interest": "100000",
            "volume": "50000", "oi_change": "1000", "turnover": "100",
            "spot_price": "495", "basis": "5", "basis_pct": "1.0",
            "spread_near_far": "10", "roll_yield": "3.5",
            "top5_long": "前5名", "top5_short": "前5名",
            "oi_concentration": "60", "long_short_ratio": "1.2",
            "inventory": "100000", "inventory_chg": "-1.0",
            "spot_premium": "0.5", "atr": "8", "vol_20d": "20",
            "vol_60d": "18", "forecast_5d": "[495, 505]", "forecast_20d": "[490, 515]",
        }
        with patch.object(LLMClient, "chat", return_value={
            "success": False, "content": "", "error": "mock failure"
        }):
            result = engine.analyze("futures_analysis", context)
        self.assertTrue(result.is_fallback)
        self.assertIn("FUTURES_ANALYSIS", result.content)

    def test_analyze_money_flow_uses_fallback(self):
        from stock_researcher.ai_analysis_engine import get_engine, LLMClient
        engine = get_engine()
        engine.clear_cache()
        context = {
            "code": "600519", "name": "茅台",
            "main_net_inflow": "5.0", "super_large_net": "3.0",
            "large_net": "2.0", "medium_net": "-1.0",
            "small_net": "-4.0", "main_pct": "60",
            "north_1d": "1.0", "north_5d": "3.0", "north_20d": "8.0",
            "north_holding_pct": "5.5",
            "margin_balance": "2000", "margin_1d": "10", "margin_5d": "50",
            "short_balance": "100", "margin_buy_pct": "8.5",
            "etf_name": "酒ETF", "etf_flow_1d": "0.5", "etf_flow_5d": "2.0",
            "etf_premium": "0.1",
            "smart_money_score": "75", "abnormal_orders": "5",
            "smart_money_direction": "买入",
            "limit_up_count": "1", "limit_down_count": "0",
            "abnormal_amplitude_count": "2", "abnormal_volume_count": "1",
        }
        with patch.object(LLMClient, "chat", return_value={
            "success": False, "content": "", "error": "mock failure"
        }):
            result = engine.analyze("money_flow_analysis", context)
        self.assertTrue(result.is_fallback)
        self.assertIn("MONEY_FLOW_ANALYSIS", result.content)

    def test_analyze_index_forecast_uses_fallback(self):
        from stock_researcher.ai_analysis_engine import get_engine, LLMClient
        engine = get_engine()
        engine.clear_cache()
        context = {
            "code": "sh000300", "name": "沪深300",
            "price": "4500", "change_pct": "0.5",
            "pe_ttm": "12", "pe_pct_10y": "30", "pe_pct_5y": "35",
            "pb_pct_10y": "20", "div_yield": "2.0",
            "ma20": "4450", "ma60": "4400", "ma120": "4300",
            "ma_position": "上", "rsi": "55", "macd": "金叉",
            "rs_20d_vs_hs300": "0", "rs_60d_vs_hs300": "1.5", "rps_pct": "60",
            "adx": "25", "trend_score": "65", "momentum_score": "70",
            "tsf_yoy": "9", "bond_10y": "2.8",
            "industrial_yoy": "5", "dxy": "103",
            "forecast_1m_direction": "看涨", "forecast_1m_prob": "60",
            "forecast_3m_direction": "看涨", "forecast_3m_prob": "65",
            "forecast_6m_direction": "中性", "forecast_6m_prob": "55",
        }
        with patch.object(LLMClient, "chat", return_value={
            "success": False, "content": "", "error": "mock failure"
        }):
            result = engine.analyze("index_forecast", context)
        self.assertTrue(result.is_fallback)
        self.assertIn("INDEX_FORECAST", result.content)

    def test_analyze_portfolio_uses_fallback(self):
        from stock_researcher.ai_analysis_engine import get_engine, LLMClient
        engine = get_engine()
        engine.clear_cache()
        context = {
            "total_value": "1000", "holdings_count": "20",
            "cash_pct": "10", "annual_return": "12",
            "benchmark_return": "8", "alpha": "4",
            "allocation_contribution": "2.5", "selection_contribution": "1.5",
            "interaction_contribution": "0",
            "holdings_detail": "贵州茅台 5%, 宁德时代 4%...",
            "industry_hhi": "0.05", "max_weight_pct": "8",
            "top3_pct": "20",
            "size_exposure": "0.7", "value_growth_exposure": "0.5",
            "quality_score": "7", "momentum_score": "6",
            "last_rebalance_days": "30", "target_drift": "3",
            "suggested_turnover": "5", "rebalance_method": "阈值",
            "current_dd": "-3", "max_dd_1y": "-15",
            "dd_recovery_days": "60",
        }
        with patch.object(LLMClient, "chat", return_value={
            "success": False, "content": "", "error": "mock failure"
        }):
            result = engine.analyze("portfolio_diagnosis", context)
        self.assertTrue(result.is_fallback)
        self.assertIn("PORTFOLIO_DIAGNOSIS", result.content)

    def test_analyze_unknown_template_raises(self):
        from stock_researcher.ai_analysis_engine import get_engine
        engine = get_engine()
        with self.assertRaises(ValueError):
            engine._format_prompt("nonexistent_template", {})

    def test_cache_reuse(self):
        """同一上下文应返回缓存结果。"""
        from stock_researcher.ai_analysis_engine import get_engine, LLMClient
        engine = get_engine()
        engine.clear_cache()
        context = {
            "code": "600519", "name": "茅台", "market": "A股",
            "price": "1880", "change_pct": "1.0",
            "high": "1890", "low": "1870",
            "volume": "100000", "amount": "188000000",
            "pe_ttm": "28", "pb": "10", "div_yield": "1.0",
            "roe": "32", "gross_margin": "90", "net_margin": "50",
            "revenue_yoy": "15", "profit_yoy": "20",
            "ma_status": "多头排列", "macd": "金叉", "rsi": "60", "trend": "上行",
            "score": "75", "short_term_view": "看涨", "medium_term_view": "看涨",
            "bull_count": "4", "bear_count": "1", "neutral_count": "1",
        }
        with patch.object(LLMClient, "chat", return_value={
            "success": True, "content": "测试响应", "model": "mock",
            "usage": {"total_tokens": 10},
        }):
            r1 = engine.analyze("stock_analysis", context)
            r2 = engine.analyze("stock_analysis", context)
        # 两次应返回同一对象（缓存）
        self.assertIs(r1, r2)


class TestV11SelfCheck(unittest.TestCase):
    """v11.0 自检输出测试。"""

    def test_self_check_includes_v11_info(self):
        from stock_researcher.ai_analysis_engine import self_check
        result = self_check()
        self.assertEqual(result["version"], "v11.0")
        self.assertIn("v11_new_templates", result)
        self.assertEqual(len(result["v11_new_templates"]), 4)
        self.assertEqual(result["template_count"], 11)


if __name__ == "__main__":
    unittest.main()