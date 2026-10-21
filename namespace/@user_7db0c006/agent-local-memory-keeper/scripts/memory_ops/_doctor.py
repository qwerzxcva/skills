# Auto-extracted submodule: _doctor
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _repair_json_text(raw: str):
    """A2 ：best-effort 修复损坏的 JSON 记忆文本。返回 (ok, text)。
    
    仅处理**常见机械性损坏**，绝不臆造内容：
      - 剥离非法尾随逗号（',' 紧邻 } 或 ] 之前）
      - 删除 ASCII 控制字符（\\x00-\\x1f 除 \\n/\\t/\\r 外）
      - 截断体（末级对象缺闭合 }）：尝试补一个 } 让结构闭合
    修复后必须能 json.loads 且含 id 字段才算成功；否则 (False, raw) 保留原文。
    """
    import re
    if not isinstance(raw, str):
        return False, raw
    candidate = raw
    # 1) 控制字符
    candidate = "".join(ch for ch in candidate
                        if ch in ("\n", "\t", "\r") or ord(ch) >= 0x20)
    # 2) 尾随逗号（在 } 或 ] 之前的 ,）
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
    # 3) 截断修复：若看起来缺闭合，尝试补 }
    try:
        json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        if candidate.count("{") > candidate.count("}"):
            candidate2 = candidate.rstrip() + "}"
            try:
                json.loads(candidate2)
                candidate = candidate2
            except (json.JSONDecodeError, ValueError):
                pass
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict) and obj.get("id"):
            return True, candidate
    except (json.JSONDecodeError, ValueError):
        pass
    return False, raw

def _restore_corrupt_file(root: str, fname: str):
    """A2 ：把 corrupt/ 里指定文件接回 memories/。返回 (ok, msg)。
    接回后做 JSON 合法性校验；不合法则保留在 corrupt/ 并警告。"""
    md = mem_dir(root)
    for cd in (os.path.join(md, "corrupt"), os.path.join(archive_dir(root), "corrupt")):
        src = os.path.join(cd, fname)
        if not os.path.isfile(src):
            continue
        # 校验内容合法性
        try:
            with open(src, encoding="utf-8") as _f:
                obj = json.load(_f)
            if not isinstance(obj, dict) or not obj.get("id"):
                return False, "内容非合法记忆 JSON（缺 id），已保留在 corrupt/ 待人工修复"
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as _e:
            return False, "内容仍无法解析（%s），已保留在 corrupt/ 待人工修复" % type(_e).__name__
        dst = os.path.join(md, fname)
        try:
            shutil.move(src, dst)
            return True, "已接回 memories/%s" % fname
        except OSError as _e:
            return False, "接回失败：%s" % _e
    return False, "corrupt/ 中找不到 %s" % fname

def _recompute_importance_from_recall(root, max_backfill=None):
    """B5：周期性按召回频次幂等重算 importance（先验 + 频次加权，不累积、可重复跑）。
    遍历全部 active 记忆：
      - 被召回过：importance = clamp(prior + 0.3·freq_score) → 频繁者稳定升温；
      - 零召回：回到先验（仅当当前高于先验才冷却，避免无谓重写）→ 长期不被召回自然降温。
    仅在实际变化时才写盘，未变化的记忆不重写。返回实际改动的记忆数。"""
    p = _recall_counts_path(root)
    counts = {}
    try:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as _f:
                counts = json.load(_f) or {}
    except Exception:
        counts = {}
    max_c = max((int(v.get("count", 0)) for v in counts.values()), default=1) or 1
    mems = _all_mems(root)
    changed = 0
    done = 0
    for mid, m in mems.items():
        if max_backfill is not None and done >= max_backfill:
            break
        if m.get("status") != "active":
            continue
        prior = _default_importance(m.get("category", ""), m.get("scope", "universal"))
        cnt = int((counts.get(mid) or {}).get("count", 0))
        freq = math.log(1 + cnt) / math.log(1 + max_c) if max_c > 0 else 0.0
        new_imp = max(0.0, min(1.0, prior + 0.3 * freq))
        cur = float(m.get("importance", prior) or prior)
        # 零召回（freq=0 → new_imp=prior）：仅当当前高于先验才冷却回先验，避免无谓重写
        if abs(new_imp - cur) <= 1e-6:
            done += 1
            continue
        m["_importance_prev"] = cur  # P1-3：保留回退值，便于撤销本次重要性重算
        m["importance"] = round(new_imp, 4)
        try:
            _save_mem(root, mid, m)
            changed += 1
        except Exception:
            pass
        done += 1
    return changed

def _index_content_sig(d):
    """内容签名：对 index entry 与记忆文件用同一规则取值，可直接相等比较。"""
    return tuple(
        json.dumps(d.get(k, []), ensure_ascii=False, sort_keys=True) if k == "tags"
        else str(d.get(k, ""))
        for k in _INDEX_CONTENT_FIELDS
    )

def report(root):
    """#4 校准可视化 + 衰减自适应可读摘要（meta.calibration / decay / last_reflect / 记忆概览）。
    
    把分散在 meta.json 里的「置信度校准计数」「衰减 λ/半衰期」「上次 reflect」聚合成
    一份人/机都可读的摘要，免去手动翻 meta.json。返回 dict；CLI 打印 JSON（含 readable
    字段）。纯只读，不写盘。"""
    meta = _load_meta(root)
    mems = _all_mems(root)
    # P5：盲区检测与域概览改用 taxonomy 自定义域；无 taxonomy 文件时退化为 的
    # KNOWN_DOMAINS 兜底（default_taxonomy 即等价于 4 已知域）。盲区只统计用户「显式」域
    # （taxonomy.domains）；fallback_domain 是兜底筐，未匹配记忆存为 domain=None，其覆盖
    # 情况由「域分布」里的 none 体现，不列入「待填充」盲区，避免误报。
    _tax = load_taxonomy(root)
    _tax_custom = os.path.exists(_taxonomy_path(root))
    _domain_keys = list(taxonomy_domain_keys(_tax))
    # ：report 回显 embedding 后端状态与国内镜像适配情况
    backend = _emb_backend()
    hf_endpoint = os.environ.get("HF_ENDPOINT", "")
    using_mirror = "hf-mirror" in hf_endpoint
    # B2 修复（假绿灯）：report 必须反映「实际后端是否真用了语义」，而非仅凭 HF_ENDPOINT
    # 含 hf-mirror 就报绿。配置神经/auto 却落到 lexical 即视为降级——此时即便显示
    # 「已走镜像」也必须追加降级告警，避免「验收显示绿灯、实际已降级」的假绿灯（与
    # _doctor_embed_backend 的 fell_back_to_lexical 同口径）。
    try:
        _cfg_backend = (_load_keeper_config().get("embed_backend") or "fastembed").lower()
    except Exception:
        _cfg_backend = "fastembed"
    _fell_back = (_cfg_backend in ("auto", "fastembed", "neural", "sentence_transformers")
                  and backend == "lexical")
    _fell_back_note = ("；⚠️ 已降级为词法级（语义模型不可用，召回质量下降；"
                       "修复：pip install fastembed 或设 AI_MEM_EMBED_BACKEND=online）"
                       if _fell_back else "")
    # ：缓存目录以 embed._fastembed_cache_dir 为唯一事实源（默认已迁到
    # ~/.workbuddy/cache/agent-local-memory-keeper/models，在 skill 目录之外），避免
    # 误报「未缓存」；embed 不可用时回退旧路径做兼容显示。
    try:
        cache_dir = _emb._fastembed_cache_dir()
    except Exception:
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "fastembed")
    model_cached = os.path.isdir(cache_dir) and any(
        os.path.isdir(os.path.join(cache_dir, d)) for d in os.listdir(cache_dir)
    ) if os.path.isdir(cache_dir) else False
    by_tier = {}
    by_type = {}                                 # v3.2.1 A4：类型分布
    by_domain = {}                               # v3.2.1 A4：域分布
    type_domain = {}                             # v3.2.1 A4：(type, domain) 覆盖矩阵
    eff_heat_sum = {}                            # v3.2.1 B3：按类型累计有效热度（衰减后）
    superseded = archived = 0
    _now = datetime.date.today()
    for m in mems.values():
        t = m.get("tier", "working")
        by_tier[t] = by_tier.get(t, 0) + 1
        st = m.get("status")
        if st == "superseded":
            superseded += 1
        elif st == "archived":
            archived += 1
        # A4/B3 覆盖与有效热度统计
        ty = m.get("type", "FACT")
        by_type[ty] = by_type.get(ty, 0) + 1
        dm = m.get("domain") or "none"
        by_domain[dm] = by_domain.get(dm, 0) + 1
        type_domain[(ty, dm)] = type_domain.get((ty, dm), 0) + 1
        last = _parse_date(m.get("accessed", ""))
        age = (_now - last).days if last else 365
        age = age if age < 10 ** 8 else 365
        eff = float(m.get("importance", 0.5) or 0.5) * (2.7 ** (-0.03 * age))
        eff_heat_sum.setdefault(ty, [0.0, 0])
        eff_heat_sum[ty][0] += eff
        eff_heat_sum[ty][1] += 1
    lam = meta.get("decay_lambda", 0.03)
    fitted = meta.get("decay_fitted", False)
    half_life = math.log(2) / lam if lam > 0 else float("inf")
    cal = meta.get("calibration", {"n_lowered": 0, "n_raised": 0})
    n_lowered = cal.get("n_lowered", 0)
    n_raised = cal.get("n_raised", 0)
    total = len(mems)
    readable = (
        "=== 记忆系统健康摘要 ===\n"
        "记忆总数：%d（active=%d，已归档=%d，已取代(superseded)=%d）\n"
        "分层：%s\n"
        "语义召回后端：%s%s%s%s\n"
        "置信度校准闭环：上调 %d 次 / 下调 %d 次（净 %+d）\n"
        "衰减自适应：λ=%.5f，半衰期≈%.1f 天，拟合样本=%d（%s）\n"
        "上次 reflect：%s"
        % (total, by_tier.get("working", 0) + by_tier.get("curated", 0)
           + by_tier.get("core", 0), archived, superseded,
           "，".join("%s=%d" % (k, v) for k, v in sorted(by_tier.items())),
           backend,
           "（已走国内镜像 hf-mirror.com）" if using_mirror else "",
           "；模型已缓存" if model_cached else "；模型未缓存，首次语义召回会自动下载（约 50MB）",
           _fell_back_note,
           n_raised, n_lowered, n_raised - n_lowered,
           lam, half_life, meta.get("n_decay_samples", 0),
           "已按真实访问间隔拟合" if fitted else "样本不足/无样本，暂用先验默认 0.03",
           meta.get("last_reflect") or "从未")
    )
    # A4 覆盖盲区 + B3 有效热度概览
    # P5：盲区基于 taxonomy 自定义域（或 KNOWN_DOMAINS 兜底），让用户看到「自己的树」哪里空。
    blind = [d for d in _domain_keys if by_domain.get(d, 0) == 0]
    extra = (
        "\n类型分布：%s\n"
        "域分布：%s\n"
        "有效热度（衰减后均值）：%s\n"
        % (",".join("%s=%d" % (k, v) for k, v in sorted(by_type.items())),
           ",".join("%s=%d" % (k, v) for k, v in sorted(by_domain.items())),
           ",".join("%s=%.2f" % (k, eff_heat_sum[k][0] / max(1, eff_heat_sum[k][1]))
                    for k in sorted(eff_heat_sum)))
    )
    # P5：用户有自定义分类树时，把「自己的树」直接渲染进摘要（替代通用 4 筐视角）。
    if _tax_custom:
        _tree = []
        for d in _tax.get("domains", []):
            subs = d.get("subdomains") or []
            _tree.append("%s%s" % (d["key"],
                                   (" → " + "/".join(s["key"] for s in subs)) if subs else ""))
        extra += "你的分类树（taxonomy）：%s\n" % " ｜ ".join(_tree)
    if blind:
        extra += "⚠ 覆盖盲区（0 记忆的域）：%s\n" % ", ".join(blind)
    readable = readable + extra
    # P1-5a 元记忆：把当前召回信号权重落盘 meta.json，使「为什么这么排」可审计、可纠
    strategy = get_recall_strategy(root)
    meta["recall_strategy"] = {k: v for k, v in strategy.items() if k != "_overridden"}
    meta["recall_strategy_overridden"] = strategy.get("_overridden", {})
    try:
        _save_meta(root, meta)
    except Exception as e:
        # P2 修复：meta.json 保存失败不静默——衰减参数丢失会导致下次 reflect 用默认 λ
        import sys as _sys
        _sys.stderr.write("[⚠ reflect] meta.json 保存失败: %s（衰减参数未落盘）\n" % e)
    return {
        "total": total,
        "by_tier": by_tier,
        "by_type": by_type,                       # v3.2.1 A4 类型分布
        "by_domain": by_domain,                   # v3.2.1 A4 域分布
        "type_domain": {("%s|%s" % k): v for k, v in type_domain.items()},  # A4 覆盖矩阵
        "effective_heat": {k: round(v[0] / max(1, v[1]), 3)
                           for k, v in eff_heat_sum.items()},  # B3 有效热度
        "blind_spots": [d for d in _domain_keys if by_domain.get(d, 0) == 0],  # v3.5 P5：taxonomy 域（或 KNOWN_DOMAINS 兜底）
        "superseded": superseded,
        "archived": archived,
        "calibration": {
            "n_lowered": n_lowered,
            "n_raised": n_raised,
            "net": n_raised - n_lowered,
        },
        "decay": {
            "lambda": lam,
            "fitted": fitted,
            "n_samples": meta.get("n_decay_samples", 0),
            "half_life_days": round(half_life, 1),
        },
        "embed": {
            "backend": backend,
            "configured_backend": _cfg_backend,
            "fell_back_to_lexical": _fell_back,   # B2：实际是否降级（不止看 using_mirror）
            "using_mirror": using_mirror,
            "hf_endpoint": hf_endpoint or "default",
            "model_cached": model_cached,
        },
        "last_reflect": meta.get("last_reflect"),
        "recall_strategy": meta["recall_strategy"],
        "recall_strategy_overridden": meta["recall_strategy_overridden"],
        "readable": readable,
    }

def summary_index(root, max_lines=50):
    """ 架构图 Layer2「summary_index」：紧凑路由视图（替代/补充 report 的域分布）。
    输出 `domain|subdomain|count|最新摘要(一行)|关键词hints|last_updated`，全库目标 <50 行。
    作用：让 Agent 在 recall 前先「看路由表」判断该去哪个域/子域找，避免无差别全量扫。
    有 taxonomy 时用其域/子域结构组织（无则不强制）；盲区由 report() 的 blind_spots 负责。
    纯只读，不写盘。"""
    mems = _all_mems(root)
    groups = {}
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        dom = m.get("domain") or "none"
        sub = m.get("subdomain") or "-"
        key = (dom, sub)
        g = groups.setdefault(key, {"count": 0, "latest": "", "last": "", "hints": []})
        g["count"] += 1
        ac = m.get("accessed") or ""
        if ac > g["last"]:
            g["last"] = ac
            g["latest"] = (m.get("summary") or "")[:40]
        for t in (m.get("tags") or []):
            if t.startswith("sub:"):
                continue
            if t not in g["hints"] and len(g["hints"]) < 8:
                g["hints"].append(t)
    lines = []
    for (dom, sub), g in sorted(groups.items()):
        lines.append("%s|%s|%d|%s|%s|%s" % (
            dom, sub, g["count"], g["latest"], ",".join(g["hints"]), g["last"]))
    if len(lines) > max_lines:
        truncated = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append("...（截断，余 %d 行；用 tree-view 看完整结构）" % truncated)
    readable = ("=== 路由索引 summary_index（domain|subdomain|count|最新摘要|关键词hints|last_updated）===\n"
                + "\n".join(lines) if lines else
                "=== 路由索引 summary_index ===\n（库为空或暂无 active 记忆）")
    return {"ok": True, "lines": lines, "total_groups": len(groups), "readable": readable}

def tree_view(root):
    """ 架构图 Layer3「tree_view」：冷存储树形可视化（domain → subdomain → topic）。
    让人一眼看清记忆库结构，定位空白/冗余分支；topic 取 pattern_key 前缀或 category。
    纯只读，不写盘。"""
    mems = _all_mems(root)
    tree = {}
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        dom = m.get("domain") or "none"
        sub = m.get("subdomain") or "-"
        topic = m.get("pattern_key") or m.get("category") or "uncategorized"
        tree.setdefault(dom, {}).setdefault(sub, {}).setdefault(topic, 0)
        tree[dom][sub][topic] += 1
    lines = ["=== 冷存储树 tree_view（domain → subdomain → topic[×count]）==="]
    for dom in sorted(tree):
        dtot = sum(tree[dom][s][t] for s in tree[dom] for t in tree[dom][s])
        lines.append("%s/  (%d)" % (dom, dtot))
        for sub in sorted(tree[dom]):
            stot = sum(tree[dom][sub][t] for t in tree[dom][sub])
            lines.append("  ├─ %s/  (%d)" % (sub, stot))
            for topic in sorted(tree[dom][sub]):
                lines.append("  │   ├─ %s  ×%d" % (topic, tree[dom][sub][topic]))
    return {"ok": True, "readable": "\n".join(lines)}

