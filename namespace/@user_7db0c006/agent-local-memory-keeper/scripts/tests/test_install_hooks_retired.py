# -*- coding: utf-8 -*-
"""install_hooks 必须主动清理「已退役钩子」的历史注册（2026-09-15 审计修复）。

背景（实读本机 settings.json 实证）：
  `bash_error_capture.py` 已从技能彻底删除（I13，职责由
  `post_tool_use_error_capture.py` 承担），但它**仍注册在本机 settings.json 的
  PostToolUse/Bash**（与 post_tool_use 同 matcher）。

根因：旧安装器第 2 步「移除模式禁止的 keeper 钩子」只在**事件未启用**时生效，
而 PostToolUse 在 silent（默认）模式里是启用的 → 该条目永远清不掉，每次
PostToolUse 都去执行一个不存在的文件（静默失败）。

修法：新增 `RETIRED_HOOK_FILES` 清单 + 第 3 步「跨所有事件、不受模式限制」清理。
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/
SKILL_ROOT = os.path.dirname(HERE)
INSTALLER = os.path.join(SKILL_ROOT, "install_hooks.py")

PYW = r"C:/py/pythonw.exe"
HOOKS_DST_STUB = r"C:/wb/hooks"
RETIRED = "bash_error_capture.py"
KEEPER_CMD = '"%s" "%s/post_tool_use_error_capture.py"' % (PYW, HOOKS_DST_STUB)
RETIRED_CMD = '"%s" "%s/%s"' % (PYW, HOOKS_DST_STUB, RETIRED)
BUILTIN_CMD = '"%s" "C:/wb/hooks/leak_scan.py"' % PYW


def _load_installer(settings_path, hooks_dst):
    """把真实 install_hooks.py 载入独立命名空间，并把 SETTINGS/HOOKS_DST
    重定向到临时沙箱（避免测试污染用户真实 ~/.workbuddy/settings.json）。"""
    with open(INSTALLER, encoding="utf-8") as f:
        src = f.read()
    ns = {"__file__": INSTALLER, "__name__": "install_hooks_undertest"}
    exec(compile(src, INSTALLER, "exec"), ns)
    ns["SETTINGS"] = settings_path
    ns["HOOKS_DST"] = hooks_dst
    return ns


def _group(cmd, matcher=None):
    g = {"hooks": [{"type": "command", "command": cmd, "timeout": 30}]}
    if matcher:
        g["matcher"] = matcher
    return g


class InstallerRetiredHookCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_installh_")
        self.settings = os.path.join(self.tmp, "settings.json")
        self.hooks_dst = os.path.join(self.tmp, "hooks")
        os.makedirs(self.hooks_dst, exist_ok=True)

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass  # 删除类 API 受限时残留临时目录不影响结论

    def _seed(self, hooks):
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"hooks": hooks}, f, ensure_ascii=False, indent=2)

    def _read(self):
        with open(self.settings, encoding="utf-8") as f:
            return json.load(f)

    def _run(self, mode, dry=False):
        ns = _load_installer(self.settings, self.hooks_dst)
        return ns["_merge_settings"](dry, mode)

    # ── 主用例：silent（默认）模式下退役条目必须被清掉 ──
    def test_retired_removed_in_silent_mode(self):
        self._seed({
            "PostToolUse": [_group(RETIRED_CMD, "Bash"),
                            _group(KEEPER_CMD, "Bash"),
                            _group(BUILTIN_CMD, "Bash")],
            "Stop": [_group('"%s" "%s/memory_auto_capture.py" Stop' % (PYW, HOOKS_DST_STUB))],
        })
        changed, detail = self._run("silent")
        self.assertTrue(changed, "应报告发生变更")
        self.assertTrue(any("已退役" in d and RETIRED in d for d in detail),
                        "detail 应声明移除了退役钩子，实际: %s" % detail)
        after = self._read()
        cmds = [h["command"] for g in after["hooks"]["PostToolUse"] for h in g.get("hooks", [])]
        self.assertFalse(any(RETIRED in c for c in cmds),
                         "退役钩子必须被移除（silent 模式下事件仍启用，旧逻辑漏清）")
        self.assertTrue(any("post_tool_use_error_capture.py" in c for c in cmds),
                        "同 matcher 的现行 keeper 钩子不得被误删")
        self.assertIn(BUILTIN_CMD, cmds, "WorkBuddy 内置钩子不得被误删")
        self.assertFalse(os.path.exists(os.path.join(self.hooks_dst, RETIRED)),
                         "退役文件不应被重新部署（不在 HOOK_FILES 内）")

    # ── full 模式同样要清（清理不受模式限制）──
    def test_retired_removed_in_full_mode(self):
        self._seed({"PostToolUse": [_group(RETIRED_CMD, "Bash"), _group(KEEPER_CMD, "Bash")]})
        self._run("full")
        cmds = [h["command"] for g in self._read()["hooks"]["PostToolUse"] for h in g.get("hooks", [])]
        self.assertNotIn(RETIRED_CMD, cmds, "full 模式也必须清理退役条目")

    # ── 混合组：只摘退役条，同组其余 hook 原样保留、组不消失 ──
    def test_mixed_group_keeps_other_hooks(self):
        mixed = {"hooks": [{"type": "command", "command": RETIRED_CMD, "timeout": 30},
                           {"type": "command", "command": BUILTIN_CMD, "timeout": 30}],
                 "matcher": "Bash"}
        self._seed({"PostToolUse": [mixed]})
        self._run("silent")
        groups = self._read()["hooks"]["PostToolUse"]
        # 第 1 步会追加一个现行 keeper 组；原混合组应存活（只摘退役条）
        self.assertTrue(any(g.get("hooks") == [{"type": "command", "command": BUILTIN_CMD,
                                                "timeout": 30}] for g in groups),
                        "混合组应存活且只剩非退役条目，实际: %s" % groups)
        self.assertFalse(any(RETIRED in h.get("command", "")
                             for g in groups for h in g.get("hooks", [])),
                         "混合组里的退役条目必须被摘掉")

    # ── 反向：名字相似但非退役清单内的命令不得被删 ──
    def test_unrelated_command_not_removed(self):
        other = '"%s" "C:/wb/hooks/error_capture_helper.py"' % PYW
        self._seed({"PostToolUse": [_group(other, "Bash")]})
        changed, detail = self._run("silent")
        cmds = [h["command"] for g in self._read()["hooks"]["PostToolUse"] for h in g.get("hooks", [])]
        self.assertIn(other, cmds, "非退役清单内的命令绝不能被删（防误伤）")

    # ── dry-run 只报告不落盘 ──
    def test_dry_run_does_not_write(self):
        self._seed({"PostToolUse": [_group(RETIRED_CMD, "Bash")]})
        with open(self.settings, "rb") as f:
            before = f.read()
        changed, detail = self._run("silent", dry=True)
        self.assertTrue(any("已退役" in d for d in detail), "dry-run 也应报告将移除，实际: %s" % detail)
        with open(self.settings, "rb") as f:
            after = f.read()
        self.assertEqual(after, before, "dry-run 绝不允许改写 settings.json")

    # ── 源码契约：退役清单必须显式存在且含 bash_error_capture.py ──
    def test_source_declares_retired_list(self):
        with open(INSTALLER, encoding="utf-8") as f:
            src = f.read()
        i = src.find("RETIRED_HOOK_FILES = [")
        self.assertGreater(i, 0, "缺 RETIRED_HOOK_FILES 常量定义（docstring 提及不算）")
        block = src[i:i + 400]
        self.assertIn(RETIRED, block, "退役清单必须含 %s" % RETIRED)
        self.assertIn("移除(已退役)", src, "缺跨事件清理的 detail 标记")


if __name__ == "__main__":
    unittest.main()
