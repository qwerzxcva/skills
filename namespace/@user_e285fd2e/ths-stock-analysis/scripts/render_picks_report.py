# -*- coding: utf-8 -*-
"""选股报告渲染（能力 #12 第二步）：把**数据区文件**注入 `gen_reco_picks.py` 模板并产出 HTML。

为什么拆成「数据区文件 + 本脚本」：
- 数据区里**只有每只股票的 why / risk / plan 等叙述需要人写**（其余市场级数字应由 `daily_prep.py` 的交接清单提供）；
- 注入逻辑（模板锚点、路径、自检、运行）不该每天重写一遍 —— 那就是 09-18 之前每天复制 500 行构建器的原因。

数据区文件的要求（本脚本会校验）：
- 必须含 `DATE = "YYYY-MM-DD"`（与 `--date` 一致）
- 必须含 `STOCKS = [`（推荐卡列表）
- 必须重新定义 TPL 数据区里的所有变量（模板是把整段数据区替换掉的）：`GEN / BT_* / BANNER / KPIS / IDX / LINES / INSIGHT01 / INSIGHT03 / STOCKS / EVID / AUDIT_ROWS / NOTE / CLS / N`
- 生成后自动跑 `check_build.py --script`（未绑定名 / 手抄当日数字 / 裸引号等），**通过后**才执行渲染

用法：
    python render_picks_report.py --date 2026-09-21 --data <工作区>/.workbuddy/output/reco_0921/picks_data_0921.py [--out <HTML 目录>]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_artifact  # noqa: E402

REQUIRED = ("GEN", "BT_SCOPE", "BANNER", "KPIS", "IDX", "LINES", "STOCKS", "NOTE", "CLS", "N")


def build_and_render(date: str, data_file: Path, workspace: Path,
                     out_html_dir: Path | None = None, tpl: Path | None = None) -> Path:
    tpl = tpl or (HERE / "gen_reco_picks.py")
    data = data_file.read_text(encoding="utf-8")

    # ── 校验数据区 ──
    m = re.search(r'^DATE\s*=\s*"([\d-]+)"', data, re.M)
    if not m:
        raise SystemExit("数据区缺少 `DATE = \"YYYY-MM-DD\"`")
    if m.group(1) != date:
        raise SystemExit(f"数据区 DATE={m.group(1)} 与 --date {date} 不一致")
    if "STOCKS = [" not in data:
        raise SystemExit("数据区缺少 `STOCKS = [`")
    # ⚠️ `N` 必须就是股数本身（2026-10-09 实测踩到）：模板用 `N` 生成
    #    「精选 {N} 股推荐」标题 **与文件名**，而原校验只查 `^N =` 是否存在 →
    #    把 N 写成叙述串时渲染「成功」，却产出
    #    `精选周五 · 收盘后生成（…）股推荐_20261009.html` 这种文件名。
    if not re.search(r"^N\s*=\s*len\(STOCKS\)", data, re.M):
        raise SystemExit("数据区的 `N` 必须是 `N = len(STOCKS)`（模板用它生成标题与文件名）；"
                         "写成叙述串会产出错误文件名")
    miss = [k for k in REQUIRED if not re.search(rf"^{k}\s*=", data, re.M)]
    if miss:
        raise SystemExit(f"数据区缺少模板要求的变量（整段替换，必须全部重定义）：{miss}")
    n_cards = len(re.findall(r"^\s*dict\(", data, re.M))
    print(f"  数据区校验通过：DATE={date}，推荐卡 {n_cards} 张")

    # ── 注入模板数据区 ──
    src = tpl.read_text(encoding="utf-8")
    tpl_date = re.search(r'DATE = "[\d-]+"', src)
    s1 = tpl_date.start() if tpl_date else src.index("DATE =")
    s2 = src.index("# ---------- 渲染 ----------")
    out_root = workspace / ".workbuddy" / "output"
    mmdd = date.replace("-", "")[4:]
    D = out_root / f"reco_{mmdd}"
    D.mkdir(parents=True, exist_ok=True)
    out_py = D / f"gen_reco_{mmdd}.py"
    out_py.write_text(src[:s1] + data.rstrip() + "\n\n" + src[s2:], encoding="utf-8", newline="\n")
    print(f"  数据版脚本 -> {out_py.name}")

    # ── 自检（未绑定名 / 手抄当日数字 / 裸引号 …）──
    ck = HERE / "check_build.py"
    if ck.exists():
        r = subprocess.run([sys.executable, str(ck), "--script", str(out_py), "--template", str(tpl)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        # ⚠️ 只认「❌ [编号]」这种结果行；汇总结论行形如「小结：❌ 0 / ⚠️ 1」也含 ❌，误判过（2026-09-21）
        out = (r.stdout or "")
        bad = [l for l in out.splitlines() if "❌ [" in l]
        warn = [l for l in out.splitlines() if "⚠️  [" in l or "⚠️ [" in l]
        if r.returncode == 1 and not bad:
            bad = [l for l in out.splitlines() if l.strip().startswith("小结")]
        print(f"  自检：{'✅ 通过' if not bad else '❌ 存在 FAIL'}"
              + (f"（{len(warn)} 条告警）" if warn else ""))
        for l in bad[:6]:
            print("    " + l.strip()[:150])
        if bad or r.returncode == 1:
            raise SystemExit("自检未通过（见上），已中止渲染")

    # ── 运行（模板用 THS_WORKSPACE 决定 HTML 输出目录）──
    env = dict(os.environ, THS_WORKSPACE=str(out_html_dir or workspace))
    t0 = time.time()      # 产物必须是本轮新写的（见下方 report_artifact.expect 的 not_before）
    r = subprocess.run([sys.executable, str(out_py)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=str(out_html_dir or workspace))
    print("  " + (r.stdout or "").strip().replace("\n", "\n  "))
    if r.returncode != 0:
        print((r.stderr or "")[-2000:])
        raise SystemExit(1)
    # ── 产物文件名契约（2026-10-09）：模板按 `精选{N}股推荐_{YYYYMMDD}.html` 落盘（N = len(STOCKS)）。
    #    统一走 `report_artifact.expect` —— **实测**文件在、非空壳、是 HTML；
    #    否则数据区把 N 写坏时，模板会"成功"写出一个名字全错的文件，而调用方以为渲染通过。
    report_artifact.expect(out_html_dir or workspace,
                           f"精选{n_cards}股推荐_{date.replace('-', '')}.html",
                           glob_hint="*股推荐_*.html", what="选股报告", not_before=t0)
    return out_html_dir or workspace


def main() -> int:
    ap = argparse.ArgumentParser(description="选股报告渲染（能力 #12）")
    ap.add_argument("--date", required=True)
    ap.add_argument("--data", required=True, help="数据区文件（含 DATE/GEN/BT_*/STOCKS/NOTE 等）")
    ap.add_argument("--workspace", help="工作区（默认 THS_WORKSPACE 或当前目录）")
    ap.add_argument("--out", help="HTML 输出目录（默认工作区根目录）")
    ap.add_argument("--tpl", help="gen_reco_picks.py 路径（默认同目录）")
    a = ap.parse_args()
    W = Path(a.workspace or os.environ.get("THS_WORKSPACE") or os.getcwd())
    print(f"═══ 渲染精选选股报告 {a.date}（工作区 {W}）═══")
    build_and_render(a.date, Path(a.data), W, Path(a.out) if a.out else None,
                     Path(a.tpl) if a.tpl else None)
    print("✅ 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
