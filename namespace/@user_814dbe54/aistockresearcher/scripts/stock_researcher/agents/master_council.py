#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大佬圆桌共识引擎 (v9.5)
Master Council — 六位投资大佬策略参考面板
=====================================
对同一份市场快照（MasterInput）运行六位大佬策略：
  利弗莫尔（趋势）/ 索罗斯（反身性）/ 格林布拉特（神奇公式）/
  费雪（成长）/ 马克斯（周期风险）/ 达利欧（宏观象限）

输出：
  - 每位大佬的评分/信号/关键依据
  - 置信度加权共识评分与信号
  - 多空一致度（agreement）与最乐观/最谨慎代表
  - format() 中文圆桌报告

纯标准库，零依赖；所有大佬评分仅作策略参考，不构成投资建议。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .master_input import MasterInput, MasterResult, score_to_signal, _clamp
from .soros import SorosAnalyzer
from .fisher import FisherAnalyzer
from .dalio import DalioAnalyzer
from .marks import MarksAnalyzer
from .greenblatt import GreenblattAnalyzer
from .livermore import LivermoreAnalyzer

__all__ = ["MasterCouncil", "CouncilReport", "quick_master_council"]

# 圆桌默认权重（和为 1）：趋势/价值/成长/宏观均衡配置
DEFAULT_WEIGHTS: Dict[str, float] = {
    "livermore": 0.18,
    "greenblatt": 0.18,
    "soros": 0.17,
    "fisher": 0.16,
    "marks": 0.16,
    "dalio": 0.15,
}


@dataclass
class CouncilReport:
    """大佬圆桌共识报告"""
    code: str = ""
    name: str = ""
    price: float = 0.0
    results: List[MasterResult] = field(default_factory=list)
    weights: Dict[str, float] = field(default_factory=dict)
    consensus_score: float = 0.0     # 置信加权共识 -100 ~ +100
    consensus_signal: str = "中性"
    agreement: float = 0.0           # 与共识同向的大佬比例 0~1
    bulls: List[str] = field(default_factory=list)   # 看多的大佬
    bears: List[str] = field(default_factory=list)   # 看空的大佬
    most_bullish: str = ""           # 最乐观大佬
    most_bearish: str = ""           # 最谨慎大佬
    valid_count: int = 0             # 有效评分大佬数


class MasterCouncil:
    """大佬圆桌：多策略参考面板 + 加权共识"""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.analyzers = {
            "livermore": LivermoreAnalyzer(),
            "greenblatt": GreenblattAnalyzer(),
            "soros": SorosAnalyzer(),
            "fisher": FisherAnalyzer(),
            "marks": MarksAnalyzer(),
            "dalio": DalioAnalyzer(),
        }
        self.weights = dict(weights or DEFAULT_WEIGHTS)

    def analyze(self, inp: MasterInput) -> CouncilReport:
        """运行全部大佬策略并合成共识"""
        rep = CouncilReport(code=inp.code, name=inp.name, price=inp.price,
                            weights=dict(self.weights))
        for key, az in self.analyzers.items():
            try:
                rep.results.append(az.analyze(inp))
            except Exception as e:  # 单个大佬失败不影响圆桌
                rep.results.append(MasterResult(
                    key, getattr(az, "NAME_CN", key), "",
                    0.0, "数据不足", 0.0, [f"分析异常：{e}"]))

        # 有效评分（排除数据不足）
        valid = [r for r in rep.results if r.signal != "数据不足"]
        rep.valid_count = len(valid)
        if not valid:
            rep.consensus_signal = "数据不足"
            return rep

        # 置信度 × 权重加权共识
        wsum, ssum = 0.0, 0.0
        for r in valid:
            w = self.weights.get(r.master, 0.1) * max(r.confidence, 0.05)
            ssum += r.score * w
            wsum += w
        rep.consensus_score = round(_clamp(ssum / wsum if wsum > 0 else 0.0,
                                           -100, 100), 1)
        rep.consensus_signal = score_to_signal(rep.consensus_score, 1.0)

        # 多空分组与一致度
        for r in valid:
            if r.score >= 20:
                rep.bulls.append(r.name_cn)
            elif r.score <= -20:
                rep.bears.append(r.name_cn)
        same_sign = sum(1 for r in valid
                        if (r.score >= 0) == (rep.consensus_score >= 0))
        rep.agreement = round(same_sign / len(valid), 2)

        # 最乐观/最谨慎代表
        best = max(valid, key=lambda r: r.score)
        worst = min(valid, key=lambda r: r.score)
        rep.most_bullish = f"{best.name_cn}({best.score:+.0f})"
        rep.most_bearish = f"{worst.name_cn}({worst.score:+.0f})"
        return rep

    # ── 中文报告 ──────────────────────────────────────────

    @staticmethod
    def format(rep: CouncilReport) -> str:
        """圆桌报告 → 中文文本"""
        title = rep.name or rep.code or "标的"
        lines = [
            "=" * 62,
            f"  🏛️ 大佬圆桌 · {title}({rep.code}) 策略参考面板",
            "=" * 62,
        ]
        if rep.price > 0:
            lines.append(f"  现价：{rep.price:.2f}")
        lines.append("")
        for r in sorted(rep.results, key=lambda x: -x.score):
            w = rep.weights.get(r.master, 0)
            lines.append(f"  【{r.name_cn}】权重{w:.0%} | 评分 {r.score:+.0f} | "
                         f"信号：{r.signal} | 置信 {r.confidence:.0%}")
            for kp in r.key_points[:3]:
                lines.append(f"      · {kp}")
        lines.append("")
        lines.append("  " + "-" * 58)
        if rep.valid_count == 0:
            lines.append("  ❌ 所有大佬均数据不足，无法形成共识。")
        else:
            lines.append(f"  🎯 圆桌共识：{rep.consensus_signal}"
                         f"（加权评分 {rep.consensus_score:+.1f}）")
            lines.append(f"  👥 一致度 {rep.agreement:.0%}"
                         f"（{rep.valid_count}/6 位有效）  "
                         f"看多：{'、'.join(rep.bulls) or '无'}  "
                         f"看空：{'、'.join(rep.bears) or '无'}")
            lines.append(f"  最乐观：{rep.most_bullish}  最谨慎：{rep.most_bearish}")
        lines.append("-" * 62)
        lines.append("  ⚠️ 大佬策略为规则化参考视角，不构成投资建议")
        lines.append("=" * 62)
        return "\n".join(lines)


def quick_master_council(inp: MasterInput) -> CouncilReport:
    """便捷入口：快照 → 圆桌共识报告"""
    return MasterCouncil().analyze(inp)
