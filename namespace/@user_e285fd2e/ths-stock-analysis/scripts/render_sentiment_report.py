# -*- coding: utf-8 -*-
"""能力 #6 市场情绪扫描 —— 通用渲染器（把「数字自动算 + 叙述人写」固化成一条命令）

为什么有这个脚本：2026-09-28 出情绪报告时，数据区是**一次性构建脚本**手写的；本脚本把这套逻辑固化，
以后一条命令出报告，和 `render_rotation_report.py`（#7）/`render_picks_report.py`（#12）保持同一模式。

分工：
- **本脚本自动算**（全部实测，不手抄）：涨跌家数/中位数（本地库）、涨停/跌停/炸板（交易所池）、封板率、
  近 5 个交易日涨停家数（**按本地交易日历定位，自动跳过休市日**）、板块热度（5 日涨停原因关键词归并）、
  持续涨停（≥3 天，按「天数 → 今日是否仍涨停 → 今连板数」排序）、龙虎榜净买 TOP6、指数收盘。
- **人写（放进 `--data` 的 JSON）**：`HERO_SUB / DIAG_EXTRA / WEEK_INSIGHT / FOCUS_INSIGHT / PERSIST_INSIGHT /
  DIAG{bull,bear,watch,level,badge,score,summary} / SUMMARY / SECTOR_VIEW`。
  缺字段时用**中性自动文本兜底**（并在页脚标注「叙述为自动生成」），保证脚本永不因缺叙述而失败。

用法：
    python render_sentiment_report.py --date 2026-09-28 [--workspace W] [--data narr.json] [--out <HTML 目录>]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import duckdb  # noqa: E402
import report_artifact  # noqa: E402
import ths_cli  # noqa: E402
from ths_indicators import limitup_pool_stats, market_breadth  # noqa: E402

TPL = HERE / "gen_sentiment.py"
HOT_TOP = 15


# ------------------------------ 取数 ------------------------------
def _ms(d: str) -> str:
    return str(int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp() * 1000))


def load_items(p: Path) -> list:
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8")).get("data")
    if isinstance(d, dict):
        for k in ("item", "stock_items", "items"):
            if k in d:
                return d[k] or []
    return d or []


def ensure_pool(out_root: Path, kind: str, date: str) -> list:
    """取某日某池（lu/ld/lb），本地没有就拉一次并落盘。"""
    mmdd = date.replace("-", "")[4:]
    fn = {"lu": f"lu_{mmdd}.json", "ld": f"ld_{mmdd}.json", "lb": f"lb_{mmdd}.json"}[kind]
    p = out_root / fn
    items = load_items(p)
    if items:
        return items
    sub = {"lu": "limit-up-pool", "ld": "limit-down-pool", "lb": "limit-break-pool"}[kind]
    args = ["special", sub, "--date-ms", _ms(date), "--size", "300", "--format", "json"]
    if kind == "lu":
        args[3:3] = ["--sort-field", "continue_day_cnt", "--sort-dir", "desc"]
    j = ths_cli.run(args, timeout=180, retries=1)
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return load_items(p)


def trading_days(target: str, n: int) -> list[str]:
    """最近 n 个交易日（含目标日），来自本地交易日历 —— 自动跳过休市日（如 2026-09-25 中秋）。"""
    con = duckdb.connect(ths_cli.duckdb_path(), read_only=True)
    try:
        rows = con.execute(f"SELECT DISTINCT date FROM raw_kline_daily WHERE date <= DATE '{target}' "
                           f"ORDER BY date DESC LIMIT {int(n)}").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def week_pools(out_root: Path, days: list[str]) -> dict:
    """近 n 个交易日的涨停池（并行拉取缺失项）。"""
    need = []
    res: dict[str, list] = {}
    for d in days:
        mmdd = d.replace("-", "")[4:]
        p = out_root / f"lu_{mmdd}.json"
        items = load_items(p)
        if items:
            res[d] = items
        else:
            need.append(d)
    if need:
        got = ths_cli.run_many([["special", "limit-up-pool", "--date-ms", _ms(d), "--size", "300",
                                 "--sort-field", "continue_day_cnt", "--sort-dir", "desc", "--format", "json"]
                                for d in need], workers=3, timeout=180, retries=1)
        for d, j in zip(need, got):
            (out_root / f"lu_{d.replace('-', '')[4:]}.json").write_text(json.dumps(j, ensure_ascii=False),
                                                                        encoding="utf-8")
            res[d] = ((j.get("data") or {}).get("item") or [])
    return res


# ------------------------------ 计算 ------------------------------
def compute(date: str, out_root: Path, name_map: dict) -> dict:
    lu = ensure_pool(out_root, "lu", date)
    ld = ensure_pool(out_root, "ld", date)
    lb = ensure_pool(out_root, "lb", date)
    mb = market_breadth(date)
    seal = len(lu) / (len(lu) + len(lb)) * 100 if (len(lu) + len(lb)) else 0.0
    top = max(lu, key=lambda x: x.get("continue_day_cnt") or 1) if lu else {}

    days = trading_days(date, 5)
    pools = week_pools(out_root, days)

    # 板块热度：近 5 日涨停原因关键词归并
    kw = Counter()
    for d in days:
        for x in pools.get(d, []):
            for part in re.split(r"[+＋、,，/／\s]+", (x.get("limit_up_reason") or "")):
                w = part.strip()
                if 2 <= len(w) <= 8:
                    kw[w] += 1
    hot = kw.most_common(HOT_TOP)

    # 持续涨停（≥3 天）
    occ = defaultdict(list)
    for d in days:
        for x in pools.get(d, []):
            occ[x["thscode"]].append(d)
    today_map = {x["thscode"]: x for x in lu}

    def rank(kv):
        c, ds = kv
        t = today_map.get(c) or {}
        return (-len(ds), 0 if t else 1, -(t.get("continue_day_cnt") or 0))
    persist = []
    for c, ds in sorted(occ.items(), key=rank):
        if len(ds) < 3:
            continue
        t = today_map.get(c)
        reason = (t or {}).get("limit_up_reason") or next(
            (x.get("limit_up_reason") for d in days for x in pools.get(d, [])
             if x["thscode"] == c and x.get("limit_up_reason")), "")
        persist.append((name_map.get(c, c), len(ds),
                        f"{reason} · " + (f"今日连板{t.get('continue_day_cnt')}板" if t else "今日未涨停")))
        if len(persist) >= 8:
            break

    # 龙虎榜（普通榜 net + 机构榜 org）
    net, org, concept = defaultdict(float), defaultdict(float), defaultdict(list)
    for x in load_items(out_root / f"lhb_{date.replace('-', '')[4:]}.json"):
        c = x["thscode"]
        net[c] += float(x.get("net_value") or 0)
        concept[c] += [k.get("name") if isinstance(k, dict) else k for k in (x.get("concept_list") or [])]
    for x in load_items(out_root / f"lhb_org_{date.replace('-', '')[4:]}.json"):
        org[x["thscode"]] += float(x.get("org_net_value") or 0)
    top6 = sorted(net.items(), key=lambda kv: -kv[1])[:6]

    # 指数收盘（日线历史，含涨跌幅）
    idx = []
    for code, label in [("000001.SH", "上证指数"), ("399001.SZ", "深证成指"),
                        ("399006.SZ", "创业板指"), ("000300.SH", "沪深300")]:
        j = ths_cli.run(["index", "history", "--thscode", code, "--start-ms", _ms(
            (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=20)).strftime("%Y-%m-%d")),
            "--end-ms", _ms(date), "--source", "remote", "--format", "json"], timeout=90)
        it = (j.get("data") or {}).get("item") or []
        if len(it) >= 2:
            c1, c0 = float(it[-1]["close_price"]), float(it[-2]["close_price"])
            idx.append((label, code, round(c1, 2), round((c1 / c0 - 1) * 100, 2)))

    # 当日板块涨幅（供「strong=热度高且走势好」自动判定；缺 rotation json 时退化为全 False 并标注）
    board_m1: dict = {}
    rp = out_root / f"reco_{date.replace('-', '')[4:]}" / f"rotation_{date.replace('-', '')}.json"
    if rp.exists():
        try:
            board_m1 = {r["name"]: r.get("m1") for r in json.loads(rp.read_text(encoding="utf-8"))["rows"]}
        except Exception as e:
            print(f"  ⚠️ 读 {rp.name} 失败：{e}")
    return {"lu": lu, "ld": ld, "lb": lb, "mb": mb, "seal": seal, "top": top,
            "days": days, "pools": pools, "hot": hot, "persist": persist,
            "net": net, "org": org, "concept": concept, "top6": top6, "idx": idx,
            "board_m1": board_m1}


# ------------------------------ 渲染 ------------------------------
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def build_data_block(date: str, c: dict, name_map: dict, narr: dict) -> str:
    lu, ld, lb, mb = c["lu"], c["ld"], c["lb"], c["mb"]
    seal, days = c["seal"], c["days"]
    up, dn, n = mb["up"], mb["dn"], mb["n"]
    top_cd = c["top"].get("continue_day_cnt") or 1
    top_name = name_map.get(c["top"].get("thscode", ""), "")
    wd = WEEKDAY_CN[datetime.datetime.strptime(date, "%Y-%m-%d").weekday()]
    rng = f"{days[-1][5:]}~{days[0][5:]}" if days else "—"
    ud = f"{len(lu)/max(len(ld),1):.2f} : 1"

    week_up = ", ".join(f'("{d[5:]}", {len(c["pools"].get(d, []))}, "{WEEKDAY_CN[datetime.datetime.strptime(d, "%Y-%m-%d").weekday()]}")'
                        for d in sorted(days))
    seq = "→".join(str(len(c["pools"].get(d, []))) for d in sorted(days))

    lhb = []
    for code, v in c["top6"]:
        lhb.append((name_map.get(code, code), code.split(".")[0], round(v / 1e8, 2),
                    (f"机构{c['org'][code]/1e8:+.2f}" if code in c["org"] else "无机构席位"),
                    "/".join(c["concept"].get(code, [])[:3]) or "—", 0.0))
    focus = [(x[0], x[1], f"{x[2]:+.2f}亿", x[3], x[4]) for x in lhb[:3]]

    N = lambda k, d_: narr.get(k) or d_          # noqa: E731
    diag = narr.get("DIAG") or {}
    DIAG = {
        "level": diag.get("level") or "自动生成 · 待人工复核", "badge": diag.get("badge") or "—",
        "score": diag.get("score") if isinstance(diag.get("score"), int) else 50,
        "summary": diag.get("summary") or (f"{date} 情绪概览：涨停 {len(lu)} 家、跌停 {len(ld)} 家、炸板 {len(lb)} 家、"
                                           f"封板率 {seal:.1f}%；上涨 {up} / 下跌 {dn}（中位 {mb['median']:+.2f}%）。"
                                           f"（本段为自动生成，建议人工复核）"),
        "bull": diag.get("bull") or ["（未提供，建议人工补充）"],
        "bear": diag.get("bear") or [f"涨停 {len(lu)} 家 / 跌停 {len(ld)} 家（自动生成，建议人工复核）"],
        "watch": diag.get("watch") or ["（未提供，建议人工补充）"],
    }
    SUMMARY = narr.get("SUMMARY") or [
        ("整体", f"涨停 {len(lu)} 家、跌停 {len(ld)} 家、炸板 {len(lb)} 家、封板率 {seal:.1f}%；"
                 f"上涨 {up} / 下跌 {dn}（中位 {mb['median']:+.2f}%）。本段为自动生成，建议人工复核。")]
    # 板块热度 → (关键词, 次数, strong)：strong = 该关键词能对应到当日收红的二级行业（热度高 + 走势好）
    bm = c.get("board_m1") or {}
    reds = [k for k, v in bm.items() if (v or 0) > 0]
    hot3 = []
    for w, cnt in c["hot"]:
        hit = any((w in sname) or (sname in w) for sname in reds)
        hot3.append((w, cnt, bool(hit)))
    if narr.get("SECTOR_TOP"):                      # 允许人工覆盖 strong 判定
        hot3 = [tuple(x) for x in narr["SECTOR_TOP"]]
    SECTOR_VIEW = narr.get("SECTOR_VIEW") or [
        (f"📊 {w}", "自动生成 · 待复核", f"近 5 个交易日涨停原因出现 {cnt} 次")
        for w, cnt in c["hot"][:6]
    ]

    block = f'''BASE = os.environ.get("THS_WORKSPACE", os.getcwd())
DATE = "{date}"
WEEKDAY = "{wd}"
WEEK_RANGE = "{rng}（{len(days)} 个交易日）"
SECTOR_RANGE = "{rng}"

# ================= 数据 =================
TEMP = {{"limit_up": {len(lu)}, "limit_down": {len(ld)}, "break_board": {len(lb)}, "seal_rate": {seal:.1f},
        "max_lianban": {top_cd}, "max_lianban_name": "{top_name}",
        "up_cnt": {up}, "down_cnt": {dn}, "total_cnt": {n}}}
up_ratio = TEMP["up_cnt"] / TEMP["total_cnt"] * 100
UD_RATIO = "{ud}"
INDEX = {c["idx"]!r}
HERO_SUB = {N("HERO_SUB", f"近 {len(days)} 个交易日涨停 {seq}，今日涨停 {len(lu)} / 跌停 {len(ld)}")!r}
DIAG_EXTRA = {N("DIAG_EXTRA", f"涨跌停比 {ud} · 封板率 {seal:.1f}% · 最高 {top_cd} 板 {top_name}")!r}
WEEK_INSIGHT = {N("WEEK_INSIGHT", f"💡 近 {len(days)} 个交易日涨停家数：{seq}（自动生成）")!r}
FOCUS_INSIGHT = {N("FOCUS_INSIGHT", "💡 资金焦点：见 06 龙虎榜资金表（自动生成，建议人工复核）")!r}
PERSIST_INSIGHT = {N("PERSIST_INSIGHT", "💡 持续涨停见 05 区（自动生成，建议人工复核）")!r}

# 近 {len(days)} 个交易日每日涨停家数（本地交易日历定位，自动跳过休市日）
WEEK_UP = [{week_up}]
# 板块热度（涨停原因关键词归并）
SECTOR_TOP = {hot3!r}
# 持续涨停个股（涨停天数≥3）
PERSIST_STOCK = {c["persist"]!r}
# 当日关注焦点（龙虎榜净买 TOP3 替代热榜；热榜历史接口不可回溯）
FOCUS = {focus!r}
# 龙虎榜资金（净买入 TOP6）
LHB = {lhb!r}
# 情绪诊断
DIAG = {DIAG!r}
# 综述段落
SUMMARY = {SUMMARY!r}
# 板块解读
SECTOR_VIEW = {SECTOR_VIEW!r}
NOTE = ("数据来源：同花顺金融数据（hithink-finance CLI：special.limit-up/limit-down/limit-break-pool + "
        "special.dragon-tiger 普通榜与机构榜 + index history 日线收盘）；"
        f"涨跌家数与中位数 = 本地 DuckDB 前复权日K 自算（{up} 涨 / {dn} 跌 / {mb['flat']} 平，中位 {mb['median']:+.2f}%）；"
        f"涨停 {len(lu)} / 跌停 {len(ld)} / 炸板 {len(lb)} 家 = 交易所涨跌停池口径（与「涨幅≥9.8%」不同）；"
        f"板块热度 = 近 {len(days)} 个交易日（{rng}，按本地交易日历定位、自动跳过休市日）涨停原因关键词归并；"
        "「strong = 真实主线」为组合口径（热度高且当日走势相对好），属模型判断；持续涨停 = 涨停天数 ≥3；"
        "连板梯队由涨停池 continue_day_cnt 重建；热榜历史接口不可回溯，关注焦点以龙虎榜净买 TOP3 替代。"
        "情绪诊断为主观综合判断（模型输出）。本报告仅供研究参考，不构成个人投资建议。")

'''
    return block


def render(date: str, workspace: Path, narr: dict, out_dir: Path | None = None) -> Path:
    out_root = workspace / ".workbuddy" / "output"
    out_root.mkdir(parents=True, exist_ok=True)
    nm_p = out_root / "bt_name_map.json"
    name_map = json.loads(nm_p.read_text(encoding="utf-8")) if nm_p.exists() else {}

    c = compute(date, out_root, name_map)
    print(f"  涨停 {len(c['lu'])} / 跌停 {len(c['ld'])} / 炸板 {len(c['lb'])} · 封板率 {c['seal']:.1f}% · "
          f"宽度 {c['mb']['up']}/{c['mb']['dn']}（中位 {c['mb']['median']:+.2f}%）")
    print(f"  交易日窗口：{c['days'][-1]} ~ {c['days'][0]}（{len(c['days'])} 个交易日，休市日已自动跳过）"
          f" · 每日涨停 {[len(c['pools'].get(d, [])) for d in sorted(c['days'])]}")
    print(f"  持续涨停 {len(c['persist'])} 只 · 龙虎榜 TOP1 "
          f"{name_map.get(c['top6'][0][0], c['top6'][0][0]) if c['top6'] else '—'}"
          f"（{c['top6'][0][1]/1e8:+.2f} 亿）" if c["top6"] else "  龙虎榜：无数据")
    print(f"  板块热度 strong 判定依据：当日收红的二级行业 {len([k for k, v in (c.get('board_m1') or {}).items() if (v or 0) > 0])} 个")

    data = build_data_block(date, c, name_map, narr)
    src = TPL.read_text(encoding="utf-8")
    i = src.index("BASE = ")
    j = src.index("# ================= SVG 图表 =================")
    code = src[:i] + data + src[j:]
    D = out_root / f"sentiment_{date.replace('-', '')[4:]}"
    D.mkdir(parents=True, exist_ok=True)
    op = D / f"gen_sentiment_{date.replace('-', '')[4:]}.py"
    op.write_text(code, encoding="utf-8", newline="\n")
    assert "__" + "NAME__" not in code, "数据区有未替换占位符"
    print(f"  数据版脚本 -> {op.name}")

    env = dict(os.environ, THS_WORKSPACE=str(out_dir or workspace))
    t0 = time.time()      # 产物必须是本轮新写的
    r = subprocess.run([sys.executable, str(op)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=str(out_dir or workspace))
    print("  " + (r.stdout or "").strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print((r.stderr or "")[-1500:])
        raise SystemExit(1)
    # 产物契约（2026-10-09）：模板落盘名 = `市场情绪扫描_{YYYYMMDD}.html`。
    # 原先不验证文件是否真的写出来 —— 而输出目录由 THS_WORKSPACE 决定，只改 cwd 无效 → 必须实测，
    # 且要求是**本轮新写**（否则上一轮遗留的同名文件会把失败伪装成通过）。
    report_artifact.expect(out_dir or workspace,
                           f"市场情绪扫描_{date.replace('-', '')}.html",
                           glob_hint="*情绪*.html", what="市场情绪扫描", not_before=t0)
    return out_dir or workspace


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #6 市场情绪扫描 —— 通用渲染器")
    ap.add_argument("--date", required=True)
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--data", help="叙述 JSON（HERO_SUB/DIAG_EXTRA/WEEK_INSIGHT/FOCUS_INSIGHT/PERSIST_INSIGHT/DIAG/SUMMARY/SECTOR_VIEW）")
    ap.add_argument("--out", help="HTML 输出目录（默认工作区根目录）")
    a = ap.parse_args()
    W = Path(a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd())
    narr = json.loads(Path(a.data).read_text(encoding="utf-8")) if a.data else {}
    print(f"═══ 渲染市场情绪扫描 {a.date}（工作区 {W}）═══")
    render(a.date, W, narr, Path(a.out) if a.out else None)
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
