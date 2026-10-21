#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 report_template.html 生成 unified_template.html：
在报告骨架基础上插入「技能概览卡」区块 + 属性雷达 JS（白底报告风配色）。
锚点：</style> 前插 CSS；图1 注释前插概览卡 HTML；</body> 前插雷达 JS。
"""
import os

HERE = r'C:\Users\Administrator\.workbuddy\skills\chanlun-multi-dim-analysis'
src = os.path.join(HERE, 'templates', 'report_template.html')
dst = os.path.join(HERE, 'templates', 'unified_template.html')

tpl = open(src, encoding='utf-8').read()

CSS = """
/* ===== 融合：技能概览卡（白底专业风） ===== */
#skill-overview.overview{margin-bottom:20px;border:2px solid #e74c3c;background:linear-gradient(135deg,#fffaf7,#fff);}
.ov-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
.ov-icon{font-size:34px;}
.ov-title h2{font-size:19px;margin:0;color:#1a1a2e;}
.ov-code{font-size:13px;color:#888;background:#f0f0f0;padding:1px 6px;border-radius:4px;}
.ov-en{font-size:12px;color:#999;}
.ov-badges{margin-left:auto;display:flex;gap:8px;}
.badge{padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700;color:#fff;}
.badge.r-legend{background:linear-gradient(135deg,#f6c945,#e67e22);}
.badge.r-epic{background:linear-gradient(135deg,#b06bd8,#7b3fa0);}
.badge.r-rare{background:linear-gradient(135deg,#5aa9ff,#2d6fd6);}
.badge.r-common{background:#9aa7c7;}
.badge.lv{background:#34495e;}
.badge.sig{color:#fff;}
.ov-meta{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0;}
.ov-meta .m{flex:1;min-width:90px;background:#fafafa;border:1px solid #eee;border-radius:8px;padding:8px;text-align:center;}
.ov-meta .k{font-size:11px;color:#999;}
.ov-meta .v{font-size:16px;font-weight:700;color:#1a1a2e;margin-top:2px;}
.ov-grid{display:flex;gap:14px;flex-wrap:wrap;}
.ov-grid .ov-box{flex:1;min-width:280px;}
.ov-box{background:#fff;border:1px solid #e8e8e8;border-radius:10px;padding:14px;margin-bottom:12px;}
.sec-t{font-size:14px;font-weight:700;color:#1a1a2e;border-left:4px solid #e74c3c;padding-left:8px;margin-bottom:8px;}
.cbox{width:100%;height:380px;}
.attr-list .attr-row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px;}
.attr-name{width:70px;color:#555;}
.attr-track{position:relative;flex:1;height:10px;background:#f0f0f0;border-radius:5px;overflow:hidden;}
.attr-track .axis{position:absolute;left:50%;top:0;width:1px;height:100%;background:#ccc;}
.attr-track .s-bar{position:absolute;top:0;height:100%;display:block;}
.s-bar.s-red{background:#e74c3c;} .s-bar.s-green{background:#27ae60;} .s-bar.s-purple{background:#8e44ad;}
.attr-val{width:60px;text-align:right;font-weight:700;}
.contrib{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px;}
.contrib th,.contrib td{border:1px solid #eee;padding:4px 6px;text-align:center;}
.contrib .pos{color:#e74c3c;} .contrib .neg{color:#27ae60;}
.calc{margin-top:6px;font-size:13px;color:#555;}
.effect{font-size:13px;line-height:1.7;color:#444;}
.effect-tp{margin-top:6px;font-size:12px;color:#888;}
.ov-two{display:flex;gap:14px;flex-wrap:wrap;}
.ov-two .ov-box{flex:1;min-width:280px;}
.mini{font-size:13px;color:#555;line-height:1.7;}
.key{font-weight:600;color:#333;}
.risk{color:#c0392b;font-size:12px;margin-top:4px;}
.posbar{height:14px;background:#f0f0f0;border-radius:7px;overflow:hidden;margin-bottom:6px;}
.posbar i{display:block;height:100%;background:linear-gradient(90deg,#e74c3c,#d4a017);}
.diag .ditem{margin:5px 0;font-size:13px;}
.diag .dt{font-weight:700;color:#1a1a2e;}
.diag .dd{color:#555;margin-left:8px;}
.note{font-size:12px;color:#888;margin-top:6px;line-height:1.6;}
.keytable{width:100%;border-collapse:collapse;font-size:13px;}
.keytable th,.keytable td{border:1px solid #eee;padding:4px 6px;text-align:center;}
.keytable .mono{font-family:monospace;}
.keytable .sub{color:#999;font-size:12px;}
"""

OVERVIEW = """
  <!-- ========== 技能概览卡（融合：游戏化元素聚合为顶部卡片） ========== -->
  <div id="skill-overview" class="card overview">
    <div class="ov-head">
      <div class="ov-icon">{{SKILL_ICON}}</div>
      <div class="ov-title">
        <h2>{{SKILL_NAME}} <span class="ov-code">${{SYMBOL}}</span></h2>
        <div class="ov-en">{{SKILL_EN}}</div>
      </div>
      <div class="ov-badges">
        <span class="badge {{RARITY_CLS}}">{{RARITY}}</span>
        <span class="badge lv">Lv.{{SKILL_LEVEL}}</span>
        <span class="badge sig" style="background:{{SIG_COLOR}}">{{SIG_LABEL}}</span>
      </div>
    </div>
    <div class="ov-meta">
      <div class="m"><div class="k">当前价</div><div class="v">{{LAST_PRICE}}</div></div>
      <div class="m"><div class="k">当日涨跌</div><div class="v">{{CHANGE_PCT}}</div></div>
      <div class="m"><div class="k">缠论趋势</div><div class="v">{{TREND_CN}}</div></div>
      <div class="m"><div class="k">综合信号</div><div class="v" style="color:{{SIG_COLOR}}">{{SIG_VAL}}</div></div>
      <div class="m"><div class="k">置信度</div><div class="v">{{CONF_PCT}}</div></div>
    </div>
    <div class="ov-grid">
      <div class="ov-box">
        <div class="sec-t">属性雷达（四维信号）</div>
        <div id="radar" class="cbox"></div>
      </div>
      <div class="ov-box">
        <div class="sec-t">属性数值</div>
        <div class="attr-list">{{ATTR_ROWS}}</div>
        <div class="sec-t" style="margin-top:10px">多维信号贡献</div>
        <table class="contrib"><tr><th>维度</th><th>信号</th><th>权重</th><th>贡献</th></tr>{{CONTRIB_ROWS}}</table>
        <div class="calc">综合信号 = {{CALC_FORMULA}} = <b style="color:{{SIG_COLOR}}">{{SIG_VAL}}</b></div>
      </div>
    </div>
    <div class="ov-box">
      <div class="sec-t">技能效果</div>
      <div class="effect">{{EFFECT_DESC}}</div>
      <div class="effect-tp">{{EFFECT_TP}}</div>
    </div>
    <div class="ov-two">
      <div class="ov-box">
        <div class="sec-t">冷却时间 · 复核周期</div>
        <div class="mini"><div class="key">{{COOLDOWN}}</div></div>
      </div>
      <div class="ov-box">
        <div class="sec-t">消耗资源 · 仓位/风控</div>
        <div class="posbar"><i style="width:{{POS_PCT}}%"></i></div>
        <div class="mini">
          <div class="key">建议仓位 {{POS_PCT}}% ｜ 信心 {{CONF_SCORE}}/10</div>
          <div class="key">{{OPERATION}}</div>
          <div class="risk">{{RISK_TXT}}</div>
        </div>
      </div>
    </div>
    <div class="ov-box">
      <div class="sec-t">多维诊断</div>
      <div class="diag">
        <div class="ditem"><div class="dt">① 缠论结构</div><div class="dd">{{DIAG_CHAN}}</div></div>
        <div class="ditem"><div class="dt">② 量价配合</div><div class="dd">{{DIAG_VOL}}</div></div>
        <div class="ditem"><div class="dt">③ 资金流向</div><div class="dd">{{DIAG_FUND}}</div></div>
        <div class="ditem"><div class="dt">④ 风险提示</div><div class="dd">{{DIAG_RISK}}</div></div>
      </div>
      <div class="note">策略参考：{{DIAG_STRATEGY}}</div>
    </div>
    <div class="ov-box">
      <div class="sec-t">关键价位</div>
      <table class="keytable"><tr><th>名称</th><th>价格</th><th>距离</th></tr>{{KEY_ROWS}}</table>
      <div class="note">周期视角：{{CYCLE_VIEW}}（{{FINAL_TREND}}）｜ 资金：{{FUND_TREND}}（强度 {{FUND_INT}}，5日 {{FUND5}}，20日 {{FUND20}}）｜ 量价 {{VOL_REL}}（量比 {{VOL_RATIO}}）</div>
    </div>
  </div>
"""

RADAR_JS = """
<script>
// ============ 技能概览卡 · 属性雷达（白底报告风配色） ============
var radar = echarts.init(document.getElementById('radar'));
radar.setOption({
  tooltip:{},
  radar:{ shape:'polygon', radius:'76%', center:['50%','54%'],
    indicator:[{name:'缠论',max:100},{name:'K线',max:100},{name:'资金',max:100},{name:'量能',max:100}],
    axisName:{color:'#666',fontSize:12},
    splitLine:{lineStyle:{color:'#ddd'}}, splitArea:{areaStyle:{color:['rgba(231,76,60,.03)','rgba(231,76,60,.07)']}},
    axisLine:{lineStyle:{color:'#ddd'}} },
  series:[{ type:'radar', data:[{ value:{{RADAR_VALS}},
    name:'多维信号', symbolSize:5,
    lineStyle:{color:'#e74c3c',width:2}, itemStyle:{color:'#e74c3c'},
    areaStyle:{color:'rgba(231,76,60,.25)'} }] }]
});
window.addEventListener('resize', function(){ radar.resize(); });
</script>
"""

assert '</style>' in tpl, '锚点 </style> 未找到'
assert '  <!-- ========== 图1' in tpl, '锚点 图1 注释未找到'
assert '</body>' in tpl, '锚点 </body> 未找到'

tpl = tpl.replace('</style>', CSS + '\n</style>', 1)
tpl = tpl.replace('  <!-- ========== 图1', OVERVIEW + '\n  <!-- ========== 图1', 1)
tpl = tpl.replace('</body>', RADAR_JS + '\n</body>', 1)

open(dst, 'w', encoding='utf-8').write(tpl)
print('unified_template.html ->', dst, '| bytes:', len(tpl))
