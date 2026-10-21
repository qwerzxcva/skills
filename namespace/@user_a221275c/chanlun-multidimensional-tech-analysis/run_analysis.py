#!/usr/bin/env python3
"""
缠论多维技术分析 — 主运行器
用法: python run_analysis.py --symbol 000001 --name "平安银行" --start 2024-01-01 --end 2024-12-31
"""

import sys
import os
import json
import argparse
from datetime import datetime
import pandas as pd
import numpy as np

# 添加引擎路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.tdx_fetcher import TDXFetcher
from engine.chan_engine import ChanEngine
from engine.candlestick_recognizer import CandlestickRecognizer
from engine.fund_flow_analyzer import FundFlowAnalyzer
from engine.volume_analyzer import VolumeAnalyzer
from engine.volume_price_analyzer import VolumePriceAnalyzer
from engine.signal_fusion import SignalFusion
from engine.technical_indicators import TechnicalIndicators


class NumpyEncoder(json.JSONEncoder):
    """处理numpy/pandas类型的JSON序列化"""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, pd.Period)):
            return str(obj)
        if isinstance(obj, np.generic):
            return obj.item()
        return super().default(obj)


class ChanlunAnalyzer:
    """缠论多维技术分析主控制器"""

    def __init__(self, symbol: str, name: str = "", period: str = "daily"):
        self.symbol = symbol
        self.name = name
        self.period = period
        self.fetcher = TDXFetcher()
        self.chan = ChanEngine()
        self.candle = CandlestickRecognizer()
        self.fund = FundFlowAnalyzer()
        self.volume = VolumePriceAnalyzer()
        self.fusion = SignalFusion()
        self.ti = TechnicalIndicators()

    def run_from_pytdx(self, pytdx_series, output_dir: str = None) -> list:
        """
        一键执行: pytdx KLineSeries → 标准化 → 四维分析 → HTML
        优先使用 pytdx-api 获取数据。

        Args:
            pytdx_series: pytdx get_kline_data() 返回的 KLineSeries 对象
            output_dir: HTML输出目录

        Returns:
            生成的HTML文件路径列表
        """
        if pytdx_series is None or pytdx_series.count < 30:
            print(f"ERROR: pytdx数据不足，仅{pytdx_series.count if pytdx_series else 0}根K线")
            return []

        records = []
        for k in pytdx_series.klines:
            records.append({
                'date': k.datetime,
                'open': k.open,
                'high': k.high,
                'low': k.low,
                'close': k.close,
                'volume': int(k.volume),
            })

        # pytdx的klines是倒序（最新在前），需要的顺序是正序（最早在前）
        records.reverse()

        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

        if len(df) < 30:
            print(f"ERROR: 有效数据仅{len(df)}根K线")
            return []

        print(f"pytdx数据: {len(df)}根K线 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
        return self._run_and_generate_html(df, output_dir)

    def run_from_tdx_rows(self, tdx_rows: list, output_dir: str = None) -> list:
        """
        TDX MCP数据源（备用）：TDX原始数据 → 标准化 → 四维分析 → HTML
        优先使用 run_from_pytdx()，TDX MCP作为备用数据源。
        """
        records = []
        for r in tdx_rows:
            try:
                vol = float(r.get('Volume', 0) or r.get('VolInStock', 0) or 0)
            except (TypeError, ValueError):
                vol = 0.0
            if vol <= 0:
                continue
            try:
                records.append({
                    'date': str(r.get('Data', r.get('date', ''))),
                    'open': float(r.get('Open', r.get('open', 0))),
                    'high': float(r.get('High', r.get('high', 0))),
                    'low': float(r.get('Low', r.get('low', 0))),
                    'close': float(r.get('Close', r.get('close', 0))),
                    'volume': int(vol),
                })
            except (TypeError, ValueError):
                continue

        if len(records) < 30:
            print(f"ERROR: 有效数据仅{len(records)}根K线，至少需要30根")
            return []

        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d', errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

        print(f"TDX数据: {len(df)}根K线 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
        return self._run_and_generate_html(df, output_dir)

    def _run_and_generate_html(self, df: pd.DataFrame, output_dir: str = None) -> list:
        """共享的处理逻辑：标准化DataFrame → 四维分析 → 信号融合 → 生成HTML"""
        # 2. 执行分析
        result = self.run(df)
        if result.get('error'):
            print(f"ERROR: {result['error']}")
            return []

        # 3. 注入图表数据
        result['_df_dates'] = [str(d.date()) for d in df['date']]
        result['_df_ohlc'] = [[float(r['open']), float(r['close']), float(r['low']), float(r['high'])]
                               for _, r in df.iterrows()]
        result['_df_volumes'] = [int(v) for v in df['volume']]

        # 4. 生成HTML
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(__file__), 'output')
        os.makedirs(output_dir, exist_ok=True)

        date_str = datetime.now().strftime('%Y%m%d')
        analysis_path = os.path.join(output_dir, f'{self.symbol}_{date_str}_analysis.html')
        self.generate_html(result, analysis_path)

        html_files = [analysis_path]

        # 5. 打印核心结论
        fused = result['analysis']['fusion']
        print(f"\n=== {self.symbol} {self.name} 分析完成 ===")
        print(f"综合信号: {fused['signal_label']} ({fused['fused_signal']:+.3f}) 置信度={fused['fused_confidence']*100:.0f}%")
        print(f"建议: {fused['recommendation']}")
        print(f"HTML报告: {html_files}")

        return html_files

    def generate_html(self, result: dict, output_path: str, template_name: str = None, extra_repl: dict = None):
        """根据分析结果渲染标准分析报告（templates/report_template.html）。"""
        analysis = result.get('analysis', {})
        chan = analysis.get('chan', {}); candle = analysis.get('candlestick', {})
        fund = analysis.get('fund_flow', {}); vol = analysis.get('volume', {})
        fused = analysis.get('fusion', {}); ti_result = analysis.get('technical_indicators', {})

        # ---- 基础序列 ----
        dates = result.get('_df_dates') or []
        ohlc = result.get('_df_ohlc') or []
        volumes = result.get('_df_volumes') or []
        N = len(dates)
        closes = [round(float(o[1]), 4) for o in ohlc] if ohlc else []
        lows = [float(o[2]) for o in ohlc] if ohlc else []
        highs = [float(o[3]) for o in ohlc] if ohlc else []
        last_price = closes[-1] if closes else 0.0

        def _ma(arr, w):
            out = [None] * len(arr)
            for i in range(len(arr)):
                if i >= w - 1:
                    out[i] = round(sum(arr[i - w + 1:i + 1]) / w, 4)
            return out
        ma5 = _ma(closes, 5); ma10 = _ma(closes, 10); ma20 = _ma(closes, 20); ma60 = _ma(closes, 60)
        recent_high = max(highs[-60:]) if highs else None
        recent_low = min(lows[-60:]) if lows else None

        # ---- P2: 可视化叠加层数据（BOLL / MACD 金叉死叉 / KDJ·RSI 超买超卖阈值） ----
        ti_result = result.get('analysis', {}).get('technical_indicators', {}) or {}
        ti_macd = ti_result.get('macd', {}) or {}
        ti_kdj = ti_result.get('kdj', {}) or {}
        ti_rsi = ti_result.get('rsi', {}) or {}
        ti_boll = ti_result.get('boll', {}) or {}

        # BOLL 三线（已有序列，直接取）
        boll_upper = [round(float(x), 4) if x is not None else None for x in (ti_boll.get('upper') or [])]
        boll_mid = [round(float(x), 4) if x is not None else None for x in (ti_boll.get('mid') or [])]
        boll_lower = [round(float(x), 4) if x is not None else None for x in (ti_boll.get('lower') or [])]

        # MACD 金叉/死叉坐标（DIF 上穿/下穿 DEA）
        macd_cross = []
        mdif = ti_macd.get('dif') or []
        mdea = ti_macd.get('dea') or []
        mbar = ti_macd.get('macd_bar') or []
        for i in range(1, len(mdif)):
            if mdif[i - 1] is None or mdif[i] is None or mdea[i - 1] is None or mdea[i] is None:
                continue
            if mdif[i - 1] <= mdea[i - 1] and mdif[i] > mdea[i]:
                macd_cross.append({'idx': i, 'type': 'golden', 'price': closes[i] if i < len(closes) else None,
                                   'bar': round(float(mbar[i]), 4) if i < len(mbar) and mbar[i] is not None else None})
            elif mdif[i - 1] >= mdea[i - 1] and mdif[i] < mdea[i]:
                macd_cross.append({'idx': i, 'type': 'dead', 'price': closes[i] if i < len(closes) else None,
                                   'bar': round(float(mbar[i]), 4) if i < len(mbar) and mbar[i] is not None else None})

        # KDJ / RSI 超买超卖阈值（markArea 用）
        kdj_over = 80 if ti_kdj.get('overbought') else None
        kdj_under = 20 if ti_kdj.get('oversold') else None
        rsi_over = 70 if ti_rsi.get('overbought') else None
        rsi_under = 30 if ti_rsi.get('oversold') else None

        def _col(sig):
            try:
                sig = float(sig)
            except (TypeError, ValueError):
                return '#999999'
            if sig > 0.05: return '#e74c3c'
            if sig < -0.05: return '#27ae60'
            return '#999999'

        # ---- 关键价位 ----
        supports = [recent_low] if recent_low is not None else []
        resistances = [recent_high] if recent_high is not None else []
        pivots = chan.get('details', {}).get('pivots', [])
        if pivots:
            p = pivots[-1]
            if p.get('zd') is not None: supports.append(p['zd'])
            if p.get('zg') is not None: resistances.append(p['zg'])

        # ---- 诊断 / 结论 / 方法论 ----
        diagnosis = self._build_diagnosis(chan, candle, fund, vol, fused, [],
                                           last_price, recent_high, recent_low,
                                           supports, resistances, closes=closes, df_volumes=volumes, N=N)
        final_conclusion = self._build_final_conclusion(chan, candle, fund, vol, fused, ti_result,
                                                        last_price, recent_high, recent_low,
                                                        supports, resistances, dates, closes, N)
        methodology_html = self._build_methodology(result, diagnosis, final_conclusion)

        # ---- 结论速览（结论版默认常驻） ----
        plain_conclusion = self._build_plain_conclusion(fused, final_conclusion, diagnosis,
                                                        last_price, supports, resistances)
        glossary_items = self._dynamic_glossary(
            chan=chan, ti=ti_result, fused=fused,
            final_conclusion=final_conclusion, last_price=last_price,
            supports=supports, resistances=resistances, diagnosis=diagnosis)
        conclusion_overview_html = self._render_conclusion_overview_html(plain_conclusion, glossary_items)
        quant_advice_html = self._render_quant_advice_html(final_conclusion, chan,
                                                           supports, resistances, last_price)
        # ---- 单指标深度解析 + 多指标共振矩阵（P0-4 / P0-5） ----
        indicator_deep_html = self._build_indicator_deep_conclusions(ti_result)
        resonance_matrix_html = self._build_resonance_matrix(ti_result, chan, fused)
        # ---- 多级别联动（日线↔周线，P1） ----
        ti_weekly = result.get('analysis', {}).get('technical_indicators_weekly')
        dual_level_html = self._build_dual_level_html(ti_result, ti_weekly)

        # ---- 近30日形态 ----
        pats = candle.get('patterns', [])
        recent = [p for p in pats if isinstance(p.get('index'), int) and p['index'] >= max(0, N - 30)]
        recent_patterns = []
        _multi2 = {'看涨吞没', '看跌吞没', '孕线', '刺透形态', '乌云盖顶'}
        _multi3 = {'早晨之星', '黄昏之星', '三只乌鸦', '三白兵'}
        for p in recent[:40]:
            idx = p.get('index', -1)
            try:
                _strength = round(float(p.get('strength') or 0), 3)
            except (TypeError, ValueError):
                _strength = None
            entry = {
                'date_str': str(p.get('date', ''))[:10],
                'name': p.get('name', ''),
                'type': p.get('type', ''),
                'desc': '',
                'index': idx,
                'strength': _strength,
            }
            # 回查 OHLC（ECharts candlestick 顺序: open, close, low, high），多K线形态取连续2-3根
            _ohlcs = []
            if isinstance(idx, int) and 0 <= idx < len(ohlc):
                _ohlcs = [ohlc[idx]]
                if p.get('name') in _multi2 and idx > 0:
                    _ohlcs.insert(0, ohlc[idx - 1])
                if p.get('name') in _multi3 and idx > 1:
                    _ohlcs.insert(0, ohlc[idx - 2])
            entry['ohlc'] = _ohlcs
            recent_patterns.append(entry)
        recent_count = len(recent_patterns)
        recent_bull = sum(1 for p in recent_patterns if p['type'] == 'bullish')
        recent_bear = sum(1 for p in recent_patterns if p['type'] == 'bearish')

        # ---- 图表 JSON ----
        cd = chan.get('details', {})
        chan_data = {
            'strokes': [{'start_idx': s.get('start'), 'end_idx': s.get('end'),
                         'start_price': s.get('start_price'), 'end_price': s.get('end_price')}
                        for s in cd.get('strokes', [])],
            'pivots': [{'start_idx': p.get('start_idx'), 'end_idx': p.get('end_idx'),
                        'zd': p.get('zd'), 'zg': p.get('zg')} for p in cd.get('pivots', [])],
            'trading_points': [{'type': t.get('type'), 'index': t.get('index'),
                                'price': t.get('price'), 'label': t.get('label') or t.get('type')}
                               for t in cd.get('trading_points', [])],
        }
        candle_data = {'patterns': pats[:60], 'markers': candle.get('markers', [])}
        fund_data = fund.get('details', {})
        vd = vol.get('details', {})
        vol_rel_map = {'bullish': '量价齐升(看多)', 'bearish': '量价背离(看空)', 'neutral': '无明显特征'}
        volume_data = {
            'vol_relation_5d': vol_rel_map.get(vd.get('volume_price_relation', 'neutral'), '无明显特征'),
            'vol_trend': vd.get('recent_trend', '平稳'),
            'vol_events': [], 'vol_analysis': ''
        }
        levels_data = {
            'supports': [round(float(x), 4) for x in supports if x is not None],
            'resistances': [round(float(x), 4) for x in resistances if x is not None],
            'ma20': ma20, 'ma60': ma60,
            'recent_high': round(float(recent_high), 4) if recent_high is not None else None,
            'recent_low': round(float(recent_low), 4) if recent_low is not None else None,
        }
        trend = cd.get('trend', 'sideways')
        trend_cn = {'up': '上升趋势', 'down': '下降趋势', 'sideways': '震荡走势'}.get(trend, '震荡走势')
        kline_analysis = {
            'trend': trend_cn,
            'position': f"当前价 {last_price:.3f}，位于中枢区间",
            'recent_action': f"近期缠论笔 {len(cd.get('strokes', []))} 笔 / 中枢 {len(cd.get('pivots', []))} 个",
            'support_text': f"{supports[0]:.3f}" if supports else '待观察',
            'resistance_text': f"{resistances[0]:.3f}" if resistances else '',
            'analysis': ''
        }

        # ---- 信号数值解读 ----
        comps = fused.get('components', {})
        name_map = {'chan': '缠论', 'candlestick': 'K线形态', 'fund_flow': '资金流向', 'volume': '量价配合'}
        interp_items = []; calc_parts = []
        for kk, c in comps.items():
            sig = c.get('signal', 0); w = c.get('weight', 0); contrib = c.get('contribution', 0)
            direction = '看多' if sig > 0.1 else ('看空' if sig < -0.1 else '中性')
            interp_items.append({'name': name_map.get(kk, kk), 'signal': round(float(sig), 3),
                                 'meaning': direction, 'contribution': f"{contrib:+.3f} (权重{int(w*100)}%)"})
            calc_parts.append(f"{name_map.get(kk, kk)}({sig:+.3f}×{int(w*100)}%)")
        calculation = ' + '.join(calc_parts) + f" = {fused.get('fused_signal', 0):+.3f}"
        cs = fused.get('confidence_score', {})
        fused_sig = fused.get('fused_signal', 0)
        gauge_table = [
            {'range': '-1.0 ~ -0.6', 'label': '极强空头', 'desc': '强烈卖出信号，趋势明确向下', 'is_active': fused_sig <= -0.6},
            {'range': '-0.6 ~ -0.2', 'label': '空头', 'desc': '偏空，注意下行风险', 'is_active': -0.6 < fused_sig <= -0.2},
            {'range': '-0.2 ~ 0.2', 'label': '中性/震荡', 'desc': '方向不明，观望为主', 'is_active': -0.2 < fused_sig <= 0.2},
            {'range': '0.2 ~ 0.6', 'label': '多头', 'desc': '偏多，关注上行机会', 'is_active': 0.2 < fused_sig <= 0.6},
            {'range': '0.6 ~ 1.0', 'label': '极强多头', 'desc': '强烈买入信号，趋势明确向上', 'is_active': fused_sig > 0.6},
        ]
        interpretation = {'items': interp_items, 'calculation': calculation,
                          'confidence_explain': cs.get('explanation', ''),
                          'gauge_table': gauge_table, 'fused_signal': fused.get('signal_label', '')}

        ti_payload = dict(ti_result)
        ti_payload['confidence'] = ti_result.get('confidence_score', {})
        report_data = {
            'dates': dates, 'ohlc': ohlc, 'volumes': volumes,
            'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
            'boll_upper': boll_upper, 'boll_mid': boll_mid, 'boll_lower': boll_lower,
            'macd_cross': macd_cross,
            'kdj_over': kdj_over, 'kdj_under': kdj_under,
            'rsi_over': rsi_over, 'rsi_under': rsi_under,
            'ti': ti_payload, 'final_conclusion': final_conclusion,
            'interpretation': interpretation, 'components': comps,
            'conflicts': fused.get('conflicts', []), 'diagnosis': diagnosis,
        }

        # ---- 标量字段 ----
        fused_label = fused.get('signal_label', '')
        fused_color = fused.get('signal_color', '#999999')
        conf_pct = round(fused.get('fused_confidence', 0) * 100)
        summ = result.get('summary', {})
        start_date = summ.get('start_date', ''); end_date = summ.get('end_date', '')
        period = result.get('period', '日线')
        gen_time = datetime.now().strftime('%Y-%m-%d %H:%M')

        chan_trend_cn = {'up': '上涨', 'down': '下跌', 'sideways': '震荡'}.get(trend, '震荡')
        chan_summary = f"共 {len(cd.get('strokes', []))} 笔 / {len(cd.get('pivots', []))} 中枢"
        fund_d = fund.get('details', {})
        fund_trend_cn = {'inflow': '流入', 'outflow': '流出', 'balanced': '平衡'}.get(fund_d.get('trend', 'balanced'), '平衡')
        fund_intensity = fund_d.get('intensity', 0)
        vol_rel_cn = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性'}.get(vd.get('volume_price_relation', 'neutral'), '中性')
        vol_ratio = vd.get('volume_ratio', 0)

        recent_detail = ''.join(
            f"<div class='pattern-item {p['type']}'><span class='p-name'>{p['name']}（{'看多' if p['type']=='bullish' else '看空'}）</span> <span class='p-date'>{p['date_str']}</span></div>"
            for p in recent_patterns[:12]) or '近30日未识别到明确形态'
        recommendation = fused.get('recommendation', '')
        summary_text = fused.get('summary', '')

        repl = {
            '{{SYMBOL}}': result.get('symbol', ''), '{{NAME}}': result.get('name', ''),
            '{{START_DATE}}': start_date, '{{END_DATE}}': end_date, '{{PERIOD}}': period,
            '{{GEN_TIME}}': gen_time,
            '{{SIGNAL_LABEL}}': fused_label, '{{FUSED_SIGNAL}}': f"{fused_sig:+.3f}",
            '{{SIGNAL_COLOR}}': fused_color, '{{CONFIDENCE}}': str(conf_pct),
            '{{FUSED_SIGNAL_RAW}}': f"{fused_sig:.3f}",
            '{{CHAN_TREND}}': chan_trend_cn, '{{CHAN_SUMMARY}}': chan_summary,
            '{{CHAN_COLOR}}': _col(chan.get('signal', 0)),
            '{{RECENT_PATTERN_COUNT}}': str(recent_count),
            '{{RECENT_BULLISH}}': str(recent_bull), '{{RECENT_BEARISH}}': str(recent_bear),
            '{{FUND_TREND}}': fund_trend_cn, '{{FUND_INTENSITY}}': f"{float(fund_intensity):.2f}",
            '{{FUND_COLOR}}': _col(fund.get('signal', 0)),
            '{{VOL_RELATION}}': vol_rel_cn, '{{VOL_RATIO}}': f"{float(vol_ratio):.2f}",
            '{{VOL_COLOR}}': _col(vol.get('signal', 0)),
            '{{RECENT_PATTERN_DETAIL}}': recent_detail,
            '{{RECOMMENDATION}}': recommendation, '{{SUMMARY}}': summary_text,
            '{{METHODOLOGY_HTML}}': methodology_html,
            '{{CONCLUSION_OVERVIEW_HTML}}': conclusion_overview_html,
            '{{QUANT_ADVICE_HTML}}': quant_advice_html,
            '{{INDICATOR_DEEP_HTML}}': indicator_deep_html,
            '{{RESONANCE_MATRIX_HTML}}': resonance_matrix_html,
            '{{DUAL_LEVEL_HTML}}': dual_level_html,
            '{{REPORT_DATA_JSON}}': json.dumps(report_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{CHAN_DATA_JSON}}': json.dumps(chan_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{CANDLE_DATA_JSON}}': json.dumps(candle_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{FUND_DATA_JSON}}': json.dumps(fund_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{VOLUME_DATA_JSON}}': json.dumps(volume_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{LEVELS_DATA_JSON}}': json.dumps(levels_data, ensure_ascii=False, cls=NumpyEncoder),
            '{{RECENT_PATTERNS_JSON}}': json.dumps(recent_patterns, ensure_ascii=False, cls=NumpyEncoder),
            '{{KLINE_ANALYSIS_JSON}}': json.dumps(kline_analysis, ensure_ascii=False, cls=NumpyEncoder),
        }

        tpl_name = template_name or 'report_template.html'
        tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', tpl_name)
        html = open(tpl_path, encoding='utf-8').read()
        if extra_repl:
            repl.update(extra_repl)
        for k, v in repl.items():
            html = html.replace(k, str(v))

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path

    def run(self, df: pd.DataFrame, weekly_df: pd.DataFrame = None) -> dict:
        """
        执行完整分析流程

        Args:
            df: 日线 OHLCV DataFrame
            weekly_df: 周线 OHLCV DataFrame（可选，P1 双级别）。周线仅作方向判定/展示增强，
                       融合权重仍只基于日线，不改变「缠论为锚、指标为辅」的融合算法。

        Returns:
            完整的分析结果字典，可直接JSON化
        """
        # 验证和预处理
        if not self.fetcher.validate_df(df):
            return {'error': '数据不足，至少需要30根K线'}

        # 确保日期列为datetime类型
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        df = self.fetcher.add_indicators(df)

        summary = self.fetcher.get_summary(df)

        # ---- 四维分析 ----
        chan_result = self.chan.analyze(df)
        candle_result = self.candle.recognize(df)
        fund_result = self.fund.analyze(df)
        volume_result = self.volume.analyze(df)

        # ---- 信号融合 ----
        fused = self.fusion.fuse(chan_result, candle_result, fund_result, volume_result)

        # ---- 技术指标分析 (MACD/KDJ/RSI + 背离 + 共振) ----
        ti_result = self.ti.analyze(df, chan_signal=chan_result.get('signal', 0))

        # ---- P1: 周线技术指标（方向判定增强，纯展示层） ----
        ti_weekly = None
        if weekly_df is not None and self.fetcher.validate_df(weekly_df):
            wdf = weekly_df.copy()
            if 'date' in wdf.columns:
                wdf['date'] = pd.to_datetime(wdf['date'], errors='coerce')
            wdf = self.fetcher.add_indicators(wdf)
            ti_weekly = self.ti.analyze(wdf, chan_signal=0)

        # ---- 综合信心打分 (融合四维置信度 + 技术指标信心) ----
        fused_conf = fused.get('fused_confidence', 0.5)
        ti_score = ti_result['confidence_score']['score'] / 10.0  # 归一化到0-1
        combined_conf = 0.6 * fused_conf + 0.4 * ti_score
        fused['fused_confidence'] = combined_conf
        fused['confidence_score'] = ti_result['confidence_score']
        fused['ti_signal'] = ti_result['signal']

        # ---- 构建完整结果 ----
        result = {
            'symbol': self.symbol,
            'name': self.name,
            'period': self.period,
            'summary': summary,
            'analysis': {
                'chan': chan_result,
                'candlestick': candle_result,
                'fund_flow': fund_result,
                'volume': volume_result,
                'fusion': fused,
                'technical_indicators': ti_result,
                'technical_indicators_weekly': ti_weekly,
            },
            'generated_at': datetime.now().isoformat(),
        }

        return result

    def _build_diagnosis(self, chan, candle, fund, vol, fused,
                         recent_patterns, last_price, recent_high, recent_low,
                         supports, resistances, closes=None, df_volumes=None, N=0) -> dict:
        """构建综合分析诊断（含数值意义解读）"""
        chan_detail = chan['details']
        fund_detail = fund['details']
        vol_detail = vol['details']
        trend = chan_detail.get('trend', 'sideways')
        pivots = chan_detail.get('pivots', [])
        
        # 计算价格变动数据
        change_from_high = (1 - last_price / recent_high) * 100 if recent_high else 0
        change_from_low = (last_price / recent_low - 1) * 100 if recent_low else 0
        
        # 缠论诊断（含数值）
        if trend == 'up' and pivots:
            last_pivot = pivots[-1]
            diag_chan = f'<span class="bull">多头趋势</span>，中枢区间{last_pivot["zd"]:.4f}~{last_pivot["zg"]:.4f}不断上移。'
            tp = chan_detail.get('trading_points', [])
            if tp: 
                diag_chan += f' 近期出现{tp[-1].get("label",tp[-1].get("type",""))} @ {tp[-1].get("price",0):.4f}。'
            else:
                diag_chan += ' 暂无明确买卖点，需等待回调确认。'
        elif trend == 'down':
            diag_chan = f'<span class="bear">空头趋势</span>，价格在中枢下方运行。'
            if pivots:
                last_pivot = pivots[-1]
                diag_chan += f' 跌破最后中枢({last_pivot["zd"]:.4f}~{last_pivot["zg"]:.4f})，距中枢上沿{last_pivot["zg"]:.4f}还有{(last_pivot["zg"]/last_price-1)*100:.1f}%空间。'
            else:
                diag_chan += f' 当前价格{last_price:.4f}，距近期低点{recent_low:.4f}已反弹{change_from_low:.1f}%。'
        else:
            diag_chan = f'<span>震荡走势</span>，方向不明。'
            if pivots:
                last_pivot = pivots[-1]
                range_pct = (last_pivot['zg'] - last_pivot['zd']) / last_pivot['zd'] * 100 if last_pivot['zd'] else 0
                diag_chan += f' 当前在最后中枢({last_pivot["zd"]:.4f}~{last_pivot["zg"]:.4f})附近，中枢宽度{range_pct:.1f}%。'
                if last_pivot['zg'] > last_price > last_pivot['zd']:
                    diag_chan += f' 价格处于中枢内部，偏中性。'
                elif last_price > last_pivot['zg']:
                    diag_chan += f' 价格突破中枢上沿，偏多。'
                else:
                    diag_chan += f' 价格跌破中枢下沿，偏空。'

        # 量价评估（含数值）
        vol_ratio = vol_detail.get('volume_ratio', 1.0)
        vol_rel_key = vol_detail.get('volume_price_relation', 'neutral')
        if vol_rel_key == 'bullish':
            diag_vol = f'<span class="bull">量价配合健康</span>，当前量比{vol_ratio:.2f}。'
        elif vol_rel_key == 'bearish':
            diag_vol = f'<span class="bear">量价背离</span>，当前量比{vol_ratio:.2f}。'
        else:
            diag_vol = f'<span>量价中性</span>，当前量比{vol_ratio:.2f}。'

        if vol_detail.get('extreme_points'):
            ep = vol_detail.get('extreme_points', [])
            diag_vol += f' 出现{len(ep)}个极端量能信号（{"/".join([e.get("label","") for e in ep[:3]])}）。'
        
        # 加上量能趋势解读
        if N >= 6 and df_volumes:
            v5 = sum(df_volumes[-5:]) / 5
            v20 = sum(df_volumes[-20:]) / 20 if N >= 20 else v5
            ratio = v5 / max(v20, 1)
            if ratio > 1.5:
                diag_vol += f' 近5日量能{ratio:.1f}x于20日均量，资金活跃。'
            elif ratio < 0.6:
                diag_vol += f' 近5日量能萎缩至{ratio:.1f}x于20日均量，市场清淡。'
            else:
                diag_vol += f' 近5日量能{ratio:.1f}x于20日均量，量能平稳。'

        # 资金判断（含数值）
        fund_t = fund_detail.get('trend', 'balanced')
        fund_intensity = fund_detail.get('intensity', 0)
        fund_5d = fund_detail.get('net_inflow_5d', 0)
        fund_20d = fund_detail.get('net_inflow_20d', 0)
        
        if fund_t == 'inflow':
            diag_fund = f'<span class="bull">资金流入</span>，主力态度偏多。'
        elif fund_t == 'outflow':
            diag_fund = f'<span class="bear">资金流出</span>，主力态度偏空。'
        else:
            diag_fund = f'<span>资金平衡</span>，主力未明确表态。'
        
        diag_fund += f' 资金强度指标{fund_intensity:.3f}。'
        if fund_5d != 0 or fund_20d != 0:
            diag_fund += f' 5日净流入{fund_5d:+.0f}，20日净流入{fund_20d:+.0f}。'

        if fund_detail.get('divergence'):
            diag_fund += ' <span class="highlight">价格与资金背离</span>——价格方向与资金方向不一致，需警惕。'

        # 风险提示（含数值）
        risks = []
        if trend == 'down':
            risks.append(f'下跌趋势未反转，距近期高点已回落{change_from_high:.1f}%')
        if fused['fused_confidence'] < 0.5:
            risks.append(f'多维度信号矛盾，置信度仅{fused["fused_confidence"]*100:.0f}%')
        if recent_high and last_price < recent_high * 0.85:
            risks.append(f'距近期高点{recent_high:.4f}已回落{change_from_high:.1f}%，处于弱势区间')
        if recent_low and last_price > recent_low * 1.15:
            risks.append(f'距近期低点{recent_low:.4f}已反弹{change_from_low:.1f}%，追高风险')

        recent30_bullish = sum(1 for p in recent_patterns if p['type'] == 'bullish')
        recent30_bearish = len(recent_patterns) - recent30_bullish
        if recent30_bearish > recent30_bullish * 2 and len(recent_patterns) >= 3:
            risks.append(f'近30日看空形态{recent30_bearish}个远多于看多{recent30_bullish}个')

        diag_risk = '；'.join(risks) if risks else '当前未见显著风险信号'

        # 策略参考（含数值）
        signal_label = fused['signal_label']
        signal_val = fused['fused_signal']
        conf = fused['fused_confidence'] * 100
        
        if signal_label == '观望':
            diag_strategy = f"信号<strong>{signal_val:+.3f}</strong>（置信度{conf:.0f}%），观望为主。"
            if supports:
                diag_strategy += f" 支撑位{'/'.join([f'{s:.4f}' for s in supports])}附近若放量突破可小仓位试探；"
            if resistances:
                diag_strategy += f" 阻力位{'/'.join([f'{r:.4f}' for r in resistances])}附近若无量突破则减仓。"
        elif '买' in signal_label:
            diag_strategy = f"信号<strong>{signal_val:+.3f}</strong>（置信度{conf:.0f}%{signal_label}），偏多操作。"
            if supports:
                diag_strategy += f" 可分批建仓，止损设在{min(supports):.4f}下方3%（约{min(supports)*0.97:.4f}）。"
            if resistances:
                diag_strategy += f" 第一目标位{resistances[0]:.4f}，第二目标位{resistances[-1]:.4f}。"
        elif '卖' in signal_label:
            diag_strategy = f"信号<strong>{signal_val:+.3f}</strong>（置信度{conf:.0f}%{signal_label}），偏空操作。"
            if supports:
                diag_strategy += f" 建议减仓或设止盈。支撑位{'/'.join([f'{s:.4f}' for s in supports])}若有效跌破则进一步减仓。"

        return {
            'chan': diag_chan,
            'vol': diag_vol,
            'fund': diag_fund,
            'risk': diag_risk,
            'strategy': diag_strategy,
        }

    def _build_final_conclusion(self, chan, candle, fund, vol, fused, ti_result,
                                last_price, recent_high, recent_low,
                                supports, resistances, dates, closes, N=0) -> dict:
        """构建最终趋势结论（5维度：趋势方向/关键价位/操作建议/风险边界/周期视角）

        基于四维信号 + 技术指标共振 + 信心打分，输出结构化交易决策建议。
        严格区分确定结构与概率推演，不给保本保收益承诺。
        """
        signal_val = fused['fused_signal']
        signal_label = fused['signal_label']
        conf = fused['fused_confidence']
        ti = ti_result
        ti_conf = ti.get('confidence_score', {})
        ti_score = ti_conf.get('score', 0)
        res = ti.get('resonance', {})

        # ===== 1. 趋势方向 =====
        chan_detail = chan.get('details', {})
        trend = chan_detail.get('trend', 'sideways')
        pivots = chan_detail.get('pivots', [])
        trading_points = chan_detail.get('trading_points', [])

        trend_map = {'up': '多头', 'down': '空头', 'sideways': '震荡'}
        trend_dir = trend_map.get(trend, '震荡')

        # 综合方向判断
        if signal_val > 0.3:
            overall_dir = '偏多'
        elif signal_val > 0.1:
            overall_dir = '温和偏多'
        elif signal_val < -0.3:
            overall_dir = '偏空'
        elif signal_val < -0.1:
            overall_dir = '温和偏空'
        else:
            overall_dir = '方向不明'

        # 中枢位置
        pivot_desc = ''
        if pivots:
            last_pivot = pivots[-1]
            zd, zg = last_pivot['zd'], last_pivot['zg']
            if last_price > zg:
                pivot_desc = f'价格在中枢({zd:.4f}~{zg:.4f})上方运行'
            elif last_price < zd:
                pivot_desc = f'价格在中枢({zd:.4f}~{zg:.4f})下方运行'
            else:
                pivot_desc = f'价格在中枢({zd:.4f}~{zg:.4f})内部'

        # 买卖点
        tp_desc = ''
        if trading_points:
            last_tp = trading_points[-1]
            tp_label = last_tp.get('label', last_tp.get('type', ''))
            tp_price = last_tp.get('price', 0)
            tp_desc = f'，最近{tp_label}@{tp_price:.4f}'

        trend_conclusion = f'缠论结构{trend_dir}，{pivot_desc}{tp_desc}。综合信号{signal_val:+.3f}（{overall_dir}）。'

        # 技术指标共振补充
        res_align = res.get('alignment', 'neutral')
        align_map = {'strong_bullish': '强多头共振', 'bullish': '多头共振',
                     'strong_bearish': '强空头共振', 'bearish': '空头共振', 'neutral': '方向分歧'}
        trend_conclusion += f'技术指标{align_map.get(res_align, "中性")}（{res.get("bull_count", 0)}多/{res.get("bear_count", 0)}空）。'

        # ===== 2. 关键价位 =====
        key_levels = []
        key_levels.append(f'当前价 {last_price:.4f}')

        if supports:
            nearest_support = max(s for s in supports if s < last_price) if any(s < last_price for s in supports) else (supports[0] if supports else None)
            if nearest_support:
                dist = (last_price / nearest_support - 1) * 100
                key_levels.append(f'第一支撑 {nearest_support:.4f}（距当前{dist:+.1f}%）')
            if len(supports) > 1:
                key_levels.append(f'第二支撑 {supports[0]:.4f}')

        if resistances:
            nearest_resist = min(r for r in resistances if r > last_price) if any(r > last_price for r in resistances) else (resistances[0] if resistances else None)
            if nearest_resist:
                dist = (nearest_resist / last_price - 1) * 100
                key_levels.append(f'第一阻力 {nearest_resist:.4f}（距当前{dist:+.1f}%）')
            if len(resistances) > 1:
                key_levels.append(f'第二阻力 {resistances[-1]:.4f}')

        # 止损位
        if '买' in signal_label and supports:
            stop_loss = min(supports) * 0.97
            key_levels.append(f'止损位 {stop_loss:.4f}（支撑下方3%）')

        # 目标位
        if '买' in signal_label and resistances:
            key_levels.append(f'目标位 {resistances[0]:.4f}')

        # ===== 2b. 方向性止损位 / 失效位（量化操作建议卡直接读取） =====
        stop_loss = None          # 建议止损价（含缓冲）
        invalidation = None       # 结构失效价（关键结构位）
        if signal_val >= 0.1:     # 偏多：止损看支撑下方
            if supports:
                below = [s for s in supports if s < last_price]
                base = max(below) if below else min(supports)
                stop_loss = base * 0.97
                invalidation = min(supports)
        elif signal_val <= -0.1:  # 偏空：止损看阻力上方
            if resistances:
                above = [r for r in resistances if r > last_price]
                base = min(above) if above else max(resistances)
                stop_loss = base * 1.03
                invalidation = max(resistances)
        else:                     # 中性震荡：以下沿为失效参考
            if supports:
                stop_loss = min(supports) * 0.97
                invalidation = min(supports)

        # ===== 3. 操作建议 =====
        # 仓位建议 (0-100%)
        if signal_val > 0.5 and conf > 0.6:
            position = '60-80%'
            action = '积极建仓'
        elif signal_val > 0.2 and conf > 0.4:
            position = '40-60%'
            action = '分批建仓'
        elif signal_val > 0.1:
            position = '20-30%'
            action = '小仓位试探'
        elif signal_val < -0.5 and conf > 0.6:
            position = '0-20%'
            action = '大幅减仓'
        elif signal_val < -0.2:
            position = '20-40%'
            action = '减仓观望'
        elif signal_val < -0.1:
            position = '40-60%'
            action = '谨慎持有'
        else:
            position = '30-50%'
            action = '观望为主'

        # 信心打分修正
        if ti_score < 3:
            position = '降低至' + position.split('-')[0] + '-' + str(int(position.split('-')[1].rstrip('%')) - 20 if '-' in position else '20') + '%' if '-' in position else position
            action += '（技术指标信心不足，建议降低仓位）'

        operation = f'{action}，建议仓位{position}。信心打分{ti_score:.1f}/10。'

        # 结构化仓位百分比（技能卡直接读取，避免脆弱文本切片解析）
        import re as _re_pos
        _m = _re_pos.search(r'(\d+)\s*-\s*(\d+)', position)
        position_pct = round((int(_m.group(1)) + int(_m.group(2))) / 2) if _m else 50

        # ===== 4. 风险边界 =====
        risks = []

        # 信号冲突风险
        conflicts = fused.get('conflicts', [])
        if conflicts:
            risks.append('四维信号存在冲突')

        # 背离风险
        top_div = res.get('top_divergences', 0)
        bot_div = res.get('bottom_divergences', 0)
        if top_div > 0 and signal_val > 0:
            risks.append(f'检测到{top_div}个顶背离，多头信号需警惕反转')
        if bot_div > 0 and signal_val < 0:
            risks.append(f'检测到{bot_div}个底背离，空头信号需警惕反弹')

        # 超买超卖风险
        kdj = ti.get('kdj', {})
        rsi = ti.get('rsi', {})
        if kdj.get('overbought'):
            risks.append('KDJ超买，短期有回调压力')
        if rsi.get('overbought'):
            risks.append('RSI超买，追高风险增加')
        if kdj.get('oversold'):
            risks.append('KDJ超卖，可能技术性反弹')
        if rsi.get('oversold'):
            risks.append('RSI超卖，杀跌动能减弱')

        # 推翻条件
        if '买' in signal_label:
            if supports:
                risks.append(f'若有效跌破{min(supports):.4f}（支撑位），则多头判断失效')
        elif '卖' in signal_label:
            if resistances:
                risks.append(f'若放量突破{min(resistances):.4f}（阻力位）并站稳3日，则空头判断失效')

        risk_boundary = '；'.join(risks) if risks else '当前未见显著风险信号'

        # ===== 5. 周期视角 =====
        # 短期 (5-10日): 看KDJ/RSI
        short_view = ''
        if kdj.get('overbought') or rsi.get('overbought'):
            short_view = '短期超买，有技术性回调需求'
        elif kdj.get('oversold') or rsi.get('oversold'):
            short_view = '短期超卖，关注技术性反弹'
        else:
            macd = ti.get('macd', {})
            if macd.get('direction') == 'bullish':
                short_view = '短期偏多，动能尚可'
            elif macd.get('direction') == 'bearish':
                short_view = '短期偏空，动能不足'
            else:
                short_view = '短期中性，方向不明'

        # 中期 (20-60日): 看缠论趋势 + 均线
        mid_view = ''
        if trend == 'up':
            mid_view = '中期多头结构，中枢上移'
        elif trend == 'down':
            mid_view = '中期空头结构，中枢下移'
        else:
            mid_view = '中期震荡，中枢未明确突破'

        # 距前高前低
        if recent_high and recent_high > last_price:
            from_high = (1 - last_price / recent_high) * 100
            mid_view += f'，距前高{recent_high:.4f}回落{from_high:.1f}%'
        if recent_low and recent_low < last_price:
            from_low = (last_price / recent_low - 1) * 100
            mid_view += f'，距前低{recent_low:.4f}反弹{from_low:.1f}%'

        cycle_view = f'短期(5-10日)：{short_view}。中期(20-60日)：{mid_view}。'

        return {
            'trend_direction': trend_conclusion,
            'key_levels': key_levels,
            'operation': operation,
            'position_pct': position_pct,
            'risk_boundary': risk_boundary,
            'cycle_view': cycle_view,
            'confidence_score': ti_score,
            'signal_value': signal_val,
            'signal_label': signal_label,
            'stop_loss': stop_loss,
            'invalidation': invalidation,
        }

    # ========== 结论速览（结论版专用：面向非专业用户） ==========
    def _build_plain_conclusion(self, fused, final_conclusion, diagnosis, last_price, supports, resistances) -> dict:
        """面向非专业用户的『结论速览』结构化数据：五档 verdict + 3 条人话理由 + 关键价位 + 仓位概率区间。

        设计来源：grilling 访谈 6 节点（术语+人话双行、图表默认折叠、仓位区间+概率标注）。
        v2 升级：四档 → 五档（强烈看多/看多/中性观望/看空/强烈看空），颜色遵循 A股涨红跌绿。
        映射规则见 references/plain_language.md。
        """
        import re
        fused_sig = fused.get('fused_signal', 0)

        # 1) 五档 verdict（缠论为锚、指标为辅的融合信号 fused_signal 分档）
        if fused_sig > 0.5:
            verdict, vcolor = '强烈看多', '#c0392b'
        elif fused_sig > 0.2:
            verdict, vcolor = '看多', '#e74c3c'
        elif fused_sig < -0.5:
            verdict, vcolor = '强烈看空', '#1e8449'
        elif fused_sig < -0.2:
            verdict, vcolor = '看空', '#27ae60'
        else:
            verdict, vcolor = '中性观望', '#888'

        if verdict == '强烈看多':
            verdict_reason = '多维度信号强烈共振偏多，趋势较明确，可逢低积极关注但避免追涨。'
        elif verdict == '看多':
            verdict_reason = '多个维度信号一致偏多，更适合逢低关注而非追高。'
        elif verdict == '强烈看空':
            verdict_reason = '多维度信号强烈共振偏空，下行风险较大，宜控制仓位、规避为主。'
        elif verdict == '看空':
            verdict_reason = '多个维度信号一致偏空，更适合控制仓位、谨慎为主。'
        else:
            verdict_reason = '各维度信号相互抵消或偏温和，方向暂不明朗，建议先观察、等信号更清晰。'

        # 2) 3 条人话理由（取诊断原文、去 HTML 标签、截断）
        def _strip(html):
            return re.sub(r'<[^>]+>', '', html or '').strip()
        reasons = []
        for key, label in (('chan', '走势'), ('fund', '资金'), ('vol', '量价')):
            txt = _strip(diagnosis.get(key, ''))
            if txt:
                reasons.append(f'{label}：{txt[:64]}')
        while len(reasons) < 3:
            reasons.append('暂无更多维度信号。')
        reasons = reasons[:3]

        # 3) 关键价位（人话）
        key_levels = final_conclusion.get('key_levels', [])
        key_text = '；'.join(key_levels) if key_levels else f'当前价 {last_price:.3f}'

        # 4) 仓位概率区间（区间 + 概率标注，呼应角色声明）
        operation = final_conclusion.get('operation', '')
        m = re.search(r'仓位([\d\-]+%)+', operation)
        pos_range = m.group(1) if m else '30-50%'
        if '看多' in verdict:
            pos_hint = f'信号偏多，可参考仓位 {pos_range}（概率推演，非确定建议）'
        elif '看空' in verdict:
            pos_hint = f'信号偏空，建议控制仓位 {pos_range}（概率推演，非确定建议）'
        else:
            pos_hint = f'方向不明，建议仓位 {pos_range}、多看少动（概率推演，非确定建议）'

        # 5) 风险（取首条，人话）
        risk = _strip(final_conclusion.get('risk_boundary', ''))
        if '；' in risk:
            risk = risk.split('；')[0]

        return {
            'verdict': verdict, 'vcolor': vcolor, 'verdict_reason': verdict_reason,
            'reasons': reasons, 'key_text': key_text, 'pos_hint': pos_hint, 'risk': risk,
        }

    def _dynamic_glossary(self, chan=None, ti=None, fused=None,
                           final_conclusion=None, last_price=0,
                           supports=None, resistances=None, diagnosis=None):
        """动态人话对照表：每只标的的术语解读均嵌入自身实际数据（非固定模板）。

        设计原则：
        - 保留术语→通俗解释的映射关系
        - 每条解读必须包含「这只股票的具体数值/状态」
        - 无数据的维度降级为通用解释 + 标注数据缺失原因
        """
        import re
        # chan 数据路径：result['analysis']['chan'] → details 子键包含 pivots/strokes/segments/trend/trading_points/signal
        chan_raw = chan or {}
        chan_d = (chan_raw.get('details') if isinstance(chan_raw, dict) else None) or {}
        ti = ti or {}
        fused = fused or {}
        fc = final_conclusion or {}
        diag = diagnosis or {}
        items = []

        # --- 背驰/背离 ---
        macd = ti.get('macd', {})
        divs = macd.get('divergences', []) or []
        top_n = sum(1 for d in divs if d.get('type') == 'top')
        bot_n = sum(1 for d in divs if d.get('type') == 'bottom')
        if divs:
            parts = []
            if top_n: parts.append(f'{top_n}个顶背离（价涨但动能衰减）')
            if bot_n: parts.append(f'{bot_n}个底背离（价跌但动能回暖）')
            items.append(('背驰/背离', f'当前检测到{"、".join(parts)}。'
                          f'意味着价格方向与指标动能出现分歧，趋势可能即将转折。'))
        else:
            direction = macd.get('direction', '')
            dir_cn = {'bullish': '偏多', 'bearish': '偏空'}.get(direction, '中性')
            items.append(('背驰/背离',
                          f'当前未见明显背离，MACD方向{dir_cn}与价格基本一致，'
                          f'暂无趋势反转信号。'))

        # --- 中枢 ---
        pivots = chan_d.get('pivots', []) or []
        trend = chan_d.get('trend', '')
        n_piv = len(pivots)
        if pivots:
            last_piv = pivots[-1]
            zd = last_piv.get('zd', 0)
            zg = last_piv.get('zg', 0)
            trend_cn = {'up': '上涨', 'down': '下跌'}.get(trend, '震荡')
            items.append(('中枢',
                          f'本标的有{n_piv}个中枢，最近一个在 [{zd:.4f}~{zg:.4f}] 区间。'
                          f'这是多空双方"拉锯"的价格密集成交区，'
                          f'当前走势类型：{trend_cn}。'))
        elif trend:
            trend_cn = {'up': '上涨趋势（尚未形成中枢或中枢正在构建中）',
                        'down': '下跌趋势（同上）'}.get(trend, '震荡整理中')
            items.append(('中枢', f'当前处于{trend_cn}，尚无完整的中枢区间可标记。'))
        else:
            items.append(('中枢',
                          '一段时间内价格来回晃荡的密集成交区，相当于「多空拉锯区」。'
                          '(本标的缠论结构未识别出明确中枢)'))

        # --- 笔/线段 ---
        strokes = chan_d.get('strokes', []) or []
        segments = chan_d.get('segments', []) or []
        last_stroke = strokes[-1] if strokes else {}
        st_dir = last_stroke.get('direction', '')
        st_cn = {'up': '上涨笔', 'down': '下跌笔'}.get(st_dir, '')
        items.append(('笔/线段',
                      f'本标的最近识别出 {len(strokes)} 笔 / {len(segments)} 线段'
                      f'{"，最新一笔为"+st_dir if st_cn else ""}。'
                      f'笔是最小级别的涨跌单元，线段由多笔组成更大级别的趋势。'))

        # --- 买卖点 ---
        tps = chan_d.get('trading_points', []) or []
        if tps:
            tp_items = [f"{tp.get('label', tp.get('type',''))}"
                        f"@{tp.get('price',0):.3f}" for tp in tps[-5:]]
            items.append(('买卖点',
                          f'近期发现 {"、".join(tp_items)} 。'
                          f'这些是缠论定义的"上车位置"，一类买点在趋势起点最安全，'
                          f'二/三类在回调/突破时确认。'))
        else:
            sig_val = fused.get('fused_signal', 0)
            hint = '偏多时可关注回调买点机会' if sig_val > 0.1 \
                else '偏空时应警惕卖点风险' if sig_val < -0.1 \
                else '观望等待信号明朗后再决策'
            items.append(('买卖点',
                          f'近期无明确买卖点信号。{hint}。'
                          f'(缠论一/二/三类买卖点分别对应趋势不同阶段的入场时机)'))

        # --- 量价齐升 / 量价背离 ---
        vol_diag = diag.get('vol', '') or ''
        dim_vol = (fused.get('dimensions', {}) or {}).get('vol', 0)
        # 从 key_levels 提取量比信息
        kl_text = fc.get('key_levels', [])
        vol_hint = ''
        for k in kl_text:
            if '量比' in k:
                vol_hint = k.replace('<br>', '').strip()
                break
        if vol_hint:
            items.append(('量价关系', f'{vol_hint}'
                          f' 量价信号={dim_vol:+.2f}。'))
        elif dim_vol > 0.15:
            items.append(('量价关系',
                          f'量价配合较好（信号{dim_vol:+.2f}），'
                          f'价格上涨有成交量支撑，健康度较高。'))
        elif dim_vol > -0.15:
            items.append(('量价关系',
                          f'量价中性（信号{dim_vol:+.2f}），'
                          f'成交量没有明显异常，方向待观察。'))
        else:
            items.append(('量价关系',
                          f'量价配合偏弱（信号{dim_vol:+.2f}），'
                          f'可能存在价涨量缩或价跌量增的背离迹象，需警惕。'))

        # --- 资金流入/流出 ---
        fund_diag = diag.get('fund', '') or ''
        dim_fund = (fused.get('dimensions', {}) or {}).get('fund', 0)
        if fund_diag:
            clean_fund = re.sub(r'<[^>]+>', '', fund_diag)[:80]
            items.append(('资金面', f'{clean_fund}（资金信号 {dim_fund:+.2f}）。'))
        elif dim_fund > 0.15:
            items.append(('资金面',
                          f'资金面偏多（信号{dim_fund:+.2f}），'
                          f'大单净流入为正，主力资金在进场。'))
        elif dim_fund > -0.15:
            items.append(('资金面',
                          f'资金面中性（信号{dim_fund:+.2f}），'
                          f'大单进出基本平衡，无明显方向性偏好。'))
        else:
            items.append(('资金面',
                          f'资金面偏空（信号{dim_fund:+.2f}），'
                          f'大单净流出为主，主力资金在撤离。(注：ETF量能缺失时该分值不可靠)'))

        # --- MACD 金叉/死叉 ---
        macd_cross = ti.get('macd_cross', [])
        if macd_cross and isinstance(macd_cross, list):
            recent_cross = [c for c in macd_cross if c]  # 非空交叉信号
            if recent_cross:
                last_c = recent_cross[-1]
                c_type = last_c.get('type', '')
                c_date = last_c.get('date', '')[:10]
                cn = {'golden': '金叉（转强）', 'death': '死叉（转弱）'}.get(c_type, '交叉')
                items.append(('MACD交叉',
                              f'最近一次{cn}出现在 {c_date} 左右，'
                              f'MACD快慢线交叉标志着短期动能切换。'))
            else:
                items.append(('MACD交叉',
                              '近期无明显金叉/死叉信号，MACD在零轴附近徘徊，方向不明确。'))
        else:
            mdir = macd.get('direction', '')
            mdir_cn = {'bullish': '多头排列（金叉区）', 'bearish': '空头排列（死叉区）'}.get(mdir, '纠缠状态')
            hist = macd.get('histogram', 0)
            h_sign = '正值（红柱，做多动能）' if hist > 0 else '负值（绿柱，做空动能）' if hist < 0 else '接近零'
            items.append(('MACD交叉',
                          f'当前MACD呈{mdir_cn}，柱状图{h_sign}。'
                          f'金叉=快线上穿慢线（短线转强），死叉反之。'))

        # --- KDJ/RSI 超买超卖 ---
        kdj = ti.get('kdj', {})
        rsi = ti.get('rsi', {})
        _to_float = lambda v: (float(v[-1]) if isinstance(v, (list, tuple)) else float(v)) if v is not None else 0
        kdj_k = _to_float(kdj.get('k'))
        rsi_val = _to_float(rsi.get('rsi6') or rsi.get('value'))
        kdj_ob = bool(kdj.get('overbought'))
        kdj_os = bool(kdj.get('oversold'))
        rsi_ob = bool(rsi.get('overbought'))
        rsi_os = bool(rsi.get('oversold'))
        parts = []
        if kdj_ob: parts.append(f'KDJ={kdj_k:.1f}(超买区>80)')
        elif kdj_os: parts.append(f'KDJ={kdj_k:.1f}(超卖区<20)')
        else: parts.append(f'KDJ={kdj_k:.1f}(正常)')
        if rsi_ob: parts.append(f'RSI={rsi_val:.1f}(超买>70)')
        elif rsi_os: parts.append(f'RSI={rsi_val:.1f}(超卖<30)')
        else: parts.append(f'RSI={rsi_val:.1f}(正常)')
        items.append(('KDJ/RSI超买超卖',
                      f'当前状态：{" / ".join(parts)}。'
                      f'超买=短期过热可能回调，超卖=杀跌过度可能反弹。'))

        # --- 共振 ---
        fused_sig = fused.get('fused_signal', 0)
        # 统计各维度投票
        chan_sig = chan_d.get('signal', 0) if chan_d else 0
        candle_sig = (ti.get('overall', '') or {}).get('signal', 0) if ti else 0
        fund_sig = (fused.get('dimensions', {}) or {}).get('fund', 0)
        vol_sig = (fused.get('dimensions', {}) or {}).get('vol', 0)
        bull_cnt = sum(1 for s in [chan_sig, candle_sig, fund_sig, vol_sig] if s > 0.05)
        bear_cnt = sum(1 for s in [chan_sig, candle_sig, fund_sig, vol_sig] if s < -0.05)
        neutral_cnt = 4 - bull_cnt - bear_cnt
        if abs(fused_sig) > 0.3:
            strength = '强' if abs(fused_sig) > 0.5 else '中等'
            side = '多' if fused_sig > 0 else '空'
            items.append(('共振',
                          f'{strength}{side}头共振（{bull_cnt}维看多/{bear_cnt}维看空/{neutral_cnt}维中立），'
                          f'融合信号={fused_sig:+.2f}。多指标同向时信号可信度更高。'))
        else:
            items.append(('共振',
                          f'各维度分歧较大（{bull_cnt}看多/{bear_cnt}看空/{neutral_cnt}中立），'
                          f'融合信号={fused_sig:+.2f}，暂未形成有效共振，建议等待信号统一。'))

        return items

    def _render_conclusion_overview_html(self, pc: dict, glossary_items=None) -> str:
        """渲染『结论速览』卡片 HTML（报告顶部常驻）。"""
        gl = glossary_items or self._dynamic_glossary()
        gl_items = ''.join(f'<li><b>{term}</b>：{human}</li>' for term, human in gl)
        reasons_html = ''.join(f'<li>{r}</li>' for r in pc['reasons'])
        return f"""
<div class="conclusion-overview" id="conclusionOverview">
  <div class="co-head">
    <div class="co-verdict" style="background:{pc['vcolor']}">{pc['verdict']}</div>
    <div class="co-head-text">
      <div class="co-title">结论速览（给非专业读者）</div>
      <div class="co-reason">{pc['verdict_reason']}</div>
    </div>
  </div>
  <div class="co-section">
    <div class="co-label">为什么这么看（3 条通俗理由）</div>
    <ul class="co-reasons">{reasons_html}</ul>
  </div>
  <div class="co-grid">
    <div class="co-box">
      <div class="co-label">关键价位</div>
      <div class="co-text">{pc['key_text']}</div>
    </div>
    <div class="co-box">
      <div class="co-label">仓位参考（概率推演）</div>
      <div class="co-text">{pc['pos_hint']}</div>
    </div>
  </div>
  <div class="co-risk"><span class="co-label">风险提示：</span>{pc['risk']}</div>
  <details class="co-glossary">
    <summary>看不懂术语？点这里看「人话对照表」</summary>
    <ul class="co-glossary-list">{gl_items}</ul>
  </details>
  <div class="co-note">以上为技术结构客观解读，严格区分确定结构与概率推演，不构成保本保收益承诺。</div>
</div>
"""

    # ========== 量化操作建议（结论版头部第二区块，面向想动手的读者） ==========
    def _render_quant_advice_html(self, final_conclusion, chan, supports, resistances, last_price) -> str:
        """渲染『量化操作建议』区块（结论版头部第二位置，紧跟结论速览卡之后）。

        与结论速览卡互补：速览卡回答「怎么看」，本模块回答「若动手怎么做」。
        内容：操作动作 + 建议仓位 + 信心打分 + 缠论买卖点信号 + 关键价位/触发失效条件。
        """
        import re
        operation = final_conclusion.get('operation', '')
        position_pct = final_conclusion.get('position_pct', 50)
        conf = final_conclusion.get('confidence_score', 0)
        risk = final_conclusion.get('risk_boundary', '')
        stop_loss = final_conclusion.get('stop_loss')
        invalidation = final_conclusion.get('invalidation')

        # 动作词（取 operation 首句，去仓位/信心/括号后缀）
        action = operation.split('，')[0] if '，' in operation else operation
        action = re.split(r'[（(]', action)[0].strip()

        # 仓位区间（优先从 operation 文本抽取「xx-yy%」，否则用 position_pct 中点）
        m = re.search(r'仓位([\d\-]+%+)', operation)
        pos_range = m.group(1) if m else f'{position_pct}%'

        # 动作配色（红=偏多/买，绿=偏空/卖，灰=中性观望）
        if '卖' in action:
            acolor = '#27ae60'
        elif '买' in action or '建仓' in action:
            acolor = '#e74c3c'
        else:
            acolor = '#888'

        # 缠论买卖点（最近若干个，按买卖着色）
        def _tp_human(raw):
            mm = re.match(r'(buy|sell)(\d)', raw or '')
            if mm:
                kind = '买点' if mm.group(1) == 'buy' else '卖点'
                cn = {1: '一', 2: '二', 3: '三', 4: '四'}.get(int(mm.group(2)), mm.group(2))
                return f'{cn}类{kind}'
            return raw or ''
        tps = chan.get('details', {}).get('trading_points', []) or []
        tp_items = []
        for tp in tps[-6:]:
            label = _tp_human(tp.get('label') or tp.get('type') or '')
            price = tp.get('price', 0)
            cls = 'buy' if '买' in label else ('sell' if '卖' in label else '')
            tp_items.append(f'<span class="qa-tp-item {cls}">{label}@{price:.3f}</span>')
        tp_html = ''.join(tp_items) if tp_items else '<span class="qa-tp-item">当前中枢内无明确买卖点，等待回调不破或突破回踩</span>'
        tp_label_suffix = f'（最近 {len(tp_items)} 个）' if tp_items else '（暂无明确点）'

        # 关键价位（就近支撑/阻力）
        def _near(lst, ref, side):
            cands = [x for x in lst if (x < ref if side == 'below' else x > ref)]
            return max(cands) if side == 'below' else (min(cands) if cands else None)
        trig = []
        s1 = _near(supports, last_price, 'below')
        r1 = _near(resistances, last_price, 'above')
        if s1 is not None:
            trig.append(f'第一支撑 {s1:.3f}')
        if r1 is not None:
            trig.append(f'第一阻力 {r1:.3f}')
        trigger_text = '；'.join(trig) if trig else f'当前价 {last_price:.3f}'

        # 失效条件（取含「若」的风险句）
        invalid = ''
        for seg in risk.split('；'):
            if seg.startswith('若'):
                invalid = seg
                break
        if invalid:
            trigger_text += f'；{invalid}'

        # 止损位 / 失效位（方向性，来自 _build_final_conclusion）
        stop_txt = f'{stop_loss:.3f}' if isinstance(stop_loss, (int, float)) else '—'
        invalid_txt = f'{invalidation:.3f}' if isinstance(invalidation, (int, float)) else '—'

        return f"""
<div class="quant-advice" id="quantAdvice">
  <div class="qa-head">
    <div class="qa-title">量化操作建议（给想动手的人）</div>
    <div class="qa-action" style="background:{acolor}">{action}</div>
  </div>
  <div class="qa-grid">
    <div class="qa-box"><div class="qa-label">建议仓位</div><div class="qa-text">{pos_range}</div></div>
    <div class="qa-box"><div class="qa-label">信心打分</div><div class="qa-text">{conf:.1f} / 10</div></div>
    <div class="qa-box"><div class="qa-label">当前价</div><div class="qa-text">{last_price:.3f}</div></div>
    <div class="qa-box"><div class="qa-label">操作动作</div><div class="qa-text">{action}</div></div>
  </div>
  <div class="qa-grid">
    <div class="qa-box"><div class="qa-label">建议止损位</div><div class="qa-text" style="color:#c0392b">{stop_txt}</div></div>
    <div class="qa-box"><div class="qa-label">结构失效位</div><div class="qa-text" style="color:#c0392b">{invalid_txt}</div></div>
    <div class="qa-box" style="flex:2"><div class="qa-label">说明</div><div class="qa-text" style="font-size:13px;">跌破止损位应严格离场；跌破失效位则本次结构判断作废</div></div>
  </div>
  <div class="qa-section">
    <div class="qa-label">缠论买卖点信号{tp_label_suffix}</div>
    <div class="qa-tp">{tp_html}</div>
  </div>
  <div class="qa-section">
    <div class="qa-label">关键价位与触发/失效条件</div>
    <div class="qa-text" style="font-size:14px;line-height:1.7;">{trigger_text}</div>
  </div>
  <div class="qa-note">以上为技术结构客观拆解，严格区分确定结构与概率推演，不构成保本保收益承诺。</div>
</div>
"""

    # ========== 单指标深度解析（P0-4） ==========
    @staticmethod
    def _signal_label_cn(sig) -> tuple:
        """信号值(-1~1)→(中文标签, 颜色)。遵循 A股涨红跌绿。"""
        try:
            sig = float(sig)
        except (TypeError, ValueError):
            sig = 0.0
        if sig >= 0.3:
            return '看多', '#e74c3c'
        if sig > 0.05:
            return '偏多', '#e67e22'
        if sig <= -0.3:
            return '看空', '#27ae60'
        if sig < -0.05:
            return '偏空', '#16a085'
        return '中性', '#888'

    @staticmethod
    def _star_rating(sig) -> str:
        """信号强度→五星（|sig| 越大星越多）。"""
        try:
            a = abs(float(sig))
        except (TypeError, ValueError):
            a = 0.0
        if a >= 0.35:
            stars = 5
        elif a >= 0.25:
            stars = 4
        elif a >= 0.15:
            stars = 3
        elif a >= 0.05:
            stars = 2
        else:
            stars = 1
        return '★' * stars + '☆' * (5 - stars)

    def _build_indicator_deep_conclusions(self, ti: dict) -> str:
        """逐指标深度结论块：MACD/KDJ/RSI/OBV/BOLL/均线，每个指标输出
        当前值 + 状态解读（结论先行）+ 信号标签&星级 + 操作指引。"""
        cards = []

        def _card(name, cur_text, verdict_sig, conclusion, guide):
            label, color = self._signal_label_cn(verdict_sig)
            stars = self._star_rating(verdict_sig)
            return f"""
  <div class="ind-deep-card">
    <div class="ind-deep-head">
      <span class="ind-deep-name">{name}</span>
      <span class="ind-deep-badge" style="background:{color}">{label} {stars}</span>
    </div>
    <div class="ind-deep-cur">{cur_text}</div>
    <div class="ind-deep-concl"><b>解读：</b>{conclusion}</div>
    <div class="ind-deep-guide"><b>指引：</b>{guide}</div>
  </div>"""

        # ---- MACD ----
        macd = ti.get('macd', {})
        if macd:
            dif = macd.get('last_dif', 0.0)
            dea = macd.get('last_dea', 0.0)
            bar = macd.get('last_bar', 0.0)
            direction = macd.get('direction', '')
            cross = macd.get('cross', '')
            dir_cn = {'bullish': '多头动能', 'bearish': '空头动能', 'neutral': '动能中性'}.get(direction, '动能中性')
            cross_cn = {'golden': '刚形成金叉', 'dead': '刚形成死叉', 'none': '无新交叉', '': '无新交叉'}.get(cross, '')
            zero_pos = '零轴上方（多头区）' if dif > 0 else '零轴下方（空头区）'
            bar_state = '红柱放大（动能增强）' if bar > 0 else ('绿柱放大（空头增强）' if bar < 0 else '柱状趋零（动能衰减）')
            div = macd.get('divergences', {})
            div_note = ''
            if isinstance(div, dict):
                if div.get('top'):
                    div_note = '，且出现顶背离，警惕上涨动能衰竭'
                elif div.get('bottom'):
                    div_note = '，且出现底背离，关注下跌动能减弱'
            cur = f'DIF {dif:+.4f} / DEA {dea:+.4f} / 柱 {bar:+.4f}，DIF位于{zero_pos}'
            concl = f'MACD {dir_cn}，{cross_cn}，{bar_state}{div_note}。'
            guide = 'DIF上穿DEA且红柱放大可视为多头信号，反之为空头；零轴上方金叉更可靠。'
            cards.append(_card('MACD', cur, macd.get('signal', 0), concl, guide))

        # ---- KDJ ----
        kdj = ti.get('kdj', {})
        if kdj:
            k = kdj.get('last_k', 0.0)
            d = kdj.get('last_d', 0.0)
            j = kdj.get('last_j', 0.0)
            cross = kdj.get('cross', '')
            cross_cn = {'golden': 'K上穿D（金叉）', 'dead': 'K下穿D（死叉）', 'none': '无新交叉', '': '无新交叉'}.get(cross, '')
            if kdj.get('overbought'):
                zone = '高位超买区（>80），短线有回调压力'
            elif kdj.get('oversold'):
                zone = '低位超卖区（<20），短线有反弹动力'
            else:
                zone = '中位区间，方向随主趋势'
            cur = f'K {k:.1f} / D {d:.1f} / J {j:.1f}'
            concl = f'KDJ运行于{zone}，{cross_cn}。'
            guide = '低位金叉偏多、高位死叉偏空；J值>100或<0为极端信号，常伴随短线拐点。'
            cards.append(_card('KDJ', cur, kdj.get('signal', 0), concl, guide))

        # ---- RSI ----
        rsi = ti.get('rsi', {})
        if rsi:
            last_rsi = rsi.get('last_rsi', 50.0)
            if rsi.get('overbought'):
                zone = '超买区（>70），追高风险偏高'
            elif rsi.get('oversold'):
                zone = '超卖区（<30），杀跌动能减弱'
            elif last_rsi >= 50:
                zone = '强弱分界上方（>50，多方占优）'
            else:
                zone = '强弱分界下方（<50，空方占优）'
            cur = f'RSI(14) {last_rsi:.1f}'
            concl = f'RSI处于{zone}。'
            guide = 'RSI>50多方主导、<50空方主导；超买不等于必跌，需结合趋势，背离时参考价值更高。'
            cards.append(_card('RSI', cur, rsi.get('signal', 0), concl, guide))

        # ---- OBV ----
        obv = ti.get('obv', {})
        if obv:
            chg = obv.get('obv_change_5d', 0.0)
            cur = f'近5日OBV变化 {chg:+.1f}%'
            concl = f"{obv.get('vol_alert', '量能中性')}。"
            guide = 'OBV与价格同向上行=量价配合健康；价涨OBV不涨为量价背离，上涨持续性存疑。'
            cards.append(_card('OBV 能量潮', cur, obv.get('signal', 0), concl, guide))

        # ---- BOLL ----
        boll = ti.get('boll', {})
        if boll and boll.get('position_state') != '数据不足':
            cur = f"上轨 {boll.get('last_upper',0):.4f} / 中轨 {boll.get('last_mid',0):.4f} / 下轨 {boll.get('last_lower',0):.4f}，带宽 {boll.get('bandwidth',0):.1f}%"
            concl = f"价格{boll.get('position_state','')}，{boll.get('bandwidth_state','')}。"
            cards.append(_card('BOLL 布林带', cur, boll.get('signal', 0), concl, boll.get('guide', '')))

        # ---- 均线系统 ----
        ma = ti.get('ma_system', {})
        if ma and ma.get('mas'):
            mas = ma['mas']
            parts = []
            for p in ['ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma250']:
                if p in mas:
                    parts.append(f"{p.upper()} {mas[p]['value']:.4f}({mas[p]['slope']})")
            cur = ' / '.join(parts)
            concl = ma.get('guide', '')
            guide = '多头排列（短期均线在上）顺势做多、空头排列规避；均线缠绕时观望，等待方向选择。'
            cards.append(_card('均线系统', cur, ma.get('signal', 0), concl, guide))

        if not cards:
            return '<div class="ind-deep-empty">指标数据不足，暂无深度解读。</div>'

        return '<div class="ind-deep-grid">' + ''.join(cards) + '</div>'

    def _build_resonance_matrix(self, ti: dict, chan: dict, fused: dict) -> str:
        """多指标信号共振矩阵：把缠论+6指标的方向/强度并排成表，
        底部给出多空计票与综合共振结论（缠论为锚、指标为辅）。"""
        rows_def = [
            ('缠论结构', chan.get('signal', 0), '锚点'),
            ('MACD', ti.get('macd', {}).get('signal', 0), '动能'),
            ('KDJ', ti.get('kdj', {}).get('signal', 0), '摆动'),
            ('RSI', ti.get('rsi', {}).get('signal', 0), '强弱'),
            ('OBV', ti.get('obv', {}).get('signal', 0), '量能'),
            ('BOLL', ti.get('boll', {}).get('signal', 0), '波动'),
            ('均线系统', ti.get('ma_system', {}).get('signal', 0), '趋势'),
        ]

        bull = bear = neutral = 0
        trs = []
        for name, sig, kind in rows_def:
            label, color = self._signal_label_cn(sig)
            stars = self._star_rating(sig)
            if '多' in label:
                bull += 1
                arrow = '▲'
            elif '空' in label:
                bear += 1
                arrow = '▼'
            else:
                neutral += 1
                arrow = '＝'
            weight_tag = '（40%权重锚点）' if name == '缠论结构' else ''
            trs.append(f"""
      <tr>
        <td class="rm-name">{name}<span class="rm-kind">{kind}{weight_tag}</span></td>
        <td class="rm-sig" style="color:{color}">{arrow} {label}</td>
        <td class="rm-star">{stars}</td>
        <td class="rm-val" style="color:{color}">{float(sig):+.2f}</td>
      </tr>""")

        # 综合共振结论（以融合信号为准，缠论为锚）
        fsig = fused.get('fused_signal', 0)
        flabel, fcolor = self._signal_label_cn(fsig)
        total = bull + bear + neutral
        if bull >= 5:
            reso = '强多头共振（多数维度指向上涨）'
        elif bear >= 5:
            reso = '强空头共振（多数维度指向下跌）'
        elif bull - bear >= 2:
            reso = '偏多共振（多头维度占优）'
        elif bear - bull >= 2:
            reso = '偏空共振（空头维度占优）'
        else:
            reso = '信号分歧（多空拉锯，方向不明）'

        return f"""
<div class="reso-matrix">
  <table class="rm-table">
    <thead>
      <tr><th>维度</th><th>信号方向</th><th>强度</th><th>信号值</th></tr>
    </thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
  <div class="rm-summary">
    <div class="rm-count">
      <span style="color:#e74c3c">看多 {bull}</span> ·
      <span style="color:#888">中性 {neutral}</span> ·
      <span style="color:#27ae60">看空 {bear}</span>
      <span class="rm-total">（共 {total} 个维度）</span>
    </div>
    <div class="rm-verdict">共振结论：<b style="color:{fcolor}">{reso}</b>；融合信号 {float(fsig):+.3f}（{flabel}）</div>
    <div class="rm-note">注：综合评级以缠论结构为锚（40%权重）、其余指标为辅，共振矩阵为展示层，不改变融合权重。</div>
  </div>
</div>"""

    def _build_dual_level_html(self, td: dict, tw: dict) -> str:
        """多级别联动（日线↔周线，P1）：每个指标并排日/周两行读数，
        凸显「周线定方向、日线找点位」的级别递归（区间套）思想。
        周线缺失时回退为提示语，不报错。"""
        if not td:
            return '<div class="dual-empty">日线指标缺失，无法构建多级别联动。</div>'

        # 每个指标的读写器：返回 (日线值文本, 周线值文本)
        def _read(name):
            if name == 'MACD':
                d = td.get('macd', {}); w = (tw or {}).get('macd', {})
                dt = f"DIF {d.get('last_dif',0):+.4f} / DEA {d.get('last_dea',0):+.4f} / 柱 {d.get('last_bar',0):+.4f}"
                wt = f"DIF {w.get('last_dif',0):+.4f} / DEA {w.get('last_dea',0):+.4f} / 柱 {w.get('last_bar',0):+.4f}" if w else None
            elif name == 'KDJ':
                d = td.get('kdj', {}); w = (tw or {}).get('kdj', {})
                dt = f"K {d.get('last_k',0):.1f} / D {d.get('last_d',0):.1f} / J {d.get('last_j',0):.1f}"
                wt = f"K {w.get('last_k',0):.1f} / D {w.get('last_d',0):.1f} / J {w.get('last_j',0):.1f}" if w else None
            elif name == 'RSI':
                d = td.get('rsi', {}); w = (tw or {}).get('rsi', {})
                dt = f"RSI(14) {d.get('last_rsi',0):.1f}"
                wt = f"RSI(14) {w.get('last_rsi',0):.1f}" if w else None
            elif name == 'OBV':
                d = td.get('obv', {}); w = (tw or {}).get('obv', {})
                dt = f"近5日 {d.get('obv_change_5d',0):+.1f}% / {d.get('vol_alert','')}"
                wt = f"近5日 {w.get('obv_change_5d',0):+.1f}% / {w.get('vol_alert','')}" if w else None
            elif name == 'BOLL':
                d = td.get('boll', {}); w = (tw or {}).get('boll', {})
                dt = f"上{d.get('last_upper',0):.4f} 中{d.get('last_mid',0):.4f} 下{d.get('last_lower',0):.4f}｜{d.get('position_state','')}"
                wt = f"上{w.get('last_upper',0):.4f} 中{w.get('last_mid',0):.4f} 下{w.get('last_lower',0):.4f}｜{w.get('position_state','')}" if (w and w.get('position_state') != '数据不足') else None
            elif name == '均线系统':
                d = td.get('ma_system', {}); w = (tw or {}).get('ma_system', {})
                def _ma_txt(m):
                    return ' / '.join(f"{p.upper()}{m['mas'][p]['value']:.4f}({m['mas'][p]['slope']})"
                                      for p in ['ma5', 'ma10', 'ma20', 'ma60', 'ma120', 'ma250'] if p in m.get('mas', {}))
                dt = _ma_txt(d)
                wt = _ma_txt(w) if (w and w.get('mas')) else None
            else:
                dt, wt = '', None
            return dt, wt

        rows = ['MACD', 'KDJ', 'RSI', 'OBV', 'BOLL', '均线系统']
        trs = []
        for nm in rows:
            dt, wt = _read(nm)
            if wt is None:
                trs.append(f"""
      <tr>
        <td class="dl-name">{nm}</td>
        <td class="dl-daily" style="color:#16213e">{dt}</td>
        <td class="dl-week" style="color:#999">周线未提供</td>
      </tr>""")
            else:
                trs.append(f"""
      <tr>
        <td class="dl-name">{nm}</td>
        <td class="dl-daily" style="color:#16213e">{dt}</td>
        <td class="dl-week" style="color:#8e44ad">{wt}</td>
      </tr>""")

        note = ('周线定方向（大级别趋势），日线找点位（小级别买卖）。两级别同向则信号更可靠，'
                '周线看多而日线走弱多为回调、可等日线企稳；周线看空而日线反弹多为减仓/做空窗口。'
                '本区块为级别递归（区间套）的可视化，不改变日线融合权重。') if tw else \
               '未提供周线数据，仅显示日线。可在 gen_unified 中开启 weekly 取数以启用双级别联动。'

        # 周线方向定调（综合 6 指标信号均值）
        wdir_badge = ''
        if tw:
            w_sigs = [tw.get(k, {}).get('signal', 0) for k in ('macd', 'kdj', 'rsi', 'obv', 'boll', 'ma_system')]
            w_avg = sum(w_sigs) / len(w_sigs) if w_sigs else 0.0
            wlabel, wcolor = self._signal_label_cn(w_avg)
            wdir_badge = f'<div class="dl-weekdir">周线综合方向：<b style="color:{wcolor}">{wlabel}</b>（均值 {w_avg:+.2f}）</div>'

        return f"""
<div class="dual-level">
  {wdir_badge}
  <table class="dl-table">
    <thead>
      <tr><th>指标</th><th>日线（找点位）</th><th>周线（定方向）</th></tr>
    </thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
  <div class="dl-note">{note}</div>
</div>"""

    # ========== 缠论方法论模块（源自三本原著） ==========
    def _detect_etf(self) -> bool:
        """依据名称/代码前缀判断是否为 ETF/基金标的。"""
        name = self.name or ''
        if any(k in name for k in ['ETF', '基金', 'LOF', '指数', '联接', 'etf']):
            return True
        s = (self.symbol or '').strip()
        # 兼容级别后缀（如 513050_30min / 600519_5min）：取前导 6 位数字代码判定
        import re as _re
        m = _re.match(r'^(\d{6})', s)
        code = m.group(1) if m else s[:6]
        if len(code) == 6 and code[:2] in ('51', '52', '56', '58', '15', '16', '18'):
            return True
        return False

    def _build_methodology(self, result: dict, diagnosis: dict, final_conclusion: dict) -> str:
        """依据引擎既有分析结果，渲染缠论方法论四模块 HTML 区块（理论/识别/决策/风控 + ETF视角）。"""
        try:
            a = result['analysis']
            chan = a.get('chan', {})
            chan_d = chan.get('details', {})
            ti = a.get('technical_indicators', {})
            fc = final_conclusion or {}
            is_etf = self._detect_etf()

            # ---- ① 理论判定摘要 ----
            trend = chan_d.get('trend', 'sideways')
            pivots = chan_d.get('pivots', []) or []
            strokes = chan_d.get('strokes', []) or []
            segments = chan_d.get('segments', []) or []
            n_piv = len(pivots)
            if trend in ('up', 'down') and n_piv >= 2:
                zstype = '趋势（' + ('上涨' if trend == 'up' else '下跌') + '）'
            elif trend in ('up', 'down') and n_piv == 1:
                zstype = '盘整（单中枢）'
            else:
                zstype = '震荡（中枢未明）'
            last_pivot = pivots[-1] if pivots else None
            pivot_txt = f"[{last_pivot['zd']:.3f}~{last_pivot['zg']:.3f}]" if (last_pivot and last_pivot.get('zd')) else '—'
            theory_html = (
                f"操作级别：<strong>{result.get('period','daily')}</strong>；走势类型：<strong>{zstype}</strong>；"
                f"中枢 {n_piv} 个（最近 {pivot_txt}）；笔 {len(strokes)} / 线段 {len(segments)}。"
            )

            # ---- ② 决策（买卖点+背驰+区间套） ----
            tps = chan_d.get('trading_points', []) or []
            tp_items = [f"{tp.get('label', tp.get('type',''))}@{tp.get('price',0):.3f}" for tp in tps[-5:]]
            tp_txt = '、'.join(tp_items) if tp_items else '暂无明显买卖点'
            macd = ti.get('macd', {})
            divs = macd.get('divergences', []) or []
            top_n = sum(1 for d in divs if d.get('type') == 'top')
            bot_n = sum(1 for d in divs if d.get('type') == 'bottom')
            if divs:
                bei_html = f"检测到背离 {len(divs)} 个（顶 {top_n} / 底 {bot_n}），可用区间套切小级别精确定位买卖点。"
            else:
                bei_html = "当前未见明显 MACD 背离；若有趋势背驰，须切小级别区间套确认。"
            decision_html = (
                f"买卖点：{tp_txt}。"
                f"{bei_html} "
                f"仓位参考：{fc.get('operation','—')}"
            )

            # ---- ③ 风控提示 ----
            risk_parts = []
            rb = fc.get('risk_boundary', '')
            if rb:
                risk_parts.append(rb)
            dr = (diagnosis or {}).get('risk', '')
            if dr and dr not in risk_parts:
                risk_parts.append(dr)
            if is_etf:
                risk_parts.append('ETF 额外核对：跟踪误差 / 流动性 / 折溢价 / 规模清盘风险。')
            risk_txt = '；'.join([r for r in risk_parts if r]) if risk_parts else '当前未见显著风险信号'

            # ---- ④ ETF 视角 ----
            if is_etf:
                etf_html = (
                    "<strong style='color:#2f54eb'>④ ETF 视角（指数合力，非个股博弈）：</strong>"
                    "本标的为 ETF，价格≈指数走势+跟踪误差。背驰看成分股整体合力；"
                    "建议以日/周线判趋势与中枢，30 分钟仅用于区间套精确买卖点；"
                    "并核对跟踪误差、流动性、折溢价与规模清盘风险。"
                )
            else:
                etf_html = (
                    "<strong style='color:#888'>④ ETF 视角：</strong>标的为个股，按庄家/主力博弈 + 公司语境分析；"
                    "如需做大类/行业配置，可切换到对应宽基/行业 ETF 用本框架择时。"
                )

            html = f"""
<div class="analysis-section" style="border:2px solid #2f54eb;background:linear-gradient(135deg,#f0f4ff,#fff);">
  <h2 style="color:#2f54eb;">缠论方法论四模块 — 理论 / 识别 / 决策 / 风控</h2>
  <div class="content"><p><strong style="color:#2f54eb">① 理论判定摘要：</strong>{theory_html}</p></div>
  <div class="content"><p><strong style="color:#2f54eb">② 决策（买卖点 + 背驰 + 区间套）：</strong>{decision_html}</p></div>
  <div class="content"><p><strong style="color:#ff9800">③ 风控提示：</strong>{risk_txt}</p></div>
  <div class="content"><p>{etf_html}</p></div>
  <div class="content" style="margin-top:8px;color:#888;font-size:12px;">方法论源自《教你炒股票》108课 / 《标准趋势三类买卖点+背驰段比较》 / 《缠论解均线系统》，详见 references/。</div>
</div>
"""
            return html
        except Exception as e:
            return f"<div class='analysis-section'><div class='content'>方法论区块生成失败：{e}</div></div>"


# ========== 命令行入口 ==========
def main():
    parser = argparse.ArgumentParser(description='缠论多维技术分析')
    parser.add_argument('--symbol', required=True, help='股票/ETF代码')
    parser.add_argument('--name', default='', help='标的名称')
    parser.add_argument('--start', default='2024-01-01', help='开始日期')
    parser.add_argument('--end', default=None, help='结束日期')
    parser.add_argument('--output', default=None, help='HTML报告输出路径')
    parser.add_argument('--data', default=None, help='JSON数据文件路径(跳过TDX获取)')
    args = parser.parse_args()

    analyzer = ChanlunAnalyzer(args.symbol, args.name)

    # 加载数据
    if args.data:
        with open(args.data, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        df = pd.DataFrame(raw['data'])
    else:
        # TDX数据获取由SKILL层处理，这里假设df已传入
        print("请通过SKILL调用获取数据")
        return

    # 执行分析
    result = analyzer.run(df)

    # 注入图表数据到结果中
    result['_df_dates'] = [str(d) for d in df['date']]
    result['_df_ohlc'] = [[
        float(row['open']), float(row['close']),
        float(row['low']), float(row['high'])
    ] for _, row in df.iterrows()]
    result['_df_volumes'] = [int(v) for v in df['volume']]

    # 生成HTML
    output = args.output or 'output/report.html'
    os.makedirs(os.path.dirname(output) if os.path.dirname(output) else 'output', exist_ok=True)

    analyzer.generate_html(result, output)

    print(f"\n分析完成: {result['symbol']} {result['name']}")
    print(f"综合信号: {result['analysis']['fusion']['signal_label']} ({result['analysis']['fusion']['fused_signal']:+.3f})")
    print(f"报告: {output}")


if __name__ == '__main__':
    main()
