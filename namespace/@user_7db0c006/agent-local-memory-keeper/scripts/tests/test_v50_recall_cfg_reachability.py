# -*- coding: utf-8 -*-
"""回归（5.0）：召回配置必须「可达」，且必须进缓存键。

背景（2026-09-16 实查，同一根因族第三次命中）：
  `_load_recall_config` 的覆盖循环是 `for kk in cfg:` —— **只遍历 RRF_DEFAULTS 的键**
  ⇒ 任何没登记进 RRF_DEFAULTS 的配置项，在 config.json 里写多少遍都**不会生效**。
  而代码早就在读它们、文档甚至明确写了怎么配：
    · `cache_ttl_seconds`   —— `_api.py` 读，`RECALL_CACHE_TTL_DEFAULT` 处注释写
                              「可在 config.json 的 recall.cache_ttl_seconds 覆盖」
    · `low_conf_downweight` —— `_api.py:437` 读
    · `ann_auto_large`      —— `_api.py:311` 读
  ⇒ 三处都是「文档/代码期待 ≠ 实现层可达」。

第二个缺口（缓存键）：
  缓存键原先只含 `root/config.json` 的 mtime，而 `_load_recall_config` 是
  **store/config.json 优先**（真库确实把 semantic_gate 写在 store/config.json）
  ⇒ 改 store/config.json 不失效缓存；且 `rerank_*` 4 项**完全不在键里**
  ⇒ 开关切换后命中旧缓存（B1 消融实验会被它污染）。
  修法 = mtime 扩到两路径 + `_recall_cache_cfg_sig` 内容签名（唯一来源）。

本用例锁住这两件事，防复发。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KEEPER_RECALL_MODE", "inprocess")

import memory_ops as mo  # noqa: E402

NEW_KEYS = ("cache_ttl_seconds", "low_conf_downweight", "ann_auto_large")


class RecallConfigReachabilityTest(unittest.TestCase):
    """A 组：配置可达性（原为死读取）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_cfgreach_")
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _wcfg(self, rel, obj):
        with io.open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False))

    def test_new_keys_are_registered(self):
        cfg = mo._load_recall_config(self.root)
        for k in NEW_KEYS:
            self.assertIn(k, cfg, "%s 未登记进 RRF_DEFAULTS → 配置永远不可达" % k)

    def test_new_keys_overridable_from_store_config(self):
        self._wcfg("store/config.json", {"recall": {
            "cache_ttl_seconds": 7, "low_conf_downweight": 0.9,
            "ann_auto_large": True}})
        cfg = mo._load_recall_config(self.root)
        self.assertEqual(cfg.get("cache_ttl_seconds"), 7)
        self.assertEqual(cfg.get("low_conf_downweight"), 0.9)
        self.assertTrue(cfg.get("ann_auto_large"))

    def test_store_config_wins_over_root(self):
        self._wcfg("config.json", {"recall": {"cache_ttl_seconds": 999}})
        self._wcfg("store/config.json", {"recall": {"cache_ttl_seconds": 7}})
        self.assertEqual(mo._load_recall_config(self.root).get("cache_ttl_seconds"), 7)

    def test_cache_ttl_default_single_source(self):
        """默认 TTL 必须与 RRF_DEFAULTS 同源（原先两处各写一个 60）。"""
        self.assertEqual(mo.RECALL_CACHE_TTL_DEFAULT,
                         int(mo.RRF_DEFAULTS["cache_ttl_seconds"]))


