#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_v30.py — 数据模型迁移独立运行器（Phase 1）。

为既有记忆库补 type/settled/probe_until/thermal 字段（幂等、可重复跑，
不改记忆原文、不改 category）。建议在升级到 v3.0 后对真实库跑一次。

用法：
python scripts/migrate_v30.py <root>
python scripts/migrate_v30.py            # 用环境变量 AI_MEMORY_STORE
AI_MEMORY_STORE=<你的记忆库路径> python scripts/migrate_v30.py
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory_ops as M


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AI_MEMORY_STORE")
    if not root:
        print(json.dumps({"ok": False, "error": "no_root",
                          "hint": "用法: python migrate_v30.py <root> 或设 AI_MEMORY_STORE"},
                         ensure_ascii=False))
        sys.exit(2)
    if not os.path.isdir(root):
        print(json.dumps({"ok": False, "error": "root_not_found", "root": root},
                         ensure_ascii=False))
        sys.exit(3)
    n = M.migrate_v30_fields(root)
    print(json.dumps({"ok": True, "migrated": n, "root": root}, ensure_ascii=False))


if __name__ == "__main__":
    main()
