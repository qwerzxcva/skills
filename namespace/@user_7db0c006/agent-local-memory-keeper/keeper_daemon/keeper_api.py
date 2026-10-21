# -*- coding: utf-8 -*-
"""keeper_api.py — 记忆系统稳定 Python API

给外部 agent / 脚本 / 自动化提供统一编程入口：
- 召回 / 写入优先经 daemon（毫秒级、复用常驻模型），daemon 不可用时
自动回退「进程内直调 memory_ops」（可靠兜底，行为一致）；
- 时间线 / 审计等只读能力直调 memory_ops（无 daemon 端点，天然快）。

用法：
from keeper_api import api_recall, api_deposit, api_timeline, api_audit
rows = api_recall("投资 仓位")
mid  = api_deposit(summary="记一下…", category="note")

维护纪律：本模块是**门面**，不实现业务逻辑；一切委托 daemon 或 memory_ops。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # skill 根
_SCRIPTS = os.path.join(_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

    # ── 延迟导入（首次调用才加载，避免 import 即加载 182MB 模型）────────────
_mops = None
_client = None


def _mo():
    global _mops
    if _mops is None:
        import memory_ops as _mops
    return _mops


def _cl():
    global _client
    if _client is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "keeper_recall_client", os.path.join(_HERE, "keeper_recall_client.py"))
        _client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_client)
    return _client


def api_recall(query=None, root=None, top_n=None, semantic_gate=None,
               include_auto=False, max_tokens=None, **kw):
    """语义召回。优先 daemon（ms 级）；daemon 不可用回退进程内直调。

    返回 list[dict]（条目含 summary/body/score/why 等字段）；daemon 兜底
    失败时返回 []（与 skill 内部 skip 语义一致，绝不抛异常阻塞调用方）。
    """
    if root is None:  # daemon 只服务默认 root → 非默认 root 直接直调
        try:
            raw = _cl().recall_proxy(query=query, top_n=top_n or 10,
                                     include_auto=include_auto,
                                     semantic_gate=semantic_gate)
            import json
            obj = json.loads(raw)
            if obj.get("ok") is True and obj.get("entries"):
                return obj["entries"]
        except Exception:
            pass
    try:
        return _mo().recall(root or _mo()._default_root(),
                            query=query, include_auto=include_auto,
                            semantic_gate=semantic_gate, max_tokens=max_tokens, **kw)
    except Exception:
        return []


def api_deposit(summary, category="note", tags="", body="", scope="universal",
                project="", recorded_by="agent", root=None, **kw):
    """写入记忆。优先 daemon /deposit（免冷启）；daemon 不可用回退进程内。

    返回 (ok, mid_or_error)。"""
    if root is None:
        try:
            return _cl().deposit_proxy(category=category, summary=summary,
                                       tags=tags, body=body, scope=scope,
                                       project=project, recorded_by=recorded_by)
        except Exception:
            pass
    try:
        mid = _mo().deposit(root or _mo()._default_root(), category or "note",
                            summary, tags, body, scope=scope, project=project,
                            recorded_by=recorded_by, **kw)
        return True, mid
    except Exception as e:
        return False, str(e)[:200]


def api_timeline(root=None, mid=None, query=None, days=None, limit=20):
    """记忆时间线回放（只读，直调）。"""
    try:
        return _mo().timeline(root or _mo()._default_root(), mid=mid,
                              query=query, days=days, limit=limit)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def api_audit(root=None, n=20, op_filter=None):
    """变更审计日志尾部（只读，直调）。"""
    try:
        return _mo()._audit_log_tail(root or _mo()._default_root(),
                                     n=n, op_filter=op_filter)
    except Exception:
        return []


def api_pending(root=None, suggest=True):
    """数据质量队列（只读，直调）。"""
    try:
        return _mo().reclassify_pending(root or _mo()._default_root(),
                                        suggest=suggest)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


__all__ = ["api_recall", "api_deposit", "api_timeline", "api_audit", "api_pending"]
