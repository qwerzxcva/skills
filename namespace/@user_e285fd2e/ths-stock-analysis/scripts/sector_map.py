# -*- coding: utf-8 -*-
"""个股 ↔ 同花顺行业板块 映射（能力 #7/#12 的板块维度基础）。

来源：`index constituents --thscode <881xxx.TI>`（26 个权威板块，见 `sector_pool.py`）。
产出：`<out-root>/sector_members.json` —— `{板块名: [成分股 thscode...]}` + 反向索引 `{个股: [板块名...]}`。
缓存策略：成分股按季度调整，默认命中缓存即不重取；`refresh=True` 或 `--refresh` 强制重取（26 次调用，并行约 4s）。

为什么需要它：用户明确要求「**从当前走势好的板块里挑股票**，个股走势好但所属板块不行的不看好」——
那就必须先知道每只候选属于哪些板块，再用当日板块动量判断"板块行不行"（坑 71）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sector_pool  # noqa: E402
import ths_cli  # noqa: E402

CACHE_NAME = "sector_members.json"


def _pull() -> dict:
    codes = sector_pool.codes()
    res = ths_cli.run_many([["index", "constituents", "--thscode", c] for c in codes],
                           workers=8, timeout=120, retries=1)
    out: dict[str, list[str]] = {}
    for c, j in zip(codes, res):
        name = sector_pool.name_of(c)
        items = (j.get("data") or {}).get("item") or (j.get("data") or {}).get("items") or []
        mem = []
        for x in items:
            code = x.get("thscode") if isinstance(x, dict) else None
            if code:
                mem.append(code.upper())
        out[name] = sorted(set(mem))
        print(f"  {'✅' if mem else '❌'} {name:<10} {len(mem):>5} 只")
    return out


def members(out_root: str, refresh: bool = False) -> dict:
    """返回 {"by_sector": {...}, "by_stock": {...}, "pulled_at": ...}。"""
    p = os.path.join(out_root, CACHE_NAME)
    if os.path.exists(p) and not refresh:
        try:
            d = json.load(open(p, encoding="utf-8"))
            # 缓存必须与当前板块池一致：板块池扩容/改名后旧缓存要自动失效重建（2026-09-23 教训：
            # 旧缓存只有 26 个板块、覆盖率 27.5%，若沿用会让「板块过滤」静默退化）
            cached = set(d.get("by_sector") or {})
            if cached and cached == set(sector_pool.SECTORS):
                return d
            print(f"  ⚠️ 板块映射缓存与当前板块池不一致（缓存 {len(cached)} 个 / 池 {len(sector_pool.SECTORS)} 个）→ 重建")
        except Exception as e:
            print(f"  ⚠️ 读缓存失败（{e}）→ 重建")
    print("  拉取 26 个板块成分股（并行）…")
    by_sector = _pull()
    by_stock: dict[str, list[str]] = {}
    for sec, lst in by_sector.items():
        for code in lst:
            by_stock.setdefault(code, []).append(sec)
    d = {"pulled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "by_sector": by_sector, "by_stock": by_stock}
    os.makedirs(out_root, exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cov = len(by_stock)
    print(f"  成分股合计 {cov} 只（去重后，覆盖 26 板块时代的 1528 只 → 现为全市场）→ {p}")
    return d


def sector_of(mapping: dict, code: str) -> list[str]:
    return mapping.get("by_stock", {}).get(code.upper(), [])


def main() -> int:
    ap = argparse.ArgumentParser(description="个股↔板块映射（26 个同花顺行业板块成分股）")
    ap.add_argument("--out-root", required=True, help=".workbuddy/output 目录（缓存落这里）")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--codes", help="查询若干代码所属板块（逗号分隔）")
    a = ap.parse_args()
    d = members(a.out_root, a.refresh)
    if a.codes:
        for c in [x.strip().upper() for x in a.codes.split(",") if x.strip()]:
            print(f"  {c}: {'/'.join(sector_of(d, c)) or '（不在 26 板块池内）'}")
    else:
        print(f"  板块 {len(d['by_sector'])} 个 · 覆盖个股 {len(d['by_stock'])} 只 · 更新于 {d['pulled_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
