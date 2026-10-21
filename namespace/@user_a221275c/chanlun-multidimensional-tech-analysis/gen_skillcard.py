#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 513050 自定义「技能卡片」风格的缠论多维分析 HTML。"""
import sys, os, json, re, argparse
from datetime import datetime
CHAN_DIR = r'C:\Users\Administrator\.workbuddy\skills\chanlun-multi-dim-analysis'
TDX_DIR = r'C:\Users\Administrator\.workbuddy\skills\tdx-pro'
sys.path.insert(0, CHAN_DIR)
sys.path.insert(0, TDX_DIR)

import pandas as pd
import numpy as np
from run_analysis import ChanlunAnalyzer, NumpyEncoder
from scripts.kline import get_kline_data

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
TMPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skillcard_template.html')
# 用法: python gen_skillcard.py 513050 "中概互联网ETF"
parser = argparse.ArgumentParser(description='缠论多维分析 · 技能卡生成器')
parser.add_argument('symbol', nargs='?', default='513050', help='股票/ETF代码')
parser.add_argument('name', nargs='?', default='中概互联网ETF', help='标的名称')
args = parser.parse_args()
SYMBOL = args.symbol
NAME = args.name
DATE_STR = datetime.now().strftime('%Y%m%d')

# ---------- 1. 获取数据 ----------
series = get_kline_data(SYMBOL, period='daily', count=380, calculate_ma=True)
records = []
for k in series.klines:
    records.append({'date': k.datetime, 'open': k.open, 'high': k.high,
                    'low': k.low, 'close': k.close, 'volume': int(k.volume)})
records.reverse()
df = pd.DataFrame(records)
df['date'] = pd.to_datetime(df['date'], errors='coerce')
df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

# ---------- 2. 运行引擎 ----------
analyzer = ChanlunAnalyzer(SYMBOL, NAME, period='daily')
result = analyzer.run(df)
a = result['analysis']
fused = a['fusion']; chan = a['chan']; candle = a['candlestick']
fund = a['fund_flow']; vol = a['volume']; ti = a['technical_indicators']
summary = result['summary']

# ---------- 3. 辅助量 ----------
dates = [str(d.date()) for d in df['date']]
closes = df['close'].tolist(); vols = [int(v) for v in df['volume']]; N = len(dates)
ohlc = [[r.open, r.close, r.low, r.high] for _, r in df.iterrows()]
recent_high = max(o[3] for o in ohlc[-60:]); recent_low = min(o[2] for o in ohlc[-60:])
pivots = chan['details'].get('pivots', [])
supports = [recent_low]; resistances = [recent_high]
if pivots:
    p = pivots[-1]
    if p.get('zd'): supports.append(p['zd'])
    if p.get('zg'): resistances.append(p['zg'])
last_price = closes[-1]; prev_close = closes[-2]
change_pct = (last_price - prev_close) / prev_close * 100

# ---------- 4. 诊断/结论/方法论 ----------
diagnosis = analyzer._build_diagnosis(chan, candle, fund, vol, fused, [],
                                       last_price, recent_high, recent_low,
                                       supports, resistances, closes, vols, N)
final = analyzer._build_final_conclusion(chan, candle, fund, vol, fused, ti,
                                         last_price, recent_high, recent_low,
                                         supports, resistances, dates, closes, N)
methodology_html = analyzer._build_methodology(result, diagnosis, final)

# ---------- 5. 派生字段 ----------
trend_cn = {'up': '上涨', 'down': '下跌', 'sideways': '震荡'}.get(chan['details'].get('trend','sideways'), '震荡')
sig = fused['fused_signal']; conf = fused['fused_confidence']

if '买' in fused['signal_label']:
    skill_name = f"{NAME[:4]}·缠论共振·多头突进"; skill_en = "多头突破形态"
elif '卖' in fused['signal_label']:
    skill_name = f"{NAME[:4]}·缠论退守·空头压制"; skill_en = "空头压制形态"
else:
    skill_name = f"{NAME[:4]}·缠论静观·中枢待破"; skill_en = "震荡待变形态"
strength = abs(sig) * (conf + 0.3)
if strength >= 0.55: rarity, rarity_cls = '传说', 'r-legend'
elif strength >= 0.4: rarity, rarity_cls = '史诗', 'r-epic'
elif strength >= 0.25: rarity, rarity_cls = '稀有', 'r-rare'
else: rarity, rarity_cls = '普通', 'r-common'
skill_level = int(min(99, max(1, round(conf*60 + (sig+1)/2*40))))
skill_icon = '📡'

