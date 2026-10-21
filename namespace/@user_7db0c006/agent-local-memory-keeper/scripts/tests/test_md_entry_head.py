# -*- coding: utf-8 -*-
"""md 条目头判定回归（4.9.2 P0 修复的防线）。

背景：4.9.1 及以前 `keeper_import._parse_md` 把**任何**以 '## ' 开头的行都当成
一个新记忆条目。记忆正文里自带的 markdown 小标题（'## 工作流'、'## 反模式'）
因此被解析成独立记忆 —— 一次 export→import 往返会把 1 条长记忆炸成多条碎片
并写入新 id，污染记忆库。

真实库实测（156 条记忆 / 220 个 '## '）：修复前解析出 216 条（凭空多 60 条
幽灵），摘要一致率 67.1%；修复后 156 条、幽灵 0、一致率 100%。

本套件全部为解析层用例，不依赖真实记忆库，可跨机器稳定跑。
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)          # scripts/
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import keeper_import as ki  # noqa: E402


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestMdEntryHead(unittest.TestCase):
    """v4.9.2：'## ' 需通过双锚点判定才算条目头。"""

    def test_t1_body_headings_not_split(self):
        """正文内的中文 markdown 标题不得被拆成新记忆（P0 主场景）。"""
        md = _write(
            "## LRN-20260801-001\n"
            "> 摘要: 一条长记忆 · 分类: 技术 · 创建: 2026-08-01\n"
            "\n"
            "## 工作流（已验证）\n"
            "第一步：导出\n"
            "\n"
            "## 反模式\n"
            "不要盲覆盖\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 1, "正文标题被误拆成 %d 条" % len(recs))
        self.assertEqual(recs[0]["id"], "LRN-20260801-001")
        self.assertIn("## 工作流（已验证）", recs[0]["body"])
        self.assertIn("## 反模式", recs[0]["body"])

    def test_t2_fenced_code_heading_not_split(self):
        """代码围栏内的 '## <id>' 只是代码内容，不得当条目头。"""
        md = _write(
            "## LRN-20260801-002\n"
            "> 摘要: 含代码块 · 创建: 2026-08-01\n"
            "\n"
            "```markdown\n"
            "## LRN-99999999-999\n"
            "> 摘要: 这是示例代码\n"
            "```\n"
            "\n"
            "收尾说明\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 1, "围栏内标题被误拆成 %d 条" % len(recs))
        self.assertIn("## LRN-99999999-999", recs[0]["body"])

    def test_t3_real_id_head_kept(self):
        """export md 的 '## <id>' + meta 行必须正常识别。"""
        md = _write(
            "## LRN-20260801-001\n"
            "> 摘要: 甲 · 分类: 技术 · 创建: 2026-08-01\n"
            "\n"
            "甲正文\n"
            "\n"
            "---\n"
            "\n"
            "## LRN-20260801-002\n"
            "> 摘要: 乙 · 分类: 技术 · 创建: 2026-08-01\n"
            "\n"
            "乙正文\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 2)
        self.assertEqual([r["id"] for r in recs],
                         ["LRN-20260801-001", "LRN-20260801-002"])
        self.assertEqual([r["summary"] for r in recs], ["甲", "乙"])

    def test_t4_learnings_head_kept(self):
        """learnings 格式 '## <id> · <摘要>' 必须识别并拆出摘要。"""
        md = _write(
            "## LRN-20260801-003 · 这是一条摘要\n"
            "\n"
            "- **date**: 2026-08-01\n"
            "- **lesson**: 正文\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["id"], "LRN-20260801-003")
        self.assertEqual(recs[0]["summary"], "这是一条摘要")

    def test_t5_non_id_head_with_meta_kept(self):
        """手写 md：标题不是 id 但紧跟 keeper meta 行 → 仍算条目头（A2 兜底）。"""
        md = _write(
            "## 一条手写的记忆\n"
            "> 摘要: 手写摘要 · 分类: 经验 · 标签: a, b\n"
            "\n"
            "正文内容\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["summary"], "手写摘要")
        self.assertEqual(recs[0]["category"], "经验")
        self.assertEqual(recs[0]["tags"], ["a", "b"])

    def test_t6_numeric_date_heading_not_split(self):
        """正文里 '## 2026-09-08' 这类纯数字日期标题不得当条目头。"""
        md = _write(
            "## LRN-20260801-004\n"
            "> 摘要: 含日期小标题 · 创建: 2026-08-01\n"
            "\n"
            "## 2026-09-08\n"
            "当天记录\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 1, "日期标题被误判为条目头")
        self.assertIn("## 2026-09-08", recs[0]["body"])

    def test_t7_no_entry_at_all(self):
        """整篇没有任何合法条目头 → 解析结果为空，不产生幽灵条目。"""
        md = _write(
            "# 标题\n"
            "\n"
            "## 小节一\n"
            "内容一\n"
            "\n"
            "## 小节二\n"
            "内容二\n"
        )
        recs = ki._parse_md(md)
        self.assertEqual(len(recs), 0, "无条目头的文档不得解析出记忆")


if __name__ == "__main__":
    unittest.main()
