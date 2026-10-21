# -*- coding: utf-8 -*-
"""能力 #13 价值投资 · 「A股宽基到底是不是震荡上行 / 定投凭什么赚钱」实测证据（可复现，不猜数）

【为什么需要它】用户质疑：①「A股宽基满足震荡上行吗？我怎么感觉一直在震荡」②「定投凭什么赚钱」。
这类问题不能用文字回答，必须给**可复现的实测数字**，而且**口径必须讲清楚** —— 同一段时间，用不同口径算出来的
A股收益能差 10 个百分点。本脚本把三种口径并列算出，谁也不能单独拿去当结论：

  口径 A · **等权·每日再平衡**（理论组合）        → 含波动收割，代表"分散 + 纪律再平衡"的上限
  口径 B · **等权·月度再平衡**                    → 同上，但只调月频，更接近真实可执行
  口径 C · **等权·买入持有**（= 个股收益算术平均）→ 完全不交易，最保守
  口径 D · **个股收益分布**（中位数 / 亏损占比 / 前30只贡献）→ 回答"随机买一只会怎样"
  口径 E · **官方指数**（沪深300 / 中证500，接口窗口 ≤5 年）→ 回答"买市值加权宽基能拿到什么"

【关键结论（本脚本要证明的两件事）】
1. **分布极度右偏**：近 10 年 A股个股收益中位数 −22.5%、64% 的股票亏损，但算术平均 +25.2%
   —— 前 30 只（1.2%）贡献 67.7% 的总收益。所以"分散"和"选对指数"比"择时"重要得多。
2. **再平衡有增益**：同一条 A股序列，买入持有 +2.3%/年 → 月度再平衡 +7.5%/年（约 +5pct/年）
   —— 这就是"指数基金定期调整成分"的价值来源，也是定投在**高波动**市场里的第二重收益。

【口径声明（必须随结论一起讲）】
- 数据源：本地 DuckDB `v_daily_qfq`（**前复权，含分红再投**），2016-08-22 起。
  指数序列经 `ths_cli index history`（**接口窗口上限 5 年**，故指数只能算近 5 年）。
- 个股收益按 ±25% 截尾（防数据异常），当日有效样本 <200 只的日子剔除。
- **未计交易成本 / 税费 / 跟踪误差 / 申赎费率**；再平衡序列假设零成本换仓。
- IRR 用二分法解月现金流内部收益率（年化），比「总收益 ÷ 年数」严谨。

用法：
    python value_evidence.py                                  # 全线 + 近4.5年，落盘 evidence.json
    python value_evidence.py --workspace <ws> --date 2026-09-28
    python value_evidence.py --selftest                        # 自检指标函数（合成序列）
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE_DIR = os.path.join(".workbuddy", "output", "value_hist")
TRADING_DAYS = 252
MONTH = 21          # 每月交易日近似值
RF = 0.02           # 无风险利率（年化），仅用于夏普
OUTLIER = 0.25      # 个股日收益截尾阈值
MIN_BREADTH = 200   # 当日最少有效样本


# ================= 基础指标 =================
def cum_curve(rets: list[float]) -> list[float]:
    """日/月收益序列 → 累计净值曲线（起点 1.0）。"""
    out, v = [], 1.0
    for r in rets:
        v *= (1.0 + r)
        out.append(v)
    return out


def ann_return(total_mult: float, years: float) -> float:
    if years <= 0 or total_mult <= 0:
        return float("nan")
    return total_mult ** (1.0 / years) - 1.0


def max_drawdown(curve: list[float]) -> float:
    """最大回撤（负数，如 -0.431 表示 -43.1%）。"""
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def ann_vol(rets: list[float]) -> float:
    n = len(rets)
    if n < 2:
        return float("nan")
    m = sum(rets) / n
    var = sum((x - m) ** 2 for x in rets) / (n - 1)
    return (var ** 0.5) * (TRADING_DAYS ** 0.5)


def sharpe(rets: list[float]) -> float:
    v = ann_vol(rets)
    if not v or v != v:
        return float("nan")
    m = sum(rets) / len(rets)
    return ((1 + m) ** TRADING_DAYS - 1 - RF) / v


def median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def pct(xs: list[float], q: float) -> float:
    """分位数（q ∈ [0,1]）。"""
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def irr_monthly(value: float, n_months: int) -> float:
    """月现金流（每期 -1，期末 +value）的内部收益率 → 年化。二分法。"""
    lo, hi = -0.95, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        pv = sum(-1.0 / ((1 + mid) ** t) for t in range(1, n_months + 1)) + value / ((1 + mid) ** n_months)
        if pv > 0:
            lo = mid
        else:
            hi = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def monthly_rebalance(daily: list[float]) -> list[float]:
    """日收益序列 → 月度再平衡的月收益序列。"""
    out = []
    for i in range(0, len(daily) - MONTH + 1, MONTH):
        v = 1.0
        for r in daily[i:i + MONTH]:
            v *= (1 + r)
        out.append(v - 1.0)
    return out


def dca_from_curve(curve: list[float], months: int, step: int = 1) -> dict:
    """在净值曲线上做月度定投：每月等额买入、期末不止盈。"""
    idxs = list(range(MONTH - 1, len(curve), MONTH))
    res, irrs = [], []
    for k in range(0, len(idxs) - months, step):
        buyp = idxs[k:k + months]
        end = idxs[k + months] if (k + months) < len(idxs) else len(curve) - 1
        units = sum(1.0 / curve[i] for i in buyp)
        value = units * curve[end]
        res.append(value / len(buyp) - 1.0)
        irrs.append(irr_monthly(value, len(buyp)))
    if not res:
        return {}
    return {"months": months, "samples": len(res), "median_total": median(res),
            "win_rate": sum(1 for x in res if x > 0) / len(res),
            "median_irr": median(irrs), "worst": min(res), "best": max(res)}


def rolling_hold(curve: list[float], years: float, step: int = 5) -> dict:
    """滚动持有 N 年：所有起点的年化收益分布。"""
    n = int(years * TRADING_DAYS)
    res = [ann_return(curve[i + n] / curve[i], years) for i in range(0, len(curve) - n, step)]
    if not res:
        return {}
    return {"n_years": years, "samples": len(res), "median": median(res),
            "win_rate": sum(1 for x in res if x > 0) / len(res),
            "worst": min(res), "best": max(res)}


# ================= 数据源 =================
def _con():
    import duckdb
    import ths_cli
    return duckdb.connect(ths_cli.duckdb_path(), read_only=True)


def load_daily_series(date_from: str, date_to: str | None = None):
    """本地 DuckDB → 每日横截面（等权均值 / 中位数）日收益序列。"""
    con = _con()
    q = """
    WITH r AS (
      SELECT thscode, date, close, LAG(close) OVER (PARTITION BY thscode ORDER BY date) AS pc
      FROM v_daily_qfq WHERE date >= DATE '{d0}' {d1}
    ),
    g AS (SELECT date, (close/pc - 1.0) AS ret FROM r WHERE pc IS NOT NULL AND pc > 0 AND close > 0)
    SELECT date, AVG(ret) AS eq, MEDIAN(ret) AS med, COUNT(*) AS n
    FROM g WHERE ret BETWEEN -{o} AND {o}
    GROUP BY date HAVING COUNT(*) >= {mb} ORDER BY date
    """.format(d0=date_from, d1=(f"AND date <= DATE '{date_to}'" if date_to else ""),
               o=OUTLIER, mb=MIN_BREADTH)
    rows = con.execute(q).fetchall()
    con.close()
    return ([str(r[0]) for r in rows], [float(r[1]) for r in rows], [float(r[2]) for r in rows])


def load_distribution(date_from: str, date_to: str | None = None) -> dict:
    """个股「买入并持有」收益分布 —— 回答「随机买一只会怎样」。"""
    con = _con()
    end = f"DATE '{date_to}'" if date_to else "(SELECT max(date) FROM v_daily_qfq)"
    q = f"""
    WITH f AS (SELECT thscode, close FROM v_daily_qfq WHERE date = DATE '{date_from}'),
         l AS (SELECT thscode, close FROM v_daily_qfq WHERE date = {end})
    SELECT l.close/f.close - 1.0 AS ret FROM f JOIN l USING(thscode) WHERE f.close > 0 AND l.close > 0
    """
    rets = sorted(float(x[0]) for x in con.execute(q).fetchall())
    con.close()
    n = len(rets)
    if n < 100:
        return {"samples": n}
    mean = sum(rets) / n
    top30 = sorted(rets, reverse=True)[:30]
    tot = sum(rets)
    return {"samples": n, "mean_total": mean, "median_total": median(rets),
            "q25": pct(rets, 0.25), "q75": pct(rets, 0.75),
            "loss_ratio": sum(1 for x in rets if x < 0) / n,
            "double_ratio": sum(1 for x in rets if x > 1) / n,
            "halve_ratio": sum(1 for x in rets if x < -0.5) / n,
            "top30_avg": sum(top30) / 30,
            "top30_share": (sum(top30) / tot) if tot > 0 else float("nan"),
            "top30_count_ratio": 30 / n}


SAFE_MARGIN_DAYS = 40  # 5 年窗口按自然日算，贴边（±0 天）会被判超限返回空 → 留出边距（坑 74）


def load_series(code: str, end: str, years: float = 4.7, kind: str = "index") -> tuple[list[str], list[float]]:
    """ths_cli 取 (日期, 收盘)。kind='index' 用 index history、'fund' 用 fund history。
    接口窗口上限 5 年（**按自然日算，贴边也会返回空**）、且结束日必须在近期（坑 74）→ 留 SAFE_MARGIN_DAYS 边距。"""
    import ths_cli
    end_d = datetime.datetime.strptime(end, "%Y-%m-%d")
    span = min(int(years * 365.25), int(5 * 365.25) - SAFE_MARGIN_DAYS)
    start_d = end_d - datetime.timedelta(days=span)
    ms = lambda d: str(int(d.timestamp() * 1000))
    cmd = "index" if kind == "index" else "fund"
    j = ths_cli.run([cmd, "history", "--thscode", code, "--start-ms", ms(start_d),
                     "--end-ms", ms(end_d), "--source", "remote", "--format", "json"], timeout=90)
    items = ((j.get("data") or {}).get("item")) or []
    days, px = [], []
    for it in items:
        c = it.get("close_price")
        if not c:
            continue
        days.append(datetime.datetime.fromtimestamp(it["date_ms"] / 1000).strftime("%Y-%m-%d"))
        px.append(float(c))
    return days, px


def load_index(code: str, end: str, years: float = 4.7) -> tuple[list[str], list[float]]:
    """向后兼容包装（口径 E 用）。"""
    return load_series(code, end, years, kind="index")


# 同窗口跨资产对比：(代码, 名称, 类型) —— 用于回答「哪类资产适合定投 / A股 vs 美股」
COMPARE = [
    ("000300.SH", "沪深300（A股大盘 · 价格指数）", "index"),
    ("000905.SH", "中证500（A股中盘 · 价格指数）", "index"),
    ("513500.SH", "标普500ETF（QDII · 价格）", "fund"),
    ("513100.SH", "纳指100ETF（QDII · 价格）", "fund"),
    ("512890.SH", "红利低波ETF（价格）", "fund"),
    ("518880.SH", "黄金ETF（价格）", "fund"),
]


def compare_window(end: str, years: float = 5.0, items=None) -> dict:
    """同一时间窗内、同一口径下的跨资产对比：一次性 vs 月定投 + 波动率。
    ⚠️ ETF 用**未复权价格**（分红被除权剔除，会低估真实收益）；指数为**价格指数**（不含分红）。"""
    out = {}
    for code, name, kind in (items or COMPARE):
        try:
            d, p = load_series(code, end, years, kind=kind)
        except Exception as e:  # noqa: BLE001
            out[code] = {"name": name, "error": str(e)[:100]}
            continue
        if len(p) < 200:
            out[code] = {"name": name, "error": f"样本不足（{len(p)}）"}
            continue
        c = [x / p[0] for x in p]
        rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        yr = len(p) / TRADING_DAYS
        idxs = list(range(MONTH - 1, len(c), MONTH))
        units = sum(1.0 / c[i] for i in idxs)
        out[code] = {"name": name, "kind": kind, "start": d[0], "end": d[-1], "days": len(p),
                     "years": yr, "mult": c[-1], "ann": ann_return(c[-1], yr),
                     "mdd": max_drawdown(c), "vol": ann_vol(rets),
                     "dca_total": units * c[-1] / len(idxs) - 1.0,
                     "dca_irr": irr_monthly(units * c[-1], len(idxs)), "months": len(idxs)}
    return out


def fmt_compare(cmp: dict, title: str) -> str:
    L = ["", f"  同窗口跨资产对比：{title}", ""]
    L.append(f"  {'资产':<28}{'一次性年化':>11}{'最大回撤':>10}{'年化波动':>10}{'月定投总收益':>13}{'月定投IRR':>11}")
    for code, v in cmp.items():
        if v.get("error"):
            L.append(f"  {v['name']:<28} 取数失败：{v['error']}")
            continue
        L.append(f"  {v['name']:<28}{v['ann']*100:>10.2f}%{v['mdd']*100:>9.1f}%{v['vol']*100:>9.1f}%"
                 f"{v['dca_total']*100:>12.1f}%{v['dca_irr']*100:>10.2f}%")
    return "\n".join(L)


def analyze(date_from: str, date_to: str | None, label: str, with_index: bool = False,
            index_codes=(("000300.SH", "沪深300"), ("000905.SH", "中证500"))) -> dict:
    days, eq, med = load_daily_series(date_from, date_to)
    if not days:
        return {"label": label, "error": "无数据"}
    years = len(eq) / TRADING_DAYS
    daily_curve = cum_curve(eq)
    mon = monthly_rebalance(eq)
    mon_curve = cum_curve(mon)
    mon_years = len(mon) / 12
    dist = load_distribution(date_from, date_to)
    out = {
        "label": label, "start": days[0], "end": days[-1], "days": len(days), "years": years,
        "A_daily_rebal": {"mult": daily_curve[-1], "ann": ann_return(daily_curve[-1], years),
                          "mdd": max_drawdown(daily_curve), "vol": ann_vol(eq), "sharpe": sharpe(eq)},
        "B_month_rebal": {"mult": mon_curve[-1], "ann": ann_return(mon_curve[-1], mon_years),
                          "mdd": max_drawdown(mon_curve)},
        "C_buy_hold": ({"mean_total": dist["mean_total"],
                        "mean_ann": ann_return(1 + dist["mean_total"], years),
                        "median_total": dist["median_total"],
                        "median_ann": ann_return(1 + dist["median_total"], years)} if dist.get("mean_total") is not None else {}),
        "D_distribution": dist,
        "rolling": [rolling_hold(daily_curve, y) for y in (1, 3, 5, 8)],
        "dca_monthly": [dca_from_curve(daily_curve, int(y * 12)) for y in (1, 3, 5, 8)],
    }
    if with_index:
        idx = {}
        for code, name in index_codes:
            try:
                d2, p2 = load_index(code, days[-1], 4.7)
            except Exception as e:  # noqa: BLE001
                idx[code] = {"name": name, "error": str(e)[:120]}
                continue
            if len(p2) < 200:
                idx[code] = {"name": name, "error": "样本不足"}
                continue
            c2 = [x / p2[0] for x in p2]
            yr = len(p2) / TRADING_DAYS
            step = MONTH
            idxs = list(range(step - 1, len(c2), step))
            units = sum(1.0 / c2[i] for i in idxs)
            idx[code] = {"name": name, "start": d2[0], "end": d2[-1], "days": len(p2), "years": yr,
                         "lump_mult": c2[-1], "lump_ann": ann_return(c2[-1], yr),
                         "mdd": max_drawdown(c2), "dca_total": units * c2[-1] / len(idxs) - 1.0,
                         "dca_irr": irr_monthly(units * c2[-1], len(idxs)), "months": len(idxs)}
        out["E_index"] = idx
    return out


def fmt(ev: dict) -> str:
    L = ["=" * 86]
    for w in ("full", "recent"):
        a = ev.get(w)
        if not a or a.get("error"):
            continue
        L.append(f"【{a['label']}】{a['start']} ~ {a['end']}  共 {a['days']} 个交易日（{a['years']:.2f} 年）")
        L.append("-" * 86)
        for key, nm in (("A_daily_rebal", "口径A 等权·每日再平衡  "), ("B_month_rebal", "口径B 等权·月度再平衡  ")):
            d = a[key]
            L.append(f"  {nm}累计 {d['mult']:.2f}倍 | 年化 {d['ann']*100:+.2f}% | 回撤 {d['mdd']*100:.1f}%"
                     + (f" | 波动 {d['vol']*100:.1f}% | 夏普 {d['sharpe']:.2f}" if "vol" in d else ""))
        c = a.get("C_buy_hold") or {}
        if c:
            L.append(f"  口径C 等权·买入持有    累计 {1+c['mean_total']:.2f}倍 | 年化 {c['mean_ann']*100:+.2f}%")
        d = a["D_distribution"]
        if d.get("samples"):
            L.append(f"  口径D 个股分布（{d['samples']}只）   中位 {d['median_total']*100:+.1f}% | 25分位 {d['q25']*100:+.1f}% | "
                     f"75分位 {d['q75']*100:+.1f}% | 亏损占比 {d['loss_ratio']*100:.1f}% | "
                     f"翻倍以上 {d['double_ratio']*100:.1f}% | 前30只贡献 {d['top30_share']*100:.1f}%")
        L.append("  滚动持有（口径A）：" + " ".join(
            f"{r['n_years']:.0f}年 年化{r['median']*100:+.1f}%/胜率{r['win_rate']*100:.0f}%/最差{r['worst']*100:+.1f}%"
            for r in a["rolling"] if r))
        L.append("  月度定投（口径A）：" + " ".join(
            f"{r['months']//12}年 总收益{r['median_total']*100:+.1f}%/胜率{r['win_rate']*100:.0f}%/IRR{r['median_irr']*100:+.1f}%"
            for r in a["dca_monthly"] if r))
        if a.get("E_index"):
            L.append("  口径E 官方指数（一次性 vs 月定投，同窗口）：")
            for code, v in a["E_index"].items():
                if v.get("error"):
                    L.append(f"    {v['name']:<8} 取数失败：{v['error']}")
                    continue
                L.append(f"    {v['name']:<8} {v['start']}~{v['end']}  一次性年化 {v['lump_ann']*100:+.2f}% | "
                         f"回撤 {v['mdd']*100:.1f}% | 月定投 {v['dca_total']*100:+.1f}%（IRR {v['dca_irr']*100:+.2f}%）")
        L.append("")
    return "\n".join(L)


# ================= 自检 =================
def curve_of(daily: float, n: int) -> list[float]:
    return cum_curve([daily] * n)


def selftest() -> int:
    print("=" * 72)
    print("value_evidence 指标函数自检")
    print("=" * 72)
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails += 1

    c = curve_of(0.001, 252)
    chk(abs(ann_return(c[-1], 1.0) - (1.001 ** 252 - 1)) < 1e-9, "恒定收益年化换算正确")
    chk(abs(max_drawdown(c)) < 1e-12, "单调上升序列最大回撤 = 0")
    chk(abs(max_drawdown([1.0, 0.75, 0.5, 0.8, 1.0]) + 0.5) < 1e-12, "最大回撤 -50% 计算正确")
    chk(median([1, 2, 3, 4]) == 2.5 and median([1, 2, 3]) == 2, "中位数（奇偶）正确")
    chk(pct([1, 2, 3, 4, 5], 0.5) == 3, "分位数正确")
    # 月度再平衡：恒定日收益下月收益应 = (1+r)^21 - 1
    mr = monthly_rebalance([0.001] * 42)
    chk(len(mr) == 2 and abs(mr[0] - (1.001 ** 21 - 1)) < 1e-12, "月度再平衡聚合正确")
    # 滚动持有：恒定上涨 → 胜率 100%
    rb = rolling_hold(curve_of(0.0008, 3000), 1.0)
    chk(rb and abs(rb["win_rate"] - 1.0) < 1e-9, "恒定上涨 → 滚动持有胜率 100%")
    # 定投：恒定上涨 → 总收益与 IRR 均 > 0
    dc = dca_from_curve(curve_of(0.0008, 3000), 60)
    chk(bool(dc) and dc["median_total"] > 0 and dc["median_irr"] > 0,
        f"恒定上涨 → 定投总收益/IRR 均 > 0（{dc.get('median_total',0)*100:.1f}% / {dc.get('median_irr',0)*100:.1f}%）")
    # 定投摊薄：反复「跌 25% → 等比涨回原点」锯齿，净值始终回 1.0，定投仍应正收益
    up = 1.0 / 0.997 - 1.0
    c3 = cum_curve(([-0.003] * 250 + [up] * 250) * 4)
    chk(abs(c3[-1] - 1.0) < 1e-9, f"锯齿序列精确回到起点（{c3[-1]:.4f}）")
    d2 = dca_from_curve(c3, 36)
    chk(bool(d2) and d2["median_total"] > 0,
        f"净值回到起点但定投为正收益（{d2.get('median_total',0)*100:.1f}%，样本 {d2.get('samples')}）")
    # IRR：把 100 万分 12 期投入、期末恰好回本 → IRR 应为 0
    chk(abs(irr_monthly(12.0, 12)) < 1e-6, f"零收益定投 IRR ≈ 0（{irr_monthly(12.0, 12)*100:.4f}%）")

    print(f"\n自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 · A股长期收益 / 定投 实测证据计算")
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--date", help="截止日（默认本地库最新交易日）")
    ap.add_argument("--full-since", default="2016-08-23", help="长期窗口起点（默认 2016-08-23）")
    ap.add_argument("--recent-since", default="2022-01-17", help="近期窗口起点（默认 2022-01-17）")
    ap.add_argument("--compare-years", type=float, default=5.0, help="跨资产对比窗口年数（≤5）")
    ap.add_argument("--out", help="输出 JSON 路径")
    ap.add_argument("--no-index", action="store_true", help="跳过指数取数（离线）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    base = a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd()
    ev = {"full": analyze(a.full_since, a.date, f"长期（{a.full_since} 起）", with_index=not a.no_index),
          "recent": analyze(a.recent_since, a.date, f"近期（{a.recent_since} 起）")}
    txt = fmt(ev)
    if not a.no_index:
        end = ev["full"].get("end") or a.date
        cmp = compare_window(end, a.compare_years)
        ev["compare"] = cmp
        txt += fmt_compare(cmp, f"近 {a.compare_years:g} 年（截至 {end}，同口径）")
        txt += ("\n  ⚠️ 口径：指数为价格指数（不含分红）、ETF 为未复权价格（分红被除权剔除）→ "
                "两者都会**低估**真实收益；横向比较成立，绝对值不可外推。")
    print(txt)
    op = a.out or os.path.join(base, CACHE_DIR, "evidence.json")
    os.makedirs(os.path.dirname(op), exist_ok=True)
    with open(op, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print(f"OK -> {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
