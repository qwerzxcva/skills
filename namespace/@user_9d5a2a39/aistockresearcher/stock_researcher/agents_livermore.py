#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
利弗莫尔分析 Agent (v9.5)
Jesse Livermore Analysis Agent — 趋势跟踪与关键点交易（《股票大作手回忆录》）
分析：趋势结构 / 关键点突破 / 最小阻力线 / 试探性建仓纪律
"""

import math
from typing import List

from stock_researcher.agents_master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["LivermoreAnalyzer"]


def _sma(closes: List[float], p: int) -> float:
    """简单均线终值；数据不足返回 NaN"""
    if len(closes) < p:
        return float("nan")
    return sum(closes[-p:]) / p


class LivermoreAnalyzer:
    """
    利弗莫尔趋势交易分析

    核心原则：
    1. 最小阻力线：价格沿阻力最小的方向运动，顺势不逆势
    2. 关键点：盘整后的突破是最佳入场时机（52 周新高附近放量突破）
    3. 试探性建仓：先小仓验证，对了才加码；错了立即离场
    4. 亏损不摊平：跌破关键均线即趋势破坏
    """

    MASTER = "livermore"
    NAME_CN = "利弗莫尔"
    STYLE = "趋势大作手：沿最小阻力线交易，突破关键点时进场，破位即离场"

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行利弗莫尔风格分析（纯趋势结构判断）"""
        if not inp.has_prices:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少历史行情，无法判断趋势结构与关键点"])

        pts: List[str] = []
        score = 0.0
        closes = inp.closes
        price = closes[-1]
        ma20, ma60, ma120 = _sma(closes, 20), _sma(closes, 60), _sma(closes, 120)

        # 1) 均线趋势结构（-40 ~ +40）
        if not any(math.isnan(x) for x in (ma20, ma60, ma120)):
            if price > ma20 > ma60 > ma120:
                score += 40
                pts.append("多头排列（价>MA20>MA60>MA120），最小阻力线向上")
            elif price < ma20 < ma60 < ma120:
                score -= 40
                pts.append("空头排列，最小阻力线向下，不宜做多")
            elif price > ma20 and price > ma60:
                score += 20
                pts.append("站上 MA20/MA60，趋势偏多但排列未完全确立")
            elif price < ma20 and price < ma60:
                score -= 25
                pts.append("跌破 MA20/MA60，趋势转弱")
            else:
                pts.append("均线纠缠，处于盘整区间")

        # 2) 关键点突破（±25）：逼近/突破 52 周高点
        if inp.pos_52w >= 0.97:
            score += 25
            pts.append("价格贴近/突破 52 周高点 —— 经典关键点，突破有效时跟进")
        elif inp.pos_52w >= 0.85 and inp.ret_20 > 3:
            score += 15
            pts.append(f"逼近 52 周高点（{inp.pos_52w:.0%}）且短期走强，关注突破确认")
        elif inp.pos_52w <= 0.1:
            score -= 15
            pts.append("处于 52 周低点区域，跌破关键支撑，勿接下落之刀")

        # 3) 动量确认（±15）
        if inp.ret_60 > 15:
            score += 15
        elif inp.ret_60 < -15:
            score -= 15

        # 4) 纪律提示（固定输出，利弗莫尔交易准则）
        if score >= 40:
            pts.append("纪律：试探性建仓 1/3，方向验证后再加码；跌破 MA20 减半，破 MA60 清仓")
        elif score <= -30:
            pts.append("纪律：亏损的头寸绝不摊平，时间是趋势交易者的敌人")

        score = _clamp(score, -100, 100)
        conf = 0.75  # 趋势判断纯行情驱动，数据可得性高
        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            conf, pts)
