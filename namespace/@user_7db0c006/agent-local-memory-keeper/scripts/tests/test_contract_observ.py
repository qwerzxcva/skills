# -*- coding: utf-8 -*-
"""observ 单测（随包发布，纯逻辑、fail-open）。

覆盖：
- InjectLog 原子追加 + recent 回读；
- doctor_contract 聚合结构（门控阈值/神经激活/注入统计/路由冲突）；
- emit_inject_record 落盘。
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from contract.observ import InjectLog, doctor_contract, emit_inject_record  # noqa: E402
from contract.router import RouteRegistry  # noqa: E402


class InjectLogTest(unittest.TestCase):
    def test_append_and_recent(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "inject.log")
        log = InjectLog(p)
        log.append({"injected": True, "picked": 1})
        log.append({"injected": False, "reason": "no_local_hit"})
        rec = log.recent()
        self.assertEqual(len(rec), 2)
        self.assertEqual(rec[0]["picked"], 1)

    def test_recent_limit(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "inject.log")
        log = InjectLog(p)
        for i in range(5):
            log.append({"i": i})
        self.assertEqual(len(log.recent(2)), 2)


class DoctorTest(unittest.TestCase):
    def test_doctor_structure(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "inject.log")
        emit_inject_record(p, {"injected": True, "picked": 1, "reason": "ok"},
                           session_id="s1")
        reg = RouteRegistry()
        reg.record("dup_fact", "L2")
        reg.record("dup_fact", "L4")
        rep = doctor_contract(p, route_registry=reg, neural_active=True)
        self.assertIn("gate", rep)
        self.assertTrue(rep["neural_recall_active"])
        self.assertEqual(rep["inject_total"], 1)
        self.assertEqual(rep["route_cross_layer_conflicts"], {"dup_fact": ["L2", "L4"]})
        # P1：路由分布 + 晋升候选（canonical 为 L2/L3 的事实数）。
        self.assertIn("route_distribution", rep)
        self.assertIn("route_promotion_candidates", rep)
        # dup_fact 记了 L2 与 L4，distribution 统计各层落地次数；晋升候选 = L2+L3 计数。
        self.assertEqual(rep["route_distribution"].get("L2", 0), 1)
        self.assertEqual(rep["route_distribution"].get("L4", 0), 1)
        self.assertEqual(rep["route_promotion_candidates"], 1)

    def test_doctor_no_registry(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "inject.log")
        rep = doctor_contract(p, route_registry=None, neural_active=False)
        self.assertEqual(rep["route_cross_layer_conflicts"], {})
        self.assertFalse(rep["neural_recall_active"])


if __name__ == "__main__":
    unittest.main()
