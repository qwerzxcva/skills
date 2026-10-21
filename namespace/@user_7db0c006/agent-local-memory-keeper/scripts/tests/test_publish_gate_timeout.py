# -*- coding: utf-8 -*-
"""发版门禁超时按闸门分档（4.9.25）。

## 为什么需要这条

`publish_gate.py` 原先把三道闸门的超时**一刀切**（统一 `--timeout 1800`）。但这三道的
耗时量级差两个数量级：文档一致性约 0.3s、静态断言约 20s，而全量集成测试在慢环境要
十几分钟。后果是**两头不对**：
  · 对 cookbook / claims —— 1800s 是完全用不上的巨大余量；
  · 对 tests —— 只剩 1.7 倍余量，实测跑满 1800s 被强杀（rc=124），
    整个门禁报 BLOCKED 却与代码质量无关（见 _gate_timeout_4.9.24.md 存证）。

修法：`STEPS` 每道自带默认超时（cookbook 300 / tests 3600 / claims 900）；
`--timeout` 仍可显式统一覆盖（用于"我确定这台机器极慢"的场景）。

## 本测试守什么

- 正向：每道闸门都声明了自己的分档超时，且 tests 显著大于其余两道
- 正向：不给 `--timeout` 时，各道用**自己的**分档值
- 正向：给了 `--timeout` 时，**所有道**都被覆盖
- 负向对照：`--timeout` 的 argparse 默认值必须是 `None`（若又硬编码成某个数，
  分档就永远不生效——这正是回归会悄悄复活的方式）
"""
import contextlib
import importlib.util
import io
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_PG_PATH = os.path.join(_SCRIPTS, "publish_gate.py")


def _load_gate():
    spec = importlib.util.spec_from_file_location("_pg_under_test", _PG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGateTimeoutTiers(unittest.TestCase):

    def setUp(self):
        self.pg = _load_gate()
        self.tiers = {s[0]: s[3] for s in self.pg.STEPS}

    # ── 正向：分档存在且合理 ────────────────────────────────────────────
    def test_every_step_declares_a_tier_timeout(self):
        self.assertTrue(self.pg.STEPS)
        for s in self.pg.STEPS:
            self.assertEqual(len(s), 4,
                             "每道闸门必须带 (id, 脚本, 参数, 分档超时)，实际 %r" % (s,))
            self.assertIsInstance(s[3], int)

    def test_tests_tier_is_much_larger(self):
        self.assertGreaterEqual(self.tiers["tests"], 3600,
                                "集成测试窗口必须显著大于原先的 1800s")
        self.assertGreater(self.tiers["tests"], self.tiers["cookbook"])
        self.assertGreater(self.tiers["tests"], self.tiers["claims"])

    # ── 行为：真的把分档值传下去了 ──────────────────────────────────────
    def _capture_run(self, argv):
        seen = {}

        def _fake(script, extra, timeout=None):
            seen[script] = timeout
            return 0, 0.0, ""

        self.pg._run = _fake
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.pg.main(argv)
        return rc, seen

    def test_default_uses_each_tier_value(self):
        rc, seen = self._capture_run([])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["run_gate.py"], self.tiers["tests"])
        self.assertEqual(seen["gen_cookbook.py"], self.tiers["cookbook"])
        self.assertEqual(seen["verify_claims.py"], self.tiers["claims"])

    def test_explicit_timeout_overrides_every_step(self):
        rc, seen = self._capture_run(["--timeout", "42"])
        self.assertEqual(rc, 0)
        self.assertEqual(set(seen.values()), {42},
                         "--timeout 应统一覆盖所有闸门，实际 %r" % seen)

    def test_only_flag_still_uses_tier_value(self):
        rc, seen = self._capture_run(["--only", "tests"])
        self.assertEqual(rc, 0)
        self.assertEqual(list(seen), ["run_gate.py"])
        self.assertEqual(seen["run_gate.py"], self.tiers["tests"])

    # ── 负向对照：防「默认值又被硬编码」的回归 ──────────────────────────
    def test_argparse_default_is_none(self):
        with io.open(_PG_PATH, encoding="utf-8") as f:
            src = f.read().replace("\r\n", "\n")
        m = re.search(r'"--timeout"\s*,\s*type=int\s*,\s*default=(\w+)', src)
        self.assertIsNotNone(m, "找不到 --timeout 的参数定义")
        self.assertEqual(
            m.group(1), "None",
            "--timeout 默认值必须是 None/未给，否则闸门分档永远不生效")


if __name__ == "__main__":
    unittest.main(verbosity=2)
