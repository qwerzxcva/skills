#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
霍华德·马克斯分析 Agent (v9.5)
Howard Marks Analysis Agent — 周期定位与风险温度计（《周期》《投资最重要的事》）
分析：风险温度 0~100 / 钟摆位置 / 第二层次思维提示
"""

from typing import List

from stock_researcher.agents_master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["MarksAnalyzer"]


class MarksAnalyzer:
    """
    马克斯周期与风险分析

    核心原则：
    1. 钟摆理论：市场情绪永远在贪婪与恐惧之间摆动，极少停在中间
    2. 风险温度：高位+高动量+估值扩张 = 高温（风险大于机会）
    3. 第二层次思维：高温时众人看多恰是风险，低温时众人恐慌恰是机会
    """

    MASTER = "marks"
    NAME_CN = "马克斯"
    STYLE = "周期与风险温度：在别人贪婪时测量风险，在别人恐惧时发现机会"

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行马克斯风格分析（逆向视角：温度越高评分越低）"""
        if not inp.has_prices and inp.pe <= 0:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少行情与估值数据，无法测量风险温度"])

        pts: List[str] = []
        temp = 50.0  # 风险温度 0(极度恐惧) ~ 100(极度贪婪)

        # 1) 位置分量（±20）：52 周区间位置
        if inp.has_prices:
            temp += (inp.pos_52w - 0.5) * 40
            if inp.pos_52w > 0.9:
                pts.append(f"价格处于 52 周区间 {inp.pos_52w:.0%} 高位，贪婪迹象")
            elif inp.pos_52w < 0.15:
                pts.append(f"价格处于 52 周区间 {inp.pos_52w:.0%} 低位，恐慌迹象")

        # 2) 动量分量（±15）：极端动量推高温度
        if inp.has_prices:
            blend = inp.momentum_blend()
            temp += _clamp(blend * 0.8, -15, 15)

        # 3) 估值分量（±15）：PE 高低（用经验带近似，非精确分位）
        if inp.pe > 0:
            if inp.pe >= 60:
                temp += 15
                pts.append(f"PE {inp.pe:.1f} 处于昂贵区域")
            elif inp.pe >= 35:
                temp += 8
            elif inp.pe <= 10:
                temp -= 15
                pts.append(f"PE {inp.pe:.1f} 处于廉价区域")
            elif inp.pe <= 18:
                temp -= 6
        if inp.dividend_yield >= 4:
            temp -= 8
            pts.append(f"股息率 {inp.dividend_yield:.1f}% 提供下行缓冲")

        temp = _clamp(temp, 0, 100)

        # 4) 钟摆位置标签
        if temp >= 75:
            zone = "贪婪区（钟摆摆向乐观极端）"
        elif temp >= 55:
            zone = "偏暖区（情绪温和偏乐观）"
        elif temp > 40:
            zone = "中性区（钟摆接近中心，罕见）"
        elif temp > 20:
            zone = "偏冷区（情绪温和偏悲观）"
        else:
            zone = "恐惧区（钟摆摆向悲观极端）"
        pts.append(f"钟摆位置：{zone}")

        # 5) 第二层次思维提示
        if temp >= 75:
            pts.append("第二层次思维：人人看好时，问问'还有谁没买入？'——风险大于机会")
        elif temp <= 25:
            pts.append("第二层次思维：人人恐慌时，问问'坏消息是否已充分定价？'——机会大于风险")

        # 逆向评分：温度 → 评分（高温低分、低温高分），幅度 ±70
        score = _clamp((50 - temp) * 1.4, -70, 70)
        conf = 0.55 + (0.1 if inp.pe > 0 else 0) + (0.1 if inp.has_prices else 0)
        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            round(_clamp(conf, 0.3, 0.9), 2),
                            [f"风险温度：{temp:.0f}/100"] + pts)
