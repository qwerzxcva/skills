# Auto-extracted submodule: _reflect
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _dedup_thresholds():
    if _emb_backend() == "lexical":
        return _CAPTURE_DEDUP_SUPERSEDE_LEXICAL, _CAPTURE_DEDUP_RESURRECT_LEXICAL
    return _CAPTURE_DEDUP_SUPERSEDE, _CAPTURE_DEDUP_RESURRECT

def _classify_type_llm(root, summary, body="", tags=None, chat=None):
    """ P2 · LLM 分类（capture/reflect 复用）。返回 (type, confidence, reason) 或 None。
    system 明确枚举 TYPE_CANON + 要求输出 confidence 与简短 reason，便于 reflect 重分类时
    判断「是否高置信改写」。解析失败一律返 None（交给规则兜底）。"""
    if chat is None:
        return None
    try:
        system = ("你是记忆分类助手。把一条经验归类到唯一类型："
                  "BP(可复用最佳实践/方法)、WF(多步流程/操作顺序)、PF(坑/别做/反例)、"
                  "PREF(用户长期偏好/习惯)、FACT(客观事实/环境常量)、DOC(长文档/报告摘要)。"
                  "只输出 JSON：{\"type\":\"<之一>\",\"confidence\":0.0~1.0,\"reason\":\"<一句话>\"}。")
        user = "摘要：%s\n正文：%s\n标签：%s" % (
            summary or "", (body or "")[:800], " ".join(tags or []))
        out = chat(system, user, temperature=0.0, max_tokens=200)
        obj = _parse_llm_json_obj(out)
        t = _normalize_type(obj.get("type", ""))
        if t not in TYPE_CANON:
            return None
        conf = float(obj.get("confidence", 0.7))
        return t, conf, (obj.get("reason") or "")[:80]
    except Exception:
        return None

