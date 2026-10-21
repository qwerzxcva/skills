# -*- coding: utf-8 -*-
"""候选交叉取证（能力 #12 的核心）：**形态信号 × (涨停池 / 龙虎榜 / 当日主线关键词)**。

设计要点：
- 形态来源 = `scan_signals.py` 的 W底 + 60日新高（新触发）；
- 证据三条：① 当日涨停池（含连板高度与涨停原因）② 龙虎榜净买（普通榜 net_value / 机构榜 org_net_value）
  ③ 主线关键词命中（涨停原因或龙虎概念里出现当日主线词）；
- **主线关键词由当日数据自动推导**（涨停热词 TOP N + 轮动当日/20日 强势板块名），避免每天手写、
  也避免沿用上一交易日的旧主线（09-21 的教训）；可用 `--main-kw` 追加人工关键词。

⚠️ 交叉只做「取证 + 排序」，**不做买卖判断**：最终是否推荐还要过能力 #8（估值/财务/成长/风险/投资指导）。

🔴 **候选池规则 v1.4（2026-09-23）：先过「板块」，再过「涨停配额」**

**① 板块过滤（用户明确要求，数据支持）**：个股走势好但**所属板块当日收绿** → 不看好、不进池。
   依据：237 个交易日规则级回测（同一信号池，口径=次日开盘买入；`backtest_picks_rule.py --sector-dir/--sector-map`）：
   | 规则 | 日均只数 | T+5 均值 | T+5 中位 | T+5 胜率 | T+10 均值 |
   |---|---|---|---|---|---|
   | 仅涨停配额（v1.3） | 5.00 | +0.368% | −0.758% | 46.6% | +0.697% |
   | **+ 板块当日 >0（v1.4）** | **4.91** | **+1.052%** | **−0.276%** | **48.6%** | **+1.566%** |
   | + 板块 5 日 >0 | 4.93 | +0.949% | −0.337% | 48.2% | +1.349% |
   | + 板块 20 日 >0 | 4.85 | +0.755% | −0.805% | 45.8% | +1.309% |
   → **「板块当日红盘」最优**（T+5 +0.68pct、中位 +0.48pct、胜率 +2.1pt、T+10 +0.87pct），
     且只牺牲 0.09 只/天（233 天中 10 天凑不满 5 只）——「当日资金」比「中期动量」更能筛掉坏票。
   ⚠️ 口径：该股**任一**所属板块（26 板块池）当日涨幅 >0 即通过；**无板块归属者不进池**
     （26 板块成分股共 1528 只，候选覆盖率 29% —— 严格口径，宁可少给）。

🔴 **推荐候选的「涨停配额」规则（2026-09-21 规则级回测后确立，勿随意改）**
- **背景**：本模块原先按 `(证据数, 成交额)` 排序 → 事实效果 **99.4% 选到当日涨停股**（涨停=大成交额+证据+1，天然占优）。
- **规则级回测**（237 个交易日 × 每种规则 1185 笔，信号=W底∪60日新高，口径=次日开盘买入，local 前复权日K）：
  | 规则 | 涨停占比 | T+5 均值 | T+5 中位 | T+5 胜率 | T+10 均值 | 次日高开>3% |
  |---|---|---|---|---|---|---|
  | R1 涨停优先（旧） | 99.4% | −0.059% | −1.355% | 44.1% | +0.283% | 24.8% |
  | **R2 混合（涨停 ≤2 /5）** | 40.0% | **+0.368%** | **−0.758%** | **46.6%** | **+0.697%** | 11.8% |
  | R3 全未涨停 | 0% | +0.147% | −0.824% | 45.8% | +0.153% | 4.1% |
  | R4 池内随机 | 9.7% | −0.158% | −0.962% | 43.8% | −0.378% | 4.3% |
- **结论**：**R2 最优**（三项指标同时最好，且次日高开>3% 的概率从 24.8% 降到 11.8% → 可执行性更好）；
  全未涨停（R3）虽优于旧规则，但不如保留 2 只涨停；**未涨停内部要挑**（随机 R4 为负，说明"按涨幅 0~5% + 成交额"的偏好有效）。
- **因此 `picks_pool`（推荐候选池）按此生成**：涨停 ≤ `--max-limitup`（默认 `max(1, round(N×0.4))`，N=5 时为 2）按成交额取；
  其余从未涨停中按 **(是否当日涨幅 0~5% 档, 成交额)** 排序取足。规则实现只此一处。
- ⚠️ 局限：口径是「次日开盘买入」而非报告倡导的「回踩买入」；单一市场环境；均值绝对量级很小（+0.4~0.7pct）、
  中位数仍为负 —— 该规则改善的是**相对排序**，不代表能赚。

用法：
    python cross_evidence.py --date 2026-09-21 --dir <reco_MMDD> [--out-root <output>] [--main-kw "A,B"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sector_pool  # noqa: E402
from ths_indicators import limitup_pool_stats  # noqa: E402

CAND_SRC = (("W底", "w_scan"), ("60日新高", "trend_scan"))

# 涨停原因里的「非题材」词：属公司行为/财务标签，不是当日主线方向 → 推导主线词时剔除。
# 保留的才是题材类（创新药 / 城市更新 / 国资背景 / 脑机接口 / 光通信 …）。
NON_THEME_KW = {
    "业绩增长", "业绩扭亏", "业绩预增", "半年报增长", "中报增长", "年报增长", "三季报增长",
    "扭亏为盈", "预盈预增", "高送转", "股东增持", "股东减持", "员工持股", "股权激励",
    "回购", "定增", "资产重组", "资产出售", "要约收购", "控制权变更", "摘帽", "ST摘帽",
}


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


def derive_main_kw(lu_json: str, rotation_json: str, top_hot: int = 8, top_sec: int = 5) -> list[str]:
    """当日主线关键词 = 涨停热词 TOP N + 轮动「今日涨幅 TOP / 20日动量 TOP」板块名。"""
    kws: list[str] = []
    try:
        for k in limitup_pool_stats(lu_json)["hot"]:
            if k in NON_THEME_KW or k in kws:
                continue                      # 财务/公司行为标签不算主线
            kws.append(k)
            if len(kws) >= top_hot:
                break
    except Exception as e:
        print(f"  ⚠️ 热词推导失败（{e}）→ 仅用板块名")
    try:
        rows = json.load(open(rotation_json, encoding="utf-8"))["rows"]
        for r in sector_pool.top_by(rows, "m1", top_sec) + sector_pool.top_by(rows, "m20", 3):
            if r["name"] not in kws:
                kws.append(r["name"])
    except Exception as e:
        print(f"  ⚠️ 轮动板块推导失败（{e}）")
    return kws


def load_board_momentum(rotation_json: str) -> dict:
    """当日板块涨幅 {板块名: m1%}（来自 calc_rotation 的 rotation_YYYYMMDD.json）。"""
    try:
        rows = json.load(open(rotation_json, encoding="utf-8"))["rows"]
        return {r["name"]: r.get("m1") for r in rows}
    except Exception as e:
        print(f"  ⚠️ 读 {rotation_json} 失败：{e}")
        return {}


def load_sector_of(out_root: str) -> dict:
    """{个股: [板块名...]}（来自 sector_map.py 的缓存）。"""
    p = os.path.join(out_root, "sector_members.json")
    try:
        return json.load(open(p, encoding="utf-8")).get("by_stock", {})
    except Exception:
        print(f"  ⚠️ 缺板块映射 {p} → 先跑 `python sector_map.py --out-root <output>`；本次不做板块过滤")
        return {}


def build_picks_pool(cands: list[dict], top: int = 5, max_limitup: int | None = None,
                     hot_r20: float = 50.0, exclude_codes: set | None = None,
                     board_m1: dict | None = None, sector_of: dict | None = None,
                     require_board_up: bool = True
                     ) -> tuple[list[dict], list[dict]]:
    """按「涨停配额 + 资金方向 + 位置 + 量能」规则生成推荐候选池（**规则唯一实现**）。

    🔴 关键点：入参是**全部形态候选 `cands`**，不是只带「涨停/龙虎/主线」证据的 `hits`。
    原因（2026-09-21 实测）：`limit_up_reason`（涨停原因）这个字段**只有涨停股才有**，
    于是「主线关键词命中」这条证据在结构上只对涨停股生效 → 若从 `hits` 里选，池子必然 ~83% 是涨停股，
    配额规则形同虚设（实测：去重 36 只里涨停 30 只）。全部候选池里非涨停占绝大多数，才可能选出混合组合。

    规则顺序（每步记录被排除者，供报告审计表直接引用）：
      ⓪ **板块否决（v1.4 新增）**：该股任一所属板块**当日收绿**（或不在 26 板块池内）→ 不进池；
      ⓪′ **重复否决**：`exclude_codes`（最近若干期已推荐的标的）→ 沿用「同一标的 5 个交易日内不重复推荐」纪律；
      ① **资金否决**：龙虎榜普通榜净卖（缺失则看机构榜）→ 资金在派发，不进池；
      ② **位置否决**：20 日涨幅 > `hot_r20`（默认 50%，妖股线，沿用既有纪律）→ 不进池；
      ③ **涨停配额**：涨停 ≤ `max_limitup`（默认 `max(1, round(top×0.4))`，N=5→2），按成交额取；
      ④ **未涨停槽位**：按 (是否当日涨幅 0~5% 档, 量比, 成交额) 排序取足 —— 回测显示 0~5% 档 T+5 最优。
    不足时**如实少给**（不硬凑）。

    返回 `(pool, excluded)`，`excluded` 为 [{name, code, why}]。
    """
    if max_limitup is None:
        max_limitup = max(1, round(top * 0.4))

    def net_sold(c: dict) -> bool:
        """龙虎榜**净卖**判定：以普通榜 `net_value` 为主（与既有报告口径一致）；
        普通榜缺失时退看机构榜。**不要求两者同时为负**（否则「普通榜 −1.92 亿 / 机构 +0.07 亿」
        这种明显派发的会被漏掉 —— 2026-09-21 万科A 实测踩到）。"""
        n, o = c.get("lhb_net_yi"), c.get("lhb_org_yi")
        if n is not None:
            return n < 0
        return o is not None and o < 0

    # 去重：同一只可能同时命中 W底 与 60日新高
    seen: set = set()
    uniq: list[dict] = []
    for c in cands:
        if c["thscode"] in seen:
            continue
        seen.add(c["thscode"])
        uniq.append(c)

    excluded: list[dict] = []
    alive: list[dict] = []
    excl = {x.upper() for x in (exclude_codes or set())}
    use_board = bool(require_board_up and board_m1 and sector_of)
    for c in uniq:
        # ⚠️ 判定顺序刻意安排：**先记最有信息量的原因**（重复 → 资金 → 位置），板块过滤放最后。
        #    否则「不在 26 板块池内」会把「妖股线 / 龙虎净卖」等原因全部盖住，审计表失去信息量（2026-09-23 实测）。
        if c["thscode"].upper() in excl:
            excluded.append({"name": c["name"], "code": c["thscode"],
                             "why": "最近若干期已推荐 → 沿用「同一标的 5 个交易日内不重复推荐」纪律"})
            continue
        if net_sold(c):
            excluded.append({"name": c["name"], "code": c["thscode"],
                             "why": f"龙虎榜净卖（普通 {c.get('lhb_net_yi')} 亿 / 机构 {c.get('lhb_org_yi')}）→ 资金派发，列观察"})
            continue
        r20 = c.get("r20")
        if r20 is not None and r20 > hot_r20:
            excluded.append({"name": c["name"], "code": c["thscode"],
                             "why": f"20日 {r20:+.1f}% 超妖股线 {hot_r20:.0f}% → 位置否决"})
            continue
        if use_board:
            boards = sector_of.get(c["thscode"].upper(), [])
            if not boards:
                excluded.append({"name": c["name"], "code": c["thscode"],
                                 "why": "不在 26 板块池成分股内（无法确认板块走势）→ 板块维度不过关"})
                continue
            ups = [b for b in boards if (board_m1.get(b) or 0) > 0]
            if not ups:
                downs = "、".join(f"{b} {board_m1.get(b):+.2f}%" for b in boards[:3])
                excluded.append({"name": c["name"], "code": c["thscode"],
                                 "why": f"所属板块当日收绿（{downs}）→ 板块不配合，个股形态再好也不进池"})
                continue
        alive.append(c)

    lu = sorted([c for c in alive if c["in_lu"]], key=lambda c: -c["amt_yi"])[:max_limitup]
    rest = [c for c in alive if not c["in_lu"]]
    rest.sort(key=lambda c: (not (0 <= (c.get("break_pct") or 0) <= 5), -(c.get("vr") or 0), -c["amt_yi"]))
    pool = (lu + rest)[:top]
    return pool, excluded


def cross(date: str, out_dir: str, out_root: str, main_kw: list[str] | None = None,
          name_map_path: str | None = None, top: int = 5, max_limitup: int | None = None,
          exclude_codes: set | None = None, require_board_up: bool = True) -> dict:
    mmdd = date.replace("-", "")[4:]
    nm_path = name_map_path or os.path.join(out_root, "bt_name_map.json")
    name_map = {}
    if os.path.exists(nm_path):
        name_map = json.load(open(nm_path, encoding="utf-8"))
    else:
        print(f"  ⚠️ 缺名称映射 {nm_path} → 暂用代码占位（跑一次 bt_backtest 会生成）")

    w = json.load(open(os.path.join(out_dir, f"w_scan_{mmdd}.json"), encoding="utf-8"))["items"]
    t = json.load(open(os.path.join(out_dir, f"trend_scan_{mmdd}.json"), encoding="utf-8"))["items"]
    lu = _items(os.path.join(out_root, f"lu_{mmdd}.json"))
    lhb = _items(os.path.join(out_root, f"lhb_{mmdd}.json"))
    lhb_org = _items(os.path.join(out_root, f"lhb_org_{mmdd}.json"))

    if main_kw is None:
        main_kw = derive_main_kw(os.path.join(out_root, f"lu_{mmdd}.json"),
                                 os.path.join(out_dir, f"rotation_{date.replace('-', '')}.json"))
    print(f"  当日主线关键词（自动推导 {len(main_kw)} 个）：{' / '.join(main_kw)}")

    lu_map = {x.get("thscode"): x for x in lu}
    net, cl, netorg = defaultdict(float), defaultdict(set), defaultdict(float)
    for x in lhb:
        c = x.get("thscode")
        net[c] += float(x.get("net_value") or 0)
        for k in (x.get("concept_list") or []):
            cl[c].add(k.get("name") if isinstance(k, dict) else k)
    for x in lhb_org:
        netorg[x.get("thscode")] += float(x.get("org_net_value") or 0)

    hit_main = lambda text: [k for k in main_kw if k in (text or "")]
    cands = []
    for src, arr in (("W底", w), ("60日新高", t)):
        for r in arr:
            c = r["thscode"]
            info = lu_map.get(c) or {}
            kw = sorted(set(hit_main(info.get("limit_up_reason")) + hit_main(" ".join(cl.get(c, [])))))
            cands.append({"src": src, "thscode": c, "name": name_map.get(c, c),
                          "close": r["close"], "break_pct": r.get("break_pct"), "amt_yi": r["amount_yi"],
                          "vr": r["vol_ratio"], "r1": r.get("r1"), "r5": r.get("r5"),
                          "r20": r.get("r20"), "r60": r.get("r60"),
                          "in_lu": bool(info), "lu_reason": info.get("limit_up_reason"),
                          "lu_cd": info.get("continue_day_cnt"),
                          "lhb_net_yi": round(net[c] / 1e8, 2) if c in net else None,
                          "lhb_org_yi": round(netorg[c] / 1e8, 2) if c in netorg else None,
                          "lhb_concepts": sorted(cl.get(c, [])), "main_kw": kw,
                          "n_evidence": (1 if info else 0) + (1 if c in net else 0) + (1 if kw else 0)})

    hits = sorted([c for c in cands if c["n_evidence"] >= 1],
                  key=lambda x: (-x["n_evidence"], -x["amt_yi"]))
    print(f"\n形态信号合计 {len(cands)} → 命中证据 {len(hits)} 只")
    print(f"  {'源':8s}{'名称':10s}{'代码':11s}{'收盘':>8s}{'日涨':>8s}{'额亿':>7s}{'量比':>6s}"
          f"{'5日':>8s}{'20日':>8s}{'60日':>9s}  证据")
    for c in hits:
        tag = []
        if c["in_lu"]:
            tag.append(f"涨停{c['lu_cd']}板")
        if c["lhb_net_yi"] is not None:
            tag.append(f"龙虎{c['lhb_net_yi']:+.2f}亿")
        if c["lhb_org_yi"]:
            tag.append(f"机构{c['lhb_org_yi']:+.2f}亿")
        if c["main_kw"]:
            tag.append("主线:" + "/".join(c["main_kw"][:3]))
        print(f"  {c['src']:8s}{str(c['name'])[:8]:10s}{c['thscode']:11s}{c['close']:>8.2f}"
              f"{c['break_pct']:>+8.2f}{c['amt_yi']:>7.2f}{c['vr']:>6.2f}{c['r5']:>8}{c['r20']:>8}"
              f"{c['r60']:>9}  {' · '.join(tag)}")
        if c["lu_reason"]:
            print(f"  {'':8s}  ↳ 涨停原因: {c['lu_reason']}")

    board_m1 = load_board_momentum(os.path.join(out_dir, f"rotation_{date.replace('-', '')}.json"))
    sector_of = load_sector_of(out_root)
    if require_board_up and board_m1 and sector_of:
        up = sum(1 for v in board_m1.values() if (v or 0) > 0)
        print(f"  板块过滤：当日 {up}/{len(board_m1)} 个板块收红；成分股映射 {len(sector_of)} 只")
    pool, excluded = build_picks_pool(cands, top=top, max_limitup=max_limitup,
                                      exclude_codes=exclude_codes,
                                      board_m1=board_m1, sector_of=sector_of,
                                      require_board_up=require_board_up)
    n_lu = sum(1 for c in pool if c["in_lu"])
    print(f"\n═══ 推荐候选池（从全部 {len(cands)} 条形态候选按规则取；涨停 ≤"
          f"{max_limitup if max_limitup is not None else max(1, round(top * 0.4))} / 共 {top}）═══")
    for i, c in enumerate(pool, 1):
        tag = []
        if c["in_lu"]:
            tag.append(f"涨停{c['lu_cd']}板")
        if c["lhb_net_yi"] is not None:
            tag.append(f"龙虎{c['lhb_net_yi']:+.2f}亿")
        if c["main_kw"]:
            tag.append("主线:" + "/".join(c["main_kw"][:2]))
        print(f"  {i}. {str(c['name'])[:8]:10s}{c['thscode']:11s} {c['close']:>8.2f} {c['break_pct']:>+7.2f}% "
              f"{c['amt_yi']:>7.2f}亿 | {' · '.join(tag)}")
    print(f"  （涨停 {n_lu} / {len(pool)}；未涨停 {len(pool) - n_lu} —— 见模块文档串的回测依据）")

    if excluded:
        print(f"\n  规则排除 {len(excluded)} 只（写报告 05/06 审计表直接用）：")
        for e in excluded:
            print(f"    ✗ {str(e['name'])[:8]:10s}{e['code']:11s} {e['why']}")
    out = {"date": date, "main_kw": main_kw, "all": cands, "hits": hits,
           "picks_pool": pool, "picks_excluded": excluded,
           "picks_rule": {"top": top, "max_limitup": max_limitup}}
    op = os.path.join(out_dir, f"cands_{mmdd}.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n落盘 -> {op}（全部 {len(cands)}，命中 {len(hits)}，推荐候选池 {len(pool)}）")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="候选交叉取证：形态 × (涨停/龙虎榜/当日主线)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--dir", required=True, help="reco_MMDD 目录（形态与轮动 json 所在）")
    ap.add_argument("--out-root", help=".workbuddy/output 目录（池/龙虎榜/名称映射所在，默认 --dir 的上级）")
    ap.add_argument("--main-kw", help="人工追加的主线关键词（逗号分隔），会与自动推导的合并")
    ap.add_argument("--name-map", help="bt_name_map.json 路径")
    ap.add_argument("--top", type=int, default=5, help="推荐候选池数量（默认 5）")
    ap.add_argument("--max-limitup", type=int, help="池内涨停股上限（默认 max(1, round(top×0.4))）")
    ap.add_argument("--exclude-codes", help="排除的标的代码（逗号分隔；最近若干期已推荐者，5 日内不重复）")
    ap.add_argument("--no-board-filter", action="store_true",
                    help="关闭「板块当日红盘」过滤（默认开启，v1.4；依据见模块文档串回测）")
    a = ap.parse_args()
    root = a.out_root or os.path.dirname(os.path.abspath(a.dir))
    extra = [x.strip() for x in (a.main_kw or "").split(",") if x.strip()]
    kw = None
    if extra:
        base = derive_main_kw(os.path.join(root, f"lu_{a.date.replace('-', '')[4:]}.json"),
                              os.path.join(a.dir, f"rotation_{a.date.replace('-', '')}.json"))
        kw = list(dict.fromkeys(base + extra))
    excl = {x.strip().upper() for x in (a.exclude_codes or "").split(",") if x.strip()}
    cross(a.date, a.dir, root, kw, a.name_map, top=a.top, max_limitup=a.max_limitup,
          exclude_codes=excl, require_board_up=not a.no_board_filter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
