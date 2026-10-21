# -*- coding: utf-8 -*-
"""keeper_mcp_server.py —— 把 keeper 记忆系统暴露为 MCP 服务。

纯 stdlib 实现 JSON-RPC 2.0 over stdio（MCP 规范帧：Content-Length 头），
零外部依赖，任何 MCP 客户端（Claude Desktop / Cursor / 自研 agent）均可连。
暴露工具：deposit / recall / doctor / stats / export。

传输：默认 stdio（MCP 客户端拉起本进程，父子管道通信）。
协议方法：initialize / ping / tools/list / tools/call。

用法：
python scripts/keeper_mcp_server.py --root <store>
# 客户端侧（示例）：在 mcpServers 配置里指向本脚本即可。
"""
import os
import re
import sys
import json
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import memory_ops as mo  # noqa: E402


def _keeper_version():
    """版本号单一来源（O2）：从 SKILL.md frontmatter `version:` 读取，避免与文档漂移。"""
    try:
        sk = os.path.join(os.path.dirname(_HERE), "SKILL.md")
        with open(sk, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("version:"):
                    return s.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


VERSION = _keeper_version()

_TOOLS = [
    {
        "name": "deposit",
        "description": "写入一条记忆（自然语言经验）。复用 keeper 去重/分类全流程。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "记忆摘要（必填）"},
                "category": {"type": "string", "description": "分类（默认 imported）"},
                "tags": {"type": "string", "description": "逗号分隔标签，或数组"},
                "body": {"type": "string", "description": "正文"},
                "tier": {"type": "string", "description": "层级 working/curated/core"},
                "scope": {"type": "string", "description": "universal/project/ephemeral"},
                "about_axis": {"type": "string", "description": "user/self/relationship/world"},
                "domain": {"type": "string"},
                "subdomain": {"type": "string"},
                "mem_type": {"type": "string", "description": "BP/WF/PF/PREF/FACT/DOC"},
                "importance": {"type": "number"},
                "confidence": {"type": "number"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "recall",
        "description": "语义/词法召回记忆。返回匹配条目列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "top_n": {"type": "integer", "description": "返回条数（默认 10）"},
                "tag": {"type": "string"},
                "category": {"type": "string"},
                "ann": {"type": "boolean", "description": "是否走 ANN 加速（默认否）"},
            },
        },
    },
    {
        "name": "doctor",
        "description": "健康检查与修复（一致性/矛盾/孤儿文件）。fix=true 时执行修复。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fix": {"type": "boolean", "description": "是否执行修复（默认 false 仅报告）"},
                "context_budget": {"type": "integer"},
                "no_cache": {"type": "boolean",
                             "description": "跳过调度探测缓存直连探测——刚改过系统限制"
                                            "（解除程序黑名单 / 换机器 / 改 PATH）后想立刻"
                                            "看真实结果时用；默认复用 24h 内的旧结论"},
            },
        },
    },
    {
        "name": "stats",
        "description": "库规模与召回热/温/冷分布。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "export",
        "description": "导出整库为 JSONL 文本。大库可用 limit 截断条数，避免撑爆客户端缓冲。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fmt": {"type": "string", "description": "jsonl / md（默认 jsonl）"},
                "limit": {"type": "integer", "description": "最多返回条数（默认不截断；jsonl 按行安全截断）"},
            },
        },
    },
]


def _coerce_tags(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)


