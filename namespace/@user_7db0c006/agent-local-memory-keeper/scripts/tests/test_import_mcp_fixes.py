# -*- coding: utf-8 -*-
"""回归：批量导入 / MCP 服务 深度复审发现的问题修复 复审轮）。

覆盖：
- B1  BOM CSV 不再静默丢数据（utf-8-sig 剥 BOM）
- B2  GBK 编码可导入；其他编码（UTF-16）给清晰编码错误而非静默/误诊
- B3  MCP export fmt=md + limit 按记忆块截断，不切断单条
- B4/C3 无法归一化记录计入 dropped（带原因），不再无感知丢弃
- B5  --on-error abort 不被「成功隔离」误触发
- B6/C4 引擎 benchmark 拒默认库；桥 benchmark --root 透传可跑
- O3/C5 MCP deposit 缺 summary 返回结构化错误
- O5 批量导入逐条 results 无界增长防护（超 RESULTS_CAP 截断，results_total 暴露真实量）
"""
import os
import sys
import io
import json
import tempfile
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPTS = os.path.join(SKILL, "scripts")
OPS = os.path.join(SCRIPTS, "memory_ops", "__init__.py")

# 全局：隔离库测试用 lexical 后端，避免拉模型
os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"
sys.path.insert(0, SCRIPTS)

import memory_ops as mo  # noqa: E402
import keeper_mcp_server as km  # noqa: E402
import keeper_import as ki  # noqa: E402


def _cli(env_extra, *args):
    """以独立子进程跑引擎 CLI（与现有门禁测试一致），返回解析后的 JSON。"""
    env = dict(os.environ)
    env["AI_MEM_EMBED_BACKEND"] = "lexical"
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, OPS, *args], capture_output=True,
                       text=True, encoding="utf-8", env=env, timeout=180)
    try:
        return json.loads(p.stdout.strip() or "{}")
    except Exception:
        return {"_raw": p.stdout, "_rc": p.returncode, "_err": p.stderr[-400:]}


class ImportEncodingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_imp_")

    def _import(self, path, **kw):
        args = ["import", "--root", self.root, "--file", path]
        for k, v in kw.items():
            args += ["--" + k.replace("_", "-"), str(v)]
        return _cli({}, *args)

    def test_bom_csv_not_silent(self):
        # B1：Excel「UTF-8 带 BOM」导出 → 此前首列名被 \\ufeff 污染静默 imported=0
        p = os.path.join(self.root, "bom.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            f.write("summary,category\n中文测试记忆,分类A\n")
        r = self._import(p)
        self.assertTrue(r.get("ok"), "BOM CSV 应成功导入，实际 %r" % r)
        self.assertEqual(r.get("imported"), 1, "BOM CSV imported 应为 1，实际 %r" % r)
        self.assertEqual(r.get("dropped", 0), 0, "BOM CSV 不应有丢弃，实际 %r" % r)

    def test_gbk_csv_importable(self):
        # C1/B2：GBK 为 Excel 常见导出编码，应可导入（utf-8-sig 失败回退 gbk）
        p = os.path.join(self.root, "gbk.csv")
        with open(p, "w", encoding="gbk", newline="") as f:
            f.write("summary,category\n股票均线策略回测,量化\n")
        r = self._import(p)
        self.assertTrue(r.get("ok"), "GBK CSV 应成功导入，实际 %r" % r)
        self.assertGreaterEqual(r.get("imported", 0), 1, "GBK CSV imported>=1，实际 %r" % r)

    def test_unsupported_encoding_clear_error(self):
        # B2：UTF-16 等非支持编码 → 清晰编码错误（仍是 parse_error 类型，但 msg 指明编码）
        p = os.path.join(self.root, "utf16.csv")
        with open(p, "w", encoding="utf-16", newline="") as f:
            f.write("summary,category\nx,y\n")
        r = self._import(p)
        self.assertFalse(r.get("ok"), "UTF-16 应导入失败，实际 %r" % r)
        self.assertEqual(r.get("error"), "parse_error")
        self.assertIn("编码", (r.get("msg") or ""), "报错应指明编码问题，实际 %r" % r)


class ImportDroppedCountTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_drop_")

    def test_dropped_records_counted(self):
        # B4/C3：非字典 / 缺 summary+body 的记录计入 dropped，不再静默丢失
        p = os.path.join(self.root, "mix.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"summary": "good one", "category": "A"}, ensure_ascii=False) + "\n")
            f.write('"a string not dict"\n')                       # 非字典 → dropped
            f.write(json.dumps({"body": "only body ok"}, ensure_ascii=False) + "\n")  # 有 body → 归一
            f.write(json.dumps({"category": "x"}, ensure_ascii=False) + "\n")         # 无 summary 无 body → dropped
        r = _cli({}, "import", "--root", self.root, "--file", p)
        self.assertTrue(r.get("ok"), "导入应成功，实际 %r" % r)
        self.assertEqual(r.get("total_parsed"), 4, "total_parsed 应为 4，实际 %r" % r)
        self.assertEqual(r.get("normalized"), 2, "normalized 应为 2，实际 %r" % r)
        self.assertEqual(r.get("dropped"), 2, "dropped 应为 2，实际 %r" % r)
        self.assertIn("dropped_reasons", r, "返回应含 dropped_reasons")


class ImportAbortNotByQuarantineTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_abort_")

    def test_abort_skips_quarantine(self):
        # B5：敏感记录被隔离(quarantine)是成功安全结果，不触发 --on-error abort
        p = os.path.join(self.root, "q.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"summary": "clean record one", "category": "A"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"summary": "password: TopSecret999", "category": "B"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"summary": "clean record three should import", "category": "A"}, ensure_ascii=False) + "\n")
        r = _cli({}, "import", "--root", self.root, "--file", p, "--on-error", "abort", "--execute")
        self.assertTrue(r.get("ok"), "导入应成功，实际 %r" % r)
        self.assertEqual(r.get("imported"), 2, "隔离不应触发 abort，clean 两条都应导入，实际 %r" % r)
        self.assertEqual(r.get("quarantined"), 1, "敏感应被隔离 1 条，实际 %r" % r)


class BenchmarkGuardTest(unittest.TestCase):
    def test_refuse_default_root(self):
        # B6：引擎 benchmark 不传 --root 应拒绝（exit 2），不污染真实库
        env = dict(os.environ)
        env["AI_MEM_EMBED_BACKEND"] = "lexical"
        p = subprocess.run([sys.executable, OPS, "benchmark"], capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=60)
        self.assertEqual(p.returncode, 2, "无 --root 的 benchmark 应 exit 2，实际 %d" % p.returncode)
        try:
            r = json.loads(p.stdout.strip() or "{}")
        except Exception:
            r = {}
        self.assertEqual(r.get("error"), "refuse_default_root")

    def test_isolated_run_ok(self):
        # B6/C4：显式 --root 隔离目录可正常跑（桥 benchmark 透传即走此路径）
        root = tempfile.mkdtemp(prefix="keeper_bench_")
        r = _cli({}, "benchmark", "--root", root, "--n", "3",
                "--recall-times", "2", "--top-n", "3", "--topics", "5")
        self.assertTrue(r.get("ok"), "隔离 benchmark 应成功，实际 %r" % r)


class McpExportAndErrorTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_mcp_")
        mo.init_store(self.root)
        for i in range(5):
            mo.deposit(self.root, category="c", summary="mem %d topic kw" % i,
                       tags="t", body="body %d" % i, recorded_by="t")

    def test_export_md_block_aware(self):
        # B3：md + limit 按 ## 记忆块截断，保留完整块（不切断单条中间）
        r = km._call_tool(self.root, "export", {"fmt": "md", "limit": 2})
        self.assertFalse(r.get("isError"), "export 不应报错")
        txt = r["content"][0]["text"]
        self.assertEqual(txt.count("## "), 2, "md limit=2 应保留 2 个完整记忆块，实际 %r" % txt[-120:])

    def test_export_jsonl_line_truncate(self):
        # md 之外的 jsonl 仍按行安全截断
        r = km._call_tool(self.root, "export", {"fmt": "jsonl", "limit": 2})
        txt = r["content"][0]["text"]
        lines = [l for l in txt.split("\n") if l.strip()]
        self.assertLessEqual(len(lines), 2, "jsonl limit=2 不应超过 2 行")

    def test_deposit_missing_summary_structured_error(self):
        # O3/C5：缺必填 summary → 结构化错误（含异常类型），非 cryptic
        r = km._call_tool(self.root, "deposit", {"category": "c"})
        self.assertTrue(r.get("isError"), "缺 summary 应 isError")
        payload = json.loads(r["content"][0]["text"])
        self.assertEqual(payload.get("ok"), False)
        self.assertEqual(payload.get("error"), "missing_required_field")


class ImportResultsCapTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_cap_")

    def test_results_truncated_and_total_exposed(self):
        # O5：超大批量时逐条 results 应被截断防内存膨胀，
        # 但 results_total 暴露真实总量，不影响计数契约。
        saved_cap = ki.RESULTS_CAP
        ki.RESULTS_CAP = 3  # 小值便于快测
        try:
            p = os.path.join(self.root, "big.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                for i in range(10):
                    f.write(json.dumps({"summary": "mem %d" % i, "category": "A"},
                                       ensure_ascii=False) + "\n")
            out = ki.run_import(self.root, p)
        finally:
            ki.RESULTS_CAP = saved_cap
        self.assertTrue(out.get("ok"), "导入应成功，实际 %r" % out)
        self.assertEqual(out.get("imported"), 10, "imported 应为 10，实际 %r" % out)
        self.assertEqual(out.get("results_total"), 10, "results_total 应=10，实际 %r" % out)
        self.assertTrue(out.get("results_truncated"), "应标记 results_truncated")
        self.assertLessEqual(len(out.get("results", [])), 3, "results 应被截断到 <=3")


if __name__ == "__main__":
    unittest.main()
