# -*- coding: utf-8 -*-
"""回归（5.0）：`_cli.py` 的 argparse 必须能构建成功且选项名全局唯一。

背景（真实事故，2026-09-16）：给 A3 加 `invalidate` 的 CLI 入参时，在**扁平单 parser**
上重复定义了 `--reason`（deposit/reclassify 段已有）与 `--at`（schedule_reflect 已有，
且默认 "03:00"）。argparse 在构建期抛
    `ArgumentError: argument --reason: conflicting option string: --reason`
→ **整个 CLI 起不来**（`memory_ops.py <任意命令>` 直接 Traceback）。
后果不是「一条用例红」，而是**所有子进程型测试级联失败**：门禁一次 20 失败 / 1 错误，
且 argparse 只报第一个冲突（`--at` 那个被掩盖），极易误判为无关回归。

两道锁：
  A. 静态：扫源码里 `add_argument("--x")` 的选项串，**不得出现重复**
     （运行时只报第一个冲突，静态扫才能一次看全）。
  B. 动态：真的把 parser 建起来（`--help` 走 `SystemExit(0)`），确认无冲突。
"""
import io
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
CLI_PY = os.path.join(HERE, "memory_ops", "_cli.py")
MEM_OPS = os.path.join(HERE, "memory_ops.py")


class CliArgparseIntegrityTest(unittest.TestCase):
    def test_no_duplicate_option_strings(self):
        src = io.open(CLI_PY, encoding="utf-8").read()
        # 只统计「选项串」字面量；短选项/位置参数不参与本断言
        opts = re.findall(r'add_argument\(\s*["\'](--[A-Za-z0-9\-]+)["\']', src)
        seen, dup = set(), {}
        for o in opts:
            if o in seen:
                dup[o] = dup.get(o, 1) + 1
            seen.add(o)
        self.assertFalse(
            dup,
            "扁平单 parser 上出现重复选项名 → argparse 构建期 ArgumentError，"
            "整条 CLI 会静默死亡。重复项：%r（argparse 只报第一个，务必全部改掉）" % dup)

    def test_parser_builds(self):
        """构建即验证：能跑出 --help 说明没有 conflict。"""
        r = subprocess.run([sys.executable, MEM_OPS, "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        blob = (r.stdout or "") + (r.stderr or "")
        self.assertNotIn("conflicting option string", blob,
                         "argparse 选项冲突，CLI 不可用：%s" % blob[-400:])
        self.assertEqual(r.returncode, 0,
                         "CLI --help 应 rc=0，实际 %s：%s" % (r.returncode, blob[-400:]))
        self.assertIn("--as-of", blob, "A3 参数未接进解析器")

    def test_invalidate_cli_end_to_end(self):
        """A3 CLI 面实跑（此前只用 Python API 验证过，CLI 面漏测才放过冲突）。"""
        import shutil
        import json as _json
        import tempfile
        root = tempfile.mkdtemp(prefix="keeper_cli_a3_")
        try:
            def run(*a):
                p = subprocess.run([sys.executable, MEM_OPS, "--root", root] + list(a),
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=300)
                return p

            p = run("init")
            self.assertEqual(p.returncode, 0, "init 失败：%s" % (p.stderr or "")[-300:])
            p = run("deposit", "--category", "pitfall", "--summary", "zzcli a3 probe",
                    "--body", "body zzcli", "--tag", "a3")
            self.assertEqual(p.returncode, 0, "deposit 失败：%s" % (p.stderr or "")[-300:])
            mid = _json.loads(p.stdout.strip().splitlines()[-1])
            mid = mid if isinstance(mid, str) else (mid.get("id") or mid.get("mid"))

            p = run("invalidate", "--id", mid, "--reason", "cli probe",
                    "--invalid-at", "2026-10-01", "--dry-run")
            self.assertEqual(p.returncode, 0,
                             "invalidate CLI 失败：%s" % (p.stderr or "")[-300:])
            self.assertIn("dry_run", p.stdout)

            p = run("invalidate", "--id", mid, "--reason", "cli probe",
                    "--invalid-at", "2026-10-01")
            self.assertEqual(p.returncode, 0, "invalidate 落盘失败：%s" % (p.stderr or "")[-300:])
            self.assertIn("2026-10-01", p.stdout)

            p = run("uninvalidate", "--id", mid)
            self.assertEqual(p.returncode, 0, "uninvalidate 失败：%s" % (p.stderr or "")[-300:])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