class RecallCacheCfgKeyTest(unittest.TestCase):
    """B 组：缓存键必须随召回配置变化（原为静默串缓存）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_cfgkey_")
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _wcfg(self, rel, obj):
        with io.open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False))

    def _key(self):
        """走真实组合：签名由 _recall_cache_cfg_sig 计算（不复刻规则）。"""
        return mo._recall_cache_key(
            self.root, None, None, "probe", None, None, None, None, False,
            cfg_sig=mo._recall_cache_cfg_sig(self.root))

    def test_rerank_toggle_changes_cache_key(self):
        self._wcfg("store/config.json", {"recall": {"rerank_enabled": False}})
        k_off = self._key()
        self._wcfg("store/config.json", {"recall": {"rerank_enabled": True}})
        k_on = self._key()
        self.assertNotEqual(
            k_off, k_on,
            "开/关 rerank 得到同一个缓存键 → 切换后仍命中旧缓存（消融实验会被污染）")

    def test_cfg_sig_independent_of_mtime(self):
        """🔴 关键：mtime 相同但内容不同，键仍必须变。

        实测 NTFS 的 getmtime 可见粒度约 15.6ms：连续两次改配置可能落在同一粒度内，
        此时只有内容签名能区分。这里用 os.utime 把 mtime 人为还原，直接证明这一点。
        """
        p = os.path.join(self.root, "store", "config.json")
        self._wcfg("store/config.json", {"recall": {"rerank_top": 5}})
        k1 = self._key()
        st = os.stat(p)
        self._wcfg("store/config.json", {"recall": {"rerank_top": 9}})
        os.utime(p, (st.st_atime, st.st_mtime))   # 还原 mtime
        self.assertAlmostEqual(os.path.getmtime(p), st.st_mtime, places=6)
        k2 = self._key()
        self.assertNotEqual(k1, k2, "mtime 相同即键相同 → 15.6ms 粒度内改配置不生效")

    def test_cfg_sig_reproducible(self):
        self._wcfg("store/config.json", {"recall": {"rerank_top": 5}})
        self.assertEqual(mo._recall_cache_cfg_sig(self.root),
                         mo._recall_cache_cfg_sig(self.root))

    def test_broken_config_falls_back_to_default_sig(self):
        """config 损坏 → `_load_recall_config` 静默回退默认值（既有行为，P2 修复），
        故签名应等于「无 config」时的签名；且非空（空签名会让所有配置变化都不失效）。"""
        p = os.path.join(self.root, "store", "config.json")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        broken = mo._recall_cache_cfg_sig(self.root)
        os.remove(p)
        clean = mo._recall_cache_cfg_sig(self.root)
        self.assertNotEqual(broken, "", "签名不得为空，否则配置变化不会失效缓存")
        self.assertEqual(broken, clean,
                         "损坏配置与缺配置应等价（都走默认），否则缓存会无谓失效")


class RecallStrategyDisplayTest(unittest.TestCase):
    """C 组：展示层（dashboard/report 的「哪些项被覆盖」）必须与实际生效一致。

    真库实况：`semantic_gate: 0.0` 写在 `store/config.json`，而 `get_recall_strategy`
    原先只读 `root/config.json` ⇒ 展示层看不到它被覆盖，用户会以为自己在用默认值。
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_strat_")
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _w(self, rel, obj):
        with io.open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False))

    def test_overridden_sees_store_config(self):
        self._w("store/config.json", {"keeper": {"semantic_gate": 0.0}})
        st = mo.get_recall_strategy(self.root)
        ov = st.get("_overridden", {})
        self.assertIn("semantic_gate", ov,
                      "store/config.json 的覆盖项必须出现在 _overridden")
        self.assertEqual(ov["semantic_gate"], 0.0)

    def test_overridden_sees_both_paths_and_both_blocks(self):
        self._w("config.json", {"keeper": {"rrf_k": 30}})
        self._w("store/config.json", {"recall": {"min_score": 0.2}})
        ov = mo.get_recall_strategy(self.root).get("_overridden", {})
        self.assertEqual(ov.get("rrf_k"), 30, "root/config.json + keeper 块须被识别")
        self.assertEqual(ov.get("min_score"), 0.2, "store/config.json + recall 块须被识别")

    def test_overridden_ignores_equal_to_default(self):
        self._w("store/config.json", {"recall": {"rrf_k": mo.RRF_DEFAULTS["rrf_k"]}})
        ov = mo.get_recall_strategy(self.root).get("_overridden", {})
        self.assertNotIn("rrf_k", ov, "等于默认值不算覆盖")


