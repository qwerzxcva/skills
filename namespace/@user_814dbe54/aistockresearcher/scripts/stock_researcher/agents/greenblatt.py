#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格林布拉特分析 Agent (v9.5)
Joel Greenblatt Analysis Agent — 神奇公式（Magic Formula）
分析：收益率因子（Earnings Yield ≈ 1/PE）× 资本回报因子（ROE/ROIC 代理）双因子排名评分
"""

from typing import List

from .master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["GreenblattAnalyzer"]


class GreenblattAnalyzer:
    """
    格林布拉特神奇公式分析

    核心原则：
    1. 以合理价格买好公司：用两个因子同时打分
    2. 收益率因子：EBIT/EV 的近似 → 用 1/PE（盈利收益率）
    3. 资本回报因子：EBIT/净经营资产 的近似 → 用 ROE
    4. 单因子不可得时降权处理，不编造排名
    """

    MASTER = "greenblatt"
    NAME_CN = "格林布拉特"
    STYLE = "神奇公式：便宜（高盈利收益率）+ 优质（高资本回报）双因子打分"

    # 经验分带（横截面排名的单标的近似）
    PE_BANDS = [(10, 90), (15, 75), (20, 60), (30, 40), (45, 20)]  # pe≤阈值 → 分
    ROE_BANDS = [(25, 90), (15, 70), (8, 45), (0, 20)]            # roe≥阈值 → 分

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行神奇公式评分（至少需估值或资本回报其一）"""
        pts: List[str] = []
        ey_score = None  # 收益率因子分 0~100
        rc_score = None  # 资本回报因子分 0~100

        # 1) 收益率因子：盈利收益率 = 1/PE
        if inp.pe > 0:
            ey = 100 / inp.pe  # %
            ey_score = 10
            for pe_th, s in self.PE_BANDS:
                if inp.pe <= pe_th:
                    ey_score = s
                    break
            pts.append(f"盈利收益率 {ey:.1f}%（PE {inp.pe:.1f}），因子分 {ey_score}")

        # 2) 资本回报因子：ROE 代理
        if inp.roe != 0 or inp.has_fundamentals:
            rc_score = 5
            for roe_th, s in self.ROE_BANDS:
                if inp.roe >= roe_th:
                    rc_score = s
                    break
            if inp.roe < 0:
                rc_score = 0
                pts.append(f"ROE {inp.roe:.1f}% 为负，资本回报因子计零分")
            else:
                pts.append(f"ROE {inp.roe:.1f}%（资本回报代理），因子分 {rc_score}")

        if ey_score is None and rc_score is None:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少 PE 与 ROE，无法计算神奇公式双因子"])

        # 3) 双因子合成（可得因子等权平均 → 映射到 -100~100）
        factors = [s for s in (ey_score, rc_score) if s is not None]
        combo = sum(factors) / len(factors)        # 0~100
        score = _clamp((combo - 50) * 2, -100, 100)
        if ey_score is not None and rc_score is not None:
            conf = 0.85
            pts.append("双因子齐备，按神奇公式等权合成")
        else:
            conf = 0.55
            pts.append("仅单因子可得，结果仅供参考（横截面排名需全市场数据）")

        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            conf, pts)
