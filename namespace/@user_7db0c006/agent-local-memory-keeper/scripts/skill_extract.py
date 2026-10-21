# -*- coding: utf-8 -*-
"""
skill_extract.py — 自动技能萃取脚手架

核心思想：高频（recurrence≥阈值）或已确认（state=confirmed）的经验，聚合成一个
「经验模式库」skill 脚手架（SKILL.md + references/ 详细模式 + hooks/ 占位 + README），
让 AI 以后遇到类似场景可加载，或用 skill-creator 进一步打磨为正式 skill。

设计：纯加性可选能力；复用 promote_rules.select_entries 取高频/已确认条目。
规则聚合（无 LLM 依赖，绝不阻塞主链路）；--llm 仅占位（提示用 skill-creator refine）。
已接入 memory_ops CLI 为 `extract-skill` op（见 _cli.py）。
"""

import os
import sys
import json
import argparse

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))


def _frontmatter_name(sel):
    """从选中条目推断一个稳定的脚手架 skill 名（取最常见 area）。"""
    from collections import Counter
    areas = [e.get("area", "learning") for e in sel]
    top = Counter(areas).most_common(1)
    return "extracted-%s-patterns" % (top[0][0] if top else "learning")


def extract(root, min_count=3, out_dir="auto_skill", llm=False,
            area=None, state=None, priority=None, filter_str=None):
    import promote_rules as PR
    from _self_heal import selection_signature, register_skill
    sel = PR.select_entries(root, min_count=min_count, area=area, state=state,
                            priority=priority, filter_str=filter_str)  # 高频/已确认
    if not sel:
        return {"ok": True, "count": 0, "note": "无高频/已确认经验可萃取"}
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "references"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "hooks"), exist_ok=True)

    groups = {}
    for e in sel:
        groups.setdefault(e.get("area", "learning"), []).append(e)

        # 围栏内模式清单（与 _self_heal._render_pattern_block 同格式，保证重生成一致）
    block_lines = ["## 模式清单（自动维护区 · 由 extract-skill 生成，勿手改本块）", ""]
    for area, items in groups.items():
        block_lines.append("## %s\n" % area)
        for e in items:
            block_lines.append(
                "- **%s**（recurrence=%d, priority=%s, id=%s）：%s"
                % (e.get("summary", ""), e.get("recurrence_count", 1),
                   e.get("priority", "normal"), e.get("id", ""),
                   (e.get("body") or e.get("summary") or "")[:80]))
        block_lines.append("")
    block = "\n".join(block_lines)
    fenced_block = "%s\n%s\n%s" % (
        "<!-- keeper-auto-begin (自动维护，勿手改) -->",
        block.strip("\n"),
        "<!-- keeper-auto-end -->")

    # 1) SKILL.md（frontmatter + 人类可编辑前言 + 围栏内自动维护区）
    skill_lines = [
        "---",
        "name: %s" % _frontmatter_name(sel),
        "description: 从 agent-local-memory-keeper 高频(recurrence≥%d)/已确认记忆自动萃取的模式库"
        "（extract-skill 生成）。覆盖领域：%s。可用 skill-creator 进一步打磨为正式 skill。"
        % (min_count, "、".join(groups.keys())),
        "---",
        "# 自动萃取经验模式库",
        "",
        "> 由 agent-local-memory-keeper `extract-skill` 从高频/已确认记忆自动生成。",
        "这是**脚手架**，请用 skill-creator 加载本目录进一步 refine 成正式 skill。",
        "",
        "## 何时用",
        "当遇到与以下模式相关的任务时，参考对应经验（每条均标注来源记忆 id，便于回溯源库）。",
        "",
        fenced_block,
        "",
    ]
    skill_md = "\n".join(skill_lines)
    skill_path = os.path.join(out_dir, "SKILL.md")
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md)

        # 2) references/patterns.md（每条记忆的完整细节，供 refine 时深挖；纯机器产物，可整体重写）
    pat_lines = ["# 萃取模式明细（references/patterns.md）", "",
                 "> 由 extract-skill 自动生成；每条来自 keeper 记忆库，id 可回溯源库。\n"]
    for area, items in groups.items():
        pat_lines.append("## %s\n" % area)
        for e in items:
            pat_lines.append("- **%s** (`id=%s`, recurrence=%d, priority=%s, type=%s)"
                              % (e.get("summary", ""), e.get("id", ""),
                                 e.get("recurrence_count", 1), e.get("priority", "normal"),
                                 e.get("type", "")))
            if e.get("tags"):
                pat_lines.append("  - 标签：%s" % ", ".join(e.get("tags")))
            if e.get("body"):
                pat_lines.append("  - 正文：%s" % e.get("body"))
            pat_lines.append("")
    pat_path = os.path.join(out_dir, "references", "patterns.md")
    with open(pat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(pat_lines))

        # 3) hooks/README.md（钩子占位模板，提示在何处加自动化触发）
    hook_path = os.path.join(out_dir, "hooks", "README.md")
    with open(hook_path, "w", encoding="utf-8") as f:
        f.write(
            "# hooks（占位）\n\n"
            "在此放置本 skill 的钩子（如会话结束自动套用这些模式）。\n"
            "参考 agent-local-memory-keeper 的 `hooks/` 目录结构：\n"
            "- `session_start_keeper_inject.py`：会话开始注入相关记忆\n"
            "- `user_prompt_recall.py`：用户提问时召回\n"
            "- `memory_auto_capture.py`：对话中自动捕获新经验\n"
            "用 skill-creator refine 时，按本 skill 的实际触发时机补具体钩子。\n")

        # 4) README.md（如何 refine 成正式 skill）
    readme_path = os.path.join(out_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(
            "# 自动萃取 Skill 脚手架\n\n"
            "本目录由 `agent-local-memory-keeper` 的 `extract-skill` 从你的高频/已确认记忆生成。\n\n"
            "## 包含的产物\n"
            "- `SKILL.md`：模式清单（围栏内为自动维护区，self-heal 会随记忆变动同步更新）\n"
            "- `references/patterns.md`：每条记忆的完整细节\n"
            "- `hooks/README.md`：钩子占位模板\n"
            "- `_extract_manifest.json`：筛选条件 + 源记忆清单 + 选择签名（self-heal 重生成依据）\n\n"
            "## 下一步：打磨成正式 skill\n"
            "用 skill-creator 加载本目录，补充触发词、示例与钩子，即可发布为可复用 skill。\n"
            "（本脚手架未调用 LLM，避免阻塞；精炼可由 skill-creator 的 LLM 能力完成。）\n")

        # 5) _extract_manifest.json（self-heal 重生成的依据：筛选条件 + 源 id + 签名）
    manifest = {
        "version": 1,
        "filter": {
            "min_count": min_count, "area": area, "state": state,
            "priority": priority, "filter_str": filter_str,
        },
        "source_ids": [e.get("id") for e in sel],
        "signature": selection_signature(sel),
        "needs_review": False,
        "review_notes": [],
        "skill_name": _frontmatter_name(sel),
        "created_at": _now_iso(),
        "last_synced_at": _now_iso(),
    }
    manifest_path = os.path.join(out_dir, "_extract_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        # 登记进 skill 注册表（self-heal 据此发现并同步本 skill）
    register_skill(root, manifest_path)

    files = [skill_path, pat_path, hook_path, readme_path, manifest_path]
    note = ("（规则聚合，无 LLM 依赖；self-heal 会随记忆变动自动同步围栏内模式清单）"
            ) if not llm else "（LLM 增强占位，精炼仍建议走 skill-creator）"
    return {"ok": True, "count": len(sel), "out_dir": out_dir,
            "skill_md": skill_path, "files": files, "manifest": manifest_path, "note": note}


def _now_iso():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def main():
    ap = argparse.ArgumentParser(description="自动技能萃取脚手架（extract-skill）")
    ap.add_argument("--root", default=None)
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--out-dir", default="auto_skill")
    ap.add_argument("--llm", action="store_true",
                    help="可选 LLM 增强（占位，默认规则聚合；精炼建议走 skill-creator）")
    args = ap.parse_args()
    import memory_ops as M
    root = args.root or M.DEFAULT_ROOT
    print(json.dumps(extract(root, args.min_count, args.out_dir, args.llm),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
