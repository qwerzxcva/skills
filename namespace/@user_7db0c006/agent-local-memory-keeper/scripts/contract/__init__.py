# -*- coding: utf-8 -*-
"""契约层：L4 keeper 主动预注入（PreInjector）—— 单一可测实现。

设计目标（稳固优先，非省事版）：
- 把原本散落在 `hooks/user_prompt_recall.py` 的闸门逻辑（tokenize / containment /
双闸门 / format / 会话去重 / fail-open）收口成**单一、纯函数、带测试**的实现；
钩子改为委托本模块，消除重复与不可测性。
- 新增：PII 护栏（绝不把疑似密钥/隐私的条目灌入对话上下文）、可观测回调
（记录注入了哪条/为何/相关性分/降级原因）。
- 硬约束（来自 Skill 总体设计，不可破）：WB 原生记忆（L1/L2/L3）与 keeper（L4）
永不直接互写；跨系统动作只走 mem_bridge，distill 由用户触发。

本模块**纯逻辑、零副作用**：不 import keeper_hook_common（那是钩子领地，可能沙箱受限）。
所有对外部（回忆/会话去重/审计/可观测）的依赖都以**回调/参数**注入，便于单测用 fake 替代。

类别约定（沿用 proven 钩子，行为保持一致）：
- prompt < 6 字不召回；
- 本地 2-gram 词法重叠门控（MIN_SHARED / MIN_RATIO）；
- 神经后端可用时额外接受 score >= MIN_SCORE；
- 字符预算 CHAR_BUDGET；会话级 skip_ids 去重；
- 任何异常 → 空注入、reason="degraded"（fail-open）。
"""
import re
from typing import List, Dict, Any, Callable, Optional

__all__ = ["tokenize", "containment", "PII_PATTERNS", "redact_or_drop",
           "INJECTION_PATTERNS", "is_injection",
           "PreInjector", "InjectResult"]

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")

# 注入侧 PII 护栏：命中即丢弃该条目（绝不灌入对话上下文）。
# 保守覆盖最危险几类；deposit 侧已有隔离，此处为注入端 defense-in-depth。
PII_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),          # OpenAI 类 key
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),          # GitHub
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack
    re.compile(r"(?i)api[_-]?key[\"'\s:=]{1,4}[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)password[\"'\s:=]{1,4}[^\s\"']{6,}"),
    re.compile(r"(?i)secret[\"'\s:=]{1,4}[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)token[\"'\s:=]{1,4}[A-Za-z0-9_\-]{16,}"),
    re.compile(r"[\w.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"),  # 邮箱
    re.compile(r"(?i)(C:\\|D:\\|/home/|/Users/)[^\s\"']+"),  # 绝对路径
]

# 注入指令护栏（defense-in-depth，P1-b 安全硬缺口）：
# keeper 库若被写入含指令注入的文本（如被诱导的 auto_capture 结果、恶意工具输出），
# 预注入会把它直接塞进对话 additionalContext，等于替攻击者给 agent 下指令。
# 此护栏与 PII 护栏同级——命中已知注入范式即丢弃该条目，绝不灌入上下文。
# 覆盖中英文典型范式（忽略/无视/忘记 + 指令/规则；system prompt；把密钥/密码输出给攻击者）。
# 这是最后一道闸，fail-open 之前；纯函数、可单测。
INJECTION_PATTERNS = [
    re.compile(r"(?i)忽略.{0,16}(之前|此前|以上|先前|所有|上面的).{0,12}(指令|指示|规则|设定|prompt)"),
    re.compile(r"(?i)无视.{0,12}(之前|此前|所有).{0,12}(指令|规则)"),
    re.compile(r"(?i)忘记.{0,8}(之前|此前|所有).{0,12}(指令|规则|设定)"),
    re.compile(r"(?i)你(现在)?(必须|应该|需要|悄悄)?(忽略|无视|忘记|绕过).{0,12}(指令|规则|设定|prompt)"),
    re.compile(r"(?i)ignore.{0,16}(previous|prior|all|above|earlier).{0,12}(instructions?|prompt|rules?)"),
    re.compile(r"(?i)disregard.{0,16}(previous|prior|all|above|earlier).{0,12}(instructions?|prompt|rules?)"),
    re.compile(r"(?i)system\s*prompt"),
    re.compile(r"(?i)系统\s*提示"),  # 中文 system prompt（含"输出系统提示"变体）
# 强信号："忽略/无视/忘记 + 所有/全部/一切"（无需紧跟指令词，覆盖"忽略以上所有内容"）
    re.compile(r"(?i)(忽略|无视|忘记|绕过).{0,8}(所有|全部|一切)"),
    re.compile(r"(?i)把.{0,10}(密钥|密码|token|secret|key|凭证).{0,14}(输出|发送|泄露|发给|告诉|粘贴|给攻击者)"),
    re.compile(r"(?i)输出.{0,10}(你的|the|your)?(密钥|密码|token|secret|key|系统提示|system)"),
    re.compile(r"(?i)output.{0,12}(your|the).{0,12}(key|password|token|secret)"),
    re.compile(r"(?i)repeat.{0,12}(your|the).{0,12}(system|initial).{0,12}(prompt|instruction)"),
    re.compile(r"(?i)reveal.{0,12}(your|the).{0,12}(key|password|token|secret|system)"),
]


