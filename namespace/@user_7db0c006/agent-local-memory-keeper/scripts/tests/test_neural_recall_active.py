# -*- coding: utf-8 -*-
"""test_neural_recall_active.py — 锁定「钩子门控的语义后端判定与真实配置同源」（4.9.17）。

背景（同族缺陷，本机实测复现）：
    旧 `keeper_hook_common.neural_recall_active()` **只读** `<root>/store/config.json` 一处，
    而 `memory_ops._load_keeper_config` 认「env > store > root > 默认」。当 `embed_backend`
    只写在 `<root>/config.json`（被 memory_ops 认可的兼容位）时，钩子侧读不到 →
    恒返回 False，而真实后端是 fastembed → 钩子门控（score 门控 vs 词法门控）与真实后端不一致。
    白名单也只认 fastembed/local，把默认/normal 的 auto、别名 neural 误判为「无语义后端」。

核心断言（防回归）：
    A. 仅 root 配 `online` → True（root 兜底生效）；
    B. store 配 `lexical` 覆盖 root 的 `online` → False（store 优先）；
    C. 仅 store 配 `online` → True；
    D. env `AI_MEM_EMBED_BACKEND=lexical` 覆盖 config 的 online → False（env 最高优先）；
    E. env `AI_MEM_EMBED_BACKEND=online` 无 config → True；
    F. `_keeper_cfg_block` 合并语义：store 覆盖 root、忽略 None。

    用 `online`/`lexical` 取值 → **零第三方依赖、零模型加载、确定性**。
    （不测「默认 fastembed → True」：那依赖本机是否装了 fastembed，会 flaky；改由 E 覆盖 env 分支。）
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)
HOOKS = os.path.join(SKILL, "hooks")
for _p in (SKILL, SCRIPTS, HOOKS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 隔离钩子运行态产物（与 test_inject_gate 同范式），避免写回源码树。
os.environ.setdefault("KEEPER_HOOKS_DIR",
                      os.path.join(tempfile.gettempdir(), "keeper_gate_hooks"))

try:
    import keeper_hook_common as H
except Exception as _e:  # 环境缺依赖时跳过而非误红
    raise unittest.SkipTest("keeper_hook_common 不可导入：%s" % _e)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


class NeuralRecallActiveTest(unittest.TestCase):

    def setUp(self):
        self.store = tempfile.mkdtemp(prefix="keeper_nra_")
        self._old_store = os.environ.get("AI_MEMORY_STORE")
        self._old_be = os.environ.get("AI_MEM_EMBED_BACKEND")
        os.environ["AI_MEMORY_STORE"] = self.store
        os.environ.pop("AI_MEM_EMBED_BACKEND", None)  # 默认清空，避免宿主 env 干扰 config 断言

    def tearDown(self):
        for key, old in (("AI_MEMORY_STORE", self._old_store),
                         ("AI_MEM_EMBED_BACKEND", self._old_be)):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        shutil.rmtree(self.store, ignore_errors=True)

    def _root_cfg(self, be):
        _write(os.path.join(self.store, "config.json"), {"keeper": {"embed_backend": be}})

    def _store_cfg(self, be):
        _write(os.path.join(self.store, "store", "config.json"),
               {"keeper": {"embed_backend": be}})

    # ── A. root 兜底（回归核心）──
    def test_root_only_online_is_active(self):
        self._root_cfg("online")
        self.assertTrue(H.neural_recall_active(),
                        "embed_backend 只配在 root/config.json 时也必须被读到（root 兜底）")

    # ── B. store 优先 ──
    def test_store_lexical_overrides_root_online(self):
        self._root_cfg("online")
        self._store_cfg("lexical")
        self.assertFalse(H.neural_recall_active(),
                         "store/config.json 的 lexical 必须覆盖 root 的 online（store 优先）")

    # ── C. 仅 store ──
    def test_store_only_online_is_active(self):
        self._store_cfg("online")
        self.assertTrue(H.neural_recall_active())

    # ── D. env 最高优先 ──
    def test_env_lexical_overrides_config_online(self):
        self._root_cfg("online")
        os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"
        self.assertFalse(H.neural_recall_active(),
                         "env AI_MEM_EMBED_BACKEND 必须覆盖 config（与 _load_keeper_config 同源）")

    # ── E. env 单独生效 ──
    def test_env_online_alone_is_active(self):
        os.environ["AI_MEM_EMBED_BACKEND"] = "online"
        self.assertTrue(H.neural_recall_active())

    # ── F. 合并语义 ──
    def test_cfg_block_merge_semantics(self):
        _write(os.path.join(self.store, "config.json"),
               {"keeper": {"embed_backend": "online", "inject_enabled": True}})
        _write(os.path.join(self.store, "store", "config.json"),
               {"keeper": {"embed_backend": "lexical", "recall_mode": None}})
        blk = H._keeper_cfg_block()
        self.assertEqual(blk.get("embed_backend"), "lexical", "store 应覆盖 root")
        self.assertTrue(blk.get("inject_enabled"), "root 独有的键应被保留")
        self.assertNotIn("recall_mode", blk, "None 值不应进入合并结果")

    # ── G. lexical 明确关闭 ──
    def test_explicit_lexical_inactive(self):
        self._store_cfg("lexical")
        self.assertFalse(H.neural_recall_active())


if __name__ == "__main__":
    unittest.main()
