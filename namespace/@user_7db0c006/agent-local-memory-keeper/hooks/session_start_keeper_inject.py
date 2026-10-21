# -*- coding: utf-8 -*-
"""
session_start_keeper_inject.py — WorkBuddy SessionStart 钩子（端口化版）
每次会话开局把 keeper 里「与当前工作区相关」的经验注入为上下文，跨会话复用踩坑/方法。

为什么不用 keeper 官方 inject：官方 inject 的 _inject_exclude_wb 会剔除所有 src:wb_memory 记忆，
而本机库目前全是 WB 来源 → 官方 inject 恒空。故直接 recall 自行格式化。

改进（相对初版）：
- 用 keeper_hook_common.prepare_env()：回退链 AI_MEMORY_STORE → ~/.keeper/store_root → ~/.ai-memory，避免读错库。
- 注入的 entry id 写入会话级状态，供 UserPromptSubmit 跨钩子去重（不重复注入）。
- 动作写 hook_audit.log，便于重启后确认会话开局注入是否真发生。
- 调试信息写 stderr，不污染 stdout 的 JSON。
- 端口化（v4.5.2）：MIRROR_DIR 由 C.WB_HOME 推导，不再硬编码具体 Windows 用户名主目录。

v4.5.50 修复：IMA_KB_ID 未配置（env 缺失/占位符）时不再把「KB=YOUR_IMA_KB_ID」这种
不可用占位指令注入 agent 上下文；仅当 env 真实配置 IMA_KB_ID 时才拼装 IMA_DIRECTIVE。

v5.1.1 新增（A2 降级开局提示）：语义后端降级状态由 mem_bridge recall 落盘到
~/.workbuddy/hooks/.keeper_degraded.json，本钩子开局零成本读取；近期曾降级则注入
「请转告用户」健康告警——独立于 inject_enabled 门禁（健康告警不是经验注入）。
"""
import sys, os, json
import datetime as _dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keeper_hook_common as C

TOP_N = 5
CHAR_BUDGET = 1600

# IMA 云端记忆镜像的本地缓存（由每周自动化写入，见 _keeper_ima_push.py）。
# 钩子子进程无法调用 IMA MCP，故用本地镜像做词法补充召回（覆盖 keeper 已归档/衰减的记忆）。
MIRROR_DIR = os.path.join(C.WB_HOME, "ima_mirror")
IMA_KB_ID = os.environ.get("IMA_KB_ID") or ""
IMA_PLACEHOLDER = "YOUR_IMA_KB_ID"

# A2：语义后端降级状态文件（mem_bridge recall 降级时落盘）
DEGRADED_STATE = os.path.join(C.WB_HOME, "hooks", ".keeper_degraded.json")


def _degraded_note():
    """A2：开局读取语义后端降级状态（mem_bridge recall 降级时落盘）。
    近期（7 天内）曾降级则返回提示，让 AI 主动告知用户并引导修复。
    不依赖 inject_enabled——健康告警独立于经验注入。"""
    try:
        if not os.path.exists(DEGRADED_STATE):
            return ""
        with open(DEGRADED_STATE, encoding="utf-8") as f:
            st = json.load(f)
        ts = st.get("degraded_at") or ""
        try:
            if (_dt.datetime.now() - _dt.datetime.fromisoformat(ts)).days > 7:
                return ""
        except Exception:
            pass
        return (
            "> ⚠️【记忆系统状态·请转告用户】语义召回后端已降级为词法级（召回质量下降）。\n"
            "> 请在本轮回复中主动告知用户：说「帮我一键配好」即可自动修复；"
            "或让用户自跑 `python mem_bridge.py doctor --fix`。")
    except Exception:
        return ""


def _ima_directive():
    """仅当 IMA_KB_ID 真实配置（非占位符/未设）时才拼装注入指令；否则返回空串。
    修复：env 未设时旧版会把「KB=YOUR_IMA_KB_ID」这种不可用占位指令喂给 agent。"""
    if not IMA_KB_ID or IMA_KB_ID == IMA_PLACEHOLDER:
        return ""
    return (
        "> 💡 IMA 云端记忆镜像（KB=%s）可作语义召回兜底：当本地记忆召回不足、用户意图模糊、"
        "或问及跨设备/久远经验时，调用 IMA MCP `search_knowledge`(knowledge_base_id=%s) "
        "做云端语义补充召回，再并入回答。" % (IMA_KB_ID, IMA_KB_ID)
    )