def _call_tool(root, name, arguments):
    try:
        if name == "deposit":
            if not arguments.get("summary"):
                return {"content": [{"type": "text", "text": json.dumps(
                    {"ok": False, "error": "missing_required_field",
                     "message": "summary 为必填字段"}, ensure_ascii=False)}],
                    "isError": True}
            mo.init_store(root)
            res = mo.deposit(
                root,
                category=arguments.get("category") or "imported",
                summary=arguments["summary"],
                tags=_coerce_tags(arguments.get("tags")),
                body=arguments.get("body") or "",
                tier=arguments.get("tier") or "working",
                scope=arguments.get("scope"),
                about_axis=arguments.get("about_axis"),
                domain=arguments.get("domain"),
                subdomain=arguments.get("subdomain"),
                mem_type=arguments.get("mem_type"),
                importance=arguments.get("importance"),
                confidence=arguments.get("confidence"),
                recorded_by="mcp",
            )
            return {"content": [{"type": "text",
                                 "text": json.dumps({"id": res.get("id") if isinstance(res, dict) else res},
                                                    ensure_ascii=False)}],
                    "isError": False}
        if name == "recall":
            res = mo.recall(root, query=arguments.get("query"),
                           tag=arguments.get("tag"),
                           category=arguments.get("category"),
                           ann=bool(arguments.get("ann", False)))
            res = (res or [])[:int(arguments.get("top_n", 10))]
            return {"content": [{"type": "text",
                                 "text": json.dumps({"count": len(res), "entries": res},
                                                    ensure_ascii=False)}],
                    "isError": False}
        if name == "doctor":
            d = mo.doctor(root, fix=bool(arguments.get("fix", False)),
                         context_budget=arguments.get("context_budget"),
                         no_cache=bool(arguments.get("no_cache", False)))
            return {"content": [{"type": "text", "text": json.dumps(d, ensure_ascii=False)}],
                    "isError": False}
        if name == "stats":
            s = mo.stats(root)
            return {"content": [{"type": "text", "text": json.dumps(s, ensure_ascii=False)}],
                    "isError": False}
        if name == "export":
            fmt = arguments.get("fmt", "jsonl")
            r = mo.export_memories(root, fmt=fmt)
            content = r.get("content") if isinstance(r, dict) else str(r)
            content = content or ""
            # 大库防护：limit 截断。
            # B3：md 按记忆块(## 标题)截断，避免切断一条记忆中间破坏格式；
            # jsonl 每行是独立 JSON 记录，按行安全截断。
            limit = arguments.get("limit")
            if limit and isinstance(content, str):
                try:
                    lim = int(limit)
                    if lim > 0:
                        if fmt == "md":
                            parts = re.split(r"(?m)^(## )", content)
                            blocks = []
                            for i in range(1, len(parts), 2):
                                blocks.append(parts[i] + parts[i + 1])
                            if len(blocks) > lim:
                                content = "".join(blocks[:lim])
                        else:
                            lines = [ln for ln in content.split("\n") if ln.strip()]
                            if len(lines) > lim:
                                content = "\n".join(lines[:lim])
                except (ValueError, TypeError):
                    pass
            return {"content": [{"type": "text", "text": content}],
                    "isError": False}
        return {"content": [{"type": "text", "text": "unknown tool: %s" % name}],
                "isError": True}
    except Exception as e:  # noqa: BLE001
        # O3/C5：结构化错误（含异常类型），便于客户端程序化判断，不再 cryptic。
        return {"content": [{"type": "text", "text": json.dumps(
            {"ok": False, "error": type(e).__name__, "message": str(e)},
            ensure_ascii=False)}], "isError": True}


def _dispatch(root, method, params):
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "keeper-mcp", "version": VERSION},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _TOOLS}
    if method == "tools/call":
        return _call_tool(root, params.get("name"), params.get("arguments", {}) or {})
    return None


def _read_message(buf_in):
    header = b""
    while b"\r\n\r\n" not in header:
        c = buf_in.read(1)
        if not c:
            return None
        header += c
    length = None
    for line in header.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except ValueError:
                pass
    if length is None:
        return None
    body = b""
    while len(body) < length:
        chunk = buf_in.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return None


def _write_message(buf_out, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    buf_out.write(b"Content-Length: %d\r\n\r\n" % len(data))
    buf_out.write(data)
    buf_out.flush()


def serve(root):
    buf_in = sys.stdin.buffer
    buf_out = sys.stdout.buffer
    while True:
        req = _read_message(buf_in)
        if req is None:
            break
        method = req.get("method")
        params = req.get("params") or {}
        mid = req.get("id")
        # 通知（无 id）不回复
        if mid is None:
            continue
        try:
            result = _dispatch(root, method, params)
            if result is None:
                _write_message(buf_out, {"jsonrpc": "2.0", "id": mid,
                                         "error": {"code": -32601,
                                                   "message": "method not found: %s" % method}})
            else:
                _write_message(buf_out, {"jsonrpc": "2.0", "id": mid, "result": result})
        except Exception as e:  # noqa: BLE001
            _write_message(buf_out, {"jsonrpc": "2.0", "id": mid,
                                     "error": {"code": -32603, "message": str(e)}})


def main(argv=None):
    ap = argparse.ArgumentParser(description="keeper MCP 服务（stdio）")
    ap.add_argument("--root", default=mo.DEFAULT_ROOT, help="记忆根目录")
    ap.add_argument("--version", action="store_true", help="打印版本并退出")
    args = ap.parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    serve(args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
