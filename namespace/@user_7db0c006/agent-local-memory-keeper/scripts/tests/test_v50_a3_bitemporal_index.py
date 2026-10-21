# -*- coding: utf-8 -*-
"""回归（5.0 / A3）：双时序字段必须镜像进召回索引，否则 `recall --as-of` 静默错。

根因（第 4 次命中「契约对账缺失」根因族：规则层期待的字段 ≠ 写入侧实际产生的字段）：
  · `_as_of_visible(m, as_of)` 判可见性要读 `valid_at` / `invalid_at`；
  · 但 `recall()` 的过滤循环遍历的是 **index entry**（不是记忆文件，不读盘）；
  · 而 `invalidate()` 只把 `status` 同步进索引，从不写 `invalid_at`；
  · `_index_entry_from_mem()`（rebuild / 索引修复路径）也没有这两个字段。
后果：`recall --as-of <失效之后>` 仍把已失效记忆当可见 —— **静默返回错误结果、不报错**。
修复：deposit entry、`_index_entry_from_mem`、`invalidate`/`uninvalidate` 索引同步四处补齐。

本测试锁定上述闭环；并锁定 rebuild 不丢字段（防「跑一次 rebuild 就打回 None」的历史缺陷复发）。
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memory_ops as M


def _entry(root, mid):
    for e in M.load_index(root)["entries"]:
        if e.get("id") == mid:
            return e
    return None


def _hit(root, mid, **kw):
    got = M.recall(root, **kw)
    rows = got.get("results") if isinstance(got, dict) else got
    return [x for x in (rows or []) if x.get("id") == mid]


class BitemporalIndexSyncTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        M.init_store(self.store)
        self.mid = M.deposit(self.store, "pitfall", "zzbitemporal index probe",
                             ["a3"], "body zzbitemporal")
        self.mem, _ = M._load_mem(self.store, self.mid)
        self.vday = self.mem.get("valid_at")
        self.assertIsNotNone(self.vday, "deposit 必须写 valid_at（双时序起点）")

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def test_entry_carries_bitemporal_at_deposit(self):
        e = _entry(self.store, self.mid)
        self.assertEqual(e.get("valid_at"), self.vday,
                         "index entry 缺 valid_at → as_of 回溯失效")
        self.assertIn("invalid_at", e, "index entry 缺 invalid_at 键")
        self.assertIsNone(e["invalid_at"], "新条目未失效，invalid_at 应为 None")

    def test_rebuild_keeps_bitemporal(self):
        M.rebuild(self.store)
        e = _entry(self.store, self.mid)
        self.assertEqual(e.get("valid_at"), self.vday, "rebuild 丢了 valid_at")
        self.assertIn("invalid_at", e, "rebuild 后 invalid_at 键丢失")

    def test_as_of_sees_invalidation(self):
        d0 = datetime.date.fromisoformat(self.vday)
        d_inv = (d0 + datetime.timedelta(days=1)).isoformat()
        d_late = (d0 + datetime.timedelta(days=400)).isoformat()

        # 失效前：无 as_of 应可见
        self.assertEqual(len(_hit(self.store, self.mid)), 1)

        M.invalidate(self.store, self.mid, reason="probe", at=d_inv)
        e = _entry(self.store, self.mid)
        self.assertEqual(e.get("status"), "superseded", "索引 status 未同步")
        self.assertEqual(e.get("invalid_at"), d_inv,
                         "索引 invalid_at 未同步 → recall --as-of 会把已失效条目当可见")

        # 有效期内时点：可见
        self.assertEqual(len(_hit(self.store, self.mid, as_of=self.vday)), 1,
                         "有效期内时点应可见")
        # 失效之后时点：必须不可见（本用例的核心断言）
        self.assertEqual(len(_hit(self.store, self.mid, as_of=d_late)), 0,
                         "失效之后的 as_of 仍可见 = 索引缺 invalid_at 的静默 bug")
        # 默认与显式开关
        self.assertEqual(len(_hit(self.store, self.mid)), 0, "默认应过滤 superseded")
        self.assertEqual(len(_hit(self.store, self.mid, include_superseded=True)), 1,
                         "--include-superseded 应可见")

        # 撤销后：索引侧清失效位、valid_at 历史保留、恢复可见
        M.uninvalidate(self.store, self.mid)
        e = _entry(self.store, self.mid)
        self.assertEqual(e.get("status"), "active", "索引 status 未复位")
        self.assertIsNone(e.get("invalid_at"), "索引 invalid_at 未清")
        self.assertEqual(e.get("valid_at"), self.vday, "valid_at 历史应保留")
        self.assertEqual(len(_hit(self.store, self.mid)), 1, "撤销后应恢复可见")


if __name__ == "__main__":
    unittest.main()
