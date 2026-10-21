# Auto-extracted submodule: _decay
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def compute_thermal(mem, now=None, domain=None, access_n=None):
    """按热度 + 最近访问判层：hot/warm/cold（Phase 2 配额落地前仅作标注）。

    v3.1.4 P1-3：新记忆 7 天新手保护期——创建未满 7 天的不判 cold，给积累热度的机会。
    v3.2.1 B1 域感知：若给定 domain 且与记忆匹配（domain 字段或 tags 含该域），
    热窗口放宽到 90d、热阈值降到 0.6，投资/工作记忆互不污染热位。不传 domain 行为不变。
    B2 衰减有效热度：热记忆若有效重要性 = importance × 2.7^(-0.03×age) < 0.15 则降 warm。
    5.0/A1：`access_n` 传单一热源的真实召回次数；不传则回退 `mem["access_count"]`（真库恒 0）。"""
    if now is None:
        now = datetime.date.today()
    last = _parse_date(mem.get("accessed", ""))
    ac = int(mem.get("access_count", 0) or 0) if access_n is None else int(access_n or 0)
    days_since = (now - last).days if last else 10 ** 9
    # P1-3：新手保护期——创建未满 7 天的不判 cold
    created = _parse_date(mem.get("created", ""))
    newbie = created and (now - created).days < THERMAL_NEWBIE_PROTECTION_DAYS
    # B1 域感知：domain 匹配则放宽热窗口/阈值，且 cold 守卫需 not domain_match
    domain_match = bool(domain) and (
        mem.get("domain") == domain or domain in (mem.get("tags") or []))
    hot_window = 90 if domain_match else 30
    hot_thr = 0.6 if domain_match else 1.0
    if newbie:
        if days_since > COLD_THRESHOLD_DAYS and ac <= 1 and not domain_match:
            return "warm"  # 新记忆保护：本应 cold → 降级为 warm
    else:
        if days_since > COLD_THRESHOLD_DAYS and ac <= 1 and not domain_match:
            return "cold"
    if heat_recent(mem, now, ac) >= hot_thr and days_since <= hot_window:
        # B2：有效重要性 = importance × 2.7^(-0.03×age)，极低则热记忆降级
        age = days_since if days_since < 10 ** 8 else 365
        eff_imp = float(mem.get("importance", 0.5) or 0.5) * (2.7 ** (-0.03 * age))
        if eff_imp < 0.15:
            return "warm"
        return "hot"
    return "warm"

def _days_since_accessed(mem, now=None):
    """返回记忆自上次访问的天数（无日期则视为 365）。"""
    if now is None:
        now = datetime.date.today()
    last = _parse_date(mem.get("accessed", ""))
    if not last:
        return 365
    d = (now - last).days
    return d if d >= 0 else 0

def _pattern_key(category, summary):
    """D3：模式指纹 = 同类别 + 归一化摘要的哈希；用于相似 deposit 的确定性 recurrence 计数。"""
    import hashlib as _hl
    norm = re.sub(r"\s+", " ", ("%s|%s" % (summary or "", category or ""))).strip().lower()
    return "pk:" + _hl.md5(norm.encode("utf-8")).hexdigest()[:16]

