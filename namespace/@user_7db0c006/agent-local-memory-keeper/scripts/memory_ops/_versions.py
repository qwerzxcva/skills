# Auto-extracted submodule: _versions
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _db_delete_entry(root, mid):
    conn = _db_conn(root)
    try:
        conn.execute("DELETE FROM entries WHERE id=?", (mid,))
        conn.execute("DELETE FROM embeddings WHERE id=?", (mid,))
        conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
        conn.commit()
    finally:
        conn.close()

def versions_dir(root):
    """版本快照目录（版本链 feature 用，独立于 memories/ 与 memories/archive/）。"""
    return os.path.join(root, "versions")

def _snapshot_version(root, mid, mem):
    """覆盖/回滚前把当前版完整快照到 versions/<mid>.v<ver>.json（已存在同版本则不覆盖）。

    原子写入避免半截文件。
    （at-rest 加密能力已于 2026-09-15 移除：快照一律明文落盘。）"""
    d = versions_dir(root)
    os.makedirs(d, exist_ok=True)
    ver = mem.get("version", 1)
    sp = os.path.join(d, "%s.v%s.json" % (mid, ver))
    if os.path.exists(sp):
        return sp
    tmp = sp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)
    os.replace(tmp, sp)  # 原子写入
    return sp

def _write_gate_enabled(root=None):
    """写入门禁开关：env KEEPER_WRITE_GATE > 配置 keeper.write_gate > 默认 True。

    默认**开**（fail-closed）：门禁拦不住的代价是"少写一次"，不设门禁的代价是
    "旧内容被覆盖且无快照、永久丢失"，二者不对称，故默认取保守侧。
    逃生通道：env KEEPER_WRITE_GATE=0（只读快照库 / CI 沙箱等确需绕过时用）。"""
    env = os.environ.get("KEEPER_WRITE_GATE")
    if env is not None and str(env).strip() != "":
        v = str(env).strip().lower()
        if v in ("0", "false", "no", "off", "n"):
            return False
        if v in ("1", "true", "yes", "on", "y"):
            return True
    try:
        v = memory_ops._load_keeper_config(root).get("write_gate")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on", "y")
        return bool(v)
    except Exception:
        return True  # 读不到配置 → 按最保守处理

def _gate_prewrite_snapshot(root, mid, fpath):
    """写入门禁：**覆盖前**确认「即将被覆盖的旧内容」已有版本快照；留不下快照就中止本次覆盖。

    为什么需要它（4.9.5）：4.9.3 把快照收口进写入真源，覆盖率 2%→100%，但快照发生在
    **写完之后**且异常被吞——一旦快照失败（磁盘满/权限/加密错），旧内容已被覆盖、永久丢失，
    而用户只看到一行 stderr 警告。这仍然是一条「没快照就覆盖」的路径。

    原则（与恒忆 commit_task 的写入门禁同一条）：快照 → 覆盖 → 记账，任一步失败即中止。
    本函数把顺序倒过来：先确认旧内容有快照，才允许覆盖。

    判定：
    · 文件不存在（新建）→ 没有旧内容可丢，直接放行；
    · 旧版本的快照文件已存在 → 旧内容已留底，放行；
    · 快照缺失 → 立即从磁盘旧内容补建；补建失败 → 抛 MemoryWriteGateError 中止写入。
    """
    if not os.path.exists(fpath):
        return None
    if not _write_gate_enabled(root):
        return None
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception as e:
        raise MemoryWriteGateError(
            "写入门禁中止：即将被覆盖的旧内容读不出来（%s）——读不出旧内容就绝不能覆盖。原因: %s"
            % (fpath, e))
    ver = (old or {}).get("version", 1)
    sp = os.path.join(versions_dir(root), "%s.v%s.json" % (mid, ver))
    if os.path.exists(sp):
        return sp  # 旧版本已留底 → 放行
    try:
        _snapshot_version(root, mid, old)
    except MemoryWriteGateError:
        raise
    except Exception as e:
        raise MemoryWriteGateError(
            "写入门禁中止：为旧版本 v%s 建立快照失败（%s）。已放弃本次覆盖，旧内容完好保留在 %s；"
            "确需绕过可设 KEEPER_WRITE_GATE=0。" % (ver, e, fpath))
    if not os.path.exists(sp):
        raise MemoryWriteGateError(
            "写入门禁中止：快照未落盘（%s），已放弃本次覆盖。" % sp)
    return sp

