# Auto-extracted submodule: _converse
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _save_llm_config(root, cfg):
    """原子写 config.json 的 llm 块（保留文件其他字段）。"""
    p = _llm_config_path(root)
    base = {"version": 1}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                base = json.load(f)
        except Exception:
            pass
            # 只保留已知字段，避免脏写
    known = {"enabled", "backend", "base_url", "model", "api_key_env",
             "max_suggestions", "batch_size", "temperature",
             "auto_apply_safe"}  # v3.1.4 P0-3
    base["llm"] = {k: cfg[k] for k in known if k in cfg}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

def _probe_llm(cfg):
    """探测 LLM 端点可达性（GET /models）。不可达/异常返回 False。"""
    try:
        import urllib.request
        base = (cfg.get("base_url") or "http://localhost:11434/v1").rstrip("/")
        url = base + "/models"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False

def _llm_hardware_requirements():
    """推荐硬件配置要求（三档）。安全版默认本地 LLM 优先，故列清楚配置门槛。"""
    return {
        "minimum": {"ram_gb": "8-16", "vram_gb": "0（纯 CPU 可跑）", "disk_gb": "~5（7B Q4 量化）",
                    "experience": "小库可用，大库偏慢（几 token/秒）"},
        "comfort": {"ram_gb": "16-32", "vram_gb": "6-8", "disk_gb": "8-12（14B 量化）",
                    "experience": "几百条记忆 reflect 几分钟，语义质量明显更好"},
        "recommended": {"ram_gb": "32+", "vram_gb": "12-24", "disk_gb": "15-20（32B 量化）",
                        "experience": "流畅，建议用 7B-14B 指令模型（如 Qwen2.5 / Llama3.1 量化版）"},
        "privacy_note": "本地 LLM（Ollama/llama.cpp）记忆不出本机、零 API 费；外部 API 则需 API key 且记忆出域（按 token 计费）。",
        "model_advice": "reflect 仅需「读记忆→出建议」，7B-14B 指令模型足够，不必上 70B。",
    }

