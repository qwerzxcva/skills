# -*- coding: utf-8 -*-
"""keeper_import.py —— 批量导入记忆。

从 JSONL / JSON / CSV / Markdown 文件批量导入记忆到 keeper 库。
- 复用 memory_ops.deposit 全流程（去重 / 自动连边 / 分类一致）。
- 批量 defer_index=True + 末尾 flush_memory_index 一次落盘（大批量高性能）。
- 默认 dry-run 预览（只解析+校验，不写库），必须加 --execute 才真实写入；与 delete 闸门
风格一致，防止批量导入手滑污染真实库。
- 支持 --keep-ids 复用原 id（默认新生成，避免跨库 id 冲突）、--on-error skip|abort、
--report 导出逐条结果 JSON。

字段映射（每条记录，键名大小写不敏感）：
必须：summary（缺则回退 text / body）
可选：category, tags(列表或逗号串), body, type, tier, scope, project,
about_axis, domain, subdomain, scene, state, priority, area,
importance, confidence, id

兼容 keeper 自有 `export --format jsonl` 的整对象（含 id/type/tier/tags 列表/...），
round-trip 友好（默认新 id，--keep-ids 复用）。

用法：
python scripts/keeper_import.py --root <store> --file in.jsonl [--format auto]
python scripts/keeper_import.py --root <store> --file in.jsonl --execute
python scripts/keeper_import.py --root <store> --file in.csv --execute --keep-ids --on-error abort
"""
import os
import sys
import re
import json
import csv
import argparse
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import memory_ops as mo  # noqa: E402


def _coerce_tags(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple, set)):
        return ",".join(str(x) for x in v if x is not None)
    return str(v)


