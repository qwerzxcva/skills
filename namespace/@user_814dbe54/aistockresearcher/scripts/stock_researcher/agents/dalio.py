#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
达利欧分析 Agent (v9.5)
Ray Dalio Analysis Agent — 经济机器视角（增长×风险四象限 + 债务周期风险）
分析：宏观象限定位 / 风险预算视角 / 分散化建议
"""

from typing import List

from .master_input import MasterInput, MasterResult, score_to_signal, _clamp

__all__ = ["DalioAnalyzer"]


class DalioAnalyzer:
    """
    达利欧"经济机器"视角分析

    核心原则：
    1. 以增长（长期动量代理）× 风险（波动率代理）划分四象限
    2. 债务周期风险：深度回撤代表去杠杆压力，需降低风险敞口
    3. 圣杯：分散化而非单点押注 —— 单标的评分保守，强调组合视角
    """

    MASTER = "dalio"
    NAME_CN = "达利欧"
    STYLE = "宏观机器视角：增长×风险四象限定位，强调分散与风险预算"

    def analyze(self, inp: MasterInput) -> MasterResult:
        """执行达利欧风格分析（宏观视角对单标的评分保守，上限 ±60）"""
        if not inp.has_prices:
            return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                                0.0, "数据不足", 0.0,
                                ["缺少历史行情，无法推断增长/风险象限"])

        pts: List[str] = []
        growth = inp.ret_250  # 增长代理：近一年收益
        risk = inp.ann_vol    # 风险代理：年化波动

        # 1) 四象限定位
        if growth > 5 and risk <= 35:
            quad, adj = "金发女孩（增长上行+风险可控）", 35
        elif growth > 5 and risk > 35:
            quad, adj = "过热/高波动（增长伴随高风险）", 10
        elif growth <= -10 and risk > 35:
            quad, adj = "衰退去杠杆（增长下行+风险高企）", -40
        elif growth <= -10:
            quad, adj = "通缩压力（增长低迷，等待政策对冲）", -25
        else:
            quad, adj = "转折观察区（方向未定）", 0
        pts.append(f"象限定位：{quad}（年增长 {growth:+.1f}% / 波动 {risk:.0f}%）")

        # 2) 债务周期/去杠杆风险：近一年最大回撤
        if inp.max_dd_250 < -40:
            adj -= 20
            pts.append(f"近一年最大回撤 {inp.max_dd_250:.0f}%，存在去杠杆式下跌痕迹")
        elif inp.max_dd_250 < -25:
            adj -= 10
            pts.append(f"近一年最大回撤 {inp.max_dd_250:.0f}%，风险预算应收紧")

        # 3) 波动率目标仓位思想：高波动 → 建议降低单标的权重
        if risk > 50:
            adj -= 10
            pts.append("波动率超出常规预算，按波动率目标法应降低仓位权重")
        elif 0 < risk <= 20 and growth > 0:
            adj += 10
            pts.append("低波动上行，符合风险预算内的优质敞口")

        # 4) 圣杯提示（固定原则输出）
        pts.append("达利欧原则：单标的不构成组合，分散 10~15 个低相关资产才能显著降低风险")

        score = _clamp(adj, -60, 60)
        conf = 0.55 if inp.pe <= 0 else 0.65  # 宏观代理指标置信有限
        return MasterResult(self.MASTER, self.NAME_CN, self.STYLE,
                            round(score, 1), score_to_signal(score, conf),
                            round(conf, 2), pts)
