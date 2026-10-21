# memory_ops/_core.py
# F18 阶段2 批5(部分)：内存文件 IO + 进程内缓存子系统（原 __init__.py L3009-L3166 整段）。
# 内容：_load_mem/_save_mem（记忆文件读写，含路径穿越守卫 + 乐观并发冲突检测 + 原子替换）、
# 进程内读取缓存（_MEM_CACHE/_cache_key/_mem_cache_put/_mem_cache_get，mtime 新鲜度校验）、
# _all_mems（两目录全量加载为 dict）。
# 零行为变化：函数体逐字搬移；外部依赖（_resolve_path/_quarantine_corrupt_file/
# _recall_cache_clear/mem_dir/archive_dir/_MTIME_CACHE 等）由 __init__.py
# 在模块加载末期通过属性注入，避免循环 import。
import os
import json
import time

def _load_mem(root: str, mid: str):
    _assert_safe_mid(mid)  # 路径穿越守卫：阻断 --id ../x / --id C:/abs 读库外文件
    # 5.0.0：旧加密库 fail-closed 守卫 —— **必须在缓存快路径之前**。
    # G1 覆盖面实跑实测：命中进程内缓存时会直接 return，根本走不到下面读盘后的判定，
    # 于是「同一个库，第一次读被挡、第二次读漏过」（长驻 daemon 里就是必然漏）。
    # 故这里只做库级标志（1 次 stat），内容层由两条 return 路径各判一次（零额外 IO）。
    assert_not_legacy_encrypted(root, op="读取记忆 %s" % mid)
    # 优先走 _mem_cache_get（命中免去 open+json.load），不命中再读盘并回填。
    # 千条库 enrich 循环实测：从 ~1.9s（1000 次 open+json.load）降到 ~0.05s（全部命中缓存）。
    cached, fresh = _mem_cache_get(root, mid)
    if cached is not None and fresh:
        # 需要回填 fp：缓存条目里没有 fp，调一次 _resolve_path（已缓存，O(1)）
        fp = _resolve_path(root, mid)
        raise_if_legacy_ciphertext(root, cached, op="读取记忆 %s" % mid)
        return cached, (fp or "")
    fp = _resolve_path(root, mid)
    if not fp:
        raise FileNotFoundError(
            "记忆不存在: %s（已搜索 %s 与 %s 两处）。\n"
            "  排查: 1) id 是否拼错？用 `recall` 不带 --id 可列出全部记忆 id；\n"
            "        2) 是否已被 archive？加 --deep 再试；\n"
            "        3) index 与文件脱节？运行 `rebuild` 重建索引后重试。"
            % (mid, mem_dir(root), archive_dir(root)))
    with open(fp, encoding="utf-8") as f:
        m = json.load(f)
    # 5.0.0：内容层判定（标志层已在函数入口查过）——只嗅探已在内存的字段，零额外 IO。
    raise_if_legacy_ciphertext(root, m, op="读取记忆 %s" % mid)
    # 读盘后回填缓存（后续同进程 recall 即命中）
    try:
        mt = os.path.getmtime(fp)
        _MEM_CACHE[_cache_key(root, mid)] = (mt, m)
        _MTIME_CACHE[(root, mid)] = (mt, time.time())
    except OSError:
        pass
    return m, fp


