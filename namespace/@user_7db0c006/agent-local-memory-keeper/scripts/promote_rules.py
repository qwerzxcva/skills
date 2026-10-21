# -*- coding: utf-8 -*-
"""
promote_rules.py — 行为规则层

核心思想：记忆的终点不只是「被 recall 命中」，更可以是「让 AI 下次不犯同样的错」。
高频（recurrence≥阈值）或已确认（state=confirmed）的经验，固化成 AGENTS.md/CLAUDE.md
的自动生成区块，成为 AI 每轮的行为规则。

设计：
- SQLite 是系统真源；规则文件是导出物（带自动生成头，可逆）。
- 每次 export-rules 整体覆盖自动区块，写前自动备份 `.bak.<时间戳>`。
- import-rules 把规则文件自动区块逆向回灌 SQLite（仅 id 不存在的新条目才 deposit）。
- 纯加性，不碰记忆原文；出错可回滚备份。

4.7.11 增项：
- 新增 --rules-target text（配 --out <路径>）：完全自定义写入位置、文件名为中性
「# Agent Instructions」标题，避免被 Copilot/Claude 平台自动加载（合规/隐私/隔离用）。
"""

import os
import re
import json
import shutil
import datetime

AUTO_START = "<!-- memory-keeper auto-rules start -->"
AUTO_END = "<!-- memory-keeper auto-rules end -->"
GEN_HEADER = ("> 以下区块由 agent-local-memory-keeper 自动生成，请勿手改；"
              "重新运行 export-rules 会整体覆盖。\n")


def _now():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _active_entries(root):
    """返回 root 下全部 `status==active` 的记忆（权威源 = 记忆 JSON 文件）。

    4.7.12 修复：原先走 `load_index`（SQLite 派生镜像的 `data` 列），该列在落盘时被
    `_index_entry_from_mem` 等裁剪，缺失 `recurrence_count` / `pattern_key` 等 D3/进化字段，
    导致 `select_entries`/`hot_rules` 的「recurrence≥阈值」分支永远命中不了高频经验——
    extract-skill、skill_sync、export-rules 的 recurrence 路径在线上实为死路（仅 state=confirmed
    可用）。改为与 `evolve` 一致的权威源 `_all_mems`（直接读记忆 JSON 文件），保证
    recurrence_count/pattern_key 等字段完整可用；仅在 `_all_mems` 异常时回退 `load_index`。
    """
    import memory_ops as M
    try:
        mems = M._all_mems(root)
        return [e for e in mems.values()
                if isinstance(e, dict) and e.get("status") == "active"]
    except Exception:
        data = M.load_index(root)
        return [e for e in data.get("entries", [])
                if isinstance(e, dict) and e.get("status") == "active"]


def _target_path(target, out_path=None):
    """行为规则固化目标路径。
    - project：当前目录 ./AGENTS.md（可提交 git，WB 生态内共享）
    - user：~/.workbuddy/AGENTS.md（全局生效）
    - copilot：当前目录 ./.github/copilot-instructions.md
    （Microsoft/GitHub 官方 Copilot 指令自动加载位置，不是我们创造的）
    - claude：当前目录 ./CLAUDE.md
    （Anthropic 官方 Claude Code 约定，自动加载）
    - text（4.7.11）：完全自定义路径，由 --out <绝对或相对路径> 指定，
    头部用中性标题「# Agent Instructions」而非任何平台名。
    用途：合规要求不能写进 .github/ 的项目 / 不想自动被 Copilot 加载 /
    自有规则引擎（自有 harness / Cursor / Continue.dev 等） / 调试 / 测试隔离。
    后两者（copilot/claude）的路径绑定是平台标准——
    Copilot/Claude 只在固定路径才会自动加载规则文件，这是这两家定义的。"""
    if target == "user":
        return os.path.join(os.path.expanduser("~"), ".workbuddy", "AGENTS.md")
    if target == "copilot":
        return os.path.join(os.getcwd(), ".github", "copilot-instructions.md")
    if target == "claude":
        return os.path.join(os.getcwd(), "CLAUDE.md")
    if target == "text":
        if not out_path:
            raise ValueError("--rules-target text 需要 --out <路径>")
        return out_path
        # project（默认）
    return os.path.join(os.getcwd(), "AGENTS.md")


