# Auto-extracted submodule: _embed
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _emb_backend():
    try:
        return _emb.backend_info()
    except Exception:
        # P0 修复：语义后端（fastembed/online）加载失败时不再完全静默降级，
        # 发出一次性 stderr 告警，把"悄悄换成词法召回"变成"换且告知"，避免敏感用户察觉不到。
        # 进程内缓存标志防刷屏（deposit/recall 每次都调，重复告警会淹没真实错误）。
        _warned = getattr(_emb_backend, "_warned", False)
        if not _warned:
            _emb_backend._warned = True
            sys.stderr.write(
                "[keeper] ⚠️ 语义后端不可用，已降级为词法召回（召回质量下降）；"
                "要恢复真语义召回请安装 fastembed（pip install fastembed）"
                "或设 AI_MEM_EMBED_BACKEND=online。\n"
            )
        return "lexical"

def _emb_text_hash(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()

def _emb_store_put(root, mid, vec, text_hash=None, model=None):
    """持久化单条向量（增量 O(1)）。vec 为 list[float]。"""
    if text_hash is None:
        text_hash = _emb_text_hash(mid)
    if model is None:
        model = _emb_backend()
    conn = _db_conn(root)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO embeddings(id,vec,model,text_hash) VALUES (?,?,?,?)",
            (mid, json.dumps(vec, ensure_ascii=False), model, text_hash))
        conn.commit()
    finally:
        conn.close()

def _emb_store_put_many(root, items):
    """批量持久化向量：单连接单事务提交，避免千条量级逐条 commit/close 的 sqlite3 连接风暴。
    items: list[(mid, vec, text_hash, model)]。失败整体回滚（最坏情况保持原状）。
    单条调用方应捕获异常并 fallback 单条 _emb_store_put（行为兼容）。"""
    if not items:
        return
    conn = _db_conn(root)
    try:
        for mid, vec, text_hash, model in items:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings(id,vec,model,text_hash) VALUES (?,?,?,?)",
                (mid, json.dumps(vec, ensure_ascii=False), model, text_hash))
        conn.commit()
    finally:
        conn.close()

