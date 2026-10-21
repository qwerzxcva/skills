# F18 阶段2 批8：_deposit 写路径簇（函数级精确搬移，零行为变化）
# deposit / _deposit_impl / _auto_link_similar / flush_memory_index
# 从 memory_ops/__init__.py 机械搬移，仅搬这 4 个顶层 def（含装饰器）。
# _with_deposit_lock 等共享装饰器/全局留在 __init__，本模块通过全局灌入式注入解析。

import sys  # 模块级导入，避免函数内 `import sys` 把 sys 变成局部变量导致 UnboundLocalError
import os   # §5.5：读 KEEPER_DOMAIN_FALLBACK 开关（模块级，不依赖注入的全局 os）

@_with_deposit_lock
def _deposit_impl(root, category, summary, tags, body, mid=None, tier="working",
            confidence=None, inferred=False, importance=None, corrects=None,
            scope=None, project="", auto_link=True, defer_index=False,
            recorded_by="agent", auto_sourced=False, sensitive_action="raise",
            type_confidence=None, secondary_types=None, domain=None, subdomain=None,
            scene=None, attrs=None, state=None, priority=None, area=None,
            about_axis=None, mem_type=None,
            provenance="agent", provenance_key=None, src_origin=None,
            skip_dedup=False, derives_from=None):
    global _BATCH_ROOT, _BATCH_DATA, _PENDING_REVERSE
    # ：单条 deposit 且三者均未显式指定时，触发词典自动预填 area/priority（hint，不碰 state）
    # （P2）：触发词典升级为「重要性打分 + 四轴预填」，返回 5 元组；
    # 显式 --importance 优先 → hint → default 0.5；显式 --about-axis 优先 → hint → None
    # 批量模式（defer_index）跳过：避免 O(n) 正则 + 批量导入通常已带显式分类
    if not defer_index and state is None and priority is None and area is None \
            and about_axis is None and importance is None:
        try:
            _ta, _tp, _ti, _taxis, _tr = trigger_dict.infer_trigger_hints(
                " ".join([summary or "", body or ""]))
            if area is None and _ta:
                area = _ta
            if priority is None and _tp:
                priority = _tp
            if importance is None and _ti is not None:
                importance = _ti
            if about_axis is None and _taxis:
                about_axis = _taxis
        except Exception:
            pass
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,\s]+", tags) if t]
        # I3（沙箱报告改进）：标签长度上限 128 字符——超长截断，避免索引膨胀。
        # 去重保序，空标签过滤。
    _seen_t = set()
    tags = [t[:128] for t in (tags or []) if t and (t[:128] not in _seen_t and not _seen_t.add(t[:128]))]
    # D-new-4 修复：summary 去空后为空（含纯空格）直接拒绝，避免建出 "" / " " 这类
    # 垃圾空记忆——它们会污染库、占热配额、还出现在 recall 结果里。converse/harvest 的
    # verbatim 兜底已有 len>=12 门槛，不会触发此拦截。
    if not (summary or "").strip():
        raise ValueError("summary 不能为空（至少含一个非空白字符）")
    if tier not in TIERS:
        raise ValueError("层级(tier)只能是这几个之一：%s；你填的是「%s」。常见值：core（核心原则）/ curated（精选）/ active（活跃）/ archived（已归档）。" % ("、".join(TIERS), tier))
        # §7 · 自动汲取敏感扫描（守 SOUL "绝不记 secrets" 红线）
        # 一票否决：命中任一敏感模式直接抛 SensitiveError，不写盘、不写索引。
    _combo_text = " ".join([str(summary or ""), str(body or "")])
    _clean_text, _sec_hits = _scan_sensitive(_combo_text)
    if _sec_hits:
        # P2 · 敏感 quarantine（修 H3）：命中敏感不再静默丢弃，改为隔离待审、可逆。
        # 默认 sensitive_action="raise" 保持旧行为（抛 SensitiveError，完全向后兼容）；
        # 调用方显式 sensitive_action="quarantine" 时，候选暂存 quarantine/ 待人工复审/放行。
        if QUARANTINE_ENABLED and sensitive_action == "quarantine":
            qid = _quarantine_candidate(root, category, summary, tags, body,
                                        _sec_hits, scope=scope, project=project,
                                        tier=tier, importance=importance)
            return {"ok": False, "quarantined": True, "qid": qid,
                    "hits": _sec_hits, "reason": "sensitive"}
        raise SensitiveError(
            "敏感信息命中（v3.0 §7 拒绝写入）: %s" % _sec_hits)
    model = _clf.load_model(root)
    custom_rules = _clf.load_rules(root)  # #2：加载用户自定义分类规则
    explicit = scope is not None
    if scope is None:
        scope, conf, reasons = _clf.classify(model, category, tags, body, summary, custom_rules=custom_rules)
    elif scope not in SCOPES:
        raise ValueError("范围(scope)只能是这几个之一：%s；你填的是「%s」。说明：universal（通用，跨项目共享）/ project（限某项目）/ ephemeral（临时，易过期）。" % ("、".join(SCOPES), scope))
    else:
        # 显式给定：强学习 + 高置信
        conf, reasons = 1.0, ["explicit"]
        _clf.learn_deposit(model, category, tags, body, summary, scope, explicit=True)
        # #19 修复：deposit 时也累积 type 先验（标签→type 映射）
        # ：type 默认由 category 推导；显式 --type 优先（让用户自己指定分类）。
        # 显式且合法 → 采用并置高置信；否则回退 category 推导。
    if mem_type:
        _nt = _normalize_type(mem_type)
        if _nt in TYPE_CANON:
            _mem_type = _nt
            type_confidence = 1.0  # 显式指定 → 高置信
        else:
            _mem_type = _normalize_type(category or "")
    else:
        _mem_type = _normalize_type(category or "")
    if _mem_type in TYPE_CANON:
        _clf.learn_type_deposit(model, tags, _mem_type, explicit=(explicit or bool(mem_type)))
        # ：记录 type 是否显式指定 + 其置信，供下方 classify_review 把 type 轴纳入保护
    type_explicit = bool(mem_type)
    type_conf = type_confidence if type_confidence is not None else _default_type_conf(category or "")
    # 批量模式（方案 A）：复用内存 index，避免每条 deposit 都 load_index（整库读）+ save_index（整库写）
    if defer_index and _BATCH_DATA is not None and _BATCH_ROOT == os.path.abspath(root):
        data = _BATCH_DATA
    else:
        data = load_index(root)
        if defer_index:
            _BATCH_ROOT = os.path.abspath(root)
            _BATCH_DATA = data
            _PENDING_REVERSE.clear()
            # §7 · 自动汲取写前查重（修 H1/H2：接 _capture_dedup，此前是死代码零调用）。
            # 仅自动捕获路径生效（显式给定 mid 视为人工覆盖、批量导入 defer_index 跳过以避免
            # O(n²) 语义比对拖垮吞吐）。advisory：失败不阻断 deposit 主流程。
            # ：派生记忆（derives_from 声明）是刻意的独立高层节点，不参与「近重复查重
            # 吞并」——否则 evolve 合成的原则会被它派生的源记忆当低质重复吞掉。这是取代
            # skip_dedup hack 的正确机制：以「派生意图」为信号而非无脑跳过查重。
    if mid is None and _CAPTURE_DEDUP_ON and not defer_index and not skip_dedup and not derives_from:
        try:
            _dd = _capture_dedup(root, summary, body, tags, include_archived=True)
            # H2：归档库已有近重复 → 复活复用，不再造新重复（永久重复漏洞）
            _sup_thr, _res_thr = _dedup_thresholds()
            _arch = [x for x in _dd["matches"]
                     if x.get("status") == "archived" and x["score"] >= _res_thr]
            if _arch:
                _rid = _arch[0]["mid"]
                _old, _ofp = _load_mem(root, _rid)
                _old["status"] = "active"
                _old["accessed"] = today()
                _old.pop("superseded_by", None)
                _old.setdefault("accessed_from", []).append(
                    {"action": "resurrect_dedup", "date": today(),
                     "reason": "archive 强匹配(%.3f)复活复用，避免重复" % _arch[0]["score"]})
                if len(_old["accessed_from"]) > 12:
                    del _old["accessed_from"][:len(_old["accessed_from"]) - 12]
                _save_mem(root, _rid, _old)
                for e in data.get("entries", []):
                    if e.get("id") == _rid:
                        e["status"] = "active"
                if not defer_index:
                    save_index(root, data)
                return _rid
                # H1：active 近重复 → 质量感知 supersede（修复「低置信重复覆盖高置信记忆」缺陷）。
                # 旧行为：无条件"后来者胜"——新记忆（即便 auto_sourced/inferred 低置信）会把
                # 高置信 explicit 旧记忆标 superseded 挤出活跃库。
                # 新行为：比较质量（来源显式度 > confidence > importance），仅当新记忆质量
                # 严格更高时才 supersede 旧记忆；否则保留旧为 canonical、丢弃新重复（不创建低质副本）。
            _act = [x for x in _dd["matches"]
                    if x.get("status") == "active" and x["score"] >= _sup_thr]
            if _act and not corrects:
                _old_mid = _act[0]["mid"]
                _om = None
                try:
                    _om, _ = _load_mem(root, _old_mid)
                except Exception:
                    _om = None
                if _om is not None and not _new_outranks_old(
                        _om, confidence, importance, inferred, auto_sourced,
                        recorded_by, category, scope,
                        new_tier=tier, old_tier=_om.get("tier")):
                    # 新记忆质量不高于旧记忆：保留旧 canonical，吸收新重复（不落盘低质副本）。
                    try:
                        _om.setdefault("accessed_from", [])
                        # 5.0/A1 续修：这条「近重复被吸收」也算旧 canonical 被使用一次，
                        # 但频次写**权威热源**（recall_counts.json），不再自增记忆文件字段
                        # —— 写文件字段正是「双写脱节」病根的一部分。
                        _bump_recall_counts(root, [_old_mid])
                        _om["accessed"] = today()
                        _om["last_seen"] = today()
                        _om["accessed_from"].append({
                            "action": "dedup_keep_old", "date": today(),
                            "reason": "near-dup(%.3f) 新记忆质量不高于既有 canonical，丢弃重复"
                                      % _act[0]["score"]})
                        if len(_om["accessed_from"]) > 12:
                            del _om["accessed_from"][:len(_om["accessed_from"]) - 12]
                        _save_mem(root, _old_mid, _om)
                        for e in data.get("entries", []):
                            if e.get("id") == _old_mid:
                                e["accessed"] = _om["accessed"]
                                # 索引侧同读单一热源（不再是文件字段的恒 0 值）
                                e["access_count"] = _access_count_of(root, _old_mid, _om)
                        save_index(root, data)
                    except Exception as _err:
                        import sys as _sys
                        _sys.stderr.write("[⚠ deposit] 索引同步失败（记忆文件已写、索引可能滞后；doctor --fix 可修复）：%s\n" % _err)
                        from _self_heal import mark_dirty_safe
                        mark_dirty_safe(root, _old_mid)
                    return _old_mid
                corrects = _old_mid
        except Exception:
            pass
            # 标签倒排缓存（进程内增量维护）：首次全量构建一次，之后每次 deposit O(1) upsert，
            # 彻底消除旧版「每次 _auto_link_similar 都 load_index + 全量重建 by_tag」的 O(n²) 瓶颈。
            # 注意：by_tag/by_id 仅供下方 _auto_link_similar 使用，故延迟到 auto_link 分支内再取，
            # 批量模式（defer_index）已跳过逐条连边，避免此处无谓的 O(n) 重建。
    if not mid:
        mid = gen_id(root, data, scan_dir=not defer_index)
        # 批量模式（defer_index=True）id 由 gen_id 增量游标保证全局唯一且大小写安全，
        # 跳过 _case_clash / _resolve_path 的全目录 listdir（O(目录大小)），否则每 deposit
        # 扫一遍万级目录 → 累积 O(n²)（实测 1万条 371s 的根因之一）。
    if not defer_index:
        clash = _case_clash(mem_dir(root), mid)
        if clash:
            raise ConflictError(
                "大小写冲突：%s 与已存在的 %s 在 Windows 下视为同名，拒绝静默覆盖" % (mid, clash))
            # 重复 id 守卫：显式传入已存在的 id 时拒绝（否则会静默覆盖文件 + 在 index 追加重复条目）
        if _resolve_path(root, mid):
            raise ConflictError("id 已存在，拒绝重复创建: %s" % mid)
            # confidence 语义化（explicit=1.0 / inferred=0.5）+ importance 默认推断
    if confidence is None or confidence == 0.0:
        confidence = 0.5 if inferred else 1.0
    conf_basis = "inferred" if inferred else "explicit"
    # Beta 校准字段：创建即按 confidence 反推初始化，K 随 type 差异化（#15）
    _beta_prior = _TYPE_BETA_PRIOR.get(_mem_type, (6.0, 0.7))
    _K = _beta_prior[0]
    conf_alpha = round(confidence * _K, 4)
    conf_beta = round((1.0 - confidence) * _K, 4)
    if importance is None:
        importance = _default_importance(category, scope)
        # I2（沙箱报告改进）：importance 值域校验硬化——clamp 到 [0.0, 1.0]，
        # 避免异常值（999 / -0.5 / NaN）进入排序影响召回质量。非数值/异常回退先验。
    try:
        importance = max(0.0, min(1.0, float(importance)))
    except (TypeError, ValueError):
        importance = _default_importance(category, scope)
        # P3：自动路由（advisory）—— domain 未显式传入时，先按用户 taxonomy 关键词归类到
        # 专属域/子域；未命中保留 None，回退 _infer_domain（绝不破坏 work/investment 等通用分类）。
        # 命中自定义子域时同步写 `sub:` 标签，使 recall --tag sub: 立即可用。
    if domain is None:
        _tax_text = " ".join([
            (summary or ""), (category or ""),
            " ".join(tags or []), (body or "")[:400]])
        _td, _ts = taxonomy_route(_tax_text, load_taxonomy(root))
        if _td is not None:
            domain = _td
            if _ts is not None:
                subdomain = _ts
    if domain is None:
        domain = _infer_domain(tags)
    # ── §5.5：域判定落空的「兜底域」——**显式开关、默认关**（行为与旧版逐字一致）──────
    # 为什么默认不落域：`domain=None` 是**有意设计**，不是缺陷——见 `_doctor.py` 明文
    # 「fallback_domain 是兜底筐，未匹配记忆存为 domain=None，其覆盖由『域分布』的 none 桶
    # 体现」，且 `reclassify_by_taxonomy` 明文拒绝「强行推到 fallback」。故仅在用户**显式**
    # 开启时才落域：`KEEPER_DOMAIN_FALLBACK=<域>`（如 general）。落域时同步打
    # `domain:fallback` 标签，以区别于用户**显式**指定的同名域，并让 `reclassify --pending`
    # 仍能捞出待人工归类（不因落域而从数据质量队列静默消失）。
    if domain is None:
        _fb = (os.environ.get("KEEPER_DOMAIN_FALLBACK") or "").strip()
        if _fb and _fb.lower() not in ("off", "none", "0", "false"):
            domain = _fb
            tags = list(tags or [])
            if "domain:fallback" not in tags:
                tags.append("domain:fallback")
        # 子域标签同步（无论自动路由命中还是显式传入）
    if subdomain is not None:
        _sub_tag = "sub:%s" % subdomain
        if _sub_tag not in tags:
            tags = list(tags) + [_sub_tag]
            # 多轴 taxonomy scene 轴：显式给定则校验；否则在线 LLM > 关键词初判。
            # 与 topic 轴（domain+subdomain）正交，纯加性。自动分类结果带 scene_confidence，
            # 便于 recall/report 标注「哪些是猜的」+ 周六维护扫描低置信复核（问题①A/B 档）。
    scene_explicit = scene is not None
    if scene is not None:
        scene = _normalize_scene(scene)
        if scene not in SCENE_CANON:
            raise ValueError("场景(scene)不认识「%s」。可选场景（或其别名）有：%s。留空让系统自动判断即可，无需手填。" % (scene, "、".join(sorted(SCENE_CANON))))
    if scene is None:
        _scene_text = " ".join([
            str(summary or ""), " ".join(str(t) for t in (tags or []) if t)])
        scene, scene_conf, scene_via, _sreasons = classify_scene_v30(root, _scene_text, tags)
    else:
        scene_conf, scene_via = 1.0, "explicit"
        # + ：重要记忆自动分类低置信保护（对应「重要事情最好自己指定分类」）。
        # 覆盖 scope / scene / type 三轴自动低置信（任一）→ 标 classify_review=True 并告警。
        # 阈值 importance≥0.7（原 0.8，覆盖「我偏好…」这类 0.7 重要记忆）；绝不阻断写入。
    classify_review = bool(
        importance is not None and importance >= 0.7
        and (
            (not explicit and conf < 0.7)
            or (not scene_explicit and scene_conf < 0.7)
            or (not type_explicit and type_conf < 0.7)
        )
    )
    if classify_review:
        sys.stderr.write(
            "⚠️ [classify_review] 高重要度记忆经自动分类且置信偏低"
            "（scope_via=%s conf=%.2f / scene_via=%s conf=%.2f / type_explicit=%s conf=%.2f），"
            "建议显式指定 --scope/--scene/--type/--domain 以固化分类，避免重要经验被错分。\n"
            % (("explicit" if explicit else "auto"), float(conf), scene_via, float(scene_conf),
               type_explicit, float(type_conf)))
    mem = {
        "id": mid,
        "category": category or "",
        "created": today(),
        "accessed": today(),
        "summary": summary or "",
        "tags": tags or [],
        "body": body or "",
        "brand_mentions": _emb.extract_brands(" ".join([summary or "", body or ""])),
        "version": 1,
        "schema_version": 1,  # v2.10.0 起：记忆体 schema 版本，未来字段演进可做迁移而不破坏旧库
        # 5.0/A3 双时序起点：生效时点。与 `invalid_at`（失效时点，由 invalidate 置位）
        # 成对，支持 `recall --as-of <date>` 回溯「当时这条是否有效」。
        "valid_at": today(),
        "access_count": 0,
        "tier": tier,
        "confidence": confidence,
        "conf_alpha": conf_alpha,
        "conf_beta": conf_beta,
        "confidence_basis": conf_basis,
        "importance": importance,
        "scope": scope,
        "scope_confidence": conf,
        "classify_reasons": reasons,
        "accessed_from": [],
        "project": project or "",
        "recorded_by": recorded_by,
        "auto_sourced": bool(auto_sourced),
        "status": "active",
        "relations": {},
    # 数据模型（Phase 1）：type 规范类型 + 沉淀门控 + 冷热分层字段
        "type": _mem_type,  # v4.4.17：默认由 category 推导，显式 --type 优先（让用户自己指定分类）
        "settled": False,                         # 待沉淀（观察期后由 settle_probe 置 True）
        "probe_until": (datetime.date.today()
                        + datetime.timedelta(days=PROBE_PERIOD_DAYS)).isoformat(),
        "thermal": "warm",                       # 新记忆从 warm 起步，不抢热位
    # A1/A2/B1 分类置信度 + 次类型 + 域感知
        "type_confidence": (type_confidence if type_confidence is not None
                            else _default_type_conf(category)),
        "secondary_types": secondary_types or [],
        "domain": domain,
        "subdomain": subdomain,
        "scene": scene,  # v3.7.0 多轴 taxonomy 第二轴（与 topic 正交）
    # ：场景分类置信度与来源（llm/rule/explicit）——自动分类非权威，供复核
        "scene_confidence": scene_conf,
        "scene_via": scene_via,
        "classify_review": classify_review,  # v4.4.17：重要记忆自动分类低置信标记（提示人工固化）
    # P0（3.9.x）：投资「指标自动收敛」——自动从 summary+body 抽取 指标名=数值，
    # 与显式 --attr 合并（显式优先）；纯加性新字段，旧库缺字段返回 {} 安全降级。
        "attrs": _merge_attrs(attrs, _extract_attrs(" ".join([summary or "", body or ""]))),
    # ：状态机 + 优先级 + 领域（纯加性，旧库缺字段降级；非法值落 default）
        "state": normalize_state(state),
        "priority": normalize_priority(priority),
        "area": normalize_area(area),
    # （P1/C1）：「关于谁」四轴（纯加性，默认 None=纯经验非个人事实）
        "about_axis": normalize_about_axis(about_axis),
    # D1/D3：模式追踪 + 优先级（确定性 recurrence 反超竞品 LLM 心算）
        "pattern_key": _pattern_key(category, summary),
        "first_seen": today(),
        "last_seen": today(),
        "recurrence_count": 1,
        "relevance_score": None,
    # ：智能进化与互补元数据（纯加性；旧库缺字段返回默认安全降级）
        "provenance": provenance or "agent",  # agent|workbuddy|auto|external
        "provenance_key": provenance_key or None,  # WB 来源幂等键（来源路径+内容hash），防回声重复
        "src_origin": src_origin or None,     # 原始来源系统标识（wb_user_memory / wb_workspace / ...）
        "derives_from": derives_from or None, # v4.7.0：本记忆刻意派生于该源记忆 id（高层抽象溯源）
        "belief_strength": 1.0,               # 信念强度：证据累积↑/反驳↓，低于阈值→erroneous
        "utility_score": 0.0,                 # 召回效用累积：被判定有用+，无用-
        "auto_evolve": bool(auto_sourced),    # 是否由自我进化自动形成（限期复核）
        "erroneous": False,                   # 被确认错误→停止召回（错误知识遗忘）
        "verified": None,                     # 投资记忆校验状态 true/false/pending
        "verified_at": None,
        "verified_source": None,
        "review_by": None,                    # auto_evolve 形成的记忆限期复核截止日
    }
    # D3：确定性 recurrence 计数（同类模式累积；不靠 LLM grep 手动 +1）
    _apply_recurrence_counts(root, mem, mid, defer_index)
    # 自动纠错：新记忆推翻旧记忆
    _supersede_corrected(root, data, mid, mem, corrects)
    # 自动相似连边（沿用悬空边+doctor 兜底设计）：
    # 仅在新记忆 relations 上追加相关 id、并把反向边写回候选文件；新记忆文件统一在连边后
    # 落盘一次（避免「连边前写一次 + 连边后重写一次」的重复 I/O）。by_tag/by_id 直接取自
    # 进程内增量缓存，零 listdir / 零全量重建。
    if auto_link and not defer_index:
        # 批量模式（defer_index=True）跳过逐条连边：_auto_link_similar 是 O(组大小) 每 deposit，
        # 千条级会累积成 O(n²) 写放大（实测 1万条 371s）。改由 flush_memory_index 全库扫一次
        # 完成（与 reflect 同口径的标签预分组），速度提升约 1~2 个数量级。
        by_tag, by_id = _tag_index_get(root, data)
        _auto_link_similar(root, mid, mem, by_tag=by_tag, by_id=by_id,
                           pending=_PENDING_REVERSE if defer_index else None)
        # P2：记录本次 deposit 时的 embedding 后端状态，让记忆自带「召回质量标签」——
        # 若当时 fastembed 不可用、回退词法级（DEGRADED），用户后续 recall 这条时能立刻知道它没被语义索引过。
    try:
        mem["embedding_status"] = _embedding_status_label()
    except Exception:
        pass
    _write_mem(root, mid, mem)
    # ：派生记忆（derives_from）→ 建立「派生 → 源」有向边（双向 related_to），
    # 便于溯源与回滚；fail-open 不拖累主流程。子模块加载顺序导致该符号未必经 globals 注入，
    # 故运行时按 sys.modules 名（`memory_ops_reflect`）惰性导入，缺失则降级跳过。
    if derives_from:
        try:
            import importlib as _ilu2
            _rm = _ilu2.import_module("memory_ops_reflect")
            _rm._write_related_edge(root, mid, derives_from)
        except Exception:
            try:
                _write_related_edge(root, mid, derives_from)
            except Exception:
                pass
                # 落盘索引层加速：批量模式暂存到内存缓冲，由 flush_memory_index 单连接单事务落盘
                # （避免每条 deposit 开合 SQLite 连接 → 千条级 O(n²) 连接开销，实测 1000 条 36s）；单条模式即时落盘。
    _persist_embeddings_or_queue(root, mid, mem, summary, body, tags, defer_index)
    if not explicit:
        _clf.learn_deposit(model, category, tags, body, summary, scope, explicit=False)
    else:
        _clf.save_model(root, model)
        # 增量维护标签倒排缓存 + 追加索引条目（保持二者 count 一致，下次 deposit 直接复用缓存）
    entry = {
        "id": mid, "category": category or "", "summary": summary or "",
        "tags": tags or [], "tier": tier, "status": "active",
        "scope": scope, "project": project or "",
        "file": mid + ".json", "type": mem["type"],
        "settled": False, "thermal": "warm",
    # 多轴 taxonomy：把 topic（domain/subdomain）+ scene 写入 index entry，
    # 让 recall --domain/--scene 在 L0 硬过滤阶段即可命中，不必读盘。
        "domain": domain, "subdomain": subdomain, "scene": scene,
    # ：场景置信度/来源镜像到 index entry，L0 硬过滤与渲染可用
        "scene_confidence": scene_conf, "scene_via": scene_via,
    # P0（3.9.x）：attrs 镜像到 index entry，供 L0 数值硬过滤与渲染
        "attrs": mem.get("attrs") or {},
    # ：state/priority/area 镜像到 index entry，供 L0 硬过滤与导出
        "state": normalize_state(state),
        "priority": normalize_priority(priority),
        "area": normalize_area(area),
    # （P1/C1）：about_axis 镜像到 index entry，供 L0 硬过滤（--filter about_axis=）
        "about_axis": normalize_about_axis(about_axis),
    # （P5/B3）：auto_sourced 镜像到 index entry，供 staging 隔离开关（recall 默认隔离）
        "auto_sourced": bool(auto_sourced),
    # ：智能进化与互补元数据镜像到 index entry，供 L0 硬过滤（recall 默认隔离 auto/erroneous）
        "provenance": provenance or "agent",
        "provenance_key": provenance_key or None,
        "src_origin": src_origin or None,
        "belief_strength": 1.0,
        "erroneous": False,
        "auto_evolve": bool(auto_sourced),
        "verified": None,
    # 5.0/A3 双时序镜像（新条目 valid_at=创建日、未失效 invalid_at=None）。
    # 必须与 __init__._index_entry_from_mem 的字段集一致，否则走 rebuild 会丢字段。
        "valid_at": mem.get("valid_at"),
        "invalid_at": mem.get("invalid_at"),
    }
    _tag_index_upsert(root, mid, tags, entry)
    data["entries"].append(entry)
    if not defer_index:
        save_index(root, data)  # 单条模式：索引立即可见；批量模式延迟到 flush_memory_index
    if not defer_index:  # 审计：批量路径由 flush_memory_index 统一记一次
        _audit_log(root, "deposit", mid, {"recorded_by": mem.get("recorded_by"),
                                          "tier": mem.get("tier"),
                                          "summary": (mem.get("summary") or "")[:40]})
        # ：新记忆写入 → 打 dirty，self-heal 据此只重算脏数据（合并多次变更为一次）
        try:
            from _self_heal import mark_dirty_safe
            mark_dirty_safe(root, mid)
        except Exception:
            pass
            # P1：路由登记册——记录本条记忆的 canonical 层（decide_home：tag > scope > category > L4），
            # 供 doctor 聚合「跨层重复/晋升候选」（防跨层重复沉积）。fail-open：任何异常不拖累 deposit 主流程。
    try:
        from contract.router import RouteRegistry
        _rr_path = os.path.join(root, "store", "route_registry.json")
        _rr = RouteRegistry(_rr_path)
        _rr.decide_and_record(mid, tags=tags or [], category=category or "",
                              summary=summary or "", scope=scope or "")
        _rr.save()
    except Exception:
        pass
        # A3：写时显式暴露分类置信——当 type 为自动推导且置信<0.6 时，
        # 向 agent 回显提示，把"非权威"变成"显式可纠"（零行为变更，纯信息）。
    if not type_explicit and float(type_conf) < 0.6:
        import sys as _sys
        _sys.stderr.write(
            "[keeper] 自动归类为 %s（conf %.2f）；如需锁定请传 --type <TYPE>\n"
            % (_mem_type, float(type_conf))
        )
    return mid