def _fit_decay_lambda(root):
    """按用户真实访问间隔拟合遗忘衰减常数 λ（替代硬编码 0.03，#4 衰减自适应）。

    做法：收集「访问次数≥2 且有≥2 条访问日期证据」的记忆，取其相邻访问间隔的中位数
    gap；拟合 λ0 = ln(2)/gap（半衰期≈median gap）。再用**贝叶斯式先验收缩**融合经验
    先验 PRIOR=0.03（等效 3 条伪样本）：λ = (n·λ0 + W·PRIOR)/(n+W)，夹紧 [0.005,0.2]。
    这样冷启动（样本<5）不再死卡默认 0.03，也不会被 1 条极端间隔带偏——样本少→先验
    主导，样本多→数据主导。decay_fitted 仍保留「≥5 真实样本」语义供报告。结果落盘
    meta.json，跨进程/跨会话生效。"""
    mems = _all_mems(root)
    gaps = []
    for m in mems.values():
        af = m.get("accessed_from") or []
        dates = []
        for a in af:
            d = a.get("date") if isinstance(a, dict) else None
            if d:
                try:
                    dates.append(datetime.date.fromisoformat(d))
                except Exception:
                    pass
        if m.get("accessed"):
            try:
                dates.append(datetime.date.fromisoformat(m["accessed"]))
            except Exception:
                pass
        dates = sorted(set(dates))
        for i in range(1, len(dates)):
            gaps.append((dates[i] - dates[i - 1]).days)
    meta = _load_meta(root)
    PRIOR = 0.03          # 经验先验：日级遗忘节奏的合理默认值
    PRIOR_W = 3           # 等效先验样本数：仅 3 条伪样本，故 1~2 条真实样本即可把 λ 拉离先验
    if gaps:
        gaps_sorted = sorted(gaps)
        med = gaps_sorted[len(gaps_sorted) // 2]
        if med <= 0:
            med = 1
        fit = math.log(2) / med
        fit = min(0.2, max(0.005, fit))
        n = len(gaps)
        # 贝叶斯式收缩：样本少→先验主导（避免冷启动死卡 0.03 且避免被单条极端间隔带偏），
        # 样本多→数据主导。decay_fitted 仍保留「≥5 真实样本」语义供报告。
        lam = (n * fit + PRIOR_W * PRIOR) / (n + PRIOR_W)
        lam = min(0.2, max(0.005, lam))
        meta["decay_lambda"] = round(lam, 5)
        meta["decay_fitted"] = (n >= 5)
        meta["n_decay_samples"] = n
        meta["decay_prior_weight"] = PRIOR_W
    else:
        meta["decay_lambda"] = PRIOR
        meta["decay_fitted"] = False
        meta["n_decay_samples"] = 0
    _save_meta(root, meta)
    return meta

def _write_related_edge(root, a_id, b_id):
    """在 a、b 之间建立双向 related_to 边并落盘（幂等）。供 deposit 自动连边与
    reflect/doctor 连边候选应用复用。任何异常静默忽略，绝不阻断主流程。"""
    try:
        if a_id == b_id:
            return
        ma, _ = _load_mem(root, a_id)
        mb, _ = _load_mem(root, b_id)
        if ma.get("status") != "active" or mb.get("status") != "active":
            return  # 仅链接活跃记忆，避免把边挂到已归档/被纠正记忆上
        ma.setdefault("relations", {})
        mb.setdefault("relations", {})
        changed = False
        if b_id not in ma["relations"].setdefault("related_to", []):
            ma["relations"]["related_to"].append(b_id)
            changed = True
        if a_id not in mb["relations"].setdefault("related_to", []):
            mb["relations"]["related_to"].append(a_id)
            changed = True
        if changed:
            _save_mem(root, a_id, ma)
            _save_mem(root, b_id, mb)
    except Exception:
        pass

def _apply_link_candidates(root, link_cands, mems=None):
    """批量建立 link_candidates 的双向 related_to 边（P0-B auto 应用）。

    性能关键：先在内存聚合「每个记忆待追加的 related_to 集合」，再对每个唯一记忆只
    _save_mem 一次（源对象直接复用 reflect 已加载的 mems，零额外读盘）。旧版 reflect
    --auto 逐对调用 _write_related_edge（每对双向各 load+save 两次），千条库 2141 候选
    时产生 ~8500 次文件 I/O，reflect 从 ~2s 涨到 32s；批量化后 I/O 降至「候选涉及的唯一
    记忆数」量级（通常数百），回到 <5s。幂等（已连不重复）、仅链接 active、异常静默。"""
    if not link_cands:
        return
    if mems is None:
        mems = _all_mems(root)
    pending = {}
    for c in link_cands:
        a, b = c.get("a"), c.get("b")
        if not a or not b or a == b:
            continue
        pending.setdefault(a, set()).add(b)
        pending.setdefault(b, set()).add(a)
    for mid, adds in pending.items():
        m = mems.get(mid)
        if m is None or m.get("status") != "active":
            continue
        rel = m.setdefault("relations", {})
        lst = rel.setdefault("related_to", [])
        changed = False
        for oid in adds:
            om = mems.get(oid)
            if om is None or om.get("status") != "active":
                continue
            if oid not in lst:
                lst.append(oid)
                changed = True
        if changed:
            _save_mem(root, mid, m)

def _subjects_overlap(a, b):
    """G1 主体重叠判定（容错版， 修复）。

    旧版用「精确集合交集」：extract_subjects 噪声会让「红烧肉要」与「红烧肉」被判为
    不同主体 → 同主体近似重复被漏标。改为：任一方没抽出主体→不豁免（交给相似度判）；
    否则任一方主体是另一方主体的子串/超串即视为重叠（如「红烧肉」⊂「红烧肉要」）。
    不同菜品（红烧肉 vs 排骨）无子串包含→仍正确豁免，不引入误判。
    """
    if not a or not b:
        return True
    for x in a:
        for y in b:
            if x == y or x in y or y in x:
                return True
    return False

def _recent_access_count(mem, days=7):
    """统计 accessed_from 中最近 days 天内的使用次数。
    「7 天内使用 N 次」频率信号，用于 reflect 的自动晋升。
    排除系统/自动动作（auto_promote/auto_archive/calibrated_*），避免晋升动作自身
    的审计条目自我膨胀、在同一次 reflect 里把记忆二次晋升。"""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    _SYS = ("auto_promote", "auto_archive", "calibrated_up", "calibrated_down")
    cnt = 0
    for af in (mem.get("accessed_from") or []):
        if not isinstance(af, dict):
            continue
        if af.get("action") in _SYS:
            continue
        d = af.get("date")
        if d:
            try:
                if datetime.date.fromisoformat(d) >= cutoff:
                    cnt += 1
            except Exception:
                pass
    return cnt

def _relevance(mem, lam=0.03, access_n=None):
    """衰减相关性（科学遗忘模型，本地化）：
    relevance = e^(-λ × 未活跃天数) × log2(访问次数+1) × 类型权重
    λ 为遗忘衰减常数（默认 0.03；reflect --auto 会按真实访问间隔拟合并经 meta 传入，见 #4）。
    类型权重：纠正类 1.2（保留更久）、project 0.8（衰减更快）、ephemeral 0.6（衰减最快，
    显式临时记忆应比项目记忆更早沉底）、其余 1.0。
    用于 reflect 的过期归档——被多次使用的记忆可"续命"，真正无人问津才沉底。
    universal 永不自动归档，故此权重主要影响 project/ephemeral。

    `access_n`（5.0/A1）：调用方可传入**单一热源**（recall_counts.json）里的真实召回次数。
    不传时回退读 `mem["access_count"]`——该字段在真库 204/211 条恒 0，会让本函数的
    `log2(ac+1)` 恒为 0 → relevance 恒 0 → 「续命」机制整体失效。批量调用请务必传入。"""
    try:
        acc = datetime.date.fromisoformat(mem.get("accessed") or mem.get("created") or today())
    except Exception:
        acc = datetime.date.today()
    age = max(0, (datetime.date.today() - acc).days)
    _an = int(mem.get("access_count", 0) or 0) if access_n is None else int(access_n or 0)
    freq = math.log2(_an + 1)
    cat = mem.get("category", "")
    sc = mem.get("scope")
    if cat == "correction":
        w = 1.2
    elif sc == "ephemeral":
        w = 0.6
    elif sc == "project":
        w = 0.8
    else:
        w = 1.0
    if mem.get("tier") == "seed":
        w *= 0.5
    conf = mem.get("confidence") or 1.0
    imp = mem.get("importance")
    imp_factor = 1.0 if imp is None else (0.6 + 0.4 * imp)
    return math.exp(-lam * age) * freq * w * (0.6 + 0.4 * conf) * imp_factor

def _reflect_llm(root, mems=None, cfg=None):
    """#8 可选 LLM 自进化（安全版）核心：内容冻结，只出建议、绝不改写记忆。

    仅当 cfg['enabled'] 为 True 触发；否则立即返回未启用，规则 reflect 照常。
    隐私：仅把 active 记忆的【元信息】(id/summary/tags/category/tier/scope) 发给 LLM，
    绝不发送 body 正文；默认本地优先（ollama），可达到记忆不出本机。
    返回 {enabled, backend, model, n_suggestions, suggestions:[...], error?} 并入 findings['llm']。
    建议落盘 store/llm_suggestions.json，供人工/未来 apply 审阅，绝不自动写记忆。
    """
    if cfg is None:
        cfg = _load_llm_config(root)
    if not cfg.get("enabled"):
        return {"enabled": False,
                "note": "LLM 自进化未启用（config.llm.enabled=false 且未传 --llm）；规则 reflect 照常。"}
    try:
        import urllib.request
        import urllib.error
    except Exception:
        return {"enabled": True, "n_suggestions": 0, "suggestions": [],
                "error": "urllib 不可用（极罕见）"}
    if mems is None:
        mems = _all_mems(root)
    active = [m for m in mems.values() if m.get("status") == "active"]
    if not active:
        return {"enabled": True, "n_suggestions": 0, "suggestions": [],
                "note": "无 active 记忆可分析"}
    meta_list = [{"id": m["id"], "category": m.get("category", ""),
                  "tier": m.get("tier", ""), "scope": m.get("scope", ""),
                  "tags": m.get("tags", []), "summary": m.get("summary", "")}
                 for m in active]
    backend = cfg.get("backend", "ollama")
    base_url = cfg.get("base_url") or ("http://localhost:11434/v1" if backend == "ollama" else "")
    model = cfg.get("model") or ("qwen2.5:7b" if backend == "ollama" else "gpt-4o-mini")
    batch = max(1, int(cfg.get("batch_size", 20)))
    max_sug = max(1, int(cfg.get("max_suggestions", 30)))
    api_key = ""
    if cfg.get("api_key_env"):
        api_key = os.environ.get(cfg["api_key_env"], "")
    system = ("你是记忆整理助手。下面是某 Agent 的长期记忆元信息（已脱敏，不含正文）。"
              "请识别可优化的点，仅输出 JSON 数组，每条形如："
              "{\"action\":\"merge|correct|promote|link|split|note\","
              "\"source_id\":\"<id>\",\"target_id\":\"<id|null>\","
              "\"reason\":\"<简短中文理由>\"}。"
              "规则：merge=两条高度重复可合并；correct=新认知推翻旧认知(target 应标为过时)；"
              "promote=值得从 working 升 curated；link=两条应建立关联；"
              "split=一条含多个独立主题应拆；note=仅评论不改。不要编造不存在的 id。"
              "只输出合法 JSON 数组，不要任何解释文字。")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    collected = []
    for i in range(0, len(meta_list), batch):
        chunk = meta_list[i:i + batch]
        user = ("当前记忆元信息（全库共 %d 条 active，本批 %d 条）：\n" %
                (len(meta_list), len(chunk)))
        user += json.dumps(chunk, ensure_ascii=False)
        user += "\n请按上述格式输出建议 JSON 数组（最多 %d 条，只针对本批）：" % max_sug
        payload = {"model": model, "temperature": float(cfg.get("temperature", 0.2)),
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "stream": False}
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            out = {"enabled": True, "backend": backend, "model": model,
                   "n_suggestions": len(collected), "suggestions": collected,
                   "error": "LLM 调用失败：%s" % e}
            _persist_llm_suggestions(root, out)
            return out
        sug = _parse_llm_json_array(content)
        if sug:
            collected.extend(sug)
        if len(collected) >= max_sug:
            collected = collected[:max_sug]
            break
    out = {"enabled": True, "backend": backend, "model": model,
           "n_suggestions": len(collected), "suggestions": collected[:max_sug]}
    _persist_llm_suggestions(root, out)
    return out

def _persist_llm_suggestions(root, out):
    """落盘 store/llm_suggestions.json（内容冻结：只写建议文件，绝不改记忆）。"""
    try:
        os.makedirs(os.path.join(root, "store"), exist_ok=True)
        out = dict(out)
        out["generated"] = today()
        with open(os.path.join(root, "store", "llm_suggestions.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _auto_apply_safe_suggestions(root, suggestions):
    """自动应用 LLM 建议的安全子集（link / note），其余建议仅落盘供人工审阅。

    安全保证：
    - link：仅在两条 active 记忆间建立双向 related_to 边（复用 _write_related_edge，
    幂等、不修改内容、不删记忆）。与 deposit 自动连边完全相同的机制。
    - note：仅在记忆的 notes 列表追加一条观察（纯加性，不改 summary/body/tags/type）。
    - 不自动应用 merge/correct/promote/split（这些有破坏性，需人工确认）。
    - 所有 ID 校验：不存在或非 active → 跳过。

    返回 {applied: int, skipped: int, link: int, note: int, details: [...]}。
    """
    result = {"applied": 0, "skipped": 0, "link": 0, "note": 0, "details": []}
    if not suggestions:
        return result
        # 预加载 active id 集合，避免逐条 _load_mem 校验
    try:
        _idx = load_index(root)
        _active_ids = {e.get("id") for e in _idx.get("entries", [])
                       if isinstance(e, dict) and e.get("status") == "active"}
    except Exception:
        _active_ids = set()

    for sug in suggestions:
        if not isinstance(sug, dict):
            result["skipped"] += 1
            continue
        action = sug.get("action", "")
        if action not in _SAFE_ACTIONS:
            result["skipped"] += 1
            continue
        src = sug.get("source_id", "")
        tgt = sug.get("target_id", "")
        reason = sug.get("reason", "")
        if not src or src not in _active_ids:
            result["skipped"] += 1
            result["details"].append({"action": action, "source_id": src,
                                       "status": "skipped", "reason": "source_id 不存在或非 active"})
            continue

        if action == "link":
            if not tgt or tgt not in _active_ids or src == tgt:
                result["skipped"] += 1
                result["details"].append({"action": "link", "source_id": src, "target_id": tgt,
                                           "status": "skipped", "reason": "target_id 无效"})
                continue
            try:
                _write_related_edge(root, src, tgt)
                result["link"] += 1
                result["applied"] += 1
                result["details"].append({"action": "link", "source_id": src, "target_id": tgt,
                                           "status": "applied", "reason": reason})
            except Exception as e:
                result["skipped"] += 1
                result["details"].append({"action": "link", "source_id": src, "target_id": tgt,
                                           "status": "error", "reason": str(e)})

        elif action == "note":
            try:
                m, _ = _load_mem(root, src)
                notes = m.setdefault("notes", [])
                # 幂等：相同 reason 不重复追加
                existing = [n.get("text", "") for n in notes if isinstance(n, dict)]
                if reason and reason not in existing:
                    notes.append({"text": reason, "source": "llm_auto_note",
                                  "date": today()})
                    if len(notes) > 20:
                        del notes[:len(notes) - 20]
                    _save_mem(root, src, m)
                result["note"] += 1
                result["applied"] += 1
                result["details"].append({"action": "note", "source_id": src,
                                           "status": "applied", "reason": reason})
            except Exception as e:
                result["skipped"] += 1
                result["details"].append({"action": "note", "source_id": src,
                                           "status": "error", "reason": str(e)})

    return result

def _recency_factor(accessed):
    """复发晋升用：按上次访问距今衰减，0~1。近期=1.0，越久越低，下限 0.25。

    修复「频率≠重要性」缺陷——被反复吐槽的陈旧琐事不应仅凭 recurrence 晋升为原则。
    """
    try:
        _d = datetime.date.fromisoformat(accessed) if accessed else None
    except Exception:
        _d = None
    if _d is None:
        return 1.0
    _days = (datetime.date.today() - _d).days
    if _days <= 0:
        return 1.0
    return max(0.25, 1.0 - _days / 180.0)


def evolve(root, dry_run=True, auto_apply=False, max_items=20, use_llm=None,
           rule_signal_only=False):
    """ · 自我进化引擎：把「被证据印证」的经验自主升华为可复用原则（越用越聪明）。

    两类信号：
    1) 规则信号（无需 LLM，永远安全）：recurrence_count>=3 的 pattern 表明同一经验被
    多次实践印证 → 合成「经 N 次验证」的原则记忆（provenance=auto）。
    2) LLM 信号（复用 reflect 产出的 llm_suggestions.json 中 synthesize/extract 建议，
    不额外发起网络调用）把跨记忆综合/抽取的高层原则晋升为真实记忆。

    形成的 auto 记忆带 review_by（默认 +30 天限期复核）与 auto_evolve 标记，便于人工回滚；
    幂等（provenance_key 防重复合成）。
    - 默认 dry_run（review）：只返回候选，不写盘。
    - auto_apply / --apply：真正落盘（仍需本条规则或 LLM 建议通过）。
    返回 {ok, dry_run, synthesized:[...], applied, skipped_existing}。
    """
    out = {"ok": True, "dry_run": bool(dry_run), "synthesized": [],
           "applied": 0, "skipped_existing": 0}
    try:
        mems = _all_mems(root)
        _existing_keys = set()
        for m in mems.values():
            _k = m.get("provenance_key")
            if _k:
                _existing_keys.add(_k)
        _seen_synth = set()  # 单次运行内去重，避免同 key 多条记忆各自合成重复候选
        synth = []
        # 1) 规则信号：复发印证 → 原则
        # ：晋升评分 = 衰减频次 × (0.5+0.5·importance) × (0.8+0.2·belief)。
        # 最低证据门槛 recurrence>=3 保留（防一次性经验误晋升），但陈旧复发(recency↓)或低
        # 重要/低信念经验会被阈值拦下——频率≠重要性，陈旧琐事不晋升。
        _PROMOTE_MIN = 2.0
        # 按 pattern_key 统计活跃记忆数：原则反映「该模式的真实总复发次数」，而非单条记忆
        # 落盘时记录的 recurrence_count（避免「4 条同模式记忆每条只记 1~4」导致原则少报）。
        _pat_counts = {}
        for _mm in mems.values():
            if _mm.get("status") == "active":
                _pk = _mm.get("pattern_key")
                if _pk:
                    _pat_counts[_pk] = _pat_counts.get(_pk, 0) + 1
        for m in mems.values():
            if m.get("status") != "active" or m.get("erroneous"):
                continue
            _pk = m.get("pattern_key")
            _rc = int(_pat_counts.get(_pk, 1) or 1)
            if _rc < 3:
                continue
            _key = "evolve:recur:%s" % _pk
            if _key in _existing_keys or _key in _seen_synth:
                out["skipped_existing"] += 1
                continue
            _imp = float(m.get("importance") or 0.5)
            _bel = float(m.get("belief_strength")
                         if m.get("belief_strength") is not None else 1.0)
            _rec = _recency_factor(m.get("accessed"))
            _score = _rc * _rec * (0.5 + 0.5 * _imp) * (0.8 + 0.2 * _bel)
            if _score < _PROMOTE_MIN:
                continue  # 陈旧/低重要/低信念的复发不晋升为原则
            _sid = m.get("id")
            principle = "经 %d 次实践印证：%s" % (_rc, (m.get("summary") or "").strip())
            # 抽象化 body：概括提炼要点而非复述原文，降低与源记忆的近重复（避免 dedup 吞并）
            body = ("[自我进化原则] 该经验经 %d 次独立实践印证，已固化为可复用原则；"
                    "它抽象自源经验（见 derives_from=%s），不再复述原始细节。"
                    "核心要点：%s"
                    % (_rc, _sid, (m.get("summary") or "").strip()))
            synth.append({"key": _key, "summary": principle, "body": body,
                          "category": "principle", "source_ids": [_sid],
                          "signal": "recurrence", "recurrence": _rc})
            _seen_synth.add(_key)
            # 2) LLM 信号：复用 reflect 的 llm_suggestions.json（synthesize/extract）
        _sug_path = os.path.join(root, "store", "llm_suggestions.json")
        if os.path.exists(_sug_path):
            try:
                _sugs = json.load(open(_sug_path, encoding="utf-8")).get("suggestions", [])
                for sg in _sugs:
                    if sg.get("action") not in ("synthesize", "extract"):
                        continue
                    _src = sg.get("source_id")
                    _sum = (sg.get("reason") or "").strip() or ("综合提炼：%s" % _src)
                    _key = "evolve:llm:%s" % ((_src or _sum)[:40])
                    if _key in _existing_keys or _key in _seen_synth:
                        out["skipped_existing"] += 1
                        continue
                    synth.append({"key": _key, "summary": _sum,
                                  "body": "由 LLM 跨记忆综合/抽取（source=%s）。" % _src,
                                  "category": "principle",
                                  "source_ids": [_src] if _src else [],
                                  "signal": "llm_synthesis"})
                    _seen_synth.add(_key)
            except Exception:
                pass
        synth.sort(key=lambda x: (x.get("signal") == "recurrence",
                                  x.get("recurrence", 0)), reverse=True)
        synth = synth[:max_items]
        out["synthesized"] = synth
        if dry_run or not auto_apply:
            return out
        applied = 0
        _rb = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        for s in synth:
            # ：rule_signal_only（self-heal 默认开启）→ 仅应用「规则信号」
            #（recurrence≥3，免 LLM、幂等、限期复核）；LLM 信号保持 review-only，
            # 不自动落盘，避免不可控内容进入记忆库。
            if rule_signal_only and s.get("signal") != "recurrence":
                continue
            if s["key"] in _existing_keys:
                out["skipped_existing"] += 1
                continue
                # ：以 derives_from 声明派生意图，取代 skip_dedup hack——派生记忆作为独立
                # 新节点创建（不进查重吞并路径），并自动建立「派生→源」有向边。
            _src = (s.get("source_ids") or [None])[0]
            cid = deposit(root, s.get("category", "principle"), s["summary"],
                          ["auto_evolve", "principle", s.get("signal", "rule")],
                          s["body"], tier="working", inferred=True, auto_sourced=True,
                          recorded_by="agent", provenance="auto",
                          provenance_key=s["key"], src_origin="self_evolve",
                          derives_from=_src)
            try:
                nm, _ = _load_mem(root, cid)
                nm["auto_evolve"] = True
                nm["review_by"] = _rb
                _save_mem(root, cid, nm)
            except Exception:
                pass
            for sid in s.get("source_ids", []):
                if sid:
                    try:
                        _write_related_edge(root, cid, sid)
                    except Exception:
                        pass
            _existing_keys.add(s["key"])
            applied += 1
            # ：新合成原则 → 打 dirty，self-heal 据此同步相关 skill/规则层
            try:
                from _self_heal import mark_dirty_safe
                mark_dirty_safe(root, cid)
            except Exception:
                pass
        out["applied"] = applied
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out

def schedule_reflect(root, at="03:00", freq="daily"):
    """生成 reflect --auto 的 WorkBuddy automation 配置 JSON（P1：自主调度）。

    本工具核心自转不依赖 WorkBuddy 自动化（converse 对话内触发已足够），
    但用户可选地注册一条每日/每周兜底保险自动化，让 reflect --auto 在后台自动跑。
    函数只负责输出配置；实际注册由调用方（WorkBuddy 助手/用户）用 automation_update 完成。
    """
    import re as _re
    m = _re.match(r"^(\d{1,2}):(\d{2})$", at)
    if not m:
        raise ValueError("--at 必须是 HH:MM 格式，收到: %s" % at)
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("--at 时刻非法: %s" % at)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(script_dir)
    cmd = ("cd \"%s\" && \"%s\" "
           "scripts/memory_ops/__init__.py reflect --auto --root \"%s\"") % (skill_dir, sys.executable, root)
    prompt = ("运行 agent-local-memory-keeper 的 reflect --auto 整理记忆。命令：\n%s\n"
              "若环境变量 AI_MEMORY_STORE 已设置，可改用该路径。") % cmd
    if freq == "daily":
        rrule = "FREQ=DAILY;BYHOUR=%d;BYMINUTE=%d" % (hh, mm)
    elif freq == "weekly":
        rrule = "FREQ=WEEKLY;BYDAY=MO;BYHOUR=%d;BYMINUTE=%d" % (hh, mm)
    else:
        raise ValueError("--freq 必须是 daily/weekly，收到: %s" % freq)
    cfg = {
        "name": "agent-local-memory-keeper reflect --auto",
        "scheduleType": "recurring",
        "rrule": rrule,
        "prompt": prompt,
        "cwds": skill_dir,
        "status": "ACTIVE",
        "notes": "由 memory_ops schedule_reflect 生成；核心自转仍由 converse 对话内触发，本自动化仅作兜底保险。"
    }
    return cfg

def _reflect_impl(root, auto=False, stale_days=90, auto_archive=True, context_budget=None, llm=False):
    """自我改进引擎：去重 / 矛盾检测 / 分类复评（自主学习）/ 过期归档 / 晋升候选 /
    相似连边候选 / AAR 复盘链 / 上下文预算预警。

    返回 findings dict；auto=True 时执行安全动作（链接、标 superseded、晋升 curated、
    分类复评、过期归档、应用连边候选），**绝不删除**——过期记忆落入更深子记忆（archive），
    需要时仍可 --deep 召回。
    """
    mems = _all_mems(root)
    # 5.0/A1：召回频次单一热源（recall_counts.json）。下面所有「访问次数」判定
    # （过期归档续命 / seed 晋升 / 长期无争议加权）原来都读 mem["access_count"]，
    # 而该字段在真库 204/211 条恒 0 → 三条判定同时失效。此处一次性加载并传参。
    _acounts = _load_recall_counts(root)

    def _acc(m):
        return _access_count_of(root, m.get("id"), m, _acounts)

    # 衰减自适应（#4）：auto 时先按真实访问间隔拟合 λ 并落盘 meta.json，
    # 后续过期检测用拟合后的 λ（未拟合/样本不足时退回默认 0.03，向后兼容）。
    if auto:
        _fit_decay_lambda(root)
    _lam = _load_meta(root).get("decay_lambda", 0.03)
    findings = {"duplicates": [], "contradictions": [], "stale": [],
                "promote_candidates": [], "scope_review": [],
                "link_candidates": [], "aar": [], "context_full": False}
    ids = list(mems)

    # 1) 重复检测：同 tag 重叠 + summary 相似；主体词不同则豁免（G1 修复）
    # 性能：大库下用「标签预分组」只比对共享标签的记忆对，避免 O(n^2) 全量两两比。
    # 关键：用「单标签组内成员数上限 MAX_GROUP」控制，而非「标签出现频率占比」。
    # 原因 修复）：旧版用「出现 >20% 活跃记忆即视为宽泛并排除」，在**小库/
    # 早期库**里任何共享标签都满足该占比 → 整组被排除 → 去重在小库整体失效（正是
    # 最该抓近似重复的阶段）。改为「组太大才跳过」：小库/中等库（组 2~几十）照常
    # 两两比；只有真·巨大通用标签（如全员共有的 "perf"，组达数百）才跳过——既保正确
    # 又保性能，且与库规模无关。（无标签记忆不在任何组，按设计不去重，见 FAQ。）
    MAX_GROUP = 150
    active_ids = [mid for mid in ids if mems[mid].get("status") == "active"]
    by_tag = {}
    for mid in active_ids:
        for t in mems[mid].get("tags", []):
            by_tag.setdefault(t, []).append(mid)
    dup_pairs = set()
    _dup_graph = {}
    for _grp in by_tag.values():
        if len(_grp) < 2 or len(_grp) > MAX_GROUP:
            continue
        for i in range(len(_grp)):
            for j in range(i + 1, len(_grp)):
                dup_pairs.add((_grp[i], _grp[j]))
    for ia, ib in dup_pairs:
        a, b = mems[ia], mems[ib]
        # #12 修复：去重比较 summary+body 而非仅 summary——两条 summary 不同但 body 高度
        # 重叠的记忆（如同一经验换了个标题重写）此前漏检，导致库膨胀。
        _text_a = (a.get("summary", "") + " " + a.get("body", "")).strip()
        _text_b = (b.get("summary", "") + " " + b.get("body", "")).strip()
        sim = _emb.semantic_similarity(_text_a, _text_b)
        # G1 修复：语义相似度高但主体不同（如「红烧肉冷水焯水」vs「排骨冷水焯水」）
        # 不应判重复——抽取主体实体，主体无重叠则豁免（容错版见 _subjects_overlap）。
        sub_a = set(_emb.extract_subjects(_text_a))
        sub_b = set(_emb.extract_subjects(_text_b))
        subjects_overlap = _subjects_overlap(sub_a, sub_b)
        # P5 修复（与 deposit 写前查重 H1 同一把尺）：用词法/神经感知的 _dedup_thresholds
        # 替代写死的 0.6。词法后端下「同结构不同内容」（仅数字/措辞差异）相似度高达
        # ~0.86–0.89，若用 0.6 会把大量「同名不同义」记忆误判为重复并 supersede 折叠
        # （实测 S3 场景 17 条记忆被折到 1 条 active）。0.99(词法)/0.88(神经) 才区分
        # 「真重复(≈1.0)」与「同结构不同内容(<0.99)」。
        _sup_thr, _res_thr = _dedup_thresholds()
        if sim >= _sup_thr and subjects_overlap:
            findings["duplicates"].append({"a": a["id"], "b": b["id"]})
            if auto:
                _dup_graph.setdefault(a["id"], set()).add(b["id"])
                _dup_graph.setdefault(b["id"], set()).add(a["id"])

                # : 自动合并重复簇——每簇留最旧代表(id 字典序最小=最早)，其余标 superseded。
                # 修复「reflect 只报告不合并」的实锤缺陷：之前 duplicates 仅进 findings，永不真正去重。
    if auto and _dup_graph:
        _par = {n: n for n in _dup_graph}
        def _find(x):
            while _par[x] != x:
                _par[x] = _par[_par[x]]; x = _par[x]
            return x
        for _a, _bs in _dup_graph.items():
            for _b in _bs:
                _ra, _rb = _find(_a), _find(_b)
                if _ra != _rb:
                    _par[_rb] = _ra
        from collections import defaultdict as _dd
        _comp = _dd(list)
        for _n in _dup_graph:
            _comp[_find(_n)].append(_n)
        _merged = 0
        for _root, _members in _comp.items():
            _members_sorted = sorted(_members, key=lambda mid: mems[mid].get("id", ""))
            _keep = _members_sorted[0]
            for _m in _members_sorted[1:]:
                _mm = mems[_m]
                _mm["status"] = "superseded"
                _mm["superseded_at"] = today()  # 回收计时起点：自被合并取代日起算 180 天
                _mm["settled"] = False  # #9：被合并取代 → settled 失效
                _mm.setdefault("relations", {})["superseded_by"] = _keep
                _mm.setdefault("accessed_from", []).append({
                    "action": "auto_merge", "by": "reflect_auto",
                    "reason": "duplicate of %s" % _keep, "date": today()})
                _save_mem(root, _m, _mm)
                _merged += 1
        findings["merged_count"] = _merged

        # 2) 矛盾检测：纠正/知识缺口 命中 旧最佳实践等
        # 性能：按标签预分组，只比对「与纠正记忆共享标签」的目标记忆（共享标签是触发前提），
        # 大库下避免 O(n^2)。与去重同策略：过于宽泛的标签（组 > MAX_GROUP）不作为候选来源，
        # 避免一条全员共有标签把候选集撑成大集团（仍靠下方 trigger 门兜底正确性）。
        # 纠正记忆无标签的罕见情况仍全量比，保证不漏判。
    contra_by_tag = {}
    for x in mems.values():
        if x.get("category") in CONTRADICTABLE and x.get("status") == "active":
            for t in x.get("tags", []):
                if len(by_tag.get(t, [])) > MAX_GROUP:
                    continue
                contra_by_tag.setdefault(t, []).append(x["id"])
    for c in mems.values():
        if c.get("category") not in CORRECTING or c.get("status") != "active":
            continue
        c_tags = c.get("tags", [])
        if c_tags:
            cand_x = set()
            for t in c_tags:
                cand_x.update(contra_by_tag.get(t, []))
        else:
            cand_x = [m["id"] for m in mems.values()
                      if m.get("category") in CONTRADICTABLE and m.get("status") == "active"]
        for xid in cand_x:
            x = mems[xid]
            if x["id"] == c["id"]:
                continue
                # O2 修复：矛盾检测要求共享 >=2 个标签，避免仅凭 1 个偶然共享标签
                # 就把无关的 best_practice/workflow 误标 superseded（误伤好记忆）。
                # G2 修复：仅靠「泛化标签」(记账/方法/技巧…) 共享不再触发矛盾——
                # 必须「共享 >=2 个具体(非泛化)标签」或「主体实体一致」，否则无关记忆
                # 会被误标 superseded。这是额外的安全网。
            shared = set(c_tags) & set(x.get("tags", []))
            shared_specific = shared - _emb.GENERIC_TAGS
            sub_c = set(_emb.extract_subjects(c.get("summary", "") + " " + c.get("body", "")))
            sub_x = set(_emb.extract_subjects(x.get("summary", "") + " " + x.get("body", "")))
            subjects_overlap = _subjects_overlap(sub_c, sub_x)
            # ── 修订：矛盾触发以「语义主题一致」为硬门槛 ──
            # 旧第三条件 (subjects_overlap and CORRECTING) 仅靠实体词重叠判主题一致，
            # 在主题聚集库里把大量「同域互补」记忆误判为矛盾；且 _has_contradiction_signal
            # 的 pos/neg 词表过泛（用/要 vs 别/不采用）制造假阳性。现统一要求：
            # 语义相似度 ≥ CONTRADICTION_SEM_THRESHOLD(0.65) 作为主题一致的必要条件，
            # 实体词重叠(subjects_overlap)不再单独作为触发证据。立场对立由类别保证
            # （c∈CORRECTING=neg，x∈CONTRADICTABLE=pos），无需依赖易假阳性的词表。
            _c_text = c.get("summary", "") + " " + c.get("body", "")
            _x_text = x.get("summary", "") + " " + x.get("body", "")
            try:
                _sem = _emb.semantic_similarity(_c_text, _x_text)
            except Exception:
                _sem = 0.0
            _sem_ok = _sem >= CONTRADICTION_SEM_THRESHOLD
            tag_signal = (len(shared_specific) >= 2) or \
                         (len(shared_specific) >= 1 and subjects_overlap)
                         # 第三条件：纠正类 + 主题一致（立场对立由类别保证，不再仅凭实体重叠）
            correcting_signal = (c.get("category") in CORRECTING) and _sem_ok
            trigger = _sem_ok and (tag_signal or correcting_signal)
            if x.get("category") in CONTRADICTABLE and trigger:
                if x.get("relations", {}).get("corrected_by") == c["id"]:
                    continue
                findings["contradictions"].append(
                    {"correction": c["id"], "contradicted": x["id"],
                     "semantic_sim": round(_sem, 3)})
                if auto:
                    # 修订：reflect --auto 不再自动 supersede 矛盾记忆
                    # （避免误伤把无关记忆踢出召回）。仅软标记 relations.conflict 供
                    # agent/人工在 `doctor --contradictions --fix` 复核后真正取代。
                    # 4.5.x 修复：conflict 统一为【列表】累积多矛盾（与 doctor --fix 一致），
                    # 不再用标量 `=` 覆盖——否则同一次 reflect 内一条记忆被多条矛盾时只留最后一条，
                    # 且会把 doctor 写入的列表整个冲掉；旧标量值也在此归一为列表。
                    # 双边互记，与 doctor 行为对称。
                    _rel_x = x.setdefault("relations", {})
                    _cf_x = _rel_x.get("conflict")
                    if not isinstance(_cf_x, list):
                        _rel_x["conflict"] = [_cf_x] if _cf_x else []
                    if c["id"] not in _rel_x["conflict"]:
                        _rel_x["conflict"].append(c["id"])
                    _rel_c = c.setdefault("relations", {})
                    _cf_c = _rel_c.get("conflict")
                    if not isinstance(_cf_c, list):
                        _rel_c["conflict"] = [_cf_c] if _cf_c else []
                    if x["id"] not in _rel_c["conflict"]:
                        _rel_c["conflict"].append(x["id"])
                    _af_x = x.setdefault("accessed_from", [])
                    # 🔴 幂等（2026-09-15 审计）：同一对矛盾在**每次** reflect --auto
                    # 都会重算命中，旧实现无条件 append → 实测真库净冗余 368 条（多条
                    # 记忆堆满 12 条上限全是同一对矛盾，仅 date 不同），把真正有用的访问
                    # 证据挤出去。改为「同对手 id 只记一次」；旧条目无 with 字段，
                    # 用 reason 前缀兼容匹配（旧 reason 格式与新一致，仅 sem_sim 值可能不同）。
                    _flag_dup = any(
                        isinstance(_e, dict)
                        and _e.get("action") == "auto_flag_conflict"
                        and (_e.get("with") == c["id"]
                             or ("possible contradiction with %s " % c["id"])
                             in str(_e.get("reason", "")))
                        for _e in _af_x)
                    if not _flag_dup:
                        _af_x.append({
                            "action": "auto_flag_conflict", "by": "reflect_auto",
                            "with": c["id"],
                            "reason": "possible contradiction with %s (sem_sim=%.2f)" % (c["id"], _sem),
                            "date": today()})
                        if len(_af_x) > 12:
                            del _af_x[:len(_af_x) - 12]
                    _save_mem(root, x["id"], x)
                    c.setdefault("relations", {}).setdefault("see_also", [])
                    if x["id"] not in c["relations"]["see_also"]:
                        c["relations"]["see_also"].append(x["id"])
                    _save_mem(root, c["id"], c)

                    # 2.5) 分类复评（自主学习 + 多信号误分类检测，
                    # 不再只做「标签相关性」复评，而是综合：标签可信先验 / 访问证据 / ephemeral 晋升 /
                    # 纠正对齐。detect_misclass 返回置信度，reflect 以 >=0.6 自动纠正（高置信即时调整），
                    # 否则标 scope_review 待审（置信不足不贸然改，避免抖动）。
    model = _clf.load_model(root)
    # P1-6：单遍扫描优化——预过滤 active 列表，learn_access + detect_misclass 共用
    # 原代码 2 次 for m in mems.values 各过滤一次 active，合并为预过滤 + 两阶段处理
    active_mems = [m for m in mems.values() if m.get("status") == "active"]
    for m in active_mems:
        _clf.learn_access(model, m)  # 访问证据刷新先验（usage 即正样本）
    for m in active_mems:
        det = _clf.detect_misclass(model, m, mems)
        if not det:
            continue
        findings["scope_review"].append({
            "id": m["id"], "stored": m.get("scope"),
            "suggest": det["suggest"], "confidence": det["confidence"],
            "reasons": det["reasons"],
        })
        if auto and det["confidence"] >= 0.6:
            # 高置信：立即纠正 + 强学习进分类器，避免反复误判
            m["scope"] = det["suggest"]
            m["scope_confidence"] = det["confidence"]
            m.setdefault("accessed_from", []).append({
                "scope": det["suggest"], "action": "auto_reclassify",
                "reasons": det["reasons"], "date": today(),
            })
            if len(m["accessed_from"]) > 12:
                del m["accessed_from"][:len(m["accessed_from"]) - 12]
            _save_mem(root, m["id"], m)
            _clf.learn_explicit(model, m.get("tags", []), m.get("category", ""),
                                det["suggest"], weight=3)
            # #19 修复：type 误分类检测（标签→type 先验冲突）——与 scope 检测对称
    for m in active_mems:
        tdet = _clf.detect_type_misclass(model, m)
        if not tdet:
            continue
        findings.setdefault("type_review", []).append({
            "id": m["id"], "stored": m.get("type") or m.get("category", ""),
            "suggest": tdet["suggest"], "confidence": tdet["confidence"],
            "reasons": tdet["reasons"],
        })
        if auto and tdet["confidence"] >= 0.6:
            old_type = m.get("type") or m.get("category", "")
            new_type = tdet["suggest"]
            m["category"] = new_type
            m["type"] = new_type
            m.setdefault("accessed_from", []).append({
                "action": "auto_reclassify_type", "by": "reflect",
                "from": old_type, "to": new_type,
                "reasons": tdet["reasons"], "date": today(),
            })
            if len(m["accessed_from"]) > 12:
                del m["accessed_from"][:len(m["accessed_from"]) - 12]
            _save_mem(root, m["id"], m)
            _clf.learn_type(model, m.get("tags", []), new_type, weight=3)
    if auto:
        _clf.save_model(root, model)

        # 3) 过期检测 + 归档（替代删除，落到更深子记忆）
        # 科学衰减遗忘：不再扁平按天数一刀切，而是用衰减
        # 相关性 relevance 决定——被多次使用的记忆可"续命"更久（越用越重要），真正无人
        # 问津的才沉底。universal 永不自动归档（宁可留着，详见 O3）。
        # #10 修复：归档配额自适应——按 active 总量比例限流，避免大库一次归档数百条
        # 导致知识库骤缩。quota = max(5, min(200, active_count * 10%))。
    _active_count = sum(1 for m in mems.values() if m.get("status") == "active")
    _archive_quota = max(5, min(200, int(_active_count * 0.1))) if _active_count > 0 else 5
    _archived_this_run = 0
    today_dt = datetime.date.today()
    for m in mems.values():
        if m.get("tier") == "core" or m.get("status") != "active":
            continue
        try:
            cd = datetime.date.fromisoformat(m.get("created", today()))
        except Exception:
            cd = today_dt
            # O3 修复：stale 基于「最后访问时间」而非「创建时间」。
        acc = m.get("accessed")
        if acc:
            try:
                cd = max(cd, datetime.date.fromisoformat(acc))
            except Exception:
                pass
        age = (today_dt - cd).days
        referenced = any(m["id"] in o.get("relations", {}).get("see_also", [])
                         for o in mems.values())
        sc = m.get("scope", "universal")
        # E1 修复：universal 也可归档，但需低重要度（<0.5）——防止高价值通用经验被误归档
        imp_val = float(m.get("importance", 0.5) or 0.5)
        can_archive = sc in ("ephemeral", "project") or (sc == "universal" and imp_val < 0.5)
        # 修 D2：working 层 + 超长 cold（2×stale_days）+ 极低 importance（<0.3）
        # 的记忆是 v30 seed 降级候选，reflect 不应抢先归档它们——否则 working→seed
        # 降级路径在 auto=True 流程下永远不可达（importance 先验下限 0.6 > 0.3 阈值，
        # 手动设低 imp 的 universal 记忆又因 imp<0.5 被先归档）。
        if (m.get("tier") == "working" and imp_val < 0.3
                and m.get("thermal") == "cold" and age > stale_days * 2):
            can_archive = False  # 让 v30 demote 处理，不归档
            # 是否过期（归档候选）：
            # - 基础门槛：超 stale_days 且访问次数 ≤1（≈旧版「未被真正用过」）→ 过期
            # - 衰减续命：访问 ≥2 次时改看 relevance；低于地板（0.05）才算真正过期。
            # 这样高频使用的 project/ephemeral 能跨过 90 天继续存活，符合"越用越聪明"。
        access_n = _acc(m)  # 5.0/A1：改读单一热源
        if age > stale_days and not referenced and m.get("tier") != "curated":
            if access_n <= 1:
                is_stale = True
            else:
                is_stale = _relevance(m, _lam, _acc(m)) < 0.05
            findings["stale"].append({"id": m["id"], "age_days": age, "scope": sc,
                                      "access_count": access_n,
                                      "relevance": round(_relevance(m, _lam, _acc(m)), 4),
                                      "will_archive": bool(auto and auto_archive and can_archive and is_stale)})
            if auto and auto_archive and can_archive and is_stale:
                if _archived_this_run >= _archive_quota:  # #10：配额已满，跳过本轮归档
                    continue
                _archived_this_run += 1
                m.setdefault("accessed_from", []).append({
                    "action": "auto_archive", "by": "reflect_auto",
                    "reason": "stale age_days=%d relevance=%.4f" % (age, _relevance(m, _lam, _acc(m))),
                    "date": today()})
                if len(m["accessed_from"]) > 12:
                    del m["accessed_from"][:len(m["accessed_from"]) - 12]
                _save_mem(root, m["id"], m)  # 先落盘触发标记，再归档搬迁
                archive(root, m["id"])

                # 3.5) 种子态生命周期（自主沉积护栏）：seed = 待观察的低置信记忆。
                # 被使用/被肯定 → 晋升 working（进入常规召回加权）；
                # 长期从未被用 → 自动归档清理，不让无用的自主沉积污染库（错/无用的自己会死）。
    for m in mems.values():
        if m.get("tier") != "seed" or m.get("status") != "active":
            continue
        access_n = _acc(m)  # 5.0/A1：改读单一热源
        try:
            cd = datetime.date.fromisoformat(m.get("accessed") or m.get("created") or today())
        except Exception:
            cd = today_dt
        age = (today_dt - cd).days
        has_good = any((a.get("action") in ("feedback_good", "calibrated_up"))
                       for a in (m.get("accessed_from") or []))
        if access_n >= 2 or (has_good and access_n >= 1):
            # 被使用/被肯定 → 晋升 working
            findings["promote_candidates"].append({"id": m["id"], "reason": "seed_proven"})
            if auto:
                m["tier"] = "working"
                m.setdefault("accessed_from", []).append({
                    "action": "auto_promote", "by": "reflect_auto",
                    "tier": "working", "reason": "seed_proven", "date": today()})
                if len(m["accessed_from"]) > 12:
                    del m["accessed_from"][:len(m["accessed_from"]) - 12]
                _save_mem(root, m["id"], m)
        elif age > 30 and access_n == 0:
            # 候选过期：从未被用 → 自动归档清理
            findings["stale"].append({"id": m["id"], "age_days": age, "tier": "seed",
                                      "access_count": 0,
                                      "will_archive": bool(auto and auto_archive)})
            if auto and auto_archive:
                if _archived_this_run >= _archive_quota:  # #10：配额已满，跳过本轮归档
                    continue
                _archived_this_run += 1
                m.setdefault("accessed_from", []).append({
                    "action": "auto_archive", "by": "reflect_auto",
                    "reason": "seed_expired age_days=%d" % age, "date": today()})
                if len(m["accessed_from"]) > 12:
                    del m["accessed_from"][:len(m["accessed_from"]) - 12]
                _save_mem(root, m["id"], m)
                archive(root, m["id"])

                # 4) 晋升候选：
                # 4a) 被多处 see_also 引用（多记忆交叉印证 → 重要）
    indeg = {}
    for o in mems.values():
        for t in o.get("relations", {}).get("see_also", []):
            indeg[t] = indeg.get(t, 0) + 1
    for mid, cnt in indeg.items():
        if cnt >= 2 and mems.get(mid, {}).get("tier") in ("working", None):
            findings["promote_candidates"].append({"id": mid, "in_degree": cnt, "reason": "referenced"})
            if auto:
                m2 = mems[mid]
                m2["tier"] = "curated"
                m2.setdefault("accessed_from", []).append({
                    "action": "auto_promote", "by": "reflect_auto",
                    "tier": "curated", "reason": "referenced", "date": today()})
                if len(m2["accessed_from"]) > 12:
                    del m2["accessed_from"][:len(m2["accessed_from"]) - 12]
                _save_mem(root, mid, m2)
                # 4b) 频率驱动晋升（"HOT 自动升级"）：
                # 7 天内被真正使用 ≥3 次的工作记忆，自动晋升 curated（"越用越聪明"自动上浮，
                # 让重要模式无需手动 promote 就被召回加权）。仅升到 curated（按需加权），
                # 不动 core（core=始终加载，需人工确认，避免上下文膨胀）——与同类方案的安全原则对齐。
                # "写入 HOT 前需确认"的安全原则对齐。
    for m in mems.values():
        if m.get("status") != "active" or m.get("tier") != "working":
            continue
        ru = _recent_access_count(m, 7)
        if ru >= 3:
            findings["promote_candidates"].append(
                {"id": m["id"], "reason": "frequent_use", "recent_uses": ru})
            if auto:
                m["tier"] = "curated"
                m["accessed"] = today()
                m.setdefault("accessed_from", []).append({
                    "action": "auto_promote", "by": "reflect_auto",
                    "tier": "curated", "reason": "frequent_use", "date": today()})
                if len(m["accessed_from"]) > 12:
                    del m["accessed_from"][:len(m["accessed_from"]) - 12]
                _save_mem(root, m["id"], m)

                # 4.5) 置信度校准闭环（Beta 后验）：召回加权依赖 confidence，长期不准会污染排序。
                # - 被多处 see_also 引用印证（重要）→ 隐式 good 信号（alpha+1）；
                # - 长期未被推翻（创建/更新>90 天、被用过≥1 次、未被纠正）→ 弱 good（alpha+0.4）；
                # - 被纠正取代的记忆已在 deposit 的 corrects 分支下调（Beta beta 大幅+）。
                # 只在 auto 模式写盘；统计进 meta.calibration 供观察。
    if auto:
        raised = 0
        for m in mems.values():
            if m.get("status") != "active":
                continue
            cid = m["id"]
            ref_n = indeg.get(cid, 0)
            try:
                upd = datetime.date.fromisoformat(m.get("updated") or m.get("created") or today())
            except Exception:
                upd = datetime.date.today()
            long_uncontested = (datetime.date.today() - upd).days > 90
            corrected = m.get("relations", {}).get("corrected_by")
            if ref_n >= 2 or (long_uncontested and not corrected
                              and _acc(m) >= 1):
                _ensure_beta(m)
                w = 1.0 if ref_n >= 2 else 0.4
                before = m.get("confidence")
                _apply_signal(m, "good", weight=w)
                if m.get("confidence") > before:
                    _af_u = m.setdefault("accessed_from", [])
                    # 幂等（2026-09-15 审计）：同日重复 reflect 不再重复记同一条 beta 上调
                    # （旧实现会累积同日重复；真库实测净冗余 5 条）。
                    if not (_af_u and isinstance(_af_u[-1], dict)
                            and _af_u[-1].get("action") == "calibrated_up"
                            and _af_u[-1].get("date") == today()):
                        _af_u.append({"action": "calibrated_up", "date": today(),
                                      "via": "beta"})
                        if len(_af_u) > 12:
                            del _af_u[:len(_af_u) - 12]
                    _save_mem(root, cid, m)
                    raised += 1
        meta = _load_meta(root)
        meta.setdefault("calibration", {"n_lowered": 0, "n_raised": 0})
        meta["calibration"]["n_raised"] = meta["calibration"].get("n_raised", 0) + raised
        _save_meta(root, meta)
        findings["calibration"] = {"raised": raised,
                                   "decay_lambda": meta.get("decay_lambda"),
                                   "decay_fitted": meta.get("decay_fitted")}

        # 5) 相似记忆连边候选（P0-B）：把「主题相关但未连边」的记忆对找出来供 AI/用户导航；
        # auto=True 时批量建立双向边（_apply_link_candidates：内存聚合+pending 写回，
        # 每唯一记忆只落盘一次，幂等，已连的不重复）。纯只读扫描（标签预分组 + _sim），
        # 不写盘，除非 auto。
    link_cands = _find_link_candidates(root)
    findings["link_candidates"] = link_cands
    if auto:
        _apply_link_candidates(root, link_cands, mems)

        # 6) AAR 复盘链（P2-E）：检测「error/correction → best_practice」学习闭环
        # （经 corrected_by / related_to / see_also 关联），输出可吸收的经验摘要。
        # 纯只读、不写盘、不递归（绝不自动 deposit，避免自我循环）。
    findings["aar"] = _detect_aar_chains(mems)

    # 7) 上下文预算预警（P1-C）：total token 超预算时标记 context_full 并建议 reflect
    if context_budget is not None:
        total = sum(token_estimate(m) for m in mems.values())
        if total > context_budget:
            findings["context_full"] = True
            findings.setdefault("recommendations", []).append(
                "上下文接近预算（%d/%d token），建议运行 reflect --auto 归档过期记忆并沉淀重点。"
                % (total, context_budget))

    _sync_index(root)
    # 记录上次 reflect（含非 auto 的手工整理），供自动化调度幂等判断（#3）
    try:
        _m = _load_meta(root)
        _m["last_reflect"] = today()
        _save_meta(root, _m)
        # 衰减个性化提示（#4 增强）：拟合后提示半衰期≈X 天，便于用户调参
        _lam = _m.get("decay_lambda", 0.03)
        _hl = math.log(2) / _lam if _lam > 0 else float("inf")
        findings["decay_hint"] = {
            "lambda": _lam,
            "half_life_days": round(_hl, 1),
            "fitted": _m.get("decay_fitted", False),
            "n_samples": _m.get("n_decay_samples", 0),
            "message": "📉 衰减自适应：半衰期≈%.1f 天（λ=%.5f，拟合样本=%d，%s）" % (
                _hl, _lam, _m.get("n_decay_samples", 0),
                "已按真实访问间隔拟合" if _m.get("decay_fitted")
                else "样本不足/无样本，暂用先验默认 0.03"),
        }
    except Exception:
        pass
        # #8 可选 LLM 自进化（安全版）：内容冻结，只出建议、绝不改写记忆；
        # 未启用（config 关闭且未传 --llm）则 _reflect_llm 直接返回未启用，规则 reflect 不受影响。
    try:
        _llm_cfg = _load_llm_config(root)
        if llm:  # 显式 --llm：即使 config 关闭也临时启用（仍内容冻结）
            _llm_cfg = dict(_llm_cfg)
            _llm_cfg["enabled"] = True
        findings["llm"] = _reflect_llm(root, mems=mems, cfg=_llm_cfg)
        # 改进 P0-3：LLM 建议 auto-apply 安全子集（link/note）
        # 仅当 LLM 启用且 config.auto_apply_safe=True 时，自动应用 link（双向连边）和
        # note（追加观察笔记），其余建议仅落盘 llm_suggestions.json 供人工审阅。
        _llm_out = findings.get("llm", {})
        if _llm_out.get("enabled") and _llm_cfg.get("auto_apply_safe", True):
            _sugs = _llm_out.get("suggestions", [])
            if _sugs:
                _apply_result = _auto_apply_safe_suggestions(root, _sugs)
                _llm_out["auto_applied"] = _apply_result
                findings["llm"] = _llm_out
    except Exception as e:
        findings["llm"] = {"enabled": False, "error": "llm block crashed: %s" % e}
    return findings

def reflect(root, auto=False, stale_days=90, auto_archive=True, context_budget=None, llm=False, undo=False):
    """reflect 公共入口——Bug-1/Bug-4 修复：加 per-root 线程锁，与 deposit 串行化。

    reflect 内部 load_index → 修改 → save_index 是非原子 read-modify-write，
    与并发 deposit 的 save_index 互相覆盖会丢索引条目（W4-C2 复现）。
    RLock 可重入，reflect 内部若间接调用 deposit 也不会死锁。
    undo=True 时改走 reflect_undo_auto（撤销自动重分类，见 §4 gap #4）。
    """
    if undo:
        return reflect_undo_auto(root)
    with _get_deposit_lock(root):
        return _reflect_impl(root, auto=auto, stale_days=stale_days,
                             auto_archive=auto_archive, context_budget=context_budget,
                             llm=llm)

def reflect_undo_auto(root, dry_run=False):
    """§4 gap #4：撤销 reflect --auto 的自动重分类（category/type 改写）。

    扫描全部记忆的 accessed_from，找到 auto_reclassify_type 记录，将 category/type
    回滚到该记录记录的 from 值（移除该条记录，可多次撤销逐步回退历史），并记
    undo_auto_reclassify 审计条目。仅回退分类，不触及 archive 状态
    （归档撤销范围外，避免误复活已归档记忆）。
    返回 {ok, reverted:[{id, from, to}], count, dry_run}。"""
    root_abs = os.path.abspath(root or _default_root())
    mems = _all_mems(root_abs)
    reverted = []
    for mid, m in mems.items():
        af = m.get("accessed_from") or []
        if not isinstance(af, list):
            continue
            # 找最近一条 auto_reclassify_type 记录
        last = None
        for e in af:
            if isinstance(e, dict) and e.get("action") == "auto_reclassify_type":
                last = e
        if not last:
            continue
        frm = last.get("from")
        if frm is None:
            continue
        cur = m.get("type") or m.get("category", "")
        if cur == frm:
            continue  # 已回到原值，无需回退
        if not dry_run:
            m["category"] = frm
            m["type"] = frm
            # 移除该条 auto_reclassify_type（逐步回退，可多次撤销）
            try:
                af.remove(last)
            except ValueError:
                pass
            m.setdefault("accessed_from", []).append({
                "action": "undo_auto_reclassify", "by": "user",
                "from": cur, "to": frm, "original_action_date": last.get("date"),
                "date": today(),
            })
            if len(m["accessed_from"]) > 12:
                del m["accessed_from"][:len(m["accessed_from"]) - 12]
            _save_mem(root_abs, mid, m)
        reverted.append({"id": mid, "from": frm, "to": cur})
    return {"ok": True, "reverted": reverted, "count": len(reverted), "dry_run": dry_run}

def _reclassify_lowconf_v30(root, mems, chat, today_d):
    """P2 · reflect 重分类（修「分类判断能力脆弱」）。

    候选：active 记忆中「存置信度<0.6」或「规则分类与现存类型高置信(≥0.7)冲突」者。
    每条让 LLM 复核；LLM 给的类型≠现存且 conf≥RECLASSIFY_MIN_CONF 且重要性<0.9 → 改写
    category/type 并记审计（accessed_from）。importance≥0.9 安全闸：用户显式重要不改。
    每轮封顶 RECLASSIFY_LLM_CAP 条，避免大库 O(n) LLM 失控。无 LLM 时 caller 不调用本函数。
    P1-2：增量标记 recl_checked_at——7天内已检查的记忆跳过，避免每次 reflect 全量重扫。"""
    RECL_CHECK_INTERVAL = 7  # 天：已检查的记忆 7 天内不重复检查
    cands = []
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        if (m.get("importance") or 0.0) >= 0.9:
            continue  # 用户显式重要，安全闸
            # P1-2：跳过近期已检查的记忆
        last_recl = m.get("recl_checked_at")
        if last_recl:
            last_d = _parse_iso_date(last_recl)
            if last_d and (today_d - last_d).days < RECL_CHECK_INTERVAL:
                continue
        stored_type = _normalize_type(m.get("category", "") or m.get("type", ""))
        low_conf = float(m.get("confidence", 1.0) or 1.0) < 0.6
        # A1：type_confidence<0.5 也纳入重审候选（分类置信度低的重审机会）
        low_type_conf = float(m.get("type_confidence", 1.0) or 1.0) < 0.5
        rule_type, rule_conf, _ = classify_type(m.get("summary", ""),
                                                 body=m.get("body", ""),
                                                 tags=m.get("tags", []))
        rule_conflicts = (rule_conf >= 0.7 and rule_type != stored_type)
        if low_conf or low_type_conf or rule_conflicts:
            cands.append((mid, m, stored_type))
    cands = cands[:RECLASSIFY_LLM_CAP]
    out = []
    for mid, m, stored_type in cands:
        res = _classify_type_llm(root, m.get("summary", ""), m.get("body", ""),
                                 m.get("tags", []), chat)
        # P1-2：无论 LLM 是否改写，都标记已检查（避免下次重复送 LLM）
        m["recl_checked_at"] = today_d.isoformat()
        if not res:
            _save_mem(root, mid, m)
            continue
        new_type, conf, reason = res
        if new_type == stored_type or conf < RECLASSIFY_MIN_CONF:
            _save_mem(root, mid, m)
            continue
        m["category"] = new_type
        m["type"] = new_type
        m["type_confidence"] = conf  # v3.2.1 A1：重分类后回填 type_confidence
        m.setdefault("accessed_from", []).append({
            "action": "v30_reclassify", "by": "reflect_v30",
            "from": stored_type, "to": new_type,
            "conf": conf, "reason": reason, "date": today_d.isoformat()})
        _save_mem(root, mid, m)
        # #19 修复：自动纠正也学习 tag→type 先验（弱于显式纠正，weight=2）
        _clf_model = _clf.load_model(root)
        _clf.learn_type(_clf_model, m.get("tags", []), new_type, weight=2)
        _clf.save_model(root, _clf_model)
        out.append({"id": mid, "from": stored_type, "to": new_type,
                    "conf": conf, "reason": reason})
    return out

def cross_type_merge_candidates(root, sim=0.60, dry_run=True):
    """ A3 · 跨类型合并候选检测（advisory，不强合并）。

    同义但不同 type 的记忆（如 BP vs PF 表达同一禁忌）写前查重按相似度漏合并，
    此处跨类型聚类识别出候选对，由用户/LLM 决定是否合并。O(n²) 相似度，
    仅供周期性 reflect（非每轮）。返回 {pairs:[...]}。"""
    am = {k: v for k, v in _all_mems(root).items() if v.get("status") == "active"}
    ids = list(am.keys())
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = am[ids[i]], am[ids[j]]
            if a.get("type") == b.get("type"):
                continue  # 同类型由 reflect 内部去重/合并处理
            if a.get("relations", {}).get("generalized_by") or \
               b.get("relations", {}).get("generalized_by"):
                continue  # 已是某规则的被吸收成员，跳过
            s = _similarity((a.get("summary", "") + " " + a.get("body", "")),
                            (b.get("summary", "") + " " + b.get("body", "")))
            if s >= sim:
                pairs.append({"a": ids[i], "b": ids[j],
                              "a_type": a.get("type"), "b_type": b.get("type"),
                              "similarity": round(s, 4)})
    return {"pairs": pairs}

def _detect_aar_chains(mems):
    """检测「踩坑→纠正→沉淀最佳实践」学习链，输出 AAR 复盘摘要（只读、不写盘）。

    链路判定：一条 best_practice / correction 记忆，若其 `corrected_by` 或 `related_to`
    或 `see_also` 指向某条 error/correction（即「它解决/关联了一个坑」），则构成一条
    AAR 闭环。中间节点缺失（如 correction 已被删/归档）时优雅跳过，不崩溃。
    """
    out = []
    by_id = mems
    for m in mems.values():
        if m.get("status") != "active":
            continue
        cat = m.get("category")
        if cat not in ("best_practice", "correction"):
            continue
        rels = m.get("relations", {}) or {}
        triggers = set()
        # 关系字段可能是标量字符串（corrected_by/superseded_by 由 deposit 存为标量）
        # 也可能是列表（related_to/see_also），统一归一为可迭代
        for key in ("corrected_by", "superseded_by", "related_to", "see_also"):
            v = rels.get(key)
            if not v:
                continue
            if isinstance(v, str):
                triggers.add(v)
            else:
                triggers.update(v)
        for tid in triggers:
            t = by_id.get(tid)
            if not t:
                continue
                # trigger（踩坑/旧结论）可能是 superseded（被本记忆纠正）——这正是最有价值的
                # AAR 闭环（坑已被解决），故不要求 trigger 为 active，只要求它存在且类别匹配。
            if t.get("category") in ("error", "correction"):
                lesson = (m.get("summary") or "") or (m.get("body") or "")[:80]
                out.append({
                    "trigger": tid, "trigger_summary": t.get("summary", ""),
                    "resolution": m["id"], "resolution_summary": m.get("summary", ""),
                    "lesson": lesson,
                    "chain": "error→%s" % cat,
                })
    return out