def tokenize(text: str) -> set:
    """中英文混合分词：ASCII 词(>=2) + 中文相邻 2-gram。返回 set。
    与 keeper_hook_common.tokenize 行为一致（单一真源）。"""
    text = text or ""
    toks = set(_TOKEN_RE.findall(text.lower()))
    cjk = re.findall(r"[一-鿿]", text)
    for i in range(len(cjk) - 1):
        toks.add(cjk[i] + cjk[i + 1])
    return {t for t in toks if len(t) >= 2 or (len(t) == 2 and not t.isdigit())}


def containment(hay: set, needle: set):
    """needle 的词表中有多少比例出现在 hay 中；返回 (比例, 交集绝对数)。"""
    if not hay or not needle:
        return 0.0, 0
    inter = hay & needle
    return (len(inter) / len(needle), len(inter))


def redact_or_drop(text: str) -> Optional[str]:
    """注入端 PII 护栏：命中任一敏感模式 → 返回 None（丢弃该条目）。
    否则原样返回。纯函数，可单测。"""
    if not text:
        return text
    for pat in PII_PATTERNS:
        if pat.search(text):
            return None
    return text


def is_injection(text: str) -> bool:
    """注入指令检测（纯函数，可单测）。命中已知注入范式（忽略指令/输出密钥等）→ True。
    
    用于 PreInjector 注入端最后一道闸：绝不把含指令注入的记忆灌进对话上下文。
    """
    if not text:
        return False
    for pat in INJECTION_PATTERNS:
        if pat.search(text):
            return True
    return False


class InjectResult:
    """inject 的结构化结果（供钩子包成 WorkBuddy hook 信封，或测试断言）。"""

    def __init__(self, injected: bool, entries: List[Dict[str, Any]],
                 formatted: str, reason: str, picked: int, candidates: int,
                 skipped: int, degraded: bool, skipped_guard: int = 0):
        self.injected = injected
        self.entries = entries
        self.formatted = formatted
        self.reason = reason
        self.picked = picked
        self.candidates = candidates
        self.skipped = skipped
        self.degraded = degraded
        self.skipped_guard = skipped_guard

    def to_dict(self) -> Dict[str, Any]:
        return {
            "injected": self.injected,
            "count": len(self.entries),
            "formatted": self.formatted,
            "reason": self.reason,
            "picked": self.picked,
            "candidates": self.candidates,
            "skipped": self.skipped,
            "skipped_guard": self.skipped_guard,
            "degraded": self.degraded,
        }

    def __repr__(self):
        return "InjectResult(%s picked=%d cand=%d reason=%s)" % (
            "INJ" if self.injected else "EMPTY",
            self.picked, self.candidates, self.reason)