def _coerce_float(v):
    """CSV 字段全是字符串；把 importance/confidence 安全转 float，非法值→None（不崩溃）。

    不转的话字符串 "0.8" 进 deposit 会被当序列做乘法，抛
    'can't multiply sequence by non-int of type 'float''，整条导入失败。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def _read_text(path):
    """统一文本读取：先试 UTF-8（含 BOM 自动剥离），再试 GBK（Excel 常见导出编码）。

    两者皆失败才抛清晰的编码错误，避免被误判为 parse_error（B2），
    也避免 BOM 污染首列导致整批静默丢数据（B1）。"""
    last_err = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError as e:
            last_err = e
    raise ValueError(
        "文件编码无法识别（已尝试 UTF-8/UTF-8-BOM/GBK 均失败，疑似 UTF-16/ISO-8859 等）："
        "%s。请用 UTF-8 或 GBK 重新保存后再导入。" % last_err)


def _sniff_format(path, fmt):
    if fmt and fmt != "auto":
        return fmt
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if ext == ".json":
        return "json"
    if ext == ".csv":
        return "csv"
    if ext in (".md", ".markdown"):
        return "md"
        # 内容嗅探
    try:
        head = _read_text(path)[:4096]
    except ValueError:
        return "jsonl"
    first = None
    for line in head.splitlines():
        s = line.strip()
        if s:
            first = s
            break
    if first is None:
        return "jsonl"
    if first.startswith("## "):
        return "md"
    if first.startswith("{") or first.startswith("["):
        nl = [l.strip() for l in head.splitlines() if l.strip()]
        obj_lines = sum(1 for l in nl if l.startswith("{") or l.startswith("["))
        return "jsonl" if obj_lines >= 2 else "json"
    return "csv"


def _read_head(path, n=4096):
    try:
        return _read_text(path)[:n]
    except ValueError:
        return ""


def _parse_jsonl(path, on_error="skip"):
    recs = []
    skipped = 0
    try:
        text = _read_text(path)
    except ValueError as e:
        raise ValueError("JSONL 文件读取失败：%s" % e)
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        try:
            recs.append(json.loads(s))
        except json.JSONDecodeError as e:
            if on_error == "abort":
                raise ValueError("第 %d 行 JSON 解析失败: %s" % (ln, e))
            skipped += 1
    return recs, skipped


def _parse_json(path):
    try:
        data = json.loads(_read_text(path))
    except ValueError as e:
        raise ValueError("JSON 文件读取/解析失败：%s" % e)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 允许 {"memories": [...]} 或单个对象
        if "memories" in data and isinstance(data["memories"], list):
            return data["memories"]
        return [data]
    raise ValueError("JSON 根必须是 数组 或 含 memories 数组的对象")


def _parse_csv(path):
    import io
    try:
        text = _read_text(path)
    except ValueError as e:
        raise ValueError("CSV 文件读取失败：%s" % e)
    reader = csv.DictReader(io.StringIO(text))
    recs = []
    for row in reader:
        recs.append({k: (v if v is not None else "") for k, v in row.items()})
    return recs


# v4.9.1：md 往返摘要修复（跨设备同步实测 P0）。
# 旧版 `export --format md` 标题只写 "## <id>"，import 把 id 当成 summary →
# 导入后所有记忆摘要变成 "LRN-20260801-001" 这类 id，正文虽在但摘要语义全丢。
# 现在按优先级取摘要：
#   1) meta 行里的「摘要: x」——v4.9.1+ 导出的 md（最可靠，支持含 '·' 的摘要）
#   2) 标题 "## <id> · <summary>" 拆分出的右侧（learnings 格式 / 手写 md）
#   3) 正文前 120 字（_normalize 兜底，旧版 md 走这条）
_META_SUMMARY_RE = re.compile(
    r"摘要\s*:\s*(.*?)(?=\s+·\s+(?:摘要|分类|类型|层级|标签|创建)\s*:|$)")
# 记忆 id 形态：LRN-20260801-001 / mem_xxx / 纯数字串等（无空格、无中文）
_ID_LIKE_RE = re.compile(r"^[A-Za-z0-9_\-\.:]{4,64}$")


def _split_md_title(title):
    """解析 md 二级标题 → (id|None, summary|None)。

    三种形态：
      1) '## LRN-20260801-001'（整串就是 id，旧版 export md）→ (id, None)
      2) '## LRN-20260801-004 · 这是摘要'（learnings）→ (id, summary)
      3) '## 关于记忆系统 · 一些想法'（普通中文标题）→ (None, 整串)——不拆，
         避免把正常标题里的 '·' 误当 id 分隔符。
    """
    t = title.strip()
    if _ID_LIKE_RE.match(t):
        return (t, None)
    for sep in (" · ", "·"):
        if sep in t:
            left, right = t.split(sep, 1)
            left, right = left.strip(), right.strip()
            if _ID_LIKE_RE.match(left):
                return (left, right or None)
            break
    return (None, t)


# v4.9.2：md 往返「条目头」判定（P0 修复）。
# 旧实现把**任何**以 '## ' 开头的行都当成一个新记忆条目，于是记忆正文里自带的
# markdown 小标题（'## 工作流'、'## 反模式' 等）会被解析成新条目 —— 一次
# export→import 往返就能把 1 条长记忆炸成多条碎片，并写入新 id 污染记忆库。
# 真实库实测：156 条真记忆的 md 里有 220 个 '## '，其中 64 个是正文标题碎片。
_META_KEY_TOKENS = ("摘要:", "分类:", "类型:", "层级:", "标签:", "创建:")


def _is_entry_head(lines, idx):
    """判定 lines[idx]（须以 '## ' 开头）是否为一条记忆的条目头。

    双锚点判定（满足其一即为条目头）：
      A1 标题首段是 id —— export md 写 '## <id>'，learnings 写 '## <id> · <摘要>'。
         附加约束「至少含一个字母」：否则 '## 2026-09-08' 这类正文日期标题会
         被误判成新条目（id 正则本身允许纯数字）。
      A2 紧随其后（跳过空行）是 '> ' meta 行，且含 keeper 特征键（摘要/分类/...）。
         兜住「手写 md 标题不是 id」但仍带 keeper meta 行的场景。

    二者皆不满足 → 视为记忆正文自带的 markdown 标题，归入上一条记忆的 body。
    代码围栏（```）内的 '## ' 由调用方直接排除，不进本函数。
    """
    title = lines[idx][3:].strip()
    head = title.split(" · ", 1)[0].strip()
    if _ID_LIKE_RE.match(head) and any(c.isalpha() for c in head):
        return True
    j = idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j < len(lines) and lines[j].startswith("> "):
        m = lines[j][2:]
        if any(tok in m for tok in _META_KEY_TOKENS):
            return True
    return False


def _parse_md(path):
    """解析 keeper export --format md 输出：## <id> [· summary] + > meta + body。
    尽力而为：meta 行提取 摘要/分类/类型/层级/标签/创建。

    v4.9.2：'## ' 需通过 _is_entry_head 双锚点判定才算条目头，正文内的
    markdown 标题不再被误拆成新记忆；代码围栏内的 '## ' 一律视为正文。"""
    recs = []
    try:
        text = _read_text(path)
    except ValueError as e:
        raise ValueError("Markdown 文件读取失败：%s" % e)
    lines = text.split("\n")
    cur = None
    buf = []
    meta = {}
    fence = False          # 是否处于 ``` 代码围栏内（围栏内的 '## ' 只是代码注释）
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # 代码围栏状态优先更新，围栏行本身照常归入正文
        if line.lstrip().startswith("```"):
            fence = not fence
            if cur is not None and line.strip() != "---":
                buf.append(line)
            i += 1
            continue
        if line.startswith("## ") and not fence and _is_entry_head(lines, i):
            if cur is not None:
                cur["body"] = "\n".join(buf).strip()
                recs.append(cur)
            title = line[3:].strip()
            _tid, _tsum = _split_md_title(title)
            # 标题可能是纯 id（旧版 export）→ 此时 summary 留空，交给 body 前 120 字兜底
            cur = {"summary": _tsum or ""}
            if _tid:
                cur["id"] = _tid
            meta = {}
            buf = []
            i += 1
            continue
        if line.startswith("> ") and cur is not None:
            m = line[2:].strip()
            # v4.9.1+：正则先取摘要（非贪婪，允许摘要内含 '·'）
            _ms = _META_SUMMARY_RE.search(m)
            if _ms and _ms.group(1).strip():
                cur["summary"] = _ms.group(1).strip()
            # "摘要: s · 分类: x · 类型: y · 层级: z · 标签: a, b · 创建: ..."
            for part in m.split("·"):
                part = part.strip()
                if ":" in part:
                    k, v = part.split(":", 1)
                    meta[k.strip()] = v.strip()
            cur["category"] = meta.get("分类", "")
            cur["type"] = meta.get("类型", "")
            cur["tier"] = meta.get("层级", "")
            if meta.get("标签"):
                cur["tags"] = [t.strip() for t in meta["标签"].split(",") if t.strip()]
            i += 1
            continue
        if cur is not None:
            if line.strip() == "---":
                i += 1
                continue
            buf.append(line)
        i += 1
    if cur is not None:
        cur["body"] = "\n".join(buf).strip()
        recs.append(cur)
    return recs


