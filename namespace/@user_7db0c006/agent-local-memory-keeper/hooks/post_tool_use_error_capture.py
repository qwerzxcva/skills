# -*- coding: utf-8 -*-
"""
post_tool_use_error_capture.py — WorkBuddy PostToolUse 钩子（端口化版）
自动捕获 Bash/Shell 工具执行失败，沉淀一条 bugfix 经验进 keeper 记忆库。

修正 keeper 自带 bash_error_capture.py 的字段名 bug：
WorkBuddy PostToolUse 实测 stdin schema 用 tool_name / tool_input / tool_response，
原脚本读 output / exit_code，导致启用后永不触发。本钩子改用正确字段。

设计要点：
- 仅在 tool 含 bash/shell 且检测到失败信号时动作；否则立即退出（零开销）。
- 同一错误指纹 10 分钟内冷却、每日上限 10 条，避免刷屏。
- 直接调 memory_ops.deposit（与 keeper 自带钩子同路，最稳），带 recorded_by/auto_sourced。
- 失败 / 超时 / 异常 -> 静默退出（fail-open，绝不阻断任务）。
- 端口化（v4.5.2）：PY/SCR/WB_HOME 由 keeper_hook_common 推导，不再硬编码具体 Windows 用户名主目录。
"""
import sys, os, json, subprocess, time, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keeper_hook_common as C

PY = C.PY
SCR = C.SCR
STATE = os.path.join(C.WB_HOME, "hooks", "_errcap_state.json")
COOLDOWN_S = 600
DAILY_CAP = 10
ERR_KEYS = ["error", "traceback", "exception", "failed", "拒绝", "错误", "异常", "errcode"]


def _load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"errors": {}, "date": "", "count": 0}


def _save_state(s):
    with C.locked(STATE):
        C.atomic_write_json(STATE, s)


def _today():
    return time.strftime("%Y-%m-%d")


def _deposit(summary, body):
    sys.path.insert(0, SCR)
    import memory_ops as M
    root = C.store_root()
    M.init_store(root)
    M.deposit(root, "pitfall", summary, "auto-captured,bash-error", body,
              area="bugfix", priority="high", recorded_by="agent", auto_sourced=True)


