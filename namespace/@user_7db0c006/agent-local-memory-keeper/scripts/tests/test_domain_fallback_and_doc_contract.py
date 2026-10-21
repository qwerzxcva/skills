# -*- coding: utf-8 -*-
"""4.9.21 回归：兜底域开关（§5.5）+ 清理/冲突告警的「文档契约」（§5.3/§5.4）。

背景（三条都源自 2026-09-13 交接单核验）：
- §5.5 `distill`/`deposit` 的 `domain` 缺省落空（14/23 为 None）。排查发现 **None 是有意设计**：
  `_doctor.py` 明文「fallback_domain 是兜底筐，未匹配记忆存为 domain=None，其覆盖由『域分布』
  的 none 桶体现」，且 `reclassify_by_taxonomy` 明文拒绝「强行推到 fallback」。
  ⇒ 结论：**不是改默认，而是加显式开关**（默认关 = 行为与旧版逐字一致）。
- §5.3 `purge` 只筛「已归档/已被取代 + 超龄 + 低重要度」，清不掉当天噪音——把边界写进
  SKILL.md 与 `--help`，消除「误用 purge 清当天噪音」的复发面。
- §5.4 `--check-conflict` 的矛盾侧是启发式（相似度 + 正负情感词），误报占多数——文案必须
  写明「须人工读正文裁定，勿直接隔离」。

本测试锁定上述 6 条断言（3 类）。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL_ROOT = os.path.dirname(SCRIPTS)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import memory_ops as M  # noqa: E402

MEM_BRIDGE = os.path.join(SKILL_ROOT, "mem_bridge.py")
SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")
PY = sys.executable

# 不在任何域关键词/已知域里，确保「域判定落空」可复现
_NOMATCH = "zzqqxxkw"


def _read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


class DomainFallbackSwitchTest(unittest.TestCase):
    """§5.5：兜底域是**显式开关**，默认关。"""

    def setUp(self):
        self._saved = os.environ.pop("KEEPER_DOMAIN_FALLBACK", None)
        self.store = tempfile.mkdtemp(prefix="keeper_domfb_")
        M.init_store(self.store)

    def tearDown(self):
        if self._saved is not None:
            os.environ["KEEPER_DOMAIN_FALLBACK"] = self._saved
        else:
            os.environ.pop("KEEPER_DOMAIN_FALLBACK", None)
        shutil.rmtree(self.store, ignore_errors=True)

    def _deposit(self, tags=None):
        return M.deposit(self.store, "note",
                         "心得 %s" % _NOMATCH, tags if tags is not None else ["raw"],
                         "body about %s" % _NOMATCH)

    def _domain_of(self, mid):
        mem, _ = M._load_mem(self.store, mid)
        return mem.get("domain"), (mem.get("tags") or [])

    def test_default_off_domain_stays_none(self):
        """默认（不设 env）→ domain 仍为 None：**行为与旧版逐字一致**（关键回归点）。"""
        mid = self._deposit()
        dom, tags = self._domain_of(mid)
        self.assertIsNone(dom, "默认关时不应落任何兜底域（None 是有意设计）")
        self.assertNotIn("domain:fallback", tags, "默认关时不应打兜底标签")

    def test_env_on_backfills_and_marks(self):
        """KEEPER_DOMAIN_FALLBACK=general → 落域 + 打 domain:fallback 标签（可与显式同名域区分）。"""
        os.environ["KEEPER_DOMAIN_FALLBACK"] = "general"
        mid = self._deposit()
        dom, tags = self._domain_of(mid)
        self.assertEqual(dom, "general", "开启后域判定落空应落到兜底域")
        self.assertIn("domain:fallback", tags, "兜底落域必须打标签以便区分/复核")

    def test_off_values_disable(self):
        """off/none/0/false → 视为关闭（避免用户写 'off' 反而开启）。"""
        for v in ("off", "none", "0", "false", "OFF", "None"):
            os.environ["KEEPER_DOMAIN_FALLBACK"] = v
            mid = self._deposit()
            dom, _ = self._domain_of(mid)
            self.assertIsNone(dom, "KEEPER_DOMAIN_FALLBACK=%r 应视为关闭" % v)

    def test_existing_routing_wins_over_fallback(self):
        """兜底域**绝不覆盖**更智能的既有判定：tags 命中已知域时保留该域、不打 fallback 标签。"""
        os.environ["KEEPER_DOMAIN_FALLBACK"] = "general"
        mid = self._deposit(tags=["investment", "raw"])
        dom, tags = self._domain_of(mid)
        self.assertEqual(dom, "investment", "tags 已能判定域时，兜底不得抢占")
        self.assertNotIn("domain:fallback", tags, "非落空路径不应打兜底标签")

    def test_fallback_entry_still_listed_as_pending(self):
        """兜底落域 ≠ 已归类：`reclassify --pending` 仍须把它列为缺 domain（防静默消失）。"""
        os.environ["KEEPER_DOMAIN_FALLBACK"] = "general"
        mid = self._deposit()
        r = M.reclassify_pending(self.store)
        hit = [e for e in r.get("pending", []) if e.get("id") == mid]
        self.assertTrue(hit, "兜底落域的条目不应从质量队列消失")
        self.assertIn("domain", hit[0].get("missing", []),
                      "domain:fallback 不算已归类，仍应报 domain 缺失")


class CleaningAndConflictDocContractTest(unittest.TestCase):
    """§5.3/§5.4：边界与「须人工裁定」必须出现在用户真正会看的地方。"""

    def test_skill_md_has_purge_boundary(self):
        t = _read(SKILL_MD)
        self.assertIn("`purge` **不是**通用清理", t, "SKILL.md 缺 purge 边界段")
        self.assertIn("今天刚记的", t, "SKILL.md 未点明「清不掉当天噪音」")
        self.assertIn("清理类命令怎么选", t, "SKILL.md 缺清理命令对照段")

    def test_skill_md_has_domain_none_semantics(self):
        t = _read(SKILL_MD)
        self.assertIn("域分类落空 = `domain=None`，是设计不是缺陷", t,
                      "SKILL.md 未声明 domain=None 是设计")
        self.assertIn("KEEPER_DOMAIN_FALLBACK", t, "SKILL.md 未给出开关名")

    def test_mem_bridge_source_has_conflict_caveat(self):
        t = _read(MEM_BRIDGE)
        self.assertGreaterEqual(t.count("须人工读正文"), 2,
                                "矛盾告警缺「须人工读正文裁定」")
        self.assertIn("不等同结论相悖", t, "未写明启发式告警 ≠ 结论矛盾")
        self.assertIn("不得据此自动隔离或删除", t, "_b_conflict_check 契约缺禁止性说明")

    def test_cli_help_exposes_boundaries(self):
        """真实跑 --help：purge 边界与 distill 冲突告警的文案必须对用户可见。"""
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"

        def _help(*args):
            p = subprocess.run([PY, MEM_BRIDGE, *args], cwd=SKILL_ROOT, env=env,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=180)
            return (p.stdout or "") + (p.stderr or "")

        purge_h = _help("purge", "--help")
        self.assertIn("不在候选内", purge_h, "purge --help 未说明 active 不在候选内")
        self.assertIn("清当天噪音请用", purge_h, "purge --help 未给替代路径")

        distill_h = _help("distill", "--help")
        self.assertIn("人工读正文", distill_h, "--check-conflict 帮助未提示须人工裁定")


if __name__ == "__main__":
    unittest.main(verbosity=2)
