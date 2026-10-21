# -*- coding: utf-8 -*-
"""IMA 云端同步边界测试（v4.8.1）。

覆盖用户反馈「高级功能（云端同步）边界情况测试不够充分」：
不连真实 IMA / 不调 MCP，纯覆盖导出侧脚本的边界路径：
1) KB id 占位符预检必须拒绝（exit 2，不静默假成功）；
2) 无导出目录时脱敏复检返回空、不报错；
3) 无 KB 清单时同步对账只打印引导、不崩溃；
4) 推送指令生成含文件清单与 KB id。
"""
import os
import sys
import json
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (SKILL, os.path.join(SKILL, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import ima_sync as I


class ImaSyncBoundaryTest(unittest.TestCase):
    def setUp(self):
        self._env_store = os.environ.get("AI_MEMORY_STORE")
        os.environ["AI_MEMORY_STORE"] = tempfile.mkdtemp()

    def tearDown(self):
        if self._env_store is None:
            os.environ.pop("AI_MEMORY_STORE", None)
        else:
            os.environ["AI_MEMORY_STORE"] = self._env_store

    def test_precheck_kb_rejects_placeholder(self):
        with self.assertRaises(SystemExit) as cm:
            I._precheck_kb("YOUR_IMA_KB_ID")
        self.assertEqual(cm.exception.code, 2)

    def test_verify_no_push_dir_returns_empty(self):
        I.PUSH_DIR = tempfile.mkdtemp()
        self.assertEqual(I._verify(), [])

    def test_verify_reconcile_no_listing_prints_guidance(self):
        I.PUSH_DIR = tempfile.mkdtemp()
        I.DEFAULT_KB_ID = "KB_TEST"
        # 不应抛异常；无清单时打印引导后返回
        I._verify_reconcile()

    def test_build_prompt_contains_files(self):
        d = tempfile.mkdtemp()
        f1 = os.path.join(d, "keeper-镜像-test.md")
        with open(f1, "w", encoding="utf-8") as fh:
            fh.write("x")
        p = I._build_prompt([f1], "KB_TEST")
        self.assertIn("KB_TEST", p)
        self.assertIn(f1, p)


if __name__ == "__main__":
    unittest.main()