def _apply_recurrence_counts(root, mem, mid, defer_index):
    """D3：确定性 recurrence 计数（同类模式累积；不靠 LLM grep 手动 +1）。

    自 _deposit_impl 抽出（2026-09-15 拆分，行为零变更）。就地修改 mem。
    defer_index=True（批量）时跳过——批量路径不做全库扫描。
    """
    if not defer_index:
        try:
            _pk = mem["pattern_key"]
            _existing = [m for m in _all_mems(root).values()
                         if m.get("pattern_key") == _pk and m.get("id") != mid
                         and m.get("status") == "active"]
            if _existing:
                mem["recurrence_count"] = len(_existing) + 1
                _fs = [m.get("first_seen") for m in _existing if m.get("first_seen")]
                if _fs:
                    mem["first_seen"] = min(_fs + [mem["first_seen"]])
        except Exception:
            pass

def _supersede_corrected(root, data, mid, mem, corrects):
    """自动纠错：新记忆推翻旧记忆（corrects 为被取代的旧记忆 id）。

    自 _deposit_impl 抽出（2026-09-15 拆分，行为零变更）。副作用：旧记忆文件标
    superseded + 置信度 Beta 下调 + 记 calibrated_down；同步 index entry.status、
    写 dirty 标记、校准统计入 meta；并在 mem.relations 上记 corrected_by。
    """
    if corrects:
        # O4 修复：corrects 目标不存在时优雅降级为「仅 deposit」，不再抛 FileNotFoundError 崩溃
        try:
            old, _ = _load_mem(root, corrects)
        except FileNotFoundError:
            old = None
        if old is not None:
            old.setdefault("relations", {})
            old["relations"]["superseded_by"] = mid
            old["status"] = "superseded"
            old["superseded_at"] = today()  # 回收计时起点：自被取代日起算 180 天
            old["settled"] = False  # #9：离开 active 集 → settled 失效，复活时需重新沉淀
            # 置信度校准（Beta 后验）：被新结论推翻 → beta 大幅+（含 alpha 比例项，
            # 多次推翻几何趋零），不再简单 *0.5，更符合「证据累积」语义。
            _ensure_beta(old)
            old["conf_beta"] = round(old.get("conf_beta", 0.0) + 3.0 + old.get("conf_alpha", 1.0) * 0.5, 4)
            _recompute_conf(old)
            old.setdefault("accessed_from", [])
            old["accessed_from"].append({"action": "calibrated_down",
                                         "reason": "corrected_by %s" % mid, "date": today()})
            if len(old["accessed_from"]) > 12:
                del old["accessed_from"][:len(old["accessed_from"]) - 12]
            _save_mem(root, corrects, old)
            mem["relations"]["corrected_by"] = corrects
            # 同步校准统计到 meta（供观察校准闭环效果）
            try:
                _cm = _load_meta(root)
                _cm.setdefault("calibration", {"n_lowered": 0, "n_raised": 0})
                _cm["calibration"]["n_lowered"] = _cm["calibration"].get("n_lowered", 0) + 1
                _save_meta(root, _cm)
            except Exception:
                pass
                # 同步 index 里旧 entry 的 status，避免「文件 superseded / 索引 active」脱节
            for e in data.get("entries", []):
                if e.get("id") == corrects:
                    e["status"] = "superseded"
                    # ：源记忆被推翻 → 打 dirty，让 self-heal 同步相关 skill/规则层
            try:
                from _self_heal import mark_dirty_safe
                mark_dirty_safe(root, corrects)
            except Exception:
                pass

