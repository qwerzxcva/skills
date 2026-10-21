"""
资金流向分析模块 — FundFlowAnalyzer

基于资金流向数据或量价关系估算，评估个股/指数的资金面信号。
输入: 行情数据 + 可选资金流数据
输出: signal(-1~1), confidence(0~1), 资金趋势、强度、背离、主力态度等细节
"""

import pandas as pd
import numpy as np
from typing import Optional


class FundFlowAnalyzer:
    """资金流向分析器
    
    支持:
    - 有显式资金流数据时直接聚合
    - 无资金流数据时通过量价关系估算
    - 资金强度计算 (量价加权)
    - 价格-资金背离检测
    """

    def analyze(self, df: pd.DataFrame, fund_flow_df: Optional[pd.DataFrame] = None) -> dict:
        """主分析入口
        
        Args:
            df: 行情DataFrame，必须包含 date, open, high, low, close, volume 列
            fund_flow_df: 可选资金流DataFrame，包含 date, main_net_inflow 等列
        
        Returns:
            dict: {signal, confidence, details}
        """
        # ---------- 边界处理 ----------
        if df is None or df.empty or len(df) < 5:
            return {
                'signal': 0.0,
                'confidence': 0.0,
                'details': {
                    'trend': 'balanced',
                    'net_inflow_5d': 0.0,
                    'net_inflow_20d': 0.0,
                    'intensity': 0.0,
                    'divergence': False,
                    'main_force_attitude': 'neutral',
                }
            }

        df = df.copy()
        df = df.sort_values('date').reset_index(drop=True)

        # ---------- 资金流数据处理 ----------
        has_flow_data = fund_flow_df is not None and not fund_flow_df.empty

        if has_flow_data:
            flow = self._process_flow_data(df, fund_flow_df)
        else:
            flow = self._estimate_flow_from_volume(df)

        # ---------- 资金强度 ----------
        intensity = self._calculate_intensity(df)

        # ---------- 背离检测 ----------
        divergence = self._detect_divergence(df, flow)

        # ---------- 趋势判断 ----------
        net_5d = flow['net_inflow'].tail(5).sum()
        net_20d = flow['net_inflow'].tail(20).sum()

        if abs(net_5d) < 1e-8:
            trend = 'balanced'
        elif net_5d > 0:
            trend = 'inflow'
        else:
            trend = 'outflow'

        # ---------- 主力态度 ----------
        main_attitude = self._classify_main_force(flow, intensity)

        # ---------- 信号合成 ----------
        signal, confidence = self._synthesize_signal(
            trend=trend,
            net_5d=net_5d,
            net_20d=net_20d,
            intensity=intensity,
            divergence=divergence,
            main_attitude=main_attitude,
        )

        return {
            'signal': signal,
            'confidence': confidence,
            'details': {
                'trend': trend,
                'net_inflow_5d': round(float(net_5d), 2),
                'net_inflow_20d': round(float(net_20d), 2),
                'intensity': round(float(intensity), 4),
                'divergence': divergence,
                'main_force_attitude': main_attitude,
            }
        }

    # ========================================================================
    #  内部方法
    # ========================================================================

    def _process_flow_data(self, df: pd.DataFrame, fund_flow_df: pd.DataFrame) -> pd.DataFrame:
        """处理显式资金流数据，对齐到行情日期
        
        Returns:
            DataFrame with columns: date, net_inflow
        """
        flow = fund_flow_df.copy()

        # 使用主力净流入 (main_net_inflow) 作为核心指标
        # 如只有分类数据，合并主力相关字段
        if 'main_net_inflow' in flow.columns:
            flow['net_inflow'] = flow['main_net_inflow']
        elif 'super_large_net_inflow' in flow.columns and 'large_net_inflow' in flow.columns:
            flow['net_inflow'] = (
                flow['super_large_net_inflow'].fillna(0)
                + flow['large_net_inflow'].fillna(0)
            )
        elif 'medium_net_inflow' in flow.columns and 'small_net_inflow' in flow.columns:
            # fallback: 使用所有分类的加总
            cols = [c for c in flow.columns if 'net_inflow' in c]
            flow['net_inflow'] = sum(flow[c].fillna(0) for c in cols)
        else:
            flow['net_inflow'] = 0.0

        # 对齐日期
        if 'date' in flow.columns:
            flow['date'] = pd.to_datetime(flow['date'])
        if 'date' in df.columns:
            df_dates = pd.to_datetime(df['date'])
        else:
            # 回退：假设行对应
            return flow[['net_inflow']].reset_index(drop=True)

        result = pd.DataFrame({'date': df_dates})
        result = result.merge(flow[['date', 'net_inflow']], on='date', how='left')
        result['net_inflow'] = result['net_inflow'].fillna(0.0)
        return result

    def _estimate_flow_from_volume(self, df: pd.DataFrame) -> pd.DataFrame:
        """当无资金流数据时，从量价关系估算资金方向
        
        核心逻辑:
        - 价涨量增 → 资金流入 (给正值)
        - 价跌量增 → 资金流出 (给负值)
        - 价平 → 弱流入/流出
        
        Returns:
            DataFrame with columns: date, net_inflow
        """
        df = df.copy()
        n = len(df)

        df['price_change'] = df['close'].diff().fillna(0)
        df['vol_change'] = df['volume'].diff().fillna(0)
        df['vol_ma'] = df['volume'].rolling(window=5, min_periods=1).mean()

        # 量比 = 当日量 / 5日均量
        df['vol_ratio'] = np.where(df['vol_ma'] > 0, df['volume'] / df['vol_ma'], 1.0)

        # 资金流估算: 量比 * 价格变动符号 * 成交量归一化
        # 价涨 → 正权重，价跌 → 负权重
        df['direction'] = np.sign(df['price_change'])
        df['magnitude'] = 1.0  # 默认幅度 (量比已包含量能信息)

        # 使用 z-score 归一化成交量来估算净流入
        vol_mean = df['volume'].mean()
        vol_std = df['volume'].std()
        if vol_std is None or np.isnan(vol_std) or vol_std < 1e-8:
            vol_std = vol_mean * 0.5 if vol_mean > 0 else 1.0

        # 估算净流入 = 方向 * |价格变动幅度| * 量比 * 成交量偏离度 * 系数
        returns = df['close'].pct_change().fillna(0)
        df['abs_ret'] = np.abs(returns)

        df['net_inflow'] = (
            df['direction']
            * df['abs_ret']
            * df['vol_ratio']
            * df['volume']
            / vol_mean
            * 1e6  # 缩放到合理量级
        )

        # 平滑极端值
        net_std = df['net_inflow'].std()
        if net_std and not np.isnan(net_std) and net_std > 0:
            clip_limit = 3 * net_std
            df['net_inflow'] = df['net_inflow'].clip(-clip_limit, clip_limit)

        result = pd.DataFrame({
            'date': df['date'] if 'date' in df.columns else df.index,
            'net_inflow': df['net_inflow'].values,
        })
        return result

    def _calculate_intensity(self, df: pd.DataFrame, window: int = 20) -> float:
        """资金强度: N日量价加权均值
        
        计算逻辑:
        1. 计算每日的"资金压力" = (close - low)/(high - low) 归一化位置
        2. 用成交量加权该位置值
        3. 取 N 日均值作为强度
        
        结果范围通常在 0.3~0.7，0.5 为中性
        """
        df = df.copy()
        n = len(df)
        actual_window = min(window, n)

        # 当日价格在当日区间的相对位置 (买方力量)
        high_low_range = df['high'] - df['low']
        df['price_position'] = np.where(
            high_low_range > 0,
            (df['close'] - df['low']) / high_low_range,
            0.5  # 一字板，默认中性
        )

        # 成交量加权价格位置
        recent = df.tail(actual_window)
        total_vol = recent['volume'].sum()

        if total_vol <= 0:
            return 0.5

        weighted_pos = (recent['price_position'] * recent['volume']).sum() / total_vol
        return float(weighted_pos)

    def _detect_divergence(self, df: pd.DataFrame, flow: pd.DataFrame) -> bool:
        """价格创新高但资金强度/净流入下降 → 背离
        
        具体条件 (触发任一即视为背离):
        1. 近5日价格创20日新高，但5日累计净流入 < 前5日
        2. 近10日价格创40日新高，但资金强度 < 历史中位数
        """
        n = len(df)
        if n < 20:
            return False

        df = df.copy()
        closes = df['close'].values

        # 条件1: 短期背离
        recent_high = closes[-5:].max()
        prior_high = closes[-20:-5].max() if n >= 20 else closes[:-5].max()
        price_new_high = recent_high > prior_high

        # 资金流对比
        recent_flow = flow['net_inflow'].tail(5).sum()
        prior_flow = flow['net_inflow'].iloc[-10:-5].sum() if n >= 10 else 0.0
        flow_declining = recent_flow < prior_flow

        if price_new_high and flow_declining:
            return True

        # 条件2: 中期背离
        if n >= 40:
            recent_40_high = closes[-10:].max()
            prior_40_high = closes[-40:-10].max()
            if recent_40_high > prior_40_high:
                recent_intensity = self._calculate_intensity(df.tail(10))
                hist_intensity = self._calculate_intensity(df.tail(40).head(20))
                if recent_intensity < hist_intensity:
                    return True

        return False

    def _classify_main_force(self, flow: pd.DataFrame, intensity: float) -> str:
        """分类主力态度: buying / selling / neutral"""
        n = len(flow)
        if n < 5:
            return 'neutral'

        net_5d = flow['net_inflow'].tail(5).sum()
        net_10d = flow['net_inflow'].tail(10).sum() if n >= 10 else net_5d

        # 持续流入 + 强度偏高 → 买入
        if net_5d > 0 and net_10d > 0 and intensity > 0.55:
            return 'buying'
        # 持续流出 + 强度偏低 → 卖出
        elif net_5d < 0 and net_10d < 0 and intensity < 0.45:
            return 'selling'
        else:
            return 'neutral'

    def _synthesize_signal(
        self,
        trend: str,
        net_5d: float,
        net_20d: float,
        intensity: float,
        divergence: bool,
        main_attitude: str,
    ) -> tuple:
        """综合各项指标生成最终信号和置信度
        
        Returns:
            (signal: float, confidence: float)
        """
        signal = 0.0
        confidence_factors = []

        # -------- 趋势因子 --------
        if trend == 'inflow':
            signal += 0.3
            confidence_factors.append(0.4)
            # 中长期也流入 → 加强
            if net_20d > 0:
                signal += 0.2
                confidence_factors.append(0.7)
            else:
                confidence_factors.append(0.4)
        elif trend == 'outflow':
            signal -= 0.3
            confidence_factors.append(0.4)
            if net_20d < 0:
                signal -= 0.2
                confidence_factors.append(0.7)
            else:
                confidence_factors.append(0.4)
        else:
            confidence_factors.append(0.2)

        # -------- 强度因子 --------
        if intensity > 0.6:
            signal += 0.2
            confidence_factors.append(0.6)
        elif intensity > 0.55:
            signal += 0.1
            confidence_factors.append(0.5)
        elif intensity < 0.4:
            signal -= 0.2
            confidence_factors.append(0.6)
        elif intensity < 0.45:
            signal -= 0.1
            confidence_factors.append(0.5)
        else:
            confidence_factors.append(0.3)

        # -------- 主力态度 --------
        if main_attitude == 'buying':
            signal += 0.2
            confidence_factors.append(0.7)
        elif main_attitude == 'selling':
            signal -= 0.2
            confidence_factors.append(0.7)
        else:
            confidence_factors.append(0.3)

        # -------- 背离修正 --------
        if divergence:
            # 背离通常与主要趋势反向
            if signal > 0:
                signal -= 0.3
            else:
                signal += 0.3
            confidence_factors.append(0.6)  # 背离增加判断确定性

        # -------- 归一化 signal 到 [-1, 1] --------
        signal = max(-1.0, min(1.0, signal))

        # -------- 置信度 = 因子均值 --------
        confidence = np.mean(confidence_factors) if confidence_factors else 0.0
        confidence = max(0.0, min(1.0, confidence))

        return round(float(signal), 4), round(float(confidence), 4)
