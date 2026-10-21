# -*- coding: utf-8 -*-
"""能力 #13 价值投资配置 —— 有效性判定 + 缓存 + 渲染（**这个能力不要求频繁更新**）

设计（按用户要求）：
- **第一次询问** → 生成配置报告（HTML）+ 落盘 `config.json`（记录生成日、有效期、锚点的基准值）
- **之后每次询问** → 先跑本脚本的判定：**仍有效就直接返回已有报告**（不重新生成）；**失效才重新生成**
- 失效条件（任一成立）：
  1. **超期**：今天 > `valid_until`（生成日 + 180 天）
  2. **锚点漂移**：**5 个锚点**（沪深300 / 黄金ETF / 纳指ETF / 红利低波ETF / 10年国债ETF）
     自生成日以来的变动超过各自阈值（±25% / ±30% / ±30% / ±25% / ±5%）
     （v5 起去掉美元债QDII——该资产已移出配置）
     ⚠️ **`ANCHORS` 与模板 `gen_value_investing.py` 的 `ANCHOR_TEXT` 必须逐项配对一致** ——
     **已由 `--selftest` 机械断言**（含负例自证），不必靠记忆。

用法：
    python value_investing.py                 # 判定 → 有效则直接返回，失效/首次则重新生成
    python value_investing.py --status         # 只看状态（不渲染）
    python value_investing.py --force          # 强制重新生成
    python value_investing.py --selftest       # 自检判定逻辑（合成用例）

缓存位置：`<工作区>/.workbuddy/output/value_investing/config.json`
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ths_cli  # noqa: E402

TPL = os.path.join(HERE, "gen_value_investing.py")
CACHE_DIR = os.path.join(".workbuddy", "output", "value_investing")
CACHE_NAME = "config.json"
VALID_DAYS = 180

# 锚点：(代码, 名称, 取值方式, 漂移阈值%)  —— 阈值越小的资产，价格越「稳」，越能反映框架是否过期
# ⚠️ 必须与 gen_value_investing.py 的 ANCHOR_TEXT 保持一致（v5 去掉美元债QDII：该资产已移出配置）
ANCHORS = [
    ("000300.SH", "沪深300（A股估值锚）", "index", 25.0),
    ("518880.SH", "黄金ETF（黄金锚）", "fund", 30.0),
    ("513100.SH", "纳指ETF（美股锚）", "fund", 30.0),
    ("512890.SH", "红利低波ETF（红利锚）", "fund", 25.0),
    ("511260.SH", "10年国债ETF（利率锚）", "fund", 5.0),
]


def _ms(d: str) -> str:
    return str(int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp() * 1000))


def fetch_anchors(today: str) -> dict:
    """取 6 个锚点的当前值（index 用日线收盘，fund 用快照）。"""
    out: dict = {}
    for code, name, kind, thr in ANCHORS:
        if kind == "index":
            j = ths_cli.run(["index", "history", "--thscode", code, "--start-ms", _ms("2026-01-01"),
                             "--end-ms", _ms(today), "--source", "remote", "--format", "json"], timeout=60)
            items = (j.get("data") or {}).get("item") or []
            px = float(items[-1].get("close_price")) if items else None
        else:
            j = ths_cli.run(["fund", "snapshot", "--thscode", code], timeout=60)
            items = (j.get("data") or {}).get("item") or []
            px = float(items[0].get("last_price")) if items and items[0].get("last_price") else None
        out[code] = {"name": name, "kind": kind, "threshold_pct": thr, "price": round(px, 4) if px else None}
    return out


def check(cache: dict | None, today: str, anchors: dict | None = None) -> tuple[bool, list[str]]:
    """返回 (是否仍有效, 失效原因列表)。anchors=None 时只判超期（离线也能判）。"""
    if not cache:
        return False, ["首次使用：尚无配置缓存"]
    reasons: list[str] = []
    if today > (cache.get("valid_until") or ""):
        reasons.append(f"超期（生成日 {cache.get('generated_at')}，有效期至 {cache.get('valid_until')}）")
    if anchors:
        for code, cur in anchors.items():
            old = (cache.get("anchors") or {}).get(code) or {}
            p0, p1, thr = old.get("price"), cur.get("price"), cur.get("threshold_pct") or 0
            if not p0 or not p1:
                continue
            dev = abs(p1 / p0 - 1) * 100
            if dev > thr:
                reasons.append(f"{cur['name']} 漂移 {dev:+.1f}%（阈值 ±{thr:.0f}%）")
    return (not reasons), reasons


def render(base: str, today: str, anchors: dict) -> str:
    """跑模板渲染 HTML（模板内的数据区是长期框架，不随锚点变动）。

    ⚠️ 必须把生成日**注入模板**（`THS_VALUE_DATE`）：模板按自己的 `DATE` 命名文件，
    若不给它，换一天重新生成时会写成上一期的文件名、**覆盖上期报告**，
    而本函数返回的却是新日期路径 → 缓存里的 `html` 指向不存在的文件（2026-10-08 实测踩到）。
    """
    env = dict(os.environ, THS_WORKSPACE=base, THS_VALUE_DATE=today)
    r = subprocess.run([sys.executable, TPL], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=base)
    print("  " + (r.stdout or "").strip())
    if r.returncode != 0:
        print((r.stderr or "")[-1500:])
        raise SystemExit(1)
    out = os.path.join(base, f"价值投资配置_{today.replace('-', '')}.html")
    # 不"假设"路径：落盘才算数（旧实现只返回假想路径，与实际产物脱节且无人发现）
    if not os.path.exists(out):
        raise SystemExit(f"模板未产出预期报告（实际产物名与生成日不一致）：{out}")
    return out


def summary_alloc() -> str:
    """从模板读出配比摘要（供「仍有效→直接返回」时一并告知）。"""
    try:
        src = open(TPL, encoding="utf-8").read()
        i = src.index("ALLOC = [")
        j = src.index("]", i)
        rows = eval(src[i + len("ALLOC = "):j + 1])  # noqa: S307 —— 自家模板的字面量
        # ⚠️ 列序：(资产, 类别, 稳健, 平衡, 进取, 作用) → **平衡是 r[3]，不是 r[2]**
        #    （2026-10-08 修：旧代码取 r[2]，把「稳健」档当成 balanced 写进了缓存，
        #      所以缓存摘要一直显示的是稳健列——与函数名/字段名都不符。）
        bal = [f"{r[0]} {r[3]}" for r in rows]
        return " · ".join(bal)
    except Exception as e:
        return f"（读取配比摘要失败：{e}）"


def main() -> int:
    ap = argparse.ArgumentParser(description="能力 #13 价值投资配置：有效性判定 + 渲染")
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--date", help="生成日（默认今天）")
    ap.add_argument("--status", action="store_true", help="只判状态，不渲染")
    ap.add_argument("--force", action="store_true", help="强制重新生成")
    ap.add_argument("--selftest", action="store_true", help="自检判定逻辑")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    base = a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd()
    today = a.date or datetime.date.today().strftime("%Y-%m-%d")
    cp = os.path.join(base, CACHE_DIR, CACHE_NAME)
    cache = json.loads(open(cp, encoding="utf-8").read()) if os.path.exists(cp) else None

    print(f"═══ 能力 #13 价值投资配置 · 有效性判定（{today}）═══")
    if cache:
        print(f"  已有配置：生成于 {cache.get('generated_at')}，有效至 {cache.get('valid_until')}，"
              f"报告 {os.path.basename(cache.get('html') or '')}")
    else:
        print("  尚无配置缓存（首次使用）")

    anchors = None if a.status and not a.force else fetch_anchors(today)
    ok, reasons = check(cache, today, anchors)
    if a.force:
        ok, reasons = False, reasons or ["--force 强制重新生成"]
    if anchors:
        for code, v in anchors.items():
            old = ((cache or {}).get("anchors") or {}).get(code) or {}
            dev = (f"{(v['price']/old['price']-1)*100:+.1f}%" if old.get("price") and v.get("price") else "—")
            print(f"    {v['name']:<20} 现值 {v['price']}  相对生成日 {dev}  (阈值 ±{v['threshold_pct']:.0f}%)")

    if ok:
        print("\n  ✅ 配置仍有效 —— 直接返回已有报告，不重新生成")
        print(f"     HTML：{cache.get('html')}")
        print(f"     平衡档配比：{summary_alloc()}")
        print(f"     失效条件：超期（> {cache.get('valid_until')}）或任一锚点漂移超阈值")
        return 0

    print("\n  ⚠️ 配置需重新生成，原因：")
    for r in reasons:
        print("     -", r)
    html = render(base, today, anchors or {})
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    new_cache = {
        "generated_at": today,
        "valid_until": (datetime.datetime.strptime(today, "%Y-%m-%d")
                        + datetime.timedelta(days=VALID_DAYS)).strftime("%Y-%m-%d"),
        "anchors": anchors or {},
        "html": html,
        "alloc_balanced": summary_alloc(),
    }
    json.dump(new_cache, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  ✅ 已重新生成并更新缓存：{cp}")
    print(f"     HTML：{html}")
    return 0


def selftest() -> int:
    """自检：超期 / 漂移 / 正常 三类判定是否按预期工作。"""
    print("=" * 72)
    print("value_investing 判定逻辑自检")
    print("=" * 72)
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails += 1

    A = lambda p: {c: {"name": n, "threshold_pct": t, "price": p} for c, n, _k, t in ANCHORS}
    base = {"generated_at": "2026-01-01", "valid_until": "2026-06-30", "anchors": A(100.0)}

    ok, why = check(base, "2026-03-01", A(100.0))
    chk(ok, f"未超期 + 无漂移 → 有效（{why}）")
    ok, why = check(base, "2026-08-01", A(100.0))
    chk((not ok) and any("超期" in w for w in why), f"超期 → 失效（{why}）")
    # 沪深300 阈值 25%：涨 20% 仍有效、涨 30% 失效
    p = A(100.0)
    p["000300.SH"]["price"] = 120.0
    ok, why = check(base, "2026-03-01", p)
    chk(ok, f"沪深300 +20%（阈值 25%）→ 仍有效（{why}）")
    p["000300.SH"]["price"] = 130.0
    ok, why = check(base, "2026-03-01", p)
    chk((not ok) and any("沪深300" in w for w in why), f"沪深300 +30% → 失效（{why}）")
    # 利率锚阈值小（5%）：国债 ETF +6% 应失效
    p = A(100.0)
    p["511260.SH"]["price"] = 106.0
    ok, why = check(base, "2026-03-01", p)
    chk((not ok) and any("国债" in w for w in why), f"国债ETF +6%（阈值 5%）→ 失效（{why}）")
    chk(check(None, "2026-03-01", A(100.0))[0] is False, "无缓存 → 需生成")

    # 锚点定义必须与模板里的 ANCHOR_TEXT 一致
    # （原先是「改一处要改两处」的文字约定 → 2026-09-30 改成代码断言，不靠人记）
    # ⚠️ 必须逐项比对「代码 ↔ 阈值」的配对，只查「字符串是否存在」检不出改错阈值
    #    （首版就是这么写的，负例一跑就露馅）
    try:
        src = open(TPL, encoding="utf-8").read()
        i = src.index("ANCHOR_TEXT = (")
        j = src.index(")", i)                       # 串内只有全角括号，首个半角 ) 即闭合
        txt = eval(src[i + len("ANCHOR_TEXT = "):j + 1])  # noqa: S307 —— 自家模板的字面量
        got = {}
        for seg in txt.split("、"):
            cm = re.search(r"(\d{6}\.[A-Z]{2})", seg)
            if not cm:
                continue
            tm = re.search(r"±\s*(\d+(?:\.\d+)?)\s*%", seg)
            got[cm.group(1)] = float(tm.group(1)) if tm else None
        want = {c: float(t) for c, _n, _k, t in ANCHORS}
        chk(got == want, f"ANCHORS ↔ 模板 ANCHOR_TEXT 逐项配对一致"
                         f"（模板 {len(got)} 项 / 脚本 {len(want)} 项；差异："
                         f"{ {k: (want.get(k), got.get(k)) for k in set(want) | set(got) if want.get(k) != got.get(k)} }）")
        # 负例：改错任一阈值必须能检出（否则等于没检查）
        bumped = {**want, next(iter(want)): want[next(iter(want))] + 5}
        chk(got != bumped, "负例：模板阈值被改错时能检出")
    except Exception as e:  # noqa: BLE001
        chk(False, f"无法解析模板 ANCHOR_TEXT：{e}")
    except Exception as e:  # noqa: BLE001
        chk(False, f"无法解析模板 ANCHOR_TEXT：{e}")

    print(f"\n自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
