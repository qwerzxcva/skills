# -*- coding: utf-8 -*-
"""
v11.0 外部 MCP 桥接 (mcp_external_bridge.py)

通过 stdio 协议调用外部 MCP Server（如「金融六日」等），
把外部工具暴露为本地函数，与本技能数据流融合。

核心能力：
  1. 启动/管理外部 MCP 子进程（ExternalMCPSession）
  2. 工具发现（list_tools）
  3. 工具调用（call_tool，自动 JSON-RPC 协议）
  4. 批量发现本地数据源适配器中可桥接的工具

v11.0 默认行为：
  - 不主动启动任何外部 MCP（需用户显式调用 connect）
  - 所有 MCP 信息从环境变量获取（避免明文配置）
    * STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND（命令行）
    * STOCK_RESEARCHER_EXTERNAL_MCP_NAME（显示名，默认 "金融六日"）

设计原则：
  1. 零依赖核心（仅 stdlib + subprocess）
  2. 外部 MCP 不可用时整个模块静默降级（不影响主功能）
  3. 凭证全走环境变量
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 配置（环境变量优先）
# ============================================================================

DEFAULT_NAME = "金融六日"
ENV_COMMAND = "STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND"
ENV_NAME = "STOCK_RESEARCHER_EXTERNAL_MCP_NAME"
ENV_PREFIX = "STOCK_RESEARCHER_EXTERNAL_MCP_ENV_"   # 前缀：STOCK_RESEARCHER_EXTERNAL_MCP_ENV_FOO=bar → FOO=bar


def load_external_mcp_config() -> Dict[str, Any]:
    """从环境变量加载外部 MCP 配置（凭证零明文）。"""
    command = os.environ.get(ENV_COMMAND, "").strip()
    name = os.environ.get(ENV_NAME, DEFAULT_NAME)
    env_overrides: Dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith(ENV_PREFIX):
            inner = k[len(ENV_PREFIX):]
            env_overrides[inner] = v
    return {
        "command": command,
        "name": name,
        "env": env_overrides,
        "configured": bool(command),
    }


# ============================================================================
# 2. 外部 MCP 会话（subprocess + stdio JSON-RPC）
# ============================================================================

@dataclass
class ExternalMCPTool:
    """外部 MCP 工具描述。"""
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


class ExternalMCPSession:
    """外部 MCP 会话（通过 stdio + JSON-RPC 协议通信）。"""

    def __init__(self, command: str, env: Optional[Dict[str, str]] = None,
                 name: str = "external"):
        self.command = command
        self.env = env or {}
        self.name = name
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._tools: List[ExternalMCPTool] = []

    def connect(self, timeout: float = 10.0) -> bool:
        """启动 MCP 子进程。"""
        if self._process and self._process.poll() is None:
            return True
        try:
            full_env = {**os.environ, **self.env}
            self._process = subprocess.Popen(
                self.command.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                bufsize=0,
            )
            # 尝试 initialize + tools/list
            time.sleep(0.3)  # 让 MCP Server 启动
            return self._discover_tools(timeout=timeout)
        except Exception as e:
            logger.warning(f"外部 MCP [{self.name}] 启动失败: {e}")
            self._process = None
            return False

    def disconnect(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except Exception:
                pass
        self._process = None
        self._tools = []

    @property
    def available(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def tools(self) -> List[ExternalMCPTool]:
        return list(self._tools)

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None,
              timeout: float = 5.0) -> Dict[str, Any]:
        """发送 JSON-RPC 请求。"""
        if not self.available:
            return {"error": "外部 MCP 不可用"}

        req_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        try:
            with self._lock:
                line = json.dumps(payload, ensure_ascii=False) + "\n"
                self._process.stdin.write(line.encode("utf-8"))
                self._process.stdin.flush()
                # 读一行响应
                response_bytes = self._process.stdout.readline()
                if not response_bytes:
                    return {"error": "外部 MCP 关闭"}
                response = json.loads(response_bytes.decode("utf-8"))
                if "error" in response:
                    return {"error": response["error"]}
                return {"result": response.get("result", {})}
        except Exception as e:
            logger.warning(f"外部 MCP 通信失败: {e}")
            return {"error": str(e)}

    def _discover_tools(self, timeout: float = 5.0) -> bool:
        """发现外部 MCP 工具列表。"""
        if not self.available:
            return False
        resp = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "stock-researcher", "version": "11.0.0"},
        }, timeout=timeout)
        if "error" in resp:
            return False
        # 列出工具
        resp = self._send("tools/list", {}, timeout=timeout)
        if "error" in resp:
            return False
        tools_data = resp.get("result", {}).get("tools", [])
        self._tools = [
            ExternalMCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_data
            if isinstance(t, dict) and t.get("name")
        ]
        logger.info(f"外部 MCP [{self.name}] 发现 {len(self._tools)} 个工具")
        return True

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None,
                  timeout: float = 10.0) -> Dict[str, Any]:
        """调用外部 MCP 工具。"""
        resp = self._send("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        }, timeout=timeout)
        return resp


# ============================================================================
# 3. 桥接器（统一管理外部 MCP）
# ============================================================================

class ExternalMCPBridge:
    """外部 MCP 桥接器（单例模式）。"""

    def __init__(self):
        self._sessions: Dict[str, ExternalMCPSession] = {}
        self._lock = threading.Lock()
        self._config = load_external_mcp_config()

    @property
    def configured(self) -> bool:
        return self._config.get("configured", False)

    @property
    def default_name(self) -> str:
        return self._config.get("name", DEFAULT_NAME)

    def auto_connect(self) -> bool:
        """根据环境变量自动连接默认外部 MCP。"""
        cfg = load_external_mcp_config()
        if not cfg["command"]:
            return False
        return self.connect(cfg["name"], cfg["command"], cfg["env"])

    def connect(self, name: str, command: str,
                env: Optional[Dict[str, str]] = None) -> bool:
        """连接指定外部 MCP。"""
        with self._lock:
            session = ExternalMCPSession(command, env=env, name=name)
            if session.connect():
                self._sessions[name] = session
                return True
            return False

    def disconnect(self, name: Optional[str] = None):
        if name is None:
            for s in self._sessions.values():
                s.disconnect()
            self._sessions.clear()
        else:
            session = self._sessions.get(name)
            if session:
                session.disconnect()
                del self._sessions[name]

    def list_sessions(self) -> Dict[str, List[str]]:
        """列出所有会话及其工具。"""
        return {name: [t.name for t in s.tools] for name, s in self._sessions.items()}

    def call(self, session_name: str, tool_name: str,
             arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用指定会话的工具。"""
        session = self._sessions.get(session_name)
        if not session:
            return {"error": f"会话 [{session_name}] 不存在或未连接"}
        return session.call_tool(tool_name, arguments)

    def status(self) -> Dict[str, Any]:
        """桥接器状态。"""
        return {
            "configured": self.configured,
            "default_name": self.default_name,
            "active_sessions": list(self._sessions.keys()),
            "tools_per_session": self.list_sessions(),
        }


