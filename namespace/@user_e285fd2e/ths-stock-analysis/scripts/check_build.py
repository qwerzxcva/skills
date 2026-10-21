# -*- coding: utf-8 -*-
"""构建自检器：把「数据区替换 + 渲染产物」这一链路的坑变成可执行校验。

为什么要有它
------------
本项目一半的坑不是「接口限制」，而是**自己做数据版脚本时的手滑**，且多为**静默失败**
（不报错、数字看着正常）：数据区漏了 `NAME = ` 前缀、`DATE/WEEKDAY` 没换导致文件名与数据错配、
模板数据区里的变量没重新定义 → 跑到渲染段才 NameError、中文引号写成裸 `"` 导致 SyntaxError、
`re.sub` 替换串含反斜杠报 bad escape……靠记忆和事后 grep 一个个查，成本极高。
本脚本把这些判据固化下来，**构建完跑一次即可**，不必依赖记忆。

用法
----
    python check_build.py --builder build_xxx.py                    # 构建器静态检查
    python check_build.py --script  gen_xxx_0917.py --template gen_xxx.py
    python check_build.py --html    产物.html [--hist hist.json] [--expect-date 2026-09-17]
    python check_build.py --codes   codes.txt                       # CLI 参数清单文件 CRLF 检查
    python check_build.py --auto    <任意路径...>                    # 按扩展名自动分派
    python check_build.py --selftest                                # 自检（用故意写坏的样本证明每条检查有效）

退出码：0=全过 / 1=有 ❌ / 2=只有 ⚠️

校验项与对应坑
--------------
| 检查 | 内容 | 对应坑 |
|---|---|---|
| B1 | 构建器用 `re.sub(pat, "字符串")` 而非 lambda | 53 |
| B2 | 构建器里残留与本脚本 DATE 不一致的日期字面量 | 33 |
| B3 | 构建器 `TPL_PATH` 指向不存在的文件 | — |
| B4 | 构建器里出现被批量引号替换改坏的 `「, 」` 之类 | 59 |
| S1 | 生成脚本能否编译（裸 ASCII 双引号会 SyntaxError） | 58 |
| S2 | **未绑定名检测**（数据区漏变量/漏 `NAME = ` 前缀/f-string 引用构建器变量） | 42 / 44 / 52 / 54 |
| S3 | 数据区里出现转义的裸引号 `\\"`（编译能过但会渲染出裸引号） | 58 |
| S4 | 生成脚本 vs 模板的变量集合差异（少了=❌，多了=ℹ️ 常为拼写错） | 42 / 44 / 54 / 60 |
| S5 | `DATE` / `WEEKDAY` 是否仍是模板默认值 | 55 |
| H1 | `<title>` 与产物文件名同口径 | 55 |
| H2 | 占位符 `__X__` 残留 | — |
| H3 | 残留 markdown `**加粗**`（HTML 不解析，会原样显示星号） | 46 |
| H4 | `[MISSING]` 计数（超过 --allow-missing 才 ⚠️） | — |
| H5 | 模板旧特征值残留（--old 给关键词） | 27② / 13⑦ / 16⑦ |
| H6 | 走势图点数（速览卡应恒为 252） | 61 |
| H7 | 补丁工具留下的「空壳」（`** **` / `（）` 等：反引号被 shell 吃掉） | —（本检查即约束） |
| H8 | 禁用行话（黑名单见 `BANNED_JARGON`，如「一腿」） | —（同上） |
| L3 | **宽表装不进容器**（`.wrap` 内容宽 < 最宽表 `min-width` → 用户要拉横向进度条） | —（同上） |
| C1 | HIST 只有 6 个字段、键名正确 | 56① |
| C2 | HIST 价格已 round(x,2)（未 round 的 17 位浮点会撑大产物） | 56② |
| C3 | HIST 日期升序/唯一/根数（<252 会触发模板 WARN） | 61 |
| K1 | 喂 CLI 的参数清单文件含 `\\r`（CRLF） | 28 |
"""
from __future__ import annotations

import argparse
import ast
import builtins
import io
import json
import os
import py_compile
import re
import sys
import tempfile

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"
_ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌", INFO: "ℹ️ "}

# H7：补丁工具留下的「空壳」特征串（写补丁时反引号被 shell 吃掉 → 文本消失只剩空壳）
SHELL_VOIDS = ("** **", "（）", "(见 )", "见 ）", "复核 **")
# H8：禁用行话——用户明确说看不懂的词，报告里一律不出现（需要时在此追加）
BANNED_JARGON = ("一腿", "这一腿", "两条腿", "三条腿", "美股腿", "债券腿", "黄金腿", "红利腿")


class Report:
    def __init__(self, title: str):
        self.title = title
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, tag: str, msg: str):
        self.items.append((level, tag, msg))

    def dump(self) -> int:
        n_fail = sum(1 for lv, _, _ in self.items if lv == FAIL)
        n_warn = sum(1 for lv, _, _ in self.items if lv == WARN)
        print(f"\n{'=' * 72}\n{self.title}\n{'=' * 72}")
        for lv, tag, msg in self.items:
            print(f"  {_ICON[lv]} [{tag}] {msg}")
        if not self.items:
            print("  （无可检查项）")
        print(f"\n  小结：❌ {n_fail} / ⚠️ {n_warn} / 共 {len(self.items)} 项")
        return 1 if n_fail else (2 if n_warn else 0)


# --------------------------------------------------------------------------- #
# AST 工具
# --------------------------------------------------------------------------- #
_BUILTINS = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "self", "cls"}


def _coverage(needle: str, hay: str) -> float:
    """needle 的字符（多重集）有多大比例出现在 hay 里——用于判断 title 是否覆盖了文件名主体。"""
    if not needle:
        return 1.0
    from collections import Counter
    a, b = Counter(needle), Counter(hay)
    hit = sum(min(v, b.get(ch, 0)) for ch, v in a.items())
    return hit / sum(a.values())


def _target_names(node: ast.AST) -> set[str]:
    """递归收集赋值目标里的名字（含解包、for/with/推导式目标）。"""
    out: set[str] = set()
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for e in node.elts:
            out |= _target_names(e)
    elif isinstance(node, ast.Starred):
        out |= _target_names(node.value)
    return out


