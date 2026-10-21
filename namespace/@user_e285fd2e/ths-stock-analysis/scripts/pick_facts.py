# -*- coding: utf-8 -*-
"""候选「事实卡」：给一批代码算好**短线技术指标 + 基本面 + 当日池/龙虎榜证据**，供报告叙述直接引用。

为什么单独一个脚本：写选股叙述（why/risk/plan）时，每只都需要
① 短线技术指标（MA/RSI/MACD/量比/%B/乖离/关键位）② 估值与中报（PE/PB/营收/归母/ROE/负债）
③ 当日涨停原因与龙虎榜净买 —— 这三类每天都要，且口径必须统一（① 走 `ths_indicators`，② 走 CLI 批量+并行）。
本脚本把三者在**一次调用**里出齐（技术面取本地前复权 parquet，基本面走 CLI，指数/池走已落盘 json）。

用法：
    python pick_facts.py --date 2026-09-22 --codes 002141.SZ,000756.SZ,... \
        --dir <workspace>/.workbuddy/output/reco_0922 --out-root <workspace>/.workbuddy/output
输出：`<dir>/facts_MMDD.json` + 终端表格（可直接照抄进报告数据区）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ths_cli  # noqa: E402
from ths_indicators import (  # noqa: E402
    boll_pctb, dist_ma_pct, judge_short_term, macd, rsi14, sma, vol_ratio,
)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _items(p: str) -> list:
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding="utf-8")).get("data")
    if isinstance(d, dict):
        for k in ("item", "stock_items", "items"):
            if k in d:
                return d[k] or []
        return []
    return d if isinstance(d, list) else []


def facts(date: str, codes: list[str], out_dir: str, out_root: str) -> dict:
    mmdd = date.replace("-", "")[4:]
    pq = os.path.join(out_dir, "bt_qfq_scan.parquet")
    con = duckdb.connect()
    tech = {}
    for c in codes:
        rows = con.execute(f"""
            SELECT CAST(date AS VARCHAR) d, close, high, low, open, volume
            FROM '{pq}' WHERE thscode = '{c}' ORDER BY d
        """).fetchall()
        if len(rows) < 25:
            print(f"  [MISSING] {c} 仅 {len(rows)} 根")
            continue
        d = [r[0] for r in rows]
        closes = [float(r[1]) for r in rows]
        highs = [float(r[2]) for r in rows]
        lows = [float(r[3]) for r in rows]
        vols = [float(r[5] or 0) for r in rows]
        if d[-1] != date:
            print(f"  ⚠️ {c} 最新日 {d[-1]} != {date}")
        short = len(closes) < 62
        bars = [{"date": dd, "open": float(r[4]), "high": float(r[2]), "low": float(r[3]),
                 "close": float(r[1]), "volume": float(r[5] or 0)} for dd, r in zip(d, rows)]
        ma5, ma10, ma20 = (sma(closes, 5)[-1], sma(closes, 10)[-1], sma(closes, 20)[-1])
        ma60 = None if short else sma(closes, 60)[-1]
        if short:
            arr = "次新(无MA60)"
        elif ma5 > ma10 > ma20 > ma60:
            arr = "多头排列"
        elif ma5 < ma10 < ma20 < ma60:
            arr = "空头排列"
        else:
            arr = "均线纠缠"
        md = macd(closes)
        st = judge_short_term(bars)
        ret = lambda n: round((closes[-1] / closes[-(n + 1)] - 1) * 100, 2) if len(closes) > n and closes[-(n + 1)] > 0 else None
        tech[c] = {
            "close": round(closes[-1], 2), "ma5": round(ma5, 2), "ma10": round(ma10, 2),
            "ma20": round(ma20, 2), "ma60": round(ma60, 2) if ma60 else None, "arr": arr,
            "above": ("站上MA5" if closes[-1] > ma5 else "破MA5") + "/" + ("站上MA20" if closes[-1] > ma20 else "破MA20"),
            "rsi": round(st["rsi14"], 1) if st["rsi14"] is not None else None,
            "macd_pos": "零轴上" if md["dif"] > 0 else "零轴下",
            "macd_cross": "金叉" if md["dif"] > md["dea"] and md["hist"] > 0 else ("多头" if md["dif"] > md["dea"] else "死叉/空头"),
            "macd_bar": round(md["hist"], 3), "vr": round(st["vol_ratio"], 2) if st["vol_ratio"] else None,
            "pb": round(st["pctb"], 1) if st["pctb"] is not None else None,
            "bias20": round(st["dist_ma20"], 2) if st["dist_ma20"] is not None else None,
            "hi20": round(max(highs[-20:]), 2), "lo20": round(min(lows[-20:]), 2),
            "hi60": round(max(highs[-60:]), 2) if not short else None,
            "lo60": round(min(lows[-60:]), 2),
            "r1": ret(1), "r5": ret(5), "r20": ret(20), "r60": None if short else ret(60),
            "state": st["state"], "state_hits": st["hits"], "bars": len(closes), "listed": d[0],
        }
    con.close()

    # 基本面：估值批量 1 次 + 中报指标并行
    val = ths_cli.run(["valuation", "snapshot", "--thscodes", ",".join(codes)])
    vmap = {x.get("thscode"): x for x in ((val.get("data") or {}).get("item") or [])}
    fins = ths_cli.run_many([["financials", "indicators", "--thscode", c, "--report", "2026-2"] for c in codes],
                            workers=8)
    fund = {}
    for c, j in zip(codes, fins):
        m = {}
        for ab in ((j.get("data") or {}).get("abilities") or []):
            for it in (ab.get("indicators") or []):
                m[it.get("index_id")] = it.get("value")
        v = vmap.get(c) or {}
        fund[c] = {
            "name": v.get("name"), "pe_ttm": _num(v.get("pe_ttm")), "pb": _num(v.get("pb_mrq")),
            "ps_ttm": _num(v.get("ps_ttm")),
            "rev_yoy": _num(m.get("calculate_operating_income_yoy_growth_ratio")),
            "np_yoy": _num(m.get("calculate_parent_holder_net_profit_yoy_growth_ratio")),
            "roe": _num(m.get("index_weighted_avg_roe")), "gross": _num(m.get("sale_gross_margin")),
            "debt": _num(m.get("assets_debt_ratio")),
        }

    # 当日池 / 龙虎榜证据
    lu = {x.get("thscode"): x for x in _items(os.path.join(out_root, f"lu_{mmdd}.json"))}
    net, org, cl = {}, {}, {}
    for x in _items(os.path.join(out_root, f"lhb_{mmdd}.json")):
        net[x.get("thscode")] = net.get(x.get("thscode"), 0) + float(x.get("net_value") or 0)
        cl.setdefault(x.get("thscode"), set()).update(
            k.get("name") if isinstance(k, dict) else k for k in (x.get("concept_list") or []))
    for x in _items(os.path.join(out_root, f"lhb_org_{mmdd}.json")):
        org[x.get("thscode")] = org.get(x.get("thscode"), 0) + float(x.get("org_net_value") or 0)
    ev = {c: {"in_lu": c in lu, "lu_reason": (lu.get(c) or {}).get("limit_up_reason"),
              "lu_cd": (lu.get(c) or {}).get("continue_day_cnt"),
              "lhb_net_yi": round(net[c] / 1e8, 2) if c in net else None,
              "lhb_org_yi": round(org[c] / 1e8, 2) if c in org else None,
              "concepts": sorted(cl.get(c, []))} for c in codes}

    out = {"date": date, "tech": tech, "fund": fund, "evid": ev}
    op = os.path.join(out_dir, f"facts_{mmdd}.json")
    # ⚠️ **合并而非覆盖**（2026-10-04 实测踩到）：本脚本常被分批调用（先跑机械池 5 只、
    #    发现候选不够再补跑几只）。早期是直接覆盖写 → 第二批把第一批的结果**静默抹掉**，
    #    且终端表格照常打印，看起来一切正常（我就是这么丢掉前 14 只的）。
    #    → 现在读入同日已有文件并 update；日期不同则视为新一天、重新开始。
    if os.path.exists(op):
        try:
            old = json.load(open(op, encoding="utf-8"))
            if old.get("date") == date:
                for sec in ("tech", "fund", "evid"):
                    merged = dict(old.get(sec) or {})
                    merged.update(out.get(sec) or {})
                    out[sec] = merged
                print(f"  ℹ️  已与已有 facts_{mmdd}.json 合并"
                      f"（本次 {len(codes)} 只，合并后共 {len(out['tech'])} 只）")
        except Exception as e:                       # noqa: BLE001
            print(f"  ⚠️  已有 facts_{mmdd}.json 读取失败（{e}）→ 本次结果将覆盖")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="候选事实卡：技术指标 + 基本面 + 池/龙虎证据")
    ap.add_argument("--date", required=True)
    ap.add_argument("--codes", required=True, help="逗号分隔的 thscode")
    ap.add_argument("--dir", required=True, help="reco_MMDD 目录")
    ap.add_argument("--out-root", required=True, help=".workbuddy/output 目录")
    a = ap.parse_args()
    codes = [c.strip().upper() for c in a.codes.split(",") if c.strip()]
    o = facts(a.date, codes, a.dir, a.out_root)
    print(f"\n{'代码':<11}{'名称':<9}{'收盘':>8}{'均线':<10}{'RSI':>6}{'%B':>7}{'乖离':>8}{'量比':>6}  "
          f"{'PE_TTM':>8}{'PB':>6}{'营收%':>8}{'归母%':>9}{'ROE%':>7}{'负债%':>7}  证据")
    for c in codes:
        t, f, e = o["tech"].get(c), o["fund"].get(c), o["evid"].get(c)
        if not t or not f:
            print(f"  {c} 数据不全")
            continue
        g = lambda v, n=2: ("—" if v is None else f"{v:.{n}f}")
        tag = []
        if e["in_lu"]:
            tag.append(f"涨停{e['lu_cd']}板")
        if e["lhb_net_yi"] is not None:
            tag.append(f"龙虎{e['lhb_net_yi']:+.2f}亿")
        if e["lhb_org_yi"]:
            tag.append(f"机构{e['lhb_org_yi']:+.2f}亿")
        print(f"  {c:<11}{(f['name'] or '')[:8]:<9}{t['close']:>8.2f}{t['arr']:<10}{g(t['rsi'],1):>6}"
              f"{g(t['pb'],1):>7}{g(t['bias20']):>8}{g(t['vr']):>6}  {g(f['pe_ttm'],1):>8}{g(f['pb']):>6}"
              f"{g(f['rev_yoy']):>8}{g(f['np_yoy']):>9}{g(f['roe']):>7}{g(f['debt']):>7}  {' · '.join(tag)}")
        if e["lu_reason"]:
            print(f"  {'':<11}  ↳ 涨停原因: {e['lu_reason']}")
        if e["concepts"]:
            print(f"  {'':<11}  ↳ 龙虎概念: {'/'.join(e['concepts'][:6])}")
        if t["state"] != "中性":
            print(f"  {'':<11}  ↳ 短线判读: {t['state']} {t['state_hits']}")
    print(f"\n落盘 -> " + str(Path(a.dir) / ("facts_" + a.date.replace("-", "")[4:] + ".json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
