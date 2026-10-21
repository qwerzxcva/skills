# memory_ops/_persistence.py
# F18 阶段2 批4：持久化层独立子模块（原 __init__.py L1618-L2022 整簇）。
# 内容：索引 IO（load_index/save_index/_flush_index_json/check_writable）、
# SQLite 权威源（_db_path/_db_checkpoint_truncate/_index_db_ensure/迁移）、
# 连接池代理（_ConnProxy/_db_conn/_db_upsert_entries/_db_load_entries_full/_db_close_all）。
# 零行为变化：函数体逐字搬移；外部依赖（today/_STATE_LOCK 等）由 __init__.py
# 在模块加载末期通过属性注入（见 __init__.py 的 _persistence 加载块），避免循环 import。
import os
import json
import sqlite3 as _sqlite3
import atexit as _atexit

def load_index(root: str) -> dict:
    """加载索引。 起 SQLite store/index.db 为权威源；index.json 为人类可读导出/兜底。
    若 SQLite 无数据且 index.json 存在，则自动迁移。
    C5 修复：SQLite 降级时记录 stderr 日志，不再完全静默。"""
    # 5.0.0：旧加密库 fail-closed 守卫。**索引镜像是第二份用户数据副本**：4.9.25 的
    # `_enc_index_entry` 把索引条目里的 summary 等一并加密，故「只读索引、不读记忆文件」  deadref-ok
    # 的路径同样会把密文当明文返回。G1 覆盖面实跑实测：不守这里时 `recall`（列表模式）
    # 与 `stats` 会输出密文摘要（rc=0，无异常无日志），是典型的静默乱码。
    assert_not_legacy_encrypted(root, op="加载索引")
    # 先确保 SQLite 库存在并完成迁移（_index_db_ensure 会回填 data 列）
    try:
        _index_db_ensure(root)
        entries = _db_load_entries_full(root)
        if entries:
            return {"version": 2, "updated": today(), "entries": entries}
    except Exception as e:
        # C5 修复：SQLite 降级时记录日志（不再完全静默）
        import sys as _sys
        _sys.stderr.write("[⚠ load_index] SQLite 不可用，降级到 index.json: %s\n" % e)
    # 回退：读 index.json（兼容 v1 及空库）
    p = os.path.join(root, "index.json")
    if not os.path.exists(p):
        return {"version": 2, "updated": today(), "entries": []}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise CorruptIndexError("index.json 解析失败: %s" % e)
    if not isinstance(data, dict):
        raise CorruptIndexError("index.json 顶层不是对象")
    data.setdefault("entries", [])
    if not isinstance(data["entries"], list):
        raise CorruptIndexError("entries 不是数组")
    data["version"] = 2
    return data


# F11：save_index SQLite 写失败计数 + 可选严格模式（KEEPER_SAVE_STRICT=1 时抛错让流水线感知）
_SAVE_INDEX_SQLITE_FAIL_COUNT = 0


