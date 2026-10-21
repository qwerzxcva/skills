# memory_ops/_graph.py —— 关系管理子模块（F18 阶段2 抽取，原 __init__.py L6822-L6921）
# 零行为变化。依赖项由 memory_ops/__init__.py 在加载时按文件绝对路径注入，以兼容
# 「作为包」与「作为独立模块（spec_from_file_location 加载 __init__.py）」两种方式
# （独立加载时无 memory_ops 包，故不在此文件内 import 包，改由调用方注入全局）。
import os
import sys


# 仅这些方向性边参与成环检测（see_also/related_to 等非方向边不传递方向性，
# 否则 deposit 自动连的 see_also 会让首次建方向边被误判成环）。
_DIRECTIONAL_EDGES = ("consumes", "test_of", "composed_of", "validated_by", "audits")


def _reaches(root, start, goal, _seen=None, _depth=0):
    """只读遍历：判断从 start 出发经【方向性】relations 是否能到达 goal（用于 link 成环检测）。"""
    if start == goal:
        return True
    if _depth >= 8:
        return False
    try:
        m, _ = _load_mem(root, start)
    except Exception:
        return False
    if _seen is None:
        _seen = set()
    if start in _seen:
        return False
    _seen.add(start)
    rels = m.get("relations") or {}
    for _et, tgts in rels.items():
        if _et not in _DIRECTIONAL_EDGES:  # 仅沿方向性边推进，避免 see_also 等非方向边误判成环
            continue
        if isinstance(tgts, list):
            for t in tgts:
                if _reaches(root, t, goal, _seen, _depth + 1):
                    return True
        elif isinstance(tgts, str):
            if _reaches(root, tgts, goal, _seen, _depth + 1):
                return True
    return False


    # F6：关系枚举单一事实源。_LINK_ALLOWED = 可经 link 创建的方向边；
    # _REL_TYPES = 关系图谱摘要覆盖的全部类型（含仅导入/手动存在的类型）。
    # 断言保证「可创建的关系必在图谱里可见」，消除双向失配（validated_by/audits 曾漏列）。
_LINK_ALLOWED = ("see_also", "superseded_by", "corrected_by",
                 "consumes", "test_of", "composed_of",
                 "validated_by", "audits")
_REL_TYPES = ("related_to", "superseded_by", "corrected_by", "supports",
              "refutes", "is_a", "part_of", "derived_from",
              "consumes", "test_of", "composed_of",
              "see_also", "validated_by", "audits")
assert set(_LINK_ALLOWED).issubset(set(_REL_TYPES)), \
    "_LINK_ALLOWED 必须是 _REL_TYPES 的子集（否则可创建的关系在图谱里不可见）"


@_with_deposit_lock
def link(root, mid, rel, target, dry_run=False, yes=False):
    if rel not in _LINK_ALLOWED:
        raise ValueError("rel 必须是 " + "/".join(_LINK_ALLOWED))
    if not target:
        raise ValueError("target 不能为空")
    if target == mid:
        raise ValueError("不能关联到自身（自环）")
        # 目标存在性校验：防止悬挂边（指向不存在的记忆）
    try:
        _load_mem(root, target)
    except Exception:
        raise ValueError("target 记忆 %s 不存在" % target)
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    if dry_run:
        return {"dry_run": True, "op": "link", "id": mid, "rel": rel, "target": target, "file": fp}
    if not yes:
        _warn_destructive("link(关联)", mid, fp,
                          "关联会改写该文件的 relations 字段（建立 %s 关系链）。低风险，确认可加 --yes。"
                          % "/".join(_LINK_ALLOWED))
        # 成环检测（仅方向性边：consumes/test_of/composed_of/validated_by/audits）
    if rel in ("consumes", "test_of", "composed_of", "validated_by", "audits"):
        if _reaches(root, target, mid):
            raise ValueError("会形成环路：%s 已（经关系）指向 %s" % (target, mid))
    mem.setdefault("relations", {})
    if rel in ("see_also", "consumes", "test_of", "composed_of", "validated_by", "audits"):
        # 一对多列表边：因子可消费多个数据(consumes)、系统可含多个因子(composed_of) 等
        lst = mem["relations"].setdefault(rel, [])
        if target not in lst:
            lst.append(target)
    else:
        mem["relations"][rel] = target
        if rel == "superseded_by":
            mem["status"] = "superseded"
            mem["superseded_at"] = today()  # 回收计时起点：自被取代日起算 180 天
            mem["settled"] = False  # #9：被取代 → settled 失效
    _save_mem(root, mid, mem, expect_mtime=mtime)
    # 同步 index 的 status —— F16：仅 upsert 变更条目，避免全量重插（破 O(n²)）
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            e["status"] = mem.get("status", "active")
            try:
                conn = _db_conn(root)
                try:
                    _db_upsert_entries(conn, [e], root)
                finally:
                    conn.close()
                _flush_index_json(root, data)   # 仅刷新 index.json 兜底，不再全量重插 SQLite
            except Exception as _e:
                import sys as _s
                _s.stderr.write("[⚠ link] 增量保存失败，回退全量 save_index: %s\n" % _e)
                _log_struct("link_incremental_save_fail", err=str(_e))
                save_index(root, data)
            break
    else:
        save_index(root, data)
        # ：纠正类连边（corrected_by/superseded_by）→ 双方打 dirty，
        # self-heal 据此同步相关 skill/规则层（源被推翻→skill 事实需复核）
    if rel in ("corrected_by", "superseded_by"):
        try:
            from _self_heal import mark_dirty_safe
            mark_dirty_safe(root, mid)
            mark_dirty_safe(root, target)
        except Exception:
            pass
    return mid


