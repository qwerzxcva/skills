# Auto-extracted submodule: _lifecycle
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _move_to_dir(src, dst_dir, mid):
    """原子移动：把 src 文件 rename 到 dst_dir/(mid.json)。

    4.5.58 修复：不挂 @_with_deposit_lock——src 是文件路径而非库 root，
    装饰器会把 src 当 root 加锁导致锁路径无效（archive/unarchive 外层已加锁）。

    用于 archive/unarchive 的物理搬迁，替代"先写副本再 os.remove"两步法。
    os.replace(rename) 在沙箱守卫 / 文件被占用 / 权限不足下都远可靠于 os.remove，
    且移动是原子的——源消失的同时目标已就位，绝不会留下双份脏数据或状态不一致。
    仅在源文件存在时执行（已只在一处则跳过，幂等）。"""
    if not src or not os.path.exists(src):
        return
    os.makedirs(dst_dir, exist_ok=True)
    os.replace(src, os.path.join(dst_dir, mid + ".json"))

@_with_deposit_lock
def invalidate(root, mid, by=None, reason="", at=None, dry_run=False):
    """软失效（5.0 / A3 双时序）：把一条记忆标记为「自 at 起不再为真」，**不删除、不搬文件**。

    为什么要它（对齐 Graphiti 的 bi-temporal 模型）：
      · 既有 `status="superseded"` 只表达「被取代了」，**没有时间维度** ——
        无法回答「2026-08 那会儿这条经验还有效吗」这类回溯问题；
      · 而 reflect 的自动归档是「冷数据沉淀」，不是「结论被推翻」，两者混在一个
        status 上会互相掩盖。

    写入的双时序字段（写一次即长期可查）：
      · `valid_at`         —— 生效时点（缺省取 `created`，即一直有效）
      · `invalid_at`       —— 失效时点（**有值 = 已失效**，置位语义，随时可撤销）
      · `invalidated_by`   —— 被哪条记忆取代（可选；不传表示「只是不再为真」）
      · `invalid_reason`   —— 人类可读原因

    `status` 同步置为 `superseded`，从而复用既有召回过滤链（默认不召回、可
    `--include-superseded` 显式查看）——故本函数**不引入新的过滤分支**，兼容旧行为。
    回溯查询用 `recall --as-of <date>`（按 valid_at/invalid_at 判定，与 status 无关）。

    dry_run=True 只返回将要写入的内容，不落盘。
    """
    mem, fp = _load_mem(root, mid)
    _at = at or today()
    _valid = mem.get("valid_at") or mem.get("created") or _at
    plan = {"id": mid, "valid_at": _valid, "invalid_at": _at,
            "invalidated_by": by or "", "invalid_reason": reason or "",
            "status": "superseded", "from": fp}
    if dry_run:
        return {"dry_run": True, "op": "invalidate", **plan}

    mem["valid_at"] = _valid
    mem["invalid_at"] = _at
    if by:
        mem["invalidated_by"] = by
    if reason:
        mem["invalid_reason"] = reason
    mem["status"] = "superseded"
    mem["settled"] = False  # 失效即离开 active 集，沉淀标记随之失效
    # 图边：同时补一条 superseded_by（沿用既有关系词汇表，便于图分析/回溯）
    if by:
        try:
            rels = mem.setdefault("relations", {})
            if isinstance(rels, dict):
                tgt = rels.get("superseded_by")
                if tgt is None:
                    rels["superseded_by"] = by
                elif isinstance(tgt, list):
                    if by not in tgt:
                        tgt.append(by)
                elif tgt != by:
                    rels["superseded_by"] = [tgt, by]
        except Exception:
            pass
    af = mem.setdefault("accessed_from", [])
    af.append({"action": "invalidate", "date": _at,
               "by": by or "", "reason": reason or ""})
    if len(af) > 12:
        del af[:len(af) - 12]
    _save_mem(root, mid, mem)
    try:
        data = load_index(root)
        for e in data["entries"]:
            if e.get("id") == mid:
                e["status"] = "superseded"
                # 5.0/A3：双时序字段必须同步进索引 —— recall --as-of 在【索引-only 路径】
                # 直接读 entry 判可见性（_api.py），不同步 = 回溯查询把已失效条目当可见。
                e["valid_at"] = _valid
                e["invalid_at"] = _at
        save_index(root, data)
    except Exception as _err:
        import sys as _sys
        _sys.stderr.write("[⚠ invalidate] 索引同步失败（superseded/双时序字段可能滞后；doctor --fix 可修复）：%s\n" % _err)
        from _self_heal import mark_dirty_safe
        mark_dirty_safe(root, mid)
    return {"ok": True, "op": "invalidate", **plan}


