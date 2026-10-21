# -*- coding: utf-8 -*-
"""契约层：可观测（注入日志 + doctor 健康摘要）。

设计目标（稳固优先）：
- 预注入是"长期可用"的关键路径，但原钩子只在 hook_audit.log 写一行诊断，难以聚合。
本模块提供结构化注入日志（JSONL，原子写、fail-open）+ doctor 健康摘要，
让"注入了什么/为何/降级几次/路由有无跨层冲突"可被一眼看清。
- 纯逻辑、零副作用（写文件 fail-open），可单测。
"""
import os
import sys
import time
import json
import tempfile

from contract import PreInjector  # 单一真源：门控阈值来自此处
from contract.router import RouteRegistry

# 注入日志滚动上限：超过此体积则仅保留尾部 KEEP_LINES 行，防长期运行无限增长。
_INJECT_LOG_MAX_BYTES = 2_000_000
_INJECT_LOG_KEEP_LINES = 2000


def _rotate_inject_log(path, max_bytes, keep):
    """体积超限时保留尾部 keep 行（原子 temp→replace）。fail-open。"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= max_bytes:
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-keep:] if len(lines) > keep else lines
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix="._tmp_", suffix=".jsonl")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(tail)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
    except Exception:
        pass


class InjectLog:
    """注入日志（JSONL，原子追加）。fail-open：任何异常静默忽略。"""

    def __init__(self, path):
        self.path = path

    def append(self, record):
        try:
            d = os.path.dirname(os.path.abspath(self.path))
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            # 追加也要防并发半截：temp 写 → os.replace 到 .tmp 再 rename 过于重；
            # 这里用单 fd 追加 + 行级 JSON（每行独立），足够可观测且低成本。
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            _rotate_inject_log(self.path, _INJECT_LOG_MAX_BYTES, _INJECT_LOG_KEEP_LINES)
        except Exception:
            pass

    def recent(self, n=20):
        try:
            if not os.path.exists(self.path):
                return []
            with open(self.path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            out = []
            for ln in lines[-n:]:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
            return out
        except Exception:
            return []


def _now_iso():
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""


def doctor_contract(inject_log_path, route_registry=None, neural_active=False):
    """聚合契约层健康摘要（供 doctor 调用）。只读、结构化。"""
    inj_log = InjectLog(inject_log_path) if inject_log_path else None
    recent = inj_log.recent(50) if inj_log else []
    total = len(recent)
    degraded = sum(1 for r in recent if r.get("degraded"))
    injected = sum(1 for r in recent if r.get("injected"))
    conflicts = route_registry.all_conflicts() if route_registry else {}
    route_dist = route_registry.distribution() if route_registry else {}
    route_promotion = (route_dist.get("L2", 0) + route_dist.get("L3", 0))
    # 2026-09-15：裸计数 → 可操作清单（给出「是哪几条、canonical 层是什么」）。
    try:
        route_promotion_list = route_registry.promotion_candidates(limit=50) if route_registry else []
    except Exception:
        route_promotion_list = []
    inj = PreInjector()  # 取默认门控阈值用于展示
    return {
        "gate": {
            "top_n": inj.top_n,
            "char_budget": inj.char_budget,
            "min_shared": inj.min_shared,
            "min_ratio": inj.min_ratio,
            "min_score": inj.min_score,
            "pii_guard": inj.pii_guard,
        },
        "neural_recall_active": bool(neural_active),
        "inject_total": total,
        "inject_injected": injected,
        "inject_degraded": degraded,
        "last_inject": recent[-1] if recent else None,
        "route_cross_layer_conflicts": conflicts,
        "route_distribution": route_dist,
        "route_promotion_candidates": route_promotion,
        # 2026-09-15：把「裸数字 212」升级为可操作清单（哪几条 + canonical 层）。
        "route_promotion_list": route_promotion_list,
        "route_promotion_note": (
            "canonical 层为 L2/L3 的事实清单（keeper 视角）。⚠️ keeper 无权读 L2/L3 "
            "原生库，故 route_cross_layer_conflicts 结构上恒空——它只在同一 fact 被以"
            "不同 scope 重复登记时才非空，**不是**跨系统去重检测器。"),
        # inject_total 恒为 0 属 silent 模式的**预期配置**（默认不注册 SessionStart/
        # UserPromptSubmit 钩子，注入改由 MEMORY.md 自提醒替代），不是故障。
        "inject_note": (
            "silent 模式（默认）不注册 SessionStart/UserPromptSubmit 钩子，故 "
            "inject_total=0 为**预期配置**而非故障；如需预注入请改用 install_hooks.py "
            "的 active 模式或开启 inject_enabled"),
    }


def emit_inject_record(log_path, res_dict, session_id=""):
    """把 PreInjector 的 to_dict 结果落注入日志（供钩子调用）。"""
    if not log_path:
        return
    rec = dict(res_dict)
    rec["ts"] = _now_iso()
    rec["session"] = session_id
    InjectLog(log_path).append(rec)
