# -*- coding: utf-8 -*-
"""【规则验证工具】回测「选股规则」而不只是「信号」：全市场形态信号 + 证据分档 → 比较不同组合规则的前瞻收益。

为什么做这个：2026-09-21 发现推荐连续全是当日涨停（近四期 22/25），于是先测了「同一信号内涨停 vs 未涨停」，
结论是涨停组明显更差（T+5 −0.02%/胜率 41.5% vs 未涨停 +0.38%/45.5%，且按涨幅分档单调）。
但那只证明了**个股特征**，没证明**规则**。本脚本直接比较四种"每日取 5 只"的规则：

  R1 涨停优先  ：(涨停, 成交额) 排序取 5        ← 现行链路的事实效果
  R2 混合(≤2)   ：最多 2 只涨停 + 其余未涨停（按涨幅 0~5% 优先、再按成交额）
  R3 全未涨停  ：只从未涨停里按同样的偏好取 5
  R4 池内随机  ：从当日全部形态候选里随机 5（基准）
  R5a~R5d     ：先按「所属板块走势」过滤（当日>0 / 5日>0 / 20日>0 / 当日与20日双正），再套 R2 的配额规则 ——
              用于回答用户的问题「板块不行的股票我不看好，宁可凑不够 5 只」（2026-09-23 新增，坑 71）

口径：信号 = W底新触发 ∪ 60日新高新触发（阈值与 scan_signals.py 一致）；
      收益 = 次日开盘买入 → T+5 / T+10 收盘；涨停判定 主板 ≥9.8% / 创业板科创板 ≥19.5%；
      同时统计「次日高开>3%（现行纪律会跳过）」的比例，衡量可执行性。

**何时用**：改动 `cross_evidence.py` 的候选排序/配额规则后，或每季度做一次规则复核时跑一遍。

用法：python backtest_picks_rule.py --parquet <parquet> --start 2025-08-01 --end 2026-08-20 [--top 5]
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import statistics as st
import sys
from collections import defaultdict

import duckdb

LIMIT_UP_MAIN, LIMIT_UP_GEM = 9.8, 19.5


def find_w_bottom(closes, tol=0.05, min_gap=5, lookback=60):
    """与 bt_backtest.py / scan_signals.py 同款。"""
    if closes is None or len(closes) < lookback:
        return None
    seq = closes[-lookback:]
    n = len(seq)
    r = 20
    r_seg = seq[n - r:]
    L2_idx = n - r + r_seg.index(min(r_seg))
    L2 = seq[L2_idx]
    if L2_idx < min_gap + 2:
        return None
    left = seq[:L2_idx - min_gap + 1]
    L1_idx = left.index(min(left))
    L1 = left[L1_idx]
    if L1 <= 0 or abs(L2 - L1) / L1 > tol:
        return None
    neck = max(seq[L1_idx:L2_idx + 1])
    if neck <= max(L1, L2) * 1.02:
        return None
    if seq[-1] <= neck:
        return None
    return neck


def load_sector_momentum(sector_dir: str) -> dict:
    """{date: {board: (m1, m5, m20)}}（板块指数收盘涨跌幅，%）— 供「板块过滤器」用。"""
    import glob
    import os as _os
    out: dict[str, dict] = {}
    for p in glob.glob(_os.path.join(sector_dir, "long_*.json")):
        board = None
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️ 读 {p} 失败：{e}")
            continue
        code = _os.path.basename(p)[len("long_"):-len(".json")].replace("_", ".")
        try:
            sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            import sector_pool
            board = sector_pool.name_of(code)
        except Exception:
            board = code
        ser = []
        for x in (d.get("data") or {}).get("item") or []:
            c = float(x.get("close_price") or 0)
            ts = x.get("date_ms")
            if c > 0 and ts:
                ser.append((datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d"), c))
        ser.sort()
        for i, (dt, c) in enumerate(ser):
            if i < 20:
                continue
            mom = lambda k: (c / ser[i - k][1] - 1) * 100 if ser[i - k][1] else None
            out.setdefault(dt, {})[board] = (mom(1), mom(5), mom(20))
    return out


def load_sector_of(map_path: str) -> dict:
    """{stock: [board, ...]} —— 来自 `sector_map.py` 的 by_stock。"""
    try:
        return json.load(open(map_path, encoding="utf-8")).get("by_stock", {})
    except Exception as e:
        print(f"  ⚠️ 读 {map_path} 失败：{e}")          # 不要静默返回空 —— 静默会让回测跑出"空过滤"的假结论
        return {}


def build_candidates(parquet: str, start: str, end: str):
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT thscode, CAST(date AS VARCHAR) d, open, high, low, close, volume, amount
        FROM '{parquet}' WHERE substr(thscode,1,2) IN ('60','00','30') ORDER BY thscode, d
    """).fetchall()
    con.close()
    series = defaultdict(list)
    for r in rows:
        series[r[0]].append(r)

    daily = defaultdict(list)      # date -> [cand]
    for code, rs in series.items():
        n = len(rs)
        if n < 80:
            continue
        closes = [float(x[5] or 0) for x in rs]
        vols = [float(x[6] or 0) for x in rs]
        amts = [float(x[7] or 0) for x in rs]
        opens = [float(x[2] or 0) for x in rs]
        dates = [x[1] for x in rs]
        for i in range(62, n - 11):                    # 需要 60 日窗口 + 未来 10 日
            d = dates[i]
            if not (start <= d <= end):
                continue
            if closes[i - 1] <= 0 or opens[i + 1] <= 0:
                continue
            vr = vols[i] / (sum(vols[i - 5:i]) / 5) if sum(vols[i - 5:i]) > 0 else 0
            chg = (closes[i] / closes[i - 1] - 1) * 100
            hi60_prev = max(closes[i - 60:i])
            is_w = find_w_bottom(closes[:i + 1]) is not None
            is_n = closes[i] >= hi60_prev and closes[i - 1] < hi60_prev
            if not (is_w or is_n):
                continue
            thr_amt, thr_vr = (1e8, 1.0) if (is_w and not is_n) else (3e8, 1.2)
            if amts[i] < thr_amt or vr < thr_vr:
                continue
            lu = chg >= (LIMIT_UP_GEM if code[:2] in ("30", "68") else LIMIT_UP_MAIN)
            entry = opens[i + 1]
            daily[d].append({
                "code": code, "chg": chg, "amt": amts[i] / 1e8, "vr": vr, "lu": lu,
                "t5": (closes[i + 5] / entry - 1) * 100,
                "t10": (closes[i + 10] / entry - 1) * 100,
                "gap": (opens[i + 1] / closes[i] - 1) * 100,
            })
    return daily


