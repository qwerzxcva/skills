# -*- coding: utf-8 -*-
"""回归：reclassify_by_taxonomy 必须把 domain/subdomain/tags 改动同步进召回索引。

根因：旧版 reclassify 只 _save_mem（写文件）就返回，从不回灌索引；且 _sync_index 只覆盖
tier/status/scope/project 四个字段，导致 subdomain/tags 这类 recall 硬过滤字段在索引里陈旧 →
recall --subdomain / --tag sub: 静默错乱（SKILL 文档 190-191 行承诺的行为实际未生效）。
2026-08-12 修复：扩展 _sync_index 覆盖全部 9 个过滤字段 + reclassify 末端补 _sync_index(root)。

本测试锁定：reclassify(dry_run=False) 后，recall 按 subdomain / tag 必须命中；
reclassify(dry_run=True) 不改变索引。
"""
import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import memory_ops as M

_KW = "zzmagicqtrading"  # 不在默认 KNOWN_DOMAINS 关键词里，确保 deposit 不动 subdomain


def _custom_tax():
    return {
        "version": 1, "created": None,
        "user_profile": {"name": None, "roles": [], "scenarios": []},
        "domains": [{
            "key": "invest", "label": "invest", "description": "",
            "keywords": ["zzinvest"], "heat_budget": None, "retention": None,
            "subdomains": [{
                "key": "qtrading", "label": "qtrading", "description": "",
                "keywords": [_KW],
            }],
        }],
        "fallback_domain": "general",
    }


class TaxonomyIndexSyncTest(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        M.init_store(self.store)
        # 文本含 _KW，但默认 taxonomy 不匹配 → deposit 后 subdomain 应为 None
        self.mid = M.deposit(self.store, "note",
                             "心得 %s" % _KW, ["raw"], "body about %s" % _KW)

    def tearDown(self):
        shutil.rmtree(self.store, ignore_errors=True)

    def test_reclassify_synced_to_index(self):
        r = M.reclassify_by_taxonomy(self.store, taxonomy=_custom_tax(), dry_run=False)
        self.assertGreater(len(r["changes"]), 0, "应检测到 subdomain 变更")
        # 文件层
        mem, _ = M._load_mem(self.store, self.mid)
        self.assertEqual(mem.get("subdomain"), "qtrading")
        self.assertIn("sub:qtrading", mem.get("tags", []))
        # 索引层（recall 只读索引镜像）
        got = M.recall(self.store, subdomain="qtrading")
        self.assertTrue(any(e["id"] == self.mid for e in got),
                        "recall --subdomain 应命中（索引已同步）")
        got2 = M.recall(self.store, tag="sub:qtrading")
        self.assertTrue(any(e["id"] == self.mid for e in got2),
                        "recall --tag sub: 应命中（索引已同步）")

    def test_dry_run_no_index_change(self):
        r = M.reclassify_by_taxonomy(self.store, taxonomy=_custom_tax(), dry_run=True)
        self.assertTrue(r["summary"]["dry_run"])
        got = M.recall(self.store, subdomain="qtrading")
        self.assertFalse(any(e["id"] == self.mid for e in got),
                         "dry_run 不应改变索引，recall 不应命中")


if __name__ == "__main__":
    unittest.main()
