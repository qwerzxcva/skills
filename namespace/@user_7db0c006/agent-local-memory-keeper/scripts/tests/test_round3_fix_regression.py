# -*- coding: utf-8 -*-
"""第三轮复审「按顺序修复」的回归锁定测试 修复轮）。

锁定本轮实际改动 / 复核结论的行为不变式，防未来回归：

- C1 异步落库绝不静默丢记忆：落库失败时 _fail_keep_payload 把载荷移入 failed/ 重试队列，
绝不删除原始载荷（成功才删）。
- I7 注入日志不含明文 prompt：emit_inject_record 落盘的注入记录绝不携带原始 prompt。
- I8 自动捕获落库前脱敏（一票否决）：默认 sensitive_action="raise"，命中敏感模式直接拒绝写盘。
- I9 会话注入态 read-modify-write 持锁：并发标记去重集合做并集合并，不丢 id、写盘为合法 JSON。
"""
import os
import sys
import json
import base64
import tempfile
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPTS = os.path.join(SKILL, "scripts")
HOOKS = os.path.join(SKILL, "hooks")
OPS = os.path.join(SCRIPTS, "memory_ops", "__init__.py")

for _p in (SCRIPTS, HOOKS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _cli(env_extra, *args):
    env = dict(os.environ)
    env["AI_MEM_EMBED_BACKEND"] = "lexical"
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, OPS, *args], capture_output=True,
                       text=True, encoding="utf-8", env=env, timeout=180)
    try:
        return json.loads(p.stdout.strip() or "{}"), p.returncode
    except Exception:
        return {"_raw": p.stdout, "_rc": p.returncode, "_err": p.stderr[-400:]}, p.returncode




class C1AsyncDepositNoSilentLossTest(unittest.TestCase):
    def test_fail_keep_payload_preserves(self):
        # C1：落库失败时载荷必须保留到 failed/，绝不删除原始文件。
        # 隔离到临时 hooks_dir，避免污染线上 hooks/failed/ 与诊断日志。
        import _async_deposit as ad
        d = tempfile.mkdtemp(prefix="c1_")
        p = os.path.join(d, "payload.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"root": d, "summary": "x", "body": "y"}, f)
        ad._fail_keep_payload(p, RuntimeError("boom"), hooks_dir=d)
        self.assertFalse(os.path.exists(p), "原始载荷应已移走")
        failed = os.path.join(d, "failed")
        kept = [fn for fn in os.listdir(failed) if fn.endswith("payload.json") or "payload" in fn]
        self.assertTrue(kept, "failed/ 应保留原始载荷副本")
        log = os.path.join(d, "_async_deposit.failed.log")
        self.assertTrue(os.path.exists(log), "应写诊断日志")


class I7InjectLogNoPromptTest(unittest.TestCase):
    def test_inject_record_excludes_prompt(self):
        # I7：真实注入管线的结果（PreInjector.to_dict）绝不携带明文 prompt；
        # emit_inject_record 落盘的记录同样不含 prompt（契约层不持久化原始 prompt）。
        from contract.observ import emit_inject_record
        from contract import PreInjector
        inj = PreInjector()
        res = inj.inject(
            prompt="用户原始提问内容SECRET（绝不可落盘）",
            session_id="s1",
            recall_fn=lambda q, n: {"ok": True, "entries": []},
            session_injected_ids_fn=lambda s: set(),
            mark_injected_fn=lambda s, ids: None,
            neural_active=False,
            audit_fn=lambda *a, **k: None,
        )
        rd = res.to_dict()
        self.assertNotIn("prompt", rd, "PreInjector.to_dict() 不得含 prompt 字段")
        d = tempfile.mkdtemp(prefix="i7_")
        log = os.path.join(d, "inject.jsonl")
        emit_inject_record(log, rd, session_id="s1")
        with open(log, encoding="utf-8") as f:
            rec = json.loads(f.read().strip())
        self.assertNotIn("prompt", rec, "注入记录不得含 prompt 字段")


class I8SensitiveRejectedTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="i8_")

    def test_deposit_secret_rejected_by_default(self):
        # I8：默认 sensitive_action="raise"，命中敏感模式直接拒绝写盘（不存储）。
        # 用符合 _SENSITIVE_PATTERNS 的真实格式（Stripe live key：sk_live_ + 24+ 字母数字）。
        _cli({}, "init", "--root", self.root)
        secret_body = "业务摘要；密钥 sk_live_ABCDEFGHIJKLMNOPQRSTUVWXYZ0001 不要记"
        r, rc = _cli({}, "deposit", "--root", self.root,
                     "--summary", "正常摘要无敏感", "--body", secret_body)
        self.assertFalse(r.get("ok"), "敏感内容应被拒绝，实际 %r" % r)
        # 确认未落盘：recall 找不到该正文
        r2, _ = _cli({}, "recall", "--root", self.root, "--query", "正常摘要无敏感")
        bodies = [e.get("body") for e in (r2.get("entries") or [])]
        self.assertNotIn(secret_body, bodies, "敏感正文绝不应被存储")


class I9SessionInjectAtomicMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="i9_")
        import keeper_hook_common as C
        self.C = C
        self._orig = C._SESS_INJECT
        C._SESS_INJECT = os.path.join(self.tmp, "_session_inject.json")

    def tearDown(self):
        self.C._SESS_INJECT = self._orig

    def test_concurrent_mark_union_no_loss(self):
        # I9：多次标记做并集合并且不丢 id，落盘为合法 JSON（持锁 read-modify-write）。
        self.C.mark_session_injected("sess1", ["a", "b"])
        self.C.mark_session_injected("sess1", ["b", "c"])  # 模拟并发/连续标记
        st = self.C.load_session_inject()
        self.assertEqual(set(st.get("sess1", [])), {"a", "b", "c"},
                         "去重集合应做并集合并，不得丢 id")
        # 落盘为合法 JSON（原子写）
        with open(self.C._SESS_INJECT, encoding="utf-8") as f:
            json.load(f)  # 不抛异常即通过


if __name__ == "__main__":
    unittest.main()
