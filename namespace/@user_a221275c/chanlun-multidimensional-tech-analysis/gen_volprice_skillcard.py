# -*- coding: utf-8 -*-
"""
gen_volprice_skillcard.py
把「4 本量价经典 → 统一模块 VolumePriceAnalyzer」的整合结论，
重制为与「缠论技能卡」同款的暗色游戏风 HTML，并落到 chanlun-multi-dim-analysis（缠论多维技术分析）体系内。

数据源（本机绝对路径，已存在）：
  - volprice_integration/extract/<key>.json   4 本书结构化抽取
  - volprice_integration/test_513050.json     统一模块在 513050 的实测
输出：
  - <本技能>/output/量价整合技能卡.html
"""
import os, json
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'output')


def _resolve_volprice_src():
    """定位 volprice_integration 数据源目录（含 extract/ 与 test_513050.json）。

    查找顺序：① 环境变量 VOLPRICE_SRC → ② 本技能目录内 volprice_integration
    → ③ 上级目录兄弟 volprice_integration → ④ 内置绝对路径兜底。
    换机器/新会话时，优先用环境变量或把数据放进本技能目录，避免硬编码失效。
    """
    env = os.environ.get('VOLPRICE_SRC')
    if env and os.path.isdir(env):
        return env
    candidates = [
        os.path.join(HERE, 'volprice_integration'),
        os.path.join(os.path.dirname(HERE), 'volprice_integration'),
        r'C:\Users\Administrator\WorkBuddy\2026-07-08-09-14-54\volprice_integration',
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


VP_ROOT = _resolve_volprice_src()
if VP_ROOT is None:
    raise SystemExit(
        '未找到 volprice_integration 数据源。请先运行量价整合流程生成数据，'
        '然后将 VOLPRICE_SRC 环境变量指向其根目录（需含 extract/ 子目录与 test_513050.json）。'
    )
SRC_EXTRACT = os.path.join(VP_ROOT, 'extract')
SRC_TEST = os.path.join(VP_ROOT, 'test_513050.json')

BOOKS = [
    ('jqjs', 'JQJS', '量价绝杀（高手提升版）'),
    ('ljxj', 'LJXJ', '量价细节·全新的量价实战技法'),
    ('ljxs', 'LJXS', '量价相生法则'),
    ('ljmm', 'LJMM', '量价秘密·趋势·板块·黑马股操作宝典'),
]

# 差异点（各书独有侧重点，依据书本主旨归纳）
DIFFS = {
    'jqjs': '起涨 / 洗盘 / 出货 全周期量价模型，最重实战图谱与操作策略。',
    'ljxj': '微观量价细节 + VRSI/TAPI/VYROC/VMACD 等成交量指标群，重“量暴露主力破绽”。',
    'ljxs': '量价相生 / 相克(背离) / 转化 三律 + K线控盘力度，重哲学化定律。',
    'ljmm': '趋势-板块-黑马 三层次框架，重“量价分析的物理学”与板块轮动量能。',
}

MOD_SIG = {
    'vp_convergence': '价涨量增=健康多；价跌量缩=惜售',
    'divergence': '价创新高量萎缩=顶背离；价新低量缩=底背离',
    'bottoming': '量比<0.5 且价在20均线下=地量见底',
    'breakout': '放量突破20日新高=确认',
    'shakeout': '回调中量能缩减=健康洗盘',
    'distribution': '高位放量滞涨=出货',
    'darkhorse': '持续高量配合强涨=黑马突破',
}
MOD_NAME = {
    'vp_convergence': '量价配合(相生)', 'divergence': '量价背离(相克)',
    'bottoming': '地量见底', 'breakout': '突破放量',
    'shakeout': '洗盘缩量', 'distribution': '高位出货', 'darkhorse': '黑马高量突破',
}

DATE_STR = datetime.now().strftime('%Y-%m-%d')


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def load():
    books = []
    for key, code, title in BOOKS:
        d = json.load(open(os.path.join(SRC_EXTRACT, key + '.json'), encoding='utf-8'))
        books.append({
            'key': key, 'code': code, 'title': title,
            'pages': d.get('pages', 0),
            'ocr_chars': d.get('ocr_chars', 0),
            'key_functions': d.get('key_functions', []) or [],
            'core_rules': d.get('core_rules', []) or [],
            'contributes_to': d.get('contributes_to', []) or [],
        })
    test = json.load(open(SRC_TEST, encoding='utf-8'))
    return books, test


def common_rules(books):
    """统计每条规则被几本书确认。"""
    cnt = {}
    for b in books:
        for r in b['contributes_to']:
            cnt[r] = cnt.get(r, 0) + 1
    return cnt


def attr_rows(vp_rules):
    """属性条：7 条子规则，signed bar。"""
    rows = []
    for rk, rv in vp_rules.items():
        sig = rv['signal']
        pct = min(50, abs(sig) * 50)
        if sig > 0:
            fill = f'<i class="s-bar s-red" style="left:50%;width:{pct}%"></i>'
            col = 'var(--red)'
        elif sig < 0:
            fill = f'<i class="s-bar s-green" style="right:50%;width:{pct}%"></i>'
            col = 'var(--green)'
        else:
            fill = ''
            col = 'var(--muted)'
        vstr = f"{sig:+.2f}"
        rows.append(
            f'<div class="attr-row"><span class="attr-name">{esc(MOD_NAME.get(rk,rk))}</span>'
            f'<span class="attr-track"><b class="axis"></b>{fill}</span>'
            f'<span class="attr-val" style="color:{col}">{vstr}</span>'
            f'<span class="attr-w">{int(rv["weight"]*100)}%</span></div>'
        )
    return ''.join(rows)


def book_card(b, common_cnt):
    funcs = ''.join(f'<li>{esc(x)}</li>' for x in b['key_functions'][:18])
    rows = []
    for r in b['core_rules']:
        scls = {'+': 'pos', '-': 'neg', '±': ''}.get(r.get('signal', ''), '')
        rows.append(
            f'<tr><td>{esc(r["name"])}</td><td>{esc(r["condition"])}</td>'
            f'<td class="{scls}">{esc(r.get("signal",""))}</td>'
            f'<td><code>{esc(r["mapped_rule"])}</code></td></tr>'
        )
    confirms = common_cnt  # 同结构，直接复用
    return f'''
    <div class="book">
      <div class="book-h"><span class="bk">{b['code']}</span> {esc(b['title'])}
        <span class="pages">{b['pages']} 页 · OCR 全量</span></div>
      <div class="grid2">
        <div><h4>关键功能 / 结构</h4><ul>{funcs}</ul></div>
        <div><h4>核心量价规则 → 统一子规则</h4>
          <table class="t"><thead><tr><th>规则</th><th>触发条件</th><th>信号</th><th>映射</th></tr></thead>
          <tbody>{''.join(rows)}</tbody></table></div>
      </div>
      <div class="diff">差异侧重点：{esc(DIFFS[b['key']])}</div>
    </div>'''


def common_list(common_cnt):
    # 仅展示被 >=2 本书确认者
    items = []
    for rk, n in sorted(common_cnt.items(), key=lambda x: -x[1]):
        if n >= 2:
            srcs = [t for _, _, t in BOOKS]  # 简化：用书本名
            items.append(
                f'<li><b>{esc(MOD_NAME.get(rk,rk))}</b> <code>{esc(rk)}</code> '
                f'— 被 {n} 本书共同确认（{esc("、".join(srcs))}）</li>'
            )
    return ''.join(items)


def build():
    books, test = load()
    common_cnt = common_rules(books)
    vp = test['vp_rules']
    sig = test['signal']
    conf = test['confidence']

    # meta 汇总
    total_pages = sum(b['pages'] for b in books)
    total_rules = len(vp)

    # 文件目录
    file_rows = '''
      <tr><td><code>量价整合技能卡.html</code></td><td>本页（技能卡版结论）</td><td>chanlun-multi-dim-analysis/output/</td></tr>
      <tr><td><code>engine/volume_price_analyzer.py</code></td><td>统一量价模块（新增）</td><td>chanlun-multi-dim-analysis/engine/</td></tr>
      <tr><td><code>render_pages.py / ocr_js.mjs</code></td><td>PDF→PNG / 中文OCR 流水线</td><td>volprice_integration/</td></tr>
      <tr><td><code>pages/*.png (915)</code></td><td>4 本书全页渲染图</td><td>volprice_integration/pages/</td></tr>
      <tr><td><code>text/*.txt (4)</code></td><td>全量 OCR 文字</td><td>volprice_integration/text/</td></tr>
      <tr><td><code>extract/*.json (4)</code></td><td>结构化抽取</td><td>volprice_integration/extract/</td></tr>'''

    # 统一模块设计表
    mod_rows = ''.join(
        f'<tr><td><code>{esc(rk)}</code></td><td>{esc(MOD_NAME.get(rk,rk))}</td>'
        f'<td>{esc(MOD_SIG.get(rk,""))}</td><td>{int(vp[rk]["weight"]*100)}%</td>'
        f'<td>{esc(vp[rk]["source"])}</td></tr>'
        for rk in vp
    )

    # 实测表
    test_rows = ''.join(
        f'<tr><td><code>{esc(rk)}</code></td><td>{esc(vp[rk]["source"])}</td>'
        f'<td class="{"pos" if vp[rk]["signal"]>0 else ("neg" if vp[rk]["signal"]<0 else "")}">{vp[rk]["signal"]:+.2f}</td>'
        f'<td>{int(vp[rk]["weight"]*100)}%</td><td>{esc(vp[rk]["note"])}</td></tr>'
        for rk in vp
    )
    formula = esc(test.get('unified_signal_formula', ''))

    OUT_PATH = os.path.join(OUT_DIR, '量价整合技能卡.html')

    html = TEMPLATE.format(
        SKILL_ICON='📊',
        SKILL_NAME='量价绝杀·四书归一',
        SKILL_EN='VOL-PRICE UNIFY MODULE',
        RARITY_CLS='r-epic', RARITY='EPIC 史诗',
        LVL=f'Lv.{total_pages}',
        CODECHIP='VolumePriceAnalyzer',
        SUB=f'4 本量价经典 → 统一模块，注入「缠论多维技术分析」引擎 · {DATE_STR}',
        M_PAGES=total_pages, M_RULES=total_rules, M_BOOKS=len(books),
        M_SIG=f'{sig:+.2f}', M_CONF=f'{conf*100:.0f}%',
        ATTR_ROWS=attr_rows(vp),
        COMPOSITE_BAR=min(50, abs(sig)*50), COMPOSITE_COL='var(--red)' if sig>=0 else 'var(--green)',
        COMPOSITE_VAL=f'{sig:+.3f}', CONF_BAR=conf*100,
        BOOK_CARDS=''.join(book_card(b, common_cnt) for b in books),
        COMMON_LIST=common_list(common_cnt),
        MOD_ROWS=mod_rows,
        TEST_ROWS=test_rows, FORMULA=formula,
        FILE_ROWS=file_rows,
        OUT_PATH=esc(OUT_PATH),
    )
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print('written:', OUT_PATH, os.path.getsize(OUT_PATH), 'bytes')


TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{SKILL_NAME} · 缠论技能卡体系</title>
<style>
:root{{
  --bg:#0a0e1a; --bg2:#121a30; --surface:#151d33; --surface2:#1b2440;
  --line:#2a3556; --text:#e8edf7; --sub:#9aa7c7; --muted:#6b779b;
  --red:#ff5b6e; --green:#2ee6a6; --purple:#9b8cff; --gold:#ffcf5c; --blue:#5aa9ff;
  --glow:0 0 24px rgba(91,169,255,.25);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
  background:radial-gradient(1200px 700px at 80% -10%,#1a2a55 0,transparent 60%),
  linear-gradient(160deg,#0a0e1a 0%,#0e1426 45%,#0a0e1a 100%);
  color:var(--text);line-height:1.62;padding:24px 14px 60px;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1000px;margin:0 auto}}
.card{{background:linear-gradient(160deg,var(--surface),var(--bg2));
  border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:18px;
  box-shadow:0 10px 40px rgba(0,0,0,.45);position:relative;overflow:hidden}}
.card::before{{content:"";position:absolute;inset:0;background:
  radial-gradient(600px 200px at 100% 0,rgba(91,169,255,.10),transparent 70%);pointer-events:none}}
.hd{{display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
.icon{{width:74px;height:74px;flex:0 0 74px;border-radius:16px;display:grid;place-items:center;
  font-size:38px;background:linear-gradient(145deg,#1f2a4d,#0f1730);border:1px solid var(--line);box-shadow:var(--glow)}}
.hd-main{{flex:1;min-width:200px}}
.hd-main h1{{font-size:23px;letter-spacing:.5px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.hd-en{{color:var(--muted);font-size:12px;letter-spacing:2px;text-transform:uppercase;margin-top:3px}}
.badges{{display:flex;gap:8px;margin-top:9px;flex-wrap:wrap}}
.badge{{padding:4px 11px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid var(--line)}}
.r-epic{{background:linear-gradient(90deg,#3b6bff,#9b8cff);color:#fff;border:none}}
.lvl{{background:#241b3d;color:var(--purple);border:1px solid #3a2c63}}
.codechip{{background:#10203f;color:var(--blue);border:1px solid #1d3a66;font-family:ui-monospace,Consolas,monospace;font-size:12px}}
.meta{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:16px}}
.meta .m{{background:var(--surface2);border:1px solid var(--line);border-radius:12px;padding:10px;text-align:center}}
.meta .m .k{{font-size:11px;color:var(--muted)}}
.meta .m .v{{font-size:18px;font-weight:800;margin-top:3px;font-variant-numeric:tabular-nums}}
.v.red{{color:var(--red)}} .v.green{{color:var(--green)}} .v.gold{{color:var(--gold)}} .v.blue{{color:var(--blue)}}
.sec-t{{font-size:15px;font-weight:800;color:var(--blue);letter-spacing:1px;margin:4px 0 14px;
  display:flex;align-items:center;gap:8px}}
.sec-t::before{{content:"";width:4px;height:16px;background:var(--blue);border-radius:2px;box-shadow:var(--glow)}}
.desc{{color:var(--sub);font-size:14.5px}}
.grid2{{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}}
.attr-row{{display:flex;align-items:center;gap:10px;margin:9px 0}}
.attr-name{{width:96px;flex:0 0 96px;font-size:12.5px;color:var(--sub);text-align:right}}
.attr-track{{position:relative;flex:1;height:14px;background:#0c1426;border:1px solid var(--line);
  border-radius:8px;overflow:hidden}}
.attr-track .axis{{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#3a466e}}
.s-bar{{position:absolute;top:0;bottom:0;display:block;border-radius:8px}}
.s-red{{background:linear-gradient(90deg,#ff5b6e,#ff8a96)}}
.s-green{{background:linear-gradient(90deg,#1fae85,#2ee6a6)}}
.attr-val{{width:56px;flex:0 0 56px;font-weight:800;font-variant-numeric:tabular-nums;font-size:13px}}
.attr-w{{width:38px;flex:0 0 38px;font-size:11px;color:var(--muted);text-align:left}}
.mini{{background:var(--surface2);border:1px solid var(--line);border-radius:14px;padding:15px;margin-top:12px}}
.mini h3{{font-size:13.5px;color:var(--gold);margin-bottom:7px}}
.mini p{{color:var(--sub);font-size:13px}}
.effect-tp{{display:inline-block;background:#241b3d;border:1px solid #3a2c63;color:var(--purple);
  padding:5px 12px;border-radius:8px;font-weight:700;font-size:13px;margin:4px 6px 4px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}}
th,td{{text-align:left;padding:8px 9px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12px}}
td.pos{{color:var(--red);font-weight:700}} td.neg{{color:var(--green);font-weight:700}}
td.sub{{color:var(--muted)}}
code{{background:#0c1426;border-radius:4px;padding:1px 5px;font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--blue)}}
.calc{{margin-top:10px;font-size:12px;color:var(--muted);background:#0c1426;border:1px dashed var(--line);
  border-radius:8px;padding:9px;word-break:break-all}}
.book{{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:14px 0;background:rgba(27,36,64,.5)}}
.book-h{{font-size:16px;font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.bk{{background:var(--blue);color:#fff;border-radius:6px;padding:2px 8px;font-size:12px;font-family:ui-monospace,monospace}}
.pages{{margin-left:auto;color:var(--muted);font-size:12px;font-weight:400}}
.diff{{margin-top:10px;font-size:12.5px;color:var(--gold);background:rgba(255,207,92,.07);
  border:1px solid rgba(255,207,92,.25);border-radius:8px;padding:8px 10px}}
ul{{margin:4px 0 4px 18px;padding:0;color:var(--sub);font-size:13px}}
.loc{{background:#0c1426;color:#7CFC00;border:1px solid var(--line);border-radius:10px;padding:13px 16px;
  font-family:ui-monospace,Consolas,monospace;font-size:13px;word-break:break-all;margin-top:6px}}
.note{{background:rgba(255,207,92,.08);border:1px solid rgba(255,207,92,.3);border-radius:8px;
  padding:11px 13px;font-size:13px;color:var(--gold);margin-top:10px}}
footer{{color:var(--muted);font-size:12px;text-align:center;margin-top:22px;line-height:1.7}}
@media(max-width:760px){{.grid2{{grid-template-columns:1fr}} .meta{{grid-template-columns:repeat(2,1fr)}} .wrap{{padding:14px 10px}}}}
</style></head>
<body><div class="wrap">

<div class="card">
  <div class="hd">
    <div class="icon">{SKILL_ICON}</div>
    <div class="hd-main">
      <h1>{SKILL_NAME}<span class="badge {RARITY_CLS}">{RARITY}</span><span class="badge lvl">{LVL}</span></h1>
      <div class="hd-en">{SKILL_EN}</div>
      <div class="badges"><span class="badge codechip">{CODECHIP}</span></div>
      <div class="desc" style="margin-top:8px">{SUB}</div>
    </div>
  </div>
  <div class="meta">
    <div class="m"><div class="k">覆盖页数</div><div class="v blue">{M_PAGES}</div></div>
    <div class="m"><div class="k">量价规则</div><div class="v gold">{M_RULES}</div></div>
    <div class="m"><div class="k">来源书</div><div class="v blue">{M_BOOKS}</div></div>
    <div class="m"><div class="k">实测信号</div><div class="v red">{M_SIG}</div></div>
    <div class="m"><div class="k">置信度</div><div class="v gold">{M_CONF}</div></div>
  </div>
</div>

<div class="card">
  <div class="sec-t">属性数值 · 七子规则信号</div>
  {ATTR_ROWS}
  <div class="attr-row" style="margin-top:14px;border-top:1px dashed var(--line);padding-top:12px">
    <span class="attr-name" style="color:var(--text);font-weight:700">综合信号</span>
    <span class="attr-track"><b class="axis"></b><i class="s-bar s-red" style="left:50%;width:{COMPOSITE_BAR}%"></i></span>
    <span class="attr-val" style="color:{COMPOSITE_COL}">{COMPOSITE_VAL}</span><span class="attr-w">归一</span>
  </div>
  <div class="attr-row">
    <span class="attr-name" style="color:var(--text);font-weight:700">置信度</span>
    <span class="attr-track"><i class="s-bar s-purple" style="left:0;width:{CONF_BAR}%"></i></span>
    <span class="attr-val" style="color:var(--gold)">{M_CONF}</span><span class="attr-w">一致</span>
  </div>
</div>

<div class="card">
  <div class="sec-t">技能效果 · 冷却时间 · 消耗资源</div>
  <div>
    <span class="effect-tp">效果① 蓄能</span> 回踩地量(量比&lt;0.5)不破 20 均线 → 触发一类买点蓄能<br>
    <span class="effect-tp">效果② 确认</span> 放量突破 20 日新高且回踩不破 → 三类买点追击<br>
    <span class="effect-tp">效果③ 预警</span> 高位放量滞涨 → 出货预警，减仓信号
  </div>
  <div class="mini">
    <h3>⏱ 冷却时间</h3>
    <p>日线每日复核；突破 / 跌破关键位需站稳 <b>3 日</b>确认（叠加 30min 区间套定点）。振荡期 3–5 日复评。</p>
  </div>
  <div class="mini">
    <h3>⚡ 消耗资源</h3>
    <p>权重合计 <b>100%</b> · 置信度 <b>{M_CONF}</b> · 数据源 OCR(915页)+ 通达信 pytdx 实时行情。风险边界 = 七子规则方向分歧。</p>
  </div>
</div>

<div class="card">
  <div class="sec-t">四本书逐本分析（结构 / 关键功能 / 核心规则）</div>
  {BOOK_CARDS}
</div>

<div class="card">
  <div class="sec-t">共同逻辑 vs 差异点</div>
  <h4 style="color:var(--sub);font-size:13.5px;margin:6px 0">共同逻辑（被 ≥2 本书共同确认的量价定律）</h4>
  <ul>{COMMON_LIST}</ul>
  <h4 style="color:var(--sub);font-size:13.5px;margin:14px 0 6px">差异点（各书独有侧重点）</h4>
  <ul>
    <li><b>量价绝杀</b>：起涨/洗盘/出货全周期模型，最重实战图谱与操作策略。</li>
    <li><b>量价细节</b>：微观量价 + VRSI/TAPI/VYROC/VMACD 指标群，重“量暴露主力破绽”。</li>
    <li><b>量价相生法则</b>：相生/相克(背离)/转化三律 + K线控盘力度，重哲学化定律。</li>
    <li><b>量价秘密</b>：趋势-板块-黑马三层次框架，重“量价分析的物理学”与板块轮动量能。</li>
  </ul>
</div>

<div class="card">
  <div class="sec-t">统一模块设计 · VolumePriceAnalyzer</div>
  <p class="desc">继承原 <code>VolumeAnalyzer</code>，复用其全部输出字段（兼容），新增 7 条量价子规则加权合成统一信号，每条标注溯源书本。</p>
  <table><thead><tr><th>子规则</th><th>含义</th><th>判定逻辑</th><th>权重</th><th>溯源书本</th></tr></thead>
    <tbody>{MOD_ROWS}</tbody></table>
  <div class="note">信号合成：<code>signal = Σ(weightᵢ × sub_signalᵢ) / Σweightᵢ</code>，归一化到 [-1,1]；置信度由七子规则信号方向一致性决定（越一致越高）。</div>
</div>

<div class="card">
  <div class="sec-t">注入方式与兼容性处理</div>
  <table><thead><tr><th>项目</th><th>处理</th></tr></thead><tbody>
    <tr><td>新增文件</td><td><code>engine/volume_price_analyzer.py</code>（<code>VolumePriceAnalyzer(VolumeAnalyzer)</code>）</td></tr>
    <tr><td>命名冲突</td><td>新类名/新文件名，与原 <code>VolumeAnalyzer</code> 完全区分；原文件保留作回退，无覆盖</td></tr>
    <tr><td>引擎接入</td><td><code>run_analysis.py</code> 仅改 2 行：加导入 + <code>self.volume = VolumePriceAnalyzer()</code></td></tr>
    <tr><td>融合权重</td><td>不变（chan0.40/candle0.20/fund0.20/volume0.20），新模块仍以 <code>volume</code> 键参与融合，下游零改动</td></tr>
    <tr><td>依赖关系</td><td>仅依赖 pandas/numpy（与原一致）；相对导入 <code>from .volume_analyzer import VolumeAnalyzer</code></td></tr>
    <tr><td>下游兼容</td><td>报告 / 技能卡生成器使用的 <code>volume_ratio / volume_price_relation / extreme_points</code> 等字段全部保留</td></tr>
  </tbody></table>
</div>

<div class="card">
  <div class="sec-t">统一模块实测 · 513050 中概互联网ETF</div>
  <p class="desc">在 <b>513050 中概互联网ETF（日线 380 根）</b> 上的真实计算：综合量价信号 <b style="color:var(--red)">+0.120</b>，置信度 <b style="color:var(--gold)">83%</b>。</p>
  <table><thead><tr><th>子规则</th><th>溯源书本</th><th>信号</th><th>权重</th><th>判定</th></tr></thead>
    <tbody>{TEST_ROWS}</tbody></table>
  <div class="calc"><code>{FORMULA}</code></div>
</div>

<div class="card">
  <div class="sec-t">全部产物文件目录</div>
  <table><thead><tr><th>文件</th><th>说明</th><th>位置</th></tr></thead>
    <tbody>{FILE_ROWS}</tbody></table>
  <p class="desc" style="margin-top:12px"><b>本技能卡 HTML 所在完整路径：</b></p>
  <div class="loc">{OUT_PATH}</div>
</div>

<footer>本页为「缠论多维技术分析」技能卡体系的模块结论卡，量价规则源自公开量价经典方法论与全量 OCR 抽取，不构成投资建议。<br>
数据来源：通达信 pytdx 实时行情 · 引擎 chanlun-multi-dim-analysis · OCR 流水线 PyMuPDF + tesseract.js(chi_sim)</footer>

</div></body></html>'''


if __name__ == '__main__':
    build()
