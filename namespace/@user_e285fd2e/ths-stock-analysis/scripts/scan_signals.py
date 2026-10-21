# -*- coding: utf-8 -*-
"""全市场形态信号扫描（能力 #1 回测最优范式 → 能力 #12 候选池的形态维度）。

两个信号源（口径与 `bt_backtest.py` 完全一致，勿各写一份）：
- **A 信号源 W底双底突破**：`find_w_bottom()` 与 `bt_backtest.py` 同款逻辑
  （回测 20 策略里 W底 +76.3% / 回撤 -23.1% 最优）
- **B 信号源 60 日新高放量突破**：海龟唐奇安 / 新高突破族（回测 +79.0% 的形态近亲）

筛选口径（两条信号通用）：universe = 沪深主板 + 创业板（60/00/30）；
金额与量比门槛 —— W底 `金额 ≥ 1 亿 且 量比 ≥ 1.0`；新高 `金额 ≥ 3 亿 且 量比 ≥ 1.2`；
均为**「新触发」**（前一交易日不满足）；量比 = 当日量 ÷ 前 5 日均量。

输入：前复权日K parquet（`thscode/date/open/high/low/close/volume/amount`，由 `db export` 自 `v_daily_qfq` 导出）
输出：`w_scan_MMDD.json`、`trend_scan_MMDD.json`、`ranges_MMDD.json`（候选 1/5/20/60 日区间涨幅，妖股剔除用）

用法：
    python scan_signals.py --date 2026-09-21 --parquet <file.parquet> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

import duckdb


def find_w_bottom(closes, tol=0.05, min_gap=5, lookback=60):
    """与 bt_backtest.py v3.6 完全同款（唯一实现）。返回 (neck, L2, L1_idx, L2_idx) 或 None。"""
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
    return neck, L2, L1_idx, L2_idx


def scan(parquet: str, target: str) -> tuple[list, list, dict]:
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT thscode, CAST(date AS VARCHAR) AS d, close, high, volume, amount
        FROM '{parquet}' WHERE substr(thscode,1,2) IN ('60','00','30') ORDER BY thscode, d
    """).fetchall()
    con.close()
    series = defaultdict(lambda: {"d": [], "close": [], "high": [], "vol": [], "amt": []})
    for thscode, d, close, high, vol, amt in rows:
        s = series[thscode]
        s["d"].append(d)
        s["close"].append(float(close or 0))
        s["high"].append(float(high or 0))
        s["vol"].append(float(vol or 0))
        s["amt"].append(float(amt or 0))

    w_items, t_items, all_stats = [], [], {}
    for code, s in series.items():
        closes = s["close"]
        if len(closes) < 62 or s["d"][-1] != target:
            continue
        vols, amt = s["vol"], s["amt"][-1]
        vr = vols[-1] / (sum(vols[-6:-1]) / 5) if sum(vols[-6:-1]) > 0 else 0
        up_pct = (closes[-1] / closes[-2] - 1) * 100

        def ret(n, _c=closes):
            return round((_c[-1] / _c[-(n + 1)] - 1) * 100, 2) if len(_c) > n and _c[-(n + 1)] > 0 else None
        stats = {"r1": ret(1), "r5": ret(5), "r20": ret(20), "r60": ret(60)}
        all_stats[code] = stats

        wb = find_w_bottom(closes)
        if wb is not None:
            neck, L2, _L1i, _L2i = wb
            prev = find_w_bottom(closes[:-1])
            if prev is None or prev[0] < closes[-2]:          # 新触发
                if amt >= 1e8 and vr >= 1.0:
                    w_items.append({"thscode": code, "date": s["d"][-1], "close": round(closes[-1], 2),
                                    "neck": round(neck, 2), "L2": round(L2, 2),
                                    "break_pct": round(up_pct, 2), "amount_yi": round(amt / 1e8, 2),
                                    "vol_ratio": round(vr, 2),
                                    "above_neck_pct": round((closes[-1] / neck - 1) * 100, 2), **stats})
        hi60 = max(closes[-60:])
        if closes[-1] >= hi60 and closes[-2] < hi60 and amt >= 3e8 and vr >= 1.2:
            t_items.append({"thscode": code, "date": s["d"][-1], "close": round(closes[-1], 2),
                            "hi60": round(hi60, 2), "ret5": stats["r5"],
                            "break_pct": round(up_pct, 2), "amount_yi": round(amt / 1e8, 2),
                            "vol_ratio": round(vr, 2), **stats})
    return (sorted(w_items, key=lambda x: -x["amount_yi"]),
            sorted(t_items, key=lambda x: -x["amount_yi"]), all_stats)


def main() -> int:
    ap = argparse.ArgumentParser(description="全市场 W底 / 60日新高 形态信号扫描")
    ap.add_argument("--date", required=True)
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--out", required=True, help="输出目录（同目录也会写 ranges_MMDD.json）")
    a = ap.parse_args()
    mmdd = a.date.replace("-", "")[4:]

    w, t, stats = scan(a.parquet, a.date)
    json.dump({"date": a.date, "count": len(w), "items": w},
              open(os.path.join(a.out, f"w_scan_{mmdd}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"date": a.date, "count": len(t), "items": t},
              open(os.path.join(a.out, f"trend_scan_{mmdd}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(stats, open(os.path.join(a.out, f"ranges_{mmdd}.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    print(f"标的数（含 60/00/30）= {len(stats)}")
    print(f"\n信号A W底新触发: {len(w)} 只")
    for r in w[:20]:
        print(f"  W {r['thscode']} c={r['close']} 颈线={r['neck']} 日涨={r['break_pct']:+.1f}% "
              f"额={r['amount_yi']}亿 量比={r['vol_ratio']} 高颈线={r['above_neck_pct']}% "
              f"| 5日{r['r5']}% 20日{r['r20']}% 60日{r['r60']}%")
    print(f"\n信号B 60日新高放量: {len(t)} 只")
    for r in t[:20]:
        print(f"  N {r['thscode']} c={r['close']} 60hi={r['hi60']} 日涨={r['break_pct']:+.1f}% "
              f"5日={r['ret5']:+.1f}% 额={r['amount_yi']}亿 量比={r['vol_ratio']} "
              f"| 20日{r['r20']}% 60日{r['r60']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