def decay_apply(root, lambda_=0.03, dry_run=False, context_budget=None, incremental=False):
    """D2：确定性重算每条 active 记忆的 relevance_score（反超竞品 LLM 心算）。

    公式（由 SQLite/JSON 真算，非 LLM 估计）：
    relevance = importance · e^(-λ·Δdays) · (1 + √access_count) · type_weight
    并据 relevance 重算 thermal（热位重排），让长期未用/低频经验自然降级，
    过时经验不挤占投资回测期的召回。返回更新条数。

    incremental=True（4.5.48，大库提速，默认 OFF）：仅重算「自上次 decay 以来被访问
    （accessed）或改动（文件 mtime）过的记忆」。未触碰记忆保持上次 relevance——因所有
    记忆同步老化（Δdays 同增、access_count 不变），其相对排序不变，仅影响跨「被访问组」
    与「未访问组」的绝对次序，正确性无损。store meta 记录 last_decay_at 供增量判定。
    默认（incremental=False）仍全量重算，零风险路径不变。
    """
    mems = _all_mems(root)
    now = datetime.date.today()
    # 5.0/A1：召回频次以热源 recall_counts.json 为唯一权威（记忆内 access_count 恒 0 且脱节）。
    # 一次性加载供全库遍历复用（逐条开文件会显著拖慢大库 decay）。
    _acounts = _load_recall_counts(root)
    meta = _load_meta(root)
    last_decay = meta.get("last_decay_at")
    _threshold_dt = None
    if incremental and last_decay:
        try:
            _threshold_dt = datetime.date.fromisoformat(str(last_decay))
        except Exception:
            _threshold_dt = None
    n = 0
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        if context_budget and n >= context_budget:
            break
            # 增量化：仅重算「自上次 decay 以来被真正使用过（recall/touch/feedback 设置了
            # accessed）」的记忆。注意不用 mtime 判定——decay 自身会重写全部文件，mtime 会
            # 把上一次全量 decay 写过的记忆误判为「已改动」。accessed 由召回/触摸显式设置，
            # decay 从不改写它，故是可靠的「自上次 decay 以来是否被动过」信号。未触碰的冷记忆
            # 保持上次 relevance（所有记忆同步老化，相对排序不变）。
        if _threshold_dt is not None:
            touched = False
            acc = m.get("accessed")
            if acc:
                try:
                    if datetime.date.fromisoformat(str(acc)) >= _threshold_dt:
                        touched = True
                except Exception:
                    pass
            if not touched:
                continue
        days = _days_since_accessed(m, now)
        # 5.0/A1：改用单一热源。原来读 m["access_count"]（真库 204/211 条恒 0）→
        # (1+√ac) 恒等于 1，衰减权重完全失效。改读热源后该因子才真正生效。
        ac = _access_count_of(root, mid, m, _acounts)
        base = float(m.get("importance", 0.5) or 0.5)
        tw = _TYPE_WEIGHT.get(m.get("type"), 1.0)
        rel = base * (2.7 ** (-lambda_ * days)) * (1.0 + (ac ** 0.5)) * tw
        m["relevance_score"] = round(rel, 4)
        try:
            m["thermal"] = compute_thermal(m, now, access_n=ac)
        except Exception:
            pass
        if not dry_run:
            try:
                _save_mem(root, mid, m)
            except Exception as e:
                # S3 修复：不再静默吞——衰减后写盘失败会导致分数未落盘却回报 ok，
                # 用户无法察觉。记 stderr 让调用方知道哪条记忆写失败（仍不抛出，避免阻塞）。
                import sys as _sys
                _sys.stderr.write("[⚠ decay] 保存 %s 失败: %s（衰减分数未落盘）\n" % (mid, e))
        n += 1
    if not dry_run:
        meta["last_decay_at"] = now.isoformat()
        try:
            _save_meta(root, meta)
        except Exception as e:
            import sys as _sys
            _sys.stderr.write("[⚠ decay] 保存 meta.json 失败: %s（last_decay_at 未更新）\n" % (e,))
    return {"ok": True, "updated": n, "dry_run": dry_run,
            "incremental": bool(_threshold_dt is not None)}

def recurrence_report(root, min_count=3, auto_candidate=False, window_days=30):
    """D3：按 pattern_key 分组，返回 recurrence_count≥min_count 的模式簇（确定性，非 LLM grep）。
    供 promote --review 用「≥3 次重复」作为代码强制的晋升信号。
    v4.1.0（P4/B1）：auto_candidate=True 时，额外判定「跨≥2 任务(project 不同) 且
    最近一次重复落在 window_days 内」→ 标 promotion_candidate=True（纯加性布尔字段，
    不碰 status）。满足候选条件的组返回时带 projects（去重任务数）与 span_days。"""
    mems = _all_mems(root)
    groups = {}
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        pk = m.get("pattern_key")
        if not pk:
            continue
        g = groups.setdefault(pk, {"count": 0, "mids": [], "category": m.get("category"),
                                   "summary": (m.get("summary") or "")[:48],
                                   "projects": set(), "created_set": set()})
        g["count"] += 1
        g["mids"].append(mid)
        if m.get("project"):
            g["projects"].add(m["project"])
        elif m.get("scope") == "project":
            g["projects"].add("<project-scope>")
        if m.get("first_seen"):
            g["created_set"].add(m["first_seen"])
    out = []
    for g in groups.values():
        if g["count"] < min_count:
            continue
        g2 = {"count": g["count"], "mids": g["mids"], "category": g["category"],
              "summary": g["summary"], "promotion_candidate": False}
        if auto_candidate:
            n_proj = len(g["projects"])
            # 时间窗：最近一次访问/创建距今天数（用 first_seen 最早 + 当前判断跨度）
            span = 0
            if g["created_set"]:
                try:
                    ds = sorted(_parse_date(d) for d in g["created_set"] if d)
                    span = (datetime.date.today() - ds[0]).days
                except Exception:
                    span = 0
            if n_proj >= 2 and span <= window_days:
                g2["promotion_candidate"] = True
            g2["projects"] = sorted(g["projects"])
            g2["span_days"] = span
        out.append(g2)
    out.sort(key=lambda x: (x["promotion_candidate"], x["count"]), reverse=True)
    return {"ok": True, "groups": out}