def select_entries(root, area=None, state=None, priority=None,
                   filter_str=None, min_count=3):
    """从 index 选符合标准的 active 条目。复用 memory_ops.parse_filter/eval_filter。"""
    import memory_ops as M
    entries = _active_entries(root)
    if state or area or priority or filter_str:
        def ok(e):
            if state and e.get("state") != state:
                return False
            if area and e.get("area") != area:
                return False
            if priority and e.get("priority") != priority:
                return False
            return True
        sel = [e for e in entries if ok(e)]
        if filter_str:
            try:
                clauses = M.parse_filter(filter_str)
            except ValueError:
                raise
            # 5.0/A1 续修：`--filter` 的**记忆级数值字段**（`access_count`/`access`）
            # 不在 index entry 上（真库 entry 实测无该键）⇒ 直接在 entry 上判会**恒不匹配、
            # 静默漏选**（「被召回 N 次以上才晋升」这类规则会永远选不出东西）。
            # 与 `_api.py` recall 路径同一口径：按需从**权威热源** recall_counts.json 补值。
            _hotf = {c.get("field") for c in clauses
                     if isinstance(c, dict) and c.get("kind") == "num"} \
                    & {"access_count", "access"}
            if _hotf:
                _cnt = M._load_recall_counts(root)
                for e in sel:
                    _v = M._access_count_of(root, e.get("id"), counts=_cnt)
                    e["access_count"] = _v
                    e["access"] = _v
            sel = [e for e in sel if M.eval_filter(e, clauses)]
    else:
        sel = [e for e in entries
               if e.get("state") == "confirmed"
               or (e.get("recurrence_count") or 1) >= min_count]
    _prio_w = {"critical": 4, "high": 3, "normal": 2, "low": 1}
    sel.sort(key=lambda e: ((e.get("recurrence_count") or 1),
                             _prio_w.get(e.get("priority"), 2)), reverse=True)
    return sel


def render_rules(sel):
    lines = [AUTO_START, GEN_HEADER]
    if not sel:
        lines.append("(暂无符合条件的已确认/高频经验)\n")
    for e in sel:
        area = e.get("area", "learning")
        prio = e.get("priority", "normal")
        summ = (e.get("summary") or "").replace("\n", " ")
        mid = e.get("id", "")
        rc = e.get("recurrence_count", 1)
        lines.append("- **[%s·%s]** %s  _(id: %s, recurrence: %d)_"
                      % (area, prio, summ, mid, rc))
    lines.append(AUTO_END)
    return "\n".join(lines) + "\n"


def _header_for(path):
    """新建规则文件时的首行标题。
    - AGENTS.md → '# AGENTS.md'（保持 v4.0.0 既有行为）
    - copilot-instructions.md → '# GitHub Copilot Instructions'（平台约定）
    - CLAUDE.md → '# Claude'（平台约定）
    - 其它（含 text 目标任意路径）→ '# Agent Instructions'
    text 目标刻意不用任何平台名，避免 keeper 规则被误识别为 Copilot/Claude 专属。"""
    base = os.path.basename(path)
    if base == "AGENTS.md":
        return "# AGENTS.md"
    if base == "copilot-instructions.md":
        return "# GitHub Copilot Instructions"
    if base == "CLAUDE.md":
        return "# Claude"
    return "# Agent Instructions"


def write_agents_md(target_path, block):
    d = os.path.dirname(target_path) or "."
    os.makedirs(d, exist_ok=True)
    if os.path.exists(target_path):
        shutil.copy2(target_path, target_path + ".bak." + _now())
        with open(target_path, encoding="utf-8") as f:
            content = f.read()
        if AUTO_START in content and AUTO_END in content:
            pre = content[:content.index(AUTO_START)]
            post = content[content.index(AUTO_END) + len(AUTO_END):]
            new_content = pre + block + post
        else:
            new_content = content.rstrip() + "\n\n" + block
    else:
        new_content = _header_for(target_path) + "\n\n" + block
    tmp = target_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_content)
    os.replace(tmp, target_path)
    return True


def _rules_sig(sel):
    """行为规则选择集的稳定签名（成员/状态/优先级变 → 签名变）。"""
    import hashlib
    h = hashlib.sha256()
    for e in sel:
        h.update(("%s|%s|%s|%s" % (e.get("id"), e.get("summary"),
                                    e.get("state"), e.get("priority"))).encode("utf-8"))
    return h.hexdigest()[:24]


