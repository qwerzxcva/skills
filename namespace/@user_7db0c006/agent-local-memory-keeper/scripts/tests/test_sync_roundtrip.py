# -*- coding: utf-8 -*-
"""keeper_sync.py 跨设备同步端到端回归（4.9.1 新增功能）。

全程在 tempfile 临时目录内跑：A 机 = 真实记忆库的**只读子集副本**（见 _copy_ignore：
排除无关归档、memories 只留最近 AI_MEM_SYNC_TEST_MAX 条、不带 index.db），B 机 = 空库。
真实记忆库只读，绝不写入。

覆盖：
  S1 out 生成全量包（含 superseded/archived，filtered_out=0）+ meta + sha256
  S2 in 预演（不带 --execute）→ 不创建目标库、不写数据、不生成备份
  S3 in --execute → 条数落盘正确
  S4 同包重复导入 → 幂等，条数不变
  S5 损坏包（尾部追加 1 字节）→ sha256 拦截中止，rc=2 且零写入
  S6 环形同步：B 机新增 → out → A 机 in（keep_ids 覆盖，不膨胀）
  S7 状态收敛：同步后目标库状态/摘要与包内完全一致（防 archived 复活 + 双份副本）
"""
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)          # scripts/
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import memory_ops as mo  # noqa: E402
import keeper_sync as ks  # noqa: E402


def _n(root):
    try:
        return len(list(mo._iter_all_mems(root)))
    except Exception:  # noqa: BLE001
        return 0


def _sqlite_ids(root):
    """目标库 SQLite 权威源（store/index.db）里的全部记忆 id。

    SKILL.md 称 index.db 是权威源（含持久化向量），memories/*.json 是可读副本；
    keeper_sync 走的是 export/import（读 json → deposit），必须验证 SQLite 也落了。
    """
    db = os.path.join(root, "store", "index.db")
    if not os.path.isfile(db):
        return None
    con = sqlite3.connect(db)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        ids = set()
        for t in tables:
            cur.execute("PRAGMA table_info(%s)" % t)
            cols = [c[1] for c in cur.fetchall()]
            if "id" in cols:
                cur.execute("SELECT id FROM %s" % t)
                ids |= {r[0] for r in cur.fetchall() if r[0]}
        return ids
    finally:
        con.close()


# ── 真库体量解耦（P6 修复，4.9.25）────────────────────────────────────────
# 本模块长期直接 `copytree(真库)`，用例耗时于是**线性绑定真库体量**：
#   · 真库里的历史归档（_retired_tmp_*/memories_bak_*/quarantine/）与同步无关，
#     却每次整锅复制；
#   · store/index.db（真库 41MB）是召回加速镜像，而同步走的是**文件层**
#     （export_memories → _iter_all_mems）。A 机只作同步源，不需要它；留下全量 DB
#     反而与裁剪后的文件层不一致。
#   · 最要命的是逐条全流程往返：真库 196 条 × 多轮 × 每条 0.1~3s，实测单条用例
#     17 分钟仍不收敛，把整个发版门禁拖到 1800s 超时（见 _gate_timeout_4.9.24.md）。
# 故：排除无关归档 + memories 根目录只留最近 N 条 + 不复制 index.db。
# N 用 AI_MEM_SYNC_TEST_MAX 覆盖（0 = 不限，退回旧行为）。
def _int_env(name, dflt):
    try:
        return int(os.environ.get(name, "") or dflt)
    except (TypeError, ValueError):
        return dflt


_MEM_MAX = _int_env("AI_MEM_SYNC_TEST_MAX", 60)
_SKIP_DIR_NAMES = {"__pycache__", ".git", ".workbuddy", "quarantine"}
_SKIP_DIR_PREFIX = ("_retired_tmp", "memories_bak", "machineA_bak", "machineB_bak")
_SKIP_DIR_SUFFIX = ("_bak", "_bak2")


def _copy_ignore(src_root, keep_names):
    """copytree 的 ignore 回调：排除无关归档、未入选的 memories、以及 index.db*。"""
    mdir = os.path.normcase(os.path.join(src_root, "memories"))
    sdir = os.path.normcase(os.path.join(src_root, "store"))

    def _ignore(dirpath, names):
        skip = set()
        dp = os.path.normcase(dirpath)
        for n in names:
            if os.path.isdir(os.path.join(dirpath, n)):
                if (n in _SKIP_DIR_NAMES or n.startswith(_SKIP_DIR_PREFIX)
                        or n.endswith(_SKIP_DIR_SUFFIX)):
                    skip.add(n)
                continue
            if dp == mdir and n.endswith(".json") and n not in keep_names:
                skip.add(n)
                continue
            if dp == sdir and n.startswith("index.db"):
                skip.add(n)
        return skip

    return _ignore


