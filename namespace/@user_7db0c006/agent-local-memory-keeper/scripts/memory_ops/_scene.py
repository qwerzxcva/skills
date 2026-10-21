# Auto-extracted submodule: _scene
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _normalize_scene(s):
    """归一化 scene 输入：接受别名/小写/中文，返回 SCENE_CANON 之一。

    注意：未知输入**不**静默归并到 general（那会掩盖拼写错误/误用，导致
    recall 按 scene 过滤时悄悄拿到错误结果）。未知输入原样返回，交由调用方
    （recall/recall_v30/deposit）的 `if scene not in SCENE_CANON: raise` 校验报错。
    """
    if s is None:
        return None
    s2 = str(s).strip().lower()
    if not s2:
        return None
    if s2 in SCENE_CANON:
        return s2
    for canon, aliases in SCENE_ALIASES.items():
        for a in aliases:
            if s2 == a or s2 in (a.lower() for a in aliases):
                return canon
    return s2

def _classify_scene(text, tags=None, return_conf=False):
    """：基于文本+tags 关键词匹配，初判 scene 轴。

    返回 (scene, confidence, hit_keywords)：
    - 多场景命中时取关键词命中数最多者（平局取 SCENE_CANON 索引靠前者）；
    - 无任何命中 → ("general", 0.3, []) 兜底；
    - 与 taxonomy_route（topic 轴）正交，可独立/并行使用。
    """
    blob = " ".join([
        str(text or ""),
        " ".join(str(t) for t in (tags or []) if t)
    ]).lower()
    if not blob.strip():
        return ("general", 0.3, []) if not return_conf else ("general", 0.3, [])
    hits = {canon: 0 for canon in SCENE_CANON}
    for canon, aliases in SCENE_ALIASES.items():
        for a in aliases:
            al = a.lower()
            if al and al in blob:
                hits[canon] += 1
                # 平局取 SCENE_CANON 索引靠前者（即更基础场景）
    best = max(hits.items(), key=lambda kv: (kv[1], -SCENE_CANON.index(kv[0])))
    if best[1] == 0:
        return ("general", 0.3, []) if not return_conf else ("general", 0.3, [])
    conf = min(1.0, 0.5 + best[1] * 0.15)
    hit_kws = [a for canon, _ in [best] for a in SCENE_ALIASES.get(canon, []) if a.lower() in blob][:4]
    return (best[0], round(conf, 3), hit_kws) if return_conf else (best[0], conf, hit_kws)

def _classify_scene_llm(root, text, tags=None, chat=None):
    """ · 在线 LLM 场景分类（deposit/reflect 复用）。返回 (scene, confidence, reason) 或 None。
    system 枚举 SCENE_CANON + 要求输出 confidence 与简短 reason，便于 reflect 重分类判断高置信改写。
    解析失败/非法 scene 一律返 None（交给规则兜底）。"""
    if chat is None:
        return None
    try:
        canon_str = " / ".join(SCENE_CANON)
        system = ("你是记忆场景分类助手。把一条经验归类到唯一「使用场景」：%s。"
                  "注意：domain=讲的是什么，scene=什么时候/什么场景下用（两轴正交）。"
                  "软件场景如 onboarding/setup/release/incident/debugging/research/maintenance/learning/conversation；"
                  "投资场景一律带 inv: 前缀，如 inv:backtest(回测)/inv:rebalance(调仓)/inv:premarket(盘前)/inv:intraday(盘中)/inv:postmarket(复盘)。"
                  "只输出 JSON：{\"scene\":\"<之一>\",\"confidence\":0.0~1.0,\"reason\":\"<一句话>\"}。") % canon_str
        user = "摘要/文本：%s\n标签：%s" % ((text or "")[:800], " ".join(tags or []))
        out = chat(system, user, temperature=0.0, max_tokens=200)
        obj = _parse_llm_json_obj(out)
        s = _normalize_scene(obj.get("scene", ""))
        if s not in SCENE_CANON:
            return None
        conf = float(obj.get("confidence", 0.7))
        return s, conf, (obj.get("reason") or "")[:80]
    except Exception:
        return None

def classify_scene_v30(root, text, tags=None, llm=None):
    """ · LLM 优先的场景分类入口（修「场景分类脆弱/误判」问题①）。
    返回 (scene, confidence, via, reasons)。via ∈ {llm, rule}。
    - llm 可用 → 调在线 LLM（带 confidence）；conf≥0.5 采用，否则回退规则关键词。
    - 无 LLM → 走 _classify_scene 关键词兜底（与旧行为一致，但带 confidence）。
    纯加性：旧 _classify_scene 不动；本函数是其 LLM 增强版，deposit 调用。"""
    chat, _ = _resolve_llm(root, llm)
    if chat is not None:
        res = _classify_scene_llm(root, text, tags, chat)
        if res:
            s, conf, reason = res
            if conf >= 0.5:
                return s, conf, "llm", ["llm:%s" % reason]
                # LLM 低置信 → 回退规则（不丢信息）
    s, conf, hit_kws = _classify_scene(text, tags, return_conf=True)
    return s, conf, "rule", ["rule:%s" % (",".join(hit_kws) or "none")]

