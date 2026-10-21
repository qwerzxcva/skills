# -*- coding: utf-8 -*-
"""板块轮动计算（能力 #7 的核心口径）：26 板块 1/5/20/60 日动量 + 量比 + 20 日超额（vs 上证）。

口径（唯一实现，报告与选股链路都取这里）：
- 动量 = 板块指数**收盘价**涨跌幅（1/5/20/60 交易日）
- 量比 = 5 日均成交额 / 20 日均成交额（>1 放量）—— 与个股「今量÷前5日均量」口径不同，勿混用
- 超额 = 板块 20 日涨幅 − 上证同期 20 日涨幅
- 板块池 = `sector_pool.SECTORS`（权威 26 个）

输入：`<idx-dir>/idx_<CODE>.json`（`index history --source remote --format json` 的落盘，见 daily_prep.py 取数）
输出：`<out>/rotation_YYYYMMDD.json`

用法：
    python calc_rotation.py --date 2026-09-21 --idx-dir <dir> [--out <dir>]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sector_pool  # noqa: E402

MIN_BARS = 61          # 需 ≥61 根才能算 60 日动量


def hist_series(idx_dir: str, code: str):
    """读 idx_<CODE>.json → [{d(ms), c(close), t(turnover)}]；缺失/异常返回 None。"""
    p = os.path.join(idx_dir, f"idx_{code.replace('.', '_')}.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    out = []
    for x in (d.get("data") or {}).get("item") or []:
        c = float(x.get("close_price") or 0)
        if c > 0:
            out.append({"d": x.get("date_ms"), "c": c,
                        "t": float(x.get("turnover") or x.get("amount") or 0)})
    return out or None


def mom(closes: list[float], n: int):
    if len(closes) <= n or closes[-(n + 1)] == 0:
        return None
    return (closes[-1] / closes[-(n + 1)] - 1) * 100


def fmt(ms) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def compute(idx_dir: str, target: str) -> dict:
    problems: list[str] = []
    sh = hist_series(idx_dir, sector_pool.BENCHMARK[0])
    if not sh:
        raise SystemExit(f"缺基准 {sector_pool.BENCHMARK[0]}（期望 {idx_dir}/idx_000001_SH.json）")
    sh_m20 = mom([x["c"] for x in sh], 20)
    rows = []
    for code, name in sector_pool.SECTORS.items():
        s = hist_series(idx_dir, code)
        if not s or len(s) < MIN_BARS:
            problems.append(f"[MISSING] {name} {code} n={len(s) if s else 0}")
            continue
        latest = fmt(s[-1]["d"])
        if latest != target:
            problems.append(f"[STALE] {name} {code} 最新={latest}")
        cs = [x["c"] for x in s]
        ts = [x["t"] for x in s]
        v5 = sum(ts[-5:]) / 5 if len(ts) >= 5 else 0
        v20 = sum(ts[-20:]) / 20 if len(ts) >= 20 else 0
        rows.append({"name": name, "code": code,
                     "m1": round(mom(cs, 1) or 0, 2), "m5": round(mom(cs, 5) or 0, 2),
                     "m20": round(mom(cs, 20) or 0, 2), "m60": round(mom(cs, 60) or 0, 2),
                     "vr": round(v5 / v20, 2) if v20 > 0 else 0,
                     "amt": round(ts[-1] / 1e8, 1), "last_c": round(cs[-1], 2)})
    for r in rows:
        r["ex20"] = round(r["m20"] - (sh_m20 or 0), 2)
    rows.sort(key=lambda x: -x["m20"])
    return {"date": target, "sh_date": fmt(sh[-1]["d"]), "sh_close": round(sh[-1]["c"], 2),
            "sh_m20": round(sh_m20 or 0, 2), "sh_amt": round(sh[-1]["t"] / 1e8, 1),
            "rows": rows, "problems": problems}


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="板块轮动计算（26 板块多窗口动量 + 量比 + 超额）")
    ap.add_argument("--date", required=True, help="目标交易日 YYYY-MM-DD")
    ap.add_argument("--idx-dir", required=True, help="idx_*.json 所在目录")
    ap.add_argument("--out", help="rotation_YYYYMMDD.json 输出目录（默认同 --idx-dir）")
    a = ap.parse_args()

    out = compute(a.idx_dir, a.date)
    rows, probs = out["rows"], out["problems"]
    print(f"上证 最新={out['sh_date']} 收={out['sh_close']:.2f} 20日={out['sh_m20']:+.2f}% (基准)")
    print(f"\n按 20日动量排序（{len(rows)} 板块）：名称 / 1日 / 5日 / 20日 / 60日 / 量比 / 成交亿 / 20日超额")
    for r in rows:
        print(f"  {r['name']:10s} {r['m1']:+7.2f} {r['m5']:+7.2f} {r['m20']:+8.2f} {r['m60']:+8.2f} "
              f"vr={r['vr']:.2f} {r['amt']:8.1f}亿 ex20={r['ex20']:+7.2f}")
    op = os.path.join(a.out or a.idx_dir, f"rotation_{a.date.replace('-', '')}.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n落盘 -> {op}（problems={len(probs)}）")
    for p in probs:
        print("  ", p)
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
