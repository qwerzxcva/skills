# -*- coding: utf-8 -*-
""" 相位 E 回归测试：verify_investment 不再静默 skipped。

锁定新语义：
· 缺 DuckDB / sql_map / DuckDB 不可用 → 投资记忆本应校验却未校验 → needs_setup（不再 skipped）；
· 已具备 DB+sql_map 但本记忆指标无可用 SQL → skipped（正常『无需复算』）；
· 真正无投资记忆 / 无数值 attrs → 既不 needs_setup 也不 skipped（本就无需校验）；
· 附带 default_sql_map_template + setup_hint 引导 bootstrap。
用临时隔离 store 跑，绝不触碰真实记忆库。
"""
import os
import sys
import json
import shutil
import subprocess
import tempfile
import unittest

PY = sys.executable
SKILL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MEM = os.path.join(SKILL, "scripts", "memory_ops", "__init__.py").replace("\\", "/")

_TEST_HOME = None
_TEST_WS = None

def _get_test_home():
    global _TEST_HOME
    if _TEST_HOME is None:
        _TEST_HOME = tempfile.mkdtemp(prefix="keeper_e_home_")
    return _TEST_HOME

def _get_test_ws():
    global _TEST_WS
    if _TEST_WS is None:
        _TEST_WS = tempfile.mkdtemp(prefix="keeper_e_ws_")
        os.makedirs(os.path.join(_TEST_WS, ".workbuddy", "memory"), exist_ok=True)
    return _TEST_WS

def run(*args, root=None, expect_fail=False):
    cmd = [PY, MEM] + [str(a) for a in args]
    if root:
        cmd += ["--root", root]
    env = dict(os.environ)
    _h = _get_test_home()
    env["HOME"] = _h
    env["USERPROFILE"] = _h
    env["WORKBUDDY_WORKSPACE"] = _get_test_ws()
    env.pop("AI_MEMORY_STORE", None)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    if expect_fail:
        return p
    if p.returncode != 0:
        raise AssertionError("cmd %s rc=%d\nstderr=%s" % (args, p.returncode, p.stderr[:800]))
    try:
        return json.loads(p.stdout)
    except Exception:
        raise AssertionError("bad json rc=%d stdout=%s" % (p.returncode, p.stdout[:400]))

def read_mem_files(root):
    out = {}
    for sub in ("memories", "memories/archive", "store"):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            try:
                fns = os.listdir(d)
            except Exception:
                continue
            for fn in fns:
                if not fn.endswith(".json"):
                    continue
                try:
                    out[fn] = json.load(open(os.path.join(d, fn), encoding="utf-8"))
                except Exception:
                    pass
    return out

def _have_duckdb():
    try:
        import duckdb  # noqa
        return True
    except Exception:
        return False


class PhaseEVerifyTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_phase_e_")
        self.root = os.path.join(self.tmp, "store").replace("\\", "/")
        run("init", root=self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _deposit_investment(self):
        run("deposit", "--category", "investment", "--summary", "某策略年化回测 18%",
            "--tags", '["invest","backtest"]', "--body", "策略回测结果",
            "--attr", "annual_return=18.0", "--domain", "investment", root=self.root)

    def test_no_investment_no_needs_setup(self):
        # 非投资记忆：verify 不应产生 needs_setup 也不应 skipped（本就无需校验）
        run("deposit", "--summary", "一般开发笔记", "--tags", '["dev"]',
            "--body", "note", "--attr", "lines=10", root=self.root)
        r = run("verify-investment", root=self.root)
        self.assertEqual(r["checked"], 0, r)
        self.assertEqual(r["needs_setup"], 0, r)
        self.assertEqual(r["skipped"], 0, r)
        self.assertTrue(r["ok"])

    def test_needs_setup_when_no_db(self):
        # 缺 DuckDB / sql_map：投资记忆本应校验却未校验 → needs_setup（相位 E 核心）
        self._deposit_investment()
        r = run("verify-investment", root=self.root)
        self.assertGreaterEqual(r["checked"], 1, r)
        self.assertGreaterEqual(r["needs_setup"], 1, r)
        self.assertEqual(r["skipped"], 0, r)
        self.assertTrue(r["ok"])
        # 引导产物必须随附
        self.assertIsInstance(r.get("default_sql_map_template"), dict, r)
        self.assertTrue(r.get("setup_hint"), r)
        # 零写入：记忆 verified 仍为 None（未误判）
        mems = read_mem_files(self.root)
        inv = [m for m in mems.values() if m.get("domain") == "investment"]
        self.assertTrue(inv, "记忆文件未落盘")
        self.assertIsNone(inv[0].get("verified"), "needs_setup 不应触发写库")

    def test_skipped_when_ready_but_no_sql(self):
        # 已具备 DB+sql_map（但映射为空）→ 本记忆指标无可用 SQL → skipped（正常无需复算）
        if not _have_duckdb():
            self.skipTest("duckdb 不可用，跳过需 DB 的用例")
        self._deposit_investment()
        dbp = os.path.join(self.tmp, "inv.duckdb").replace("\\", "/")
        import duckdb
        conn = duckdb.connect(dbp)
        conn.execute("CREATE TABLE m(name VARCHAR, val DOUBLE);")
        conn.execute("INSERT INTO m VALUES ('annual_return', 18.0);")
        conn.close()
        sqlmap = os.path.join(self.tmp, "empty_map.json").replace("\\", "/")
        json.dump({}, open(sqlmap, "w", encoding="utf-8"))
        r = run("verify-investment", "--duckdb", dbp, "--sql-map", sqlmap, root=self.root)
        self.assertGreaterEqual(r["checked"], 1, r)
        self.assertEqual(r["needs_setup"], 0, r)
        self.assertGreaterEqual(r["skipped"], 1, r)
        self.assertTrue(r.get("setup_ready"), r)

    def test_verified_true_when_matches(self):
        # DB+sql_map 匹配 → 复算一致 → verified_true，且写库标记 verified=True
        if not _have_duckdb():
            self.skipTest("duckdb 不可用，跳过需 DB 的用例")
        self._deposit_investment()
        dbp = os.path.join(self.tmp, "inv.duckdb").replace("\\", "/")
        import duckdb
        conn = duckdb.connect(dbp)
        conn.execute("CREATE TABLE m(name VARCHAR, val DOUBLE);")
        conn.execute("INSERT INTO m VALUES ('annual_return', 18.0);")
        conn.close()
        sqlmap = os.path.join(self.tmp, "map.json").replace("\\", "/")
        json.dump({"annual_return": "SELECT val FROM m WHERE name='annual_return'"},
                  open(sqlmap, "w", encoding="utf-8"))
        r = run("verify-investment", "--duckdb", dbp, "--sql-map", sqlmap,
                root=self.root)
        self.assertGreaterEqual(r["verified_true"], 1, r)
        mems = read_mem_files(self.root)
        inv = [m for m in mems.values() if m.get("domain") == "investment"]
        self.assertTrue(inv[0].get("verified") is True, "复算一致未标记 verified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
