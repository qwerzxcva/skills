# -*- coding: utf-8 -*-
"""静态闸门回归测试：文档「默认值声明」必须与代码一致。

锁定 2026-09-11 复核发现的三组实锤矛盾：
  · LIMITS §7 写「默认**不自动运行**」 vs 代码 auto_capture=True；
  · SKILL.md / CAPABILITY_MAP 把「自动记忆（钩子）」标成需手动开启 vs 代码钩子默认自动注册；
  · 旧 `config_doc_matches_code` 只比**键名**、不比值，且只看一个 JSON 块 → 值写错也放行。

测试策略：在临时目录搭一个"最小 skill_root"（只需 SKILL.md + references/ + 两个代码桩），
直接调用静态闸门函数做**正反双向**断言：
  - 干净文档 → PASS（防"闸门空转"）；
  - 注入错误声明 / 错误默认值 → 必须 FAIL（防"闸门形同虚设"）；
  - 澄清误解的正确写法（如"默认不是『不自动记』"）→ 不得被误杀（防误报）。
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
sys.path.insert(0, HERE)
import verify_claims as vc  # noqa: E402


# 代码桩：只需要 KEEPER_DEFAULTS（含 auto_capture=True）+ _KEEPER_ENV_MAP
_MO_STUB = '''KEEPER_DEFAULTS = {
    "embed_backend": "fastembed",
    "inject_enabled": False,
    "auto_capture": True,
    "converse_threshold": 20,
    "write_gate": True,
}
_KEEPER_ENV_MAP = {
    "embed_backend": "AI_MEM_EMBED_BACKEND",
    "inject_enabled": "KEEPER_INJECT_ENABLED",
    "auto_capture": "KEEPER_AUTO_CAPTURE",
}
'''

# 代码桩：钩子自动注册默认开（与真实 _hooks.py 同形）
_HOOKS_STUB = '''def _ensure_hooks():
    if os.environ.get("KEEPER_AUTO_INSTALL_HOOKS", "1") == "0":
        return
'''

# SKILL.md 桩：含合法的 keeper JSON 块（{AC} 处替换 auto_capture 的值）
_SKILL_STUB = '''# AI Agent 记忆系统
version: 9.9.9

## 六、如何配置

```json
{
  "keeper": {
    "embed_backend": "fastembed",
    "inject_enabled": false,
    "auto_capture": {AC},
    "converse_threshold": 20,
    "write_gate": true
  }
}
```

## 九、安全护栏 · 红线与边界（唯一真源）
'''


class DefaultClaimsGateTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_dc_")
        os.makedirs(os.path.join(self.root, "scripts", "memory_ops"))
        os.makedirs(os.path.join(self.root, "references"))
        self._w("scripts/memory_ops/__init__.py", _MO_STUB)
        self._w("scripts/memory_ops/_hooks.py", _HOOKS_STUB)

    def tearDown(self):
        # 注：本环境删除类 API 受限，失败时残留临时目录不影响测试结论
        try:
            shutil.rmtree(self.root)
        except Exception:
            pass

    def _w(self, rel, text):
        p = os.path.join(self.root, rel.replace("/", os.sep))
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def _build(self, auto_capture="true", limits_md="", quickstart_md=""):
        self._w("SKILL.md", _SKILL_STUB.replace("{AC}", auto_capture))
        self._w("references/LIMITS.md", limits_md)
        self._w("QUICKSTART.md", quickstart_md)

    # ── 正向：干净文档必须 PASS（防闸门空转）──
    def test_clean_docs_pass(self):
        self._build(auto_capture="true")
        r1 = vc._static_default_claims_consistent(self.root)
        self.assertTrue(r1["ok"], "干净文档应通过；实际: %s" % r1.get("error"))
        r2 = vc._static_config_doc_matches_code(self.root)
        self.assertTrue(r2["ok"], "键+值都一致应通过；实际: %s" % r2.get("error"))

    # ── 负向 1：prose 声称「默认不自动」必须 FAIL ──
    def test_prose_says_default_not_auto_fails(self):
        self._build(auto_capture="true",
                    limits_md="- 默认**不自动运行**：须用户显式说\"记一下\"才触发。\n")
        r = vc._static_default_claims_consistent(self.root)
        self.assertFalse(r["ok"], "『默认不自动运行』与 auto_capture=True 矛盾，闸门必须 FAIL")

    # ── 负向 2：prose 声称「钩子需跑一次才激活」必须 FAIL ──
    def test_prose_says_hooks_need_manual_activate_fails(self):
        self._build(auto_capture="true",
                    limits_md="- 自动记忆（钩子）需跑一次 keeper_setup.py all 才激活。\n")
        r = vc._static_default_claims_consistent(self.root)
        self.assertFalse(r["ok"], "『钩子需跑一次 setup 才激活』与自动注册矛盾，闸门必须 FAIL")

    # ── 负向 3：JSON 块里的默认值写错必须 FAIL（旧断言漏掉的正是这一类）──
    def test_wrong_value_in_json_block_fails(self):
        self._build(auto_capture="false")   # 代码是 True，文档写成 false
        r = vc._static_config_doc_matches_code(self.root)
        self.assertFalse(r["ok"], "值不一致（code=True / doc=false）必须 FAIL")

    # ── 防误报：澄清误解的正确写法不得被误杀 ──
    def test_corrective_wording_not_flagged(self):
        self._build(auto_capture="true",
                    limits_md="- 注意：**默认不是「不自动记」**——auto_capture 默认就是开的。\n")
        r = vc._static_default_claims_consistent(self.root)
        self.assertTrue(r["ok"], "澄清句不应被误判为矛盾声明；实际: %s" % r.get("error"))


if __name__ == "__main__":
    unittest.main()