def _emb_store_get(root, mid):
    conn = _db_conn(root)
    try:
        cur = conn.execute("SELECT vec,model,text_hash FROM embeddings WHERE id=?", (mid,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"vec": json.loads(row[0]), "model": row[1], "text_hash": row[2]}

def _emb_store_load_all(root):
    """返回 {id: (vec, text_hash, model)}（全部持久化向量 + 文本哈希 + 落库后端），
    供 recall / ANN 一次加载。返回 hash 以便召回时校验新鲜度：文件被外部改写后向量自动失效重算；
    返回 model 以便检测「后端切换」：存量向量空间与当前查询后端不一致时必须重嵌，否则跨空间余弦塌缩（#O5-bug）。"""
    conn = _db_conn(root)
    try:
        cur = conn.execute("SELECT id, vec, text_hash, model FROM embeddings")
        return {r[0]: (json.loads(r[1]), r[2], r[3]) for r in cur.fetchall()}
    finally:
        conn.close()

def _backend_compatible(stored, cur):
    """判定落盘向量的 model 标识与当前后端是否同属一个向量空间（可直接比余弦）。

    为什么需要它：历史上「写入方」用 _model_fingerprint()（'backend:model#<size>.<mtime>'，
    带模型文件内容指纹），而「比对方」用 backend_info()（'backend:model'，不带指纹）。
    两者字符串永不相等 -> refresh 每次都误判为「后端切换」-> 每次全量重嵌且不落盘，
    永不收敛（实测 140/170 条被误判，每次 recall 额外 ~0.4s；缓存失效时更慢）。

    判定规则：剥掉 '#' 及其后的指纹后缀，比较 'backend:model' 前缀。
    真正的后端切换（lexical <-> fastembed:xxx、换模型名）前缀必然不同，仍会正确触发重嵌。

    职责分离：'模型文件是否被替换' 由磁盘缓存键 _bkey() = md5(fingerprint + text) 负责，
    embeddings.model 字段只应表达「这条向量属于哪个向量空间」，不掺文件指纹。
    """
    if not stored or not cur:
        return False
    return str(stored).split("#", 1)[0] == str(cur).split("#", 1)[0]


def _emb_store_refresh_backend(root, store):
    """就地把 store（来自 _emb_store_load_all）中 model 与当前后端不一致的向量，
    重嵌为当前后端向量。仅「后端切换后」偶发触发，常态无任何开销。避免不同向量空间的
    记忆被混在一起算相似度（ANN 近邻错乱 / 聚类串味，#O5-bug 同类根因）。"""
    try:
        cur = _emb_backend()
        if any(not _backend_compatible(v[2], cur) for v in store.values()):
            mems = _all_mems(root)
            for _mid, (_vec, _th, _mdl) in list(store.items()):
                if not _backend_compatible(_mdl, cur):
                    _m = mems.get(_mid)
                    if _m:
                        _text = " ".join([_m.get("summary", ""), _m.get("body", ""),
                                          " ".join(_m.get("tags", []))])
                        store[_mid] = (_emb.embed(_text), _th, cur)
    except Exception:
        pass
    return store

def _inv_upsert(root, mid, tags):
    conn = _db_conn(root)
    try:
        conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
        for t in (tags or []):
            conn.execute("INSERT OR IGNORE INTO inverted(tag,id) VALUES (?,?)", (t, mid))
        conn.commit()
    finally:
        conn.close()

def _inv_delete(root, mid):
    conn = _db_conn(root)
    try:
        conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
        conn.commit()
    finally:
        conn.close()

def _inv_query(root, tag):
    """从持久化倒排索引取带某标签的记忆 id 列表（#5：标签查询免全表扫 entries）。
    失败/表不存在返回 None，调用方回退到普通 entries 遍历。"""
    try:
        conn = _db_conn(root)
        try:
            cur = conn.execute("SELECT id FROM inverted WHERE tag=?", (tag,))
            return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        return None

def _ann_state_path(root):
    return os.path.join(root, "store", "ann.state.json")

def _ann_hnsw_path(root):
    return os.path.join(root, "store", "ann.idx")

def _ann_npy_path(root):
    return os.path.join(root, "store", "ann.emb.npy")

def _ann_ids_path(root):
    return os.path.join(root, "store", "ann.ids.json")

def _ann_digest(root):
    """基于 embeddings 表（id + text_hash + model）算一个稳定指纹，检测 ANN 索引是否过期。
    记忆增删改或「后端切换」→ 指纹变 → 落盘索引自动失效重建（无需手动删）。
    纳入 model 是关键修复：否则切换神经后端后旧空间向量仍被 ANN 复用，近邻候选错乱（#O5-bug）。"""
    try:
        conn = _db_conn(root)
        try:
            cur = conn.execute("SELECT id, text_hash, model FROM embeddings ORDER BY id")
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return ""
    h = hashlib.sha256()
    for r in rows:
        h.update(("%s|%s|%s\n" % (r[0], r[1], r[2])).encode("utf-8"))
    return h.hexdigest()

def _ann_invalidate(root):
    """作废一切落盘 ANN 索引文件（rebuild 后调用，避免残留过期索引）。"""
    for p in (_ann_hnsw_path(root), _ann_npy_path(root),
              _ann_ids_path(root), _ann_state_path(root)):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception as _e:
            # ：删除失败不再静默吞（沙箱 safe-delete / 文件占用都会触发）。
            # 残留旧索引无脏召回风险（_ann_load_numpy 有 digest 校验兜底），
            # 但显式告警便于排查；下轮 recall --ann 会走 digest 不匹配 → 重建。
            sys.stderr.write("[keeper] 警告: 删除 ANN 索引文件失败 %s: %s\n"
                             % (p, _e))

def _ann_try_incremental(root, store, digest):
    """ 改进 P0-4：尝试增量更新 ANN 索引（add_items + mark_deleted）。

    原问题：任何 deposit/delete 都使 _ann_digest 变化 → 全量重建索引。
    大库（1000+条）每次 deposit 一条就要全量重建 HNSW/numpy 索引，O(n) 开销浪费。

    做法：读取已落盘索引的 ID 列表，与当前 embeddings 表对比：
    - to_add = 新增的 ID（deposit 后新嵌入的）
    - to_remove = 消失的 ID（delete/archive 后从 embeddings 表删除的）
    - 若 len(to_add)+len(to_remove) ≤ ANN_INCREMENTAL_THRESHOLD × total → 增量更新
    - 否则返回 None，调用方走全量重建

    支持 hnswlib（add_items + mark_deleted）和 numpy（append + filter）两种后端。
    返回 (ids, data, backend) 成功；None 表示需全量重建。
    """
    try:
        import numpy as _np
    except Exception:
        return None

    stpath = _ann_state_path(root)
    idsf = _ann_ids_path(root)
    if not (os.path.exists(stpath) and os.path.exists(idsf)):
        return None

    try:
        with open(stpath, encoding="utf-8") as f:
            st = json.load(f)
        with open(idsf, encoding="utf-8") as f:
            old_ids = json.load(f)
    except Exception:
        return None

    cur_ids = set(store.keys())
    old_set = set(old_ids)
    to_add = cur_ids - old_set
    to_remove = old_set - cur_ids
    total = len(cur_ids) | len(old_set)
    n_changes = len(to_add) + len(to_remove)

    # 变更量超过阈值 → 全量重建
    if total > 0 and n_changes / total > ANN_INCREMENTAL_THRESHOLD:
        return None
        # 无变更（理论上 digest 已匹配不会走到这，但防御性检查）
    if n_changes == 0:
        return None

    backend = st.get("backend", "numpy")

    # ── hnswlib 增量 ──
    if backend == "hnsw":
        try:
            import hnswlib as _hnsw
            hpath = _ann_hnsw_path(root)
            dim = st.get("dim", 0)
            if dim == 0 and old_ids:
                dim = len(store[old_ids[0]][0]) if old_ids[0] in store else 0
            if dim == 0:
                return None
            idx = _hnsw.Index(space="cosine", dim=dim)
            idx.load_index(hpath, allow_replace_deleted=True)
            # 旧 ID → HNSW label 映射（label = 在 old_ids 中的 index）
            old_label_map = {mid: i for i, mid in enumerate(old_ids)}

            # mark_deleted
            for mid in to_remove:
                lbl = old_label_map.get(mid)
                if lbl is not None:
                    try:
                        idx.mark_deleted(lbl)
                    except Exception:
                        pass

                        # add_items（新 ID 用后续 label）
            new_ids_sorted = sorted(to_add)
            if new_ids_sorted:
                new_data = _np.array(
                    [store[mid][0] for mid in new_ids_sorted if mid in store],
                    dtype=_np.float32)
                next_label = len(old_ids)
                new_labels = _np.arange(next_label, next_label + len(new_data))
                idx.add_items(new_data, new_labels)

            idx.save_index(hpath)
            # 更新 IDs 列表：保留未被删的旧 ID + 新增 ID
            updated_ids = [mid for mid in old_ids if mid not in to_remove] + new_ids_sorted
            with open(idsf, "w", encoding="utf-8") as f:
                json.dump(updated_ids, f)
            with open(stpath, "w", encoding="utf-8") as f:
                json.dump({"digest": digest, "n": len(updated_ids),
                           "backend": "hnsw", "dim": dim}, f)
                # 返回供查询用的 ids + dummy data（hnsw 路径直接用 idx 查询，data 不需要）
            return updated_ids, None, "hnsw"
        except Exception:
            return None  # 增量失败 → 全量重建

            # ── numpy 增量 ──
    try:
        npy = _ann_npy_path(root)
        data = _np.load(npy)
        # 保留未被删的行
        keep_mask = [mid not in to_remove for mid in old_ids]
        keep_ids = [mid for mid in old_ids if mid not in to_remove]
        keep_data = data[keep_mask] if any(keep_mask) else _np.zeros((0, data.shape[1]), dtype=_np.float32)

        # 追加新行
        new_ids_sorted = sorted(to_add)
        if new_ids_sorted:
            new_data = _np.array(
                [store[mid][0] for mid in new_ids_sorted if mid in store],
                dtype=_np.float32)
            if len(new_data) > 0:
                if len(keep_data) > 0:
                    combined = _np.vstack([keep_data, new_data])
                else:
                    combined = new_data
            else:
                combined = keep_data
        else:
            combined = keep_data

        updated_ids = keep_ids + new_ids_sorted
        with open(npy, "wb") as f:
            _np.save(f, combined)
        with open(idsf, "w", encoding="utf-8") as f:
            json.dump(updated_ids, f)
        with open(stpath, "w", encoding="utf-8") as f:
            json.dump({"digest": digest, "n": len(updated_ids),
                       "backend": "numpy", "dim": int(combined.shape[1])}, f)
        return updated_ids, combined, "numpy"
    except Exception:
        return None

def _ann_build_numpy(root, store, digest):
    import numpy as _np
    ids = list(store.keys())
    data = _np.array([store[i][0] for i in ids], dtype=_np.float32)
    with open(_ann_npy_path(root), "wb") as f:
        _np.save(f, data)
    with open(_ann_ids_path(root), "w", encoding="utf-8") as f:
        json.dump(ids, f)
    with open(_ann_state_path(root), "w", encoding="utf-8") as f:
        json.dump({"digest": digest, "n": len(ids),
                   "backend": "numpy", "dim": int(data.shape[1])}, f)
    return ids, data

def _ann_load_numpy(root):
    npy, idsf, stf = _ann_npy_path(root), _ann_ids_path(root), _ann_state_path(root)
    if not (os.path.exists(npy) and os.path.exists(idsf) and os.path.exists(stf)):
        return None
    try:
        import numpy as _np
        with open(stf, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("digest") != _ann_digest(root):
            return None
        data = _np.load(npy)
        with open(idsf, encoding="utf-8") as f:
            ids = json.load(f)
        return ids, data
    except Exception:
        return None

def _ann_candidates(root, q_emb, k):
    """#7 可选 ANN 近邻候选生成（索引**持久化**到磁盘，避免每次 recall 重建）。

    后端无关设计：
    - 若装了 hnswlib+numpy → 优先用 hnswlib，索引落盘 `store/ann.idx`（加速版）；
    - 否则回退 numpy 持久化索引（`store/ann.emb.npy` + ids + state），同样落盘复用；
    两者都用 `_ann_digest`（embeddings 表指纹）检测数据变更 → 自动失效重建。
    库 <AI_MEM_ANN_MIN_MEMORIES（默认 50）条或任何异常 → 返回 (None, False)，调用方回退全量线性扫描，结果不变。
    recall 现默认自动启用（库≥ann_min 时）；中小库安全 k 全覆盖、结果与全量一致；仅大库近邻剪枝加速。"""
    try:
        import numpy as _np
    except Exception:
        return None, False
    try:
        store = _emb_store_load_all(root)
    except Exception:
        return None, False
    ann_min = _load_keeper_config(root)["ann_min_memories"]
    if len(store) < ann_min:
        return None, False
    digest = _ann_digest(root)
    # #O5-bug 修复：后端切换后落盘向量可能是旧空间（如 lexical），直接建 ANN 索引会导致近邻错乱。
    # 建索引前把 model 不匹配当前后端的向量就地重嵌为当前后端向量（仅重建时偶发，不影响常态性能）。
    store = _emb_store_refresh_backend(root, store)
    # 1) hnswlib 加速后端（可选）：优先复用落盘索引，否则建好落盘
    try:
        import hnswlib as _hnsw
        ids = list(store.keys())
        dim = len(store[ids[0]][0])
        hpath, stpath = _ann_hnsw_path(root), _ann_state_path(root)
        idsf = _ann_ids_path(root)
        if os.path.exists(hpath) and os.path.exists(stpath):
            with open(stpath, encoding="utf-8") as f:
                st = json.load(f)
            if st.get("digest") == digest and st.get("backend") == "hnsw":
                idx = _hnsw.Index(space="cosine", dim=dim)
                idx.load_index(hpath)
                idx.set_ef(min(512, max(k, 50)))
                qa = _np.array(q_emb, dtype=_np.float32)
                knn, _ = idx.knn_query(qa, k=min(k, len(ids)))
                return [ids[int(j)] for j in knn[0] if j >= 0], True
                # P0-4：digest 不匹配时先尝试增量更新
        _incr = _ann_try_incremental(root, store, digest)
        if _incr is not None and _incr[2] == "hnsw":
            # 增量更新成功 → 用更新后的索引查询
            _up_ids = _incr[0]
            idx = _hnsw.Index(space="cosine", dim=dim)
            idx.load_index(hpath)
            idx.set_ef(min(512, max(k, 50)))
            qa = _np.array(q_emb, dtype=_np.float32)
            knn, _ = idx.knn_query(qa, k=min(k, len(_up_ids)))
            return [_up_ids[int(j)] for j in knn[0] if j >= 0 and j < len(_up_ids)], True
            # 重建并落盘
        data = _np.array([store[i][0] for i in ids], dtype=_np.float32)
        idx = _hnsw.Index(space="cosine", dim=dim)
        idx.init_index(max_elements=len(ids), ef_construction=200, M=16)
        idx.set_num_threads(1)
        idx.add_items(data, _np.arange(len(ids)))
        idx.set_ef(min(512, max(k, 50)))
        idx.save_index(hpath)
        # P0-4：hnswlib 也保存 ID 列表，供增量更新对比
        with open(idsf, "w", encoding="utf-8") as f:
            json.dump(ids, f)
        with open(stpath, "w", encoding="utf-8") as f:
            json.dump({"digest": digest, "n": len(ids),
                       "backend": "hnsw", "dim": dim}, f)
        knn, _ = idx.knn_query(_np.array(q_emb, dtype=_np.float32), k=min(k, len(ids)))
        return [ids[int(j)] for j in knn[0] if j >= 0], True
    except Exception:
        pass  # hnswlib 不可用/失败 → 回退 numpy 持久化后端
        # 2) numpy 持久化后端（恒可用）：优先复用落盘索引，否则建好落盘
    loaded = _ann_load_numpy(root)
    if loaded is None:
        # P0-4：digest 不匹配时先尝试增量更新
        _incr_np = _ann_try_incremental(root, store, digest)
        if _incr_np is not None and _incr_np[2] == "numpy":
            ids, data = _incr_np[0], _incr_np[1]
        else:
            ids, data = _ann_build_numpy(root, store, digest)
    else:
        ids, data = loaded
    qa = _np.array(q_emb, dtype=_np.float32)
    qn = float(_np.linalg.norm(qa)) or 1e-9
    norms = _np.linalg.norm(data, axis=1)
    safe = _np.where(norms == 0, 1e-9, norms)
    sims = data.dot(qa) / (safe * qn)
    kk = min(k, len(ids))
    order = _np.argsort(-sims)[:kk]
    return [ids[int(j)] for j in order], True

def _persist_embed_and_inv(root, mid, summary, body, tags, text=None):
    """落盘索引层加速写入：持久化向量 + 倒排（单连接单事务，O(1) 增量）。单条模式用。
    recall 复用，免逐条 embed / 免全扫连边。合并为单连接避免每条 deposit 两次开合连接的开销。
    text: 可选，显式指定落向量文本 §6.2 用 render_cold 保语义质量）；缺则回退摘要拼接。"""
    if text is None:
        text = " ".join([summary or "", body or "", " ".join(tags or [])])
    vec = _emb.embed(text)
    model = _emb_backend()
    th = _emb_text_hash(text)
    conn = _db_conn(root)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT OR REPLACE INTO embeddings(id, vec, model, text_hash) VALUES (?,?,?,?)",
            (mid, json.dumps(vec, ensure_ascii=False), model, th))
        conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
        for t in (tags or []):
            conn.execute("INSERT OR IGNORE INTO inverted(tag, id) VALUES (?,?)", (t, mid))
        conn.commit()
    finally:
        conn.close()

def _persist_batch(root, items):
    """批量 deposit flush 用：向量+倒排**单连接单事务**落盘，消除逐条开合连接的开销（1000 条省 ~2000 次连接）。"""
    if not items:
        return
    model = _emb_backend()
    conn = _db_conn(root)
    try:
        emb_rows, inv_rows = [], []
        for it in items:
            if len(it) == 6:
                mid, summary, body, tags, typ, scope = it
            elif len(it) == 5:
                mid, summary, body, tags, typ = it
                scope = None
            else:
                mid, summary, body, tags = it
                typ = None
                scope = None
                # §6.2：落向量文本统一走 render_cold（完整叙述、语义最稳）
            text = _embed_text_for({"summary": summary or "", "body": body or "",
                                    "tags": tags or [], "type": typ or "FACT",
                                    "scope": scope or ""})
            emb_rows.append((mid, json.dumps(_emb.embed(text)), _emb_text_hash(text), model))
            for t in (tags or []):
                inv_rows.append((t, mid))
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT OR REPLACE INTO embeddings(id, vec, text_hash, model) VALUES(?,?,?,?)",
            emb_rows)
        if inv_rows:
            conn.executemany("INSERT OR IGNORE INTO inverted(tag, id) VALUES(?,?)", inv_rows)
        conn.commit()
    finally:
        conn.close()

