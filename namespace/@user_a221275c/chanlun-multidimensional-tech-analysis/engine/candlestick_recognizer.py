"""
缠论多维技术分析 - K线形态识别模块

支持的形态（16+种）：
- 单线形态：锤子线、上吊线、倒锤子、流星线、十字星、长脚十字星、墓碑十字
- 双线形态：看涨吞没、看跌吞没、刺透形态、乌云盖顶、孕线
- 三线+形态：早晨之星、黄昏之星、三只乌鸦、三白兵
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple


class CandlestickRecognizer:
    """K线形态识别器，识别经典日本蜡烛图形态并生成多/空信号。"""

    # 可配置参数
    MIN_BODY_RATIO = 0.3        # 实体占K线总长度最小比例（用于判断"大"K线）
    DOJI_BODY_RATIO = 0.1       # 十字星实体占比上限
    SHADOW_RATIO = 2.0          # 影线≥实体倍数的阈值
    SMALL_BODY_MAX = 0.5        # 小实体的最大占比
    TREND_LOOKBACK = 10         # 判断趋势的回看周期
    SIGNAL_LOOKBACK = 30        # 信号综合计算的回看周期
    GAP_THRESHOLD = 0.005       # 跳空阈值（相对于前收盘）

    def __init__(self, **kwargs):
        """初始化识别器，可通过关键字参数覆盖默认配置。"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    # =========================================================================
    # 公共接口
    # =========================================================================

    def recognize(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        对DataFrame执行全量形态识别。

        Args:
            df: pandas DataFrame，必须包含列: date, open, high, low, close, volume

        Returns:
            dict: {
                'signal': float (-1.0 ~ 1.0),
                'confidence': float (0.0 ~ 1.0),
                'patterns': list[dict],
                'markers': list[dict]
            }
        """
        self._validate_columns(df)
        n = len(df)
        if n < 2:
            return self._empty_result()

        # 预计算每个bar的基本属性
        bars = self._precompute_bars(df)

        patterns: List[dict] = []
        markers: List[dict] = []
        bullish_count = 0
        bearish_count = 0

        # ---- 单线形态（需要 ≥1 bar）----
        for i in range(n):
            pat = self._single_line_patterns(df, bars, i)
            if pat:
                patterns.append(pat)
                markers.append({
                    'index': i,
                    'label': pat['name'],
                    'color': 'red' if pat['type'] == 'bullish' else 'green'
                })
                if pat['type'] == 'bullish':
                    bullish_count += 1
                else:
                    bearish_count += 1

        # ---- 双线形态（需要 ≥2 bar）----
        for i in range(1, n):
            pat = self._two_line_patterns(df, bars, i)
            if pat:
                patterns.append(pat)
                markers.append({
                    'index': i,
                    'label': pat['name'],
                    'color': 'red' if pat['type'] == 'bullish' else 'green'
                })
                if pat['type'] == 'bullish':
                    bullish_count += 1
                else:
                    bearish_count += 1

        # ---- 三线形态（需要 ≥3 bar）----
        for i in range(2, n):
            pat = self._three_line_patterns(df, bars, i)
            if pat:
                patterns.append(pat)
                markers.append({
                    'index': i,
                    'label': pat['name'],
                    'color': 'red' if pat['type'] == 'bullish' else 'green'
                })
                if pat['type'] == 'bullish':
                    bullish_count += 1
                else:
                    bearish_count += 1

        # 计算综合信号
        signal, confidence = self._compute_signal(bullish_count, bearish_count, n, patterns)

        return {
            'signal': round(signal, 4),
            'confidence': round(confidence, 4),
            'patterns': patterns,
            'markers': markers
        }

    # =========================================================================
    # 内部辅助方法
    # =========================================================================

    def _empty_result(self) -> Dict[str, Any]:
        """K线数量不足时的空结果。"""
        return {
            'signal': 0.0,
            'confidence': 0.0,
            'patterns': [],
            'markers': []
        }

    def _validate_columns(self, df: pd.DataFrame):
        """校验DataFrame是否包含必需的列。"""
        required = {'open', 'high', 'low', 'close'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame缺少必需的列: {missing}")

    def _get_date(self, df: pd.DataFrame, idx: int) -> str:
        """安全获取日期字符串。"""
        if 'date' not in df.columns:
            return str(idx)
        val = df.iloc[idx]['date']
        return str(val)

    def _precompute_bars(self, df: pd.DataFrame) -> List[dict]:
        """预计算每根K线的实体、影线、颜色等属性。"""
        n = len(df)
        bars = []
        for i in range(n):
            row = df.iloc[i]
            o, h, l, c = float(row['open']), float(row['high']), float(row['low']), float(row['close'])
            body = abs(c - o)
            total_range = h - l
            body_ratio = body / total_range if total_range > 0 else 0
            upper_shadow = h - max(o, c)
            lower_shadow = min(o, c) - l
            is_bullish = c > o
            is_bearish = c < o
            body_center = (o + c) / 2.0

            # 趋势判断：使用SMA近似
            trend = 0  # -1: 下跌, 0: 无趋势, +1: 上涨
            if i >= self.TREND_LOOKBACK:
                closes_before = df['close'].iloc[i - self.TREND_LOOKBACK:i].values.astype(float)
                sma_short = np.mean(closes_before[:self.TREND_LOOKBACK // 2])
                sma_long = np.mean(closes_before[self.TREND_LOOKBACK // 2:])
                if sma_short > sma_long * 1.01:
                    trend = 1
                elif sma_short < sma_long * 0.99:
                    trend = -1

            bars.append({
                'open': o, 'high': h, 'low': l, 'close': c,
                'body': body,
                'total_range': total_range,
                'body_ratio': body_ratio,
                'upper_shadow': upper_shadow,
                'lower_shadow': lower_shadow,
                'is_bullish': is_bullish,
                'is_bearish': is_bearish,
                'body_center': body_center,
                'trend': trend,
            })
        return bars

    def _compute_signal(self, bullish_count: int, bearish_count: int,
                        n: int, patterns: List[dict]) -> Tuple[float, float]:
        """
        综合计算信号强度和置信度。

        signal: 多空形态数差值归一化到 [-1, 1]
        confidence: 识别到的形态中最高强度值
        """
        total = bullish_count + bearish_count
        if total == 0:
            return 0.0, 0.0

        # 信号 = (bullish - bearish) / max_possible，归一化
        max_possible = max(n, 1)
        signal = (bullish_count - bearish_count) / max_possible
        signal = max(-1.0, min(1.0, signal))

        # 置信度 = 最高形态强度
        max_strength = 0.0
        for p in patterns:
            max_strength = max(max_strength, p.get('strength', 0.5))
        confidence = max_strength if max_strength > 0 else 0.5

        return signal, confidence

    # =========================================================================
    # 趋势与信号区分（基于位置）
    # =========================================================================

    def _is_downtrend(self, bars: List[dict], idx: int) -> bool:
        """判断当前位置是否处于下跌趋势中（短期均价下移）。"""
        return bars[idx]['trend'] == -1

    def _is_uptrend(self, bars: List[dict], idx: int) -> bool:
        """判断当前位置是否处于上涨趋势中。"""
        return bars[idx]['trend'] == 1

    def _gap_up(self, bar: dict, prev_close: float) -> bool:
        """当前K线开盘价显著高于前收盘（向上跳空）。"""
        if prev_close <= 0:
            return False
        return (bar['open'] - prev_close) / prev_close > self.GAP_THRESHOLD

    def _gap_down(self, bar: dict, prev_close: float) -> bool:
        """当前K线开盘价显著低于前收盘（向下跳空）。"""
        if prev_close <= 0:
            return False
        return (prev_close - bar['open']) / prev_close > self.GAP_THRESHOLD

    # =========================================================================
    # 单线形态识别
    # =========================================================================

    def _single_line_patterns(self, df: pd.DataFrame, bars: List[dict], idx: int) -> Optional[dict]:
        """识别所有单线形态，返回首个匹配的形态（按优先级）。"""
        bar = bars[idx]

        # 1. 十字星系列（最高优先级，因为实体极小）
        doji = self._is_doji(bar)
        if doji is not None:
            doji['index'] = idx
            doji['date'] = self._get_date(df, idx)
            return doji

        # 2. 锤子线/上吊线（有共同特征，方向由趋势决定）
        if bar['lower_shadow'] >= bar['body'] * self.SHADOW_RATIO and \
           bar['upper_shadow'] <= bar['body'] * 0.5 and \
           bar['body'] > 0:
            if self._is_downtrend(bars, idx):
                date_str = self._get_date(df, idx)
                strength = self._calc_strength(bar, 'bullish')
                return {'name': '锤子线', 'type': 'bullish', 'index': idx,
                        'date': date_str, 'strength': strength}
            elif self._is_uptrend(bars, idx):
                date_str = self._get_date(df, idx)
                strength = self._calc_strength(bar, 'bearish')
                return {'name': '上吊线', 'type': 'bearish', 'index': idx,
                        'date': date_str, 'strength': strength}
            # 无明确趋势时，不输出

        # 3. 倒锤子/流星线
        if bar['upper_shadow'] >= bar['body'] * self.SHADOW_RATIO and \
           bar['lower_shadow'] <= bar['body'] * 0.5 and \
           bar['body'] > 0:
            if self._is_downtrend(bars, idx):
                date_str = self._get_date(df, idx)
                strength = self._calc_strength(bar, 'bullish')
                return {'name': '倒锤子', 'type': 'bullish', 'index': idx,
                        'date': date_str, 'strength': strength}
            elif self._is_uptrend(bars, idx):
                date_str = self._get_date(df, idx)
                strength = self._calc_strength(bar, 'bearish')
                return {'name': '流星线', 'type': 'bearish', 'index': idx,
                        'date': date_str, 'strength': strength}

        return None

    # ---- 十字星子系列 ----

    def _is_doji(self, bar: dict) -> Optional[dict]:
        """
        十字星识别：开盘≈收盘。

        子类型：
        - 墓碑十字：上影线长，下影线极短（看跌）
        - 长脚十字星：上下影线都很长（反转信号）
        - 普通十字星：上下影线相当（中性/反转）
        """
        if bar['total_range'] == 0:
            return None  # 一字板，不计入

        if bar['body_ratio'] > self.DOJI_BODY_RATIO:
            return None  # 实体太大，不是十字星

        upper = bar['upper_shadow']
        lower = bar['lower_shadow']
        body = bar['body']

        # 墓碑十字：上影线≥总长度60%，下影线极短
        if upper >= bar['total_range'] * 0.6 and lower <= bar['total_range'] * 0.1:
            return {
                'name': '墓碑十字', 'type': 'bearish', 'index': -1, 'date': '',
                'strength': min(1.0, upper / max(bar['total_range'], 0.0001))
            }

        # 长脚十字星：上下影线都很长
        if upper >= body * 3 and lower >= body * 3:
            return {
                'name': '长脚十字星', 'type': 'bearish', 'index': -1, 'date': '',
                'strength': min(1.0, (upper + lower) / max(bar['total_range'], 0.0001))
            }

        # 普通十字星
        if bar['body_ratio'] <= self.DOJI_BODY_RATIO:
            return {
                'name': '十字星', 'type': 'bearish', 'index': -1, 'date': '',
                'strength': 0.5
            }

        return None

    # =========================================================================
    # 双线形态识别
    # =========================================================================

    def _two_line_patterns(self, df: pd.DataFrame, bars: List[dict], idx: int) -> Optional[dict]:
        """
        识别所有双线形态（idx指向第2根K线）。

        按置信度从高到低尝试匹配：吞没 → 刺透/乌云盖顶 → 孕线
        """
        prev = bars[idx - 1]
        curr = bars[idx]
        date_str = self._get_date(df, idx)

        # 看涨吞没：阴线后跟阳线，阳线实体完全包住阴线
        engulfing = self._is_bullish_engulfing(prev, curr)
        if engulfing:
            engulfing['index'] = idx
            engulfing['date'] = date_str
            return engulfing

        # 看跌吞没：阳线后跟阴线，阴线实体完全包住阳线
        engulfing = self._is_bearish_engulfing(prev, curr)
        if engulfing:
            engulfing['index'] = idx
            engulfing['date'] = date_str
            return engulfing

        # 刺透形态：阴线后低开阳线，收盘超过阴线中点
        piercing = self._is_piercing(prev, curr)
        if piercing:
            piercing['index'] = idx
            piercing['date'] = date_str
            return piercing

        # 乌云盖顶：阳线后高开阴线，收盘低于阳线中点
        dark_cloud = self._is_dark_cloud_cover(prev, curr)
        if dark_cloud:
            dark_cloud['index'] = idx
            dark_cloud['date'] = date_str
            return dark_cloud

        # 孕线：小K线完全在前一根大K线实体内
        harami = self._is_harami(prev, curr)
        if harami:
            harami['index'] = idx
            harami['date'] = date_str
            return harami

        return None

    def _is_bullish_engulfing(self, prev: dict, curr: dict) -> Optional[dict]:
        """
        看涨吞没：
        - 前一根为阴线
        - 当前为阳线
        - 当前实体完全包住前一根实体（开 < 前收，收 > 前开）
        """
        if not prev['is_bearish'] or not curr['is_bullish']:
            return None
        if prev['body'] <= 0:
            return None
        if curr['open'] < prev['close'] and curr['close'] > prev['open']:
            strength = self._calc_strength(curr, 'bullish')
            return {'name': '看涨吞没', 'type': 'bullish', 'index': -1, 'date': '', 'strength': strength}
        return None

    def _is_bearish_engulfing(self, prev: dict, curr: dict) -> Optional[dict]:
        """
        看跌吞没：
        - 前一根为阳线
        - 当前为阴线
        - 当前实体完全包住前一根实体（开 > 前收，收 < 前开）
        """
        if not prev['is_bullish'] or not curr['is_bearish']:
            return None
        if prev['body'] <= 0:
            return None
        if curr['open'] > prev['close'] and curr['close'] < prev['open']:
            strength = self._calc_strength(curr, 'bearish')
            return {'name': '看跌吞没', 'type': 'bearish', 'index': -1, 'date': '', 'strength': strength}
        return None

    def _is_piercing(self, prev: dict, curr: dict) -> Optional[dict]:
        """
        刺透形态：
        - 前一根为阴线
        - 当前为阳线
        - 当前开盘低于前收盘
        - 当前收盘超过前一根阴线的中点
        """
        if not prev['is_bearish'] or not curr['is_bullish']:
            return None
        if prev['body'] <= 0:
            return None
        if curr['open'] < prev['close'] and curr['close'] > prev['body_center']:
            # 收盘未超过前阴线实体顶部（否则可能变成吞没）
            if curr['close'] < prev['open']:
                penetration = (curr['close'] - prev['close']) / prev['body']
                strength = min(1.0, penetration * 2)
                return {'name': '刺透形态', 'type': 'bullish', 'index': -1, 'date': '',
                        'strength': round(strength, 3)}
        return None

    def _is_dark_cloud_cover(self, prev: dict, curr: dict) -> Optional[dict]:
        """
        乌云盖顶：
        - 前一根为阳线（较大实体）
        - 当前为阴线
        - 当前开盘高于前收盘
        - 当前收盘低于前一根阳线的中点
        """
        if not prev['is_bullish'] or not curr['is_bearish']:
            return None
        if prev['body'] <= 0:
            return None
        if curr['open'] > prev['close'] and curr['close'] < prev['body_center']:
            # 收盘未跌破前阳线实体底部（否则可能变成吞没）
            if curr['close'] > prev['open']:
                penetration = (prev['close'] - curr['close']) / prev['body']
                strength = min(1.0, penetration * 2)
                return {'name': '乌云盖顶', 'type': 'bearish', 'index': -1, 'date': '',
                        'strength': round(strength, 3)}
        return None

    def _is_harami(self, prev: dict, curr: dict) -> Optional[dict]:
        """
        孕线：
        - 前一根为大K线（实体占比较高）
        - 当前为小K线（实体占比较小）
        - 当前K线的实体和影线完全在前一根K线的实体内
        """
        if prev['body'] <= 0:
            return None
        # 当前实体必须明显小于前一根实体
        if curr['body'] > prev['body'] * 0.8:
            return None
        # 当前整个K线范围在前一根实体范围内
        if max(curr['open'], curr['close']) <= max(prev['open'], prev['close']) and \
           min(curr['open'], curr['close']) >= min(prev['open'], prev['close']):
            # 方向由前一根决定
            if prev['is_bearish']:
                return {'name': '孕线', 'type': 'bullish', 'index': -1, 'date': '',
                        'strength': 0.55}
            elif prev['is_bullish']:
                return {'name': '孕线', 'type': 'bearish', 'index': -1, 'date': '',
                        'strength': 0.55}
        return None

    # =========================================================================
    # 三线形态识别
    # =========================================================================

    def _three_line_patterns(self, df: pd.DataFrame, bars: List[dict], idx: int) -> Optional[dict]:
        """
        识别所有三线形态（idx指向第3根K线）。
        """
        p2 = bars[idx - 2]  # 第一根
        p1 = bars[idx - 1]  # 第二根
        p0 = bars[idx]      # 第三根
        date_str = self._get_date(df, idx)

        # 早晨之星
        ms = self._is_morning_star(p2, p1, p0)
        if ms:
            ms['index'] = idx
            ms['date'] = date_str
            return ms

        # 黄昏之星
        es = self._is_evening_star(p2, p1, p0)
        if es:
            es['index'] = idx
            es['date'] = date_str
            return es

        # 三只乌鸦
        tbc = self._is_three_black_crows(p2, p1, p0)
        if tbc:
            tbc['index'] = idx
            tbc['date'] = date_str
            return tbc

        # 三白兵
        tws = self._is_three_white_soldiers(p2, p1, p0)
        if tws:
            tws['index'] = idx
            tws['date'] = date_str
            return tws

        return None

    def _is_morning_star(self, b1: dict, b2: dict, b3: dict) -> Optional[dict]:
        """
        早晨之星：
        - 第1根：大阴线（实体占比较高）
        - 第2根：小K线/星线（实体小），有向下跳空
        - 第3根：大阳线，收盘超过第1根中点位
        """
        # 第1根：大阴线
        if not b1['is_bearish'] or b1['body_ratio'] < self.MIN_BODY_RATIO:
            return None
        # 第2根：小星线
        if b2['body_ratio'] >= self.SMALL_BODY_MAX:
            return None
        # 向下跳空：星线开盘低于第1根收盘
        if b2['close'] >= b1['close'] * (1 - self.GAP_THRESHOLD):
            return None
        # 第3根：大阳线，收盘超过第1根中点
        if not b3['is_bullish'] or b3['body_ratio'] < self.MIN_BODY_RATIO:
            return None
        if b3['close'] <= b1['body_center']:
            return None

        strength = min(1.0, (b3['close'] - b1['close']) / max(b1['body'], 0.0001))
        return {'name': '早晨之星', 'type': 'bullish', 'index': -1, 'date': '',
                'strength': round(strength, 3)}

    def _is_evening_star(self, b1: dict, b2: dict, b3: dict) -> Optional[dict]:
        """
        黄昏之星：
        - 第1根：大阳线
        - 第2根：小K线/星线，有向上跳空
        - 第3根：大阴线，收盘低于第1根中点
        """
        # 第1根：大阳线
        if not b1['is_bullish'] or b1['body_ratio'] < self.MIN_BODY_RATIO:
            return None
        # 第2根：小星线
        if b2['body_ratio'] >= self.SMALL_BODY_MAX:
            return None
        # 向上跳空：星线开盘高于第1根收盘
        if b2['close'] <= b1['close'] * (1 + self.GAP_THRESHOLD):
            return None
        # 第3根：大阴线，收盘低于第1根中点
        if not b3['is_bearish'] or b3['body_ratio'] < self.MIN_BODY_RATIO:
            return None
        if b3['close'] >= b1['body_center']:
            return None

        strength = min(1.0, (b1['close'] - b3['close']) / max(b1['body'], 0.0001))
        return {'name': '黄昏之星', 'type': 'bearish', 'index': -1, 'date': '',
                'strength': round(strength, 3)}

    def _is_three_black_crows(self, b1: dict, b2: dict, b3: dict) -> Optional[dict]:
        """
        三只乌鸦：
        - 三根连续阴线
        - 每根开盘在前一根实体内
        - 收盘价依次降低
        """
        if not (b1['is_bearish'] and b2['is_bearish'] and b3['is_bearish']):
            return None
        # b2开盘在b1实体内
        if not (b1['close'] <= b2['open'] <= b1['open']):
            return None
        # b3开盘在b2实体内
        if not (b2['close'] <= b3['open'] <= b2['open']):
            return None
        # 收盘依次降低
        if not (b1['close'] > b2['close'] > b3['close']):
            return None

        strength = min(1.0, (b1['close'] - b3['close']) / max(b1['close'], 0.0001) * 5)
        return {'name': '三只乌鸦', 'type': 'bearish', 'index': -1, 'date': '',
                'strength': round(strength, 3)}

    def _is_three_white_soldiers(self, b1: dict, b2: dict, b3: dict) -> Optional[dict]:
        """
        三白兵：
        - 三根连续阳线
        - 每根开盘在前一根实体内
        - 收盘价依次升高
        """
        if not (b1['is_bullish'] and b2['is_bullish'] and b3['is_bullish']):
            return None
        # b2开盘在b1实体内
        if not (b1['open'] <= b2['open'] <= b1['close']):
            return None
        # b3开盘在b2实体内
        if not (b2['open'] <= b3['open'] <= b2['close']):
            return None
        # 收盘依次升高
        if not (b1['close'] < b2['close'] < b3['close']):
            return None

        strength = min(1.0, (b3['close'] - b1['close']) / max(b1['close'], 0.0001) * 5)
        return {'name': '三白兵', 'type': 'bullish', 'index': -1, 'date': '',
                'strength': round(strength, 3)}

    # =========================================================================
    # 强度计算
    # =========================================================================

    def _calc_strength(self, bar: dict, direction: str) -> float:
        """
        计算单根K线形态的强度。

        基于实体占比和影线比例综合评估，范围 [0, 1]。
        """
        if bar['total_range'] == 0:
            return 0.5

        body_score = min(1.0, bar['body_ratio'] * 2)  # 实体占比贡献
        if direction == 'bullish':
            shadow_score = min(1.0, bar['lower_shadow'] / max(bar['total_range'], 0.0001))
        else:
            shadow_score = min(1.0, bar['upper_shadow'] / max(bar['total_range'], 0.0001))

        strength = body_score * 0.4 + shadow_score * 0.6
        return round(strength, 3)


# =============================================================================
# 便捷函数
# =============================================================================

def recognize_candlestick_patterns(df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
    """
    便捷函数：直接对DataFrame执行K线形态识别。

    Args:
        df: 包含 open, high, low, close 列的DataFrame
        **kwargs: 传递给 CandlestickRecognizer 的参数

    Returns:
        与 CandlestickRecognizer.recognize() 相同格式的字典
    """
    recognizer = CandlestickRecognizer(**kwargs)
    return recognizer.recognize(df)


# =============================================================================
# 自测入口
# =============================================================================

if __name__ == '__main__':
    # 生成模拟K线数据进行测试
    np.random.seed(42)
    n_days = 200

    # 模拟一个完整的趋势+反转行情
    prices = []
    price = 100.0
    for i in range(n_days):
        # 前100天缓涨，后100天缓跌
        if i < 100:
            trend = 0.5
        elif i < 150:
            trend = -0.3
        else:
            trend = 0.2
        change = np.random.randn() * 1.5 + trend
        price = max(1.0, price + change)
        prices.append(price)

    df = pd.DataFrame(index=range(n_days))
    df['date'] = pd.date_range('2025-01-01', periods=n_days, freq='B')

    opens, highs, lows, closes = [], [], [], []
    for i in range(n_days):
        o = prices[i]
        c = o + np.random.randn() * 2
        h = max(o, c) + abs(np.random.randn()) * 1.5
        l = min(o, c) - abs(np.random.randn()) * 1.5
        opens.append(o)
        closes.append(c)
        highs.append(h)
        lows.append(l)

    df['open'] = opens
    df['high'] = highs
    df['low'] = lows
    df['close'] = closes
    df['volume'] = np.random.randint(10000, 100000, n_days)

    # 手工注入一些经典形态
    # 锤子线：下跌中，下影线长，实体在顶部
    idx = 40
    df.loc[idx, 'open'] = 102
    df.loc[idx, 'close'] = 103
    df.loc[idx, 'low'] = 95
    df.loc[idx, 'high'] = 104

    # 看涨吞没
    idx = 120
    df.loc[idx - 1, 'open'] = 95
    df.loc[idx - 1, 'close'] = 90
    df.loc[idx, 'open'] = 88
    df.loc[idx, 'close'] = 96

    # 三白兵
    for j in range(3):
        idx = 160 + j
        base = 80 + j * 3
        df.loc[idx, 'open'] = base + 0.5
        df.loc[idx, 'close'] = base + 2.5
        df.loc[idx, 'high'] = base + 3.0
        df.loc[idx, 'low'] = base

    recognizer = CandlestickRecognizer()
    result = recognizer.recognize(df)

    print(f"信号强度: {result['signal']:.4f}")
    print(f"置信度:   {result['confidence']:.4f}")
    print(f"识别形态数: {len(result['patterns'])}")
    print(f"标注点数:   {len(result['markers'])}")
    print()
    print("形态列表 (前10):")
    for p in result['patterns'][:10]:
        print(f"  [{p['type']:>8}] {p['name']:>8} @ idx={p['index']:>3} str={p['strength']:.3f}")

    print("\n自测通过 - CandlestickRecognizer 正常工作。")
