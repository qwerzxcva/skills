#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ima_bridge.py — 记忆系统 ⇄ IMA 知识库 桥接（v3.8.0 候选能力）

设计动机
────────
本地记忆系统擅长「结构化、按轴精确召回」（scene/domain/subdomain/tag 硬过滤 +
本地向量余弦），但有两个天然短板：
① 语义泛化召回弱（本地词法/小模型对深度改写、跨词面语义有限）；
② 大库全量语义比对吃本地算力。
IMA 知识库是**云端 RAG**，语义召回强、零本地算力。把记忆「镜像」一份到 IMA，
等于给记忆系统加了一层「云端语义召回」，本地依旧零模型、零负担。

数据流（职责分离，绝不耦合 MCP）
──────────────────────────────
memory_ops → 本地权威存储（JSON + SQLite 索引 + 本地向量缓存）
│  ima_bridge.export_corpus(root)  ← 纯读取，导出为 IMA 可 ingest 的文档
▼
corpus.jsonl  （每条 = 一个记忆的 Markdown 文档 + 元数据 frontmatter）
│  agent 调用 IMA MCP（add_knowledge / import）推送到云端
▼
IMA 知识库   ← 语义召回层（recall --semantic 走这里）

为什么 Python 不直接调 IMA MCP？
MCP 工具由 agent 运行时注入，Python 脚本无法调用。因此桥接层只负责
「导出标准语料 + 说明工作流」，真正的推送/搜索由 agent 用 IMA MCP 完成。
这样既解耦，又保证离线可用（无 IMA 时记忆系统完全自洽）。

文档格式（IMA ingest 友好）
─────────────────────────
# <summary>
> id: <mid> · scene: <scene> · domain: <domain> · subdomain: <subdomain> · type: <type>
> importance: <x> · created: <date>

<body>

tags: a, b, c
---attrs---
key=value（若有结构化属性）

元数据同时写进 frontmatter（部分 IMA 支持）与正文首行（兜底，确保可检索/可回填）。

用法
────
python ima_bridge.py export --root <store根> [--out corpus.jsonl] [--active-only]
python ima_bridge.py one   --root <store根> --mid <id>     # 单条预览
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from memory_ops import _all_mems, _default_root
except Exception:  # 兜底：直接以脚本方式被调用时 memory_ops 已在同目录
    _all_mems = None
    # S7 修复：兜底也尊重 AI_MEMORY_STORE 环境变量 + 跨平台回退（与 memory_ops._default_root 一致），
    # 机器特定路径不写死：统一走 AI_MEMORY_STORE / ~/.keeper/store_root 回退链。
    def _default_root():
        _env = os.environ.get("AI_MEMORY_STORE")
        if _env:
            return _env
        _ov = _user_store_override()
        if _ov:
            return _ov
        if os.name == "nt":
            return os.path.join(os.path.expanduser("~"), "AI记忆")
        _h = os.path.expanduser("~")
        if os.name == "nt":
            return os.path.join(_h, "AI记忆")
        return os.path.join(_h, ".ai-memory")


ESC = "Ⓑ"  # 占位，避免与正文冲突（实际未用，保留扩展位）


def _user_store_override():
    """用户级显式指定：~/.keeper/store_root（一行路径）。不存在/为空 → None。"""
    try:
        p = os.path.join(os.path.expanduser("~"), ".keeper", "store_root")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8-sig") as f:
            v = (f.readline() or "").strip().strip('"').strip("'")
        return v or None
    except Exception:
        return None


def _safe(v, default=""):
    return v if v else default


def to_doc(mem):
    """把一个记忆 dict 渲染成 IMA 可 ingest 的 Markdown 文档（含元数据首行）。"""
    mid = _safe(mem.get("id"), "?")
    scene = _safe(mem.get("scene"), "general")
    domain = _safe(mem.get("domain"), "-")
    subdomain = _safe(mem.get("subdomain"), "-")
    mtype = _safe(mem.get("type") or mem.get("category"), "-")
    importance = mem.get("importance")
    importance = "%.2f" % float(importance) if isinstance(importance, (int, float)) else "-"
    created = _safe(mem.get("created"), "-")
    summary = _safe(mem.get("summary"), "(无摘要)")
    body = _safe(mem.get("body"), "")
    tags = ", ".join(mem.get("tags", []) or [])
    via = _safe(mem.get("scene_via"), "-")
    sc = mem.get("scene_confidence")
    sc = "%.2f" % float(sc) if isinstance(sc, (int, float)) else "-"

    lines = []
    lines.append("# %s" % summary)
    lines.append("")
    lines.append("> id: %s · scene: %s · domain: %s · subdomain: %s · type: %s" % (
        mid, scene, domain, subdomain, mtype))
    lines.append("> importance: %s · scene_confidence: %s · scene_via: %s · created: %s" % (
        importance, sc, via, created))
    lines.append("")
    if body:
        lines.append(body)
        lines.append("")
    if tags:
        lines.append("tags: %s" % tags)
    attrs = mem.get("attrs") or []
    if attrs:
        lines.append("")
        lines.append("---attrs---")
        for a in attrs:
            lines.append("%s=%s" % (a.get("key"), a.get("value")))
    lines.append("")
    text = "\n".join(lines)
    meta = {
        "id": mid, "scene": scene, "domain": domain, "subdomain": subdomain,
        "type": mtype, "importance": importance, "created": created,
        "scene_confidence": sc, "scene_via": via,
    }
    return {"id": mid, "markdown": text, "meta": meta}


def export_corpus(root, out_path=None, active_only=True):
    """导出全库（或仅 active）为 IMA 语料。返回 (docs, path)。"""
    if _all_mems is None:
        raise RuntimeError("memory_ops 不可导（同目录缺失？）")
    mems = _all_mems(root)
    docs = []
    for m in mems.values():
        if active_only and m.get("status") != "active":
            continue
        if not isinstance(m, dict) or not m.get("id"):
            continue
        docs.append(to_doc(m))
    docs.sort(key=lambda d: d["id"])
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            for d in docs:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return docs, out_path


def _main():
    ap = argparse.ArgumentParser(description="记忆 ⇄ IMA 知识库桥接（导出语料）")
    sub = ap.add_subparsers(dest="op")

    pe = sub.add_parser("export", help="导出全库为 IMA 可 ingest 语料")
    pe.add_argument("--root", default=None,
                    help="store 根目录（默认走 AI_MEMORY_STORE / ~/.keeper/store_root 回退链）")
    pe.add_argument("--out", default="ima_corpus.jsonl", help="输出 jsonl 路径")
    pe.add_argument("--all", action="store_true", help="导出全部（含 archived/superseded）")

    po = sub.add_parser("one", help="预览单条记忆的 IMA 文档")
    po.add_argument("--root", default=None)
    po.add_argument("--mid", required=True)

    args = ap.parse_args()
    root = args.root or _default_root()

    if args.op == "export":
        docs, path = export_corpus(root, args.out, active_only=not args.all)
        print("已导出 %d 条记忆 → %s" % (len(docs), path or "(未写文件)"))
        if not path:
            for d in docs[:3]:
                print("---- %s ----\n%s" % (d["id"], d["markdown"][:400]))
    elif args.op == "one":
        mems = _all_mems(root)
        m = mems.get(args.mid)
        if not m:
            print("未找到 %s" % args.mid)
            return
        print(to_doc(m)["markdown"])
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
