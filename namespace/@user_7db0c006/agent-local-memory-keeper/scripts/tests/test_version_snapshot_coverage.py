# -*- coding: utf-8 -*-
"""
test_version_snapshot_coverage.py — 锁定「写记忆即自动留版本快照」（根治版本覆盖率 2% 缺口）。

背景（2026-09-08 实测）：
    改前 `_snapshot_version` 只有 overwrite / rollback 两个**命令层**调用点，而真实写入真源是
    `_save_mem`（~55 处调用 / 15 个模块）与 `_write_mem`（deposit 落盘入口）。结果是除显式
    overwrite 外的一切修改都静默丢失历史 —— 实测 147 条记忆仅 3 条有版本（覆盖率 2.0%），
    `timeline` / `rollback` 沦为「有命令、无数据」。

修复：把版本快照收口进 `_save_mem` 与 `_write_mem` 两个写入真源，复用 keeper 2026-08-12
    根治索引双写漂移的同一手法（单一真源点，覆盖率 2%→100%）。

核心断言（本测试锁死这三条不变量，防止未来回归）：
    A. deposit 新建 → versions/ 自动留下 v1 基线（不再只有 overwrite 才有版本）；
    B. overwrite 修改 → 自动新增 v2，且 `versions --id` 能列出 v1+v2（timeline 可回放）；
    C. 幂等：同一版本号重复写入（touch / 高频访问更新）**不产生**新快照文件，
       杜绝「每次 recall 触摸都写一个版本」的磁盘爆炸。
"""
import os
import sys
import glob
import shutil
import tempfile
import unittest

# 与同目录用例一致的 sys.path 引导（保证 `python 本文件.py` 单跑也能过）
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (SKILL, os.path.join(SKILL, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 🔴 本模块直接读磁盘文件断言快照内容——前提是「落盘是明文」。
# （at-rest 加密能力已于 2026-09-15 移除，落盘一律明文，无需再钉 env 前提。）

import memory_ops as M  # noqa: E402


def _snaps(root, mid):
    """列出某记忆的全部版本快照文件名。"""
    d = os.path.join(root, "versions")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, "%s.v*.json" % mid)))


class VersionSnapshotCoverageTest(unittest.TestCase):

    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_ver_cov_")
        M.init_store(self.store)
        # 关掉神经后端，避免单测拉 90MB 模型（本用例只验版本落盘，不验向量）
        os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)
        os.environ.pop("AI_MEM_EMBED_BACKEND", None)

    # ── A. deposit 新建即留 v1 基线 ──
    def test_deposit_creates_v1_snapshot(self):
        M.deposit(self.store, summary="原始结论A", body="内容A",
                  tags=["t"], category="learning", mid="v1")
        self.assertEqual(_snaps(self.store, "v1"), ["v1.v1.json"],
                         "deposit 新建后必须自动留下 v1 版本基线（收口进 _write_mem）")

    # ── B. overwrite 修改即追加 v2，versions 可列出 ──
    def test_overwrite_appends_v2_and_listable(self):
        M.deposit(self.store, summary="原始结论A", body="内容A",
                  tags=["t"], category="learning", mid="v2")
        M.overwrite(self.store, "v2", summary="修正后的结论B", body="内容B")
        self.assertEqual(_snaps(self.store, "v2"), ["v2.v1.json", "v2.v2.json"])
        vs = M.versions(self.store, "v2")
        got = sorted(v["version"] for v in vs)
        self.assertEqual(got, [1, 2], "versions --id 必须能列出 v1+v2，供 timeline 回放")

    # ── C. 幂等：同版本重复写入不产生新快照 ──
    def test_repeated_write_same_version_is_idempotent(self):
        M.deposit(self.store, summary="结论", body="内容",
                  tags=["t"], category="learning", mid="v3")
        before = _snaps(self.store, "v3")
        for _ in range(5):
            M.touch(self.store, "v3")  # 高频访问路径（version 不变）
        after = _snaps(self.store, "v3")
        self.assertEqual(before, after,
                         "同一版本号重复写入必须幂等，不得产生新快照文件（防磁盘爆炸）")
        self.assertEqual(len(after), 1)

    # ── D. rollback 后仍可撤销：回滚产生新版本且内容正确 ──
    def test_rollback_restores_and_is_undoable(self):
        M.deposit(self.store, summary="原始结论A", body="内容A",
                  tags=["t"], category="learning", mid="v4")
        M.overwrite(self.store, "v4", summary="修正后的结论B", body="内容B")
        M.rollback(self.store, "v4", to_version=1, yes=True)
        mem, _ = M._load_mem(self.store, "v4")
        self.assertEqual(mem.get("summary"), "原始结论A", "rollback 必须真恢复到 v1 内容")
        # 回滚前的 v2 内容被快照为 v3 → 回滚本身也可撤销
        self.assertIn("v4.v3.json", _snaps(self.store, "v4"),
                      "回滚前状态须先快照，保证回滚操作本身可撤销")

    # ── E. 快照走加密路径，不留明文缺口（无加密配置时等价于明文，仅验不崩）──
    def test_snapshot_is_readable_json(self):
        import json
        M.deposit(self.store, summary="结论", body="内容",
                  tags=["t"], category="learning", mid="v5")
        sp = os.path.join(self.store, "versions", "v5.v1.json")
        with open(sp, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d.get("id"), "v5")
        self.assertEqual(d.get("summary"), "结论")


if __name__ == "__main__":
    unittest.main()