def main():
    try:
        # 消毒：Bash 输出常含非法字节（git-bash 中文/GBK 混排），stdin 解成 \udcXX 后
        # json.load 不报错但写盘必崩（实测 502 次 deposit_error），故读进来就替换成 U+FFFD
        evt = C.read_event()
    except Exception:
        print(json.dumps({"continue": True}))
        return
    if not isinstance(evt, dict):
        print(json.dumps({"continue": True}))
        return
    tool = (evt.get("tool_name") or evt.get("tool") or "").lower()
    if "bash" not in tool and "shell" not in tool:
        return
    resp = evt.get("tool_response") or evt.get("output") or evt.get("result") or ""
    # ── 2026-09-05 修复：原实现两处缺陷叠加，造成 100% 误判（每次 bash 执行都被当错误入库）──
    # ① 退出码：原读 snake_case `exit_code`，而 WorkBuddy 事件实为 camelCase `exitCode`
    #    → 恒为 None，退出码判定彻底失效。
    # ② 关键词：原对「整段响应 JSON」裸匹配，而响应恒含字段名 "tool_error_code"
    #    （内含子串 "error"）→ ERR_KEYS 永远命中，成功命令也被判为错误。
    # 实测后果：记忆库 30 条中 22 条（73%）是 bash 输出垃圾，仅 2 条为真经验。
    # 修法：退出码兼容两种命名；关键词只对「真实输出内容」匹配，不对含字段名的元数据 JSON 匹配。
    # 2026-09-12 修复：原实现将整个 Bash 返回 JSON（dict）json.dumps 成单行串后 splitlines 取末行，
    # 导致 summary 变成整个 {"exitCode":...} 结构（已污染库 11 条格式错误记忆）。
    # 修法：直接从真实输出字段（stderr/stdout 文本）提取错误行，元数据 JSON 不再参与 summary/匹配。
    # 2026-09-13 修复（第三种缺陷，前两次均未覆盖）：真失败**能**抓到，错误文本却取不到 → 落库空壳。
    #   实测证据：5 条 auto-captured 记忆的「错误输出」全空；_errcap_state.json 指纹恒为
    #   d41d8cd98f00b204e9800998ecf8427e（= md5("")）→ 10 分钟去重冷却被彻底架空（所有失败共用一个坑位）。
    #   成因：`tr = resp if isinstance(resp, dict) else {}` 在事件把 tool_response 给成**字符串**时
    #   tr 恒为空 dict → stderr/stdout 皆空 → real_out=""；而 code≠0 已令 err_sig 为真，于是照写空壳。
    #   修法：① 字符串响应先尝试 json 解析，失败则整体视为纯文本 stdout（兼容两种事件形态）；
    #         ② **加空文本早退门** —— 取不到任何错误文本就不入库（空壳对未来的自己零信息量，
    #            却因 tier=working+priority=high 霸占 list_working 进行态列表）。
    tr = resp if isinstance(resp, dict) else {}
    if not tr and isinstance(resp, str) and resp.strip():
        _s = resp.strip()
        if _s[0] in "{[":
            try:
                _j = json.loads(_s)
                if isinstance(_j, dict):
                    tr = _j
            except Exception:
                pass
        if not tr:
            tr = {"stdout": _s}
    stderr_text = str(tr.get("stderr") or "").strip()
    stdout_text = str(tr.get("stdout") or "").strip()
    real_out = stderr_text or stdout_text  # 仅真实输出文本，不含含字段名的元数据 JSON
    code = evt.get("exitCode", evt.get("exit_code", tr.get("exitCode", tr.get("exit_code"))))
    if code is not None:
        # 拿到退出码即以它为准：非 0 必是错误；为 0 时只查 stderr（不把 stdout 日志里的 error 字样误判）。
        err_sig = (code != 0) or any(k in stderr_text.lower() for k in ERR_KEYS)
    else:
        # 无退出码：退回真实输出内容匹配（real_out 只含 stdout/stderr 文本，不含元数据 JSON 字段名）。
        err_sig = any(k in real_out.lower() for k in ERR_KEYS)
    if not err_sig:
        return
    lines = [l for l in real_out.splitlines() if l.strip()][-10:]
    err_text = "\n".join(lines)[-1000:]
    if not err_text.strip():
        # 空壳门（2026-09-13）：判定为失败但拿不到任何错误文本 → 不入库。
        # 依据：md5("") 恒定会让指纹去重失效；且空壳对排障零价值，只污染 working 层。
        return
    fingerprint = hashlib.md5(err_text[-300:].encode("utf-8")).hexdigest()
    st = _load_state()
    if st.get("date") != _today():
        st = {"errors": {}, "date": _today(), "count": 0}
    now = time.time()
    prev = st["errors"].get(fingerprint)
    if prev and now - prev < COOLDOWN_S:
        return
    if st.get("count", 0) >= DAILY_CAP:
        return
    tin = evt.get("tool_input") or {}
    cmd = ""
    if isinstance(tin, dict):
        cmd = tin.get("command") or tin.get("cmd") or tin.get("code") or ""
    elif isinstance(tin, str):
        cmd = tin
    summary = (("%s -> %s" % (cmd[:50], lines[-1])) if (cmd and lines) else (lines[-1] if lines else (cmd[:80] if cmd else "bash 执行失败")))[:120]
    body = "命令:\n%s\n\n错误输出:\n%s" % (cmd[:600], err_text)
    try:
        _deposit(summary, body)
        st["errors"][fingerprint] = now
        st["count"] = st.get("count", 0) + 1
        _save_state(st)
        C.audit("PostToolUse", "deposit", summary[:60])
    except Exception as e:
        sys.stderr.write("[errcap] deposit 失败: %s\n" % e)
        C.audit("PostToolUse", "deposit_error", str(e)[:60])


if __name__ == "__main__":
    main()