def timeline(root, mid=None, query=None, days=None, limit=20):
    """记忆时间线回放：按时间回放「单条记忆的演变」或「某主题的脉络」。

    - --id：版本链（versions 快照按时间）+ 当前版本 + 访问历史（accessed_from），
    附 relations 供看关联；复盘"这条结论怎么来的/被谁用过"。
    - --query：语义召回相关记忆按 created 时间排序（--days 限定最近 N 天），
    看某主题随时间积累的脉络。
    纯只读，不写盘。"""
    try:
        if mid:
            mem, fp = _load_mem(root, mid)
            events = []
            for v in _list_versions(root, mid):
                events.append({"date": v.get("updated", ""), "type": "version",
                               "version": v["version"],
                               "summary": (v.get("summary") or "")[:80]})
            events.append({"date": mem.get("updated") or mem.get("created", ""),
                           "type": "current", "version": mem.get("version", 1),
                           "summary": (mem.get("summary") or "")[:80]})
            for af in (mem.get("accessed_from") or [])[-limit:]:
                events.append({"date": af.get("date", ""),
                               "type": af.get("action", "access"),
                               "via": af.get("via", "")})
            events.sort(key=lambda e: e["date"] or "")
            return {"ok": True, "op": "timeline", "id": mid,
                    "summary": mem.get("summary", ""), "events": events[-limit:],
                    "relations": mem.get("relations", {}), "read_only": True}
        elif query:
            rel = memory_ops.recall(root, query=query, include_superseded=True, deep=True)
            evs = []
            for e in rel:
                try:
                    mm, _ = _load_mem(root, e.get("id") or "")
                    evs.append({"id": e.get("id"),
                                "date": mm.get("created") or "",
                                "summary": (mm.get("summary") or "")[:60],
                                "tier": mm.get("tier"), "status": mm.get("status")})
                except Exception:
                    continue
            evs.sort(key=lambda x: x["date"] or "")
            if days and days > 0:
                import datetime as _dt
                cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
                evs = [x for x in evs if (x["date"] or "") >= cutoff]
            return {"ok": True, "op": "timeline", "query": query,
                    "count": len(evs), "events": evs[:limit], "read_only": True}
            # 新增：recent 模式——不传 --id/--query 时，按时间回放最近 limit 条记忆
            # （纯只读；--days 可限定最近 N 天）。让 `timeline --limit 10` 单独可用，
            # 快速浏览"最近记了什么"，无需先知道某条 id 或主题词。
        else:
            data = load_index(root)
            evs = []
            for e in (data.get("entries") or []):
                if e.get("status") and e.get("status") != "active":
                    continue
                evs.append({"id": e.get("id"),
                            "date": e.get("created") or e.get("updated") or "",
                            "summary": (e.get("summary") or "")[:60],
                            "category": e.get("category", ""),
                            "tier": e.get("tier"), "status": e.get("status")})
            evs.sort(key=lambda x: x["date"] or "", reverse=True)
            if days and days > 0:
                import datetime as _dt
                cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
                evs = [x for x in evs if (x["date"] or "") >= cutoff]
            return {"ok": True, "op": "timeline", "mode": "recent",
                    "count": len(evs), "events": evs[:limit], "read_only": True}
    except Exception as e:
        return {"ok": False, "error": "timeline: %s" % e}

