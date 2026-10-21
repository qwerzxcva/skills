# -*- coding: utf-8 -*-
"""test_sched_probe.py — 锁定 doctor 调度自检的「降噪缓存 + 可诊断提示」（4.9.13）。

背景：
    本机 `schtasks.exe` 被安全中心的「程序黑名单」拦（不可绕过）。改前
    `_check_scheduler_status()` **每次** doctor 都会白撞一次，且失败提示写死为
    「(无法查询) / schtasks 不可用」——分不清「根本没有这个程序」还是「有但被策略拦」，
    使用者只会以为是 keeper 自己的毛病。

修复（4.9.13）：
    1) 探测结果缓存 24h（落在部署目录 `.keeper_sched_probe.json`，**不随包分发**）；
    2) 提示带成因分类 + 原始异常；🔴 成因按可能性列候选，不把单机经验当通用结论；
    3) 顺带修掉 `/NH`（不出表头）与 `splitlines()[1:]`（跳过首行）的矛盾——那会
       **漏掉第一条** keeper 任务；
    4) 补 `--no-cache` 强制重探 + 缓存命中自曝年龄与逃生口（修「改了限制却看不到变化」）。

核心断言：
    A. 缓存往返可读；过期 → 视为未缓存（必须重新探测，不得漏检）；
    B. 缓存损坏 / 无路径 → 一律退化为「直接探测」，不抛异常；
    C. 🔴 缓存读写在任何异常下都必须 fail-open（缓存只降噪，不承担正确性）；
    D. 提示能区分「PATH 里没有该程序」与「有但调用被拒」，且始终带上原始错误；
       🔴 且**不得把单机经验写成通用结论**——同一错误码有多种成因，须按可能性列候选；
    E. 🔴 只对负向结果短路（可用时每次都实查，否则新装任务会被缓存永久掩盖）；
       缓存命中须自曝年龄 + 给出 --no-cache 逃生口，且该提示只拼在展示层、不写回缓存；
    F. --no-cache 必须真的接进解析器（可被 doctor --help 看到）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
sys.path.insert(0, HERE)
import memory_ops as M  # noqa: E402

DOC = M._doctor_mod  # 零 import 模块：符号由包在加载时注入 globals
MEM_OPS = os.path.join(HERE, "memory_ops.py")


class SchedProbeCacheTest(unittest.TestCase):
    """A–C：缓存的读写、过期与 fail-open。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_schedprobe_")
        self._old = os.environ.get("KEEPER_HOOKS_DIR")
        # _sched_probe_path() 走 _hooks_deploy_dir()，而后者读该 env → 天然可隔离
        os.environ["KEEPER_HOOKS_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("KEEPER_HOOKS_DIR", None)
        else:
            os.environ["KEEPER_HOOKS_DIR"] = self._old
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass

    def test_path_follows_deploy_dir(self):
        self.assertEqual(os.path.normcase(DOC._sched_probe_path()),
                         os.path.normcase(os.path.join(self.tmp, ".keeper_sched_probe.json")),
                         "缓存必须落在部署目录（可被 KEEPER_HOOKS_DIR 隔离），不写源码树")

    def test_write_then_read_roundtrip(self):
        DOC._sched_probe_write({"available": False, "note": "被策略拦"})
        got = DOC._sched_probe_read()
        self.assertIsNotNone(got, "刚写入的缓存必须可读")
        self.assertFalse(got["available"])
        self.assertIn("checked_at", got, "必须记录时间戳，否则无从判断过期")

    def test_expired_cache_returns_none(self):
        DOC._sched_probe_write({"available": False, "note": "旧"})
        p = DOC._sched_probe_path()
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["checked_at"] = time.time() - DOC._SCHED_PROBE_TTL - 60  # 过期
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
        self.assertIsNone(DOC._sched_probe_read(),
                          "过期缓存必须返回 None → 强制重新探测（否则永久误报不可用）")

    def test_corrupt_cache_fail_open(self):
        with open(DOC._sched_probe_path(), "w", encoding="utf-8") as f:
            f.write("{ 这不是 JSON")
        self.assertIsNone(DOC._sched_probe_read(), "损坏缓存必须 fail-open，不得抛异常")

    def test_write_failure_is_swallowed(self):
        """写不进去（如路径被同名文件占住）也不得抛——缓存只降级为「无缓存」。"""
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("占位")
        # 把 hooks 目录指到「一个文件」底下 → makedirs/写文件必然失败
        os.environ["KEEPER_HOOKS_DIR"] = os.path.join(blocker, "sub")
        try:
            DOC._sched_probe_write({"available": False, "note": "x"})
        except Exception as e:  # noqa: BLE001
            self.fail("写缓存失败必须被吞掉，实际抛出 %s: %s" % (type(e).__name__, e))
        self.assertIsNone(DOC._sched_probe_read(), "不可写时应等效于「无缓存」")


class SchedDiagTest(unittest.TestCase):
    """D：成因分类。"""

    def test_blocked_mentions_policy_and_path(self):
        msg = DOC._sched_diag(PermissionError("[WinError 5] 拒绝访问"))
        self.assertIn("PermissionError", msg, "必须带原始异常类型，否则无从定位")
        self.assertIn("程序黑名单", msg, "被拦时必须点明成因与解除入口")

    def test_missing_binary_branch(self):
        with mock.patch("shutil.which", return_value=None):
            msg = DOC._sched_diag(FileNotFoundError("no such file"))
        self.assertIn("PATH", msg, "找不到程序时须报 PATH，而不是笼统的「不可用」")
        self.assertNotIn("程序黑名单", msg, "两种成因不得混为一谈")

    def test_always_carries_original_error(self):
        with mock.patch("shutil.which", return_value=None):
            msg = DOC._sched_diag(OSError("boom-detail"))
        self.assertIn("boom-detail", msg, "原始错误原文必须透出（4.9.11 零 import 教训）")

    def test_blocked_lists_candidates_not_single_verdict(self):
        """🔴 不得把「本机经验」当通用结论：同一错误码（WinError 5）不止黑名单一种成因。

        旧实现直接断言「本机安全中心的程序黑名单会拦它」——对本机成立，但换一台机器
        可能是权限不足 / 组策略 / 组件损坏，会让人去改一个跟自己无关的设置。
        """
        msg = DOC._sched_diag(PermissionError("[WinError 5] 拒绝访问"))
        self.assertIn("①", msg, "必须按可能性列出候选成因")
        self.assertIn("②", msg, "只给一条会让人改错地方")
        self.assertNotIn("会拦它", msg, "不得把单一成因写成定论")

    def test_blocked_tells_user_it_does_not_break_function(self):
        """成因不确定时，至少要让使用者知道「这项不修也不影响功能」，避免白折腾。"""
        msg = DOC._sched_diag(PermissionError("[WinError 5] 拒绝访问"))
        self.assertIn("不依赖", msg, "须说明 keeper 定时维护不依赖 schtasks")


class SchedNoCacheTest(unittest.TestCase):
    """E：--no-cache 必须绕过负向缓存；缓存命中必须自曝年龄 + 给出逃生口。

    背景：加了 24h 降噪缓存后，使用者解除系统限制再跑 doctor，会看到 24h 前的旧结论，
    容易误判「我的修改没生效」。故：① 提供强制重探开关；② 缓存命中时把「这是旧结论」
    和「怎么强制重探」直接写进提示。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_schednc_")
        self._old = os.environ.get("KEEPER_HOOKS_DIR")
        os.environ["KEEPER_HOOKS_DIR"] = self.tmp
        # 预置一条「不可用」负向缓存：默认调用会命中它
        DOC._sched_probe_write({"available": False, "note": "旧的被拦结论"})

    def tearDown(self):
        if self._old is None:
            os.environ.pop("KEEPER_HOOKS_DIR", None)
        else:
            os.environ["KEEPER_HOOKS_DIR"] = self._old
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 走 schtasks 分支")
    def test_negative_cache_short_circuits_by_default(self):
        """对照：默认命中负向缓存 → 直接返回，不碰 schtasks（这才是降噪的本意）。"""
        with mock.patch("subprocess.check_output",
                        side_effect=AssertionError("命中缓存时不该真探测")) as m:
            r = DOC._check_scheduler_status()
        self.assertFalse(m.called, "默认应复用缓存，不该白撞一次 schtasks")
        self.assertEqual(r["tasks"][0]["name"], "(不可用)")
        self.assertTrue(r["tasks"][0].get("cached"))

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 走 schtasks 分支")
    def test_no_cache_probes_even_with_negative_cache(self):
        """no_cache=True：缓存里有旧结论也必须实探，否则「解除限制后看不到变化」。"""
        out = b'"keeper-nightly","N/A","Ready","Ready"\r\n'
        with mock.patch("subprocess.check_output", return_value=out) as m:
            r = DOC._check_scheduler_status(no_cache=True)
        self.assertTrue(m.called, "no_cache=True 必须真的调用 schtasks")
        self.assertEqual(r["tasks"][0]["name"], "keeper-nightly",
                         "必须返回真实探测结果，而不是缓存的「不可用」")
        self.assertNotIn("cached", r["tasks"][0], "实探结果不得标为缓存")

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 走 schtasks 分支")
    def test_no_cache_skips_cache_read(self):
        """语义是「连读都不读」——读缓存本身已无意义，还多一个失败点。"""
        with mock.patch.object(DOC, "_sched_probe_read",
                               side_effect=AssertionError("no_cache 时不得读缓存")):
            with mock.patch("subprocess.check_output",
                            return_value=b'"keeper-x","N/A","Ready","Ready"\r\n'):
                DOC._check_scheduler_status(no_cache=True)

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 走 schtasks 分支")
    def test_cached_note_discloses_age_and_escape(self):
        """缓存命中必须自曝「这是多久前的结论」并给出强制重探法。"""
        r = DOC._check_scheduler_status()
        note = r["tasks"][0]["note"]
        self.assertIn("的探测缓存", note, "必须说明这是旧结论，否则会被当成实时结果")
        self.assertIn("--no-cache", note, "必须给出强制重探法，否则使用者只能等 24h")

    @unittest.skipUnless(sys.platform == "win32", "仅 Windows 走 schtasks 分支")
    def test_age_hint_not_written_back_to_cache(self):
        """年龄提示只拼在展示层——写回缓存会让尾巴「每读一次滚一圈」。"""
        DOC._check_scheduler_status()
        got = DOC._sched_probe_read()
        self.assertNotIn("的探测缓存", got.get("note") or "",
                         "缓存原文不得被展示层污染（否则提示会自我叠加）")


class CliWiringTest(unittest.TestCase):
    """F：参数必须真的接进解析器，而不是只写在帮助文本里。"""

    def test_cli_exposes_no_cache(self):
        r = subprocess.run([sys.executable, MEM_OPS, "doctor", "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        blob = (r.stdout or "") + (r.stderr or "")
        self.assertIn("--no-cache", blob,
                      "doctor --help 里必须能看到 --no-cache（否则参数没接上）")


if __name__ == "__main__":
    unittest.main()
