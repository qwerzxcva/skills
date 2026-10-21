"""keeper 包级冒烟测试（随包发布，lexical 后端，无需 fastembed）。

覆盖：
- 核心链路 init -> deposit -> recall 真实跑通（与钩子实际调用方式一致：subprocess 调 CLI）；
- Bug-2 回归：根 `mem_bridge.py` 不应要求 PYTHONPATH 才能加载。

不依赖开发实验室脚本，不触碰 L1/L2/L3 原生记忆。
"""
import os
import sys
import json
import tempfile
import subprocess
import unittest


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(HERE, "memory_ops", "__init__.py")
MEM_BRIDGE = os.path.abspath(os.path.join(HERE, "..", "mem_bridge.py"))


class SmokePackageTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_gate_")
        self.env = dict(os.environ)
        self.env["AI_MEMORY_STORE"] = self.store
        self.env["AI_MEM_EMBED_BACKEND"] = "lexical"

    def _run(self, *args):
        p = subprocess.run(
            [sys.executable, CLI, *args],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(p.returncode, 0, msg=p.stderr)
        return json.loads(p.stdout)

    def test_init_deposit_recall(self):
        self._run("init")
        dep = self._run("deposit", "--summary", "冒烟：递归下降解析", "--tags", "test")
        self.assertIn("id", dep)
        rec = self._run("recall", "--query", "递归下降")
        self.assertTrue(rec.get("ok"))
        self.assertGreaterEqual(rec.get("count", 0), 1)

    def test_mem_bridge_loads_without_pythonpath(self):
        # Bug-2 回归：根 mem_bridge.py 在 F18 包化后必须不依赖 PYTHONPATH 即可加载
        if not os.path.exists(MEM_BRIDGE):
            self.skipTest("mem_bridge.py 不在预期路径")
        p = subprocess.run(
            [sys.executable, MEM_BRIDGE, "--help"],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(p.returncode, 0, msg=p.stderr)


if __name__ == "__main__":
    unittest.main()
