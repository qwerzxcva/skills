# -*- coding: utf-8 -*-
"""门禁临时目录回收的回归测试（4.9.25 · 磁盘卫生）。

对应 scripts/run_gate.py 的 `_cleanup_temp_residue`：门禁跑前清超龄残留、跑完清本轮
产生的临时目录。这个功能的**风险点全在「清错东西」**上——所以每个「必须保留」的情形
都配了负向对照，避免实现退化成「无脑清空 TEMP」还能一路全绿。

判据全程注入隔离沙箱（base=自建目录），不碰宿主真实 TEMP。
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import run_gate  # noqa: E402


def _mk(base, name, age_seconds=0.0, files=1):
    """在 base 下建名为 name 的目录；age_seconds>0 表示「把 mtime 拨到那么久以前」。"""
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    members = [path]
    for i in range(files):
        fp = os.path.join(path, "f%d.txt" % i)
        with open(fp, "w", encoding="utf-8") as f:
            f.write("x" * 64)
        members.append(fp)
    if age_seconds:
        ts = time.time() - age_seconds
        for m in members:
            os.utime(m, (ts, ts))
    return path


class TempResidueCleanupTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="gate_tmpclean_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    # ---- 该清的：两档判定各一条 ----------------------------------------
    def test_stale_residue_is_removed(self):
        """档②：超龄（早于 stale_age）的残留必须回收。"""
        victim = _mk(self.base, "keeper_old_sandbox", age_seconds=7 * 3600)
        removed, freed = run_gate._cleanup_temp_residue(
            time.time(), stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 1)
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(victim), "超龄残留必须被清掉")

    def test_fresh_since_start_is_removed(self):
        """档①：本轮运行期间新建的（mtime >= since_ts）必须回收。"""
        victim = _mk(self.base, "keeper_fresh_sandbox")
        removed, _freed = run_gate._cleanup_temp_residue(
            time.time() - 5, stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(victim), "本轮新建的必须被清掉")

    def test_plain_prefix_is_in_whitelist(self):
        """白名单要真的覆盖 plain_*（否则该族残留永远清不掉）。"""
        victim = _mk(self.base, "plain_dep_abc", age_seconds=7 * 3600)
        removed, _freed = run_gate._cleanup_temp_residue(
            time.time(), stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(victim))

    # ---- 必须保留的：三条防恒绿负向对照 --------------------------------
    def test_foreign_prefix_is_kept(self):
        """🔴 非本技能前缀的目录一律不动——回归到「无脑清 TEMP」就会红。"""
        keep = _mk(self.base, "some_other_tool_cache", age_seconds=30 * 24 * 3600)
        removed, _freed = run_gate._cleanup_temp_residue(
            time.time(), stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.exists(keep), "非白名单前缀必须保留")

    def test_pinned_shared_sandbox_is_kept(self):
        """🔴 固定共享沙箱（keeper_gate_hooks / keeper_gate_daemon）永不回收。"""
        # 🔴 名字**硬编码**，不从 run_gate._TEMP_PINNED 读：若读实现的集合，
        # 一旦有人把该集合清空，本用例会退化成「建 0 个目录 → 断言 0 个被删」而恒绿。
        kept = [_mk(self.base, nm, age_seconds=30 * 24 * 3600)
                for nm in ("keeper_gate_hooks", "keeper_gate_daemon")]
        removed, _freed = run_gate._cleanup_temp_residue(
            time.time(), stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 0)
        for p in kept:
            self.assertTrue(os.path.exists(p), "固定共享沙箱必须保留: %s" % p)

    def test_fresh_but_older_than_start_is_kept(self):
        """🔴 跑前那档：新目录但 mtime 早于本次启动 → 属并发进程，必须保留。"""
        keep = _mk(self.base, "keeper_concurrent_sandbox", age_seconds=60)
        removed, _freed = run_gate._cleanup_temp_residue(
            time.time(), stale_age=6 * 3600, base=self.base)
        self.assertEqual(removed, 0)
        self.assertTrue(os.path.exists(keep),
                        "早于本次启动的新目录属并发进程，不得回收")


class BusyHandleCleanupTest(unittest.TestCase):
    """🔴 句柄占用场景（2026-09-16 实锤根因的回归锁）。

    背景：memory_ops 的 per-root 连接池只在 **atexit** 关闭，早于门禁的回收
    ⇒ 沙箱里的 `store/index.db` 仍被本进程持有 ⇒ Windows 抛共享冲突拒绝删除
    ⇒ 原实现 `rmtree(ignore_errors=True)` 把「删不掉」和「没东西可删」混为一谈。
    证据：三轮全量门禁（399/409/415 用例）回收数恒为 **99 个 / 0.7MB**，
    用例数变了、"99" 不动；单跑 test_md_roundtrip 新建 1 个含 index.db 的沙箱、
    跑完回收 **0** 个，而进程退出 14.7s 后同一目录 rmtree 一次成功。

    本组用例把「删不掉必须被如实计数」钉死——否则又会退化成静默漏网。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="gate_tmpclean_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base, ignore_errors=True)

    def _sqlite_probe(self, name):
        """在 base 下建一个目录并用 sqlite3 连接持有它，返回 (path, conn)。

        🔴 **为什么不能用 `open()` 模拟**（2026-09-16 实测踩到）：CPython 在 Windows
        上打开文件时共享模式含 `FILE_SHARE_DELETE`，被 `open()` 持有的文件**照样能删**
        （用 open 写的第一版用例实测 `removed == 1`，断言直接失败）。而 sqlite3 的
        文件句柄不含 DELETE 共享位 ⇒ 拒绝删除 —— **这才是门禁沙箱删不掉的真实机制**
        （沙箱里躺着的是 `store/index.db`）。
        """
        import sqlite3
        path = os.path.join(self.base, name)
        os.makedirs(path, exist_ok=True)
        conn = sqlite3.connect(os.path.join(path, "index.db"))
        conn.execute("CREATE TABLE IF NOT EXISTS t(x)")
        conn.commit()
        return path, conn

    def test_pool_held_sandbox_is_reclaimed(self):
        """🔴 复现真实根因并验证修复：memory_ops 连接池持有的沙箱必须能回收。

        这是本次修复的**主验证**——修复前此用例必红（连接池只在 atexit 关闭，
        回收发生在它之前 ⇒ index.db 句柄仍在 ⇒ 删不掉），修复后必绿。
        """
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        try:
            import memory_ops as mo
        except Exception as e:  # noqa: BLE001
            self.skipTest("memory_ops 不可导入，跳过：%s" % e)
        victim = os.path.join(self.base, "keeper_pool_sandbox")
        try:
            mo.init_store(victim)          # 建出 store/index.db
        except Exception as e:  # noqa: BLE001
            self.skipTest("init_store 不可用，跳过：%s" % e)
        _conn_fn = getattr(mo, "_db_conn", None)
        if not callable(_conn_fn):
            _conn_fn = getattr(getattr(mo, "_persistence_mod", None), "_db_conn", None)
        if not callable(_conn_fn):
            self.skipTest("拿不到 _db_conn，无法复现连接池占用")
        _conn_fn(victim)                    # 主动入池且**不关闭**
        removed, _freed, failed = run_gate._cleanup_temp_residue(
            time.time() - 5, stale_age=6 * 3600, base=self.base, with_stats=True)
        self.assertEqual(
            removed, 1,
            "连接池持有的沙箱必须被回收 —— 回收前必须先释放 sqlite 句柄")
        self.assertEqual(failed, 0)
        self.assertFalse(os.path.exists(victim))

    def test_sqlite_held_dir_is_counted_not_silently_swallowed(self):
        """池外连接（模拟子进程/未知持有者）：允许删不掉，但**必须**计入 failed。"""
        path, conn = self._sqlite_probe("keeper_busy_sandbox")
        try:
            removed, _freed, failed = run_gate._cleanup_temp_residue(
                time.time() - 5, stale_age=6 * 3600, base=self.base, with_stats=True)
            if removed == 1:
                self.skipTest("本平台 sqlite 句柄不阻止删除，无法模拟占用场景")
            self.assertEqual(removed, 0)
            self.assertGreaterEqual(
                failed, 1, "删不掉的目录必须计入 failed —— 静默吞掉正是残渣累积根因")
            self.assertTrue(os.path.exists(path))
        finally:
            conn.close()

    def test_released_dir_is_reclaimed_with_zero_failed(self):
        """占用解除后：同一目录必须被回收成功、failed 归零。"""
        victim = _mk(self.base, "keeper_released_sandbox")
        fh = open(os.path.join(victim, "f0.txt"), "r+", encoding="utf-8")
        fh.close()
        removed, freed, failed = run_gate._cleanup_temp_residue(
            time.time() - 5, stale_age=6 * 3600, base=self.base, with_stats=True)
        self.assertEqual(removed, 1)
        self.assertEqual(failed, 0)
        self.assertGreater(freed, 0)
        self.assertFalse(os.path.exists(victim))

    def test_with_stats_defaults_to_two_tuple(self):
        """向后兼容：不传 with_stats 仍返回二元组（旧调用点不破）。"""
        _mk(self.base, "keeper_compat_sandbox")
        r = run_gate._cleanup_temp_residue(
            time.time() - 5, stale_age=6 * 3600, base=self.base)
        self.assertEqual(len(r), 2)

    def test_handles_released_before_delete(self):
        """🔴 删除前必须真的调过句柄释放（这是根因修复的关键一步）。

        静态锁：若有人把 `_release_db_handles()` 从清理路径里摘掉，
        本用例必须红——它是「修好了」与「看着像修好了」的分界线。
        """
        with open(os.path.join(SCRIPTS, "run_gate.py"), encoding="utf-8") as _f:
            src = _f.read()
        i = src.index("def _cleanup_temp_residue")
        body = src[i:]
        body = body[:body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
        self.assertIn("_release_db_handles()", body,
                      "回收路径必须主动释放 sqlite 句柄，否则 Windows 上删不掉沙箱")
        self.assertIn("_db_close_all", src,
                      "必须复用 memory_ops 既有的连接池关闭入口")

    def test_failed_count_is_surfaced_by_gate(self):
        """🔴 失败数必须被打印出来（不能只算不说）。

        这个 bug 能潜伏多轮，正是因为日志里「99 个」看起来一切正常。
        """
        with open(os.path.join(SCRIPTS, "run_gate.py"), encoding="utf-8") as _f:
            src = _f.read()
        self.assertIn("with_stats=True", src)
        self.assertEqual(src.count("_n, _freed, _failed = _cleanup_temp_residue"), 2,
                         "跑前与跑后的回收都要拿到失败数")
        self.assertGreaterEqual(src.count("未能回收"), 2,
                                "跑前/跑后各要有一句失败可见的提示")


class KeepTempFlagTest(unittest.TestCase):
    def test_keep_temp_flag_declared(self):
        """--keep-temp 必须在门禁 CLI 里真实可解析（否则文档承诺的逃生口不存在）。"""
        import argparse
        with open(os.path.join(SCRIPTS, "run_gate.py"), encoding="utf-8") as _f:
            src = _f.read()
        self.assertIn('"--keep-temp"', src)
        self.assertIn("args.keep_temp", src)
        # 两个清理调用点都必须被 keep_temp 守住（跑前 / 跑后各一）
        self.assertEqual(src.count("if not args.keep_temp:"), 2,
                         "跑前与跑后的回收都必须受 --keep-temp 约束")
        self.assertTrue(callable(run_gate._cleanup_temp_residue))
        self.assertIsInstance(argparse.ArgumentParser, type)


if __name__ == "__main__":
    unittest.main()