def _persist_embeddings_or_queue(root, mid, mem, summary, body, tags, defer_index):
    """向量/倒排落盘：单条模式即时写，批量模式暂存内存缓冲（由 flush 统一落盘）。

    自 _deposit_impl 抽出（2026-09-15 拆分，行为零变更）。落盘失败不再静默吞：
    告警并带上 mid，便于 doctor / 运维发现后 rebuild 修复。
    """
    if defer_index:
        _PENDING_EMBEDS.setdefault(os.path.abspath(root), []).append(
            (mid, summary, body, tags, mem.get("type"), mem.get("scope")))
    else:
        try:
            _persist_embed_and_inv(root, mid, summary, body, tags,
                                   text=_embed_text_for(mem))
        except Exception as e:
            # 向量/倒排落盘失败：记忆已入库（_write_mem 已写）但无向量 → 不可语义召回。
            # 不再静默吞：告警 + 记录 mid，便于 doctor / 运维发现并 rebuild 修复。
            import sys as _sys
            _sys.stderr.write(
                "WARN: 向量/倒排落盘失败 mid=%s err=%s"
                "（记忆已入库但不可语义召回，可 rebuild 修复）\n" % (mid, repr(e)[:200]))
            # 自动初判（非显式）也轻量累积先验（进程内），但**不每次落盘 classifier.json**
            # —— 避免千条库 bulk deposit 反复读写模型文件拖累吞吐；强信号（显式 scope /
            # reclassify / reflect 自动纠正）才持久化，保证跨会话学习不丢。

