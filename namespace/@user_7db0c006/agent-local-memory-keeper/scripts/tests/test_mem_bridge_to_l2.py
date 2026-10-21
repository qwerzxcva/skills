import os
import sys
import json
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))  # skill 根目录（mem_bridge.py 在此）
sys.path.insert(0, SKILL)
import mem_bridge as MB  # noqa: E402


class ToL2Test(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_tol2_")
        os.environ["AI_MEMORY_STORE"] = self.root

    def _entries(self):
        return [
            {"id": "L1", "status": "active", "tier": "working", "importance": 0.9,
             "access_count": 1, "tags": [], "summary": "高重要经验", "body": "b", "category": "tip"},
            {"id": "L2", "status": "active", "tier": "working", "importance": 0.2,
             "access_count": 5, "tags": [], "summary": "高频经验", "body": "b", "category": "tip"},
            {"id": "L3", "status": "active", "tier": "working", "importance": 0.1,
             "access_count": 1, "tags": ["confirmed_by_user"], "summary": "用户确认", "body": "b", "category": "tip"},
            {"id": "L4", "status": "active", "tier": "curated", "importance": 0.99,
             "access_count": 99, "tags": [], "summary": "已晋升", "body": "b", "category": "tip"},
            {"id": "L5", "status": "archived", "tier": "working", "importance": 0.99,
             "access_count": 99, "tags": [], "summary": "已归档", "body": "b", "category": "tip"},
            {"id": "L6", "status": "active", "tier": "working", "importance": 0.1,
             "access_count": 1, "tags": [], "summary": "低价值", "body": "b", "category": "tip"},
        ]

    def test_md_draft_filters_correctly(self):
        path, n, diag = MB.to_l2_draft(self._entries(), min_importance=0.7,
                                       min_access=3, top_n=30, fmt="md")
        self.assertIsNotNone(path)
        self.assertEqual(n, 3)  # L1(imp) L2(access) L3(confirmed)
        self.assertEqual(diag["active_l4_scanned"], 4)  # L1-L4 中 active working；L4 curated 跳过
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("L4→L2 晋升草稿", txt)
        self.assertIn("[L1]", txt)
        self.assertIn("[L2]", txt)
        self.assertIn("[L3]", txt)
        self.assertNotIn("[L4]", txt)  # tier 跳过
        self.assertNotIn("[L5]", txt)  # status 跳过
        self.assertNotIn("[L6]", txt)  # 低价值

    def test_json_draft(self):
        path, n, diag = MB.to_l2_draft(self._entries(), fmt="json",
                                       export_path=os.path.join(self.root, "custom.json"))
        self.assertEqual(n, 3)
        self.assertTrue(diag["ok"])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        self.assertEqual({d["id"] for d in data}, {"L1", "L2", "L3"})

    def test_no_candidates(self):
        ents = [{"id": "X", "status": "active", "tier": "working", "importance": 0.1,
                 "access_count": 1, "tags": [], "summary": "s", "body": "b", "category": ""}]
        path, n, diag = MB.to_l2_draft(ents, min_importance=0.7, min_access=3)
        self.assertIsNone(path)
        self.assertEqual(n, 0)
        self.assertFalse(diag["ok"])
        self.assertIn("active_l4_scanned", diag)

    def test_dry_run_does_not_write(self):
        path, n, diag = MB.to_l2_draft(self._entries(), fmt="md", dry_run=True)
        self.assertIsNone(path)
        self.assertEqual(n, 3)
        self.assertTrue(diag.get("dry_run"))

    def test_does_not_touch_wb_files(self):
        wb_mem = os.path.expanduser("~/.workbuddy/MEMORY.md")
        before = os.path.exists(wb_mem)
        MB.to_l2_draft(self._entries(), fmt="md")
        self.assertEqual(os.path.exists(wb_mem), before)


if __name__ == "__main__":
    unittest.main()
