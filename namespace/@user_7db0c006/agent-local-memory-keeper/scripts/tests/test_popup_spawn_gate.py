# -*- coding: utf-8 -*-
"""静态闸门回归测试：后台子进程不得弹窗。

锁定 2026-09-11 全量体检发现的实锤：`install_hooks.py` 后台拉起 daemon 时用
`CREATE_NEW_PROCESS_GROUP (0x00000200)`。受控实验（父 pythonw + 子 python.exe + DEVNULL 重定向，
即真实形态）：
    不设 flags → hwnd=722416 **可见** ｜ 0x200 → hwnd=984144 **可见**
    0x08000000 / DETACHED_PROCESS / 0x8|0x200 → hwnd=0 不可见
即：不加静默旗标 = 每次安装/后台刷新弹一个黑窗。

测试策略：搭最小"技能树"，正反双向断言——
  - 真实技能树 → PASS（防闸门空转）；
  - 0x200 / 无旗标 → 必须 FAIL（防形同虚设）；
  - CREATE_NO_WINDOW / DETACHED_PROCESS / POSIX start_new_session → 不得被误杀。
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SKILL_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import verify_claims as vc  # noqa: E402


class PopupSpawnGateTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_popup_")
        os.makedirs(os.path.join(self.root, "hooks"))

    def tearDown(self):
        try:
            shutil.rmtree(self.root)
        except Exception:
            pass

    def _write_hook(self, body):
        with open(os.path.join(self.root, "hooks", "spawner.py"), "w",
                  encoding="utf-8") as f:
            f.write(body)

    # ── 正向：真实技能树必须 PASS ──
    def test_real_tree_passes(self):
        r = vc._static_no_popup_spawn(SKILL_ROOT)
        self.assertTrue(r["ok"], "真实技能树应全部带静默旗标；实际: %s" % r.get("error"))

    # ── 负向 1：单用 CREATE_NEW_PROCESS_GROUP（正是被修掉的那个写法）──
    def test_new_process_group_only_fails(self):
        self._write_hook(
            "import subprocess\n"
            "subprocess.Popen(cmd, stdout=subprocess.DEVNULL,\n"
            "                 creationflags=0x00000200)\n")
        r = vc._static_no_popup_spawn(self.root)
        self.assertFalse(r["ok"], "0x200 不静默，必须 FAIL")

    # ── 负向 2：完全不传旗标（父进程无控制台时会新开可见控制台）──
    def test_no_flags_fails(self):
        self._write_hook(
            "import subprocess\n"
            "subprocess.run([py, script], capture_output=True, timeout=300)\n")
        r = vc._static_no_popup_spawn(self.root)
        self.assertFalse(r["ok"], "无旗标必须 FAIL（会新开可见控制台）")

    # ── 防误杀 1：CREATE_NO_WINDOW 是正解 ──
    def test_create_no_window_passes(self):
        self._write_hook(
            "import subprocess\n"
            "kwargs = {'stdout': subprocess.DEVNULL}\n"
            "if os.name == 'nt':\n"
            "    kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW\n"
            "subprocess.Popen(cmd, **kwargs)\n")
        r = vc._static_no_popup_spawn(self.root)
        self.assertTrue(r["ok"], "CREATE_NO_WINDOW 应通过；实际: %s" % r.get("error"))

    # ── 防误杀 2：DETACHED_PROCESS（守护进程用它脱离父进程）实测不弹窗 ──
    def test_detached_process_passes(self):
        self._write_hook(
            "import subprocess\n"
            "flags = getattr(subprocess, 'DETACHED_PROCESS', 0)\n"
            "subprocess.Popen([py, daemon], creationflags=flags)\n")
        r = vc._static_no_popup_spawn(self.root)
        self.assertTrue(r["ok"], "DETACHED_PROCESS 实测不可见，不应被误杀；实际: %s" % r.get("error"))

    # ── 防误杀 3：POSIX 分支用 start_new_session（无 creationflags 概念）──
    def test_posix_start_new_session_passes(self):
        self._write_hook(
            "import subprocess\n"
            "subprocess.Popen([py, daemon], start_new_session=True)\n")
        r = vc._static_no_popup_spawn(self.root)
        self.assertTrue(r["ok"], "POSIX start_new_session 不应被误杀；实际: %s" % r.get("error"))


if __name__ == "__main__":
    unittest.main()