def _targets_path(root):
    return os.path.join(root, "store", "export_rules_targets.json")


def _record_target(root, target):
    """记录已初始化的行为规则目标（供 self-heal 自动同步）。"""
    p = _targets_path(root)
    targets = []
    if os.path.exists(p):
        try:
            targets = json.load(open(p, encoding="utf-8")).get("targets", [])
        except Exception:
            targets = []
    if target not in targets:
        targets.append(target)
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump({"targets": targets}, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as _e:
            # 2026-10-06：目标登记写失败不再静默。self-heal 自动同步依赖本登记表判断
            # 「目标是否已初始化」，写失败 → 下次同步误判「未初始化」而漏同步。原
            # `except Exception: pass` 把「同步目标丢失」吞成静默；改为告警留痕，不阻断导出。
            import sys as _sys
            _sys.stderr.write("[⚠ export_rules] 目标登记失败（self-heal 自动同步可能漏该目标）：%s\n" % _e)


def export_rules(root, target="project", area=None, state=None, priority=None,
                 filter_str=None, min_count=3, dry_run=False, out_path=None,
                 sync=False, last_sig=None):
    """导出行为规则到目标文件（AGENTS.md/CLAUDE.md/copilot-instructions.md/text）。

    - 手动模式（sync=False）：正常写自动区块 + .bak，并记录目标（供 self-heal 自动同步）。
    - 自动同步模式（sync=True，self-heal 调用）：仅当目标已初始化（文件存在）且
    选择集签名变化时才重写 + .bak；无变化则跳过（避免 .bak 抖动）。尊重
    KEEPER_AUTO_EXPORT_RULES=0（关闭自动写，由 self-heal 在调用前判定）。
    """
    sel = select_entries(root, area, state, priority, filter_str, min_count)
    block = render_rules(sel)
    path = _target_path(target, out_path=out_path)
    sig = _rules_sig(sel)
    if sync:
        if not os.path.exists(path):
            return {"ok": True, "changed": False, "skipped": True,
                    "note": "目标未初始化（先手动跑一次 export-rules 开启自动同步）"}
        if last_sig is not None and last_sig == sig:
            return {"ok": True, "changed": False, "skipped": True, "signature": sig}
        if dry_run:
            return {"ok": True, "dry_run": True, "changed": True, "signature": sig, "target": path}
        write_agents_md(path, block)
        return {"ok": True, "changed": True, "count": len(sel), "signature": sig, "target": path}
        # 手动模式
    if dry_run:
        return {"ok": True, "dry_run": True, "count": len(sel),
                "target": path, "preview": block}
    write_agents_md(path, block)
    try:
        _record_target(root, target)
    except Exception:
        pass
    return {"ok": True, "count": len(sel), "target": path}


def hot_rules(root, min_count=3):
    import memory_ops as M
    sel = [e for e in _active_entries(root)
           if (e.get("recurrence_count") or 1) >= min_count]
    sel.sort(key=lambda e: e.get("recurrence_count", 1), reverse=True)
    return sel


def import_rules(root, target="project", dry_run=False, out_path=None):
    """规则文件自动区块逆向回灌 SQLite（仅 id 不存在的新条目才 deposit）。
    ：--rules-target text 时通过 out_path 传入文件路径，其它目标忽略。"""
    import memory_ops as M
    path = _target_path(target, out_path=out_path)
    if not os.path.exists(path):
        return {"ok": True, "count": 0, "note": "规则文件不存在"}
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if AUTO_START not in content or AUTO_END not in content:
        return {"ok": True, "count": 0, "note": "无自动区块"}
    block = content[content.index(AUTO_START) + len(AUTO_START):
                    content.index(AUTO_END)]
    pat = re.compile(r"-\s+\*\*\[(\w+)[·•](\w+)\]\*\*\s+(.*?)\s+_\(id:\s*(\S+),", re.S)
    added = 0
    for m in pat.finditer(block):
        area, prio, summ, mid = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
        if M._resolve_path(root, mid):
            continue  # 已存在，跳过
        if dry_run:
            added += 1
            continue
        M.deposit(root, "rule", summ, "auto-imported",
                  "从 AGENTS.md 回灌（v4.0.0 import-rules）",
                  area=area, priority=prio)
        added += 1
    return {"ok": True, "count": added, "dry_run": dry_run}
