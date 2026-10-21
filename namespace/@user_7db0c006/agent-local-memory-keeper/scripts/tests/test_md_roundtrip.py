# -*- coding: utf-8 -*-
"""export md ↔ import md 往返回归（4.9.1 P0 修复的防线）。

背景：4.9.0 及以前 `export --format md` 只写 `## <id>` 不写摘要，import 侧又把标题
当 summary → **导入后摘要全部退化成记忆 id**（实测一致率 0%）。本套件锁死该行为。

解析层用例（T1–T5）不依赖真实库，可跨机器稳定跑；端到端（T6）用真实库只读副本
+ 临时目标库，不动真库。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)          # scripts/
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import keeper_import as ki  # noqa: E402
import memory_ops as mo  # noqa: E402


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestMdParse(unittest.TestCase):
    """md 解析层（纯解析，无需记忆库）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_md_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _norm(self, name, text):
        p = _write(os.path.join(self.tmp, name), text)
        return ki._normalize(ki._parse_md(p)[0])

    def test_t1_legacy_md_summary_not_id(self):
        """旧版 md（## <id> 无摘要键）→ 摘要回退正文，不再是 id。"""
        s = self._norm("old.md", """## LRN-20260801-001

> 分类: 踩坑 · 类型: pitfall · 层级: working · 标签: a, b · 创建: 2026-08-01

Windows 沙箱下 rm -f 会被 safe-delete 拦截，须用 ctypes 硬删。

---
""")
        self.assertNotIn("LRN-20260801-001", s["summary"],
                         "摘要不应退化成 id：%r" % s["summary"])
        self.assertTrue(s["summary"].startswith("Windows"), s["summary"])
        self.assertIn("ctypes 硬删", s["body"], "正文应完整保留")
        self.assertEqual(s.get("id"), "LRN-20260801-001")

    def test_t2_new_md_summary_exact(self):
        """新版 md（meta 含 摘要:）→ 摘要精确还原，其他 meta 不受影响。"""
        s = self._norm("new.md", """## LRN-20260801-002

> 摘要: DuckDB 跨库合并必须用 ATTACH + CREATE OR REPLACE · 分类: 技巧 · 类型: tip · 层级: core

正文内容在这里。

---
""")
        self.assertEqual(s["summary"], "DuckDB 跨库合并必须用 ATTACH + CREATE OR REPLACE")
        self.assertEqual(s["category"], "技巧")
        self.assertEqual(s["tier"], "core")
        self.assertEqual(s["body"], "正文内容在这里。")

    def test_t3_summary_with_separator(self):
        """摘要内含 '·' → 不被截断。"""
        s = self._norm("t3.md", """## LRN-20260801-003

> 摘要: A · B 两段式摘要不能被截 · 分类: x · 创建: 2026-08-01

body

---
""")
        self.assertEqual(s["summary"], "A · B 两段式摘要不能被截")

    def test_t4_learnings_title(self):
        """learnings 标题 '## <id> · <summary>' → 正确拆出 id 与摘要。"""
        s = self._norm("t4.md", """## LRN-20260801-004 · 这是 learnings 格式的摘要

> 分类: x · 创建: 2026-08-01

body4

---
""")
        self.assertEqual(s["summary"], "这是 learnings 格式的摘要")
        self.assertEqual(s.get("id"), "LRN-20260801-004")

    def test_t5_chinese_title_not_split(self):
        """正常中文标题（含 · 但左侧不像 id）→ 不被误拆。"""
        s = self._norm("t5.md", """## 关于记忆系统 · 一些想法

> 分类: x

body5

---
""")
        self.assertEqual(s["summary"], "关于记忆系统 · 一些想法")


class TestMdEndToEnd(unittest.TestCase):
    """端到端：真实库（只读）→ jsonl → 中间库 → export md → import → 比对摘要。"""

    @classmethod
    def setUpClass(cls):
        cls.src = os.environ.get("AI_MEMORY_STORE") or mo.DEFAULT_ROOT
        if not os.path.isdir(cls.src):
            raise unittest.SkipTest("真实记忆库不可用：%s" % cls.src)

    def test_roundtrip_keeps_summaries(self):
        tmp = tempfile.mkdtemp(prefix="keeper_md_e2e_")
        try:
            exp = mo.export_memories(self.src, fmt="jsonl",
                                     include_archived=True, include_superseded=True)
            self.assertEqual(exp.get("filtered_out"), 0,
                             "全量开关应生效，filtered_out=0（不再静默丢 superseded）")
            src_mems = [json.loads(ln) for ln in (exp.get("content") or "").splitlines()
                        if ln.strip()]
            self.assertTrue(src_mems, "源库导出为空，无法验证")

            jsonl_path = os.path.join(tmp, "src.jsonl")
            with open(jsonl_path, "w", encoding="utf-8") as f:
                f.write(exp["content"])

            mid_store = os.path.join(tmp, "mid_store")
            r1 = ki.run_import(mid_store, jsonl_path, fmt="jsonl",
                               dry_run=False, keep_ids=True)
            self.assertGreater(r1.get("imported", 0), 0, "中间库导入失败")

            md_path = os.path.join(tmp, "roundtrip.md")
            mo.export_memories(mid_store, fmt="md", dest=md_path, include_archived=True)
            tgt_store = os.path.join(tmp, "tgt_store")
            ki.run_import(tgt_store, md_path, fmt="md", dry_run=False, keep_ids=True)

            exp2 = mo.export_memories(tgt_store, fmt="jsonl", include_archived=True)
            tgt_mems = [json.loads(ln) for ln in (exp2.get("content") or "").splitlines()
                        if ln.strip()]
            src_map = {m.get("id"): (m.get("summary") or "").strip() for m in src_mems}
            tgt_map = {m.get("id"): (m.get("summary") or "").strip() for m in tgt_mems}

            self.assertTrue(tgt_map, "目标库为空，往返失败")
            id_like = [k for k, v in tgt_map.items()
                       if v.startswith("LRN-") or v.startswith("mem_")]
            self.assertEqual(id_like, [],
                             "摘要退化成 id（4.9.0 P0 回归）：%s" % id_like[:5])
            same = sum(1 for k, v in tgt_map.items() if src_map.get(k) == v)
            rate = same / max(1, len(tgt_map))
            self.assertGreaterEqual(rate, 0.9,
                                    "摘要一致率 %.1f%% 过低（%d/%d）"
                                    % (rate * 100, same, len(tgt_map)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
