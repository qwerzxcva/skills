# -*- coding: utf-8 -*-
"""
test_save_mem_index_sync.py — 锁定「_save_mem 写文件即自动同步索引」（根治 claim B 双写漂移）。

核心断言：
- 任何调用方只调 _save_mem（不再显式 save_index/_sync_index），索引（entries 镜像 + inverted
  倒排）也会自动更新；recall 的 --status / --subdomain / --tag 硬过滤因此不再静默漂移。
- 这是「存储一致性收口」的回归锁：防止未来新增 _save_mem 调用点再次遗漏索引同步。
"""
import os
import sys
import shutil
import tempfile
import unittest

# v4.9.1：补 sys.path 引导（与同目录其它用例一致）。此前只有
# `unittest discover` 模式能跑（靠 discover 注入 scripts/ 路径），
# 直接 `python scripts/tests/本文件.py` 会 ModuleNotFoundError:
# No module named 'memory_ops'，容易被误判成代码坏了。
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (SKILL, os.path.join(SKILL, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import memory_ops as M  # noqa: E402


def _deposit_active(root, mid, **kw):
    M.deposit(root, summary=kw.get("summary", "测试记忆 %s" % mid),
              body=kw.get("body", ""), tags=kw.get("tags", ["tag_%s" % mid]),
              subdomain=kw.get("subdomain"), category=kw.get("category", "learning"),
              mid=mid)


class SaveMemIndexSyncTest(unittest.TestCase):

    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_sm_sync_")
        M.init_store(self.store)
        # 预置一条活跃记忆（deposit 已内部走 _save_mem 收口）
        _deposit_active(self.store, "m1", tags=["python"], subdomain="db")

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def test_flush_does_not_resurrect_deleted_root(self):
        """🔴 幽灵目录锁：flush 不得重建「已删除」的 root。

        真实场景：本类 tearDown 先 `rmtree(store)`，而召回缓存是**延迟合并写**
        （`_PENDING_DISK` 登记、atexit 才落盘）⇒ 旧实现会在落盘时 `makedirs`
        把已删目录**重新建出来**。2026-09-16 实测：门禁每轮为此多留 3 个
        `keeper_sm_sync_*` 空壳（内容只有 `store/.recall_cache.db`），且它们出现在
        主进程退出之后 —— 属「删后又被重建」型残留（本项目的老坑型态）。
        """
        # 先产生待落盘 key（recall 会写进程内缓存并登记脏 key）
        M.recall(self.store, query="测试", include_auto=False)
        _mod = getattr(M, "_recall_cache_mod", None)
        _pend = getattr(_mod, "_PENDING_DISK", None)
        if not _pend:
            self.skipTest("本路径未产生待落盘 key，无法覆盖复活场景（跳过可见）")
        # 🔴 先释放本进程持有的 sqlite 句柄，否则 Windows 上 rmtree 会**静默失败**
        #（`ignore_errors=True` 把它藏起来）——这正是门禁残渣的第一因，见
        # run_gate._release_db_handles 的证据链；本用例要测的是**第二因**（flush
        # 把已删目录重建回来），所以必须先把第一因排干净，否则前置断言就不成立。
        _persist = getattr(M, "_persistence_mod", None)
        _close = getattr(_persist, "_db_close_all", None)
        if callable(_close):
            _close()
        shutil.rmtree(self.store, ignore_errors=True)
        self.assertFalse(os.path.exists(self.store),
                         "前置：目录必须真的被删掉（句柄已释放）")
        M._recall_cache_flush()                            # 手动触发落盘点
        self.assertFalse(
            os.path.exists(self.store),
            "flush 不得复活已删除的 root —— 会留下幽灵目录")

    def test_save_mem_auto_syncs_status_filter(self):
        # 只调 _save_mem（不手动 save_index）把 status 改为 archived
        m, _ = M._load_mem(self.store, "m1")
        m["status"] = "archived"
        M._save_mem(self.store, "m1", m)
        M._recall_cache_clear(self.store)
        # recall 默认只返回 active —— 已归档应自动被过滤（不再漏过滤）
        res = M.recall(self.store, query="测试", include_auto=False)
        ent = res if isinstance(res, list) else res.get("entries", [])
        ids = [e.get("id") for e in ent]
        self.assertNotIn("m1", ids, "只调 _save_mem 改 status 后，索引应自动同步，归档记忆不应被召回")

    def test_save_mem_auto_syncs_subdomain_filter(self):
        m, _ = M._load_mem(self.store, "m1")
        m["subdomain"] = "cache"
        M._save_mem(self.store, "m1", m)
        M._recall_cache_clear(self.store)
        # --subdomain cache 应命中（索引自动同步了 subdomain）
        res = M.recall(self.store, query="测试", subdomain="cache", include_auto=False)
        ent = res if isinstance(res, list) else res.get("entries", [])
        ids = [e.get("id") for e in ent]
        self.assertIn("m1", ids, "只调 _save_mem 改 subdomain 后，索引应自动同步，--subdomain 应命中")

    def test_save_mem_auto_syncs_tag_inverted(self):
        m, _ = M._load_mem(self.store, "m1")
        m["tags"] = ["newtag"]
        M._save_mem(self.store, "m1", m)
        M._recall_cache_clear(self.store)
        # 纯 --tag 路径走 inverted 倒排表，应自动同步命中
        res = M.recall(self.store, query="测试", tag="newtag", include_auto=False)
        ent = res if isinstance(res, list) else res.get("entries", [])
        ids = [e.get("id") for e in ent]
        self.assertIn("m1", ids, "只调 _save_mem 改 tags 后，inverted 倒排应自动同步，--tag 应命中")


if __name__ == "__main__":
    unittest.main()