attrs = [('缠论结构', chan['signal']), ('K线形态', candle['signal']),
         ('资金流向', fund['signal']), ('量价配合', vol['signal']), ('指标共振', ti.get('signal', 0))]
# 雷达仅取四维（缠论/K线/资金/量能），不含「指标共振」
radar_vals100 = [round((v+1)/2*100, 1) for _, v in attrs[:4]]

cooldown = ("中枢震荡期：缩短至 3–5 个交易日复核，等待方向选择；"
            "有效突破中枢上沿或跌破中枢下沿后重新计时（区间套切 30 分钟精确定点）。") if trend_cn == '震荡' else \
           ("日线主周期：每 5–10 个交易日复核一次；突破/跌破关键位需站稳 3 日确认。")

tps = chan['details'].get('trading_points', [])
tp_items = [f"{tp.get('label', tp.get('type',''))}@{tp.get('price',0):.3f}" for tp in tps[-5:]]
effect_tp = '、'.join(tp_items) if tp_items else '当前中枢内无明确买卖点，等待回调不破或突破回踩'
effect_desc = (f"缠论结构判定为 <strong>{trend_cn}</strong>，共 {len(chan['details'].get('strokes',[]))} 笔 / "
               f"{len(chan['details'].get('segments',[]))} 线段 / {len(pivots)} 中枢。"
               f"综合信号 <strong>{sig:+.3f}</strong>（{fused['signal_label']}）。"
               f"价格位于中枢区间，技能效果 = 在中枢下沿不破时触发『一类买点』蓄能，"
               f"在放量突破中枢上沿并回踩不破时触发『三类买点』追击；"
               f"若有效跌破中枢下沿则技能反转为空头压制。")

# 多维信号贡献
_dmap = {'chan':('缠论结构',0.4),'candle':('K线形态',0.2),'fund':('资金流向',0.2),'volume':('量价配合',0.2)}
_sigmap = {'chan':chan['signal'],'candle':candle['signal'],'fund':fund['signal'],'volume':vol['signal']}
contribs = []
for dk,(dv,w) in _dmap.items():
    raw = _sigmap[dk]; contribs.append((dv, raw, w, raw*w))
calc_formula = ' + '.join([f'{dv}({raw:+.3f}×{int(w*100)}%)={c:+.3f}' for dv,raw,w,c in contribs])

fund_d = fund['details']; vol_d = vol['details']
fund_trend_cn = {'inflow':'流入','outflow':'流出','balanced':'平衡'}.get(fund_d.get('trend','balanced'),'平衡')
vol_rel_cn = {'bullish':'看多','bearish':'看空','neutral':'中性'}.get(vol_d.get('volume_price_relation','neutral'),'中性')

# 支撑/阻力清洁显示
def dist_down(s): return (last_price - s) / last_price * 100 if s < last_price else 0
def dist_up(r): return (r - last_price) / last_price * 100 if r > last_price else 0
sup1 = max([s for s in supports if s < last_price], default=supports[0])
res1 = min([r for r in resistances if r > last_price], default=resistances[0])
res2 = max(resistances) if len(resistances) > 1 else res1
key_levels = [('当前价', f'{last_price:.4f}', '当前'),
              ('第一支撑', f'{sup1:.4f}', f'下方 {dist_down(sup1):.1f}%'),
              ('第二支撑', f'{supports[0]:.4f}', f'下方 {dist_down(supports[0]):.1f}%'),
              ('第一阻力', f'{res1:.4f}', f'上方 {dist_up(res1):.1f}%'),
              ('第二阻力', f'{res2:.4f}', f'上方 {dist_up(res2):.1f}%')]

# ---------- 6. 构建属性条 HTML ----------
def bar_html(label, val, signed=True):
    if signed:
        pct = min(50, abs(val)*50)
        if val >= 0:
            fill = f'<i class="s-bar s-red" style="left:50%;width:{pct}%"></i>'
        else:
            fill = f'<i class="s-bar s-green" style="right:50%;width:{pct}%"></i>'
        color = 'var(--red)' if val >= 0 else 'var(--green)'
    else:
        pct = min(100, abs(val))
        fill = f'<i class="s-bar s-purple" style="width:{pct}%"></i>'
        color = 'var(--purple)'
    vstr = f'{val:+.3f}' if signed else f'{val:.1f}%'
    return (f'<div class="attr-row"><span class="attr-name">{label}</span>'
            f'<span class="attr-track"><b class="axis"></b>{fill}</span>'
            f'<span class="attr-val" style="color:{color}">{vstr}</span></div>')