def promote_auto(root, dry_run=True, min_recurrence=3, min_relevance=0.6,
                 min_access=5, min_age_days=30, promote_tier="curated",
                 merge=True, top_n=50):
    """ 自主晋升 + 自主合并（自判断决策，无需人确认）。
    设计依据：晋升/合并属「记忆整理」而非安全操作——archive 可 unarchive 找回、tier 可逆，
    故让 keeper 自己按启发式判断并行动，减少人确认负担（呼应「问题」第④条诉求）。
    启发式（可解释、诚实标注，每条决策附 reasons）：
      - 晋升候选 = active 且 tier∈{working,seed}：
          * 重复簇 recurrence_count≥min_recurrence → 该模式「值得固化」→ 晋升簇内最佳；
          * 或 (relevance_score≥min_relevance 或 importance≥min_relevance)
                且 access_count≥min_access 且 龄期(created)≥min_age_days。
      - 合并：同一 pattern_key 簇只留最佳，其余 supersede→archive（沉底不销毁，可找回）。
    默认 dry_run=True 只出决策报告；传 dry_run=False（CLI --apply）才落盘，仍保留 decisions 审计。
    该自判断引擎同时被 T78（IMA 永久储备）复用：复用同一套「是否值得固化/外迁」的判断。"""
    mems = _all_mems(root)
    _acounts = _load_recall_counts(root)  # 5.0/A1：晋升筛选改读单一热源（原字段恒 0 → 恒空）
    today = datetime.date.today()

    def _age_days(m):
        c = _parse_date(m.get("created") or m.get("first_seen") or "")
        return (today - c).days if c else 9999

    def _rel(m):
        r = m.get("relevance_score")
        if isinstance(r, (int, float)):
            return float(r)
        return float(m.get("importance") or 0.5)

    clusters = {}
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        if m.get("tier") in ("curated", "core"):
            continue
        pk = m.get("pattern_key") or ("_single_" + mid)
        clusters.setdefault(pk, []).append(mid)
    decisions = []
    promoted, merged = [], []
    for pk, mids in clusters.items():
        best = max(mids, key=lambda x: (_rel(mems[x]), _access_count_of(root, x, mems[x], _acounts)))
        bm = mems[best]
        rec = bm.get("recurrence_count") or 0
        age = _age_days(bm)
        rel = _rel(bm)
        acc = _access_count_of(root, best, bm, _acounts)
        reasons = []
        worth = False
        if rec >= min_recurrence:
            worth = True
            reasons.append("recurrence=%d≥%d" % (rec, min_recurrence))
        if rel >= min_relevance and acc >= min_access and age >= min_age_days:
            worth = True
            reasons.append("rel=%.2f,access=%d,age=%dd" % (rel, acc, age))
        if not worth:
            continue
        decisions.append({"mid": best, "action": "promote", "to_tier": promote_tier,
                          "reasons": reasons, "recurrence": rec})
        if not dry_run:
            try:
                promote(root, best, promote_tier)
                promoted.append(best)
            except Exception as e:  # 单条失败不影响其余决策
                decisions[-1]["error"] = str(e)
        if merge and len(mids) > 1:
            for om in mids:
                if om == best:
                    continue
                decisions.append({"mid": om, "action": "merge_supersede",
                                  "canonical": best, "cluster": pk})
                if not dry_run:
                    try:
                        archive(root, om, yes=True)  # 沉底不销毁，可 unarchive 找回
                        merged.append(om)
                    except Exception as e:
                        decisions[-1]["error"] = str(e)
    return {"ok": True, "dry_run": dry_run, "promoted": promoted, "merged": merged,
            "decisions": decisions[:top_n], "n_decisions": len(decisions)}

def promote_candidates(root, min_recurrence=3, min_relevance=0.6,
                       min_access=5, min_age_days=30):
    """ 列出「满足晋升条件但还没晋升」的候选——纯只读，不改任何记忆。
    复用 promote_auto 的判断逻辑（recurrence/relevance/access/age 四门槛），
    但不修改 tier、不 archive 任何条目。
    返回：[{id, summary, tier, recurrence, relevance, access, age_days, reasons}]"""
    mems = _all_mems(root)
    _acounts = _load_recall_counts(root)  # 5.0/A1：访问次数改读单一热源
    today = datetime.date.today()

    def _age_days(m):
        c = _parse_date(m.get("created") or m.get("first_seen") or "")
        return (today - c).days if c else 9999

    def _rel(m):
        r = m.get("relevance_score")
        if isinstance(r, (int, float)):
            return float(r)
        return float(m.get("importance") or 0.5)

    out = []
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        if m.get("tier") in ("curated", "core"):
            continue  # 已晋升的跳过
        rec = m.get("recurrence_count") or 0
        rel = _rel(m)
        acc = _access_count_of(root, mid, m, _acounts)  # 5.0/A1：单一热源
        age = _age_days(m)
        reasons = []
        if rec >= min_recurrence:
            reasons.append("recurrence=%d≥%d" % (rec, min_recurrence))
        if rel >= min_relevance and acc >= min_access and age >= min_age_days:
            reasons.append("rel=%.2f,access=%d,age=%dd" % (rel, acc, age))
        if not reasons:
            continue
        out.append({
            "id": mid,
            "summary": m.get("summary", ""),
            "tier": m.get("tier", "working"),
            "recurrence": rec,
            "relevance": round(rel, 3),
            "access": acc,
            "age_days": age,
            "reasons": reasons,
        })
    # 按综合得分排序：recurrence * relevance 高的优先
    out.sort(key=lambda x: x["recurrence"] * x["relevance"] + x["access"] * 0.01, reverse=True)
    return out

def _neural_installable():
    for mod in ("fastembed", "sentence_transformers"):
        try:
            __import__(mod)
            return True
        except Exception:
            pass
    return False

def _clusters_exist(root):
    p = os.path.join(root, "store", "clusters.json")
    if not os.path.exists(p):
        return False
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return bool(d.get("assign"))
    except Exception:
        return False

def _audit_item(id_, name, status, rec, prio, reason, how):
    return {"id": id_, "name": name, "status": status,
            "recommendation": rec, "priority": prio,
            "reason": reason, "how": how}

def _audit_readable(env, feats, summary):
    icon = {"enable": "[建议开启]", "disable": "[建议关闭]",
            "keep": "[保持]", "optional": "[按需]"}
    lines = [
        "=== 记忆系统能力体检 ===",
        "记忆总数：%d  嵌入后端：%s  ANN阈值：%d（当前%s）" % (
            env["n_memories"], env["embedding_backend"],
            env["ann"]["min_memories"],
            "可用" if env["ann"]["usable_now"] else "未达阈值"),
        "LLM增强：%s  聚类：%s  Dashboard：%s" % (
            "已启用" if env["llm_enabled"] else "未启用",
            "已生成" if env["clusters_exist"] else "无",
            "已生成" if env["dashboard_exist"] else "无"),
        "",
        summary, "",
        "逐项建议：",
    ]
    for f in feats:
        lines.append("%s %s（优先级 %s）" % (icon.get(f["recommendation"], ""),
                                             f["name"], f["priority"]))
        lines.append("    为什么：%s" % f["reason"])
        lines.append("    怎么做：%s" % f["how"])
    return "\n".join(lines)

def audit_features(root):
    """能力体检 + 开关顾问：针对当前记忆库规模与环境，评估每个可选功能的开启/关闭建议。
    
    当用户问「帮我看看有哪些功能可以开启或关闭」时调用。纯只读（不写盘）。
    返回 {ok, environment, features[], summary, readable}。features 每项含
    recommendation(enable/disable/keep/optional) 与 priority(high/medium/low)，
    便于有选择性地开关。"""
    mems = _all_mems(root)
    n = len(mems)
    backend = _emb_backend()
    neural_ok = backend != "lexical"
    neural_installable = _neural_installable()
    ann_min = _load_keeper_config(root)["ann_min_memories"]
    ann_usable_now = n >= ann_min
    ann_built = (os.path.exists(os.path.join(root, "store", "ann.idx"))
                 or os.path.exists(os.path.join(root, "store", "ann.emb.npy")))
    llm_cfg = _load_llm_config(root)
    llm_on = bool(llm_cfg.get("enabled"))
    clusters_exist = _clusters_exist(root)
    dash_exist = os.path.exists(os.path.join(root, "store", "dashboard.html"))
    get_recall_strategy(root)  # 仅读权重，不写

    feats = []

    # 1. 神经语义召回
    if neural_ok:
        feats.append(_audit_item("neural", "神经语义召回（真·同义/改写理解）", "on", "keep", "low",
                                  "当前已是神经后端，换说法也能召回，保持即可。",
                                  "无需操作；换模型见 FEATURES.md §6。"))
    elif neural_installable:
        feats.append(_audit_item("neural", "神经语义召回（真·同义/改写理解）", "off", "enable", "high",
                                  "检测到已装 fastembed/sentence_transformers 但未启用；开启后中文换个说法也能召回（你反馈过的痛点）。",
                                  "设 AI_MEM_EMBED_BACKEND=fastembed 后重开进程即可。"))
    else:
        feats.append(_audit_item("neural", "神经语义召回（真·同义/改写理解）", "off", "enable", "medium",
                                  "默认回退词法向量，对中文深度改写召回偏弱（你反馈过的痛点）。装 fastembed 即可启用真语义。",
                                  "pip install fastembed，再设 AI_MEM_EMBED_BACKEND=fastembed。"))

    # 2. ANN 加速
    if ann_usable_now and ann_built:
        feats.append(_audit_item("ann", "ANN 近邻加速（大库更快）", "on", "keep", "low",
                                  "记忆已超阈值且索引已建，召回已走加速路径。", "无需操作。"))
    elif n >= 200:
        feats.append(_audit_item("ann", "ANN 近邻加速（大库更快）", "off", "enable", "medium",
                                  "记忆已达 %d 条，超过默认阈值 50，建议启用 ANN 加速 recall。" % n,
                                  "recall --ann（首次建索引后自动复用）。"))
    elif ann_usable_now:
        feats.append(_audit_item("ann", "ANN 近邻加速（大库更快）", "off", "optional", "low",
                                  "记忆已达 %d 条（≥阈值 %d），可用 ANN，但线性扫描在小规模下已足够快，开不开皆可。"
                                  % (n, ann_min),
                                  "想体验：recall --ann；或设 AI_MEM_ANN_MIN_MEMORIES 调低阈值。"))
    else:
        feats.append(_audit_item("ann", "ANN 近邻加速（大库更快）", "off", "keep", "low",
                                  "记忆仅 %d 条（<阈值 %d），线性扫描更快更准，暂不需要 ANN。" % (n, ann_min),
                                  "库变大后再考虑；可设 AI_MEM_ANN_MIN_MEMORIES=N 提前开启。"))

    # 3. 聚类
    if clusters_exist:
        feats.append(_audit_item("cluster", "记忆聚类 / 主题发现", "on", "keep", "low",
                                  "已生成聚类，结构可见。", "想刷新：cluster --apply。"))
    elif n >= 20:
        feats.append(_audit_item("cluster", "记忆聚类 / 主题发现", "off", "enable", "medium",
                                  "记忆已达 %d 条，聚类能自动发现主题簇、辅助去重与导航。" % n,
                                  "cluster --apply（零依赖，k-means）。"))
    else:
        feats.append(_audit_item("cluster", "记忆聚类 / 主题发现", "off", "optional", "low",
                                  "记忆仅 %d 条，聚类收益有限，可先攒够 20 条。" % n,
                                  "cluster --apply（随时可跑）。"))

    # 4. Dashboard
    if dash_exist:
        feats.append(_audit_item("dashboard", "可视化 Dashboard", "on", "keep", "low",
                                  "已生成 dashboard.html，可随时浏览器查看。", "想刷新：dashboard。"))
    elif n >= 5:
        feats.append(_audit_item("dashboard", "可视化 Dashboard", "off", "enable", "medium",
                                  "记忆已有 %d 条，生成一张结构图（记忆树 + 聚类 + 矛盾高亮）便于总览。" % n,
                                  "dashboard（默认写到 store/dashboard.html）。"))
    else:
        feats.append(_audit_item("dashboard", "可视化 Dashboard", "off", "optional", "low",
                                  "记忆较少，先攒一些再生成可视化更有意义。", "dashboard（随时可跑）。"))

    # 5. 矛盾扫描
    if n >= 15:
        feats.append(_audit_item("contradiction", "主动矛盾 / 重复扫描", "off", "enable", "medium",
                                  "记忆已达 %d 条，容易出现『记重了 / 新结论与旧结论打架』，建议定期扫描。" % n,
                                  "doctor --contradictions（加 --fix 软标记 relations.conflict）。"))
    else:
        feats.append(_audit_item("contradiction", "主动矛盾 / 重复扫描", "off", "optional", "low",
                                  "记忆尚少（%d 条），冲突概率低，可等攒多后再定期跑。" % n,
                                  "doctor --contradictions。"))

    # 6. 元记忆 / 召回权重微调
    feats.append(_audit_item("meta", "元记忆（召回权重可审计/微调）", "on", "keep", "low",
                              "召回信号权重已落盘 meta.json，可在 report 里看 recall_strategy；默认即合理，一般无需改。",
                              "report 查看；config.json 的 recall 块可改 rrf_k 等（高阶）。"))

    # 7. LLM 增强
    if llm_on:
        feats.append(_audit_item("llm", "本地 LLM 记忆增强（Ollama）", "on", "keep", "low",
                                  "已启用 LLM 增强（reflect --llm 自动提炼/去重）。",
                                  "保持；无 Ollama 时 reflect 会回退规则模式。"))
    else:
        feats.append(_audit_item("llm", "本地 LLM 记忆增强（Ollama）", "off", "optional", "low",
                                  "可选。装了 Ollama 并想让 reflect 用模型自动提炼记忆时可开启；否则规则模式已够用。",
                                  "装 Ollama → llm-setup --enable。"))

    # 8. IMA 知识库镜像（跨工具共享）
    # 直接读原始 config.json 的 keeper.ima_kb_id（绕过 _load_keeper_config 白名单，与 keeper_setup.py 一致）
    ima_kb = ""
    try:
        _cfgp = os.path.join(root, "config.json")
        if os.path.exists(_cfgp):
            with open(_cfgp, encoding="utf-8") as _cf:
                _cfg = json.load(_cf)
            ima_kb = (_cfg.get("keeper", {}) or {}).get("ima_kb_id") or ""
    except Exception:
        ima_kb = ""
    if ima_kb and ima_kb != "YOUR_IMA_KB_ID":
        feats.append(_audit_item("ima", "IMA 知识库镜像（跨工具共享沉淀）", "on", "keep", "low",
                                  "已配置 IMA 知识库，归档记忆会自动镜像推送到 IMA，跨工具/会话共享沉淀。",
                                  "保持；推送前强制脱敏（绝不交付明文），详见 COOKBOOK.md / LIMITS.md。"))
    else:
        feats.append(_audit_item("ima", "IMA 知识库镜像（跨工具共享沉淀）", "off", "optional", "low",
                                  "可选。把归档记忆自动推送到 IMA 知识库，跨工具/会话共享沉淀；"
                                  "推送前强制脱敏（绝不交付明文）。当前未配置 IMA 知识库。",
                                  "在已连 IMA MCP 的会话里让 AI 帮你选库，或 `keeper_setup.py ima --kb-id <ID>`。"))
    # D1：探测上次 IMA 镜像导出时间，把"半同步"状态显性化
    # （doctor 绿 ≠ 已推送到 KB；导出≠入库）。给出可观测的『上次导出』时间戳。
    _ima_push_dir = os.path.join(os.path.expanduser("~"), ".workbuddy", "ima_push")
    _ima_last_export = ""
    try:
        _pf = [os.path.join(_ima_push_dir, f) for f in os.listdir(_ima_push_dir)
               if f.startswith("keeper-") and f.endswith(".md")]
        if _pf:
            _ima_last_export = max(os.path.getmtime(p) for p in _pf)
    except Exception:
        _ima_last_export = ""

    env = {
        "n_memories": n,
        "embedding_backend": backend,
        "neural_installable": neural_installable,
        "ann": {"min_memories": ann_min, "usable_now": ann_usable_now, "index_built": ann_built},
        "llm_enabled": llm_on,
        "clusters_exist": clusters_exist,
        "dashboard_exist": dash_exist,
        "ima_kb_configured": bool(ima_kb and ima_kb != "YOUR_IMA_KB_ID"),
        "ima_last_export": _ima_last_export,
    }
    n_enable = sum(1 for f in feats if f["recommendation"] == "enable")
    n_disable = sum(1 for f in feats if f["recommendation"] == "disable")
    n_keep = sum(1 for f in feats if f["recommendation"] == "keep")
    n_optional = sum(1 for f in feats if f["recommendation"] == "optional")
    summary = "建议开启 %d 项、关闭 %d 项、保持 %d 项、按需 %d 项。" % (
        n_enable, n_disable, n_keep, n_optional)
    readable = _audit_readable(env, feats, summary)
    return {"ok": True, "root": root, "environment": env,
            "features": feats, "summary": summary, "readable": readable}