def save_index(root: str, data: dict, full_replace: bool = False) -> None:
    """保存索引。 起先写 SQLite 权威源，再导出 index.json 供人类阅读/兜底。
    C1 修复：SQLite 写失败不再静默吞——记录错误到 stderr，让上层可感知。

    full_replace=True（v4.9.2）：先 `DELETE FROM entries` 再全量插入，用于
    rebuild 这类「磁盘文件才是事实源」的场景。
    必要性：默认的 scoped DELETE 只删本次传入的 id 集合，于是
    「索引里有、文件已不存在的陈旧条目（僵尸）」永远删不掉 —— 实测本库
    index 272 条 vs 文件 156 条，rebuild 后仍是 272（116 条僵尸纹丝不动）。
    """
    data["updated"] = today()
    data["version"] = 2
    entries = data.get("entries", [])
    # 1) 写 SQLite（含完整 JSON 与镜像列）；WAL 模式已启用，天然具备崩溃恢复
    sqlite_ok = True
    try:
        conn = _db_conn(root)
        try:
            # ：scoped DELETE（仅删本次要写的 id 集合），取代 unscoped `DELETE FROM entries`。
            # 当 save_index 被传入「部分 entries」（如 link/reclassify 单条目变更复用本函数）时，
            # 不会误删其他条目；全量重写时 id 集合 == 全量，行为与旧版一致，但锁窗口更小、更安全。
            # 这是「存储一致性收口」的一环：杜绝「整表清空再全量重插」的脆弱写法。
            if full_replace:
                # v4.9.2：全量重建场景——先清表，否则 scoped DELETE 删不掉僵尸条目
                conn.execute("DELETE FROM entries")
            else:
                _ids = [e.get("id") for e in entries if isinstance(e, dict) and e.get("id")]
                # 分批 DELETE，避免单条 IN (...) 超过 SQLite 默认 999 参数上限（大库全量重写时也安全）
                _CHUNK = 500
                for _i in range(0, len(_ids), _CHUNK):
                    _batch = _ids[_i:_i + _CHUNK]
                    _ph = ",".join("?" * len(_batch))
                    conn.execute("DELETE FROM entries WHERE id IN (%s)" % _ph, _batch)
            _db_upsert_entries(conn, entries, root)
            conn.execute("INSERT OR REPLACE INTO _db_meta(key,value) VALUES (?,?)",
                         ("last_save", today()))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        # C1 修复：SQLite 写失败不再静默——记录错误，继续写 index.json 兜底
        sqlite_ok = False
        global _SAVE_INDEX_SQLITE_FAIL_COUNT
        _SAVE_INDEX_SQLITE_FAIL_COUNT += 1
        import sys as _sys
        _sys.stderr.write("[⚠ save_index] SQLite 写失败(%d): %s（已降级写 index.json 兜底，"
                          "但权威源可能与文件不一致，建议运行 doctor --fix）\n"
                          % (_SAVE_INDEX_SQLITE_FAIL_COUNT, e))
        _log_struct("save_index_sqlite_fail", count=_SAVE_INDEX_SQLITE_FAIL_COUNT, err=str(e))
        if os.environ.get("KEEPER_SAVE_STRICT") == "1":
            raise
    # 2) 导出 index.json（人类可读 + 兜底）
    p = os.path.join(root, "index.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)  # 原子替换，避免半截文件


def _flush_index_json(root: str, data: dict) -> None:
    """仅重写 index.json 兜底导出（不触碰 SQLite）。用于 link 等单条目变更，避免全量重插。"""
    data = dict(data)
    data["updated"] = today()
    data["version"] = 2
    p = os.path.join(root, "index.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# F12：写前可写性探针。创建 root/store 目录并试写临时文件后删除；
# 失败返回 False（调用方据此 fail-closed），成功返回 True。不抛异常。
def check_writable(root: str) -> bool:
    try:
        d = os.path.join(os.path.abspath(root), "store")
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".keeper_writable_probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


# ── 落盘索引层 新增，P0； 升级为权威源）──
# 设计： 起 SQLite store/index.db 为**权威源**，承载「entries 完整 JSON + 持久化向量
# + 倒排」；index.json 保留为**人类可读导出 / 兜底**（SQLite 损坏时仍可恢复，旧版仅 index.json
# 的库首次打开自动迁移回填）。recall 主瓶颈（_rank_query 逐条 embed 的 O(n)）复用持久化向量
# → O(1) embed(query) + O(n) 点积。索引与向量均落盘、进程间共享，绕开进程内缓存失效。
# 与离线零依赖定位一致：仅用标准库 sqlite3，不联网、不装重模型；WAL 模式并发更稳，
# backup 前 wal_checkpoint(TRUNCATE) 保证单文件自包含。
def _db_path(root):
    return os.path.join(root, "store", "index.db")


def _db_checkpoint_truncate(root):
    """WAL 模式：把 -wal/-shm 中未落盘的数据强制 checkpoint 回主库文件（TRUNCATE）。
    
    备份前必须调用：否则 index.db 单文件备份会丢掉 WAL 中已提交但未 checkpoint
    的向量/倒排数据，restore 后语义召回出现「幽灵记忆」。仅标准库 sqlite3。"""
    p = _db_path(root)
    if not os.path.exists(p):
        return
    try:
        conn = _sqlite3.connect(p)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            conn.close()
    except _sqlite3.Error as _e:
        # 4.9.17（同族：不再完全静默）：备份前 checkpoint 失败时，-wal 中已提交但未落盘的
        # 向量/倒排会缺席单文件备份 → restore 后可能对不上（幽灵记忆）。此处仅**告警**，
        # 不阻断备份（主文件仍会尽力备份）——把「静默的不完整备份」变成「可见的风险」。
        import sys as _sys
        _sys.stderr.write(
            "[⚠ backup] WAL checkpoint(TRUNCATE) 失败，单文件备份可能不含最新数据"
            "（restore 后或出现幽灵记忆）：%s\n" % _e)


def _index_db_ensure(root):
    """确保 store/index.db 与表结构存在；首次建库且 index.json 有数据则导入镜像（含倒排）。
    
    v2.12.0 起 entries 表新增 data TEXT 列存储完整记忆 JSON，SQLite 升级为权威源；
    index.json 保留为人类可读导出/兜底。迁移时若 data 列全空，自动从 index.json 回填。"""
    p = _db_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = _sqlite3.connect(p)
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # 并发更稳（#5）
        conn.execute("""CREATE TABLE IF NOT EXISTS entries(
            id TEXT PRIMARY KEY, category TEXT, summary TEXT, body TEXT,
            tags TEXT, tier TEXT, status TEXT, scope TEXT, project TEXT,
            file TEXT, updated TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS embeddings(
            id TEXT PRIMARY KEY, vec TEXT, model TEXT, text_hash TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS inverted(
            tag TEXT, id TEXT, PRIMARY KEY(tag, id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS _db_meta(
            key TEXT PRIMARY KEY, value TEXT)""")
        # 二级索引 校正）。
        # 曾一次性建 8 个列索引，声称"让 recall 走索引查"——经 EXPLAIN QUERY PLAN 实测，
        # 该说法不成立：召回主路径是 `SELECT data FROM entries WHERE data IS NOT NULL` 全量取出后
        # 在 Python 内过滤，从不在 SQL 侧按 category/tier/scope/project 过滤。故其中 6 个索引
        # （category/tier/scope/project/cat_tier_status/scope_project）从未被查询计划采用，
        # 只在每次 INSERT/UPDATE 时白白增加维护开销 —— 纯负收益，本版删除。
        # 仅保留实测被采用的 status 索引：`COUNT(*) WHERE status='active'` 走 SEARCH 覆盖索引；
        # 它同时是表上最窄索引，裸 `COUNT(*)` 也会自动改用它做覆盖扫描（优于扫含 data 大字段的主表）。
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status)")
        except _sqlite3.OperationalError:
            pass
        # 清理 遗留的死索引（已升级用户的库首次连接时自动瘦身，幂等）。
        for _dead_idx in ("idx_entries_category", "idx_entries_tier", "idx_entries_scope",
                          "idx_entries_project", "idx_entries_file",
                          "idx_entries_cat_tier_status", "idx_entries_scope_project"):
            try:
                conn.execute("DROP INDEX IF EXISTS %s" % _dead_idx)
            except _sqlite3.OperationalError:
                pass
        # 迁移：补 data 列
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN data TEXT")
            conn.execute("INSERT OR REPLACE INTO _db_meta(key,value) VALUES (?,?)",
                         ("schema_version", "2"))
        except _sqlite3.OperationalError:
            # 列已存在
            pass
        conn.commit()
        # 若 data 列全空（旧库升级或首次建库），从 index.json 回填完整 JSON
        cur = conn.execute("SELECT COUNT(*) FROM entries WHERE data IS NOT NULL")
        has_data = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM entries")
        total = cur.fetchone()[0]
        if total == 0 or has_data == 0:
            data = _load_index_json_only(root)
            entries = data.get("entries", []) if isinstance(data, dict) else []
            if entries:
                _db_upsert_entries(conn, entries, root)
                conn.commit()
        conn.execute("INSERT OR REPLACE INTO _db_meta(key,value) VALUES (?,?)",
                     ("schema_version", "2"))
        conn.commit()
    finally:
        conn.close()
    # .x 迁移：旧索引 entries 缺多轴字段（domain/subdomain/scene/attrs/state…），
    # 导致 recall --subdomain/--scene 静默返回 0 命中（见 _index_entry_from_mem 注释）。
    # 升级后自动从记忆文件回填索引，无需手动 rebuild；不重算 embedding（embeddings 表独立）。
    _migrate_index_multiaxis(root)


_MIGRATING_ROOTS = set()  # 重入防护：防止迁移内 _db_conn → _index_db_ensure 递归触发自身


def _migrate_index_multiaxis(root):
    """一次性迁移：旧版索引缺多轴字段时，从记忆文件重建完整 entries 写回索引。
    
    幂等（_db_meta.multiaxis_v1 标记，跨进程仅跑一次）；重入安全（_MIGRATING_ROOTS 防递归）；
    全程异常吞掉并告警，绝不阻断正常命令——失败仅降级为『需手动 rebuild』。"""
    ab = os.path.abspath(root)
    if ab in _MIGRATING_ROOTS:
        return
    _MIGRATING_ROOTS.add(ab)
    try:
        conn = _db_conn(root)
        try:
            cur = conn.execute("SELECT value FROM _db_meta WHERE key='multiaxis_v1'")
            row = cur.fetchone()
            if row and row[0] == "1":
                return
            entries = _db_load_entries_full(root)
            # 无需迁移：非空且每条都已带 subdomain（多轴字段齐备）
            if entries and all("subdomain" in e for e in entries):
                conn.execute("INSERT OR REPLACE INTO _db_meta(key,value) VALUES (?,?)",
                             ("multiaxis_v1", "1"))
                conn.commit()
                return
        finally:
            conn.close()
        # 执行迁移：重读记忆文件，用 _index_entry_from_mem 重建完整 entries，写回索引
        md, ad = mem_dir(root), archive_dir(root)
        new_entries = []
        for d, archived in ((md, False), (ad, True)):
            try:
                fns = sorted(os.listdir(d))
            except FileNotFoundError:
                continue
            for fn in fns:
                if not fn.endswith(".json"):
                    continue
                fpath = os.path.join(d, fn)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        mem = json.load(f)
                    mid = mem.get("id") or fn[:-5]
                    st = mem.get("status", "archived" if archived else "active")
                    new_entries.append(_index_entry_from_mem(mem, mid, fn, archived, st))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    new_entries.append({"id": fn[:-5], "category": "", "summary": "[unparseable]",
                                        "tags": [], "tier": "working", "status": "corrupt", "file": fn})
        save_index(root, {"version": 2, "updated": today(), "entries": new_entries})
        conn2 = _db_conn(root)
        try:
            conn2.execute("INSERT OR REPLACE INTO _db_meta(key,value) VALUES (?,?)",
                          ("multiaxis_v1", "1"))
            conn2.commit()
        finally:
            conn2.close()
    except Exception as e:
        import sys
        sys.stderr.write("[migrate multiaxis] 索引多轴回填失败，已跳过（可手动 rebuild 修复）: %s\n" % e)
    finally:
        _MIGRATING_ROOTS.discard(ab)


def _load_index_json_only(root):
    """只读 index.json（不经过 SQLite），供迁移/兜底使用。"""
    p = os.path.join(root, "index.json")
    if not os.path.exists(p):
        return {"version": 1, "updated": today(), "entries": []}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as _e:
        # 4.9.17（同族：不再静默返回空）；损坏时若按空索引处理会**静默**跳过索引回填，
        # 让「文件坏了」看起来像「库里本来就没东西」。这里显式告警，便于 doctor/运维发现。
        import sys as _sys
        _sys.stderr.write(
            "[⚠ index] index.json 解析失败，按空索引处理（迁移/回填将跳过）: %s\n" % _e)
        return {"version": 1, "updated": today(), "entries": []}
    d.setdefault("entries", [])
    return d


_SCHEMA_INITIALIZED = set()  # P3 修复：已初始化 schema 的 root 集合，避免每次连接都跑 schema 检查

# P1：per-root 连接缓存。每条 CLI 命令是一个独立 Python 进程，进程内多次
# _db_conn 调用复用同一连接，省去重复的 sqlite3.connect + PRAGMA 开销（doctor/recall_multi/
# audit 等单进程内多次查询的场景收益明显）。进程退出由 _db_close_all 兜底关闭。
_DB_CACHE = {}
import atexit as _atexit


class _ConnProxy:
    """sqlite3.Connection 的薄包装：把 close 变成 no-op，使缓存的连接在进程内持续复用，
    而 execute/commit/cursor 等全部透传到真实连接。这样既有调用点的 `conn.close()` 无需改动，
    连接也不会被提前关掉。"""
    __slots__ = ("_r",)

    def __init__(self, real):
        object.__setattr__(self, "_r", real)

    def close(self):
        return None  # 保持缓存，不真正关闭

    def commit(self):
        return self._r.commit()

    def rollback(self):
        return self._r.rollback()

    def execute(self, *a, **k):
        return self._r.execute(*a, **k)

    def executemany(self, *a, **k):
        return self._r.executemany(*a, **k)

    def executescript(self, *a, **k):
        return self._r.executescript(*a, **k)

    def cursor(self, *a, **k):
        return self._r.cursor(*a, **k)

    def __enter__(self):
        return self  # 返回代理自身，避免 with-as 拿到真实连接后被误关

    def __exit__(self, *a):
        return None  # 退出上下文不关闭缓存连接

    def __getattr__(self, name):
        return getattr(self._r, name)


def _db_close_all():
    """进程退出时关闭所有缓存连接，确保 WAL 落盘。"""
    for _c in _DB_CACHE.values():
        try:
            _c._r.close()
        except Exception:
            pass
    _DB_CACHE.clear()


_atexit.register(_db_close_all)


def _db_conn(root):
    # P3 修复：schema 检查每个 root 只跑一次（首次连接时），后续直接连接
    # P4 修复：加锁保护 check-then-add 竞态（多线程同时首次连接同一 root 时，
    # 两个线程都可能通过 `not in` 检查 → 重复跑 schema 初始化）
    root_abs = os.path.abspath(root)
    with _STATE_LOCK:
        if root_abs not in _SCHEMA_INITIALIZED:
            _index_db_ensure(root)
            _SCHEMA_INITIALIZED.add(root_abs)
        conn = _DB_CACHE.get(root_abs)
        if conn is None:
            # check_same_thread=False：本库写入已用 per-root RLock 串行化，读路径单线程，
            # 允许缓存连接跨同进程调用复用而不触发线程归属检查。
            conn = _sqlite3.connect(_db_path(root), check_same_thread=False)
            # I4（沙箱报告改进）：busy_timeout 5s——写锁竞争时等待而非立即报
            # "database is locked"，配合 WAL 模式提升高并发下的可用性。
            conn.execute("PRAGMA busy_timeout=5000")
            _DB_CACHE[root_abs] = _ConnProxy(conn)
    return _DB_CACHE[root_abs]


def _db_upsert_entries(conn, entries, root=None):
    """批量幂等 upsert entries（INSERT OR REPLACE）。 改用 executemany 单批提交，
    取代逐条 execute，降低 O(n) 写放大（千条库实测 1000 条 36s → 单批毫秒级）。"""
    rows = []
    for e in entries:
        if not isinstance(e, dict) or "id" not in e:
            continue
        rows.append((
            e.get("id"), e.get("category", ""), e.get("summary", ""),
            e.get("body", ""), json.dumps(e.get("tags", []), ensure_ascii=False),
            e.get("tier", "working"), e.get("status", "active"),
            e.get("scope", "universal"), e.get("project", ""),
            e.get("file", (e.get("id", "") or "") + ".json"), today(),
            json.dumps(e, ensure_ascii=False)))
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO entries"
            "(id,category,summary,body,tags,tier,status,scope,project,file,updated,data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def _db_load_entries_full(root):
    """从 SQLite entries.data 列读取完整记忆 JSON 列表；SQLite 现为权威源。"""
    conn = _db_conn(root)
    try:
        cur = conn.execute("SELECT data FROM entries WHERE data IS NOT NULL")
        rows = cur.fetchall()
        out = []
        for (raw,) in rows:
            try:
                e = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            out.append(e)
        return out
    finally:
        conn.close()
