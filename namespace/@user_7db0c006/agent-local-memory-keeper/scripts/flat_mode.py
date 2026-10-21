# -*- coding: utf-8 -*-
"""
flat_mode.py — 轻量文件层（零依赖哲学）

给只想「记个坑」的零依赖用户：跳过 SQLite、向量、LLM，全部记忆落单个纯 Markdown
文件（~/.workbuddy/memory/keeper_flat.md），召回走纯文本 grep。与 SQLite 路径互斥——
一旦使用 --flat，本次操作完全不碰 SQLite。

条目格式（grep 友好，按 [FK-#####] 分块）：
[FK-00001] 2026-07-27 14:00 area=bugfix priority=high state=pending tags=bug,api
summary: 踩坑了：这个API会报错
body: 详细原因与规避

设计：纯加性可选能力；无 SQLite 时记忆系统完全自洽（这条路径本身就是自洽的）。
"""

import os
import re
import datetime

FLAT_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "memory")
FLAT_FILE = os.path.join(FLAT_DIR, "keeper_flat.md")
HEAD_RE = re.compile(
    r"^\[FK-(\d+)\]\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s+"
    r"area=(\w+)\s+priority=(\w+)\s+state=(\w+)\s+tags=(.*)$"
)
SPLIT_RE = re.compile(r"\n(?=\[FK-\d+\])")


def _ensure():
    os.makedirs(FLAT_DIR, exist_ok=True)
    if not os.path.exists(FLAT_FILE):
        with open(FLAT_FILE, "w", encoding="utf-8") as f:
            f.write("# keeper_flat.md — 轻量零依赖记忆（--flat 模式）\n\n")


def _next_id():
    if not os.path.exists(FLAT_FILE):
        return 1
    maxn = 0
    with open(FLAT_FILE, encoding="utf-8") as f:
        for line in f:
            m = HEAD_RE.match(line.strip())
            if m:
                maxn = max(maxn, int(m.group(1)))
    return maxn + 1


def flat_add(summary, tags="", body="", area="learning", priority="normal", state="pending"):
    _ensure()
    n = _next_id()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    block = ("\n[FK-%05d] %s area=%s priority=%s state=%s tags=%s\n"
             "summary: %s\nbody: %s\n"
             % (n, ts, area, priority, state, tags, summary, body))
    with open(FLAT_FILE, "a", encoding="utf-8") as f:
        f.write(block)
    return {"ok": True, "id": "FK-%05d" % n, "target": FLAT_FILE}


def _parse():
    if not os.path.exists(FLAT_FILE):
        return []
    with open(FLAT_FILE, encoding="utf-8") as f:
        text = f.read()
    items = []
    for p in SPLIT_RE.split(text):
        p = p.strip()
        if not p or not p.startswith("[FK-"):
            continue
        lines = p.split("\n")
        m = HEAD_RE.match(lines[0].strip())
        if not m:
            continue
        meta = {
            "id": "FK-%05d" % int(m.group(1)),
            "ts": m.group(2),
            "area": m.group(3),
            "priority": m.group(4),
            "state": m.group(5),
            "tags": m.group(6),
            "summary": "",
            "body": "",
        }
        for ln in lines[1:]:
            if ln.startswith("summary: "):
                meta["summary"] = ln[len("summary: "):]
            elif ln.startswith("body: "):
                meta["body"] = ln[len("body: "):]
        items.append(meta)
    return items


def flat_recall(query=""):
    items = _parse()
    if not query:
        return items
    q = query.lower()
    return [it for it in items
            if q in (it.get("summary", "") + " " + it.get("body", "") + " " + it.get("tags", "")).lower()]


def flat_list():
    return _parse()
