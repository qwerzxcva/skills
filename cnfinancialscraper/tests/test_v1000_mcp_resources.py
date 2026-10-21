# -*- coding: utf-8 -*-
"""
v10.0.0 测试套件 — MCP Resource + Prompt（mcp_resources_prompts）

覆盖：
1. 8 个 Resource Provider 函数（不依赖 FastMCP 即可调用）
2. 10 个 Prompt 模板（验证 title/description/template 完整）
3. register_resources_and_prompts 注册到 FastMCP
4. list_resources / list_prompts 元信息
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from scripts.mcp_resources_prompts import (  # noqa: E402
    RESOURCE_REGISTRY, PROMPT_REGISTRY,
    resource_media_sources, resource_institutions, resource_query_types,
    resource_report_templates, resource_cache_index,
    resource_data_source_health, resource_anti_block_status, resource_crawl_state,
    register_resources_and_prompts, list_resources, list_prompts,
)


# ============================================================================
# 1. Resource Provider 直接调用
# ============================================================================

class TestResourceProviders(unittest.TestCase):
    """8 个 Resource Provider 直接调用（不依赖 FastMCP）。"""

    def test_media_sources_returns_json(self):
        out = resource_media_sources()
        # 可能是 dict 或 list，序列化后必然是 JSON
        parsed = json.loads(out)
        self.assertIsInstance(parsed, (dict, list))

    def test_institutions_returns_summary(self):
        out = resource_institutions()
        parsed = json.loads(out)
        # 应该至少有 total 字段
        if isinstance(parsed, dict):
            self.assertIn("total", parsed)

    def test_query_types_counts(self):
        out = resource_query_types()
        parsed = json.loads(out)
        self.assertIn("v9_count", parsed)
        self.assertIn("v10_count", parsed)
        self.assertIn("total", parsed)
        self.assertGreater(parsed["total"], 30)
        # 验证至少有一些 v9 + v10 类型
        self.assertGreater(len(parsed["v9_query_types"]), 0)
        self.assertGreater(len(parsed["v10_query_types"]), 0)

    def test_report_templates_returns_list(self):
        out = resource_report_templates()
        parsed = json.loads(out)
        self.assertIn("templates", parsed)

    def test_cache_index_returns_stats(self):
        out = resource_cache_index()
        parsed = json.loads(out)
        # 至少有 stats 或 error 字段
        self.assertTrue("stats" in parsed or "error" in parsed)

    def test_data_source_health_returns_dict(self):
        out = resource_data_source_health()
        parsed = json.loads(out)
        self.assertIn("v9_sources", parsed)
        self.assertIn("v10_sources", parsed)
        self.assertIn("timestamp", parsed)

    def test_anti_block_status_returns_dict(self):
        out = resource_anti_block_status()
        parsed = json.loads(out)
        self.assertIn("components", parsed)

    def test_crawl_state_returns_dict(self):
        out = resource_crawl_state()
        parsed = json.loads(out)
        # 即便 dispatcher 不可用也应返回 dict
        self.assertIsInstance(parsed, dict)


# ============================================================================
# 2. RESOURCE_REGISTRY 完整性
# ============================================================================

class TestResourceRegistry(unittest.TestCase):
    """RESOURCE_REGISTRY 应包含 8 个资源。"""

    def test_count(self):
        self.assertEqual(len(RESOURCE_REGISTRY), 8)

    def test_required_uris(self):
        expected_uris = {
            "cnfs://media-sources",
            "cnfs://institutions",
            "cnfs://query-types",
            "cnfs://report-templates",
            "cnfs://cache-index",
            "cnfs://data-source-health",
            "cnfs://anti-block-status",
            "cnfs://crawl-state",
        }
        actual = set(RESOURCE_REGISTRY.keys())
        self.assertEqual(actual, expected_uris)

    def test_each_resource_has_required_fields(self):
        for uri, meta in RESOURCE_REGISTRY.items():
            self.assertIn("name", meta, f"{uri} missing name")
            self.assertIn("title", meta, f"{uri} missing title")
            self.assertIn("description", meta, f"{uri} missing description")
            self.assertIn("provider", meta, f"{uri} missing provider")
            self.assertIn("mime_type", meta, f"{uri} missing mime_type")

    def test_provider_callable(self):
        for uri, meta in RESOURCE_REGISTRY.items():
            self.assertTrue(callable(meta["provider"]),
                            f"{uri} provider not callable")


# ============================================================================
# 3. PROMPT_REGISTRY 完整性
# ============================================================================

class TestPromptRegistry(unittest.TestCase):
    """PROMPT_REGISTRY 应包含 10 个模板。"""

    def test_count(self):
        self.assertEqual(len(PROMPT_REGISTRY), 10)

    def test_required_prompts(self):
        expected = {
            "analyze_institution_sentiment_30d",
            "export_quarterly_report",
            "query_stock_full_view",
            "crawl_url_list",
            "interpret_announcement",
            "search_policy_documents",
            "compare_two_funds",
            "generate_research_report",
            "monitor_page_changes",
            "test_anti_block_effect",
        }
        self.assertEqual(set(PROMPT_REGISTRY.keys()), expected)

    def test_each_prompt_has_required_fields(self):
        for name, meta in PROMPT_REGISTRY.items():
            self.assertIn("title", meta, f"{name} missing title")
            self.assertIn("description", meta, f"{name} missing description")
            self.assertIn("template", meta, f"{name} missing template")
            self.assertGreater(len(meta["template"]), 20,
                                f"{name} template too short")

    def test_templates_have_placeholders(self):
        """模板应包含 {placeholder} 用于 format() 调用。"""
        for name, meta in PROMPT_REGISTRY.items():
            self.assertIn("{", meta["template"],
                          f"{name} template missing placeholders")


# ============================================================================
# 4. 注册到 FastMCP
# ============================================================================

class TestRegisterResourcesAndPrompts(unittest.TestCase):
    """register_resources_and_prompts(server) 实际注册。"""

    def test_register_success(self):
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            self.skipTest("mcp not available")
        server = FastMCP("test-cnfs-resources")
        result = register_resources_and_prompts(server)
        self.assertEqual(result["resources"], 8)
        self.assertEqual(result["prompts"], 10)
        self.assertEqual(result["failed"], [])


# ============================================================================
# 5. list_resources / list_prompts
# ============================================================================

class TestListMetadata(unittest.TestCase):
    """元信息列表函数。"""

    def test_list_resources(self):
        result = list_resources()
        self.assertEqual(len(result), 8)
        for item in result:
            self.assertIn("uri", item)
            self.assertIn("name", item)
            self.assertIn("title", item)
            self.assertIn("description", item)

    def test_list_prompts(self):
        result = list_prompts()
        self.assertEqual(len(result), 10)
        for item in result:
            self.assertIn("name", item)
            self.assertIn("title", item)
            self.assertIn("description", item)


if __name__ == "__main__":
    unittest.main()