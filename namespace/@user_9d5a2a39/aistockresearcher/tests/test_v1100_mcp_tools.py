# -*- coding: utf-8 -*-
"""
v11.0 MCP 工具测试 (test_v1100_mcp_tools.py)

覆盖 v11.0 新增的 6 个 MCP 工具：
  - ai_analyze_futures
  - ai_analyze_money_flow
  - ai_analyze_index_forecast
  - ai_analyze_portfolio
  - get_futures_quote
  - predict_multi_horizon

以及 v11.0 更新的 ai_analyze_market_regime / ai_analyze_macro_outlook /
ai_analyze_risk_report / ai_analyze_sector_rotation 工具签名。

由于 conftest 屏蔽 mcp SDK，本测试通过源码解析 + 子模块独立加载验证，
避免触发 mcp SDK 导入。
"""
import sys
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


MCP_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp_server.py"


def _read_mcp_server_source() -> str:
    return MCP_SERVER_PATH.read_text(encoding="utf-8")


def _extract_tool_functions(content: str) -> list:
    """从源码提取 @server.tool() 装饰的 async 函数名。"""
    matches = re.findall(r'@server\.tool\(\)\s*\nasync def (\w+)\(', content)
    return matches


def _extract_function_signature(content: str, func_name: str) -> str:
    """从源码中提取函数签名（含所有参数声明）。"""
    pattern = rf'async def {func_name}\(([^)]+)\)'
    m = re.search(pattern, content, re.DOTALL)
    return m.group(1) if m else ""


class TestMCPServerToolRegistry(unittest.TestCase):
    """MCP Server 工具注册测试。"""

    def test_total_tools_is_20(self):
        """MCP Server 应注册 20 个工具（v10.0 14 + v11.0 6）。"""
        content = _read_mcp_server_source()
        tools = _extract_tool_functions(content)
        self.assertEqual(len(tools), 20, f"应注册 20 工具，实际 {len(tools)}: {tools}")

    def test_v11_new_tools_registered(self):
        """v11.0 新增 6 工具应在文件中。"""
        content = _read_mcp_server_source()
        for tool_name in ("ai_analyze_futures", "ai_analyze_money_flow",
                          "ai_analyze_index_forecast", "ai_analyze_portfolio",
                          "get_futures_quote", "predict_multi_horizon"):
            self.assertIn(f"async def {tool_name}", content,
                          f"{tool_name} 未注册")

    def test_v10_tools_still_present(self):
        """v10.0 原 14 个工具应保留。"""
        content = _read_mcp_server_source()
        for tool_name in ("get_stock_quote", "get_fund_nav", "get_macro_data",
                          "list_data_sources",
                          "ai_analyze_stock", "ai_analyze_fund",
                          "ai_analyze_market_regime",
                          "ai_analyze_master_council", "ai_analyze_macro_outlook",
                          "ai_analyze_risk_report", "ai_analyze_sector_rotation",
                          "run_master_council", "quick_predict",
                          "get_skill_status"):
            self.assertIn(f"async def {tool_name}", content,
                          f"v10.0 工具 {tool_name} 缺失")


class TestMCPServerVersion(unittest.TestCase):
    """MCP Server 版本号测试。"""

    def test_version_is_v1100(self):
        content = _read_mcp_server_source()
        self.assertIn('VERSION = "11.0.0"', content)


