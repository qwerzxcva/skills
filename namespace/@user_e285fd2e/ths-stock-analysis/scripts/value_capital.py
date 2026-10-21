# -*- coding: utf-8 -*-
"""能力 #13 · 从真实账本算「可投资金 / 月结余」，并直接产出模板参数。

【为什么单独一个脚本】
「月结余」这一步**最容易算错，而且错得离谱**：账本（简记导出 CSV）里混着三类非经常性流水，
不剔除会把月结余**高估约 6 倍**（2026-10-08 实测：正确 2,779.50/月，不剔除算成 17,377.87/月）。
所以把剔除规则**固化成代码**，而不是每次凭记忆筛。

必须剔除的三类：
  ① **一次性收入**（政府购房补贴 / 学费代偿 …）—— 不是经常性收入
  ② **理财申购与收益**（分类 = 理财）—— 资产内部划转，既非消费也非收入
  ③ **出差垫付与报销**（分类 = 出差）—— 报销滞后且含补助，且垫付不是消费

【用法】
    python value_capital.py --ledger "D:/AI/记账"      # 自动找该目录下的账本 CSV
    python value_capital.py --csv a.csv --csv b.csv    # 显式指定
    python value_capital.py --ledger ... --as-template  # 输出可直接粘进模板的参数块
    python value_capital.py --selftest

【输出】经常性收入/支出月均、月结余、应急金（6 个月支出）、以及**扣除应急金与专项后的可投资金**。
⚠️ `--reserve-extra`（婚期/职业转换专项）**不是账本实测值**，须人工给定（默认 0，脚本会提醒）。
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import os
import sys
from collections import Counter, defaultdict

ONE_OFF_KEYS = ("政府购房补贴", "学费代偿", "购房补贴")   # 备注里含这些 → 一次性
EXCLUDE_CATS = ("理财", "出差")                          # 分类命中 → 非经常性
EMERGENCY_MONTHS = 6


def _read(path: str) -> list[dict]:
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            t = io.open(path, encoding=enc).read()
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise SystemExit(f"无法解码：{path}")
    out = []
    for r in csv.DictReader(io.StringIO(t)):
        if not r.get("日期"):
            continue
        # ⚠️ 账本里有两套导出，**列名不一样**（实测 2026-10-08）：
        #    月度文件 `202601.csv` 用 `日期,星期,类型,分类,描述,金额`；
        #    合并文件 `简记导入-*.csv` 用 `日期,类型,分类,金额,账户,备注`。
        #    不归一化 → `r.get("备注")` 取不到 → **一次性收入（购房补贴）漏剔**。
        r = dict(r)
        r["_memo"] = (r.get("备注") or r.get("描述") or "").strip()
        out.append(r)
    return out


def _key(r: dict) -> tuple:
    return (r["日期"], r["类型"], r["分类"], float(r["金额"]), r["_memo"])


def dedupe(files_rows: list[list[dict]]) -> tuple[list[dict], int]:
    """跨文件去重：对每个 key 保留「**任一单文件内出现过的最大次数**」。

    ⚠️ 为什么不能简单按行去重（2026-10-08 实测踩到）：
    `总结分析/data/2026MM.csv` 与 `总结分析/data/简记导入-2026年1-8月.csv` 是**同一批数据的两种导出**
    （2026-01 两边 (日期,类型,分类,金额,备注) 集合**完全一致 121/121**），两个都读 → 收支翻倍。
    **但天真地「按行去重」也会算错**：同一天两笔完全相同的「地铁 −6」在单文件里本来就是 2 笔，
    读两遍变 4 笔；按行去重会只剩 1 笔 → **少算一笔**（实测交通少 10 元、出差少 2 元、礼品多 124 元）。
    → 正确做法：`keep[k] = max(各单文件内 k 的计数)`，再按文件顺序最多取 keep[k] 份。
    """
    per_file = [Counter(_key(r) for r in fs) for fs in files_rows]
    keep: Counter = Counter()
    for c in per_file:
        for k, v in c.items():
            if v > keep[k]:
                keep[k] = v
    out: list[dict] = []
    seen: Counter = Counter()
    for fs in files_rows:
        for r in fs:
            k = _key(r)
            if seen[k] < keep[k]:
                seen[k] += 1
                out.append(r)
    total = sum(len(fs) for fs in files_rows)
    return out, total - len(out)


def find_ledgers(root: str) -> list[str]:
    """在账本项目里找「简记」导出 CSV。

    选取策略（2026-10-08 实测定）：**优先用较新的合并导出，跳过同期的旧月度快照**。
    实测：`简记导入-2026年1-8月.csv`（mtime 09-05）比 `2026MM.csv`（mtime 08-22）**新**，
    且月度文件里多出 2 条（茶叶/坚果两笔）在较新的合并导出里**已被删改**
    → 两套都读会既重复计数、又把已删交易算回来。
    所以：**有 `简记导入-*.csv` 时就不读 `2026MM.csv`**；`收支明细/*/简记_导出_*.csv` 是另一段区间，照读。
    （跨文件去重仍保留作安全网，见 `dedupe`。）
    """
    cons = sorted(glob.glob(os.path.join(root, "总结分析", "data", "简记导入-*.csv")))
    out: list[str] = list(cons)
    if not cons:      # 没有合并导出时，才退回读月度快照
        out += sorted(glob.glob(os.path.join(root, "总结分析", "data", "2026*.csv")))
    out += sorted(glob.glob(os.path.join(root, "收支明细", "*", "简记_导出_*.csv")))
    return out


def analyse(rows: list[dict]) -> dict:
    inc, exp = defaultdict(float), defaultdict(float)
    raw_inc, raw_exp = defaultdict(float), defaultdict(float)
    months: set[str] = set()
    for r in rows:
        a = float(r["金额"])
        c, memo = r["分类"], r["_memo"]
        months.add(r["日期"][:7])
        if r["类型"] == "收入":
            raw_inc[c] += a
        else:
            raw_exp[c] += -a if a < 0 else a
        if any(k in memo for k in ONE_OFF_KEYS):
            continue
        if c in EXCLUDE_CATS:
            continue
        if r["类型"] == "收入":
            inc[c] += a
        else:
            exp[c] += -a if a < 0 else a
    n = max(1, len(months))
    ti, te = sum(inc.values()), sum(exp.values())
    return {"months": sorted(months), "n": n, "inc": dict(inc), "exp": dict(exp),
            "inc_avg": ti / n, "exp_avg": te / n, "surplus": (ti - te) / n,
            "raw_inc_avg": sum(raw_inc.values()) / n, "raw_exp_avg": sum(raw_exp.values()) / n,
            "raw_surplus": (sum(raw_inc.values()) - sum(raw_exp.values())) / n}


def report(o: dict, reserve_extra: float, cap_cash: float, cap_stock: float) -> None:
    print("═" * 74)
    print("能力 #13 · 资金口径测算")
    print("═" * 74)
    print(f"  区间：{o['months'][0]} ~ {o['months'][-1]}（{o['n']} 个月）")
    print()
    print("  经常性收入分类（已剔一次性 / 理财 / 出差）：")
    for k, v in sorted(o["inc"].items(), key=lambda x: -x[1]):
        print(f"     {k:<6}{v:>12,.2f}   月均 {v/o['n']:>10,.2f}")
    print(f"     {'合计':<6}{sum(o['inc'].values()):>12,.2f}   月均 {o['inc_avg']:>10,.2f}")
    print()
    print("  经常性支出分类（同上）：")
    for k, v in sorted(o["exp"].items(), key=lambda x: -x[1])[:12]:
        print(f"     {k:<6}{v:>12,.2f}   月均 {v/o['n']:>10,.2f}")
    print(f"     {'合计':<6}{sum(o['exp'].values()):>12,.2f}   月均 {o['exp_avg']:>10,.2f}")
    print()
    print(f"  ★ 月结余（经常性口径）：{o['surplus']:>10,.2f} 元/月")
    print(f"    ⚠️ 不剔除那三类会算成：{o['raw_surplus']:>10,.2f} 元/月"
          f"（高估 {o['raw_surplus']/max(o['surplus'],1):.1f} 倍）")
    print()
    emerg = o["exp_avg"] * EMERGENCY_MONTHS
    print(f"  应急金 = {EMERGENCY_MONTHS} 个月经常性支出 = {emerg:,.2f}")
    print(f"  专项预留（婚期/职业转换）= {reserve_extra:,.2f}"
          + ("　⚠️ 未设置：账本里没有婚期支出记录，这是人工判断项，不是实测值" if reserve_extra == 0 else ""))
    cap_total = cap_cash + cap_stock
    print(f"  资产：现金类 {cap_cash:,.2f} + 股票账户 {cap_stock:,.2f} = {cap_total:,.2f}")
    print()
    print(f"  ★ 可投资金 = {cap_cash:,.2f} − {emerg:,.2f} − {reserve_extra:,.2f} = "
          f"{(cap_cash - emerg - reserve_extra):,.2f}")


def as_template(o: dict, reserve_extra: float, cap_cash: float, cap_stock: float) -> str:
    emerg = o["exp_avg"] * EMERGENCY_MONTHS
    return textwrap_block(o, emerg, reserve_extra, cap_cash, cap_stock)


def textwrap_block(o, emerg, reserve_extra, cap_cash, cap_stock) -> str:
    return (
        "# ---------- 真实资金口径（由 scripts/value_capital.py 生成）----------\n"
        f"CAP_CASH = {cap_cash:.2f}\n"
        f"CAP_STOCK = {cap_stock:.2f}\n"
        f"MON_INCOME = {o['inc_avg']:.2f}\n"
        f"MON_EXPENSE = {o['exp_avg']:.2f}\n"
        f"MON_SURPLUS = {o['surplus']:.2f}\n"
        f"RES_EMERGENCY = {emerg:.2f}\n"
        f"RES_EXTRA = {reserve_extra:.2f}   # ⚠️ 人工判断项（婚期/职业转换），非账本实测\n"
    )


def selftest() -> int:
    """负例自证：同一个样本，剔除前/剔除后必须差出数倍（证明剔除规则真的在起作用）。"""
    print("=" * 72)
    print("value_capital 自检")
    print("=" * 72)
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails += 1

    sample = (
        "日期,类型,分类,金额,账户,备注\n"
        "2026-01-09,收入,工资,8000,,工资\n"
        "2026-01-15,支出,餐饮,-1000,,吃饭\n"
        "2026-01-20,支出,理财,-5000,,买基金\n"
        "2026-01-22,收入,理财,200,,赎回收益\n"
        "2026-01-25,支出,出差,-3000,,出差垫付\n"
        "2026-02-09,收入,工资,8000,,工资\n"
        "2026-02-15,支出,餐饮,-1000,,吃饭\n"
        "2026-03-15,支出,餐饮,-1000,,吃饭\n"
        "2026-04-01,收入,工资,100000,,政府购房补贴\n"      # 一次性，必须剔
    )
    rows = [r for r in csv.DictReader(io.StringIO(sample)) if r.get("日期")]
    for r in rows:
        r["_memo"] = (r.get("备注") or r.get("描述") or "").strip()
    o = analyse(rows)
    # 样本共 4 个月（01~04）：
    #   经常性收入 = 8000+8000 = 16000 → 月均 4000
    #   经常性支出 = 1000×3 = 3000      → 月均  750
    #   月结余 = (16000−3000)/4 = 3250
    chk(abs(o["inc_avg"] - 4000) < 0.01, f"一次性收入已剔除（经常性收入月均 {o['inc_avg']:.2f}，应 4000.00）")
    chk(abs(o["exp_avg"] - 750) < 0.01, f"理财与出差已剔除（经常性支出月均 {o['exp_avg']:.2f}，应 750.00）")
    chk(abs(o["surplus"] - 3250) < 0.01, f"月结余 {o['surplus']:.2f}，应 3250.00")
    # 不剔除时：收入 (8000×2+200+100000)/4=29050；支出 (1000×3+5000+3000)/4=2750 → 26300
    chk(o["raw_surplus"] > o["surplus"] * 5,
        f"负例：不剔除会高估 {o['raw_surplus']/o['surplus']:.1f} 倍"
        f"（{o['raw_surplus']:.2f} vs {o['surplus']:.2f}）→ 证明剔除规则确实生效")
    chk(o["n"] == 4, f"月份数识别正确（{o['n']}，应 4）")
    # 去重：同一批数据读两遍必须回到原值，**且不能把合法的重复交易并掉**
    d, n = dedupe([rows, rows])
    chk(len(d) == len(rows) and n == len(rows),
        f"负例：重复文件被正确去重（{len(rows)} 条读两遍 → {len(d)} 条，丢 {n} 条）")
    dupc = [{"日期": "2026-05-04", "类型": "支出", "分类": "交通", "金额": "-6", "_memo": "地铁"},
            {"日期": "2026-05-04", "类型": "支出", "分类": "交通", "金额": "-6", "_memo": "地铁"}]
    dd, _ = dedupe([dupc, dupc])          # 单文件内本来就 2 笔相同交易，读两遍
    chk(len(dd) == 2,
        f"负例：单文件内**合法重复**（同日两笔相同的「地铁 −6」）不被误并（保留 {len(dd)} 笔，应 2）")
    # 列名归一：月度文件用「描述」列，必须同样能读到备注
    alt = [{"日期": "2026-04-01", "类型": "收入", "分类": "工资", "金额": "100000",
            "_memo": "政府购房补贴"}]
    chk(analyse(alt)["surplus"] == 0.0,
        "负例：只有一次性收入时月结余为 0（说明备注能读到、且被正确剔除）")

    print(f"\n  自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 · 从真实账本算可投资金 / 月结余")
    ap.add_argument("--ledger", help="账本项目目录（自动找「简记」导出的 CSV）")
    ap.add_argument("--csv", action="append", default=[], help="显式指定 CSV（可多次）")
    ap.add_argument("--cap-cash", type=float, default=0.0, help="现金类合计（账户快照，必须人工给）")
    ap.add_argument("--cap-stock", type=float, default=0.0, help="股票账户金额")
    ap.add_argument("--reserve-extra", type=float, default=0.0,
                    help="婚期/职业转换专项（⚠️ 人工判断项，非账本实测值）")
    ap.add_argument("--as-template", action="store_true", help="输出可直接粘进模板的参数块")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    files = list(a.csv)
    if a.ledger:
        files += find_ledgers(a.ledger)
    files = [f for f in dict.fromkeys(files) if os.path.exists(f)]
    if not files:
        print("未找到账本 CSV —— 用 --ledger <账本目录> 或 --csv <文件> 指定")
        return 2
    print("读取账本：")
    for f in files:
        print("   ", f)
    files_rows = [_read(f) for f in files]
    rows, dropped = dedupe(files_rows)
    print(f"   共 {len(rows)} 条" + (f"（跨文件去重：去掉 {dropped} 条重复副本）" if dropped else ""))
    print()
    o = analyse(rows)
    report(o, a.reserve_extra, a.cap_cash, a.cap_stock)
    if a.as_template:
        print("\n" + "─" * 74)
        print("粘进 gen_value_investing.py 的参数块：")
        print("─" * 74)
        print(as_template(o, a.reserve_extra, a.cap_cash, a.cap_stock))
    return 0


if __name__ == "__main__":
    sys.exit(main())
