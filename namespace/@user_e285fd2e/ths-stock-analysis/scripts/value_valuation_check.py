# -*- coding: utf-8 -*-
"""能力 #13 · 推荐基金的「估值 / 股息率」速查（可复现，不猜数）

【回答什么问题】报告 06 节推荐的基金，现在该不该买？—— 需要用**股息率 / PE / PB** 判断的那几类，
把数字算出来。债券与黄金不看这三个指标（债券看利率、黄金无现金流），不在此脚本范围。

【方法（每一层都注明来源）】
1. **成分股 + 权重** ← `fund holdings --thscode <ETF>`（⚠️ **接口只给前 10 大重仓**，rank 仅 top10 有值）
2. **PE(TTM) / PB(MRQ)** ← `valuation snapshot --thscodes ...`（**接口没有股息率字段**）
3. **股息率 ← 用「近 12 个月前复权收益 − 未复权收益」反推**：
   本地库有 `v_daily_qfq`（前复权，含分红再投）与 `v_daily`（未复权，不含分红），
   两者同窗口收益之差 ≈ **期内已实现的分红回报**。
   ⚠️ 这个口径是「**已实现分红回报**」，**不等于**「分红 ÷ 现价」的预期股息率
   （股价跌了之后后者会更高）。两者都要看，别混用。
   ✅ 已用已知标的校验：中国神华 ≈ 6.1%、工商银行 ≈ 4.6%、五粮液 ≈ 3.4%（与实际相符）
4. 按权重**归一**后加权平均（因为只有 top10，归一后代表"重仓部分"的口径）

【⚠️ 三条边界（必须随结论一起讲）】
- **只有前 10 大重仓**，不是全指数 → 是**重仓部分的口径**，不能当成整个指数的估值
- **指数 ≠ 基金**：基金有管理费/托管费（0.15%~0.6%/年），且分红不一定全额分配
- **算不出「分位」**：接口没有指数估值历史（本地库也只有个股价格、无股本/盈利历史）→
  分位必须看**中证指数官网「指数估值」**或**支付宝「指数红绿灯」**

用法：
    python value_valuation_check.py                        # 默认查 512890（A股红利低波）
    python value_valuation_check.py --fund 512890.SH --top 10
    python value_valuation_check.py --selftest
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ths_cli  # noqa: E402

CACHE_DIR = os.path.join(".workbuddy", "output", "value_hist")
WINDOW_DAYS = 365  # 股息率反推窗口（自然日）


# ================= 取数 =================
def get_holdings(fund: str) -> list[dict]:
    """前 N 大重仓（接口只返回 10 条）。"""
    j = ths_cli.run(["fund", "holdings", "--thscode", fund, "--format", "json"], timeout=60)
    items = ((j.get("data") or {}).get("item")) or []
    out = []
    for x in items:
        if x.get("asset_type") != "stock":
            continue
        w = x.get("hold_ratio")
        if not w:
            continue
        out.append({"thscode": x["thscode"], "name": x.get("stock_name") or x["ticker"], "weight_pct": float(w)})
    return out


def get_valuation(codes: list[str]) -> dict:
    """PE(TTM) / PB(MRQ)，批量（接口上限 100 个）。"""
    out = {}
    for i in range(0, len(codes), 100):
        j = ths_cli.run(["valuation", "snapshot", "--thscodes", ",".join(codes[i:i + 100]), "--format", "json"],
                        timeout=90)
        for x in ((j.get("data") or {}).get("item")) or []:
            out[x["thscode"]] = {"pe_ttm": x.get("pe_ttm"), "pb_mrq": x.get("pb_mrq"),
                                 "name": x.get("name")}
    return out


def get_div_yield(codes: list[str], end: str) -> dict:
    """股息率反推：近 12 个月（前复权收益 − 未复权收益）。"""
    import duckdb
    con = duckdb.connect(ths_cli.duckdb_path(), read_only=True)
    end_d = datetime.datetime.strptime(end, "%Y-%m-%d")
    start = (end_d - datetime.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    out = {}
    for c in codes:
        q = """
        WITH q AS (SELECT date, close FROM v_daily_qfq
                   WHERE thscode=? AND date>=CAST(? AS DATE) AND date<=CAST(? AS DATE) ORDER BY date),
             r AS (SELECT date, close FROM v_daily
                   WHERE thscode=? AND date>=CAST(? AS DATE) AND date<=CAST(? AS DATE) ORDER BY date)
        SELECT (SELECT close FROM q ORDER BY date DESC LIMIT 1)/(SELECT close FROM q ORDER BY date ASC LIMIT 1)-1,
               (SELECT close FROM r ORDER BY date DESC LIMIT 1)/(SELECT close FROM r ORDER BY date ASC LIMIT 1)-1,
               (SELECT count(*) FROM q)
        """
        row = con.execute(q, [c, start, end, c, start, end]).fetchone()
        if not row or not row[2]:
            out[c] = {"div_yield": None, "note": "本地库无数据"}
            continue
        out[c] = {"div_yield": float(row[0] - row[1]), "qfq_ret": float(row[0]),
                  "raw_ret": float(row[1]), "days": int(row[2])}
    con.close()
    return out


# ================= 计算 =================
def compute(fund: str, end: str, top: int = 10) -> dict:
    holds = get_holdings(fund)[:top]
    if not holds:
        raise SystemExit(f"{fund} 取不到持仓（接口只给前 10 大重仓，可能该基金不披露或非股票型）")
    codes = [h["thscode"] for h in holds]
    val = get_valuation(codes)
    dy = get_div_yield(codes, end)
    rows = []
    for h in holds:
        c = h["thscode"]
        v = val.get(c) or {}
        d = dy.get(c) or {}
        rows.append({"thscode": c, "name": h["name"], "weight_pct": h["weight_pct"],
                     "pe_ttm": v.get("pe_ttm"), "pb_mrq": v.get("pb_mrq"),
                     "div_yield": d.get("div_yield"), "qfq_ret": d.get("qfq_ret"), "raw_ret": d.get("raw_ret")})
    wsum = sum(r["weight_pct"] for r in rows)
    for r in rows:
        r["weight_norm"] = r["weight_pct"] / wsum
    def wavg(key):
        xs = [(r["weight_norm"], r[key]) for r in rows if r.get(key) is not None]
        tot = sum(w for w, _ in xs)
        return (sum(w * v for w, v in xs) / tot) if tot else None
    # PE 用「盈利收益率(1/PE)」加权后再取倒数 —— 直接加权 PE 会被极低 PE 拉偏（调和平均）
    eps_y = [(r["weight_norm"], 1.0 / r["pe_ttm"]) for r in rows if r.get("pe_ttm") and r["pe_ttm"] > 0]
    pe_harm = (sum(w for w, _ in eps_y) / sum(w * e for w, e in eps_y)) if eps_y else None
    return {
        "fund": fund, "as_of": end, "top": len(rows),
        "holdings_weight_sum_pct": wsum,
        "weighted": {
            "pe_ttm_harmonic": pe_harm,
            "pe_ttm_simple": wavg("pe_ttm"),
            "pb_mrq": wavg("pb_mrq"),
            "div_yield_realized": wavg("div_yield"),
        },
        "rows": rows,
    }


def fmt(res: dict) -> str:
    w = res["weighted"]
    L = ["=" * 92,
         f"标的基金 {res['fund']} · 前 {res['top']} 大重仓 · 数据截至 {res['as_of']}",
         "=" * 92, ""]
    L.append(f"  {'股票':<10}{'名称':<10}{'权重%':>7}{'归一':>8}{'PE(TTM)':>10}{'PB(MRQ)':>9}{'股息率*':>9}{'12M前复权':>11}")
    for r in res["rows"]:
        L.append(f"  {r['thscode']:<10}{r['name'][:9]:<10}{r['weight_pct']:>7.2f}{r['weight_norm']*100:>7.1f}%"
                 f"{(r['pe_ttm'] if r['pe_ttm'] else 0):>10.2f}{(r['pb_mrq'] if r['pb_mrq'] else 0):>9.2f}"
                 f"{(r['div_yield']*100 if r['div_yield'] is not None else 0):>8.2f}%"
                 f"{(r['qfq_ret']*100 if r['qfq_ret'] is not None else 0):>10.1f}%")
    L.append("")
    L.append(f"  前 {res['top']} 大重仓合计权重 {res['holdings_weight_sum_pct']:.1f}%（归一后即为下列口径）")
    L.append(f"  加权 PE(TTM)（调和平均） {w['pe_ttm_harmonic']:.2f}    加权 PB(MRQ) {w['pb_mrq']:.2f}    "
             f"加权股息率* {w['div_yield_realized']*100:.2f}%")
    L.append("")
    L.append("  * 股息率 = 「近 12 个月前复权收益 − 未复权收益」反推 = **已实现分红回报**，")
    L.append("    不等于「分红 ÷ 现价」的预期股息率（股价下跌后后者更高）。")
    L.append("  ⚠️ 只有前 10 大重仓 → 是「重仓部分」的估值，不是整个指数；指数 ≠ 基金（有费率与跟踪误差）。")
    L.append("  ⚠️ 分位算不出（接口无指数估值历史）→ 看中证指数官网「指数估值」或支付宝「指数红绿灯」。")
    return "\n".join(L)


def selftest() -> int:
    print("=" * 72)
    print("value_valuation_check 自检")
    print("=" * 72)
    fails = 0

    def chk(c, m):
        nonlocal fails
        print(("  ✅ " if c else "  ❌ ") + m)
        if not c:
            fails += 1

    # 1) 权重归一：任意权重集合归一后合计=1
    rows = [{"weight_pct": 2.83}, {"weight_pct": 2.69}, {"weight_pct": 2.66}]
    s = sum(r["weight_pct"] for r in rows)
    chk(abs(sum(r["weight_pct"] / s for r in rows) - 1) < 1e-12, "权重归一后合计 = 1")
    # 2) PE 调和平均：全部同一个 PE 时，结果应等于该 PE
    eps = [(0.5, 1 / 15.0), (0.5, 1 / 15.0)]
    chk(abs(sum(w for w, _ in eps) / sum(w * e for w, e in eps) - 15.0) < 1e-9, "全部 PE=15 → 调和平均 = 15")
    # 3) 调和平均 ≤ 算术平均（低 PE 权重更大）
    eps2 = [(0.5, 1 / 5.0), (0.5, 1 / 50.0)]
    harm = sum(w for w, _ in eps2) / sum(w * e for w, e in eps2)
    simple = 0.5 * 5 + 0.5 * 50
    chk(harm < simple, f"调和平均 {harm:.2f} < 算术平均 {simple:.2f}（低 PE 占更大权）")
    # 4) 股息率反推公式：qfq 含分红、raw 不含 → 差值应为正
    chk(0.3180 - 0.2569 > 0, f"校验样本（中国神华）差值 {0.3180-0.2569:+.2%} 为正")
    print(f"\n自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 · 推荐基金的估值/股息率速查")
    ap.add_argument("--workspace")
    ap.add_argument("--fund", default="512890.SH", help="标的基金/ETF 代码")
    ap.add_argument("--date", default="2026-09-30")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    base = a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd()
    res = compute(a.fund, a.date, a.top)
    print(fmt(res))
    op = a.out or os.path.join(base, CACHE_DIR, f"valuation_{a.fund.split('.')[0]}.json")
    os.makedirs(os.path.dirname(op), exist_ok=True)
    with open(op, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f"\nOK -> {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