def _list_versions(root, mid):
    """列出某记忆的可用历史版本（versions/ 快照）。"""
    # 5.0.0：旧加密库 fail-closed 守卫。版本快照是**第三条独立读路径**（自带 open/json.load，
    # 既不经过 _load_mem/_all_mems，也不经过 load_index）。G1 覆盖面实跑实测：不守这里时
    # `versions --id` 会把快照里的 summary 当明文返回（rc=0）。
    assert_not_legacy_encrypted(root, op="读取历史版本 %s" % mid)
    d = versions_dir(root)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        m = re.match(r"^%s\.v(\d+)\.json$" % re.escape(mid), fn)
        if m:
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    v = json.load(f)
                out.append({"version": int(m.group(1)),
                             "updated": v.get("updated", ""),
                             "summary": v.get("summary", "")})
            except Exception as e:
                # P2 修复：不再静默返回空数据——版本文件损坏/解析失败时用户不知道哪个版本坏了。
                # 仍返回占位（保持列表完整），但记 stderr 让用户可定位修复。
                import sys as _sys
                _sys.stderr.write("[⚠ versions] 读取 %s 失败: %s\n" % (fn, e))
                out.append({"version": int(m.group(1)), "updated": "", "summary": ""})
    out.sort(key=lambda x: x["version"])
    return out

def versions(root, mid):
    """列出某记忆的可用历史版本（来自 versions/ 快照目录）。"""
    return _list_versions(root, mid)

@_with_deposit_lock
def rollback(root, mid, to_version, dry_run=False, yes=False):
    """真回滚：把记忆恢复到指定历史版本（versions/<mid>.v<to_version>.json）。
    回滚前先把当前版快照（回滚本身可撤销）；恢复后 version 单调 +1 并记 restored_from。
    E3 修复：快照失败不静默。E4 修复：全字段更新索引。"""
    # 5.0.0：旧加密库 fail-closed 守卫 —— 放在最前，使 `--dry-run` 预览也一并拒绝
    # （回滚是状态变更命令，在密文库上预览「恢复到哪个版本」同样没有意义且会误导）。
    assert_not_legacy_encrypted(root, op="回滚记忆 %s" % mid)
    sp = os.path.join(versions_dir(root), "%s.v%s.json" % (mid, to_version))
    if not os.path.exists(sp):
        raise FileNotFoundError(
            "版本快照不存在: %s\n  可用版本: %s\n  提示: 用 `versions --id %s` 查看。" %
            (sp, [v["version"] for v in _list_versions(root, mid)], mid))
    if dry_run:
        return {"dry_run": True, "op": "rollback", "id": mid,
                "to_version": to_version, "snapshot": sp}
    if not yes:
        _warn_destructive("rollback(回滚)", mid, sp,
                          "回滚会把记忆内容恢复到历史版本 %s（当前版会先快照到 versions/ 以便撤销）。" % to_version)
    cur, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    # E3 修复：快照失败不再静默吞——当前版无快照则回滚不可撤销，必须报错
    _snapshot_version(root, mid, cur)  # 当前版先快照，回滚可撤销
    with open(sp, encoding="utf-8") as f:
        old = json.load(f)
    old["id"] = mid
    old["version"] = cur.get("version", 1) + 1
    old["restored_from"] = to_version
    old["updated"] = today()
    old["accessed"] = today()
    old["status"] = "active"
    _save_mem(root, mid, old, expect_mtime=mtime)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            # E4 修复：全字段更新索引（此前只更新 summary/tags/tier/status/file）
            e["summary"] = old.get("summary", "")
            e["tags"] = old.get("tags", [])
            e["tier"] = old.get("tier", "working")
            e["status"] = "active"
            e["file"] = mid + ".json"
            e["category"] = old.get("category", e.get("category", ""))
            e["scope"] = old.get("scope", e.get("scope", "universal"))
            e["project"] = old.get("project", e.get("project", ""))
            e["importance"] = old.get("importance", e.get("importance", 0.5))
            e["confidence"] = old.get("confidence", e.get("confidence", 1.0))
    save_index(root, data)
    try:
        _persist_embed_and_inv(root, mid, old.get("summary", ""), old.get("body", ""), old["tags"])
    except Exception as e:
        import sys as _sys
        _sys.stderr.write("[⚠ rollback] 向量/倒排更新失败: %s（语义召回可能返回旧内容）\n" % e)
    return {"id": mid, "restored_to_version": to_version, "new_version": old["version"]}

