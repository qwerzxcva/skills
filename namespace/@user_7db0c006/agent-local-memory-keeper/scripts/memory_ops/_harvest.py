# Auto-extracted submodule: _harvest
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

import hashlib  # v4.6.13：WB 来源 provenance_key 计算（注入命名空间亦含，显式导入更稳健）

def _harvest_llm(root, src_text, mode, cfg, max_items=10):
    """调用 LLM 抽取学习点。返回 {"candidates":[...], "corrections":[...]}。"""
    import urllib.request
    import urllib.error
    backend = cfg.get("backend", "ollama")
    base_url = cfg.get("base_url") or ("http://localhost:11434/v1" if backend == "ollama" else "")
    model = cfg.get("model") or ("qwen2.5:7b" if backend == "ollama" else "gpt-4o-mini")
    api_key = os.environ.get(cfg.get("api_key_env", ""), "") if cfg.get("api_key_env") else ""
    if mode == "self_learn":
        system = ("你是记忆整理助手。下面是某 Agent 长期记忆的【正文摘要】(已截断，不含私密)。"
                  "请跨记忆发现深层规律，仅输出 JSON 数组，每条形如："
                  "{\"kind\":\"contradiction|synthesize|extract\","
                  "\"text\":\"<发现的中文描述>\","
                  "\"contradicts\":\"<与某条记忆矛盾的正文片段,用于定位,可空>\","
                  "\"new_category\":\"<best_practice|architecture_decision|correction|principle>\","
                  "\"new_summary\":\"<可沉淀的新洞察摘要>\","
                  "\"new_tags\":[\"<tag>\"],\"new_body\":\"<新洞察正文>\"}。"
                  "contradiction=两条记忆正文互相矛盾; synthesize=多条讲同一事可合成更高层原则;"
                  "extract=某条正文里藏着可独立成条的经验。不要编造 id。只输出合法 JSON 数组。")
    else:
        system = ("你是记忆整理助手。下面是一段 Agent 的工作会话文本。请抽取其中【值得长期记住】的"
                  "经验点，仅输出 JSON 数组，每条形如："
                  "{\"category\":\"<best_practice|architecture_decision|correction|principle>\","
                  "\"summary\":\"<一句话摘要>\",\"tags\":[\"<tag>\"],\"body\":\"<经验正文>\","
                  "\"type\":\"new|correction\"}。"
                  "只抽真正可复用的；丢弃闲聊/临时状态。不要编造 id。只输出合法 JSON 数组。")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    user = ("模式: %s\n输入内容:\n%s\n请按上述格式输出最多 %d 条 JSON 数组:"
            % (mode, src_text[:6000], max_items))
    payload = {"model": model, "temperature": float(cfg.get("temperature", 0.2)),
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}], "stream": False}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    arr = _parse_llm_json_array(content)
    candidates, corrections = [], []
    for it in arr or []:
        if not isinstance(it, dict):
            continue
        if mode == "self_learn":
            if it.get("kind") in ("contradiction", "synthesize", "extract"):
                corrections.append({
                    "kind": it.get("kind"), "text": it.get("text", ""),
                    "contradicts": it.get("contradicts", ""),
                    "category": it.get("new_category", "best_practice"),
                    "summary": it.get("new_summary", ""),
                    "tags": it.get("new_tags", []) or ["auto"],
                    "body": it.get("new_body", ""),
                })
        else:
            candidates.append({
                "category": it.get("category", "best_practice"),
                "summary": it.get("summary", ""),
                "tags": it.get("tags", []) or ["auto"],
                "body": it.get("body", ""),
            })
    return {"candidates": candidates, "corrections": corrections}

