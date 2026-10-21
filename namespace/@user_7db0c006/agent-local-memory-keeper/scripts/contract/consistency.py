# -*- coding: utf-8 -*-
"""契约层：跨系统矛盾只读扫描（scan_contradictions）。

设计目标（稳固优先，务实不 over-engineering）：
- 跨 L2/L3（WorkBuddy 原生记忆）与 L4（keeper）的"语义矛盾"难做全量引擎（误报多、投入大）。
本模块只做**低误报、可解释**的显式矛盾检测：同一语义轴上出现相反极性陈述即报冲突。
- 只读：输入是已抽取的结构化事实（dict: {id, statement, layer}），不主动读 L2/L3 原生库；
跨系统真实抽取由调用方（doctor / 手动导出）负责，本模块只比对。
- 冲突**只报告不自动改**（符合"永不直接互写"硬约束）。
- 纯逻辑、可单测；CLI（`python -m contract.consistency --l2 f --l4 f`）便于手动巡检。

极性判定：含否定词（不/勿/禁止/不要/避免/不可/never/no）为负面，否则正面。
轴：去否定词后的词表（复用 contract.tokenize 单一真源）；同轴的相反极性 = 矛盾候选。
"""
import sys
import os
import json
import argparse

from contract import tokenize

NEG_MARKERS = ("不", "勿", "禁", "不要", "避免", "不可", "不能", "never", "no", "not")


def _polarity(statement):
    s = (statement or "").lower()
    for m in NEG_MARKERS:
        if m in s:
            return -1
    return 1


def _axis(statement):
    # 先去除否定词再 tokenize：避免"不要X"在 2-gram 边界生成"要X"污染语义轴，
    # 使"不要X"与"X"被正确判为同一轴（再说极性相反 → 矛盾候选）。
    # 必须按长度降序删（先"不要"后"不"），否则先删单字"不"会把"不要"拆成"要X"残留。
    s = statement or ""
    for m in sorted(NEG_MARKERS, key=len, reverse=True):
        s = s.replace(m, "")
    return frozenset(tokenize(s))


def scan_contradictions(facts):
    """facts: list[{id, statement, layer}]。返回冲突列表：
    [{axis_tokens, a:{id,layer,statement}, b:{...}, reason}]。只读、可解释。"""
    by_axis = {}
    for f in facts or []:
        ax = _axis(f.get("statement") or "")
        if not ax:
            continue
        by_axis.setdefault(ax, []).append(f)

    conflicts = []
    for ax, group in by_axis.items():
        if len(group) < 2:
            continue
        pols = {f.get("id"): _polarity(f.get("statement")) for f in group}
        positives = [f for f in group if pols[f.get("id")] > 0]
        negatives = [f for f in group if pols[f.get("id")] < 0]
        if positives and negatives:
            for a in positives:
                for b in negatives:
                    conflicts.append({
                        "axis_tokens": sorted(ax),
                        "a": {"id": a.get("id"), "layer": a.get("layer"),
                              "statement": a.get("statement")},
                        "b": {"id": b.get("id"), "layer": b.get("layer"),
                              "statement": b.get("statement")},
                        "reason": "同一语义轴上相反极性陈述（矛盾候选）",
                    })
    return conflicts


def main(argv=None):
    ap = argparse.ArgumentParser(description="跨系统矛盾只读扫描（JSON 输入）")
    ap.add_argument("--l2", help="L2/L3 事实 JSON 文件（数组）")
    ap.add_argument("--l4", help="L4 事实 JSON 文件（数组）")
    ap.add_argument("--stdin", action="store_true", help="从 stdin 读 JSON {l2:[],l4:[]}")
    args = ap.parse_args(argv)

    facts = []
    if args.stdin:
        d = json.load(sys.stdin)
        facts = (d.get("l2") or []) + (d.get("l4") or [])
    else:
        for path in (args.l2, args.l4):
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    facts.extend(json.load(f))
    conflicts = scan_contradictions(facts)
    out = {"scanned": len(facts), "conflicts": len(conflicts), "items": conflicts}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not conflicts else 2  # 有冲突以退出码 2 提示（不阻断，供 doctor 调用判读）


if __name__ == "__main__":
    sys.exit(main())
