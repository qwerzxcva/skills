#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mem_bridge.py — WorkBuddy 原生记忆(L2/L3) 与 agent-local-memory-keeper(L4) 的「共进型」桥接。

设计原则（见《共进型记忆协同架构方案.md》）：
· WB→keeper：受控提炼（distill_to_keeper），仅在显式调用时跑，带 source/rev 戳 + 去重，绝不整库抄。
· keeper→WB：只读注入（inject_active），把 keeper 活跃经验输出为可注入 system 上下文的块，不回写任何 WB 文件。
· 媒介是 agent，不是文件系统：两端永不直接互写 → 切断震荡回路。

用法：
python mem_bridge.py inject [--query Q] [--top N] [--no-header] [--reinforce] [--explain]
python mem_bridge.py feedback --mid X,Y [--used|--good|--bad] | --from-inject [--used|--good|--bad]
python mem_bridge.py distill [--text "..." | --file path.md] [--category best_practice] [--source wb_memory]
python mem_bridge.py distill --summary "..." --body "..." --tags a,b --category correction
python mem_bridge.py distill --working   --summary "..." --body "下一步...;阻塞点..."
python mem_bridge.py distill --decision  --summary "选了X" --body "理由...;备选...;否决原因..."
python mem_bridge.py distill --category correction --subtype technical --summary "..." --body "..."
python mem_bridge.py working          # I6 列出进行态记忆
python mem_bridge.py graph  --around LRN-xxx   # I12 关系图
python mem_bridge.py guard  --text "..." | --file x.md   # I10 发布前安全检查
python mem_bridge.py drift            # I13 版本漂移检查
python mem_bridge.py seed   --domain <项目领域>   # I7 冷启动播种（注：量化 已废弃→investment）
python mem_bridge.py compress [--stale 30] [--apply]   # I11 日志压缩
python mem_bridge.py coach [--llm agent|off]           # B 语义卫生教练（agent=零配置用 Agent 自身模型）
python mem_bridge.py reflect [--llm agent|ollama|openai|off]   # B1 双模式自检（agent=零配置）
python mem_bridge.py promote --review | --confirm MID1,MID2   # A1 用户确认晋升环
python mem_bridge.py inject [--budget-lines 100]   # A2 HOT/WARM/COLD 行数预算（默认 100 行）
# B2：Agent 会话内调用可加 --from-agent（或设 env WB_AGENT_SESSION=1）→ 自动走零配置 Agent 自身推理

也可 import：from mem_bridge import inject_active, distill_to_keeper, feedback_k, feedback_batch
"""
import os
import sys
import re
import json
import hashlib
import subprocess
try:
    import winreg  # Windows 专有模块；mac/Linux 上置 None，所有注册表调用走 env 兜底
except ImportError:
    winreg = None
import argparse
import datetime as _dt

# ---------- 路径 ----------
KEEPER_SKILL_DIR = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "agent-local-memory-keeper")
KEEPER_SKILL = os.path.join(KEEPER_SKILL_DIR, "scripts")
# keeper 存储根（跨工作区统一脑）。
# 发布安全：不硬编码真实盘符路径。解析优先级：
# 1) 进程 env AI_MEMORY_STORE
# 2) 注册表 HKCU\Environment AI_MEMORY_STORE（换机只改一处）
# 3) 回退「用户目录下的 AI记忆」可移植默认
def _load_mem_store():
    v = os.environ.get("AI_MEMORY_STORE")
    if v:
        return v
    if winreg is not None:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
            rv, _ = winreg.QueryValueEx(k, "AI_MEMORY_STORE")
            winreg.CloseKey(k)
            if rv:
                return rv
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "AI记忆")


KEEPER_ROOT = _load_mem_store()
# 神经模型：优先用本地缓存 ~/.cache/fastembed（首次自动下载，可离线复用）；
# 发布包不含 models/（91M 运行时下载项，不应随 skill 发布），故不指向 skill 内 models/。
FALLBACK_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "fastembed")
# I1：inject 落盘「本次被注入（surfaced）的 MID」，供 feedback 闭环强化使用
INJECT_LAST = os.path.join(os.path.expanduser("~"), ".workbuddy", ".inject_last.json")
# 防自反馈循环：inject 每日会话级计数器。
# 现象：WorkBuddy host 在工具结果后重调模型，每轮 inject 又喂入"活跃经验+校准话术"，
# 模型进入"再确认"的开放回路、每次只多输出几个字。修复：在 session/日期级别限制
# inject 触发次数，超过即跳过（return 空字符串），切断循环燃料。
INJECT_COUNTER = os.path.join(os.path.expanduser("~"), ".workbuddy", ".inject_counter.json")
# 配置收口：inject 开关统一走 config.json 的 keeper 块（env 仍可逐条覆盖，优先级最高）。
def _inject_keeper_cfg():
    import memory_ops as _m
    _root = os.environ.get("AI_MEMORY_STORE") or _m._default_root()
    return _m._load_keeper_config(_root)

    # F18 包化修复：memory_ops 已搬入 scripts/ 包，但本文件顶层（_inject_keeper_cfg 内）import memory_ops
    # 在模块加载时即执行，而原 sys.path.insert 在文件末尾函数内、执行太晚，导致 `python mem_bridge.py` 无 PYTHONPATH 时
    # 直接 ModuleNotFoundError。此处提前把 scripts/ 加入 sys.path，确保 import 不依赖外部环境。
if os.path.isdir(KEEPER_SKILL):
    sys.path.insert(0, KEEPER_SKILL)
_KC = _inject_keeper_cfg()
MAX_INJECT_PER_DAY = _KC["inject_daily_cap"]            # 默认 6 次/日
INJECT_COUNTER_RESET_HOUR = 4  # 凌晨 4 点为新会话起点（与 WorkBuddy 平台默认对齐）
# P1-2（架构级消除自反馈）：去重门——记录每条记忆"上次被注入"的日期，
# 在 INJECT_DEDUP_DAYS 窗口内再次被召回时跳过，从结构上避免"同一条旧记忆被反复注入→AI 反复再确认"的回路。
# 与 KEEPER_INJECT_DAILY_CAP（每日次数闸）叠加而非替换：次数闸夹频率，去重门夹"重复同一记忆"。
INJECT_SURFACED = os.path.join(os.path.expanduser("~"), ".workbuddy", ".inject_surfaced.json")
INJECT_DEDUP_DAYS = _KC["inject_dedup_days"]            # 同记忆 14 天内最多注入一次
INJECT_DEDUP_ENABLED = _KC["inject_dedup"]              # 默认去重开
# C 方案，架构级消除与 WorkBuddy L2 云记忆的双重注入）：
# inject 默认【关闭】，必须显式设 `KEEPER_INJECT_ENABLED=1` 才参与。
# 根因：WB L2 每层对话自动注入历史画像，keeper inject 又塞 keeper 经验，两套无"已注入"清单共享
# → 同一记忆被塞两次 → AI 反复再确认 → 再 deposit → 再被两边注入（死循环）。
# 默认关（防自反馈循环）。 起：`_inject_exclude_wb` 按 `workbuddy_memory` 标签自动排除从 WorkBuddy 同步来的记忆，
# 故 inject 与 WB L2 可并存、不再要求二选一（无需关 WB L2）；只开 WB L2 或只开 inject 都安全。
KEEPER_INJECT_ENABLED = _KC["inject_enabled"]           # 默认 False（必须显式开启，防自反馈循环）
# I-cache：跨进程持久化的 embed 向量缓存（sqlite），让 coach/rank/retrieve 复用向量
EMB_CACHE_DB = os.path.join(os.path.expanduser("~"), ".workbuddy", ".emb_cache.db")
_EMB_MODEL_ID = "fast-bge-small-zh-v1.5"


def _emb_cache_conn():
    import sqlite3
    conn = sqlite3.connect(EMB_CACHE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS emb (k TEXT PRIMARY KEY, vec TEXT, model TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return conn


def embed_cached(text):
    """I-cache：跨进程持久化的 embed 向量缓存。命中即返回，未命中算后落盘。
    模型变更（_EMB_MODEL_ID）自动失效（清空重建）。包装 keeper embed，提速 coach/rank/retrieve。"""
    key = hashlib.md5((text or "").encode("utf-8")).hexdigest()
    conn = None
    try:
        conn = _emb_cache_conn()
        cur = conn.execute("SELECT v FROM meta WHERE k='model'")
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO meta (k,v) VALUES ('model',?)", (_EMB_MODEL_ID,))
            conn.commit()
        elif row[0] != _EMB_MODEL_ID:
            conn.execute("DELETE FROM emb")
            conn.execute("UPDATE meta SET v=? WHERE k='model'", (_EMB_MODEL_ID,))
            conn.commit()
        cur = conn.execute("SELECT vec FROM emb WHERE k=?", (key,))
        row = cur.fetchone()
        if row is not None:
            return json.loads(row[0])
    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    import embed as _emb
    vec = _emb.embed(text)
    try:
        conn = _emb_cache_conn()
        conn.execute("INSERT OR REPLACE INTO emb (k,vec,model) VALUES (?,?,?)",
                     (key, json.dumps(vec), _EMB_MODEL_ID))
        conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return vec


    # ---------- I10：写前/发布前敏感信息护栏（路径/邮箱/通用 token/内部信息）----------
    # keeper 自带 _scan_sensitive 已覆盖各类 API Key/密码/PII；这里补它没覆盖的真实路径、
    # 邮箱、通用 token、内部信息——复用用户级「发布到 SkillHub 前的安全检查」清单规则。
_PUB_LEAK_PATTERNS = [
    (re.compile(r'[A-Za-z]:[\\/][^\s]{4,}'), "real_path"),
    (re.compile(r'/(?:c|d|e|f)/[^\s]{4,}'), "real_path_unix"),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), "email"),
    (re.compile(r'skh_[A-Za-z0-9]{20,}'), "skillhub_token"),
    (re.compile(r'(?i)(?:api[_-]?key|password|secret|token)\s*[=:]\s*\S+'), "cred_assignment"),
    (re.compile(r'(?:内网|公司名|部门|岗位|工号)'), "internal_info"),
]


def _scan_publish_leak(text):
    """I10：扫描真实路径/邮箱/通用 token/内部信息。返回 [(name, snippet), ...]。"""
    if not text:
        return []
    hits = []
    for rx, name in _PUB_LEAK_PATTERNS:
        for m in rx.finditer(text):
            snip = m.group(0)
            if len(snip) > 32:
                snip = snip[:20] + "…"
            hits.append((name, snip))
    return hits


def _redact_publish_leak(text):
    """I10：把命中的泄露片段替换为占位符（脱敏，不阻断写入）。"""
    if not text:
        return text
    for rx, name in _PUB_LEAK_PATTERNS:
        if name in ("real_path", "real_path_unix"):
            text = rx.sub("<path>", text)
        elif name == "email":
            text = rx.sub("<email>", text)
        elif name == "skillhub_token":
            text = rx.sub("<token>", text)
        elif name == "cred_assignment":
            text = rx.sub("<redacted>", text)
        elif name == "internal_info":
            text = rx.sub("<internal>", text)
    return text


def _keeper_version():
    """I13：读取本地 keeper 技能版本（来自 _skillhub_meta.json / _meta.json）。"""
    for fp in (os.path.join(KEEPER_SKILL_DIR, "_skillhub_meta.json"),
               os.path.join(KEEPER_SKILL_DIR, "_meta.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                v = (json.load(fh) or {}).get("version")
                if v:
                    return v
        except Exception:
            pass
    return "unknown"


    # 工作记忆 / 决策记忆 的规范标签
_WORKING_TAG = "working"
_DECISION_TAG = "decision"

# A3 纠正分类细化：correction 的子类型白名单（format/technical/communication/project/personal）。
# 旧数据未带 sub: 标签时缺省归 general，向后兼容。
_CORRECTION_SUBTYPES = {
    "format": "格式/排版/命名规范",
    "technical": "技术实现/算法/接口",
    "communication": "沟通表达/措辞/语气",
    "project": "项目约定/流程/分工",
    "personal": "个人偏好/习惯/边界",
}

# ---------- 投资场景适配（G1/G2/G3/G4/G5/G6）----------
# G1：investment 已是 keeper 原生 domain（KNOWN_DOMAINS 含 investment）；
# 这里补子域白名单，让经验可「按子系统」精准筛选（你做量化全链路的核心诉求）。
INVESTMENT_SUBDOMAINS = {
    "risk_control": "风控系统",
    "position_mgmt": "仓位系统",
    "industry_analysis": "行业分析系统",
    "stock_analysis": "个股分析系统",
    "data_pipeline": "数据整理/清洗管道",
    "backtest": "回测/模拟操盘",
    "strategy": "策略研发",
    "execution": "执行/交易",
}
# G5：param:xxx 结构化数值经验（止盈止损/仓位上限等），纯约定标签，零代码风险。
# G2：valid_until → until:<ISO日期> 标签；G3：source_quirk → quirk:<数据源>；
# G4：status → st:<testing|production|deprecated>；D1：priority → pri:<high|med|low>。


def _normalize_valid_until(v):
    """G2：把 2020Q1 / 2026Q4 / 2026-12-31 / 统一为 ISO 日期（存 until: 标签供 --filter-fresh 过滤）。
    季度支持任意年/季度（不限定固定表）。"""
    if not v:
        return None
    v = v.strip()
    import re as _re
    # 季度：YYYYQn → 季度末 ISO 日期（任意年）
    mq = _re.match(r"^(\d{4})Q([1-4])$", v)
    if mq:
        y, q = int(mq.group(1)), int(mq.group(2))
        _ld = (31, 30, 30, 31)[q - 1]  # 3/6/9/12 月末天数
        return "%04d-%02d-%02d" % (y, q * 3, _ld)
        # ISO 日期（允许 . 或 - 分隔）
    mi = _re.match(r"^(\d{4})[.\-]?(\d{1,2})(?:[.\-]?(\d{1,2}))?$", v)
    if mi:
        y, mo = int(mi.group(1)), int(mi.group(2))
        d = int(mi.group(3)) if mi.group(3) else 1
        try:
            return _dt.date(y, mo, d).isoformat()
        except Exception:
            pass
    return None


def _is_expired(entry, today):
    """G2：记忆是否过了 valid_until（until: 标签）。过期则 --filter-fresh 隐藏，避免误导回测。"""
    for t in (entry.get("tags") or []):
        if t.startswith("until:"):
            try:
                return _dt.date.fromisoformat(t[6:]) < today
            except Exception:
                pass
    return False


def _fastembed_cache():
    """返回 fastembed 缓存目录：直接回退 ~/.cache/fastembed（首次自动下载，可离线复用）。
    发布包不含 models/（91M 运行时下载项），故不检测 skill 内 bundled 模型。"""
    return FALLBACK_CACHE


    # 当前工作区记忆目录（coach 体检扫描范围）。
    # 发布安全：不硬编码工作区绝对路径。解析优先级：
    # 1) env WB_WORKSPACE_MEM（显式指定工作区 .workbuddy/memory）
    # 2) 注册表 HKCU\Environment WB_WORKSPACE_MEM（与 KEEPER_ROOT 同权威源）
    # 3) env WB_WORKSPACE + ".workbuddy/memory"
    # 4) 注册表 WB_WORKSPACE + ".workbuddy/memory"
    # 5) 当前 cwd 下的 .workbuddy/memory（兜底，适配被 workspace 调用时）
def _resolve_workspace_mem():
    def _reg(name):
        if winreg is None:
            return ""
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
            v, _ = winreg.QueryValueEx(k, name)
            winreg.CloseKey(k)
            return v or ""
        except Exception:
            return ""
    v = os.environ.get("WB_WORKSPACE_MEM") or _reg("WB_WORKSPACE_MEM")
    if v:
        return v
    ws = os.environ.get("WB_WORKSPACE") or _reg("WB_WORKSPACE")
    if ws:
        return os.path.join(ws, ".workbuddy", "memory")
    return os.path.join(os.getcwd(), ".workbuddy", "memory")


WORKSPACE_MEM = _resolve_workspace_mem()

if os.path.isdir(KEEPER_SKILL):
    sys.path.insert(0, KEEPER_SKILL)

    # ---------- B2：调用来源检测（Agent 会话 / CLI 独立）----------
    # Agent 调用 mem_bridge 时注入 WB_AGENT_SESSION=1（或由 --from-agent 显式置位），
    # 据此走「模式 A = Agent 自身推理」：keeper 只产出结构化推理任务书，Agent 用自己正在
    # 使用的模型执行推理后写回 → 零配置、零延迟、记忆不出本机。无需用户再装 Ollama/OpenAI。
def _in_agent_session():
    return _AGENT_OVERRIDE or (os.environ.get("WB_AGENT_SESSION") == "1")

_AGENT_OVERRIDE = False  # main() 内可由 --from-agent 运行时置位
IN_AGENT = _in_agent_session()


def _resolve_llm_mode(flag):
    """B1 双模式 LLM 路由：
    - flag 显式给定（agent/ollama/openai/off）→ 用之
    - 未给定 → Agent 会话内默认 'agent'（零配置，用 Agent 自身模型）；
    CLI 独立调用默认 'off'（规则兜底，不退化）
    """
    if flag:
        return flag
    return "agent" if IN_AGENT else "off"


def _ensure_env():
    os.environ["AI_MEM_EMBED_BACKEND"] = "fastembed"  # 本地已化 ONNX，强制神经后端
    cache = _fastembed_cache()
    # 2026-09-05 修复（P0 模型缓存漂移）：原为强制覆盖，会把用户/注册表已配置的
    # 持久缓存目录（skill 外，升级不丢 90MB 权重）冲掉，退回 ~/.cache/fastembed
    # （通常为空 → 每次联网 → HF_ENDPOINT 异常时静默降级词法）。改为尊重已有配置。
    if not os.environ.get("FASTEMBED_CACHE_PATH"):
        os.environ["FASTEMBED_CACHE_PATH"] = cache  # A4 回退：仅在未配置时用 ~/.cache
    # 本地模型存在则离线加载（绕开沙箱 TLS 拦截的联网下载）；真实机无本地模型时不设，仍可联网拉
    if os.path.isdir(os.path.join(cache, "fast-bge-small-zh-v1.5")):
        os.environ["HF_HUB_OFFLINE"] = "1"
    if KEEPER_SKILL not in sys.path:
        sys.path.insert(0, KEEPER_SKILL)


        # ---------- 环③：keeper→WB 只读注入（成就 WB，不改文件）----------
def _estimate_tokens(text):
    """粗略 token 估算：中文≈1.6 字/token，英文≈0.75 词/token（按字符近似）。用于注入预算。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.6 + other / 4 + 1)