def deposit(root, category, summary, tags, body, mid=None, tier="working",
            confidence=None, inferred=False, importance=None, corrects=None,
            scope=None, project="", auto_link=True, defer_index=False,
            recorded_by="agent", auto_sourced=False, sensitive_action="raise",
            type_confidence=None, secondary_types=None, domain=None, subdomain=None,
            scene=None, attrs=None, state=None, priority=None, area=None,
            about_axis=None, mem_type=None,
            provenance="agent", provenance_key=None, src_origin=None, skip_dedup=False,
            derives_from=None):
    """deposit 公共入口——Bug-1/Bug-4 修复：非批量模式加 per-root 线程锁。

    世模沙箱 W4 暴露的根因：deposit() 直接被 Python 多线程调用时（非 CLI 路径），
    gen_id 的 scan-then-create + load_index/save_index 的 read-modify-write 均非原子，
    导致 ID 冲突丢数据 + 索引覆盖不一致。批量模式（defer_index=True）由单线程驱动、
    _BULK_SEQ/_BATCH_DATA 进程内增量维护，无需加锁（RLock 可重入，即使批量内嵌套
    调用也不会死锁）。

    skip_dedup=True：跳过写前查重（兼容旧调用，已不推荐）。
    derives_from=<source_id>：声明本记忆是 <source_id> 的**刻意高层抽象派生**（如 evolve
    合成的原则）。派生记忆应作为独立新节点创建，不被近重复查重吞掉成源记忆 ID——
    这是 v4.7.0 取代 skip_dedup hack 的正确机制：用「派生意图」而非「无脑跳过查重」。
    派生关系会写入 `derives_from` 字段并建立 related_to 边，便于溯源与回滚。
    """
    if defer_index:
        return _deposit_impl(root, category, summary, tags, body, mid=mid, tier=tier,
                             confidence=confidence, inferred=inferred, importance=importance,
                             corrects=corrects, scope=scope, project=project,
                             auto_link=auto_link, defer_index=defer_index,
                             recorded_by=recorded_by, auto_sourced=auto_sourced,
                             sensitive_action=sensitive_action,
                             type_confidence=type_confidence,
                             secondary_types=secondary_types, domain=domain, subdomain=subdomain,
                             scene=scene, attrs=attrs, state=state, priority=priority,
                             area=area, about_axis=about_axis, mem_type=mem_type,
                             provenance=provenance, provenance_key=provenance_key, src_origin=src_origin,
                             skip_dedup=skip_dedup, derives_from=derives_from)
    with _get_deposit_lock(root):
        return _deposit_impl(root, category, summary, tags, body, mid=mid, tier=tier,
                             confidence=confidence, inferred=inferred, importance=importance,
                             corrects=corrects, scope=scope, project=project,
                             auto_link=auto_link, defer_index=defer_index,
                             recorded_by=recorded_by, auto_sourced=auto_sourced,
                             sensitive_action=sensitive_action,
                             type_confidence=type_confidence,
                             secondary_types=secondary_types, domain=domain, subdomain=subdomain,
                             scene=scene, attrs=attrs, state=state, priority=priority,
                             area=area, about_axis=about_axis, mem_type=mem_type,
                             provenance=provenance, provenance_key=provenance_key, src_origin=src_origin,
                             skip_dedup=skip_dedup, derives_from=derives_from)