def _harvest_rule(src_text, mode, bodies=None):
    """规则兜底抽取（无 LLM 时）：关键词/模式匹配。返回 (candidates, corrections)。"""
    import re
    candidates, corrections = [], []
    if mode == "self_learn":
        # 检测 body 高度重叠（疑似重复/可合并）→ 提 correction 建议
        if bodies:
            seen = []
            for b in bodies:
                bid, bbody = b.get("id"), (b.get("body") or "").strip()
                if len(bbody) < 20:
                    continue
                for ob in seen:
                    if _similarity(bbody, ob.get("body", "")) >= 0.5:
                        corrections.append({
                            "kind": "synthesize",
                            "text": "两条记忆正文高度重叠，可合并",
                            "contradicts": bbody[:80],
                            "category": "best_practice",
                            "summary": "合并重复记忆: %s" % b.get("summary", ""),
                            "tags": b.get("tags", []) or ["auto"],
                            "body": bbody[:200],
                        })
                        break
                seen.append({"id": bid, "body": bbody})
        return candidates, corrections
        # 会话模式：按句切分，关键词命中型
    for sent in re.split(r"[。\n；;]", src_text):
        s = sent.strip()
        if len(s) < 8:
            continue
        low = s
        if ("原来" in low) and any(k in low for k in ("错", "不对", "误", "应该", "改成", "其实", "不是")):
            candidates.append({"category": "correction", "summary": s[:60], "tags": ["auto"], "body": s})
        elif any(k in low for k in ("决定", "采用", "方案是", "统一用", "选定")):
            candidates.append({"category": "architecture_decision", "summary": s[:60], "tags": ["auto"], "body": s})
        elif any(k in low for k in ("以后", "记住", "下次", "约定", "统一", "务必", "总是")):
            # H9 修复：负向黑名单——含日常动作词（关灯/吃饭/睡觉…）的句子非知识，
            # 跳过不捕，避免「下次记得关灯」被当长期最佳实践。同时要求与知识/命令类
            # 词共现（双词门控），纯触发词单独出现不捕。
            if any(b in low for b in _BP_NEG_BLACKLIST):
                continue
            if not any(k2 in low for k2 in _BP_KNOWLEDGE_WORDS):
                continue
            candidates.append({"category": "best_practice", "summary": s[:60], "tags": ["auto"], "body": s})
    return candidates, corrections

def _find_similar_mem(root, phrase, bodies):
    """在现有记忆 body 中找与 phrase 最相似的 active 记忆 id（用于 self_learn 矛盾定位）。"""
    if not phrase or not bodies:
        return None
    best, best_id = 0.0, None
    for b in bodies:
        sc = _similarity(phrase, b.get("body", "") or b.get("summary", ""))
        if sc > best:
            best, best_id = sc, b.get("id")
    return best_id if best >= 0.3 else None

def _workbuddy_ws_memory_dir():
    """自动发现当前工作区的 .workbuddy/memory 目录（向上回溯 cwd）。"""
    env = os.environ.get("WORKBUDDY_WORKSPACE")
    if env and os.path.isdir(os.path.join(env, ".workbuddy", "memory")):
        return os.path.join(env, ".workbuddy", "memory")
    cur = os.getcwd()
    while True:
        cand = os.path.join(cur, ".workbuddy", "memory")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None

def _split_md_chunks(txt):
    """按空行 / Markdown 标题切片为知识块。"""
    parts = re.split(r"\n\s*\n|^#{1,6}\s", txt or "", flags=re.M)
    return [p.strip() for p in parts if p and p.strip()]

    # ：keeper→WB 蒸馏哨兵（distill-to-wb 写，harvest 读时跳过，防回声循环）
KEEPER_DISTILLED_SENTINEL = "<!-- keeper-distilled:"

def _collect_workbuddy_memory(wb_dir=None, max_bodies=80):
    """采集 WorkBuddy 原生记忆为 body 列表（不打工具自身库，只读对方）：
    - 用户级长期记忆 ~/.workbuddy/MEMORY.md（curated，优先级最高）；
    - 工作区 .workbuddy/memory/*.md（每日日志 + MEMORY.md）；
    - 云端缓存 ~/.workbuddy/memory/*.md（可选，通常只读）。
    返回 [{"id","category":"workbuddy_memory","summary","body","source"}]。
    v4.6.13：含 keeper-distilled 哨兵的行（keeper 蒸馏回流到 WB 的内容）直接跳过，
    避免「keeper→WB→又被 harvest 回 keeper」的回声循环（只抄不学）。
    """
    bodies = []
    files = []
    user_md = os.path.expanduser("~/.workbuddy/MEMORY.md")
    if os.path.exists(user_md):
        files.append((user_md, "user_memory"))
    ws = wb_dir or _workbuddy_ws_memory_dir()
    if ws and os.path.isdir(ws):
        for fn in sorted(os.listdir(ws)):
            if fn.endswith(".md"):
                files.append((os.path.join(ws, fn), "workspace_memory"))
    cloud = os.path.expanduser("~/.workbuddy/memory")
    if os.path.isdir(cloud):
        for fn in sorted(os.listdir(cloud)):
            if fn.endswith(".md"):
                files.append((os.path.join(cloud, fn), "cloud_memory"))
    for path, kind in files:
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for idx, ch in enumerate(_split_md_chunks(txt)):
            if len(ch) < 20:
                continue
                # 反回声：keeper 蒸馏回流的内容不回采
            if KEEPER_DISTILLED_SENTINEL in ch:
                continue
            bodies.append({
                "id": "wb:%s:%d" % (os.path.basename(path), idx),
                "category": "workbuddy_memory",
                "summary": ch[:60],
                "body": ch[:600],
                "source": kind,
            })
            if len(bodies) >= max_bodies:
                return bodies
    return bodies