def _fmt_entry(e, with_tags=True, explain=False, matched=None):
    """matched=触发本次召回的 query（用于 I9 出处可视化）。"""
    mid = e.get("id", "?")
    summary = (e.get("summary") or "").strip()
    body = (e.get("body") or "").strip().replace("\n", " ")
    tags = ",".join(e.get("tags", []) or [])
    item = f"- `[{mid}]` **{summary}**：{body}"
    if with_tags and tags:
        item += f" _{tags}_"
    if explain:
        meta = []
        sc = e.get("score")
        if sc is not None:
            meta.append(f"score={sc}")
        imp = e.get("importance")
        if imp is not None:
            meta.append(f"imp={imp}")
        if matched:
            meta.append(f"hit={matched!r}")
        if meta:
            item += f"  `{' '.join(meta)}`"
    return item


def _append_agent_brief(text, kind="coach"):
    """B1：在规则分析结果后追加『推理委托』brief，提示 Agent 用自身模型合成建议。
    不调用任何外部 LLM；Agent 读到后用自己的智力给出建议，零配置零延迟。"""
    brief = "\n\n---\n### 🤖 推理委托（Agent 自身模型 · 零配置）\n"
    if kind == "coach":
        brief += ("以上为 keeper 语义体检的结构化结果（重复/矛盾/过期）。"
                  "请基于这些数据，用你正在使用的模型直接给出：\n"
                  "1. 合并/去重的优先级建议；2. 矛盾条目的裁决意见；"
                  "3. 过期日志是否可归档。以你的话回复用户，无需再调任何 LLM。")
    elif kind == "reflect":
        brief += ("以上为 keeper 规则自检结果。请用你正在使用的模型合成可执行建议"
                  "（晋升/合并/纠正/归档），并以你的话回复用户。")
    brief += ("\n\n> 模式说明：当前为「Agent 自身推理」模式——你（Agent）就是 LLM，"
              "keeper 只提供数据，零额外配置、零延迟、记忆不出本机。"
              "若想改用本地 Ollama 离线增强，可显式 `--llm ollama`（需先配 llm-setup）。")
    return text + brief


def reflect_wb(mode="off", stale_days=90, auto=False):
    """B1 双模式 reflect：
    - agent / off：keeper 跑规则 reflect（findings），agent 模式追加推理委托 brief。
    - ollama / openai：透传 keeper `reflect --llm`（需用户已配端点；CLI 场景离线/隐私增强）。
    返回精简 findings 文本 + 可选 brief。规则兜底保证核心功能不退化。
    """
    _ensure_env()
    cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
    cmd = [sys.executable, cli, "reflect", "--stale-days", str(stale_days)]
    if auto:
        cmd.append("--auto")
    if mode in ("ollama", "openai"):
        cmd.append("--llm")  # 透传：keeper 用其 config 后端（ollama 默认本地）
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        d = json.loads(proc.stdout)
        f = (d.get("findings", {}) or {})
    except Exception as e:
        return f"[mem_bridge] reflect 调用失败：{e}"
    n_dup = len(f.get("duplicates", []) or [])
    n_contra = len(f.get("contradictions", []) or [])
    n_stale = len(f.get("stale", []) or [])
    lines = ["## 🔍 keeper 规则自检（reflect · 仅建议不改）",
             f"- 重复候选：{n_dup} ｜ 矛盾候选：{n_contra} ｜ 过期记忆：{n_stale}"]
    llm = f.get("llm")
    if isinstance(llm, dict) and llm.get("enabled"):
        sug = llm.get("suggestions", []) or []
        lines.append(f"- LLM 自进化建议（{llm.get('backend','?')}/{llm.get('model','?')}）：{len(sug)} 条")
        for s in sug[:10]:
            lines.append(f"  - {s.get('action','?')}: {(s.get('summary','') or '')[:60]}")
    else:
        lines.append("- LLM 自进化：未启用（规则兜底）")
    out = "\n".join(lines)
    if mode == "agent":
        out = _append_agent_brief(out, "reflect")
    return out


