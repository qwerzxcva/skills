# -*- coding: utf-8 -*-
"""
investment_bridge.py — 投资域（4 层模型）与外部数据源 / 工具链的「桥接入口」。

把分散在 docs 里承诺的命令落到实处：
seed   从外部数据源批量播种 L0 记忆（当前支持 investment 域：读 duckdb catalog 表）；
并幂等对齐投资域记忆的遗留 sub: 标签（老 sub: → topic:，补规范 sub:<subdomain> 镜像）。
graph  把投资域记忆的关联链路（数据→因子→测试→系统，含 consumes/test_of/composed_of/related_to）
渲染成单文件 SVG，便于一眼看清因子依赖了哪些数据、系统由哪些因子/测试组成。

设计约束（与 keeper 一致）：纯本地、零云端、无第三方绘图依赖（手写 SVG）。

用法：
python scripts/investment_bridge.py seed --domain investment [--db D:/.../unified_market.duckdb | --discover] [--dry-run]
python scripts/investment_bridge.py graph --around <记忆ID> [--hops 2] [--out investment_graph.svg]
python scripts/investment_bridge.py graph --subdomain system [--top 40] [--out sys_graph.svg]
"""
import os, sys, argparse, subprocess, json, collections

SK = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SK)
import memory_ops as mo

# 子域清单从 taxonomy.json 派生（单一事实源），避免与 references/investment_taxonomy.json 双份真相漂移。
_TAX_PATH = os.path.join(os.path.dirname(SK), "references", "investment_taxonomy.json")
def _load_inv_subdomains():
    try:
        with open(_TAX_PATH, encoding="utf-8") as f:
            d = json.load(f)
        for dom in d.get("domains", []):
            if dom.get("key") == "investment":
                subs = [s["key"] for s in dom.get("subdomains", []) if "key" in s]
                if subs:
                    return subs
    except Exception:
        pass
        # 兜底（与 taxonomy 保持一致）
    return ["data_catalog", "factor", "factor_test", "system",
            "data_integrity", "backtest_integrity"]
INV_SUBDOMAINS = _load_inv_subdomains()
CANON = set(INV_SUBDOMAINS)
EDGE_COLORS = {
    "consumes": "#165dff",       # 因子消费数据
    "test_of": "#f53f3f",        # 测试指向因子
    "composed_of": "#00b42a",    # 系统由…组成
    "related_to": "#86909c",     # 泛关联
}