def sector_pass(c: dict, cond: str, sec_mom: dict, sec_of: dict) -> bool:
    """该股**任一**所属板块满足 cond 即通过；无板块归属（不在 26 板块池内）→ 不通过（严格口径）。"""
    boards = sec_of.get(c["code"], [])
    if not boards:
        return False
    day = sec_mom.get(c["_date"], {})
    for b in boards:
        v = day.get(b)
        if not v:
            continue
        m1, m5, m20 = v
        ok = ((cond == "has_board" and True)                    # 对照：只要是板块成分股即可（不看涨跌）
              or (cond == "m1>0" and m1 is not None and m1 > 0)
              or (cond == "m5>0" and m5 is not None and m5 > 0)
              or (cond == "m20>0" and m20 is not None and m20 > 0)
              or (cond == "m1>0&m20>0" and m1 is not None and m1 > 0 and m20 is not None and m20 > 0)
              or (cond == "m1>0|m20>0" and ((m1 or -1) > 0 or (m20 or -1) > 0)))
        if ok:
            return True
    return False


def pick(rule: str, cands: list[dict], top: int, rng: random.Random) -> list[dict]:
    if rule == "R1_涨停优先":
        return sorted(cands, key=lambda c: (not c["lu"], -c["amt"]))[:top]
    if rule == "R2_混合≤2":
        lu = sorted([c for c in cands if c["lu"]], key=lambda c: -c["amt"])[:2]
        rest = [c for c in cands if not c["lu"]]
        rest.sort(key=lambda c: (not (0 <= c["chg"] <= 5), -c["amt"]))
        return (lu + rest[:max(0, top - len(lu))])[:top]
    if rule == "R3_全未涨停":
        rest = [c for c in cands if not c["lu"]]
        rest.sort(key=lambda c: (not (0 <= c["chg"] <= 5), -c["amt"]))
        return rest[:top]
    if rule == "R4_池内随机":
        return rng.sample(cands, min(top, len(cands)))
    if rule.startswith("R5"):
        # 与 R2 同一配额规则（涨停 ≤2 + 未涨停按 0~5% 档/成交额），前置条件已由调用方按板块过滤
        return pick("R2_混合≤2", cands, top, rng)
    raise ValueError(rule)