def promote_review(min_access=3, min_conf=0.6, top_n=20):
    """A1 用户确认晋升环：列出「高频但未分类/低置信」的待确认晋升候选。
    访问频次高（>=min_access）但 category 为空或 confidence<min_conf 的条目，
    不直接自动晋升——交由用户确认（Agent 在对话里问）后再 `promote --confirm`。"""
    _ensure_env()
    cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
    env = dict(os.environ)
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    try:
        proc = subprocess.run([sys.executable, cli, "recall"], env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        d = json.loads(proc.stdout)
        entries = d.get("entries", [])
    except Exception as e:
        return f"[mem_bridge] promote --review 失败：{e}"
    cands = []
    for e in entries:
        if e.get("status") != "active":
            continue
        if e.get("tier") in ("curated", "core"):
            continue  # 已晋升，跳过
        ac = e.get("access_count", 0) or 0
        conf = e.get("confidence")
        cat = (e.get("category") or "").strip()
        # 高频 且 (未分类 或 低置信)
        if ac >= min_access and (not cat or (conf is not None and conf < min_conf)):
            cands.append(e)
    cands.sort(key=lambda x: (x.get("access_count", 0) or 0), reverse=True)
    cands = cands[:top_n]
    if not cands:
        return "_（无待确认晋升候选：当前无高频且未分类/低置信的记忆）_"
    lines = [f"## 🪜 待确认晋升候选（A1 · 高频但未分类/低置信，需用户确认才晋升）",
             f"- 阈值：access_count≥{min_access} 且 (category 空 或 confidence<{min_conf})",
             f"- 候选 {len(cands)} 条；确认请用 `promote --confirm <MID1,MID2>`"]
    for e in cands:
        mid = e.get("id")
        summ = (e.get("summary") or "")[:48]
        lines.append(f"  - `{mid}` tier={e.get('tier')} conf={e.get('confidence')} "
                     f"access={e.get('access_count')} cat='{e.get('category')}' → {summ}")
    return "\n".join(lines)


def promote_confirm(mids, target_tier="curated"):
    """A1：用户确认后晋升——tier 升为 curated + 打 confirmed_by_user 标签。
    用 keeper overwrite（只传 tier+tags，summary/body 为 None → 保留不动）原子完成。"""
    _ensure_env()
    cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
    env = dict(os.environ)
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    results = []
    for mid in mids:
        try:
            proc = subprocess.run([sys.executable, cli, "recall", "--id", mid],
                                  env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            ents = (json.loads(proc.stdout) or {}).get("entries", [])
            cur_tags = (ents[0].get("tags") or []) if ents else []
            if "confirmed_by_user" not in cur_tags:
                cur_tags = cur_tags + ["confirmed_by_user"]
            p2 = subprocess.run([sys.executable, cli, "overwrite", "--id", mid,
                                 "--tier", target_tier,
                                 "--tags", ",".join(cur_tags), "--yes"],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            try:
                ok = bool((json.loads(p2.stdout) or {}).get("ok"))
            except Exception:
                ok = False
            results.append(f"{mid}:{'✅' if ok else '❌'} tier→{target_tier}+confirmed_by_user")
        except Exception as ex:
            results.append(f"{mid}:❌ {ex}")
    return "\n".join(results)


def _safe_store_path(path, store, label="export"):
    """路径穿越拦截：确保 path 落在 store 目录之内（含 store 本身）。

    禁止 `..`、绝对路径越界、符号链接逃逸。返回规范化绝对路径。
    """
    abs_store = os.path.abspath(store)
    abs_path = os.path.abspath(os.path.join(abs_store, path)
                               if not os.path.isabs(path) else path)
    # 统一分隔符后前缀比较，防止 Z:/store 与 Z:/store_evil 误判
    store_prefix = abs_store.replace("\\", "/").rstrip("/") + "/"
    path_norm = abs_path.replace("\\", "/")
    if path_norm != abs_store.replace("\\", "/").rstrip("/") and \
            not path_norm.startswith(store_prefix):
        raise ValueError(
            "%s 路径 %s 超出记忆库边界 %s（禁止路径穿越）" % (label, path, abs_store))
    return abs_path


def to_l2_draft(entries, min_importance=0.7, min_access=3, top_n=30,
                export_path=None, fmt="md", dry_run=False):
    """P2 跨系统晋升导出（不直写 WB 文件）。

    筛选高价值 L4 记忆（importance≥min_importance 或 access_count≥min_access
    或 带 confirmed_by_user 标签），生成草稿文件（MD/JSON），供用户 / AI 经 WB
    自身捕获机制（"记住这条" 或贴入 MEMORY.md）落 L2/L3。

    entries 由调用方（main 分发）先 recall 后传入，本函数只做筛选 + 写盘。
    默认写入 <AI_MEMORY_STORE 或 memory_ops 默认根>/to_l2_draft.<ext>；
    --export 可指定路径。绝不写任何 WB 原生文件、绝不删 L4 原文。

    dry_run=True 时只统计候选、不写盘（供预览 / 测试）。
    返回 (草稿路径, 条数, 诊断 dict)；无候选或出错时 (None, 0, 诊断)。fail-open。
    诊断含 active_l4_scanned / max_importance / max_access，便于解释"为何 0 候选"。
    """
    cands = []
    n_active_l4 = 0
    max_imp = 0.0
    max_ac = 0
    for e in entries:
        if e.get("status") != "active":
            continue
        if e.get("tier") in ("curated", "core"):
            continue
        n_active_l4 += 1
        imp = e.get("importance")
        ac = e.get("access_count", 0) or 0
        if imp is not None:
            max_imp = max(max_imp, float(imp))
        max_ac = max(max_ac, int(ac))
        tags = e.get("tags") or []
        if (imp is not None and imp >= min_importance) or ac >= min_access \
                or ("confirmed_by_user" in tags):
            cands.append(e)
    cands.sort(key=lambda x: (x.get("importance") or 0,
                               x.get("access_count", 0) or 0), reverse=True)
    cands = cands[:top_n]
    diag = {"active_l4_scanned": n_active_l4,
            "max_importance": round(max_imp, 3),
            "max_access": max_ac,
            "min_importance": min_importance,
            "min_access": min_access}
    if not cands:
        if n_active_l4 == 0:
            reason = ("库内没有任何 active 工作态(L4)记忆——先 deposit 一些经验，"
                      "或对已有记忆 feedback/被使用以提升 importance/access_count")
        else:
            reason = ("有 %d 条 active L4 但都未达阈值（当前最高 importance=%.2f<%.2f，"
                      "最高 access=%d<%d；或缺少 confirmed_by_user 标签）。"
                      "可调低 --min-importance/--min-access，或对高价值记忆打 "
                      "confirmed_by_user 标签 / 多 feedback 提升分数"
                      % (n_active_l4, max_imp, min_importance, max_ac, min_access))
        sys.stderr.write("[mem_bridge] to-l2：无符合阈值的高价值 L4 候选\n")
        return None, 0, {"ok": False, "reason": reason, **diag}
    if dry_run:
        return None, len(cands), {"ok": True, "dry_run": True, **diag}
    try:
        import memory_ops as _m
        store = os.environ.get("AI_MEMORY_STORE") or _m._default_root()
        if export_path:
            path = _safe_store_path(export_path, store, label="to-l2 export")
        else:
            ext = "json" if fmt == "json" else "md"
            path = os.path.join(store, "to_l2_draft.%s" % ext)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if fmt == "json":
            payload = [{"id": e.get("id"), "summary": e.get("summary"),
                        "body": e.get("body"), "category": e.get("category"),
                        "tags": e.get("tags"), "importance": e.get("importance"),
                        "access_count": e.get("access_count")}
                       for e in cands]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        else:
            lines = [
                "# L4→L2 晋升草稿（P2 导出式，不直写 WB 文件）",
                "",
                "> 这些是候选晋升到 WB 长期记忆（L2/L3）的 keeper 经验。",
                "> 请经 WB 自身捕获机制（\"记住这条\" 或贴入 MEMORY.md）落库；",
                "> 本文件不改任何 WB 文件，也不删 L4 原文。",
                "",
                "- 阈值：importance≥%.2f 或 access_count≥%d 或 confirmed_by_user"
                % (min_importance, min_access),
                "- 候选 %d 条（扫描 %d 条 active L4，最高 importance=%.2f / access=%d）"
                % (len(cands), n_active_l4, max_imp, max_ac),
                "",
            ]
            for e in cands:
                mid = e.get("id")
                summ = (e.get("summary") or "").strip()
                cat = e.get("category") or ""
                imp = e.get("importance")
                ac = e.get("access_count", 0) or 0
                lines.append("- [%s] %s  `cat=%s imp=%s access=%s`"
                              % (mid, summ, cat, imp, ac))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except Exception as e:
        sys.stderr.write("[mem_bridge] to-l2 草稿写盘失败：%s\n" % e)
        return None, 0, {"ok": False, "reason": "草稿写盘失败：%s" % e, **diag}
    return path, len(cands), {"ok": True, **diag}


def _inject_exclude_wb(entries):
    """C 方案：过滤 WB 来源记忆，切断「WB 记忆 → keeper → 再被 keeper 注回上下文」的回路。
    harvest --self-learn --with-workbuddy 同步进来的 WB 记忆带 `workbuddy_memory` 标签，返回过滤后列表。"""
    return [e for e in entries if "workbuddy_memory" not in (e.get("tags") or [])]


def _memory_ops_cli():
    """定位 memory_ops 的 CLI 入口（recall/deposit 等子命令）。

    2026-08-29 修复：原写死 `<skill>/memory_ops/__init__.py`，但包实际位于
    `<skill>/scripts/memory_ops/`。路径错 → recall 子进程启动失败 → 异常被
    `except: continue` 静默吞掉 → retrieve/inject **永久返回空**（能存不能取）。
    新路径优先、旧路径回退，两者皆无则明确告警（不再静默）。
    """
    for p in (os.path.join(KEEPER_SKILL, "scripts", "memory_ops", "__init__.py"),
              os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")):
        if os.path.isfile(p):
            return p
    sys.stderr.write(
        "[mem_bridge] 警告：未找到 memory_ops CLI（已查 <skill>/scripts/memory_ops 与 "
        "<skill>/memory_ops），recall 将不可用——请检查 keeper 安装完整性。\n")
    return os.path.join(KEEPER_SKILL, "scripts", "memory_ops", "__init__.py")


_DEGRADED_STATE = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "hooks", ".keeper_degraded.json")


def _mark_degraded(reason=""):
    """A2：把「语义后端降级」状态落盘，供 SessionStart 钩子开局零成本读取。
    失败静默——降级提示是 best-effort，绝不影响召回主流程。"""
    try:
        _dir = os.path.dirname(_DEGRADED_STATE)
        if _dir and not os.path.isdir(_dir):
            os.makedirs(_dir, exist_ok=True)
        with open(_DEGRADED_STATE, "w", encoding="utf-8") as f:
            json.dump({"degraded": True,
                       "degraded_at": _dt.datetime.now().isoformat(),
                       "reason": reason}, f, ensure_ascii=False)
    except Exception:
        pass


def _clear_degraded():
    """A2：语义后端恢复后清掉降级状态文件。失败静默（残留最多多提示一次，无害）。"""
    try:
        if os.path.exists(_DEGRADED_STATE):
            os.remove(_DEGRADED_STATE)
    except Exception:
        pass


def inject_active(query=None, top_n=5, with_header=True, max_tokens=400,
                  expand=True, explain=False, max_lines=100,
                  domain=None, subdomain=None, filter_fresh=False,
                  include_auto=False, respect_inject_gate=True):
    """include_auto / 提案 A）：显式包含被动捕获暂存项（auto_sourced=True）。
    默认仍隔离（B3 staging 开关），仅当用户明确 --include-auto 时，蒸馏/捕获的暂存记忆
    才会在 inject/retrieve 中被召回——破「只存不取」死循环，让 distill→回顾→promote 闭环可用。"""
    """
    召回 keeper 活跃经验，返回可注入 system 上下文的 Markdown 块（只读，不写任何 WB 文件）。
    A2 查询扩展：query 经 embed.expand_synonyms 生成多表面形式，分别召回后合并去重。
    A1 兜底：神经后端无果时退回 lexical，保证 recall 不崩。
    A2 HOT/WARM/COLD 预算：优先 HOT(core/curated) 层，再 WARM(working/seed)；按行数硬预算
    （默认 ≤100 行）截断，超预算标注 truncated，WARM 仍可经 retrieve 按需拉取、COLD 仅索引。
    A3 动态预算：按 max_tokens 截断，控制每次注入 token 成本（默认 ≤400）。
    """
    _TIER_RANK = {"core": 0, "curated": 1, "working": 2, "seed": 3}
    # C 方案：inject 默认关闭，显式开关开启才参与（自动注入上下文）。
    # 2026-08-29 修复：`retrieve`（I2 主动顾问，Agent/用户显式调用拉经验）此前也被此门禁挡住，
    # 导致 inject 关闭时主动检索永远返回空——能存不能取。该门禁只应约束"自动注入"，
    # 不应约束"显式检索"，故加 respect_inject_gate 开关：retrieve 传 False 绕过。
    if respect_inject_gate and not KEEPER_INJECT_ENABLED:
        return "" if not with_header else (
            "_（keeper inject 默认关闭；开启后自动排除从 WorkBuddy 同步来的记忆（`workbuddy_memory` 标签），"
            "因此可与 WorkBuddy L2 并存、不会形成双重注入回路；若只想用 WB 原生注入，保持 inject 关闭即可。"
            "注：显式检索请用 `retrieve --task`，不受本开关影响）_")
    # 防自反馈循环：会话级计数，超过 cap 直接返回空（切断循环燃料）。
    # 计数 IO 异常时 hit_cap=False 保守不拦截；正常累计后判定 hit_cap。
    # 2026-08-29：与上方 inject 门禁同理，本上限只约束"自动注入"，
    # 显式检索（retrieve，respect_inject_gate=False）不应被计数上限挡住。
    _inj_n, _hit_cap = _inject_counter_tick()
    if respect_inject_gate and _hit_cap:
        return "" if not with_header else (
            "_（keeper 本日 inject 已达上限 %d 次，跳过注入以避免自反馈循环；"
            "调高请设 env `KEEPER_INJECT_DAILY_CAP=N`）_" % MAX_INJECT_PER_DAY)
    env = dict(os.environ)
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    cache = _fastembed_cache()
    # 2026-09-05 修复（同 _ensure_env）：尊重已配置的持久缓存目录，不再强制覆盖。
    if not env.get("FASTEMBED_CACHE_PATH"):
        env["FASTEMBED_CACHE_PATH"] = cache  # A4 回退：仅在未配置时用 ~/.cache
    if os.path.isdir(os.path.join(cache, "fast-bge-small-zh-v1.5")):
        env["HF_HUB_OFFLINE"] = "1"
    cli = _memory_ops_cli()

    # A2 查询扩展：生成多表面形式，分别召回后合并去重
    queries = [query] if query else [None]
    if expand and query:
        try:
            import embed as _emb
            forms = _emb.expand_synonyms(query)
            if forms:
                queries = forms[:4]
        except Exception:
            pass

    entries, seen, _last_meta = [], set(), None
    mid2q = {}
    for q in queries:
        cmd = [sys.executable, cli, "recall"]
        if q:
            cmd += ["--query", q]
        if domain:
            cmd += ["--domain", domain]
        if subdomain:
            cmd += ["--tag", "sub:%s" % subdomain]
        if include_auto:
            cmd += ["--include-auto"]
        cmd += ["--with-meta"]  # A：随带后端/meta，AI 无需手动 doctor 即知降级
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
            d = json.loads(proc.stdout)
            if d.get("meta"):
                _last_meta = d.get("meta")
            for e in d.get("entries", []):
                mid = e.get("id")
                if mid and mid not in seen:
                    seen.add(mid)
                    mid2q.setdefault(mid, q)
                    entries.append(e)
        except Exception as e:
            # 不再静默：2026-08-29 因 CLI 路径错误导致每轮 recall 都失败却毫无提示，
            # 表现为 retrieve/inject 永久返回空（能存不能取）。失败必须可见。
            sys.stderr.write("[mem_bridge] recall 子命令失败(query=%r)：%s: %s\n"
                             % ((q or "")[:40], type(e).__name__, str(e)[:200]))
            continue
            # A1 兜底：神经无果 → lexical 回退
    if not entries and query:
        try:
            env2 = dict(env)
            env2["AI_MEM_EMBED_BACKEND"] = "lexical"
            cmd = [sys.executable, cli, "recall", "--query", query]
            if domain:
                cmd += ["--domain", domain]
            if subdomain:
                cmd += ["--tag", "sub:%s" % subdomain]
            if include_auto:
                cmd += ["--include-auto"]
            proc = subprocess.run(cmd, env=env2, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)
            d = json.loads(proc.stdout)
            # 注意：此路径是我们「主动」强制 lexical 重查，其 meta.fell_back_to_lexical 必然为真，
            # 不能据此判定「后端降级」（那由主循环的 _last_meta 决定），故此处不覆盖 _last_meta。
            entries = d.get("entries", [])
            for e in entries:
                mid2q.setdefault(e.get("id"), query)
        except Exception as e:
            sys.stderr.write("[mem_bridge] lexical 兜底 recall 失败(query=%r)：%s: %s\n"
                             % ((query or "")[:40], type(e).__name__, str(e)[:200]))
            pass
            # C 方案：过滤 WB 来源记忆，切断「WB 记忆 → keeper → 再被 keeper 注回上下文」的回路。
            # harvest --self-learn --with-workbuddy 同步进来的 WB 记忆带 `workbuddy_memory` 标签，
            # 若被 keeper inject 再推回上下文，会与 WB L2 注入形成重复/放大。
    entries = _inject_exclude_wb(entries)
    # A：语义后端降级闭环——recall meta 已随带实际后端状态；若降级词法级，向 stderr 告警、
    # 落盘降级状态（供 SessionStart 钩子开局读取），并在注入块追加「请转告用户」行动指令，
    # 使 AI 无需手动跑 doctor 即知「搜不到是因为降级了」并主动引导用户配置修复（B1 红线运行时闭环）。
    _DEGRADED_NOTE = ""
    if _last_meta and _last_meta.get("fell_back_to_lexical"):
        _mark_degraded("fell_back_to_lexical")
        sys.stderr.write(
            "[mem_bridge] ⚠️ 语义后端已降级为词法级（召回质量下降）；"
            "请引导用户说「帮我一键配好」或自跑 python mem_bridge.py doctor --fix 修复。\n")
        _DEGRADED_NOTE = (
            "\n> ⚠️【记忆系统状态·请转告用户】语义召回后端已降级为词法级，"
            "本次召回质量低于真·语义（结果可能不准）。\n"
            "> 请在本轮回复开头主动告知用户并引导修复：说「帮我一键配好」即可自动修复；"
            "或让用户自跑 `python mem_bridge.py doctor --fix` 自愈模型缓存。")
    elif _last_meta and not _last_meta.get("fell_back_to_lexical"):
        # 明确「未降级」才清状态；recall 失败 / 无 meta 时不动，避免误清真实降级态
        _clear_degraded()
    # P1-2 去重门：窗口内已被注入过的记忆不再重复注入（结构性切断"同记忆反复注入"回路）
    # 2026-09-05 修复：去重门原本对 inject（自动注入）与 retrieve（显式检索）一视同仁，
    # 但二者语义相反 —— 去重门是为切断「同一条记忆被自动反复注回上下文」的自反馈回路，
    # 属**自动注入**的防护；而 retrieve 是用户/AI 显式发起的查询，理应「问必答」。
    # 实测后果：一条经验被召回过一次后，14 天内所有显式检索都返回空
    # （本机 .inject_surfaced.json 累计 __suppressed__=117），表现为「存了却找不到」。
    # 与既有 respect_inject_gate 口径保持一致：显式检索（False）不受自动注入策略约束。
    if INJECT_DEDUP_ENABLED and respect_inject_gate:
        _surf = _inject_load_surfaced()
        _today = _dt.date.today()
        _kept, _suppressed = [], 0
        for e in entries:
            mid = e.get("id")
            _last = _surf.get(mid) if mid else None
            if _last:
                try:
                    if (_today - _dt.date.fromisoformat(_last)).days < INJECT_DEDUP_DAYS:
                        _suppressed += 1
                        continue
                except Exception:
                    pass
            _kept.append(e)
        entries = _kept
        if _suppressed:  # 累计被抑制次数 = 回路强度测量
            _surf["__suppressed__"] = int(_surf.get("__suppressed__", 0) or 0) + _suppressed
            _inject_save_surfaced(_surf)
            # G2：--filter-fresh 隐藏已过期（until: < 今天）的经验，避免误导多年回测决策
    if filter_fresh:
        _today = _dt.date.today()
        entries = [e for e in entries if not _is_expired(e, _today)]
        # G1：domain/subdomain 精确过滤（recall --domain 仅放松热位、不排他，故桥接层强制）
    if domain:
        entries = [e for e in entries if e.get("domain") == domain]
    if subdomain:
        entries = [e for e in entries
                   if ("sub:%s" % subdomain) in (e.get("tags") or [])]

        # A2 HOT/WARM/COLD 预算：优先 HOT(core/curated)，再 WARM(working/seed)，同层按 score 降序
    entries.sort(key=lambda e: (_TIER_RANK.get(e.get("tier"), 4), -(e.get("score") or 0)))
    entries = entries[:top_n]
    # A3 动态预算截断
    if max_tokens:
        out, used = [], 0
        for e in entries:
            t = _estimate_tokens(_fmt_entry(e))
            if out and used + t > max_tokens:
                break
            out.append(e)
            used += t
        entries = out
        # A2 行数硬预算（HOT≤100 行约束）：超预算按当前顺序截断并标注
    truncated = 0
    if max_lines:
        out2, used = [], 0
        for e in entries:
            ln = _fmt_entry(e, explain=explain, matched=mid2q.get(e.get("id"))).count("\n") + 1
            if out2 and used + ln > max_lines:
                truncated += 1
                continue
            out2.append(e)
            used += ln
        entries = out2

        # P1-2 去重门：记录本次实际注入的记忆（供下一轮去重判定 + 测量回路强度）
    # 同上：显式检索不写 surfaced，否则一次调试性查询会让该记忆静默消失 14 天。
    if INJECT_DEDUP_ENABLED and respect_inject_gate and entries:
        _surf = _inject_load_surfaced()
        _today_iso = _dt.date.today().isoformat()
        for e in entries:
            mid = e.get("id")
            if mid:
                _surf[mid] = _today_iso
                # 仅保留窗口内的记录，避免无限增长
        _surf = {k: v for k, v in _surf.items()
                 if k == "__suppressed__"
                 or (_dt.date.today() - _dt.date.fromisoformat(v)).days < INJECT_DEDUP_DAYS + 1}
        _inject_save_surfaced(_surf)

    if not entries:
        # 可发现性提示（2026-08-29）：distill 存入的记忆是 auto_sourced=True 暂存项，
        # recall 默认排除（B3 staging 开关，防自反馈）。用户未带 --include-auto 时
        # 会看到"暂无活跃经验"，误以为没记住——此处显式给出解锁方式。
        if not include_auto:
            _empty_msg = ("_（keeper 无匹配经验；若记忆是 distill 存入的暂存项，"
                          "加 `--include-auto` 重试）_")
        else:
            _empty_msg = "_（keeper 暂无活跃经验）_"
        _empty_msg += _DEGRADED_NOTE
        return _empty_msg if with_header else _DEGRADED_NOTE
    lines = []
    if with_header:
        lines.append("## 🧠 当前生效的 AI 经验（来自 keeper，跨工作区复用）")
    for e in entries:
        lines.append(_fmt_entry(e, explain=explain, matched=mid2q.get(e.get("id"))))
    if truncated:
        lines.append(f"_（上下文预算：已截断 {truncated} 条 WARM/COLD 经验；用 `retrieve --task` 按需拉取）_")
    if _DEGRADED_NOTE:
        lines.append(_DEGRADED_NOTE)
        # I1：记录本次 surfaced 的 MID（供 feedback 强化闭环使用），绝不影响注入输出本身
    if entries:
        _record_inject(query, [e.get("id") for e in entries if e.get("id")])
    return "\n".join(lines)


def _record_inject(query, mids):
    """把本次 inject 召回的 MID 落盘到 INJECT_LAST，供后续 feedback 强化闭环读取。
    失败静默（绝不阻塞注入本身）。"""
    try:
        payload = {
            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
            "query": query,
            "mids": mids,
        }
        with open(INJECT_LAST, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception:
        pass


def _inject_counter_tick():
    """：会话级 inject 计数器。返回 (count_after, hit_cap)。

    行为：
    - 用 INJECT_COUNTER 记录 {date, count, session_start}。
    - 若距上次写入 ≥ INJECT_COUNTER_RESET_HOUR 小时，视为新会话、count 重置为 0。
    - 命中 MAX_INJECT_PER_DAY 时 hit_cap=True，调用方应跳过 inject。
    - 性能：O(1) JSON 读写 + atomic replace；任何 IO 异常均静默返回 count=0、hit_cap=False
    （保守不拦截），避免一次写失败导致 inject 全部失能。
    """
    try:
        now = _dt.datetime.now()
        try:
            with open(INJECT_COUNTER, "r", encoding="utf-8") as fh:
                d = json.load(fh) or {}
        except Exception:
            d = {}
        st = d.get("session_start")
        if isinstance(st, str):
            try:
                dt0 = _dt.datetime.fromisoformat(st)
                if (now - dt0).total_seconds() >= INJECT_COUNTER_RESET_HOUR * 3600:
                    d = {"date": now.date().isoformat(), "count": 0,
                         "session_start": now.isoformat(timespec="seconds")}
            except Exception:
                pass
        if "session_start" not in d:
            d = {"date": now.date().isoformat(), "count": 0,
                 "session_start": now.isoformat(timespec="seconds")}
        d["count"] = int(d.get("count", 0)) + 1
        d["date"] = now.date().isoformat()
        d["last_ts"] = now.isoformat(timespec="seconds")
        try:
            tmp = INJECT_COUNTER + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            os.replace(tmp, INJECT_COUNTER)
        except Exception:
            pass
        return d["count"], d["count"] > MAX_INJECT_PER_DAY
    except Exception:
        return 0, False


def _inject_load_surfaced():
    """P1-2 去重门：读取 {mid: 上次注入日期} 映射；__suppressed__ 为累计被去重抑制次数（测量回路强度）。"""
    try:
        with open(INJECT_SURFACED, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def _inject_save_surfaced(d):
    try:
        os.makedirs(os.path.dirname(INJECT_SURFACED), exist_ok=True)
        tmp = INJECT_SURFACED + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, INJECT_SURFACED)
    except OSError:
        pass


def inject_stats():
    """P1-2 测量：返回自反馈闸门运行状态（每日次数闸 + 去重门）。
    用于量化'回路强度'—— suppressed 越高说明同一批记忆被反复召回越严重。"""
    try:
        with open(INJECT_COUNTER, encoding="utf-8") as fh:
            _c = json.load(fh) or {}
    except Exception:
        _c = {}
    _surf = _inject_load_surfaced()
    _suppressed = int(_surf.get("__suppressed__", 0) or 0)
    _tracked = [k for k in _surf if k != "__suppressed__"]
    return {
        "daily_cap": MAX_INJECT_PER_DAY,
        "daily_used": int(_c.get("count", 0) or 0),
        "daily_hit_cap": int(_c.get("count", 0) or 0) > MAX_INJECT_PER_DAY,
        "dedup_enabled": INJECT_DEDUP_ENABLED,
        "dedup_window_days": INJECT_DEDUP_DAYS,
        "distinct_surfaced_tracked": len(_tracked),
        "suppressed_cumulative": _suppressed,
        "inject_enabled": KEEPER_INJECT_ENABLED,
    }


    # ---------- I1：闭环使用反馈（WB→keeper 强化，成就 B 的自学习）----------
def feedback_k(mid, signal=None):
    """
    对单条 keeper 经验给反馈（底层复用 keeper 现成的 touch / feedback）：
    - signal=None  → memory_ops.touch（中性：记录「被使用」，刷新 accessed/access_count）
    - signal=good/bad → memory_ops.feedback（强信号：调 confidence + importance，Beta 后验校准）
    返回结果 dict（含最新 confidence/importance 供观察）。
    """
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return {"ok": False, "id": mid, "err": f"无法加载 keeper：{e}"}
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        if signal in ("good", "bad"):
            return _m.feedback(root, mid, signal)
        return {"ok": True, "id": mid, "action": "touch",
                "result": _m.touch(root, mid)}
    except Exception as e:
        return {"ok": False, "id": mid, "err": str(e)}


def feedback_batch(mids=None, signal=None, from_inject=False):
    """批量反馈。from_inject=True 时取上次 inject 记录的 MID 列表（会话结束强化用）。
    signal: None=中性 touch；good/bad=强信号。返回汇总结论。"""
    if from_inject and not mids:
        try:
            with open(INJECT_LAST, encoding="utf-8") as fh:
                mids = (json.load(fh) or {}).get("mids", []) or []
        except Exception:
            mids = []
    mids = [m.strip() for m in (mids or []) if m and m.strip()]
    if not mids:
        return {"ok": True, "applied": 0, "succeeded": 0, "signal": signal or "touch",
                "msg": "无可反馈 MID"}
    out = [feedback_k(mid, signal) for mid in mids]
    return {
        "ok": True,
        "applied": len(out),
        "succeeded": sum(1 for r in out if r.get("ok")),
        "signal": signal or "touch",
        "details": out,
    }


    # ---------- 环②：WB→keeper 受控提炼（成就 keeper，带 source/rev 戳）----------
_EXP_KW = ["经验", "踩坑", "坑", "最佳实践", "纠正", "务必", "不要", "必须",
           "一定", "建议", "记住", "记得", "规律", "原则", "禁止", "避免",
           "优先", "改用", "替代", "应当", "慎用", "切忌"]

# D1 三级切分关键词：事实→L2 / 项目专属→L3 / 跨项目经验→L4
_USER_KW = ["用户", "偏好", "称呼", "习惯", "城市", "职业", "我叫", "叫我",
            "性别", "年龄", "生日"]
_PROJ_KW = ["本工作区", "当前项目", "本仓库", "本项目", "电脑清理", "workspace"]

# keeper deposit 的 scope 只接受 universal/project/ephemeral；WB 侧语义需映射：
# user（用户事实，跨工作区通用）→ universal
# cross（跨项目经验）→ universal
# project（项目专属）→ project 不变
_SCOPE_MAP = {"user": "universal", "cross": "universal", "project": "project"}


# I3 抽象阶梯：脱去具体标识符，生成可跨项目复用的「通用原则」层
_PATH_RE = re.compile(r'[A-Za-z]:[\\/][^\s]+|/(?:c|d|e|f)/[^\s]+')
_MID_RE = re.compile(r'LRN-[\w-]+')


def _scrub_concrete(text):
    """脱去具体路径/MID 等本机标识符，保留规律本身。"""
    if not text:
        return ""
    t = _PATH_RE.sub("<path>", text)
    t = _MID_RE.sub("<mid>", t)
    return t


def _abstract_principle(summary, body):
    """由具体经验启发式生成通用原则文本（离线、无需 LLM）。
    复用 keeper 的 _redact_sensitive 做敏感信息兜底脱敏；结果打 auto_abstract 供复核。"""
    raw = (body or summary or "").strip()
    scrubbed = _scrub_concrete(raw)
    try:
        import memory_ops as _m
        scrubbed = _m._redact_sensitive(scrubbed)
    except Exception:
        pass
    if body:
        return scrubbed
    return ("通用原则：" + _scrub_concrete(summary or "")).strip()


def route_target(text):
    """D1 三级切分建议：事实→A 的 L2；项目专属→A 的 L3；跨项目通用经验→B 的 L4。
    返回 (tier, reason)。仅给建议，实际落点由 agent 决策（媒介是 agent，不是文件系统）。"""
    if any(k in text for k in _USER_KW):
        return "L2", "命中用户事实关键词（偏好/称呼/习惯等）→ 进 WB 用户级记忆"
    if any(k in text for k in _PROJ_KW):
        return "L3", "命中项目专属关键词 → 进工作区 .workbuddy/memory"
    return "L4", "通用方法/陷阱/纠正 → 进 keeper 跨工作区经验库"


def _extract_experience_bullets(text):
    """极简规则提炼：取含经验关键词、且较长的行作为经验条目。无命中则返回整段。"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    hits = [l for l in lines if len(l) >= 10 and any(k in l for k in _EXP_KW)]
    return hits if hits else [text.strip()]


    # ---------- I4：会话内失败自捕获（草稿优先，确认门防噪音）----------
def capture_failure(text, corrects=None, commit=False):
    """I4：把工具报错 / 用户纠正起草为 correction 记忆。
    默认只打印草稿不落盘（确认门，防误捕获噪音）；--commit 才经 distill 写入并挂纠正链。"""
    summary = (text or "").strip().replace("\n", " ")[:60]
    if commit:
        ids, msg = distill_to_keeper(
            summary=summary, body=(text or "").strip(),
            category="correction", source="wb_memory",
            scope="cross", corrects=corrects)
        return {"ids": ids, "msg": msg}
    return ("## 📝 失败自捕获草稿（未落盘）\n"
            f"- **类型**：correction\n"
            f"- **摘要**：{summary}\n"
            f"- **正文**：{(text or '').strip()}\n"
            f"- **corrects**：{corrects or '（无，独立纠正）'}\n"
            "- ⚠️ 默认不写入；确认无误后加 `--commit` 落盘为 keeper 经验（自动挂纠正链）。")


    # ---------- I5：B 内部矛盾检测（防主库腐烂）----------
_POS_KW = ["必须", "启用", "推荐", "建议", "应", "用", "开"]
_NEG_KW = ["禁止", "禁用", "避免", "勿", "切忌", "不要", "不用", "关"]


def _b_conflict_check(new_text):
    """I5：在 B（keeper 主线）检测与新经验冲突的已有经验。
    返回 (dup_mid, contra_mid)：近重复→dup_mid（建议 supersede 避免重复）；
    情感对立高相似→contra_mid（矛盾候选，**仅建议人工复核**）。无 keeper 时返回 (None,None)。

    ⚠️ 判据是启发式：`cos≥0.6` **且** 两侧「正/负情感关键词」相反即点名，
    **不等同结论相互矛盾**——描述同一件事正反两面的经验、以及自然语句里同时出现
    「要/不要」的条目都会命中（实测误报占多数，真正的结论对立才是少数）。
    因此 contra_mid 只作**定位线索**，一律须人工读正文裁定，
    **不得据此自动隔离或删除**（这也是 `--quarantine-conflict` 默认不开的原因）。"""
    _ensure_env()
    try:
        import memory_ops as _m
        import numpy as np
    except Exception:
        return None, None
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        mems = _m._all_mems(root)
    except Exception:
        return None, None
    new_vec = np.asarray(embed_cached(new_text), dtype=float)
    dup_mid, dup_sc = None, 0.0
    contra_mid, contra_sc = None, 0.0
    pa = any(k in new_text for k in _POS_KW)
    na = any(k in new_text for k in _NEG_KW)
    for mid, mem in mems.items():
        if mem.get("status") != "active":
            continue
        vec = embed_cached((mem.get("summary", "") + " " + mem.get("body", "")))
        vec = np.asarray(vec, dtype=float)
        denom = (np.linalg.norm(new_vec) * np.linalg.norm(vec)) + 1e-9
        sc = float(np.dot(new_vec, vec) / denom)
        if sc >= 0.92 and sc > dup_sc:
            dup_sc, dup_mid = sc, mid
        ta = (mem.get("summary", "") + " " + mem.get("body", ""))
        pb = any(k in ta for k in _POS_KW)
        nb = any(k in ta for k in _NEG_KW)
        if sc >= 0.6 and ((pa and nb) or (na and pb)) and sc > contra_sc:
            contra_sc, contra_mid = sc, mid
    return dup_mid, contra_mid


def _is_abstract_pair(mid_a, mem_a, mid_b, mem_b):
    """判定两条记忆是否为「具体层 ↔ 其 auto_abstract 派生的原则层」配对（I3 抽象阶梯产物）。

    判据（两条须同时满足）：
      1. 任一侧 tags 含 `auto_abstract`（说明该条是抽象阶梯生成的）；
      2. 存在 `relates_to:<对方 MID>` 指向（抽象阶梯写入时固定打此标签）。

    目的：scan_dup（I5）与冲突检测会对此类配对稳定产生 cos≈1.00 的"近重复"，
    且因两侧分别含正/负情感关键词（描述同一件事的正反两面）常被误判为"矛盾"。
    此二者均为设计结构，必须排除，否则 --auto supersede 会删掉刚生成的层。
    """
    ta = mem_a.get("tags") or []
    tb = mem_b.get("tags") or []
    if not (any(t == "auto_abstract" for t in ta)
            or any(t == "auto_abstract" for t in tb)):
        return False
    return (any(t == f"relates_to:{mid_b}" for t in ta)
            or any(t == f"relates_to:{mid_a}" for t in tb))


def audit_b():
    """I5 只读审计：扫描 B 主线内部近重复与矛盾，仅报告不写。"""
    _ensure_env()
    try:
        import memory_ops as _m
        import numpy as np
    except Exception as e:
        return f"[mem_bridge] audit 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        mems = _m._all_mems(root)
    except Exception as e:
        return f"[mem_bridge] audit 读取失败：{e}"
    active = [(mid, m) for mid, m in mems.items() if m.get("status") == "active"]
    if len(active) < 2:
        return "_（B 主线经验不足 2 条，无可比对）_"
    vecs = {}
    for mid, m in active:
        v = embed_cached((m.get("summary", "") + " " + m.get("body", "")))
        vecs[mid] = np.asarray(v, dtype=float)
    dups, contra = [], []
    skipped_pairs = 0
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            mi, mj = active[i][0], active[j][0]
            # 跳过「具体层 ↔ 其 auto_abstract 派生的原则层」配对（I3 抽象阶梯产物）：
            # 二者由设计生成为高度相似且经 relates_to 关联，属正常结构而非重复/矛盾。
            # 若不过滤会稳定 cos≈1.00 误报，且下游 --auto supersede 会把刚生成的层删掉。
            if _is_abstract_pair(mi, mems[mi], mj, mems[mj]):
                skipped_pairs += 1
                continue
            a, b = vecs[mi], vecs[mj]
            sc = float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))
            if sc >= 0.92:
                dups.append((sc, mi, mj))
            ta = (mems[mi].get("summary", "") + " " + mems[mi].get("body", ""))
            tb = (mems[mj].get("summary", "") + " " + mems[mj].get("body", ""))
            if sc >= 0.6 and ((any(k in ta for k in _POS_KW) and any(k in tb for k in _NEG_KW))
                              or (any(k in ta for k in _NEG_KW) and any(k in tb for k in _POS_KW))):
                contra.append((sc, mi, mj))
    dups.sort(reverse=True)
    lines = ["## 🔬 B 主线矛盾审计（I5 · 只读）",
             f"- 扫描：{len(active)} 条活跃经验"]
    if skipped_pairs:
        lines.append(
            f"- 已排除 {skipped_pairs} 组「具体层↔auto_abstract 原则层」配对"
            "（I3 抽象阶梯产物，设计上高度相似，非重复/矛盾）")
    if dups:
        lines.append("- **近重复（cos≥0.92，建议 supersede 避免重复）：**")
        for sc, a, b in dups[:10]:
            lines.append(f"  - `{a}` ↔ `{b}` (cos={sc:.2f})")
    else:
        lines.append("- 近重复：未检出")
    if contra:
        lines.append("- **潜在矛盾候选（高相似+情感对立；⚠️ 启发式告警，须人工读正文裁定，勿直接隔离）：**")
        for sc, a, b in contra[:10]:
            lines.append(f"  - `{a}` ↔ `{b}` (cos={sc:.2f})")
    else:
        lines.append("- 矛盾：未检出")
    return "\n".join(lines)


def distill_to_keeper(text=None, file=None, summary=None, body=None,
                      tags=None, category="best_practice",
                      source="wb_memory", scope="cross",
                      project=None, corrects=None, abstract=False,
                      check_conflict=False, quarantine_conflict=False,
                      tier="seed", working=False, decision=False, no_guard=False,
                      llm_mode=None, subtype=None,
                      domain=None, subdomain=None, params=None,
                      valid_until=None, source_quirk=None, status=None):
    """
    把 WB 侧（L2/L3）的经验性内容提炼进 keeper L4。
    - 显式模式：传 summary/body/tags 直接 deposit。
    - 规则模式：传 text/file，按关键词抽取经验条目，逐条 deposit。
    每条带 source + rev(时间戳) 戳；deposit 自带写前查重（同 source+rev 幂等）。
    D1 scope/project：scope=user/project/cross 决定经验可见范围；project 绑定项目。
    scope 经 _SCOPE_MAP 映射到 keeper 接受的 universal/project/ephemeral。
    C2 corrects：传被推翻的旧经验 MID → keeper 自动给旧经验打 superseded，形成纠正链。
    I3 abstract：传 --abstract 时，对每条经验额外生成「通用原则」层（scope=universal，
    带 principle + relates_to:<具体MID> + auto_abstract 标签），提升跨项目复用率；
    原则由离线启发式抽象生成（脱具体路径/MID/敏感信息），首条建议人工复核。
    返回 deposited id 列表。
    """
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return [], f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT

    if file and not text:
        with open(file, encoding="utf-8") as fh:
            text = fh.read()
    if summary and body:
        bullets = [{"summary": summary, "body": body}]
    elif text:
        bl = _extract_experience_bullets(text)
        bullets = [{"summary": b[:60], "body": b} for b in bl]
    else:
        return [], "[mem_bridge] 需提供 --text/--file 或 --summary/--body"

    rev = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    real_scope = _SCOPE_MAP.get(scope, "universal")  # cross/user → universal
    if decision:
        category = "decision"
    eff_tier = "working" if working else tier
    base_tags = list(tags or [])
    # 本地补丁 5（2026-09-13）：notes 必须在使用前初始化。
    # 原代码把 `notes = []` 放在下方 subtype 段（原 1355 行），但 G1(subdomain)/G4(status)
    # 两个校验分支在它之前就 notes.append → 传白名单外的 subdomain 或非法 status 时
    # 抛 UnboundLocalError: cannot access local variable 'notes'（实测复现）。
    notes = []
    # G1/G2/G3/G4/G5：投资场景适配标签（纯约定，零代码风险，向后兼容旧数据）
    if subdomain:
        sd = subdomain.strip().lower()
        if sd in INVESTMENT_SUBDOMAINS:
            base_tags.append(f"sub:{sd}")
        else:
            notes.append(f"G1 忽略未知 subdomain='{subdomain}'（允许：{','.join(INVESTMENT_SUBDOMAINS)}）")
    for p in (params or []):
        p = p.strip()
        if p and "=" in p:
            base_tags.append(f"param:{p}")
    vu = _normalize_valid_until(valid_until)
    if vu:
        base_tags.append(f"until:{vu}")
    if source_quirk:
        base_tags.append(f"quirk:{source_quirk.strip().lower()}")
    if status:
        st = status.strip().lower()
        if st in ("testing", "production", "deprecated"):
            base_tags.append(f"st:{st}")
        else:
            notes.append(f"G4 忽略未知 status='{status}'（允许：testing/production/deprecated）")
            # B1：外部 LLM（ollama/openai）生成的内容打来源标签；agent/off 不打（Agent 自身模型即默认假设）
    if llm_mode in ("ollama", "openai"):
        base_tags.append(f"llm:{llm_mode}")
        # A3 纠正分类细化：correction 类可带子类型，归一为 sub:<type> 标签（白名单外忽略并告警）
    if subtype:
        st = subtype.strip().lower()
        if st in _CORRECTION_SUBTYPES:
            base_tags.append(f"sub:{st}")
        else:
            notes.append(f"A3 忽略未知 sub-type='{subtype}'（允许：{','.join(_CORRECTION_SUBTYPES)}）")
    deposited = []
    errs = []
    for b in bullets:
        btxt = (b.get("body") or b.get("summary") or "")
        s_text = b.get("summary", "") or ""
        b_text = b.get("body", "")
        # I10：写前敏感护栏（路径/邮箱/通用 token/内部信息）。默认脱敏+警告；--no-guard 跳过。
        if not no_guard:
            leaks = _scan_publish_leak(s_text) + _scan_publish_leak(b_text)
            if leaks:
                s_text = _redact_publish_leak(s_text)
                b_text = _redact_publish_leak(b_text)
                notes.append(f"I10 脱敏 {len(leaks)} 处泄露（路径/邮箱/内部信息）")
                # I5：冲突检测（可选）。近重复→自动 supersede；矛盾→可选送 quarantine。
        eff_corrects = corrects
        route_quarantine = False
        if check_conflict and btxt:
            dup_mid, contra_mid = _b_conflict_check(btxt)
            if dup_mid and not corrects:
                eff_corrects = dup_mid
                notes.append(f"近重复 {dup_mid} → 自动 supersede（避免重复）")
            if contra_mid:
                if quarantine_conflict:
                    route_quarantine = True
                    notes.append(f"矛盾候选 {contra_mid} → 送 quarantine 待审"
                                 f"（⚠️ 启发式告警：仅「相似度≥0.6 且正/负情感词相反」，"
                                 f"不等同结论相悖——须人工读正文裁定，勿直接隔离）")
                else:
                    notes.append(f"矛盾候选 {contra_mid}（未送 quarantine，加 --quarantine-conflict 启用；"
                                 f"⚠️ 须人工读正文裁定，勿直接隔离）")
        try:
            if route_quarantine:
                # I5：送隔离区（不进主库），待人工复核
                q_tags = list(base_tags)
                if source:
                    q_tags.append(f"src:{source}")
                q_tags += [f"rev:{rev}", "contradiction_candidate"]
                qmid = _m._quarantine_candidate(
                    root, category, s_text or "auto-distill",
                    q_tags, b_text, hits=None, scope=real_scope,
                    project=project, tier="working")
                deposited.append(qmid)
                continue
                # 具体层：deposit（尊重 --scope/--project/tier；I10 已脱敏）
            tags_list = list(base_tags)
            if source:
                tags_list.append(f"src:{source}")
            tags_list.append(f"rev:{rev}")
            tags_list.append(f"ver:{_keeper_version()}")
            if category == "correction":
                tags_list.append("correction")
            if working:
                tags_list.append(_WORKING_TAG)
            if decision:
                tags_list.append(_DECISION_TAG)
            if abstract:
                tags_list.append("concrete")
            cid = _m.deposit(
                root,
                category,
                s_text or "auto-distill",
                tags_list,
                b_text,
                tier=eff_tier, inferred=True, auto_sourced=True,
                recorded_by="mem_bridge",
                scope=real_scope, project=project, corrects=eff_corrects,
                domain=domain, subdomain=subdomain,
            )
            deposited.append(cid)
            # I3 抽象阶梯：额外生成「通用原则」层（scope=universal，关联回具体层）
            if abstract:
                principle = _abstract_principle(s_text, b_text)
                p_tags = [f"src:{source}", f"rev:{rev}", "principle",
                          f"relates_to:{cid}", "auto_abstract", f"ver:{_keeper_version()}"]
                if category == "correction":
                    p_tags.append("correction")
                pid = _m.deposit(
                    root,
                    category,
                    ("原则：" + _scrub_concrete(s_text))[:80] or "auto-abstract",
                    p_tags, principle,
                    tier="seed", inferred=True, auto_sourced=True,
                    recorded_by="mem_bridge",
                    scope="universal", project=None, corrects=None,
                )
                deposited.append(pid)
        except Exception as e:
            errs.append(str(e))
    n_concrete = len([d for d in deposited])
    msg = f"deposited={len(deposited)}"
    if abstract:
        msg += f" (具体层 + 原则层各半，原则层 scope=universal 已关联)"
    if notes:
        msg += " | " + "; ".join(notes)
    if errs:
        msg += f" errors={len(errs)}:{errs[:2]}"
    return deposited, msg


    # ---------- 环④：keeper→WB 卫生教练（只读分析，只建议不改）----------
def _collect_wb_units(recent_days=5, max_age_days=None, workspace=None):
    """收集 WB 的 L2 / 工作区 MEMORY.md / daily 日志的平文单元。
    返回 [(loc, text, date_or_None), ...]；date 仅对 daily 日志有值，用于过期判断。
    recent_days 与 max_age_days 互斥：recent_days 取近 N 天，max_age_days 取近 N 天内全部。
    workspace：显式指定工作区 .workbuddy/memory 目录；缺省回退模块级 WORKSPACE_MEM
    （解析优先级见 _resolve_workspace_mem）。供 CLI --workspace 精确控制，避免依赖导入期 cwd。"""
    files = []
    l2 = os.path.join(os.path.expanduser("~"), ".workbuddy", "MEMORY.md")
    if os.path.isfile(l2):
        files.append(("L2", l2, None))
    ws_mem_dir = workspace or WORKSPACE_MEM
    ws_mem = os.path.join(ws_mem_dir, "MEMORY.md")
    if os.path.isfile(ws_mem):
        files.append(("WS", ws_mem, None))
    if os.path.isdir(ws_mem_dir):
        today = _dt.date.today()
        for fn in sorted(os.listdir(ws_mem_dir)):
            if fn.startswith("20") and fn.endswith(".md") and fn != "MEMORY.md":
                try:
                    d = _dt.datetime.strptime(fn[:10], "%Y-%m-%d").date()
                except Exception:
                    continue
                age = (today - d).days
                if recent_days is not None and age <= recent_days:
                    files.append(("LOG:" + fn[:10], os.path.join(WORKSPACE_MEM, fn), d))
                elif max_age_days is not None and age <= max_age_days:
                    files.append(("LOG:" + fn[:10], os.path.join(WORKSPACE_MEM, fn), d))
    units = []
    for tag, fp, d in files:
        with open(fp, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                s = line.strip()
                if not s or s.startswith("#") or len(s) < 12:
                    continue
                units.append((f"{tag}:{i}", s, d))
    return units


def coach_wb(dup_thresh=0.82, recent_days=5, top_n=20, stale_days=30, workspace=None):
    """
    用 keeper 的语义能力反向体检 WB 的 L2/L3 平文本：检测重复与矛盾，并列出过期日志。
    B1 输出三档（可安全合并 / 疑似重复待核 / 潜在矛盾需核实）+ B3 过期归档建议。
    只读、只建议、不改任何 WB 文件——"keeper 成就 WB"的卫生教练闭环。
    workspace：显式指定工作区 .workbuddy/memory 目录；缺省回退 WORKSPACE_MEM。
    """
    _ensure_env()
    try:
        import embed as _emb
        import numpy as np
    except Exception as e:
        return f"[mem_bridge] coach 无法加载 keeper embed：{e}"
    units = _collect_wb_units(recent_days=recent_days, workspace=workspace)
    if len(units) < 2:
        return "_（无可分析单元）_"
    texts = [u[1] for u in units]
    try:
        vecs = [np.asarray(embed_cached(t), dtype=float) for t in texts]
    except Exception as e:
        return f"[mem_bridge] embed 失败（后端={_emb.backend_info()}）：{e}"

    dups = []
    for a in range(len(units)):
        for b in range(a + 1, len(units)):
            sc = float(_emb.cosine(vecs[a], vecs[b]))
            if sc >= dup_thresh:
                dups.append((sc, a, b))
    dups.sort(reverse=True)

    POS = ["必须", "启用", "推荐", "建议", "应", "用", "开"]
    NEG = ["禁止", "禁用", "避免", "勿", "切忌", "不要", "不用", "关"]
    contra = []
    for sc, a, b in dups:
        if sc < 0.6:
            continue
        ta, tb = units[a][1], units[b][1]
        pa, na = any(k in ta for k in POS), any(k in ta for k in NEG)
        pb, nb = any(k in tb for k in POS), any(k in tb for k in NEG)
        if (pa and nb) or (na and pb):
            contra.append((sc, a, b))

            # B3 过期日志：>stale_days 仍存在的 daily 日志（应已蒸馏进 MEMORY.md）
    stale_logs = set()
    today = _dt.date.today()
    _ws_dir = workspace or WORKSPACE_MEM
    if os.path.isdir(_ws_dir):
        for fn in sorted(os.listdir(_ws_dir)):
            if fn.startswith("20") and fn.endswith(".md") and fn != "MEMORY.md":
                try:
                    d = _dt.datetime.strptime(fn[:10], "%Y-%m-%d").date()
                    if (today - d).days > stale_days:
                        stale_logs.add(fn[:10])
                except Exception:
                    pass

    n_files = len(set(u[0].split(":")[0] for u in units))
    lines = []
    lines.append("## 🧹 WB 记忆体检（keeper 语义卫生教练 · 仅建议不改）")
    lines.append(f"- 扫描：{n_files} 个文件 / {len(units)} 条单元；后端 `{_emb.backend_info()}`")
    # 档① 可安全合并
    merge = [(sc, a, b) for sc, a, b in dups[:top_n] if sc >= 0.92]
    maybe = [(sc, a, b) for sc, a, b in dups[:top_n] if 0.92 > sc >= dup_thresh]
    if merge:
        lines.append(f"- **① 可安全合并（cos≥0.92）：**")
        for sc, a, b in merge:
            lines.append(f"  - `{units[a][0]}` {units[a][1][:42]}…  ↔  `{units[b][0]}` {units[b][1][:42]}…  (cos={sc:.2f})")
    if maybe:
        lines.append(f"- **② 疑似重复待核（{dup_thresh}≤cos<0.92）：**")
        for sc, a, b in maybe:
            lines.append(f"  - `{units[a][0]}` ↔ `{units[b][0]}` (cos={sc:.2f})")
    if not merge and not maybe:
        lines.append("- 重复：未检出")
    if contra:
        lines.append("- **③ 潜在矛盾候选需人工核实（⚠️ 启发式：相似度+正负情感词，非结论对立）：**")
        for sc, a, b in contra[:top_n]:
            lines.append(f"  - `{units[a][0]}` ↔ `{units[b][0]}` (cos={sc:.2f})")
    else:
        lines.append("- 矛盾：未检出")
    if stale_logs:
        lines.append(f"- **④ 过期日志建议归档（>{stale_days}天，应已蒸馏进 MEMORY.md）：** {', '.join(sorted(stale_logs))}")
    else:
        lines.append(f"- 过期日志（>{stale_days}天）：未检出")
    return "\n".join(lines)


    # ---------- D2：B 当 A 的相关性排序器（只读）----------
def rank_wb(query, top_n=5, days=30):
    """
    D2：把 keeper 的语义召回能力用于给 WB 的 L2/L3 单元按 query 相关性排序。
    弥补 A 只能整读、长文里捞不准的短板；agent 只读 top-N。只读不改。
    """
    _ensure_env()
    try:
        import embed as _emb
        import numpy as np
    except Exception as e:
        return f"[mem_bridge] rank 无法加载 keeper embed：{e}"
    units = _collect_wb_units(recent_days=None, max_age_days=days)
    if not units:
        return "_（无可排序单元）_"
    try:
        qv = np.asarray(embed_cached(query), dtype=float)
        vecs = [np.asarray(embed_cached(t), dtype=float) for _, t, _ in units]
    except Exception as e:
        return f"[mem_bridge] embed 失败：{e}"
    scored = []
    for (loc, t, _), v in zip(units, vecs):
        scored.append((float(_emb.cosine(qv, v)), loc, t))
    scored.sort(reverse=True)
    lines = [f"## 🔎 WB 记忆相关性排序（keeper 语义 · query=`{query}`）"]
    for sc, loc, t in scored[:top_n]:
        lines.append(f"- (cos={sc:.2f}) `{loc}` {t[:78]}")
    return "\n".join(lines)


    # ---------- C3：keeper 真遗忘「安全预览 / 受控执行」（绝不自动真删）----------
def purge_keeper(dry=True, older_than_days=180, min_importance=0.4,
                 protect_tags=("src:user", "pinned", "correction", "keep"),
                 max_purge=50):
    """
    C3 安全真遗忘（已统一为 reclaim 回收框架）：对归档/被取代两类软删记忆做受控清理。
    - 默认 dry=True：只报告候选（含被保护的条目），不删任何文件。
    - 真执行需 dry=False（由 CLI `purge --apply` 显式触发，任何自动化都不得自动调用）。
    返回人类可读报告。绝不碰 active 记忆。
    """
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    res = _m.reclaim(root, ttl_days=older_than_days, importance_floor=min_importance,
                     max_archive=max_purge, dry_run=dry)
    lines = []
    lines.append("## 🧽 keeper 回收预览（受控真遗忘 · 默认不删除）")
    lines.append(f"- 策略：归档(180天内未深度召回才删) + 被取代(超 {older_than_days} 天删) + 容量配额环形覆盖；"
                 f"保护 core 层/保护标签/未过期 until/被引用")
    lines.append(f"- 候选删除：{res.get('n_candidates', 0)} 条")
    if res.get("protected"):
        _ps = [f"{p.get('id')}({p.get('reason')})" for p in res["protected"][:10]]
        lines.append(f"- **被保护、本次跳过：{res.get('n_protected', 0)} 条** → {', '.join(_ps)}")
    if res.get("candidates"):
        lines.append(f"- **实际将{'删除' if not dry else '在 --apply 后删除'}：{res.get('n_candidates', 0)} 条**")
        for c in res["candidates"][:max_purge]:
            lines.append(f"  - `{c}`")
    else:
        lines.append("- 实际将删除：0 条（当前库无符合阈值的软删记忆）")
    lines.append(f"- 模式：{'DRY-RUN（未执行）' if dry else 'REAL（已执行删除）'}")
    return "\n".join(lines)


def _days_since_helper(last, now):
    try:
        from datetime import date as _d
        if isinstance(last, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    last = _d.strptime(last[:19], fmt)
                    break
                except Exception:
                    continue
        return (now - last).days
    except Exception:
        return "?"


        # ---------- I6：进行态记忆（半空接班，续上未竟工作）----------
def list_working(top_n=10):
    """I6：列出当前进行态（tier=working）记忆，让 agent 多会话项目「半空接班」。
    只读、不写。返回 Markdown 列表（open 任务/下一步/阻塞点）。"""
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        mems = _m._all_mems(root)
    except Exception as e:
        return f"[mem_bridge] 读取失败：{e}"
    ws = [(mid, m) for mid, m in mems.items()
          if m.get("status") == "active" and m.get("tier") == "working"]
    if not ws:
        return "_（当前无进行态记忆）_"
    ws.sort(key=lambda x: (x[1].get("updated") or ""), reverse=True)
    lines = ["## 📌 进行态记忆（I6 · 半空接班用）",
             f"- 共 {len(ws)} 条 open 任务 / 下一步 / 阻塞点"]
    for mid, m in ws[:top_n]:
        s = (m.get("summary") or "").strip()
        b = (m.get("body") or "").strip().replace("\n", " ")
        lines.append(f"- `[{mid}]` **{s}**：{b}")
    return "\n".join(lines)


    # ---------- I12：关系图（relates_to / corrects / superseded 遍历）----------
def graph_around(mid, top_n=20):
    """I12：以 <MID> 为中心，遍历 relates_to:/corrects/superseded 关系，输出邻接表。
    只读、不写。支持「沙箱删除相关的所有经验」这类遍历查询。"""
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        mems = _m._all_mems(root)
    except Exception as e:
        return f"[mem_bridge] 读取失败：{e}"
    if mid not in mems:
        return f"_（未找到 {mid}）_"
    rel_tag = f"relates_to:{mid}"
    lines = [f"## 🕸️ 关系图（I12 · 中心 `{mid}`）"]
    # 关系①：指向本节点的（relates_to 标签 / corrects / supersedes）
    inbound = []
    for oid, m in mems.items():
        if oid == mid:
            continue
        tags = m.get("tags", []) or []
        rels = m.get("relations", {}) or {}
        if rel_tag in tags or rels.get("corrects") == mid or rels.get("supersedes") == mid:
            inbound.append(oid)
    lines.append("- **指向本节点（关联/纠正）：** " +
                  (", ".join(f"`{o}`" for o in inbound[:top_n]) or "无"))
    # 关系②：本节点指向外
    center = mems[mid]
    crels = center.get("relations", {}) or {}
    outbound = []
    for k in ("corrects", "supersedes", "superseded_by"):
        v = crels.get(k)
        if v:
            outbound.append(f"{k}={v}")
    out_tags = [t for t in (center.get("tags", []) or []) if t.startswith("relates_to:")]
    outbound += out_tags
    lines.append("- **本节点指向外：** " +
                  (", ".join(outbound[:top_n]) or "无"))
    return "\n".join(lines)


    # ---------- I13：上游版本漂移标记 ----------
def drift_check():
    """I13：比对每条记忆落库时的 skill/工具版本（ver: 标签）与当前版本，
    漂移则报告（建议标 stale_review 复核）。只读、不写。"""
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    cur = _keeper_version()
    try:
        mems = _m._all_mems(root)
    except Exception as e:
        return f"[mem_bridge] 读取失败：{e}"
    drifted = []
    for mid, m in mems.items():
        if m.get("status") != "active":
            continue
        tags = m.get("tags", []) or []
        vt = next((t[4:] for t in tags if t.startswith("ver:")), None)
        if vt and vt != cur:
            drifted.append((mid, vt))
    if not drifted:
        return f"_（版本漂移检查：当前 {cur}，无漂移）_"
    lines = [f"## 🔄 版本漂移（I13 · 当前 {cur}）",
             f"- **{len(drifted)} 条记忆的验证版本与当前不符，建议标 stale_review 复核：**"]
    for mid, vt in drifted:
        lines.append(f"  - `{mid}` 落库于 {vt}")
    return "\n".join(lines)


    # ---------- I7：新项目冷启动播种（可调用命令；平台钩子由 SOUL/自动化触发）----------
def seed(domain, top_n=5):
    """I7：按项目领域预载相关经验（结合 D1 三级切分，只进上下文不写文件）。
    这是「新建/打开工作区」钩子应调用的逻辑；沙箱无平台钩子，故暴露为命令供手动/钩子调用。"""
    # F24：废弃遗留 `--domain 量化`（量化域已统一为 investment）。仅告警、不改写数据；
    # 投资记忆冷启动请改用 `python scripts/investment_bridge.py seed --domain investment`。
    if domain == "量化":
        sys.stderr.write(
            "[mem_bridge] ⚠ `--domain 量化` 已废弃：量化域已统一为 `investment`。\n"
            "  投资记忆冷启动请改用：`python scripts/investment_bridge.py seed --domain investment`\n"
            "  存量 `量化` 记忆可一次性迁移（按 taxonomy 重路由 / doctor --fix），本命令不自动改写数据。\n")
    return inject_active(query=domain, top_n=top_n, with_header=True,
                         max_tokens=500, expand=True,
                         explain=False)


    # ---------- I11：日志压缩（LLM 摘要优先；无 LLM 时 extractive 兜底，默认 dry-run）----------
def compress_logs(stale_days=30, apply=False, llm_fn=None):
    """I11：对 >stale_days 的 daily 日志做压缩——抽取关键条目写入 MEMORY.md 月度段，
    原日志移入 .archived/（不删，可回滚）。无 LLM 时做 extractive 兜底（取各段首句/关键行）。
    llm_fn(summary_text)->str 可注入真实 LLM 摘要；沙箱默认 None → extractive。
    默认 dry=True 只报告，--apply 才执行。"""
    if not os.path.isdir(WORKSPACE_MEM):
        return "_（无工作区记忆目录）_"
    today = _dt.date.today()
    cands = []
    for fn in sorted(os.listdir(WORKSPACE_MEM)):
        if fn.startswith("20") and fn.endswith(".md") and fn != "MEMORY.md":
            try:
                d = _dt.datetime.strptime(fn[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - d).days > stale_days:
                cands.append((fn[:10], os.path.join(WORKSPACE_MEM, fn)))
    if not cands:
        return f"_（无 >{stale_days} 天日志需压缩）_"
    if not apply:
        return (f"## 🗜️ 日志压缩预览（I11 · dry-run）\n"
                f"- 待压缩日志（>{stale_days}天）：{len(cands)} 条 → "
                + ", ".join(fn for fn, _ in cands) + "\n"
                "- 加 `--apply` 执行：抽取关键条目并入 MEMORY.md 月度段，原日志移入 .archived/")
        # apply：extractive 兜底——取每篇日志的非标题、较长、含关键词的行作为摘要
    digest_lines = [f"### 日志压缩摘要（{cands[0][0]} ~ {cands[-1][0]}）"]
    for fn, fp in cands:
        with open(fp, encoding="utf-8") as fh:
            raw = fh.read()
        key_lines = [l.strip() for l in raw.splitlines()
                     if l.strip() and not l.startswith("#")
                     and len(l.strip()) >= 16
                     and any(k in l for k in _EXP_KW + _USER_KW + _PROJ_KW)]
        digest_lines.append(f"\n**{fn}**（{len(key_lines)} 条关键）")
        for l in key_lines[:12]:
            digest_lines.append(f"- {l[:100]}")
    summary = "\n".join(digest_lines)
    if callable(llm_fn):
        try:
            summary = llm_fn(raw)
        except Exception:
            pass
    mem_path = os.path.join(WORKSPACE_MEM, "MEMORY.md")
    try:
        with open(mem_path, encoding="utf-8") as fh:
            existing = fh.read()
    except Exception:
        existing = ""
    with open(mem_path, "a", encoding="utf-8") as fh:
        fh.write("\n\n" + summary + "\n")
        # 原日志移入 .archived/（不删）
    arch = os.path.join(WORKSPACE_MEM, ".archived")
    try:
        os.makedirs(arch, exist_ok=True)
    except Exception:
        pass
    moved = []
    for fn, fp in cands:
        dst = os.path.join(arch, fn + ".md")
        try:
            import shutil
            shutil.move(fp, dst)
            moved.append(fn)
        except Exception:
            pass
    return (f"## 🗜️ 日志压缩完成（I11）\n"
            f"- 已并入 MEMORY.md 月度段：{len(cands)} 篇\n"
            f"- 原日志移入 .archived/：{len(moved)} 篇（未删除，可回滚）")


    # ---------- CLI ----------
def _selftest_run(mb_path, store, *cli_args):
    """以隔离 AI_MEMORY_STORE 起子进程跑一条命令，返回 (rc, stdout)。

    v4.4.13（提案 B 硬化）：显式开启 KEEPER_INJECT_ENABLED 并解除每日次数闸与去重门，
    让 selftest 真正走通 inject 主链路（此前 inject 默认关 → 所有 inject 断言拿不到数据而假性失败）。
    同时暴露 distill→recall 的 auto_sourced 隔离行为，由调用方按需传 --include-auto。"""
    env = dict(os.environ)
    env["AI_MEMORY_STORE"] = store
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    env["KEEPER_INJECT_ENABLED"] = "1"
    env["KEEPER_INJECT_DAILY_CAP"] = "999"
    env["KEEPER_INJECT_DEDUP"] = "0"
    try:
        p = subprocess.run([sys.executable, mb_path, *cli_args],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
        return p.returncode, p.stdout + p.stderr
    except Exception as e:  # pragma: no cover
        return 1, str(e)


def _selftest_recall_tags(mb_path, store):
    """隔离库 recall，返回全部 tags 列表（用于断言 sub: 等）。"""
    rc, out = _selftest_run(mb_path, store, "inject", "--top", "20")
    tags = []
    for m in re.findall(r"_([a-z][\w:,]*?)_", out):
        tags.append(m)
    return tags


def _selftest_run_mo(store, *cli_args):
    """以隔离 AI_MEMORY_STORE 起子进程跑 memory_ops CLI 命令，返回 (rc, stdout+stderr)。

    embedding 安装日志会污染 stderr，selftest 只关心命令结果 JSON，因此把 stderr
    也合并进来便于断言（并保留错误信息）。"""
    cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
    env = dict(os.environ)
    env["AI_MEMORY_STORE"] = store
    env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
    try:
        p = subprocess.run([sys.executable, cli, *cli_args],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # pragma: no cover
        return 1, str(e)


def _selftest_json(out):
    """从被日志污染的输出中提取最后一个 JSON 对象（支持嵌套对象）。"""
    if not out:
        return {}
    start = out.rfind("{")
    if start == -1:
        return {}
    for end in range(len(out), start, -1):
        try:
            return json.loads(out[start:end])
        except Exception:
            continue
    return {}


def selftest():
    """整改回归自测：隔离 AI_MEMORY_STORE，自动化核心路径与安全不变量，断言通过率。
    覆盖：合法/非法 subtype、guard 检测、预算截断、promote、agent 模式 brief、
    delete --yes 闸门、to-l2 路径穿越拦截。
    任何一项失败立即暴露（避免带 bug 发布）。"""
    import shutil
    import tempfile
    mb_path = os.path.abspath(__file__)
    store = os.path.join(tempfile.gettempdir(), "mem_bridge_selftest")
    shutil.rmtree(store, ignore_errors=True)
    os.makedirs(store, exist_ok=True)
    results = []
    def check(name, cond, detail=""):
        results.append((name, cond))
        mark = "✅" if cond else "❌"
        line = f"  [{mark}] {name}"
        if not cond and detail:
            line += f" — {detail[:80]}"
        print(line)
    print("== mem_bridge 回归自测（隔离库）==")
    # 1) 合法 subtype → 落 sub: 标签
    _selftest_run(mb_path, store, "distill", "--category", "correction",
                  "--subtype", "technical", "--summary", "s", "--body", "b", "--tags", "t")
    tags = _selftest_run(mb_path, store, "inject", "--top", "20", "--include-auto")[1]
    check("合法 subtype 落 sub: 标签", "sub:technical" in tags, tags[:5])
    # 2) 非法 subtype → 优雅不崩（不抛 UnboundLocalError）
    rc, out = _selftest_run(mb_path, store, "distill", "--category", "correction",
                            "--subtype", "BOGUS", "--summary", "x", "--body", "y", "--tags", "t")
    check("非法 subtype 优雅处理（无 UnboundLocalError）",
          ("UnboundLocalError" not in out) and ("忽略未知 sub-type" in out), out[:80])
    check("非法 subtype 不落 sub: 标签", "sub:BOGUS" not in tags)
    # 3) guard 检测 路径/邮箱/内部信息（用占位值，避免发布包被平台字面扫描误报）
    # 注意：路径用 Z:/mock 这种明显非真实盘的占位；邮箱用 RFC2606 保留的 .invalid 域；
    # 内部信息词是 guard 自身词表，属预期命中，非真实泄露。
    rc, out = _selftest_run(mb_path, store, "guard", "--text",
                            "Z:/mock/sample fake@test.invalid 内网部门")
    check("guard 命中 real_path", "real_path" in out, out[:60])
    check("guard 命中 email", "email" in out, out[:60])
    check("guard 命中 internal_info", "internal_info" in out, out[:60])
    # 4) 预算截断（注入多条后 --budget-lines 1 应出截断标注）
    for i in range(3):
        _selftest_run(mb_path, store, "distill", "--summary", f"多余条目{i}",
                      "--body", "b", "--tags", "t")
    rc, out = _selftest_run(mb_path, store, "inject", "--budget-lines", "1", "--include-auto")
    check("A2 预算截断标注出现", "截断" in out, out[-60:])
    # 5) promote --review 不崩
    rc, out = _selftest_run(mb_path, store, "promote", "--review")
    check("promote --review 正常", rc == 0 and "待确认" in out, out[:60])
    # 6) agent 模式 brief（coach/reflect）
    rc, out = _selftest_run(mb_path, store, "--from-agent", "coach")
    check("coach --from-agent 含推理委托 brief", "推理委托" in out, out[:60])
    rc, out = _selftest_run(mb_path, store, "--from-agent", "reflect")
    check("reflect --from-agent 含推理委托 brief", "推理委托" in out, out[:60])
    # 7) G1 投资 domain + 子域 + G5 param + G2 valid_until
    _selftest_run(mb_path, store, "distill", "--domain", "investment",
                  "--subdomain", "risk_control", "--param", "stop_loss=8%",
                  "--valid-until", "2026Q4", "--summary", "风控经验",
                  "--body", "b", "--tags", "t")
    tags_i = _selftest_run(mb_path, store, "inject", "--domain", "investment",
                           "--top", "30", "--include-auto")[1]
    check("G1 投资 domain 召回命中", "风控经验" in tags_i, tags_i[:40])
    check("G1 排除非投资经验", "多余条目" not in tags_i, tags_i[:60])
    check("G1 subdomain 落 sub: 标签", "sub:risk_control" in tags_i, tags_i[:60])
    check("G5 param 落 param: 标签", "param:stop_loss=8%" in tags_i, tags_i[:60])
    check("G2 valid_until 落 until: 标签", "until:2026-12-31" in tags_i, tags_i[:60])
    # 8) G2 --filter-fresh 隐藏过期经验
    _selftest_run(mb_path, store, "distill", "--summary", "过期经验",
                  "--body", "b", "--tags", "t", "--valid-until", "2020Q1")
    out_fresh = _selftest_run(mb_path, store, "inject", "--filter-fresh", "--top", "30", "--include-auto")[1]
    check("G2 filter-fresh 隐藏过期经验", "过期经验" not in out_fresh, out_fresh[:60])
    # 9) 安全不变量：delete 缺 --yes 必须拒绝执行（不可逆物理删除需显式确认）
    rc, out = _selftest_run_mo(store, "init")
    rc, out = _selftest_run_mo(store, "deposit", "--category", "best_practice",
                                "--summary", "待删测试", "--body", "测试 delete --yes 闸门")
    mid = _selftest_json(out).get("id", "")
    rc_no_yes, out_no_yes = _selftest_run_mo(store, "delete", "--id", mid or "LRN-NOEXIST")
    check("delete 缺 --yes 拒绝执行",
          "confirm_required" in out_no_yes, out_no_yes[:60])
    # 10) 安全不变量：to-l2 --export 路径穿越必须被拦截（禁止写库外）
    # 先确认有 active L4 候选可被导出
    rc, out = _selftest_run_mo(store, "deposit", "--category", "best_practice",
                               "--summary", "高价值待导出", "--body", "正文足够长正文足够长正文足够长正文足够长正文足够长",
                               "--importance", "0.9")
    rc, out = _selftest_run(mb_path, store, "to-l2", "--min-importance", "0.1",
                            "--min-access", "0", "--export", "../evil_selftest.md")
    check("to-l2 export 路径穿越被拦截",
          "禁止路径穿越" in out, out[:120])
    # 汇总
    passed = sum(1 for _, c in results if c)
    total = len(results)
    print(f"== 结果：{passed}/{total} 通过 ==")
    return 0 if passed == total else 1


    # ---------- D2/D3：确定性衰减 + recurrence 入口（反超竞品 LLM 心算）----------
def decay_k(dry_run=True, lambda_=0.03):
    """D2 入口：确定性重算 relevance_score（反超 LLM 心算）。
    默认 dry-run 预览；`--apply` 才写盘。返回人类可读报告。"""
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        res = _m.decay_apply(root, lambda_=lambda_, dry_run=dry_run)
    except Exception as e:
        return f"[mem_bridge] decay 失败：{e}"
    n = res.get("updated", 0)
    return (f"## 📉 确定性衰减（D2 · {'DRY-RUN 预览' if dry_run else '已执行写盘'}）\n"
            f"- 重算 {n} 条 active 记忆的 relevance_score（λ={lambda_}）\n"
            f"- 公式：importance·e^(-λ·Δdays)·(1+√access)·type_weight\n"
            f"- 结果写入 relevance_score 并重排 thermal（长期未用/低频经验自然降级）")


def recurrence_k(min_count=3):
    """D3 入口：按 pattern_key 报告重复模式簇（确定性 recurrence，非 LLM grep）。"""
    _ensure_env()
    try:
        import memory_ops as _m
    except Exception as e:
        return f"[mem_bridge] 无法加载 keeper：{e}"
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    try:
        res = _m.recurrence_report(root, min_count=min_count)
    except Exception as e:
        return f"[mem_bridge] recurrence 失败：{e}"
    groups = res.get("groups", [])
    if not groups:
        return f"_（无 recurrence_count≥{min_count} 的重复模式簇）_"
    lines = [f"## 🔁 重复模式簇（D3 · 确定性 recurrence，≥{min_count} 次）",
             f"- 共 {len(groups)} 个模式被重复沉积（代码强制，非 LLM 心算）"]
    for g in groups[:20]:
        lines.append(f"  - ×{g['count']} [{g['category']}] {g['summary']} → {','.join(g['mids'][:5])}")
    return "\n".join(lines)


def taxonomy_k(mode, json_path=None, dry_run=False):
    """用户场景分类树管理（向导产物落地）：mode=apply|show|reclassify。

    - apply：把向导生成的 taxonomy JSON 持久化到 store/taxonomy.json（经 save_taxonomy 原子写+校验）
    - show：渲染当前分类树（人类可读）
    - reclassify：按 taxonomy 关键词把现有活跃记忆重路由到自定义域/子域（advisory）"""
    try:
        import memory_ops as _m
    except Exception as e:
        return json.dumps({"ok": False, "error": "load_fail", "msg": str(e)}, ensure_ascii=False)
    root = _m.resolve_root(KEEPER_ROOT) if hasattr(_m, "resolve_root") else KEEPER_ROOT
    if mode == "show":
        try:
            tax = _m.load_taxonomy(root)
        except Exception as e:
            return f"[mem_bridge] 读取 taxonomy 失败：{e}"
        return _format_taxonomy(tax)
    if mode == "apply":
        if not json_path or not os.path.isfile(json_path):
            return json.dumps({"ok": False, "error": "missing_json",
                               "msg": "需 --json <路径> 指向 taxonomy 文件"}, ensure_ascii=False)
        try:
            with open(json_path, encoding="utf-8") as f:
                tax = json.load(f)
        except Exception as e:
            return json.dumps({"ok": False, "error": "bad_json", "msg": str(e)}, ensure_ascii=False)
        try:
            _m.save_taxonomy(root, tax)
        except ValueError as e:
            return json.dumps({"ok": False, "error": "invalid_taxonomy", "msg": str(e)}, ensure_ascii=False)
        return json.dumps({"ok": True, "msg": "taxonomy 已持久化（向导分类树已生效）",
                           "path": _m._taxonomy_path(root)}, ensure_ascii=False)
    if mode == "reclassify":
        try:
            r = _m.reclassify_by_taxonomy(root, dry_run=dry_run)
        except Exception as e:
            return json.dumps({"ok": False, "error": "reclassify_fail", "msg": str(e)}, ensure_ascii=False)
        return json.dumps({"ok": True, **r}, ensure_ascii=False)
    return json.dumps({"ok": False, "error": "bad_mode", "msg": mode}, ensure_ascii=False)


def _format_taxonomy(tax):
    """把 taxonomy 渲染成人类可读树（供 --show / 引导确认时查看）。"""
    lines = ["=== 用户记忆分类树（taxonomy）===", ""]
    up = tax.get("user_profile") or {}
    if isinstance(up, dict):
        name = up.get("name") or "（未设置）"
        roles = "、".join(up.get("roles", []) or []) or "（未设置）"
        scenes = "、".join(up.get("scenarios", []) or []) or "（未设置）"
        lines.append("用户: %s | 角色: %s | 高频场景: %s" % (name, roles, scenes))
        lines.append("")
    for d in tax.get("domains", []):
        hb = d.get("heat_budget")
        rt = d.get("retention") or {}
        head = "- %s（%s）" % (d.get("label", d["key"]), d["key"])
        if hb:
            head += "  热位配额≤%s" % hb
        if rt:
            head += "  留存:%sd/imp≥%s" % (rt.get("stale_days", "?"), rt.get("min_importance", "?"))
        lines.append(head)
        for s in d.get("subdomains") or []:
            lines.append("    - %s（%s）  关键词:%s" % (
                s.get("label", s["key"]), s["key"],
                "、".join(s.get("keywords") or []) or "（无）"))
    lines.append("")
    lines.append("回退域(fallback): %s" % tax.get("fallback_domain", "general"))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="WB<->keeper 共进型桥接")
    ap.add_argument("--from-agent", action="store_true",
                    help="B2 声明本次调用来自 Agent 会话（零配置走『Agent 自身推理』模式）；"
                         "也可由 env WB_AGENT_SESSION=1 自动识别")
    sub = ap.add_subparsers(dest="op", required=True)
    pi = sub.add_parser("inject")
    pi.add_argument("--query", default=None)
    pi.add_argument("--top", type=int, default=5)
    pi.add_argument("--max-tokens", type=int, default=400,
                    help="A3 动态注入预算上限（token 估算），默认 400")
    pi.add_argument("--budget-lines", type=int, default=100,
                    help="A2 HOT/WARM/COLD 行数硬预算（默认 100 行，0=不限）；超预算截断并标注")
    pi.add_argument("--no-expand", action="store_true",
                    help="关闭 A2 查询扩展")
    pi.add_argument("--no-header", action="store_true")
    pi.add_argument("--reinforce", action="store_true",
                    help="I1：inject 后对 surfaced MID 自动 touch（被动强化），写 stderr 不污染注入")
    pi.add_argument("--explain", action="store_true",
                    help="I9 出处可视化：每条经验附 score/imp/命中 query")
    pi.add_argument("--domain", default=None,
                    help="G1 域过滤（investment/work/personal/project）：只召回匹配域经验")
    pi.add_argument("--subdomain", default=None,
                    help="G1 投资子域过滤（risk_control/position_mgmt/...）：经 sub: 标签过滤")
    pi.add_argument("--filter-fresh", action="store_true",
                    help="G2 隐藏已过期（until:<今天）经验，避免误导多年回测决策")
    pi.add_argument("--include-auto", action="store_true",
                    help="A 提案：包含被动捕获暂存项（auto_sourced，默认隔离）；"
                         "让蒸馏/捕获的暂存记忆也能被 inject 召回（需配合 KEEPER_INJECT_ENABLED=1）")
    pstat = sub.add_parser("inject_stats",
                           help="P1-2 测量：返回自反馈双闸门状态（每日次数闸 + 去重门），"
                                "含被去重抑制的累计次数（回路强度指标）")
    pd = sub.add_parser("distill")
    pd.add_argument("--text", default=None)
    pd.add_argument("--file", default=None)
    pd.add_argument("--summary", default=None)
    pd.add_argument("--body", default=None)
    pd.add_argument("--tags", default=None)
    pd.add_argument("--category", default="best_practice")
    pd.add_argument("--source", default="wb_memory")
    pd.add_argument("--llm", default=None, choices=["agent", "ollama", "openai", "off"],
                    help="B1 LLM 模式：agent=内容由 Agent 自身模型提供（零配置，默认在 Agent 会话内）；"
                         "ollama/openai=标记外部 LLM 生成来源；off=纯规则。Agent 调用时 --text/--summary 即 Agent 已提炼内容")
    pd.add_argument("--scope", default="cross",
                    choices=["user", "project", "cross"])
    pd.add_argument("--project", default=None, help="D1 绑定项目名")
    pd.add_argument("--corrects", default=None,
                    help="C2 被推翻的旧经验 MID，自动 supersede 形成纠正链")
    pd.add_argument("--abstract", action="store_true",
                    help="I3 抽象阶梯：额外生成「通用原则」层（scope=universal + principle + relates_to）")
    pd.add_argument("--check-conflict", action="store_true",
                    help="I5 检测 B 内近重复→自动 supersede 避免重复。"
                         "⚠️ 矛盾侧为启发式告警（相似度+正负情感词），误报多，"
                         "只作定位线索，须人工读正文裁定，勿据此直接隔离")
    pd.add_argument("--quarantine-conflict", action="store_true",
                    help="I5 矛盾候选送 quarantine 待审（需配合 --check-conflict）。"
                         "⚠️ 送隔离前须人工读正文确认结论确相悖（启发式告警不等同矛盾）")
    pd.add_argument("--tier", default="seed",
                    choices=["seed", "working", "curated", "core"],
                    help="I6 记忆 tier（默认 seed；进行态用 working）")
    pd.add_argument("--working", action="store_true",
                    help="I6 工作记忆：tier=working + 打 working 标签（open 任务/下一步/阻塞点）")
    pd.add_argument("--decision", action="store_true",
                    help="I8 决策与理由记忆：category=decision（选择+理由+备选+否决原因）")
    pd.add_argument("--no-guard", action="store_true",
                    help="I10 关闭写前敏感护栏（路径/邮箱/内部信息脱敏）；仅信任的内部内容用")
    pd.add_argument("--subtype", default=None,
                    help="A3 纠正子类型（correction 类用）：format/technical/communication/project/personal，"
                         "归一为 sub:<type> 标签；其余类别忽略")
    pd.add_argument("--domain", default=None,
                    help="G1 域（investment/work/personal/project）；investment 落 domain 字段")
    pd.add_argument("--subdomain", default=None,
                    help="G1 投资子域（risk_control/position_mgmt/industry_analysis/stock_analysis/"
                         "data_pipeline/backtest/strategy/execution）→ sub: 标签")
    pd.add_argument("--param", action="append", default=[],
                    help="G5 结构化数值经验，可重复：--param stop_loss=8%% --param max_pos=30%%（→ param: 标签）")
    pd.add_argument("--valid-until", default=None,
                    help="G2 时效：2026Q4 / 2026-12-31 → until: 标签；配合 --filter-fresh 过滤")
    pd.add_argument("--source-quirk", default=None,
                    help="G3 数据源坑专存：--source-quirk wind（→ quirk: 标签，记数据源特有坑）")
    pd.add_argument("--status", default=None, choices=["testing", "production", "deprecated"],
                    help="G4 测试→生产生命周期：testing/production/deprecated（→ st: 标签）")
    pr = sub.add_parser("rank")
    pr.add_argument("--query", required=True)
    pr.add_argument("--top", type=int, default=5)
    pr.add_argument("--days", type=int, default=30)
    prt = sub.add_parser("route")
    prt.add_argument("--text", required=True)
    prr = sub.add_parser("retrieve",
                         help="I2 即时检索：动手前按子任务拉最相关经验（主动顾问）")
    prr.add_argument("--task", required=True, help="当前子任务描述，拉取最相关经验")
    prr.add_argument("--top", type=int, default=5)
    prr.add_argument("--max-tokens", type=int, default=400,
                     help="A3 动态注入预算上限（token 估算），默认 400")
    prr.add_argument("--budget-lines", type=int, default=100,
                     help="A2 HOT/WARM/COLD 行数硬预算（默认 100 行，0=不限）；超预算截断并标注")
    prr.add_argument("--no-expand", action="store_true", help="关闭 A2 查询扩展")
    prr.add_argument("--no-header", action="store_true")
    prr.add_argument("--explain", action="store_true",
                     help="I9 出处可视化：每条经验附 score/imp/命中 query")
    prr.add_argument("--domain", default=None,
                    help="G1 域过滤（investment/work/personal/project）：只召回匹配域经验")
    prr.add_argument("--subdomain", default=None,
                    help="G1 投资子域过滤（risk_control/position_mgmt/...）：经 sub: 标签过滤")
    prr.add_argument("--filter-fresh", action="store_true",
                    help="G2 隐藏已过期（until:<今天）经验，避免误导多年回测决策")
    prr.add_argument("--include-auto", action="store_true",
                    help="（向后兼容，默认已包含）包含被动捕获暂存项（auto_sourced）")
    prr.add_argument("--exclude-auto", action="store_true",
                    help="显式排除被动捕获暂存项（auto_sourced，默认已包含）")
    pc = sub.add_parser("capture",
                        help="I4 会话内失败自捕获：把报错/纠正起草为 correction（默认草稿不落盘）")
    pc.add_argument("--text", required=True, help="失败/纠正内容（工具报错或用户纠正）")
    pc.add_argument("--corrects", default=None, help="被推翻的旧经验 MID（形成纠正链）")
    pc.add_argument("--commit", action="store_true",
                    help="确认落盘为 correction 记忆（默认仅打印草稿）")
    pa = sub.add_parser("scan_dup", help="I5 只读审计：扫描 B 主线内部近重复与矛盾（原同名 audit，与 memory_ops audit 异义，已更名消歧）")
    pw = sub.add_parser("working", help="I6 列出进行态记忆（半空接班，续上未竟工作）")
    pw.add_argument("--top", type=int, default=10)
    pg = sub.add_parser("graph", help="I12 关系图：以某 MID 为中心遍历关联/纠正链")
    pg.add_argument("--around", required=True, help="中心记忆 MID，如 LRN-xxx")
    pg.add_argument("--top", type=int, default=20)
    pguard = sub.add_parser("guard", help="I10 发布前安全检查：扫描文本/文件泄露并报告")
    pguard.add_argument("--text", default=None, help="待检查文本")
    pguard.add_argument("--file", default=None, help="待检查文件")
    pd2 = sub.add_parser("drift", help="I13 版本漂移检查：比对记忆落库版本与当前版本")
    pseed = sub.add_parser("seed", help="I7 冷启动播种：按领域预载相关经验（供工作区钩子调用）")
    pseed.add_argument("--domain", required=True, help="项目领域，如 investment/小说/开发（注：量化 已废弃→investment）")
    pseed.add_argument("--top", type=int, default=5)
    pcomp = sub.add_parser("compress", help="I11 日志压缩：>N 天日志抽取摘要并入 MEMORY.md")
    pcomp.add_argument("--stale", type=int, default=30, help="过期天数阈值，默认 30")
    pcomp.add_argument("--apply", action="store_true", help="执行（默认仅 dry-run 预览）")
    pc = sub.add_parser("coach")
    pc.add_argument("--dup", type=float, default=0.82)
    pc.add_argument("--days", type=int, default=5)
    pc.add_argument("--top", type=int, default=20)
    pc.add_argument("--stale", type=int, default=30,
                    help="B3 过期日志阈值（天），默认 30")
    pc.add_argument("--workspace", default=None,
                    help="显式指定工作区 .workbuddy/memory 目录（绝对路径）；缺省回退 _resolve_workspace_mem 的解析（env/注册表/cwd）。周任务调度用此精确锁定工作区，避免依赖导入期 cwd")
    pc.add_argument("--llm", default=None, choices=["agent", "off"],
                    help="B1 LLM 模式：agent=在规则体检后追加『推理委托』brief，由 Agent 自身模型合成建议（零配置，默认在 Agent 会话内）；off=仅规则体检")
    preflect = sub.add_parser("reflect", help="B1 双模式自检：规则 reflect + 可选 Agent 推理委托 / Ollama 离线增强")
    preflect.add_argument("--llm", default=None,
                          choices=["agent", "ollama", "openai", "off"],
                          help="B1 LLM 模式：agent=规则结果后追加『推理委托』brief（零配置，默认 Agent 会话内）；"
                               "ollama/openai=透传 keeper reflect --llm（需先 llm-setup 配端点）；off=纯规则")
    preflect.add_argument("--stale", type=int, default=90,
                          help="过期记忆阈值（天），默认 90")
    preflect.add_argument("--auto", action="store_true",
                          help="执行安全自动动作（过期记忆归档，不删除）")
    pp = sub.add_parser(
        "purge",
        help="C3 受控真删（默认 DRY-RUN）。⚠️ 边界：只筛「已归档/已被取代」且超龄(默认180天)、"
             "低重要度(默认<0.4)的软删记忆；active（含今天刚记的）永不在候选内——"
             "清当天噪音请用 reflect --auto 或 archive，purge 不承担（详见 SKILL.md §九）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="C3 受控真删（默认 DRY-RUN 预览；加 --apply 才真删，不可逆）。\n"
                    "\n"
                    "⚠️ 范围边界（最常被误用的一处）：候选仅含「已归档 / 已被取代」两类软删记忆，\n"
                    "且须同时满足「超龄（默认 180 天）」与「低重要度（默认 <0.4）」。\n"
                    "active 条目——含今天刚记的——永远不在候选内，所以本命令清不掉「当天噪音」，\n"
                    "跑出「0 条候选」属正常，不是 bug。\n"
                    "\n"
                    "清当天噪音请用：reflect --auto（去重/纠错/归档，永不删除）\n"
                    "                或 archive --id <id>（单条软归档，可 unarchive 撤回）。")
    pp.add_argument("--apply", action="store_true",
                    help="C3 真执行删除（默认仅 DRY-RUN 预览）。需显式，绝不自动。")
    pp.add_argument("--older", type=int, default=180,
                    help="超龄天数阈值（仅对「已归档/已被取代」的软删件生效，不影响 active），默认 180")
    pp.add_argument("--min-imp", type=float, default=0.4,
                    help="重要度下限（≥此值不删），默认 0.4")
    ppromote = sub.add_parser("promote", help="A1 晋升环：自主晋升/合并（--auto）或用户确认晋升（--review/--confirm）")
    ppromote.add_argument("--review", action="store_true",
                          help="列出高频但未分类/低置信的待确认晋升候选（不直接晋升）")
    ppromote.add_argument("--confirm", default=None,
                          help="确认晋升的 MID 列表，逗号分隔；tier→curated 并打 confirmed_by_user")
    ppromote.add_argument("--min-access", type=int, default=3,
                          help="A1 高频阈值（access_count≥此值），默认 3")
    ppromote.add_argument("--min-conf", type=float, default=0.6,
                          help="A1 低置信阈值（confidence<此值算低），默认 0.6")
    ppromote.add_argument("--auto", action="store_true",
                          help="自主晋升+合并：按启发式自己判断并行动，无需人确认（默认 dry-run 预览）")
    ppromote.add_argument("--apply", action="store_true",
                          help="与 --auto 搭配：真正落盘（默认仅预览决策）；--apply 不写盘则只出决策报告")
    ppromote.add_argument("--merge", dest="merge", action="store_true", default=True,
                          help="--auto 时对重复簇自动合并（保留最佳、其余 archive；可 unarchive 找回）")
    ppromote.add_argument("--no-merge", dest="merge", action="store_false",
                          help="--auto 时只晋升不合并")
    ppromote.add_argument("--min-relevance", type=float, default=0.6,
                          help="--auto 晋升相关性阈值（relevance_score 或 importance≥此值）")
    ppromote.add_argument("--min-age-days", type=int, default=30,
                          help="--auto 晋升最小龄期（天）")
    ptl2 = sub.add_parser("to-l2", help="P2 跨系统晋升导出：筛选高价值 L4 经验生成草稿（MD/JSON），由用户/AI 经 WB 自身捕获落 L2/L3；不直写 WB 文件")
    ptl2.add_argument("--min-importance", type=float, default=0.7,
                      help="晋升候选重要性阈值（importance≥此值），默认 0.7")
    ptl2.add_argument("--min-access", type=int, default=3,
                      help="晋升候选访问频次阈值（access_count≥此值），默认 3")
    ptl2.add_argument("--top", type=int, default=30, help="最多导出条数，默认 30")
    ptl2.add_argument("--export", default=None,
                      help="草稿输出路径（默认 <store>/to_l2_draft.<md|json>）")
    ptl2.add_argument("--format", default="md", choices=["md", "json"],
                      help="草稿格式，默认 md")
    ptl2.add_argument("--dry-run", action="store_true",
                      help="仅统计候选、不写草稿文件（预览哪些会被导出）")
    pf = sub.add_parser("feedback", help="I1 闭环使用反馈：强化/弱化 keeper 经验")
    pf.add_argument("--mid", default=None, help="MID 列表，逗号分隔，如 LRN-xxx,LRN-yyy")
    pf.add_argument("--good", action="store_true",
                    help="正反馈：升 confidence/importance（经验确实帮上忙）")
    pf.add_argument("--bad", action="store_true",
                    help="负反馈：降 confidence/importance（经验误导/已过时，供 I5 检测）")
    pf.add_argument("--used", action="store_true",
                    help="中性：仅记录「被使用」（touch，刷新 accessed），不改重要度")
    pf.add_argument("--from-inject", action="store_true",
                    help="对上次 inject 记录的全部 MID 反馈（会话结束强化用）")
    ps = sub.add_parser("selftest", help="整改回归自测：隔离库自动化核心路径，发布前必跑")
    pdcy = sub.add_parser("decay", help="D2 确定性衰减：重算 relevance_score（默认 dry-run 预览）")
    pdcy.add_argument("--apply", action="store_true", help="写盘执行（默认仅预览）")
    pdcy.add_argument("--lambda", type=float, default=0.03, dest="decay_lambda",
                      help="衰减系数 λ（默认 0.03，越大过期越快）")
    prc = sub.add_parser("recurrence", help="D3 重复模式簇报告（确定性 recurrence）")
    prc.add_argument("--min-count", type=int, default=3, help="最小重复阈值（默认 3）")
    pidx = sub.add_parser("summary-index", help="Layer2 紧凑路由视图：domain|subdomain|count|摘要|hints|updated（<50行，recall 前看路由表）")
    ptre = sub.add_parser("tree-view", help="Layer3 冷存储树形可视化：domain→subdomain→topic")
    ptax = sub.add_parser("taxonomy", help="用户场景分类树：向导产物 apply / 查看 show / 重分类 reclassify")
    ptax.add_argument("--apply", action="store_true", help="持久化向导生成的分类树（需 --json）")
    ptax.add_argument("--json", help="taxonomy JSON 文件路径（--apply 用）")
    ptax.add_argument("--show", action="store_true", help="查看当前分类树")
    ptax.add_argument("--reclassify", action="store_true",
                      help="按 taxonomy 把现有记忆重路由到自定义域/子域（advisory）")
    ptax.add_argument("--dry-run", action="store_true", help="reclassify 仅报告不写盘")
    # ：批量导入 / 性能基准 / MCP 服务（引擎 op 的 mem_bridge 统一入口，转发 memory_ops CLI）
    pimp = sub.add_parser("import", help="批量导入记忆（JSONL/JSON/CSV/MD → deposit，复用去重/分类全流程）")
    pimp.add_argument("--file", required=True, help="待导入文件路径")
    pimp.add_argument("--format", default="auto", choices=["auto", "jsonl", "json", "csv", "md"],
                      help="文件格式（默认 auto 嗅探）")
    pimp.add_argument("--root", default=None,
                      help="目标库（默认真实库；隔离测试可指定独立目录）")
    pimp.add_argument("--execute", action="store_true", help="真实写入记忆库（默认仅 dry-run 预览）")
    pimp.add_argument("--keep-ids", action="store_true", help="复用记录原 id（默认新生成）")
    pimp.add_argument("--on-error", choices=["skip", "abort"], default="skip", help="遇坏行策略")
    pimp.add_argument("--report", default=None, help="逐条结果 JSON 报告路径")
    pbench = sub.add_parser("benchmark", help="性能基准：批量写入吞吐 + 随机 recall 时延（p50/p95/avg）")
    pbench.add_argument("--root", required=True,
                        help="隔离目录（必填；禁止对默认真实记忆库跑，否则写入合成记忆污染召回）")
    pbench.add_argument("--n", type=int, default=200, help="合成记忆条数")
    pbench.add_argument("--recall-times", type=int, default=50, help="recall 次数")
    pbench.add_argument("--top-n", type=int, default=10, help="每次 recall 返回条数")
    pbench.add_argument("--ann", action="store_true", help="走 ANN 加速路径")
    pbench.add_argument("--topics", type=int, default=20, help="topic 数量空间")
    pbench.add_argument("--out", default=None, help="JSON 报告输出路径")
    pmcp = sub.add_parser("mcp", help="把 keeper 暴露为 MCP 服务（stdio 长驻，供 Claude/Cursor 等连）")
    pmcp.add_argument("--root", default=None,
                      help="目标库（默认真实库；可指定独立目录）")
    args = ap.parse_args()

    # B2：运行时置位 Agent 会话覆盖（--from-agent 或 env WB_AGENT_SESSION=1）
    global _AGENT_OVERRIDE, IN_AGENT
    _AGENT_OVERRIDE = bool(args.from_agent)
    IN_AGENT = _in_agent_session()

    if args.op == "inject":
        _bl = args.budget_lines
        if args.domain == "investment" and _bl == 100:  # G6：投资场景预算提升
            _bl = 200
        out = inject_active(query=args.query, top_n=args.top,
                            with_header=not args.no_header,
                            max_tokens=args.max_tokens,
                            expand=not args.no_expand,
                            explain=args.explain,
                            max_lines=_bl,
                            domain=args.domain, subdomain=args.subdomain,
                            filter_fresh=args.filter_fresh,
                            include_auto=args.include_auto)
        if args.reinforce:
            try:
                with open(INJECT_LAST, encoding="utf-8") as fh:
                    mids = (json.load(fh) or {}).get("mids", []) or []
                if mids:
                    fb = feedback_batch(mids, signal=None)
                    sys.stderr.write(
                        f"[I1 reinforce] touched {fb.get('succeeded')}/{fb.get('applied')} surfaced MIDs\n")
            except Exception as e:
                sys.stderr.write(f"[I1 reinforce] 跳过：{e}\n")
        print(out)
    elif args.op == "inject_stats":
        print(json.dumps(inject_stats(), ensure_ascii=False))
    elif args.op == "feedback":
        signal = "good" if args.good else ("bad" if args.bad else None)
        if args.from_inject:
            res = feedback_batch(from_inject=True, signal=signal)
        else:
            mids = [m.strip() for m in (args.mid or "").split(",") if m.strip()]
            res = feedback_batch(mids, signal=signal)
        print(json.dumps(res, ensure_ascii=False))
    elif args.op == "selftest":
        sys.exit(selftest())
    elif args.op == "coach":
        mode = _resolve_llm_mode(args.llm)
        out = coach_wb(dup_thresh=args.dup, recent_days=args.days,
                       top_n=args.top, stale_days=args.stale,
                       workspace=args.workspace)
        if mode == "agent":
            out = _append_agent_brief(out, "coach")
        print(out)
    elif args.op == "reflect":
        mode = _resolve_llm_mode(args.llm)
        print(reflect_wb(mode=mode, stale_days=args.stale, auto=args.auto))
    elif args.op == "rank":
        print(rank_wb(query=args.query, top_n=args.top, days=args.days))
    elif args.op == "route":
        tier, reason = route_target(args.text)
        print(f"## 🧭 三级切分建议\n- **目标层：{tier}**\n- 理由：{reason}\n- 原文：{args.text[:60]}")
    elif args.op == "retrieve":
        _bl = args.budget_lines
        if args.domain == "investment" and _bl == 100:  # G6：投资场景预算提升
            _bl = 200
        print(inject_active(query=args.task, top_n=args.top,
                            with_header=not args.no_header,
                            max_tokens=args.max_tokens,
                            expand=not args.no_expand,
                            explain=args.explain,
                            max_lines=_bl,
                            domain=args.domain, subdomain=args.subdomain,
                            filter_fresh=args.filter_fresh,
                            include_auto=not args.exclude_auto,
                            respect_inject_gate=False))
    elif args.op == "capture":
        print(capture_failure(args.text, corrects=args.corrects, commit=args.commit))
    elif args.op == "scan_dup":
        print(audit_b())
    elif args.op == "working":
        print(list_working(top_n=args.top))
    elif args.op == "graph":
        print(graph_around(args.around, top_n=args.top))
    elif args.op == "guard":
        txt = args.text
        if not txt and args.file:
            try:
                with open(args.file, encoding="utf-8") as fh:
                    txt = fh.read()
            except Exception as e:
                print(json.dumps({"ok": False, "err": str(e)}, ensure_ascii=False))
                return
        hits = _scan_publish_leak(txt or "")
        if hits:
            uniq = {}
            for n, s in hits:
                uniq.setdefault(n, []).append(s)
            rep = {n: vs[:3] for n, vs in uniq.items()}
            print(json.dumps({"leak": True, "by_type": rep,
                              "redacted_preview": _redact_publish_leak(txt or "")[:200]},
                             ensure_ascii=False))
        else:
            print(json.dumps({"leak": False, "msg": "未发现路径/邮箱/通用token/内部信息泄露"},
                            ensure_ascii=False))
    elif args.op == "drift":
        print(drift_check())
    elif args.op == "seed":
        print(seed(args.domain, top_n=args.top))
    elif args.op == "compress":
        print(compress_logs(stale_days=args.stale, apply=args.apply))
    elif args.op == "purge":
        print(purge_keeper(dry=not args.apply, older_than_days=args.older,
                           min_importance=args.min_imp))
    elif args.op == "promote":
        if args.auto:
            _ensure_env()
            cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
            env = dict(os.environ)
            env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
            cmd = [sys.executable, cli, "promote", "--auto",
                   "--min-relevance", str(args.min_relevance),
                   "--min-access", str(args.min_access),
                   "--min-age-days", str(args.min_age_days)]
            if args.apply:
                cmd.append("--apply")
            if not args.merge:
                cmd.append("--no-merge")
            try:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
                print(proc.stdout or proc.stderr)
            except Exception as e:
                print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        elif args.confirm:
            mids = [m.strip() for m in args.confirm.split(",") if m.strip()]
            print(promote_confirm(mids))
        else:
            print(promote_review(min_access=args.min_access, min_conf=args.min_conf))
    elif args.op == "to-l2":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        # 注意：不强制 AI_MEM_EMBED_BACKEND=fastembed。to-l2 只需枚举 L4 条目，
        # 用库自身配置/默认后端即可；强制 fastembed 会让词法后端（或沙箱无模型）的库
        # 召回失败，导致 to-l2 静默无候选、F7 的"0 候选解释"也到不了。
        try:
            proc = subprocess.run([sys.executable, cli, "recall"], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            d = json.loads(proc.stdout or "{}")
            entries = d.get("entries", [])
        except Exception as e:
            print(json.dumps({"ok": False, "error": "recall failed: %s" % e},
                             ensure_ascii=False))
            return
        path, n, diag = to_l2_draft(entries, min_importance=args.min_importance,
                                    min_access=args.min_access, top_n=args.top,
                                    export_path=args.export, fmt=args.format,
                                    dry_run=args.dry_run)
        if path:
            print(json.dumps({"ok": True, "draft": path, "count": n, "diag": diag},
                             ensure_ascii=False))
        elif args.dry_run:
            print(json.dumps({"ok": True, "draft": None, "count": n,
                              "dry_run": True,
                              "note": diag.get("reason"),
                              "diag": diag},
                             ensure_ascii=False))
        else:
            print(json.dumps({"ok": True, "draft": None, "count": n,
                              "note": diag.get("reason"),
                              "diag": diag},
                             ensure_ascii=False))
    elif args.op == "summary-index":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
        try:
            proc = subprocess.run([sys.executable, cli, "summary-index"], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            d = json.loads(proc.stdout or "{}")
            print(d.get("readable", proc.stdout))
        except Exception as e:
            print("[mem_bridge] summary-index 失败：%s" % e)
    elif args.op == "tree-view":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        env.setdefault("AI_MEM_EMBED_BACKEND", "fastembed")
        try:
            proc = subprocess.run([sys.executable, cli, "tree-view"], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
            d = json.loads(proc.stdout or "{}")
            print(d.get("readable", proc.stdout))
        except Exception as e:
            print("[mem_bridge] tree-view 失败：%s" % e)
    elif args.op == "distill":
        tags = args.tags.split(",") if args.tags else None
        ids, msg = distill_to_keeper(
            text=args.text, file=args.file, summary=args.summary,
            body=args.body, tags=tags, category=args.category,
            source=args.source, scope=args.scope,
            project=args.project, corrects=args.corrects,
            abstract=args.abstract,
            check_conflict=args.check_conflict,
            quarantine_conflict=args.quarantine_conflict,
            tier=args.tier, working=args.working, decision=args.decision,
            no_guard=args.no_guard,
            llm_mode=_resolve_llm_mode(args.llm),
            subtype=args.subtype,
            domain=args.domain, subdomain=args.subdomain, params=args.param,
            valid_until=args.valid_until, source_quirk=args.source_quirk,
            status=args.status)
        print(json.dumps({"ids": ids, "msg": msg}, ensure_ascii=False))
    elif args.op == "decay":
        print(decay_k(dry_run=not args.apply, lambda_=args.decay_lambda))
    elif args.op == "recurrence":
        print(recurrence_k(min_count=args.min_count))
    elif args.op == "taxonomy":
        _mode = ("apply" if args.apply else
                 "show" if args.show else
                 "reclassify" if args.reclassify else None)
        if _mode is None:
            print(json.dumps({"ok": False, "error": "no_action",
                              "msg": "taxonomy 需指定 --apply/--show/--reclassify"}, ensure_ascii=False))
        elif _mode == "show":
            print(taxonomy_k("show"))
        else:
            print(taxonomy_k(_mode, json_path=args.json, dry_run=args.dry_run))
    elif args.op == "import":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        cmd = [sys.executable, cli, "import", "--file", args.file,
               "--import-format", args.format, "--on-error", args.on_error]
        if args.root:
            cmd += ["--root", args.root]
        if args.execute:
            cmd.append("--execute")
        if args.keep_ids:
            cmd.append("--keep-ids")
        if args.report:
            cmd += ["--report", args.report]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                  encoding="utf-8", timeout=600)
            print(proc.stdout or proc.stderr)
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
    elif args.op == "benchmark":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        cmd = [sys.executable, cli, "benchmark", "--root", args.root,
               "--n", str(args.n),
               "--recall-times", str(args.recall_times), "--top-n", str(args.top_n),
               "--topics", str(args.topics)]
        if args.ann:
            cmd.append("--ann")
        if args.out:
            cmd += ["--out", args.out]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                  encoding="utf-8", timeout=600)
            print(proc.stdout or proc.stderr)
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
    elif args.op == "mcp":
        _ensure_env()
        cli = os.path.join(KEEPER_SKILL, "memory_ops", "__init__.py")
        env = dict(os.environ)
        # 长驻 MCP 服务：继承父进程 stdin/stdout，供 MCP 客户端经管道通信
        try:
            cmd = [sys.executable, cli, "mcp"]
            if args.root:
                cmd += ["--root", args.root]
            subprocess.run(cmd, env=env)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
