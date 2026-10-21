# Auto-extracted submodule: _recall_cache
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.
#
# ── 5.0 / B2 改造（2026-09-16）──────────────────────────────────────────────
# 问题：磁盘缓存原为单个 `.recall_cache.json`，**每次写入都把整个文件读出→改→全量
# 序列化回写**。实测（真库 226 条）：文件 11.56 MB / 19 条，单条 value 最大 553 KB；
# cProfile 显示 50 次 recall 里 5 次 `_recall_cache_set` 占去 13.7s（92%），
# `json.dump` 累计 13.3s / 约 390 万次编码器回调 → recall p50 1.58ms 而 p95 2590ms。
# 根因是「缓存值 = 完整召回结果（含 body/relations，且 recall(query) 会返回全库）」
# × 「全量重写」= O(总文件大小) 的序列化成本。
#
# 修法（三条，均不改召回语义）：
#   ① 磁盘后端 JSON 文件 → **SQLite**（`store/.recall_cache.db`）：写入变为单行
#      `INSERT OR REPLACE`，序列化成本从 O(文件总大小) 降到 O(单条)。
#   ② **延迟合并写**：进程内多次 set 只登记脏 key，退出时（atexit）批量落盘一次。
#      同一进程内连跑 N 次 recall 由「N 次全量重写」变为「1 次增量写」。
#   ③ **root 规范化**：缓存键的 root 走 `_root_key`，避免 `D:\X` 与 `D:/X`
#      把同一个库劈成两套命名空间（实测真库曾 1 条 vs 18 条）。
# 另：单条 value 的上限、以及「recall 无阈值返回全库」属召回层问题，见 5.0 方案 B2 后续项。