class RerankDocCharsReachabilityTest(unittest.TestCase):
    """D 组：`rerank_doc_chars` 必须可配且真的作用于成本主项。

    背景（2026-09-16 第二轮实测）：重排成本 ≈ **1.2 ms/字符**（线性于「候选条数 × 截断字符」），
    真实记忆文本下 top-20×1200 字 = 12~15 s/次。而截断长度原先**硬编码在
    `_rerank_doc_text(item, limit=1200)`**，配置面拿不到 ⇒ 用户即使想「用便宜档」也改不了。
    又一次「代码里有成本参数、配置面不可达」——同一根因族。

    本组锁两件事：① 键登记进 RRF_DEFAULTS 且可被 config.json 覆盖；
    ② **真的传到了 cross-encoder 的输入上**（否则等于配了个寂寞）。
    """

    class _StubEncoder:
        """假编码器：记录收到的文档文本，不加载任何模型（用例必须能离线秒跑）。"""

        def __init__(self):
            self.seen = []

        def rerank(self, query, docs):
            docs = list(docs)
            self.seen.append([len(d) for d in docs])
            return [1.0 - 0.1 * i for i in range(len(docs))]

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_rrdc_")
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)
        self.model = "stub/test-doc-chars"
        self.stub = self._StubEncoder()
        mo._rerank_mod._RERANK_FAILED.discard(self.model)
        mo._rerank_mod._RERANK_ENC[self.model] = self.stub

    def tearDown(self):
        mo._rerank_mod._RERANK_ENC.pop(self.model, None)
        shutil.rmtree(self.root, ignore_errors=True)

    def _cfg(self, doc_chars):
        cfg = dict(mo.RRF_DEFAULTS)
        cfg.update({"rerank_enabled": True, "rerank_model": self.model,
                    "rerank_top": 3, "rerank_weight": 0.6,
                    "rerank_doc_chars": doc_chars})
        return cfg

    @staticmethod
    def _candidates(n=3):
        out = []
        for i in range(n):
            out.append({"id": "M%d" % i,
                        "summary": "摘要%d" % i,
                        "body": "正文" * 2000})       # 超长正文，确保截断真的在起作用
        return out

    def test_key_registered_and_overridable(self):
        self.assertIn("rerank_doc_chars", mo.RRF_DEFAULTS,
                      "未登记进 RRF_DEFAULTS → 覆盖循环遍历不到，配了也不生效")
        p = os.path.join(self.root, "store", "config.json")
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"recall": {"rerank_doc_chars": 321}}))
        self.assertEqual(mo._load_recall_config(self.root).get("rerank_doc_chars"), 321)

    def test_doc_chars_reaches_encoder_input(self):
        out = self._candidates()
        ranked = {"M0": 1.0, "M1": 0.8, "M2": 0.6}
        mo._rerank_apply(self.root, "query 文本", out, ranked, self._cfg(200))
        self.assertTrue(self.stub.seen, "假编码器一次都没被调用 —— 说明走了静默回退，用例无效")
        longest = max(max(row) for row in self.stub.seen)
        self.assertLessEqual(longest, 200,
                             "配置的 rerank_doc_chars 没传到编码器输入上")

    def test_smaller_doc_chars_shrinks_encoder_input(self):
        ranked = {"M0": 1.0, "M1": 0.8, "M2": 0.6}
        mo._rerank_apply(self.root, "q", self._candidates(), ranked, self._cfg(800))
        big = max(max(row) for row in self.stub.seen)
        self.stub.seen = []
        mo._rerank_apply(self.root, "q", self._candidates(), ranked, self._cfg(64))
        small = max(max(row) for row in self.stub.seen)
        self.assertLess(small, big,
                        "调小 rerank_doc_chars 必须减少编码器输入长度（成本主项）")

    def test_rerank_top_bounds_candidate_count(self):
        ranked = {"M%d" % i: 1.0 - 0.1 * i for i in range(8)}
        out = self._candidates(8)
        mo._rerank_apply(self.root, "q", out, ranked, self._cfg(120))
        self.assertEqual(len(self.stub.seen[-1]), 3,
                         "只应重排 RRF top-N 条，N 之外的候选不得进入编码器")

    def test_defaults_single_source(self):
        """默认档必须三处一致：`RRF_DEFAULTS` = `_rerank.py` 常量 = 实测便宜档。

        （原默认 top=20/1200 字 = 12~15s/次，网格实测后改为 5/200 —— 见报告第十三节。）
        """
        self.assertEqual(mo.RERANK_DEFAULT_TOP, mo.RRF_DEFAULTS["rerank_top"])
        self.assertEqual(mo._rerank_mod.RERANK_DEFAULT_DOC_CHARS,
                         mo.RRF_DEFAULTS["rerank_doc_chars"])
        self.assertEqual(mo._rerank_mod.RERANK_DEFAULT_TOP, mo.RRF_DEFAULTS["rerank_top"])

    def test_source_has_no_hardcoded_doc_limit(self):
        """静态锁：成本限制不得再被写死回 `_rerank_doc_text(e)` 的默认值。"""
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "memory_ops", "_rerank.py")
        with io.open(src, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("rerank_doc_chars", text,
                      "成本主项必须从配置读取，不能被硬编码")
        self.assertNotIn("_rerank_doc_text(e)]", text,
                         "不得回退成不带 limit 的调用（会吃默认 1200）")


if __name__ == "__main__":
    unittest.main()
