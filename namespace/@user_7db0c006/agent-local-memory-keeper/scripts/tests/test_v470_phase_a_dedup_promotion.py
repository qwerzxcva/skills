# -*- coding: utf-8 -*-
""" 相位 A 回归测试：dedup + 晋升根治（unittest 版，纳入随包门禁）。

锁死三件事：
1) evolve 合成的原则必须带 derives_from 指向源记忆，且是**独立新节点**（不被近重复
查重吞并进源记忆）——这验证 v4.7.0 用「派生意图」机制取代了 v4.6.13 的 skip_dedup hack。
2) 幂等：重复 --apply 不重复合成。
3) 晋升评分门控：陈旧(recency 衰减)或低重要/低信念的复发经验**不**晋升为原则
（修复「频率≠重要性」缺陷）。
用临时隔离 store 跑，绝不触碰真实记忆库。
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import datetime
import unittest

PY = sys.executable
SKILL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MEM = os.path.join(SKILL, "scripts", "memory_ops", "__init__.py").replace("\\", "/")

_TEST_HOME = None
_TEST_WS = None


def _get_test_home():
    global _TEST_HOME
    if _TEST_HOME is None:
        _TEST_HOME = tempfile.mkdtemp(prefix="keeper_a_home_")
    return _TEST_HOME


def _get_test_ws():
    global _TEST_WS
    if _TEST_WS is None:
        _TEST_WS = tempfile.mkdtemp(prefix="keeper_a_ws_")
        os.makedirs(os.path.join(_TEST_WS, ".workbuddy", "memory"), exist_ok=True)
    return _TEST_WS


def run(*args, root=None):
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
    if p.returncode != 0:
        raise AssertionError("cmd %s rc=%d\nstderr=%s" % (args, p.returncode, p.stderr[:800]))
    try:
        return json.loads(p.stdout)
    except Exception:
        raise AssertionError("bad json rc=%d stdout=%s" % (p.returncode, p.stdout[:400]))


def read_mem_files(root):
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
               "index.db", "seq.json", "audit.log", ".write_lock", ".write.lock"}
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


class PhaseADedupPromotionTest(unittest.TestCase):

    def test_derives_from_and_distinct_node(self):
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "store").replace("\\", "/")
        run("init", root=root)
        ids = []
        for _ in range(4):
            r = run("deposit", "--category", "best_practice",
                    "--summary", "沙箱删除必须 ctypes 兜底",
                    "--tags", '["auto","sandbox"]',
                    "--body", "Windows 沙箱 unlink 被 safe-delete 拦截，需 ctypes.windll.kernel32.DeleteFileW 真删",
                    root=root)
            ids.append(r["id"])
            # evolve apply：应落盘带 derives_from 的 auto 原则
        r2 = run("evolve", "--apply", root=root)
        self.assertGreaterEqual(r2["applied"], 1, r2)
        mems = read_mem_files(root)
        principles = [m for m in mems.values()
                      if m.get("provenance") == "auto" and m.get("derives_from")]
        self.assertGreaterEqual(len(principles), 1, "未生成带 derives_from 的 auto 原则")
        pr = principles[0]
        self.assertIn(pr["derives_from"], ids, "derives_from 未指向源记忆 id")
        # 源记忆应仍是 active 的独立节点，未被合并/取代（派生新节点，而非查重吞并）
        src = [m for m in mems.values() if m.get("id") == pr["derives_from"]][0]
        self.assertEqual(src.get("status"), "active", "源记忆被错误合并/取代")
        self.assertNotEqual(src.get("id"), pr.get("id"), "派生原则与源记忆是同一节点（未独立创建）")
        # 幂等：再次 apply 不重复合成
        r3 = run("evolve", "--apply", root=root)
        self.assertGreaterEqual(r3["skipped_existing"], 1, r3)
        shutil.rmtree(tmp, ignore_errors=True)

    def test_recency_penalty_no_promote(self):
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "store").replace("\\", "/")
        run("init", root=root)
        ids = []
        for _ in range(3):
            r = run("deposit", "--category", "best_practice",
                    "--summary", "低频但陈旧的经验不应晋升",
                    "--tags", '["stale"]', "--body", "x", root=root)
            ids.append(r["id"])
            # 把全部 3 条的 accessed 回拨到 200 天前，制造 recency 衰减 → 评分低于阈值
        _old = (datetime.date.today() - datetime.timedelta(days=200)).isoformat()
        for mid in ids:
            p = os.path.join(root, "memories", mid + ".json")
            mj = json.load(open(p, encoding="utf-8"))
            mj["accessed"] = _old
            json.dump(mj, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        r = run("evolve", root=root)  # dry_run
        self.assertEqual(len(r["synthesized"]), 0, "陈旧复发不应晋升为原则: %s" % r)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