def _recall_cache_cfg_sig(root):
    """召回配置的**内容签名**（缓存键的一部分）。

    🔴 为什么需要它（2026-09-16 实测）：缓存键原先把 config.json 的 **mtime** 当作
    「配置版本」，但 mtime 有两个致命局限：
      ① NTFS 上 `getmtime` 的可见粒度约 15.6ms —— 连续两次改配置落在同一粒度内时
         键**完全不变**（实测：写 `rerank_enabled: true` 再写回，键相等）；
      ② mtime 表达的是「文件被动过」，不是「配置是什么」（同 mtime 不同内容、或配置
         来源换了而文件没动，都捕获不到）。
    而 5.0 新增的 rerank_enabled/rerank_model/rerank_top/rerank_weight **原先完全不在
    键里** → 开关切换后仍命中旧缓存（B1 消融实验与真实使用都会被它坑）。

    修法：对 `_load_recall_config(root)` 的结果算内容哈希。**本函数是唯一来源**，
    调用方与测试都调它，不得各自复刻（复刻规则＝同类 bug 的温床）。
    mtime 仍保留在键里作为兜底（多监视一个 `store/config.json`）。
    """
    try:
        cfg = _load_recall_config(root)
        return hashlib.sha256(
            json.dumps(cfg, sort_keys=True, ensure_ascii=False,
                       default=str).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


def _recall_cache_key(root, tag, category, query, tier, min_tier, scope, project, deep, domain=None, scene=None, subdomain=None, include_auto=False, about_axis=None, semantic_gate=None, cfg_sig=None, filter_sig=None):
    """生成缓存键（不含 touch/ann/mid 等副作用参数——有副作用的调用不缓存）。
    I5（沙箱报告改进）：缓存键增加 config.json 的 mtime——config 变更后自动失效缓存，
    避免缓存了旧配置下的召回结果。
    v3.2.1 B1：缓存键增加 domain——避免跨域召回串缓存。
    v3.7.0：缓存键增加 scene——scene 是硬过滤轴，缺失会与 scene=None 串缓存导致过滤被绕过。
    v3.7.2：缓存键增加 subdomain——subdomain 同为硬过滤轴，缺失会与 subdomain=None 串缓存。
    D-new-1 修复：缓存键增加 index.json 的 mtime——任何更新索引的写入（deposit/overwrite/
    delete/archive/reclassify/restore…）都会让旧召回缓存失效，避免同进程内「先写后查」看到
    过期结果（CLI 每次独立进程本无此问题，长驻库调用时才暴露）。
    5.0/B2：root 经 `_root_key` 规范化——否则 `D:\\X` 与 `D:/X` 会各自缓存一份。
    5.0 修正（两个真缺口）：
    ① mtime 原先只取 `root/config.json`，但 `_load_recall_config` 是
       **`store/config.json` 优先、root 兜底**，且真库实际把 `semantic_gate` 写在
       `store/config.json` → 改那个文件**不会**失效缓存（键没变、配置已变）。
       现两个路径都纳入。
    ② `cfg_sig`（配置内容签名，由调用方传入）——mtime 只能捕获「文件被动过」，
       捕获不了「同 mtime 不同内容」以及「配置来源换了但文件没动」。
       rerank_enabled/rerank_model/rerank_top/rerank_weight 这些 5.0 新增项原先
       **完全不在键里** → 开关切换后读到旧缓存（消融实验与真实使用都会被它坑）。
       传内容签名后，任何召回配置变化都必然换键。
    ③ `filter_sig`（`--filter` 子句签名）—— `filter_clauses` 原先**不在键里**
       ⇒ 同 query 配不同 `--filter` 的两次 recall 会**互相返回对方的结果**
       （与 `as_of` 串缓存完全同类；2026-09-16 自查发现）。
    """
    _cfg_mtime = 0.0
    _idx_mtime = 0.0
    _cfg_mtimes = []
    for _cp in (os.path.join(root, "config.json"),
                os.path.join(root, "store", "config.json")):
        try:
            _cfg_mtimes.append(os.path.getmtime(_cp))
        except OSError:
            pass
    _cfg_mtime = tuple(_cfg_mtimes)
    _idx_path = os.path.join(root, "index.json")
    if os.path.exists(_idx_path):
        try:
            _idx_mtime = os.path.getmtime(_idx_path)
        except OSError:
            pass
    return (_root_key(root), tag or "", category or "", (query or "").lower().strip(),
            tier or "", min_tier or "", scope or "", project or "", bool(deep),
            _cfg_mtime, _idx_mtime, domain or "", scene or "", subdomain or "",
            bool(include_auto), normalize_about_axis(about_axis) or "",
            semantic_gate, (cfg_sig or ""), (filter_sig or ""))  # 5.0：配置签名 + 过滤签名

def _recall_cache_clear(root=None):
    """失效进程内召回缓存。root 给定时只清该 root 的条目（精准、无副作用）；
    不传则清全部。任何改变召回结果的写入都应触发，确保长驻库调用时『先写后查』
    不返回过期结果：
    - 更新 index.json 的写入（deposit/overwrite/archive/reclassify/reflect/delete…）
    已通过缓存键内置的 index.json mtime 自动失效；
    - 不更新索引的写入（decay 改 relevance_score/thermal、feedback 改 importance、
    touch 改 recency 等）由本函数显式失效兜底。
    统一在 _save_mem（所有记忆文件写入入口）与 delete 末尾调用，覆盖全部写路径。"""
    if root is None:
        _RECALL_CACHE.clear()
        return
    root = _root_key(root)
    for k in [kk for kk in _RECALL_CACHE if kk[0] == root]:
        del _RECALL_CACHE[k]

def _recall_cache_file(root):
    """磁盘缓存文件：落在 store/ 运行时目录（与 index.db 同层），不属记忆文件，doctor 不扫此处，
    也不进主召回链路。用于跨进程命中——mem_bridge 每调 spawn 新进程，进程内缓存一次都活不到下条命令，
    落盘后连续两次 recall 可复用。

    5.0/B2：改为 **SQLite**（`store/.recall_cache.db`），单行 upsert 取代全量重写。
    本函数保留（返回数据库路径），旧调用点语义不变。"""
    return os.path.join(os.path.dirname(_db_path(root)), ".recall_cache.db")

def _recall_cache_legacy_file(root):
    """4.9.x 的 JSON 缓存文件路径（仅供一次性迁移/清理识别，不再读写）。"""
    return os.path.join(os.path.dirname(_db_path(root)), ".recall_cache.json")

_CACHE_DISK_MAX = 16      # 磁盘缓存最多保留多少个查询（按写入时间取最近 N 条）
_CACHE_MEM_MAX = 64       # 进程内缓存上限（防长驻进程内存增长）
_PENDING_DISK = set()     # 待落盘的 key（延迟合并写）
_FLUSH_HOOK = [False]     # atexit 是否已注册


def _cache_db_conn(root, create=True):
    """打开（并按需建表）召回缓存的 SQLite 连接。"""
    import sqlite3 as _sq
    fp = _recall_cache_file(root)
    d = os.path.dirname(fp)
    if create and d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    conn = _sq.connect(fp, timeout=5.0)
    if create:
        conn.execute("CREATE TABLE IF NOT EXISTS recall_cache "
                     "(k TEXT PRIMARY KEY, ts REAL, results TEXT)")
        conn.commit()
    return conn


def _recall_cache_flush():
    """把待落盘的 key 批量写入磁盘缓存（延迟合并写的落盘点）。

    由 atexit 自动调用；也可显式调用（测试/长驻进程定期落盘用）。
    幂等：无待写 key 时立即返回。全程吞异常——缓存失败绝不影响召回正确性。"""
    if not _PENDING_DISK:
        return
    try:
        keys = list(_PENDING_DISK)
        _PENDING_DISK.clear()
        by_root = {}
        for k in keys:
            by_root.setdefault(k[0], []).append(k)
        for root, ks in by_root.items():
            # 🔴 root 已被删除 ⇒ 丢弃其脏 key，**绝不重建目录**。
            #    延迟合并写的落盘点在 atexit，**晚于**删除动作；无脑 create 会把已删
            #    目录「复活」成幽灵。2026-09-16 实测：每轮门禁因此多留 3 个
            #    `keeper_sm_sync_*` 空壳（里面只有 `store/.recall_cache.db`）——
            #    因为 test_save_mem_index_sync 的 tearDown 先 rmtree、atexit 再落盘。
            #    生产侧同理：用户删掉某个库后，进程退出会把它凭空建回来。
            if not os.path.isdir(root):
                continue
            try:
                conn = _cache_db_conn(root)
            except Exception:
                continue
            try:
                rows = []
                for k in ks:
                    hit = _RECALL_CACHE.get(k)
                    if not hit:
                        continue
                    rows.append((json.dumps(k, ensure_ascii=False, sort_keys=True),
                                 float(hit[0]),
                                 json.dumps(hit[1], ensure_ascii=False)))
                if rows:
                    conn.executemany("INSERT OR REPLACE INTO recall_cache(k,ts,results) "
                                     "VALUES(?,?,?)", rows)
                # 只保留最近 N 条（超出即淘汰最旧，避免缓存文件无界增长）
                conn.execute("DELETE FROM recall_cache WHERE k NOT IN "
                             "(SELECT k FROM recall_cache ORDER BY ts DESC LIMIT ?)",
                             (_CACHE_DISK_MAX,))
                conn.commit()
                # 一次性清理：把 4.9.x 的 JSON 缓存改名归档（不删除，可逆）
                lf = _recall_cache_legacy_file(root)
                if os.path.exists(lf):
                    try:
                        os.replace(lf, lf + ".retired")
                    except OSError:
                        pass
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception:
        pass


def _register_flush_hook():
    """注册进程退出时的落盘钩子（只注册一次）。"""
    if _FLUSH_HOOK[0]:
        return
    try:
        import atexit
        atexit.register(_recall_cache_flush)
        _FLUSH_HOOK[0] = True
    except Exception:
        pass


def _recall_cache_get(key, ttl):
    """命中返回 (results, True)；未命中返回 (None, False)。
    先查进程内，未命中再查磁盘（跨进程兜底）。
    注：at-rest 加密能力已于 4.9.27 整体下线，本路径不再存在「加密库」分支。"""
    import time as _time
    if key in _RECALL_CACHE:
        ts, results = _RECALL_CACHE[key]
        if _time.time() - ts < ttl:
            return results, True
        del _RECALL_CACHE[key]
        # 跨进程磁盘兜底：同 root 的另一进程（如连续两次 mem_bridge recall）可命中，省去重算向量+余弦
    try:
        skey = json.dumps(key, ensure_ascii=False, sort_keys=True)
        conn = _cache_db_conn(key[0], create=False)
        try:
            cur = conn.execute("SELECT ts, results FROM recall_cache WHERE k = ?", (skey,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row:
            ts, payload = float(row[0]), row[1]
            if _time.time() - ts < ttl:
                results = json.loads(payload)
                _RECALL_CACHE[key] = (ts, results)  # 回填内存，后续同进程命中更快
                return results, True
    except Exception:
        pass
    return None, False

def _recall_cache_set(key, results):
    """写入缓存（进程内立即 + 磁盘延迟合并），并清理过期条目（防止内存泄漏）。"""
    import time as _time
    _RECALL_CACHE[key] = (_time.time(), results)
    # 清理内存中的过期条目（超过 5 分钟的）与超量条目（保最近 _CACHE_MEM_MAX 条）
    cutoff = _time.time() - 300
    for k in [k for k, v in _RECALL_CACHE.items() if v[0] < cutoff]:
        del _RECALL_CACHE[k]
    if len(_RECALL_CACHE) > _CACHE_MEM_MAX:
        items = sorted(_RECALL_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in items[:len(_RECALL_CACHE) - _CACHE_MEM_MAX]:
            del _RECALL_CACHE[k]
    # 磁盘：只登记脏 key，退出时批量落盘（同一进程内 N 次 set → 1 次增量写）
    _PENDING_DISK.add(key)
    _register_flush_hook()