class TestKeeperSyncRoundtrip(unittest.TestCase):
    """跨设备同步全流程（A→B→A 环形）。"""

    @classmethod
    def setUpClass(cls):
        cls.real = os.environ.get("AI_MEMORY_STORE") or mo.DEFAULT_ROOT
        if not os.path.isdir(cls.real):
            raise unittest.SkipTest("真实记忆库不可用：%s" % cls.real)
        cls.base = tempfile.mkdtemp(prefix="keeper_sync_test_")
        cls.A = os.path.join(cls.base, "machineA")
        cls.B = os.path.join(cls.base, "machineB")
        cls.sync = os.path.join(cls.base, "sync")
        os.makedirs(cls.sync, exist_ok=True)
        # 只复制「与同步有关」的那部分真库（见 _copy_ignore 说明）
        mdir = os.path.join(cls.real, "memories")
        allm = (sorted(f for f in os.listdir(mdir) if f.endswith(".json"))
                if os.path.isdir(mdir) else [])
        keep = set(allm) if _MEM_MAX <= 0 else set(allm[-_MEM_MAX:])
        cls.copied_mems, cls.trimmed_mems = len(keep), len(allm) - len(keep)
        shutil.copytree(cls.real, cls.A,
                        ignore=_copy_ignore(cls.real, keep))   # 只读副本，保护真库
        cls.a0 = _n(cls.A)
        if cls.a0 == 0:
            raise unittest.SkipTest("真实记忆库为空，无法验证同步")
        if cls.trimmed_mems > 0:
            sys.stderr.write(
                "[sync-test] 真库 memories 根目录 %d 条 → 本次复制最近 %d 条"
                "（裁掉 %d 条；只为把用例耗时与真库体量解耦，"
                "AI_MEM_SYNC_TEST_MAX=0 可退回全量）\n"
                % (len(allm), cls.copied_mems, cls.trimmed_mems))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_full_roundtrip(self):
        A, B, sync = self.A, self.B, self.sync
        a0 = self.a0

        # S1 —— out 全量包
        rc = ks.main(["out", "--dest", sync, "--root", A])
        pkgs = sorted(glob.glob(os.path.join(sync, "keeper_sync_*.jsonl")))
        self.assertEqual(rc, 0, "out 返回非零")
        self.assertEqual(len(pkgs), 1, "应只生成 1 个同步包，实际 %d" % len(pkgs))
        pkg = pkgs[0]
        meta = json.load(open(pkg[:-6] + ".meta.json", encoding="utf-8"))
        self.assertEqual(meta["count"], a0,
                         "包条数(%s) 应等于 A 机全量(%s)" % (meta["count"], a0))
        self.assertEqual(meta.get("filtered_out"), 0,
                         "filtered_out 应为 0（不应静默少导）")
        sha = hashlib.sha256(open(pkg, "rb").read()).hexdigest()
        self.assertEqual(sha, meta["sha256"], "meta.sha256 与文件内容不一致")

        # S2 —— 预演不落盘
        rc = ks.main(["in", "--dir", sync, "--root", B])
        self.assertEqual(rc, 0, "预演返回非零")
        self.assertEqual(_n(B), 0, "预演不应写入目标库")
        self.assertFalse(
            any(d.startswith("machineB_bak_") for d in os.listdir(self.base)
                if os.path.isdir(os.path.join(self.base, d))),
            "预演不应生成备份目录")

        # S3 —— 真正落盘
        rc = ks.main(["in", "--dir", sync, "--root", B, "--execute"])
        self.assertEqual(rc, 0, "落盘返回非零")
        b1 = _n(B)
        self.assertEqual(b1, meta["count"],
                         "落盘条数(%s) 应等于包条数(%s)" % (b1, meta["count"]))

        # S4 —— 幂等
        ks.main(["in", "--dir", sync, "--root", B, "--execute", "--no-backup"])
        self.assertEqual(_n(B), b1, "同包重复导入应幂等，条数不变")

        # S7 —— 状态/摘要收敛（防 archived 复活 + 双份副本）
        pkg_map = {}
        for line in open(pkg, encoding="utf-8"):
            if line.strip():
                m = json.loads(line)
                pkg_map[m["id"]] = ((m.get("status") or "active"),
                                    (m.get("summary") or "").strip())
        a_map = {}
        for m in mo._iter_all_mems(B):
            a_map[m.get("id")] = ((m.get("status") or "active"),
                                  (m.get("summary") or "").strip())
        self.assertEqual(len(a_map), len(pkg_map),
                         "同步后条数应与包一致（无重复副本）")
        for mid, (st, sm) in a_map.items():
            self.assertEqual(pkg_map.get(mid, ("", ""))[0], st,
                             "id=%s 状态漂移: 包=%s 库=%s" % (mid, pkg_map.get(mid), st))
            self.assertEqual(pkg_map.get(mid, ("", ""))[1], sm,
                             "id=%s 摘要漂移（应保留摘要而非退化为 id）" % mid)

        # S5 —— 损坏包必须被拦截且零写入
        cor = pkg[:-6] + "_corrupt.jsonl"
        open(cor, "wb").write(open(pkg, "rb").read() + b"x")
        shutil.copy(pkg[:-6] + ".meta.json", cor[:-6] + ".meta.json")
        before = _n(B)
        rc = ks.main(["in", "--file", cor, "--root", B, "--execute", "--no-backup"])
        self.assertEqual(rc, 2, "损坏包应 rc=2 中止，实际 %s" % rc)
        self.assertEqual(_n(B), before, "损坏包不应写入任何数据")

        # S6 —— 环形同步：B 机新增 → 回导 A 机
        new_id = "LRN-SYNC-TEST-001"
        ks.mo.deposit(B, category="测试", tags=[],
                      summary="B 机专有经验：环形同步验证条目",
                      body="这条只存在于 B 机，用于验证 B→A 回导。",
                      tier="working", mid=new_id)
        ks.mo.flush_memory_index(B)
        self.assertEqual(_n(B), b1 + 1, "B 机新增失败")

        ks.main(["out", "--dest", sync, "--root", B])
        pkg_b = sorted(glob.glob(os.path.join(sync, "keeper_sync_*.jsonl")))[-1]
        meta_b = json.load(open(pkg_b[:-6] + ".meta.json", encoding="utf-8"))
        rc = ks.main(["in", "--file", pkg_b, "--root", A, "--execute"])
        self.assertEqual(rc, 0, "回导 A 机失败")
        has_new = any(m.get("id") == new_id for m in mo._iter_all_mems(A))
        self.assertTrue(has_new, "A 机未拿到 B 机新增条目")
        a1 = _n(A)
        self.assertEqual(a1, max(a0, meta_b["count"]),
                         "A 机条数异常膨胀：A=%s a0=%s pkgB=%s"
                         % (a1, a0, meta_b["count"]))

    def test_sqlite_authoritative_source_in_sync(self):
        """同步后 SQLite（store/index.db）与文件层 id 集合一致——防「只写 JSON 副本」。

        这是 4.9.1 实测的关键风险点：导入若只落 memories/*.json 而不落 SQLite，
        目标库召回会全部落空，但条数看起来完全正常。
        """
        ks.main(["out", "--dest", self.sync, "--root", self.A])
        rc = ks.main(["in", "--dir", self.sync, "--root", self.B, "--execute"])
        self.assertEqual(rc, 0, "同步落盘失败")
        file_ids = {m.get("id") for m in mo._iter_all_mems(self.B) if m.get("id")}
        self.assertTrue(file_ids, "目标库文件层为空")
        db_ids = _sqlite_ids(self.B)
        self.assertIsNotNone(db_ids, "目标库未生成 store/index.db")
        self.assertEqual(file_ids, db_ids,
                         "SQLite 与文件层不一致：仅文件 %s / 仅DB %s"
                         % (sorted(file_ids - db_ids)[:5], sorted(db_ids - file_ids)[:5]))

    def test_out_never_touches_source(self):
        """out 只读：导出前后源库条数与状态不变。"""
        before = sorted((m.get("id"), (m.get("status") or "active"))
                        for m in mo._iter_all_mems(self.A))
        ks.main(["out", "--dest", self.sync, "--root", self.A])
        after = sorted((m.get("id"), (m.get("status") or "active"))
                       for m in mo._iter_all_mems(self.A))
        self.assertEqual(before, after, "out 不应修改源库")


if __name__ == "__main__":
    unittest.main(verbosity=2)