def harvest(root, text=None, session_file=None, self_learn=False,
            max_items=10, llm=None, with_workbuddy=True, wb_dir=None,
            dry_run=False, from_conversations=False):
    """自主沉积入口。返回 {ok, mode, n_deposited, deposited, n_corrections, corrections, llm_used, n_wb_deposited, wb_deposited}。
    - text/session_file：从会话文本抽学习点；self_learn：读现有记忆 body 做跨记忆深层学习。
    - 抽到的候选以 seed 态(auto_sourced)存入；self_learn 的矛盾发现落建议(不自动改写)。
    - **与 WorkBuddy 原生记忆打通**：self_learn 时默认 `with_workbuddy=True`，自动读取
    ~/.workbuddy/MEMORY.md + 工作区 .workbuddy/memory/*.md（可被 --no-workbuddy 关闭、
    --workbuddy-memory <dir> 指定），把「库里没有且像长期知识」的条目自沉淀为 seed，
    并纳入重复/矛盾检测——即工具自己调取对方记忆、自己学、自己沉淀。"""
    cfg = _load_llm_config(root)
    use_llm = (llm is True) or (llm is None and bool(cfg.get("enabled")))
    bodies = None
    wb_bodies = None
    if self_learn:
        mems = _all_mems(root)
        active = [m for m in mems.values() if m.get("status") == "active"]
        bodies = [{"id": m["id"], "category": m.get("category", ""),
                   "summary": m.get("summary", ""),
                   "body": (m.get("body", "") or "")[:600]} for m in active]
        if with_workbuddy:
            try:
                wb_bodies = _collect_workbuddy_memory(wb_dir=wb_dir)
            except Exception:
                wb_bodies = []
            if wb_bodies:
                bodies = bodies + wb_bodies
        src_text = json.dumps(bodies, ensure_ascii=False)
        mode = "self_learn"
    else:
        if session_file:
            try:
                with open(session_file, encoding="utf-8") as f:
                    src_text = f.read()
            except Exception:
                src_text = ""
        else:
            src_text = text or ""
        mode = "session"
    if not src_text or not src_text.strip():
        return {"ok": True, "mode": mode, "n_deposited": 0, "deposited": [],
                "n_corrections": 0, "corrections": [], "llm_used": use_llm,
                "note": "空输入"}
    candidates, corrections = [], []
    if use_llm:
        try:
            r = _harvest_llm(root, src_text, mode, cfg, max_items=max_items)
            candidates, corrections = r.get("candidates", []), r.get("corrections", [])
        except Exception:
            candidates, corrections = _harvest_rule(src_text, mode, bodies)
    else:
        candidates, corrections = _harvest_rule(src_text, mode, bodies)
    deposited = []
    # P0①：会话摄入（来自 WB 历史会话 conversation_search）幂等去重——
    # 对齐 WB 分支的 provenance_key 机制，避免重复喂同一段历史会话造成重复沉积/回声。
    _ingest_prov = "wb_session" if from_conversations else None
    _existing_ingest_keys = set()
    if from_conversations:
        try:
            for _m in _all_mems(root).values():
                _k = _m.get("provenance_key")
                if _k:
                    _existing_ingest_keys.add(_k)
        except Exception:
            _existing_ingest_keys = set()
    for c in candidates[:max_items]:
        if dry_run:
            deposited.append({"id": "<dry-run>", "summary": c.get("summary", ""),
                              "source": _ingest_prov or "session"})
            continue
        _tags = c.get("tags", []) or ["auto"]
        _prov_key = None
        if _ingest_prov:
            if "wb_session" not in _tags:
                _tags = _tags + ["wb_session"]
            _prov_key = hashlib.sha1(
                ("%s\x00%s" % (_ingest_prov, (c.get("body", "") or c.get("summary", ""))))\
                .encode("utf-8")).hexdigest()[:16]
            if _prov_key in _existing_ingest_keys:
                continue
        cid = deposit(root, c.get("category", "best_practice"),
                      c.get("summary", "") or "auto-harvest",
                      _tags, c.get("body", ""),
                      tier="seed", inferred=True, auto_sourced=True, recorded_by="agent",
                      provenance=_ingest_prov, provenance_key=_prov_key,
                      src_origin=_ingest_prov)
        if _prov_key:
            _existing_ingest_keys.add(_prov_key)
        deposited.append({"id": cid, "summary": c.get("summary", "")})
        # P0-1 修复：无 LLM / 无结构化候选（命中触发词）时，把实质文本逐句落为低置信 seed，
        # 避免 converse「对话内自主沉淀」等场景把用户显式给出的要点静默丢弃（此前 n_deposited=0）。
        # B1 优化：fallback 加「含触发词或知识关键词」门槛，避免"嗯/好的/明白了"等口水句污染 seed。
        # P0①：from_conversations 模式下 fallback 始终穷尽执行（不依赖主循环是否已有 deposit），
        # 确保同一段历史会话首次即存尽、二次跑因 provenance_key 幂等而 n_deposited=0（避免分两次存完）。
    if (not deposited or from_conversations) and mode == "session" and src_text.strip():
        import re as _re
        # 触发词词典：复用内置触发词典（覆盖知识/偏好/决策/修复/经验等高价值话题）
        try:
            import trigger_dict as _td
            _td_patterns = [(p.pattern if hasattr(p, "pattern") else p) for (p, *_rest) in _td._compiled()]
        except Exception:
            _td_patterns = []
            # 知识关键词集合（约定/规则/偏好/决策/原则...）
        _kb_kw = set(_KB_KEYWORDS)
        _n = 0
        for _sent in _re.split(r"[。\n；;]", src_text):
            _s = _sent.strip()
            if len(_s) < 12:
                continue
                # 门槛：句中至少含 1 个触发词或知识关键词，否则视为口水句丢弃
            _hit = any(k in _s for k in _kb_kw) or any(_re.search(pat, _s) for pat in _td_patterns)
            if not _hit:
                continue
            if dry_run:
                deposited.append({"id": "<dry-run>", "summary": _s[:80], "verbatim": True,
                                  "source": _ingest_prov or "session"})
            else:
                _ftags = ["auto", "harvest"]
                _fprov_key = None
                if _ingest_prov:
                    if "wb_session" not in _ftags:
                        _ftags = _ftags + ["wb_session"]
                    _fprov_key = hashlib.sha1(
                        ("%s\x00%s" % (_ingest_prov, _s)).encode("utf-8")).hexdigest()[:16]
                    if _fprov_key in _existing_ingest_keys:
                        continue
                _cid = deposit(root, "best_practice", _s[:80], _ftags, _s,
                              tier="seed", inferred=True, auto_sourced=True, recorded_by="agent",
                              provenance=_ingest_prov, provenance_key=_fprov_key,
                              src_origin=_ingest_prov)
                if _fprov_key:
                    _existing_ingest_keys.add(_fprov_key)
                deposited.append({"id": _cid, "summary": _s[:80], "verbatim": True})
            _n += 1
            if _n >= max_items:
                break
    corr_out = []
    if self_learn and corrections:
        for cor in corrections:
            target = _find_similar_mem(root, cor.get("contradicts", ""), bodies)
            corr_out.append({"kind": cor.get("kind"), "text": cor.get("text", ""),
                             "target_id": target, "status": "proposed",
                             "note": ("运行 deposit --corrects %s 以应用" % target) if target else "未定位到目标记忆"})
            # ── 打通沉淀：把 WorkBuddy 记忆里「库里没有、且像长期知识」的条目自沉淀为 seed ──
    n_wb_deposited = 0
    wb_deposited = []
    if self_learn and with_workbuddy and wb_bodies:
        own_bodies = [{"body": (m.get("body", "") or "")} for m in active]
        # ：幂等集合——已落盘的 WB 来源 provenance_key，避免重复沉淀与回声循环
        _existing_wb_keys = set()
        try:
            for _m in _all_mems(root).values():
                _k = _m.get("provenance_key")
                if _k:
                    _existing_wb_keys.add(_k)
        except Exception:
            _existing_wb_keys = set()
        for wb in wb_bodies:
            wbb = wb.get("body", "")
            if len(wbb) < 30:
                continue
                # 自身库已存在相似记忆 → 跳过（已在库里）
            if any(_similarity(wbb, ob.get("body", "")) >= 0.5 for ob in own_bodies):
                continue
                # 知识价值启发式：用户级长期记忆全收；工作区/云端仅收含「长期知识」关键词的
            is_user = wb.get("source") == "user_memory"
            has_kw = any(k in wbb for k in _KB_KEYWORDS)
            if not is_user and not has_kw:
                continue
            cat = "convention" if has_kw else "best_practice"
            # ：WB 来源幂等键（来源 + 内容 hash），同一 WB 记忆重复 harvest 不再造新副本
            _wb_key = hashlib.sha1(
                ("%s\x00%s" % (wb.get("source", "wb"), wbb)).encode("utf-8")).hexdigest()[:16]
            if _wb_key in _existing_wb_keys:
                continue
            if dry_run:
                wb_deposited.append({"id": "<dry-run>", "summary": wb.get("summary", ""),
                                     "source": wb.get("source")})
                n_wb_deposited += 1
                if n_wb_deposited >= max_items:
                    break
                continue
            cid = deposit(root, cat, (wb.get("summary", "") or wbb[:40])[:80],
                          ["workbuddy_memory", wb.get("source", "wb")], wbb,
                          tier="seed", inferred=True, auto_sourced=True,
                          recorded_by="workbuddy_sync",
                          provenance="workbuddy", provenance_key=_wb_key,
                          src_origin=wb.get("source", "wb"))
            _existing_wb_keys.add(_wb_key)
            wb_deposited.append({"id": cid, "summary": wb.get("summary", ""),
                                 "source": wb.get("source")})
            n_wb_deposited += 1
            if n_wb_deposited >= max_items:
                break
    return {"ok": True, "mode": mode, "n_deposited": len(deposited),
            "deposited": deposited, "n_corrections": len(corr_out),
            "corrections": corr_out, "llm_used": use_llm,
            "dry_run": dry_run,
            "n_wb_deposited": n_wb_deposited, "wb_deposited": wb_deposited}

