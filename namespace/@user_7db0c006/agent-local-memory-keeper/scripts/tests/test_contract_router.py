# -*- coding: utf-8 -*-
"""RouteRegistry 单测（随包发布，纯逻辑）。

覆盖：
- decide_home 规则优先级（tag > scope > category > 默认 L4）；
- scope 字段三值映射（universal→L2 / project→L3 / ephemeral→L4）；
- 非法层拒绝；
- 跨层重复检测（同事实落多层的冲突只报告）；
- 持久化 round-trip（fail-open）；
- promotion_candidates：裸计数 → 可操作清单（含 canonical 层、确定性排序）。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from contract.router import decide_home, RouteRegistry, LAYERS  # noqa: E402


class DecideHomeTest(unittest.TestCase):
    def test_tag_wins_over_category(self):
        self.assertEqual(
            decide_home(tags=["cross_project"], category="project_context"),
            "L2")

    def test_category_fallback(self):
        self.assertEqual(decide_home(tags=[], category="project_context"), "L3")

    def test_default_l4(self):
        self.assertEqual(decide_home(tags=[], category=None), "L4")
        self.assertEqual(decide_home(tags=["random"], category="unknown"), "L4")

    # ── A（4.9.26）：scope 字段兜底判定 ──
    def test_scope_field_maps_to_layer(self):
        """scope 是 100% 覆盖的结构化字段（真库 universal 142/project 70/ephemeral 4），
        语义与 L2/L3/L4 一一对应；此前 router 从不读它 → 216 条全落 L4。"""
        self.assertEqual(decide_home(tags=[], category=None, scope="universal"), "L2")
        self.assertEqual(decide_home(tags=[], category=None, scope="project"), "L3")
        self.assertEqual(decide_home(tags=[], category=None, scope="ephemeral"), "L4")

    def test_tag_wins_over_scope(self):
        """显式 tag（用户主动写）> scope（可能由分类器推断）。"""
        self.assertEqual(
            decide_home(tags=["cross_project"], category=None, scope="project"), "L2")
        self.assertEqual(
            decide_home(tags=["project"], category=None, scope="universal"), "L3")

    def test_scope_wins_over_category(self):
        self.assertEqual(
            decide_home(tags=[], category="project_context", scope="universal"), "L2")

    def test_unknown_scope_falls_through(self):
        """未知 scope 不得静默判层——应继续走 category / 默认（防止旧文案里的
        非法值 'private' 被当成合法 scope 悄悄改写分层结果）。"""
        self.assertEqual(decide_home(tags=[], category=None, scope="private"), "L4")
        self.assertEqual(
            decide_home(tags=[], category="project_context", scope="private"), "L3")


class RecordConflictTest(unittest.TestCase):
    def test_illegal_layer_rejected(self):
        reg = RouteRegistry()
        with self.assertRaises(ValueError):
            reg.record("k", "L9")

    def test_single_layer_no_conflict(self):
        reg = RouteRegistry()
        home, conf = reg.decide_and_record("fact_a", tags=["project"], category=None)
        self.assertEqual(home, "L3")
        self.assertEqual(conf, ["L3"])
        self.assertFalse(reg.is_duplicate("fact_a"))

    def test_decide_and_record_forwards_scope(self):
        """A（4.9.26）：登记册必须把 scope 透传给 decide_home——
        _deposit.py 的调用点补了 scope=…，若此处漏转发则修复等于空转。"""
        reg = RouteRegistry()
        home, conf = reg.decide_and_record("fact_s", tags=[], scope="universal")
        self.assertEqual(home, "L2")
        self.assertEqual(conf, ["L2"])

    def test_cross_layer_duplicate_detected(self):
        reg = RouteRegistry()
        reg.record("fact_b", "L2")
        reg.record("fact_b", "L4")  # 同一事实又被 L4 沉积
        self.assertTrue(reg.is_duplicate("fact_b"))
        self.assertEqual(reg.conflicts("fact_b"), ["L2", "L4"])
        self.assertEqual(reg.all_conflicts(), {"fact_b": ["L2", "L4"]})


class PersistenceTest(unittest.TestCase):
    def test_round_trip_fail_open(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "route.json")
        reg = RouteRegistry(p)
        reg.decide_and_record("x", tags=["cross_project"])
        reg.save()
        self.assertTrue(os.path.exists(p))
        reg2 = RouteRegistry(p)
        self.assertEqual(reg2.layers_of("x"), ["L2"])


class DistributionTest(unittest.TestCase):
    def test_distribution_counts_by_canonical_layer(self):
        reg = RouteRegistry()
        reg.decide_and_record("a", tags=["cross_project"])   # -> L2
        reg.decide_and_record("b", tags=["project"])         # -> L3
        reg.decide_and_record("c", tags=[])                   # -> L4
        reg.decide_and_record("d", category="standing_convention")  # -> L2
        dist = reg.distribution()
        self.assertEqual(dist["L2"], 2)
        self.assertEqual(dist["L3"], 1)
        self.assertEqual(dist["L4"], 1)
        # 晋升候选 = canonical 为 L2/L3 的事实（应归跨项目/项目层但物理只在 L4）。
        self.assertEqual(dist["L2"] + dist["L3"], 3)

    def test_scope_drives_distribution_like_real_store(self):
        """A（4.9.26）回归：修复前真库 route_distribution 恒为
        {L2:0, L3:0, L4:N}、晋升候选恒 0；接上 scope 后应真实分流。"""
        reg = RouteRegistry()
        for i in range(3):
            reg.decide_and_record("u%d" % i, tags=[], scope="universal")   # -> L2
        for i in range(2):
            reg.decide_and_record("p%d" % i, tags=[], scope="project")     # -> L3
        reg.decide_and_record("e0", tags=[], scope="ephemeral")            # -> L4
        dist = reg.distribution()
        self.assertEqual(dist["L2"], 3)
        self.assertEqual(dist["L3"], 2)
        self.assertEqual(dist["L4"], 1)
        self.assertEqual(dist["L2"] + dist["L3"], 5)  # 晋升候选不再恒 0


class PromotionListTest(unittest.TestCase):
    """2026-09-15 审计：doctor 的 `route_promotion_candidates` 原为裸计数（一行加法），
    无法据此行动。新增 `promotion_candidates()` 返回「哪几条 + canonical 层」清单。"""

    def _reg(self):
        reg = RouteRegistry()
        reg.decide_and_record("u1", tags=[], scope="universal")   # L2
        reg.decide_and_record("u2", tags=[], scope="universal")   # L2
        reg.decide_and_record("p1", tags=[], scope="project")     # L3
        reg.decide_and_record("e1", tags=[], scope="ephemeral")   # L4（非候选）
        return reg

    def test_returns_ids_with_layer(self):
        items = self._reg().promotion_candidates()
        self.assertEqual([(i["id"], i["layer"]) for i in items],
                         [("u1", "L2"), ("u2", "L2"), ("p1", "L3")])
        self.assertEqual(len(items), 3)

    def test_excludes_l4(self):
        ids = {i["id"] for i in self._reg().promotion_candidates()}
        self.assertNotIn("e1", ids, "L4 事实不得进晋升清单")

    def test_deterministic_order_and_limit(self):
        reg = self._reg()
        self.assertEqual(reg.promotion_candidates(), reg.promotion_candidates())
        lim = reg.promotion_candidates(limit=2)
        self.assertEqual(len(lim), 2, "limit 应只截断返回长度")
        self.assertEqual([i["id"] for i in lim], ["u1", "u2"])

    def test_multi_layer_fact_prefers_higher_layer(self):
        """同 fact 曾以不同 scope 登记（L2+L3）→ 清单取更高层 L2（确定性）。"""
        reg = RouteRegistry()
        reg.record("x", "L3")
        reg.record("x", "L2")
        self.assertEqual(reg.promotion_candidates(), [{"id": "x", "layer": "L2"}])


class PromotionObservTest(unittest.TestCase):
    """doctor_contract 必须把清单与「跨层冲突恒空」的诚实说明一起暴露。"""

    def test_observ_exposes_list_and_notes(self):
        from contract.observ import doctor_contract
        reg = RouteRegistry()
        reg.decide_and_record("u1", tags=[], scope="universal")
        out = doctor_contract("", route_registry=reg)
        self.assertEqual(out["route_promotion_candidates"], 1)
        self.assertEqual(out["route_promotion_list"], [{"id": "u1", "layer": "L2"}])
        self.assertIn("原生库", out["route_promotion_note"])
        # inject_total=0 是 silent 默认态的预期配置，必须随数据一起解释
        self.assertIn("预期配置", out["inject_note"])


if __name__ == "__main__":
    unittest.main()
