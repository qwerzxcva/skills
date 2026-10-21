# -*- coding: utf-8 -*-
"""同步测试「复制真库的范围」护栏（4.9.25）。

## 为什么需要这条

`test_sync_roundtrip` 曾直接 `copytree(真库)`，导致用例耗时**线性绑定真库体量**：
  · 历史归档（`_retired_tmp_*` / `memories_bak_*` / `quarantine/`）与同步无关却整锅复制；
  · `store/index.db`（真库 41MB）是召回加速镜像，而同步走的是**文件层**
    （`export_memories → _iter_all_mems`）；
  · 逐条全流程往返：真库 196 条 × 多轮 × 每条 0.1~3s。

修法：`_copy_ignore()` 回调排除上述内容，`memories` 根目录只留最近 N 条
（`AI_MEM_SYNC_TEST_MAX`，默认 60）。

## 本测试守什么

用**合成的假真库**（不依赖用户真库）验证裁剪范围，逐项正反断言：
  排除 → `_retired_tmp_*` / `memories_bak_*` / `quarantine` / `.workbuddy` / `__pycache__`
         / 未入选的 `memories/*.json` / `store/index.db*`
  保留 → `memories/archive/`（状态收敛要用）、`store/` 下的其它文件、入选的 memories
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def _load_sync_test_mod():
    """按路径加载同目录的 test_sync_roundtrip.py（只取它的裁剪辅助，不跑其用例）。"""
    spec = importlib.util.spec_from_file_location(
        "_tsr_for_scope_test", os.path.join(_HERE, "test_sync_roundtrip.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSyncCopyScope(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tsr = _load_sync_test_mod()

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="keeper_sync_scope_")
        self.real = os.path.join(self.base, "real_lib")
        mem = os.path.join(self.real, "memories")
        store = os.path.join(self.real, "store")
        os.makedirs(os.path.join(mem, "archive"))
        os.makedirs(store)
        # 5 条根目录记忆（只保留 2 条）
        for i in range(1, 6):
            with open(os.path.join(mem, "LRN-2026010%d-001.json" % i), "w",
                      encoding="utf-8") as f:
                f.write("{}")
        # archive 里的必须**全保留**（状态收敛要覆盖它）
        for i in range(1, 3):
            with open(os.path.join(mem, "archive", "LRN-2025-ARCH-%02d.json" % i), "w",
                      encoding="utf-8") as f:
                f.write("{}")
        # store：index.db* 应排除，其它文件保留
        for n in ("index.db", "index.db-wal", "index.db-shm", "config.json"):
            with open(os.path.join(store, n), "w", encoding="utf-8") as f:
                f.write("x")
        # 无关归档目录：应全部排除
        for d in ("_retired_tmp_20260909", "memories_bak_20260831_告警验证",
                  "quarantine", ".workbuddy", "__pycache__"):
            os.makedirs(os.path.join(self.real, d))
            with open(os.path.join(self.real, d, "junk.txt"), "w",
                      encoding="utf-8") as f:
                f.write("x")
        self.keep = {"LRN-20260103-001.json", "LRN-20260105-001.json"}
        self.dst = os.path.join(self.base, "copy")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _copy(self):
        shutil.copytree(self.real, self.dst,
                        ignore=self.tsr._copy_ignore(self.real, self.keep))
        return self.dst

    # ── 正向：该保留的保留了 ────────────────────────────────────────────
    def test_kept_memories_are_copied(self):
        d = self._copy()
        root_jsons = sorted(f for f in os.listdir(os.path.join(d, "memories"))
                            if f.endswith(".json"))
        self.assertEqual(root_jsons, sorted(self.keep))

    def test_archive_is_fully_kept(self):
        d = self._copy()
        arch = os.path.join(d, "memories", "archive")
        self.assertTrue(os.path.isdir(arch), "archive/ 必须保留（状态收敛依赖它）")
        self.assertEqual(len(os.listdir(arch)), 2)

    def test_other_store_files_are_kept(self):
        d = self._copy()
        self.assertTrue(os.path.exists(os.path.join(d, "store", "config.json")))

    # ── 负向：该排除的排除了 ────────────────────────────────────────────
    def test_index_db_is_excluded(self):
        d = self._copy()
        store = os.listdir(os.path.join(d, "store"))
        self.assertFalse([f for f in store if f.startswith("index.db")],
                         "index.db* 应排除（A 机只作同步源，DB 与裁剪后文件层不一致）")

    def test_unselected_memories_are_excluded(self):
        d = self._copy()
        root_jsons = set(os.listdir(os.path.join(d, "memories")))
        self.assertFalse(root_jsons & {"LRN-20260101-001.json", "LRN-20260102-001.json",
                                       "LRN-20260104-001.json"},
                         "未入选的 memories 不应被复制")

    def test_irrelevant_archives_are_excluded(self):
        d = self._copy()
        present = set(os.listdir(d))
        for n in ("_retired_tmp_20260909", "memories_bak_20260831_告警验证",
                  "quarantine", ".workbuddy", "__pycache__"):
            self.assertNotIn(n, present, "无关目录 %s 不应被复制" % n)

    # ── 边界：keep 为空（全排除）与全保留 ───────────────────────────────
    def test_empty_keep_excludes_all_root_memories(self):
        self.dst = os.path.join(self.base, "copy_empty")
        shutil.copytree(self.real, self.dst,
                        ignore=self.tsr._copy_ignore(self.real, set()))
        left = [f for f in os.listdir(os.path.join(self.dst, "memories"))
                if f.endswith(".json")]
        self.assertEqual(left, [], "空 keep 时根目录不应有 json")
        self.assertTrue(os.path.isdir(os.path.join(self.dst, "memories", "archive")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
