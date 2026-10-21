# -*- coding: utf-8 -*-
"""gen_cookbook 漂移闸门自身的回归（4.9.24）。

背景（实测发现）：文档里的主 CLI 写法是 `python scripts/memory_ops.py backup --zip x`，
而 `scripts/memory_ops.py` 只是 3 行转发垫片，真实参数声明在 `scripts/memory_ops/_cli.py`。
闸门原先只跟「包内 `__init__.py`」，**不跟转发垫片** → 主入口的 flag 从来没人校验：
既把真存在的 `--zip` / `--keep` 报成漂移（假红灯），也让这条闸门对主入口**实质失效**。

本模块锁三件事：
1. `_src_with_package` 必须跟进垫片指向的包（`--zip` / `--keep` 能被找到）；
2. 端到端：真实 COOKBOOK 跑 `check()` 必须零问题；
3. **负向对照**：文档里写一个真不存在的 flag，`check()` 必须报出来——否则这个闸门
   等于「扫了但什么都不会红」，绿得毫无意义。
"""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import gen_cookbook as G  # noqa: E402


class ShimFollowTest(unittest.TestCase):
    def test_shim_source_includes_package_modules(self):
        shim = os.path.join(SKILL, "scripts", "memory_ops.py")
        self.assertTrue(os.path.isfile(shim), "转发垫片必须存在（文档契约）")
        src = G._src_with_package(shim)
        # 垫片本身很短；跟进去之后必须远大于它，且含真实参数声明
        self.assertGreater(len(src), 10000, "没跟进包目录，读到的仍是 3 行垫片")
        for flag in ("--zip", "--keep", "--offline", "--ann", "--deep"):
            self.assertIn(flag, src, "垫片跟随后应能看到 %s" % flag)

    def test_init_py_still_aggregates_siblings(self):
        ini = os.path.join(SKILL, "scripts", "memory_ops", "__init__.py")
        self.assertIn("release-audit", G._src_with_package(ini))


class CheckEndToEndTest(unittest.TestCase):
    def test_real_cookbook_has_no_drift(self):
        self.assertEqual([], G.check(), "真实 COOKBOOK.md 与代码漂移了")

    def test_unknown_flag_is_reported(self):
        """负向对照：闸门必须真的会红（否则等于没有闸门）。"""
        tmp = tempfile.mkdtemp(prefix="keeper_cb_")
        fake = os.path.join(tmp, "COOKBOOK.md")
        with io.open(fake, "w", encoding="utf-8") as f:
            f.write("# fake\n\n```bash\n"
                    "python scripts/memory_ops.py backup --definitely-not-a-flag\n"
                    "```\n")
        old = G.COOKBOOK
        try:
            G.COOKBOOK = fake
            problems = G.check()
        finally:
            G.COOKBOOK = old
        self.assertTrue(any("--definitely-not-a-flag" in p for p in problems),
                        "不存在的 flag 没被报出来，闸门是空的：%s" % problems)

    def test_missing_script_is_reported(self):
        tmp = tempfile.mkdtemp(prefix="keeper_cb2_")
        fake = os.path.join(tmp, "COOKBOOK.md")
        with io.open(fake, "w", encoding="utf-8") as f:
            f.write("```bash\npython scripts/no_such_script_zz.py --x\n```\n")
        old = G.COOKBOOK
        try:
            G.COOKBOOK = fake
            problems = G.check()
        finally:
            G.COOKBOOK = old
        self.assertTrue(any("脚本不存在" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