# ============================================================================
# 4. 全局单例 + 与数据层集成
# ============================================================================

_bridge: Optional[ExternalMCPBridge] = None
_bridge_lock = threading.Lock()


def get_bridge() -> ExternalMCPBridge:
    """获取全局桥接器（单例）。"""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = ExternalMCPBridge()
        return _bridge


def reset_bridge():
    """重置全局桥接器（用于测试）。"""
    global _bridge
    with _bridge_lock:
        if _bridge:
            _bridge.disconnect()
        _bridge = None


# ============================================================================
# 5. 自检
# ============================================================================

def self_check() -> Dict[str, Any]:
    """v11.0 外部 MCP 桥接器自检。"""
    bridge = get_bridge()
    cfg = load_external_mcp_config()
    return {
        "version": "v11.0",
        "ExternalMCPBridge": "OK",
        "configured": cfg.get("configured", False),
        "default_name": cfg.get("name", DEFAULT_NAME),
        "env_vars": {
            "command": ENV_COMMAND,
            "name": ENV_NAME,
            "env_prefix": ENV_PREFIX,
        },
        "active_sessions": list(bridge._sessions.keys()),
        "note": (
            "未配置环境变量 STOCK_RESEARCHER_EXTERNAL_MCP_COMMAND 时，"
            "外部 MCP 桥接器为空闲状态，不影响主功能。"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(self_check(), ensure_ascii=False, indent=2))