# -*- coding: utf-8 -*-
"""回归：embedding 磁盘缓存『幽灵向量』污染（#cache-poison）。

根因：_backend_id() 仅看配置 mode，神经后端加载失败时仍返回 "fastembed:..."，
导致词法级兜底的向量被缓存到 "fastembed" 键下；模型恢复后误命中旧词法向量，
语义余弦失真 → 语义召回静默失效。上一轮『语义召回看似坏掉』即此。

修复：
- _backend_id() 在 _NEURAL is False 时返回 "lexical"（与实际降级行为一致）；
- _bkey() 纳入模型内容指纹（backend:model#size.mtime），模型替换/损坏后旧向量键自动失效。

本测试锁定这两条不变量，防止回归。为保证不依赖其它测试文件的 env 泄漏
（多测试模块会在 import 期把 AI_MEM_EMBED_BACKEND 钉为 lexical 且不还原），
每个用例 setUp 内把 env 钉死为 fastembed 并强制重读配置，tearDown 还原本用例前 env。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

    # ── 模块级确定性后端：强制 fastembed + 离线从技能内模型缓存加载 ──
# ⚠️ 下面 6 个变量是**模块级**注入（import 期生效，`import embed` 需要），tearDown 无法
# 安全撤销（见 tearDown 注释），会泄漏给后续测试模块。实测后果：全量跑时随机有 1 个
# 测试失败、单跑该模块却通过（典型顺序依赖型 flaky）。
# 兜底不在本文件，而在 run_gate.py 的「模块间 env 隔离 + 统一 lexical 基线」。
os.environ["AI_MEM_EMBED_BACKEND"] = "fastembed"
os.environ["AI_MEM_NO_AUTO_INSTALL"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
SKILL = os.path.dirname(HERE)
CACHE = os.path.join(SKILL, "models")
if os.path.isdir(CACHE):
    os.environ["HF_HUB_CACHE"] = CACHE
    os.environ["FASTEMBED_CACHE_PATH"] = CACHE

import embed  # noqa: E402
import memory_ops  # noqa: E402
memory_ops._load_keeper_config(force=True)  # 让上面的 env 生效


class EmbedCachePoisonTest(unittest.TestCase):
    def setUp(self):
        # 关键：每个用例前把 env 钉死为 fastembed 并强制重读配置，
        # 防止被其它测试模块残留的
        # AI_MEM_EMBED_BACKEND=lexical 污染——否则 _backend_id 在神经分支也会返回 lexical，
        # 使 test_cache_key_isolates_lexical_from_neural 两端键相等而误判。
        self._saved_env = dict(os.environ)
        os.environ["AI_MEM_EMBED_BACKEND"] = "fastembed"
        memory_ops._load_keeper_config(force=True)
        self._neural = embed._NEURAL
        self._fp = embed._MODEL_FP

    def tearDown(self):
        embed._NEURAL = self._neural
        embed._MODEL_FP = self._fp
        # 还原 env 到本用例前（_saved_env）。
        # ⚠️ 模块级注入的那 6 个变量（见文件头）无法在类内安全撤销：它们必须在 import 期
        # 生效，而「还原到哪个基线」在本模块内无从判断（还原到模块注入前会连带清掉其它
        # 模块 import 期设置的 AI_MEM_EMBED_BACKEND=lexical，反而害了它们）。
        # 因此泄漏由 run_gate.py 的「模块间 env 隔离」统一兜底，本模块只保证用例级干净。
        # 注意：某些沙箱会注入单个 >32767 字符的环境变量（如 ACC_PRODUCT_CONFIG_V3，
        # 可达数百 KB），Windows 不允许重新设置超过 32767 字符的变量，直接
        # os.environ.update 会抛 ValueError 并导致 os.environ 处于「部分清除」的损坏状态，
        # 进而污染后续所有测试。这里逐变量还原并跳过超限变量（属环境产物，非功能变量）。
        os.environ.clear()
        for k, v in self._saved_env.items():
            try:
                os.environ[k] = v
            except ValueError:
                # 变量超过 Windows 单变量大小上限，跳过（不影响功能测试）
                pass

    def test_backend_id_falls_back_to_lexical_when_neural_fails(self):
        # 神经加载失败：_backend_id 必须=lexical（与 backend_info 实际降级一致）
        embed._NEURAL = False
        embed._MODEL_FP = None
        self.assertEqual(embed._backend_id(), "lexical")

    def test_backend_id_consistent_with_backend_info_on_failure(self):
        # 关键不变量：失败时必须两端一致，否则缓存键会说谎
        embed._NEURAL = False
        embed._MODEL_FP = None
        self.assertEqual(embed._backend_id(), embed.backend_info())

    def test_backend_id_returns_neural_id_when_neural_available(self):
        # 独立强制 config=fastembed，验证神经可用时 _backend_id 返回神经标识
        # （不依赖全局 env 是否被其它模块残留 lexical 污染）
        embed._NEURAL = ("fastembed", object())
        embed._MODEL_FP = None
        self.assertTrue(
            embed._backend_id().startswith("fastembed:"),
            "神经可用时 _backend_id 必须返回 fastembed 标识，而非 lexical",
        )

    def test_cache_key_isolates_lexical_from_neural(self):
        # 词法兜底键 绝不能与 正常神经键 相同（否则误命中旧词法向量）
        embed._NEURAL = False
        embed._MODEL_FP = None
        k_lex = embed._bkey("两个事务互相阻塞卡死了怎么办")
        # 神经分支：直接给神经指纹，确保键 ≠ 词法键（不依赖全局 env/config 是否被污染）
        embed._NEURAL = ("fastembed", object())
        embed._MODEL_FP = "fastembed:BAAI/bge-small-zh-v1.5#100.1"
        k_neural = embed._bkey("两个事务互相阻塞卡死了怎么办")
        self.assertNotEqual(k_lex, k_neural)

    def test_model_fingerprint_part_of_key(self):
        # 同一后端、不同模型指纹 → 键必须不同（模型升级/损坏自动失效旧向量）
        embed._NEURAL = ("fastembed", object())
        embed._MODEL_FP = "fastembed:BAAI/bge-small-zh-v1.5#100.1"
        k1 = embed._bkey("hello")
        embed._MODEL_FP = "fastembed:BAAI/bge-small-zh-v1.5#200.2"
        k2 = embed._bkey("hello")
        self.assertNotEqual(k1, k2)

    def test_cache_key_stable_for_same_backend(self):
        # 同后端同指纹 → 键稳定（保证正常命中缓存）
        embed._NEURAL = ("fastembed", object())
        embed._MODEL_FP = "fastembed:BAAI/bge-small-zh-v1.5#100.1"
        self.assertEqual(embed._bkey("x"), embed._bkey("x"))


class EmbedSemanticRecallE2E(unittest.TestCase):
    """端到端：真实 fastembed 模型下，语义 paraphrase 必须召回正确记忆。
    模型缺失/不可加载时跳过（不影响 CI），模型在位时锁真·语义召回。"""

    @classmethod
    def setUpClass(cls):
        cls.M = memory_ops
        try:
            cls.M._emb._NEURAL = None
            ok = cls.M._emb._probe_neural()
            cls.model_ok = bool(ok)
        except Exception:
            cls.model_ok = False

    def test_semantic_paraphrase_recall(self):
        if not self.model_ok:
            self.skipTest("fastembed 模型不可用，跳过端到端语义召回（非缺陷，环境使然）")
        import tempfile, shutil
        store = tempfile.mkdtemp()
        os.environ["AI_MEMORY_STORE"] = store
        try:
            self.M.init_store(store)
            self.M.deposit(store, category="best_practice",
                           summary="数据库死锁预防", tags=["死锁", "数据库", "事务", "锁"],
                           body="事务应按固定顺序加锁，避免循环等待导致死锁", importance=0.8)
            self.M.deposit(store, category="best_practice",
                           summary="Python异步实践", tags=["python", "异步", "asyncio"],
                           body="用 asyncio 处理高并发 IO", importance=0.8)
            q = "两个事务互相阻塞卡死了怎么办"
            res = self.M.recall(store, query=q)
            hit = any("死锁" in (e.get("summary") or "") for e in res)
            cos = self.M._emb.cosine(
                self.M._emb.embed(q),
                self.M._emb.embed("事务应按固定顺序加锁，避免循环等待导致死锁"))
            self.assertTrue(hit, "语义 paraphrase 必须召回死锁记忆")
            self.assertGreater(cos, 0.3, "真·语义余弦应显著>0（非仅靠 TF-IDF）")
        finally:
            shutil.rmtree(store, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