attr_rows = ''.join([bar_html(l, v, True) for l, v in attrs])
attr_rows += bar_html('综合信号', sig, True)
attr_rows += bar_html('置信度', conf*100, False)

contrib_rows = ''.join([
    f'<tr><td>{dv}</td><td class="{"pos" if raw>=0 else "neg"}">{raw:+.3f}</td>'
    f'<td>{int(w*100)}%</td><td class="{"pos" if c>=0 else "neg"}">{c:+.3f}</td></tr>'
    for dv, raw, w, c in contribs])

key_rows = ''.join([f'<tr><td>{n}</td><td class="mono">{p}</td><td class="sub">{d}</td></tr>'
                    for n, p, d in key_levels])

diag_vol_ratio = vol_d.get('volume_ratio', 0) or 0

# ---------- 6a. K线图数据（整合核心图表，单文件呈现） ----------
ma5=[None]*N; ma10=[None]*N; ma20=[None]*N; ma60=[None]*N
for i in range(N):
    if i >= 4:  ma5[i]  = round(sum(closes[i-4:i+1])/5, 4)
    if i >= 9:  ma10[i] = round(sum(closes[max(0,i-9):i+1])/min(10,i+1), 4)
    if i >= 19: ma20[i] = round(sum(closes[i-19:i+1])/20, 4)
    if i >= 59: ma60[i] = round(sum(closes[i-59:i+1])/60, 4)
strokes_k = [{'start_idx': s.get('start'), 'end_idx': s.get('end'),
              'start_price': s.get('start_price'), 'end_price': s.get('end_price')}
             for s in chan['details'].get('strokes', [])]
pivots_k = [{'start_idx': p.get('start_idx'), 'end_idx': p.get('end_idx'),
             'zd': p.get('zd'), 'zg': p.get('zg')} for p in pivots]
tps_k = [{'type': t.get('type'), 'index': t.get('index'), 'price': t.get('price'),
          'label': t.get('label') or t.get('type')} for t in chan['details'].get('trading_points', [])]
kline_json = json.dumps({
    'dates': dates,
    'ohlc': [[round(o[0],4), round(o[1],4), round(o[2],4), round(o[3],4)] for o in ohlc],
    'volumes': vols,
    'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
    'recentHigh': recent_high, 'recentLow': recent_low,
    'strokes': strokes_k, 'pivots': pivots_k, 'tradingPoints': tps_k,
}, ensure_ascii=False)

# ---------- 6b. 文件目录（产物清单，扫描父技能 output/ 下的完整产物） ----------
import glob as _glob
FILE_OUT_DIR = os.path.join(CHAN_DIR, 'output')
prod_files = []
for fp in sorted(_glob.glob(os.path.join(FILE_OUT_DIR, f'{SYMBOL}_*'))):
    base = os.path.basename(fp)
    size_kb = os.path.getsize(fp) / 1024.0
    if base.endswith('_skillcard.html'):
        typ, desc = '技能卡 HTML', '本页 · 游戏技能卡可视化'
    elif base.endswith('_skillcard_data.json'):
        typ, desc = '结构化 JSON', '多维信号原始数据（驱动本页）'
    elif base.endswith('_analysis.html'):
        if '30min' in base: typ, desc = '分析报告(30分钟)', '30 分钟周期缠论结构'
        elif '5min' in base: typ, desc = '分析报告(5分钟)', '5 分钟周期缠论结构'
        else: typ, desc = '分析报告(日线)', '日线缠论多维分析标准报告'
    else:
        typ, desc = '文件', ''
    prod_files.append((base, typ, size_kb, desc))
file_rows = ''.join([
    f'<tr><td class="mono">{b.replace("30min","30分钟").replace("5min","5分钟")}</td><td>{t}</td><td class="sub">{s:.1f} KB</td><td class="sub">{d}</td></tr>'
    for b, t, s, d in prod_files])
file_count = len(prod_files)

