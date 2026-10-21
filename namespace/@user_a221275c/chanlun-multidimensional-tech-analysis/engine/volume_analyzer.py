"""
成交量分析模块 — VolumeAnalyzer

基于量价关系、量比、成交量趋势和极端量检测，评估成交量维度的技术信号。
输入: 行情DataFrame
输出: signal(-1~1), confidence(0~1), 量价关系、量比、趋势、天量/地量标记等细节
"""

import pandas as pd
import numpy as np
from typing import List, Dict


class VolumeAnalyzer:
    """成交量分析器

    功能:
    - 量价关系分类 (价升量增/价跌量缩 等)
    - 量比计算 (当日量 / 5日均量)
    - 成交量趋势判断 (放量/缩量/平稳)
    - 天量/地量极端点检测
    - ECharts 标注数据生成
    """

    def analyze(self, df: pd.DataFrame) -> dict:
        """主分析入口

        Args:
            df: 行情DataFrame，必须包含 date, open, high, low, close, volume 列

        Returns:
            dict: {signal, confidence, details}
        """
        # ---------- 边界处理 ----------
        if df is None or df.empty or len(df) < 5:
            return {
                'signal': 0.0,
                'confidence': 0.0,
                'details': {
                    'volume_price_relation': 'neutral',
                    'volume_ratio': 1.0,
                    'recent_trend': 'stable',
                    'extreme_points': [],
                    'markers': [],
                }
            }

        df = df.copy()
        df = df.sort_values('date').reset_index(drop=True)
        n = len(df)

        # ---------- 量比 ----------
        vol_ratio_series = self._calculate_volume_ratio(df)
        latest_vol_ratio = float(vol_ratio_series.iloc[-1]) if len(vol_ratio_series) > 0 else 1.0

        # ---------- 量价关系 ----------
        vp_relation = self._classify_vp_relation(df)

        # ---------- 成交量趋势 ----------
        recent_trend = self._classify_volume_trend(df)

        # ---------- 极端量检测 ----------
        extreme_points = self._detect_extreme_volume(df)
        markers = self._generate_markers(extreme_points)

        # ---------- 信号合成 ----------
        signal, confidence = self._synthesize_signal(
            vp_relation=vp_relation,
            vol_ratio=latest_vol_ratio,
            recent_trend=recent_trend,
            extreme_points=extreme_points,
            n=n,
        )

        return {
            'signal': signal,
            'confidence': confidence,
            'details': {
                'volume_price_relation': vp_relation,
                'volume_ratio': round(latest_vol_ratio, 2),
                'recent_trend': recent_trend,
                'extreme_points': extreme_points,
                'markers': markers,
            }
        }

    # ========================================================================
    #  内部方法
    # ========================================================================

    def _classify_vp_relation(self, df: pd.DataFrame) -> str:
        """量价关系分类

        基于最近5日的整体量价关系进行判断:
        - 价升量增 → 'bullish'  (健康上涨，需求驱动)
        - 价跌量缩 → 'bullish'  (惜售，抛压减轻)
        - 价升量缩 → 'bearish'  (上涨乏力，追高意愿不足)
        - 价跌量增 → 'bearish'  (恐慌抛售，供应增加)
        - 其他       → 'neutral'

        Returns:
            str: 'bullish' | 'bearish' | 'neutral'
        """
        df = df.copy()
        n = len(df)

        # 使用最近5日（或更少）来判断
        lookback = min(10, n)
        recent = df.tail(lookback)

        # 价格变化 (首尾比较)
        price_start = recent['close'].iloc[0]
        price_end = recent['close'].iloc[-1]
        price_change_pct = (price_end - price_start) / price_start if price_start > 0 else 0

        # 成交量比较: 后半段 vs 前半段
        mid = len(recent) // 2
        if mid < 1:
            mid = 1
        vol_first_half = recent['volume'].iloc[:mid].mean()
        vol_second_half = recent['volume'].iloc[mid:].mean()

        if vol_first_half <= 0:
            volume_increase = False
        else:
            volume_increase = vol_second_half > vol_first_half * 1.05

        volume_decrease = not volume_increase

        # 判断阈值: 价格变动 < 0.5% 视为平盘
        threshold = 0.005

        if price_change_pct > threshold:
            if volume_increase:
                return 'bullish'   # 价升量增
            elif volume_decrease:
                return 'bearish'   # 价升量缩
            else:
                return 'neutral'
        elif price_change_pct < -threshold:
            if volume_increase:
                return 'bearish'   # 价跌量增
            elif volume_decrease:
                return 'bullish'   # 价跌量缩
            else:
                return 'neutral'
        else:
            return 'neutral'

    def _detect_extreme_volume(
        self, df: pd.DataFrame, high_threshold: float = 2.5, low_threshold: float = 0.4
    ) -> List[Dict]:
        """天量/地量极端点检测

        检测逻辑:
        - 天量: 成交量 > N日均量 * high_threshold (默认2.5倍)
        - 地量: 成交量 < N日均量 * low_threshold  (默认0.4倍)

        Args:
            df: 行情DataFrame
            high_threshold: 天量阈值倍数
            low_threshold: 地量阈值倍数

        Returns:
            List[Dict]: [{index, type, ratio}, ...]
        """
        df = df.copy()
        n = len(df)

        # 计算滚动均量 (20日)
        window = min(20, n)
        df['vol_ma'] = df['volume'].rolling(window=window, min_periods=max(5, window // 2)).mean()

        # 量比 = 当日量 / 均量
        df['ratio'] = np.where(df['vol_ma'] > 0, df['volume'] / df['vol_ma'], np.nan)

        extreme_points = []

        for i in range(n):
            ratio = df['ratio'].iloc[i]
            if pd.isna(ratio):
                continue

            if ratio >= high_threshold:
                extreme_points.append({
                    'index': int(i),
                    'type': 'tian_liang',
                    'ratio': round(float(ratio), 2),
                })
            elif ratio <= low_threshold and df['volume'].iloc[i] > 0:
                extreme_points.append({
                    'index': int(i),
                    'type': 'di_liang',
                    'ratio': round(float(ratio), 2),
                })

        # 合并相邻同类标注 (保留ratio最大的天量、ratio最小的地量)
        extreme_points = self._merge_adjacent_extremes(extreme_points, df)

        # 限制返回数量，避免标注过多
        # 天量保留 top 5, 地量保留 top 5
        tian_liang_points = [p for p in extreme_points if p['type'] == 'tian_liang']
        di_liang_points = [p for p in extreme_points if p['type'] == 'di_liang']

        tian_liang_points.sort(key=lambda x: x['ratio'], reverse=True)
        di_liang_points.sort(key=lambda x: x['ratio'])

        return tian_liang_points[:5] + di_liang_points[:5]

    def _merge_adjacent_extremes(
        self, points: List[Dict], df: pd.DataFrame
    ) -> List[Dict]:
        """合并相邻的同类极端点 (间隔 < 3 日视为同一波)
        
        保留 ratio 更极端的那一个
        """
        if not points:
            return []

        points = sorted(points, key=lambda x: x['index'])
        merged = []
        group = [points[0]]

        for p in points[1:]:
            last = group[-1]
            if p['type'] == last['type'] and (p['index'] - last['index']) <= 3:
                group.append(p)
            else:
                # 选择 group 中最极端的
                if group[0]['type'] == 'tian_liang':
                    best = max(group, key=lambda x: x['ratio'])
                else:
                    best = min(group, key=lambda x: x['ratio'])
                merged.append(best)
                group = [p]

        if group:
            if group[0]['type'] == 'tian_liang':
                best = max(group, key=lambda x: x['ratio'])
            else:
                best = min(group, key=lambda x: x['ratio'])
            merged.append(best)

        return merged

    def _generate_markers(self, extreme_points: List[Dict]) -> List[Dict]:
        """基于极端点生成 ECharts markPoint 标注数据

        Returns:
            List[Dict]: [{index, label, color}, ...] 可直接供ECharts使用
        """
        markers = []
        for point in extreme_points:
            if point['type'] == 'tian_liang':
                markers.append({
                    'index': point['index'],
                    'label': '天量',
                    'color': '#ff4444',
                })
            elif point['type'] == 'di_liang':
                markers.append({
                    'index': point['index'],
                    'label': '地量',
                    'color': '#44aa44',
                })

        return markers

    def _calculate_volume_ratio(self, df: pd.DataFrame) -> pd.Series:
        """量比 = 当日成交量 / 5日均量

        Returns:
            pd.Series: 量比序列
        """
        df = df.copy()
        vol_ma5 = df['volume'].rolling(window=5, min_periods=1).mean()
        ratio = np.where(vol_ma5 > 0, df['volume'] / vol_ma5, 1.0)
        return pd.Series(ratio, index=df.index)

    def _classify_volume_trend(self, df: pd.DataFrame, window: int = 20) -> str:
        """成交量趋势分类

        使用最近 window 日的成交量线性回归斜率来判断:
        - 斜率 > 0 且显著 → 'expanding'  (放量)
        - 斜率 < 0 且显著 → 'contracting' (缩量)
        - 其他             → 'stable'     (平稳)

        Args:
            df: 行情DataFrame
            window: 趋势判断窗口

        Returns:
            str: 'expanding' | 'contracting' | 'stable'
        """
        n = len(df)
        actual_window = min(window, n, 30)  # 最多取最近30日

        if actual_window < 5:
            return 'stable'

        recent_vol = df['volume'].tail(actual_window).values

        # 线性回归: vol ~ day_index
        x = np.arange(actual_window, dtype=float)
        y = recent_vol.astype(float)

        # 处理全零情况
        if y.std() < 1e-8:
            return 'stable'

        # 最小二乘斜率
        x_mean = x.mean()
        y_mean = y.mean()
        slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)

        # 相对斜率 = slope / mean (归一化，使不同价格水平的股票可比)
        rel_slope = slope / y_mean if y_mean > 0 else 0.0

        # 判断阈值
        if rel_slope > 0.01:
            return 'expanding'
        elif rel_slope < -0.01:
            return 'contracting'
        else:
            return 'stable'

    def _synthesize_signal(
        self,
        vp_relation: str,
        vol_ratio: float,
        recent_trend: str,
        extreme_points: List[Dict],
        n: int,
    ) -> tuple:
        """综合指标生成最终信号和置信度

        Returns:
            (signal: float, confidence: float)
        """
        signal = 0.0
        confidence_factors = []

        # -------- 量价关系因子 --------
        if vp_relation == 'bullish':
            signal += 0.3
            confidence_factors.append(0.6)
        elif vp_relation == 'bearish':
            signal -= 0.3
            confidence_factors.append(0.6)
        else:
            confidence_factors.append(0.2)

        # -------- 量比因子 --------
        # 量比适中(0.7~1.5) → 中性偏多
        # 量比过高(>2.5) → 可能是顶/异常放量
        # 量比过低(<0.3) → 可能底部但无资金参与
        if pd.isna(vol_ratio):
            vol_ratio = 1.0

        if 0.7 <= vol_ratio <= 1.5:
            signal += 0.1
            confidence_factors.append(0.5)
        elif vol_ratio > 2.5:
            # 若量价关系为 bullish → 强势放量上攻
            # 若为 bearish → 恐慌放量
            if vp_relation == 'bullish':
                signal += 0.15
                confidence_factors.append(0.6)
            elif vp_relation == 'bearish':
                signal -= 0.15
                confidence_factors.append(0.6)
            else:
                # 放量但不明确 → 信号减弱
                confidence_factors.append(0.3)
        elif vol_ratio < 0.3:
            # 极度缩量 → 观望，偏中性
            confidence_factors.append(0.3)
        else:
            confidence_factors.append(0.4)

        # -------- 成交量趋势因子 --------
        if recent_trend == 'expanding':
            if vp_relation == 'bullish':
                signal += 0.15
                confidence_factors.append(0.6)
            elif vp_relation == 'bearish':
                signal -= 0.15
                confidence_factors.append(0.6)
            else:
                confidence_factors.append(0.4)
        elif recent_trend == 'contracting':
            if vp_relation == 'bullish':
                # 缩量上涨 → 小心
                signal -= 0.1
                confidence_factors.append(0.4)
            elif vp_relation == 'bearish':
                # 缩量下跌 → 偏多（惜售）
                signal += 0.1
                confidence_factors.append(0.4)
            else:
                confidence_factors.append(0.3)
        else:
            confidence_factors.append(0.3)

        # -------- 极端量因子 --------
        if extreme_points:
            latest_idx = n - 1
            recent_extremes = [p for p in extreme_points if latest_idx - p['index'] <= 3]

            has_recent_tian_liang = any(p['type'] == 'tian_liang' for p in recent_extremes)
            has_recent_di_liang = any(p['type'] == 'di_liang' for p in recent_extremes)

            if has_recent_tian_liang:
                # 天量通常是转折信号
                if signal > 0:
                    signal -= 0.2
                else:
                    signal += 0.2
                confidence_factors.append(0.7)

            if has_recent_di_liang:
                # 地量可能是底部信号
                if signal < 0:
                    signal += 0.2
                confidence_factors.append(0.6)

        # -------- 归一化 signal 到 [-1, 1] --------
        signal = max(-1.0, min(1.0, signal))

        # -------- 置信度 = 因子均值 --------
        confidence = np.mean(confidence_factors) if confidence_factors else 0.0
        confidence = max(0.0, min(1.0, confidence))

        return round(float(signal), 4), round(float(confidence), 4)
