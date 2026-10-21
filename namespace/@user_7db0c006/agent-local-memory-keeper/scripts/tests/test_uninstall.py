# -*- coding: utf-8 -*-
"""keeper_setup.py uninstall 契约回归（4.9.24）。

卸载是**唯一会拆掉用户环境**的动作，所以本测试只锁两件事：

1. 🔴 **默认必须只预览**：不带 `--yes` 一律 dry-run；且输出里必须看得见
   「只读预览」与「不碰记忆库数据」这两句承诺（承诺不可见 = 用户不敢用/误用）。
2. 🔴 **持久化 env 只在显式 `--purge-env` 时才清**：默认必须原样保留——env
   是「库位置 / IMA 知识库」的唯一指针，误清 = 工具下次找不到记忆。

   注：加密能力已于 2026-09-15 整体移除，因此原先的「加密库卸载安全门」
   （加密库 + 库外 keyfile 缺失 → 拒绝清 env）已随之下线，相关用例一并退役。

隔离手法：`action_uninstall` **进程内**调用（不在子进程里）——
`keeper_setup.py` 的 `PY` 由 `~/.workbuddy/binaries` 推导，重定向 HOME 会让它指不到解释器；
改为把 `subprocess.run` 打桩成空操作：既不动真实环境，又能观察真实的输出契约。
"""
import contextlib
import io
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import keeper_setup as K  # noqa: E402

SRC = os.path.join(SCRIPTS, "keeper_setup.py")


def _args(**kw):
    base = dict(dry_run=True, yes=False, purge_env=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _run_action(args):
    """跑一次 action_uninstall，返回 (rc, 输出文本)。子进程打桩，不触真实环境。"""
    if not (args.dry_run or not args.yes):
        raise AssertionError("本测试只允许走 dry-run 路径，不得触发真实卸载")
    buf = io.StringIO()
    fake_run = mock.Mock(return_value=types.SimpleNamespace(returncode=0))
    with mock.patch.object(K.subprocess, "run", fake_run), \
            contextlib.redirect_stdout(buf):
        rc = K.action_uninstall(args)
    return rc, buf.getvalue()


def _func_body(path, name):
    """取某顶层函数的源码片段（按行切，避免依赖行尾风格）。"""
    with io.open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("def %s(" % name))
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith("def ")), len(lines))
    return "\n".join(lines[i:j])


class UninstallSafetyTest(unittest.TestCase):
    def test_default_is_preview_and_promises_not_to_touch_data(self):
        rc, out = _run_action(_args())
        self.assertEqual(rc, 0)
        self.assertIn("只读预览", out)
        self.assertIn("不碰记忆库数据", out, "安全承诺必须在输出里看得见")
        self.assertIn("以上为预览", out)

    def test_execute_requires_explicit_yes(self):
        """执行开关的公式必须是「显式 --dry-run 或 未给 --yes」→ dry；防有人改成默认执行。"""
        body = _func_body(SRC, "action_uninstall")
        self.assertIn("args.dry_run", body)
        self.assertIn("args.yes", body)

    def test_preview_keeps_env_by_default(self):
        """默认预览不得清 env：env 是库位置 / IMA 的唯一指针，清了工具就找不到记忆。"""
        rc, out = _run_action(_args())
        self.assertEqual(rc, 0)
        self.assertNotIn("将移除持久化 env", out)

    def test_purge_env_preview_is_allowed_and_lists_names(self):
        """显式 --purge-env 时放行（不再有任何加密安全门），且逐条列出待清 env。"""
        rc, out = _run_action(_args(purge_env=True, dry_run=True))
        self.assertEqual(rc, 0)
        self.assertNotIn("拒绝", out)
        for n in K._KEEPER_ENV_NAMES:
            self.assertIn("将移除持久化 env：%s" % n, out)

    def test_all_declared_env_names_are_listed(self):
        """env 清单必须覆盖「库位置 / IMA」两类，且都出现在输出里。"""
        self.assertEqual(tuple(K._KEEPER_ENV_NAMES),
                         ("AI_MEMORY_STORE", "IMA_KB_ID"))
        rc, out = _run_action(_args(purge_env=True, dry_run=True))
        self.assertEqual(rc, 0)
        for n in K._KEEPER_ENV_NAMES:
            self.assertIn(n, out)


class UninstallWiringTest(unittest.TestCase):
    """入口与归档安全（防「实现了但没挂上」——本 skill 踩过的同族坑）。"""

    def test_uninstall_subcommand_registered(self):
        with io.open(SRC, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('sub.add_parser("uninstall"', src)
        self.assertIn('cmd == "uninstall"', src)

    def test_retire_dir_only_renames(self):
        """归档必须走 os.rename（同卷、可逆），不得出现删除类调用。"""
        seg = _func_body(SRC, "_retire_dir")
        self.assertIn("os.rename", seg)
        for bad in ("os.remove(", "shutil.rmtree(", "os.unlink("):
            self.assertNotIn(bad, seg, "归档路径不得出现删除类调用：%s" % bad)

    def test_dry_run_does_not_move_deploy_copies(self):
        """dry-run 下部署目录必须原地不动。"""
        wb_hooks = os.path.join(K.WB_HOME, "hooks")
        if not os.path.isdir(wb_hooks):
            self.skipTest("本机没有 %s，无法验证「dry-run 不动部署副本」" % wb_hooks)
        rc, out = _run_action(_args())
        self.assertEqual(rc, 0)
        self.assertIn("[dry] 将搬离部署副本", out)
        self.assertTrue(os.path.isdir(wb_hooks), "dry-run 动了部署副本目录")


if __name__ == "__main__":
    unittest.main()
