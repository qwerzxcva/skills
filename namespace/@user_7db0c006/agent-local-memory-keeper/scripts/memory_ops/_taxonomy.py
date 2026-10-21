# Auto-extracted submodule: _taxonomy
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _taxonomy_path(root):
    """taxonomy.json 与 index.db 同根 store/。"""
    return os.path.join(root, "store", "taxonomy.json")

def default_taxonomy():
    """无 taxonomy.json 时的兜底定义：等价于 行为（4 个已知域 + general 兜底）。"""
    return {
        "version": 1,
        "created": None,
        "user_profile": {"name": None, "roles": [], "scenarios": []},
        "domains": [{"key": d, "label": d, "description": "", "keywords": [],
                     "heat_budget": None, "retention": None, "subdomains": []}
                    for d in KNOWN_DOMAINS],
        "fallback_domain": "general",
    }

def validate_taxonomy(tax):
    """校验 + 归一化 taxonomy。返回归一化 dict；非法返回 None（便于 load 静默兜底，不抛）。"""
    if not isinstance(tax, dict):
        return None
    domains = tax.get("domains")
    if not isinstance(domains, list) or not domains:
        return None
    norm_domains, seen = [], set()
    for d in domains:
        if not isinstance(d, dict) or not d.get("key"):
            return None
        key = str(d["key"]).strip()
        if not key or key in seen:
            return None
        seen.add(key)
        norm_subs, sub_seen = [], set()
        for s in (d.get("subdomains") or []):
            if isinstance(s, dict) and s.get("key"):
                sk = str(s["key"]).strip()
                if sk and sk not in sub_seen:
                    sub_seen.add(sk)
                    norm_subs.append({"key": sk,
                                      "label": str(s.get("label") or sk),
                                      "keywords": [str(k) for k in (s.get("keywords") or []) if k]})
        norm_domains.append({
            "key": key,
            "label": str(d.get("label") or key),
            "description": str(d.get("description") or ""),
            "keywords": [str(k) for k in (d.get("keywords") or []) if k],
            "heat_budget": (int(d["heat_budget"]) if isinstance(d.get("heat_budget"), int)
                            and d["heat_budget"] > 0 else None),
            "retention": (d.get("retention") if isinstance(d.get("retention"), dict) else None),
            "subdomains": norm_subs,
        })
    fb = tax.get("fallback_domain") or "general"
    return {
        "version": int(tax.get("version") or 1),
        "created": tax.get("created"),
        "user_profile": (tax.get("user_profile") if isinstance(tax.get("user_profile"), dict)
                         else {"name": None, "roles": [], "scenarios": []}),
        "domains": norm_domains,
        "fallback_domain": str(fb),
    }

def load_taxonomy(root, silent=True):
    """读 store/taxonomy.json；不存在/损坏/非法 → default_taxonomy。"""
    p = _taxonomy_path(root)
    if not os.path.isfile(p):
        return default_taxonomy()
    try:
        with open(p, "r", encoding="utf-8") as f:
            tax = json.load(f)
        return validate_taxonomy(tax) or default_taxonomy()
    except Exception:
        if not silent:
            raise
        return default_taxonomy()

def save_taxonomy(root, tax):
    """写 store/taxonomy.json（原子写：先 .tmp 再 replace）。写前校验，失败抛 ValueError。"""
    norm = validate_taxonomy(tax)
    if norm is None:
        raise ValueError("taxonomy 校验失败，拒绝写入")
    p = _taxonomy_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p

def taxonomy_domain_keys(tax):
    """返回所有域 key（供路由/渲染使用）。"""
    return [d["key"] for d in (tax or {}).get("domains", [])]

def domain_heat_budget(tax, domain, default_cap):
    """返回某域热位配额：taxonomy 中该域有 heat_budget 则用之，否则 default_cap。

    v3.5 P4 防稀释：该值取代 reflect_v30/recall_v30 的 per-type 配额，
    让高频专属域（如 quant）始终保住自己的热位，不被通用问题淹没。"""
    if not domain:
        return default_cap
    for d in (tax or {}).get("domains", []):
        if d.get("key") == domain:
            hb = d.get("heat_budget")
            if isinstance(hb, int) and hb > 0:
                return hb
            return default_cap
    return default_cap

def domain_retention(tax, domain, default_stale, default_floor):
    """返回 (stale_days, protection_floor) 给某域。

    v3.5 P4 防稀释 / 差异化遗忘：taxonomy 中该域有 retention 则覆盖默认，否则退化为
    全局默认（stale_days=90 / 保护线=0.9）。
    - stale_days 越大 → 该域越「耐忘」（更晚触发降级/衰减）；
    - protection_floor 越低 → 越多记忆被保护（同样更耐忘）；越高 → 更积极归档。
    无 taxonomy 时与 行为完全一致。"""
    if not domain:
        return default_stale, default_floor
    for d in (tax or {}).get("domains", []):
        if d.get("key") == domain:
            ret = d.get("retention") if isinstance(d.get("retention"), dict) else {}
            sd = default_stale
            if isinstance(ret.get("stale_days"), int) and ret["stale_days"] > 0:
                sd = ret["stale_days"]
            fl = default_floor
            if isinstance(ret.get("min_importance"), (int, float)):
                fl = float(ret["min_importance"])
            return sd, fl
    return default_stale, default_floor

