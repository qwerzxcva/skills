# -*- coding: utf-8 -*-
"""keeper_sync.py 落盘前硬拦截（fail-closed）回归测试。

背景：跨设备同步的 5 个坑原先只有 4 条是「文档说强制、代码只 warn」——
  - `--no-keep-ids` 会让库 19→38→57 膨胀，却只红字警告不拦；
  - 同步包丢了 `.meta.json` 时**根本不会做** sha256 校验，却一声不响直接导入；
  - 导入有失败 / 幂等校验不通过，也照样 rc=0（看起来成功了）。

本文件把「默认拒绝 + 显式逃生 flag 才放行」这条设计锁死，防止以后被改回软提示。
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)          # scripts/
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import memory_ops as mo  # noqa: E402
import keeper_sync as ks  # noqa: E402


def _n(root):
    try:
        return len(list(mo._iter_all_mems(root)))
    except Exception:  # noqa: BLE001
        return 0


class TestKeeperSyncGates(unittest.TestCase):
    """落盘前闸门：默认拒绝，逃生 flag 才放行。"""

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp(prefix="keeper_syncgate_")
        cls.A = os.path.join(cls.base, "A")
        cls.sync = os.path.join(cls.base, "sync")
        os.makedirs(cls.sync, exist_ok=True)
        for i in range(3):
            mo.deposit(cls.A, category="best_practice", tags=[],
                       summary="同步闸门测试条目 %d" % i,
                       body="用于验证 keeper_sync 落盘前硬拦截（第 %d 条）。" % i,
                       tier="working", mid="LRN-GATE-%03d" % i)
        mo.flush_memory_index(cls.A)
        cls.expect = _n(cls.A)
        if cls.expect == 0:
            raise unittest.SkipTest("源库存入失败，无法验证同步闸门")
        rc = ks.main(["out", "--dest", cls.sync, "--root", cls.A])
        if rc != 0:
            raise unittest.SkipTest("out 失败 rc=%s" % rc)
        cls.pkg = sorted(glob.glob(os.path.join(cls.sync, "keeper_sync_*.jsonl")))[-1]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _fresh_target(self, name):
        d = os.path.join(self.base, name)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        return d

    def _pkg_without_meta(self, name):
        """复制一份**没有** .meta.json 的包（模拟只拷了 jsonl 就导入）。

        刻意用「只把 jsonl 拷进干净目录」而不是「拷完再删 meta」——
        本环境删除类 API 会被安全策略拦截（os.remove 可能静默不生效），
        用构造法避开删除，测试才可信。
        """
        d = os.path.join(self.base, "nometa_" + name)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name + ".jsonl")
        shutil.copy(self.pkg, p)
        assert not os.path.exists(p[:-6] + ".meta.json"), "干净目录里不该有 meta"
        return p

    # ── G2 完整性闸门 ──
    def test_no_meta_execute_blocked(self):
        """缺 .meta.json 时 --execute 必须被拦（rc=7）且零写入。"""
        p = self._pkg_without_meta("nometa.jsonl")
        B = self._fresh_target("B_nometa")
        rc = ks.main(["in", "--file", p, "--root", B, "--execute", "--no-backup"])
        self.assertEqual(rc, 7, "缺 meta 应 rc=7 中止，实际 %s" % rc)
        self.assertEqual(_n(B), 0, "被拦下时不应写入任何数据")

    def test_no_meta_dryrun_not_blocked(self):
        """预演阶段不受拦截（否则看不到数字，无从判断）。"""
        p = self._pkg_without_meta("nometa_dry.jsonl")
        B = self._fresh_target("B_nometa_dry")
        rc = ks.main(["in", "--file", p, "--root", B])
        self.assertEqual(rc, 0, "dry-run 不应被完整性闸门拦下，实际 %s" % rc)
        self.assertEqual(_n(B), 0, "预演不应写入")

    def test_no_meta_escape_allows(self):
        """显式 --allow-unverified 才放行（逃生开关必须真的能用）。"""
        p = self._pkg_without_meta("nometa_ok.jsonl")
        B = self._fresh_target("B_nometa_ok")
        rc = ks.main(["in", "--file", p, "--root", B, "--execute",
                      "--no-backup", "--allow-unverified"])
        self.assertEqual(rc, 0, "逃生开关应放行，实际 rc=%s" % rc)
        self.assertEqual(_n(B), self.expect, "放行后条数应等于包内条数")

    # ── G1 keep_ids 闸门 ──
    def test_no_keep_ids_execute_blocked(self):
        """--no-keep-ids 在 --execute 时必须被拦（rc=8）且零写入。"""
        B = self._fresh_target("B_nokid")
        rc = ks.main(["in", "--file", self.pkg, "--root", B, "--execute",
                      "--no-backup", "--no-keep-ids"])
        self.assertEqual(rc, 8, "--no-keep-ids 应 rc=8 中止，实际 %s" % rc)
        self.assertEqual(_n(B), 0, "被拦下时不应写入任何数据")

    def test_no_keep_ids_escape_allows(self):
        """显式 --i-know-id-bloat 才放行（且不因逃生而被静默拦下）。"""
        B = self._fresh_target("B_nokid_ok")
        rc = ks.main(["in", "--file", self.pkg, "--root", B, "--execute",
                      "--no-backup", "--no-keep-ids", "--i-know-id-bloat"])
        self.assertNotEqual(rc, 8, "逃生开关应放行，不该再返回 rc=8")

    def test_normal_sync_still_works(self):
        """正常路径（有 meta + keep-ids）不受影响，rc=0 且条数正确。"""
        B = self._fresh_target("B_normal")
        rc = ks.main(["in", "--file", self.pkg, "--root", B, "--execute", "--no-backup"])
        self.assertEqual(rc, 0, "正常同步应 rc=0，实际 %s" % rc)
        self.assertEqual(_n(B), self.expect, "正常同步条数不符")

    def test_corrupted_package_still_rc2(self):
        """包损坏（有 meta 但 sha 不匹配）仍是 rc=2——旧行为不能被改坏。"""
        cor = os.path.join(self.sync, "corrupt.jsonl")
        with open(cor, "wb") as f:
            f.write(open(self.pkg, "rb").read() + b"x")
        shutil.copy(self.pkg[:-6] + ".meta.json", cor[:-6] + ".meta.json")
        B = self._fresh_target("B_corrupt")
        rc = ks.main(["in", "--file", cor, "--root", B, "--execute", "--no-backup"])
        self.assertEqual(rc, 2, "损坏包应 rc=2，实际 %s" % rc)
        self.assertEqual(_n(B), 0, "损坏包不应写入")


if __name__ == "__main__":
    unittest.main(verbosity=2)