def distill_to_wb(root, dry_run=True, max_items=20, min_importance=0.7,
                  min_confidence=0.7):
    """ · keeper→WorkBuddy 蒸馏回流（让两套系统真正互补而非镜像）。

    选取 keeper 库中「值得上升为身份级原则」的记忆（tier=curated 或 高重要度+高置信且
    非 WB 镜像、非自动生成、未被判错），以幂等哨兵 <!-- keeper-distilled:KEY --> 蒸馏
    追加到 ~/.workbuddy/MEMORY.md。WB 的 agent 身份卡因此越用越聪明（吸收 keeper 深度脑
    的高层原则），而 keeper 仍保有结构化/操作级知识——分工而非互抄。

    - 默认 dry_run（review）：只返回候选与预览，绝不写 WB 文件；需显式 --apply 才写。
    - 幂等：KEY 已存在于 WB MEMORY.md → 跳过（防重复蒸馏 / 回声）。
    - 绝不蒸馏 provenance=workbuddy 的记忆（那是 WB 自己的内容，回抄即镜像）。
    - fail-open：任何异常返回 skipped，绝不阻断。
    """
    out = {"ok": True, "dry_run": bool(dry_run), "candidates": [],
           "applied": 0, "skipped_existing": 0, "target": ""}
    try:
        wb_md = os.path.expanduser("~/.workbuddy/MEMORY.md")
        out["target"] = wb_md
        mems = _all_mems(root)
        cands = []
        for m in mems.values():
            if m.get("status") != "active":
                continue
            if m.get("erroneous"):
                continue
            if m.get("provenance") == "workbuddy":  # 不回抄 WB 自身内容
                continue
            _imp = float(m.get("importance") or 0.0)
            _conf = float(m.get("confidence") or 0.0)
            _curated = (m.get("tier") == "curated")
            if not (_curated or (_imp >= min_importance and _conf >= min_confidence
                                 and not m.get("auto_sourced"))):
                continue
            summary = (m.get("summary") or "").strip()
            body = (m.get("body") or "").strip().replace("\n", " ")
            if not summary:
                continue
            key = hashlib.sha1(("distill:%s" % summary).encode("utf-8")).hexdigest()[:12]
            cands.append({"id": m.get("id"), "key": key, "summary": summary,
                          "body": body[:200], "importance": _imp, "confidence": _conf,
                          "tier": m.get("tier"), "domain": m.get("domain")})
        cands.sort(key=lambda x: (x["tier"] == "curated", x["importance"], x["confidence"]),
                   reverse=True)
        cands = cands[:max_items]
        out["candidates"] = cands
        if dry_run:
            return out
            # --apply：幂等追加到 WB MEMORY.md
        existing = ""
        if os.path.exists(wb_md):
            try:
                existing = open(wb_md, encoding="utf-8").read()
            except Exception:
                existing = ""
        appended = []
        skipped = 0
        for c in cands:
            sentinel = "%s%s -->" % (KEEPER_DISTILLED_SENTINEL, c["key"])
            if sentinel in existing or sentinel in "\n".join(appended):
                skipped += 1
                continue
            line = ("- 🧪 keeper 蒸馏原则：%s —— %s %s%s -->"
                    % (c["summary"], c["body"],
                       KEEPER_DISTILLED_SENTINEL, c["key"]))
            appended.append(line)
        if not appended:
            out["skipped_existing"] = skipped
            out["applied"] = 0
            return out
        block = "\n\n## 🧪 Keeper 蒸馏原则（自动回流，勿手改哨兵行）\n" + "\n".join(appended) + "\n"
        new_text = existing.rstrip() + block if existing.strip() else block.lstrip()
        tmp = wb_md + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, wb_md)
        out["applied"] = len(appended)
        out["skipped_existing"] = skipped
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out