def scan_names(src: str) -> tuple[set[str], set[str]]:
    """返回 (被赋值的名字, 被读取的名字)。

    赋值侧覆盖：Assign / AnnAssign / AugAssign / For / With(as) / 推导式 /
    except as / global / 函数名 / 类名 / import / `globals()["X"] = ...`。
    读取侧覆盖所有 `ast.Name` 的 Load 上下文。
    """
    tree = ast.parse(src)
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in tgts:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "globals":
                    # globals()["X"] = ... 形式的动态注入
                    sl = t.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        assigned.add(sl.value)
                    continue
                assigned |= _target_names(t)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            assigned |= _target_names(node.target)
        elif isinstance(node, ast.comprehension):
            assigned |= _target_names(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            assigned |= _target_names(node.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            assigned.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assigned.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for a in list(node.args.args) + list(node.args.kwonlyargs) + list(node.args.posonlyargs):
                    assigned.add(a.arg)
                if node.args.vararg:
                    assigned.add(node.args.vararg.arg)
                if node.args.kwarg:
                    assigned.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            for a in list(node.args.args) + list(node.args.kwonlyargs) + list(node.args.posonlyargs):
                assigned.add(a.arg)
        elif isinstance(node, ast.Import):
            for al in node.names:
                assigned.add((al.asname or al.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for al in node.names:
                assigned.add(al.asname or al.name)
        elif isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            assigned |= set(node.names)
    used = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return assigned, used


# --------------------------------------------------------------------------- #
# 构建器检查
# --------------------------------------------------------------------------- #
_DATE8 = re.compile(r"\b(20\d{2})(0[1-9]|1[0-2])([0-2]\d)\b")
_DATE_DASH = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def check_builder(path: str) -> Report:
    src = open(path, encoding="utf-8", errors="replace").read()
    rep = Report(f"构建器检查：{os.path.basename(path)}")

    # 本脚本自己的日期基准（取第一个出现的日期字面量作为基准）
    dates = _DATE_DASH.findall(src) + [f"{a}-{b}-{c}" for a, b, c in _DATE8.findall(src)]
    base = dates[0] if dates else None

    # B1 re.sub 的替换串不是 lambda（坑 53）
    for m in re.finditer(r"\.subn?\(\s*([^,]+),\s*([^,)]+)", src):
        repl = m.group(2).strip()
        line = src[: m.start()].count("\n") + 1
        if not (repl.startswith("lambda") or repl.startswith("__") or repl.startswith("_repl")):
            if re.search(r'^["\']', repl) or re.search(r"^\w+\s*$", repl):
                rep.add(WARN, "B1", f"第 {line} 行 `re.sub(..., {repl[:28]}…)` 替换串不是 lambda → "
                                    f"内容含 `\\` 会报 bad escape（坑 53）。写法：`pat.sub(lambda _m, _t=txt: _t, src)`")
    # B2 残留其它日期（坑 33）
    if base:
        others = {d for d in dates if d != base}
        if others:
            rep.add(WARN, "B2", f"本脚本日期基准={base}，但还出现其它日期 {sorted(others)[:6]} → "
                                f"疑似复制旧脚本未替换全（坑 33）。改完必须 grep 全部 open()/json.dump 目标名")
    # B3 TPL_PATH 指向不存在的文件
    for m in re.finditer(r"TPL_PATH\s*=\s*r?[\"']([^\"']+)[\"']", src):
        tgt = m.group(1)
        if not os.path.exists(tgt):
            rep.add(FAIL, "B3", f"TPL_PATH 不存在：{tgt}（skill 目录可能已改名；"
                                f"建议改用 glob 自动定位，见 references/构建个人量化平台指南.md）")
    # B4 批量引号替换改坏的痕迹（坑 59）
    bad = re.findall(r"「\s*,\s*」|「\s*」|「\)|「\]", src)
    if bad:
        rep.add(FAIL, "B4", f"发现 {len(bad)} 处疑似被批量引号替换改坏的 `「, 」`/空引号（坑 59）——"
                            f"合法的元组分隔符 `\", \"` 曾被误换，逐处核对")
    if not rep.items:
        rep.add(OK, "B*", "未发现构建器层面的已知隐患")
    return rep


# --------------------------------------------------------------------------- #
# 生成脚本检查
# --------------------------------------------------------------------------- #
def check_script(path: str, template: str | None, expect_date: str | None) -> Report:
    src = open(path, encoding="utf-8", errors="replace").read()
    rep = Report(f"生成脚本检查：{os.path.basename(path)}")

    # S1 编译（坑 58 的裸引号会在这里暴露）
    try:
        compile(src, path, "exec")
    except SyntaxError as e:
        msg = f"{e.msg}（第 {e.lineno} 行）"
        rep.add(FAIL, "S1", f"无法编译 → 多半是数据区写了裸 ASCII 双引号（坑 58，中文强调改用「」）：{msg}")
        return rep
    except Exception as e:  # pragma: no cover
        rep.add(FAIL, "S1", f"编译异常：{e}")
        return rep

    # S2 未绑定名检测（坑 42/44/52/54）
    try:
        assigned, used = scan_names(src)
    except SyntaxError as e:
        rep.add(FAIL, "S2", f"AST 解析失败：{e}")
        return rep
    unbound = sorted(n for n in used - assigned - _BUILTINS if not n.startswith("__"))
    if unbound:
        rep.add(FAIL, "S2", "存在「被读取但从未赋值」的名字（跑了必 NameError，或数据区漏了 `NAME = ` 前缀）："
                            + ", ".join(unbound[:12]) + ("…" if len(unbound) > 12 else "")
                            + "　→ 坑 42/44/52/54 排查口诀：数据区变量必须带 `NAME = `，"
                              "且模板数据区原有的变量要全部重新定义")
    else:
        rep.add(OK, "S2", "无未绑定名（数据区变量齐全，含 `NAME = ` 前缀）")

    # N 叙述常量（坑 64 的脚本化；传入脚本路径以便做「可溯源」判定）
    check_narration_constants(src, rep, path)

    # V 配比一致性（仅对含 ALLOC 的能力脚本生效）
    check_alloc_consistency(src, rep)

    # S3 数据区转义裸引号（坑 58 隐蔽形态）
    trio = re.search(r"={2,}[^\n]*数据[^\n]*={2,}(.+?)(?:={2,}[^\n]*渲染[^\n]*={2,}|# -{2,} 渲染)", src, re.S)
    seg = trio.group(1) if trio else src
    n_esc = len(re.findall(r'\\"', seg))
    if n_esc:
        rep.add(WARN, "S3", f"数据区出现 {n_esc} 处 `\\\"`（会被还原成裸引号，坑 58 的隐蔽形态）——"
                            f"中文强调一律用「」，不要用英文双引号")

    # S5 DATE / WEEKDAY 是否仍是模板默认值（坑 55）
    def _const(name: str, s: str):
        """取**最后一个** `NAME = "..."` —— 不是第一个（2026-10-13 实测踩到）。

        为什么：`render_rotation_report.py` / `render_sentiment_report.py` 走的是「双锚点替换数据区」，
        注入区间是「数据区标记**之间**」，而**模板自己的示例 `DATE` 落在标记之前**、不在替换范围内
        → 生成脚本里会出现**两个** DATE：前者是模板默认值（残留）、后者是真实日期（生效）。
        取第一个会把模板默认值当成真实值 → S5 误报「与模板默认值相同」。
        （`render_picks_report.py` 的替换起点就是模板第一个 `DATE = "`，所以它只有一个 DATE，不受影响。）
        """
        vals = re.findall(rf'^{name}\s*=\s*[\'"]([^\'"]*)[\'"]', s, re.M)
        return vals[-1] if vals else None

    if template and os.path.exists(template):
        tsrc = open(template, encoding="utf-8", errors="replace").read()
        t_date, g_date = _const("DATE", tsrc), _const("DATE", src)
        if t_date and g_date == t_date:
            rep.add(WARN, "S5", f"`DATE` 与模板默认值相同（{g_date}）→ 若这是新一天的数据版脚本说明忘了替换："
                                f"文件名会变成模板日期（坑 55）")
        elif expect_date and g_date and g_date.replace("-", "") != expect_date.replace("-", ""):
            rep.add(FAIL, "S5", f"`DATE`={g_date} 与期望 {expect_date} 不一致 → 产物文件名会错（坑 55）")
        else:
            # 补 OK 分支（2026-10-13）：原来通过时**不产生任何 S5 条目**，
            # 自检无法断言「不误报」—— 而这次的缺陷恰恰就是误报，必须能被断言。
            rep.add(OK, "S5", f"`DATE`={g_date} 取的是**生效值**（最后一个 DATE 赋值），"
                              f"与模板默认值 {t_date} 不同 ✓")
        # S4 变量集合比对（坑 42/44/54/60）
        t_assigned, _ = scan_names(tsrc)
        g_assigned, _ = scan_names(src)
        missing = sorted(t_assigned - g_assigned - _BUILTINS)
        extra = sorted(g_assigned - t_assigned - _BUILTINS)
        if missing:
            rep.add(FAIL, "S4", "模板里有、生成脚本里却没有的变量（渲染段会 NameError）："
                                + ", ".join(missing[:14]) + ("…" if len(missing) > 14 else "")
                                + "　→ 数据区是**整段替换**，模板数据区定义的变量必须自己重新定义（坑 42/44）")
        else:
            rep.add(OK, "S4", "生成脚本已覆盖模板的全部变量（数据区整段替换后无缺口）")
        if extra:
            rep.add(INFO, "S4", f"生成脚本多出的变量（{len(extra)} 个，通常是自己算的中间量；"
                                f"若有拼写错会同时出现在 missing 里）：{', '.join(extra[:12])}")
    else:
        if expect_date:
            g_date = _const("DATE", src)
            if g_date and g_date.replace("-", "") != expect_date.replace("-", ""):
                rep.add(FAIL, "S5", f"`DATE`={g_date} ≠ 期望 {expect_date}（坑 55）")
    return rep


# --------------------------------------------------------------------------- #
# 产物 HTML 检查
# --------------------------------------------------------------------------- #
def check_html(path: str, hist: str | None, expect_date: str | None,
               expect_points: int | None, allow_missing: int, old: list[str]) -> Report:
    html = open(path, encoding="utf-8", errors="replace").read()
    fname = os.path.basename(path)
    rep = Report(f"产物检查：{fname}")

    body = re.sub(r"<style.*?</style>|<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text)

    # H1 title 与文件名同口径（坑 55）
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = (m.group(1).strip() if m else "")
    stem = os.path.splitext(fname)[0]
    norm = lambda s: re.sub(r"[\s_\-·|/]+", "", s)  # noqa: E731
    if not title:
        rep.add(FAIL, "H1", "没有 <title>")
    else:
        dm = re.search(r"(\d{8})$", stem)
        core = stem[: dm.start()].rstrip("_-") if dm else stem
        core_norm, title_norm = norm(core), norm(title)
        cov = _coverage(core_norm, title_norm)
        if cov < 0.6:
            rep.add(WARN, "H1", f"title 疑似**缺主体名**：文件名芯=`{core}`，title=`{title}`"
                                f"（主体字符覆盖仅 {cov:.0%}）→ 应为 `{stem}` 的口径（坑 55）")
        elif dm and dm.group(1) not in title_norm and "速览卡" not in title:
            rep.add(WARN, "H1", f"title **缺日期**：文件名带 {dm.group(1)}，但 title=`{title}`（坑 55）"
                                f"；速览卡 title 用「名称 代码 · 速览卡」属既定风格，已豁免")
        else:
            rep.add(OK, "H1", f"title 与文件名同口径（{title}）")
    if expect_date:
        d8 = expect_date.replace("-", "")
        if d8 not in html and expect_date not in html:
            rep.add(WARN, "H1", f"产物里找不到期望日期 {expect_date}（DATE 可能未替换或数据未对齐，坑 55）")

    # H2 占位符残留
    # ⚠️ 两种都要查（2026-10-08 实测）：① 模板的 `__NAME__`；② **f-string 漏前缀**留下的 `{_VAR}`
    #    ——Python 的隐式字符串拼接里，`f` 只作用于**紧邻的那个字面量**：
    #    `f"a{x}" "b{y}"` → 只有 a 是 f-string，`{y}` 会**原样输出到页面**。
    ph = sorted(set(re.findall(r"__[A-Za-z][A-Za-z0-9_]{2,}__", html)))
    fph = sorted(set(re.findall(r"\{_[A-Za-z][A-Za-z0-9_]*[^}]{0,10}\}", html)))
    if ph or fph:
        det = []
        if ph:
            det.append(f"模板占位符 {', '.join(ph[:8])}{'…' if len(ph) > 8 else ''}")
        if fph:
            det.append(f"未替换的 f-string 占位符 {', '.join(fph[:6])}"
                       "（多半是隐式拼接时漏了 f 前缀 —— f 只作用于紧邻的那个字面量）")
        rep.add(FAIL, "H2", "占位符残留：" + "；".join(det))
    else:
        rep.add(OK, "H2", "无占位符残留（模板 __X__ 与 f-string {_X} 均为 0）")

    # H3 markdown 语法残留在 HTML 里（坑 46 家族）
    # ⚠️ 反引号是**同一类**问题（2026-10-08 实测：报告脚注里写了 `value_evidence.py`，
    #    页面原样显示成带反引号的字面量）→ 合并检查，避免只防星号、漏掉反引号。
    nstar = html.count("**")
    ntick = html.count("`")
    if nstar or ntick:
        det = []
        if nstar:
            det.append(f"`**` {nstar} 处")
        if ntick:
            det.append(f"反引号 `\\`` {ntick} 处")
        rep.add(FAIL, "H3", "残留 markdown 语法在 HTML 里（页面会原样显示符号）："
                            + "、".join(det) + " ——改用 <b>／纯文本")
    else:
        rep.add(OK, "H3", "无 markdown 语法残留（`**` 与反引号均为 0）")

    # H4 [MISSING]
    nmiss = len(re.findall(r"\[\s*MISSING\s*\]", text))
    if nmiss > allow_missing:
        rep.add(WARN, "H4", f"[MISSING] {nmiss} 处（上限 {allow_missing}）——确认每处都是真的取不到，"
                            f"而不是漏填")
    else:
        rep.add(OK, "H4", f"[MISSING] {nmiss} 处（≤{allow_missing}）")

    # H5 旧特征值残留
    for kw in old:
        if kw and kw in text:
            rep.add(FAIL, "H5", f"发现旧特征值残留：`{kw}`（换日期/换标的必须 grep 清理，坑 27②/13⑦/16⑦）")

    # H6 走势图点数（坑 61）
    mpts = re.search(r'<polyline points="([^"]+)" fill="none" stroke="#1f3a93" stroke-width="2"', html)
    if mpts:
        n = len(mpts.group(1).split())
        if expect_points and n != expect_points:
            rep.add(WARN, "H6", f"走势图 {n} 个点 ≠ 期望 {expect_points}（速览卡按 252 交易日窗口，坑 61）")
        else:
            rep.add(OK, "H6", f"走势图 {n} 个点")

    # H7 补丁工具留下「空壳」——用 `python -c "…"`（双引号）写含反引号的内容时，
    #    bash 会执行命令替换，把反引号里的文本静默吃掉，留下 `** **` / `（）` 这种空壳（2026-09-30 实测踩 2 次）
    voids = sorted({v for v in SHELL_VOIDS if v in text})
    if voids:
        rep.add(WARN, "H7", f"疑似补丁工具留下的空壳：{'、'.join('`'+v+'`' for v in voids)}"
                            f"——多半是写补丁时反引号被 shell 吃掉（改用 Edit 工具 / 单引号）")
    else:
        rep.add(OK, "H7", "无空壳痕迹")

    # H8 禁用行话（用户明确看不懂的词，报告里一律不出现）
    jargon = sorted({j for j in BANNED_JARGON if j in text})
    if jargon:
        rep.add(WARN, "H8", f"出现禁用行话：{'、'.join('「'+j+'」' for j in jargon)}"
                            f"——用户明确说看不懂，改用白话（黑名单见 BANNED_JARGON）")
    else:
        rep.add(OK, "H8", "无禁用行话")

    # L 布局 / P 计划价位（坑 65 的脚本化）
    check_layout(html, rep)
    check_table_fit(html, rep)
    check_topbox_wrap(html, rep)
    check_plan_levels(html, rep)

    # C1-C3 HIST 文件（坑 56 / 61）
    if hist:
        rep2 = check_hist(hist)
        rep.items.extend(rep2.items)
    return rep


def check_hist(path: str) -> Report:
    rep = Report(f"HIST 检查：{os.path.basename(path)}")
    try:
        env = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        rep.add(FAIL, "C0", f"读取失败：{e}")
        return rep
    bars = env["data"].get("item") if isinstance(env.get("data"), dict) else env.get("data")
    if not isinstance(bars, list) or not bars:
        rep.add(FAIL, "C0", "找不到 K 线数组（应走 data 或 data.item）")
        return rep
    keys = set().union(*[set(b.keys()) for b in bars[:50]])
    remote = {"date_ms", "close_price", "high_price", "low_price", "open_price", "volume"}
    if remote <= keys:
        datek, pricek = "date_ms", "close_price"
        rep.add(INFO, "C1", "远端/ETF 结构（data.item[] + *_price）")
    else:
        want = {"date", "open", "high", "low", "close", "volume"}
        extra = sorted(keys - want)
        if extra:
            rep.add(WARN, "C1", f"字段超出 6 个（多出 {extra}）→ 多余字段会进 JSON 甚至 SVG（坑 56①）")
        else:
            rep.add(OK, "C1", "字段恰为 6 个（date/open/high/low/close/volume）")
        datek, pricek = "date", "close"
    # C2 价格是否 round(2)（查全部价格字段，坑 56②）
    if remote <= keys:
        pkeys = ["open_price", "high_price", "low_price", "close_price"]
    else:
        pkeys = ["open", "high", "low", "close"]
    bad, tot = 0, 0
    for b in bars[:400]:
        for k in pkeys:
            v = b.get(k)
            if isinstance(v, float):
                tot += 1
                if len(str(v).split(".")[-1]) > 2:
                    bad += 1
    if bad:
        rep.add(WARN, "C2", f"{bad}/{tot} 个价格小数位 >2（未 round(x,2) → 撑大文本与坐标，坑 56②）")
    else:
        rep.add(OK, "C2", f"价格均已 round(x,2)（查了 {tot} 个值）")
    # C3 日期与根数
    ds = [str(b.get(datek)) for b in bars]
    if len(bars) < 252:
        rep.add(WARN, "C3", f"仅 {len(bars)} 根 < 252 → 速览卡会打 [WARN] 且「近1年涨幅」退化为区间值（坑 61）")
    else:
        rep.add(OK, "C3", f"{len(bars)} 根（≥252，够近一年窗口）")
    return rep


def check_codes(path: str) -> Report:
    rep = Report(f"参数清单 CRLF 检查：{os.path.basename(path)}")
    raw = open(path, "rb").read()
    n = raw.count(b"\r\n")
    if n:
        rep.add(FAIL, "K1", f"含 {n} 处 CRLF → 逐行喂 CLI 时每行会带尾 \\r，报 Invalid string"
                            f"（坑 28）。修复：`sed -i 's/\\r$//'` 或写文件时 newline='\\n'")
    else:
        rep.add(OK, "K1", "纯 LF，无尾 \\r")
    return rep


# --------------------------------------------------------------------------- #
# 自检：用故意写坏的样本证明每条检查确实有效
# --------------------------------------------------------------------------- #
_BAD_SCRIPT = '''# -*- coding: utf-8 -*-
DATE = "2026-09-17"
WEEKDAY = "周四"
CFG = {"name": "测试"}
DIVS = [(2024, 0.5)]

def render():
    return f"{CFG['name']} {DIVS} {BT_SCOPE}"

print(render())
'''

_BAD_SCRIPT_QUOTE = '''# -*- coding: utf-8 -*-
DATE = "2026-09-17"
NOTE = "他问"有没有增长"，而不是"为什么""


def render():
    return NOTE
'''

_BAD_BUILDER = '''# -*- coding: utf-8 -*-
import re
DATE = "2026-09-17"
TPL_PATH = r"C:\\\\nope\\\\gen_x.py"
src = open(TPL_PATH).read()
src = re.sub(r"^DATE = .*$", 'DATE = "2026-09-16"', src, count=1)
NOTE = "「, 」坏了"
'''


# ── 2026-09-18 追加：布局 / 计划价位 / 叙述常量 三类检查（坑 63-65 的脚本化）──

_GRID_RE = re.compile(r"grid-template-columns\s*:\s*repeat\(\s*(\d+)\s*,\s*1fr", re.I)


def check_table_fit(html: str, rep: Report) -> None:
    """L3：宽表装不进容器 → 页面两侧留大片空白、用户却还要拉横向进度条（2026-09-30 实测）。

    判据：`.wrap` 的**内容宽**（max-width − 左右 padding）必须 ≥ 最宽那张表的 `min-width`。
    宽度是「容器 max-width / 表 min-width / padding」三件套，只改一处必然出问题：
    能力 #13 加第 6 列后容器 960px、表 min-width 980px → 用户反馈「左右两面空白还很多，
    但执行总表那儿我需要拉进度条了」。
    """
    css_m = re.search(r"<style.*?</style>", html, re.S | re.I)
    if not css_m:
        return
    css = re.sub(r"/\*.*?\*/", "", css_m.group(0), flags=re.S)
    m = re.search(r"\.wrap\s*\{([^}]*)\}", css)
    if not m:
        return
    body = m.group(1)
    mw = re.search(r"max-width:\s*(\d+)px", body)
    if not mw:
        return
    inner = int(mw.group(1))
    pm = re.search(r"padding:\s*([^;}]+)", body)
    if pm:
        nums = [int(x[:-2]) for x in pm.group(1).split() if re.fullmatch(r"\d+px", x.strip())]
        if nums:
            horiz = nums[1] if len(nums) >= 2 else nums[0]
            inner -= 2 * horiz
    cands = []
    for t in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        sel = t.group(1).strip()
        if sel.startswith("@") or "table" not in sel:
            continue
        w = re.search(r"min-width:\s*(\d+)px", t.group(2))
        if w:
            cands.append((sel, int(w.group(1))))
    if not cands:
        return
    sel, need = max(cands, key=lambda x: x[1])
    if need > inner:
        rep.add(WARN, "L3", f"宽表装不进容器：内容宽 {inner}px < `{sel}` 的 min-width {need}px "
                            f"→ 用户必须拉横向进度条（宽度三件套：容器 max-width / 表 min-width / padding 要一起改）")
    else:
        rep.add(OK, "L3", f"表格可容纳（内容宽 {inner}px ≥ 最宽表 min-width {need}px，`{sel}`）")


def check_layout(html: str, rep: Report) -> None:
    """L：定列网格「填不满」→ 视觉上就是「左半边有内容、右半边空」。"""
    css_m = re.search(r"<style.*?</style>", html, re.S | re.I)
    css = css_m.group(0) if css_m else ""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)      # 剥掉注释
    grid: dict[str, int] = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        g = _GRID_RE.search(m.group(2))
        if g:
            # ⚠️ 只归给选择器的「主体」（最后一个复合选择器）：`.hero .kpis{...}` 的网格属于 .kpis，
            # 若把 .hero 也算上，就会去数 .hero 的子元素（title/sub/kpis=3）→ 误报（2026-09-18 实测踩到）
            subject = m.group(1).split(",")[-1].strip().split()[-1]
            for cls in re.findall(r"\.([\w-]+)", subject):
                grid.setdefault(cls, int(g.group(1)))
    body = html[html.find("<body"):]
    bad = []
    for cls, ncol in grid.items():
        for m in re.finditer(r'<div class="' + re.escape(cls) + r'"[^>]*>', body):
            i, depth, j = m.end(), 1, m.end()
            while depth and j < len(body):
                nxt = re.search(r"<div\b|</div>", body[j:])
                if not nxt:
                    break
                j += nxt.end()
                depth += 1 if nxt.group(0).startswith("<div") else -1
            inner, direct, d = body[i:j], 0, 0
            for mm in re.finditer(r"<div\b|</div>", inner):
                if mm.group(0).startswith("<div"):
                    if d == 0:
                        direct += 1
                    d += 1
                else:
                    d -= 1
            if direct and direct % ncol:
                bad.append(f".{cls}（{ncol} 列 / {direct} 项 → 末行空 {ncol - direct % ncol} 格）")
            break
    if bad:
        rep.add(WARN, "L1", "网格填不满（会显示成「右半边空」）：" + "；".join(bad)
                            + "　→ 改 flex + `flex:1` 让子项撑满，或把子项数调成列数整数倍")
    else:
        rep.add(OK, "L1", "定列网格均已填满（无「右半边空」）")


def check_topbox_wrap(html: str, rep: Report) -> None:
    """L2：顶部两栏盒子（`header` / `.hero`）若 `flex-wrap:wrap` 且子块不可收缩，
    文案一变长就会把右块整块挤到第二行 —— 视觉上就是「顶部右侧空着」（2026-09-18 实测）。"""
    css = (re.search(r"<style.*?</style>", html, re.S | re.I) or [""])[0]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)      # 剥掉注释，否则注释会被并进选择器名
    rules = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        rules[m.group(1).strip()] = m.group(2)
    bad = []
    # 已经用 @media 在窄屏把盒子改成纵向堆叠的（`.hero{flex-direction:column}`），
    # 换行风险由响应式接管，不算缺陷 —— 否则会误报（2026-09-18 实测：轮动报告被误报）
    handled = set()
    for m in re.finditer(r"@media[^{]*\{", css):
        i, depth, j = m.end(), 1, m.end()
        while depth and j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        blk = css[m.end():j]
        for r in re.finditer(r"([^{}]+)\{([^}]*)\}", blk):
            if "column" in r.group(2).replace(" ", ""):
                for box in (r.group(1).strip().split(",")[0].strip(),):
                    if box:
                        handled.add(box)

    for box in ("header", ".hero"):
        base = rules.get(box, "")
        if "flex-wrap:wrap" not in base.replace(" ", ""):
            continue
        if box in handled:
            continue
        kids = {k: v for k, v in rules.items() if k.startswith(box + " ") and "{" not in k}
        shrinkable = [k for k, v in kids.items()
                      if "min-width:0" in v.replace(" ", "") or "max-width:" in v.replace(" ", "")]
        if not shrinkable:
            bad.append(f"{box}（子块：{', '.join(list(kids)[:4]) or '无'}）")
    # 反向坑（2026-09-18 实测踩到）：给已被 @media 接管的盒子右块加 `max-width:NN%` 压窄，
    # 会把子元素（KPI 卡）压到内部换行/缩水，观感更差 —— 这种情况只要 `min-width:0` 就够。
    squeezed = []
    for box in ("header", ".hero"):
        if box not in handled:
            continue
        for k, v in rules.items():
            if k.startswith(box + " ") and "{" not in k and re.search(r"max-width\s*:\s*\d", v):
                squeezed.append(k.strip())
    if squeezed:
        rep.add(WARN, "L2", "顶部盒子已被 @media 接管，右块却又被 `max-width` 压窄 → 子元素会被压到内部换行"
                            "（KPI 卡缩水/掉行，比换行更难看）：" + "、".join(squeezed)
                            + "　→ 该盒子只需 `min-width:0`，不要加 `max-width`")
    if bad:
        rep.add(WARN, "L2", "顶部两栏盒子是 flex-wrap 且右块不可收缩 → 文案变长时右块会整块跳到第二行"
                            "（视觉=顶部右侧空）：" + "；".join(bad)
                            + "　→ 给右块加 `min-width:0`，让它内部换行而不是整块跳行")
    elif not squeezed:
        rep.add(OK, "L2", "顶部两栏盒子的右块可收缩、且未被 `max-width` 压窄（不会整块跳行 / 不会压扁）")


def check_plan_levels(html: str, rep: Report) -> None:
    """P：每张卡的「止损 < 入场区下限」必须成立（坑 65）。"""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    pairs = []
    for m in re.finditer(r"回踩\s*([\d.]+)\s*[~\-]\s*([\d.]+)[^。]{0,90}?跌破\s*([\d.]+)", txt):
        lo, hi, stop = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
        pairs.append((min(lo, hi), stop))
    if not pairs:
        return
    bad = [p for p in pairs if p[1] >= p[0]]
    if bad:
        # ⚠️ 提示语必须与判据**完全一致**（2026-10-04：旧提示写「应取 入场区下限 ×0.95」，
        #    比判据 `止损 < 入场区下限` 更严 → 我按提示理解反而写错，故改成陈述判据本身）
        rep.add(FAIL, "P1", "止损位 ≥ 入场区下限（一买入即触发止损，坑 65）："
                            + "；".join(f"入场下限 {lo} vs 止损 {st}" for lo, st in bad[:5])
                            + "　→ **止损必须低于入场区下限**；"
                              "建议按「支撑位下方」与「入场参考价 ×(1−止损幅度)」取较高者，"
                              "且任何情况下 <b>止损 &lt; 入场区下限</b>")
    else:
        rep.add(OK, "P1", f"计划价位一致（{len(pairs)} 张卡：止损均低于入场区下限）")


_NARR_PAT = [(re.compile(r"全市场\s*\d{4}\s*只"), "全市场只数"),
             (re.compile(r"\d{3,5}\s*家上涨"), "上涨家数"),
             (re.compile(r"\d{3,5}\s*家下跌"), "下跌家数"),
             (re.compile(r"涨停\s*\d{1,4}\s*家"), "涨停家数"),
             (re.compile(r"中位\s*[+-]?\d"), "中位涨幅")]


_ALLOC_FORWARD = {"A股红利低波": 8.0, "美股宽基（QDII）": 7.0, "国内债券": 3.0,
                  "黄金": 3.0, "现金 / 货币": 1.6}   # 前瞻假设（与报告口径一致）


def parse_alloc(src: str):
    """从脚本源码里解析 `ALLOC = [...]` → {资产: (稳健, 平衡, 进取)}（小数）。"""
    m = re.search(r"^ALLOC\s*=\s*\[(.*?)^\]", src, re.M | re.S)
    if not m:
        return {}
    out = {}
    for row in re.finditer(r'\(\s*"([^"]+)"\s*,\s*"[^"]*"\s*,\s*"(\d+)%"\s*,\s*"(\d+)%"\s*,\s*"(\d+)%"\s*,', m.group(1)):
        out[row.group(1)] = tuple(int(row.group(i)) for i in (2, 3, 4))
    return out


def check_alloc_consistency(src: str, rep: Report) -> None:
    """V1：配比（`ALLOC`）变更后，跟着它走的硬编码是否同步。

    为什么（2026-10-08）：配比虽是「单一数据源」，但报告里仍有多处**跟着平衡档走的硬编码**——
    `MAIN` 的「月结余 × N%」、`ALLOC_NOTE` 的风险资产占比、`BT2` 的前瞻中枢。
    实测改一次配比要同步 13 处，漏一处报告就自相矛盾，而当时**没有任何检查**。
    """
    alloc = parse_alloc(src)
    if not alloc:
        return
    problems: list[str] = []

    # ① 三列各自合计必须 = 100
    for idx, tier in ((0, "稳健"), (1, "平衡"), (2, "进取")):
        tot = sum(v[idx] for v in alloc.values())
        if tot != 100:
            problems.append(f"{tier}档合计 {tot}% ≠ 100%")

    # ② ALLOC_NOTE 的风险资产占比（红利 + 美股）必须与 ALLOC 一致
    risk = {"稳健": 0, "平衡": 0, "进取": 0}
    for i, t in ((0, "稳健"), (1, "平衡"), (2, "进取")):
        risk[t] = sum(v[i] for k, v in alloc.items() if k in ("A股红利低波", "美股宽基（QDII）"))
    note = re.search(r"风险资产占比[^：:]*[：:][^。]{0,80}", src)
    if note:
        for t, rx in (("稳健", r"稳健\s*(\d+)%"), ("平衡", r"平衡\s*(\d+)%"), ("进取", r"进取\s*(\d+)%")):
            got = re.search(rx, note.group(0))
            if got and int(got.group(1)) != risk[t]:
                problems.append(f"ALLOC_NOTE 里{t}档风险资产写了 {got.group(1)}%，"
                                f"按 ALLOC 应为 {risk[t]}%")

    # ③ 全文所有「月结余 × N%」与「按 N%」的 N 必须来自平衡列
    #    （2026-10-08 实测：漏改的第 14 处正是「按 36% 正常定投即可」——没有「月结余 ×」前缀，
    #      只查前一种写法会漏掉它）
    bal = {v[1] for v in alloc.values()}
    for mm in re.finditer(r"月结余\s*[×x]\s*(\d+)%", src):
        if int(mm.group(1)) not in bal:
            problems.append(f"「月结余 × {mm.group(1)}%」不在平衡列取值 {sorted(bal)} 中")
    for mm in re.finditer(r"按\s*(\d+)%\s*(?:正常定投|定投|配|买)", src):
        if int(mm.group(1)) not in bal:
            problems.append(f"「按 {mm.group(1)}% …定投」不在平衡列取值 {sorted(bal)} 中")

    # ④ 前瞻中枢必须 = 平衡列 × 前瞻假设 的加权和
    m = re.search(r'\("平衡（默认）"[^\n]*?"([+\-−][\d.]+)%"\s*\)', src)
    if m:
        want = sum(alloc[k][1] / 100 * _ALLOC_FORWARD[k] for k in alloc if k in _ALLOC_FORWARD)
        got = float(m.group(1).replace("−", "-").lstrip("+"))
        if abs(got - want) > 0.02:
            problems.append(f"BT2 平衡档前瞻中枢 {got:+.2f}%，按 ALLOC×假设应为 {want:+.2f}%")

    if problems:
        rep.add(FAIL, "V1", "配比变更未同步（改 ALLOC 后要一起改的地方）：" + "；".join(problems[:5])
                            + "　→ 见 `gen_value_investing.py` 中 `ALLOC` 上方的同步清单")
    else:
        n = len(alloc)
        rep.add(OK, "V1", f"配比一致（{n} 类资产：三列均合计 100%、"
                          f"风险资产占比 {risk['稳健']}%/{risk['平衡']}%/{risk['进取']}%、"
                          f"月结余系数与前瞻中枢均与 ALLOC 同步）")


def _pipeline_sourced(src: str, script_path: str | None) -> str | None:
    """数据区里的市场数字**是否可溯源到同日 pipeline 产物**（可则返回说明文本，否则 None）。

    为什么需要（2026-10-04）：N1 的判据是「数字次日即变旧值」，但**日更流程产出的数据区文件本来就是
    日期专属的**（`DATE = "YYYY-MM-DD"` + 数字取自 `daily_prep.py` 的交接清单），
    按原判据会在正常流程里持续误报，噪声会让人不再信任这条检查。
    → 改用**可溯源**判定：若脚本同日的 `lu_/ld_/lb_MMDD.json`（涨停/跌停/炸板池）存在，
    说明这些数字有 pipeline 出处，**不算"手抄"**；此时报 OK 并把命中项作为明细列出（不隐藏）。
    找不到同日产物时才退回原判据。
    """
    if not script_path:
        return None
    # ⚠️ 取**最后一个** DATE，不是第一个（2026-10-13 实测踩到）：
    #    `render_rotation_report.py` / `render_sentiment_report.py` 注入的是「数据区标记**之间**」那一段，
    #    而模板自己的示例 `DATE` 落在标记**之前**、不会被替换 → 生成脚本里出现**两个** DATE
    #    （前者 = 模板默认值、后者 = 真实日期，**后者才生效**）。
    #    取第一个会拿模板默认值去掉 `lu_MMDD.json`（如 0821，根本不存在）→ 豁免失效 → N1 天天误报。
    ms = re.findall(r'DATE\s*=\s*"(\d{4})-(\d{2})-(\d{2})"', src)
    if not ms:
        return None
    _y, _mo, _d = ms[-1]
    mmdd = _mo + _d
    root = os.path.dirname(os.path.dirname(os.path.abspath(script_path)))   # …/output/reco_MMDD/x.py → …/output
    found = []
    for tag, lab in (("lu", "涨停池"), ("ld", "跌停池"), ("lb", "炸板池")):
        f = os.path.join(root, f"{tag}_{mmdd}.json")
        if os.path.exists(f):
            try:
                items = ((json.load(open(f, encoding="utf-8")).get("data") or {}).get("item")) or []
                if items:
                    found.append(f"{lab} {len(items)} 家")
            except Exception:
                continue
    return (f"数据区 DATE={_y}-{_mo}-{_d} 的同日 pipeline 产物在场（{'、'.join(found)}）"
            if found else None)


def check_narration_constants(src: str, rep: Report, script_path: str | None = None) -> None:
    """N：脚本里「手抄的当日市场数字」——复制到次日即变旧值（坑 64）。

    ⚠️ 先做**可溯源判定**（见 `_pipeline_sourced`）：正常日更流程产出的数据区文件会被豁免，
    避免把「日期专属但来源正确」的文件误报成手抄。
    """
    hits = []
    for i, line in enumerate(src.splitlines(), 1):
        for rx, _lab in _NARR_PAT:
            for m in rx.finditer(line):
                pre = line[:m.start()]
                if pre.count("{") > pre.count("}"):      # 落在 f-string 的 {} 里 = 由数据算
                    continue
                hits.append((i, m.group(0)))
    if not hits:
        rep.add(OK, "N1", "未发现手抄的当日市场数字")
        return
    src_note = _pipeline_sourced(src, script_path)
    if src_note:
        rep.add(OK, "N1", f"市场数字共 {len(hits)} 处，**已可溯源、不算手抄**：{src_note}"
                          f"（明细：{'；'.join(f'行{i}「{v}」' for i, v in hits[:6])}）")
        return
    rep.add(WARN, "N1", f"疑似**手抄的当日市场数字** {len(hits)} 处（次日即变旧值，坑 64）："
                        + "；".join(f"行{i}「{v}」" for i, v in hits[:6])
                        + "　→ 改由脚本算（本地库 market_breadth / 涨停池统计 / fund snapshot）"
                          "；若该文件本就是**日期专属**的数据区，请确认同日 `lu_/ld_/lb_MMDD.json` 在场")


def selftest() -> int:
    tmp = tempfile.mkdtemp(prefix="checkbuild_selftest_")
    fails = []
    print("=" * 72)
    print("自检：故意写坏的样本，检查器必须逐条报出来")
    print("=" * 72)

    def expect(name: str, rep: Report, tag: str, want: str):
        got = [lv for lv, tg, _ in rep.items if tg == tag]
        ok = want in got
        print(f"  {'✅' if ok else '❌'} {name}: 期望 {tag}={want}，实际 {tag}={got}")
        if not ok:
            fails.append(name)

    p1 = os.path.join(tmp, "gen_bad.py")
    open(p1, "w", encoding="utf-8").write(_BAD_SCRIPT)
    expect("未绑定名(BT_SCOPE)", check_script(p1, None, None), "S2", FAIL)

    p2 = os.path.join(tmp, "gen_bad_quote.py")
    open(p2, "w", encoding="utf-8").write(_BAD_SCRIPT_QUOTE)
    expect("裸引号 SyntaxError", check_script(p2, None, None), "S1", FAIL)

    p3 = os.path.join(tmp, "build_bad.py")
    open(p3, "w", encoding="utf-8").write(_BAD_BUILDER)
    r3 = check_builder(p3)
    expect("re.sub 非 lambda", r3, "B1", WARN)
    expect("残留旧日期", r3, "B2", WARN)
    expect("TPL_PATH 不存在", r3, "B3", FAIL)
    expect("引号批量替换坏掉", r3, "B4", FAIL)

    p4 = os.path.join(tmp, "codes.txt")
    open(p4, "wb").write(b"881101.TI\r\n881102.TI\r\n")
    expect("CRLF", check_codes(p4), "K1", FAIL)

    p5 = os.path.join(tmp, "hist.json")
    json.dump({"data": [{"date": "2026-09-01", "open": 1.234567, "high": 2.0,
                         "low": 1.0, "close": 1.5, "volume": 100, "ticker": "x"}]},
              open(p5, "w", encoding="utf-8"))
    r5 = check_hist(p5)
    expect("HIST 多余字段", r5, "C1", WARN)
    expect("HIST 未 round", r5, "C2", WARN)

    # H7 空壳痕迹 / H8 禁用行话 / L3 宽表装不进容器
    _SHELL = ('<html><head><title>样本 20260930</title><style>'
              '.wrap{max-width:960px;margin:0 auto;padding:24px 20px}'
              '.scroll table{min-width:1260px}</style></head><body>'
              '<div class="wrap"><p>改宽度时**必须同步复核 **（见 ）</p>'
              '<p>美股这一腿买不到足额（本文档会因此被判禁用行话）</p>'
              '<div class="card scroll"><table><tr><td>x</td></tr></table></div>'
              '</div></body></html>')
    p6 = os.path.join(tmp, "shell_bad.html")
    open(p6, "w", encoding="utf-8").write(_SHELL)
    r6 = check_html(p6, None, None, None, 0, [])   # (path, hist, expect_date, expect_points, allow_missing, old)
    expect("补丁空壳痕迹", r6, "H7", WARN)
    expect("禁用行话「腿」", r6, "H8", WARN)
    expect("宽表装不进容器", r6, "L3", WARN)
    # 正例：同一份 HTML 修好三处后必须全部通过
    _FIXED = (_SHELL.replace("**必须同步复核 **（见 ）", "必须同步复核 min-width")
                    .replace("美股这一腿买不到足额", "美股这一类买不到足额")
                    .replace("max-width:960px", "max-width:1360px")
                    .replace("min-width:1260px", "min-width:1200px"))
    p7 = os.path.join(tmp, "shell_ok.html")
    open(p7, "w", encoding="utf-8").write(_FIXED)
    r7 = check_html(p7, None, None, None, 0, [])
    for tg, name in (("H7", "空壳"), ("H8", "行话"), ("L3", "宽度")):
        expect(f"修好后 {name} 通过", r7, tg, OK)

    # H2 家族：f-string 漏前缀留下的 {_VAR} 必须被检出（2026-10-08 实测踩到）
    p_f = os.path.join(tmp, "fprefix_bad.html")
    open(p_f, "w", encoding="utf-8").write(
        '<html><head><title>样本 20260930</title></head><body>'
        '<div class="wrap" style="max-width:960px"><p>目标 {_DCA_MON:,.0f} 元/月</p>'
        '</div></body></html>')
    expect("H2 f-string 漏前缀 → FAIL", check_html(p_f, None, None, None, 0, []), "H2", FAIL)
    p_css = os.path.join(tmp, "css_ok.html")
    open(p_css, "w", encoding="utf-8").write(
        '<html><head><title>样本 20260930</title><style>.t{min-width:1260px}</style></head><body>'
        '<div class="wrap" style="max-width:960px"><p>正常文本</p></div></body></html>')
    expect("H2 CSS 花括号不误报 → OK", check_html(p_css, None, None, None, 0, []), "H2", OK)

    # H3 家族：markdown 语法漏进 HTML 必须被检出（`**` 与反引号同族）
    p_tick = os.path.join(tmp, "tick_bad.html")
    open(p_tick, "w", encoding="utf-8").write(
        '<html><head><title>样本 20260930</title></head><body>'
        '<div class="wrap" style="max-width:960px"><p>口径见 `value_evidence.py` 的说明</p>'
        '</div></body></html>')
    expect("H3 反引号残留 → FAIL", check_html(p_tick, None, None, None, 0, []), "H3", FAIL)
    p_clean = os.path.join(tmp, "tick_ok.html")
    open(p_clean, "w", encoding="utf-8").write(
        '<html><head><title>样本 20260930</title></head><body>'
        '<div class="wrap" style="max-width:960px"><p>口径见 <b>value_evidence.py</b> 的说明</p>'
        '</div></body></html>')
    expect("H3 干净样本 → OK", check_html(p_clean, None, None, None, 0, []), "H3", OK)

    # N1 溯源判定：有同日 pipeline 产物 → OK（豁免）；没有 → 仍 WARN
    _NARR = ('DATE = "2026-01-02"\nGEN = "x"\n'
             'BANNER = ("全市场 5558 只，2557 家上涨 / 2831 家下跌，涨停 56 家，中位 -0.10%")\n')
    d_ok = os.path.join(tmp, "out", "reco_0102"); os.makedirs(d_ok, exist_ok=True)
    # ⚠️ 产物必须放在 reco_MMDD 的**上一级**（真实布局：`<output>/lu_MMDD.json` 与 `reco_MMDD/` 平级）
    for tag, n in (("lu", 56), ("ld", 11), ("lb", 12)):
        json.dump({"data": {"item": [{}] * n}},
                  open(os.path.join(tmp, "out", f"{tag}_0102.json"), "w", encoding="utf-8"))
    p_ok = os.path.join(d_ok, "gen_reco_0102.py")
    open(p_ok, "w", encoding="utf-8").write(_NARR)
    expect("N1 有同日产物 → 豁免", check_script(p_ok, None, None), "N1", OK)
    p_no = os.path.join(tmp, "bare_0102.py")
    open(p_no, "w", encoding="utf-8").write(_NARR)
    expect("N1 无同日产物 → 仍告警", check_script(p_no, None, None), "N1", WARN)

    # —— DATE 取值位置（2026-10-13 实测误报修复）——
    # 注入式脚本里会有**两个** DATE：模板示例（在前、不生效）+ 注入的真实日期（在后、生效）。
    # 曾经取第一个 → S5 误报「与模板默认值相同」、N1 拿模板日期去找 lu_MMDD.json（不存在）→ 双重误报。
    _TPL2 = 'DATE = "2026-08-21"\nBASE = "."\nBANNER = "x"\n'
    p_tpl2 = os.path.join(tmp, "tpl_dual.py")
    open(p_tpl2, "w", encoding="utf-8").write(_TPL2)
    _DUAL = ('DATE = "2026-08-21"\nBASE = "."\n'            # ← 模板残留（不生效）
             '# ================= 数据 =================\n'
             'DATE = "2026-10-13"\n'                        # ← 注入（生效）
             'BANNER = ("全市场 5558 只，2905 家上涨 / 2487 家下跌，涨停 70 家，中位 +0.16%")\n')
    d_dual = os.path.join(tmp, "out2", "reco_1013")
    os.makedirs(d_dual, exist_ok=True)
    for tag, n in (("lu", 70), ("ld", 9), ("lb", 19)):
        json.dump({"data": {"item": [{}] * n}},
                  open(os.path.join(tmp, "out2", f"{tag}_1013.json"), "w", encoding="utf-8"))
    p_dual = os.path.join(d_dual, "gen_rotation_1013.py")
    open(p_dual, "w", encoding="utf-8").write(_DUAL)
    r_dual = check_script(p_dual, p_tpl2, "2026-10-13")
    expect("S5 双 DATE 取生效值 → 不误报", r_dual, "S5", OK)
    expect("N1 双 DATE 用生效日期溯源 → 豁免", r_dual, "N1", OK)
    # 守门：生效 DATE 真的还是模板默认值 → S5 必须仍然告警（别把检查改坏）
    _SAME = _DUAL.replace('DATE = "2026-10-13"', 'DATE = "2026-08-21"')
    p_same = os.path.join(d_dual, "gen_same_1013.py")
    open(p_same, "w", encoding="utf-8").write(_SAME)
    expect("S5 生效 DATE 仍为模板默认值 → 告警", check_script(p_same, p_tpl2, None), "S5", WARN)

    # V1 配比一致性：真实模板应 OK；把「月结余 × N%」改成不在平衡列的值必须报 FAIL
    _vi = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_value_investing.py")
    if os.path.exists(_vi):
        _src = open(_vi, encoding="utf-8").read()
        expect("V1 真实配比一致", check_script(_vi, None, None), "V1", OK)
        _bad = _src.replace("月结余 × 33%", "月结余 × 99%", 1)
        if _bad != _src:
            _p = os.path.join(tmp, "gen_value_investing_bad.py")
            open(_p, "w", encoding="utf-8").write(_bad)
            expect("V1 系数与 ALLOC 不符 → FAIL", check_script(_p, None, None), "V1", FAIL)

    print(f"\n  自检结果：{'全部通过 ✅' if not fails else '失败项 ' + str(fails)}")
    return 0 if not fails else 1


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="构建自检器（把坑变成可执行校验）")
    ap.add_argument("--builder", help="构建器脚本 build_*.py")
    ap.add_argument("--script", help="生成的数据版脚本 gen_*_MMDD.py")
    ap.add_argument("--template", help="对应的 skill 模板（用于变量集合比对）")
    ap.add_argument("--html", help="产出的 HTML")
    ap.add_argument("--hist", help="HIST JSON（校验字段/精度/根数）")
    ap.add_argument("--codes", help="喂 CLI 的参数清单文本（CRLF 检查）")
    ap.add_argument("--auto", nargs="*", help="按扩展名自动分派")
    ap.add_argument("--expect-date", help="期望日期 YYYY-MM-DD（校验 DATE 与产物）")
    ap.add_argument("--expect-points", type=int, help="走势图期望点数（速览卡=252）")
    ap.add_argument("--allow-missing", type=int, default=0, help="[MISSING] 允许上限，超出才 ⚠️")
    ap.add_argument("--old", default="", help="旧特征值关键词，逗号分隔（残留即 ❌）")
    ap.add_argument("--selftest", action="store_true", help="用故意写坏的样本自检")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    reps: list[Report] = []
    old = [s.strip() for s in a.old.split(",") if s.strip()]
    if a.builder:
        reps.append(check_builder(a.builder))
    if a.script:
        reps.append(check_script(a.script, a.template, a.expect_date))
    if a.html:
        reps.append(check_html(a.html, a.hist, a.expect_date, a.expect_points, a.allow_missing, old))
    elif a.hist:
        reps.append(check_hist(a.hist))
    if a.codes:
        reps.append(check_codes(a.codes))
    for p in (a.auto or []):
        ext = os.path.splitext(p)[1].lower()
        if ext == ".py":
            reps.append(check_builder(p) if os.path.basename(p).startswith("build_")
                        else check_script(p, a.template, a.expect_date))
        elif ext in (".html", ".htm"):
            reps.append(check_html(p, a.hist, a.expect_date, a.expect_points, a.allow_missing, old))
        elif ext == ".json":
            reps.append(check_hist(p))
        elif ext in (".txt", ".csv"):
            reps.append(check_codes(p))
    if not reps:
        ap.print_help()
        return 0

    worst = 0
    for r in reps:
        worst = max(worst, r.dump())
    print(f"\n{'✅ 全部通过' if worst == 0 else ('❌ 存在必须修的问题' if worst == 1 else '⚠️ 仅告警')}"
          f"　（退出码 {worst}）")
    return worst


if __name__ == "__main__":
    sys.exit(main())