@_with_deposit_lock
def overwrite(root, mid, summary=None, body=None, tags=None, tier=None,
              importance=None, dry_run=False, yes=False):
    if tier is not None and tier not in TIERS:
        raise ValueError("tier 必须是 %s 之一" % (TIERS,))
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    if dry_run:
        return {"dry_run": True, "op": "overwrite", "id": mid,
                "will_change": {"summary": summary is not None, "body": body is not None,
                                "tags": tags is not None, "tier": tier is not None},
                "file": fp}
    if not yes:
        _warn_destructive("overwrite(覆盖)", mid, fp,
                          "覆盖会改写该文件内容（version+1）。若想保留旧版请改用 archive 归档；"
                          "误覆盖可用文件历史/备份找回，或 recall 读取旧版摘要。")
        # D6 修复：被纠正版取代(superseded)的记忆不可直接覆盖复活——否则会与纠正记忆
        # 形成「两条互相矛盾的 active 记忆共存」，召回同时返回冲突结论。需更新请新建纠正
        # 记忆(deposit --corrects) 或先删旧链；归档(archived)记忆的覆盖复活仍允许（F6）。
    if mem.get("status") == "superseded":
        raise ValueError(
            "该记忆已被纠正版取代(superseded)，不可直接覆盖；如需更新请新建纠正记忆"
            "(deposit --corrects) 或先删除旧链")
    was_archived = mem.get("status") == "archived"
    # 版本链：覆盖前先把当前版（编辑前状态）快照到 versions/，供 rollback 真回滚
    # E3 修复：快照失败不再静默吞——旧版无快照则不可回滚，必须报错
    _snapshot_version(root, mid, mem)
    if summary is not None:
        mem["summary"] = summary
    if body is not None:
        mem["body"] = body
    if tags is not None:
        mem["tags"] = [t for t in re.split(r"[,\s]+", tags) if t] if isinstance(tags, str) else (tags or [])
    if tier is not None:
        mem["tier"] = tier
        # P0 品牌名诚实标注：summary/body 变化后刷新品牌检测
    if summary is not None or body is not None:
        mem["brand_mentions"] = _emb.extract_brands(" ".join([mem.get("summary", ""), mem.get("body", "")]))
    mem["updated"] = today()
    mem["version"] = mem.get("version", 1) + 1
    mem["accessed"] = today()
    # O1 修复：overwrite 显式更新记忆时，文件与索引状态必须一致（旧版只改索引不改文件，
    # 导致「文件 superseded / 索引 active」脱节）。显式复活为 active 即二者对齐。
    # 若目标是归档记忆，编辑即视为重新启用 → 自动从更深子记忆解除归档。
    mem["status"] = "active"
    if was_archived:
        mem["settled"] = False  # #9：从归档复活 → 需重新走沉淀/probe 流程
    _save_mem(root, mid, mem, expect_mtime=mtime)
    _tag_index_reset(root)  # 标签/状态可能变化，作废增量缓存
    if was_archived:
        old = os.path.join(archive_dir(root), mid + ".json")
        if os.path.exists(old):
            os.remove(old)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            if summary is not None:
                e["summary"] = summary
            if tags is not None:
                e["tags"] = mem["tags"]
            if tier is not None:
                e["tier"] = tier
            e["status"] = "active"
            e["file"] = mid + ".json"
    save_index(root, data)
    # 落盘索引层：overwrite 改了 body/summary/tags → 刷新向量 + 倒排
    try:
        _persist_embed_and_inv(root, mid, mem.get("summary", ""), mem.get("body", ""), mem["tags"])
    except Exception as e:
        import sys as _sys
        _sys.stderr.write("[⚠ overwrite] 向量/倒排更新失败: %s（语义召回可能返回旧内容）\n" % e)
    _audit_log(root, "overwrite", mid, {"version": mem.get("version", 1)})
    return mid

