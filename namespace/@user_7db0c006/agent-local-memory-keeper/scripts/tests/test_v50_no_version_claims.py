# -*- coding: utf-8 -*-
"""5.0 防复发锁 · 用户向文档不得残留版本号（闸门有效性 + 真仓实况）。

背景（为什么需要这组锁）：
  这条规则**早就写在文档里**（`references/EVOLUTION.md` 开头的 ⚠️ 块），
  判据也在 CHANGELOG 4.9.9 定过（「版本号只是时间戳式的叙事前缀，去掉后原意不损」），
  但**从未有过闸门** —— 结果 5.0 开发期把 4.9.9 清理过的 `FORMAT_ANALYSIS.md`
  又写脏了（2 处「5.0 起」），另有 COMMANDS / FEATURES / QA / QUICKSTART /
  recovery_runbook 共 6 文件 10 处。规则靠人自觉 = 必然回归。

本组锁防三件事：
  A 有效性：真版号必须被抓（含「（双时序，5.0）」这类不带「起/新增」的写法）
  B 精度  ：数值 / IP / Python 版本路径 / 章节号 / 参数值不得误报
  C 实况  ：真技能树自身必须 0 命中
"""
import importlib.util as ilu
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(_HERE)
SKILL_ROOT = os.path.dirname(SCRIPTS)
_SRC = os.path.join(SCRIPTS, "verify_claims.py")

_spec = ilu.spec_from_file_location("vc_undertest", _SRC)
vc = ilu.module_from_spec(_spec)
sys.modules["vc_undertest"] = vc
_spec.loader.exec_module(vc)

_BASE_CHANGELOG = (
    "# CHANGELOG\n\n## 5.0.0 · 2026-09-16\n\n> x\n\n## 4.9.27 · 2026-09-15\n\n> y\n")
_BASE_SKILL = "---\nname: t\nversion: 5.0.0\n---\n\nbody\n"


class VersionClaimGateTest(unittest.TestCase):
    """闸门行为锁（隔离假库，不触碰真技能树）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_vergate_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "skill")
        os.makedirs(os.path.join(self.root, "references", "_design"), exist_ok=True)

    # ── helpers ──
    def _w(self, rel, text):
        p = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def _base(self):
        self._w("CHANGELOG.md", _BASE_CHANGELOG)
        self._w("SKILL.md", _BASE_SKILL)

    def _verdict(self):
        return vc._static_no_version_claims_in_user_docs(self.root)

    def _blob(self):
        return json.dumps(self._verdict(), ensure_ascii=False)

    # ── A · 有效性：真版号必须被抓 ──
    def test_real_version_is_flagged(self):
        self._base()
        self._w("QUICKSTART.md", "- 本 skill 自 4.9.27 起不再提供加密\n")
        v = self._verdict()
        self.assertFalse(v["ok"], "真版号 4.9.27 未被抓：闸门形同虚设")
        self.assertIn("QUICKSTART.md:1", self._blob())

    def test_bare_version_form_is_flagged(self):
        """历史漏报形态：不带「起 / 新增」，直接写在括号里。"""
        self._base()
        self._w("references/COMMANDS.md", "| `invalidate` | 软失效（双时序，5.0）：不删不搬 |\n")
        v = self._verdict()
        self.assertFalse(v["ok"], "「（双时序，5.0）」未被抓：口径过窄")
        self.assertIn("COMMANDS.md:1", self._blob())

    def test_v_prefixed_form_is_flagged(self):
        self._base()
        self._w("references/QA.md", "- 自 v4.9.27 起改用 SQLite\n")
        self.assertFalse(self._verdict()["ok"], "带 v 前缀的版本号未被抓")

    # ── B · 精度：数值 / 路径 / 章节号不得误报 ──
    def test_numeric_and_path_noise_not_flagged(self):
        self._base()
        self._w(
            "references/COMMANDS.md",
            "- bind 127.0.0.1 random port\n"
            "- python at versions/3.13.12/python.exe\n"
            "- see SKILL.md 4.3 section\n"
            "- top=5 and chars=1200 and 2.92s and 1.66x\n"
            "- rrf_weak=0.03 threshold\n"
            "- talks to an external api v1.2 endpoint\n",
        )
        v = self._verdict()
        self.assertTrue(v["ok"], "数值/路径/章节号被误报：%s" % json.dumps(v, ensure_ascii=False))
        self.assertIn("0 处版本号", str(v["actual"]))

    # ── C · 豁免面 ──
    def test_frontmatter_version_is_exempt(self):
        self._base()
        self._w("SKILL.md", "---\nname: t\nversion: 5.0.0\n---\n\nbody\n")
        self.assertTrue(self._verdict()["ok"], "frontmatter 的 version: 被误报（它是版本单一真源）")

    def test_exempt_files_are_skipped(self):
        self._base()
        self._w("references/EVOLUTION.md", "v4.7.0 replaced v4.6.13 skip_dedup\n")
        self._w("references/_design/changelog_archive.md", "## 4.5.49 · x\n")
        self.assertTrue(self._verdict()["ok"], "豁免文件被误扫")

    def test_changelog_itself_is_skipped(self):
        self._base()
        # 记账本满篇版本号是它的职责
        self.assertTrue(self._verdict()["ok"])

    # ── D · 基线缺失必须响亮（不得静默 ok） ──
    def test_missing_baseline_fails_loudly(self):
        self._w("references/QA.md", "anything\n")   # 无 CHANGELOG / SKILL.md
        v = self._verdict()
        self.assertFalse(v["ok"], "判定基线缺失时静默通过：闸门会永远 OK")
        self.assertIn("基线缺失", str(v["error"]))

    # ── E · 真仓实况（最高价值的一条） ──
    def test_real_skill_tree_is_clean(self):
        v = vc._static_no_version_claims_in_user_docs(SKILL_ROOT)
        self.assertTrue(
            v["ok"],
            "真技能树的用户向文档残留版本号（发版阻塞项）：%s"
            % json.dumps(v.get("actual"), ensure_ascii=False))

    def test_real_skill_tree_scan_is_not_empty(self):
        """防止闸门因路径写错而「扫了 0 个文档」却报 ok。"""
        v = vc._static_no_version_claims_in_user_docs(SKILL_ROOT)
        self.assertGreaterEqual(
            len(vc._repo_version_set(SKILL_ROOT)), 10,
            "版本号集合异常小：CHANGELOG 解析可能失效")


if __name__ == "__main__":
    unittest.main()
