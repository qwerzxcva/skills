# F18 阶段2 批7：_recall 读路径簇（函数级精确搬移，零行为变化）
# export_memories / stats / _rank_query / recall_multi / recall
# 从 memory_ops/__init__.py 机械搬移，仅搬这 5 个顶层 def。
# 共享 helper（_audit_log/_audit_log_tail/recall_cache*/各依赖符号）留在 __init__，
# 本模块通过 __init__ 全局灌入式注入解析它们。

# md 往返（export → import）摘要键。v4.9.1 前 export md 只写 id 不写 summary，
# 导致 import 把 id 当 summary，正文摘要丢失（跨设备同步实测 P0）。
# 现在 meta 行首位写入摘要，import 侧用正则优先取回（见 keeper_import._parse_md）。
META_SUMMARY_KEY = "摘要"
META_KEYS = ("摘要", "分类", "类型", "层级", "标签", "创建")


def _render_md(m):
    """单条记忆 → 标准 Markdown 块。

    v4.9.1：meta 行首位新增「摘要: <summary>」，使 md 往返（export→import）不再丢摘要。
    旧渲染（无摘要键）仍可被 import 兼容解析（回退 body 前 120 字）。"""
    mid = m.get("id", "")
    summ = (m.get("summary") or "").strip()
    cat = m.get("category", "")
    typ = m.get("type", "")
    tier = m.get("tier", "")
    tags = m.get("tags", []) or []
    created = m.get("created") or m.get("created_at", "")
    meta = []
    if summ:
        # 单行化：md 的 meta 行必须是单行，摘要里的换行会截断后续字段
        meta.append("%s: %s" % (META_SUMMARY_KEY,
                                " ".join(summ.split())))
    if cat:
        meta.append("分类: %s" % cat)
    if typ:
        meta.append("类型: %s" % typ)
    if tier:
        meta.append("层级: %s" % tier)
    if tags:
        meta.append("标签: %s" % ", ".join(tags))
    if created:
        meta.append("创建: %s" % created)
    body = m.get("body", "") or ""
    blk = ["## %s" % mid]
    if meta:
        blk.append("> " + " · ".join(meta))
    blk.append("")
    blk.append(body)
    blk.append("")
    blk.append("---")
    blk.append("")
    return "\n".join(blk)


def _safe_name(s):
    """把记忆 id 转成安全文件名（避免路径分隔符/冒号等非法字符）。"""
    return str(s).replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_")


def _is_dir_target(dest):
    """learnings 导出：dest 是否应解释成「目录模式」（每条记忆一个文件，git 可 diff）。
    - 以路径分隔符结尾 / 本身是已存在目录 / 不含 .扩展名 → 目录模式
    - 含 .md/.txt/.jsonl 扩展名 → 单文件模式"""
    if dest.endswith(os.sep) or dest.endswith("/"):
        return True
    if os.path.isdir(dest):
        return True
    base = os.path.basename(dest)
    return not base.endswith((".md", ".txt", ".jsonl"))


def _render_learning(m, rc_map):
    """单条记忆 → 标准化 learnings 条目（date/trigger/lesson/
    recurrence_count/status），可被任意支持 .learnings/ 的工具或 git 共享消费。

    trigger 由 keeper 现有字段合成（scene/domain/tags），lesson 优先 body 后 summary；
    recurrence_count 取自 index 镜像（mem 文件未必含），status 取自记忆实况。"""
    mid = m.get("id", "")
    summary = (m.get("summary") or "").strip()
    body = (m.get("body") or "").strip()
    tags = m.get("tags", []) or []
    scene = m.get("scene") or ""
    domain = m.get("domain") or ""
    typ = m.get("type") or m.get("category") or ""
    tier = m.get("tier") or ""
    status = m.get("status") or "active"
    rc = int(rc_map.get(mid, m.get("recurrence_count", 1)) or 1)
    created = (m.get("created") or m.get("created_at") or "")[:10]
    trigger_parts = []
    if scene:
        trigger_parts.append("场景=%s" % scene)
    if domain:
        trigger_parts.append("域=%s" % domain)
    if tags:
        trigger_parts.append("标签=%s" % ", ".join(tags))
    trigger = "；".join(trigger_parts) if trigger_parts else (summary or "(未标注触发条件)")
    lesson = body or summary
    return (
        "## %s · %s\n\n"
        "- **date**: %s\n"
        "- **trigger**: %s\n"
        "- **lesson**: %s\n"
        "- **recurrence_count**: %d\n"
        "- **status**: %s\n"
        "- **type**: %s\n"
        "- **tier**: %s\n\n"
        "---\n\n"
    ) % (mid, summary, created, trigger, lesson, rc, status, typ, tier)