def uninvalidate(root, mid, dry_run=False):
    """撤销软失效（A3）：清空 `invalid_at`/`invalidated_by`，`status` 回到 active。

    双时序字段保留历史（`valid_at` 不动），只把「是否已失效」这一位复位——
    这就是「置位不删」相对真删除的价值：误判可无损回滚。"""
    mem, fp = _load_mem(root, mid)
    if dry_run:
        return {"dry_run": True, "op": "uninvalidate", "id": mid,
                "had_invalid_at": mem.get("invalid_at"), "from": fp}
    had = mem.get("invalid_at")
    mem.pop("invalid_at", None)
    mem.pop("invalidated_by", None)
    mem.pop("invalid_reason", None)
    if mem.get("status") == "superseded":
        mem["status"] = "active"
    af = mem.setdefault("accessed_from", [])
    af.append({"action": "uninvalidate", "date": today(), "had_invalid_at": had})
    if len(af) > 12:
        del af[:len(af) - 12]
    _save_mem(root, mid, mem)
    try:
        data = load_index(root)
        for e in data["entries"]:
            if e.get("id") == mid and e.get("status") == "superseded":
                e["status"] = "active"
                # 5.0/A3：索引侧同步清失效位（valid_at 保留历史，与记忆文件一致）
                e.pop("invalid_at", None)
                if had:
                    e["valid_at"] = mem.get("valid_at")
        save_index(root, data)
    except Exception as _err:
        import sys as _sys
        _sys.stderr.write("[⚠ uninvalidate] 索引同步失败（active 状态可能滞后；doctor --fix 可修复）：%s\n" % _err)
        from _self_heal import mark_dirty_safe
        mark_dirty_safe(root, mid)
    return {"ok": True, "op": "uninvalidate", "id": mid, "had_invalid_at": had}


def archive(root, mid, dry_run=False, yes=False):
    """移到「更深子记忆」：物理搬迁到 memories/archive/ + 标 status=archived。
    与 delete 的区别：不销毁，只是沉到冷层，需要时 recall --deep 仍可自主读取。"""
    mem, fp = _load_mem(root, mid)
    if mem.get("status") == "archived":
        return mid
    if dry_run:
        return {"dry_run": True, "op": "archive", "id": mid,
                "from": fp, "to": os.path.join(archive_dir(root), mid + ".json")}
    if not yes:
        _warn_destructive("archive(归档)", mid, fp,
                          "归档会把文件从 memories/ 搬到 memories/archive/（沉到冷层），"
                          "不销毁；日后 `recall --deep` 仍可召回。若确定不再需要再用 delete。")
    mem["status"] = "archived"
    mem["archived_at"] = today()  # 回收计时起点：自归档日起算 180 天沉淀窗口
    mem["settled"] = False  # #9：归档离开 active 集 → settled 失效
    # 025 修复：先用 os.replace 原子移动（根→archive），根瞬间消失、绝不留双份；
    # 再 _save_mem 原子写回更新后的内容。彻底去掉原"先写副本再 os.remove"两步法——
    # os.remove 在沙箱/文件被占用/权限不足下会失败并造重复脏数据（LRN-20260723-025）。
    _move_to_dir(fp, archive_dir(root), mid)
    _save_mem(root, mid, mem)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            e["status"] = "archived"
            e["file"] = "archive/" + mid + ".json"
    _tag_index_reset(root)  # status 变化，作废增量缓存
    save_index(root, data)
    _audit_log(root, "archive", mid)
    return mid