# ---------- 6c. 英文→中文清洗（针对引擎生成的可见文本，不影响 KLINE_JSON 数据） ----------
def cn_tech(s):
    if not isinstance(s, str): return s
    s = re.sub(r'(buy|sell)(\d)', lambda m: ('一类' if m.group(2) == '1' else '二类' if m.group(2) == '2' else '三类') + ('买点' if m.group(1) == 'buy' else '卖点'), s)
    s = s.replace('MACD', '指数平滑异同平均线').replace('KDJ', '随机指标').replace('RSI', '相对强弱指标')
    s = s.replace('daily', '日线').replace('references', '参考文献')
    return s
methodology_html = cn_tech(methodology_html)
diagnosis = {k: cn_tech(v) for k, v in diagnosis.items()}
final = {k: cn_tech(v) for k, v in final.items()}
effect_tp = cn_tech(effect_tp); effect_desc = cn_tech(effect_desc)

# ---------- 7. 套用模板 ----------
T = open(TMPL, encoding='utf-8').read()
repl = {
 '{{SKILL_ICON}}': skill_icon, '{{SKILL_NAME}}': skill_name, '{{SKILL_EN}}': skill_en,
 '{{FILE_COUNT}}': str(file_count), '{{FILE_ROWS}}': file_rows,
 '{{KLINE_JSON}}': kline_json,
 '{{RARITY}}': rarity, '{{RARITY_CLS}}': rarity_cls, '{{SKILL_LEVEL}}': str(skill_level),
 '{{SYMBOL}}': SYMBOL, '{{NAME}}': NAME,
 '{{LAST_PRICE}}': f'{last_price:.4f}', '{{CHANGE_PCT}}': f'{change_pct:+.2f}%',
 '{{TREND_CN}}': trend_cn, '{{SIG_LABEL}}': fused['signal_label'],
 '{{SIG_VAL}}': f'{sig:+.3f}', '{{CONF_PCT}}': f'{conf*100:.0f}%',
 '{{SIG_COLOR}}': ('var(--gold)' if fused['signal_label']=='观望' else ('var(--red)' if sig>=0 else 'var(--green)')),
 '{{ATTR_ROWS}}': attr_rows,
 '{{RADAR_VALS}}': json.dumps(radar_vals100),
 '{{GAUGE_VAL}}': f'{sig*100:.1f}',
 '{{EFFECT_TP}}': effect_tp, '{{EFFECT_DESC}}': effect_desc,
 '{{COOLDOWN}}': cooldown,
 '{{POS_PCT}}': str(final.get('position_pct', 50)),
 '{{OPERATION}}': final.get('operation',''), '{{RISK_TXT}}': final.get('risk_boundary',''),
 '{{CONTRIB_ROWS}}': contrib_rows, '{{CALC_FORMULA}}': calc_formula,
 '{{DIAG_CHAN}}': diagnosis.get('chan',''), '{{DIAG_VOL}}': diagnosis.get('vol',''),
 '{{DIAG_FUND}}': diagnosis.get('fund',''), '{{DIAG_RISK}}': diagnosis.get('risk',''),
 '{{DIAG_STRATEGY}}': diagnosis.get('strategy',''),
 '{{KEY_ROWS}}': key_rows, '{{METHODOLOGY_HTML}}': methodology_html,
 '{{CYCLE_VIEW}}': final.get('cycle_view',''), '{{FINAL_TREND}}': final.get('trend_direction',''),
 '{{CONF_SCORE}}': f"{final.get('confidence_score',0):.1f}",
 '{{FUND_TREND}}': fund_trend_cn, '{{FUND_INT}}': f"{fund_d.get('intensity',0):.3f}",
 '{{FUND5}}': f"{fund_d.get('net_inflow_5d',0):+,}", '{{FUND20}}': f"{fund_d.get('net_inflow_20d',0):+,}",
 '{{VOL_REL}}': vol_rel_cn, '{{VOL_RATIO}}': f'{diag_vol_ratio:.2f}',
 '{{REC_DATE}}': f"{df.date.iloc[0].date()} ~ {df.date.iloc[-1].date()}",
}

html = T
for k, v in repl.items():
    html = html.replace(k, str(v))

out_path = os.path.join(OUT_DIR, f'{SYMBOL}_{DATE_STR}_skillcard.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print('SKILLCARD HTML ->', out_path)
print('skill_name:', skill_name, '| rarity:', rarity, '| level:', skill_level)
print('attrs radar:', radar_vals100)
