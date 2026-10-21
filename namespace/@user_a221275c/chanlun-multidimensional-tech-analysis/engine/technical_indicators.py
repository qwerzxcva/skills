"""
技术指标引擎 — TechnicalIndicators

计算 MACD / KDJ / RSI 三大经典技术指标，检测顶背离/底背离，
做多指标共振判断。配合缠论多维分析系统使用。

输出信号: -1 ~ +1 (负=看空, 零=中性, 正=看多)
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional


class TechnicalIndicators:
    """技术指标引擎

    功能:
    - MACD 计算 (DIF/DEA/柱状图) + 顶背离/底背离检测
    - KDJ 计算 (K/D/J) + 超买/超卖识别
    - RSI 计算 + 超买/超卖识别
    - 多指标共振判断 (同向计数 → 信号强度)
    """

    # ============ MACD ============
    def macd(self, closes: np.ndarray, fast: int = 12,
             slow: int = 26, signal: int = 9) -> dict:
        """计算MACD指标

        Args:
            closes: 收盘价数组
            fast: 快线EMA周期 (默认12)
            slow: 慢线EMA周期 (默认26)
            signal: 信号线EMA周期 (默认9)

        Returns:
            dict: dif, dea, macd_bar, signal(当前方向), cross(金叉/死叉)
        """
        closes = np.asarray(closes, dtype=float)
        n = len(closes)
        if n < slow + signal:
            return self._empty_indicator('dif,dea,macd_bar')

        # EMA计算
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        dif = ema_fast - ema_slow
        dea = self._ema(dif, signal)
        macd_bar = 2 * (dif - dea)

        # 当前信号方向
        last_dif = dif[-1]
        last_dea = dea[-1]
        if last_dif > last_dea:
            direction = 'bullish'
        elif last_dif < last_dea:
            direction = 'bearish'
        else:
            direction = 'neutral'

        # 金叉/死叉检测 (最近3根)
        cross = 'none'
        if len(dif) >= 3:
            for i in range(-3, -1):
                if dif[i - 1] < dea[i - 1] and dif[i] > dea[i]:
                    cross = 'golden'
                    break
                elif dif[i - 1] > dea[i - 1] and dif[i] < dea[i]:
                    cross = 'death'
                    break

        # MACD信号值 (-1~1)
        if direction == 'bullish' and cross == 'golden':
            macd_signal = 0.6
        elif direction == 'bullish':
            macd_signal = 0.3
        elif direction == 'bearish' and cross == 'death':
            macd_signal = -0.6
        elif direction == 'bearish':
            macd_signal = -0.3
        else:
            macd_signal = 0.0

        return {
            'dif': dif.tolist(),
            'dea': dea.tolist(),
            'macd_bar': macd_bar.tolist(),
            'direction': direction,
            'cross': cross,
            'signal': macd_signal,
            'last_dif': float(last_dif),
            'last_dea': float(last_dea),
            'last_bar': float(macd_bar[-1]),
        }

    # ============ KDJ ============
    def kdj(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
            n: int = 9, m1: int = 3, m2: int = 3) -> dict:
        """计算KDJ指标

        Args:
            highs: 最高价数组
            lows: 最低价数组
            closes: 收盘价数组
            n: RSV周期 (默认9)
            m1: K值平滑周期 (默认3)
            m2: D值平滑周期 (默认3)

        Returns:
            dict: k, d, j, signal, overbought, oversold
        """
        highs = np.asarray(highs, dtype=float)
        lows = np.asarray(lows, dtype=float)
        closes = np.asarray(closes, dtype=float)
        length = len(closes)
        if length < n:
            return self._empty_indicator('k,d,j')

        k_values = np.zeros(length)
        d_values = np.zeros(length)

        for i in range(length):
            if i < n - 1:
                k_values[i] = 50.0
                d_values[i] = 50.0
                continue
            window_high = highs[i - n + 1: i + 1].max()
            window_low = lows[i - n + 1: i + 1].min()
            if window_high == window_low:
                rsv = 50.0
            else:
                rsv = (closes[i] - window_low) / (window_high - window_low) * 100
            k_values[i] = (m1 - 1) / m1 * k_values[i - 1] + 1 / m1 * rsv
            d_values[i] = (m2 - 1) / m2 * d_values[i - 1] + 1 / m2 * k_values[i]

        j_values = 3 * k_values - 2 * d_values

        last_k = float(k_values[-1])
        last_d = float(d_values[-1])
        last_j = float(j_values[-1])

        # 超买超卖
        overbought = last_k > 80 or last_j > 100
        oversold = last_k < 20 or last_j < 0

        # 信号方向
        if last_k > last_d and last_j > last_k:
            kdj_signal = 0.5 if not overbought else 0.2  # 超买削弱信号
        elif last_k < last_d and last_j < last_k:
            kdj_signal = -0.5 if not oversold else -0.2
        else:
            kdj_signal = 0.0

        # 金叉死叉
        cross = 'none'
        if length >= 3:
            for i in range(-3, -1):
                if k_values[i - 1] < d_values[i - 1] and k_values[i] > d_values[i]:
                    cross = 'golden'
                    break
                elif k_values[i - 1] > d_values[i - 1] and k_values[i] < d_values[i]:
                    cross = 'death'
                    break

        if cross == 'golden' and kdj_signal > 0:
            kdj_signal = min(1.0, kdj_signal + 0.2)
        elif cross == 'death' and kdj_signal < 0:
            kdj_signal = max(-1.0, kdj_signal - 0.2)

        return {
            'k': k_values.tolist(),
            'd': d_values.tolist(),
            'j': j_values.tolist(),
            'signal': kdj_signal,
            'last_k': last_k,
            'last_d': last_d,
            'last_j': last_j,
            'overbought': overbought,
            'oversold': oversold,
            'cross': cross,
        }

    # ============ RSI ============
    def rsi(self, closes: np.ndarray, period: int = 14) -> dict:
        """计算RSI指标

        Args:
            closes: 收盘价数组
            period: RSI周期 (默认14)

        Returns:
            dict: rsi_values, signal, overbought, oversold
        """
        closes = np.asarray(closes, dtype=float)
        n = len(closes)
        if n < period + 1:
            return self._empty_indicator('rsi_values')

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        # Wilder's smoothing
        avg_gain = np.zeros(n)
        avg_loss = np.zeros(n)
        avg_gain[period] = gains[:period].mean()
        avg_loss[period] = losses[:period].mean()

        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

        rsi_values = np.zeros(n)
        for i in range(period, n):
            if avg_loss[i] == 0:
                rsi_values[i] = 100.0
            else:
                rs = avg_gain[i] / avg_loss[i]
                rsi_values[i] = 100 - 100 / (1 + rs)

        # 前 period 个填50
        rsi_values[:period] = 50.0

        last_rsi = float(rsi_values[-1])
        overbought = last_rsi > 70
        oversold = last_rsi < 30

        # 信号
        if overbought:
            rsi_signal = -0.2  # 超买偏空
        elif oversold:
            rsi_signal = 0.2   # 超卖偏多
        elif last_rsi > 50:
            rsi_signal = 0.3
        elif last_rsi < 50:
            rsi_signal = -0.3
        else:
            rsi_signal = 0.0

        return {
            'rsi_values': rsi_values.tolist(),
            'signal': rsi_signal,
            'last_rsi': last_rsi,
            'overbought': overbought,
            'oversold': oversold,
        }

    # ============ 背离检测 ============
    def detect_divergence(self, prices: np.ndarray, indicator: np.ndarray,
                          indicator_name: str, window: int = 60,
                          max_results: int = 2) -> List[dict]:
        """检测顶背离/底背离（优化版：限制范围+只取最近1-2个）

        顶背离: 价格创新高，指标未创新高
        底背离: 价格创新低，指标未创新低

        优化策略:
        - 只扫描最近 window 根K线 (默认60)
        - 每种背离只返回最近 max_results 个 (默认2: 1顶+1底)
        - 避免历史背离过多压垮信心打分

        Args:
            prices: 价格序列 (通常用close)
            indicator: 指标序列 (如MACD柱状图、RSI、KDJ的D值)
            indicator_name: 指标名称
            window: 回溯窗口 (默认60根)
            max_results: 每种背离最多返回几个 (默认2)

        Returns:
            list of divergence dicts: type, idx, price_high/low, indicator_value
        """
        prices = np.asarray(prices, dtype=float)
        indicator = np.asarray(indicator, dtype=float)
        n = len(prices)
        if n < 10:
            return []

        # 只扫描最近 window 根
        start_idx = max(0, n - window)
        scan_prices = prices[start_idx:]
        scan_indicator = indicator[start_idx:]
        scan_n = len(scan_prices)

        if scan_n < 10:
            return []

        # 找局部极值点 (在窗口内)
        peaks = self._find_peaks(scan_prices, window=5)
        troughs = self._find_troughs(scan_prices, window=5)

        top_divergences = []
        bottom_divergences = []

        # 顶背离检测：从最近的peak往前找，只取最近max_results个
        for i in range(len(peaks) - 1, 0, -1):
            if len(top_divergences) >= max_results:
                break
            p1, p2 = peaks[i - 1], peaks[i]
            if p2 - p1 < 5:
                continue
            if scan_prices[p2] > scan_prices[p1] and scan_indicator[p2] < scan_indicator[p1]:
                strength = (scan_prices[p2] / scan_prices[p1] - 1) * 100
                top_divergences.append({
                    'type': 'top',
                    'indicator': indicator_name,
                    'start_idx': int(p1 + start_idx),
                    'end_idx': int(p2 + start_idx),
                    'price_high_1': float(scan_prices[p1]),
                    'price_high_2': float(scan_prices[p2]),
                    'indicator_value_1': float(scan_indicator[p1]),
                    'indicator_value_2': float(scan_indicator[p2]),
                    'strength': float(strength),
                    'description': f'{indicator_name}顶背离: 价格新高{scan_prices[p2]:.4f}>{scan_prices[p1]:.4f}, '
                                   f'指标未新高{scan_indicator[p2]:.4f}<{scan_indicator[p1]:.4f}',
                })

        # 底背离检测：从最近的trough往前找
        for i in range(len(troughs) - 1, 0, -1):
            if len(bottom_divergences) >= max_results:
                break
            t1, t2 = troughs[i - 1], troughs[i]
            if t2 - t1 < 5:
                continue
            if scan_prices[t2] < scan_prices[t1] and scan_indicator[t2] > scan_indicator[t1]:
                strength = (1 - scan_prices[t2] / scan_prices[t1]) * 100
                bottom_divergences.append({
                    'type': 'bottom',
                    'indicator': indicator_name,
                    'start_idx': int(t1 + start_idx),
                    'end_idx': int(t2 + start_idx),
                    'price_low_1': float(scan_prices[t1]),
                    'price_low_2': float(scan_prices[t2]),
                    'indicator_value_1': float(scan_indicator[t1]),
                    'indicator_value_2': float(scan_indicator[t2]),
                    'strength': float(strength),
                    'description': f'{indicator_name}底背离: 价格新低{scan_prices[t2]:.4f}<{scan_prices[t1]:.4f}, '
                                   f'指标未新低{scan_indicator[t2]:.4f}>{scan_indicator[t1]:.4f}',
                })

        # 合并并按时间排序
        all_divs = top_divergences + bottom_divergences
        all_divs.sort(key=lambda x: x['end_idx'], reverse=True)
        return all_divs

    # ============ 多指标共振 ============
    def resonance(self, macd_result: dict, kdj_result: dict,
                  rsi_result: dict, chan_signal: float = 0,
                  obv_result: dict = None) -> dict:
        """多指标共振判断

        统计 MACD/KDJ/RSI/OBV/缠论 信号方向，同向计数越多，共振越强。

        Args:
            macd_result: MACD结果
            kdj_result: KDJ结果
            rsi_result: RSI结果
            chan_signal: 缠论信号 (-1~1)
            obv_result: OBV结果 (可选)

        Returns:
            dict: score(-1~1), alignment(bullish/bearish/neutral),
                  bull_count, bear_count, details
        """
        signals = {
            'macd': macd_result.get('signal', 0),
            'kdj': kdj_result.get('signal', 0),
            'rsi': rsi_result.get('signal', 0),
            'chan': chan_signal,
        }
        if obv_result:
            signals['obv'] = obv_result.get('signal', 0)

        bull_count = sum(1 for v in signals.values() if v > 0.1)
        bear_count = sum(1 for v in signals.values() if v < -0.1)
        total = len(signals)
        neutral_count = total - bull_count - bear_count

        # 共振强度 (5个指标: 3+同向=强, 2+同向=中)
        strong_threshold = 3 if total >= 5 else 2
        if bull_count >= strong_threshold:
            alignment = 'strong_bullish'
            score = 0.8
        elif bull_count >= 2:
            alignment = 'bullish'
            score = 0.4
        elif bear_count >= strong_threshold:
            alignment = 'strong_bearish'
            score = -0.8
        elif bear_count >= 2:
            alignment = 'bearish'
            score = -0.4
        else:
            alignment = 'neutral'
            score = 0.0

        # 背离汇总
        divergences = []
        if 'divergences' in macd_result:
            divergences.extend(macd_result['divergences'])
        if 'divergences' in kdj_result:
            divergences.extend(kdj_result['divergences'])
        if 'divergences' in rsi_result:
            divergences.extend(rsi_result['divergences'])

        top_div_count = sum(1 for d in divergences if d['type'] == 'top')
        bottom_div_count = sum(1 for d in divergences if d['type'] == 'bottom')

        # 背离会减弱共振信号
        if top_div_count > 0 and score > 0:
            score = max(0, score - 0.3 * top_div_count)
        if bottom_div_count > 0 and score < 0:
            score = min(0, score + 0.3 * bottom_div_count)

        return {
            'score': float(score),
            'alignment': alignment,
            'bull_count': bull_count,
            'bear_count': bear_count,
            'neutral_count': neutral_count,
            'signals': {k: float(v) for k, v in signals.items()},
            'divergences': divergences,
            'top_divergences': top_div_count,
            'bottom_divergences': bottom_div_count,
            'description': self._resonance_description(alignment, bull_count, bear_count,
                                                       top_div_count, bottom_div_count),
        }

    # ============ OBV ============
    def obv(self, closes: np.ndarray, volumes: np.ndarray) -> dict:
        """计算OBV(能量潮)指标

        OBV逻辑: 上涨日加成交量，下跌日减成交量，平盘不变。
        OBV趋势反映资金流向，与价格趋势对比可判断量能配合。

        Args:
            closes: 收盘价数组
            volumes: 成交量数组

        Returns:
            dict: obv_values, obv_ma5, obv_ma20, signal, vol_alert, last_obv
        """
        closes = np.asarray(closes, dtype=float)
        volumes = np.asarray(volumes, dtype=float)
        n = len(closes)
        if n < 2:
            return {'obv_values': [], 'obv_ma5': [], 'obv_ma20': [],
                    'signal': 0.0, 'vol_alert': '数据不足', 'last_obv': 0}

        obv_values = np.zeros(n)
        obv_values[0] = volumes[0]
        for i in range(1, n):
            if closes[i] > closes[i - 1]:
                obv_values[i] = obv_values[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv_values[i] = obv_values[i - 1] - volumes[i]
            else:
                obv_values[i] = obv_values[i - 1]

        obv_ma5 = self._sma(obv_values, 5)
        obv_ma20 = self._sma(obv_values, 20)

        last_obv = float(obv_values[-1])
        last_ma5 = float(obv_ma5[-1]) if n >= 5 else last_obv
        last_ma20 = float(obv_ma20[-1]) if n >= 20 else last_obv

        # 量能提示
        if last_obv > last_ma5 * 1.05 and last_ma5 > last_ma20:
            vol_alert = 'OBV放量上攻，资金积极流入'
            obv_signal = 0.4
        elif last_obv > last_ma5 and last_ma5 > last_ma20:
            vol_alert = 'OBV温和上行，资金持续流入'
            obv_signal = 0.2
        elif last_obv < last_ma5 * 0.95 and last_ma5 < last_ma20:
            vol_alert = 'OBV缩量回落，资金流出明显'
            obv_signal = -0.4
        elif last_obv < last_ma5 and last_ma5 < last_ma20:
            vol_alert = 'OBV温和下行，资金缓慢流出'
            obv_signal = -0.2
        else:
            vol_alert = 'OBV平稳震荡，量能中性'
            obv_signal = 0.0

        # 近5日OBV变化率
        if n >= 6:
            obv_5d_ago = obv_values[-6]
            if obv_5d_ago != 0:
                obv_change_5d = (last_obv / obv_5d_ago - 1) * 100
            else:
                obv_change_5d = 0
        else:
            obv_change_5d = 0

        return {
            'obv_values': obv_values.tolist(),
            'obv_ma5': obv_ma5.tolist(),
            'obv_ma20': obv_ma20.tolist(),
            'signal': obv_signal,
            'vol_alert': vol_alert,
            'last_obv': last_obv,
            'last_ma5': last_ma5,
            'last_ma20': last_ma20,
            'obv_change_5d': float(obv_change_5d),
        }

    # ============ BOLL 布林带 ============
    def boll(self, closes: np.ndarray, period: int = 20, k: float = 2.0) -> dict:
        """计算布林带(BOLL)指标

        中轨=period日均线，上/下轨=中轨±k倍标准差。
        用于判断价格相对波动区间的位置与波动率开口状态。

        Args:
            closes: 收盘价数组
            period: 均线周期(默认20)
            k: 标准差倍数(默认2.0)

        Returns:
            dict: upper/mid/lower 序列, 当前值, position_state, bandwidth_state,
                  signal(-1~1), guide
        """
        closes = np.asarray(closes, dtype=float)
        n = len(closes)
        if n < period:
            return {
                'upper': [], 'mid': [], 'lower': [],
                'last_upper': 0.0, 'last_mid': 0.0, 'last_lower': 0.0,
                'last_close': float(closes[-1]) if n else 0.0,
                'position_state': '数据不足', 'bandwidth_state': '数据不足',
                'bandwidth': 0.0, 'signal': 0.0, 'guide': '数据不足，无法计算布林带',
            }

        mid = self._sma(closes, period)
        std = np.zeros(n)
        for i in range(n):
            if i < period - 1:
                std[i] = closes[:i + 1].std(ddof=0)
            else:
                std[i] = closes[i - period + 1:i + 1].std(ddof=0)
        upper = mid + k * std
        lower = mid - k * std

        last_close = float(closes[-1])
        last_upper = float(upper[-1])
        last_mid = float(mid[-1])
        last_lower = float(lower[-1])

        # 价格位置状态
        if last_close >= last_upper:
            position_state = '触及/突破上轨(超买区)'
        elif last_close >= last_mid:
            position_state = '运行于中轨与上轨之间(偏强)'
        elif last_close > last_lower:
            position_state = '运行于中轨与下轨之间(偏弱)'
        else:
            position_state = '触及/跌破下轨(超卖区)'

        # 带宽(波动率)与开口状态
        bandwidth = (last_upper - last_lower) / last_mid * 100 if last_mid else 0.0
        if n >= period + 5:
            prev_bw = (upper[-6] - lower[-6]) / mid[-6] * 100 if mid[-6] else bandwidth
        else:
            prev_bw = bandwidth
        bw_change = bandwidth - prev_bw
        if bw_change > bandwidth * 0.03:
            bandwidth_state = '开口放大(波动率上升)'
        elif bw_change < -bandwidth * 0.03:
            bandwidth_state = '开口收窄(波动率下降)'
        else:
            bandwidth_state = '开口走平(波动率平稳)'

        # 信号
        if last_close >= last_upper:
            boll_signal = -0.3  # 超买，短线有回落风险
        elif last_close < last_lower:
            boll_signal = 0.3   # 超卖，短线有反弹动力
        elif last_close >= last_mid and '收窄' not in bandwidth_state:
            boll_signal = 0.3
        elif last_close < last_mid and '收窄' not in bandwidth_state:
            boll_signal = -0.3
        else:
            boll_signal = 0.0

        # 文字指引
        if boll_signal > 0:
            guide = f'价格{position_state}，{bandwidth_state}，短线偏多，可关注中轨({last_mid:.4f})支撑'
        elif boll_signal < 0:
            guide = f'价格{position_state}，{bandwidth_state}，短线偏空，注意上轨({last_upper:.4f})压力'
        else:
            guide = f'价格{position_state}，{bandwidth_state}，方向不明，等待开口方向确认'

        return {
            'upper': upper.tolist(),
            'mid': mid.tolist(),
            'lower': lower.tolist(),
            'last_upper': last_upper,
            'last_mid': last_mid,
            'last_lower': last_lower,
            'last_close': last_close,
            'position_state': position_state,
            'bandwidth_state': bandwidth_state,
            'bandwidth': float(bandwidth),
            'signal': boll_signal,
            'guide': guide,
        }

    # ============ 均线系统 ============
    def ma_system(self, df: pd.DataFrame) -> dict:
        """均线系统分析

        读取 df 的 ma5/ma10/ma20/ma60/ma120/ma250 列，
        判断多空排列、支撑/压力均线、信号与指引。

        Args:
            df: 含 close 及 ma* 列的 DataFrame

        Returns:
            dict: mas(各均线当前值+斜率), arrangement, support_ma, resist_ma,
                  signal(-1~1), guide
        """
        last_close = float(df['close'].values[-1])
        ma_periods = [5, 10, 20, 60, 120, 250]
        mas = {}
        for p in ma_periods:
            col = f'ma{p}'
            if col in df.columns:
                series = df[col].values
                val = series[-1]
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    continue
                # 斜率(近5日方向)
                if len(series) >= 6 and not np.isnan(series[-6]):
                    slope_raw = val - series[-6]
                    if slope_raw > 0:
                        slope = '上行'
                    elif slope_raw < 0:
                        slope = '下行'
                    else:
                        slope = '走平'
                else:
                    slope = '走平'
                mas[col] = {'value': float(val), 'slope': slope}

        # 排列判断(以短中长期为准)
        short_mid_long = [mas.get('ma5'), mas.get('ma10'), mas.get('ma20'), mas.get('ma60')]
        vals = [m['value'] for m in short_mid_long if m]
        arrangement = '均线数据不足'
        if len(vals) >= 3:
            if all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)):
                arrangement = '多头排列(短期在上，趋势向上)'
            elif all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)):
                arrangement = '空头排列(短期在下，趋势向下)'
            else:
                arrangement = '均线缠绕(方向不明，震荡格局)'

        # 支撑/压力均线
        below = [(p, m['value']) for p, m in mas.items() if m['value'] < last_close]
        above = [(p, m['value']) for p, m in mas.items() if m['value'] > last_close]
        support_ma = max(below, key=lambda x: x[1]) if below else None
        resist_ma = min(above, key=lambda x: x[1]) if above else None

        # 信号
        ma20 = mas.get('ma20', {}).get('value')
        if '多头排列' in arrangement and ma20 and last_close > ma20:
            ma_signal = 0.4
        elif '空头排列' in arrangement and ma20 and last_close < ma20:
            ma_signal = -0.4
        elif '缠绕' in arrangement:
            ma_signal = 0.0
        elif ma20 and last_close > ma20:
            ma_signal = 0.2
        elif ma20 and last_close < ma20:
            ma_signal = -0.2
        else:
            ma_signal = 0.0

        # 指引
        sup_txt = f"{support_ma[0].upper()}({support_ma[1]:.4f})" if support_ma else '无明确支撑'
        res_txt = f"{resist_ma[0].upper()}({resist_ma[1]:.4f})" if resist_ma else '无明确压力'
        guide = f'{arrangement}；下方支撑看 {sup_txt}，上方压力看 {res_txt}'

        return {
            'mas': mas,
            'last_close': last_close,
            'arrangement': arrangement,
            'support_ma': {'name': support_ma[0], 'value': support_ma[1]} if support_ma else None,
            'resist_ma': {'name': resist_ma[0], 'value': resist_ma[1]} if resist_ma else None,
            'signal': ma_signal,
            'guide': guide,
        }

    # ============ 主分析入口 ============
    def analyze(self, df: pd.DataFrame, chan_signal: float = 0) -> dict:
        """主分析入口

        Args:
            df: 含 open/high/low/close/volume 的DataFrame
            chan_signal: 缠论维度信号 (-1~1)，用于共振判断

        Returns:
            完整技术指标分析结果
        """
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values if 'volume' in df.columns else np.zeros(len(closes))

        # 计算四大指标
        macd_result = self.macd(closes)
        kdj_result = self.kdj(highs, lows, closes)
        rsi_result = self.rsi(closes)
        obv_result = self.obv(closes, volumes)

        # BOLL + 均线系统 (纯展示/深度解读层，不回灌融合权重)
        boll_result = self.boll(closes)
        ma_result = self.ma_system(df)

        # 背离检测 (用MACD柱状图和RSI)
        if len(macd_result.get('macd_bar', [])) > 10:
            macd_div = self.detect_divergence(
                closes, np.array(macd_result['macd_bar']), 'MACD', window=60)
            macd_result['divergences'] = macd_div

        if len(rsi_result.get('rsi_values', [])) > 10:
            rsi_div = self.detect_divergence(
                closes, np.array(rsi_result['rsi_values']), 'RSI', window=60)
            rsi_result['divergences'] = rsi_div

        if len(kdj_result.get('d', [])) > 10:
            kdj_div = self.detect_divergence(
                closes, np.array(kdj_result['d']), 'KDJ', window=60)
            kdj_result['divergences'] = kdj_div

        # 多指标共振 (含OBV)
        resonance_result = self.resonance(macd_result, kdj_result, rsi_result,
                                          chan_signal, obv_result)

        # 信心打分 (0-10分)
        confidence_score = self._confidence_score(
            macd_result, kdj_result, rsi_result, resonance_result)

        return {
            'macd': macd_result,
            'kdj': kdj_result,
            'rsi': rsi_result,
            'obv': obv_result,
            'boll': boll_result,
            'ma_system': ma_result,
            'resonance': resonance_result,
            'confidence_score': confidence_score,
            'signal': resonance_result['score'],  # 技术指标综合信号
            'summary': self._build_summary(macd_result, kdj_result, rsi_result,
                                           resonance_result, confidence_score, obv_result),
        }

    # ============ 内部工具 ============
    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """指数移动平均"""
        result = np.zeros_like(data, dtype=float)
        if len(data) == 0:
            return result
        result[0] = data[0]
        alpha = 2 / (period + 1)
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    def _sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """简单移动平均"""
        result = np.zeros_like(data, dtype=float)
        for i in range(len(data)):
            if i < period - 1:
                result[i] = data[:i + 1].mean()
            else:
                result[i] = data[i - period + 1:i + 1].mean()
        return result

    def _find_peaks(self, data: np.ndarray, window: int = 5) -> List[int]:
        """找局部峰值索引"""
        peaks = []
        for i in range(window, len(data) - window):
            if all(data[i] >= data[i - j] for j in range(1, window + 1)) and \
               all(data[i] >= data[i + j] for j in range(1, window + 1)):
                peaks.append(i)
        return peaks

    def _find_troughs(self, data: np.ndarray, window: int = 5) -> List[int]:
        """找局部谷值索引"""
        troughs = []
        for i in range(window, len(data) - window):
            if all(data[i] <= data[i - j] for j in range(1, window + 1)) and \
               all(data[i] <= data[i + j] for j in range(1, window + 1)):
                troughs.append(i)
        return troughs

    def _empty_indicator(self, keys: str) -> dict:
        """空指标返回"""
        result = {}
        for k in keys.split(','):
            result[k.strip()] = []
        result['signal'] = 0.0
        return result

    def _confidence_score(self, macd_r: dict, kdj_r: dict, rsi_r: dict,
                          resonance: dict) -> dict:
        """计算信心打分 (0-10分)

        评分维度:
        - 指标一致性 (0-4分): 共振方向一致度
        - 趋势强度 (0-3分): 信号强度
        - 背离反向惩罚 (-2~0分): 有背离扣分
        - 金叉/死叉加分 (0-1分): 近期发生金叉/死叉

        Returns:
            dict: score(0-10), factors(各维度分值), explanation
        """
        score = 0.0
        factors = {}

        # 1. 一致性 (0-4分)
        bull = resonance['bull_count']
        bear = resonance['bear_count']
        max_align = max(bull, bear)
        consistency = min(4, max_align)  # 4个指标同向=4分
        factors['一致性'] = consistency
        score += consistency

        # 2. 趋势强度 (0-3分)
        abs_score = abs(resonance['score'])
        strength = min(3, abs_score * 3.75)  # 0.8对应3分
        factors['趋势强度'] = strength
        score += strength

        # 3. 背离惩罚 (-2~0分)
        top_div = resonance['top_divergences']
        bottom_div = resonance['bottom_divergences']
        div_penalty = 0
        if resonance['alignment'] in ('bullish', 'strong_bullish') and top_div > 0:
            div_penalty = -min(2, top_div)
        elif resonance['alignment'] in ('bearish', 'strong_bearish') and bottom_div > 0:
            div_penalty = -min(2, bottom_div)
        factors['背离惩罚'] = div_penalty
        score += div_penalty

        # 4. 金叉/死叉加分 (0-1分)
        cross_bonus = 0
        if macd_r.get('cross') == 'golden' and resonance['score'] > 0:
            cross_bonus = 1
        elif macd_r.get('cross') == 'death' and resonance['score'] < 0:
            cross_bonus = 1
        factors['交叉确认'] = cross_bonus
        score += cross_bonus

        score = max(0, min(10, score))

        # 解释文本
        level = '极高' if score >= 8 else '高' if score >= 6 else '中' if score >= 4 else '低' if score >= 2 else '极低'
        explanation = f'信心打分{score:.1f}/10 ({level}): 一致性{consistency:.0f}/4 + 趋势强度{strength:.1f}/3'
        if div_penalty < 0:
            explanation += f' + 背离惩罚{div_penalty:.0f}'
        if cross_bonus > 0:
            explanation += f' + 交叉确认+{cross_bonus}'

        return {
            'score': float(score),
            'factors': factors,
            'level': level,
            'explanation': explanation,
        }

    def _resonance_description(self, alignment: str, bull: int, bear: int,
                               top_div: int, bottom_div: int) -> str:
        """生成共振描述"""
        align_map = {
            'strong_bullish': '强多头共振',
            'bullish': '多头共振',
            'strong_bearish': '强空头共振',
            'bearish': '空头共振',
            'neutral': '方向分歧',
        }
        desc = f'{align_map.get(alignment, "中性")}：{bull}多/{bear}空/{4-bull-bear}中性'
        if top_div > 0:
            desc += f'，{top_div}个顶背离警示'
        if bottom_div > 0:
            desc += f'，{bottom_div}个底背离支持'
        return desc

    def _build_summary(self, macd_r: dict, kdj_r: dict, rsi_r: dict,
                       resonance: dict, confidence: dict,
                       obv_r: dict = None) -> str:
        """构建技术指标综合摘要"""
        parts = []

        # MACD
        macd_dir = {'bullish': '多头', 'bearish': '空头', 'neutral': '中性'}.get(
            macd_r.get('direction', 'neutral'), '中性')
        cross_map = {'golden': '金叉', 'death': '死叉', 'none': '无'}
        macd_cross = cross_map.get(macd_r.get('cross', 'none'), '无')
        parts.append(f'MACD {macd_dir}(DIF{macd_r.get("last_dif",0):.4f}/DEA{macd_r.get("last_dea",0):.4f}) {macd_cross}')

        # KDJ
        k = kdj_r.get('last_k', 50)
        d = kdj_r.get('last_d', 50)
        j = kdj_r.get('last_j', 50)
        kdj_state = '超买' if kdj_r.get('overbought') else '超卖' if kdj_r.get('oversold') else '正常'
        parts.append(f'KDJ K{k:.1f}/D{d:.1f}/J{j:.1f} {kdj_state}')

        # RSI
        rsi_val = rsi_r.get('last_rsi', 50)
        rsi_state = '超买' if rsi_r.get('overbought') else '超卖' if rsi_r.get('oversold') else '中性'
        parts.append(f'RSI {rsi_val:.1f} {rsi_state}')

        # OBV
        if obv_r:
            parts.append(f'OBV {obv_r.get("vol_alert", "")}')

        # 共振
        parts.append(resonance['description'])

        # 信心
        parts.append(confidence['explanation'])

        return ' | '.join(parts)


# ============ 单元测试 ============
if __name__ == '__main__':
    import random
    random.seed(42)

    ti = TechnicalIndicators()

    # 生成模拟数据
    n = 100
    closes = np.cumsum(np.random.randn(n) * 0.02) + 10
    highs = closes + np.abs(np.random.randn(n) * 0.01)
    lows = closes - np.abs(np.random.randn(n) * 0.01)

    # 测试MACD
    print('=== MACD测试 ===')
    macd_r = ti.macd(closes)
    print(f'方向: {macd_r["direction"]}, 交叉: {macd_r["cross"]}')
    print(f'信号: {macd_r["signal"]:+.3f}')
    assert len(macd_r['dif']) == n, 'MACD长度错误'
    assert -1 <= macd_r['signal'] <= 1, 'MACD信号超出范围'

    # 测试KDJ
    print('\n=== KDJ测试 ===')
    kdj_r = ti.kdj(highs, lows, closes)
    print(f'K={kdj_r["last_k"]:.2f} D={kdj_r["last_d"]:.2f} J={kdj_r["last_j"]:.2f}')
    print(f'超买: {kdj_r["overbought"]}, 超卖: {kdj_r["oversold"]}')
    assert len(kdj_r['k']) == n, 'KDJ长度错误'

    # 测试RSI
    print('\n=== RSI测试 ===')
    rsi_r = ti.rsi(closes)
    print(f'RSI: {rsi_r["last_rsi"]:.2f}')
    print(f'超买: {rsi_r["overbought"]}, 超卖: {rsi_r["oversold"]}')
    assert 0 <= rsi_r['last_rsi'] <= 100, 'RSI超出范围'

    # 测试背离检测
    print('\n=== 背离检测测试 ===')
    divs = ti.detect_divergence(closes, np.array(macd_r['macd_bar']), 'MACD')
    print(f'检测到{len(divs)}个背离')
    for d in divs[:3]:
        print(f'  {d["description"]}')

    # 测试共振
    print('\n=== 共振判断 ===')
    res = ti.resonance(macd_r, kdj_r, rsi_r, chan_signal=0.3)
    print(f'共振方向: {res["alignment"]}')
    print(f'多头: {res["bull_count"]}, 空头: {res["bear_count"]}')
    print(f'共振得分: {res["score"]:+.3f}')
    print(res['description'])

    # 测试完整分析
    print('\n=== 完整分析 ===')
    df = pd.DataFrame({
        'date': pd.date_range('2025-01-01', periods=n),
        'open': closes, 'high': highs, 'low': lows, 'close': closes,
        'volume': np.random.randint(1000000, 5000000, n),
    })
    result = ti.analyze(df, chan_signal=0.3)
    print(f'综合信号: {result["signal"]:+.3f}')
    print(f'信心: {result["confidence_score"]["explanation"]}')
    print(f'摘要: {result["summary"]}')

    print('\n[OK] 所有测试通过')
