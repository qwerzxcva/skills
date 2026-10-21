# -*- coding: utf-8 -*-
"""PreInjector 单测（随包发布，纯函数 + 编排，无 fastembed 依赖）。

覆盖：
- tokenize / containment 与 proven 钩子行为一致；
- select 双闸门（词法 + score 自适应）；
- format 字符预算截断；
- inject 编排：prompt 过短 / 会话去重 / PII 护栏丢弃 / fail-open 降级 / 可观测回调；
- 与 user_prompt_recall 既有判定逻辑等价（用相同 entry 断言 picked 集合一致）。
"""
import os
import sys
import json
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from contract import (  # noqa: E402
    tokenize, containment, redact_or_drop,
    PreInjector, InjectResult,
)


def _entry(eid, summary, body="", score=None, category="general"):
    d = {"id": eid, "summary": summary, "body": body, "category": category}
    if score is not None:
        d["score"] = score
    return d


class TokenizeTest(unittest.TestCase):
    def test_cjk_bigram(self):
        t = tokenize("沙箱安全删除")
        self.assertIn("沙箱", t)
        self.assertIn("箱安", t)
        self.assertIn("安全", t)

    def test_ascii_word(self):
        t = tokenize("safe delete ctypes")
        self.assertIn("safe", t)
        self.assertIn("delete", t)
        self.assertIn("ctypes", t)


class ContainmentTest(unittest.TestCase):
    def test_partial_overlap(self):
        a = tokenize("沙箱 safe-delete 要用 ctypes 真删兜底")
        b = tokenize("沙箱删除必须 ctypes 兜底")
        ratio, shared = containment(a, b)
        self.assertGreater(shared, 0)
        self.assertGreater(ratio, 0.0)


class PIIGuardTest(unittest.TestCase):
    def test_drop_api_key(self):
        self.assertIsNone(redact_or_drop("我的 key 是 sk-1a2b3c4d5e6f7g8h9i0j 别泄露"))

    def test_drop_email(self):
        self.assertIsNone(redact_or_drop("联系 admin@corp.com 即可"))

    def test_drop_path(self):
        self.assertIsNone(redact_or_drop("文件在 C:\\Users\\admin\\secret.txt"))

    def test_keep_clean(self):
        self.assertEqual(redact_or_drop("递归下降解析的边界处理"), "递归下降解析的边界处理")


class SelectGateTest(unittest.TestCase):
    def test_lexical_hit(self):
        inj = PreInjector()
        entries = [_entry("L1", "沙箱 safe-delete 要用 ctypes 真删兜底")]
        picked = inj.select("沙箱删除必须 ctypes 兜底", entries, set(), neural_active=False)
        self.assertEqual(len(picked), 1)

    def test_lexical_miss(self):
        inj = PreInjector()
        entries = [_entry("L1", "量化策略回测 CAGR 计算")]
        picked = inj.select("怎么煮咖啡", entries, set(), neural_active=False)
        self.assertEqual(len(picked), 0)

    def test_score_hit_when_neural(self):
        inj = PreInjector()
        entries = [_entry("L1", "无关主题词", score=0.85)]
        picked = inj.select("完全不相关 query 词", entries, set(), neural_active=True)
        self.assertEqual(len(picked), 1)

    def test_skip_ids_respected(self):
        inj = PreInjector()
        entries = [_entry("L1", "沙箱 safe-delete 要用 ctypes 真删兜底")]
        picked = inj.select("沙箱删除必须 ctypes 兜底", entries, {"L1"}, neural_active=False)
        self.assertEqual(len(picked), 0)


class FormatTest(unittest.TestCase):
    def test_char_budget_truncates(self):
        inj = PreInjector(char_budget=50)
        entries = [_entry("L%d" % i, "经验%d 关于沙箱 safe delete ctypes 兜底真删" % i)
                   for i in range(10)]
        out = inj.format(entries)
        self.assertIn("更多可用 recall 拉取", out)