def export_memories(root, fmt="md", dest=None, include_archived=False,
                    include_superseded=False):
    """导出整库记忆为标准 Markdown / JSONL / learnings（独立于 zip 备份，增强跨工具可移植性）。
    fmt:
    - 'md'（每条二级标题 + 元数据 + 正文）
    - 'jsonl'（每行一个 JSON 记忆）
    - 'learnings'（标准化可读学习条目：date/trigger/lesson/
    recurrence_count/status；--out 指向目录时每条记忆写一个 .md 文件，git 可 diff 共享）
    dest 不传则把内容直接写到 stdout（便于管道 `export > out.md`）；传入则写文件并返回路径。

    v4.9.1 状态过滤（跨设备同步实测修复）：
    - 默认仅 active；--include-superseded 追加被取代记忆；--include-archived 追加全部
      （含 archived + superseded，保持历史语义不变）。
    - 返回 filtered_out / hidden_superseded / hidden_archived，让「静默少导」变成显式可见。

    返回 {ok, format, count, filtered_out, hidden_superseded, hidden_archived, dest?} /
    {ok, format, count, ..., content}（stdout 模式）/
    {ok, format, count, ..., dest, files}（learnings 目录模式）。"""
    if fmt not in ("md", "jsonl", "learnings"):
        return {"ok": False, "error": "unsupported_format", "msg": "fmt 仅支持 md / jsonl / learnings"}
    init_store(root)
    # recurrence_count 来自 index 镜像（mem 文件未必含该字段），learnings 渲染需要
    try:
        _idx = load_index(root)
        _rc_map = {e.get("id"): e.get("recurrence_count", 1)
                   for e in _idx.get("entries", []) if isinstance(e, dict) and e.get("id")}
    except Exception:
        _rc_map = {}
    _all = list(_iter_all_mems(root))

    def _keep(m):
        """状态过滤：默认 active；superseded 需显式开关；archived 需 --include-archived。
        未知/缺失状态一律保留（宁可多导，不可静默丢）。"""
        st = (m.get("status") or "active")
        if st == "active":
            return True
        if st == "superseded":
            return bool(include_superseded or include_archived)
        if st == "archived":
            return bool(include_archived)
        return True

    mems = [m for m in _all if _keep(m)]
    count = len(mems)
    _export_meta = {
        "filtered_out": len(_all) - count,
        "hidden_superseded": sum(1 for m in _all
                                 if (m.get("status") or "active") == "superseded"
                                 and not _keep(m)),
        "hidden_archived": sum(1 for m in _all
                               if (m.get("status") or "active") == "archived"
                               and not _keep(m)),
    }
    if _export_meta["filtered_out"] > 0:
        sys.stderr.write(
            "HINT: export 默认仅导出 active 记忆，已跳过 %d 条"
            "（superseded %d / archived %d）。如需全量跨设备同步，"
            "加 --include-superseded --include-archived。\n"
            % (_export_meta["filtered_out"], _export_meta["hidden_superseded"],
               _export_meta["hidden_archived"]))
    # learnings 目录模式：每条记忆一个文件（git/跨工具友好）
    if fmt == "learnings" and dest and _is_dir_target(dest):
        os.makedirs(dest, exist_ok=True)
        written = []
        for m in mems:
            fn = os.path.join(dest, "%s.md" % _safe_name(m.get("id", "mem")))
            try:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(_render_learning(m, _rc_map))
                written.append(fn)
            except Exception as _e:
                return {"ok": False, "error": "write_failed", "msg": str(_e)}
        out = {"ok": True, "format": fmt, "count": count,
               "dest": dest, "files": written}
        out.update(_export_meta)
        return out
        # 单文件 / stdout
    if fmt == "jsonl":
        text = "\n".join(json.dumps(m, ensure_ascii=False) for m in mems)
    elif fmt == "learnings":
        text = "\n".join(_render_learning(m, _rc_map) for m in mems)
    else:
        text = "\n".join(_render_md(m) for m in mems)
    if dest:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
        out = {"ok": True, "format": fmt, "count": count, "dest": dest}
        out.update(_export_meta)
        return out
    out = {"ok": True, "format": fmt, "count": count, "content": text}
    out.update(_export_meta)
    return out

def stats(root, top=5):
    """可观测性（§6#8）：汇总召回频次热/温/冷分布 + Top 高频记忆 + 库规模。
    只读、零模型依赖、不触盘（仅读 recall_counts.json 与 index.json）。
    统计口径与 daemon._stats 对齐：hot>=5, warm 1-4, cold==0。"""
    # 5.0.0：旧加密库 fail-closed 守卫。**必须显式放在最前**：本函数内部两处读盘
    # （`_load_mem` / `load_index`）都写在 `except Exception: pass` 里，守卫异常会被
    # **静默吞掉**，于是「拒绝服务」退化回「静默返回 total_memories=0 / summary=""」——
    # 恰好是守卫要根治的那种假答案。这正是「静默容错会吃掉 fail-closed」的实例。
    assert_not_legacy_encrypted(root, op="统计记忆库")
    rp = os.path.join(root, "recall_counts.json")
    data = {}
    try:
        if os.path.exists(rp):
            with open(rp, encoding="utf-8") as _f:
                data = json.load(_f) or {}
    except Exception:
        data = {}
    counts = {k: (int(v.get("count", 0)) if isinstance(v, dict) else 0)
              for k, v in data.items()}
    n = len(counts)
    hot = sum(1 for c in counts.values() if c >= 5)
    warm = sum(1 for c in counts.values() if 1 <= c < 5)
    cold = sum(1 for c in counts.values() if c == 0)
    # Top 高频（按 count 降序，附带 summary 便于定位热点）
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_items = []
    for mid, c in ranked[:max(0, int(top))]:
        summary = ""
        try:
            m, _ = _load_mem(root, mid)
            summary = (m.get("summary") or "")[:120]
        except Exception:
            summary = ""
        top_items.append({"id": mid, "count": c, "summary": summary})
        # 库规模（active / archived）
    total_mems = 0
    archived = 0
    try:
        idx = load_index(root)
        for e in idx.get("entries", []):
            total_mems += 1
            if e.get("status") == "archived":
                archived += 1
    except Exception:
        pass
    return {
        "ok": True,
        "recall_tracked": n,
        "hot": hot, "warm": warm, "cold": cold,
        "max_recall_count": max(counts.values()) if counts else 0,
        "total_recall_events": sum(counts.values()),
        "top": top_items,
        "total_memories": total_mems,
        "active": total_mems - archived,
        "archived": archived,
        "vector_coverage": vector_coverage(root),
    }