@_with_deposit_lock
def unarchive(root, mid):
    """从更深子记忆解除归档：搬回 memories/ 根 + 标 status=active。"""
    mem, _ = _load_mem(root, mid)
    if mem.get("status") != "archived":
        return mid
    mem["status"] = "active"
    mem["settled"] = False  # #9：从归档复活 → 需重新走沉淀/probe 流程
    fp = _resolve_path(root, mid)  # 当前在 archive 目录
    # 025 修复：os.replace 原子移动（archive→根），根就位的同时 archive 副本消失，绝不留双份。
    _move_to_dir(fp, mem_dir(root), mid)
    _save_mem(root, mid, mem)  # 写回 mem_dir（status=active）
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            e["status"] = "active"
            e["file"] = mid + ".json"
    _tag_index_reset(root)  # status 变化，作废增量缓存
    save_index(root, data)
    _audit_log(root, "unarchive", mid)
    return mid

def _reclaim_state_path(root):
    return os.path.join(root, "store", "reclaim_state.json")

def _reclaim_load_state(root):
    """读取上一次回收运行持久化的候选集合（两次运行冷却的基准）。"""
    p = _reclaim_state_path(root)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("candidates"), list):
            return d
    except (OSError, ValueError):
        pass
    return None

def _reclaim_save_state(root, candidates):
    """把本次运行算出的候选持久化，供下一轮 --apply 做冷却校验。"""
    try:
        os.makedirs(os.path.join(root, "store"), exist_ok=True)
        with open(_reclaim_state_path(root), "w", encoding="utf-8") as f:
            json.dump({"candidates": list(candidates), "at": today()},
                      f, ensure_ascii=False)
    except OSError:
        pass

