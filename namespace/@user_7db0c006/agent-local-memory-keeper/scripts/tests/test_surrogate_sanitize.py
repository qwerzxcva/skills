# -*- coding: utf-8 -*-
"""回归锁：钩子读 stdin 时的半代理码点（surrogate）消毒。

背景（实测，非推断）：hook_audit.log 中 502 条 `deposit_error` 全部是
`'utf-8' codec can't encode character '\\udcXX'`——Python UTF-8 模式下 sys.stdin
用 errors='surrogateescape'，Bash 输出里的非法字节被解成半代理码点；json.load 不报错，
但后续 json.dump / 写文件必抛 UnicodeEncodeError，自动捕获因此静默失效。

修法：在 `hooks/keeper_hook_common.py` 提供 sanitize_text / sanitize_obj / read_event，
各钩子读 stdin 处统一消毒。本文件锁死该行为，防止回退。
"""
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(os.path.dirname(HERE))  # .../scripts/tests -> skill root
HOOKS_DIR = os.path.join(SKILL_ROOT, "hooks")

if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

import keeper_hook_common as C  # noqa: E402

# ⚠️ 源码里不能出现 "\udcba" 这类转义字面量：CPython 3.13 编译期即抛 UnicodeEncodeError，
# 模块 import 不了。故用 chr() 在运行期构造半代理码点。
BAD = "cd /c/Users/x/" + chr(0xDCBA) + "skills/agent"   # 含半代理码点（模拟非法字节）
GOOD = "cd /c/Users/x/" + chr(0xFFFD) + "skills/agent"  # 期望：替换为 U+FFFD


class TestSanitizeText(unittest.TestCase):
    def test_surrogate_replaced(self):
        self.assertEqual(C.sanitize_text(BAD), GOOD)

    def test_clean_text_untouched(self):
        s = "正常的中文与 ascii 混合 text 123"
        self.assertEqual(C.sanitize_text(s), s)

    def test_non_str_passthrough(self):
        self.assertEqual(C.sanitize_text(None), None)
        self.assertEqual(C.sanitize_text(42), 42)

    def test_sanitized_is_encodable(self):
        """核心：消毒前写盘必炸，消毒后 json.dump 正常。"""
        with self.assertRaises(UnicodeEncodeError):
            BAD.encode("utf-8")
        json.dumps({"cmd": C.sanitize_text(BAD)}, ensure_ascii=False).encode("utf-8")


class TestSanitizeObj(unittest.TestCase):
    def test_nested_dict_list(self):
        obj = {"a": BAD, "b": [BAD, {"c": BAD}], "d": 1}
        out = C.sanitize_obj(obj)
        self.assertEqual(out, {"a": GOOD, "b": [GOOD, {"c": GOOD}], "d": 1})

    def test_dict_key_sanitized(self):
        self.assertEqual(C.sanitize_obj({BAD: 1}), {GOOD: 1})

    def test_full_event_encodable(self):
        """端到端：整个事件体消毒后可 json.dumps（此前会在 dump 阶段抛错）。"""
        evt = C.sanitize_obj({
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": BAD},
            "tool_response": {"exitCode": 1, "output": BAD},
        })
        raw = json.dumps(evt, ensure_ascii=False)
        self.assertNotIn(chr(0xDCBA), raw)
        self.assertEqual(json.loads(raw)["tool_input"]["command"], GOOD)


class TestReadEvent(unittest.TestCase):
    def test_read_event_sanitizes_stdin(self):
        payload = json.dumps({"prompt": BAD, "session_id": "s1"}, ensure_ascii=False)
        old = sys.stdin
        try:
            sys.stdin = io.StringIO(payload)
            evt = C.read_event()
        finally:
            sys.stdin = old
        self.assertEqual(evt.get("prompt"), GOOD)
        self.assertEqual(evt.get("session_id"), "s1")

    def test_read_event_fail_open(self):
        old = sys.stdin
        try:
            sys.stdin = io.StringIO("not json at all")
            self.assertEqual(C.read_event(), {})
        finally:
            sys.stdin = old

    def test_read_event_handles_raw_invalid_bytes(self):
        """严格解码模式下 json.load(sys.stdin) 会当场抛 UnicodeDecodeError（钩子静默 return），
        故 read_event 必须走「读字节 → decode(replace)」，本用例用真实非法字节锁死该行为。"""
        payload = json.dumps({"prompt": BAD}, ensure_ascii=False).encode(
            "utf-8", "surrogatepass")  # 半代理码点 → WTF-8 非法字节 ED B2 BA
        self.assertIn(b"\xed\xb2\xba", payload)
        old = sys.stdin
        try:
            sys.stdin = io.BytesIO(payload)
            evt = C.read_event()
        finally:
            sys.stdin = old
        # 注：ED B2 BA 是 3 个各自无法解码的字节 → surrogateescape 解出 3 个半代理码点
        # → 3 个 U+FFFD（每字节一个）。与「文本流入口」（1 个半代理码点 → 1 个 U+FFFD）
        # 数量不同是字节语义使然；二者都保证「可编码、不抛异常」，这才是本用例锁的目标。
        self.assertEqual(evt.get("prompt"), "cd /c/Users/x/" + chr(0xFFFD) * 3 + "skills/agent")
        json.dumps(evt, ensure_ascii=False).encode("utf-8")  # 消毒后一定能编码


if __name__ == "__main__":
    unittest.main()