def _auto_link_similar(root, mid, mem, by_tag=None, by_id=None, threshold=0.15, max_links=5, pending=None):
    """deposit 时自动把新记忆与库内「主题相关」的活跃记忆连边（related_to，双向）。

    知识图谱式的自动连边，零新增依赖。性能关键：用「标签预分组
    + 大组跳过」把比较对从 O(n) 降到共享标签子集（复用去重的 MAX_GROUP 原则，避免千条库
    O(n²) 爆炸），组内再用廉价 `_sim` 预筛，仅对少量候选写回反向边。

    by_tag/by_id 由调用方（deposit）直接传入进程内增量缓存，本函数**不再 load_index +
    全量重建**（旧版千条库 O(n²) 的根因）。阈值 0.15 < 去重阈值 0.6，专抓「相关但不重复」
    的记忆，供 AI/用户导航，不会与 reflect 的近似去重冲突。沿用 link 的悬空边设计：
    related_to 指向真实存在的记忆；若未来某条被 delete，doctor 的 dangling_relations 会
    兜底检出。任何异常都不阻断 deposit 主流程。

    注意：本函数只在新记忆的 relations 上「就地追加」相关 id，并把反向边写回候选文件；
    新记忆文件本身由 deposit 统一落盘一次（避免连边前/后的重复写 I/O）。"""
    try:
        if by_tag is None or by_id is None:
            # 兜底：无缓存时退回一次性全量构建（极少见，仅防御性路径）
            data = load_index(root)
            by_tag, by_id = _tag_index_get(root, data)
        my_tags = mem.get("tags", []) or []
        if not my_tags:
            return
        my_set = set(my_tags)
        # 从进程内增量缓存直接取预分组（零 listdir、零全量重建）
        cand_ids = set()
        for t in my_set:
            grp = by_tag.get(t)
            if grp and len(grp) <= 150:
                cand_ids.update(grp)
        cand_ids.discard(mid)  # 防御：正常 upsert 后 mid 尚未进缓存，但保险排除自身
        if not cand_ids:
            return
        text = " ".join([mem.get("summary", ""), mem.get("body", ""),
                         " ".join(my_tags)]).strip()
        if not text:
            return
        cand = []
        for oid in cand_ids:
            e = by_id.get(oid)
            if e is None or e.get("status") != "active":
                continue
            otext = " ".join([e.get("summary", ""), " ".join(e.get("tags", []))]).strip()
            if not otext:
                continue
            s = _sim(text, otext)  # 纯词法 jaccard，零文件读（用 index 的 summary+tags）
            if s >= threshold:
                cand.append((oid, s))
        cand.sort(key=lambda x: x[1], reverse=True)
        chosen = [c[0] for c in cand[:max_links]]
        if not chosen:
            return
        mem.setdefault("relations", {})
        for oid in chosen:
            if oid not in mem["relations"].setdefault("related_to", []):
                mem["relations"]["related_to"].append(oid)
            if pending is not None:
                # 方案 D：批量模式反向边仅记内存 pending，flush 时合并回写（每旧文件只 open 一次）
                pending.setdefault(oid, set()).add(mid)
                continue
            e = by_id.get(oid)
            if e is None:
                continue
                # 候选必为 active（已过滤），物理文件恒在 mem_dir 根
            fp = os.path.join(mem_dir(root), oid + ".json")
            if not os.path.exists(fp):
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    om = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            except Exception:
                # 读不出来就跳过本条反向边，绝不污染旧记忆
                continue
            om.setdefault("relations", {})
            if mid not in om["relations"].setdefault("related_to", []):
                om["relations"]["related_to"].append(mid)
                _save_mem(root, oid, om)  # 反向边落盘
                # 新记忆文件由 deposit 统一落盘，此处不写，避免重复 I/O
    except Exception:
        # 自动连边是锦上添花，绝不阻断 deposit
        pass

