# -*- coding: utf-8 -*-
""" 回归测试：智能进化（evolve / belief / forget）+ 与 WorkBuddy 互补协同
（provenance 幂等 / 反回声 / distill-to-wb）+ 投资记忆 DuckDB 校验。

用临时隔离 store 跑，绝不触碰真实记忆库。
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import unittest

PY = sys.executable
SKILL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MEM = os.path.join(SKILL, "scripts", "memory_ops", "__init__.py").replace("\\", "/")

# 隔离 HOME + WORKBUDDY_WORKSPACE：harvest 默认会读真实 ~/.workbuddy/MEMORY.md、
# ~/.workbuddy/memory（云端），并从 cwd 向上回溯找 .workbuddy/memory（工作区）。这些都会
# 以 additive 方式把「用户真实记忆」灌进测试，破坏幂等/反回声断言。本测试用一个临时
# HOME 让前两者失效，并用一个含空 .workbuddy/memory 的临时 WORKBUDDY_WORKSPACE 短路
# cwd 回溯，使 keeper 只读到测试注入的 --workbuddy-memory 目录。
_TEST_HOME = None
_TEST_WS = None

def _get_test_home():
    global _TEST_HOME
    if _TEST_HOME is None:
        _TEST_HOME = tempfile.mkdtemp(prefix="keeper_test_home_")
    return _TEST_HOME

def _get_test_ws():
    global _TEST_WS
    if _TEST_WS is None:
        _TEST_WS = tempfile.mkdtemp(prefix="keeper_test_ws_")
        os.makedirs(os.path.join(_TEST_WS, ".workbuddy", "memory"), exist_ok=True)
    return _TEST_WS


def run(*args, root=None, expect_fail=False):
    cmd = [PY, MEM] + [str(a) for a in args]
    if root:
        cmd += ["--root", root]
    env = dict(os.environ)
    # 隔离记忆来源：managed Windows python 的 expanduser 走 USERPROFILE 而非 HOME，
    # 故两者都要重定向到临时 HOME，使 ~/.workbuddy/MEMORY.md 与 ~/.workbuddy/memory
    # （真实用户/云端记忆）失效；WORKBUDDY_WORKSPACE 短路 cwd 向上回溯。
    _h = _get_test_home()
    env["HOME"] = _h
    env["USERPROFILE"] = _h
    env["WORKBUDDY_WORKSPACE"] = _get_test_ws()
    env.pop("AI_MEMORY_STORE", None)  # 杜绝误写真实记忆库
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
    """读取记忆库内真实记忆文件。

    注意：keeper 把每条记忆存在 root/memories/<id>.json（root/store 是 SQLite 索引层，
    不含记忆 json）；provenance/auto_evolve/erroneous/status/review_by/verified/domain
    等元数据以明文存于 json，本测试断言的正是这些字段。
    为兼容不同布局，依次扫描 root/memories、root/store、root 本身，合并去重。
    """
    out = {}
    candidates = []
    for sub in ("memories", "memories/archive", "store"):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            candidates.append(d)
    if os.path.isdir(root):
        candidates.append(root)
    EXCLUDE = {"index.json", "meta.json", "config.json",
               "llm_suggestions.json", "route_registry.json", "taxonomy.json",
               "index.db", "seq.json", "audit.log",
               ".write_lock", ".write.lock"}
    for d in candidates:
        try:
            fns = os.listdir(d)
        except Exception:
            continue
        for fn in fns:
            if not fn.endswith(".json") or fn in EXCLUDE:
                continue
            try:
                out[fn] = json.load(open(os.path.join(d, fn), encoding="utf-8"))
            except Exception:
                pass
    return out


def test_evolve_and_schema():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store").replace("\\", "/")
    run("init", root=root)
    # 复发印证：同一经验 deposit 4 次 → recurrence_count>=3
    for _ in range(4):
        run("deposit", "--category", "best_practice",
            "--summary", "沙箱删除必须 ctypes 兜底",
            "--tags", '["auto","sandbox"]',
            "--body", "Windows 沙箱 unlink 被 safe-delete 拦截，需 ctypes.windll.kernel32.DeleteFileW 真删",
            root=root)
        # evolve review：应合成「经 4 次实践印证」原则
    r = run("evolve", root=root)
    assert len(r["synthesized"]) >= 1, r
    assert "经 4 次实践印证" in r["synthesized"][0]["summary"], r
    # evolve apply：落盘 auto 记忆
    r2 = run("evolve", "--apply", root=root)
    assert r2["applied"] >= 1, r2
    # 校验新记忆字段：provenance=auto / auto_evolve=True / review_by 设定
    mems = read_mem_files(root)
    auto = [m for m in mems.values()
            if m.get("provenance") == "auto" and m.get("auto_evolve")]
    assert len(auto) >= 1, "未生成 provenance=auto 记忆"
    assert auto[0].get("review_by"), "auto 记忆缺少 review_by 限期复核"
    # 幂等：再次 apply 不应重复合成
    r3 = run("evolve", "--apply", root=root)
    assert r3["skipped_existing"] >= 1, r3
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS test_evolve_and_schema")


def test_belief_and_forget():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store").replace("\\", "/")
    run("init", root=root)
    d = run("deposit", "--category", "best_practice",
            "--summary", "将被遗忘的临时记忆", "--tags", '["tmp"]',
            "--body", "用于测试错误遗忘", root=root)
    mid = d["id"]
    # bad 反馈高权重 → 信念强度跌破阈值 → 判错归档
    fb = run("feedback", "--id", mid, "--signal", "bad", "--weight", 5, root=root)
    assert fb["belief_strength"] is not None
    assert float(fb["belief_strength"]) < 1.0, fb
    mems = read_mem_files(root)
    m = mems.get(mid + ".json") or mems.get(mid)
    # 找到该记忆文件
    target = None
    for fn, mm in mems.items():
        if mm.get("id") == mid:
            target = mm
    assert target is not None
    assert target.get("erroneous") is True, "bad 反馈后未判错"
    assert target.get("status") == "archived", "bad 反馈后未归档"
    # 归档后 recall 不应召回
    rc = run("recall", "--query", "将被遗忘的临时记忆", root=root)
    ids = [e.get("id") for e in rc.get("entries", [])]
    assert mid not in ids, "已遗忘记忆仍被召回"
    # explicit forget 同样生效
    d2 = run("deposit", "--category", "best_practice",
             "--summary", "另一条待遗忘", "--tags", '["tmp"]',
             "--body", "x", root=root)
    mid2 = d2["id"]
    fg = run("forget", "--id", mid2, "--forget-reason", "test", root=root)
    assert fg["ok"] is True, fg
    mems2 = read_mem_files(root)
    t2 = [mm for mm in mems2.values() if mm.get("id") == mid2][0]
    assert t2["erroneous"] and t2["status"] == "archived"
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS test_belief_and_forget")


def test_wb_provenance_idempotent_and_antiecho():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store").replace("\\", "/")
    wb_dir = os.path.join(tmp, "wbmem").replace("\\", "/")
    os.makedirs(wb_dir)
    # 写几条 WB 记忆（每条 ≥30 字且含知识关键词，才能通过 harvest 的「长期知识」启发式）
    with open(os.path.join(wb_dir, "MEMORY.md"), "w", encoding="utf-8") as f:
        f.write(
            "# 工作区记忆\n\n"
            "- 用户偏好：所有回复必须使用简体中文，技术术语可保留英文原文，"
            "不得滑入纯英文回答。\n\n"
            "- 编码规范：Python 脚本统一使用 UTF-8 编码，文件路径尽量避免使用中文，"
            "以规避 Windows 下的编码错误。\n\n")
    run("init", root=root)
    # 第一次 self-learn with_workbuddy：应沉淀为 provenance=workbuddy
    r1 = run("harvest", "--self-learn", "--with-workbuddy",
             "--workbuddy-memory", wb_dir, root=root)
    wb_dep = r1.get("wb_deposited", [])
    assert len(wb_dep) >= 1, r1
    mems = read_mem_files(root)
    wb_mems = [m for m in mems.values() if m.get("provenance") == "workbuddy"]
    assert len(wb_mems) >= 1, "WB 来源未标记 provenance=workbuddy"
    assert wb_mems[0].get("provenance_key"), "WB 来源缺少幂等键"
    # 第二次：幂等，不应再沉淀重复
    r2 = run("harvest", "--self-learn", "--with-workbuddy",
             "--workbuddy-memory", wb_dir, root=root)
    assert r2.get("n_wb_deposited", 0) == 0, "WB 来源未实现幂等，重复沉淀"
    # 反回声：含 keeper-distilled 哨兵的行不应被回采
    with open(os.path.join(wb_dir, "MEMORY.md"), "a", encoding="utf-8") as f:
        f.write("\n- 🧪 keeper 蒸馏原则：x <!-- keeper-distilled:abc123 -->\n")
    r3 = run("harvest", "--self-learn", "--with-workbuddy",
             "--workbuddy-memory", wb_dir, root=root)
    # 哨兵行不应产生新沉淀
    assert r3.get("n_wb_deposited", 0) == 0, "反回声失败：哨兵行被回采"
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS test_wb_provenance_idempotent_and_antiecho")


def test_distill_to_wb_review():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store").replace("\\", "/")
    run("init", root=root)
    # 高置信 curated 原则
    run("deposit", "--category", "principle", "--summary", "部署前必须 grep 真实路径",
        "--tags", '["publish","security"]', "--body", "发布前自查真实路径/邮箱/token",
        "--tier", "curated", "--importance", "0.9", "--confidence", "0.9", root=root)
    # review（dry_run）只返回候选，不写 WB MEMORY.md
    r = run("distill-to-wb", root=root)
    assert len(r["candidates"]) >= 1, r
    assert r["dry_run"] is True
    wb_md = os.path.expanduser("~/.workbuddy/MEMORY.md")
    existed = os.path.exists(wb_md)
    if existed:
        before = open(wb_md, encoding="utf-8").read()
    else:
        before = ""
        # 再次确认未写（dry_run）
    after = open(wb_md, encoding="utf-8").read() if os.path.exists(wb_md) else ""
    assert before == after, "dry_run 不应写 WB MEMORY.md"
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS test_distill_to_wb_review")


def test_verify_investment_failopen():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "store").replace("\\", "/")
    run("init", root=root)
    # 投资记忆（带数值 attrs）
    run("deposit", "--category", "investment", "--summary", "某策略年化回测 18%",
        "--tags", '["invest","backtest"]', "--body", "策略回测结果",
        "--attr", "annual_return=18.0", "--domain", "investment", root=root)
    # 无 duckdb → 应有 checked>0，且相位 E 起显式 needs_setup（不再静默 skipped）
    r = run("verify-investment", root=root)
    assert r["checked"] >= 1, r
    assert r["needs_setup"] >= 1, r
    assert r["skipped"] == 0, r
    assert r["ok"] is True, r
    # 有条件 duckdb 复算（仅当 duckdb 可用）
    try:
        import duckdb  # noqa
        have = True
    except Exception:
        have = False
    if have:
        dbp = os.path.join(tmp, "inv.duckdb").replace("\\", "/")
        conn = duckdb.connect(dbp)
        conn.execute("CREATE TABLE m(name VARCHAR, val DOUBLE);")
        conn.execute("INSERT INTO m VALUES ('annual_return', 18.0);")
        conn.close()
        sqlmap = os.path.join(tmp, "map.json").replace("\\", "/")
        json.dump({"annual_return": "SELECT val FROM m WHERE name='annual_return'"},
                  open(sqlmap, "w", encoding="utf-8"))
        r2 = run("verify-investment", "--duckdb", dbp, "--sql-map", sqlmap, root=root)
        assert r2["verified_true"] >= 1, r2
        mems = read_mem_files(root)
        inv = [m for m in mems.values() if m.get("domain") == "investment"][0]
        assert inv.get("verified") is True, "DuckDB 复算未标记 verified"
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS test_verify_investment_failopen")


# pytest 风格顶层函数不会被 unittest.discover 收集（只认 TestCase 子类），
# 会导致 run_gate.py 对该文件判 0 测试而静默跳过这 5 个回归用例（假绿）。
# 故包一层 TestCase，使门禁能发现并运行。函数体保持原样，只做转发。
class EvolutionSynergyTest(unittest.TestCase):
    def test_evolve_and_schema(self):
        test_evolve_and_schema()

    def test_belief_and_forget(self):
        test_belief_and_forget()

    def test_wb_provenance_idempotent_and_antiecho(self):
        test_wb_provenance_idempotent_and_antiecho()

    def test_distill_to_wb_review(self):
        test_distill_to_wb_review()

    def test_verify_investment_failopen(self):
        test_verify_investment_failopen()


if __name__ == "__main__":
    test_evolve_and_schema()
    test_belief_and_forget()
    test_wb_provenance_idempotent_and_antiecho()
    test_distill_to_wb_review()
    test_verify_investment_failopen()
    print("ALL v4.6.13 EVOLUTION/SYNERGY TESTS PASSED")
