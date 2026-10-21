# -*- coding: utf-8 -*-
"""A1/A2 语义降级提示的落盘 + 开局读取回归测试。

锁定本轮「语义降级提示」核心功能：
- A1（mem_bridge）：recall meta.fell_back_to_lexical=True 时 _mark_degraded 落盘
  ~/.workbuddy/hooks/.keeper_degraded.json；明确未降级时 _clear_degraded 清掉。
- A2（session_start 钩子）：_degraded_note 开局读该文件，7 天内曾降级则注入
  「请转告用户」健康告警（独立于 inject_enabled 门禁）。

防「声明了却没人验」：降级提示是 best-effort 兜底，最容易被当成「不影响主流程」
而漏测——一旦 mark/clear 路径写坏（状态文件路径漂移、窗口判断颠倒），降级提示
会静默失效，退回「降级了却没人知道」的老坑。故落盘、清理、窗口三分支全部断言。
"""
import os
import sys
import json
import shutil
import tempfile
import datetime as dt
import unittest
import importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SKILL_ROOT = os.path.dirname(HERE)                                  # skill 根
HOOKS_DIR = os.path.join(SKILL_ROOT, "hooks")

# mem_bridge 在 skill 根
sys.path.insert(0, SKILL_ROOT)
import mem_bridge


def _load_session_start_hook():
    """session_start_keeper_inject 依赖同目录 keeper_hook_common，用 importlib 加载。"""
    sys.path.insert(0, HOOKS_DIR)
    spec = importlib.util.spec_from_file_location(
        "session_start_keeper_inject",
        os.path.join(HOOKS_DIR, "session_start_keeper_inject.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SS = _load_session_start_hook()


class DegradedMarkClearTest(unittest.TestCase):
    """A1：mem_bridge 的降级状态落盘 / 清理。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_degraded_test_")
        self.state_path = os.path.join(self.tmp, "hooks", ".keeper_degraded.json")
        self._orig = mem_bridge._DEGRADED_STATE
        mem_bridge._DEGRADED_STATE = self.state_path

    def tearDown(self):
        mem_bridge._DEGRADED_STATE = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mark_degraded_writes_state_and_auto_mkdir(self):
        # 目录不存在时应自动创建（真实 ~/.workbuddy/hooks 通常已存在，但不可假设）
        mem_bridge._mark_degraded("fell_back_to_lexical")
        self.assertTrue(os.path.exists(self.state_path))
        with open(self.state_path, encoding="utf-8") as f:
            st = json.load(f)
        self.assertTrue(st.get("degraded"))
        self.assertEqual(st.get("reason"), "fell_back_to_lexical")
        self.assertIn("degraded_at", st)

    def test_clear_degraded_removes_state(self):
        mem_bridge._mark_degraded("fell_back_to_lexical")
        self.assertTrue(os.path.exists(self.state_path))
        mem_bridge._clear_degraded()
        self.assertFalse(os.path.exists(self.state_path))

    def test_clear_degraded_noop_when_absent(self):
        # 无状态文件时 clear 不应抛错（残留最多多提示一次，无害）
        mem_bridge._clear_degraded()  # 不应 raise


class DegradedNoteReadTest(unittest.TestCase):
    """A2：session_start 钩子开局读降级状态 + 7 天窗口。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_degraded_note_")
        self.state_path = os.path.join(self.tmp, ".keeper_degraded.json")
        self._orig = _SS.DEGRADED_STATE
        _SS.DEGRADED_STATE = self.state_path

    def tearDown(self):
        _SS.DEGRADED_STATE = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_state(self, days_ago):
        ts = (dt.datetime.now() - dt.timedelta(days=days_ago)).isoformat()
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump({"degraded": True, "degraded_at": ts,
                       "reason": "fell_back_to_lexical"}, f)

    def test_recent_degraded_returns_prompt(self):
        self._write_state(0)  # 今天
        note = _SS._degraded_note()
        self.assertTrue(note)
        self.assertIn("请转告用户", note)

    def test_expired_degraded_returns_empty(self):
        self._write_state(8)  # 8 天前，超过 7 天窗口
        self.assertEqual(_SS._degraded_note(), "")

    def test_absent_state_returns_empty(self):
        self.assertEqual(_SS._degraded_note(), "")


if __name__ == "__main__":
    unittest.main()
