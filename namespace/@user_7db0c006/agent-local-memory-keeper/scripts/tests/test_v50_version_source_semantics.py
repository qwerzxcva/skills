# -*- coding: utf-8 -*-
"""版本字段**语义分离**回归锁（5.0.0）。

背景（本轮实锤的真缺陷）：`_meta.json` 与 `SKILL.md` frontmatter 是**两个不同概念**——
  · `_meta.json.version`   = 平台**上次发布 / 本机已安装**版本（发布器 `update_meta()`
                             在发布成功后回写；该文件不进发布包，见 publish_skill.py:99）
  · `SKILL.md frontmatter` = **本地源码当前版本**（本仓约定的「版本单一真源」，见
                             `_hooks._read_skill_version` 的 docstring）

此前 `_doctor.release_audit` 把二者当「同一概念的两种来源」做「**优先 `_meta.json`**，
回退 SKILL.md」，后果：

  1. **开发者机器上 `local_version` 永远读到陈旧值** —— 实测源码 `5.0.0` 却报 `4.9.25`；
  2. 更严重：「双主」告警被同源污染。本机 `lvp == plp` 时两条分支都不走 ⇒ 长期**静默**；
     线上一旦发布任何新版本（如 4.9.26）⇒ `lvp(4.9.25) < plp(4.9.26)` ⇒ **误报
     `verdict="drift"`**，并提示「先把线上包取回做基准，再动任何代码」——而本地源码其实
     **领先**。那条指引会覆盖掉未发布的本地改动。
  3. `_self_heal._verify_version_alignment` 同根因：把 `_meta.json` 当「同概念第三源」，
     开发者机器上必然 `aligned=False`，把**常态**当**错位**告警。

🔴 **「测试全绿 ≠ 现实正确」**：旧测试 `test_release_audit.py` 的 `_mk_skill()` 把两处版本
写成**同值**，恰好绕过真机形态（`_meta.json` 落后源码）。本文件专锁该形态，并保留
「真双主前兆仍须报」的反向锁，避免把告警一并修没。

全部用注入参数或临时目录，**不发真实网络请求**、不碰真实记忆库。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import memory_ops as M  # noqa: E402

RA = M.release_audit
_MOPS_DIR = os.path.join(SCRIPTS, "memory_ops")

# 临时目录统一回收：门禁虽有 `keeper_` 前缀兜底回收（`run_gate.py` 跑完清本轮），
# 但**单独跑本文件**时不经过门禁 ⇒ 会留残渣。这里自己收口（与仓内 `test_release_audit`
# 等文件同款做法），保证「跑单个测试文件」也零残留。
_TMPDIRS = []


def tearDownModule():
    for _d in _TMPDIRS:
        shutil.rmtree(_d, ignore_errors=True)
    del _TMPDIRS[:]


def _mk_skill(source_version="5.0.0", meta_version="4.9.25",
              changelog_versions=None, slug="agent-local-memory-keeper"):
    """技能目录：SKILL.md frontmatter 与 `_meta.json` 版本**分别**指定（真机形态）。

    `meta_version=None` = 不写 `_meta.json`（纯净源码树）。
    """
    d = tempfile.mkdtemp(prefix="keeper_versrc_")
    _TMPDIRS.append(d)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: x\nversion: %s\n---\n\n# x\n" % source_version)
    if meta_version is not None:
        with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": slug, "version": meta_version}, f)
    if changelog_versions:
        body = "".join("## %s \u00b7 2026-09-17\n\n> x\n\n" % v for v in changelog_versions)
        with open(os.path.join(d, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write("# CHANGELOG\n\n" + body)
    return d


class ReleaseAuditVersionSourceTest(unittest.TestCase):
    """release-audit：`local_version` 取**源码**，双主告警比**安装版本**。"""

    def test_local_version_comes_from_skill_md_when_meta_lags(self):
        """★ 真机形态：`_meta.json` 落后源码 ⇒ `local_version` 仍是源码版本。"""
        fx = _mk_skill(source_version="5.0.0", meta_version="4.9.25")
        r = RA(skill_root=fx, changelog_versions=["4.9.25", "5.0.0"],
               platform_versions=["4.9.25"])
        self.assertEqual(r["local_version"], "5.0.0",
                         "local_version 必须取 SKILL.md frontmatter（版本单一真源）")
        self.assertEqual(r["installed_version"], "4.9.25",
                         "`_meta.json` 的版本须单独暴露为 installed_version")

    def test_meta_lagging_does_not_trigger_double_master(self):
        """🔴 核心回归锁：源码领先 + 安装版本与线上齐平 ⇒ **不得**报 drift / 双主 / 取回线上包。"""
        fx = _mk_skill(source_version="5.0.0", meta_version="4.9.25")
        r = RA(skill_root=fx, changelog_versions=["4.9.25", "5.0.0"],
               platform_versions=["4.9.25"])
        self.assertEqual(r["verdict"], "ok", "源码领先是常态，不是 drift")
        joined = " ".join(r["hints"])
        self.assertNotIn("双主", joined, "安装版本与线上齐平时不得报双主")
        self.assertNotIn("取回做基准", joined,
                         "那条指引会覆盖本地未发布改动，绝不得出现")
        self.assertIn("未发布改动", joined, "应作为**信息项**指出源码领先")

    def test_installed_version_behind_platform_still_flags_double_master(self):
        """反向锁：**安装版本**真落后线上时，双主前兆仍须报（别把告警一并修没）。

        构造要点：平台版本全部在 CHANGELOG 里 ⇒ `missing_log` 为空 ⇒ drift 只能由
        `installed_version < platform_latest` 触发，精确命中「同语义比较」这条路径。
        """
        fx = _mk_skill(source_version="5.0.0", meta_version="4.9.24")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.24", "4.9.25", "5.0.0"],
               platform_versions=["4.9.24", "4.9.25"])
        self.assertEqual(r["missing_log"], [], "本用例的前提：无绕过日志的版本")
        self.assertEqual(r["verdict"], "drift")
        self.assertIn("双主", " ".join(r["hints"]))

    def test_missing_meta_falls_back_to_source_and_leaves_installed_empty(self):
        """没有 `_meta.json`（纯净源码树）⇒ 回退源码版本，`installed_version` 为空。"""
        fx = _mk_skill(source_version="5.0.0", meta_version=None)
        r = RA(skill_root=fx, changelog_versions=["5.0.0"],
               platform_versions=["5.0.0"])
        self.assertEqual(r["local_version"], "5.0.0")
        self.assertEqual(r["installed_version"], "")

    def test_source_code_keeps_the_separation(self):
        """静态锁：`local_version` 的赋值**只能**来自 frontmatter 变量（防改回旧口径）。"""
        with io.open(os.path.join(_MOPS_DIR, "_doctor.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('out["local_version"] = v_source or v_installed', src,
                      "local_version 的主源必须是 frontmatter（v_source）")
        self.assertIn('out["installed_version"] = v_installed', src)
        self.assertIn('_parse_ver(out["installed_version"]), _parse_ver(out["platform_latest"])',
                      src, "双主告警必须比 installed_version ↔ platform_latest（同语义）")


class SelfHealAlignmentLayerTest(unittest.TestCase):
    """`_self_heal._verify_version_alignment`：源码层判对齐，安装层只记录。"""

    def _fn(self):
        # `_self_heal` 不在 `_SUBMODULES`（由专用 loader 块加载），但模块对象在包全局
        # 命名空间里，可经 `_self_heal_mod` 取得（与 `__init__` 内 `self_heal = ...` 同源）。
        return M._self_heal_mod._verify_version_alignment

    def test_source_layer_mismatch_is_flagged(self):
        """SKILL.md ↔ CHANGELOG.md 不一致 = 真错位 ⇒ aligned=False。"""
        fx = _mk_skill(source_version="5.0.0", meta_version="4.9.25",
                       changelog_versions=["4.9.25"])
        r = self._fn()(fx)
        self.assertFalse(r["aligned"])
        self.assertTrue(r["mismatch"])

    def test_installed_lag_is_not_misalignment(self):
        """🔴 开发者机器常态：`_meta.json` 落后源代码 ⇒ aligned 仍 True，只记 installed_lag。"""
        fx = _mk_skill(source_version="5.0.0", meta_version="4.9.25",
                       changelog_versions=["5.0.0"])
        r = self._fn()(fx)
        self.assertTrue(r["aligned"], "安装版本落后是常态，不得判成错位")
        self.assertTrue(r["installed_lag"])
        self.assertTrue(r["notes"])
        self.assertEqual(r["sources"]["meta"], "4.9.25",
                         "`_meta.json` 仍须如实暴露在 sources 里（供人核对）")

    def test_all_three_agree_is_clean(self):
        """三处一致（纯净发布态）⇒ 无告警、无 note。"""
        fx = _mk_skill(source_version="5.0.0", meta_version="5.0.0",
                       changelog_versions=["5.0.0"])
        r = self._fn()(fx)
        self.assertTrue(r["aligned"])
        self.assertFalse(r["installed_lag"])
        self.assertEqual(r["notes"], [])
        self.assertEqual(r["mismatch"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
