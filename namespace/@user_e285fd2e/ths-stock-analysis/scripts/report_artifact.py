# -*- coding: utf-8 -*-
"""产物文件名契约检查（能力 #6 / #7 / #12 三个渲染器共用）。

## 为什么有这个模块（2026-10-09 实测踩到）
`render_picks_report.py` 原先**只校验数据区里 `N = ` 是否存在、不校验内容**，而模板用 `N` 生成
「精选 {N} 股推荐」标题**与文件名**。把 `N` 写成叙述串后，模板"成功"写出了
`精选周五 · 收盘后生成（…）股推荐_20261009.html` —— **渲染脚本报成功、调用方以为通过了**，
只有肉眼才看得出文件名全错。

同类的第二个缺口：三个渲染器**都没有验证产物是否真的落在自己以为的位置**。
模板的输出目录由 `THS_WORKSPACE` 决定（`BASE = os.environ.get("THS_WORKSPACE", os.getcwd())`），
只改 `cwd` 是无效的（2026-09-21 已踩过一次：`--out` 不生效、报告落到工作区根）

→ 所以「渲染成功」必须由**实测产物**定义，而不是由 subprocess 退出码定义。
本模块把这件事做成唯一实现：`expect()` 按契约名去找文件，找不到就把目录里**实际有什么**列出来。

## 契约（三个模板的落盘名，勿改公式）
| 能力 | 模板 | 文件名 |
|---|---|---|
| #6 情绪 | `gen_sentiment.py` | `市场情绪扫描_{YYYYMMDD}.html` |
| #7 轮动 | `gen_rotation.py`  | `板块轮动雷达_{YYYYMMDD}.html` |
| #12 选股 | `gen_reco_picks.py` | `精选{N}股推荐_{YYYYMMDD}.html`（N = len(STOCKS)） |

用法：
    from report_artifact import expect
    expect(out_dir, f"板块轮动雷达_{date.replace('-', '')}.html", glob_hint="*雷达_*.html")

自检（含负例）：
    python report_artifact.py --selftest
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

MIN_BYTES = 200          # 小于此值几乎一定是空壳/写了一半
HEAD_MARK = ("<!doctype html", "<html")
MTIME_SLACK = 1.0        # 允许的时钟/文件系统粒度误差（秒）


def expect(out_dir, expected_name: str, *, glob_hint: str = "*.html",
           min_bytes: int = MIN_BYTES, what: str = "报告",
           not_before: float | None = None) -> Path:
    """断言产物已按契约名落盘，返回其 Path；不合格则 SystemExit（退出码 1）。

    - `expected_name`：契约文件名（含 .html）。
    - `glob_hint`：失败时用来列出「目录里实际有什么」的通配符，便于一眼看出真因。
    - `not_before`：**本轮渲染的开始时刻**（`time.time()`）。给了就要求产物 mtime 不早于它
      —— 否则会命中**上一轮遗留的旧同名文件**，把「本次其实没写出来」误判成通过
      （2026-10-09 实测：模板改名后仍因为旧文件在场而"通过"）。
    """
    d = Path(out_dir)
    p = d / expected_name
    if not d.exists():
        raise SystemExit(f"❌ {what}输出目录不存在：{d}")
    if not p.exists():
        got = sorted(x.name for x in d.glob(glob_hint)) or sorted(x.name for x in d.glob("*"))
        raise SystemExit(
            f"❌ {what}未按契约名落盘：期望 {expected_name}\n"
            f"   目录 {d} 内实际有：{got}\n"
            f"   多半是数据区把决定文件名的变量写错了（如 #12 的 `N` 必须是 `len(STOCKS)`），"
            f"或模板的输出目录由 THS_WORKSPACE 决定、而调用方没注入正确的工作区。"
        )
    st = p.stat()
    if not_before is not None and st.st_mtime < not_before - MTIME_SLACK:
        age = not_before - st.st_mtime
        raise SystemExit(
            f"❌ {what}疑似**上一轮遗留的旧产物**：{expected_name} 的修改时间比本次渲染开始还早 {age:.1f}s\n"
            f"   → 本次渲染很可能没有真的写出文件（只改 cwd / THS_WORKSPACE 注入错 / 模板被改过）\n"
            f"   注意：本检查要求产物必须是**本轮新写**的，光有同名文件不算通过。"
        )
    n = st.st_size
    if n < min_bytes:
        raise SystemExit(f"❌ {what}疑似空壳：{expected_name} 只有 {n} bytes（< {min_bytes}）")
    head = p.read_text(encoding="utf-8", errors="replace")[:400].lower()
    if not any(m in head for m in HEAD_MARK):
        raise SystemExit(f"❌ {what}不像 HTML：{expected_name} 开头 400 字符内没有 <!DOCTYPE html / <html")
    print(f"  ✅ 产物契约通过：{expected_name}（{n:,} bytes，本轮新写）")
    return p


# ------------------------------ 自检（含负例） ------------------------------
def _selftest() -> int:
    """负例必须被报出来，正例必须通过 —— 否则等于没有检查。"""
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = "<!DOCTYPE html><html><body>" + "x" * 400 + "</body></html>"

        # 负例1：文件缺失（正是 2026-10-09 那个坑 + --out 不生效那个坑）
        try:
            expect(d, "板块轮动雷达_20261009.html", glob_hint="*雷达_*.html")
            raise AssertionError("负例1（文件缺失）未被拦下")
        except SystemExit as e:
            assert "未按契约名落盘" in str(e), e
            ok += 1
            print("  负例1（文件缺失）✅ 被拦下")

        # 负例1b：同目录有同类文件但名字不对 → 提示里要列出它（这才是"一眼看出真因"）
        (d / "板块轮动雷达_坏名字.html").write_text(good, encoding="utf-8")
        try:
            expect(d, "板块轮动雷达_20261009.html", glob_hint="*雷达_*.html")
            raise AssertionError("负例1b 未被拦下")
        except SystemExit as e:
            assert "板块轮动雷达_坏名字.html" in str(e), e
            ok += 1
            print("  负例1b（名字不匹配且列出实际文件）✅ 被拦下")

        # 负例1c：同名文件在场，但是**上一轮遗留的**（mtime 早于本轮开始）→ 必须报出来
        #   （2026-10-09 实测：模板落盘名被改掉后，上一轮留下的旧同名文件让检查误判为通过）
        stale = d / "板块轮动雷达_20261009.html"
        stale.write_text(good, encoding="utf-8")
        old = time.time() - 600
        os.utime(stale, (old, old))
        try:
            expect(d, "板块轮动雷达_20261009.html", not_before=time.time())
            raise AssertionError("负例1c（旧产物冒充本轮）未被拦下")
        except SystemExit as e:
            assert "上一轮遗留的旧产物" in str(e), e
            ok += 1
            print("  负例1c（旧同名文件冒充本轮产物）✅ 被拦下")

        # 负例2：空壳
        (d / "市场情绪扫描_20261009.html").write_text("x", encoding="utf-8")
        try:
            expect(d, "市场情绪扫描_20261009.html")
            raise AssertionError("负例2（空壳）未被拦下")
        except SystemExit as e:
            assert "空壳" in str(e), e
            ok += 1
            print("  负例2（空壳文件）✅ 被拦下")

        # 负例3：够大但不是 HTML（如把裸 JSON 写进了 .html）
        (d / "精选5股推荐_20261009.html").write_text('{"ok": false, "error": {}}' + "y" * 300,
                                                    encoding="utf-8")
        try:
            expect(d, "精选5股推荐_20261009.html")
            raise AssertionError("负例3（非 HTML）未被拦下")
        except SystemExit as e:
            assert "不像 HTML" in str(e), e
            ok += 1
            print("  负例3（非 HTML 内容）✅ 被拦下")

        # 正例（必须带 not_before，且是「刚写的」）
        (d / "精选5股推荐_20261009.html").write_text(good, encoding="utf-8")
        expect(d, "精选5股推荐_20261009.html", not_before=time.time() - 5)
        ok += 1
        print("  正例（合规产物）✅ 通过")

        # 负例4：输出目录不存在
        try:
            expect(d / "nope", "x.html")
            raise AssertionError("负例4（目录不存在）未被拦下")
        except SystemExit as e:
            assert "输出目录不存在" in str(e), e
            ok += 1
            print("  负例4（输出目录不存在）✅ 被拦下")

    print(f"\n✅ report_artifact 自检通过（{ok}/7，含 5 个负例）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="产物文件名契约检查")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
