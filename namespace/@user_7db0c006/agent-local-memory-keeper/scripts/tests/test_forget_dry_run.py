# -*- coding: utf-8 -*-
"""回归：forget 必须尊重 --dry-run（#forget-dry-run / P1-6）。

根因：forget(root, mid, reason) 既无 dry_run 参数、CLI 也不传，导致用户敲
`forget --dry-run` 想预览却真实归档该记忆（与 delete/archive/reclassify 等破坏性操作
的 dry-run 约定不一致，是静默破坏记忆的安全缺口）。

本测试锁定：dry_run=True 只回显 will_change、绝不写盘；dry_run=False 才真实归档。
"""
import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memory_ops as M


class ForgetDryRunTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        M.init_store(self.store)
        self.mid = M.deposit(self.store, "best_practice",
                             "测试经验：做X要用Y", ["test"], "body", importance=0.8)

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def _state(self):
        mem, _ = M._load_mem(self.store, self.mid)
        return mem.get("status"), mem.get("erroneous"), mem.get("belief_strength")

    def test_dry_run_does_not_mutate(self):
        before = self._state()
        r = M.forget(self.store, self.mid, reason="t", dry_run=True)
        self.assertTrue(r.get("dry_run"), "dry_run 必须回显 dry_run=True")
        self.assertIn("will_change", r, "dry_run 必须回显 will_change 预览")
        after = self._state()
        self.assertEqual(after, before,
                         "forget(dry_run=True) 绝不能改动 status/erroneous/belief_strength")
        # 索引也不应被改动
        idx = M.load_index(self.store)
        entry = next((e for e in idx.get("entries", []) if e.get("id") == self.mid), {})
        self.assertEqual(entry.get("status"), "active")

    def test_real_forget_archives(self):
        r = M.forget(self.store, self.mid, reason="t", dry_run=False)
        self.assertIsNone(r.get("dry_run"), "真实 forget 不应标记 dry_run")
        st, err, bs = self._state()
        self.assertEqual(st, "archived")
        self.assertTrue(err)
        self.assertEqual(bs, 0.0)

    def test_backward_compat_default_is_real(self):
        # 默认（不传 dry_run）应保持原破坏性语义，避免回归
        r = M.forget(self.store, self.mid, reason="t")
        self.assertIsNone(r.get("dry_run"))
        self.assertEqual(self._state()[0], "archived")


if __name__ == "__main__":
    unittest.main()