def _ensure_embeddings(root, max_backfill=None):
    """为缺向量/文本变化的 entry 从文件回填（持久化）。rebuild/迁移后调用。

    返回 {"processed": 扫描条数, "embedded": 实际新写入/更新向量数}（A3: 供 doctor --fix 报告）。
    """
    mems = _all_mems(root)
    model = _emb_backend()
    done = 0
    written = 0
    for m in mems.values():
        if max_backfill is not None and done >= max_backfill:
            break
        mid = m.get("id")
        if not mid:
            continue
        text = _embed_text_for(m)
        h = _emb_text_hash(text)
        ex = _emb_store_get(root, mid)
        if not (ex and ex.get("text_hash") == h and ex.get("model") == model):
            vec = _emb.embed(text)
            _emb_store_put(root, mid, vec, text_hash=h, model=model)
            written += 1
        _inv_upsert(root, mid, m.get("tags", []))
        done += 1
    return {"processed": done, "embedded": written}

def _rebuild_index_db(root):
    """重建 SQLite 加速层（向量 + 倒排）从文件全量回填。rebuild 后调用。"""
    conn = _db_conn(root)
    try:
        conn.execute("DELETE FROM embeddings")
        conn.execute("DELETE FROM inverted")
        conn.commit()
    finally:
        conn.close()
    return _ensure_embeddings(root)

