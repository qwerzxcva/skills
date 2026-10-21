# -*- coding: utf-8 -*-
"""backup --keep / backup_prune 契约回归（4.9.24）。

备份是灾难恢复的**最后一道**，所以这里的硬约束比别处更紧：

🔴 **只搬不删**：清理旧备份只能 `os.rename` 到同级 `_retired_backups_<日期>/`，
   任何情况下都不得硬删（红线 A2）。本测试同时断言「源已不在原位」与「目标确实存在」——
   只验其中一个，就可能把「删了」误判成「搬走了」。

其余锁：`keep` 含本次刚生成那份；`keep<1` 抬到 1；`protect` 指定的那份永不入选；
备份数量不超 `keep` 时完全不动。
"""
import datetime
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import memory_ops as M  # noqa: E402

PRUNE = M.backup_prune


class BackupPruneTest(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.mkdtemp(prefix="keeper_bp_")
        self.root = os.path.join(self.parent, "AI记忆")
        os.makedirs(self.root, exist_ok=True)
        self.zips = []
        for i in range(5):
            p = os.path.join(self.parent, "ai_memory_backup_2026090%d_120000.zip" % (i + 1))
            with open(p, "w", encoding="utf-8") as f:
                f.write("zip-payload-%d" % i)
            os.utime(p, (1700000000 + i * 100, 1700000000 + i * 100))
            self.zips.append(p)

    def _retired_dir(self):
        return os.path.join(self.parent,
                            "_retired_backups_%s" % datetime.date.today().isoformat())

    def test_keep_moves_older_ones_without_deleting(self):
        r = PRUNE(self.root, keep=2)
        self.assertTrue(r["ok"], msg=r)
        self.assertEqual(r["n_total"], 5)
        self.assertEqual(r["kept"], 2)
        self.assertEqual(len(r["retired"]), 3)
        # 最新两份留在原位
        for p in self.zips[3:]:
            self.assertTrue(os.path.exists(p), "最新两份必须留在原位：%s" % p)
        # 旧三份：既离开了原位，又**确实存在**于归档目录（只搬不删）
        for p in self.zips[:3]:
            self.assertFalse(os.path.exists(p), "旧备份仍留在原位：%s" % p)
            dst = os.path.join(r["retired_dir"], os.path.basename(p))
            self.assertTrue(os.path.exists(dst), "旧备份被删而非搬离：%s" % dst)
        self.assertEqual(os.path.basename(r["retired_dir"]),
                         os.path.basename(self._retired_dir()))

    def test_keep_not_exceeded_is_noop(self):
        r = PRUNE(self.root, keep=9)
        self.assertTrue(r["ok"])
        self.assertEqual(r["retired"], [])
        self.assertEqual(r["retired_dir"], "")
        for p in self.zips:
            self.assertTrue(os.path.exists(p))
        self.assertFalse(os.path.isdir(self._retired_dir()), "无事可做时不该建归档目录")

    def test_keep_zero_is_clamped_to_one(self):
        r = PRUNE(self.root, keep=0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["kept"], 1)
        self.assertEqual(len(r["retired"]), 4)
        self.assertTrue(os.path.exists(self.zips[-1]))

    def test_protect_entry_never_retired(self):
        """protect = 用户点名要留的那份（如「升级前的手工基线」）。"""
        oldest = self.zips[0]
        r = PRUNE(self.root, keep=1, protect=oldest)
        self.assertTrue(r["ok"])
        self.assertNotIn(os.path.basename(oldest), r["retired"])
        self.assertTrue(os.path.exists(oldest), "被 protect 的备份不得动")
        self.assertEqual(len(r["retired"]), 3)   # 5 份 - 留 1 - protect 1 = 3

    def test_only_files_with_backup_prefix_are_considered(self):
        """收窄范围：别目录里的同名 zip、其它前缀一律不参与（防误扫误搬）。"""
        stray = os.path.join(self.parent, "someone_else_backup.zip")
        with open(stray, "w", encoding="utf-8") as f:
            f.write("not mine")
        r = PRUNE(self.root, keep=1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["n_total"], 5)
        self.assertTrue(os.path.exists(stray))

    def test_repeat_run_is_idempotent(self):
        PRUNE(self.root, keep=2)
        r2 = PRUNE(self.root, keep=2)
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["n_total"], 2, "已搬离的不该再被算进来")
        self.assertEqual(r2["retired"], [])


if __name__ == "__main__":
    unittest.main()