def _lazy_importance_decay(root):
    """ 改进 P0-2：recall 入口懒检查 importance 衰减。

    原问题：importance 衰减仅在 reflect_v30 内触发，若用户长期不跑 reflect，
    冷记忆 importance 永远停在历史峰值，持续占用热配额、挤压新记忆。

    做法：recall_v30 入口每 DECAY_LAZY_CHECK_INTERVAL_DAYS 天懒触发一次轻量衰减——
    只做 importance 回归先验（与 reflect_v30 §2.0 完全相同的逻辑），不跑去重/重分类/
    demote/resurrect 等重操作。安全闸同 reflect：importance≥0.9 不衰减、不低于先验、
    近期访问跳过。任何异常静默吞掉（绝不阻塞 recall 主路径）。

    返回 dict：{triggered: bool, decayed: int, skipped: int} 供调试/日志。
    """
    result = {"triggered": False, "decayed": 0, "skipped": 0}
    try:
        from datetime import date
        today_d = date.today()
        _acounts = _load_recall_counts(root)  # 5.0.x：陈旧判定按「天数 AND 次数」双因子

        # 读 config.json 覆盖
        interval = DECAY_LAZY_CHECK_INTERVAL_DAYS
        stale_days = DECAY_LAZY_STALE_DAYS
        try:
            p = os.path.join(root, "config.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
                dc = c.get("decay", {})
                if isinstance(dc, dict):
                    if "lazy_check_days" in dc:
                        interval = int(dc["lazy_check_days"])
                    if "stale_days" in dc:
                        stale_days = int(dc["stale_days"])
        except Exception:
            pass

            # 检查上次懒衰减时间
        meta = _load_meta(root)
        last_check = meta.get("last_decay_check")
        if last_check:
            last_d = _parse_iso_date(last_check)
            if last_d and (today_d - last_d).days < interval:
                return result  # 间隔未到，跳过

                # 间隔已到 → 执行轻量衰减
        result["triggered"] = True
        data = load_index(root)
        for e in data.get("entries", []):
            if not isinstance(e, dict) or e.get("status") != "active":
                continue
            mid = e.get("id")
            if not mid:
                continue
            try:
                m, _ = _load_mem(root, mid)
            except Exception:
                result["skipped"] += 1
                continue

            imp = float(m.get("importance", 0.5) or 0.5)
            if imp >= 0.9:
                result["skipped"] += 1
                continue  # 用户显式重要，安全闸
            prior = _default_importance(m.get("category", ""), m.get("scope", "universal"))
            if imp <= prior + 1e-6:
                result["skipped"] += 1
                continue  # 已在先验或更低
            last_access = m.get("accessed") or m.get("updated") or m.get("created")
            if _days_since(last_access, today_d) < stale_days:
                result["skipped"] += 1
                continue  # 近期还用过，保留
            # 5.0.x：即使超 stale_days，若被反复验证（访问次数 ≥ DECAY_HIGH_USAGE_FLOOR）也豁免——
            # 避免「长时间不开机 → 自然日累积 → 把仍反复验证有用的记忆冤枉老化」。
            # 只有「既超天数、又低频使用」才判陈旧降权（天数 AND 次数，非纯天数）。
            if _access_count_of(root, mid, m, _acounts) >= DECAY_HIGH_USAGE_FLOOR:
                result["skipped"] += 1
                continue

            new_imp = max(prior, round(imp * IMPORTANCE_DECAY, 4))
            if new_imp != imp:
                m["importance"] = new_imp
                m.setdefault("accessed_from", []).append({
                    "action": "v30_lazy_importance_decay", "by": "recall_v30_lazy",
                    "old_imp": imp, "new_imp": new_imp,
                    "reason": "lazy_decay_long_unused", "date": today_d.isoformat()})
                if len(m["accessed_from"]) > 12:
                    del m["accessed_from"][:len(m["accessed_from"]) - 12]
                _save_mem(root, mid, m)
                result["decayed"] += 1
            else:
                result["skipped"] += 1

                # 更新 meta.json 的 last_decay_check
        meta["last_decay_check"] = today_d.isoformat()
        _save_meta(root, meta)
    except Exception:
        pass  # 衰减失败绝不阻塞 recall
    return result

def settle_probe(root, daily_n=None, llm=None, as_of=None):
    """ Phase 2 settle_probe（设计基线 §5.2）：主动探针打破冷启动死循环。
    抽样未沉淀记忆（按 importance 加权 top-N），主动验证 → 通过则 SETTLED。
    - llm: False/None/True/callable（默认 None→配置启用才用）。
    - 无 LLM / 解析失败 → 规则兜底：被访问过 或 importance≥floor 即信任沉淀，否则继续观察。
    返回报告 dict。"""
    if daily_n is None:
        daily_n = PHASE2_SETTLE_PROBE_DAILY_N
    chat, _ = _resolve_llm(root, llm)
    asof = as_of or today()
    mems = _all_mems(root)
    _acounts = _load_recall_counts(root)  # 5.0/A1：沉淀门槛改读热源（原读记忆内字段，恒 0）
    pending = [m for mid, m in mems.items()
               if isinstance(m, dict) and m.get("status") == "active" and not m.get("settled")]
    pending.sort(key=lambda m: float(m.get("importance") if isinstance(m.get("importance"), (int, float)) else 0.5),
                 reverse=True)
    sample = pending[:daily_n]
    settled_now, skipped, details = [], [], []
    for m in sample:
        mid = m.get("id")
        verdict, reason = None, ""
        if chat is not None:
            try:
                system = ("你是记忆质检助手。判断一条长期记忆当前是否仍然【正确/可复用】。"
                          "只输出 JSON 对象：{\"verdict\":\"settled|correct|merge|supersede\","
                          "\"reason\":\"<简短>\"}. settled/correct=可沉淀; merge=应合并; supersede=已过时淘汰。")
                user = "记忆：type=%s\nsummary：%s\nbody：%s" % (
                    m.get("type", ""), m.get("summary", ""), (m.get("body", "") or "")[:800])
                out = chat(system, user, temperature=0.0, max_tokens=200)
                obj = _parse_llm_json_obj(out)
                verdict = obj.get("verdict", "")
                reason = obj.get("reason", "")
            except Exception:
                verdict = None
        imp = float(m.get("importance") if isinstance(m.get("importance"), (int, float)) else 0.5)
        if verdict in ("settled", "correct"):
            m["settled"] = True
            m["probe_until"] = None
            settled_now.append(mid)
        elif verdict in ("merge", "supersede"):
            reason = (reason + " [待 reflect 处理]").strip()
            skipped.append(mid)
        else:
            # H4 修复：规则兜底沉淀门槛从「或」改为「且」——必须真正复用（访问≥2）
            # 且重要性达标（≥SETTLE_AUTO_FLOOR），否则继续观察。原「访问1次 或 高
            # importance」形同虚设（默认 importance 0.6、recall 一次即访问+1，噪音照单全收）。
            # 5.0/A1：访问次数改读单一热源 recall_counts.json——原来读 m["access_count"]
            # 而该字段在真库 204/211 条恒 0 → 本分支**从未触发过**（沉淀链整条失效）。
            if (_access_count_of(root, mid, m, _acounts) >= 2) and (imp >= SETTLE_AUTO_FLOOR):
                m["settled"] = True
                m["probe_until"] = None
                settled_now.append(mid)
                reason = reason or "rule fallback: accessed or importance>=floor"
            else:
                skipped.append(mid)
                reason = reason or "rule fallback: 仍观察（未访问且 importance<floor）"
        af = m.setdefault("accessed_from", [])
        af.append({"action": "settle_probe", "date": asof, "verdict": verdict or "rule", "reason": reason})
        if len(af) > 12:
            del af[:len(af) - 12]
        try:
            _save_mem(root, mid, m)
        except Exception as e:
            # P2 修复：不再静默吞——沉淀状态写盘失败会导致下次重复探针，
            # 用户无法察觉。记 stderr 让调用方知道哪条记忆写失败了。
            import sys as _sys
            _sys.stderr.write("[⚠ settle_probe] 保存 %s 失败: %s（沉淀状态未落盘）\n" % (mid, e))
        details.append({"id": mid, "verdict": verdict or "rule",
                        "settled": mid in settled_now, "reason": reason})
    return {"ok": True, "probed": len(sample), "pending_total": len(pending),
            "settled_now": len(settled_now), "skipped": len(skipped),
            "llm_used": chat is not None, "details": details}