class InjectOrchestrationTest(unittest.TestCase):
    def _fake_recall(self, hits):
        def fn(q, n):
            return {"ok": True, "count": len(hits), "entries": hits}
        return fn

    def test_prompt_too_short(self):
        inj = PreInjector()
        res = inj.inject("abc", "s1",
                         recall_fn=self._fake_recall([]),
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        self.assertFalse(res.injected)
        self.assertEqual(res.reason, "prompt_too_short")

    def test_normal_inject(self):
        inj = PreInjector()
        hits = [_entry("L1", "沙箱 safe-delete 要用 ctypes 真删兜底")]
        res = inj.inject("沙箱删除必须 ctypes 兜底", "s1",
                         recall_fn=self._fake_recall(hits),
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        self.assertTrue(res.injected)
        self.assertEqual(res.picked, 1)
        self.assertEqual(res.reason, "ok")
        self.assertIn("safe-delete", res.formatted)

    def test_session_dedup(self):
        inj = PreInjector()
        hits = [_entry("L1", "沙箱 safe-delete 要用 ctypes 真删兜底")]
        res = inj.inject("沙箱删除必须 ctypes 兜底", "s1",
                         recall_fn=self._fake_recall(hits),
                         session_injected_ids_fn=lambda s: {"L1"},
                         mark_injected_fn=lambda s, ids: None)
        self.assertFalse(res.injected)  # 已被本会话注入过 → 跳过
        self.assertEqual(res.reason, "no_local_hit")

    def test_pii_guard_drops_secret_entry(self):
        inj = PreInjector()
        hits = [_entry("L1", "我的 key 是 sk-1a2b3c4d5e6f7g8h9i0j 别泄露")]
        res = inj.inject("key 密钥 泄露", "s1",
                         recall_fn=self._fake_recall(hits),
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        # 即使词法命中，PII 护栏也应丢弃 → 无注入
        self.assertFalse(res.injected)
        self.assertEqual(res.candidates, 1)

    def test_fail_open_on_recall_error(self):
        inj = PreInjector()
        def boom(q, n):
            raise RuntimeError("daemon down")
        res = inj.inject("沙箱删除必须 ctypes 兜底", "s1",
                         recall_fn=boom,
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        self.assertFalse(res.injected)
        self.assertTrue(res.degraded)
        self.assertEqual(res.reason, "degraded")

    def test_observ_callback_fired(self):
        inj = PreInjector()
        hits = [_entry("L1", "沙箱 safe-delete 要用 ctypes 真删兜底")]
        seen = {}
        def obs(name, d):
            seen[name] = d
        inj.observ = obs
        res = inj.inject("沙箱删除必须 ctypes 兜底", "s1",
                         recall_fn=self._fake_recall(hits),
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        self.assertIn("inject", seen)
        self.assertEqual(seen["inject"]["picked"], 1)


class EquivalenceWithHookTest(unittest.TestCase):
    """确认 PreInjector.select 与 user_prompt_recall._select 判定一致（防回归）。"""
    def test_same_pick_on_known_entries(self):
        inj = PreInjector()
        # 复制钩子原判定常量
        MIN_SHARED, MIN_RATIO, MIN_SCORE = 3, 0.15, 0.30
        pt = tokenize("沙箱删除必须 ctypes 兜底")
        neural = False
        entries = [
            _entry("A", "沙箱 safe-delete 要用 ctypes 真删兜底"),
            _entry("B", "量化策略回测 CAGR 计算"),
        ]
        picked = inj.select("沙箱删除必须 ctypes 兜底", entries, set(), neural_active=neural)
        picked_ids = {e["id"] for e in picked}
        # 手算钩子逻辑（与 user_prompt_recall._select 等价）
        expect = set()
        for e in entries:
            et = tokenize((e.get("summary") or "") + " " + (e.get("body") or ""))
            r1, shared = containment(pt, et)
            r2, _ = containment(et, pt)
            if shared >= MIN_SHARED and max(r1, r2) >= MIN_RATIO:
                expect.add(e["id"])
        self.assertEqual(picked_ids, expect)
        self.assertEqual(picked_ids, {"A"})


if __name__ == "__main__":
    unittest.main()
