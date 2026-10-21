# -*- coding: utf-8 -*-
"""
user_prompt_recall.py — WorkBuddy UserPromptSubmit 钩子（端口化版）
每次你发消息，按这条消息语义召回经验，仅当**相关性闸门**判定真正相关时才注入。

闸门逻辑（tokenize / 双闸门 / 会话去重 / PII 护栏 / fail-open）已收口到
`scripts/contract/__init__.py` 的 PreInjector（单一可测实现）；本钩子只做：
- 解析 hook 事件、构造 recall/会话回调；
- 调用 PreInjector.inject 拿到结构化结果；
- 包成 WorkBuddy hook 信封，或在弱召回时给 IMA 云端镜像兜底提示。
所有动作写 hook_audit.log；失败/异常 → continue:true 空上下文（fail-open）。

v4.5.2 端口化；v4.5.50 门控自适应（神经后端可用时优先 score 门控）；
v4.6.5 闸门逻辑收口至 contract.PreInjector（去重 + 加测试 + PII 护栏）。
"""
import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keeper_hook_common as C

# 让本钩子能 import 契约层（scripts/contract）
_SCRIPTS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from contract import PreInjector  # noqa: E402
from contract.observ import emit_inject_record  # noqa: E402

# IMA 云端记忆镜像 KB（本地弱召回时的语义兜底源；钩子不能调 MCP，仅提示 agent 去查）
IMA_KB_ID = os.environ.get("IMA_KB_ID") or ""
IMA_PLACEHOLDER = "YOUR_IMA_KB_ID"

# 注入日志路径（与 hook_audit.log 同目录）：让"注入了什么/为何/降级几次"可被 doctor 聚合。
INJECT_LOG_PATH = os.path.join(C.HOOKS_DIR, "inject_log.jsonl")


def main():
    try:
        evt = C.read_event()
    except Exception:
        evt = {}
    if not isinstance(evt, dict):
        evt = {}
    prompt = evt.get("prompt") or ""
    session = evt.get("session_id") or ""

    inj = PreInjector()  # 默认阈值与历史 proven 钩子一致
    try:
        res = inj.inject(
            prompt=prompt,
            session_id=session,
            # 🔴 4.9.19：带 `inject_include_auto`（默认 True）——recall 默认隔离
            # auto_sourced 暂存项，而「库内全是自动捕获、从未 confirm」的用户若不带上它
            # 会恒召回为空（注入功能名存实亡）。详见 keeper_hook_common.inject_include_auto。
            recall_fn=lambda q, n: json.loads(
                C.recall(query=q, top_n=n, include_auto=C.inject_include_auto())),
            session_injected_ids_fn=C.session_injected_ids,
            mark_injected_fn=C.mark_session_injected,
            neural_active=C.neural_recall_active(),
            audit_fn=C.audit,
        )
    except Exception as e:
        sys.stderr.write("[prompt_recall] %s\n" % e)
        C.audit("UserPromptSubmit", "error", str(e))
        print(json.dumps({"continue": True}))
        return

        # 可观测：每次召回（无论是否注入）落注入日志，供 doctor_contract 聚合健康/降级率。
        # fail-open：日志写失败不影响本次注入。
    try:
        emit_inject_record(INJECT_LOG_PATH, res.to_dict(), session)
    except Exception:
        pass

        # 可观测：保留与历史一致的诊断审计行
    C.audit("UserPromptSubmit", "recall",
            "candidates=%d picked=%d skip=%d reason=%s"
            % (res.candidates, res.picked, res.skipped, res.reason))

    if not res.injected:
        # 弱/零召回：无 IMA 兜底源时保持空上下文；有则提示 agent 对 IMA 云端镜像做语义补充召回。
        if res.reason == "degraded":
            C.audit("UserPromptSubmit", "degraded", "recall failed → empty ctx")
        else:
            C.audit("UserPromptSubmit", "weak", "no local hit → suggest IMA fallback")
        if IMA_KB_ID and IMA_KB_ID != IMA_PLACEHOLDER:
            hint = (
                "## 🔎 本地记忆弱召回提示\n"
                "> 本次提问本地 keeper 无强相关记忆（相关性闸门未命中）。如需更广语义召回，"
                "可对 IMA 云端记忆镜像（KB=%s）调用 `search_knowledge` 做云端语义补充——"
                "尤其涉及跨设备/久远/中文改写表述的经验。" % IMA_KB_ID
            )
            print(json.dumps({"continue": True, "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": hint
            }}, ensure_ascii=False))
        else:
            print(json.dumps({"continue": True}))
        return

    print(json.dumps({"continue": True, "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": res.formatted
    }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