def dashboard(root, out=None):
    """P1-4 轻量可视化 dashboard：生成单文件 HTML（记忆树 + 聚类关系图 + 矛盾高亮 + 召回策略）。
    零依赖：纯内联 CSS/JS，无外部库、无网络；双击即可在浏览器打开。默认写到 store/dashboard.html，
    可用 --out 指定。复用已有 report() / _load_clusters() / _find_contradiction_candidates() / 元记忆策略。
    返回 {ok, file, total, contradictions, clusters}。纯只读（除写这一个 HTML 文件）。"""
    mems = _all_mems(root)
    rep = report(root)
    cl = _load_clusters(root)
    cands = _find_contradiction_candidates(root, limit=50)
    strat = get_recall_strategy(root)

    # 记忆树：按 category 聚合 scope/tier 分布
    by_cat = {}
    for m in mems.values():
        cat = m.get("category", "uncategorized")
        scope = m.get("scope", "universal")
        tier = m.get("tier", "working")
        c = by_cat.setdefault(cat, {"total": 0, "scope": {}, "tier": {}})
        c["total"] += 1
        c["scope"][scope] = c["scope"].get(scope, 0) + 1
        c["tier"][tier] = c["tier"].get(tier, 0) + 1
    rows = []
    for m in mems.values():
        rows.append({
            "id": m.get("id"),
            "category": m.get("category", ""),
            "tier": m.get("tier", "working"),
            "scope": m.get("scope", "universal"),
            "status": m.get("status", "active"),
            "summary": m.get("summary", ""),
            "tags": (m.get("tags") or [])[:6],
            "confidence": round(float(m.get("confidence", 1.0)), 2),
            # 5.0/A1 续修：仪表盘原先读**记忆文件字段**（真库 204/211 条恒 0），
            # 于是「最常被召回的记忆」在 dashboard 上一律显示 0 次。改读单一热源。
            "access_count": _access_count_of(root, m.get("id"), m),
            "version": m.get("version", 1),
        })

    # 聚类关系图：从 assign 重建簇，按 size 排序，取 top-tag 作为簇标签
    clusters = []
    if cl and cl.get("assign"):
        groups = {}
        for mid, cid in cl["assign"].items():
            groups.setdefault(cid, []).append(mid)
        for cid, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            mt = [mems[i] for i in members if i in mems]
            tags = _top_tags_for_cluster(mt) if mt else []
            clusters.append({"cid": cid, "size": len(members),
                             "members": members[:60], "tags": tags})
    # 簇间边：共享 top-tag 的簇之间连线（展示知识结构）
    edges = []
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            if set(clusters[i]["tags"]) & set(clusters[j]["tags"]):
                edges.append([i, j])

    # P0 升级：关系图谱摘要（记忆间推理边）——supports/refutes/is_a/part_of 等
    # F6：_REL_TYPES 已提升为模块级单一事实源（含 validated_by/audits），此处直接复用
    _rel_counts = {t: 0 for t in _REL_TYPES}
    _rel_edges = []
    for m in mems.values():
        if m.get("status") != "active":
            continue
        rels = m.get("relations", {}) or {}
        for t in _REL_TYPES:
            v = rels.get(t)
            if not v:
                continue
            tgts = [v] if isinstance(v, str) else v
            for tg in tgts:
                if isinstance(tg, str):
                    _rel_counts[t] += 1
                    if len(_rel_edges) < 60:
                        _rel_edges.append({"src": m.get("id"), "rel": t, "dst": tg})
    relations_summary = {"counts": _rel_counts, "edges": _rel_edges,
                         "total": sum(_rel_counts.values())}

    data = {
        "generated": today(),
        "root": os.path.abspath(root),
        "report": {k: rep[k] for k in ("total", "by_tier", "superseded",
                                        "archived", "calibration", "decay",
                                        "last_reflect")},
        "by_cat": by_cat,
        "rows": rows,
        "clusters": clusters,
        "edges": edges,
        "contradictions": cands,
        "relations_summary": relations_summary,
        "strategy": {k: strat[k] for k in strat if k != "_overridden"},
        "strategy_overridden": strat.get("_overridden", {}),
    }
    html = _render_dashboard_html(data)
    if out is None:
        out = os.path.join(root, "store", "dashboard.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return {"ok": True, "file": out, "total": data["report"]["total"],
            "clusters": len(clusters), "contradictions": len(cands)}

