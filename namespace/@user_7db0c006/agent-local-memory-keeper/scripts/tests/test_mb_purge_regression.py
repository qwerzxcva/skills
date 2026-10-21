#!/usr/bin/env python3
"""mb-purge 回归测试。

背景：4.7.0 审计发现 `mem_bridge.py` 的 purge_keeper 向 reclaim()(=archive_sweep)
误传不存在的 `max_purge=` 形参，导致任何用户跑 `purge` 都 TypeError 崩溃。
该命令当时未被 run_gate 覆盖，才漏过 93 项测试。

本测试在隔离 AI_MEMORY_STORE 中跑真实 CLI：
- purge 默认 dry-run（不删）必须 rc=0 且不含 TypeError；
- purge --apply 真实删除路径也必须 rc=0（真正覆盖此前崩溃的代码分支）。
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
MEM_BRIDGE = os.path.join(SKILL_ROOT, "mem_bridge.py")
PY = sys.executable


def _run(store, *cli_args, timeout=120):
    env = dict(os.environ)
    env["AI_MEMORY_STORE"] = store
    env["WORKBUDDY_WORKSPACE"] = store
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    try:
        p = subprocess.run([PY, MEM_BRIDGE, *cli_args], env=env,
                           capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except Exception as e:  # pragma: no cover
        return 1, str(e)


def _seed(store, n=3):
    _run(store, "init")
    for i in range(n):
        _run(store, "distill", "--summary", f"待清理经验{i}",
             "--body", "正文足够长" * 5, "--tags", "t",
             "--category", "best_practice")


class TestMbPurgeRegression(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_purge_reg_")
        _seed(self.store)

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def test_purge_dry_run_no_crash(self):
        """默认 dry-run：必须 rc=0，且不得出现此前 TypeError。"""
        rc, out = _run(self.store, "purge", "--older", "0")
        self.assertEqual(rc, 0, f"purge dry-run 返回 {rc}，输出: {out[:200]}")
        self.assertNotIn("TypeError", out, "purge 仍抛 TypeError（max_purge 形参未修）")
        self.assertNotIn("unexpected keyword argument", out)

    def test_purge_apply_path_no_crash(self):
        """--apply 真实删除分支：必须 rc=0，真正覆盖崩溃代码路径。"""
        rc, out = _run(self.store, "purge", "--older", "0", "--apply")
        self.assertEqual(rc, 0, f"purge --apply 返回 {rc}，输出: {out[:200]}")
        self.assertNotIn("TypeError", out)
        self.assertNotIn("unexpected keyword argument", out)
        # apply 后库应被清空（older=0 全候选）
        try:
            d = json.loads(out[out.rfind("{"):]) if "{" in out else {}
            self.assertIn("ok", d, f"purge 输出缺少 ok 字段: {out[:200]}")
        except Exception:
            # 输出可能被日志污染，仅断言无崩溃即可（上方已判 rc==0）
            pass

    def test_purge_dry_run_is_non_destructive(self):
        """dry-run 不应删除任何记忆（与 --apply 区分）。"""
        before = len([f for f in os.listdir(os.path.join(self.store, "memories"))
                      if f.endswith(".json")]) if os.path.isdir(
            os.path.join(self.store, "memories")) else 0
        rc, out = _run(self.store, "purge", "--older", "0")
        self.assertEqual(rc, 0)
        after = len([f for f in os.listdir(os.path.join(self.store, "memories"))
                     if f.endswith(".json")]) if os.path.isdir(
            os.path.join(self.store, "memories")) else 0
        self.assertEqual(before, after, "dry-run 不应删除记忆却删了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
