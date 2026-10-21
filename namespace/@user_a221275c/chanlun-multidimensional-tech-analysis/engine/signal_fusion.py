"""
信号融合引擎
四维分析结果加权投票，输出综合交易信号
"""

import numpy as np
from typing import Optional


class SignalFusion:
    """
    加权投票制信号融合

    默认权重:
      - 缠论信号: 40%
      - K线形态:  20%
      - 资金流向:  20%
      - 成交量:   20%

    信号等级:
      强买 >0.6  |  中买 0.3~0.6  |  观望 -0.3~0.3  |  中卖 -0.6~-0.3  |  强卖 <-0.6
    """

    DEFAULT_WEIGHTS = {
        'chan': 0.40,
        'candlestick': 0.20,
        'fund_flow': 0.20,
        'volume': 0.20,
    }

    SIGNAL_LEVELS = [
        (-1.0, -0.6, 'strong_sell', '强卖', '#006600'),
        (-0.6, -0.3, 'medium_sell', '中卖', '#33aa33'),
        (-0.3, 0.3, 'neutral', '观望', '#999999'),
        (0.3, 0.6, 'medium_buy', '中买', '#ff9933'),
        (0.6, 1.0, 'strong_buy', '强买', '#ff0000'),
    ]

    def __init__(self, weights: Optional[dict] = None):
        """
        weights: 自定义权重字典 {'chan': 0.5, 'candlestick': 0.15, ...}
        权重之和会自动归一化
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self._normalize_weights()

    def _normalize_weights(self):
        """权重归一化，确保总和为1.0"""
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()

    def _extract_signal(self, result: dict, key: str) -> tuple:
        """从单个分析结果中提取信号值和置信度"""
        if result is None or not isinstance(result, dict):
            return 0.0, 0.0
        signal = float(result.get('signal', 0.0))
        confidence = float(result.get('confidence', 0.0))
        # 钳制到[-1, 1]范围
        signal = max(-1.0, min(1.0, signal))
        confidence = max(0.0, min(1.0, confidence))
        return signal, confidence

    def _classify_signal(self, fused_score: float) -> dict:
        """将融合评分映射到信号等级"""
        for low, high, key, label, color in self.SIGNAL_LEVELS:
            if low <= fused_score < high or (high == 1.0 and fused_score == 1.0):
                return {'level': key, 'label': label, 'color': color}
        return {'level': 'neutral', 'label': '观望', 'color': '#999999'}

    def _resolve_conflict(self, chan_signal: float, fused_score: float) -> float:
        """
        冲突解决规则:
        - 缠论强信号(>0.6或<-0.6)优先，其他维度只能降级不能反转
        - 缠论无明确信号时，其他三维决定方向
        """
        if abs(chan_signal) > 0.6:
            # 缠论强信号 → 可被其他维度降级最多50%
            if np.sign(chan_signal) != np.sign(fused_score):
                fused_score = chan_signal * 0.5
            elif abs(fused_score) < abs(chan_signal) * 0.5:
                fused_score = chan_signal * 0.5
        return fused_score

    def fuse(self,
             chan_result: Optional[dict] = None,
             candle_result: Optional[dict] = None,
             fund_result: Optional[dict] = None,
             volume_result: Optional[dict] = None) -> dict:
        """
        融合四维分析结果

        Args:
            chan_result: 缠论引擎输出
            candle_result: K线形态识别输出
            fund_result: 资金流向分析输出
            volume_result: 成交量分析输出

        Returns:
            {
                'fused_signal': float,     # 融合后的最终信号 (-1.0 ~ 1.0)
                'fused_confidence': float, # 综合置信度
                'signal_level': str,       # 信号等级 key
                'signal_label': str,       # 信号等级中文标签
                'signal_color': str,       # 信号等级颜色
                'components': {            # 各维度贡献
                    'chan': {'signal': ..., 'confidence': ..., 'weight': ..., 'contribution': ...},
                    'candlestick': {...},
                    'fund_flow': {...},
                    'volume': {...},
                },
                'conflicts': [...],        # 冲突记录
                'summary': str,            # 一句话总结
                'recommendation': str,     # 操作建议
            }
        """
        # 提取各维度信号
        chan_sig, chan_conf = self._extract_signal(chan_result, 'chan')
        candle_sig, candle_conf = self._extract_signal(candle_result, 'candlestick')
        fund_sig, fund_conf = self._extract_signal(fund_result, 'fund_flow')
        volume_sig, volume_conf = self._extract_signal(volume_result, 'volume')

        # 计算加权分数
        raw_score = (
            self.weights['chan'] * chan_sig +
            self.weights['candlestick'] * candle_sig +
            self.weights['fund_flow'] * fund_sig +
            self.weights['volume'] * volume_sig
        )

        # 计算综合置信度（各维度置信度的加权平均）
        raw_confidence = (
            self.weights['chan'] * chan_conf +
            self.weights['candlestick'] * candle_conf +
            self.weights['fund_flow'] * fund_conf +
            self.weights['volume'] * volume_conf
        )

        # 冲突检测
        conflicts = self._detect_conflicts(
            chan_sig, candle_sig, fund_sig, volume_sig
        )

        # 冲突解决
        fused_score = self._resolve_conflict(chan_sig, raw_score)

        # 如果冲突严重，降低置信度
        if len(conflicts) >= 2:
            raw_confidence *= 0.6
        elif len(conflicts) == 1:
            raw_confidence *= 0.8

        # 信号等级分类
        level = self._classify_signal(fused_score)

        # 构建各维度贡献详情
        components = {
            'chan': {
                'signal': round(chan_sig, 3),
                'confidence': round(chan_conf, 3),
                'weight': self.weights['chan'],
                'contribution': round(self.weights['chan'] * chan_sig, 3),
            },
            'candlestick': {
                'signal': round(candle_sig, 3),
                'confidence': round(candle_conf, 3),
                'weight': self.weights['candlestick'],
                'contribution': round(self.weights['candlestick'] * candle_sig, 3),
            },
            'fund_flow': {
                'signal': round(fund_sig, 3),
                'confidence': round(fund_conf, 3),
                'weight': self.weights['fund_flow'],
                'contribution': round(self.weights['fund_flow'] * fund_sig, 3),
            },
            'volume': {
                'signal': round(volume_sig, 3),
                'confidence': round(volume_conf, 3),
                'weight': self.weights['volume'],
                'contribution': round(self.weights['volume'] * volume_sig, 3),
            },
        }

        # 生成摘要和建议
        summary, recommendation = self._generate_advice(
            level, components, fused_score, raw_confidence
        )

        return {
            'fused_signal': round(fused_score, 4),
            'fused_confidence': round(raw_confidence, 4),
            'signal_level': level['level'],
            'signal_label': level['label'],
            'signal_color': level['color'],
            'raw_score': round(raw_score, 4),
            'components': components,
            'conflicts': conflicts,
            'summary': summary,
            'recommendation': recommendation,
        }

    def _detect_conflicts(self, chan_sig, candle_sig, fund_sig, volume_sig) -> list:
        """检测各维度信号冲突"""
        conflicts = []
        signals = {
            '缠论': chan_sig,
            'K线形态': candle_sig,
            '资金流向': fund_sig,
            '成交量': volume_sig,
        }

        names = list(signals.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                s1, s2 = signals[names[i]], signals[names[j]]
                # 方向相反且至少一方信号显著
                if abs(s1) > 0.2 and abs(s2) > 0.2 and np.sign(s1) != np.sign(s2):
                    conflicts.append({
                        'dim_a': names[i],
                        'dim_b': names[j],
                        'signal_a': round(s1, 3),
                        'signal_b': round(s2, 3),
                        'severity': 'high' if abs(s1) > 0.5 and abs(s2) > 0.5 else 'medium',
                    })

        return conflicts

    def _generate_advice(self, level, components, fused_score, confidence) -> tuple:
        """生成中文摘要和操作建议"""
        label = level['label']
        score_abs = abs(fused_score)
        conf_pct = int(confidence * 100)

        # 主信号方向
        directions = []
        for name, comp in [('缠论', components['chan']), ('K线', components['candlestick']),
                           ('资金', components['fund_flow']), ('量能', components['volume'])]:
            s = comp['signal']
            if s > 0.3:
                directions.append(f'{name}看多')
            elif s < -0.3:
                directions.append(f'{name}看空')
            elif abs(s) > 0.1:
                directions.append(f'{name}偏{"多" if s > 0 else "空"}')

        direction_text = '，'.join(directions) if directions else '各维度信号不明显'

        summary = f"综合信号: {label}（强度 {score_abs:.2f}，置信度 {conf_pct}%）。{direction_text}。"

        # 操作建议
        advice_map = {
            'strong_buy': '强烈看多信号，建议积极布局。可考虑分批建仓，设好止损保护。',
            'medium_buy': '偏多信号，可适度参与。建议小仓位试探，待信号加强后加仓。',
            'neutral': '信号不明确，建议观望等待。可轻仓持有现有头寸，不宜新开仓。',
            'medium_sell': '偏空信号，建议减仓或设好止盈。观察是否演变为强卖信号。',
            'strong_sell': '强烈看空信号，建议大幅减仓或清仓。不宜逆势操作。',
        }

        recommendation = advice_map.get(level['level'], '信号不明确，建议观望。')
        if conflicts := self._detect_conflicts(
            components['chan']['signal'],
            components['candlestick']['signal'],
            components['fund_flow']['signal'],
            components['volume']['signal']
        ):
            if conflicts:
                recommendation += ' 注意：各维度存在冲突信号，建议谨慎对待。'

        return summary, recommendation

    def set_weights(self, weights: dict):
        """动态调整权重"""
        for k in self.DEFAULT_WEIGHTS:
            if k in weights:
                self.weights[k] = weights[k]
        self._normalize_weights()