def archive_sweep(root, ttl_days=180, importance_floor=0.4,
                  quota_archived=300, quota_superseded=300,
                  protect_tags=("src:user", "pinned", "keep", "correction"),
                  max_archive=200,
                  include_staging=True, staging_ttl_days=365,
                  include_quarantine=False, quarantine_ttl_days=365,
                  mirror_ima=True,
                  dry_run=True):
    """归档清理框架（取代 4.x 已删除的 purge_forgotten，并与设计文档「回收治理」同源）：
    对「归档 / 被取代 / 暂存」三类做受控**归档**（软保留，绝不硬删）。

    ⚠️ 终态变更（v4.5.17 用户决策）：本函数**不再删除任何记忆**。原 180 天「自动删除」改为
    「自动归档 + 镜像到 IMA 知识库归档」——软删记忆本地沉到 archive/ 且永远保留，同时推到 IMA
    （带【归档】标记）作为跨设备/换机的可检索冷存储。「将来遇到了还能找到」。

    双模式：
    - 时间沉淀：归档/被取代记忆需 (距今-沉淀日 ≥ ttl) 且 (距今-最近召回日 ≥ ttl) 且 importance < floor
    → 候选（已归档/被取代项本就软保留，仅作「已保留」登记，不重复动作）。
    - 容量回收：某类数量超过配额时，最老的（按沉淀日）超配额部分列为候选——但**只归档尚未归档的
    活跃种子（暂存区）**，已归档项只报「数量偏大」不删除（守住「不丢」底线）。
    扩展作用域：
    - 暂存(auto_sourced)：默认清理——活跃库中 auto_sourced=True 且创建满 staging_ttl_days 仍未晋级的
    种子记忆，经相同重要性地板与保护规则后**归档**（不再留在活跃区制造噪音）。
    - 隔离(quarantine)：默认【不】参与自动归档（属安全缓冲，误归档真实记忆风险高）；即使显式
    include_quarantine 时，超时且未复审的隔离候选也只归入 protected（quarantine_manual，留人工
    决议），绝不自动归档/删除——隔离记忆多涉敏感标记，自动处置风险高，必须由人复核。
    保护（绝不归档/删）：核心层(core) / 含保护标签 / 带未过期 until: / 被活跃记忆 see_also 引用。
    安全闸：默认 dry_run=True 只报告；apply=True 才真归档（须经 --apply 显式触发，任何自动化不得
    跳过人工确认）。两次运行冷却对【全部作用域】统一生效——首轮 --apply 只落 cooldown_pending，防手滑。
    """
    mems = _all_mems(root)
    now = datetime.date.fromisoformat(today())

    def _days_since(d):
        if not d:
            return None
        try:
            if isinstance(d, str):
                d = datetime.date.fromisoformat(d[:10])
            return (now - d).days
        except Exception:
            return None

    archived_list, superseded_list = [], []
    referenced = set()
    for m in mems.values():
        st = m.get("status")
        if st == "archived":
            archived_list.append(m)
        elif st == "superseded":
            superseded_list.append(m)
        if st == "active":
            for t in (m.get("relations", {}).get("see_also") or []):
                referenced.add(t)

    def _is_protected(m):
        if m.get("tier") == "core":
            return "core"
        if any(t in protect_tags for t in (m.get("tags") or [])):
            return "protect_tag"
        for t in (m.get("tags") or []):
            if isinstance(t, str) and t.startswith("until:"):
                exp = t[6:].strip()
                try:
                    if len(exp) == 7 and exp[4] == "Q":
                        y, q = int(exp[:4]), int(exp[6:])
                        exp_dt = datetime.date(y, 12, 31) if q == 4 else datetime.date(y, q * 3, 1) - datetime.timedelta(days=1)
                    elif "." in exp:
                        exp_dt = datetime.date.fromisoformat(exp.replace(".", "-"))
                    else:
                        exp_dt = datetime.date.fromisoformat(exp)
                    if exp_dt >= now:
                        return "until_future"
                except Exception:
                    pass
        if m.get("id") in referenced:
            return "referenced"
        return None

        # 时间沉淀候选
    ttl_cands = []
    for m in archived_list:
        archived_at = m.get("archived_at") or m.get("updated") or m.get("created_at")
        last_recalled = m.get("last_recalled") or archived_at
        a_total = _days_since(archived_at)
        a_recall = _days_since(last_recalled)
        if a_total is None or a_total < ttl_days:
            continue
        if a_recall is not None and a_recall < ttl_days:
            continue  # 180 天内被深度召回过 → 豁免
        if (m.get("importance") or 0) >= importance_floor:
            continue
        ttl_cands.append(m)
    for m in superseded_list:
        sup_at = m.get("superseded_at") or m.get("updated") or m.get("created_at")
        a = _days_since(sup_at)
        if a is None or a < ttl_days:
            continue
        if (m.get("importance") or 0) >= importance_floor:
            continue
        ttl_cands.append(m)

        # 召回豁免集合：归档记忆若在 ttl 窗口内被深度召回过，视为仍被需要，
        # 时间沉淀与容量覆盖两种模式都不得删除它（守住"误删可救"安全网）。
    recall_exempt = set()
    for m in archived_list:
        lr = m.get("last_recalled")
        if lr is not None and _days_since(lr) is not None and _days_since(lr) < ttl_days:
            recall_exempt.add(m["id"])

            # 容量回收候选（最老的超配额部分；召回豁免的归档记忆不被容量覆盖）
    def _oldest_extra(lst, quota, exempt):
        def _sed(m):
            d = m.get("archived_at") if m.get("status") == "archived" else m.get("superseded_at")
            d = d or m.get("updated") or m.get("created_at")
            try:
                if isinstance(d, str):
                    d = datetime.date.fromisoformat(d[:10])
            except Exception:
                return datetime.date(2000, 1, 1)
                # 健壮性修复：记忆缺时间戳字段(archived_at/updated/created_at 皆空)时
                # d 为 None，原 `return d` 会让 sorted 比较 None<date 抛 TypeError。
                # 恒返回 date，缺值回退到远古日期（排序时排最前，仅影响容量回收候选顺序，不影响正确性）。
            return d if isinstance(d, datetime.date) else datetime.date(2000, 1, 1)
        pool = [m for m in lst if m["id"] not in exempt]
        ordered = sorted(pool, key=_sed)
        return ordered[:max(0, len(ordered) - quota)] if len(ordered) > quota else []

    cap_set = {m["id"]: m for m in (_oldest_extra(archived_list, quota_archived, recall_exempt)
                                    + _oldest_extra(superseded_list, quota_superseded, set()))}

    # 合并（ttl 候选 ∪ 容量候选）
    final = {}
    for m in ttl_cands:
        final[m["id"]] = m
    for mid, m in cap_set.items():
        final.setdefault(mid, m)

        # P1-1：扩展作用域——暂存(auto_sourced) 与 隔离(quarantine)。
        # 统一成候选列表，复用同一套保护规则 + 两次运行冷却（防止新作用域悄悄拆掉安全闸）。
    all_cands = [{"id": mid, "q": None, "m": m} for mid, m in final.items()]
    # 暂存：活跃库中 auto_sourced=True 且创建满 staging_ttl_days 仍未晋级的种子记忆
    if include_staging:
        for m in mems.values():
            if m.get("status") == "active" and m.get("auto_sourced") and not m.get("reviewed"):
                cd = m.get("created_at") or m.get("updated")
                if _days_since(cd) is not None and _days_since(cd) >= staging_ttl_days:
                    if (m.get("importance") or 0) >= importance_floor:
                        continue
                    all_cands.append({"id": m["id"], "q": None, "m": m})
                    # 隔离：超时且未复审的隔离候选（默认关，需 include_quarantine 显式开启）
    n_quarantine_cands = 0
    if include_quarantine:
        for rec in list_quarantine(root):
            if rec.get("reviewed"):
                continue
            cd = rec.get("created_at")
            if _days_since(cd) is not None and _days_since(cd) >= quarantine_ttl_days:
                qid = rec.get("id")
                if qid:
                    all_cands.append({"id": "q:" + qid, "q": qid, "m": None})
                    n_quarantine_cands += 1

                    # 两次运行冷却：--apply 时只归档「上一次运行已报告过」的候选，
                    # 首次出现的候选先报告、不归档，强制"先看报告再确认"，防手滑（对全作用域生效）。
                    # ⚠️ 终态：只归档（软保留），绝不 delete——已归档/被取代项本就软保留，仅登记「已保留」。
    prior = _reclaim_load_state(root)
    prior_set = set((prior or {}).get("candidates", []))
    candidates, protected, archived_now, already_soft, cooldown_pending = [], [], [], [], []
    for c in all_cands:
        cid = c["id"]
        m = c["m"]
        # 隔离区候选不参与自动归档（安全缓冲，留人工决议）
        if c["q"] is not None:
            protected.append({"id": cid, "reason": "quarantine_manual"})
            continue
        prot = _is_protected(m) if m is not None else None
        if prot:
            protected.append({"id": cid, "reason": prot})
            continue
        if len(archived_now) + len(already_soft) >= max_archive:
            protected.append({"id": cid, "reason": "max_archive_cap"})
            continue
        candidates.append(cid)
        if not dry_run:
            if cid in prior_set:
                try:
                    if m is not None and m.get("status") == "active":
                        # 暂存种子（活跃）→ 归档（沉到冷层，保留可召回，不再污染活跃区）
                        archive(root, cid, dry_run=False, yes=True)
                        archived_now.append(cid)
                    else:
                        # 已归档/被取代：本就软保留，仅登记「已保留」，不重复动作、不删除
                        already_soft.append(cid)
                except Exception as e:
                    protected.append({"id": cid, "reason": "archive_error:%s" % e})
            else:
                cooldown_pending.append(cid)

                # 每次运行都把本次候选持久化，作为下一轮 --apply 的冷却基准
    _reclaim_save_state(root, candidates)

    # apply 且有新归档 → 重新生成 IMA 导出（含归档项，归档项带【归档】标记）+ 打印推送指令
    mirrored = False
    if not dry_run and archived_now and mirror_ima:
        mirrored = _archive_mirror_ima(root)

    return {
        "mode": "DRY-RUN" if dry_run else "REAL",
        "ttl_days": ttl_days,
        "importance_floor": importance_floor,
        "quota_archived": quota_archived,
        "quota_superseded": quota_superseded,
        "include_staging": include_staging,
        "include_quarantine": include_quarantine,
        "candidates": candidates,
        "cooldown_pending": cooldown_pending,
        "protected": protected,
        "archived_now": archived_now,
        "already_soft": already_soft,
        "mirrored_to_ima": mirrored,
        "n_candidates": len(candidates),
        "n_cooldown_pending": len(cooldown_pending),
        "n_protected": len(protected),
        "n_archived_now": len(archived_now),
        "n_already_soft": len(already_soft),
    }