class PreInjector:
    """L4 -> 对话上下文的主动预注入器（单一可测实现）。
    
    用法（钩子委托）：
    inj = PreInjector()
    res = inj.inject(
    prompt=prompt,
    session_id=session,
    recall_fn=lambda q, n: json.loads(C.recall(query=q, top_n=n)),
    session_injected_ids_fn=C.session_injected_ids,
    mark_injected_fn=C.mark_session_injected,
    neural_active=C.neural_recall_active(),
    audit_fn=C.audit,
    )
    # 再按 res.to_dict 包成 WorkBuddy hook 信封 / IMA 兜底提示。
    """

    def __init__(self, top_n: int = 8, char_budget: int = 900,
                 min_shared: int = 3, min_ratio: float = 0.15,
                 min_score: float = 0.30, pii_guard: bool = True,
                 observ: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.top_n = top_n
        self.char_budget = char_budget
        self.min_shared = min_shared
        self.min_ratio = min_ratio
        self.min_score = min_score
        self.pii_guard = pii_guard
        self.observ = observ

# ---- 纯函数：相关性闸门（与 proven 钩子 _select 行为一致）----
    def select(self, prompt: str, entries: List[Dict[str, Any]],
               skip_ids: set, neural_active: bool) -> List[Dict[str, Any]]:
        pt = tokenize(prompt)
        picked = []
        for e in entries:
            eid = e.get("id")
            if eid in skip_ids:
                continue
            et = tokenize((e.get("summary") or "") + " " + (e.get("body") or ""))
            r1, shared = containment(pt, et)
            r2, _ = containment(et, pt)
            lexical_hit = shared >= self.min_shared and max(r1, r2) >= self.min_ratio
            score_hit = False
            if neural_active:
                sc = e.get("score")
                try:
                    if sc is not None and float(sc) >= self.min_score:
                        score_hit = True
                except Exception:
                    pass
            if lexical_hit or score_hit:
                picked.append(e)
        return picked

# ---- 纯函数：格式化（与 proven 钩子 _format 行为一致，含字符预算）----
    def format(self, entries: List[Dict[str, Any]]) -> str:
        lines = ["## 🧠 与本次提问相关的历史经验（keeper）", "", ""]
        used = 0
        for e in entries:
            s = (e.get("summary") or "").strip()
            b = (e.get("body") or "").strip().replace("\n", " ")[:160]
            block = "- **%s**：%s %s" % (e.get("category", "general"), s, b)
            if used + len(block) > self.char_budget:
                lines.append("_（更多可用 recall 拉取）_")
                break
            lines.append(block)
            used += len(block)
        return "\n".join(lines)

# ---- 编排：召回 + PII 护栏 + 闸门 + 格式化 + 会话去重 + fail-open + 可观测 ----
    def inject(self, prompt: str, session_id: str,
               recall_fn: Callable[[str, int], Dict[str, Any]],
               session_injected_ids_fn: Callable[[str], set],
               mark_injected_fn: Callable[[str, List[str]], None],
               neural_active: Optional[bool] = None,
               audit_fn: Optional[Callable[[str, str, str], None]] = None
               ) -> InjectResult:
# 护栏 0：prompt 过短不召回（省成本 + 降噪）
        if not prompt or len(prompt.strip()) < 6:
            return InjectResult(False, [], "", "prompt_too_short", 0, 0, 0, False)

        skip_ids = set()
        try:
            skip_ids = set(session_injected_ids_fn(session_id) or [])
        except Exception:
            skip_ids = set()

        try:
            raw = recall_fn(prompt, self.top_n)
            entries = (raw or {}).get("entries", []) or []
        except Exception as e:
            if audit_fn:
                try:
                    audit_fn("PreInjector", "error", "recall failed: %s" % e)
                except Exception:
                    pass
            return InjectResult(False, [], "", "degraded", 0, 0, len(skip_ids), True)
        n_raw = len(entries)  # 召回原始候选数（PII 护栏前），用于诊断
        skipped_guard = 0

# 护栏 1：PII 护栏 + 注入指令护栏（注入端 defense-in-depth）
        if self.pii_guard:
            safe = []
            for e in entries:
                txt = (e.get("summary") or "") + " " + (e.get("body") or "")
                if redact_or_drop(txt) is None:
# PII（密钥/邮箱/路径）命中 → 丢弃
                    skipped_guard += 1
                    continue
                if is_injection(txt):
# 注入指令命中（忽略指令/输出密钥等）→ 丢弃并审计
                    skipped_guard += 1
                    if audit_fn:
                        try:
                            audit_fn("PreInjector", "drop",
                                     "injection guard: %s" % (e.get("id") or "?"))
                        except Exception:
                            pass
                    continue
                safe.append(e)
            entries = safe

        picked = self.select(prompt, entries, skip_ids, bool(neural_active))

        if not picked:
            return InjectResult(False, [], "", "no_local_hit", 0, n_raw,
                                 len(skip_ids), False, skipped_guard)

        formatted = self.format(picked)
        try:
            mark_injected_fn(session_id, [e.get("id") for e in picked if e.get("id")])
        except Exception:
            pass  # fail-open：标记失败不影响本次注入

        res = InjectResult(True, picked, formatted, "ok", len(picked),
                           n_raw, len(skip_ids), False, skipped_guard)
        if self.observ:
            try:
                self.observ("inject", res.to_dict())
            except Exception:
                pass
        return res
