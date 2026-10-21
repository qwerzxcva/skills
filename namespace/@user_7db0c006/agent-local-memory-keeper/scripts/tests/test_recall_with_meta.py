"""recall --with-meta 契约回归（4.9.17）。

锁定 A 方案（召回可观测性）的对外契约，防止后续改动破坏：
- 缺省（不带 --with-meta）返回形状**不变**（顶层仅 ok/count/entries，无 meta）——后向兼容；
- `recall --query --with-meta` 返回 meta，含 backend / configured_backend /
  fell_back_to_lexical / count；空结果时附 empty_hint（诊断为什么搜不到）；
- `recall --id --with-meta` 返回 meta，含 backend / backend_state / fell_back_to_lexical；
  backend_state ∈ {loaded, degraded, unprobed}，且**绝不**在未 probe 时用配置值冒充 live。

不依赖 fastembed（lexical 基线），不触碰真实记忆库。
"""
import os
import sys
import json
import tempfile
import subprocess
import unittest


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(HERE, "memory_ops", "__init__.py")


class RecallWithMetaTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_gate_meta_")
        self.env = dict(os.environ)
        self.env["AI_MEMORY_STORE"] = self.store
        self.env["AI_MEM_EMBED_BACKEND"] = "lexical"  # 门禁基线：不拉模型
        self.env["AI_MEM_NO_AUTO_INSTALL"] = "1"
        self._run("init")

    def _run(self, *args):
        p = subprocess.run(
            [sys.executable, CLI, *args],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(p.returncode, 0, msg=p.stderr)
        return json.loads(p.stdout)

    def test_default_recall_has_no_meta_backward_compatible(self):
        """缺省返回形状不变：顶层不得出现 meta（旧调用方零回归）。"""
        self._run("deposit", "--summary", "递归下降解析", "--tags", "test")
        rec = self._run("recall", "--query", "递归下降")
        self.assertTrue(rec.get("ok"))
        self.assertNotIn("meta", rec)
        self.assertIn("entries", rec)

    def test_query_with_meta_exposes_backend_and_degraded_flag(self):
        self._run("deposit", "--summary", "递归下降解析", "--tags", "test")
        rec = self._run("recall", "--query", "递归下降", "--with-meta")
        self.assertIn("meta", rec)
        meta = rec["meta"]
        for k in ("backend", "configured_backend", "fell_back_to_lexical", "count"):
            self.assertIn(k, meta, msg="meta 缺字段 %s" % k)
        self.assertIsInstance(meta["fell_back_to_lexical"], bool)
        # lexical 基线：配置=lexical，故不算「降级」（降级仅指配置神经却落到词法）
        self.assertFalse(meta["fell_back_to_lexical"])

    def test_empty_query_with_meta_gives_empty_hint(self):
        """搜不到时给出 empty_hint（诊断"为什么没命中"），这正是本修复的核心价值。"""
        rec = self._run("recall", "--query", "绝不可能命中的词zzzqqq", "--with-meta")
        self.assertEqual(rec.get("count"), 0)
        self.assertIn("empty_hint", rec["meta"])
        self.assertTrue(rec["meta"]["empty_hint"])

    def test_recall_by_id_with_meta_reports_honest_state(self):
        dep = self._run("deposit", "--summary", "按id召回测试", "--tags", "test")
        mid = dep["id"]
        # 缺省：无 meta
        plain = self._run("recall", "--id", mid)
        self.assertNotIn("meta", plain)
        # --with-meta：带诚实后端状态
        rec = self._run("recall", "--id", mid, "--with-meta")
        self.assertIn("meta", rec)
        meta = rec["meta"]
        self.assertIn("backend_state", meta)
        self.assertIn(meta["backend_state"], ("loaded", "degraded", "unprobed"))
        self.assertIsInstance(meta["fell_back_to_lexical"], bool)


if __name__ == "__main__":
    unittest.main()