@_with_deposit_lock
def delete(root, mid, dry_run=False, yes=False):
    """C4 修复：delete 操作的各步骤失败不再静默——记录到 stderr，
    反向边清理失败时仍尝试完成索引/DB 清理，减少不一致窗口。"""
    # 5.0.0：旧加密库 fail-closed 守卫。**本函数是全库唯一直接 `os.remove` 记忆文件的地方**
    # （绕过 _save_mem/_write_mem），G2 副作用实跑实测曾出现「被拒的 delete 已经把文件删掉」。
    # 装饰器已有一道同样的守卫，这里再显式留一道：本函数的破坏性最强，
    # 且「写路径收口点」将来可能被重构 —— 就地设防是最不容易失效的位置。
    assert_not_legacy_encrypted(root, op="删除记忆 %s" % mid)
    fpath = _resolve_path(root, mid)
    if not fpath:
        raise FileNotFoundError(
            "记忆不存在，无法删除: %s（预期路径 %s）。\n"
            "  排查: 1) id 是否拼错？`recall` 不带 --id 可列出全部 id；\n"
            "        2) 是否已被 archive？加 --deep 再试；\n"
            "        3) index 脱节？运行 `rebuild` 重建索引后重试。"
            % (mid, os.path.join(mem_dir(root), mid + ".json")))
    if dry_run:
        return {"dry_run": True, "op": "delete", "id": mid, "file": fpath}
    if not yes:
        _warn_destructive("delete(删除)", mid, fpath,
                          "删除会**直接从磁盘移除**该 JSON 文件，无法靠本系统自我恢复。"
                          "若想保留请改用 archive（归档，可 --deep 召回）；误删可用系统/网盘文件历史找回，"
                          "或先 `recall --id %s` 把内容存一份再删。" % mid)
        # C4 修复：先收集所有需要修改的数据（in-memory），再统一提交
        # 沙箱安全删除守卫会拦截 os.remove → 回退 Win32 DeleteFileW 真删
        # （与 rolling-backup 同款兜底；仅在用户确认 --yes 后执行，安全语义不变）
    try:
        os.remove(fpath)
    except OSError:
        try:
            import ctypes
            if not ctypes.windll.kernel32.DeleteFileW(fpath):
                raise OSError("safe-delete 兜底仍失败: %s" % ctypes.FormatError())
        except Exception as e:
            raise OSError("无法删除记忆文件 %s: %s" % (fpath, e))
    _RESOLVE_PATH_CACHE.pop((root, mid), None)  # delete 绕过 _save_mem，独立清缓存
    _MTIME_CACHE.pop((root, mid), None)
    _recall_cache_clear(root)  # 物理删除后，确保召回不再返回已删记忆
    # 反向边清理：收集需要修改的记忆
    mems = _all_mems(root)
    to_fix = []
    for m in mems.values():
        rel = m.get("relations") or {}
        changed = False
        for key in ("related_to", "see_also"):
            lst = rel.get(key) or []
            if mid in lst:
                rel[key] = [x for x in lst if x != mid]
                changed = True
        for key in ("superseded_by", "corrected_by"):
            if rel.get(key) == mid:
                rel[key] = ""
                changed = True
        if changed:
            to_fix.append(m)
            # C4 修复：逐个保存反向边修改，失败记录但不中断后续步骤
    save_errors = []
    for m in to_fix:
        try:
            _save_mem(root, m["id"], m)
        except Exception as e:
            save_errors.append("%s: %s" % (m["id"], e))
    _tag_index_reset(root)  # 记忆被删，作废增量缓存
    data = load_index(root)
    data["entries"] = [e for e in data["entries"] if e.get("id") != mid]
    # 维护当日序号高水位：被删记忆的序号不参与降序，避免后续 deposit 复用被删 id
    try:
        _sm = re.match(r"LRN-(\d{8})-(\d+)$", mid)
        if _sm:
            _sd, _sq = _sm.group(1), int(_sm.group(2))
            _ss = _seq_load(root)
            _ss[_sd] = max(int(_ss.get(_sd) or 0), _sq)
            _seq_save(root, _ss)
    except Exception as _err:
        import sys as _sys
        _sys.stderr.write("[⚠ delete] 序号高水位落盘失败（可能复用已删 id；doctor --fix 可修复）：%s\n" % _err)
    save_index(root, data)
    try:
        _db_delete_entry(root, mid)  # 落盘索引层：移除 entry + 向量 + 倒排
    except Exception as e:
        import sys as _sys
        _sys.stderr.write("[⚠ delete] DB 清理失败: %s（建议运行 doctor --fix）\n" % e)
    if save_errors:
        import sys as _sys
        _sys.stderr.write("[⚠ delete] 反向边清理部分失败: %s（建议运行 doctor --fix）\n" % save_errors)
    _audit_log(root, "delete", mid)  # 删除后文件已不存在，仅记 id
    return True