def _parse_records(path, fmt, on_error="skip"):
    fmt = _sniff_format(path, fmt)
    if fmt == "jsonl":
        return _parse_jsonl(path, on_error)
    if fmt == "json":
        return _parse_json(path), 0
    if fmt == "csv":
        return _parse_csv(path), 0
    if fmt == "md":
        return _parse_md(path), 0
    raise ValueError("不支持的格式: %s（支持 jsonl/json/csv/md）" % fmt)


def _normalize(rec):
    """键名大小写不敏感归一 + 抽取 summary 兜底。"""
    if not isinstance(rec, dict):
        return None
    low = {k.lower(): v for k, v in rec.items()}
    # v4.9.1：summary 缺失时不再把整个 body 当摘要（旧行为会让摘要变成几千字正文），
    # 统一截断为前 120 字，保证 summary 语义成立。
    summary = (low.get("summary") or low.get("text") or "").strip()
    body = (low.get("body") or "").strip()
    if not summary and body:
        summary = body[:120]
    if not summary and not body:
        return None
    return {
        "summary": summary,
        "body": body,
        "category": low.get("category") or "",
        "tags": _coerce_tags(low.get("tags")),
        "type": low.get("type") or "",
        "tier": low.get("tier") or "",
        "scope": low.get("scope") or None,
        "project": low.get("project") or "",
        "about_axis": low.get("about_axis") or None,
        "domain": low.get("domain") or None,
        "subdomain": low.get("subdomain") or None,
        "scene": low.get("scene") or None,
        "state": low.get("state") or None,
        "priority": low.get("priority") or None,
        "area": low.get("area") or None,
        "importance": _coerce_float(low.get("importance")),
        "confidence": _coerce_float(low.get("confidence")),
        "id": low.get("id") or None,
    }


