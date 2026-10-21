# -*- coding: utf-8 -*-
"""能力 #13 价值投资配置 · 组合历史回测（回答「这一套组合下来历史收益多少」）

【定位】把报告的「配比表」原样搬进历史数据跑一遍 —— **权重不是另写一份，而是直接读 `gen_value_investing.py` 的 `ALLOC`**，
保证「报告里写的配比」与「回测用的配比」永远一致。

【口径与边界（必须随结论一起讲）】
- **数据源**：同花顺接口 `fund history`（ETF 日线）。**接口窗口硬上限 5 年、且结束日须在近期**（坑 74）
  → 本回测窗口固定在 **近 ~4.9 年**，无法更长（本地 DuckDB 只有 A 股、无 ETF，见坑 75）。
- **ETF 用未复权价格 → 现金分红被除权剔除 → 结果系统性低估真实收益**（红利低波、债券 ETF 分红较多，
  低估幅度最大）。方向上偏保守，属「宁可低估」的处理，但**不可当作真实可得收益上限**。
- 现金腿用**银华日利 511880**（净值随收益累积）。❌ 不用 511990 华宝添益——它价格恒为 100、收益走分红，
  价格序列收益恒为 0，会严重低估货币收益（实测累计 +0.0%）。
- 组合按**每日盯市 + 定期再平衡**；再平衡成本按 `--cost-bps`（单边）计：
  `成本 = 单边换手率 × 2 ×bps/1e4`。
- **样本只有一轮市场环境**（2022-2024 调整 + 2024-2026 修复 + 黄金/美股大牛），
  **不能外推**；只能回答「过去这段它大概是什么体验」。

用法：
    python value_backtest.py                          # 平衡档，月度再平衡
    python value_backtest.py --profile conservative --rebalance Q
    python value_backtest.py --all                    # 三档 × 四种再平衡频率的敏感度
    python value_backtest.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import value_evidence as ve  # noqa: E402

TPL = os.path.join(HERE, "gen_value_investing.py")
CACHE_DIR = os.path.join(".workbuddy", "output", "value_hist")
PROFILE_IDX = {"conservative": 2, "balanced": 3, "aggressive": 4}
PROFILE_CN = {"conservative": "稳健", "balanced": "平衡", "aggressive": "进取"}

# 配比表里的资产名 → (ETF 代码, 回测显示名)
LEG_MAP = {
    "A股红利低波": ("512890.SH", "A股红利低波 512890"),
    "美股宽基（QDII）": ("513500.SH", "美股宽基 标普500ETF 513500"),
    "国内债券": ("511260.SH", "国内债券 10年国债ETF 511260"),
    "黄金": ("518880.SH", "黄金 黄金ETF 518880"),
    "现金 / 货币": ("511880.SH", "现金 货币ETF 511880"),
}


# ================= 读模板配比（唯一来源，避免双份数据漂移） =================
def load_alloc(script: str = TPL) -> list[tuple]:
    """从模板读出 ALLOC（与 `value_investing.summary_alloc()` 同一套解析法）。
    注意：ALLOC 的字符串里不含 `]`，所以第一个 `]` 就是闭合括号（切片要 +1 含进去）。"""
    src = open(script, encoding="utf-8").read()
    i = src.index("ALLOC = [")
    j = src.index("]", i)
    return eval(src[i + len("ALLOC = "):j + 1])  # noqa: S307 —— 自家模板的字面量


def weights_of(rows: list[tuple], profile: str) -> dict:
    k = PROFILE_IDX[profile]
    return {r[0]: float(r[k].strip("%")) / 100.0 for r in rows}


# ================= 回测核心 =================
def align(legs: dict) -> list[str]:
    """多标的口径对齐：取交易日交集。legs 的值是 (日期列表, 价格列表)。"""
    sets = [set(v[0]) for v in legs.values()]
    return sorted(set.intersection(*sets))


def backtest(prices: dict, days: list[str], w: dict, rebal: str = "M",
             cost_bps: float = 10.0) -> dict:
    """每日盯市 + 定期再平衡。prices[c] = (日期列表, 价格列表)。"""
    codes = [c for c in w if w[c] > 0]
    px = {c: dict(zip(prices[c][0], prices[c][1])) for c in codes}
    val = {c: w[c] for c in codes}
    nav, dates = [], []
    turnover_total = 0.0
    prev = days[0]
    for i, d in enumerate(days):
        if i > 0:
            for c in codes:
                r = px[c][d] / px[c][prev] - 1.0
                val[c] *= (1.0 + r)
            prev = d
        # 再平衡判定
        do = False
        if i > 0:
            if rebal == "D":
                do = True
            elif rebal == "M":
                do = d[:7] != days[i - 1][:7]
            elif rebal == "Q":
                do = (d[:4], (int(d[5:7]) - 1) // 3) != (days[i - 1][:4], (int(days[i - 1][5:7]) - 1) // 3)
            elif rebal == "Y":
                do = d[:4] != days[i - 1][:4]
        if do:
            tot = sum(val.values())
            tgt = {c: w[c] * tot for c in codes}
            turn = sum(abs(tgt[c] - val[c]) for c in codes) / 2.0
            if tot > 0:
                turnover_total += turn / tot
            cost = turn * 2.0 * (cost_bps / 1e4)
            tot -= cost
            val = {c: w[c] * tot for c in codes}
        nav.append(sum(val.values()))
        dates.append(d)
    return {"dates": dates, "nav": nav, "turnover_total": turnover_total}


def stats(dates: list[str], nav: list[float]) -> dict:
    rets = [nav[i] / nav[i - 1] - 1 for i in range(1, len(nav))]
    years = len(nav) / ve.TRADING_DAYS
    # 逐年收益：每年最后一个净值 / 上一年最后一个净值
    ye = {}
    for i, d in enumerate(dates):
        ye[d[:4]] = nav[i]
    yearly, prev = {}, 1.0
    for y in sorted(ye):
        yearly[y] = ye[y] / prev - 1
        prev = ye[y]
    # 滚动 12 个月
    roll = [nav[i] / nav[i - ve.TRADING_DAYS] - 1 for i in range(ve.TRADING_DAYS, len(nav))]
    return {
        "days": len(nav), "years": years, "start": dates[0], "end": dates[-1],
        "total": nav[-1] - 1, "ann": ve.ann_return(nav[-1], years),
        "mdd": ve.max_drawdown(nav), "vol": ve.ann_vol(rets), "sharpe": ve.sharpe(rets),
        "yearly": yearly,
        "roll12_min": min(roll) if roll else None,
        "roll12_median": ve.median(roll) if roll else None,
        "roll12_max": max(roll) if roll else None,
    }


BOND_OPT = {  # 债券腿可选标的（敏感性检验：这 4.7 年吃到利率下行红利，10 年国债偏高）
    "511260.SH": "国内债券 10年国债ETF 511260",
    "511010.SH": "国内债券 5年国债ETF 511010",
    "511220.SH": "国内债券 城投债ETF 511220",
    "511360.SH": "国内债券 短融ETF 511360",
}


def fetch(end: str, years: float, bond: str = "511260.SH") -> dict:
    out = {}
    for name, (code, label) in LEG_MAP.items():
        if name == "国内债券":
            code, label = bond, BOND_OPT[bond]
        d, p = ve.load_series(code, end, years, kind="fund")
        if len(p) < 200:
            raise SystemExit(f"{code} 样本不足（{len(p)}）—— 检查接口窗口限制（坑 74）")
        out[name] = (d, p, label, code)
    return out


def run(end: str, years: float, profile: str, rebal: str, cost_bps: float, data: dict) -> dict:
    rows = load_alloc()
    w = weights_of(rows, profile)
    prices = {n: data[n][:2] for n in data}
    days = align(prices)
    bt = backtest(prices, days, w, rebal, cost_bps)
    st = stats(bt["dates"], bt["nav"])
    st["profile"] = profile
    st["rebalance"] = rebal
    st["cost_bps"] = cost_bps
    st["weights"] = w
    st["turnover_total"] = bt["turnover_total"]
    return st


# ================= 输出 =================
def fmt_legs(data: dict, days: list[str]) -> str:
    L = ["", "  各标的单独表现（同窗口，未复权价格）", ""]
    L.append(f"  {'标的':<30}{'累计':>10}{'年化':>9}{'最大回撤':>10}{'年化波动':>10}")
    for name, (d, p, label, code) in data.items():
        m = {dd: pp for dd, pp in zip(d, p)}
        cur = [m[dd] for dd in days if dd in m]
        if len(cur) < 2:
            continue
        rets = [cur[i] / cur[i - 1] - 1 for i in range(1, len(cur))]
        yr = len(cur) / ve.TRADING_DAYS
        L.append(f"  {label:<30}{(cur[-1]/cur[0]-1)*100:>9.1f}%{ve.ann_return(cur[-1]/cur[0], yr)*100:>8.2f}%"
                 f"{ve.max_drawdown(cur)*100:>9.1f}%{ve.ann_vol(rets)*100:>9.1f}%")
    return "\n".join(L)


def fmt_bt(st: dict) -> str:
    w = st["weights"]
    L = [f"\n  ── 组合：{PROFILE_CN[st['profile']]}档 · 再平衡={st['rebalance']} · 单边成本 {st['cost_bps']:.0f}bp ──"]
    L.append("  权重：" + " / ".join(f"{k} {v*100:.0f}%" for k, v in w.items() if v > 0))
    L.append(f"  区间 {st['start']} ~ {st['end']}（{st['days']} 交易日 / {st['years']:.2f} 年）")
    L.append(f"  累计 {st['total']*100:+.1f}%  |  年化 {st['ann']*100:+.2f}%  |  最大回撤 {st['mdd']*100:.1f}%  |  "
             f"年化波动 {st['vol']*100:.1f}%  |  夏普 {st['sharpe']:.2f}")
    L.append("  逐年：" + "  ".join(f"{y} {v*100:+.1f}%" for y, v in st["yearly"].items()))
    if st["roll12_median"] is not None:
        L.append(f"  滚动 12 个月收益：最差 {st['roll12_min']*100:+.1f}% / 中位 {st['roll12_median']*100:+.1f}% / "
                 f"最好 {st['roll12_max']*100:+.1f}%")
    L.append(f"  区间累计单边换手 {st['turnover_total']*100:.0f}%")
    return "\n".join(L)


def selftest() -> int:
    print("=" * 72)
    print("value_backtest 自检")
    print("=" * 72)
    fails = 0

    def chk(c, m):
        nonlocal fails
        print(("  ✅ " if c else "  ❌ ") + m)
        if not c:
            fails += 1

    rows = load_alloc()
    for p in PROFILE_IDX:
        w = weights_of(rows, p)
        chk(abs(sum(w.values()) - 1) < 1e-9, f"{PROFILE_CN[p]}档权重合计 = 1（{sum(w.values()):.4f}）")
    chk(all(r[0] in LEG_MAP for r in rows), "配比表每一项都有对应回测标的")
    chk(len(rows) == 5 and len(LEG_MAP) == 5, "配比表 5 类 ↔ 5 个回测标的")
    # 构造序列
    days = sorted({f"2024-{m:02d}-{i:02d}" for m in (1, 2, 3, 4, 5, 6) for i in range(1, 29)})
    n = len(days)
    up = [100 * (1.0008 ** i) for i in range(n)]
    # ① 单一资产 100% → 组合净值 = 该资产
    bt = backtest({"A": (days, up)}, days, {"A": 1.0}, "M", 0)
    chk(abs(bt["nav"][-1] - up[-1] / up[0]) < 1e-12, "单一资产 100% → 组合净值 = 该资产净值")
    chk(abs(bt["turnover_total"]) < 1e-12, "单一资产无换手 → 换手率 = 0")
    # ② 两个相同资产各 50% → 无论怎么再平衡都等于该资产
    d2 = [f"2024-{m:02d}-{i:02d}" for m in (1, 2, 3) for i in range(1, 29)]
    u2 = [100 * (1.001 ** i) for i in range(len(d2))]
    b2 = backtest({"A": (d2, u2), "B": (d2, u2)}, d2, {"A": .5, "B": .5}, "D", 10)
    chk(abs(b2["nav"][-1] - u2[-1] / u2[0]) < 1e-9, f"两个相同资产各 50% → 等同该资产（{b2['nav'][-1]:.4f}）")
    # ③ 一涨一跌（等权、每日再平衡）→ 日收益应恰为两者算术平均
    pts = [f"2024-{m:02d}-{i:02d}" for m in (1, 2, 3) for i in range(1, 29)]
    ra, rb = 0.001, -0.0008
    pa = [100 * (1 + ra) ** i for i in range(len(pts))]
    pb = [100 * (1 + rb) ** i for i in range(len(pts))]
    b3 = backtest({"A": (pts, pa), "B": (pts, pb)}, pts, {"A": .5, "B": .5}, "D", 0)
    exp = (1 + (ra + rb) / 2) ** (len(pts) - 1)
    chk(abs(b3["nav"][-1] - exp) < 1e-9, f"每日再平衡 → 日收益 = 算术平均（{b3['nav'][-1]:.6f} vs {exp:.6f}）")
    # ④ 成本必须让收益变差
    b4 = backtest({"A": (pts, pa), "B": (pts, pb)}, pts, {"A": .5, "B": .5}, "D", 100)
    chk(b4["nav"][-1] < b3["nav"][-1], "交易成本 > 0 → 净值低于零成本")
    # ⑤ 月度再平衡的换手率应 > 年度（需跨年边界，否则年度永不触发）
    pts2 = [f"{y}-{m:02d}-{i:02d}" for y in (2023, 2024) for m in range(1, 13) for i in range(1, 29)]
    pa2 = [100 * (1 + ra) ** i for i in range(len(pts2))]
    pb2 = [100 * (1 + rb) ** i for i in range(len(pts2))]
    bm = backtest({"A": (pts2, pa2), "B": (pts2, pb2)}, pts2, {"A": .5, "B": .5}, "M", 0)
    by = backtest({"A": (pts2, pa2), "B": (pts2, pb2)}, pts2, {"A": .5, "B": .5}, "Y", 0)
    chk(bm["turnover_total"] > by["turnover_total"] > 0,
        f"换手率 月度 > 年度（{bm['turnover_total']:.3f} > {by['turnover_total']:.3f}）")
    print(f"\n自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def forward(w: dict, exp: dict) -> tuple[float, list[tuple[str, float, float]]]:
    """前瞻中枢：只做加权算术，不是预测。返回 (组合年化, [(资产, 权重, 假设年化)])。"""
    rows = [(n, w[n], exp[n]) for n in w if w[n] > 0]
    return sum(x * e for _, x, e in rows), rows


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 · 组合历史回测")
    ap.add_argument("--workspace")
    ap.add_argument("--date", default="2026-09-30")
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--profile", default="balanced", choices=list(PROFILE_IDX))
    ap.add_argument("--rebalance", default="M", choices=["M", "Q", "Y", "N"])
    ap.add_argument("--cost-bps", type=float, default=10.0, help="单边交易成本（bp），默认 10")
    ap.add_argument("--bond", default="511260.SH", choices=list(BOND_OPT), help="债券腿标的（敏感性）")
    ap.add_argument("--all", action="store_true", help="三档 × 四种再平衡频率敏感度")
    ap.add_argument("--forward", help="前瞻中枢：5 个假设年化%%（按配比表顺序，逗号分隔），只做加权算术")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    base = a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd()
    data = fetch(a.date, a.years, a.bond)
    days = align({n: data[n][:2] for n in data})
    print("═" * 90)
    print(f"能力 #13 组合回测 · 窗口 {days[0]} ~ {days[-1]}（{len(days)} 交易日 / {len(days)/ve.TRADING_DAYS:.2f} 年）")
    print("═" * 90)
    print(fmt_legs(data, days))
    out = {"window": [days[0], days[-1]], "days": len(days)}
    if a.all:
        print("\n  三档 × 再平衡频率敏感度（年化 / 最大回撤）")
        print(f"  {'':<6}" + "".join(f"{r:>18}" for r in ["月度", "季度", "年度", "不再平衡"]))
        for p in ("conservative", "balanced", "aggressive"):
            cells = []
            for r in ("M", "Q", "Y", "N"):
                st = run(a.date, a.years, p, r, a.cost_bps, data)
                out[f"{p}_{r}"] = st
                cells.append(f"{st['ann']*100:+.2f}%/{st['mdd']*100:.1f}%")
            print(f"  {PROFILE_CN[p]:<6}" + "".join(f"{c:>18}" for c in cells))
    else:
        st = run(a.date, a.years, a.profile, a.rebalance, a.cost_bps, data)
        out[f"{a.profile}_{a.rebalance}"] = st
        print(fmt_bt(st))

    if a.forward:
        vals = [float(x) for x in a.forward.replace("%", "").split(",")]
        names = [r[0] for r in load_alloc()]
        if len(vals) != len(names):
            raise SystemExit(f"--forward 需要 {len(names)} 个值（按配比表顺序：{' / '.join(names)}）")
        exp = {n: v / 100 for n, v in zip(names, vals)}
        print("\n  ── 前瞻中枢（假设值，非预测；仅加权算术，不含再平衡增益）──")
        for p in ("conservative", "balanced", "aggressive"):
            w = weights_of(load_alloc(), p)
            tot, rows = forward(w, exp)
            print(f"  {PROFILE_CN[p]:<4} → 假设年化 {tot*100:+.2f}%   （" +
                  "  ".join(f"{n} {wd*100:.0f}%×{exp[n]*100:.1f}%" for n, wd, _ in rows) + "）")
        out["forward"] = {"assumption": exp, "comment": "加权算术，非预测"}

    op = os.path.join(base, CACHE_DIR, "backtest.json")
    os.makedirs(os.path.dirname(op), exist_ok=True)
    with open(op, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nOK -> {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
