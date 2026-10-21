# Auto-extracted submodule: _quarantine
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def quarantine_dir(root: str) -> str:
    """ P2 · 敏感隔离区：命中敏感模式但不宜静默丢弃的候选暂存于此待人工复审。
    与 memories/ 平级，物理分离确保隔离记忆不被正常 recall/reflect 触达。"""
    return os.path.join(root, "quarantine")

def _corrupt_dir_for(fpath: str) -> str:
    """O4 · 损坏记忆隔离区：与损坏文件**同级**的 corrupt/ 子目录
    （memories/corrupt 或 memories/archive/corrupt），避免与敏感隔离区 quarantine/ 混淆。"""
    return os.path.join(os.path.dirname(fpath), "corrupt")

def _quarantine_corrupt_file(fpath: str) -> bool:
    """O4 ：把损坏的记忆文件移入同级 corrupt/ 隔离区，保留原文可恢复，而非静默丢弃。
    返回是否成功移动；任何异常（如只读存储、移动失败）返回 False，调用方退化为跳过（绝不崩溃）。"""
    try:
        d = os.path.join(os.path.dirname(fpath), "corrupt")
        dst = os.path.join(d, os.path.basename(fpath))
        if os.path.abspath(fpath) == os.path.abspath(dst):
            return False
        os.makedirs(d, exist_ok=True)
        shutil.move(fpath, dst)
        return True
    except Exception:
        return False

def _redact_sensitive(text):
    """把命中的敏感片段替换为 ***（用于 review_quarantine 放行时脱敏）。"""
    if not text:
        return text
    for rx, _ in _SENSITIVE_PATTERNS:
        text = rx.sub("***", text)
    return text

def _quarantine_candidate(root, category, summary, tags, body, hits,
                          scope=None, project="", tier="working", importance=None):
    """把命中敏感的候选写入 quarantine/ 待复审。返回 qid（LRN-日期-序号）。
    物理与 active 库隔离，正常 recall/reflect 不触达；review_quarantine 可放行/清除。
    纯加性：完全不影响正常 deposit 路径（仅 sensitive_action='quarantine' 时走入）。
    （at-rest 加密能力已于 2026-09-15 移除：隔离文件与活跃库一致，一律明文落盘。）"""
    os.makedirs(quarantine_dir(root), exist_ok=True)
    data = load_index(root)
    qid = gen_id(root, data, scan_dir=True)
    rec = {
        "id": qid, "category": category, "summary": summary, "tags": tags or [],
        "body": body, "scope": scope, "project": project, "tier": tier,
        "importance": importance, "status": "quarantined",
        "hits": [list(h) for h in hits], "created_at": today(),
        "reviewed": False,
    }
    qpath = os.path.join(quarantine_dir(root), qid + ".json")
    tmp = qpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    os.replace(tmp, qpath)
    return qid

def list_quarantine(root):
    """列出 quarantine/ 内待复审候选（status=quarantined）。返回 [rec...]（含 qid）。"""
    qd = quarantine_dir(root)
    if not os.path.isdir(qd):
        return []
    out = []
    for fn in sorted(os.listdir(qd)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(qd, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        out.append(rec)
    return out

def review_quarantine(root, qid, action="release", redact=True, llm=None):
    """复审隔离候选：
    - action="release"：脱敏(redact=True 时替换敏感片段)后正式 deposit 入 active 库；
    返回 {action, id}（deposit 后的记忆 id）。
    - action="purge"：直接删除隔离文件（永不入活跃库）。
    - action="keep"：标记已复审、保留在隔离区（不写库、不删）。
    纯加性：不影响正常 deposit/recall。
    （at-rest 加密能力已于 2026-09-15 移除，本路径一律明文读写。）"""
    qd = quarantine_dir(root)
    qpath = os.path.join(qd, qid + ".json")
    if not os.path.exists(qpath):
        raise FileNotFoundError("隔离候选不存在: %s" % qid)
    with open(qpath, encoding="utf-8") as f:
        rec = json.load(f)
    if action == "purge":
        os.remove(qpath)
        return {"action": "purge", "qid": qid}
    if action == "keep":
        rec["reviewed"] = True
        tmp = qpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmp, qpath)
        return {"action": "keep", "qid": qid}
        # release
    summary = _redact_sensitive(rec.get("summary", "")) if redact else rec.get("summary", "")
    body = _redact_sensitive(rec.get("body", "")) if redact else rec.get("body", "")
    new_id = memory_ops.deposit(root, rec.get("category", "best_practice"),
                    summary, rec.get("tags", []) or ["auto"], body,
                    tier=rec.get("tier", "working"),
                    importance=rec.get("importance"),
                    scope=rec.get("scope"), project=rec.get("project", ""),
                    recorded_by="agent", auto_sourced=True)
    # deposit 返回 dict（quarantine 结果）或 str（id）——统一取 id
    if isinstance(new_id, dict):
        # 极端：放行后仍命中敏感（如教学句）→ 仍在隔离；返回原 qid 提示
        if new_id.get("quarantined"):
            return {"action": "release_blocked", "qid": qid,
                    "reason": "release 后仍命中敏感，保留隔离", "hits": new_id.get("hits")}
        new_id = new_id.get("id")
    os.remove(qpath)  # 放行成功：清除隔离副本
    return {"action": "release", "qid": qid, "id": new_id}

