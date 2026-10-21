"""
统一量价分析模块 — VolumePriceAnalyzer
=====================================

继承并增强原 VolumeAnalyzer，将以下 4 本量价经典的核心逻辑合并为一个统一模块：

  1. 《量价绝杀（高手提升版）》      → 起涨放量 / 洗盘缩量 / 突破放量 / 高位出货模型
  2. 《量价细节·全新的量价实战技法》  → 地量见底 / 缩量微调 / 量比阈值
  3. 《量价相生法则》                → 量价配合(相生) / 量价背离(相克) 的根本律
  4. 《量价秘密·趋势·板块·黑马股》    → 趋势量价配合 / 黑马股高量突破 / 板块量能验证

设计原则（兼容优先）：
  - 完全复用父类 VolumeAnalyzer 的全部输出字段
    (volume_price_relation / volume_ratio / recent_trend / extreme_points / markers)，
    下游 run_analysis.py、report 模板、技能卡生成器无需任何改动。
  - 新增 details['vp_rules']（各子规则信号+权重+溯源书本）、details['book_sources']，
    用于结论 HTML 透明展示"每条规则来自哪本书"。
  - 最终 signal 由 7 条子规则加权合成（归一化到 [-1,1]），置信度由规则间一致性决定。

仅需在 run_analysis.py 中将 `self.volume = VolumeAnalyzer()` 改为
`self.volume = VolumePriceAnalyzer()` 即可完成注入，无命名冲突、无依赖破坏。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from .volume_analyzer import VolumeAnalyzer


class VolumePriceAnalyzer(VolumeAnalyzer):
    """统一量价分析器：合并 4 本量价经典的核心规则。"""

    # 子规则 → 溯源书本
    BOOK_MAP = {
        'vp_convergence': '量价相生法则',
        'divergence':     '量价相生法则',
        'bottoming':      '量价细节',
        'breakout':       '量价绝杀',
        'shakeout':       '量价绝杀 / 量价细节',
        'distribution':   '量价绝杀',
        'darkhorse':      '量价秘密',
    }

    # 子规则权重（合成统一信号时归一化）
    RULE_WEIGHTS = {
        'vp_convergence': 0.20,   # 量价配合（相生）
        'divergence':     0.18,   # 量价背离（相克）
        'bottoming':      0.15,   # 地量见底
        'breakout':       0.15,   # 突破放量
        'shakeout':       0.12,   # 洗盘缩量
        'distribution':   0.12,   # 高位出货
        'darkhorse':      0.08,   # 黑马高量突破
    }

    def analyze(self, df: pd.DataFrame) -> dict:
        """主分析入口：复用父类基础字段 + 叠加 4 本书合并的 7 条量价子规则。"""
        base = super().analyze(df)  # 保留 volume_price_relation/volume_ratio/... 全部字段

        if df is None or df.empty or len(df) < 20:
            # 数据不足时直接返回父类结果（保持兼容）
            return base

        df = df.copy().sort_values('date').reset_index(drop=True)
        n = len(df)

        rules = self._merged_rules(df, n)
        signal, confidence = self._synthesize_unified(rules)

        details = dict(base['details'])
        details.update({
            'vp_rules': rules,                 # 各子规则明细
            'book_sources': self.BOOK_MAP,     # 规则→书本溯源
            'unified_sub_count': len(rules),
            'unified_signal_formula': ' + '.join(
                f"{k}({v['signal']:+.2f}×{int(self.RULE_WEIGHTS[k]*100)}%)"
                for k, v in rules.items()
            ),
        })

        return {
            'signal': round(float(signal), 4),
            'confidence': round(float(confidence), 4),
            'details': details,
        }

    # ====================================================================
    #  合并子规则计算
    # ====================================================================
    def _merged_rules(self, df: pd.DataFrame, n: int) -> Dict[str, dict]:
        close = df['close'].astype(float)
        vol = df['volume'].astype(float)
        ret = close.pct_change()

        vol_ma20 = vol.rolling(20, min_periods=5).mean()
        vol_ratio_last = float(vol.iloc[-1] / vol_ma20.iloc[-1]) if vol_ma20.iloc[-1] > 0 else 1.0
        ma20_close = close.rolling(20, min_periods=5).mean().iloc[-1]

        rules: Dict[str, dict] = {}

        # ---- 1. 量价配合 vp_convergence（量价相生法则）----
        look = min(10, n)
        recent = df.tail(look)
        p0, p1 = recent['close'].iloc[0], recent['close'].iloc[-1]
        mid = max(1, len(recent) // 2)
        vf = recent['volume'].iloc[:mid].mean()
        vs = recent['volume'].iloc[mid:].mean()
        pchg = (p1 - p0) / p0 if p0 > 0 else 0.0
        vup = vs > vf * 1.05
        vdn = vs < vf * 0.95
        if pchg > 0.005 and vup:
            s_conv = 0.6
        elif pchg > 0.005 and vdn:
            s_conv = -0.6
        elif pchg < -0.005 and vdn:
            s_conv = 0.4
        elif pchg < -0.005 and vup:
            s_conv = -0.6
        else:
            s_conv = 0.0
        rules['vp_convergence'] = self._rule('vp_convergence', s_conv,
                                             f"近{look}日价{'涨' if pchg>0 else '跌'}"
                                             f"量{'增' if vup else ('缩' if vdn else '平')}")

        # ---- 2. 量价背离 divergence（量价相生法则）----
        s_div = 0.0
        note_div = "无量价背离"
        if n >= 20:
            hh = close.iloc[-1] > close.iloc[-20:-5].max()   # 创新高
            ll = close.iloc[-1] < close.iloc[-20:-5].min()   # 创新低
            v_recent = vol.iloc[-5:].mean()
            v_prev = vol.iloc[-20:-5].mean()
            if hh and v_recent < v_prev * 0.95:
                s_div = -0.8; note_div = "价创新高而量能萎缩→顶背离"
            elif ll and v_recent < v_prev * 0.95:
                s_div = 0.7; note_div = "价创新低而量能萎缩→底背离"
        rules['divergence'] = self._rule('divergence', s_div, note_div)

        # ---- 3. 地量见底 bottoming（量价细节）----
        s_bot = 0.0
        note_bot = "非地量"
        if vol_ratio_last < 0.5 and close.iloc[-1] < ma20_close:
            s_bot = 0.7; note_bot = f"量比{vol_ratio_last:.2f}<0.5 且价在20均线下→地量见底"
        elif vol_ratio_last < 0.4:
            s_bot = 0.5; note_bot = f"量比{vol_ratio_last:.2f}<0.4→极度缩量"
        rules['bottoming'] = self._rule('bottoming', s_bot, note_bot)

        # ---- 4. 突破放量 breakout（量价绝杀）----
        s_brk = 0.0
        note_brk = "无突破"
        if n >= 20:
            is_new_high = close.iloc[-1] > close.iloc[-20:-1].max()
            if is_new_high and vol_ratio_last > 1.5:
                s_brk = 0.8; note_brk = f"放量突破20日新高(量比{vol_ratio_last:.2f})"
        rules['breakout'] = self._rule('breakout', s_brk, note_brk)

        # ---- 5. 洗盘缩量 shakeout（量价绝杀/量价细节）----
        s_shk = 0.0
        note_shk = "非洗盘"
        if n >= 10 and close.iloc[-1] < close.iloc[-5] and vol.iloc[-5:].mean() < vol.iloc[-10:-5].mean():
            s_shk = 0.5; note_shk = "回调中量能缩减→健康洗盘"
        rules['shakeout'] = self._rule('shakeout', s_shk, note_shk)

        # ---- 6. 高位出货 distribution（量价绝杀）----
        s_dis = 0.0
        note_dis = "非出货"
        if n >= 20:
            near_high = close.iloc[-1] > close.iloc[-20:].max() * 0.98
            stall = close.iloc[-1] <= close.iloc[-3]
            if near_high and vol_ratio_last > 2.5 and stall:
                s_dis = -0.8; note_dis = f"高位放量滞涨(量比{vol_ratio_last:.2f})→出货"
        rules['distribution'] = self._rule('distribution', s_dis, note_dis)

        # ---- 7. 黑马高量突破 darkhorse（量价秘密）----
        s_dh = 0.0
        note_dh = "非黑马形态"
        if vol_ratio_last > 1.8 and (ret.iloc[-1] > 0.03 or (close.iloc[-1] / close.iloc[-5] - 1) > 0.08):
            s_dh = 0.7; note_dh = f"持续高量(量比{vol_ratio_last:.2f})配合强涨→黑马突破"
        rules['darkhorse'] = self._rule('darkhorse', s_dh, note_dh)

        return rules

    # ====================================================================
    #  合成
    # ====================================================================
    def _rule(self, key: str, signal: float, note: str) -> dict:
        return {
            'signal': round(float(signal), 3),
            'weight': self.RULE_WEIGHTS.get(key, 0.0),
            'source': self.BOOK_MAP.get(key, ''),
            'note': note,
        }

    def _synthesize_unified(self, rules: Dict[str, dict]):
        """7 条子规则加权合成统一信号；置信度由规则间一致性决定。"""
        total_w = sum(r['weight'] for r in rules.values())
        if total_w <= 0:
            return 0.0, 0.0
        signal = sum(r['weight'] * r['signal'] for r in rules.values()) / total_w
        signal = max(-1.0, min(1.0, signal))

        # 置信度：规则信号方向越一致 → 置信越高
        sigs = np.array([r['signal'] for r in rules.values()], dtype=float)
        std = float(np.std(sigs)) if len(sigs) > 1 else 0.0
        confidence = max(0.3, min(0.9, 0.55 + 0.35 * (1.0 - std)))
        return round(float(signal), 4), round(float(confidence), 4)