def _archive_mirror_ima(root):
    """重新生成 IMA 导出（含归档项，归档项在 _keeper_ima_push 里已打【归档】标记）。
    脚本不直接调 MCP（设计使然——create_media/add_knowledge 由 Agent 经 IMA MCP 执行）；
    返回是否导出成功，调用方负责把推送指令交给 Agent 完成云端入库。"""
    here = os.path.dirname(os.path.abspath(__file__))
    exporter = os.path.join(here, "_keeper_ima_push.py")
    if not os.path.exists(exporter):
        return False
    try:
        # v4.9.1：原为 shell=True + 字符串拼接（'"%s" "%s"'），路径含空格
        # （如 C:\Program Files\ 下的解释器、含空格的 skill 目录）时命令行被拆断
        # → IMA 导出静默失败（异常被下方 except 吞掉，表现为"导出了但没文件"）。
        # 改为 list 传参，由 subprocess 负责加引号。
        # 静默旗标：本模块可能被**钩子路径**（父进程是无控制台的 pythonw）调到，此时子进程若不显式
        # 指定 CREATE_NO_WINDOW 会被系统新开一个**可见**控制台（实测 hwnd≠0 且 IsWindowVisible=true）。
        # creationflags 为 Windows 专属，故按平台拼装，POSIX 不受影响。
        _pkw = {}
        if os.name == "nt":
            _pkw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        r = subprocess.run([sys.executable, exporter],
                            capture_output=True, timeout=300, **_pkw)
        return r.returncode == 0
    except Exception:
        return False