def _render_dashboard_html(data):
    """把 data 渲染为自包含 HTML（内联 CSS/JS，无外部依赖）。"""
    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # 防止 summary 内含 </script> 截断
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent 记忆系统 · Dashboard</title>
<style>
:root{--bg:#f7f8fa;--card:#fff;--ink:#1f2329;--sub:#646a73;--line:#e5e6eb;
--red:#f53f3f;--green:#00b42a;--blue:#165dff;--orange:#ff7d00;--purple:#722ed1;}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--ink);font-size:14px;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}
.meta{color:var(--sub);font-size:12px;margin-bottom:18px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:120px}
.card .n{font-size:24px;font-weight:700}
.card .l{color:var(--sub);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.panel h2{font-size:15px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.bar{display:flex;align-items:center;gap:8px;margin:6px 0}
.bar .name{width:130px;color:var(--sub);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar .track{flex:1;background:#eef0f3;border-radius:6px;height:18px;position:relative;overflow:hidden}
.bar .fill{height:100%;background:var(--blue);border-radius:6px}
.bar .v{width:40px;text-align:right;font-size:12px;color:var(--sub)}
.tag{display:inline-block;background:#eef2ff;color:var(--blue);border-radius:4px;padding:1px 6px;font-size:11px;margin:2px 3px 2px 0}
.tier{display:inline-block;border-radius:4px;padding:1px 6px;font-size:11px;margin-right:4px}
.t-working{background:#e8f3ff;color:var(--blue)} .t-curated{background:#e8ffea;color:var(--green)}
.t-core{background:#fff3e8;color:var(--orange)} .t-seed{background:#f2f3f5;color:var(--sub)}
.scope-u{color:var(--green)} .scope-p{color:var(--blue)} .scope-e{color:var(--orange)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600}
.conf{color:var(--sub)}
svg{max-width:100%;height:auto;display:block;margin:0 auto}
.node circle{stroke:#fff;stroke-width:2}
.legend{font-size:12px;color:var(--sub);margin-top:8px}
.cand{border-left:3px solid var(--red);background:#fff5f5;padding:8px 12px;margin:8px 0;border-radius:6px}
.cand .score{color:var(--red);font-weight:700}
.strat{font-size:12px;color:var(--sub)}
.strat b{color:var(--ink)}
.enc{display:inline-block;background:#f0fff5;color:var(--green);border:1px solid #b7ebc9;border-radius:4px;padding:1px 6px;font-size:11px}
.empty{color:var(--sub);font-size:12px;padding:8px 0}
</style></head>
<body><div class="wrap">
<h1>Agent 记忆系统 · 记忆 Dashboard</h1>
<div class="meta">生成于 __GEN__ · 根目录 __ROOT__</div>
<div class="cards" id="cards"></div>
<div class="grid">
  <div class="panel"><h2>记忆树（按类别）</h2><div id="tree"></div></div>
  <div class="panel"><h2>分层 / 状态</h2><div id="tiers"></div>
    <h2 style="margin-top:14px">召回策略（元记忆）</h2><div id="strat" class="strat"></div></div>
</div>
<div class="panel"><h2>聚类关系图（主题簇）</h2><div id="graph"></div>
  <div class="legend" id="clegend"></div></div>
<div class="panel"><h2>矛盾 / 重复候选 <span class="conf" id="ccount"></span></h2>
  <div id="cands"></div></div>
<div class="panel"><h2>关系图谱（记忆间推理边）<span class="conf" id="relcount"></span></h2>
  <div id="rels"></div></div>
<div class="panel"><h2>全部记忆（__TOTAL__ 条）</h2>
  <table><thead><tr><th>id</th><th>类别</th><th>层级</th><th>范围</th><th>置信</th><th>访问</th><th>ver</th><th>摘要</th></tr></thead>
  <tbody id="rows"></tbody></table></div>
</div>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
var D = JSON.parse(document.getElementById('data').textContent);
function el(id){return document.getElementById(id);}
// 卡片
var r=D.report, c=D.cards=[];
var cards=[['总数',r.total],['已归档',r.archived],['已取代',r.superseded],
  ['聚类簇',D.clusters.length],['矛盾候选',D.contradictions.length]];
el('cards').innerHTML=cards.map(x=>'<div class="card"><div class="n">'+x[1]+'</div><div class="l">'+x[0]+'</div></div>').join('');
// 记忆树
var cats=Object.keys(D.by_cat).sort((a,b)=>D.by_cat[b].total-D.by_cat[a].total);
var maxc=Math.max.apply(null,cats.map(k=>D.by_cat[k].total));
el('tree').innerHTML=cats.map(k=>{
  var o=D.by_cat[k],sc=Object.keys(o.scope).map(s=>'<span class="scope-'+s[0]+'">'+s+':'+o.scope[s]+'</span>').join(' ');
  return '<div class="bar"><div class="name">'+k+'</div><div class="track"><div class="fill" style="width:'+(o.total/maxc*100)+'%"></div></div><div class="v">'+o.total+'</div></div><div style="margin:-2px 0 4px 138px;font-size:11px">'+sc+'</div>';
}).join('')||'<div class="empty">暂无记忆</div>';
// tiers
var bt=r.by_tier,tr=Object.keys(bt).sort((a,b)=>bt[b]-bt[a]);
el('tiers').innerHTML=tr.map(t=>'<span class="tier t-'+t+'">'+t+' '+bt[t]+'</span>').join(' ');
// strategy
var s=D.strategy,ov=D.strategy_overridden;
el('strat').innerHTML=['sem_emb','sem_tf','sem_syn','rrf_k','min_score','rrf_weak'].map(k=>'<div><b>'+k+'</b> = '+(typeof s[k]=='number'?s[k].toFixed(3):s[k])+(ov&&ov[k]!=null?' <span class="enc">config 覆盖</span>':'')+'</div>').join('');
// 聚类图（SVG，簇节点环形布局 + 共享 tag 连边）
var cl=D.clusters, edges=D.edges;
if(cl.length){
  var W=520,H=360,cx=W/2,cy=H/2,R=130,N=cl.length;
  var pos=cl.map((c,i)=>{var a=2*Math.PI*i/N;return [cx+R*Math.cos(a),cy+R*Math.sin(a),Math.sqrt(c.size)*4+8,i];});
  var svg='<svg viewBox="0 0 '+W+' '+H+'" width="520" height="360">';
  edges.forEach(function(e){var a=pos[e[0]],b=pos[e[1]];svg+='<line x1="'+a[0]+'" y1="'+a[1]+'" x2="'+b[0]+'" y2="'+b[1]+'" stroke="#d0d3d9" stroke-width="1.5"/>';});
  pos.forEach(function(p){svg+='<circle class="node" cx="'+p[0]+'" cy="'+p[1]+'" r="'+p[2]+'" fill="#165dff" opacity="0.8"><title>'+cl[p[3]].tags.join(',')+'（'+cl[p[3]].size+'）</title></circle>';});
  pos.forEach(function(p){svg+='<text x="'+p[0]+'" y="'+(p[1]+p[2]+12)+'" font-size="10" text-anchor="middle" fill="#646a73">C'+p[3]+'</text>';});
  svg+='</svg>';
  el('graph').innerHTML=svg;
  el('clegend').innerHTML=cl.map(c=>'<span class="tag">C'+c.cid+' ('+c.size+')：'+(c.tags.join('/')||'—')+'</span>').join('');
}else{el('graph').innerHTML='<div class="empty">尚未聚类（先跑 `cluster` 生成主题簇）。</div>';}
// 矛盾候选
el('ccount').textContent='（'+D.contradictions.length+'）';
el('cands').innerHTML=D.contradictions.length?D.contradictions.map(c=>
  '<div class="cand"><span class="score">'+c.score+'</span> · <b>'+c.a+'</b> ⇄ <b>'+c.b+'</b> <span class="conf">（共享：'+c.shared+'）</span><br>'+
  '<span class="conf">A：'+c.summary_a+'</span><br><span class="conf">B：'+c.summary_b+'</span></div>').join('')
  :'<div class="empty">未发现明显矛盾 / 重复候选 ✓</div>';
// 全部记忆表
el('rows').innerHTML=D.rows.map(m=>'<tr><td>'+m.id+'</td><td>'+m.category+'</td><td><span class="tier t-'+m.tier+'">'+m.tier+'</span></td>'+
  '<td class="scope-'+m.scope[0]+'">'+m.scope+'</td><td>'+m.confidence+'</td><td>'+m.access_count+'</td><td>'+m.version+'</td><td>'+m.summary.replace(/</g,"&lt;")+'</td></tr>').join('');
// P0 升级（4.5.36）：关系图谱面板
var rs=D.relations_summary||{counts:{},edges:[],total:0};
el('relcount').textContent='（'+rs.total+' 条边）';
var rc=rs.counts||{}, rlabels={related_to:'相关',superseded_by:'被取代',corrected_by:'被纠正',
  supports:'支持',refutes:'推翻',is_a:'属于',part_of:'组成',derived_from:'提炼自'};
el('rels').innerHTML=(Object.keys(rc).filter(k=>rc[k]>0).map(function(k){
  return '<span class="tag">'+rlabels[k]+' '+rc[k]+'</span>';}).join(' ')||'<span class="conf">暂无推理边（先跑 `graph --build` 自动建边）</span>')
  + (rs.edges&&rs.edges.length?'<table style="margin-top:10px"><thead><tr><th>源</th><th>关系</th><th>目标</th></tr></thead><tbody>'
    +rs.edges.map(function(e){return '<tr><td>'+e.src+'</td><td>'+rlabels[e.rel]+'</td><td>'+e.dst+'</td></tr>';}).join('')
    +'</tbody></table>':'<div class="empty">暂无边样例</div>');
el('ccount').textContent='（'+D.contradictions.length+'）';
document.querySelector('title').textContent='Agent 记忆系统 · '+r.total+' 条 · Dashboard';
</script>
</body></html>""".replace("__GEN__", data["generated"]).replace("__ROOT__", data["root"]) \
        .replace("__TOTAL__", str(data["report"]["total"])).replace("__PAYLOAD__", payload)

def _euclid2(a, b):
    s = 0.0
    for x, y in zip(a, b):
        d = x - y
        s += d * d
    return s

def _kmeans_fit(vecs, k, iters=25, seed=0):
    """轻量 k-means（k-means++ 初始化），返回 (centroids, assign)。vecs 为 list[list[float]]。"""
    import random
    rnd = random.Random(seed)
    n = len(vecs)
    dim = len(vecs[0])
    # k-means++ 初始化
    cents = [vecs[rnd.randrange(n)]]
    D = [math.inf] * n
    for _ in range(1, k):
        for i, v in enumerate(vecs):
            d = _euclid2(v, cents[-1])
            if d < D[i]:
                D[i] = d
        total = sum(D)
        if total <= 0:
            cents.append(vecs[rnd.randrange(n)])
            continue
        r = rnd.random() * total
        cum = 0.0
        picked = False
        for i in range(n):
            cum += D[i]
            if cum >= r:
                cents.append(vecs[i])
                picked = True
                break
        if not picked:
            cents.append(vecs[rnd.randrange(n)])
    assign = [0] * n
    for _ in range(iters):
        changed = False
        for i, v in enumerate(vecs):
            best, bd = 0, math.inf
            for c, cent in enumerate(cents):
                d = _euclid2(v, cent)
                if d < bd:
                    bd, best = d, c
            if assign[i] != best:
                assign[i], changed = best, True
        sums = [[0.0] * dim for _ in range(k)]
        cnts = [0] * k
        for i, v in enumerate(vecs):
            c = assign[i]
            cnts[c] += 1
            sc = sums[c]
            for j in range(dim):
                sc[j] += v[j]
        for c in range(k):
            if cnts[c] > 0:
                inv = 1.0 / cnts[c]
                sums[c] = [x * inv for x in sums[c]]
        cents = sums
        if not changed:
            break
    return cents, assign

def _top_tags_for_cluster(mems_in_cluster):
    """簇内标签频次 → 取 Top-3 作为建议标签（涌现主题）。"""
    from collections import Counter
    c = Counter()
    for m in mems_in_cluster:
        for t in (m.get("tags") or []):
            c[t] += 1
    return [t for t, _ in c.most_common(3)]

@_with_deposit_lock
def cluster_memories(root, max_k=12, apply=False, dry_run=False, min_size=8):
    """#6 聚类自标签：对落盘向量做 k-means，输出主题簇 + 建议标签，可选回写到记忆。
    
    返回 {clusters:[{label, ids, suggested_tags, size}], generated, n, k}。
    apply=True 时把 suggested_tags 合并进各记忆（去重、不覆盖已有），dry_run 仅预览。
    样本<8 条不聚类（簇无意义）。规模>4000 时随机采样 4000 以保证单次聚类可控耗时。"""
    store = _emb_store_load_all(root)  # {id: (vec, text_hash, model)}
    store = _emb_store_refresh_backend(root, store)  # #O5-bug：后端切换后避免跨空间聚类
    if len(store) < min_size:
        return {"clusters": [], "generated": today(), "n": len(store), "k": 0,
                "below_min": True,
                "note": "记忆不足 %d 条，跳过聚类（簇无意义）。小库可用 --min-size 降低门槛（最低 2），"
                        "但样本越少主题簇可靠性越低，建议积累到 %d 条以上再聚类。"
                        % (min_size, max(min_size, 8))}
    ids = list(store.keys())
    vecs = [store[i][0] for i in ids]
    if len(ids) > 4000:
        import random
        rnd = random.Random(42)
        idx = rnd.sample(range(len(ids)), 4000)
        ids = [ids[i] for i in idx]
        vecs = [vecs[i] for i in idx]
    mems_by_id = _all_mems(root)
    k = max(2, min(max_k, int(round((len(ids) ** 0.5) / 2))))
    k = min(k, len(ids) - 1)
    cents, assign = _kmeans_fit(vecs, k)
    groups = {}
    for i, cid in enumerate(assign):
        groups.setdefault(cid, []).append(ids[i])
    clusters = []
    for cid, members in groups.items():
        mems_c = [mems_by_id[i] for i in members if i in mems_by_id]
        suggested = _top_tags_for_cluster(mems_c)
        clusters.append({"label": "cluster-%d" % cid, "ids": members,
                         "suggested_tags": suggested, "size": len(members)})
    clusters.sort(key=lambda c: c["size"], reverse=True)
    # 质心落盘：供 recall --cluster-boost 在查询时找「最近主题质心」做召回增强（#6→recall）
    centroids = {}
    for _cid, _vec in enumerate(cents):
        centroids[str(_cid)] = [round(x, 6) for x in _vec]
    result = {"clusters": clusters, "centroids": centroids,
              "generated": today(), "n": len(ids), "k": k}
    # 持久化簇（供 reflect / 人工查看涌现结构）
    try:
        p = os.path.join(root, "store", "clusters.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if apply and not dry_run:
        for cl in clusters:
            for mid in cl["ids"]:
                m = mems_by_id.get(mid)
                if not m:
                    continue
                existing = set(m.get("tags") or [])
                add = [t for t in cl["suggested_tags"] if t and t not in existing]
                if add:
                    m["tags"] = (m.get("tags") or []) + add
                    _save_mem(root, mid, m)
                    data = load_index(root)
                    for e in data.get("entries", []):
                        if e.get("id") == mid:
                            e["tags"] = m["tags"]
                    save_index(root, data)
                    _inv_upsert(root, mid, m["tags"])
    return result

def _find_contradiction_candidates(root, threshold=0.7, jac_pregate=0.3, limit=50,
                                   graded=True, large_threshold=200, return_meta=False):
    """主动矛盾/重复扫描（纯词法零依赖）。
    先按『共享具体标签 / 品牌 / 主体』预筛候选对（避免 O(n^2) 全扫）；
    对候选对先用廉价 Jaccard(_sim) 预筛(>=jac_pregate)排除明显无关，
    再算 embedding 余弦（语义更稳）作为最终相似度，>=threshold 即标记疑似矛盾/重复。
    #13 修复：① Jaccard 预筛未过但主体共享的对仍算 embedding（避免语义相似但词法不同漏检）；
    ② 标记 contradiction_signal=True 的对含对立信号词（疑似真矛盾而非重复）。
    P2-2 分级：大库（活跃记忆数 ≥ large_threshold，默认 200）跳过昂贵的『主体桶』，
    改走「聚类内 + 标签/品牌」配对——把 O(主体²) 压成 O(簇内²)，簇内仍两两比不漏同主题矛盾；
    若未跑过 cluster（无 clusters.json）则仅保留 tag/brand 桶。小库或 graded=False 走全桶（含主体）。
    只报告候选对供 agent/人工裁决（FLAG/UPDATE/SKIP），不合并/不删（避免误伤）。
    return_meta=True 时返回 (list, meta)；否则返回 list（兼容旧调用）。"""
    mems = {i: mm for i, mm in _all_mems(root).items() if mm.get("status") == "active"}
    ids = list(mems)
    n = len(ids)
    # P2-2 分级：大库（>= large_threshold）跳过昂贵的主体桶，改走「聚类内 + 标签/品牌」配对，
    # 把 O(主体²) 压成 O(簇内²)；簇内仍两两比，不漏同主题矛盾。小库/关闭 graded 走全桶（含主体）。
    _large = graded and n >= large_threshold
    cl = None
    _use_clusters = False
    if _large:
        cl = _load_clusters(root)
        if cl and cl.get("assign"):
            _use_clusters = True
    buckets = {}  # 预筛：共享具体标签 / 品牌 / 主体（或簇） 的记忆归同桶
    for mid in ids:
        mm = mems[mid]
        if _use_clusters:
            cid = cl["assign"].get(mid)
            if cid is not None:
                buckets.setdefault("cl:" + str(cid), []).append(mid)
        for t in (mm.get("tags") or []):
            if t not in _emb.GENERIC_TAGS:
                buckets.setdefault("tag:" + t, []).append(mid)
        for b in (mm.get("brand_mentions") or []):
            buckets.setdefault("brand:" + b, []).append(mid)
        if not _large:
            for s in _emb.extract_subjects(mm.get("summary", "") + " " + mm.get("body", "")):
                buckets.setdefault("subj:" + s, []).append(mid)
    seen = set()
    _survivors = []  # (a, b, ta, tb, shared) —— Jaccard 预筛后存活的对
    for _key, grp in buckets.items():
        if len(grp) < 2:
            continue
        is_subject_bucket = _key.startswith("subj:")
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if a == b:
                    continue
                pair = (a, b) if a < b else (b, a)
                if pair in seen:
                    continue
                seen.add(pair)
                ma, mb = mems[a], mems[b]
                ta = " ".join([ma.get("summary", ""), ma.get("body", ""), " ".join(ma.get("tags", []))])
                tb = " ".join([mb.get("summary", ""), mb.get("body", ""), " ".join(mb.get("tags", []))])
                jac = _sim(ta, tb)
                # #13 修复：主体共享的对即使 Jaccard 低也算 embedding（语义相似但措辞不同）
                if jac < jac_pregate and not is_subject_bucket:
                    continue
                _survivors.append((a, b, ta, tb, _key.split(":", 1)[1]))
    # #92：批量化嵌入——收集全部唯一文本一次 embed_batch，避免每对重复单条推理。
    # 结果与原逐对 embed 完全一致（cache key 同为 _bkey，向量相同），仅减少模型调用次数；
    # 行为零风险，默认路径不变（仍先 Jaccard 预筛，再批算余弦）。
    _uniq = {}
    for (_a, _b, ta, tb, _sh) in _survivors:
        if ta not in _uniq:
            _uniq[ta] = len(_uniq)
        if tb not in _uniq:
            _uniq[tb] = len(_uniq)
    _vecs = {}
    if _uniq:
        _vec_list = _emb.embed_batch(list(_uniq.keys()))
        for _t, _v in zip(_uniq.keys(), _vec_list):
            _vecs[_t] = _v
    cands = []
    for (a, b, ta, tb, shared) in _survivors:
        sc = _emb.cosine(_vecs.get(ta), _vecs.get(tb))
        if sc >= threshold:
            # #13：检测对立信号词，区分真矛盾 vs 重复/补充
            ma, mb = mems[a], mems[b]
            contra_sig = _has_contradiction_signal(
                ma.get("summary", "") + " " + ma.get("body", ""),
                mb.get("summary", "") + " " + mb.get("body", ""))
            cands.append({"a": a, "b": b, "score": round(sc, 4),
                          "summary_a": ma.get("summary", ""), "summary_b": mb.get("summary", ""),
                          "shared": shared,
                          "contradiction_signal": contra_sig})
    # 🔴 可复现性修复（2026-09-15 审计）：原 `sort(key=score, reverse=True)` 对同分对
    # 依赖输入顺序（Timsort 稳定），叠加 [:limit] 截断后，同分候选的存留会不稳定。
    # 加 (a, b) 确定性 tiebreaker，使「同库同参 → 逐字节一致」。
    cands.sort(key=lambda c: (-c["score"], c["a"], c["b"]))
    _out = cands[:limit]
    if return_meta:
        _mode = ("cluster" if (_use_clusters)
                 else ("tag_brand" if _large else "full"))
        return _out, {"graded": _large, "mode": _mode, "active_n": n,
                      "note": "大库分级：仅同簇/同标签/同品牌内两两比，避免 O(n²) 全扫；"
                              "如需全量请设 graded=False"}
    return _out


def _find_adjacent_contradiction_lane(root, low=0.45, high=0.7, limit=60):
    """C1：相邻矛盾 lane——捕捉语义相邻但非重复的『反对者』。
    
    复用 _find_contradiction_candidates(threshold=low) 取全部余弦 ≥low 的对，
    剔除已归为高分(≥high, 主通道已报告)者，剩余在 [low,high) 且含对立信号词
    （contradiction_signal=True，同桶隐含共享话题轴）的，标为 adjacent_contradiction。
    把矛盾检测从『只能找双胞胎(近重复)』升级为『能找同主题相反建议(反对者)』。
    纯只读、fail-open（异常返回空列表），不影响主通道结果。"""
    try:
        _all = _find_contradiction_candidates(root, threshold=low, limit=limit * 4)
        _out = []
        for _c in _all:
            if _c["score"] >= high:
                continue  # 高分对已由主通道报告
            if not _c.get("contradiction_signal"):
                continue
            _c2 = dict(_c)
            _c2["lane"] = "adjacent"
            _out.append(_c2)
            if len(_out) >= limit:
                break
        return _out
    except Exception:
        return []


def _llm_adjudicate_contradictions(cands, llm):
    """C2：LLM 矛盾裁决（opt-in，fail-open）。
    
    对候选对批量调用 llm(text)->dict，判 contradiction/duplicate/complementary/unrelated
    并附一句话理由。llm 为 None 或未提供时直接返回原候选（不启用）。
    任何异常一律降级为『未裁决』（保留 rule 结果），绝不阻断 doctor。
    cands 每项会被附加 'verdict' 字段（LLM 结论或 None）。"""
    if not llm or not cands:
        return cands
    _out = []
    for _c in cands:
        _c = dict(_c)
        try:
            _prompt = (
                "判断两条记忆是否矛盾/重复/互补/无关，只回 JSON："
                "{\"verdict\":\"contradiction|duplicate|complementary|unrelated\","
                "\"reason\":\"一句话\"}\n"
                "A: %s\nB: %s" % (_c.get("summary_a", ""), _c.get("summary_b", "")))
            _resp = llm(_prompt)
            if isinstance(_resp, str):
                import json as _json
                _resp = _json.loads(_resp)
            _c["verdict"] = _resp.get("verdict")
            _c["verdict_reason"] = _resp.get("reason")
        except Exception:
            _c["verdict"] = None
        _out.append(_c)
    return _out

@_with_deposit_lock
def _doctor_embed_backend(root):
    """B6' ：doctor 嵌入后端健康面。
    
    只读健康态，不触盘（仅 SELECT + 模型完整性探测）。异常一律降级为 degraded 信息，不致命。
    返回 dict：
      - backend: 实际生效后端（_emb.backend_info()，如 'fastembed:BAAI/bge-small-zh-v1.5' / 'lexical'）
      - configured: 配置后端（config.json keeper.embed_backend）
      - fell_back_to_lexical: 配置神经/auto 但实际落到 lexical（即「回退词法」）
      - model_present: 模型缓存完整性（仅神经后端有意义；词法模式为 None）
      - model_detail: 模型完整性详情/路径
      - coverage: 嵌入覆盖率（缓存命中率代理）= 当前后端下带向量的 active 记忆 / active 记忆总数
    """
    info = {"backend": None, "configured": None, "fell_back_to_lexical": None,
            "model_present": None, "model_detail": None,
            "coverage": {"active": 0, "with_embedding": 0, "rate": 0.0}}
    try:
        info["backend"] = _emb_backend()
        try:
            info["configured"] = (_load_keeper_config().get("embed_backend")
                                  or "fastembed").lower()
        except Exception:
            info["configured"] = "fastembed"
        info["fell_back_to_lexical"] = (
            info["configured"] in ("auto", "fastembed", "neural", "sentence_transformers")
            and info["backend"] == "lexical")
        if info["backend"] not in ("lexical",) and ":" in (info["backend"] or ""):
            try:
                ok, detail = _emb.verify_model_integrity()
                info["model_present"] = bool(ok)
                info["model_detail"] = detail
            except Exception as _e:
                info["model_present"] = False
                info["model_detail"] = "verify error: %s" % _e
        else:
            info["model_present"] = None
            info["model_detail"] = "lexical 模式无模型依赖"
        # 嵌入覆盖率（缓存命中率代理）：当前后端下带向量的 active 记忆占比
        cur = info["backend"]
        try:
            conn = _db_conn(root)
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE status='active'").fetchone()[0]
                if cur:
                    # 用「同向量空间」判定而非字符串等值：落盘值可能带 '#<size>.<mtime>'
                    # 模型内容指纹后缀，等值匹配会恒为 0（假红灯），见 _backend_compatible。
                    rows = conn.execute(
                        "SELECT em.model FROM embeddings em "
                        "JOIN entries e ON e.id=em.id "
                        "WHERE e.status='active'").fetchall()
                    with_emb = sum(1 for (_m,) in rows
                                   if _backend_compatible(_m, cur))
                else:
                    with_emb = 0
            finally:
                conn.close()
            rate = round(with_emb / total, 4) if total else 0.0
            info["coverage"] = {"active": total, "with_embedding": with_emb, "rate": rate}
            try:
                info["fingerprint_drift"] = sum(
                    1 for (_m,) in rows if "#" in str(_m or ""))
            except Exception:
                info["fingerprint_drift"] = None
        except Exception:
            pass
    except Exception as _e:
        info["error"] = "doctor_embed_backend failed: %s" % _e
    return info

def _check_investment_invariants(root):
    """F14：投资域不变式 lint（只读、无副作用、无 float 崩溃）。
    检查 investment 域中 **active** 的 verified factor/system 记忆是否至少挂 1 条 validated_by 出边
    （L3→L2 闭环证据）。

    4.9.26 审计修订（方案A：降级为提示，不再作违规刷屏）
    ------------------------------------------------------
    背景（2026-09-15 真库实读，216 条 index）：全库 26 类关系边均在正常产生，唯独
    `validated_by` 仅 2 条（占比 0.9%）；本 lint 命中 18 条中只有 2 条带该边 → 16 条
    **每次 doctor 都固定重复报同一句**，构成告警疲劳（真信号会被恒定噪音淹没）。
    判定：该 invariant 在**当前使用方式下几乎无法被满足**，属下述模式的一个实例——
    **「规则层期待的字段 ≠ 写入侧实际产生的字段」**（另两例：分层路由读 tags 钥匙词而真信号在
    `scope` 字段；`semantic_gate` 写在 keeper 块而代码只读 recall 块）。
    故本版做两处收敛，而非加抑制机制（抑制是治标，改判定才是治本）：
      ① **排除非 active 条目**（archived / superseded）——要求已失效条目持有"当前证据"逻辑不通；
      ② 结果从 `violations` **降级为 `hints`（severity=info）**——仍是可选的改进建议，不再是"错误"。
    返回 {"checked":int, "excluded_inactive":int, "violations":[...], "hints":[...]}；
    `violations` 恒为空（保留键以向后兼容既有读取方）。"""
    out = {"checked": 0, "excluded_inactive": 0, "violations": [], "hints": []}
    _ACTIVE_STATUSES = ("", "active", "verified")
    try:
        idx = load_index(root)
    except Exception:
        return out
    for e in idx.get("entries", []):
        if e.get("domain") != "investment":
            continue
        sub = e.get("subdomain") or ""
        if sub not in ("factor", "system"):
            continue
        tags = e.get("tags") or []
        status = e.get("status") or ""
        if not (("st:verified" in tags) or (status == "verified")):
            continue
        # ① 排除非 active（archived/superseded 等）：已失效条目不该被要求持有当前证据链
        if status not in _ACTIVE_STATUSES:
            out["excluded_inactive"] += 1
            continue
        out["checked"] += 1
        mid = e.get("id")
        fp = os.path.join(mem_dir(root), mid + ".json")
        if not os.path.exists(fp):
            fp = os.path.join(archive_dir(root), mid + ".json")
        has_vb = False
        try:
            m = json.load(open(fp, encoding="utf-8"))
            rel = m.get("relations") or {}
            has_vb = bool(rel.get("validated_by"))
        except Exception:
            pass
        if not has_vb:
            # ② 降级为 hint（info）：可选改进建议，不再计入 violations
            out["hints"].append({
                "id": mid, "subdomain": sub, "severity": "info",
                "summary": (e.get("summary") or "")[:80],
                "reason": "verified %s 未挂 validated_by 出边（可选：补 L2 测试证据链，不影响使用）" % sub,
                "how": "可选：`link %s validated_by <通过测试ID>`" % mid,
            })
    return out

def _check_deployment_status():
    """E2：本机"部署副本"是否与当前技能版本一致——更新后最易遗漏的一环。

    背景：`install_hooks.py` 只在"settings.json 里还没注册 keeper 钩子"时被触发，
    于是**技能升级后 ~/.workbuddy/hooks/ 与 keeper_daemon/ 下的副本会静默停在旧版**，
    用户"更新完感觉没生效"却查不出原因。本检查把暴露面交给 `doctor`，
    让"我更新了 keeper，到底生效没有"有一个确定答案。

    零 import 模块铁律：依赖一律函数内取；异常必须带根因（type + 原文），不许只剩一句"检查失败"。
    """
    import json as _json
    _r = {"checked": False, "stale": None, "reason": "",
          "deployed_version": "", "current_version": ""}
    try:
        _root = _skill_root()
        _r["checked"] = True
        _sk = os.path.join(_root, "SKILL.md")
        if os.path.exists(_sk):
            with open(_sk, encoding="utf-8") as _f:
                for _line in _f:
                    _s = _line.strip()
                    if _s.startswith("version:"):
                        _r["current_version"] = _s.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        _st = os.path.join(os.path.expanduser("~"), ".workbuddy", "hooks",
                           ".keeper_deploy_state.json")
        if os.path.exists(_st):
            with open(_st, encoding="utf-8") as _f:
                _d = _json.load(_f) or {}
            _r["deployed_version"] = str(_d.get("version") or "")
        _stale, _why = _hooks_stale_reason()
        _r["stale"] = bool(_stale)
        _r["reason"] = _why
    except Exception as e:
        _r["error"] = "%s: %s" % (type(e).__name__, e)
    return _r


def _check_hooks_status():
    """E1：检查 keeper 钩子在 settings.json 中的注册状态与命令可达性。
    返回 {registered, missing, stale_pythonw, mode}——供 doctor 聚合展示。"""
    import json as _json
    _wb = os.path.join(os.path.expanduser("~"), ".workbuddy")
    _settings = os.path.join(_wb, "settings.json")
    # 🔴 5.0.x 修复：模式持久化位置自 4.9.19 起已迁到**用户配置域**
    #   <WB_HOME>/hooks/hooks_config.json（与 install_hooks.HOOKS_CONFIG 同源）。
    #   旧实现读源码树 `_skill_root()/hooks_config.json`（该文件已不存在）→ 恒报 unknown。
    #   改为：新位置优先，旧位置（源码树）兜底，与 install_hooks.load_mode() 同源。
    _hooks_cfg = os.path.join(_wb, "hooks", "hooks_config.json")
    if not os.path.exists(_hooks_cfg):
        try:
            _hooks_cfg = os.path.join(_skill_root(), "hooks_config.json")
        except Exception:
            _hooks_cfg = ""
    if not _hooks_cfg or not os.path.exists(_hooks_cfg):
        _hooks_cfg = os.path.join(_wb, "skills", "agent-local-memory-keeper", "hooks_config.json")
    _result = {"registered": [], "missing": [], "stale_pythonw": [], "mode": "unknown"}
    # 读持久模式
    try:
        if os.path.exists(_hooks_cfg):
            with open(_hooks_cfg, encoding="utf-8") as _f:
                _d = _json.load(_f)
            _result["mode"] = _d.get("hooks_mode", "unknown")
    except Exception:
        pass
    # 读已注册钩子
    _KEEPER_FILES = ["keeper_hook_common.py", "session_start_keeper_inject.py",
                     "user_prompt_recall.py", "post_tool_use_error_capture.py",
                     "memory_auto_capture.py", "_async_deposit.py"]
    if not os.path.exists(_settings):
        return {**_result, "error": "settings.json not found"}
    try:
        with open(_settings, encoding="utf-8") as _f:
            _data = _json.load(_f)
    except Exception:
        return {**_result, "error": "settings.json parse failed"}
    _hooks = _data.get("hooks", {})
    for _event, _groups in (_hooks or {}).items():
        for _g in (_groups or []):
            if not isinstance(_g, dict):
                continue
            for _h in _g.get("hooks", []):
                _cmd = (_h.get("command", "") or "") if isinstance(_h, dict) else ""
                for _kf in _KEEPER_FILES:
                    if _kf in _cmd:
                        _result["registered"].append("%s/%s" % (_event, _kf))
                        # 检查是否用了 pythonw（无弹窗）
                        if "python.exe" in _cmd and "pythonw.exe" not in _cmd:
                            _result["stale_pythonw"].append("%s/%s" % (_event, _kf))
                        # 检查脚本文件是否存在
                        if ".py\"" in _cmd or ".py'" in _cmd:
                            _script = _cmd.split("\"")[-2] if "\"" in _cmd else _cmd.split("'")[-2]
                            if not os.path.exists(_script):
                                _result["missing"].append("%s → %s" % (_event, _script))
    return _result


_SCHED_PROBE_TTL = 86400  # 调度探测结果缓存 24h


def _sched_probe_path():
    """调度探测缓存文件（部署目录下，与 .keeper_deploy_state.json 同处）。"""
    try:
        return os.path.join(_hooks_deploy_dir(), ".keeper_sched_probe.json")
    except Exception:
        return None


def _sched_probe_read():
    """读缓存；过期 / 损坏 / 无路径一律返回 None（退化为直接探测，不漏检）。"""
    import json as _json
    import time as _time
    _p = _sched_probe_path()
    if not _p:
        return None
    try:
        with open(_p, encoding="utf-8") as _f:
            _d = _json.load(_f)
        if _time.time() - float(_d.get("checked_at") or 0) > _SCHED_PROBE_TTL:
            return None
        return _d
    except Exception:
        return None


def _sched_probe_write(rec):
    """写缓存；任何异常都忽略——缓存只用于降噪，不承担正确性。"""
    import json as _json
    import time as _time
    _p = _sched_probe_path()
    if not _p:
        return
    try:
        _rec = dict(rec)
        _rec["checked_at"] = _time.time()
        _dir = os.path.dirname(_p)
        if _dir and not os.path.isdir(_dir):
            os.makedirs(_dir, exist_ok=True)
        with open(_p, "w", encoding="utf-8") as _f:
            _json.dump(_rec, _f, ensure_ascii=False)
    except Exception:
        pass


def _sched_cache_age_hint(rec):
    """给「缓存命中」项追加：这是多久前的结论 + 如何强制重探。

    🔴 只在**展示层**拼接，绝不写回缓存——否则每读一次尾巴就再滚一圈。
    """
    import time as _time
    try:
        _age_s = max(0.0, _time.time() - float(rec.get("checked_at") or 0))
    except Exception:
        return ""
    _p = _sched_probe_path() or ""
    if _age_s < 3600:
        _age = "约 %d 分钟前" % int(_age_s // 60)
    else:
        _age = "约 %.1f 小时前" % (_age_s / 3600.0)
    return ("（此为%s的探测缓存；若已改过相关限制，"
            "加 --no-cache 或删除 %s 可强制重探）" % (_age, _p))


def _sched_diag(_e):
    """把「查不到」翻译成能对症的提示——区分「没有该程序」与「有但被拦」。

    🔴 只有「PATH 里找不到程序」能下确定结论。拿到调用失败（PermissionError /
    WinError 5 等）时**不得断言单一成因**：同一个错误码至少有下述四类来源，
    本机实测最常见的是第 ① 条，但换一台机器可能是 ②~④。把单机经验当通用结论，
    会让人去改一个跟自己无关的设置，白折腾还可能改坏环境。
    """
    import shutil as _shutil
    _head = "%s: %s" % (type(_e).__name__, str(_e)[:140])
    try:
        _which = _shutil.which("schtasks")
    except Exception:
        _which = None
    if not _which:
        return "本机 PATH 无 schtasks.exe（非 Windows 或系统组件缺失）。原始错误：%s" % _head
    return ("schtasks.exe 在（%s）但调用被拒。可能成因（按常见度排序，多数机器是第 ① 条）："
            "① 安全软件的「程序黑名单」拦了它（如 WorkBuddy 安全中心 → Command Security "
            "→ Program Blacklist）；"
            "② 当前进程权限不足（未提权 / UAC 受限令牌）；"
            "③ 组策略或企业管控（AppLocker / WDAC / 软件限制策略）；"
            "④ 系统组件损坏或被同名文件替换。"
            "注：keeper 的定时维护走 WorkBuddy 自动化、不依赖 schtasks，"
            "本项不可用不影响记忆功能。原始错误：%s" % (_which, _head))


def _check_scheduler_status(no_cache=False):
    """E1：检查调度器（schtasks/launchd/systemd）是否注册了 keeper 自动化任务。
    返回 {platform, tasks: [{name, enabled, note}]}。

    4.9.13 降噪 + 可诊断：
      · 结果缓存 24h——某类机器上 schtasks 调用会被拦，此前**每次** doctor 都会白撞一次
        （stderr 被 DEVNULL 吞掉，用户看不见，只在系统安全日志里留记录）；
      · 提示分得清「被策略拦 / 根本没有 / 有但未注册任务」——恒显示「无法查询」会让人
        误以为是 keeper 自己的毛病。

    🔴 两条设计边界，改动前务必留意：
      · **只对负向结果短路**（available is False）。可用时每次都实查任务列表——否则
        新装的调度任务会被缓存永久掩盖，那才是真漏检。这是刻意的，别顺手"优化"掉。
      · 缓存命中的提示必须**自曝年龄 + 给出强制重探法**。否则使用者解除了限制来跑
        doctor，看到的是 24h 前的旧结论，会以为解除没生效（此即 --no-cache 的用途）。

    缓存读写在任何异常下都退化为「直接探测」，绝不因缓存坏掉而漏检。
    no_cache=True（doctor --no-cache）：跳过缓存直连探测——「刚改了限制，立刻看结果」。
    """
    # 本模块无顶层 import（符号靠运行期注入），而 subprocess 不在注入集合里：
    # 先前直接引用会抛 NameError → 被上层吞成"检查失败"，调度自检实际从未执行过。
    import subprocess
    _result = {"platform": sys.platform, "tasks": []}
    if sys.platform == "win32":
        _cached = None if no_cache else _sched_probe_read()
        if _cached is not None and _cached.get("available") is False:
            _note = (_cached.get("note") or "schtasks 不可用") + _sched_cache_age_hint(_cached)
            _result["tasks"] = [{"name": "(不可用)", "note": _note, "cached": True}]
            return _result
        try:
            _out = subprocess.check_output(
                ["schtasks", "/Query", "/FO", "CSV", "/NH",
                 "/Filter", "TaskName eq keeper*"],
                stderr=subprocess.DEVNULL, timeout=10)
            for _line in _out.decode("utf-8", "replace").splitlines():
                if not _line.strip():
                    continue
                _parts = [_p.strip().strip('"') for _p in _line.split(",")]
                # /NH 已要求不出表头；个别版本仍带，按名过滤（原先写死 [1:] 会**漏掉第一条任务**）
                if _parts and _parts[0].lower() == "taskname":
                    continue
                if len(_parts) >= 4 and _parts[0]:
                    _result["tasks"].append({
                        "name": _parts[0], "status": _parts[3] if len(_parts) > 3 else "?"
                    })
            if _result["tasks"]:
                _sched_probe_write({"available": True})
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as _e:
            _note = _sched_diag(_e)
            _result["tasks"] = [{"name": "(不可用)", "note": _note}]
            _sched_probe_write({"available": False, "note": _note})
    elif sys.platform == "darwin":
        _plist = os.path.expanduser("~/Library/LaunchAgents/com.keeper.*.plist")
        import glob as _gl
        for _f in _gl.glob(_plist):
            _result["tasks"].append({"name": os.path.basename(_f), "status": "plist exists"})
    else:  # linux / posix
        _unit_dir = os.path.expanduser("~/.config/systemd/user/")
        if os.path.isdir(_unit_dir):
            import glob as _gl
            for _f in _gl.glob(os.path.join(_unit_dir, "keeper*")):
                _result["tasks"].append({"name": os.path.basename(_f), "status": "unit file"})
    if not _result["tasks"]:
        _result["tasks"] = [{"name": "(无)", "note": "未检测到 keeper 调度任务"}]
    return _result


# ═══════════════════════════════════════════════════════════════════════════════
# doctor 建议项 ack 抑制（2026-09-15 审计新增）
# ───────────────────────────────────────────────────────────────────────────────
# 动机：doctor 每轮都会重复列出同一批「建议类」条目（连接候选 / 矛盾候选 / 场景低置信 /
#       类型漂移 / 投资域证据链提示…）。用户看过后它们仍每轮刷屏 → 告警疲劳 → 真信号被
#       恒定噪音淹没。本机制允许对某条建议「确认已知悉」，之后默认不再显示。
#
# 🔴 安全规约（防「抑制」变成「永久静音」把真问题埋掉）：
#   ① 只抑制**建议类**条目；完整性类（缺文件 / 悬空引用 / 索引漂移 / 损坏）**永不可抑制**。
#   ② 抑制带 **TTL**（默认 30 天）——过期自动复活，逼用户重新面对，不会一劳永逸。
#   ③ 抑制键 = `kind::id`；**id 变化即视为新建议**（如连接候选换了记忆对），自然重新显示。
#      注：诚实说明——原方案设想的「同 id 分数变化自动复活」未实现（收益低、需在 ack 时
#      回填签名），改用「身份键 + TTL + 显式 clear」三重保险，逻辑更简单也更好测。
#   ④ `doctor --ack-all` 一次性展开全部（含已 ack）；`--ack-clear` 一键清空全部抑制。
# ═══════════════════════════════════════════════════════════════════════════════

DOCTOR_ACK_FILE = "doctor_ack.json"
DOCTOR_ACK_TTL_DAYS = 30

# (result 键, kind, id 取法) —— 仅「建议类」进入抑制面；完整性类刻意不在此表。
_ACK_SECTIONS = (
    ("link_candidates", "link",
     lambda it: "%s~%s" % (it.get("a"), it.get("b"))),
    ("contradiction_candidates", "contradiction",
     lambda it: "%s~%s" % (it.get("a"), it.get("b"))),
    ("adjacent_contradiction_candidates", "adjacent",
     lambda it: "%s~%s" % (it.get("a"), it.get("b"))),
    ("scope_mismatch_candidates", "scope",
     lambda it: str(it.get("id"))),
    ("type_mismatch_candidates", "type",
     lambda it: str(it.get("id"))),
    ("low_confidence_scenes", "scene",
     lambda it: str(it.get("id"))),
)


def _ack_file(root):
    return os.path.join(root, "store", DOCTOR_ACK_FILE)


def _ack_key(kind, ident):
    return "%s::%s" % (kind, ident)


def _load_doctor_ack(root):
    try:
        with open(_ack_file(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_doctor_ack(root, d):
    p = _ack_file(root)
    _d = os.path.dirname(p)
    if _d:
        os.makedirs(_d, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, p)
    return p


def doctor_ack(root, kind, ident, reason="", now=None):
    """记录一条 doctor 建议的 ack（确认已知悉，后续默认不再显示）。返回写入条目。"""
    d = _load_doctor_ack(root)
    d[_ack_key(kind, ident)] = {
        "kind": kind, "id": ident, "reason": reason or "",
        "at": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
    }
    _save_doctor_ack(root, d)
    return d[_ack_key(kind, ident)]


def doctor_ack_list(root, now=None):
    """列出全部 ack 记录（含是否已过期）。"""
    now = now or datetime.datetime.now()
    out = []
    for k, v in sorted(_load_doctor_ack(root).items()):
        age = _ack_age_days(v.get("at"), now)
        out.append({"key": k, "kind": v.get("kind"), "id": v.get("id"),
                    "reason": v.get("reason", ""), "at": v.get("at"),
                    "age_days": (None if age is None else round(age, 2)),
                    "expired": (age is None or age > DOCTOR_ACK_TTL_DAYS)})
    return out


def doctor_ack_clear(root, kind=None, ident=None):
    """清除 ack：kind 与 ident 都给 → 只清该条；否则清全部。返回被清掉的键列表。"""
    d = _load_doctor_ack(root)
    if kind and ident:
        k = _ack_key(kind, ident)
        keys = [k] if k in d else []
    else:
        keys = list(d.keys())
    for k in keys:
        d.pop(k, None)
    _save_doctor_ack(root, d)
    return keys


def _ack_age_days(iso, now):
    try:
        t = datetime.datetime.fromisoformat(str(iso))
    except Exception:
        return None
    return (now - t).total_seconds() / 86400.0


def _apply_doctor_ack(root, result, ack_all=False, now=None, ttl_days=None):
    """按 ack 记录过滤 result 中的「建议类」条目（原地修改 result）。返回汇总 dict。

    只动 _ACK_SECTIONS 列出的键 + investment_invariants.hints；完整性类字段一律不动。
    """
    now = now or datetime.datetime.now()
    ttl = DOCTOR_ACK_TTL_DAYS if ttl_days is None else ttl_days
    acked = _load_doctor_ack(root)
    summary = {"suppressed": 0, "shown": 0, "acked_total": len(acked),
               "expired_revived": 0, "ack_all": bool(ack_all),
               "ttl_days": ttl, "file": _ack_file(root)}
    if ack_all:
        return summary

    def _filter(items, kind, ident_of):
        keep, drop, revived = [], 0, 0
        for it in (items or []):
            rec = acked.get(_ack_key(kind, ident_of(it)))
            if not rec:
                keep.append(it)
                continue
            age = _ack_age_days(rec.get("at"), now)
            if age is None or age > ttl:
                revived += 1
                keep.append(it)      # 过期 → 复活
                continue
            drop += 1
        return keep, drop, revived

    for key, kind, ident_of in _ACK_SECTIONS:
        if key not in result:
            continue
        kept, dropped, revived = _filter(result.get(key), kind, ident_of)
        result[key] = kept
        summary["suppressed"] += dropped
        summary["shown"] += len(kept)
        summary["expired_revived"] += revived
    iv = result.get("investment_invariants")
    if isinstance(iv, dict) and isinstance(iv.get("hints"), list):
        kept, dropped, revived = _filter(iv["hints"], "invariant",
                                         lambda it: str(it.get("id")))
        iv["hints"] = kept
        summary["suppressed"] += dropped
        summary["shown"] += len(kept)
        summary["expired_revived"] += revived
    return summary


def doctor(root, fix=False, context_budget=None, contradictions=False, low_confidence=False,
           repair=False, restore=None, llm=None, no_cache=False, ack_all=False):
    """健康自检：索引/文件双向一致性、孤儿、悬空关系、损坏、token 估算。
    同时检查 memories/ 与 memories/archive/ 两处，并同时核对「索引↔文件」两个方向：
      - index_without_file / missing_files：索引里有、磁盘文件已不在（孤儿索引条目）
      - orphan_files：磁盘上有合法记忆文件、却不在索引里（漏登记，rebuild 才会补，doctor 现也能检出）
    """
    _tag_index_reset(root)  # 自检/修复可能改动状态，作废增量缓存（非热路径）
    data = load_index(root)
    md = mem_dir(root)
    ad = archive_dir(root)
    entries = data.get("entries", [])
    # A2 ：在文件扫描前处理 corrupt/ 隔离区，使修复/还原出的文件被后续扫描正常收录。
    repaired_list, restored_list, restore_errors = [], [], []
    if restore:
        ok, msg = _restore_corrupt_file(root, restore)
        (restored_list if ok else restore_errors).append(msg)
    if repair:
        for _qd in (os.path.join(md, "corrupt"), os.path.join(ad, "corrupt")):
            if not os.path.isdir(_qd):
                continue
            for _qfn in sorted(os.listdir(_qd)):
                if not _qfn.endswith(".json"):
                    continue
                _qpath = os.path.join(_qd, _qfn)
                try:
                    with open(_qpath, encoding="utf-8") as _rf:
                        raw = _rf.read()
                except OSError:
                    continue
                ok_rep, fixed = _repair_json_text(raw)
                if ok_rep:
                    try:
                        with open(os.path.join(md, _qfn), "w", encoding="utf-8") as _wf:
                            _wf.write(fixed)
                        os.remove(_qpath)
                        repaired_list.append(_qfn)
                    except OSError:
                        continue
                # 修复失败保留原地等人工处理
    file_map = {}          # id -> 真实文件路径（两目录都扫，仅成功解析的合法记忆入库）
    corrupt = []            # 损坏但仍留在 memories/（隔离移动失败，如只读存储）
    corrupt_quarantined = []  # 已移入同级 corrupt/ 隔离区（保留原文，可恢复）
    for d in (md, ad):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            fpath = os.path.join(d, fn)
            try:
                with open(fpath, encoding="utf-8") as _f:
                    m = json.load(_f)
                mid = m.get("id") or fn[:-5]
                if mid not in file_map:        # 同名 id 在两目录同时出现时以 memories/ 为准
                    file_map[mid] = fpath
            except (json.JSONDecodeError, UnicodeDecodeError):
                # O4 ：尝试隔离到同级 corrupt/，成功入 quarantined，失败仍留原地入 corrupt
                if _quarantine_corrupt_file(fpath):
                    corrupt_quarantined.append(fn)
                else:
                    corrupt.append(fn)
    file_ids = set(file_map)
    idx_ids = {e.get("id") for e in entries}
    missing_files = [e.get("id") for e in entries if e.get("id") and e.get("id") not in file_map]
    # 反向一致性：磁盘有合法文件但索引漏登记（如拷贝进库 / 索引部分丢失 / 部分重建）
    orphan_files = [mid for mid in file_ids if mid not in idx_ids]
    dangling = []
    mems = _all_mems(root)
    # O4 ：汇总 recall/其他读路径已先行隔离的损坏文件（如 recall 已把损坏文件移走）
    _qseen = set(corrupt_quarantined)
    for _qd in (os.path.join(md, "corrupt"), os.path.join(ad, "corrupt")):
        if os.path.isdir(_qd):
            for _qfn in sorted(os.listdir(_qd)):
                if _qfn.endswith(".json") and _qfn not in _qseen:
                    corrupt_quarantined.append(_qfn)
                    _qseen.add(_qfn)
    for m in mems.values():
        for rel, tgts in (m.get("relations") or {}).items():
            tg = tgts if isinstance(tgts, list) else [tgts]
            for t in tg:
                if t not in file_ids:
                    dangling.append({"id": m.get("id"), "rel": rel, "target": t})
    status_mismatch = []
    for e in entries:
        m = mems.get(e.get("id"))
        if m and m.get("status") != e.get("status"):
            status_mismatch.append({"id": e.get("id"), "file": m.get("status"), "index": e.get("status")})
    # P2：三层内容一致性检测（只读）。memories/*.json 是内容真源，
    # store/index.db 的 data 列与 index.json 是派生镜像。若文件被外部编辑而索引未同步，
    # 会出现「文件新、索引旧」漂移——此时主 recall 从 SQLite 读到的仍是旧内容。只读检测，
    # fix 模式下以文件为准回填（见下方 fix 块）。
    content_mismatch = []
    for e in entries:
        m = mems.get(e.get("id"))
        if not m:
            continue
        if _index_content_sig(e) != _index_content_sig(m):
            content_mismatch.append({"id": e.get("id")})
    # ：误分类候选（只读检测，不改动）——供人工/AI 复核「归类可能错」的记忆
    scope_candidates = []
    type_candidates = []  # #19：type 误分类候选
    try:
        cmodel = _clf.load_model(root)
        for m in mems.values():
            if m.get("status") != "active":
                continue
            det = _clf.detect_misclass(cmodel, m, mems)
            if det:
                scope_candidates.append({"id": m.get("id"), "stored": m.get("scope"),
                                         "suggest": det["suggest"],
                                         "confidence": det["confidence"],
                                         "reasons": det["reasons"]})
            # #19：type 误分类检测
            tdet = _clf.detect_type_misclass(cmodel, m)
            if tdet:
                type_candidates.append({"id": m.get("id"),
                                        "stored": m.get("type") or m.get("category", ""),
                                        "suggest": tdet["suggest"],
                                        "confidence": tdet["confidence"],
                                        "reasons": tdet["reasons"]})
    except Exception:
        pass
    total_tokens = sum(token_estimate(m) for m in mems.values())
    # 连边候选（P0-B，只读建议）：找出「主题相关但未连边」的记忆对，供 AI/用户导航或
    # 经 reflect --auto 应用。doctor 本身只报告、不写盘。
    link_candidates = _find_link_candidates(root)
    # 主动矛盾/重复扫描（doctor --contradictions 时启用，只读报告候选对）
    # P2-2 分级：大库自动降级为簇内/标签/品牌配对，避免 O(n²) 全扫；返回 grade 元数据。
    if contradictions:
        contradiction_candidates, contradiction_grade = _find_contradiction_candidates(
            root, return_meta=True)
        # C1：相邻矛盾 lane——捕捉语义相邻但非重复的反对者
        adjacent_candidates = _find_adjacent_contradiction_lane(root)
        # C2：LLM 裁决（opt-in，llm=None 时不启用，fail-open）
        if llm:
            contradiction_candidates = _llm_adjudicate_contradictions(contradiction_candidates, llm)
            adjacent_candidates = _llm_adjudicate_contradictions(adjacent_candidates, llm)
    else:
        contradiction_candidates, contradiction_grade = [], None
        adjacent_candidates = []
    # ：低置信场景分类候选（问题①B 档）——自动分类非权威，列出供人工/AI 复核。
    # 触发条件：scene_via=="rule"（纯关键词，脆弱）或 scene_confidence < 0.7。
    low_conf_scenes = []
    if low_confidence:
        for m in mems.values():
            if m.get("status") != "active":
                continue
            via = m.get("scene_via")
            sc = m.get("scene_confidence")
            if via == "rule" or (isinstance(sc, (int, float)) and sc < 0.7):
                low_conf_scenes.append({
                    "id": m.get("id"), "scene": m.get("scene"),
                    "scene_confidence": sc, "scene_via": via,
                    "summary": (m.get("summary") or "")[:60]})
    context_full = False
    recommendations = []
    if context_budget is not None and total_tokens > context_budget:
        context_full = True
        recommendations.append(
            "上下文接近预算（%d/%d token），建议运行 reflect --auto 归档过期记忆并沉淀重点。"
            % (total_tokens, context_budget))
    # P2：相关性衰减提示。decay_apply 已确定性重算 relevance_score（含时间衰减+近因加权），
    # 但需定期触发（无后台调度时）。库≥50 条时建议周期性 `decay --incremental` 让长期未用经验自然降级，
    # 避免过时经验挤占召回；反馈用 `recall --id <id> --outcome good|bad` 提权/降权（已内建）。
    if len(entries) >= 50 and not low_confidence and not contradictions:
        recommendations.append(
            "库已达 %d 条，建议周期性运行 `decay --incremental`（时间衰减+近因加权，让过时经验自然降级）；"
            "对单条可用 `recall --id <id> --outcome good|bad` 反馈提权/降权。" % len(entries))
    # P1：--flat 草稿区健康提示。flat 模式是全局轻量草稿垫（~/.workbuddy/memory/keeper_flat.md），
    # 不进 SQLite 主库，主 recall 永远召回不到——属「静默数据分区」。doctor 检出有内容即告警，
    # 提醒用户 flat 记忆是独立于主库的草稿，需手动迁移或接受其仅走 flat_recall。
    flat_entries = []
    try:
        from flat_mode import flat_list
        flat_entries = flat_list() or []
    except Exception:
        flat_entries = []
    if flat_entries:
        recommendations.append(
            "检测到 %d 条 --flat 轻量草稿（keeper_flat.md）：它们不进主库、主 recall 召回不到，是独立草稿垫；"
            "如需纳入主库请用普通 deposit 重记，或仅用 flat_recall 检索。" % len(flat_entries))
    result = {
        "entries": len(entries), "files": len(file_ids),
        "corrupt_files": corrupt, "corrupt_quarantined": corrupt_quarantined,
        "repaired": repaired_list, "restored": restored_list, "restore_errors": restore_errors,
        "index_without_file": [i for i in idx_ids if i not in file_ids],
        "missing_files": missing_files, "orphan_files": orphan_files,
        "dangling_relations": dangling,
        "status_mismatch": status_mismatch,
        "content_mismatch": content_mismatch,
        "scope_mismatch_candidates": scope_candidates,
        "type_mismatch_candidates": type_candidates,
        "link_candidates": link_candidates,
        "contradiction_candidates": contradiction_candidates,
        "contradiction_grade": contradiction_grade,
        "adjacent_contradiction_candidates": adjacent_candidates,
        "low_confidence_scenes": low_conf_scenes,
        "flat_mode_entries": len(flat_entries),
        "total_token_estimate": total_tokens,
        "context_full": context_full,
        "recommendations": recommendations,
    }
    if fix:
        # P1-3 安全闸：--fix 写盘前先对整库做快照备份（zip），提供完整回滚点；
        # 无法快照则拒绝写入，避免无回滚点的破坏性修复。
        _ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        _bdest = os.path.join(os.path.dirname(os.path.abspath(root)),
                              "doctor_fix_backup_%s.zip" % _ts)
        try:
            _bdest = backup(root, dest=_bdest)
            result["fixed_backup"] = _bdest
            try:
                result["pruned_old_backups"] = _prune_doctor_fix_backups(root)
            except Exception:
                pass
        except Exception as _be:
            result["fixed"] = None
            result["error"] = "pre_backup_failed: %s" % _be
            return result
        # 安全自动修复（绝不删记忆内容，只让 index↔文件一致）：
        # ① 移除 index 中文件已不存在的孤儿条目；
        # ② 以文件为准同步 index 的 status（消解「文件 superseded / 索引 active」脱节）；
        # ③ 把「磁盘有合法文件但索引漏登记」的孤儿文件补登进索引（安全：只增不删，等价于局部 rebuild）；
        # ④ 剪枝悬空关系（relations 指向已不存在的记忆）。
        # 需要彻底重建索引请用 rebuild（以文件为准全量重扫）。
        data = load_index(root)
        before = len(data["entries"])
        data["entries"] = [e for e in data["entries"]
                           if e.get("id") and e.get("id") in file_map]
        dropped = before - len(data["entries"])
        synced = 0
        for e in data["entries"]:
            m = mems.get(e.get("id"))
            if m and m.get("status") != e.get("status"):
                e["status"] = m.get("status")
                synced += 1
        added = 0
        present_ids = {e.get("id") for e in data["entries"]}
        for mid, fpath in file_map.items():
            if mid in present_ids:
                continue
            try:
                with open(fpath, encoding="utf-8") as _ff:
                    mm = json.load(_ff)
                is_archived = fpath.startswith(archive_dir(root) + os.sep)
                # P2：孤儿恢复取完整记忆 JSON（保留 body/attrs/type 等），使恢复的索引条目
                # 完整可用（recall 不必再读盘），三层（文件↔SQLite data↔index.json）一致。
                entry_full = dict(mm)
                entry_full["file"] = ("archive/" + mid + ".json") if is_archived else (mid + ".json")
                entry_full.setdefault("id", mid)
                entry_full.setdefault("category", "")
                entry_full.setdefault("summary", "")
                entry_full.setdefault("tags", [])
                entry_full.setdefault("tier", "working")
                entry_full.setdefault("scope", "universal")
                entry_full.setdefault("project", "")
                entry_full.setdefault("status", "active")
                data["entries"].append(entry_full)
                added += 1
            except Exception:
                pass
        # P2：三层内容回填——以文件为准，把索引条目的可变内容字段同步成文件内容，
        # 修复「文件新、索引旧」漂移（content_mismatch）。文件是内容真源，SQLite data 列/index.json 是派生镜像。
        resynced = 0
        for e in data["entries"]:
            m = mems.get(e.get("id"))
            if not m:
                continue
            if _index_content_sig(e) != _index_content_sig(m):
                # 只回填索引字段集内的内容字段；严禁 `for k,v in m.items: e[k]=v` 旧行为），
                # 那会把 body 正文/向量等大字段灌进精简索引，撑爆 index.json 并污染 L0 过滤读取面。
                for k in _INDEX_CONTENT_FIELDS:
                    if k in m:
                        e[k] = m[k]
                resynced += 1
        result["content_resynced"] = resynced
        pruned = 0
        for m in mems.values():
            rels = m.get("relations") or {}
            if not rels:
                continue
            changed = False
            for rel, tgts in list(rels.items()):
                if isinstance(tgts, list):
                    new = [t for t in tgts if t in file_ids]
                    if len(new) != len(tgts):
                        rels[rel] = new
                        changed = True
                elif isinstance(tgts, str) and tgts not in file_ids:
                    del rels[rel]
                    changed = True
            if changed:
                if not rels:
                    m.pop("relations", None)
                _save_mem(root, m["id"], m)
                pruned += 1
        save_index(root, data)
        # 修复 inverted（标签倒排）SQLite 表：orphan_added/status_synced 等改变了索引结构，
        # 不重建的话 recall --tag 会查不到新加的孤儿。直接清空按当前 entries 全量重建一次。
        try:
            conn = _db_conn(root)
            try:
                conn.execute("DELETE FROM inverted")
                rows = [(t, e.get("id")) for e in data["entries"]
                        for t in (e.get("tags") or []) if e.get("id")]
                if rows:
                    conn.executemany("INSERT OR IGNORE INTO inverted(tag, id) VALUES (?, ?)", rows)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # inverted 表缺失/损坏时不致命，recall 会自动回退全量 entries 遍历
        # ⑤ 矛盾候选软标记（doctor --contradictions --fix）：双方 relations.conflict 互记对方 id，
        # 非破坏性（不合并/不删/不改 status），仅留痕供 agent/人工裁决（FLAG/UPDATE/SKIP）。
        # C3：已裁决账本去重——同一对记忆不会反复冒泡打扰用户。
        conflict_marked = 0
        skipped_reviewed = 0
        _reviewed_file = os.path.join(root, "store", "contradiction_reviewed.json")
        _reviewed = set()
        try:
            with open(_reviewed_file, encoding="utf-8") as _rvf:
                _reviewed = set(json.load(_rvf))
        except Exception:
            pass
        # 合并主通道 + C1 相邻 lane 候选，统一软标记（C3 账本去重覆盖两者）
        _conflict_all = (result.get("contradiction_candidates") or []) + \
                        (result.get("adjacent_contradiction_candidates") or [])
        for c in _conflict_all:
            # 排序对保证 (a,b) 与 (b,a) 命中同一 key
            _pair_key = tuple(sorted([c["a"], c["b"]]))
            if _pair_key in _reviewed:
                skipped_reviewed += 1
                continue
            for xid, yid in ((c["a"], c["b"]), (c["b"], c["a"])):
                try:
                    xm = _load_mem(root, xid)[0]
                    rel = xm.setdefault("relations", {})
                    _cf = rel.get("conflict")
                    if not isinstance(_cf, list):
                        rel["conflict"] = [_cf] if _cf else []
                    if yid not in rel["conflict"]:
                        rel["conflict"].append(yid)
                        _save_mem(root, xid, xm)
                        conflict_marked += 1
                except Exception:
                    pass
            # 标记为已裁决（无论 FLAG/UPDATE/SKIP，不再重复扫描）
            _reviewed.add(_pair_key)
        # 持久化裁决账本（追加式，不丢历史）
        try:
            with open(_reviewed_file, "w", encoding="utf-8") as _rvw:
                json.dump(sorted(_reviewed), _rvw)
        except Exception:
            pass
        result["skipped_reviewed"] = skipped_reviewed
        # ⑥ 嵌入回填（A3, ：修复后确保「索引里的每条 active 记忆都有向量」，
        # 否则语义召回会漏掉刚补登的孤儿记忆。_ensure_embeddings 只为缺失/文本变更者重算，
        # 健康库为幂等 no-op。需嵌入后端不可用（无 fastembed 且无线上）时静默跳过，不致命。
        embed_backfilled = 0
        try:
            _eb = _ensure_embeddings(root)
            embed_backfilled = _eb.get("embedded", 0) if isinstance(_eb, dict) else 0
        except Exception as _ee:
            import sys as _sys2
            _sys2.stderr.write("[⚠ doctor --fix] 嵌入回填跳过: %s\n" % _ee)
        # B5 ：按召回频次幂等重算 importance（频繁召回升温、零召回回先验降温）
        importance_recomputed = 0
        try:
            importance_recomputed = _recompute_importance_from_recall(root)
        except Exception as _ie:
            import sys as _sys3
            _sys3.stderr.write("[⚠ doctor --fix] 频次重要性重算跳过: %s\n" % _ie)
        result["fixed"] = {"dropped_index_entries": dropped,
                           "status_synced": synced,
                           "orphan_added": added,
                           "dangling_rels_pruned": pruned,
                           "conflict_marked": conflict_marked,
                           "embed_backfilled": embed_backfilled,
                           "importance_recomputed": importance_recomputed}
    # B6' ：嵌入后端健康面（只读，不触盘）
    try:
        result["embed_backend"] = _doctor_embed_backend(root)
    except Exception as _ebe:
        result["embed_backend"] = {"error": "doctor_embed_backend failed: %s" % _ebe}
    # F14：投资域不变式 lint（validated_by 证据链）——只读、异常自吞，绝不拖累 doctor。
    try:
        result["investment_invariants"] = _check_investment_invariants(root)
    except Exception as _iv:
        result["investment_invariants"] = {"error": "investment invariant check failed: %s" % _iv}
    # P1：契约层健康聚合（doctor_contract：门控/注入日志/路由分布/晋升候选）+
    # 显式极性矛盾扫描（scan_contradictions，与既有向量/Jaccard 互补）。全部 fail-open。
    _c_doctor = _c_rr_cls = _c_scan = None
    try:
        from contract.observ import doctor_contract as _c_doctor
        from contract.router import RouteRegistry as _c_rr_cls
        from contract.consistency import scan_contradictions as _c_scan
    except Exception:
        _c_doctor = _c_rr_cls = _c_scan = None
    try:
        if _c_doctor:
            _hooks_dir = os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks"))
            _inj_log = os.path.join(_hooks_dir, "inject_log.jsonl")
            _rr_path = os.path.join(root, "store", "route_registry.json")
            _rr = _c_rr_cls(_rr_path) if (_c_rr_cls and os.path.exists(_rr_path)) else None
            # 4.9.17 修复（同族：恒量值冒充实测）：neural_active 原为硬编码 False，
            # 使 doctor 的 contract.neural_recall_active 永远是 false（与真实后端脱节）。
            # 现复用上方 _doctor_embed_backend 的权威探测结果：真实后端非 lexical 即视为语义活跃。
            _eb = result.get("embed_backend") or {}
            _na = bool(_eb.get("backend") and _eb.get("backend") != "lexical")
            result["contract"] = _c_doctor(_inj_log, route_registry=_rr, neural_active=_na)
        else:
            result["contract"] = {"error": "contract modules unavailable"}
    except Exception as _ce:
        result["contract"] = {"error": "doctor_contract failed: %s" % _ce}
    if contradictions and _c_scan:
        try:
            _facts = [{"id": m.get("id"),
                       "statement": ((m.get("summary") or "") + " " + (m.get("body") or "")),
                       "layer": "L4"}
                      for m in mems.values() if m.get("status") == "active"]
            result["explicit_polarity_contradictions"] = _c_scan(_facts)
        except Exception as _se:
            result["explicit_polarity_contradictions"] = {
                "error": "scan_contradictions failed: %s" % _se}
    # E1：钩子与调度自检——把"装了但没生效"变成可见可诊断状态。
    try:
        result["hooks"] = _check_hooks_status()
    except Exception as _he:
        # 不吞根因（同 scheduler）：否则用户只看到"检查失败"，无从下手。
        result["hooks"] = {
            "error": "hooks status check failed",
            "detail": "%s: %s" % (type(_he).__name__, _he),
        }
    try:
        result["scheduler"] = _check_scheduler_status(no_cache=no_cache)
    except Exception as _se:
        # 不吞根因：否则用户只看到"检查失败"，分不清是没装调度任务还是命令被拦。
        result["scheduler"] = {
            "error": "scheduler status check failed",
            "detail": "%s: %s" % (type(_se).__name__, _se),
        }
    # E2：部署一致性——"我更新了 keeper，到底生效没有"（钩子/守护副本不随技能自动刷新）。
    try:
        result["deployment"] = _check_deployment_status()
    except Exception as _de:
        result["deployment"] = {
            "error": "deployment check failed",
            "detail": "%s: %s" % (type(_de).__name__, _de),
        }
    # 2026-09-15 审计：doctor 建议项 ack 抑制（治标层，配合 P0-2 的降级治本）。
    # 只过滤「建议类」条目；完整性类（缺文件/悬空/漂移/损坏）永不受影响。
    try:
        result["ack"] = _apply_doctor_ack(root, result, ack_all=ack_all)
    except Exception as _ake:
        result["ack"] = {"error": "ack apply failed: %s" % _ake}
    return result

def token_report(root, top_n=10):
    """token 用量报告（P1-D）：按 tier/scope/category 统计 token，列出最大 top_n 记忆。
    纯只读，零依赖（token_estimate 为启发式估算，非真实 tokenizer）。"""
    mems = _all_mems(root)
    by_tier, by_scope, by_cat = {}, {}, {}
    total = 0
    rows = []
    for m in mems.values():
        t = token_estimate(m)
        total += t
        tier = m.get("tier", "working")
        scope = m.get("scope", "universal")
        cat = m.get("category", "")
        by_tier[tier] = by_tier.get(tier, 0) + t
        by_scope[scope] = by_scope.get(scope, 0) + t
        by_cat[cat] = by_cat.get(cat, 0) + t
        rows.append({"id": m.get("id"), "category": cat, "tier": tier,
                     "scope": scope, "tokens": t})
    rows.sort(key=lambda r: r["tokens"], reverse=True)
    return {
        "total_tokens": total,
        "count": len(rows),
        "by_tier": by_tier,
        "by_scope": by_scope,
        "by_category": by_cat,
        "top": rows[:top_n],
    }

def backup(root, dest=None, progress=False):
    """整库备份：把 memories/、memories/archive/、index.json、classifier.json、
    config（如有）、store/index.db（SQLite 向量库）、store/clusters.json（聚类质心）
    打包成一个 ZIP。dest 不传则落到 root/../ai_memory_backup_<时间戳>.zip。
    零依赖（zipfile 标准库）。返回 zip 路径。"""
    import zipfile
    init_store(root)
    # WAL 模式下先把未落盘数据 checkpoint 回主库文件，保证 index.db 单文件自包含
    _db_checkpoint_truncate(root)
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(os.path.dirname(os.path.abspath(root)),
                            "ai_memory_backup_%s.zip" % ts)
    src_files = []
    for d in (mem_dir(root), archive_dir(root)):
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    src_files.append((os.path.join(d, fn),
                                      os.path.relpath(os.path.join(d, fn), root).replace("\\", "/")))
    for fn in ("index.json", "classifier.json", "config.json"):
        p = os.path.join(root, fn)
        if os.path.exists(p):
            src_files.append((p, fn))
    # F6 修复：备份 SQLite 向量库（store/index.db）与聚类质心（store/clusters.json）。
    # 漏备会导致 restore 后语义召回返回"幽灵记忆"（文件已不存在但 embeddings 仍在）。
    _store_dir = os.path.join(root, "store")
    for fn in ("index.db", "clusters.json", "meta.json"):
        p = os.path.join(_store_dir, fn)
        if os.path.exists(p):
            src_files.append((p, "store/" + fn))
    if progress:
        _tot = len(src_files)
        _est = sum(os.path.getsize(s[0]) for s in src_files if os.path.exists(s[0]))
        sys.stderr.write("[backup] 预估 %d 个文件，约 %.1f MB\n" % (_tot, _est / 1048576.0))
        sys.stderr.flush()
    # C8 ：生成完整性 manifest（每文件 sha256），随包携带——备份可携带、
    # 可在任意机器校验是否被篡改/损坏，restore 时自动比对。
    manifest = {
        "backup_version": 1,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "checksum_algo": "sha256",
        "file_count": len(src_files),
        "entries": [],
    }
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        _total = len(src_files)
        for _i, (full, arc) in enumerate(src_files, 1):
            zf.write(full, arc)
            if progress and _i % 25 == 0:
                sys.stderr.write("\r[backup] 进度 %d/%d" % (_i, _total))
                sys.stderr.flush()
            try:
                _h = hashlib.sha256()
                with open(full, "rb") as _f:
                    for _chunk in iter(lambda: _f.read(65536), b""):
                        _h.update(_chunk)
                manifest["entries"].append({"path": arc, "size": os.path.getsize(full),
                                            "sha256": _h.hexdigest()})
            except OSError:
                manifest["entries"].append({"path": arc, "size": -1, "sha256": None})
        # manifest 本身也写入包（可携带、自描述）
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
    return dest

def _prune_doctor_fix_backups(root, keep=5):
    """P2 收尾：doctor --fix 生成的 doctor_fix_backup_*.zip 自动清理。
    保留最近 keep 份（默认 5；可用环境变量 KEEPER_DOCTOR_FIX_BACKUP_KEEP 调整），删除更旧的。
    安全闸：
      - 仅在本函数被调用（即已成功生成新备份）后执行；绝不在生成前删；
      - 若目录下不足 keep+1 份则不动，确保至少保留 keep 份 + 当前刚生成的这一份；
      - 删除失败不致命（best-effort）。"""
    try:
        keep = int(os.environ.get("KEEPER_DOCTOR_FIX_BACKUP_KEEP", str(keep)))
    except Exception:
        keep = 5
    if keep < 1:
        keep = 1
    parent = os.path.dirname(os.path.abspath(root))
    try:
        zips = sorted(
            (os.path.join(parent, f) for f in os.listdir(parent)
             if f.startswith("doctor_fix_backup_") and f.endswith(".zip")),
            key=lambda p: os.path.getmtime(p))
    except OSError:
        return []
    if len(zips) <= keep:
        return []
    remove = zips[:-keep]
    deleted = []
    for p in remove:
        _gone = False
        try:
            os.remove(p)
            _gone = not os.path.exists(p)
        except OSError:
            _gone = False
        # Windows safe-delete shim 可能把 os.remove 包成「返回成功但实际未删」或
        # FAIL_CLOSED；删后查存在性，未真删则用原生 Win32 DeleteFileW 兜底（不走回收站）。
        if not _gone and sys.platform == "win32":
            try:
                import ctypes
                if ctypes.windll.kernel32.DeleteFileW(p):
                    _gone = not os.path.exists(p)
            except Exception:
                _gone = False
        if _gone:
            deleted.append(os.path.basename(p))
    return deleted

def _verify_backup_zip(zf):
    """C8 ：校验备份 ZIP 内 manifest 与实际文件 sha256 是否一致。
    
    返回 {ok, algo, file_count, checked, mismatches, missing_in_zip, extra_files, note}。
    无 manifest（旧版/手工打包）时 ok=False 且 note 说明，restore 需 --force 才恢复。"""
    import hashlib
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (KeyError, json.JSONDecodeError):
        return {"ok": False, "algo": None, "file_count": 0, "checked": 0,
                "mismatches": [], "missing_in_zip": [], "extra_files": [],
                "entries": [],
                "note": "备份不含 manifest.json（旧版或手工打包），无法校验完整性；"
                        "如需强制恢复加 --force。"}
    algo = manifest.get("checksum_algo", "sha256")
    entries = manifest.get("entries", [])
    mismatches = []
    missing_in_zip = []
    names = set(zf.namelist())
    for e in entries:
        p = e.get("path")
        exp = e.get("sha256")
        if not p or p not in names:
            missing_in_zip.append(p)
            continue
        if not exp:
            continue  # 备份时读取失败的项，跳过其校验（不误判）
        try:
            actual = hashlib.sha256(zf.read(p)).hexdigest()
        except Exception:
            mismatches.append({"path": p, "expected": exp, "actual": "(unreadable)"})
            continue
        if actual != exp:
            mismatches.append({"path": p, "expected": exp, "actual": actual})
    manifest_paths = {e.get("path") for e in entries}
    extra = [n for n in names if n not in manifest_paths and n != "manifest.json"]
    ok = (not mismatches) and (not missing_in_zip)
    return {"ok": ok, "algo": algo, "file_count": len(entries),
            "checked": len(entries) - len(missing_in_zip),
            "mismatches": mismatches, "missing_in_zip": missing_in_zip,
            "extra_files": extra, "entries": entries,
            "note": "ok" if ok else "完整性校验失败，详见 mismatches / missing_in_zip"}

def _safe_extract_member(zf, name, dest_root):
    """安全抽取单个 ZIP 成员到 dest_root：严格路径遏制，拒绝绝对路径 / ../ 穿越 /
    盘符前缀（如 C:），不依赖 Python 版本的运行期 sanitize，根治 zip-slip。
    返回 True（已抽取）/ False（已跳过危险路径）。"""
    if not name:
        return False
    norm = name.replace("\\", "/")
    head = norm.split("/", 1)[0]
    # 绝对路径、盘符根（C:）、Windows 反斜杠根 一律拒绝
    if norm.startswith("/") or norm.startswith("\\") or ":" in head:
        return False
    if ".." in norm.split("/"):
        return False
    target = os.path.normpath(os.path.join(dest_root, norm))
    base = os.path.normpath(dest_root)
    if target != base and not target.startswith(base + os.sep):
        return False
    try:
        zf.extract(name, dest_root)
    except (OSError, KeyError):
        return False
    return True

def restore(root, zip_path, dry_run=False, yes=False, verify=False, force=False):
    """从备份 ZIP 恢复整库（P1-D）。C8 增强：携带 manifest 完整性校验。
    
    - 校验 ZIP 自身完整性（testzip）防截断/字节损坏；
    - 读取包内 manifest.json，逐文件比对 sha256（可携带、跨机器可校验）；
    - `--verify`：仅校验完整性、不提取（安全预览损坏情况）；
    - 实际恢复前若完整性校验失败且未 `--force`，拒绝恢复（防还原损坏备份）；
    - `--force`：跳过完整性中止（不推荐，仅用于明知损坏仍要抢救部分文件）。
    无 --yes 拒绝执行（不可逆操作，安全网与 delete 一致）。返回 dict。"""
    import zipfile
    if not os.path.exists(zip_path):
        raise FileNotFoundError("备份文件不存在: %s" % zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        # ① ZIP 自身完整性（防截断/字节损坏）
        _bad = zf.testzip()
        if _bad is not None:
            return {"ok": False, "error": "zip_corrupt", "bad_file": _bad,
                    "msg": "备份 ZIP 自身损坏（testzip 检测到 %s），拒绝恢复。" % _bad}
        names = zf.namelist()
        # index.json 是备份的本质标记（空库备份可能只有 index.json，无 memories/ 目录）。
        # 只要有 index.json 即视为合法备份；memories/ 缺失仅代表库为空，恢复后即为空库。
        if "index.json" not in names:
            raise ValueError("备份 ZIP 结构非法：缺少 index.json，拒绝恢复。")
        # C8：完整性校验（manifest 比对）
        _integrity = _verify_backup_zip(zf)
        if verify:
            return {"op": "restore", "verify_only": True, "zip": zip_path,
                    "integrity": _integrity}
        if dry_run:
            return {"dry_run": True, "op": "restore", "zip": zip_path,
                    "contains": names, "will_overwrite": root,
                    "integrity": _integrity}
    if not yes:
        return {"ok": False, "error": "confirm_required",
                "msg": "restore 会清空当前记忆库并用备份覆盖（不可逆）。",
                "hint": "确认要恢复请加 --yes；想先看内容加 --dry-run；想校验完整性加 --verify。",
                "integrity": _integrity}
    # 实际恢复前：完整性校验失败且未 --force → 中止（防还原损坏备份）
    if not force and not _integrity.get("ok"):
        return {"ok": False, "error": "integrity_failed",
                "msg": "备份完整性校验未通过，拒绝恢复（加 --force 可强制，但不推荐）。",
                "integrity": _integrity}
    # ── 恢复实施：staging + 原子交换（P0 加固，──
    # 旧实现：先逐文件删当前库再 zf.extractall(root)——extractall 不做路径遏制，
    # 会解压任意成员（含 ../ 穿越、非 manifest 的额外文件），且中途失败=当前库永久丢失。
    # 新实现：① 仅解压「清单内条目」+ 逐条路径遏制（拒绝 ../ 与绝对路径）；
    # ② 先解压到 staging 临时目录，校验通过后再原子交换（当前库→bak 兜底、staging→root），
    # 任一环节失败回滚，当前库始终不被破坏；成功后才清 bak。整库恢复语义更正确
    # （旧实现会残留未知文件，现整库替换）。
    parent = os.path.dirname(os.path.abspath(root))
    staging = os.path.join(parent, ".restore_staging_%s" % uuid.uuid4().hex)
    bak = os.path.join(parent, ".restore_bak_%s" % uuid.uuid4().hex)
    os.makedirs(staging, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest_entries = _integrity.get("entries") if isinstance(_integrity, dict) else None
            if manifest_entries:
                # 仅解压清单内条目（防备份夹带额外文件）
                for e in manifest_entries:
                    _safe_extract_member(zf, e.get("path"), staging)
            else:
                # 旧版/手工备份（无 manifest，已要求 --force）：仅做路径遏制后全量解压
                for n in names:
                    if n == "manifest.json":
                        continue
                    _safe_extract_member(zf, n, staging)
        if not os.path.exists(os.path.join(staging, "index.json")):
            raise ValueError("恢复内容缺少 index.json，疑似备份不完整，已中止且不改动当前库。")
    except Exception as _ex:
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": "extract_failed", "msg": str(_ex),
                "integrity": _integrity}
    # 还原实施：逐文件移动式交换，规避 Windows「整目录 os.rename 被外部进程锁定报
    # WinError 5」的固有脆弱性（整库 rename/replace 原子交换在目录被锁时必失败）。
    # 做法：① 把当前库安全复制为 bak 作为回滚兜底（优先 rename，失败则 copytree）；
    # ② 清空当前库内文件（保留目录骨架，避免目录级锁）；③ staging 逐文件移入 root。
    # 任一环节失败 → 从 bak 还原当前库，staging 丢弃。成功后才清 bak / staging。
    _bak_ok = False
    try:
        if os.path.exists(root) and os.listdir(root):
            try:
                os.rename(root, bak)
            except OSError:
                if os.path.isdir(bak):
                    shutil.rmtree(bak, ignore_errors=True)
                # 关键：跳过运行时锁文件。restore 自身持有 memories/.write_lock
                # 的独占句柄，copytree 复制它必报 [Errno 13] Permission denied，
                # 导致 bak 建立失败 → swap_failed → 备份无法恢复（自锁死）。
                # 锁文件是纯运行时产物，不需要备份，回滚时会自动重建。
                shutil.copytree(root, bak, ignore=shutil.ignore_patterns(
                    ".write_lock", ".write.lock", "*.lock"))
            _bak_ok = True
        # ② 清空当前库内文件（保留目录骨架）
        if os.path.isdir(root):
            for _dn, _ds, _fs in os.walk(root, topdown=False):
                for _f in _fs:
                    try:
                        os.remove(os.path.join(_dn, _f))
                    except OSError:
                        pass
        # ③ staging 内容逐文件移入 root
        for _sn, _sd, _sf in os.walk(staging):
            _rel = os.path.relpath(_sn, staging)
            _dst = root if _rel == "." else os.path.join(root, _rel)
            os.makedirs(_dst, exist_ok=True)
            for _f in _sf:
                _src = os.path.join(_sn, _f)
                _tgt = os.path.join(_dst, _f)
                try:
                    os.replace(_src, _tgt)
                except OSError:
                    shutil.copy2(_src, _tgt)
                    os.remove(_src)
    except Exception as _ex:
        # 回滚：从 bak 还原当前库，staging 丢弃（仅当 bak 已成功建立才回滚，
        # 避免 bak 建立失败反而误删完好当前库）
        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)
        if _bak_ok and os.path.exists(bak):
            try:
                if os.path.isdir(root):
                    shutil.rmtree(root, ignore_errors=True)
                os.rename(bak, root)
            except OSError:
                try:
                    if not os.path.isdir(root):
                        shutil.copytree(bak, root)
                except OSError:
                    pass
        return {"ok": False, "error": "swap_failed", "msg": str(_ex),
                "integrity": _integrity}
    # 交换成功：清理 bak（旧库）与 staging
    shutil.rmtree(bak, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    _tag_index_reset(root)
    extracted = (len(manifest_entries)
                 if manifest_entries
                 else len([n for n in names if n != "manifest.json"]))
    return {"ok": True, "restored": root, "from": zip_path, "files": extracted,
            "integrity": _integrity}


# ─────────────────────────────────────────────────────────────────────────────
# 4.9.24 · 生命周期补口
#   发布端：release_audit —— CHANGELOG 版本账 ↔ 平台真实发布版本
#   运维端：backup_prune  —— 备份保留 N 份，更旧的**搬**走而非删
# 本模块由 __init__ 运行期注入符号（顶部零 import）→ 新增依赖一律函数内 import。
# ─────────────────────────────────────────────────────────────────────────────


def _volume_missing(path):
    """判断 path 所在**卷/盘**当前是否不可见（移动盘没插、网络盘掉线）。

    🔴 为什么必须按「卷」而不是按「路径」判：目标路径不存在有两种来路——
      ① 库真的被删了；② 库所在的盘此刻没挂上。二者混淆 = 把「盘没插」误判成
      「库没了」→ 触发下游「没备份 / 库丢了」告警。宁可漏判，不可误判。
    POSIX 上挂载点判据不可靠，一律返回 False（保守：视为可见，不做孤儿判定）。
    """
    if os.name != "nt":
        return False
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            return False
        return not os.path.exists(drive + os.sep)
    except Exception:
        return False


def _discover_daemon_roots():
    """从守护进程 STATE 里捞出「本机跑过哪些库」。

    STATE（`.daemon-<指纹>.json`）自 4.9.13 起带 `root` 字段——它是一处**现成的**
    「库 → 指纹」证据源，可直接对表。
    纯只读；异常一律吞掉（发现失败只影响判定覆盖面，不影响正确性）。
    """
    import glob as _glob
    import json as _json
    dirs = []
    try:
        dirs.append(os.path.join(os.path.expanduser("~"), ".workbuddy", "keeper_daemon"))
    except Exception:
        pass
    try:
        sr = _skill_root()
        if sr:
            dirs.append(os.path.join(sr, "keeper_daemon"))
    except Exception:
        pass
    roots, seen = [], set()
    for d in dirs:
        for p in _glob.glob(os.path.join(d, ".daemon*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    st = _json.load(f)
                rt = st.get("root") if isinstance(st, dict) else None
            except Exception:
                continue
            if rt and rt not in seen:
                seen.add(rt)
                roots.append(rt)
    return roots


def backup_prune(root, keep, protect=None):
    """整库备份只留最近 keep 份，更旧的**搬**进同级 `_retired_backups_<日期>/`。

    🔴 只搬不删：备份是灾难恢复的最后一道，任何自动化都不得硬删（红线 A2）。
    `keep` 含本次刚生成的那份（故 <1 会被抬到 1）；`protect` 指定的那份永不入选。
    """
    import glob as _glob
    try:
        keep = int(keep)
    except Exception:
        return {"ok": False, "error": "bad_keep", "msg": "keep 必须是整数"}
    if keep < 1:
        keep = 1
    parent = os.path.dirname(os.path.abspath(root))
    try:
        zips = sorted(_glob.glob(os.path.join(parent, "ai_memory_backup_*.zip")),
                      key=lambda p: os.path.getmtime(p), reverse=True)
    except Exception as e:
        return {"ok": False, "error": "list_failed", "msg": str(e)}
    pabs = os.path.abspath(protect) if protect else None
    victims = [p for p in zips[keep:] if not (pabs and os.path.abspath(p) == pabs)]
    if not victims:
        return {"ok": True, "kept": min(len(zips), keep), "n_total": len(zips),
                "retired": [], "retired_dir": "", "errors": []}
    rdir = os.path.join(parent, "_retired_backups_%s" % datetime.date.today().isoformat())
    moved, errs = [], []
    try:
        os.makedirs(rdir, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": "mkdir_failed", "msg": str(e)}
    for v in victims:
        dst = os.path.join(rdir, os.path.basename(v))
        if os.path.exists(dst):
            dst = dst + ".%d" % int(time.time())
        try:
            os.rename(v, dst)          # 同卷 rename：不触发删除守卫、可逆
            moved.append(os.path.basename(v))
        except Exception as e:
            errs.append("%s: %s" % (os.path.basename(v), e))
    return {"ok": not errs, "kept": min(len(zips), keep), "n_total": len(zips),
            "retired": moved, "retired_dir": rdir if moved else "", "errors": errs}


def _parse_ver(v):
    """'4.9.23' → (4, 9, 23)；解析不出返回 None（绝不抛）。"""
    try:
        parts = [int(x) for x in str(v).strip().split(".")]
    except Exception:
        return None
    if not parts:
        return None
    return tuple((parts + [0, 0, 0])[:3])


def release_audit(root=None, skill_root=None, timeout=8, offline=False,
                  api_base=None, changelog_versions=None, platform_versions=None,
                  window_since=None, main_only=None):
    """发布账本核对：CHANGELOG 记录的版本 ↔ 平台真实发布的版本。

    为什么需要（4.9.23 的「双主」事故）：另一台机器连发版本、本机毫不知情——
    因为「线上到底发到几版」此前只存在于人的记忆里。本命令把它变成机器可查。

    口径（三条，都是为了「不误报」）：
      1. **权威窗口**：历史 CHANGELOG 会轮转归档，早年版本常被合并成摘要条目，
         对全史做集合差会常年误报。故只比对「主 `CHANGELOG.md` 里最早版本」之后的
         区间（`window_since`）；更早的平台独有版本归入 `legacy_missing`（信息项）。
      2. **区间标题**：`## 4.8.2–4.8.7` 这类连续迭代的合并条目，按区间覆盖处理，
         不要求逐版本单列。
      3. **本地未发布 ≠ 漂移**：本地版本高于线上（可以累积**多个**未发布版本）是「改完没发」
         的正常状态（本项目默认不主动发布），一律记 `unreleased_local` 提示、不算 drift。

    判定（**只认两类 drift**，其余一律只提示——假红灯会让真红灯被无视）：
      missing_log = 窗口内、平台有、日志无 → 有人绕过日志发布 → **drift**
      local < platform_latest → **drift**（多机并行时这正是「双主」前兆）
    只提示、不算 drift：
      bundled          = 日志有、平台无、且平台已越过它（其后有更晚版本）→ 改动随后续版本发出
      unreleased_local = 日志有、平台无、且不早于平台最新版 → 本地记录未上线；本项目约定
                         「未经用户明确要求不主动发布更新」，故这是**正常状态**
      legacy_missing   = 窗口外、平台独有的早年版本（归档区未逐版记录）→ 信息项
      拿不到平台数据 → verdict="unknown"（CLI 退出码 3）：「不知道」绝不当作「有问题」。
    只读：不写任何文件。`changelog_versions` / `platform_versions` / `api_base` /
    `window_since` 供测试注入，生产不用传。
    """
    import glob as _glob
    import json as _json
    import re as _re
    out = {
        "ok": False, "verdict": "unknown",
        "mode": "offline" if offline else "online",
        "skill_root": "", "slug": "", "local_version": "", "installed_version": "",
        "changelog_versions": [], "changelog_ranges": [], "archive_versions": [],
        "platform_versions": [], "window_since": "",
        "missing_log": [], "bundled": [], "unreleased_local": [],
        "legacy_missing": [], "platform_latest": "",
        "hints": [], "error": None,
    }
    sr = skill_root
    if not sr:
        try:
            sr = _skill_root()
        except Exception:
            sr = ""
    out["skill_root"] = sr or ""
    if not sr or not os.path.isdir(sr):
        out["error"] = "skill_root_not_found"
        out["hints"].append("定位不到技能根目录（需含 SKILL.md / CHANGELOG.md），无法核对。")
        return out

    # 🔴 版本字段**语义分离**（5.0.0 修正）。此前把两个**不同概念**当成「同一概念的两种
    # 来源」做「优先 _meta.json，回退 SKILL.md frontmatter」，结果**开发者机器上永远读到
    # 陈旧值**（源码 5.0.0，却报 local_version=4.9.25）：
    #   · `local_version`     = **本地源码版本** ← SKILL.md frontmatter。这是本仓约定的
    #                            「版本单一真源」（见 `_hooks._read_skill_version`）。
    #   · `installed_version` = **平台上次发布 / 本机已安装的版本** ← `_meta.json`。发布器
    #                            `update_meta()` 在发布成功后回写它，且该文件不进发布包。  deadref-ok
    # 纯净用户机上两者一致；开发机上源码领先（有未发布改动）是**常态**。二者混用会让
    # 「双主」告警（见下方版本对比）在源码领先时**误报**，并给出会覆盖本地改动的指引。
    v_source = ""
    try:
        with open(os.path.join(sr, "SKILL.md"), encoding="utf-8-sig") as f:
            for line in f:
                s = line.strip()
                if s.startswith("version:"):
                    v_source = s.split(":", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
    v_installed = ""
    try:
        mp = os.path.join(sr, "_meta.json")
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                meta = _json.load(f)
            if isinstance(meta, dict):
                v_installed = str(meta.get("version") or "")
                out["slug"] = str(meta.get("slug") or "")
    except Exception:
        pass
    out["local_version"] = v_source or v_installed
    out["installed_version"] = v_installed

    _RE_EXACT = _re.compile(r"^##\s+(\d+\.\d+\.\d+)\b")
    _RE_RANGE = _re.compile(
        r"^##\s+(\d+\.\d+\.\d+)\s*[\u2013\u2014~-]\s*(\d+\.\d+\.\d+)")

    def _scan(path):
        """→ (exact[], ranges[[lo,hi]])；文件缺失返回 ([], [])。"""
        ex, rg = [], []
        if not os.path.isfile(path):
            return ex, rg
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                m = _RE_RANGE.match(line)
                if m:
                    lo, hi = _parse_ver(m.group(1)), _parse_ver(m.group(2))
                    if lo and hi:
                        rg.append([lo, hi])
                    continue
                m = _RE_EXACT.match(line)
                if m:
                    ex.append(m.group(1))
        return ex, rg

    cl, cl_ranges = ([], [])
    if changelog_versions is None:
        try:
            cl, cl_ranges = _scan(os.path.join(sr, "CHANGELOG.md"))
        except Exception as e:
            out["error"] = "changelog_unreadable"
            out["hints"].append("读不到 CHANGELOG.md：%s" % e)
            return out
        if not cl and not cl_ranges:
            out["error"] = "changelog_no_versions"
            out["hints"].append("CHANGELOG.md 里找不到任何「## X.Y.Z」版本标题——格式变了吗？")
            return out
    else:
        cl = list(changelog_versions)
    # 归档历史（`references/**/changelog_archive*.md`）只用于**覆盖**判定，不扩展窗口
    arc, arc_ranges = ([], [])
    if main_only is not True and changelog_versions is None:
        for p in sorted(_glob.glob(os.path.join(sr, "references", "**",
                                                "changelog_archive*.md"), recursive=True)):
            try:
                _a, _ar = _scan(p)
                arc += _a
                arc_ranges += _ar
            except Exception:
                continue

    vkey = lambda s: _parse_ver(s) or (0, 0, 0)
    out["changelog_versions"] = sorted(set(cl), key=vkey)
    out["changelog_ranges"] = ["%s–%s" % (".".join(map(str, lo)), ".".join(map(str, hi)))
                               for lo, hi in cl_ranges]
    out["archive_versions"] = sorted(set(arc), key=vkey)

    # 窗口起点：主 CHANGELOG 的最早版本（含区间下界）
    if window_since:
        ws = _parse_ver(window_since)
    else:
        lows = [_parse_ver(v) for v in cl] + [r[0] for r in cl_ranges]
        lows = [x for x in lows if x]
        ws = min(lows) if lows else (0, 0, 0)
    out["window_since"] = ".".join(str(x) for x in ws)

    documented = set(cl) | set(arc)
    ranges = cl_ranges + arc_ranges

    def _documented(v):
        p = _parse_ver(v)
        if p is None:
            return False
        if v in documented:
            return True
        return any(lo <= p <= hi for lo, hi in ranges)

    # 平台版本集
    pv = platform_versions
    if pv is None:
        if offline:
            out["hints"].append(
                "离线（--offline）：未查询平台，**无法判定一致性**——这是「不知道」不是「有问题」。")
            return out
        if not out["slug"]:
            out["error"] = "slug_unknown"
            out["hints"].append("_meta.json 里没有 slug，拼不出平台查询地址（下载/安装副本才带它）。")
            return out
        import urllib.request
        base = (api_base or "https://api.skillhub.cn").rstrip("/")
        url = "%s/api/v1/skills/%s/versions" % (base, out["slug"])
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = _json.loads(r.read().decode("utf-8"))
            items = data.get("versions") if isinstance(data, dict) else data
            pv = [str(it.get("version")) for it in (items or [])
                  if isinstance(it, dict) and it.get("version")]
            if not pv:
                out["error"] = "platform_empty"
                out["hints"].append("平台返回了版本列表但内容为空（%s）——按「未知」处理。" % url)
                return out
        except Exception as e:
            out["error"] = "network_unavailable"
            out["hints"].append(
                "查不到平台版本（%s: %s）——**这是「未知」不是「有问题」**："
                "联网后重跑即可，离线不影响任何本地功能。" % (type(e).__name__, e))
            return out
    out["platform_versions"] = sorted(set(pv), key=vkey)

    pv_set = set(out["platform_versions"])
    out["platform_latest"] = max(pv_set, key=vkey) if pv_set else ""
    latest_p = _parse_ver(out["platform_latest"]) or (0, 0, 0)

    in_win = lambda v: (_parse_ver(v) or (0, 0, 0)) >= ws
    undoc = sorted([v for v in pv_set if not _documented(v)], key=vkey)
    out["missing_log"] = [v for v in undoc if in_win(v)]
    out["legacy_missing"] = [v for v in undoc if not in_win(v)]

    doc_ge = sorted([v for v in documented if in_win(v)], key=vkey)
    unreleased = [v for v in doc_ge if v not in pv_set]
    _pk = lambda v: _parse_ver(v) or (0, 0, 0)
    out["bundled"] = [v for v in unreleased if _pk(v) < latest_p]
    # 不早于平台最新版 = 本地已记录但**尚未上线**：本项目正常状态，只提示
    out["unreleased_local"] = [v for v in unreleased if _pk(v) >= latest_p]

    drift = bool(out["missing_log"])
    out["verdict"] = "drift" if drift else "ok"

    # 「双主」告警必须比**同语义**的两个量：本机**已安装 / 上次发布**的版本 ↔ 线上最新版。
    # 🔴 此前这里用的是 `local_version`；在修正前的实现里它取自 `_meta.json`（= 安装版本），
    # 凑巧同义，掩盖了字段错配。字段语义分离后若仍比 `local_version`，会把这个告警变成
    # 「**源码领先 = 误报双主**」——所以这里必须换成 `installed_version`。
    ivp, plp = _parse_ver(out["installed_version"]), _parse_ver(out["platform_latest"])
    if ivp and plp:
        if ivp < plp:
            out["verdict"] = "drift"
            out["hints"].append(
                "⚠️ 本机安装副本（%s）落后于线上（%s）——多机并行时这正是**「双主」的前兆**："
                "先把线上包取回做基准，再动任何代码。"
                % (out["installed_version"], out["platform_latest"]))
        elif ivp > plp:
            out["hints"].append(
                "本机安装版本（%s）高于线上（%s）：改动尚未上线。若本次不打算发布，属正常，忽略即可。"
                % (out["installed_version"], out["platform_latest"]))
    # 源码版本 ↔ 安装版本：**仅信息项**。开发机上源码领先是常态（本仓约定「未经用户明确
    # 要求不主动发布」），绝不可据此判 drift，也不可据此提示「取回线上包」。
    lvp = _parse_ver(out["local_version"])
    if lvp and ivp and lvp != ivp:
        out["hints"].append(
            "本地源码版本（%s）与本机安装版本（%s）不同：源码领先 = 有未发布改动，属本仓常态。"
            % (out["local_version"], out["installed_version"]))
    if out["missing_log"]:
        out["hints"].append(
            "（窗口 ≥%s）平台已发布但日志无记录：%s —— 有人绕过日志发布；补条目，或确认这是预期。"
            % (out["window_since"], ", ".join(out["missing_log"])))
    if out["bundled"]:
        out["hints"].append(
            "日志有、平台无、且平台已越过它（改动应已随更晚版本发出，仅提示）：%s"
            % ", ".join(out["bundled"]))
    if out["unreleased_local"]:
        out["hints"].append(
            "本地已记录但未上线：%s —— 本项目默认不主动发布更新，属正常状态；"
            "要发版时按发布流程走即可。" % ", ".join(out["unreleased_local"]))
    if out["legacy_missing"]:
        out["hints"].append(
            "窗口外的历史账缺口 %d 个（早于 %s，归档区未逐版记录）——信息项，不影响结论。"
            % (len(out["legacy_missing"]), out["window_since"]))
    if not (lvp and plp) and not out["error"]:
        out["hints"].append("本地版本或平台最新版本解析不出，跳过「落后/超前」判断。")
    out["ok"] = (out["verdict"] == "ok")
    return out

