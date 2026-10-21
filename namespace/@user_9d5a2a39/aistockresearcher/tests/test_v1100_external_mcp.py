# -*- coding: utf-8 -*-
"""
v11.0 外部 MCP 桥接测试 (test_v1100_external_mcp.py)

覆盖 mcp_external_bridge.py：
  - load_external_mcp_config 环境变量加载
  - ExternalMCPSession subprocess 生命周期
  - ExternalMCPBridge 单例模式
  - self_check 输出
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLoadExternalMCPConfig(unittest.TestCase):
    """环境变量配置加载测试。"""

    def setUp(self):
        # 清理环境变量
        for k in list(os.environ.keys()):
            if k.startswith("STOCK_RESEARCHER_EXTERNAL_MCP_"):
                del os.environ[k]

    def test_no_env_returns_defaults(self):
        from stock_researcher.mcp_external_bridge import (
            load_external_mcp_config, DEFAULT_NAME
        )
        cfg = load_external_mcp_config()
        self.assertEqual(cfg["command"], "")
        self.assertEqual(cfg["name"], DEFAULT_NAME)
        self.assertFalse(cfg["configured"])

    def test_command_env_sets_command(self):
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND"] = "python test.py"
        from stock_researcher.mcp_external_bridge import load_external_mcp_config
        cfg = load_external_mcp_config()
        self.assertEqual(cfg["command"], "python test.py")
        self.assertTrue(cfg["configured"])

    def test_name_env_overrides_default(self):
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND"] = "x"
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_NAME"] = "我的金融数据"
        from stock_researcher.mcp_external_bridge import load_external_mcp_config
        cfg = load_external_mcp_config()
        self.assertEqual(cfg["name"], "我的金融数据")

    def test_env_prefix_loads_env_overrides(self):
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND"] = "x"
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_ENV_TOKEN"] = "abc"
        os.environ["STOCK_RESEARCHER_EXTERNAL_MCP_ENV_BASE_URL"] = "https://api.test.com"
        from stock_researcher.mcp_external_bridge import load_external_mcp_config
        cfg = load_external_mcp_config()
        self.assertEqual(cfg["env"]["TOKEN"], "abc")
        self.assertEqual(cfg["env"]["BASE_URL"], "https://api.test.com")


class TestExternalMCPTool(unittest.TestCase):
    """ExternalMCPTool 数据类测试。"""

    def test_creation(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPTool
        tool = ExternalMCPTool(name="test_tool", description="Test")
        self.assertEqual(tool.name, "test_tool")
        self.assertEqual(tool.description, "Test")
        self.assertEqual(tool.input_schema, {})

    def test_with_input_schema(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPTool
        schema = {"type": "object", "properties": {"code": {"type": "string"}}}
        tool = ExternalMCPTool(name="t", input_schema=schema)
        self.assertEqual(tool.input_schema["type"], "object")


class TestExternalMCPBridge(unittest.TestCase):
    """ExternalMCPBridge 桥接器测试。"""

    def setUp(self):
        from stock_researcher.mcp_external_bridge import reset_bridge
        reset_bridge()

    def test_default_state(self):
        from stock_researcher.mcp_external_bridge import (
            ExternalMCPBridge, get_bridge
        )
        bridge = get_bridge()
        self.assertIsInstance(bridge, ExternalMCPBridge)
        self.assertFalse(bridge.configured)

    def test_status_returns_dict(self):
        from stock_researcher.mcp_external_bridge import get_bridge
        bridge = get_bridge()
        status = bridge.status()
        self.assertIn("configured", status)
        self.assertIn("default_name", status)
        self.assertIn("active_sessions", status)
        self.assertEqual(status["active_sessions"], [])

    def test_call_unknown_session_returns_error(self):
        from stock_researcher.mcp_external_bridge import get_bridge
        bridge = get_bridge()
        result = bridge.call("nonexistent_session", "any_tool")
        self.assertIn("error", result)
        self.assertIn("不存在", result["error"])

    def test_connect_returns_false_for_invalid_command(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPBridge
        bridge = ExternalMCPBridge()
        # 不存在的命令应返回 False
        result = bridge.connect("test", "this_command_does_not_exist_xyz123")
        self.assertFalse(result)
        self.assertNotIn("test", bridge._sessions)

    def test_disconnect_all(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPBridge
        bridge = ExternalMCPBridge()
        bridge.disconnect()
        self.assertEqual(len(bridge._sessions), 0)


class TestExternalMCPSession(unittest.TestCase):
    """ExternalMCPSession 子进程管理测试。"""

    def test_initial_state_not_available(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPSession
        session = ExternalMCPSession("echo test")
        self.assertFalse(session.available)
        self.assertEqual(session.tools, [])

    def test_disconnect_when_not_connected(self):
        from stock_researcher.mcp_external_bridge import ExternalMCPSession
        session = ExternalMCPSession("echo test")
        # 未连接时 disconnect 不应抛错
        session.disconnect()
        self.assertIsNone(session._process)


class TestSelfCheck(unittest.TestCase):
    """自检输出测试。"""

    def test_self_check_structure(self):
        from stock_researcher.mcp_external_bridge import self_check
        result = self_check()
        self.assertEqual(result["version"], "v11.0")
        self.assertEqual(result["ExternalMCPBridge"], "OK")
        self.assertIn("env_vars", result)
        self.assertIn("command", result["env_vars"])
        self.assertIn("name", result["env_vars"])
        self.assertIn("env_prefix", result["env_vars"])
        self.assertIn("active_sessions", result)
        self.assertIn("note", result)


class TestModuleExports(unittest.TestCase):
    """模块导出测试。"""

    def test_top_level_exports(self):
        from stock_researcher import mcp_external_bridge as mod
        for name in ("get_bridge", "ExternalMCPBridge", "ExternalMCPSession",
                     "load_external_mcp_config", "ExternalMCPTool"):
            self.assertTrue(hasattr(mod, name),
                            f"{name} not exported from mcp_external_bridge")

    def test_package_level_reexport(self):
        """通过顶层 __getattr__ 应能访问。"""
        from stock_researcher import get_bridge, ExternalMCPBridge
        self.assertTrue(callable(get_bridge))
        self.assertTrue(callable(ExternalMCPBridge))


if __name__ == "__main__":
    unittest.main()