# -*- coding: utf-8 -*-
"""回归（5.0）：派生文件的幽灵键必须能被统一回收（`prune_derived`），且重建即对齐。

根因（真库实测）：`route_registry.json` 426 键 vs 真实记忆 226 条、`recall_counts.json`
1014 键 vs 存活 142 —— 这些派生文件都是「按 id 增量写」，**删除/归档路径从不回删键**，
而 `rebuild()` 只重建 index.json/index.db，**完全不碰派生文件** → 幽灵键只增不减。
后果不是报错，而是**静默跑偏**：doctor 的跨层聚合虚胖、热度中位数被幽灵计数拉偏。

本测试锁定：
  A. 四类派生文件的幽灵键都能被回收，存活 id 一个不丢；
  B. `rebuild(return_report=True)` 顺带完成回收，返回体含 pruned 明细；
  C. 🔴 **安全阀**：alive 集合为空 / 索引不可读时一律 `skipped`，
     **绝不**因一次读取异常把派生文件整体清空（这是本类清理最危险的失败模式）；
  D. `dry_run` 只报告不落盘。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memory_ops as M


def _w(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _r(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


class PruneDerivedTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_prune_")
        M.init_store(self.root)
        self.alive = [
            M.deposit(self.root, "pitfall", "zzprune A", ["p"], "body A"),
            M.deposit(self.root, "pitfall", "zzprune B", ["p"], "body B"),
        ]
        self.rr = os.path.join(self.root, "store", "route_registry.json")
        self.rc = os.path.join(self.root, "recall_counts.json")
        self.md = os.path.join(self.root, "store", "maintenance_dirty.json")
        self.cl = os.path.join(self.root, "store", "clusters.json")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _inject_ghosts(self, n=5):
        """注入 n 个幽灵键（id 形如 GHOST-xxx，磁盘上不存在）。"""
        ghosts = ["GHOST-%03d" % i for i in range(n)]
        rr = _r(self.rr) if os.path.exists(self.rr) else {}
        for g in ghosts:
            rr[g] = ["L3"]
        _w(self.rr, rr)

        rc = _r(self.rc) if os.path.exists(self.rc) else {}
        # 注意：deposit **不写** recall_counts（只有 recall 才 bump），故这里要显式
        # 造出「存活 id 的真计数」，才能验证回收不会误删存活键。
        for mid in self.alive:
            rc[mid] = {"count": 9, "last": "2026-09-16"}
        for g in ghosts:
            rc[g] = {"count": 3, "last": "2026-01-01"}
        _w(self.rc, rc)

        _w(self.md, {"dirty_mids": ghosts + list(self.alive), "updated_at": "x"})
        _w(self.cl, {"clusters": [{"label": "c0", "ids": ghosts + list(self.alive)}],
                     "centroids": {"0": [0.0]}, "generated": "x", "n": 1})
        return ghosts

    def test_prune_drops_ghosts_keeps_alive(self):
        ghosts = self._inject_ghosts()
        rep = M.prune_derived(self.root, alive_ids=self.alive)
        self.assertEqual(rep["dropped_total"], len(ghosts) * 4,
                         "四类派生文件各应掉 %d 个幽灵键，实际 %r" % (len(ghosts), rep))
        for g in ghosts:
            self.assertNotIn(g, _r(self.rr), "route_registry 幽灵键未回收")
            self.assertNotIn(g, _r(self.rc), "recall_counts 幽灵键未回收")
        self.assertNotIn(ghosts[0], _r(self.md)["dirty_mids"], "dirty 幽灵未回收")
        self.assertNotIn(ghosts[0], _r(self.cl)["clusters"][0]["ids"], "cluster 幽灵未回收")
        # 存活 id 一个都不能丢
        for mid in self.alive:
            self.assertIn(mid, _r(self.rr), "存活 id 被误删（route_registry）")
            self.assertIn(mid, _r(self.rc), "存活 id 被误删（recall_counts）")
            self.assertIn(mid, _r(self.md)["dirty_mids"], "存活 id 被误删（dirty）")
            self.assertIn(mid, _r(self.cl)["clusters"][0]["ids"], "存活 id 被误删（cluster）")

    def test_rebuild_prunes_and_reports(self):
        ghosts = self._inject_ghosts()
        r = M.rebuild(self.root, return_report=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["rebuilt"], len(self.alive))
        self.assertEqual(r["pruned"]["dropped_total"], len(ghosts) * 4,
                         "rebuild 未顺带回收派生幽灵键：%r" % r["pruned"])
        self.assertNotIn(ghosts[0], _r(self.rr))
        # 兼容：默认仍返回 int（老调用方不受影响）
        self.assertIsInstance(M.rebuild(self.root), int)

    def test_dry_run_reports_without_writing(self):
        ghosts = self._inject_ghosts()
        rep = M.prune_derived(self.root, alive_ids=self.alive, dry_run=True)
        self.assertEqual(rep["dropped_total"], len(ghosts) * 4)
        self.assertIn(ghosts[0], _r(self.rr), "dry_run 不应落盘")

    def test_safety_valve_empty_alive_never_wipes(self):
        """🔴 最危险的失败模式：alive 为空时若照常做差集，会把派生层整体清空。"""
        ghosts = self._inject_ghosts()
        rep = M.prune_derived(self.root, alive_ids=[])
        self.assertIn("skipped", rep, "空 alive 必须跳过，实际 %r" % rep)
        self.assertIn(ghosts[0], _r(self.rr), "空 alive 竟把派生文件清空了（严重数据事故）")
        self.assertIn(self.alive[0], _r(self.rc))

    def test_safety_valve_empty_index(self):
        """alive_ids=None 且索引为空/不可读 → skipped，不得当成空集合照常做差集。

        （不直接改名 index.db —— sqlite 连接持有句柄会 PermissionError；
        改用一个「有派生文件但没有索引」的根目录来构造同一条件。）"""
        ghosts = self._inject_ghosts()
        bare = tempfile.mkdtemp(prefix="keeper_prune_bare_")
        try:
            os.makedirs(os.path.join(bare, "store"), exist_ok=True)
            rr = os.path.join(bare, "store", "route_registry.json")
            _w(rr, {g: ["L3"] for g in ghosts})
            rep = M.prune_derived(bare)  # alive_ids=None + 无索引
            self.assertTrue(("skipped" in rep) or (rep.get("dropped_total") == 0),
                            "无索引时不得误删派生键：%r" % rep)
            self.assertIn(ghosts[0], _r(rr), "无索引竟清空了派生文件")
        finally:
            shutil.rmtree(bare, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
