# -*- coding: utf-8 -*-
"""回归测试：钩子持久模式读取 + 部署副本漂移检测。

锁定两个真实缺陷（2026-09-11 复核发现，均属"静默失效"）：
  1. `_keeper_hook_mode()` 按 `<skill>/scripts/hooks_config.json` 探测，而真实文件在
     **技能根** → 恒返回兜底 "full"，用户持久化的 silent/off 被静默忽略（连 off 短路也失效）。
  2. `install_hooks.py` 只在"settings.json 里还没 keeper 钩子"时才被触发 →
     **技能升级后 ~/.workbuddy/hooks/ 与 keeper_daemon/ 的副本会静默停在旧版**。
     新增「部署指纹 + 漂移检测 + 自动刷新」后，本测试锁死检测与节流行为。

做法：真实 `_hooks.py` 以独立命名空间加载（复刻 __init__ 的依赖注入），
在临时"技能树"里跑，并用 env `KEEPER_HOOKS_DIR` 把部署目录隔离到临时区——
避免读写真实用户目录污染环境。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/
SKILL_ROOT = os.path.dirname(HERE)
HOOKS_SRC = os.path.join(SKILL_ROOT, "scripts", "memory_ops", "_hooks.py")

_HOOK_FILES = ["keeper_hook_common.py", "session_start_keeper_inject.py",
               "user_prompt_recall.py", "post_tool_use_error_capture.py",
               "memory_auto_capture.py", "_async_deposit.py"]


def _load_hooks_module(skill_dir, deploy_dir):
    """把真实 _hooks.py 加载进独立命名空间（模拟 __init__ 的 globals 注入）。"""
    with open(HOOKS_SRC, encoding="utf-8") as f:
        src = f.read()
    os.environ["KEEPER_HOOKS_DIR"] = deploy_dir
    ns = {
        "__file__": os.path.join(skill_dir, "scripts", "memory_ops", "_hooks.py"),
        "__name__": "memory_ops_hooks_undertest",
        "os": os, "json": json, "sys": sys,
        "_KEEPER_HOOK_FILES": tuple(_HOOK_FILES),
    }
    exec(compile(src, HOOKS_SRC, "exec"), ns)
    return ns


class HookModeAndDeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_hookmode_")
        self.skill = os.path.join(self.tmp, "skill")
        os.makedirs(os.path.join(self.skill, "scripts", "memory_ops"))
        os.makedirs(os.path.join(self.skill, "hooks"))
        self.deploy = os.path.join(self.tmp, "deploy")
        os.makedirs(self.deploy, exist_ok=True)
        with open(os.path.join(self.skill, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("# stub\nversion: 9.9.9\n")
        for fn in _HOOK_FILES:
            with open(os.path.join(self.skill, "hooks", fn), "w", encoding="utf-8") as f:
                f.write("# %s\n" % fn)
        self.ns = _load_hooks_module(self.skill, self.deploy)

    def tearDown(self):
        os.environ.pop("KEEPER_HOOKS_DIR", None)
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass  # 本环境删除类 API 受限，残留临时目录不影响结论

    def _write_state(self, version="9.9.9", corrupt=None, daemon=None):
        files = {}
        for fn in _HOOK_FILES:
            p = os.path.join(self.skill, "hooks", fn)
            with open(p, "rb") as fh:
                files[fn] = hashlib.sha256(fh.read()).hexdigest()
        if corrupt:
            files[corrupt] = "0" * 64
        p = os.path.join(self.deploy, ".keeper_deploy_state.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"version": version, "files": files, "daemon": daemon or {}}, f)

    # ── 缺陷 1：模式必须从技能根读（旧实现在 scripts/ 下探测 → 恒 full）──
    def test_mode_read_from_skill_root(self):
        with open(os.path.join(self.skill, "hooks_config.json"), "w", encoding="utf-8") as f:
            json.dump({"hooks_mode": "off"}, f)
        self.assertEqual(
            self.ns["_keeper_hook_mode"](), "off",
            "hooks_config.json 在技能根，必须能读到（旧实现恒返回 full）")

    def test_mode_default_full_when_missing(self):
        self.assertEqual(self.ns["_keeper_hook_mode"](), "full",
                         "配置缺失时应回退 full")

    # ── 缺陷 2：部署副本漂移检测 ──
    def test_stale_when_no_deploy_state(self):
        stale, why = self.ns["_hooks_stale_reason"]()
        self.assertTrue(stale, "没有部署记录时应判为滞后（触发一次自愈）")
        self.assertIn("无部署记录", why)

    def test_fresh_when_version_and_hash_match(self):
        self._write_state(version="9.9.9")
        stale, why = self.ns["_hooks_stale_reason"]()
        self.assertFalse(stale, "版本+哈希全一致时不得误判滞后；实际: %s" % why)

    def test_stale_when_version_differs(self):
        self._write_state(version="9.9.8")
        stale, why = self.ns["_hooks_stale_reason"]()
        self.assertTrue(stale, "技能已升级 → 副本滞后，必须检测到")
        self.assertIn("版本变化", why)

    def test_stale_when_file_content_changed(self):
        self._write_state(version="9.9.9", corrupt="memory_auto_capture.py")
        stale, why = self.ns["_hooks_stale_reason"]()
        self.assertTrue(stale, "副本内容与部署指纹不符时必须检测到")
        self.assertIn("滞后", why)

    def test_stale_when_daemon_copy_changed(self):
        """守护进程副本也要查——调度项直接指向部署副本，升级后同样会滞后。"""
        os.makedirs(os.path.join(self.skill, "keeper_daemon"))
        with open(os.path.join(self.skill, "keeper_daemon", "daemon.py"),
                  "w", encoding="utf-8") as f:
            f.write("# daemon v1\n")
        self._write_state(version="9.9.9", daemon={"daemon.py": "1" * 64})
        stale, why = self.ns["_hooks_stale_reason"]()
        self.assertTrue(stale, "守护进程副本与指纹不符时必须检测到")
        self.assertIn("守护进程", why)

    # ── 节流：防"刷新失败 → 每条命令都重试"的静默风暴 ──
    def test_refresh_attempt_throttled_per_version(self):
        self.assertTrue(self.ns["_should_attempt_refresh"]("9.9.9"))
        self.ns["_mark_refresh_attempt"]("9.9.9")
        self.assertFalse(self.ns["_should_attempt_refresh"]("9.9.9"),
                         "同版本 6 小时内不得重复尝试刷新")
        self.assertTrue(self.ns["_should_attempt_refresh"]("9.9.10"),
                        "换版本应重新允许尝试")


    # ── 缺陷 3：首次自动注册的 installer 路径必须落在**技能根** ──
    # 旧实现 `os.path.dirname(os.path.abspath(__file__))` → `<skill>/scripts/memory_ops/`，
    # 那里没有 install_hooks.py → `if not os.path.exists(_installer): return` 直接吞掉 →
    # 「装完首次跑命令自动注册钩子」这条路径**从未生效**（与缺陷 1 同类路径错位）。
    def _capture_installer_spawn(self):
        """在"未注册钩子"的前提下调用 _ensure_hooks，捕获它要派发的命令。"""
        installer = os.path.join(self.skill, "install_hooks.py")
        with open(installer, "w", encoding="utf-8") as f:
            f.write("# stub installer\n")
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".workbuddy"), exist_ok=True)
        old_env = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME",
                                                 "KEEPER_AUTO_INSTALL_HOOKS")}
        os.environ["USERPROFILE"] = home
        os.environ["HOME"] = home
        os.environ["KEEPER_AUTO_INSTALL_HOOKS"] = "1"
        calls = []

        class _FakePopen(object):
            def __init__(self, *a, **kw):
                calls.append((a, kw))

        real = subprocess.Popen
        subprocess.Popen = _FakePopen
        try:
            self.ns["_ensure_hooks"]()
        finally:
            subprocess.Popen = real
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertTrue(calls, "未注册钩子时必须派发安装器（旧实现因路径错位静默 return）")
        argv = calls[0][0][0]  # Popen 的首个位置参数（命令字符串）
        return argv, calls[0][1]

    def test_ensure_hooks_dispatches_skill_root_installer(self):
        argv, kwargs = self._capture_installer_spawn()
        self.assertIn("install_hooks.py", argv)
        self.assertIn(os.path.join(self.skill, "install_hooks.py"), argv,
                      "安装器必须取自技能根；实际派发: %s" % argv)
        self.assertNotIn("memory_ops", argv,
                         "不得再落到 scripts/memory_ops/（那是旧实现错位的路径）")

    # ── 缺陷 4：派发安装器必须静默（父进程是无控制台的 pythonw）──
    def test_ensure_hooks_dispatch_is_silent_on_windows(self):
        _argv, kwargs = self._capture_installer_spawn()
        if sys.platform.startswith("win"):
            self.assertEqual(kwargs.get("creationflags"), 0x08000000,
                             "Windows 必须用 CREATE_NO_WINDOW；CREATE_NEW_PROCESS_GROUP 会弹黑窗")
        else:
            self.assertIsNone(kwargs.get("creationflags"))


if __name__ == "__main__":
    unittest.main()
