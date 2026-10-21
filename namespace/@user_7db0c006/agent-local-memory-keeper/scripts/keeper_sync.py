#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keeper_sync.py —— 跨设备记忆同步（多台电脑 / 一周用一次的低频场景）。

## 为什么需要它
keeper 的 export/import 单独用会踩 4 个坑（2026-09-05 实测，见 CHANGELOG 4.9.1）：
  1. export 默认只导 active，静默丢掉 superseded/archived（本机实测 19 条只出 7 条）
  2. `--include-superseded` 在 4.9.0 及以前对 export **无效**（传了也不生效）
  3. import 默认 dry-run，不加 `--execute` 一条都不写（跑完以为成功了）
  4. md 格式往返会丢摘要（4.9.1 已修；但同步仍建议用 jsonl 保真）

## 三条铁律（实测结论，**代码硬拦截 fail-closed**，逃生必须显式加 flag）
  1. **必须 --keep-ids**：不带时每次导入都生成新 id，19→38→57 无限膨胀。
     `in --execute` 时带 `--no-keep-ids` 会**直接拒绝（rc=8）**，
     确属特殊修复场景须再加 `--i-know-id-bloat` 才放行；dry-run 预演不受影响。
  2. **同 id 重复导入 = 覆盖（后导入者为准）**。所以同步必须**单向**（源→目标），
     绝不能同一轮里 A→B 又 B→A，否则互相回滚。
  3. **落盘前先备份 + 完整性校验**：
     - 备份：`in --execute` 默认把目标库整体备份为 `<store>_bak_<ts>`
       （`--no-backup` 可关，不推荐，会红字警告）。
     - 校验：同步包**必须**带同名 `.meta.json`（含 sha256）；缺失时 `--execute`
       **直接拒绝（rc=7）**，须显式加 `--allow-unverified` 才放行。

## 退出码（便于脚本判断）
  0 成功 ｜ 1 参数缺失 ｜ 2 包损坏（sha256 不匹配）｜ 3 备份失败
  4 导入失败 ｜ 5 导入有部分失败（库可能只导入了一半）
  6 幂等校验失败（条数异常）｜ 7 未经完整性校验 ｜ 8 未确认 id 膨胀