def memory_hook_listen(root, conv_text, llm=None, auto_settle=True,
                       immediate_max=3, deep_every=10):
    """ P1 · 被动监听 hook（修 H6：capture 从「需 agent 主动调」→「每轮自动」）。

    作用：agent 把本轮回合文本在**每轮结束**调用一次本函数（注册为 turn-end hook 即真·被动），
    函数自动完成「捕获→写前查重(已在 deposit)→周期性深层整理→沉淀」。agent 不再需要判断
    『该不该记』，漏调用=漏记的问题由此消解（只要 hook 注册了）。

    行为：
    - 每轮：轻量即时 harvest(conv_text) 进 seed；重复靠 deposit 写前查重兜住（幂等）。
    - 每 deep_every 轮：跑 harvest --self-learn（跨记忆自学习）+ 可选 settle_probe（沉淀终判）。
    - 纯加性：不改动 harvest/converse/reflect/deposit 任何语义；独立维护 listen_count 计数。
    返回轻量报告 dict。"""
    init_store(root)
    captured = 0
    if conv_text and str(conv_text).strip():
        try:
            r = harvest(root, text=str(conv_text), max_items=immediate_max, llm=llm)
            captured = r.get("n_deposited", 0)
        except Exception:
            captured = 0
            # 周期深层整理（复用 round_state 持久化，跨进程累加）
    st = _load_round_state(root)
    lc = int(st.get("listen_count", 0)) + 1
    st["listen_count"] = lc
    _save_round_state(root, st)
    deep = None
    consolidated = (lc % deep_every == 0)
    if consolidated:
        try:
            deep = harvest(root, self_learn=True, max_items=immediate_max,
                          with_workbuddy=True, llm=llm)
        except Exception:
            deep = None
        if auto_settle:
            try:
                settle_probe(root, llm=llm)
            except Exception:
                pass
    return {"ok": True, "hook": "listen", "round": lc, "captured": captured,
            "deep_consolidated": consolidated, "deep": deep}

