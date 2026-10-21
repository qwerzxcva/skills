# -*- coding: utf-8 -*-
"""板块轮动雷达报告渲染（能力 #7 日更）—— 把 `daily_prep.py` 算好的数据注入 `gen_rotation.py` 模板并产出 HTML。

设计原则（2026-09-21 定）：
- **featured 板块全部按当日数据取**（今日最强 / 今日第二 / 20日榜首 / 最大资金池 / 收绿第一 / 20日垫底），
  绝不写死板块名 —— 否则次日会用错主线（09-21 教训：沿用上一交易日的「半导体/通信设备」，而当日第一是化学制药）；
- **叙述里的当日数字一律由数据算出**（宽度/涨停/封板率/动量），禁止手抄；
- ETF 行按「板块 ↔ ETF」映射匹配当日 featured 板块；无对应 ETF 时**如实标注**，不硬凑。

输入（`daily_prep.py` 的产物）：
    <out>/rotation_YYYYMMDD.json   板块池动量（当前 90 个同花顺二级行业）
    <out>/etf_MMDD.json            板块 ETF 快照（可缺 → ETF 行标注未发布）
    <output>/lu_MMDD.json          涨停池（提供热词/连板结构；可缺 → 相关文案降级）

用法：
    python render_rotation_report.py --date 2026-09-21 [--workspace W] [--out <HTML 输出目录>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_artifact  # noqa: E402
import sector_pool  # noqa: E402
from ths_indicators import limitup_pool_stats, market_breadth  # noqa: E402

# 板块 ↔ 代表 ETF（代码, 基金名+代码, 跟踪说明, 对应板块名）
ETF_OPTIONS = [
    ("512010.SH", "医药ETF易方达 512010.SH", "沪深300医药卫生，恒瑞医药/药明康德/迈瑞医疗权重高", "化学制药"),
    ("512200.SH", "房地产ETF南方 512200.SH", "中证全指房地产，保利/万科/招商蛇口权重高", "房地产"),
    ("512480.SH", "半导体ETF国联安 512480.SH", "中证全指半导体，中芯国际/北方华创/韦尔股份权重高", "半导体"),
    ("515880.SH", "通信ETF国泰 515880.SH", "中证全指通信设备，中际旭创/新易盛/天孚通信（光模块）权重高", "通信设备"),
    ("159825.SZ", "农业ETF富国 159825.SZ", "中证农业主题，牧原/温氏权重高（养殖权重约四成，与 881101/881102 口径有差）", "种植业与林业"),
    ("512400.SH", "有色金属ETF南方 512400.SH", "中证申万有色金属，紫金矿业/中国铝业/云铝权重高", "工业金属"),
    ("512800.SH", "银行ETF华宝 512800.SH", "中证银行，四大行/招行等", "银行"),
    ("512660.SH", "军工ETF国泰 512660.SH", "中证军工，军工电子/航空装备权重高", "航天装备"),
    ("512880.SH", "证券ETF国泰 512880.SH", "中证全指证券公司", "证券"),
    ("159928.SZ", "消费ETF汇添富 159928.SZ", "中证主要消费，白酒/食品权重高", "白酒"),
]


def _f(v, nd: int = 1) -> str:
    return f"{v:+.{nd}f}"


def render(date: str, workspace: Path, out_html_dir: Path | None = None, tpl: Path | None = None) -> Path:
    out_root = workspace / ".workbuddy" / "output"
    mmdd = date.replace("-", "")[4:]
    D = out_root / f"reco_{mmdd}"
    tpl = tpl or (HERE / "gen_rotation.py")

    rot = json.loads((D / f"rotation_{date.replace('-', '')}.json").read_text(encoding="utf-8"))
    rows, sh_m20 = rot["rows"], rot["sh_m20"]
    by = {r["name"]: r for r in rows}
    sector_tuples = [(r["name"], r["m1"], r["m5"], r["m20"], r["m60"], r["amt"], r["vr"], r["ex20"]) for r in rows]
    up_today = sum(1 for r in rows if r["m1"] > 0)
    N_BOARD = len(rows)          # 板块池大小（动态，勿写死 26）
    pos_cnt = sum(1 for r in rows if r["m20"] > 0)

    # 市场宽度 + 涨停结构（口径唯一实现在 ths_indicators）
    _mb = market_breadth(date)
    MB_N, MB_UP, MB_DN, MB_MED = _mb["n"], _mb["up"], _mb["dn"], _mb["median"]
    lu_path = out_root / f"lu_{mmdd}.json"
    if lu_path.exists() and json.loads(lu_path.read_text(encoding="utf-8")).get("ok"):
        lu = limitup_pool_stats(str(lu_path))
        LU_N, LU_BOARDS, LU_HOT, HOT = lu["n"], lu["board_text"], lu["hot_text"], lu["hot"]
    else:
        LU_N, LU_BOARDS, LU_HOT, HOT = None, "（涨停池数据缺失）", "（缺失）", {}
    hot = lambda w: HOT.get(w, 0)

    # ETF 快照
    etf_path = D / f"etf_{mmdd}.json"
    etf_raw = json.loads(etf_path.read_text(encoding="utf-8")) if etf_path.exists() else {}

    def etf_txt(code: str):
        x = ((etf_raw.get(code) or {}).get("data") or {}).get("item") or [{}]
        x = x[0]
        if not x.get("last_price"):
            return None
        return x["price_change_ratio_pct"], x["last_price"], x["turnover"] / 1e8

    # ── featured 板块：全部按当日数据取 ──
    lead = max(rows, key=lambda r: r["m1"])
    lead2 = sorted(rows, key=lambda r: -r["m1"])[1]
    lead20 = max(rows, key=lambda r: r["m20"])
    pool_top = max(rows, key=lambda r: r["amt"])
    down = sorted([r for r in rows if r["m1"] <= 0], key=lambda r: r["m1"])
    bot3 = sorted(rows, key=lambda r: r["m20"])[:3]
    # 收绿板块多时（90 个池里可能收绿 50+）只展示最弱 5 个 + 计数，避免综述被拖长（2026-09-23 用户要求）
    _down_show = down[:5]
    down_txt = "、".join(f"{r['name']} {_f(r['m1'])}%" for r in _down_show) or "无（全板块收红）"
    if len(down) > len(_down_show):
        down_txt += f" …（共 {len(down)} 个板块收绿）"
    # 市场定性词必须按当日真实宽度自适应（三档，不得写死；2026-09-22 与 09-28 各踩到一次）：
    #   普涨日 = 上涨 > 下跌；分化日 = 上涨 ≥ 下跌的一半；普跌日 = 更差（如 09-28 的 897 涨 / 4555 跌、跌停 > 涨停）
    #   报告里把普跌日写成"分化日"会严重低估风险，把非普涨日写成"普涨日"会与事实相反。
    if MB_UP > MB_DN:
        _breadth_word, _is_broad = "普涨日", True
        _weak_tag = "被抛弃的方向"
        _weak_head = "普涨日真正值得看的是「谁在跌」"
        _weak_note = f"在 {MB_UP} 家上涨的普涨日仍收绿，信息量远大于普跌日里的跌"
    elif MB_UP >= MB_DN * 0.5:
        _breadth_word, _is_broad = "分化日", False
        _weak_tag = "今日收绿方向"
        _weak_head = "今日收绿方向（仅列最弱 5 个）"
        _weak_note = f"当日并非普涨日（{MB_UP} 家上涨 / {MB_DN} 家下跌），收绿更多是顺势回落"
    else:
        _breadth_word, _is_broad = "普跌日", False
        _weak_tag = "今日普跌中的最弱方向"
        _weak_head = "深度普跌下的最弱方向（仅列最弱 5 个）"
        _weak_note = (f"当日为<b>深度普跌</b>（{MB_UP} 家上涨 / {MB_DN} 家下跌，比例约 1:{(MB_DN / max(MB_UP, 1)):.1f}）"
                      f"——收绿是普遍现象而非个体选择，应看「最抗跌」而非「谁在跌」")

    # 坑 73：20 日榜首在当日**可能是负的**（中期最强 ≠ 当日安全）→ 三处措辞都必须自适应，
    # 否则会出现「今日仍有 -6.84%」「中期动量与当日资金同向」这类与事实相反的句子（2026-09-28 实测：元件 20日 +9.55% / 今日 -6.84%）
    if (lead20["m1"] or 0) < 0:
        _l20_sig = (f"20日 {_f(lead20['m20'])}%（超额 {_f(lead20['ex20'])}pct）<b>全池第一</b>，"
                    f"但<b>今日 {_f(lead20['m1'])}%</b>、成交 {lead20['amt']:.0f} 亿——"
                    f"<b>中期最强的方向正在被兑现抛售（中期动量 ≠ 当日安全）</b>。")
        _l20_sum = (f"<b>{lead20['name']}</b> 20日 {_f(lead20['m20'])}%（超额 {_f(lead20['ex20'])}pct）居第一，"
                    f"但今日 <b>{_f(lead20['m1'])}%</b>——<b>中期动量最强 ≠ 当日安全</b>，本行只描述「谁曾经强」。")
        _l20_ins = f"20日榜首是<b>{lead20['name']}</b>（{_f(lead20['m20'])}%），<b>但它今日 {_f(lead20['m1'])}%</b>（已被兑现抛售）；"
    else:
        _l20_sig = (f"20日 {_f(lead20['m20'])}%（超额 {_f(lead20['ex20'])}pct）<b>全池第一</b>，今日仍有 {_f(lead20['m1'])}%、"
                    f"成交 {lead20['amt']:.0f} 亿——<b>中期动量与当日资金同向</b>，可靠性高于单看当日涨幅。")
        _l20_sum = (f"<b>{lead20['name']}</b> 20日 {_f(lead20['m20'])}%（超额 {_f(lead20['ex20'])}pct）居第一，"
                    f"今日仍有 {_f(lead20['m1'])}%——中期动量与当日资金同向。")
        _l20_ins = f"20日榜首是<b>{lead20['name']}</b>（{_f(lead20['m20'])}%），今日仍有 {_f(lead20['m1'])}%；"

    bot_txt = "、".join(f"{r['name']} {_f(r['m20'])}%" for r in bot3)
    hot_top = " / ".join(f"{k} {v}" for k, v in list(HOT.items())[:4]) if HOT else "（缺失）"
    lu_txt = f"{LU_N} 家（{LU_BOARDS}）" if LU_N else "数据缺失"
    seal_txt = "（炸板池缺失，未计算）"
    lb_path = out_root / f"lb_{mmdd}.json"
    try:
        lb = json.loads(lb_path.read_text(encoding="utf-8"))
        lb_items = (lb.get("data") or {}).get("item") or (lb.get("data") or {}).get("stock_items") or []
        if lb.get("ok") and lb_items and LU_N:
            seal_txt = f"{LU_N / (LU_N + len(lb_items)) * 100:.1f}%（炸板 {len(lb_items)} 家）"
    except Exception:
        pass

    SIGNALS = [
        (lead["name"], "今日最强",
         f"今日 {_f(lead['m1'])}% 为 {N_BOARD} 个板块涨幅第一、成交 {lead['amt']:.0f} 亿、量比 {lead['vr']:.2f}；"
         f"涨停热词 {hot_top}——<b>板块涨幅与涨停结构同日验证</b>；其 20日 {_f(lead['m20'])}%、60日 {_f(lead['m60'])}%，"
         f"属低位反转起涨还是趋势中继，需看后续量能是否延续。"),
        (lead2["name"], "今日第二",
         f"今日 {_f(lead2['m1'])}%（20日 {_f(lead2['m20'])}%、成交 {lead2['amt']:.0f} 亿、量比 {lead2['vr']:.2f}）——"
         f"与今日第一的 {lead['name']} 构成当日资金的两个主要去向。"),
        (lead20["name"], "20日榜首 · 中期动量第一", _l20_sig),
        (pool_top["name"], "最大资金池",
         f"成交 {pool_top['amt']:.0f} 亿为全池最大、量比 {pool_top['vr']:.2f}、今日 {_f(pool_top['m1'])}%、"
         f"5日 {_f(pool_top['m5'])}%、20日 {_f(pool_top['m20'])}%——存量资金最大的方向，"
         f"其当日涨跌与量比是判断「增量有没有来」的第一观察点。"),
        ("/".join(r["name"] for r in bot3), "20日动量垫底",
         "、".join(f"{r['name']} 20日 {_f(r['m20'])}%（今日 {_f(r['m1'])}%）" for r in bot3)
         + "——中期最弱的方向；今日若随大盘飘红，属超跌反抽而非资金选择。"),
        # ⚠️ 曾经这里有一条「普涨日仍收绿」信号项：名称字段 = 全部收绿板块用 / 连接（90 板块池里可达 50+ 个），
        #    既把该行撑爆、又在非普涨日给出错误标签 → 2026-09-23 用户要求删除，改由 01 综述的「{_weak_tag}」行承担（只列最弱 5 个）。
    ]

    _flow_pick = sorted(rows, key=lambda r: -r["amt"])[:6]

    def flow_state(vr):
        return "显著放量" if vr >= 1.2 else "放量" if vr >= 1.05 else "平量" if vr >= 0.95 else "缩量流出"
    FLOW = [(r["name"], round(r["amt"]), r["vr"], flow_state(r["vr"])) for r in _flow_pick]

    SUMMARY = [
        ("结论", f"全市场 {MB_N} 只中 <b>{MB_UP} 家上涨 / {MB_DN} 家下跌、中位 {_f(MB_MED, 2)}%</b>，"
                 f"{N_BOARD} 个板块 {up_today} 个收红（{pos_cnt} 个 20日为正），涨停 {lu_txt}，封板率 {seal_txt}；"
                 f"上证收 {rot['sh_close']:.2f}（20日 {_f(sh_m20)}%）。"
                 f"领涨的是 <b>{lead['name']} {_f(lead['m1'])}%</b> 与 {lead2['name']} {_f(lead2['m1'])}%；"
                 f"20 日动量榜首仍是 <b>{lead20['name']} {_f(lead20['m20'])}%</b>。"),
        ("最强", f"<b>{lead['name']}</b>今日 {_f(lead['m1'])}% 全池第一、成交 {lead['amt']:.0f} 亿、量比 {lead['vr']:.2f}，"
                 f"涨停热词 {hot_top}。"),
        ("最大资金池", f"<b>{pool_top['name']}</b>成交 {pool_top['amt']:.0f} 亿为全池最大（量比 {pool_top['vr']:.2f}），"
                       f"5日 {_f(pool_top['m5'])}%、20日 {_f(pool_top['m20'])}%——存量最大的方向。"),
        ("20日榜首", _l20_sum),
        (_weak_tag, f"最弱 5 个：{down_txt}——{_weak_note}。"),
        ("与「20日垫底」区分", f"20日动量垫底的是 {bot_txt}，它们今日多数随大盘上涨——属超跌反弹，不是资金选择。"),
    ]

    # ── ETF 行：按 featured 板块匹配 ──
    def find_etf(sector_name: str):
        for code, label, desc, sec in ETF_OPTIONS:
            if sec == sector_name:
                return code, label, desc
        return None

    ETF_ROWS = []
    _missed = []
    for rank, sec in (("🥇 ", lead), ("🥈 ", lead2), ("🥉 ", lead20), ("⚠️ ", pool_top),
                      ("⚠️ ", down[0] if down else bot3[0])):
        m = find_etf(sec["name"])
        if not m:
            # featured 板块没有收录对应 ETF 时**不留空行**，只记账；全都没有时给一行说明（不硬凑基金代码）
            _missed.append(sec["name"])
            continue
        code, label, desc = m
        t = etf_txt(code)
        body = (f"（{desc}）——今日<b>{t[0]:+.2f}%</b>、收 {t[1]}、成交 {t[2]:.1f} 亿"
                if t else f"（{desc}）——<b>本日 fund snapshot 未发布</b>，仅列板块指数口径")
        ETF_ROWS.append((f"{rank}{sec['name']}(今日{_f(sec['m1'])}%·板块 {_f(sec['m20'])}%/20日)",
                         label,
                         body + f"；对应板块 20日 {_f(sec['m20'])}%、量比 {sec['vr']:.2f}、成交 {sec['amt']:.0f} 亿"))

    if not ETF_ROWS:
        ETF_ROWS.append(("—", "—",
                         f"今日 featured 板块（{'、'.join(_missed)}）在本 ETF 池中暂无收录的跟踪基金，"
                         f"故仅列板块指数口径（不硬凑基金代码）"))

    CFG = {
        "name": "板块轮动雷达", "code": f"{N_BOARD} 个同花顺二级行业 · 截至 {rot['date']}",
        "verdict": f"{lead['name']}{_f(lead['m1'])}%领涨 · {lead2['name']}{_f(lead2['m1'])}%次之 · "
                   f"{_breadth_word}{MB_UP}家上涨 · 涨停{lu_txt} · 20日榜首{lead20['name']}{_f(lead20['m20'])}%",
        "verdict_short": f"{lead['name']}领涨 · {lead20['name']}中期居首",
        "verdict_note": (f"全市场 {MB_N} 只中 <b>{MB_UP} 家上涨、{MB_DN} 家下跌、中位 {_f(MB_MED, 2)}%</b>；"
                         f"{N_BOARD} 个板块 {up_today} 个收红、涨停 {lu_txt}、封板率 {seal_txt}、"
                         f"上证 {rot['sh_close']:.2f}（20日 {_f(sh_m20)}%）。"
                         f"领涨端：<b>{lead['name']} {_f(lead['m1'])}%</b>、{lead2['name']} {_f(lead2['m1'])}%；"
                         f"20日榜首 {lead20['name']} {_f(lead20['m20'])}%；最大资金池 {pool_top['name']} {pool_top['amt']:.0f} 亿。"
                         f"收绿的是：{down_txt}——{_weak_note}。涨停热词：{LU_HOT}。"),
    }

    NOTE = (f"数据来源：同花顺金融数据（hithink-finance CLI，index history <b>同花顺二级行业 881xxx.TI 共 {N_BOARD} 个</b> + 上证 000001.SH 基准，成分股覆盖全市场 100%；"
            f"已含 {rot['date']} 收盘）；动量=板块指数收盘价涨跌幅（1/5/20/60 交易日）；量比=5日均成交额/20日均成交额（>1 放量）；"
            "超额=板块 20 日涨幅-上证同期；市场涨跌家数与中位数=本地 DuckDB 前复权日K 自算（口径：收盘 vs 前收）；"
            "涨停家数/连板结构/热词=交易所涨停池（口径与「涨幅≥9.8%」不同）；ETF 行情=fund snapshot 当日实测（未发布者已标注）。"
            "轮动信号为模型综合判断（模型输出）。仅供研究参考，不构成个人投资建议。")

    KPI = {"strong": f"{lead['m1']:+.2f}%", "strong_k": f"今日最强板块({lead['name']})",
           "pos_cnt": f"{up_today} 个", "pos_cnt_k": f"今日红盘板块（全场 {N_BOARD} 中）",
           "pool": f"{pool_top['amt']:.0f} 亿", "pool_k": f"最大资金池({pool_top['name']})"}
    TABLE_HINT = f"{N_BOARD} 个二级行业 × 多窗口动量矩阵 · 红强绿弱 · 上证基准 20日{_f(sh_m20)}%"
    INSIGHT_TABLE = ("💡 " + _l20_ins +
                     f"而今日板块涨幅第一是 <b>{lead['name']}（{_f(lead['m1'])}%）</b>——两者是否重合，"
                     f"决定这是「低位补涨」还是「主线延续」；{N_BOARD} 个板块 {up_today} 个收红（{pos_cnt} 个 20日为正），"
                     f"全市场 {MB_UP} 家上涨、涨停 {lu_txt}——<b>{_weak_head}</b>：{down_txt}。")
    INSIGHT_SIGNAL = (f"💡 核心轮动信号：<b>{lead['name']} {_f(lead['m1'])}%</b>（成交 {lead['amt']:.0f} 亿、量比 {lead['vr']:.2f}）"
                      f"+ <b>{lead2['name']} {_f(lead2['m1'])}%</b>；涨停热词 {hot_top}。"
                      f"最大资金池 {pool_top['name']} {pool_top['amt']:.0f} 亿（今日 {_f(pool_top['m1'])}%、5日 {_f(pool_top['m5'])}%）"
                      f"——<b>「存量最大」与「当日最强」是否为同一方向，是判断增量资金去向的关键</b>；"
                      f"20 日垫底的是 {bot_txt}，今日随大盘反弹但无资金验证。")
    INSIGHT_FLOW = (f"💡 资金池与量比：最大 <b>{pool_top['name']} {pool_top['amt']:.0f} 亿</b>（量比 {pool_top['vr']:.2f}）、"
                    f"次之 <b>{sorted(rows, key=lambda r: -r['amt'])[1]['name']} "
                    f"{sorted(rows, key=lambda r: -r['amt'])[1]['amt']:.0f} 亿</b>；"
                    f"量比最高的是 <b>{max(rows, key=lambda r: r['vr'])['name']}（{max(rows, key=lambda r: r['vr'])['vr']:.2f}）</b>"
                    f"——增量资金优先看量比>1 且当日上涨的板块。")

    # ── 注入模板数据区并运行 ──
    src = tpl.read_text(encoding="utf-8")
    import re
    m = re.search(r"(# ================= 数据 =================)(.*?)(# ================= 渲染 =================)", src, re.S)
    if not m:
        raise SystemExit(f"模板数据区标记未找到：{tpl}")
    py = lambda v: json.dumps(v, ensure_ascii=False)
    lines = [f'DATE = "{date}"',
             'ETF_ETL_SUBTITLE = "ETF 名称/代码经 hithink fund 实测 · 跟踪指数为公开披露口径"',
             "CFG = {" + f'"name": {py(CFG["name"])}, "code": {py(CFG["code"])}, '
                           f'"verdict": {py(CFG["verdict"])}, "verdict_short": {py(CFG["verdict_short"])}, '
                           f'"verdict_note": {py(CFG["verdict_note"])}' + "}",
             "ETF_ROWS = ["]
    lines += [f"    ({py(a)}, {py(b)}, {py(c)})," for a, b, c in ETF_ROWS]
    lines += ["]", "SECTORS = ["]
    lines += [f"    ({py(t[0])}, {t[1]}, {t[2]}, {t[3]}, {t[4]}, {t[5]:.0f}, {t[6]}, {t[7]})," for t in sector_tuples]
    lines += ["]", "SIGNALS = ["]
    lines += [f"    ({py(a)}, {py(b)}, {py(c)})," for a, b, c in SIGNALS]
    lines += ["]", "FLOW = ["]
    lines += [f"    ({py(a)}, {b}, {c}, {py(d)})," for a, b, c, d in FLOW]
    lines += ["]", "SUMMARY = ["]
    lines += [f"    ({py(a)}, {py(b)})," for a, b in SUMMARY]
    lines += ["]",
              f"NOTE = {py(NOTE)}", f"KPI = {py(KPI)}", f"TABLE_HINT = {py(TABLE_HINT)}",
              f"INSIGHT_TABLE = {py(INSIGHT_TABLE)}", f"INSIGHT_SIGNAL = {py(INSIGHT_SIGNAL)}",
              f"INSIGHT_FLOW = {py(INSIGHT_FLOW)}", f"HL = {py(lead['name'])}", ""]
    new_src = src[:m.start(2)] + "\n" + "\n".join(lines) + "\n" + src[m.start(3):]
    out_py = D / f"gen_rotation_{mmdd}.py"
    out_py.write_text(new_src, encoding="utf-8", newline="\n")
    print(f"  数据版脚本 -> {out_py.name}")

    # 模板用 THS_WORKSPACE 决定 HTML 输出目录（gen_rotation.py 第 30 行）→ 必须以它为准，
    # 只改 cwd 是无效的（2026-09-21 踩到：--out 不生效，报告落到了工作区根）
    env = dict(os.environ, THS_WORKSPACE=str(out_html_dir or workspace))
    t0 = time.time()      # 产物必须是本轮新写的
    r = subprocess.run([sys.executable, str(out_py)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=str(out_html_dir or workspace))
    print("  " + (r.stdout or "").strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print((r.stderr or "")[-1500:])
        raise SystemExit(1)
    # 产物契约（2026-10-09）：模板落盘名 = `板块轮动雷达_{YYYYMMDD}.html`。
    # 原先此处**不验证文件是否真的写出来了** —— 而模板输出目录由 THS_WORKSPACE 决定，
    # 只改 cwd 无效（2026-09-21 踩过：--out 不生效、报告落到工作区根）→ 必须实测，
    # 且要求是**本轮新写**（否则上一轮遗留的同名文件会把失败伪装成通过）。
    report_artifact.expect(out_html_dir or workspace,
                           f"板块轮动雷达_{date.replace('-', '')}.html",
                           glob_hint="*雷达_*.html", what="板块轮动雷达", not_before=t0)
    return out_html_dir or workspace


def main() -> int:
    ap = argparse.ArgumentParser(description="板块轮动雷达报告渲染（能力 #7）")
    ap.add_argument("--date", required=True)
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--out", help="HTML 输出目录（默认工作区根目录）")
    ap.add_argument("--tpl", help="gen_rotation.py 路径（默认同目录）")
    a = ap.parse_args()
    W = Path(a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd())
    print(f"═══ 渲染板块轮动雷达 {a.date} （工作区 {W}）═══")
    render(a.date, W, Path(a.out) if a.out else None, Path(a.tpl) if a.tpl else None)
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