# ───────────────────────── seed ─────────────────────────
def _align_investment_subdomain(root, apply=True):
    """把投资域记忆的遗留 sub: 标签对齐到规范：非规范的 sub:X → topic:X，
    并确保每条带规范镜像 sub:<subdomain>。幂等。返回 (变更数, [(id,old,new)])。"""
    idx = mo.load_index(root)
    entries = idx.get("entries", [])
    changed = []
    for e in entries:
        if e.get("domain") != "investment":
            continue
        mid = e["id"]
        sub = e.get("subdomain") or ""
        fp = os.path.join(mo.mem_dir(root), mid + ".json")
        if not os.path.exists(fp):
            fp = os.path.join(mo.archive_dir(root), mid + ".json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, encoding="utf-8") as _f:
                mem = json.load(_f)
        except Exception:
            continue
        old = list(mem.get("tags") or [])
        new = []
        for t in old:
            if t.startswith("sub:"):
                x = t[4:]
                new.append("sub:" + x if x == sub else "topic:" + x)
            else:
                new.append(t)
        if sub and ("sub:" + sub) not in new:
            new.append("sub:" + sub)
        if new != old:
            changed.append((mid, old, new))
            if apply:
                mem["tags"] = new
                # I4 修复：改用统一写入口 _save_mem（原子 tmp+os.replace + 句柄安全），
                # 不再用 json.dump(open) 直写导致崩溃写半截 JSON / 句柄泄漏。
                mo._save_mem(root, mid, mem)
                for ee in entries:
                    if ee["id"] == mid:
                        ee["tags"] = new
                        break
    if apply and changed:
        mo.save_index(root, idx)
    return len(changed), changed


    # ───────────────────────── taxonomy 合并（F8） ─────────────────────────
def _merge_investment_taxonomy(root):
    """F8：把 references/investment_taxonomy.json 的 investment 域合并进
    store/taxonomy.json，使声明的 heat_budget(22) 等真正生效（此前 cmd_seed 从不
    合并 → 预算死配置）。保留其它域；store 无 taxonomy 时基于 default 合并。"""
    try:
        with open(_TAX_PATH, encoding="utf-8") as f:
            src = json.load(f)
    except Exception:
        return 0
    inv = None
    for d in src.get("domains", []):
        if d.get("key") == "investment":
            inv = d
            break
    if inv is None:
        return 0
    try:
        tax = mo.load_taxonomy(root)
    except Exception:
        tax = {"version": 1, "domains": [], "fallback_domain": "general"}
    domains = list(tax.get("domains", []))
    replaced = False
    for i, d in enumerate(domains):
        if d.get("key") == "investment":
            merged = dict(d)
            for k in ("label", "description", "keywords", "heat_budget", "retention", "subdomains"):
                if k in inv:
                    merged[k] = inv[k]
            domains[i] = merged
            replaced = True
            break
    if not replaced:
        domains.append(inv)
    tax["domains"] = domains
    try:
        mo.save_taxonomy(root, tax)
        return 1
    except Exception as _e:
        sys.stderr.write("[mem_bridge] 合并 investment taxonomy 失败（heat_budget 可能不生效）: %s\n" % _e)
        return 0


def cmd_seed(args):
    if args.domain != "investment":
        sys.stderr.write("[mem_bridge] seed 目前仅支持 --domain investment（其它域规划中）。\n")
        return 2
    if not args.dry_run and not mo.check_writable(args.root):
        sys.stderr.write("[mem_bridge] 目标库不可写（root=%s），拒绝写入。\n" % args.root)
        return 2
    seed_py = os.path.join(SK, "investment_seed.py")
    cmd = [sys.executable, seed_py, "--root", args.root]
    if args.db:
        cmd += ["--db", args.db]
    if args.discover:
        cmd.append("--discover")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.table:
        cmd += ["--table", args.table]
    print("[mem_bridge] ① 播种 L0 投资记忆（duckdb catalog）…")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        return r.returncode
    if not args.no_align:
        print("[mem_bridge] ② 对齐投资域遗留 sub: 标签（幂等）…")
        n, _ = _align_investment_subdomain(args.root, apply=not args.dry_run)
        print("[mem_bridge] 对齐完成：%s 条%s。" %
              (n, "（dry-run 未落盘）" if args.dry_run else "已变更"))
        # F8：把投资分类树合并进 store/taxonomy.json，使 heat_budget(22) 等真正生效
        if not args.dry_run:
            m = _merge_investment_taxonomy(args.root)
            print("[mem_bridge] ③ 合并 investment 分类树到 store/taxonomy.json（heat_budget 生效）：%s"
                  % ("是" if m else "跳过/失败"))
    return 0


    # ───────────────────────── graph ─────────────────────────
def _load_investment_graph(root):
    """读全部投资域记忆文件，构建 {id: entry}、正向边 edges 与反向邻接 rev。"""
    idx = mo.load_index(root)
    nodes = {}
    edges = collections.defaultdict(lambda: collections.defaultdict(list))
    rev = collections.defaultdict(list)   # tgt -> [src]，供 --around 反向边 O(1) 查找
    for e in idx.get("entries", []):
        if e.get("domain") != "investment":
            continue
        nodes[e["id"]] = e
        # relations 在记忆文件里，按需读取
    for mid in nodes:
        fp = os.path.join(mo.mem_dir(root), mid + ".json")
        if not os.path.exists(fp):
            fp = os.path.join(mo.archive_dir(root), mid + ".json")
        if not os.path.exists(fp):
            continue
        try:
            m = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        rel = m.get("relations") or {}
        for etype, targets in rel.items():
            if etype in ("consumes", "test_of", "composed_of", "related_to"):
                for t in (targets or []):
                    if t in nodes:       # 只连投资域内部边
                        edges[mid][etype].append(t)
                        rev[t].append(mid)
    return nodes, edges, rev


def _bfs_ego(nodes, edges, rev, start, hops):
    seen = {start}
    frontier = {start}
    for _ in range(max(1, hops)):
        nxt = set()
        for u in frontier:
            for etype, tgts in edges.get(u, {}).items():
                for t in tgts:
                    if t not in seen:
                        seen.add(t)
                        nxt.add(t)
                        # 反向边（被谁消费/测试/组成）：走 rev 邻接表 O(1)，不再全表扫描
            for v in rev.get(u, []):
                if v not in seen:
                    seen.add(v)
                    nxt.add(v)
        frontier = nxt
    return seen


def _svg_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _render_svg(nodes, edges, selected, out, title):
    sel = [n for n in selected if n in nodes]
    # 按 subdomain 分列布局
    col_of = {s: i for i, s in enumerate(INV_SUBDOMAINS)}
    col_x = {}
    counts = collections.Counter(nodes[n].get("subdomain") or "?" for n in sel)
    col_cursor = collections.Counter()
    pos = {}
    for n in sel:
        s = nodes[n].get("subdomain") or "?"
        c = col_of.get(s, len(INV_SUBDOMAINS))
        y = 40 + col_cursor[c] * 46
        col_cursor[c] += 1
        x = 60 + c * 240
        pos[n] = (x, y)
    H = 40 + max(list(col_cursor.values()) + [1]) * 46 + 40
    W = 60 + (len(INV_SUBDOMAINS) + 1) * 240
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">' % (W, H),
             '<rect width="100%" height="100%" fill="#0f1115"/>',
             '<text x="20" y="24" fill="#e5e6eb" font-size="16" font-family="sans-serif">%s</text>'
             % _svg_escape(title)]
    # 列标题
    for s, c in col_of.items():
        x = 60 + c * 240
        lines.append('<text x="%d" y="38" fill="#86909c" font-size="12" font-family="sans-serif">%s (%d)</text>'
                     % (x, _svg_escape(s), counts.get(s, 0)))
        # 边
    for u in sel:
        ux, uy = pos[u]
        for etype, tgts in edges.get(u, {}).items():
            for t in tgts:
                if t not in pos:
                    continue
                tx, ty = pos[t]
                color = EDGE_COLORS.get(etype, "#86909c")
                lines.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.5" opacity="0.7"/>'
                             % (ux, uy, tx, ty, color))
                # 节点
    for n in sel:
        x, y = pos[n]
        s = nodes[n].get("subdomain") or "?"
        fill = "#1f2329" if s != "?" else "#2a2f36"
        stroke = "#165dff" if s == "data_catalog" else "#00b42a" if s == "system" else \
                 "#f53f3f" if s == "backtest_integrity" else "#ff7d00" if s == "factor_test" else \
                 "#722ed1" if s == "data_integrity" else "#86909c"
        label = _svg_escape((nodes[n].get("summary") or n)[:22])
        lines.append('<g><rect x="%d" y="%d" width="210" height="34" rx="6" fill="%s" stroke="%s" stroke-width="1.5"/>'
                     % (x - 105, y - 17, fill, stroke))
        lines.append('<text x="%d" y="%d" fill="#e5e6eb" font-size="11" font-family="sans-serif">%s</text>'
                     % (x - 98, y - 2, label))
        lines.append('<text x="%d" y="%d" fill="#86909c" font-size="9" font-family="sans-serif">%s</text>'
                     % (x - 98, y + 11, _svg_escape(n)))
        lines.append('</g>')
    lines.append('</svg>')
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(sel)