def converse(root, text=None, rounds=None, set_threshold=None, force_end=False, max_items=10, with_workbuddy=False, no_llm=False):
    """对话内自主沉淀入口（无需 WorkBuddy 自动化）。

    设计要点（v2.11.9）：
    - 默认**每轮只记对话次数**，不立即沉淀；本轮回想要点若提供则进入 buffer 暂存。
    - **阈值不写死**：`threshold`（默认 10）存在 <root>/_round_state.json，用户可用自然语言让
    agent 调用 `converse --set-threshold N` 改成任意值（几十轮/几百轮皆可）。
    - 每满 `threshold` 轮（或 `force_end=True` 收尾）工具**自己**触发：
    * 先把 buffer 累积要点用 `harvest` 以 seed 态沉积（默认每 10 轮才沉淀，而非每轮）；
    * `harvest --self-learn`：读全部记忆 body 跨记忆自学习（重复/矛盾/合成建议）；
    * `reflect --auto`：自主晋升被证明有用的种子、归档过期种子（整理）。
    即「自己学习、自己整理、自己沉淀」的无人值守闭环，且频率完全由用户掌控。
    轮次计数持久化在 _round_state.json，跨多次 CLI 调用累加（每次 agent 轮次=一次进程调用）。
    返回 {ok, round, threshold, deposited, n_deposited, consolidated, self_learn, reflect, next_at}。
    """
    init_store(root)
    st = _load_round_state(root)

    # 配置类操作：仅改阈值、不计数、不沉淀
    if set_threshold is not None:
        try:
            nval = max(1, int(set_threshold))
        except Exception:
            nval = 10
        st["threshold"] = nval
        st["threshold_auto"] = False  # v3.1.4 P1-4：用户显式设置 → 关闭自适应
        _save_round_state(root, st)
        return {"ok": True, "action": "set_threshold", "threshold": nval,
                "round": st["count"], "next_at": _rounds_until(st["count"], nval)}

        # P1-4 自适应 修正）：开箱默认 20 轮，自适应**只上调不下调**——
        # 仅大库（>500条）为防止整理过频上调到 40；小/中库（≤500）一律沿用默认 20，不向下改。
        # 这样"默认阈值20轮"对用户诉求恒成立，同时保留大库降频保护。
    if st.get("threshold_auto", True):
        try:
            _idx = load_index(root)
            _n_mem = len([e for e in _idx.get("entries", [])
                          if isinstance(e, dict) and e.get("status") == "active"])
            _base = int(st.get("threshold", 20))
            _auto_thresh = max(_base, 40) if _n_mem > 500 else _base
            if st.get("threshold") != _auto_thresh:
                st["threshold"] = _auto_thresh
        except Exception:
            pass

    n = max(1, int(rounds)) if rounds else int(st.get("threshold", 10))
    st["count"] = int(st.get("count", 0)) + 1
    round_no = st["count"]

    # 本轮回想要点：进 buffer 暂存，不立即沉淀
    if text and str(text).strip():
        st["buffer"].append(str(text).strip())
        if len(st["buffer"]) > 200:
            st["buffer"] = st["buffer"][-200:]

    should = bool(force_end) or (round_no % n == 0)
    deposited = []
    n_deposited = 0
    self_learn = None
    reflect_summary = None
    if should:
        # 到阈值才把累积要点真正沉积为种子记忆
        buf = st.get("buffer", [])
        if buf:
            try:
                r = harvest(root, text="。".join(buf), max_items=max_items,
                            llm=(False if no_llm else None))
                n_deposited = r.get("n_deposited", 0)
                deposited = r.get("deposited", [])
            except Exception:
                pass
        try:
            self_learn = harvest(root, self_learn=True, max_items=max_items,
                                with_workbuddy=with_workbuddy,
                                llm=(False if no_llm else None))
        except Exception:
            self_learn = {"ok": False, "error": "self_learn_failed"}
        try:
            fr = reflect(root, auto=True)
            reflect_summary = {k: len(fr.get(k, [])) for k in
                               ("duplicates", "contradictions", "stale",
                                "promote_candidates", "scope_review",
                                "link_candidates", "aar")}
        except Exception:
            reflect_summary = {"ok": False, "error": "reflect_failed"}
        st["last_consolidated"] = round_no
        st["buffer"] = []  # 沉淀后清空待办缓冲
    _save_round_state(root, st)
    return {"ok": True, "round": round_no, "threshold": n,
            "deposited": deposited, "n_deposited": n_deposited,
            "consolidated": bool(should), "self_learn": self_learn,
            "reflect": reflect_summary, "next_at": _rounds_until(round_no, n)}

def llm_setup(root, backend=None, base_url=None, model=None, api_key_env=None,
              max_suggestions=None, batch_size=None, temperature=None,
              enable=None, dry=False):
    """#8 配置助手：检测 LLM 端点可达性 + 展示推荐硬件配置要求 + 写入 config.json 的 llm 块。
    纯只读检测 + 写 config，绝不改记忆。--dry 只检测并打印要求，不写 config。"""
    cfg = _load_llm_config(root)
    if backend:
        cfg["backend"] = backend
    if base_url:
        cfg["base_url"] = base_url
    if model:
        cfg["model"] = model
    if api_key_env:
        cfg["api_key_env"] = api_key_env
    if max_suggestions is not None:
        cfg["max_suggestions"] = max(1, int(max_suggestions))
    if batch_size is not None:
        cfg["batch_size"] = max(1, int(batch_size))
    if temperature is not None:
        cfg["temperature"] = float(temperature)
    if enable is not None:
        cfg["enabled"] = bool(enable)
    reachable = _probe_llm(cfg)
    req = _llm_hardware_requirements()
    result = {"config": cfg, "reachable": reachable, "requirements": req,
              "dry": dry, "written": False}
    if not dry:
        _save_llm_config(root, cfg)
        result["written"] = True
    return result

