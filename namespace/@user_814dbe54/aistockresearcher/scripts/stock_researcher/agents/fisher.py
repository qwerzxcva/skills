#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
费雪分析 Agent (v9.5)
Philip Fisher Analysis Agent — 成长股投资（《怎样选择成长股》十五要点量化简版）
分析：营收成长 / 盈利质量 / 成长持续性 / 估值容忍度（PEG 思想）
"""

from typing import List

from .master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["FisherAnalyzer"]


class FisherAnalyzer:
    """
    费雪成长股分析（十五要点 → 可量化维度简版）

    核心原则：
    1. 成长潜力：营收持续增长，市场空间足够大
    2. 盈利质量：利润率高于同行且能维持（护城河的代理指标）
    3. 持续性：长期趋势向上 + 波动可控，说明成长不是一次性脉冲
    4. 估值容忍：愿意为确定性成长付溢价，但 PEG 仍要合理
    """

    MASTER = "fisher"
    NAME_CN = "费雪"
    STYLE = "成长股投资：寻找营收与利润可持续增长的公司，愿意为确定性付溢价"

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行费雪风格分析（依赖基本面，缺失时降低置信度）"""
        pts: List[str] = []
        score = 0.0
        parts = 0  # 参与评分的维度数（用于归一化）

        # 1) 营收成长（-30 ~ +30）
        if inp.revenue_growth != 0 or inp.has_fundamentals:
            g = inp.revenue_growth
            parts += 1
            if g >= 30:
                score += 30
                pts.append(f"营收增速 {g:+.1f}% ≥ 30%，高速成长")
            elif g >= 10:
                score += 18
                pts.append(f"营收增速 {g:+.1f}%，稳健成长")
            elif g > 0:
                score += 6
                pts.append(f"营收增速 {g:+.1f}%，成长偏慢")
            else:
                score -= 20
                pts.append(f"营收负增长 {g:+.1f}%，不符合成长股标准")

        # 2) 盈利质量（-20 ~ +20）：净利率 + ROE
        if inp.net_margin != 0 or inp.roe != 0:
            parts += 1
            q = 0.0
            if inp.net_margin >= 20:
                q += 10
                pts.append(f"净利率 {inp.net_margin:.1f}%，盈利能力突出")
            elif inp.net_margin >= 10:
                q += 6
            elif inp.net_margin < 0:
                q -= 12
                pts.append(f"净利率 {inp.net_margin:.1f}%，仍在亏损")
            if inp.roe >= 15:
                q += 10
                pts.append(f"ROE {inp.roe:.1f}% ≥ 15%，资本回报优秀")
            elif inp.roe >= 8:
                q += 5
            score += _clamp(q, -20, 20)

        # 3) 成长持续性代理（-20 ~ +20）：长期趋势 + 波动
        if inp.has_prices:
            parts += 1
            s = 0.0
            if inp.ret_250 > 20:
                s += 12
                pts.append(f"近一年涨幅 {inp.ret_250:+.1f}%，市场验证成长逻辑")
            elif inp.ret_250 > 0:
                s += 6
            elif inp.ret_250 < -30:
                s -= 15
                pts.append(f"近一年跌幅 {inp.ret_250:+.1f}%，成长逻辑遭市场质疑")
            if 0 < inp.ann_vol <= 35:
                s += 8
            elif inp.ann_vol > 60:
                s -= 8
                pts.append(f"年化波动 {inp.ann_vol:.0f}% 过高，成长稳定性存疑")
            score += _clamp(s, -20, 20)

        # 4) 估值容忍（-20 ~ +20）：PEG 思想（PE 相对增速）
        if inp.pe > 0 and inp.revenue_growth > 5:
            parts += 1
            peg = inp.pe / inp.revenue_growth
            if peg <= 1.0:
                score += 20
                pts.append(f"PEG≈{peg:.2f} ≤ 1，成长未被充分定价")
            elif peg <= 2.0:
                score += 8
            elif peg <= 3.5:
                score -= 5
            else:
                score -= 18
                pts.append(f"PEG≈{peg:.1f}，估值已透支成长")
        elif inp.pe > 0 and inp.revenue_growth <= 0:
            parts += 1
            if inp.pe > 40:
                score -= 15
                pts.append(f"负增长叠加 PE {inp.pe:.1f}，估值风险大")

        if parts == 0:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少基本面数据（营收增速/净利率/ROE），无法评估成长性"])

        # 归一化到 -100~100（按满分 70/维度均值折算）
        score = _clamp(score / max(parts, 1) / 30 * 100 * 0.9, -100, 100)
        conf = min(0.5 + parts * 0.125, 1.0) * inp.data_completeness() + 0.2
        conf = _clamp(conf, 0.3, 0.95)
        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            round(conf, 2), pts)