def _emit(context=None):
    if context:
        print(json.dumps({
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
    else:
        print(json.dumps({"continue": True}))


def _format(entries):
    lines = ["## 🧠 当前生效的 AI 经验（来自 keeper 记忆库，跨工作区复用）",
             "> 以下为与本次工作区相关的历史经验，仅供参考；如有冲突以当前事实为准。", ""]
    used = 0
    for e in entries:
        summary = (e.get("summary") or "").strip()
        body = (e.get("body") or "").strip().replace("\n", " ")
        cat = e.get("category") or "general"
        snippet = body[:200]
        block = "- **[%s] %s**：%s" % (cat, summary, snippet)
        if used + len(block) > CHAR_BUDGET and lines[-1] != "":
            lines.append("_（上下文预算已满，更多经验可用 `recall` 按需拉取）_")
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


def _recall(query=None):
    # 透明召回分发器：recall_mode=inprocess 时直接 memory_ops recall（无独立守护进程）；
    # 否则走常驻 daemon。由 keeper_hook_common.recall 按 config 分发。
    # 🔴 4.9.19：显式带上 `inject_include_auto`（默认 True）。recall 默认隔离「自动捕获
    #    但未 confirm」的暂存项，而很多用户（含本机）库里**全部**记忆都是 auto_sourced
    #    → 不带该开关时本钩子恒召回为空（审计只见 `empty no entries`），「启动即注入」名存实亡。
    #    注入文案自带「仅供参考；冲突以当前事实为准」免责声明，且有 TOP_N/字符预算限流。
    return json.loads(C.recall(query=query, top_n=TOP_N,
                               include_auto=C.inject_include_auto()))


def _parse_mirror_entries():
    """解析本地 IMA 镜像目录，返回 [{summary,meta,body,status,importance}] 列表。"""
    import re as _re
    entries = []
    if not os.path.isdir(MIRROR_DIR):
        return entries
    for fn in os.listdir(MIRROR_DIR):
        if not fn.endswith(".md"):
            continue
        try:
            text = open(os.path.join(MIRROR_DIR, fn), encoding="utf-8").read()
        except Exception:
            continue
            # 按 `## N. 标题` 切分每条记忆
        parts = _re.split(r"\n##\s+\d+\.\s+", "\n" + text)
        for seg in parts[1:]:
            lines = seg.splitlines()
            summary = lines[0].strip() if lines else ""
            meta = ""
            body_lines = []
            for ln in lines[1:]:
                if ln.startswith("> 域:"):
                    meta = ln
                elif ln.startswith("**标签**"):
                    break
                elif ln.strip() in ("---", ""):
                    continue
                else:
                    body_lines.append(ln.strip())
            st = _re.search(r"状态:(\w+)", meta)
            status = st.group(1) if st else "active"
            imp = _re.search(r"重要度:([\d.]+)", meta)
            importance = float(imp.group(1)) if imp else 0.0
            body = " ".join(body_lines)
            entries.append({"summary": summary, "meta": meta, "body": body,
                            "status": status, "importance": importance})
    return entries


def _ima_mirror_supplement(ws):
    """从本地镜像挑 archived/superseded 且与工作区相关的条目做补充（keeper 不覆盖的部分）。"""
    try:
        entries = _parse_mirror_entries()
    except Exception as e:
        sys.stderr.write("[hook] mirror parse failed: %s\n" % e)
        return ""
    wt = C.tokenize(ws)
    picked = []
    for e in entries:
        if e["status"] == "active":
            continue  # 活跃记忆本地 keeper 已覆盖，镜像只补归档/衰减部分
        et = C.tokenize(e["summary"] + " " + e["body"])
        r, shared = C.containment(wt, et)
        if shared >= 2 and r >= 0.1:
            picked.append(e)
    picked.sort(key=lambda x: x["importance"], reverse=True)
    picked = picked[:2]
    if not picked:
        return ""
    lines = ["## 🧊 IMA 冷存储补充（本地 keeper 已归档/衰减，镜像兜底）", ""]
    for e in picked:
        snippet = e["body"][:120].replace("\n", " ")
        lines.append("- **[%s] %s**：%s" % (e["status"], e["summary"], snippet))
    return "\n".join(lines)


def main():
    try:
        evt = C.read_event()
    except Exception:
        evt = {}
    if not isinstance(evt, dict):
        evt = {}
    if evt.get("source") not in (None, "startup"):
        _emit()
        return
    # A2：开局读一次降级状态（健康告警，独立于 inject_enabled 与经验注入）
    _degraded = _degraded_note()
    # ── 注入开关守门（方案 A，4.9.3）──
    # SKILL.md 承诺 `inject_enabled` 默认 false =「默认关，靠显式 retrieve」。此前钩子完全不读
    # 这个开关，导致承诺落空：只要钩子模式不是 off，每会话开局都无条件注入 TOP_N 条。
    # 现在守在此处，开关真正生效；想恢复自动注入：
    #   store/config.json 的 keeper.inject_enabled=true，或 env KEEPER_INJECT_ENABLED=1。
    if not C.inject_enabled():
        C.audit("SessionStart", "skip", "inject_enabled=false（默认关）；"
                "开启：store/config.json keeper.inject_enabled=true 或 KEEPER_INJECT_ENABLED=1")
        _emit(_degraded)
        return

    cwd = evt.get("cwd") or ""
    ws = os.path.basename(cwd.rstrip("/\\")) or "work"
    session = evt.get("session_id") or ""
    entries = []
    try:
        d = _recall(ws)
        entries = d.get("entries", [])
        if not entries:
            d = _recall(None)
            entries = d.get("entries", [])
    except Exception as e:
        sys.stderr.write("[hook] recall 失败: %s\n" % e)
        C.audit("SessionStart", "error", str(e))
        _emit(_degraded)
        return

    if not entries:
        C.audit("SessionStart", "empty", "no entries")
        _emit(_degraded)
        return
    chosen = entries[:TOP_N]
    C.mark_session_injected(session, [e.get("id") for e in chosen if e.get("id")])
    # IMA 镜像冷存储补充（归档/衰减记忆，本地 keeper 不覆盖）
    supp = _ima_mirror_supplement(ws)
    C.audit("SessionStart", "inject", "ws=%s entries=%d supp=%d ids=%s"
            % (ws, len(chosen), 1 if supp else 0,
               [e.get("id") for e in chosen if e.get("id")][:3]))
    parts = [_format(chosen)]
    if supp:
        parts.append(supp)
    ima_d = _ima_directive()
    if ima_d:
        parts.append(ima_d)
    if _degraded:
        parts.append(_degraded)
    _emit("\n\n".join(parts))


if __name__ == "__main__":
    main()