def _save_mem(root: str, mid: str, mem: dict, expect_mtime=None) -> None:
    _assert_safe_mid(mid)  # 路径穿越守卫：阻断把记忆 JSON 写到库外/覆盖同名文件
    # 5.0.0：旧加密库 fail-closed 守卫（**写路径**）。为什么写也要挡：明文写进密文库 =
    # 混库；此后降级回 4.9.25 时其「明文写 fail-closed」会让整库读不出（详见 _legacy.py）。
    assert_not_legacy_encrypted(root, op="写入记忆 %s" % mid, mem=mem)
    # archived 记忆落到 archive 子目录；其余在 memories/ 根
    target_dir = archive_dir(root) if mem.get("status") == "archived" else mem_dir(root)
    # 自清理：状态切换（active<->archived / 被纠正 superseded 从 archive 复活）时，
    # 删除「另一目录」的同名副本，避免重复物理文件（FG1：deposit --corrects 指向已归档
    # 记忆时旧 archive 副本残留，导致 _all_mems 在冷缓存下返回错误版本）。
    other_dir = mem_dir(root) if target_dir == archive_dir(root) else archive_dir(root)
    other_path = os.path.join(other_dir, mid + ".json")
    if os.path.exists(other_path):
        try:
            os.remove(other_path)
        except OSError as _e:
            # 2026-09-15 审计：删不掉「另一目录」的旧副本会留下重复物理文件，而
            # _all_mems 冷缓存时可能返回错误版本（FG1 同族缺陷）。原先静默吞掉，
            # 用户无从知道库里有幽灵副本 → 留痕并提示 doctor --fix。
            import sys as _sys
            _sys.stderr.write(
                "[⚠ 存储] 清理另一目录旧副本失败（%s）：%s；建议跑 doctor --fix 检查一致性\n"
                % (other_path, _e))
            # 乐观并发守卫：同文件编辑时，若磁盘上的 mtime 比我们「读取时」更新（说明另一个
            # 进程/窗口已写入），拒绝静默覆盖，抛出可操作的冲突错误（而非互相吞掉修改）。
    if expect_mtime is not None:
        fpath_chk = os.path.join(target_dir, mid + ".json")
        if os.path.exists(fpath_chk):
            cur = os.path.getmtime(fpath_chk)
            if abs(cur - expect_mtime) > 1.0:  # 容忍亚秒级抖动
                raise MemoryConflictError(
                    "写入冲突：记忆 %s 在您读取后被另一个进程修改过"
                    "（磁盘 mtime %.3f 与您读取时的 %.3f 不一致）。\n"
                    "  已中止本次写入，避免两个窗口的修改互相覆盖。\n"
                    "  解决: 先用 `recall --id %s` 重新读取最新内容，合并您的修改后再写；"
                    "或运行 `doctor --fix` 检查一致性。" % (mid, cur, expect_mtime, mid))
    os.makedirs(target_dir, exist_ok=True)
    fpath = os.path.join(target_dir, mid + ".json")
    # ── 写入门禁（4.9.5，与恒忆 commit_task 同原则）──
    # 覆盖前必须确认「即将被覆盖的旧内容」已留下版本快照；留不下就中止，绝不出现
    # "没快照就覆盖" 的路径。4.9.3 的快照在写完之后且异常被吞 → 快照失败时旧内容已丢。
    # 门禁只做「补建缺失快照」这一件事：绝大多数写入（快照已存在/新建）零额外开销。
    memory_ops._gate_prewrite_snapshot(root, mid, fpath)
    tmp = "%s.%d.tmp" % (fpath, os.getpid())  # v4.9.2：带 pid，避免并发写同一记忆时两进程抢同一 .tmp
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fpath)  # 原子替换：写一半崩溃也只留下 .tmp，不会破坏正式文件
    except BaseException:
        # v4.9.2：写失败必须清掉临时文件。旧实现异常时留下 <id>.json.tmp 半成品，
        # 实测累积 346 个（每个都对应一次失败的自动捕获），既占空间又让目录看起来像有数据。
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    _mem_cache_put(root, mid, mem, fpath)  # 缓存明文 mem（与调用方视角一致）
    # invalidate 缓存：路径/状态变化后下次查询需重算（避免缓存陈旧导致幽灵文件返回）
    _RESOLVE_PATH_CACHE.pop((root, mid), None)
    _MTIME_CACHE.pop((root, mid), None)
    # 写盘即失效该 root 的召回缓存（覆盖「不更新索引但改召回结果」的写入，如 decay/touch/feedback）
    memory_ops._recall_cache_clear(root)
    # ── 存储一致性收口（根治 claim B 双写漂移）──
    # 旧架构：_save_mem 只写文件，索引同步靠每个 op 显式再调 save_index/_sync_index，
    # 任一调用点遗漏即导致 recall 漏过滤/误杀（静默无报错）。现在把「写文件即同步索引」
    # 收口进 _save_mem 本身（单一真源点），调用方无需记得手动同步。
    # 守卫：① touch/访问类写入（不碰过滤字段）跳过，避免 recall 触摸路径（_api 631）高频重建；
    # ② 索引库尚未建立（首次 deposit 前）跳过；③ 任何异常都吞掉，绝不阻断写文件主路径。
    try:
            if not mem.get("_no_index_sync"):
                memory_ops._sync_index_one(root, mid, mem)
    except Exception as _e:
        import sys as _sys
        _sys.stderr.write("[⚠ _save_mem] 索引增量同步失败(已忽略，主写入成功): %s\n" % _e)
    # ── 版本历史收口（根治版本覆盖率 2% 的架构缺口）──
    # 旧架构：_snapshot_version 只有 overwrite/rollback 两个**命令层**调用点，而 _save_mem 是
    # 真正的写入真源（~55 处调用 / 15 个模块），导致除显式 overwrite 外的一切修改都静默丢失
    # 历史——实测 147 条记忆仅 3 条有版本（覆盖率 2.0%），timeline/rollback 沦为空有命令无数据。
    # 现在把「写文件即留版本」收口进 _save_mem 本身，与已收口的 _sync_index_one 并列，
    # 复用 keeper 2026-08-12 根治索引双写漂移的同一手法（单一真源点，覆盖率 2%→100%）。
    # 语义：versions/<mid>.v<n>.json = 版本 n 的完整内容快照，供 timeline/rollback 回放。
    # 守卫：① _snapshot_version 内部对「同版本快照文件已存在」直接返回（幂等），故 touch/decay
    #   等高频写入（version 不变）不产生新文件、不增长磁盘；② 快照一律明文落盘
    #   （at-rest 加密能力已于 2026-09-15 移除）；③ 快照只写 versions/ 目录、不回调 _save_mem，无递归风险；
    #   ④ 任何异常一律吞掉，绝不阻断写文件主路径。
    try:
        memory_ops._snapshot_version(root, mid, mem)
    except Exception as _e:
        import sys as _sys
        _sys.stderr.write("[⚠ _save_mem] 版本快照失败(已忽略，主写入成功): %s\n" % _e)


    # ── 进程内记忆读取缓存（按 mtime 校验新鲜度；写盘即刷新）──
    # 目的：千条库 query 时避免重复冷读全部 JSON 文件（COLD _all_mems ~2.2s，
    # 缓存命中后 ~0.16s）。mtime 守卫保证外部改动/原子替换可被感知；delete 后
    # _resolve_path 找不到文件即失效。archive/unarchive 会删另一目录副本，无歧义。
