# Auto-extracted submodule: _rerank
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_load_recall_config, _root_key, json/os, etc.) resolve through the
# injected namespace; do NOT re-define them here.
#
# ── 5.0 / B1 cross-encoder 重排（2026-09-16 新增）───────────────────────────
# 目的：补上「RRF 融合后仍按弱信号排序」的质量缺口——RRF 只用名次，看不出
# query 与候选的**真实语义匹配强度**；cross-encoder 直接对 (query, doc) 打分，
# 是检索链上质量增益最大的单点（也是本仓外调研中唯一被反复验证有效的新技术）。
#
# 🔴 但必须诚实标注成本（本机 CPU，**两轮实测**，2026-09-16）：
#   · 模型体积：BAAI/bge-reranker-base = 1.04GB（现有嵌入模型 bge-small-zh 仅 90MB，
#     即 11 倍）；jina-reranker-v2-base-multilingual = 1.11GB。
#   · 推理延迟：成本主项是 **候选文档总字符数 ≈ 1.1 ms/字符**（**不是条数**）。
#     用**真实记忆文本**实测（`_d5_rerank_len_scaling.py`）：
#       同一批 20 条候选，改截断长度 → 100 字 2.5s / 200 字 4.5s / 400 字 7.8s /
#       800 字 14.8s / 1200 字 15.1s（800 字后趋平 = 触到 512 token 上限）
#       固定 1200 字，改条数 → 5 条 3.8s / 10 条 7.4s / 20 条 14.8s / 40 条 26.7s
#     76 条真实 query 的开/关消融实测：**p50 11.65s / p95 14.60s**（OFF 轮 0.31s）。
#   · 🔴 更正：本文件早先写的「top-20 = 562ms/次」是**用 30 字合成短文本**测的，
#     **低估约 20 倍**（30 字 596ms → 1.0ms/字符，与真实文本口径一致，可见是长度差而非缺陷）。
#     CHANGELOG / FEATURES.md / RRF_DEFAULTS 处的同款数字均已更正。
#   · 叠加效应：B2 修好缓存后 recall p95 = 352ms；再叠 12s → 等于把 B2 的性能收益彻底抹掉。
#   · 下载还有坑：HF 的 Xet/CAS 通道在国内直连返回 401，必须
#     `HF_HUB_DISABLE_XET=1` + `HF_ENDPOINT=https://hf-mirror.com` 才下得下来。
#
# 🔴 质量 × 成本网格实测（76 条真实 query，`_d6_grid_ablation.py`，报告第十三节）：
#                          hit@1   hit@3   MRR    p50 延迟
#     不开重排               0.566   0.789  0.686    0.30s
#     top=5  × 200 字  →     0.803   0.842  0.829    1.83s   ← **本默认**
#     top=5  × 1200 字 →     0.816   0.855  0.837    4.08s
#     top=20 × 200 字  →     0.816   0.855  0.838    3.95s
#     top=20 × 1200 字 →     0.829   0.868  0.849   11.65s
#   结论：质量收益**真实且零倒退**（最多 24 升 0 降），但**原默认档（top20/1200 字）
#   要 12~15s/次**，不可作默认 ⇒ ① `rerank_enabled` **仍默认关**（1.04GB 模型需用户知情下载）；
#   ② 但 `rerank_top`/`rerank_doc_chars` 的默认值改成**便宜档 5/200**（拿到 90% 质量增益、1.8s），
#   让「开了就能用」；要满配自己调大（最后 2.6 个点要付 6.4 倍成本）。
#   ⚠️ 成本只与 top × 截断有关，**与库规模无关** ⇒ 库越大，收益越大而成本不变。
#   ⚠️ 5 条 query 在所有档位都未命中（金标根本没进候选集）—— 属**召回层**缺口，重排管不到。
#
# 设计原则（三条，保证「开着不会更差」）：
#   ① 只调 RRF top-N 内部顺序，N 之外候选的分数与相对次序完全不动；
#   ② 融合采用「区间映射」而非直接替换——rerank 分归一化后映射回 top-N 原有的
#      RRF 分区间，故不会与 N 之外候选的可比性断裂；
#   ③ 任何异常（模型缺失/下载失败/推理报错/条数不匹配）一律静默回退原排序，
#      绝不让重排把召回弄挂——失败只是「没提升」，不是「变差」。

