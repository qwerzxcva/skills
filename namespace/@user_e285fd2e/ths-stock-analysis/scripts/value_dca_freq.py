# -*- coding: utf-8 -*-
"""能力 #13 · 定投频率回测（每日 / 每周 / 每两周 / 每月）。

【回答什么问题】「美股我习惯每日定投，跟每月有区别吗？」
用户对报告里「美股宽基 = 定投」是清楚的，但**日报 vs 月报的差别**需要实测，不能凭感觉。

【口径（必须随结论一起讲）】
- **同窗口、同一总投入**：设月预算 B，则每日投入 `B ÷ 月均交易日`、每周 `B ÷ 4.333`、
  每月 `B`（取当月首个交易日）。这样各频率的**总投入几乎相等**，比期末市值才干净。
- 数据源 `fund history`（ETF 日线）。⚠️ 接口窗口上限 5 年（坑 74），所以样本有限。
- **用未复权价格**：ETF 现金分红被除权剔除 → 系统性低估；对分红多的品种（红利低波、债券）低估最大。
  ⚠️ **但四档频率用的是同一价格序列，低估是共同的**，所以**频率之间的比较仍然有效**。
- 不看单一起点：同时给**滚动起点**（每季度一个起点）的分布 —— 单起点容易得出相反结论。

【结论方向（预期，需实测确认）】
长期上行的资产里，**每日定投 ≈ 每月定投**，差别通常在小数点后；因为定投的收益主要来自
「长期上行 + 波动摊薄」，**频率只是把同一笔钱早投几天**。真正的变量是**投多久**和**投什么**。

用法：
    python value_dca_freq.py                          # 默认 4 个标的、月预算 1000
    python value_dca_freq.py --codes 513500.SH --monthly 2780
    python value_dca_freq.py --selftest
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ths_cli  # noqa: E402

CST = timezone(timedelta(hours=8))
DEFAULT_CODES = [("513500.SH", "标普500ETF"), ("513100.SH", "纳指100ETF"),
                 ("512890.SH", "红利低波ETF"), ("518880.SH", "黄金ETF")]
FREQS = ("每日", "每周", "每两周", "每月")


def _ms(d: str) -> str:
    return str(int(datetime.fromisoformat(d).replace(tzinfo=CST).timestamp() * 1000))


def fetch(code: str, start: str, end: str) -> list[tuple[str, float]]:
    j = ths_cli.run(["fund", "history", "--thscode", code, "--start-ms", _ms(start),
                     "--end-ms", _ms(end), "--format", "json"], timeout=180)
    items = (j.get("data") or {}).get("item") or []
    out = []
    for it in items:
        ms, px = it.get("date_ms"), it.get("close_price")
        if not ms or not px:
            continue
        d = datetime.fromtimestamp(ms / 1000, CST).strftime("%Y-%m-%d")
        out.append((d, float(px)))
    out.sort()
    return out


def irr(cfs: list[tuple[str, float]], final_value: float) -> float | None:
    """资金加权年化（bisection）。cfs = [(日期, 现金流为负=投入)]。"""
    if not cfs or final_value <= 0:
        return None
    t0 = datetime.fromisoformat(cfs[0][0])
    def npv(r: float) -> float:
        v = 0.0
        for d, cf in cfs:
            yrs = (datetime.fromisoformat(d) - t0).days / 365.25
            v += cf / (1.0 + r) ** yrs
        return v + final_value / (1.0 + r) ** ((datetime.fromisoformat(cfs[-1][0]) - t0).days / 365.25)
    lo, hi = -0.95, 3.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _hits(series: list[tuple[str, float]], freq: str) -> list[int]:
    """返回该频率的**买入下标**（先算命中，再按命中数定每笔金额 → 保证各频率总投入相等）。"""
    idx: list[int] = []
    last_key = None
    for i, (d, _px) in enumerate(series):
        dt = datetime.fromisoformat(d)
        if freq == "每日":
            hit = True
        elif freq == "每月":
            hit = (dt.year, dt.month) != last_key
            last_key = (dt.year, dt.month)
        elif freq == "每周":
            hit = dt.isocalendar()[1] != last_key
            last_key = dt.isocalendar()[1]
        else:                                     # 每两周：ISO 周奇偶交替
            wk = dt.isocalendar()[1] % 2
            hit = wk != last_key
            last_key = wk
        if hit:
            idx.append(i)
    return idx


def simulate(series: list[tuple[str, float]], freq: str, monthly: float) -> dict:
    """按频率投入 → 期末市值 / 总投入 / 收益率 / IRR / 平均成本。

    ⚠️ **同预算口径**：每笔金额 = `月预算 × 月数 ÷ 该频率的买入笔数`，
    这样四种频率的**总投入几乎完全相等**，比期末市值才公平（否则「每日」会因为笔数多而多投）。
    """
    if not series:
        return {}
    months = len({d[:7] for d, _ in series}) or 1
    idx = _hits(series, freq)
    if not idx:
        return {}
    per = monthly * months / len(idx)
    units, invested = 0.0, 0.0
    cfs: list[tuple[str, float]] = []
    for i in idx:
        d, px = series[i]
        if px > 0:
            units += per / px
            invested += per
            cfs.append((d, -per))
    if invested <= 0 or units <= 0:
        return {}
    final = units * series[-1][1]
    return {"invested": invested, "value": final, "ret": final / invested - 1,
            "irr": irr(cfs, final), "avg_cost": invested / units, "last_px": series[-1][1],
            "n_buys": len(idx), "units": units}


def rolling(series: list[tuple[str, float]], months: int, bud: float) -> dict:
    """滚动起点（每季度一个）→ 各频率的总收益率分布。"""
    out = {f: [] for f in FREQS}
    n = len(series)
    step = max(1, int(21 * 3))
    min_len = int(21 * months)
    for s in range(0, max(1, n - min_len), step):
        seg = series[s:]
        if len(seg) < min_len:
            break
        for f in FREQS:
            r = simulate(seg, f, bud)
            if r:
                out[f].append(r["ret"])
    return out


def report(codes, start, end, monthly) -> None:
    print("═" * 96)
    print(f"能力 #13 · 定投频率回测  窗口 {start} ~ {end}  月预算 {monthly:,.0f} 元  ⚠️ 未复权价格（低估分红）")
    print("═" * 96)
    for code, name in codes:
        series = fetch(code, start, end)
        if len(series) < 60:
            print(f"\n{name} {code}：数据不足（{len(series)} 条），跳过")
            continue
        yrs = len(series) / 252.0
        print(f"\n▌ {name} {code}   {series[0][0]} ~ {series[-1][0]}（{len(series)} 交易日 / {yrs:.2f} 年）")
        print(f"  起始净值 {series[0][1]:.4f} → 期末 {series[-1][1]:.4f}"
              f"（价格 {series[-1][1]/series[0][1]-1:+.1%}）")
        print(f"  {'频率':<8}{'投入':>12}{'期末市值':>13}{'总收益':>10}{'年化IRR':>10}"
              f"{'平均成本':>10}{'期数':>7}")
        base = None
        for f in FREQS:
            r = simulate(series, f, monthly)
            if not r:
                continue
            if base is None:
                base = r["value"]
            print(f"  {f:<8}{r['invested']:>12,.0f}{r['value']:>13,.0f}{r['ret']:>9.1%}"
                  f"{(r['irr'] or 0):>10.2%}{r['avg_cost']:>10.4f}{r['n_buys']:>7}")
        print(f"  → 每日 vs 每月：期末市值差 {'':>4}"
              f"{(simulate(series,'每日',monthly)['value'] / simulate(series,'每月',monthly)['value'] - 1):+.2%}")

    # 滚动起点（以第一个标的为例，避免单起点偏差）
    code0, name0 = codes[0]
    s0 = fetch(code0, start, end)
    if len(s0) > 252 * 2:
        band = rolling(s0, 24, monthly)
        print(f"\n▌ 滚动起点分布（{name0}，各起点至少 24 个月，每季度一个起点）")
        print(f"  {'频率':<8}{'样本':>6}{'中位总收益':>12}{'最好':>10}{'最差':>10}{'标准差':>10}")
        for f in FREQS:
            v = band[f]
            if len(v) < 3:
                continue
            print(f"  {f:<8}{len(v):>6}{statistics.median(v):>11.1%}"
                  f"{max(v):>10.1%}{min(v):>10.1%}{statistics.pstdev(v):>10.2%}")


def selftest() -> int:
    """负例自证：单调上涨 / 单调下跌 / V 型 三种合成曲线上，频率效应方向必须符合预期。"""
    print("=" * 72)
    print("value_dca_freq 自检")
    print("=" * 72)
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails += 1

    def mk(prices):
        d0 = datetime(2024, 1, 1)
        return [((d0 + timedelta(days=i)).strftime("%Y-%m-%d"), p)
                for i, p in enumerate(prices)]

    # ① 单调上涨：买得越早越便宜 → **每月 ≥ 每日**（月首一次买 vs 摊到每天，平均买入时点更晚）
    up = mk([1.0 * (1.003 ** i) for i in range(504)])
    du, mo = simulate(up, "每日", 1000), simulate(up, "每月", 1000)
    chk(mo["ret"] > du["ret"], f"单调上涨：每月 ≥ 每日（{mo['ret']:.2%} vs {du['ret']:.2%}）")

    # ② 单调下跌：买得越晚越便宜 → **每日 ≥ 每月**
    dn = mk([1.0 * (0.997 ** i) for i in range(504)])
    dud, mod = simulate(dn, "每日", 1000), simulate(dn, "每月", 1000)
    chk(dud["ret"] > mod["ret"], f"单调下跌：每日 ≥ 每月（{dud['ret']:.2%} vs {mod['ret']:.2%}）")

    # ③ 来回震荡：差异应当很小 —— 这正是"频率几乎不重要"的场景
    zig = mk([1.0 + (0.25 if (i // 21) % 2 else 0.0) - (0.06 if i % 2 else 0.0) for i in range(504)])
    dz, mz = simulate(zig, "每日", 1000), simulate(zig, "每月", 1000)
    chk(abs(dz["ret"] - mz["ret"]) < 0.05,
        f"来回震荡：每日与每月差异很小（{abs(dz['ret']-mz['ret']):.2%} < 5%）")

    # ④ 同预算口径：四档**总投入必须相等**（否则比较不成立）
    inv = {f: simulate(up, f, 1000)["invested"] for f in FREQS}
    chk(max(inv.values()) / min(inv.values()) < 1.001,
        f"同预算口径：四档总投入相等（{min(inv.values()):,.0f} ~ {max(inv.values()):,.0f}）")

    print(f"\n  自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 · 定投频率回测（每日/每周/每两周/每月）")
    ap.add_argument("--codes", help="逗号分隔 thscode（默认 4 个代表标的）")
    ap.add_argument("--start", default="2021-11-09")
    ap.add_argument("--end", default="2026-10-08")
    ap.add_argument("--monthly", type=float, default=1000.0, help="月预算（元）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    codes = DEFAULT_CODES
    if a.codes:
        codes = [(c.strip().upper(), c.strip().upper()) for c in a.codes.split(",") if c.strip()]
    report(codes, a.start, a.end, a.monthly)
    return 0


if __name__ == "__main__":
    sys.exit(main())