def _parse_hhmm(at):
    """解析 HH:MM 为 (hh, mm) 整数；非法抛 ValueError。"""
    import re as _re
    m = _re.match(r"^(\d{1,2}):(\d{2})$", at)
    if not m:
        raise ValueError("--at 必须是 HH:MM 格式，收到: %s" % at)
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("--at 时刻非法: %s" % at)
    return hh, mm

def _stagger_hhmm(hh, mm, delta_h):
    """在 (hh, mm) 基础上加 delta_h 小时（可为小数，如 1.5），回绕到 0-23 返回 (nh, nm)。"""
    total = (hh + delta_h) % 24
    nh = int(total)
    frac = total - nh
    nm = mm + int(round(frac * 60))
    if nm >= 60:
        nh = (nh + 1) % 24
        nm -= 60
    return nh, nm

def schedule_self_heal(root, at="03:00", with_rebuild=False, cron=False):
    """生成「低频自愈调度」自动化配置清单（C7：。

    把三类低频自愈动作接入既有 WorkBuddy 自动化机制（与 schedule_reflect 同源），
    统一安排在避高峰的凌晨时段、并彼此错位避免长任务重叠：
    - 每日 reflect --auto（anchor 时刻）：核心自转（去重/矛盾检测/分类复评/过期归档/晋升）
    - 每周矛盾仲裁扫描（周日 anchor+1h）：doctor --contradictions --fix --arbitrate
    （无 LLM 时自动跳过仲裁门，降级为仅报告强矛盾对——安全）
    - 每月衰减清扫（每月1日 anchor+2h）：decay --apply 确定性重算 relevance/thermal
    （兜底「长期不被 recall 的冷库」也能衰减；无 LLM 依赖）
    - [可选] 索引重建（每月2日 anchor+1.5h）：graph --rebuild 干净重算（消除历史 noise 边）
    —— 仅 --with-rebuild 时排入；默认「按需」不排，符合「index 重建按需」语义

    cron=True（4.5.48，§6.2）：改产出 systemd/cron 片段，让非 WorkBuddy 环境也能低频自愈
    （脱离 WB 自动化机制）。默认（cron=False）仍产出 WB 自动化清单。
    函数只产出配置清单；实际注册由调用方用 automation_update（WB）或 crontab/systemctl 完成。
    返回 list[dict]（WB 模式）或 dict（cron 模式，含 crontab/systemd 片段）。
    """
    hh, mm = _parse_hhmm(at)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(script_dir)
    c_contra_h, c_contra_m = _stagger_hhmm(hh, mm, 1)    # anchor +1h
    c_decay_h, c_decay_m = _stagger_hhmm(hh, mm, 2)      # anchor +2h
    c_rebuild_h, c_rebuild_m = _stagger_hhmm(hh, mm, 1.5)  # anchor +1.5h

    def _cmd(op_args):
        return ("cd \"%s\" && \"%s\" scripts/memory_ops/__init__.py %s --root \"%s\""
                % (skill_dir, sys.executable, op_args, root))
    def _cmd_sh(op_args):
        return ("cd '%s' && '%s' scripts/memory_ops/__init__.py %s --root '%s'"
                % (skill_dir, sys.executable, op_args, root))

    if cron:
        # 脱离 WorkBuddy 的自调度：生成 cron + systemd 片段，供 Linux/macOS 等环境低频自愈。
        def _ct(h, m):
            return "%d %d" % (m, h)
        crontab = [
            "%s * * * %s   # keeper 每日自转 reflect --auto" % (_ct(hh, mm), _cmd_sh("reflect --auto")),
            "%s * * 0 %s   # keeper 每周矛盾仲裁扫描（周日）"
            % (_ct(c_contra_h, c_contra_m), _cmd_sh("doctor --contradictions --fix --arbitrate")),
            "%s 1 * * %s   # keeper 每月衰减清扫（每月1日）"
            % (_ct(c_decay_h, c_decay_m), _cmd_sh("decay --apply")),
        ]
        if with_rebuild:
            crontab.append("%s 2 * * %s   # keeper 索引重建（每月2日，按需）"
                           % (_ct(c_rebuild_h, c_rebuild_m), _cmd_sh("graph --rebuild")))
        svc = (
            "[Unit]\nDescription=agent-local-memory-keeper 低频自愈\n[Service]\nType=oneshot\n"
            "WorkingDirectory=%s\n"
            "ExecStart=%s scripts/memory_ops/__init__.py reflect --auto --root %s\n"
            "ExecStart=%s scripts/memory_ops/__init__.py doctor --contradictions --fix --arbitrate --root %s\n"
            "ExecStart=%s scripts/memory_ops/__init__.py decay --apply --root %s\n"
            % (skill_dir, sys.executable, root, sys.executable, root, sys.executable, root)
        )
        timer = (
            "[Unit]\nDescription=keeper 每日低频自愈定时器\n"
            "[Timer]\nOnCalendar=*-*-* %02d:%02d:00\nPersistent=true\n"
            "[Install]\nWantedBy=timers.target\n" % (hh, mm)
        )
        return {
            "ok": True, "mode": "cron",
            "crontab": crontab,
            "systemd": {
                "keeper-self-heal.service": svc,
                "keeper-self-heal.timer": timer,
                "install": ("cp keeper-self-heal.service keeper-self-heal.timer "
                            "/etc/systemd/system/ && systemctl daemon-reload "
                            "&& systemctl enable --now keeper-self-heal.timer"),
            },
            "note": "cron/systemd 片段供非 WorkBuddy 环境低频自愈；Windows 用户用「任务计划程序」"
                    "在对应时刻触发上方 _cmd（Windows 风格）命令即可。",
        }

    autos = []
    # 1) 每日 reflect --auto（核心自转，anchor 时刻）
    autos.append({
        "name": "keeper 每日自转 reflect --auto",
        "scheduleType": "recurring",
        "rrule": "FREQ=DAILY;BYHOUR=%d;BYMINUTE=%d" % (hh, mm),
        "prompt": ("运行 agent-local-memory-keeper 的 reflect --auto 整理记忆"
                   "（去重/矛盾检测/分类复评/过期归档/晋升）。命令：\n%s" % _cmd("reflect --auto")),
        "cwds": skill_dir,
        "status": "ACTIVE",
        "notes": "由 schedule_self_heal 生成（C7, 4.5.45）。核心自转；若 AI_MEMORY_STORE 已设可用该路径。"
    })
    # 2) 每周矛盾仲裁扫描（周日 anchor+1h，低频避高峰）
    autos.append({
        "name": "keeper 每周矛盾仲裁扫描",
        "scheduleType": "recurring",
        "rrule": "FREQ=WEEKLY;BYDAY=SU;BYHOUR=%d;BYMINUTE=%d" % (c_contra_h, c_contra_m),
        "prompt": ("运行 agent-local-memory-keeper 的每周矛盾仲裁扫描（只读强矛盾对，"
                   "自动把旧/低置信条标 superseded，只标不删）。命令：\n%s"
                   % _cmd("doctor --contradictions --fix --arbitrate")),
        "cwds": skill_dir,
        "status": "ACTIVE",
        "notes": "由 schedule_self_heal 生成（C7, 4.5.45）。周日低频避高峰；无 LLM 时自动跳过仲裁（降级为仅报告）。"
    })
    # 3) 每月衰减清扫（每月1日 anchor+2h）
    autos.append({
        "name": "keeper 每月衰减清扫",
        "scheduleType": "recurring",
        "rrule": "FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=%d;BYMINUTE=%d" % (c_decay_h, c_decay_m),
        "prompt": ("运行 agent-local-memory-keeper 的每月衰减清扫（确定性重算 relevance_score/thermal，"
                   "让冷记忆自然降级、不挤占热位）。命令：\n%s" % _cmd("decay --apply")),
        "cwds": skill_dir,
        "status": "ACTIVE",
        "notes": "由 schedule_self_heal 生成（C7, 4.5.45）。兜底冷库（长期不被 recall 的库）也能衰减；无 LLM 依赖。"
    })
    # 4) [可选] 索引重建（按需，默认不排）—— 消除历史 noise 图边
    if with_rebuild:
        autos.append({
            "name": "keeper 索引重建（按需）",
            "scheduleType": "recurring",
            "rrule": "FREQ=MONTHLY;BYMONTHDAY=2;BYHOUR=%d;BYMINUTE=%d" % (c_rebuild_h, c_rebuild_m),
            "prompt": ("运行 agent-local-memory-keeper 的 graph --rebuild 干净重算"
                       "（清空图衍生边 + 重算，消除历史 noise 边）。命令：\n%s" % _cmd("graph --rebuild")),
            "cwds": skill_dir,
            "status": "ACTIVE",
            "notes": "由 schedule_self_heal 生成（C7, 4.5.45）。默认按需（--with-rebuild 才排）；低频每月第2日，错开衰减清扫。"
        })
    return autos