def taxonomy_has_budget(tax):
    """taxonomy 是否定义了任何域 heat_budget（决定是否启用每域配额路径）。"""
    return any(isinstance(d.get("heat_budget"), int) and d.get("heat_budget") > 0
               for d in (tax or {}).get("domains", []))

def taxonomy_budget_map(tax):
    """返回 {domain_key: heat_budget} 仅含显式设了 budget 的域（供 recall/reflect 快速查）。"""
    return {d["key"]: int(d["heat_budget"])
            for d in (tax or {}).get("domains", [])
            if isinstance(d.get("heat_budget"), int) and d.get("heat_budget") > 0}

def taxonomy_route(text, taxonomy):
    """按 taxonomy 关键词两阶段匹配：子域优先（更具体），再顶层域；命中返回 (domain, subdomain)，否则 (None, None)。

    纯函数（无副作用），供 `reclassify_by_taxonomy` 与 `_deposit_impl` 自动路由复用。
    advisory 语义由调用方决定：返回 (None, None) 时调用方保留原分类，绝不强行落到 fallback。"""
    matchers = []
    for d in taxonomy.get("domains", []):
        dk = d["key"]
        dkws = [k for k in (d.get("keywords") or []) if k]
        if dkws:
            matchers.append((dk, None, dkws))
        for s in d.get("subdomains") or []:
            sk = s["key"]
            skws = [k for k in (s.get("keywords") or []) if k] or dkws
            if skws:
                matchers.append((dk, sk, skws))
                # 阶段一：子域优先
    best_sub = None
    for dk, sk, kws in matchers:
        if sk is None:
            continue
        score = sum(1 for kw in kws if kw and kw in text)
        if score and (best_sub is None or score > best_sub[0]):
            best_sub = (score, dk, sk)
    if best_sub:
        return best_sub[1], best_sub[2]
        # 阶段二：顶层域
    best_top = None
    for dk, sk, kws in matchers:
        if sk is not None:
            continue
        score = sum(1 for kw in kws if kw and kw in text)
        if score and (best_top is None or score > best_top[0]):
            best_top = (score, dk, None)
    if best_top:
        return best_top[1], None
    return None, None

def reclassify_by_taxonomy(root, taxonomy=None, dry_run=False):
    """按 taxonomy 关键词把现有活跃记忆重路由到用户自定义域/子域（advisory 模式）。

    - 先匹配最具体的子域关键词，再匹配顶层域关键词，命中即覆盖原 domain/subdomain；
    - 未命中 taxonomy 任何域 → 保留原 domain（advisory：绝不强行把 work/investment 等既定
    分类误推到 fallback，避免破坏通用记忆）；
    - 同时把 subdomain 落进 mem 字典（新增字段，向后兼容 _save_mem 全量写回）并同步 `sub:`
    标签（recall --tag sub: 可用，无需等 P3 自动路由即可享受子域检索）；
    - dry_run=True 只返回变更计划不写盘（引导期必用，先预览再确认）。
    返回 {changes, summary, taxonomy_keys}。"""
    if taxonomy is None:
        taxonomy = load_taxonomy(root)
    tax_keys = set(taxonomy_domain_keys(taxonomy))
    fb = taxonomy.get("fallback_domain", "general")
    # 匹配逻辑统一交给纯函数 taxonomy_route（见上方），避免与 _deposit_impl 自动路由双份实现。
    mems = _all_mems(root)
    changes = []
    n_active = 0
    for mid, mem in mems.items():
        if mem.get("status") != "active":
            continue
        n_active += 1
        text = " ".join([
            (mem.get("summary") or ""),
            (mem.get("category") or ""),
            " ".join(mem.get("tags") or []),
            (mem.get("body") or "")[:400],
        ])
        # 两阶段匹配（复用 taxonomy_route 纯函数：子域优先→顶层域，advisory 语义）
        new_dom, new_sub = taxonomy_route(text, taxonomy)
        if new_dom is None:
            new_dom, new_sub = mem.get("domain"), mem.get("subdomain")
        old_dom = mem.get("domain")
        old_sub = mem.get("subdomain")
        if new_dom != old_dom or new_sub != old_sub:
            changes.append({
                "id": mid,
                "summary": (mem.get("summary") or "")[:40],
                "old_domain": old_dom, "new_domain": new_dom,
                "old_subdomain": old_sub, "new_subdomain": new_sub,
            })
            if not dry_run:
                mem["domain"] = new_dom
                if new_sub is not None:
                    mem["subdomain"] = new_sub
                elif "subdomain" in mem:
                    mem.pop("subdomain")
                tags = [t for t in (mem.get("tags") or []) if not t.startswith("sub:")]
                if new_sub:
                    tags.append("sub:%s" % new_sub)
                mem["tags"] = tags
                _save_mem(root, mid, mem)
    # 补全：文件改动后必须回灌索引（domain/subdomain/tags 都是 recall 硬过滤字段）。
    # 旧版漏掉这一步 → recall --subdomain / --tag sub: 静默错乱（文档 190-191 行承诺的行为实际未生效）。
    if not dry_run:
        _sync_index(root)
    return {
        "changes": changes,
        "summary": {"total_active": n_active, "changed": len(changes),
                    "dry_run": dry_run, "fallback_domain": fb},
        "taxonomy_keys": sorted(tax_keys),
    }