def _tag_index_reset(root: str) -> None:
    """作废某 store 的标签倒排缓存（写操作改变了索引结构/状态时调用）。"""
    _TAG_INDEX.pop(os.path.abspath(root), None)

def _tag_index_get(root: str, data: dict):
    """返回 (by_tag, by_id)。必要时按当前 data 全量重建；否则复用增量缓存。"""
    key = os.path.abspath(root)
    n = len(data.get("entries", []))
    c = _TAG_INDEX.get(key)
    if c is None or c.get("n") != n:
        by_tag, by_id = {}, {}
        for e in data.get("entries", []):
            if not isinstance(e, dict) or "id" not in e:
                continue
            by_id[e["id"]] = e
            for t in (e.get("tags", []) or []):
                by_tag.setdefault(t, []).append(e["id"])
        c = {"by_tag": by_tag, "by_id": by_id, "n": n}
        _TAG_INDEX[key] = c
    return c["by_tag"], c["by_id"]

def _tag_index_upsert(root: str, mid: str, tags, entry: dict) -> None:
    """增量把新记忆挂入标签倒排缓存（O(1)）。缓存缺失时下次 deposit 全量重建。"""
    c = _TAG_INDEX.get(os.path.abspath(root))
    if c is None:
        return
    c["by_id"][mid] = entry
    for t in (tags or []):
        if t not in c["by_tag"]:
            c["by_tag"][t] = [mid]
        elif mid not in c["by_tag"][t]:
            c["by_tag"][t].append(mid)
    c["n"] = c.get("n", 0) + 1

def _seq_path(root):
    return os.path.join(root, "store", "seq.json")

def _seq_load(root):
    """读取当日序号高水位（防复用被删 id）。独立文件，不依赖 index（load_index
    走 SQLite 权威源时会丢弃 data 上的附加字段，故 seq 不能挂在 data 上）。"""
    try:
        with open(_seq_path(root), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}

def _seq_save(root, state):
    try:
        os.makedirs(os.path.join(root, "store"), exist_ok=True)
        with open(_seq_path(root), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError as _e:
        # ：写失败不再静默——seq.json 是 id 高水位，写失败会导致 gen_id
        # 反复返回同一 id（同 id 覆盖丢记忆，跨进程并发时尤其致命）。
        sys.stderr.write("[keeper] 警告: 写入 seq.json 失败 %s: %s\n"
                         % (_seq_path(root), _e))