def _sha2gram(text):
    """中文友好的 2-gram 集合（无 NLP 依赖的主题重叠近似）。"""
    text = (text or "").strip()
    if len(text) < 2:
        return set()
    return set(text[i:i + 2] for i in range(len(text) - 1))

def _topics_overlap(a_tags, a_text, b_tags, b_text):
    """返回 0~1 的主题重叠度：标签交集优先，其次 2-gram Jaccard（近似「同主题」）。"""
    at = set(a_tags or [])
    bt = set(b_tags or [])
    if at and bt and (at & bt):
        return 1.0
    sa = _sha2gram(a_text)
    sb = _sha2gram(b_text)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

def archive_review(root, stale_days=365, overlap_thr=0.18):
    """归档复查：扫描已归档/被取代记忆，标注「是否已过时 / 是否有更优新方法替代」，供每周人工/自动化复核。
    返回 {reviewed, n_flagged, n_ok, flagged:[...], ok:[...]}。⚠️ 绝不自动删除——只产出可读报告。"""
    mems = _all_mems(root)
    archived = [m for m in mems.values() if m.get("status") in ("archived", "superseded")]
    active = [m for m in mems.values() if m.get("status") == "active"]
    flagged, ok = [], []
    for m in archived:
        mid = m.get("id")
        at = m.get("archived_at") or m.get("superseded_at") or m.get("updated") or m.get("created_at")
        idle = _days_since(m.get("last_recalled") or m.get("accessed") or at)
        arch_days = _days_since(at)
        # 找更优新方法：与活跃记忆主题重叠且内容更新（被取代项除外——它本身就是被新版取代的）
        better = None
        if m.get("status") != "superseded":
            best_score, best = 0.0, None
            for a in active:
                sc = _topics_overlap(m.get("tags", []),
                                     (m.get("summary") or "") + (m.get("body") or ""),
                                     a.get("tags", []),
                                     (a.get("summary") or "") + (a.get("body") or ""))
                if sc > best_score:
                    best_score, best = sc, a
            if best and best_score >= overlap_thr:
                better = {"id": best.get("id"),
                          "summary": (best.get("summary") or "")[:80],
                          "score": round(best_score, 3)}
        reasons = []
        if m.get("status") == "superseded":
            reasons.append("已被更优记忆取代（保留作血缘）")
        if idle is not None and idle >= stale_days:
            reasons.append("归档后超 %d 天未被召回（疑似过时）" % stale_days)
        if better:
            reasons.append("疑似有更优新方法：%s" % (better.get("summary") or better.get("id")))
        entry = {
            "id": mid,
            "status": m.get("status"),
            "summary": (m.get("summary") or "")[:80],
            "archived_days": arch_days,
            "idle_days": idle,
            "reasons": reasons,
        }
        if reasons:
            entry["better_method"] = better
            flagged.append(entry)
        else:
            ok.append(entry)
            # 严重度排序：有更优方法 > 过时 > 仅血缘
    def _sev(e):
        return (1 if e.get("better_method") else 0,
                1 if any("过时" in r for r in e["reasons"]) else 0)
    flagged.sort(key=_sev, reverse=True)
    return {"reviewed": len(archived), "n_flagged": len(flagged),
            "n_ok": len(ok), "flagged": flagged, "ok": ok}

