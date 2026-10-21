#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大佬策略统一输入层 (v9.5)
Master Strategy Unified Input Layer
=====================================
所有大佬策略 Agent（索罗斯/费雪/达利欧/霍华德·马克斯/格林布拉特/利弗莫尔）
共享同一份市场快照输入 `MasterInput` 与统一输出 `MasterResult`。

设计原则（与项目既有模块一致）：
  1. 纯标准库、纯函数，零依赖
  2. 数据缺失诚实降级：无价格序列/无基本面时标记 confidence，不编造评分
  3. 行情派生特征（动量/波动/回撤/52周位置）统一在此计算，各大师只消费
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = ["MasterInput", "MasterResult", "score_to_signal"]


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def score_to_signal(score: float, confidence: float = 1.0) -> str:
    """评分 → 信号（-100~+100 统一映射）。

    confidence 过低（数据不足）时返回"数据不足"而非误导性信号。
    """
    if confidence < 0.3:
        return "数据不足"
    if score >= 50:
        return "强烈买入"
    if score >= 20:
        return "买入"
    if score > -20:
        return "中性"
    if score > -50:
        return "卖出"
    return "强烈卖出"


@dataclass
class MasterResult:
    """大佬策略统一输出"""
    master: str = ""          # 英文标识（soros/fisher/...）
    name_cn: str = ""         # 中文名
    style: str = ""           # 风格一句话
    score: float = 0.0        # 综合评分 -100 ~ +100
    signal: str = "中性"      # 强烈买入/买入/中性/卖出/强烈卖出/数据不足
    confidence: float = 0.0   # 数据完整度 0~1（决定评分可信程度）
    key_points: List[str] = field(default_factory=list)  # 关键依据


@dataclass
class MasterInput:
    """大佬策略统一输入快照。

    基本面字段（roe/revenue_growth/net_margin/pe/pb/dividend_yield）
    均可缺省（0 视为缺失）；closes 为日线收盘价序列（最新在末尾）。
    """
    code: str = ""
    name: str = ""
    price: float = 0.0
    # 估值
    pe: float = 0.0             # 市盈率（<=0 视为缺失）
    pb: float = 0.0             # 市净率（<=0 视为缺失）
    dividend_yield: float = 0.0  # 股息率 %
    # 基本面
    roe: float = 0.0            # 净资产收益率 %
    revenue_growth: float = 0.0  # 营收增速 %
    net_margin: float = 0.0     # 净利率 %
    # 行情序列（最新在末尾）
    closes: List[float] = field(default_factory=list)
    # 派生特征（from_market 自动填充）
    ret_20: float = 0.0        # 20 日收益率 %
    ret_60: float = 0.0        # 60 日收益率 %
    ret_250: float = 0.0       # 250 日收益率 %
    ann_vol: float = 0.0       # 年化波动率 %
    max_dd_250: float = 0.0    # 近一年最大回撤 %（负值）
    pos_52w: float = 0.5       # 52 周区间位置 0~1
    has_prices: bool = False   # 行情序列是否可用
    has_fundamentals: bool = False  # 基本面是否可用

    # ── 构造 ──────────────────────────────────────────────

    @classmethod
    def from_market(
        cls,
        code: str = "",
        name: str = "",
        price: float = 0.0,
        pe: float = 0.0,
        pb: float = 0.0,
        dividend_yield: float = 0.0,
        roe: float = 0.0,
        revenue_growth: float = 0.0,
        net_margin: float = 0.0,
        closes: Optional[List[float]] = None,
    ) -> "MasterInput":
        """从行情 + 基本面构建快照，自动计算派生特征。"""
        closes = [float(c) for c in (closes or []) if c and float(c) > 0]
        inp = cls(
            code=code, name=name, price=price, pe=pe, pb=pb,
            dividend_yield=dividend_yield, roe=roe,
            revenue_growth=revenue_growth, net_margin=net_margin,
            closes=closes,
        )
        inp.has_prices = len(closes) >= 20
        inp.has_fundamentals = any(v for v in (roe, revenue_growth, net_margin))
        if inp.has_prices:
            inp.ret_20 = cls._ret(closes, 20)
            inp.ret_60 = cls._ret(closes, 60)
            inp.ret_250 = cls._ret(closes, 250)
            inp.ann_vol = cls._annualized_vol(closes)
            inp.max_dd_250 = cls._max_drawdown(closes[-250:])
            inp.pos_52w = cls._range_position(closes[-250:])
        if price <= 0 and closes:
            inp.price = closes[-1]
        return inp

    # ── 派生特征计算（纯函数）──────────────────────────────

    @staticmethod
    def _ret(closes: List[float], days: int) -> float:
        """区间收益率 %；数据不足返回 0"""
        if len(closes) <= days or closes[-days - 1] <= 0:
            return 0.0
        return (closes[-1] / closes[-days - 1] - 1) * 100

    @staticmethod
    def _annualized_vol(closes: List[float], window: int = 60) -> float:
        """年化波动率 %（最近 window 日对数收益标准差 × √250）"""
        seg = closes[-window - 1:]
        if len(seg) < 11:
            return 0.0
        rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg))
                if seg[i - 1] > 0]
        if len(rets) < 10:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(max(var, 0.0)) * math.sqrt(250) * 100

    @staticmethod
    def _max_drawdown(closes: List[float]) -> float:
        """最大回撤 %（负值）"""
        if not closes:
            return 0.0
        peak, mdd = closes[0], 0.0
        for c in closes:
            if c > peak:
                peak = c
            if peak > 0:
                dd = (c / peak - 1) * 100
                if dd < mdd:
                    mdd = dd
        return mdd

    @staticmethod
    def _range_position(closes: List[float]) -> float:
        """当前价在区间最高/最低之间的位置 0~1"""
        if not closes:
            return 0.5
        hi, lo = max(closes), min(closes)
        if hi <= lo:
            return 0.5
        return _clamp((closes[-1] - lo) / (hi - lo), 0.0, 1.0)

    # ── 便利读取 ──────────────────────────────────────────

    def momentum_blend(self) -> float:
        """短/中/长期动量加权混合（%），趋势延续性度量"""
        return self.ret_20 * 0.5 + self.ret_60 * 0.3 + self.ret_250 * 0.2

    def data_completeness(self) -> float:
        """数据完整度 0~1：行情 0.6 + 估值 0.2 + 基本面 0.2"""
        c = 0.0
        if self.has_prices:
            c += 0.6
        if self.pe > 0 or self.pb > 0:
            c += 0.2
        if self.has_fundamentals:
            c += 0.2
        return c
