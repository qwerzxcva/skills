# -*- coding: utf-8 -*-
"""
error_hook.py — Hook 自动捕获（bash 执行失败信号强制捕获）

核心思想：bash 执行失败是最有价值的「踩坑」信号，应由 hook 级**强制**自动捕获，
而非依赖 AI 自觉 deposit（那个会漏）。本模块默认不安装——提供：
- `--install`：打印 WorkBuddy hook 注册说明（JSON 片段，手动加入连接器配置）
- `--dry-run`：模拟一段 bash 错误输出，预览会记录的记忆（不实际写盘）

设计：纯加性可选能力；不强制写任何未知路径，避免平台耦合风险。
注：`--write-capture` 已移除——旧版 hooks/bash_error_capture.py 因字段名 bug 且
从未注册，自 v4.5.50 起停带，并于 v4.6.11 彻底删除（I13）；现由
hooks/post_tool_use_error_capture.py（真正的已注册 PostToolUse 钩子）承担同等捕获职责。
"""

import argparse
import os
import sys
import json

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(SKILL_DIR, "hooks")


def dry_run(sample=""):
    if not sample:
        sample = ("Traceback (most recent call last):\n"
                  "  File x.py, line 1\nValueError: bad input")
    err_sig = any(k in sample.lower() for k in
                  ["error", "traceback", "exception", "failed", "拒绝", "错误", "异常"])
    lines = [l for l in sample.splitlines() if l.strip()][-8:]
    return {"would_capture": err_sig,
            "summary": (lines[-1] if lines else "")[:120],
            "tags": "auto-captured,bash-error",
            "area": "bugfix", "priority": "high"}


def install_guide():
    return {
        "note": "WorkBuddy hook 注册说明（默认不自动安装，需手动在连接器/hook 配置中加入）：",
        "hook_event": "PostToolUse",
        "match_tool": "bash / shell",
        "command": "python <skill>/hooks/post_tool_use_error_capture.py",
        "json_example": {
            "hooks": [{
                "event": "PostToolUse",
                "matcher": {"tool": "bash"},
                "command": "python <skill_dir>/hooks/post_tool_use_error_capture.py"
            }]
        }
    }


def main():
    ap = argparse.ArgumentParser(description="Hook 自动捕获（bash 错误→记忆）")
    ap.add_argument("--install", action="store_true", help="打印 WorkBuddy hook 注册说明")
    ap.add_argument("--dry-run", action="store_true", help="模拟一段 bash 错误，预览会记录的记忆")
    ap.add_argument("--sample", default="", help="--dry-run 的样例错误输出")
    args = ap.parse_args()
    if args.install:
        print(json.dumps(install_guide(), ensure_ascii=False, indent=2))
    elif args.dry_run:
        print(json.dumps(dry_run(args.sample), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"hint": "使用 --install / --dry-run"},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
