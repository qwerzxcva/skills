# -*- coding: utf-8 -*-
"""回归（5.0 / A1 续修）：`access_count` 只能有**一个写入权威**，且每次使用只计一次。

背景：A1 上轮只清了 `_api.py` 两处文件侧自增，本轮全仓复查又抓到 4 处漏点
（全属「双写脱节」病根 —— 文件字段恒 0、热源有真值，下游治理链全读错）：
  · `_api.py` touch 块的 bump 与函数末尾的批量 bump **重复计数** → `recall --touch` 翻倍
  · `__init__.py::touch()` 仍在自增记忆文件字段
  · `__init__.py::_cross_type_associate` 从文件字段读 → 关联补入项恒显示 0
  · `_deposit.py` 近重复吸收路径仍在自增文件字段
  · `_doctor.py::dashboard` 读文件字段 → 真库 204/211 恒 0，仪表盘「最常召回」全是 0
并**排除一处误报**：`_reflect._recent_access_count` 统计的是 `accessed_from` 审计条目，
与 `access_count` 字段无关（按「三态定性」先排除开关/文档默认态/权限再判 bug）。

两道锁：
  A. 静态：`memory_ops/` 下不得再出现「文件侧自增」（`["access_count"] = … + 1`）
  B. 行为：`touch` / `recall --touch` / `recall --outcome` 都只让热源 **+1**
"""
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.environ.setdefault("KEEPER_RECALL_MODE", "inprocess")

import memory_ops as M  # noqa: E402

MOD_DIR = os.path.join(HERE, "memory_ops")
FILE_SIDE_INC = re.compile(r'\[\s*"access_count"\s*\]\s*=[^\n]*\+\s*1')


class AccessCountSingleSourceTest(unittest.TestCase):

    def setUp(self):
        self.store = tempfile.mkdtemp()
        M.init_store(self.store)
        self.mid = M.deposit(self.store, "pitfall", "zza1 single source probe",
                             ["a1"], "body zza1 single source")

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def _file_ac(self):
        m, _ = M._load_mem(self.store, self.mid)
        return int(m.get("access_count", 0) or 0)

    def _hot(self):
        return M._access_count_of(self.store, self.mid)

    # ── A 静态锁 ──────────────────────────────────────────────
    def test_no_file_side_increment_left(self):
        hits = []
        for f in sorted(os.listdir(MOD_DIR)):
            if not f.endswith(".py"):
                continue
            s = io.open(os.path.join(MOD_DIR, f), encoding="utf-8").read()
            for i, l in enumerate(s.split("\n"), 1):
                if l.strip().startswith("#"):
                    continue
                if FILE_SIDE_INC.search(l):
                    hits.append("%s:%d %s" % (f, i, l.strip()[:90]))
        self.assertFalse(
            hits,
            "仍有文件侧自增 `access_count` —— 频次的唯一权威是 recall_counts.json，"
            "写记忆文件字段就是双写脱节的病根。命中：%r" % hits)

    # ── B 行为锁 ──────────────────────────────────────────────
    def test_touch_bumps_hot_source_once_and_not_file(self):
        f0, c0 = self._file_ac(), self._hot()
        M.touch(self.store, self.mid)
        self.assertEqual(self._file_ac(), f0, "touch 不得再自增记忆文件字段")
        self.assertEqual(self._hot(), c0 + 1, "touch 应让权威热源恰好 +1")

    def test_recall_touch_does_not_double_count(self):
        c0 = self._hot()
        M.recall(self.store, query="zza1 single source probe", touch=True)
        self.assertEqual(
            self._hot(), c0 + 1,
            "recall --touch 对同一命中条目只能 +1（曾出现「touch 块 + 末尾批量段」双计）")

    def test_recall_outcome_bumps_once_only(self):
        c0 = self._hot()
        M.recall(self.store, mid=self.mid, outcome="good")
        self.assertEqual(self._hot(), c0 + 1,
                         "recall --outcome（mid 快路径）只能 +1")

    def test_plain_recall_counts_once(self):
        c0 = self._hot()
        M.recall(self.store, query="zza1 single source probe")
        self.assertEqual(self._hot(), c0 + 1,
                         "普通 recall 命中一次应计一次（末尾批量段）")

    # ── C `--filter` 可用性 + 不串缓存 ────────────────────────
    def _flt_hits(self, expr):
        r = M.recall(self.store, query="zza1 single source probe",
                     filter_clauses=M.parse_filter(expr))
        rows = r.get("results") if isinstance(r, dict) else r
        return [x for x in (rows or []) if x.get("id") == self.mid]

    def test_filter_on_access_count_is_usable(self):
        """`--filter "access_count>N"` 曾**恒返回空**：entry 上无该键，且过滤早于补值。"""
        M.recall(self.store, query="zza1 single source probe")   # 热源 → 1
        self.assertTrue(self._flt_hits("access_count>0"),
                        "access_count>0 应命中（热源已 ≥1）")
        self.assertFalse(self._flt_hits("access_count>999"),
                         "access_count>999 不应命中")

    def test_filter_clauses_do_not_share_cache(self):
        """不同 `--filter` 不得串缓存（`filter_clauses` 原先不在缓存键里，与 as_of 同类）。"""
        M.recall(self.store, query="zza1 single source probe")   # 让热源 ≥1
        n_yes = len(self._flt_hits("access_count>0"))
        n_no = len(self._flt_hits("access_count>999"))
        self.assertEqual((n_yes, n_no), (1, 0),
                         "两次不同 filter 拿到同一结果 = 缓存键缺 filter_clauses")


if __name__ == "__main__":
    unittest.main()
