# -*- coding: utf-8 -*-
""" 相位 B 回归测试：存储一致性收口（unittest 版，纳入随包门禁）。

锁死两件事：
1) save_index 改为「scoped DELETE（仅删本次要写的 id）+ 幂等 upsert」，取代旧的
unscoped `DELETE FROM entries` 全表清空。当传入「部分 entries」时，不应误删其他条目
（验证 scoped 删除的正确性）。
2) 大库全量重写走分批 DELETE + executemany upsert，不会因单条 IN (...) 超过 SQLite
999 参数上限而崩溃（验证 chunk 逻辑）。
直接 import memory_ops 包调用 load_index/save_index/deposit（与 CLI 同源）。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

SKILL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import memory_ops  # noqa: E402  (包形态 import，触发 __init__ 动态加载子模块)


def _new_root():
    os.environ.pop("AI_MEMORY_STORE", None)  # 杜绝误写真实记忆库
    tmp = tempfile.mkdtemp(prefix="keeper_b_")
    root = os.path.join(tmp, "store").replace("\\", "/")
    memory_ops.init_store(root)
    return tmp, root


class PhaseBStorageTest(unittest.TestCase):

    def test_scoped_save_no_drift(self):
        tmp, root = _new_root()
        try:
            for i in range(6):
                memory_ops.deposit(root, "best_practice", "mem %d" % i,
                                  ["t%d" % i], "body %d" % i)
            idx = memory_ops.load_index(root)
            self.assertEqual(len(idx["entries"]), 6,
                             "deposit 后条目数应为 6，实际 %d" % len(idx["entries"]))
            # 仅传入前 2 条做部分 save：scoped DELETE 只删这 2 个 id，其余 4 条必须保留
            partial = {"entries": idx["entries"][:2]}
            memory_ops.save_index(root, partial)
            idx2 = memory_ops.load_index(root)
            self.assertEqual(len(idx2["entries"]), 6,
                             "部分 save 误删了其他条目，剩 %d" % len(idx2["entries"]))
            # 全量 save 后仍为 6，无漂移
            memory_ops.save_index(root, idx)
            idx3 = memory_ops.load_index(root)
            self.assertEqual(len(idx3["entries"]), 6,
                             "全量 save 后条目数异常 %d" % len(idx3["entries"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_large_save_chunking(self):
        tmp, root = _new_root()
        try:
            # 1200 条合成 entries，远超 SQLite 单条 IN (...) 999 参数上限 → 必须走分批 DELETE
            entries = []
            for i in range(1200):
                entries.append({
                    "id": "e%d" % i, "category": "best_practice", "summary": "s%d" % i,
                    "tags": ["t"], "tier": "working", "status": "active",
                    "scope": "universal", "project": "", "file": "e%d.json" % i})
            memory_ops.save_index(root, {"entries": entries})
            idx = memory_ops.load_index(root)
            self.assertEqual(len(idx["entries"]), 1200,
                             "大库 save 后条目数应为 1200，实际 %d" % len(idx["entries"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