RERANK_DEFAULT_MODEL = "BAAI/bge-reranker-base"
RERANK_DEFAULT_TOP = 5            # 与 RRF_DEFAULTS["rerank_top"] 同源（测试锁一致）
RERANK_DEFAULT_DOC_CHARS = 200    # 与 RRF_DEFAULTS["rerank_doc_chars"] 同源
RERANK_DEFAULT_WEIGHT = 0.6

_RERANK_ENC = {}      # model_name → encoder 或 None（加载失败缓存在 _RERANK_FAILED）
_RERANK_FAILED = set()


def _rerank_available(model_name=None):
    """重排模型是否可用（不抛异常；供 doctor/自检展示）。"""
    return _rerank_encoder(model_name or RERANK_DEFAULT_MODEL) is not None


def _rerank_encoder(model_name):
    """惰性加载 fastembed cross-encoder。失败返回 None 并记入失败集（不反复重试）。"""
    if not model_name:
        return None
    if model_name in _RERANK_FAILED:
        return None
    if model_name in _RERANK_ENC:
        return _RERANK_ENC.get(model_name)
    enc = None
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        enc = TextCrossEncoder(model_name=model_name)
    except Exception:
        _RERANK_FAILED.add(model_name)
        enc = None
    _RERANK_ENC[model_name] = enc
    return enc


def _rerank_doc_text(item, limit=RERANK_DEFAULT_DOC_CHARS):
    """把一条候选拼成重排用的文档文本（摘要 + 正文截断）。

    `limit` **是成本主项**（≈1.1 ms/字符，见文件头），调用方从配置 `rerank_doc_chars` 传入。
    """
    if not isinstance(item, dict):
        return ""
    s = item.get("summary") or ""
    b = item.get("body") or ""
    t = ("%s\n%s" % (s, b)).strip()
    return (t or s)[:limit]


def _rerank_apply(root, query, out, ranked, cfg=None):
    """对 RRF top-N 候选做 cross-encoder 重排，**就地改写并返回** `ranked`。

    返回的 `ranked` 在「未启用 / 不可用 / 任何异常」时与入参**完全一致**（同一对象）。
    调用方无需判断是否生效——顺序已体现在 ranked 里。
    """
    if not query or not out or not ranked:
        return ranked
    try:
        if cfg is None:
            cfg = _load_recall_config(root)
        if not cfg.get("rerank_enabled"):
            return ranked
        model_name = str(cfg.get("rerank_model") or RERANK_DEFAULT_MODEL)
        top_n = max(1, int(cfg.get("rerank_top") or RERANK_DEFAULT_TOP))
        weight = float(cfg.get("rerank_weight", RERANK_DEFAULT_WEIGHT))
        # 候选文档截断（成本主项，≈1.1ms/字符）：默认取 RRF_DEFAULTS["rerank_doc_chars"]（唯一来源）
        doc_chars = max(64, int(cfg.get("rerank_doc_chars") or RERANK_DEFAULT_DOC_CHARS))
        if weight <= 0:
            return ranked
        enc = _rerank_encoder(model_name)
        if enc is None:
            return ranked

        cand = sorted(out, key=lambda e: ranked.get(e.get("id"), 0.0), reverse=True)[:top_n]
        cand = [e for e in cand if e.get("id")]
        if len(cand) < 2:
            return ranked
        docs = [_rerank_doc_text(e, doc_chars) for e in cand]
        scores = [float(x) for x in enc.rerank(query, docs)]
        if len(scores) != len(cand):
            return ranked

        # rerank 分归一化（min-max；全等时视为同分）
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        rr = [(s - lo) / span for s in scores]

        # 原 RRF 分区间（只在这段区间内重排，保持与 N 之外候选的可比性）
        rvals = [ranked.get(e.get("id"), 0.0) for e in cand]
        r_lo, r_hi = min(rvals), max(rvals)
        r_span = (r_hi - r_lo) or 1.0

        for e, _rr in zip(cand, rr):
            _orig = ranked.get(e.get("id"), 0.0)
            _norm = (_orig - r_lo) / r_span
            _blend = (1.0 - weight) * _norm + weight * _rr
            ranked[e.get("id")] = r_lo + _blend * r_span
        return ranked
    except Exception:
        return ranked