_MEM_CACHE = {}  # (root_abs, mid) -> (mtime:float, mem:dict)


def _cache_key(root, mid):
    return (os.path.abspath(root), mid)


def _mem_cache_put(root, mid, mem, fpath=None):
    fp = fpath or _resolve_path(root, mid)
    if not fp:
        return
    try:
        mt = os.path.getmtime(fp)
    except OSError:
        mt = time.time()
    _MEM_CACHE[_cache_key(root, mid)] = (mt, mem)


def _mem_cache_get(root, mid):
    """返回 (mem, fresh)。fresh=True 表示命中且文件 mtime 未变。"""
    key = _cache_key(root, mid)
    cached = _MEM_CACHE.get(key)
    if cached is None:
        return None, False
    fp = _resolve_path(root, mid)
    if not fp:
        _MEM_CACHE.pop(key, None)
        return None, False
        # mtime 缓存：同 (root, mid) 在 _MTIME_TTL 内复用上次结果，避免 recall 千条库时
        # 每条都 os.path.getmtime 触 Windows 文件系统（实测 1000 次 getmtime ~1s）。
        # TTL 极短（默认 50ms），write 操作清 _MTIME_CACHE（写入路径极少），保证正确性。
    now = time.time()
    mt_cache_key = (root, mid)
    cached_mt = _MTIME_CACHE.get(mt_cache_key)
    if cached_mt is not None and (now - cached_mt[1]) < _MTIME_TTL:
        mt = cached_mt[0]
    else:
        try:
            mt = os.path.getmtime(fp)
        except OSError:
            _MEM_CACHE.pop(key, None)
            return None, False
        _MTIME_CACHE[mt_cache_key] = (mt, now)
    if cached[0] != mt:
        return None, False
    return cached[1], True


def _all_mems(root: str):
    """加载 memories/ 与 memories/archive/ 两处全部记忆文件为 dict(id->mem)。
    带进程内读取缓存：同进程内先 deposit/overwrite/touch 的记忆直接命中缓存，
    跳过冷盘读取（千条库 query 从 ~2.2s 降至 ~0.16s）。mtime 守卫保证一致性。"""
    out = {}
    for d in (mem_dir(root), archive_dir(root)):
        try:
            fns = sorted(os.listdir(d))
        except FileNotFoundError:
            continue
        for fn in fns:
            if not fn.endswith(".json"):
                continue
            mid = fn[:-5]
            cached, fresh = _mem_cache_get(root, mid)
            if fresh:
                if isinstance(cached, dict) and "id" in cached:
                    out[cached["id"]] = cached
                continue
            try:
                fpath = os.path.join(d, fn)
                with open(fpath, encoding="utf-8") as f:
                    mem = json.load(f)
                if isinstance(mem, dict) and "id" in mem:
                    out[mem["id"]] = mem
                    _mem_cache_put(root, mem["id"], mem, fpath)
            except (json.JSONDecodeError, UnicodeDecodeError):
                # O4 ：损坏文件不再静默丢——移入同级 corrupt/ 隔离区保留原文可恢复，
                # doctor 会汇总报告；移动失败（如只读存储）则退化为跳过，绝不崩溃。
                memory_ops._quarantine_corrupt_file(fpath)
                continue
    # 5.0.0：旧加密库 fail-closed 守卫（读路径的总闸）。零额外 IO —— 只嗅探已加载进
    # 内存的字段；库级标志（store/salt.bin 等）由同一函数检查。放在最后是为了让
    # 前面已发生的损坏隔离逻辑保持原状，从而**不改变任何非加密库的行为**。
    assert_not_legacy_encrypted(root, op="加载记忆库", mems=out)
    return out