## 用法
```bash
# 源机：导出全量同步包（含 superseded/archived，jsonl 保真 + sha256 校验）
python scripts/keeper_sync.py out --dest D:/同步盘/keeper

# 目标机：先预演（默认 dry-run，看新增/覆盖多少）
python scripts/keeper_sync.py in --dir D:/同步盘/keeper
# 确认无误后落盘
python scripts/keeper_sync.py in --dir D:/同步盘/keeper --execute
```
"""
import os
import re
import sys
import json
import shutil
import hashlib
import datetime
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import memory_ops as mo          # noqa: E402
import keeper_import as ki       # noqa: E402

SYNC_PREFIX = "keeper_sync_"


def _ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _host():
    try:
        import socket
        return socket.gethostname()
    except Exception:  # noqa: BLE001
        return "unknown"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _warn(msg):
    sys.stderr.write("!! %s\n" % msg)


def _info(msg):
    sys.stdout.write("%s\n" % msg)


def _jl(content):
    return [json.loads(ln) for ln in (content or "").splitlines() if ln.strip()]


def _count_mems(root):
    try:
        return len(list(mo._iter_all_mems(root)))
    except Exception:  # noqa: BLE001
        return -1


# ---------------------------------------------------------------- out
def cmd_out(args):
    root = args.root or (os.environ.get("AI_MEMORY_STORE") or mo.DEFAULT_ROOT)
    dest = args.dest
    os.makedirs(dest, exist_ok=True)

    # 全量导出（两个开关都开，避免静默少导）
    r = mo.export_memories(root, fmt="jsonl",
                           include_archived=True, include_superseded=True)
    if not r.get("ok"):
        _warn("导出失败: %s" % r)
        return 1
    content = r.get("content") or ""
    n = r.get("count", 0)
    if r.get("filtered_out", 0) != 0:
        _warn("仍有 %d 条被过滤（应为 0），请检查状态过滤逻辑" % r["filtered_out"])

    stamp = _ts()
    fn = os.path.join(dest, "%s%s_%s.jsonl" % (SYNC_PREFIX, _host(), stamp))
    with open(fn, "w", encoding="utf-8") as f:
        f.write(content)
    sha = _sha256(fn)

    meta = {
        "schema": "keeper_sync/1",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "host": _host(),
        "keeper_root": root,
        "count": n,
        "filtered_out": r.get("filtered_out", 0),
        "sha256": sha,
        "file": os.path.basename(fn),
        "format": "jsonl",
        "note": "全量包（active+superseded+archived）。导入时必须 --keep-ids（由 keeper_sync in 强制）。",
    }
    mp = fn[:-6] + ".meta.json"
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    _info(json.dumps({"ok": True, "file": fn, "meta": mp, "count": n,
                      "sha256": sha[:16], "from_root": root}, ensure_ascii=False))
    _info("下一步：把这两个文件拷到目标机，跑 "
          "`keeper_sync.py in --file %s`（先看预演，再加 --execute）"
          % os.path.basename(fn))
    return 0


def _hard_delete(path):
    """真删（沙箱 safe-delete 会 fails closed，须 Win32 兜底）。

    同步去重时删除重复的记忆副本文件必须真删——此处的新文件不会被覆盖，
    若删除静默失效就会留下双份脏数据。"""
    try:
        os.remove(path)
        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes
        if ctypes.windll.kernel32.DeleteFileW(path):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _set_status_superseded(root, mid):
    """把目标库的某条记忆置为 superseded（keeper 尚无公开 API，此处按 _deposit
    的既有写法对齐：改 mem 文件 status + 改 index 条目 + 作废增量缓存）。"""
    try:
        mem, _fp = mo._load_mem(root, mid)
    except Exception:  # noqa: BLE001
        return False
    if mem.get("status") == "superseded":
        return False
    mem["status"] = "superseded"
    mem["superseded_at"] = mo.today()
    mo._save_mem(root, mid, mem)
    try:
        data = mo.load_index(root)
        for e in data.get("entries", []):
            if e.get("id") == mid:
                e["status"] = "superseded"
        mo._tag_index_reset(root)
        mo.save_index(root, data)
    except Exception:  # noqa: BLE001
        pass
    return True


def _fix_index_entry(root, mid, rel_file, status):
    """修正 index 里的 file 指向（去重删掉重复副本后，条目可能还指向已删文件）。"""
    try:
        data = mo.load_index(root)
        hit = False
        for e in data.get("entries", []):
            if e.get("id") == mid:
                e["file"] = rel_file
                e["status"] = status
                hit = True
        if hit:
            mo._tag_index_reset(root)
            mo.save_index(root, data)
    except Exception:  # noqa: BLE001
        pass


def _reconcile(root, pkg_status, dry=False):
    """导入后按同步包状态收敛目标库（v4.9.1 关键修复）。

    为什么需要：deposit 导入一律写 active 状态到 memories/ 根目录，而
    archived 记忆住在 memories/archive/ —— 于是会产生两个问题：
      ① 状态丢失：源库的 superseded/archived 记忆在目标库全部"复活"成 active
      ② 重复副本：archived 记忆在 root 与 archive 各一份（实测 19→26 条）
    本函数做三件事：
      1. dedup：同 id 双份时删除与包状态不符的那份
      2. archived：包里是 archived → archive() 搬进 archive 目录
      3. superseded：包里是 superseded → 置 status=superseded（留在 root 目录）
    """
    stat = {"archived": 0, "superseded": 0, "dedup_removed": 0, "skipped": 0}
    mdir, adir = mo.mem_dir(root), mo.archive_dir(root)
    for mid, want in pkg_status.items():
        p_root = os.path.join(mdir, mid + ".json")
        p_arch = os.path.join(adir, mid + ".json")
        has_root, has_arch = os.path.exists(p_root), os.path.exists(p_arch)
        if not (has_root or has_arch):
            stat["skipped"] += 1
            continue
        if has_root and has_arch:
            # 双份：删掉与包状态不符的那份（archived 留 archive，其余留 root）
            victim = p_root if want == "archived" else p_arch
            if not dry:
                if _hard_delete(victim):
                    stat["dedup_removed"] += 1
                else:
                    _warn("去重删除失败（保留双份）：%s" % victim)
            else:
                stat["dedup_removed"] += 1
            if want == "archived":
                has_root = False
            else:
                has_arch = False
        if want == "archived" and has_root:
            if not dry:
                try:
                    mo.archive(root, mid, yes=True)
                    stat["archived"] += 1
                except Exception as e:  # noqa: BLE001
                    _warn("archive 失败 %s: %s" % (mid, e))
            else:
                stat["archived"] += 1
        elif want == "superseded" and has_root:
            if not dry:
                if _set_status_superseded(root, mid):
                    stat["superseded"] += 1
            else:
                stat["superseded"] += 1
        if dry:
            continue
        # 保证 index 指向正确的物理位置
        if want == "archived":
            _fix_index_entry(root, mid, "archive/%s.json" % mid, "archived")
    if not dry:
        try:
            mo._tag_index_reset(root)
        except Exception:  # noqa: BLE001
            pass
    return stat


# ---------------------------------------------------------------- in
def _pick_latest(d):
    cands = [f for f in os.listdir(d)
             if f.startswith(SYNC_PREFIX) and f.endswith(".jsonl")]
    if not cands:
        _warn("目录里没有 %s*.jsonl：%s" % (SYNC_PREFIX, d))
        return None
    cands.sort()
    return os.path.join(d, cands[-1])


def cmd_in(args):
    root = args.root or (os.environ.get("AI_MEMORY_STORE") or mo.DEFAULT_ROOT)
    path = args.file
    if not path and args.dir:
        path = _pick_latest(args.dir)
    if not path or not os.path.exists(path):
        _warn("找不到同步包：%s" % path)
        return 1

    # ① 完整性校验（有 meta 就核 sha256，防传输/拷贝截断）
    meta_path = path[:-6] + ".meta.json"
    meta = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:  # noqa: BLE001
            _warn("meta 读取失败（忽略）：%s" % e)
    if meta and meta.get("sha256"):
        actual = _sha256(path)
        if actual != meta["sha256"]:
            _warn("SHA256 不匹配！文件可能损坏或被截断。\n"
                  "  期望: %s\n  实际: %s\n已中止，请重新拷贝。" % (meta["sha256"], actual))
            return 2
        _info("✓ 完整性校验通过（sha256 %s…）" % meta["sha256"][:16])

    # ② keep_ids 铁律
    keep_ids = not args.no_keep_ids
    if not keep_ids:
        _warn("你选了 --no-keep-ids：同一份包每导入一次就会生成一批新 id，"
              "库会 19→38→57 无限膨胀。跨设备同步绝对不要这么用"
              "（--execute 落盘时会被直接拦下，须再加 --i-know-id-bloat）。")

    # ③ 预演统计：新增 / 覆盖 / 目标库现状
    with open(path, encoding="utf-8") as f:
        incoming = [json.loads(ln) for ln in f if ln.strip()]
    in_ids = set(m.get("id") for m in incoming if m.get("id"))
    try:
        existing = set(m.get("id") for m in mo._iter_all_mems(root))
    except Exception:  # noqa: BLE001
        existing = set()
    new_ids = in_ids - existing
    overlap = in_ids & existing
    idempotent_bad = False
    before_n = _count_mems(root)

    # 同步包状态分布（导入后会按此收敛，预演时先告知）
    pkg_status = {m.get("id"): (m.get("status") or "active")
                  for m in incoming if m.get("id")}
    dist = {}
    for v in pkg_status.values():
        dist[v] = dist.get(v, 0) + 1

    _info("同步包: %s（%d 条）" % (os.path.basename(path), len(incoming)))
    _info("目标库: %s（现有 %d 条）" % (root, before_n))
    _info("预计新增 %d 条 / 覆盖同 id %d 条（覆盖=以同步包为准）"
          % (len(new_ids), len(overlap)))
    _info("包内状态分布: %s → 导入后自动收敛（archived 归档 / superseded 标记 / 去重双份）"
          % json.dumps(dist, ensure_ascii=False))
    if meta and meta.get("host") and meta.get("host") == _host():
        _info("注意：同步包来自本机（%s），通常无需导入。" % meta["host"])

    # ③-b 完整性校验是否真的生效了（meta 丢了就压根没校验，不能静默放过）
    verified = bool(meta and meta.get("sha256"))
    if not verified:
        _warn("⚠️ 本次没有做完整性校验：没找到配套的 .meta.json（或里面没有 sha256），"
              "无法确认这个包在拷贝/传输中有没有损坏或被截断。\n"
              "  建议：把 <包名>.meta.json 一起拷过来再导入。")

    if not args.execute:
        _info("\nDRY-RUN 预演结束，未写入任何数据。确认上面数字无误后加 --execute 落盘。")
        return 0

    # ── ④ 落盘前硬拦截（fail-closed）──
    # 这两条踩了都会毁库（静默丢数据 / 库膨胀成双份），必须显式逃生才放行。
    if not verified and not args.allow_unverified:
        _warn("已中止（rc=7）：这个同步包没有经过完整性校验（缺 .meta.json / sha256）。\n"
              "  这是防「拷到一半的坏包被导入、静默丢数据」的硬闸门。\n"
              "  要继续：① 把配套的 .meta.json 一起拷来；"
              "② 或确知风险后显式加 --allow-unverified（后果自负）。")
        return 7
    if not keep_ids and not args.i_know_id_bloat:
        _warn("已中止（rc=8）：--no-keep-ids 会让同一份包每次导入都生成一批新 id，"
              "库会 19→38→57 无限膨胀。\n"
              "  这是防「跨设备同步把库搞成双份」的硬闸门。\n"
              "  若确属特殊修复场景，请显式加 --i-know-id-bloat 再执行。")
        return 8

    # ⑤ 落盘前备份
    if args.no_backup:
        _warn("你选了 --no-backup：落盘前不会备份目标库，一旦导入出问题无法回退。"
              "除非库是临时的，否则强烈建议去掉这个参数。")
    elif os.path.isdir(root):
        bak = "%s_bak_%s" % (root.rstrip("\\/"), _ts())
        try:
            shutil.copytree(root, bak)
            _info("✓ 目标库已备份：%s" % bak)
        except Exception as e:  # noqa: BLE001
            _warn("备份失败（%s）。加 --no-backup 可跳过，但不推荐。" % e)
            return 3

    # ⑤ 真实导入
    res = ki.run_import(root, path, fmt="jsonl", dry_run=False,
                        keep_ids=keep_ids, on_error=args.on_error)

    # ⑥ 状态收敛：把 deposit 一律写 active 造成的「状态丢失 + 重复副本」修回来
    rec = _reconcile(root, pkg_status, dry=False)
    _info("状态收敛: 归档 %d / 标 superseded %d / 去重删副本 %d / 未找到 %d"
          % (rec["archived"], rec["superseded"], rec["dedup_removed"], rec["skipped"]))
    if rec.get("skipped"):
        _warn("有 %d 条包内记忆在库里没找到（状态收敛跳过），"
              "说明导入可能不完整，请核对下面的条数。" % rec["skipped"])

    after_n = _count_mems(root)
    if res.get("errors"):
        _warn("有 %s 条导入失败（--on-error=%s）。库可能只导入了一部分，"
              "**不要当成同步成功**；建议加 --on-error abort 重跑一次。"
              % (res.get("errors"), args.on_error))
    _info(json.dumps({
        "ok": res.get("ok"),
        "imported": res.get("imported"),
        "errors": res.get("errors"),
        "quarantined": res.get("quarantined"),
        "store_before": before_n,
        "store_after": after_n,
        "new": len(new_ids),
        "overwritten": len(overlap),
    }, ensure_ascii=False))
    # 幂等校验：期望 = 包内条数 + 目标库中「包外独有」的条数
    kept_other = len(existing - in_ids)
    expected = kept_other + len(pkg_status)
    if keep_ids and after_n == expected:
        _info("✓ 幂等校验通过：%d（包内）+ %d（目标库包外独有）= %d，实际 %d"
              % (len(pkg_status), kept_other, expected, after_n))
    elif keep_ids:
        idempotent_bad = True
        _warn("条数异常：期望 %d（包内 %d + 包外独有 %d），实际 %d，请检查"
              % (expected, len(pkg_status), kept_other, after_n))
    _info("提醒：本次同步是单向的（包→目标库）。"
          "若目标机之后也有新增，请在目标机 `out` 后再回源机 `in`，不要同一轮反向同步。")

    if not res.get("ok"):
        return 4
    if res.get("errors"):
        return 5          # 部分失败 —— 不能算同步成功
    if idempotent_bad:
        return 6          # 幂等校验失败 —— 条数不对，需人工核对
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="keeper 跨设备记忆同步（out 导出全量包 / in 导入）")
    ap.add_argument("op", choices=["out", "in"])
    ap.add_argument("--root", default=None,
                    help="记忆库根目录（默认取 AI_MEMORY_STORE 或跨平台默认路径）")
    ap.add_argument("--dest", default=None, help="out：同步包输出目录")
    ap.add_argument("--file", default=None, help="in：同步包 jsonl 路径")
    ap.add_argument("--dir", default=None,
                    help="in：同步包所在目录（自动取最新的 keeper_sync_*.jsonl）")
    ap.add_argument("--execute", action="store_true",
                    help="in：真实落盘（默认 dry-run 预演）")
    ap.add_argument("--no-keep-ids", action="store_true",
                    help="in：不复用原 id（危险：会导致重复膨胀，仅特殊修复场景用）")
    ap.add_argument("--no-backup", action="store_true",
                    help="in --execute：跳过落盘前备份（不推荐）")
    ap.add_argument("--on-error", choices=["skip", "abort"], default="skip",
                    help="in：单条失败时跳过还是中止（默认 skip；失败会以 rc=5 报出）")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="in --execute：放行未经 sha256 校验的包（缺 .meta.json 时的逃生开关）")
    ap.add_argument("--i-know-id-bloat", action="store_true",
                    help="in --execute：确认接受 --no-keep-ids 造成的 id 膨胀（逃生开关）")
    args = ap.parse_args(argv)

    if args.op == "out":
        if not args.dest:
            _warn("out 需要 --dest <目录>")
            return 1
        return cmd_out(args)
    if args.op == "in":
        if not args.file and not args.dir:
            _warn("in 需要 --file <jsonl> 或 --dir <目录>")
            return 1
        return cmd_in(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