def evaluate(daily: dict, rule: str, top: int, rng: random.Random,
             sec_mom: dict | None = None, sec_of: dict | None = None, cond: str | None = None) -> dict:
    t5, t10, gaps, n_days, n_lu = [], [], [], 0, 0
    n_picks_per_day, n_short = [], 0
    for _d, cands in daily.items():
        for c in cands:
            c["_date"] = _d
        if cond and sec_mom is not None and sec_of is not None:
            cands = [c for c in cands if sector_pass(c, cond, sec_mom, sec_of)]
            if not cands:
                continue
        elif len(cands) < top:
            continue
        picks = pick(rule, cands, top, rng)
        if not picks:
            continue
        n_days += 1
        n_picks_per_day.append(len(picks))
        if len(picks) < top:
            n_short += 1
        n_lu += sum(1 for p in picks if p["lu"])
        n_pick = len(picks)
        t5 += [p["t5"] for p in picks]
        t10 += [p["t10"] for p in picks]
        gaps += [1 for p in picks if p["gap"] > 3]
    if not t5:
        return {}
    return {"days": n_days, "n": len(t5), "lu_share": n_lu / max(len(t5), 1) * 100,
            "per_day": (sum(n_picks_per_day) / len(n_picks_per_day)) if n_picks_per_day else 0,
            "short_days": n_short,
            "avg5": st.mean(t5), "med5": st.median(t5),
            "win5": sum(1 for x in t5 if x > 0) / len(t5) * 100,
            "avg10": st.mean(t10), "win10": sum(1 for x in t10 if x > 0) / len(t10) * 100,
            "gap3": sum(gaps) / max(len(t5), 1) * 100}


def main() -> int:
    ap = argparse.ArgumentParser(description="比较不同选股规则的前瞻收益")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--start", default="2025-08-01")
    ap.add_argument("--end", default="2026-08-20")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sector-dir", help="板块指数历史缓存目录（long_*.json，见 sector_map/sector_pool）")
    ap.add_argument("--sector-map", help="sector_members.json 路径")
    a = ap.parse_args()

    print(f"═══ 构建候选（{a.start} ~ {a.end}）═══")
    daily = build_candidates(a.parquet, a.start, a.end)
    tot = sum(len(v) for v in daily.values())
    print(f"  有候选的交易日 {len(daily)} 天，候选合计 {tot} 条"
          f"（日均 {tot/max(len(daily),1):.1f}）")

    rng = random.Random(a.seed)
    sec_mom, sec_of = {}, {}
    if a.sector_dir and a.sector_map:
        print("\n═══ 加载板块动量与个股↔板块映射 ═══")
        sec_mom = load_sector_momentum(a.sector_dir)
        sec_of = load_sector_of(a.sector_map)
        cover = sum(1 for v in daily.values() for c in v if sec_of.get(c["code"]))
        tot_c = sum(len(v) for v in daily.values())
        print(f"  板块-日 组合 {len(sec_mom)} 天；候选中有板块归属 {cover}/{tot_c}（{cover/max(tot_c,1)*100:.0f}%）")

    print(f"\n{'规则':<16}{'交易日':>7}{'样本':>7}{'日均只数':>9}{'不足5只天数':>11}{'涨停占比':>9}"
          f"{'T+5均值':>10}{'T+5中位':>10}{'T+5胜率':>9}{'T+10均值':>10}{'次日高开>3%':>11}")
    res = {}
    for rule in ["R1_涨停优先", "R2_混合≤2", "R3_全未涨停", "R4_池内随机"]:
        m = evaluate(daily, rule, a.top, rng)
        res[rule] = m
        if not m:
            print(f"  {rule:<14} 无样本")
            continue
        print(f"  {rule:<14}{m['days']:>7}{m['n']:>7}{m['per_day']:>9.2f}{m['short_days']:>11}{m['lu_share']:>8.1f}%"
              f"{m['avg5']:>10.3f}{m['med5']:>10.3f}{m['win5']:>8.1f}%{m['avg10']:>10.3f}{m['gap3']:>10.1f}%")

    if sec_mom and sec_of:
        for cond in ["has_board", "m1>0", "m5>0", "m20>0", "m1>0&m20>0", "m1>0|m20>0"]:
            rule = f"R5_板块{cond}"
            m = evaluate(daily, rule, a.top, rng, sec_mom, sec_of, cond)
            res[rule] = m
            if not m:
                print(f"  {rule:<14} 无样本")
                continue
            print(f"  {rule:<14}{m['days']:>7}{m['n']:>7}{m['per_day']:>9.2f}{m['short_days']:>11}{m['lu_share']:>8.1f}%"
                  f"{m['avg5']:>10.3f}{m['med5']:>10.3f}{m['win5']:>8.1f}%{m['avg10']:>10.3f}{m['gap3']:>10.1f}%")

    base = res.get("R2_混合≤2", {})
    print("\n═══ 与 R2（当前 v1.3 规则）的差 ═══")
    for k, m in res.items():
        if k in ("R1_涨停优先", "R2_混合≤2") or not m or not base:
            continue
        print(f"  {k:<20} T+5 {m['avg5']-base['avg5']:+.3f}pct  胜率 {m['win5']-base['win5']:+.1f}pt  "
              f"日均 {m['per_day']:.2f} 只  T+10 {m['avg10']-base['avg10']:+.3f}pct")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
