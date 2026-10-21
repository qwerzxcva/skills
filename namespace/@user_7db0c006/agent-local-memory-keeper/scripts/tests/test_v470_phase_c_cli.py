# -*- coding: utf-8 -*-
""" 相位 C 回归测试：CLI 面 / 能力区引用一致性（unittest 版，纳入随包门禁）。

锁死（反复验证核实的护栏）：CAPABILITY_ZONES 里登记的 bridge_module / seed_fn 模块名
必须指向真实存在的文件，杜绝「 investment_bridge 死引用」这类漂移 bug（曾因模块路径
判断失误被误报为不存在，实则在 scripts/ 下存活）。本测试在发布前静态校验所有引用可解析。

注：经核实，mem_bridge.py 是合法的独立桥接 facade（inject/distill/guard/drift/seed/
coach/promote/to-l2 等均为桥接专属能力，非 recall 的呈现变体），且其绝大多数 op 已
进程内调用 memory_ops，仅少数 recall/overwrite 走 subprocess——故不做高风险的 29 命令
fold-in，保留 facade 反而更清晰。本测试专注「引用一致性」这一可验证、零风险的收口点。
"""
import os
import sys
import unittest

SKILL = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import memory_ops  # noqa: E402


class PhaseCZoneRefsTest(unittest.TestCase):

    def test_zone_module_refs_resolve(self):
        zones = memory_ops.CAPABILITY_ZONES
        self.assertIsInstance(zones, dict)
        self.assertTrue(zones, "CAPABILITY_ZONES 为空或非法")
        for domain, cfg in zones.items():
            for key in ("bridge_module", "seed_fn"):
                mod = (cfg or {}).get(key)
                if not mod:
                    continue
                    # 形如 "scripts.investment_bridge" → scripts/investment_bridge.py
                rel = mod.replace(".", os.sep) + ".py"
                p = os.path.join(SKILL, rel)
                self.assertTrue(os.path.exists(p),
                                "CAPABILITY_ZONES[%r][%r]=%r 指向的模块文件不存在: %s"
                                % (domain, key, mod, p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
