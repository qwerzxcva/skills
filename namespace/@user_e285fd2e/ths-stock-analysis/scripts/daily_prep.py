# -*- coding: utf-8 -*-
"""日更链路一键编排（能力 #12 协同选股的「数据 + 候选」阶段）。

一条命令跑完：**数据门禁 → 并行取数 → 导出前复权 parquet → 形态扫描 → 板块轮动 → 候选交叉取证 → 交接清单**。
之后只剩两件事需要人/Agent 做：① 逐只写 why / risk / plan 叙述；② 渲染选股报告。

用法：
    python daily_prep.py --date 2026-09-21                  # 默认工作区 = 当前目录（或 THS_WORKSPACE）
    python daily_prep.py --date 2026-09-21 --workspace D:/AI/理财/同花顺二次开发
    python daily_prep.py --date 2026-09-21 --no-sync        # 不跑 data sync（本地库已确认含当日时）
    python daily_prep.py --date 2026-09-21 --main-kw "创新药,城市更新"   # 追加人工主线词

产物（`<工作区>/.workbuddy/output/`）：
    lu_/ld_/lb_/lhb_/lhb_org_<MMDD>.json     当日涨停/跌停/炸板池 + 龙虎榜（普通/机构）
    reco_<MMDD>/idx_*.json                  27 条指数历史（26 板块 + 上证，回溯约 4 个月）
    reco_<MMDD>/etf_<MMDD>.json             板块 ETF 当日快照（轮动报告用）
    reco_<MMDD>/rotation_<YYYYMMDD>.json     26 板块多窗口动量 + 量比 + 超额
    reco_<MMDD>/bt_qfq_scan.parquet          本地前复权日K（形态扫描用）
    reco_<MMDD>/w_scan_/trend_scan_/ranges__<MMDD>.json   W底 / 60日新高 / 区间涨幅
    reco_<MMDD>/cands_<MMDD>.json            形态 × (涨停/龙虎榜/当日主线) 候选

⚠️ 两条经验（2026-09-21 实测）：
1. `ensure_data.py --check` 的判据是「日历中 < 今天 的最大日期」，**不含当天** → 当天出当天报告必须直接跑 `data sync`
   （本脚本默认按本地库 `max(date)` 判断，缺当日就同步；`data sync` 耗时可达 150s+，故与 API 取数**并行**）。
2. 单次 CLI 调用固定开销 ~1.2s → 所有独立调用都走 `ths_cli.run_many` 并行（27 条指数 41.9s → 12.4s）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calc_rotation  # noqa: E402
import cross_evidence  # noqa: E402
import scan_signals  # noqa: E402
import sector_pool  # noqa: E402
import ths_cli  # noqa: E402
from ths_indicators import limitup_pool_stats, market_breadth  # noqa: E402

ETF_POOL = {
    "512010.SH": "医药ETF易方达", "512200.SH": "房地产ETF南方", "512480.SH": "半导体ETF国联安",
    "515880.SH": "通信ETF国泰", "159825.SZ": "农业ETF富国", "512400.SH": "有色金属ETF南方",
    "512800.SH": "银行ETF华宝",
}
IDX_SNAPSHOT = ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH"]
IDX_LOOKBACK_START = "2026-05-01"      # 指数历史起点（≥61 个交易日，够算 60 日动量）


def _shift(date: str, days: int) -> str:
    """目标日 ± 若干自然日（用于指数历史的起点）。"""
    dt = datetime.datetime.strptime(date, "%Y-%m-%d") + datetime.timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def _ms(d: str) -> str:
    return str(int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp() * 1000))


def _local_max_date() -> str | None:
    """本地库最新交易日（读 v_daily_qfq）。"""
    try:
        import duckdb
        con = duckdb.connect(ths_cli.duckdb_path(), read_only=True)
        try:
            return str(con.execute("SELECT max(date) FROM v_daily_qfq").fetchone()[0])
        finally:
            con.close()
    except Exception as e:
        print(f"  ⚠️ 读本地库失败：{e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="日更链路一键编排：取数 → 扫描 → 轮动 → 候选")
    ap.add_argument("--date", required=True, help="目标交易日 YYYY-MM-DD")
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sync", dest="sync", action="store_true", default=None, help="强制先跑 data sync")
    ap.add_argument("--no-sync", dest="sync", action="store_false", help="不跑 data sync")
    ap.add_argument("--main-kw", help="追加人工主线关键词（逗号分隔）")
    ap.add_argument("--skip-parquet", action="store_true", help="跳过 parquet 导出与形态扫描")
    ap.add_argument("--force-refetch", action="store_true",
                    help="忽略本地已有的当日数据文件，强制重新拉取（默认：同目标日的有效文件直接复用）")
    ap.add_argument("--only-special", action="store_true",
                    help="只重取当日池/龙虎榜（上游限流恢复后补数用），其余步骤跳过")
    a = ap.parse_args()

    T = time.time()
    W = Path(a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd())
    out_root = W / ".workbuddy" / "output"
    mmdd = a.date.replace("-", "")[4:]
    D = out_root / f"reco_{mmdd}"
    D.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)
    print(f"═══ 日更链路 {a.date} ═══")
    print(f"  工作区 {W}")
    print(f"  输出   {D}")

    # ── 0) 数据门禁（判断是否需要 data sync；决定后**先起同步线程**，与 API 取数并行）──
    local_max = _local_max_date()
    need_sync = (a.sync is True) or (a.sync is None and (local_max or "") < a.date)
    print(f"\n[0] 数据门禁：本地库最新 = {local_max}，目标 = {a.date} → "
          f"{'需要同步（与取数并行跑）' if need_sync else '已含当日，跳过同步'}")
    sync_res: dict = {}

    def _do_sync():
        t0 = time.time()
        sync_res.update(ths_cli.run(["data", "sync"], timeout=1200) or {})
        sync_res["_sec"] = round(time.time() - t0, 1)
        print(f"    ↳ data sync 完成 rc_ok={ths_cli.ok(sync_res)} 耗时 {sync_res['_sec']}s "
              f"release={(sync_res.get('data') or {}).get('release_id')}")

    th = threading.Thread(target=_do_sync, daemon=True) if need_sync else None
    if th:
        th.start()

    # ── 1) 并行取数：当日池/龙虎榜 + 27 条指数历史 + ETF 快照 ──
    t1 = time.time()
    pools = [
        (f"lu_{mmdd}.json", ["special", "limit-up-pool", "--date-ms", _ms(a.date), "--size", "200",
                             "--sort-field", "continue_day_cnt", "--sort-dir", "desc", "--format", "json"]),
        (f"ld_{mmdd}.json", ["special", "limit-down-pool", "--date-ms", _ms(a.date), "--size", "100", "--format", "json"]),
        (f"lb_{mmdd}.json", ["special", "limit-break-pool", "--date-ms", _ms(a.date), "--size", "100", "--format", "json"]),
        (f"lhb_{mmdd}.json", ["special", "dragon-tiger", "--date", a.date, "--format", "json"]),
        (f"lhb_org_{mmdd}.json", ["special", "dragon-tiger", "--date", a.date, "--board-type", "org", "--format", "json"]),
    ]
    idx_calls = [["index", "history", "--thscode", c, "--start-ms", _ms(IDX_LOOKBACK_START),
                  "--end-ms", _ms(a.date), "--source", "remote", "--format", "json"]
                 for c in sector_pool.codes(with_benchmark=True)]
    etf_calls = [["fund", "snapshot", "--thscode", c] for c in ETF_POOL]
    # ⚠️ 不要用 `index snapshot`：它返回**实时行情**。在非当日跑历史日期时会拿到"今天的盘中价"，
    #    把前一交易日的收盘价当成本日收盘（2026-09-23 实测：目标 09-22，snapshot 给的是 09-23 盘中 3938.08 −0.36%，
    #    而 09-22 真实收盘是 3952.13 +0.06%）→ 一律用 `index history` 截到目标日，取最后两根算涨跌。
    snap_calls = [["index", "history", "--thscode", c, "--start-ms", _ms(_shift(a.date, -20)),
                   "--end-ms", _ms(a.date), "--source", "remote", "--format", "json"]
                  for c in IDX_SNAPSHOT]

    # 🔴 分组并发（2026-09-21 实测）：`special` 特色数据接口并发高会被上游限流（FUYAO_5002 timeout），
    #    龙虎榜整表还常 >90s → 单独用 workers<=3 + 重试 + 180s 超时；行情/基础接口用 workers=8。
    t_special = time.time()
    # ① 已有且有效的当日文件直接复用（当天反复跑时不必重复拉同一批数据）
    pool_res: list = [None] * len(pools)
    todo = []
    for i, (fn, args) in enumerate(pools):
        p = out_root / fn
        if not a.force_refetch and p.exists():
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                if ths_cli.ok(j):
                    pool_res[i] = j
                    continue
            except Exception:
                pass
        todo.append(i)
    if pool_res.count(None):
        sub = ths_cli.run_many([pools[i][1] for i in todo], workers=min(3, len(todo)),
                               timeout=90, retries=1, backoff=3.0)
        for i, j in zip(todo, sub):
            pool_res[i] = j
    reused = len(pools) - len(todo)
    if a.only_special:
        for (fn, _), j in zip(pools, pool_res):
            if j is not None:
                (out_root / fn).write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        bad = [fn for (fn, _), j in zip(pools, pool_res) if not ths_cli.ok(j)]
        print(f"  special 补数完成（复用 {reused} / 重取 {len(todo)}）：{'✅ 全部有效' if not bad else '❌ 仍失败 ' + ', '.join(bad)}")
        return 1 if bad else 0
    print(f"    （special 组：复用 {reused} / 重取 {len(todo)}，用时 {time.time()-t_special:.1f}s）")

    t_rest = time.time()
    rest = ths_cli.run_many(idx_calls + etf_calls + snap_calls, workers=a.workers, timeout=120, retries=1)
    n_idx = len(idx_calls)
    idx_res = rest[:n_idx]
    etf_res = rest[n_idx:n_idx + len(etf_calls)]
    snap_res = rest[n_idx + len(etf_calls):]
    snap: dict = {}                     # 由历史接口算出的「指数收盘 + 涨跌」
    for c, j in zip(IDX_SNAPSHOT, snap_res):
        it = (j.get("data") or {}).get("item") or []
        if len(it) >= 2:
            d1 = datetime.datetime.fromtimestamp(it[-1]["date_ms"] / 1000).strftime("%Y-%m-%d")
            c1, c0 = float(it[-1]["close_price"]), float(it[-2]["close_price"])
            snap[c] = {"date": d1, "last_price": round(c1, 2), "price_change_ratio_pct": round((c1 / c0 - 1) * 100, 2)}
    (D / f"idx_close_{mmdd}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"    （行情/基础组 {n_idx + len(etf_calls) + 1} 个调用，用时 {time.time()-t_rest:.1f}s）")
    for (fn, _), j in zip(pools, pool_res):
        (out_root / fn).write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    idx_bad = []
    for c, j in zip(sector_pool.codes(with_benchmark=True), idx_res):
        items = (j.get("data") or {}).get("item") or []
        last = (datetime.datetime.fromtimestamp(items[-1]["date_ms"] / 1000).strftime("%Y-%m-%d") if items else None)
        (D / f"idx_{c.replace('.', '_')}.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        if last != a.date:
            idx_bad.append(f"{c}({last})")
    (D / f"etf_{mmdd}.json").write_text(
        json.dumps({c: j for c, j in zip(ETF_POOL, etf_res)}, ensure_ascii=False), encoding="utf-8")
    n_pool = len(pools)
    ok_pool = sum(1 for j in pool_res if ths_cli.ok(j))
    bad_pool = [fn for (fn, _), j in zip(pools, pool_res) if not ths_cli.ok(j)]
    print(f"\n[1] 并行取数 {time.time()-t1:.1f}s：池/龙虎榜 {ok_pool}/{n_pool} · "
          f"指数 {n_idx - len(idx_bad)}/{n_idx} 到 {a.date} · ETF {sum(1 for j in etf_res if ths_cli.ok(j))}/{len(etf_calls)}")
    if bad_pool:
        print(f"    ❌ 未取到的文件：{', '.join(bad_pool)}")
        print(f"       原因多为上游限流/超时（FUYAO_5002，夜间尤甚）。恢复后补数："
              f"python {os.path.basename(__file__)} --date {a.date} --only-special")
        print(f"       ⚠️ 相关派生指标（如封板率、龙虎榜证据）将缺失，报告中不得臆造。")
    if idx_bad:
        print(f"    ⚠️ 未到目标日的指数：{idx_bad[:5]}")

    # ── 2) 等同步完成 → 导出 parquet ──
    if th:
        print("\n[2] 等 data sync 结束…")
        th.join()
    pq = D / "bt_qfq_scan.parquet"
    if not a.skip_parquet:
        t2 = time.time()
        sql = ("SELECT thscode, date, open, high, low, close, volume, amount FROM v_daily_qfq "
               "WHERE date >= DATE '2025-06-01'")
        j = ths_cli.run(["db", "export", "--sql", sql, "--output", str(pq).replace("\\", "/"),
                         "--file-format", "parquet"], timeout=600)
        print(f"\n[2] parquet 导出 {time.time()-t2:.1f}s → {pq.name} "
              f"{pq.stat().st_size/1e6:.1f} MB" if pq.exists() else f"    ❌ 导出失败 {j.get('error')}")
    else:
        print("\n[2] 跳过 parquet / 形态扫描")

    # ── 3) 板块轮动 ──
    t3 = time.time()
    rot = calc_rotation.compute(str(D), a.date)
    json.dump(rot, open(D / f"rotation_{a.date.replace('-', '')}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[3] 板块轮动 {time.time()-t3:.1f}s：{len(rot['rows'])} 板块，problems={len(rot['problems'])}；"
          f"上证 {rot['sh_close']}（20日 {rot['sh_m20']:+.2f}%）")

    # ── 4) 形态扫描 ──
    if not a.skip_parquet:
        t4 = time.time()
        w, tr, stats = scan_signals.scan(str(pq), a.date)
        json.dump({"date": a.date, "count": len(w), "items": w},
                  open(D / f"w_scan_{mmdd}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump({"date": a.date, "count": len(tr), "items": tr},
                  open(D / f"trend_scan_{mmdd}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(stats, open(D / f"ranges_{mmdd}.json", "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n[4] 形态扫描 {time.time()-t4:.1f}s：W底 {len(w)} 只 / 60日新高 {len(tr)} 只（universe {len(stats)}）")

    # ── 5) 候选交叉取证 ──
    t5 = time.time()
    # 确保「个股↔板块映射」存在（成分股按季度调整，缓存命中即不重取）
    try:
        import sector_map
        sm = sector_map.members(str(out_root))
        print(f"    板块映射：{len(sm['by_sector'])} 个板块 / {len(sm['by_stock'])} 只成分股")
    except Exception as e:
        print(f"    ⚠️ 板块映射构建失败（{e}）→ 本次不做板块过滤")

    # 收集「最近 5 个交易日内」推荐过的标的（纪律：同一标的 5 个交易日内不重复推荐）
    # ⚠️ 口径修正（2026-09-28）：原先按「最近 6 个报告文件」粗筛 —— 报告不连续时会算错
    #    （例如 09-25 没出报告，则 09-16/09-17 的票仍被算进来，实际已超 5 个交易日 → 误排除）
    #    改为用**本地交易日历精确定位最近 6 个交易日**（含目标日），只排除落在该窗口内的报告。
    recent: set = set()
    try:
        import re as _re
        import duckdb as _dd
        con = _dd.connect(ths_cli.duckdb_path(), read_only=True)
        try:
            win = [str(r[0]) for r in con.execute(
                f"SELECT DISTINCT date FROM raw_kline_daily WHERE date <= DATE '{a.date}' "
                f"ORDER BY date DESC LIMIT 6").fetchall()]
        finally:
            con.close()
        win_excl = {d for d in win if d != a.date}          # 含目标日的最近 6 个交易日，去掉目标日本身
        reports = []
        for rp in W.glob("精选*_2026*.html"):
            m = _re.search(r"(20\d{6})", rp.name)
            if not m:
                continue
            d8 = m.group(1)
            iso = f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"
            if iso in win_excl:
                reports.append((iso, rp))
        for iso, rp in reports:
            recent |= {m.upper() for m in _re.findall(r'<span class="tcode">([0-9]{6}\.[A-Z]{2})</span>',
                                                      rp.read_text(encoding="utf-8", errors="replace"))}
        print(f"    5 个交易日窗口 = {sorted(win_excl)}（命中 {len(reports)} 份报告）")
    except Exception as e:
        print(f"    ⚠️ 读取历史推荐失败（{e}）→ 未自动排除重复标的，请人工确认")
    if recent:
        print(f"    （自动排除窗口内 {len(recent)} 只已推荐标的：{', '.join(sorted(recent))}）")
    extra = [x.strip() for x in (a.main_kw or "").split(",") if x.strip()]
    kw = None
    if extra:
        base = cross_evidence.derive_main_kw(str(out_root / f"lu_{mmdd}.json"),
                                            str(D / f"rotation_{a.date.replace('-', '')}.json"))
        kw = list(dict.fromkeys(base + extra))
    print(f"\n[5] 候选交叉取证 {time.time()-t5:.1f}s")
    cand = cross_evidence.cross(a.date, str(D), str(out_root), kw, exclude_codes=recent)

    # ── 6) 交接清单 ──
    lu = limitup_pool_stats(str(out_root / f"lu_{mmdd}.json"))
    mb = market_breadth(a.date)
    lb_items = cross_evidence._items(str(out_root / f"lb_{mmdd}.json"))
    # ⚠️ 炸板数据缺失时**绝不算封板率**（否则算出 100% 这种错数）——真实来源：交易所炸板池
    seal_txt = (f"{lu['n'] / (lu['n'] + len(lb_items)) * 100:.1f}%（炸板 {len(lb_items)} 家）"
                if lb_items else "⚠️ 炸板池数据缺失（本次 special limit-break-pool 未取到）→ 不计算")
    snap_rows = snap
    print("\n" + "=" * 78)
    print(f"交接清单（写叙述 & 渲染选股报告时直接引用这些数，勿手抄）")
    print("=" * 78)
    print(f"  市场宽度 : 全市场 {mb['n']} 只，{mb['up']} 涨 / {mb['dn']} 跌 / {mb['flat']} 平，"
          f"中位 {mb['median']:+.2f}%、均值 {mb['mean']:+.2f}%")
    print(f"  涨停结构 : {lu['n']} 家（{lu['board_text']}）；封板率 {seal_txt}")
    print(f"  涨停热词 : {' / '.join(f'{k} {v}' for k, v in list(lu['hot'].items())[:8])}")
    idx_txt = " · ".join(f"{c} {snap_rows[c]['last_price']} {snap_rows[c]['price_change_ratio_pct']:+.2f}%"
                         for c in IDX_SNAPSHOT if c in snap_rows) or "（指数历史未取到）"
    print(f"  指数快照 : {idx_txt}")
    r20 = sector_pool.top_by(rot["rows"], "m20", 3)
    r1 = sector_pool.top_by(rot["rows"], "m1", 3)
    rdn = [r for r in rot["rows"] if r["m1"] <= 0]
    txt1 = " / ".join(r["name"] + f" {r['m1']:+.2f}%" for r in r1)
    txt20 = " / ".join(r["name"] + f" {r['m20']:+.2f}%" for r in r20)
    txtdn = " / ".join(r["name"] + f" {r['m1']:+.2f}%" for r in rdn) or "无"
    print(f"  板块 今日前三 : {txt1}")
    print(f"  板块 20日前三 : {txt20}")
    print(f"  板块 收绿     : {txtdn}")
    print(f"  当日主线词    : {' / '.join(cand['main_kw'])}")
    seen: set = set()
    uniq = []
    for c in cand["hits"]:                      # 同一只可能同时命中 W底 与 60日新高 → 展示去重
        if c["thscode"] in seen:
            continue
        seen.add(c["thscode"])
        uniq.append(c)
    pool = cand.get("picks_pool") or []
    print(f"  推荐候选池（涨停配额规则，涨停 {sum(1 for c in pool if c['in_lu'])}/{len(pool)}）——**写叙述就用这 {len(pool)} 只**：")
    for i, c in enumerate(pool, 1):
        tag = []
        if c["in_lu"]:
            tag.append(f"涨停{c['lu_cd']}板")
        if c["lhb_net_yi"] is not None:
            tag.append(f"龙虎{c['lhb_net_yi']:+.2f}亿")
        if c["lhb_org_yi"]:
            tag.append(f"机构{c['lhb_org_yi']:+.2f}亿")
        if c["main_kw"]:
            tag.append("主线:" + "/".join(c["main_kw"][:2]))
        print(f"    {i}. {str(c['name'])[:8]:10s}{c['thscode']:11s} {c['close']:>8.2f} {c['break_pct']:>+7.2f}% "
              f"{c['amt_yi']:>7.2f}亿 量比{c['vr']:>5.2f} | r5 {c['r5']:>7} r20 {c['r20']:>7} | {' · '.join(tag)}")

    print(f"\n  【参考】全部命中候选（去重后 {len(uniq)} 只）Top 12：")
    for c in uniq[:12]:
        tag = []
        if c["in_lu"]:
            tag.append(f"涨停{c['lu_cd']}板")
        if c["lhb_net_yi"] is not None:
            tag.append(f"龙虎{c['lhb_net_yi']:+.2f}亿")
        if c["lhb_org_yi"]:
            tag.append(f"机构{c['lhb_org_yi']:+.2f}亿")
        if c["main_kw"]:
            tag.append("主线:" + "/".join(c["main_kw"][:2]))
        print(f"    {str(c['name'])[:8]:10s}{c['thscode']:11s} {c['close']:>8.2f} {c['break_pct']:>+7.2f}% "
              f"{c['amt_yi']:>7.2f}亿 量比{c['vr']:>5.2f} | r5 {c['r5']:>7} r20 {c['r20']:>7} | {' · '.join(tag)}")
    print(f"\n  下一步：")
    print(f"    1) 逐只写 why / risk / plan（数据区见 {D.name}/cands_{mmdd}.json + tech/tech_ 指标）")
    print(f"    2) 渲染选股报告；轮动报告：python {os.path.join(HERE, 'render_rotation_report.py')} --date {a.date}")
    print(f"\n总耗时 {time.time()-T:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
