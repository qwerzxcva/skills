# -*- coding: utf-8 -*-
"""scan_contradictions 单测（随包发布，纯逻辑、只读）。

覆盖：
- 同轴对称极性 → 报矛盾；
- 同轴同极性（冗余）→ 不报矛盾；
- 不同轴 → 不报；
- 空/单条输入 → 空；
- CLI 从 stdin 读 JSON 可跑。
"""
import os
import sys
import json
import io
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from contract.consistency import scan_contradictions, main  # noqa: E402


def _f(fid, statement, layer="L4"):
    return {"id": fid, "statement": statement, "layer": layer}


class ScanTest(unittest.TestCase):
    def test_opposite_polarity_same_axis(self):
        facts = [
            _f("a", "默认优先简单方案"),
            _f("b", "不要默认优先简单方案", layer="L2"),
        ]
        c = scan_contradictions(facts)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["reason"], "同一语义轴上相反极性陈述（矛盾候选）")

    def test_same_polarity_not_conflict(self):
        facts = [_f("a", "优先简单方案"), _f("b", "优先简单方案")]
        self.assertEqual(scan_contradictions(facts), [])

    def test_different_axis_no_conflict(self):
        facts = [_f("a", "优先简单方案"), _f("b", "不要使用重型框架")]
        self.assertEqual(scan_contradictions(facts), [])

    def test_empty_and_single(self):
        self.assertEqual(scan_contradictions([]), [])
        self.assertEqual(scan_contradictions([_f("a", "优先简单方案")]), [])

    def test_cli_stdin(self):
        inp = json.dumps({"l2": [_f("a", "默认优先简单方案", "L2")],
                          "l4": [_f("b", "不要默认优先简单方案", "L4")]})
        old = sys.stdin
        sys.stdin = io.StringIO(inp)
        try:
            rc = main(["--stdin"])
        finally:
            sys.stdin = old
        self.assertEqual(rc, 2)  # 有冲突 → 退出码 2


if __name__ == "__main__":
    unittest.main()
