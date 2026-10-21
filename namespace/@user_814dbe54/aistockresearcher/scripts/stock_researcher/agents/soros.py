#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
索罗斯分析 Agent (v9.5)
George Soros Analysis Agent — 反身性（Reflexivity）与盛衰周期
分析：动量自我强化 / 盛衰阶段定位 / 趋势反转风险
"""

from typing import List

from .master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["SorosAnalyzer"]


class SorosAnalyzer:
    """
    索罗斯反身性交易分析

    核心原则：
    1. 反身性：价格上涨强化乐观预期，预期再推动价格 → 自我强化循环
    2. 盛衰周期：启动→自我强化→考验期→黄昏→崩溃，趋势后段风险陡增
    3. 可错性：认知永远有偏差，极端动量 + 波动放大 = 反转信号
    """

    MASTER = "soros"
    NAME_CN = "索罗斯"
    STYLE = "反身性趋势交易：顺势而为，在自我强化循环的黄昏前离场"

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行索罗斯风格分析（需要行情序列，缺省时诚实降级）"""
        if not inp.has_prices:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少历史行情，无法判断反身性趋势阶段"])

        pts: List[str] = []
        blend = inp.momentum_blend()

        # 1) 动量方向分（-60 ~ +60）：加权动量映射
        mom_score = _clamp(blend * 3.0, -60, 60)

        # 2) 自我强化判定：短中期同向且短期加速 → 强化循环成立
        reinforcing = (inp.ret_20 > 0 and inp.ret_60 > 0
                       and inp.ret_20 * 2.5 > inp.ret_60)
        weakening = (inp.ret_60 > 0 and inp.ret_20 < 0)
        if reinforcing:
            mom_score += 15
            pts.append(f"短期涨幅 {inp.ret_20:+.1f}% 加速，反身性自我强化成立")
        elif weakening:
            mom_score -= 20
            pts.append(f"60日涨幅 {inp.ret_60:+.1f}% 但20日转跌，强化循环疑似断裂")

        # 3) 盛衰阶段定位
        stage = self._locate_stage(inp)
        pts.append(f"盛衰周期定位：{stage['label']}")
        mom_score += stage["adj"]

        # 4) 反转风险：极端动量 + 高波动 → 黄昏惩罚
        if inp.pos_52w > 0.9 and inp.ann_vol > 45 and inp.ret_20 > 15:
            mom_score -= 25
            pts.append(f"52周高位({inp.pos_52w:.0%})叠加年化波动 {inp.ann_vol:.0f}%，警惕盛极而衰")
        if inp.pos_52w < 0.1 and inp.ret_20 < -10:
            mom_score -= 10
            pts.append("低位阴跌未见底，反身性向下循环未结束")

        score = _clamp(mom_score, -100, 100)
        conf = 0.6 if inp.pe > 0 else 0.5  # 纯行情驱动，置信上限受限
        if not pts:
            pts.append(f"动量混合 {blend:+.1f}%，趋势中性")
        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            conf, pts)

    @staticmethod
    def _locate_stage(inp: MasterInput) -> dict:
        """盛衰五阶段粗定位 → (标签, 评分修正)"""
        if inp.ret_60 > 15 and inp.pos_52w > 0.85:
            if inp.ann_vol > 40:
                return {"label": "黄昏期（高位高波动，趋势可能衰竭）", "adj": -15}
            return {"label": "自我强化后期（趋势强但需防考验期）", "adj": -5}
        if inp.ret_60 > 5 and inp.ret_20 > 0:
            return {"label": "自我强化期（顺势持有）", "adj": 10}
        if inp.ret_60 < -15 and inp.pos_52w < 0.2:
            return {"label": "崩溃后低位（等待新循环启动信号）", "adj": 0}
        if inp.ret_60 < -5 and inp.ret_20 < 0:
            return {"label": "向下强化期（规避）", "adj": -10}
        return {"label": "启动/考验期（方向未明，小仓试探）", "adj": 0}