@_with_deposit_lock
def promote(root, mid, tier):
    if tier not in TIERS:
        raise ValueError("tier 必须是 %s 之一" % (TIERS,))
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    mem["tier"] = tier
    _save_mem(root, mid, mem, expect_mtime=mtime)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            e["tier"] = tier
    save_index(root, data)
    return mid

@_with_deposit_lock
def confirm(root, mid, tier=None):
    """（P0）：staging「人工放行」——auto_sourced 暂存记忆确认入库。

    补齐 staging 机制缺失的晋级入口：promote 只改 tier 不清 auto_sourced，
    此前暂存记忆一旦被自动收割（workbuddy_sync/self_learn），无任何 op 能
    置 reviewed=True，只能等 reclaim 365 天 TTL 自动归档——用户确认过的
    长期偏好（如 WorkBuddy 画像同步）会被错误地踢出默认召回。

    confirm 做三件事：
    1. 置 reviewed=True（reclaim 的暂存清理豁免依据）；
    2. 清 auto_sourced（staging 隔离解除 → 进入默认召回）；
    3. 可选 --tier 顺带升级（如 seed→curated）。
    文件与 index entry 同步更新，保持 L0 硬过滤字段一致。
    """
    if tier is not None and tier not in TIERS:
        raise ValueError("tier 必须是 %s 之一" % (TIERS,))
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    was_staging = bool(mem.get("auto_sourced")) or not mem.get("reviewed")
    mem["reviewed"] = True
    mem["auto_sourced"] = False
    if tier:
        mem["tier"] = tier
    _save_mem(root, mid, mem, expect_mtime=mtime)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            e["auto_sourced"] = False
            if tier:
                e["tier"] = tier
    save_index(root, data)
    _audit_log(root, "confirm", mid, {"tier": mem.get("tier"),
                                      "was_staging": was_staging})
    return {"ok": True, "id": mid, "was_staging": was_staging,
            "tier": mem.get("tier"), "reviewed": True, "auto_sourced": False}