def _emit_report(report, summary, results):
    """把导入摘要+逐条结果写出 JSON 报告（异常分支也保证可追溯）。

    写失败给出明确 stderr 警告而非静默吞（O7）——避免掩盖真实错误。"""
    if not report:
        return
    try:
        with open(report, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "items": results}, f,
                      ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("WARN: 写入导入报告 %s 失败: %s\n" % (report, e))


        # O5：逐条 results 列表无界增长防护——超大批量文件（数十万行）可能吃内存。
        # 超过上限后只保留「失败/隔离」明细（安全相关必留），成功项截断并标记，
        # 真实总量由 results_total 暴露，调用方/报告据此判断，不破坏小批量契约。
RESULTS_CAP = 5000


def run_import(root, path, fmt="auto", dry_run=False, keep_ids=False,
               on_error="skip", report=None):
    if not os.path.exists(path):
        out = {"ok": False, "error": "file_not_found", "path": path}
        _emit_report(report, out, [])
        return out
    try:
        raw, parse_errors = _parse_records(path, fmt, on_error)
    except ValueError as e:
        out = {"ok": False, "error": "parse_error", "msg": str(e)}
        _emit_report(report, out, [])
        return out

    norm = []
    dropped = 0
    dropped_reasons = []
    for r in raw:
        n = _normalize(r)
        if n is None:
            # B4/C3：非字典 / 缺 summary+body 的记录被静默丢弃→改为计数暴露，
            # 不再无感知丢数据。
            dropped += 1
            dropped_reasons.append(
                "non-dict record" if not isinstance(r, dict) else "missing summary/body")
            continue
        norm.append(n)

    if not dry_run:
        mo.init_store(root)

    imported = errors = quarantined = 0
    results = []
    results_total = 0

    def _add_result(entry, always=False):
        # O5：成功项超 RESULTS_CAP 后截断（防内存膨胀）；隔离/错误必留（安全相关）。
        nonlocal results_total
        results_total += 1
        if always or len(results) < RESULTS_CAP:
            results.append(entry)

    for i, n in enumerate(norm):
        try:
            if dry_run:
                imported += 1
                _add_result({"ok": True, "dry_run": True,
                             "summary": n["summary"][:40]})
                continue
            res = mo.deposit(
                root,
                category=n["category"] or "imported",
                summary=n["summary"],
                tags=n["tags"],
                body=n["body"],
                tier=n["tier"] or "working",
                scope=n["scope"],
                project=n["project"],
                about_axis=n["about_axis"],
                domain=n["domain"],
                subdomain=n["subdomain"],
                mem_type=n["type"],
                importance=n["importance"],
                confidence=n["confidence"],
                auto_link=False,            # 批量内不逐条连边，flush 时统一
                defer_index=True,           # 批量延迟索引，末尾一次落盘
                recorded_by="import",
                state=n["state"],
                priority=n["priority"],
                area=n["area"],
                scene=n["scene"],
                sensitive_action="quarantine",
                mid=(n["id"] if keep_ids else None),
            )
            # deposit 命中敏感时返回 {ok:False, quarantined:True, qid} 字典，
            # 不能当成功计数——如实标记为「已隔离待复审」。
            # B5：隔离是成功的安全结果，不触发 --on-error abort（abort 仅对真实写入错误）。
            if isinstance(res, dict) and (res.get("quarantined") or res.get("ok") is False):
                quarantined += 1
                _add_result({"ok": False, "quarantined": True,
                             "qid": res.get("qid"),
                             "summary": n["summary"][:40]}, always=True)
                continue
                # 正常写入返回字符串 id；个别路径可能返回 {ok:True, id} 字典，兼容提取
            mid = res if isinstance(res, str) else (res.get("id") if isinstance(res, dict) else None)
            imported += 1
            _add_result({"ok": True, "summary": n["summary"][:40], "id": mid})
        except Exception as e:  # noqa: BLE001
            errors += 1
            _add_result({"ok": False, "error": str(e)[:200],
                         "summary": n["summary"][:40]}, always=True)
            if on_error == "abort":
                break

    if not dry_run and imported > 0:
        try:
            mo.flush_memory_index(root, auto_link=False)
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": "flush_failed", "msg": str(e),
                   "total_parsed": len(raw), "normalized": len(norm),
                   "dropped": dropped, "imported": imported,
                   "quarantined": quarantined, "errors": errors,
                   "results": results, "results_total": results_total,
                   "results_truncated": results_total > RESULTS_CAP,
                   "root": root}
            _emit_report(report, out, results)
            return out

    # v4.9.1：默认 dry-run 是防手滑设计，不做改动；但必须在输出与 stderr 双向提示，
    # 避免「跑完了以为导入成功、其实一条没写」（跨设备同步实测踩坑）。
    _hint = None
    if dry_run:
        _hint = ("DRY-RUN 预演完成：本次未写入任何记忆。"
                 "确认条数与摘要无误后，加 --execute 重新执行才真正落盘。")
        sys.stderr.write("HINT: %s\n" % _hint)
    out = {
        "ok": True,
        "dry_run": dry_run,
        "hint": _hint,
        "total_parsed": len(raw),
        "normalized": len(norm),
        "dropped": dropped,
        "dropped_reasons": dropped_reasons,
        "imported": imported,
        "quarantined": quarantined,
        "errors": errors,
        "parse_errors": parse_errors,
        "results": results,
        "results_total": results_total,
        "results_truncated": results_total > RESULTS_CAP,
        "root": root,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if report:
        with open(report, "w", encoding="utf-8") as f:
            json.dump({"summary": out, "items": results}, f,
                      ensure_ascii=False, indent=2)
        out["report"] = report
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="keeper 批量导入记忆（JSONL/JSON/CSV/MD → deposit）")
    ap.add_argument("--root", default=mo.DEFAULT_ROOT,
                    help="记忆根目录（默认跨平台零配置路径）")
    ap.add_argument("--file", required=True, help="待导入文件路径")
    ap.add_argument("--format", default="auto",
                    help="auto/jsonl/json/csv/md（默认 auto 按扩展名/内容嗅探）")
    ap.add_argument("--execute", action="store_true",
                    help="真实写入记忆库（默认仅 dry-run 预览，不写库）")
    ap.add_argument("--keep-ids", action="store_true",
                    help="复用记录原 id（默认新生成，避免跨库冲突）")
    ap.add_argument("--on-error", choices=["skip", "abort"], default="skip",
                    help="遇错策略（默认 skip 跳过继续）")
    ap.add_argument("--report", default=None,
                    help="逐条结果 JSON 报告输出路径")
    args = ap.parse_args(argv)
    res = run_import(args.root, args.file, fmt=args.format,
                     dry_run=not args.execute, keep_ids=args.keep_ids,
                     on_error=args.on_error, report=args.report)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