def _rank_query(root, query, include_superseded=False, include_archived=False, min_score=0.06, ann=False, cluster_boost=False, as_of=None):
    """多信号 RRF 融合排序（多路信号融合）。
    每条记忆由多路弱信号各自排序，再用 RRF(1/(k+rank), k=60) 汇总成强排序：
    1) 语义混合分 sem = 0.6·emb_c + 0.3·tf + 0.2·syn  — 主信号，兼作召回地板
    2) Jaccard 词重叠 _sim(query, text)              — 中英混合 tokenizer 重叠
    3) 时间衰减 recency(accessed/created)            — 越新越高
    4) 置信度 confidence                              — 记忆自身校准置信
    5) 品牌重叠 brand_mentions                        — query/记忆 共同提及品牌占比
    返回 {id: rrf_score}，供 recall 过滤与降序排序。
    相比原单点积混合分，能把『语义分中等但多路弱信号一致』的记忆顶上来，缓解『相似度≠相关性』，
    并补强『换种说法 / 部分词汇重叠 / 同品牌』的召回质量。
    召回集合门槛 = 语义地板(sem>=min_score) ∪ 强信号(substring/brand/syn) ∪ RRF 弱门(fused>=0.03)，
    在『不退化旧召回』与『补强部分匹配』间取平衡。无 hnswlib 时 ann 静默回退全量，结果不变。

    跨语言召回引导（详见 references/FEATURES.md §8）：
    - 词法后端下 TF-IDF/Jaccard 跨语言弱，靠品牌名重叠 + 双语标签弥补；
    - 神经后端（fastembed/sentence_transformers）的 embedding 余弦可跨语言语义匹配；
    - deposit 时在 tags 中同时写中英文关键词可显著提升跨语言召回率。"""
    mems = _all_mems(root)
    cfg = _load_recall_config(root)  # P1-5a：召回信号权重（默认 or config.json 覆盖）
    tfidf = dict(_tfidf_search(root, query, mems=mems, include_superseded=include_superseded,
                              include_archived=include_archived,
                              top_k=10 ** 9, min_score=0.0))
    try:
        q_emb = _emb.embed(query)
    except Exception:
        q_emb = None  # P-audit F2：神经嵌入不可用时不整段 abort，降级词法（tfidf/强信号仍生效）
    q_forms = _emb.expand_synonyms(query)
    q_low = query.lower()
    bq = _emb.extract_brands(query)  # query 品牌集合，循环外算一次
    # 落盘向量：一次加载全部持久化向量；失败则退化为现场 embed（保持旧行为）
    try:
        vecs = _emb_store_load_all(root)
    except Exception:
        vecs = {}
        # #7：可选 ANN 候选集（仅 ann=True 且 hnswlib 可用时生效；否则 None 走全量）
        # 自动启用：库 ≥ ann_min（默认 50）且 ≤256 时自动走 ANN——O2 安全 k 全覆盖，
        # 召回结果与全量线性一致（实测 500 条默认 1824ms → ANN 226ms，8 倍加速）。
        # >256 条的大库剪枝是近似行为，需显式 ann=True 才启用（不悄悄替用户做 tradeoff）。
    ann_ids = None
    if ann and q_emb is not None:
        n_mem = len(mems)
        ann_k = n_mem if n_mem <= 256 else min(512, max(256, n_mem // 4))
        cand, ok = _ann_candidates(root, q_emb, k=ann_k)
        if ok and cand:
            ann_ids = set(cand)
    else:
        try:
            _n_all = len(mems)
            _cfg = _load_keeper_config(root)
            _ann_min = _cfg["ann_min_memories"]
            if q_emb is not None and _n_all >= _ann_min and _n_all <= 256:
                # 中小库：k=n_all 全覆盖，ANN 结果与线性一致，安全自动开。
                cand, ok = _ann_candidates(root, q_emb, k=_n_all)
                if ok and cand:
                    ann_ids = set(cand)
            elif q_emb is not None and _n_all > 256 and _cfg.get("ann_auto_large", False):
                # 大库高召回 ANN（opt-in，默认关）：k 取六成以上留足召回余量。
                # 仍属近似剪枝——仅用户显式接受「快但可能漏少量」时启用，不静默 tradeoff。
                _k = min(_n_all, max(512, int(_n_all * 0.6)))
                cand, ok = _ann_candidates(root, q_emb, k=_k)
                if ok and cand:
                    ann_ids = set(cand)
        except Exception:
            pass  # 自动启用失败静默回退全量线性（结果不变）
            # 用 _model_fingerprint（不触发模型加载）拿后端标识+模型内容指纹做比对，
            # 避免冷进程仅为取标识而加载模型；同时模型被替换/损坏后旧落盘向量自动失效重嵌。
    model = _emb._model_fingerprint()
    # 每路信号原始分收集（RRF 各自排名后融合）
    sig_sem, sig_jac, sig_rec, sig_conf, sig_brand, sig_sem_raw = {}, {}, {}, {}, {}, {}  # P1-3 sig_sem_raw
    strong = set()        # substring / brand / syn 命中 → 强信号，越过语义地板直接召回
    pending_persist = []  # 待落盘向量：(mid, vec, text_hash, model)；循环外单事务提交
    for m in mems.values():
        if ann_ids is not None and m["id"] not in ann_ids:
            continue  # #7：ANN 模式下仅对近邻候选算分（未装 hnswlib 时 ann_ids 为 None，全量）
        # 5.0/A3：as_of 给定 → 按双时序可见性筛选（绕过 status，否则过去的真相查不到）
        if as_of is not None:
            if not _as_of_visible(m, as_of):
                continue
        else:
            st = m.get("status", "active")
            if st != "active" and not (include_superseded and st == "superseded") \
                    and not (include_archived and st == "archived"):
                continue
        text = " ".join([m.get("summary", ""), m.get("body", ""),
                         " ".join(m.get("tags", []))])
        text_low = text.lower()
        item = vecs.get(m["id"]) if vecs else None
        # #O5-bug 修复：除文本哈希（新鲜度）外，必须校验落库后端是否与当前后端一致。
        if item is None or item[1] != _emb_text_hash(text) or item[2] != model:
            try:
                vec = _emb.embed(text)
            except Exception:
                vec = None  # 神经嵌入失败：本轮无语义向量，emb_c 记 0，词法路径兜底
            if vec is not None:
                pending_persist.append((m["id"], vec, _emb_text_hash(text), model))
        else:
            vec = item[0]
        emb_c = _emb.cosine(q_emb, vec) if (q_emb is not None and vec is not None) else 0.0
        sig_sem_raw[m["id"]] = emb_c  # P1-3：保留原始语义余弦，供离题绝对门控使用
        tf = tfidf.get(m["id"], 0.0)
        syn_hit = 0.0
        _syn_matched = 0
        for f in q_forms:
            if f and f.lower() in text_low:
                _syn_matched += 1
                # B1：同义词分级连续打分（替代二值 0/0.6）——命中越多分越高，
                # 提升部分同义词命中的排序区分度。上限仍为 0.6（与原权重一致）。
        if _syn_matched > 0:
            syn_hit = min(1.0, _syn_matched / max(len(q_forms), 1)) * 0.6
        sem = cfg["sem_emb"] * emb_c + cfg["sem_tf"] * tf + cfg["sem_syn"] * syn_hit
        if q_low in text_low:           # 直接子串命中，强信号
            sem = max(sem, 0.9)
            strong.add(m["id"])
        sig_sem[m["id"]] = sem
        sig_jac[m["id"]] = _sim(query, text)
        sig_rec[m["id"]] = _recency_score(m)
        sig_conf[m["id"]] = float(m.get("confidence", 1.0))
        # 品牌重叠：query 提到的品牌中，记忆也提到的占比（复用记忆已存的 brand_mentions）
        if bq:
            bt = set(m.get("brand_mentions", []) or [])
            if not bt:
                bt = set(_emb.extract_brands(text))
            if bt:
                overlap = len(set(bq) & bt) / len(set(bq))
                if overlap > 0:
                    sig_brand[m["id"]] = overlap
                    strong.add(m["id"])
                    # 批量落盘：本轮新 embed 的向量一次性提交（避免逐条 commit 的连接风暴）
    if pending_persist:
        try:
            _emb_store_put_many(root, pending_persist)
        except Exception:
            for mid, vec, th, mdl in pending_persist:
                try:
                    _emb_store_put(root, mid, vec, text_hash=th, model=mdl)
                except Exception as e:
                    # P2 修复：批量+逐条都失败时不静默——向量未落盘会导致下次召回缺失语义结果
                    import sys as _sys
                    _sys.stderr.write("[⚠ recall] 向量落盘失败 %s: %s（语义召回可能退化）\n" % (mid, e))
                    # RRF 融合：仅『查询相关』信号(语义sem + 词重叠jac + 品牌brand)进主融合；
                    # 时间衰减(rec)/置信(conf)为查询无关信号，降为后置乘性 boost，避免把语义差异冲平
                    # （k=60 下四路同票会把 10 条记忆压成 ~0.002 带宽，导致改写召回排名与 query 几乎无关）。
                    # Plan Y 修复：神经语义已激活，但原四路同票让 recency/confidence 主导，语义召回名存实亡。
    signals = [sig_sem, sig_jac]
    if sig_brand:
        signals.append(sig_brand)
    fused = _rrf_fuse(signals, k=cfg["rrf_k"])
    # A（召回排序修复·：RRF 把 sem/jac 压成近扁平带（k=60、~112 候选时
    # 1/(60+rank) 仅 0.006–0.033 跨度），高语义相关记忆与中游项几无区分度——
    # 表现为「换说法搜不到」。把原始余弦(emb_c) magnitude 重新注入融合分，
    # 让高相关项真正浮到前排；RRF 仍作词法/tie-break 次级信号保留鲁棒性。
    # β 经回归测试定为 0.5（config sem_magnitude_blend 可调：0=纯RRF,1=纯余弦）。
    _beta = float(cfg.get("sem_magnitude_blend", 0.5))
    if _beta > 0:
        for _mid in list(fused.keys()):
            _ec = sig_sem_raw.get(_mid, 0.0)  # 原始余弦 0..1（未混合 tf/syn）
            fused[_mid] = (1.0 - _beta) * fused[_mid] + _beta * _ec
    fused_pre = dict(fused)  # B4 (4.5.45)：boost 前快照（含 A 语义 magnitude 注入），供 why 分解展示

    def _why(out_map):
        """B4 ：把每条命中拆成可读信号贡献：sem 语义混合分 / jac 词重叠 / rec 时间衰减 /
        conf 置信 / brand 品牌重叠 / strong 是否强信号 / fused_pre 融合分（boost 前）/ final 最终分。"""
        return {_mid: {
            "sem": round(sig_sem.get(_mid, 0.0), 4),
            "jac": round(sig_jac.get(_mid, 0.0), 4),
            "rec": round(sig_rec.get(_mid, 0.5), 4),
            "conf": round(sig_conf.get(_mid, 1.0), 4),
            "brand": (round(sig_brand[_mid], 4) if _mid in sig_brand else None),
            "strong": _mid in strong,
            "fused_pre": round(fused_pre.get(_mid, 0.0), 4),
            "final": round(out_map[_mid], 4),
        } for _mid in out_map}

        # 后置 boost：recency/confidence 仅做轻度修正，不占主票（保留其影响力但不再压过语义）
    for _mid in list(fused.keys()):
        _rc = sig_rec.get(_mid, 0.5)
        _cf = sig_conf.get(_mid, 1.0)
        fused[_mid] = fused[_mid] * (0.7 + 0.3 * _rc) * (0.85 + 0.15 * _cf)
        # P2-3：低置信自动分类降权——scene_via=='rule'（纯关键词，脆弱）且置信<0.7 的记忆，
        # 在召回排序中降权（非隐藏），减少错场景误召回。纯检索层、零数据风险；
        # 不影响召回门（语义/强信号命中仍召回），只压低其排名。
    _lc_dw = float(cfg.get("low_conf_downweight", 0.5))
    _excos = float(cfg.get("sem_exempt_lowconf_cos", 0.5))
    for _mid, _m in mems.items():
        if _m.get("scene_via") == "rule" and float(_m.get("scene_confidence", 1.0)) < 0.7:
            # B：高语义相关（原始余弦≥阈值）的记忆即便 scene 靠规则分类，
            # 也不应被砍半——高 cosine 已强暗示其确为相关，豁免避免「最相关项被埋没」。
            if _mid in fused and sig_sem_raw.get(_mid, 0.0) < _excos:
                fused[_mid] *= _lc_dw
                # A2：type 低置信对称降权——type_via 缺失或为 'rule' 且置信<0.7 时，
                # 与 scene 同比例降权，减少错类型误召回（如 BP 被当 FACT 检出）。
        _tv = _m.get("type_via", "")
        _tc = float(_m.get("type_confidence", 1.0))
        if (_tv == "rule" or not _tv) and _tc < 0.7:
            if _mid in fused:
                fused[_mid] *= _lc_dw
                # #6→recall 增强：cluster_boost 在 RRF 之上加性加成，放宽地板让簇成员浮出
    if cluster_boost:
        _cl = _load_clusters(root)
        if _cl and _cl.get("centroids"):
            best_cid, best_sim = None, -1.0
            for _cid, _vec in _cl["centroids"].items():
                _sim_c = _emb.cosine(q_emb, _vec) if q_emb is not None else 0.0
                if _sim_c > best_sim:
                    best_sim, best_cid = _sim_c, _cid
            if best_cid is not None and best_sim > 0.0:
                CLUSTER_BOOST = 0.15
                for _mid in list(fused.keys()):
                    if _mid in _cl["assign"] and _cl["assign"][_mid] == best_cid:
                        fused[_mid] = min(1.0, fused[_mid] + CLUSTER_BOOST * best_sim)
                relax_floor = max(min_score * 0.6, 0.04)
                out = {_mid: round(_sc, 4) for _mid, _sc in fused.items() if _sc >= relax_floor}
                return out, strong, sig_sem_raw, _why(out)
                # 召回门：语义地板 ∪ 强信号 ∪ RRF 弱门（不退化旧召回，同时补强部分匹配）
                # 修复：弱门不再对「纯靠时间/置信撑分、语义与词重叠均极低」的无关记忆放行，
                # 要求弱门命中的记忆至少有语义中等或词重叠支撑，消除「任何 query 都返回全库」的噪音。
    floor = cfg["min_score"] if min_score == 0.06 else min_score  # 调用方未显式改则用 config
    jac_min = cfg.get("rrf_jac_min", 0.05)
    out = {}
    for _mid, _sc in fused.items():
        sem_score = sig_sem.get(_mid, 0.0)
        if sem_score >= floor or _mid in strong:
            out[_mid] = round(_sc, 4)
        elif _sc >= cfg["rrf_weak"] and sig_jac.get(_mid, 0.0) >= jac_min:
            # 弱门只放「词重叠达标」的记忆（部分关键词命中），不放纯语义/时间撑分的无关记忆
            out[_mid] = round(_sc, 4)
    return out, strong, sig_sem_raw, _why(out)

def recall_multi(roots, query=None, top_n=20, max_tokens=None, **kw):
    """多库交叉召回 最小版）：对多个 root 分别召回，按 score 合并降序，
    每条标记 source 根目录，便于工作/个人/投资分库后统一检索。
    roots: list[str] 或逗号分隔字符串。任一根异常不影响其它根。"""
    if isinstance(roots, str):
        roots = [r.strip() for r in roots.split(",") if r.strip()]
    merged = []
    for root in roots:
        try:
            rows = recall(root, query=query, max_tokens=None, **kw)
            for e in rows:
                e["source_root"] = os.path.abspath(root)
                merged.append(e)
        except Exception:
            continue
    merged.sort(key=lambda e: e.get("score", 0.0), reverse=True)
    if max_tokens and max_tokens > 0:
        _used = 0
        _kept = []
        for _e in merged:
            _t = token_estimate(_e)
            if _used + _t > max_tokens and _kept:
                break
            _used += _t
            _kept.append(_e)
        merged = _kept
    return merged[:top_n]

def recall(root, tag=None, category=None, query=None, tier=None,
           min_tier=None, include_superseded=False, scope=None,
           project=None, deep=False, touch=False, mid=None, ann=False,
           cluster_boost=False, outcome=None, domain=None, scene=None, subdomain=None,
           filter_clauses=None, include_auto=False, about_axis=None,
           semantic_gate=None, hops=0, llm=None, max_tokens=None, with_meta=False,
           as_of=None):
    # 单条读取：按 id 精确取一条（memories/ 与 memories/archive/ 两处都查，
    # 故归档记忆也能取到，无需 --deep）。不存在抛 FileNotFoundError → 调用方得
    # 到清晰的 not_found（这也是多处错误提示里「先 recall --id 重读最新」的真实命令）。
    if mid:
        m, fp = _load_mem(root, mid)
        # 显式按 id 召回归档记忆 → 记录最近召回日，使其免于被回收误删（回收豁免）
        if m.get("status") == "archived":
            _mark_recalled(root, mid)
            # recall --outcome：单条召回时附带正负反馈（自主校准）。仅 mid 路径生效。
        if outcome in ("good", "bad"):
            _apply_signal(m, outcome)
            # 5.0/A1 根治：删掉此处的 `m["access_count"] = … + 1`（写记忆文件）。
            # 频次的**权威存储是 recall_counts.json**（见 _access_count_of 契约），
            # 文件侧自增正是「双写脱节」的病根：文件恒为 0 而热源有真值，
            # 下游三条治理链读文件 → 同时失效。现在改为**只写热源**（语义不变：
            # 一次反馈仍算一次使用；并尊重 frequency_tracking 开关）。
            _bump_recall_counts(root, [mid])
            m.setdefault("accessed_from", [])
            m["accessed_from"].append({"action": "feedback_%s" % outcome,
                                       "date": today(), "via": "recall_outcome"})
            if len(m["accessed_from"]) > 12:
                del m["accessed_from"][:len(m["accessed_from"]) - 12]
            _save_mem(root, mid, m)
        _entry = {
            "id": m.get("id"), "category": m.get("category", ""),
            "summary": m.get("summary", ""), "tags": m.get("tags", []),
            "tier": m.get("tier", "working"), "scope": m.get("scope", "universal"),
            "status": m.get("status", "active"), "relations": m.get("relations", {}),
            "version": m.get("version", 1), "file": fp,
        # #2 修复：补回审计字段，让 agent 不必再读盘即可审计触发来源/次数
            "recorded_by": m.get("recorded_by", "agent"),
        # P0 升级：surface deposit --why 决策理由，便于复盘回溯推理链
            "reason": m.get("reason"),
            "access_count": _access_count_of(root, mid, m),
            "importance": m.get("importance"),
            "accessed_from": m.get("accessed_from", []),
        # F1 修复：召回返回正文，闭合"AI 消费记忆"链路（不必再额外读文件）
            "body": m.get("body", ""),
            "confidence": m.get("confidence", 1.0),
            "conf_alpha": m.get("conf_alpha"), "conf_beta": m.get("conf_beta"),
            "auto_sourced": m.get("auto_sourced", False),
        # P2：暴露 deposit 时落库的 embedding 后端标签（该条向量「由谁生成」的事实，保持后向兼容）
            "embedding_status": m.get("embedding_status"),
        # 数据模型字段（Phase 1）
            "type": m.get("type", ""), "settled": m.get("settled", False),
            "thermal": m.get("thermal", "warm"),
        # ：补回 subdomain/scene，使单条召回与列表召回字段一致（投资等细分子域/场景可被消费）
            "subdomain": m.get("subdomain"), "scene": m.get("scene"),
            "scene_confidence": m.get("scene_confidence"),
            "scene_via": m.get("scene_via"),
        # P0（3.9.x）：暴露结构化指标，供调用方按数值消费
            "attrs": m.get("attrs") or {},
        }
        # B1 修复：按 id 召回不触发 embed（热路径成本/自动安装风险），故默认返回落库标签即可；
        # 仅当显式 with_meta=True 时，附带「进程内真实后端状态」诊断（loaded/degraded/unprobed）。
        # 注意：不在此强制 probe（backend_info() 可能触发 pip 自动安装，最长 420s 卡死），
        # 只读已探测的 _NEURAL 真实态；未探测则诚实标 unprobed，绝不用配置值冒充 live。
        if with_meta:
            try:
                _neural = _emb._NEURAL
            except Exception:
                _neural = None
            _state = ("loaded" if isinstance(_neural, tuple)
                      else ("degraded" if _neural is False else "unprobed"))
            _bk = _emb._backend_id()
            return {"results": [_entry], "meta": {
                "backend": _bk,
                "backend_state": _state,
                "fell_back_to_lexical": (_neural is False),
                "count": 1}}
        return [_entry]
        # P1-5：recall 结果缓存（仅无副作用的调用缓存）
        # 5.0/A3：as_of 回溯查询**不进缓存**——缓存键是按「当前库状态」编的，而 as_of 结果
        # 取决于历史时点，两者语义不同；若共用键会串缓存（2026-09-16 实测：as_of 查询
        # 返回了普通查询的缓存结果，把「该时点已失效」的记忆当成有效返回）。
    _can_cache = not (touch or outcome or include_superseded or with_meta or as_of)
    if _can_cache:
        # 5.0：**召回配置内容签名**进缓存键。
        # 原先键里只有 config.json 的 mtime，而 2026-09-16 实查发现两个真缺口：
        #   ① mtime 只取 root/config.json，但 _load_recall_config 是 store/config.json 优先
        #      （真库确实把 semantic_gate 写在 store/config.json）→ 改它不失效缓存；
        #   ② rerank_enabled/rerank_model/rerank_top/rerank_weight 这 4 项**根本不在键里**
        #      → 开关切换后仍命中旧缓存（B1 消融实验会被它污染）。
        # mtime 只能表达「文件被动过」，表达不了「内容是什么」；故再补一个内容签名。
        _rcfg = {}
        _cfg_sig = ""
        try:
            _rcfg = _load_recall_config(root)
            _cfg_sig = _recall_cache_cfg_sig(root)   # 单一来源，勿在此复刻哈希逻辑
        except Exception:
            pass
        # 5.0：`--filter` 子句也必须进缓存键 —— 原先不在键里，同 query 配不同 filter
        # 会互相返回对方结果（与 as_of 串缓存同类，2026-09-16 自查发现）。
        _flt_sig = ""
        if filter_clauses:
            try:
                _flt_sig = json.dumps(filter_clauses, sort_keys=True,
                                      ensure_ascii=False, default=str)
            except Exception:
                _flt_sig = str(filter_clauses)
        _ckey = _recall_cache_key(root, tag, category, query, tier, min_tier, scope, project, deep, domain, scene, subdomain, include_auto, about_axis, semantic_gate, _cfg_sig, _flt_sig)
        _ttl = RECALL_CACHE_TTL_DEFAULT
        try:
            _ttl = int(_rcfg.get("cache_ttl_seconds", RECALL_CACHE_TTL_DEFAULT))
        except Exception:
            pass
        _cached, _hit = _recall_cache_get(_ckey, _ttl)
        if _hit:
            return _cached
    data = load_index(root)
    # #5：标签查询走持久化倒排索引，免对全量 entries 逐一判断（规模大时线性下降）。
    # 仅「纯标签过滤、无语义 query」时启用；query 路径仍走 _rank_query（已复用落盘向量）。
    if tag and not query:
        try:
            cand = _inv_query(root, tag)
            if cand is not None:
                by_id = {e.get("id"): e for e in data["entries"] if isinstance(e, dict)}
                data = dict(data)
                data["entries"] = [by_id[i] for i in cand if i in by_id]
        except Exception:
            pass
    if min_tier and min_tier not in TIERS:
        raise ValueError("min_tier 必须是 %s 之一" % (TIERS,))
    if scope and scope not in SCOPES:
        raise ValueError("scope 必须是 %s 之一" % (SCOPES,))
        # 多轴 taxonomy scene 轴过滤（显式归一化，含 general 兜底）
    if scene is not None:
        scene = _normalize_scene(scene)
        if scene not in SCENE_CANON:
            raise ValueError("scene 必须是 %s 之一" % (SCENE_CANON,))
    min_lv = TIERS.index(min_tier) if min_tier else 0
    # 语义召回：query 时按「离线 embedding 余弦 + TF-IDF + 同义词子串」混合排序（O5 深度改写修复）
    ranked = None
    strong_ids = set()  # 默认空集：无 query 的 deep 召回（如按 category 找回归档）不会触发 _api.py:595 的 UnboundLocalError
    if query:
        ranked, strong_ids, raw_cos, why_map = _rank_query(root, query, include_superseded=include_superseded,
                            include_archived=deep, ann=ann,
                            cluster_boost=cluster_boost, as_of=as_of)
        # P1-3 离题绝对语义门控：神经/online 后端下，原始语义余弦 < 阈值且无强信号（子串/品牌）命中的
        # 条目一律剔除，避免离题 query 仍把无关记忆注入上下文。词法后端分布不同，自动关闭（_apply_gate=0）。
        _sg = semantic_gate
        if _sg is None:
            _sg = _load_recall_config(root).get("semantic_gate", 0.0)
        _bk = _emb._backend_id()
        _apply_gate = _sg if _bk not in ("lexical", "none", "") else 0.0
        if _apply_gate and _apply_gate > 0:
            ranked = {_mid: _sc for _mid, _sc in ranked.items()
                      if _mid in strong_ids or raw_cos.get(_mid, 0.0) >= _apply_gate}
    out = []
    # 🔴 5.0/A1 续修（第四处漏点）：`--filter` 的**记忆级数值字段**里，
    # `access_count` / `access` **不在 index entry 上**（真库 entry 字段实测无此键），
    # 而下面的 filter 判定发生在**后续 enrichment 补热源值之前** ⇒
    # `recall --filter "access_count>N"` 会**恒不匹配、静默返回空**（不报错）。
    # 这里只对 clauses 真正用到的「需外部取值」字段做按需补值，避免给每条候选加开销。
    # 已知限制（如实标注，未在此处改动）：同名单里的 `age_days` / `thermal_weight`
    # 同样不在 entry 上，需要各自的派生口径，本轮不动。
    _flt_hot_fields = set()
    if filter_clauses:
        try:
            _flt_hot_fields = {c.get("field") for c in filter_clauses
                               if isinstance(c, dict) and c.get("kind") == "num"} \
                              & {"access_count", "access"}
        except Exception:
            _flt_hot_fields = set()
    for e in data["entries"]:
        if not isinstance(e, dict):
            continue
            # （P5/B3）：staging 隔离开关——被动捕获(auto_sourced=true)默认不进 recall/inject，
            # 除非显式 --include-auto；避免未确认的暂存经验污染主召回链路（F11 周评审确认后才放行）。
        if not include_auto and e.get("auto_sourced"):
            continue
        # 5.0/A3：as_of 回溯查询按双时序判定（绕过 status）。见 _as_of_visible 注释。
        if as_of is not None:
            if not _as_of_visible(e, as_of):
                continue
        else:
            st = e.get("status")
            if st != "active" and not include_superseded:
                if not (deep and st == "archived"):
                    continue
        if tier and e.get("tier") != tier:
            continue
        if min_tier and TIERS.index(e.get("tier", "working")) < min_lv:
            continue
        if tag and tag not in e.get("tags", []):
            continue
        if category and e.get("category") != category:
            continue
            # 四轴硬过滤：about_axis 显式指定时，只返回匹配轴的记忆
            # （未标注轴的记忆视为「无轴」，被任何具体轴查询排除，避免串味/越权召回）
        if about_axis and normalize_about_axis(e.get("about_axis")) != normalize_about_axis(about_axis):
            continue
            # scene 轴硬过滤（与 domain 平行；零命中时 skip）
        if scene is not None and _normalize_scene(e.get("scene")) != scene:
            continue
            # subdomain 轴硬过滤（与 scene 平行；投资等细分子域精确召回）
        if subdomain is not None and e.get("subdomain") != subdomain:
            continue
            # P0（3.9.x）：数值/字符串过滤 DSL（--filter 解析后的 clauses）。
            # 列表路径 e 已含 index entry 镜像的 attrs，直接判；空 clauses 全通过。
            # 5.0/A1：热源字段（access_count/access）按需补值（见循环前注释）。
        if filter_clauses and _flt_hot_fields:
            e = dict(e)          # 不改原 entry（可能被索引缓存复用）
            _hv = _access_count_of(root, e.get("id"))
            e["access_count"] = _hv
            e["access"] = _hv
        if filter_clauses and not eval_filter(e, filter_clauses):
            continue
            # scope 收窄：project 过滤时恒带 universal（跨项目通用经验不丢失）
        if scope:
            if scope == "project":
                if e.get("scope") not in ("project", "universal"):
                    continue
            elif e.get("scope") != scope:
                continue
                # project 收窄：指定项目时，非该项目且非 universal 的记忆不返回
        if project and e.get("project") != project and e.get("scope") != "universal":
            continue
            # query 命中：子串（兼容旧行为）或 TF-IDF 语义命中
        if query:
            if ranked is not None:
                if e.get("id") not in ranked:
                    continue
            else:
                hay = (e.get("summary", "") + " " + e.get("body", "")).lower()
                if query.lower() not in hay:
                    continue
                    # 标记孤儿条目（index 指向的文件已不存在），避免调用方去加载幽灵
        fp = _resolve_path(root, e.get("id") or "")
        if not fp:
            e = dict(e)
            e["file_missing"] = True
        elif touch:
            # 显式 touch：刷新最后访问时间（读操作默认不写盘，避免「读副作用」），
            # 并记录「本次召回的上下文」作为访问证据（accessed_from），供 reflect 误分类检测。
            try:
                m, _ = _load_mem(root, e["id"])
                if m.get("status") == "active":
                    m["accessed"] = today()
                    # 🔴 5.0 修正：此处**不得**再计频次。本函数末尾有一段统一批量计数
                    #   （`_bump_recall_counts(root, [全部命中])`），覆盖的正是这里循环的同一个
                    #   out。上一版把原来的 `m["access_count"] += 1` 就地改成了 bump，
                    #   结果 `recall --touch` 会对每条命中**计数两次**（2026-09-16 自查发现）。
                    #   频次的唯一权威仍是 recall_counts.json，写入点收敛到末尾那一处。
                    # （访问证据 accessed_from / 复述加权 / thermal 重算仍属 touch 独有语义，
                    #   保留在此处并落盘。）
                    _apply_rehearsal_weight(m)  # v4.1.0（P3）：召回命中也复述加权
                    af = m.setdefault("accessed_from", [])
                    ctx = {"date": today()}
                    if project:
                        ctx["project"] = project
                        ctx["scope"] = "project"
                    elif scope:
                        ctx["scope"] = scope
                    af.append(ctx)
                    if len(af) > 12:          # 仅保留最近 12 条证据，避免无限增长
                        del af[:len(af) - 12]
                    _save_mem(root, e["id"], m)
            except Exception:
                pass
        out.append(e)
        # F1/F2 修复：列表路径（--query）补齐审计字段与关系字段，对齐 --id 单条路径。
        # 从文件加载 recorded_by/access_count/accessed_from/relations/version；
        # 文件缺失或异常时用安全默认值，不因单条失败阻断整批召回。
    _enriched = 0
    for e in out:
        if e.get("file_missing"):
            e.setdefault("recorded_by", "agent")
            e.setdefault("access_count", 0)
            e.setdefault("importance", None)
            e.setdefault("accessed_from", [])
            e.setdefault("relations", {})
            e.setdefault("version", 1)
            e.setdefault("body", "")
            e.setdefault("confidence", 1.0)
            e.setdefault("auto_sourced", False)
            e.setdefault("type", "")
            e.setdefault("secondary_types", [])
            e.setdefault("domain", None)
            e.setdefault("type_confidence", 1.0)
            e.setdefault("settled", False)
            e.setdefault("thermal", "warm")
            continue
        try:
            m, _ = _load_mem(root, e.get("id") or "")
            e["recorded_by"] = m.get("recorded_by", "agent")
            e["access_count"] = _access_count_of(root, e.get("id"), m)
            e["importance"] = m.get("importance")
            e["accessed_from"] = m.get("accessed_from", [])
            e["relations"] = m.get("relations", {})
            e["version"] = m.get("version", 1)
            e["body"] = m.get("body", "")
            e["confidence"] = m.get("confidence", 1.0)
            e["conf_alpha"] = m.get("conf_alpha")
            e["conf_beta"] = m.get("conf_beta")
            e["auto_sourced"] = m.get("auto_sourced", False)
            # 数据模型字段（Phase 1）：type/沉淀状态/冷热层随召回暴露，供路由使用
            e["type"] = m.get("type", "")
            # A1/A2/B1 分类置信度/次类型/域随召回暴露
            e["secondary_types"] = m.get("secondary_types", [])
            e["domain"] = m.get("domain")
            e["type_confidence"] = m.get("type_confidence", 1.0)
            e["settled"] = m.get("settled", False)
            e["thermal"] = m.get("thermal", "warm")
            # P0 升级：surface deposit --why 决策理由，便于复盘回溯推理链
            e["reason"] = m.get("reason")
            # P0（3.9.x）：暴露结构化指标，供调用方按数值消费
            e["attrs"] = m.get("attrs") or {}
            _enriched += 1
        except Exception:
            e.setdefault("recorded_by", "agent")
            e.setdefault("access_count", 0)
            e.setdefault("importance", None)
            e.setdefault("accessed_from", [])
            e.setdefault("type", "")
            e.setdefault("settled", False)
            e.setdefault("thermal", "warm")
            e.setdefault("relations", {})
            e.setdefault("version", 1)
            e.setdefault("body", "")
            e.setdefault("confidence", 1.0)
            e.setdefault("auto_sourced", False)
            e.setdefault("relations", {})
            e.setdefault("version", 1)
    if ranked is not None:
        # 5.0/B1：cross-encoder 重排（默认关闭，见 recall.rerank_enabled）。
        # 只调 RRF top-N 的内部顺序、不动其余候选；任何失败静默回退原序，
        # 故「开着」最差等于「没开」，不会把召回弄坏。
        if query:
            try:
                ranked = _rerank_apply(root, query, out, ranked)
            except Exception:
                pass
        out.sort(key=lambda e: ranked.get(e["id"], 0), reverse=True)
        # 修复：把召回分数写回 entry，让 AI/用户能自行过滤低分噪音
        for e in out:
            e["score"] = round(ranked.get(e["id"], 0.0), 4)
            # B4 ：召回可解释性——附 why 信号分解，用户能看懂"为啥这条排第一"
            if why_map and e.get("id") in why_map:
                e["why"] = why_map[e["id"]]
                # B5 ：召回频次统计（轻量、独立文件，不写记忆文件；可经 config recall.frequency_tracking 关）
        try:
            _bump_recall_counts(root, [e["id"] for e in out if e.get("id") in ranked])
        except Exception:
            pass
            # B1 域感知重排：domain 命中（同域）的记忆优先（稳定排序，同域内仍按语义分降序）
    if domain:
        out.sort(key=lambda e: 0 if (e.get("domain") == domain
                                     or domain in (e.get("tags") or [])) else 1)
        # #6 修复：跨 type 联想——query 召回后，若 top 结果缺少某些 type，
        # 从全库找共享标签的同主题记忆补入（标记 associated=True，低分追加），
        # 让 agent 看到「最佳实践 + 对应坑 + 相关流程」的全景而非单一 type。
    if query and len(out) >= 1:
        out = _cross_type_associate(root, data, out, scope, project, deep, include_superseded)
        # 回收豁免：仅当归档记忆被「显式按 id 召回」或「深度召回中直接命中（子串/品牌强信号）」时，
        # 才记录最近召回日使其免于被回收误删。松散语义/词重叠邻居不算「被召回」（否则一次宽泛深度召回
        # 会把整个归档区都标记为受保护，180 天沉淀策略失效、冷数据永不清理）。
    if deep:
        for e in out:
            if e.get("status") == "archived" and (e.get("id") == mid or e.get("id") in strong_ids):
                _mark_recalled(root, e.get("id"))
                # P0 升级：关系图谱扩跳（recall --hops N）。沿 related_to/supports/refutes
                # 把关联记忆加权追加到召回尾部，不破坏 RRF 主序。离线可用，无 LLM 依赖。
    if hops and hops > 0:
        try:
            from p0_upgrade import recall_expand_hops
            out = recall_expand_hops(root, out, hops=hops)
        except Exception:
            pass
            # P1-5：写入 recall 缓存（hops 扩跳结果不缓存，避免污染基准召回）
    if _can_cache and not hops:
        _recall_cache_set(_ckey, out)
        # ：注入预算控制——按 token 估算裁剪结果（保留最高分条目直到预算用尽）。
        # 裁剪在缓存写入之后，故缓存完整结果、返回裁剪视图，不污染缓存键。
    if max_tokens and max_tokens > 0:
        _used = 0
        _kept = []
        for _e in out:
            _t = token_estimate(_e)
            if _used + _t > max_tokens and _kept:
                break
            _used += _t
            _kept.append(_e)
        out = _kept
    if with_meta:
        # A：召回可观测性——把「实际生效后端 / 是否降级 / 空结果诊断」随结果回传，
        # 使 AI 在常规 recall 时即可感知语义降级，不必手动跑 doctor（B1 红线运行时闭环）。
        # 仅 with_meta=True 时改变返回形状（dict），其余调用方仍拿裸 list，零回归。
        try:
            _cfg_bk = (_load_keeper_config(root).get("embed_backend")
                       or "fastembed").lower()
        except Exception:
            _cfg_bk = "fastembed"
        _bk = _emb._backend_id()
        _fell = _cfg_bk in ("auto", "fastembed", "neural", "sentence_transformers") and _bk == "lexical"
        _meta = {"backend": _bk, "configured_backend": _cfg_bk,
                 "fell_back_to_lexical": _fell, "count": len(out)}
        if query and len(out) == 0:
            if _fell:
                _meta["empty_hint"] = ("语义后端已降级为词法级（召回率明显下降）。修复："
                                       "pip install fastembed，或设 AI_MEM_EMBED_BACKEND=online，"
                                       "或运行 `python mem_bridge.py doctor --fix` 自愈模型缓存。")
            else:
                _meta["empty_hint"] = ("当前后端(%s)下未命中相关记忆；可尝试换关键词、放宽语义门控，"
                                       "或确认记忆已 deposit。" % _bk)
        return {"results": out, "meta": _meta}
    return out