@_with_deposit_lock
def flush_memory_index(root: str, auto_link: bool = True) -> None:
    """批量导入收尾（方案 A+D 的落盘点）：save_index 一次 + 合并回写所有 pending 反向边。

    必须在所有 defer_index=True 的 deposit 之后调用一次；非批量场景下调用无副作用。
    反向边合并：每个被连边的旧文件只 open+read+write 一次（即使被多条新记忆连边），
    消除旧版「每条 deposit 对最多 max_links 个候选各开一次」的 I/O 放大。
    auto_link=True 时再补一次「全库标签预分组连边」（批量 deposit 跳过了逐条连边，
    这里一次性补齐，避免 O(n²) 写放大）。"""
    global _BATCH_ROOT, _BATCH_DATA, _PENDING_REVERSE, _BULK_SEQ, _PENDING_EMBEDS
    if _BATCH_DATA is None:
        return
        # 1) 全量索引落盘一次（替代每条 deposit 一次 save_index 的 O(n²) 写入量）
    save_index(root, _BATCH_DATA)
    # 1.5) 批量落盘向量+倒排（单连接单事务；recall 复用免逐条 embed）
    _pending = _PENDING_EMBEDS.pop(os.path.abspath(root), [])
    _batch_mids = [p[0] for p in _pending] if _pending else []
    if _pending:
        try:
            _persist_batch(root, _pending)
        except Exception:
            pass  # 加速层失败不阻断主流程（recall 会惰性回填）
            # 2) 反向边合并回写：每个 oid 只 open+read+write 一次
    for oid, mids in _PENDING_REVERSE.items():
        fp = os.path.join(mem_dir(root), oid + ".json")
        if not os.path.exists(fp):
            fp = os.path.join(archive_dir(root), oid + ".json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                om = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        rel = om.setdefault("relations", {})
        lst = rel.setdefault("related_to", [])
        changed = False
        for m in mids:
            if m not in lst:
                lst.append(m)
                changed = True
        if changed:
            _save_mem(root, oid, om)
            # 2.5) 批量一次性连边（替代逐条 deposit 的 O(n²) 写放大）：批量 deposit 已跳过逐条
            # _auto_link_similar，这里用标签预分组全库扫一次（与 reflect 同口径），快得多；
            # _apply_link_candidates 内部按「每唯一记忆只写一次」批量化，零额外放大。
    if auto_link:
        try:
            cands = _find_link_candidates(root)
            _apply_link_candidates(root, cands)
        except Exception:
            pass  # 连边是锦上添花，绝不阻断收尾
            # 3) 重置批量状态
            # ：批量写入的记忆 → 打 dirty，让 self-heal 同步相关 skill/规则层
    try:
        from _self_heal import mark_dirty_safe
        _reverse_oids = list(_PENDING_REVERSE.keys())
        for _mid in set(_batch_mids + _reverse_oids):
            if _mid:
                mark_dirty_safe(root, _mid)
    except Exception:
        pass
    _BATCH_ROOT = None
    _BATCH_DATA = None
    _PENDING_REVERSE.clear()
    _BULK_SEQ.pop(os.path.abspath(root), None)
    _tag_index_reset(root)  # 旧文件 relations 已变，作废倒排缓存（下次 deposit 全量重建一次）
