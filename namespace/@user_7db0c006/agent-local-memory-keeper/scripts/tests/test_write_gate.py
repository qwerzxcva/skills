# -*- coding: utf-8 -*-
"""
test_write_gate.py — 锁定「写入门禁」：覆盖前必须留快照，留不下就中止（fail-closed）。

背景（4.9.5）：
    4.9.3 把版本快照收口进 `_save_mem` / `_write_mem` 两个写入真源，覆盖率 2%→100%。
    但快照发生在**写完之后**且异常被吞 —— 一旦快照失败（磁盘满/权限/加密错），
    旧内容已被覆盖、永久丢失，用户只看到一行 stderr 警告。
    这仍然是一条「没快照就覆盖」的路径。

    恒忆 memory-system 的 `commit_task.py` 有一条 keeper 此前没有的写入门禁：
    快照 → 覆盖 → manifest → daily → 索引，任一步失败即中止。
    本文件锁死 keeper 侧补齐后的同款不变量。

核心不变量：
    A. 新建（文件不存在）→ 门禁不拦，零额外开销；
    B. 旧版本快照缺失 → 门禁**补建**后再放行（内容 = 磁盘上的旧内容）；
    C. 快照建不出来 → 抛 MemoryWriteGateError 中止，**原文件一字未改**；
    D. 逃生通道有效：KEEPER_WRITE_GATE=0（或配置 write_gate=false）时放行。
"""
import os
import sys
import glob
import json
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (SKILL, os.path.join(SKILL, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 🔴 本模块直接读磁盘文件比对旧内容原样无损——前提是「落盘是明文」。
# （at-rest 加密能力已于 2026-09-15 移除，落盘一律明文，无需再钉 env 前提。）

import memory_ops as M  # noqa: E402


class WriteGateTest(unittest.TestCase):

    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_gate_")
        M.init_store(self.store)
        os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"  # 不拉 90MB 模型
        os.environ.pop("KEEPER_WRITE_GATE", None)

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)
        os.environ.pop("AI_MEM_EMBED_BACKEND", None)
        os.environ.pop("KEEPER_WRITE_GATE", None)

    # ── 小工具 ──
    def _new_mem(self, mid="G1", body="旧内容", ver=1):
        mem = {"id": mid, "summary": "摘要", "body": body, "version": ver,
               "status": "active", "tier": "hot", "tags": ["t"], "category": "learning"}
        M._save_mem(self.store, mid, mem)
        return mem

    def _disk_body(self, mid="G1"):
        p = os.path.join(self.store, "memories", mid + ".json")
        return json.load(open(p, encoding="utf-8")).get("body")

    def _snaps(self, mid="G1"):
        d = os.path.join(self.store, "versions")
        if not os.path.isdir(d):
            return []
        return sorted(os.path.basename(x) for x in glob.glob(os.path.join(d, "%s.v*.json" % mid)))

    # ── A. 新建不拦 ──
    def test_create_not_blocked(self):
        self._new_mem(mid="G1")
        self.assertEqual(self._disk_body("G1"), "旧内容")

    # ── B. 快照缺失 → 门禁补建（内容 = 旧内容） ──
    def test_gate_backfills_missing_snapshot(self):
        self._new_mem(mid="G1", body="旧内容", ver=1)
        shutil.rmtree(os.path.join(self.store, "versions"), ignore_errors=True)  # 抹掉全部快照
        self.assertEqual(self._snaps("G1"), [])

        mem, _ = M._load_mem(self.store, "G1")
        mem["version"] = 2
        mem["body"] = "新内容"
        M._save_mem(self.store, "G1", mem)          # 门禁应先补 v1 再放行

        self.assertIn("G1.v1.json", self._snaps("G1"))
        v1 = json.load(open(os.path.join(self.store, "versions", "G1.v1.json"), encoding="utf-8"))
        self.assertEqual(v1.get("body"), "旧内容")   # 快照保存的是**被覆盖掉的那份**
        self.assertEqual(self._disk_body("G1"), "新内容")

    # ── C. 快照建不出来 → 中止，原文件一字未改 ──
    def test_gate_blocks_when_snapshot_fails(self):
        self._new_mem(mid="G1", body="旧内容", ver=1)
        shutil.rmtree(os.path.join(self.store, "versions"), ignore_errors=True)
        # 让 versions 变成一个**文件**：_snapshot_version 的 makedirs 必然失败，
        # 模拟"磁盘满/权限不足"这类真实故障，而不是 monkeypatch 出来的假失败。
        open(os.path.join(self.store, "versions"), "w").close()

        mem, _ = M._load_mem(self.store, "G1")
        mem["version"] = 2
        mem["body"] = "新内容"
        with self.assertRaises(M.MemoryWriteGateError):
            M._save_mem(self.store, "G1", mem)

        self.assertEqual(self._disk_body("G1"), "旧内容")   # 旧内容完好无损
        self.assertEqual(self._snaps("G1"), [])
        os.remove(os.path.join(self.store, "versions"))

    # ── D. 逃生通道：env KEEPER_WRITE_GATE=0 ──
    def test_gate_off_allows_write(self):
        self._new_mem(mid="G1", body="旧内容", ver=1)
        shutil.rmtree(os.path.join(self.store, "versions"), ignore_errors=True)
        open(os.path.join(self.store, "versions"), "w").close()

        os.environ["KEEPER_WRITE_GATE"] = "0"
        self.assertFalse(M._write_gate_enabled(self.store))
        mem, _ = M._load_mem(self.store, "G1")
        mem["version"] = 2
        mem["body"] = "新内容"
        M._save_mem(self.store, "G1", mem)              # 门禁关 → 放行
        self.assertEqual(self._disk_body("G1"), "新内容")
        os.remove(os.path.join(self.store, "versions"))

    # ── 开关默认值与优先级 ──
    def test_default_on_and_env_overrides_config(self):
        self.assertTrue(M._write_gate_enabled(self.store))          # 默认开（fail-closed）
        os.environ["KEEPER_WRITE_GATE"] = "0"
        self.assertFalse(M._write_gate_enabled(self.store))
        os.environ["KEEPER_WRITE_GATE"] = "1"
        self.assertTrue(M._write_gate_enabled(self.store))

    def test_config_file_can_disable(self):
        cfg_dir = os.path.join(self.store, "store")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"keeper": {"write_gate": False}}, f)
        M._load_keeper_config(self.store, force=True)
        self.assertFalse(M._write_gate_enabled(self.store))

    # ── 第二个写入真源 _write_mem 同样受门禁保护 ──
    def test_write_mem_also_gated(self):
        self._new_mem(mid="G2", body="旧内容", ver=1)
        shutil.rmtree(os.path.join(self.store, "versions"), ignore_errors=True)
        open(os.path.join(self.store, "versions"), "w").close()
        with self.assertRaises(M.MemoryWriteGateError):
            M._write_mem(self.store, "G2", {"id": "G2", "body": "新内容", "version": 2})
        self.assertEqual(self._disk_body("G2"), "旧内容")
        os.remove(os.path.join(self.store, "versions"))


if __name__ == "__main__":
    unittest.main()