def cmd_graph(args):
    if args.domain != "investment":
        sys.stderr.write("[mem_bridge] graph 目前仅支持 --domain investment。\n")
        return 2
    nodes, edges, rev = _load_investment_graph(args.root)
    total_edges = sum(len(t) for u in edges.values() for t in u.values())
    print("[mem_bridge] 投资域节点 %d，内部边 %d。" % (len(nodes), total_edges))

    if args.around:
        if args.around not in nodes:
            sys.stderr.write("[mem_bridge] 记忆 %s 不在投资域或不存在。\n" % args.around)
            return 2
        sel = _bfs_ego(nodes, edges, rev, args.around, args.hops)
        title = "投资链路 ego-graph · %s (hops=%d)" % (args.around, args.hops)
    elif args.subdomain:
        if args.subdomain not in CANON:
            sys.stderr.write("[mem_bridge] --subdomain 须为 %s 之一。\n" % INV_SUBDOMAINS)
            return 2
        cand = [n for n in nodes if (nodes[n].get("subdomain") or "") == args.subdomain]
        # 取该子域节点 + 其跨子域边涉及的邻居，按 --top 截断
        sel = set(cand)
        for n in cand:
            for tgts in edges.get(n, {}).values():
                sel.update(tgts)
                # 若仍过大，优先保留该子域节点，邻居按出现顺序截断
        if args.top and len(sel) > args.top:
            keep = [n for n in sel if (nodes[n].get("subdomain") or "") == args.subdomain][:args.top]
            extra = [n for n in sel if n not in keep]
            sel = set(keep) | set(extra[:max(0, args.top - len(keep))])
        title = "投资链路 · subdomain=%s (top=%s)" % (args.subdomain, args.top or "all")
    else:
        sys.stderr.write("[mem_bridge] 请指定 --around <ID> 或 --subdomain <s>。\n")
        return 2

    n = _render_svg(nodes, edges, sel, args.out, title)
    print("[mem_bridge] 已渲染 %d 个节点 → %s" % (n, os.path.abspath(args.out)))
    return 0


def main():
    ap = argparse.ArgumentParser(description="记忆↔外部数据源桥接入口")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("seed", help="从外部数据源播种 L0 记忆并对齐子域标签")
    s.add_argument("--domain", default="investment")
    s.add_argument("--root", default=mo._default_root())
    s.add_argument("--db", default="")
    s.add_argument("--discover", action="store_true")
    s.add_argument("--table", default="")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-align", action="store_true", help="跳过遗留 sub: 标签对齐")
    s.set_defaults(func=cmd_seed)

    g = sub.add_parser("graph", help="渲染投资域关联链路 SVG")
    g.add_argument("--domain", default="investment")
    # S7 修复：默认根目录走 memory_ops 的零配置默认值（尊重 AI_MEMORY_STORE 环境变量 + 跨平台回退），
    # 不硬编码机器路径（换盘/换机改 AI_MEMORY_STORE 或 ~/.keeper/store_root 即可）。
    g.add_argument("--root", default=mo.DEFAULT_ROOT)
    g.add_argument("--around", default="", help="以某记忆为中心画 ego 子图")
    g.add_argument("--hops", type=int, default=2)
    g.add_argument("--subdomain", default="")
    g.add_argument("--top", type=int, default=40)
    g.add_argument("--out", default="investment_graph.svg")
    g.set_defaults(func=cmd_graph)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