class TestMCPUpdatedSignatures(unittest.TestCase):
    """v11.0 更新的工具签名测试（基于源码解析）。"""

    def test_market_regime_signature_has_new_fields(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_market_regime"
        )
        for new_param in ("star50_close", "ad_ratio", "vol_skew",
                          "pcr", "etf_flow", "ah_premium", "hsi_chg",
                          "usdcny_change", "regime_label"):
            self.assertIn(new_param, sig, f"market_regime 缺 {new_param}")

    def test_macro_outlook_signature_has_new_fields(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_macro_outlook"
        )
        for new_param in ("industrial_yoy", "real_estate_yoy",
                          "retail_yoy", "export_yoy", "core_cpi_yoy",
                          "new_deposits", "dr007", "cn_us_short_spread",
                          "fed_funds"):
            self.assertIn(new_param, sig, f"macro_outlook 缺 {new_param}")

    def test_risk_report_signature_has_new_fields(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_risk_report"
        )
        for new_param in ("last_rebalance_days", "style_drift",
                          "inflation_shock", "avg_daily_turnover",
                          "days_to_liquidate", "limit_up_holding_pct",
                          "suspended_holding",
                          "highest_corr_pair", "highest_corr_value",
                          "lowest_corr_pair", "lowest_corr_value"):
            self.assertIn(new_param, sig, f"risk_report 缺 {new_param}")

    def test_sector_rotation_signature_has_new_fields(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_sector_rotation"
        )
        for new_param in ("smart_money_inflow_top3",
                          "smart_money_outflow_top3",
                          "etf_inflow_top3", "etf_outflow_top3"):
            self.assertIn(new_param, sig, f"sector_rotation 缺 {new_param}")

    def test_futures_signature_complete(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_futures"
        )
        for p in ("contract", "symbol", "exchange", "delivery_month",
                  "price", "open_interest", "volume", "basis",
                  "roll_yield", "top5_long", "top5_short",
                  "forecast_5d", "forecast_20d"):
            self.assertIn(p, sig, f"futures 缺 {p}")

    def test_money_flow_signature_complete(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_money_flow"
        )
        for p in ("code", "name", "main_net_inflow", "north_1d",
                  "north_5d", "margin_balance", "smart_money_score",
                  "limit_up_count"):
            self.assertIn(p, sig, f"money_flow 缺 {p}")

    def test_index_forecast_signature_complete(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_index_forecast"
        )
        for p in ("code", "name", "price", "pe_ttm",
                  "rps_pct", "forecast_1m_direction",
                  "forecast_3m_direction", "forecast_6m_direction"):
            self.assertIn(p, sig, f"index_forecast 缺 {p}")

    def test_portfolio_signature_complete(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "ai_analyze_portfolio"
        )
        for p in ("total_value", "holdings_count", "annual_return",
                  "allocation_contribution", "industry_hhi",
                  "size_exposure", "value_growth_exposure"):
            self.assertIn(p, sig, f"portfolio 缺 {p}")

    def test_predict_multi_horizon_signature(self):
        sig = _extract_function_signature(
            _read_mcp_server_source(), "predict_multi_horizon"
        )
        for p in ("code", "prices", "regime", "horizons"):
            self.assertIn(p, sig, f"predict_multi_horizon 缺 {p}")


class TestMCPServerModuleImports(unittest.TestCase):
    """验证模块结构（不实际加载 mcp_server.py 全文以避免 mcp SDK 依赖）。"""

    def test_get_skill_status_defined(self):
        content = _read_mcp_server_source()
        self.assertIn("async def get_skill_status", content)

    def test_get_skill_status_includes_v11_changelog(self):
        content = _read_mcp_server_source()
        # 找 get_skill_status 函数体
        idx = content.find("async def get_skill_status")
        self.assertGreater(idx, 0)
        # 往后取 3000 字符
        body = content[idx:idx + 3000]
        self.assertIn("v11_changelog", body)
        self.assertIn("新增 4 数据源适配器", body)
        self.assertIn("AI 模板扩充", body)
        self.assertIn("MCP 工具: 14 → 20", body)

    def test_get_skill_status_lists_20_tools(self):
        content = _read_mcp_server_source()
        idx = content.find("async def get_skill_status")
        body = content[idx:idx + 3000]
        # 应列出 20 个工具名
        for tool in ("get_stock_quote", "get_futures_quote",
                     "ai_analyze_stock", "ai_analyze_futures",
                     "ai_analyze_money_flow", "ai_analyze_index_forecast",
                     "ai_analyze_portfolio",
                     "predict_multi_horizon", "get_skill_status"):
            self.assertIn(f'"{tool}"', body, f"get_skill_status 未列出 {tool}")


class TestPredictionV11Core(unittest.TestCase):
    """predict_multi_horizon MCP 工具底层测试。"""

    def test_predict_multi_horizon_core(self):
        """通过核心函数验证 predict_multi_horizon 返回结构。"""
        from stock_researcher.prediction_v1100 import (
            predict_multi_horizon, MultiHorizonResult, HorizonPrediction
        )

        prices = [100 + i * 0.3 for i in range(60)]
        result = predict_multi_horizon("600519", prices=prices)
        self.assertIsInstance(result, MultiHorizonResult)
        d = result.to_dict()
        # 验证可序列化
        import json
        json.dumps(d, ensure_ascii=False)
        # 验证 horizon 结构
        for h, hp in result.horizons.items():
            self.assertIsInstance(hp, HorizonPrediction)
            self.assertEqual(hp.horizon, h)


if __name__ == "__main__":
    unittest.main()