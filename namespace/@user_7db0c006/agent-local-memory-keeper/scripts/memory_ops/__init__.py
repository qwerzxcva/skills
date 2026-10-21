#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory_ops (package) — Agent 本地记忆系统：本地文件存储与语义召回的命令行操作入口

CLI 操作（python scripts/memory_ops/__init__.py <op> ... 或 python -m memory_ops <op>）：
deposit    沉淀（写 memories/<id>.json + 登记 index；--tier / --corrects 自动纠错 / --scope / --project；
G1 落原生 --domain 域字段；G5 写 param: 标签；G2 写 until:；G3 写 quirk:；G4 写 st:）
recall     召回（tag/category/query/tier/min-tier/scope/project/deep 过滤；含 relations；--domain 域内优先）
touch      显式刷新 accessed（记录「被真正使用」的上下文证据）
overwrite  覆盖（同文件改写 body/summary/tags，原地 true-overwrite，version+1；自动快照可回滚）
delete     删除（物理删文件 + 移除 index 条目；须 --yes）
archive / unarchive   归档 / 解除归档（沉底不销毁，可找回）
rebuild    重建（扫描 memories/ 与 memories/archive/ 两处反推 index）
link       关联（see_also / superseded_by / corrected_by）
promote    晋升（tier: working→curated→core，召回时按重要度加权）
reflect    反思/巩固引擎（去重、矛盾检测、分类复评、过期归档、晋升候选——自我改进闭环，绝不删除）
doctor     健康自检（索引↔文件双向一致性/孤儿/悬空关系/损坏；--fix 安全对账，不删内容）
reclassify 显式重分类 + 强学习进分类器（避免反复误判）
init       首次准备（建目录 + 空 index，幂等，开箱即用）
decay      D2 确定性衰减：decay_apply() 重算 relevance_score
（relevance = importance · e^(-λ·Δdays) · (1+√access) · type_weight，真实代码，非 LLM 心算）
recurrence D3 确定性重复模式簇：recurrence_report() 按 pattern_key 分组
（category+summary 归一化 md5，可复现，非 LLM grep）

代码地图（功能分区，按函数簇而非行号，避免随重构漂移）：
· 路径/默认值   ：_default_store_root() / DEFAULTS（回退链：AI_MEMORY_STORE → ~/.keeper/store_root → 平台默认 ~/AI记忆 或 ~/.ai-memory）
· 记忆模型      ：_deposit_impl() / _all_mems() / 记忆 dict 字段
（pattern_key / first_seen / last_seen / recurrence_count / relevance_score）
· 召回管线      ：recall() / _route_* / _rrf_fuse() / embed 集成（fastembed 神经语义 + 词法兜底）
· 反思/纠错     ：reflect() / _auto_correct() / _detect_contradiction() / _merge_similar()
· 确定性派生    ：decay_apply() / recurrence_report() / _pattern_key() / _days_since_accessed()
· 安全          ：_scan_sensitive()（写前敏感信息一票否决，定义在 scripts/kernel.py）/ 并发乐观 mtime 守卫
· 沙箱补丁      ：delete ctypes 兜底真删 / harvest --dry-run 守卫（由 _patch_keeper_sandbox.py 幂等重放）

所有路径以 --root 为基准；默认走回退链：AI_MEMORY_STORE → ~/.keeper/store_root → 平台默认（Windows ~/AI记忆，mac/Linux ~/.ai-memory）。
沙箱必须传独立的 --root 临时副本。
"""
import argparse
import contextlib
import copy
import json
import os
import shutil
import uuid
import re
import sys
import threading
import time
import datetime
import hashlib
import math
import sqlite3 as _sqlite3
import zipfile

# F18 惰性解析自引用：让各子模块内部可用 `memory_ops.NAME` 引用包级属性
# （PEP 562 __getattr__ 兜底），从而移除人工反向注入。各子模块命名空间由 loader
# 的 `mod.__dict__.update(globals)` 注入本引用。
memory_ops = sys.modules[__name__]

# F18 包化兼容：作为脚本直接运行（python scripts/memory_ops/__init__.py <op>）时，
# Python 仅把 scripts/memory_ops/ 加入 sys.path[0]，导致同级 kernel.py / memory_schema.py /
# trigger_dict.py / embed.py 等无法 import（ModuleNotFoundError）。这里把 scripts/ 目录显式
# 加入搜索路径，恢复与「扁平 scripts/memory_ops.py」时代完全一致的导入行为。
# 当以包形态 import memory_ops 时（__name__=="memory_ops"）此分支不触发，零副作用。
if __name__ == "__main__":
    _SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _SCRIPTS_DIR and _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)

        # ：状态机/优先级/领域枚举 + 触发词典（纯加性，旧库缺字段降级）
try:
    from memory_schema import (normalize_state, normalize_priority,
                               normalize_area, normalize_about_axis, safe_fields,
                               DEFAULT_STATE, DEFAULT_PRIORITY, DEFAULT_AREA, STATE_ENUM)
    import trigger_dict
except Exception:  # 极端情况下（如直接拷贝单文件）降级为内置兜底，保证不崩
    def normalize_state(v, default="pending"):
        return v if v in ("pending", "confirmed", "resolved", "wont_fix") else default
    def normalize_priority(v, default="normal"):
        return v if v in ("low", "normal", "high", "critical") else default
    def normalize_area(v, default="learning"):
        return v if v in ("bugfix", "feature", "learning", "decision") else default
    def normalize_about_axis(v, default=None):
        return v if v in ("user", "self", "relationship", "world") else default
    def safe_fields(state=None, priority=None, area=None, about_axis=None):
        return {"state": normalize_state(state), "priority": normalize_priority(priority),
                "area": normalize_area(area), "about_axis": normalize_about_axis(about_axis)}
    DEFAULT_STATE, DEFAULT_PRIORITY, DEFAULT_AREA = "pending", "normal", "learning"
    STATE_ENUM = ("pending", "confirmed", "resolved", "wont_fix")
    class trigger_dict:
        @staticmethod
        def infer_trigger_hints(text, roots=None):
            return (None, None, "")

            # ：纯函数/常量区拆分（敏感扫描 + id 校验）——便于单测/fuzz，行为零变化
from kernel import (_UNSAFE_MID_CHARS, _is_safe_mid, _assert_safe_mid,
                     _SENSITIVE_PATTERNS, _SCAN_FAST_GATES, _SCAN_CHAR_BUDGET,
                     _scan_sensitive)
try:  # 跨进程文件锁（best-effort，并发串行化用；真正正确性由 mtime 乐观并发守卫保证）
    import fcntl as _fcntl  # POSIX
except ImportError:
    _fcntl = None
try:
    import msvcrt as _msvcrt  # Windows
except ImportError:
    _msvcrt = None

    # 离线 embedding / 主体抽取（零依赖、可离线，解决 O5/G1/G2）
import contextlib
@contextlib.contextmanager
def _quiet_import():
    """第三方库（fastembed/transformers/sentencepiece）import 时可能向 stdout 打印
    警告（如 "Error importing huggingface_hub..."），会污染本技能的 JSON 输出契约、
    导致 AI 解析失败。import 期间临时把 stdout/stderr 重定向到 devnull，import 失败仍
    以异常形式正常抛出（不被吞）。"""
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = open(os.devnull, "w"); sys.stderr = open(os.devnull, "w")
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err

try:
    with _quiet_import():
        import embed as _emb
except ImportError:  # 运行目录不在 sandbox/ 时按文件位置兜底
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    with _quiet_import():
        import embed as _emb

        # 自主学习分类器（多信号判断 + 自我纠正， 新增）
try:
    with _quiet_import():
        import classifier as _clf
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    with _quiet_import():
        import classifier as _clf

        # F18 阶段2：配置与默认值独立为 memory_ops/_config.py（原 L138-L170 整段，零行为变化）。
        # 用按文件绝对路径加载，兼容 regression 以 spec_from_file_location 独立加载 __init__.py
        # 的场景（相对导入在该场景会 ModuleNotFoundError）。
import importlib.util as _ilu
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_config.py")
_cfg_spec = _ilu.spec_from_file_location("memory_ops._config", _cfg_path)
_config = _ilu.module_from_spec(_cfg_spec)
sys.modules["memory_ops._config"] = _config
_cfg_spec.loader.exec_module(_config)
_default_root = _config._default_root
DEFAULT_ROOT = _config.DEFAULT_ROOT


def _root_key(p):
    """root 判等 / 缓存键用的规范化形式：解析相对路径、`~`，统一大小写与分隔符。

    🔴 为什么必须用它：`D:/<库路径>` 与 `D:\\<库路径>` 指向同一个库，但**字符串不相等**。
    2026-09-16 实锤两处受害：
      ① benchmark 护栏 `args.root == DEFAULT_ROOT` 被 `D:/<库路径>` 绕过 → 200 条合成
         记忆写进真库（护栏失效，属数据事故）；
      ② recall 磁盘缓存把同一 root 劈成两套命名空间（`D:\\<库路径>` 1 条 / `D:/<库路径>`
         18 条），跨进程命中率被无故腰斩。
    凡「判断两个 root 是否同一库」或「用 root 作缓存键」一律走本函数，勿再手写比较。
    """
    if not p:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.path.expanduser(str(p))))
    except Exception:
        return str(p)


TIERS = _config.TIERS
CONTRADICTABLE = _config.CONTRADICTABLE
CORRECTING = _config.CORRECTING
CONTRADICTION_SEM_THRESHOLD = _config.CONTRADICTION_SEM_THRESHOLD
_OPPOSITE_MARKERS = _config._OPPOSITE_MARKERS

# 记忆分类（scope）：通用必记 / 工作专属 / 一次性。默认 universal = 安全默认（宁可留着，不埋没）
SCOPES = ("universal", "project", "ephemeral")

# ── 记忆类型（type）封闭枚举 + 规范化（Phase 1）──────────────────────────
# 设计基线 §2.2：type 为封闭互斥清单，根治「category 自由字符串导致跨会话归类不一致」。
# 原 category 字段保留作原始输入追溯；type 为规范化后的 规范类型（短码）。
TYPE_CANON = ("BP", "WF", "PF", "PREF", "FACT", "DOC")
# 旧版/别名 → 规范 type 映射（记忆原文不变，仅归类规范化；内容零损失）
TYPE_ALIASES = {
    "best_practice": "BP", "workflow": "WF", "pitfall": "PF", "preference": "PREF",
    "fact": "FACT", "document": "DOC", "doc": "DOC",
# 旧版长命名
    "architecture_decision": "BP", "principle": "BP",
    "convention": "PREF",           # 约定/惯例 → 用户长期偏好（修分类不一致：harvest 用 convention 但旧归 FACT）
    "correction": "PF",              # 纠错记忆本质是「别这样做」的坑
    "error": "PF", "integration_error": "PF",
    "feature_request": "FACT", "knowledge_gap": "FACT",
    "technical_constraint": "PREF",
    "workbuddy_memory": "FACT",
# 短码（旧库 category 常见小写下划线/缩写）：bp/wf/pf/pref/fact/doc
    "bp": "BP", "wf": "WF", "pf": "PF", "pref": "PREF",
}
TYPE_DEFAULT = "FACT"               # 未知 → FACT（设计基线「未知归 FACT」）

# ── §6.2 格式分化渲染（canonical 唯一源 + 双渲染）──────────────────────────
# 每条记忆只存一份 canonical 完整内容（summary+body+tags+type）；热/冷只是不同「渲染
# 视图」，流动时只换渲染、绝不丢信息（设计基线 §6.2）。本段为纯函数、无副作用。
_TYPE_RENDER_KEYS = ("type", "category")   # render 取 type 优先，缺则回退 category

def _mem_type_code(mem):
    """取规范 type 短码（BP/WF/PF/PREF/FACT/DOC）；缺省 FACT。"""
    if not isinstance(mem, dict):
        return TYPE_DEFAULT
    for k in _TYPE_RENDER_KEYS:
        t = mem.get(k)
        if t:
            return _normalize_type(t)
    return TYPE_DEFAULT

def render_hot(mem):
    """热记忆渲染（喂 LLM 前部 / 紧凑模板）：`[TYPE] summary ｜ 标签… ｜ 要点…`。

    - 省 token、易解析、无 emoji 噪音（设计基线 §6.2）。
    - 全角 `｜` 分隔、显式 `[TAG]`、短句；body 仅取首 60 字作「要点」。
    - 返回**单行**字符串（无换行）。"""
    if not isinstance(mem, dict):
        mem = {}
    parts = ["[%s]" % _mem_type_code(mem)]
    s = (mem.get("summary") or "").strip()
    if s:
        parts.append(s)
    tags = mem.get("tags") or []
    if tags:
        parts.append("标签 " + "/".join(tags[:4]))
    body = (mem.get("body") or "").strip().replace("\n", " ")
    if body:
        parts.append("要点 " + body[:60])
    return " ｜ ".join(parts)

def render_cold(mem):
    """冷记忆渲染（做 embedding / 完整叙述）：保留上下文与因果、关键词丰富，
    保 embedding 语义质量（设计基线 §6.2）。多行、信息全。"""
    if not isinstance(mem, dict):
        mem = {}
    lines = ["[%s]" % _mem_type_code(mem)]
    s = (mem.get("summary") or "").strip()
    if s:
        lines.append("摘要: " + s)
    body = (mem.get("body") or "").strip()
    if body:
        lines.append("详述: " + body.replace("\n", " "))
    tags = mem.get("tags") or []
    if tags:
        lines.append("标签: " + " ".join(tags))
    scope = mem.get("scope")
    if scope:
        lines.append("范围: " + scope)
    return "\n".join(lines)

def _embed_text_for(mem):
    """记忆落向量用的文本：统一走 render_cold（完整叙述、语义最稳）。"""
    return render_cold(mem)

def _normalize_type(cat):
    """category（任意字符串）→ 规范 type；未知/空归 FACT。纯函数、无副作用。"""
    if cat in TYPE_CANON:
        return cat
    c = (cat or "").strip().lower()
    if c in TYPE_CANON:
        return c
    if c in TYPE_ALIASES:
        return TYPE_ALIASES[c]
        # 模糊匹配：去分隔符后比对
    norm = c.replace("_", "").replace("-", "").replace(" ", "")
    for k, v in TYPE_ALIASES.items():
        if k.replace("_", "").replace("-", "").replace(" ", "") == norm:
            return v
    return TYPE_DEFAULT

    # ── 冷热分层（Phase 1 建立字段 + 计算；路由/配额在 Phase 2 落地）────────────
HEAT_HALF_LIFE_DAYS = 14          # 热度衰减半衰期（天）= 两周动态轮替周期
COLD_THRESHOLD_DAYS = 90          # 沉 cold 天数阈值
PROBE_PERIOD_DAYS = 14            # 沉淀观察期（天）
THERMAL_NEWBIE_PROTECTION_DAYS = 7  # v3.1.4 P1-3：新记忆 7 天新手保护期，不判 cold

# §7 · 自动汲取查重（H1/H2 修复）：写库前近重复拦截阈值
_CAPTURE_DEDUP_ON = True           # deposit 默认开启写前查重（advisory，失败不阻断）
_CAPTURE_DEDUP_SUPERSEDE = 0.88    # active 近重复（≥此分）→ 自动 supersede 旧记忆（H1）
_CAPTURE_DEDUP_RESURRECT = 0.90    # archived 近重复（≥此分）→ 复活复用，不再造新重复（H2）
# 修复：lexical 回退模式下语义相似度对「同结构不同内容」文本偏高（实测不同内容≈0.886、
# 完全相同=1.0），若沿用 0.88/0.90 会把本应不同的记忆误判为重复→过度 supersede/复活致数据丢失。
# 故 lexical 模式用更严阈值（仅放过近乎完全相同的文本），neural 模式维持原阈值不变。
_CAPTURE_DEDUP_SUPERSEDE_LEXICAL = 0.99
_CAPTURE_DEDUP_RESURRECT_LEXICAL = 0.99
SETTLE_AUTO_FLOOR = 0.5            # E2 修复：从 0.75 降到 0.5，使 universal(默认 0.6) 也能达标沉淀
# P1 · importance 用 reuse 信号更新（修 H8：不再只靠类别先验）
IMPORTANCE_USE_DELTA = 0.05         # 每次被 recall 真正引用（touch）→ 上调，封顶 1.0
IMPORTANCE_DECAY = 0.95             # reflect 长冷未访问 → 缓慢衰减（≥0.9 安全闸不衰减）
IMPORTANCE_DECAY_FLOOR = 0.1        # 衰减下限，避免沉 0
IMPORTANCE_MIN_USE = IMPORTANCE_DECAY_FLOOR  # 低于此视为「从未被证明有用」
# 改进 P0-2：importance 衰减触发解耦——recall 入口懒检查
# 原仅 reflect_v30 内做衰减，若用户长期不跑 reflect，冷记忆 importance 永停峰值、占热配额。
# recall 入口每 DECAY_LAZY_CHECK_INTERVAL_DAYS 天懒触发一次轻量衰减（不跑全量 reflect）。
DECAY_LAZY_CHECK_INTERVAL_DAYS = 7  # 懒检查间隔（天），可在 config.json 的 decay.lazy_check_days 覆盖
DECAY_LAZY_STALE_DAYS = 90          # 懒衰减的 stale 阈值（与 reflect 默认一致）
# 5.0.x：陈旧判定加「次数」维度——超 stale_days 但访问次数 ≥ 此阈值者豁免衰减，
# 避免「长时间不开机 → 自然日累积 → 把仍反复验证有用的记忆冤枉老化」。
# 阈值 2 与 settle 的「访问≥2 即沉淀」口径一致（低频 0/1 次才走衰减）。
DECAY_HIGH_USAGE_FLOOR = 2

# P2 · 敏感 quarantine（修 H3：命中敏感不再静默丢弃，改为可逆隔离待审）
QUARANTINE_ENABLED = True
# P2 · 真遗忘 purge（修 H5：只降不删 → 可真正删除过期记忆）
PURGE_DEFAULT_DRY_RUN = True
PURGE_MAX_PER_RUN = 200
# P2 · reflect 重分类（修分类脆弱）：每轮最多 LLM 重分类条数（防 O(n) 失控）
RECLASSIFY_LLM_CAP = 30
RECLASSIFY_MIN_CONF = 0.7          # LLM 重分类置信门槛（低于则不改写分类）

def _parse_date(s):
    try:
        return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def heat_recent(mem, now=None, access_n=None):
    """近两周衰减热度：heat = Σ 0.5^(days/14) over 访问事件；新记忆=0。

    优先用 accessed_from 的逐次访问日期（最准）；无逐次记录时退化为
    access_count × 最近访问衰减（粗估）。返回 float，约 0~N。
    5.0/A1：`access_n` 传单一热源（recall_counts.json）的真实召回次数；
    不传则回退 `mem["access_count"]`——该字段真库 204/211 条恒 0，会让退化分支恒为 0。"""
    if now is None:
        now = datetime.date.today()
    evs = [e.get("date") for e in (mem.get("accessed_from") or []) if e.get("date")]
    if evs:
        h = 0.0
        for d in evs:
            pd = _parse_date(d)
            if not pd:
                continue
            days = max(0, (now - pd).days)
            h += 0.5 ** (days / HEAT_HALF_LIFE_DAYS)
        return round(h, 4)
    ac = int(mem.get("access_count", 0) or 0) if access_n is None else int(access_n or 0)
    last = _parse_date(mem.get("accessed", ""))
    rec = 1.0
    if last:
        rec = 0.5 ** (max(0, (now - last).days) / HEAT_HALF_LIFE_DAYS)
    return round(ac * rec, 4)

    # B1 域感知：域封闭枚举 + tags→domain 推断
    # F19 能力区注册表：新增能力圈只需在此登记，KNOWN_DOMAINS 自动派生，
    # 不再硬编码（消除「加能力圈须改核心 + 复制 seed/bridge 脚本」痛点）。
    # 每项字段：
    # taxonomy = 该域 taxonomy 文件名（相对 references/，可 None）
    # seed_fn = 冷启动播种入口模块（可 None）
    # bridge_module = 专用桥模块名（可 None，通用走 mem_bridge）
CAPABILITY_ZONES = {
    "investment": {"taxonomy": "investment_taxonomy.json",
                   "seed_fn": "scripts.investment_seed",
                   "bridge_module": "scripts.investment_bridge"},
    "work":     {"taxonomy": None, "seed_fn": None, "bridge_module": None},
    "personal": {"taxonomy": None, "seed_fn": None, "bridge_module": None},
    "project":  {"taxonomy": None, "seed_fn": None, "bridge_module": None},
}

def get_zone(domain):
    """安全取能力区配置；未知域返回空 dict（不抛）。"""
    return CAPABILITY_ZONES.get(domain, {})

KNOWN_DOMAINS = tuple(CAPABILITY_ZONES.keys())  # 由注册表派生，勿硬编码

def _infer_domain(tags):
    """从 tags 推断 domain（取首个已知域标签）；无则返回 None。"""
    if not tags:
        return None
    for t in tags:
        if t in KNOWN_DOMAINS:
            return t
    return None

    # 多轴 taxonomy 第二轴：scene（使用场景）
    # 与 topic 轴（domain+subdomain）正交：domain=讲的是什么，scene=什么时候/什么场景下用。
    # 例如「Wind EDB 月度拉取单 ID 稳定」→ topic=work.devops / scene=incident（出问题时调出的经验）。
    # 又如「金蝶用网页版更稳」→ topic=work.tools / scene=setup（配置阶段踩的坑）。
    # ：场景轴拆为「软件场景」与「投资场景」两个互不相交的家族。
    # 投资场景统一带 `inv:` 命名空间（inv:backtest 等），与通用软件场景彻底解耦，
    # 消除「复盘/学习」「调仓/复盘」类平局歧义；旧库裸写 backtest 仍可经 _normalize_scene 归一。
SOFTWARE_SCENES = ("onboarding", "setup", "release", "incident", "debugging",
                   "research", "maintenance", "learning", "conversation", "general")
INV_SCENES = ("backtest", "rebalance", "premarket", "intraday", "postmarket")
INV_SCENE_PREFIX = "inv:"
SCENE_CANON = SOFTWARE_SCENES + tuple(INV_SCENE_PREFIX + s for s in INV_SCENES)
# ：scene 别名归一（用户口语化输入也能命中）
SCENE_ALIASES = {
    "onboarding":   ("onboarding", "首次", "上手", "入门", "安装", "new", "init", "start"),
    "setup":        ("setup", "配置", "环境", "配环境", "部署前", "环境配置"),
    "release":      ("release", "发布", "上线", "出包", "版本", "deploy", "publish"),
    "incident":     ("incident", "事故", "出问题了", "线上问题", "故障", "生产事故"),
    "debugging":    ("debugging", "调试", "排查", "定位", "根因", "debug"),
    "research":     ("research", "调研", "评估", "对比", "选型", "可行性"),
    "maintenance":  ("maintenance", "维护", "巡检", "清理", "归档", "备份", "迁移"),
    "learning":     ("learning", "学习", "总结", "读后感", "读书"),
    "conversation": ("conversation", "对话", "沟通", "会议", "汇报", "对齐", "协作"),
# ：投资场景统一 inv: 命名空间（别名首元素为裸写形式，便于旧数据归一）
    "inv:backtest":     ("backtest", "回测", "回溯", "历史测试", "策略测试"),
    "inv:rebalance":    ("rebalance", "调仓", "换仓", "再平衡", "仓位调整"),
    "inv:premarket":    ("premarket", "盘前", "开盘前", "早盘前", "盘前计划"),
    "inv:intraday":     ("intraday", "盘中", "交易时段", "盘中监控", "实时"),
    "inv:postmarket":   ("postmarket", "复盘", "盘后", "收盘后", "总结当天", "收盘复盘"),
}

# ── 在线 LLM 场景分类（问题①根因修复：替代纯关键词误判）──────────────
# 与 _classify_type_llm 完全对称：在线 LLM 是「用户正在使用的线上模型」，
# 推理在云端完成、本地零算力；无 LLM 配置时退化为 _classify_scene 关键词兜底（带置信度）。

# ── 用户场景分类分层：taxonomy.json 数据层（P1）──────────────────────
# 用户首次使用由 agent 引导生成「专属记忆分类树 + 分层策略」，落盘 store/taxonomy.json。
# 该文件可选：不存在时退化为 默认（KNOWN_DOMAINS + general 兜底），全向后兼容。

def _default_type_conf(category):
    """ A1 类型分类置信默认：
    - 直接规范成员（如 BP/PF/WF）→ 1.0（显式高置信）；
    - 经别名/原始串归一到规范（如 pitfall→PF）→ 0.8（映射，留可重审空间）；
    - 非规范（防御性）→ 0.6。
    形成真实梯度，避免『一律 1.0』使低置信重审永不被触发。"""
    c = (category or "").upper()
    if c in TYPE_CANON:
        return 1.0
    nt = _normalize_type(category or "")
    return 0.8 if nt in TYPE_CANON else 0.6

    # D2/D3：确定性衰减 + 模式追踪（以确定性计算反超 LLM 心算）
    # 竞品里这些只是「让 LLM 心算」的提示词；keeper 用真代码确定性实现，结果可复现。
_TYPE_WEIGHT = {  # 类型权重：纠正/工作流类经验更该被长期保留
    "PF": 1.2, "WF": 1.1, "BP": 1.0, "PREF": 1.0, "FACT": 1.0, "DOC": 0.9,
}

# 改进 P1-1：分类规则表外置为 config.json 配置
# 原硬编码关键词表不可配置，用户无法针对自己的语料调整分类规则。
# 现支持在 config.json 的 classify 块覆盖关键词/阈值，默认值与原硬编码完全一致。
TYPE_RULES_DEFAULTS = {
    "PREF": {"keywords": ["用户习惯", "永远", "必须", "不要", "喜欢", "讨厌",
                          "反感", "拒绝", "偏好", "口味", "每次都", "别给我",
# #18: English preference keywords
                          "preference", "always", "never", "must", "habit",
                          "like", "hate", "dislike", "refuse"],
             "confidence": 0.7},
    "DOC": {"min_length": 400, "confidence": 0.5},
    "PF": {"keywords": ["坑", "踩过", "别做", "反例", "失败", "报错", "出错",
                        "禁忌", "切忌", "阻塞", "卡死", "踩坑",
# #18: English pitfall keywords
                        "pitfall", "trap", "mistake", "error", "fail", "failed",
                        "bug", "gotcha", "watch out", "don't do", "caution"],
           "confidence": 0.7},
    "WF": {"keywords": ["流程", "→", "->", "步骤",
# #18: English workflow keywords
                        "workflow", "process", "steps", "procedure",
                        "pipeline", "step 1", "step 2", "first then"],
           "confidence": 0.6},
    "FACT": {"keywords": ["事实", "常量", "路径", "端口", "版本", "api key",
                          "配置", "地址", "2026", "2025", "2024",
# #18: English fact keywords
                          "fact", "constant", "path", "port", "version",
                          "config", "address", "endpoint", "environment"],
             "confidence": 0.6},
    "BP": {"confidence": 0.5},  # 默认兜底
}
_TYPE_RULES_CACHE = {}  # (root, mtime) → rules dict

def _load_type_rules(root):
    """读取分类规则：默认 TYPE_RULES_DEFAULTS，config.json 的 classify 块可逐项覆盖。
    支持覆盖每类的关键词列表和置信度，以及 DOC 的 min_length 阈值。"""
    cfg_root = os.path.join(root, "config.json")
    try:
        mtime = os.path.getmtime(cfg_root) if os.path.exists(cfg_root) else 0
    except Exception:
        mtime = 0
    cache_key = (root, mtime)
    if cache_key in _TYPE_RULES_CACHE:
        return _TYPE_RULES_CACHE[cache_key]

    rules = {}
    for t, defaults in TYPE_RULES_DEFAULTS.items():
        rules[t] = dict(defaults)
        if isinstance(defaults.get("keywords"), list):
            rules[t]["keywords"] = list(defaults["keywords"])

    try:
        if os.path.exists(cfg_root):
            with open(cfg_root, encoding="utf-8") as f:
                c = json.load(f)
            cc = c.get("classify", {})
            if isinstance(cc, dict):
                for t in TYPE_RULES_DEFAULTS:
                    tc = cc.get(t, {})
                    if isinstance(tc, dict):
                        if "keywords" in tc and isinstance(tc["keywords"], list):
                            rules[t]["keywords"] = [str(k) for k in tc["keywords"]]
                        if "confidence" in tc:
                            rules[t]["confidence"] = float(tc["confidence"])
                        if "min_length" in tc:
                            rules[t]["min_length"] = int(tc["min_length"])
    except Exception:
        pass  # config 损坏用默认值

    _TYPE_RULES_CACHE[cache_key] = rules
    return rules

def classify_type(summary, body="", tags=None, root=None):
    """ 类型规则初判（设计基线 §2.2 判定规则 + 混淆矩阵）。
    返回 (type, confidence, reasons)。LLM 路由在 Phase 2；此处为纯规则兜底，
    供 harvest / 自动汲取在 Phase 3 调用。
    P1-1：root 参数可选，传入时从 config.json 加载可配置规则。"""
    text = " ".join([summary or "", body or "", " ".join(tags or [])]).lower()
    # P1-1：优先使用 config.json 可配置规则，无 root 时回退硬编码默认
    rules = _load_type_rules(root) if root else TYPE_RULES_DEFAULTS
    # PREF：用户长期习惯/口味（强信号）
    _kw = rules.get("PREF", {}).get("keywords", [])
    if any(k in text for k in _kw):
        return "PREF", rules.get("PREF", {}).get("confidence", 0.7), ["rule:preference"]
        # PF：坑/别做（与 BP 互补）。注意：仅"防击穿/防雪崩"是 BP（预防做法），
        # 故"击穿/雪崩"不列入 PF 触发词（避免把预防措施误判为坑）。
        # #1 修复：PF 优先于 DOC——长坑文（400+字）此前被判 DOC 而非 PF，系统性误分类。
    _kw = rules.get("PF", {}).get("keywords", [])
    if any(k in text for k in _kw):
        return "PF", rules.get("PF", {}).get("confidence", 0.7), ["rule:pitfall"]
        # WF：多步流程/顺序（含"流程"或"→/->"或"步骤"任一序列标记即判）
    _kw = rules.get("WF", {}).get("keywords", [])
    if any(k in text for k in _kw):
        return "WF", rules.get("WF", {}).get("confidence", 0.6), ["rule:workflow"]
        # FACT：客观事实/环境常量
    _kw = rules.get("FACT", {}).get("keywords", [])
    if any(k in text for k in _kw):
        return "FACT", rules.get("FACT", {}).get("confidence", 0.6), ["rule:fact"]
        # DOC：长文/报告摘要（兜底型——只在不含 PF/WF/FACT 关键词时才判 DOC，
        # 避免长坑文/长流程被误判为文档摘要）
    _min_len = rules.get("DOC", {}).get("min_length", 400)
    if len(text) > _min_len:
        return "DOC", rules.get("DOC", {}).get("confidence", 0.5), ["rule:document:long"]
        # 默认 BP（可复用方法/步骤）
        # A1：规则置信偏低时，用嵌入原型分类器做「兜底升级」——
        # 若已有 ≥3 条同类型样本，取质心最近者；其置信高于规则则采用（type_via='embedding'）。
        # 纯检索、fail-open（异常/N/A/未开开关一律回退规则），不引入 LLM 延迟与依赖。
        # 默认关闭（不改变既有行为、不增加门禁回归风险）；设 KEEPER_TYPE_EMB_FALLBACK=1 开启。
    _rule_type, _rule_conf = "BP", rules.get("BP", {}).get("confidence", 0.5)
    if root and _rule_conf < 0.6 and os.environ.get("KEEPER_TYPE_EMB_FALLBACK") == "1":
        try:
            _emb_ret = _classify_by_embedding_prototype(root, summary, body, tags)
            if _emb_ret and _emb_ret[1] > _rule_conf:
                return _emb_ret[0], round(_emb_ret[1], 4), (_emb_ret[2] or []) + ["embedding:prototype"]
        except Exception:
            pass
    return _rule_type, _rule_conf, ["rule:best_practice:default"]

def _classify_by_embedding_prototype(root, summary, body="", tags=None):
    """嵌入原型分类器：计算各 type 的嵌入质心，返回最近 type。
    返回 (type, confidence, reason) 或 None（无足够样本时）。
    需要 ≥3 条已分类记忆才生效（防止小库噪声）。"""
    try:
        import numpy as _np
    except Exception:
        return None

        # 加载/刷新质心缓存
    db_path = _db_path(root)
    try:
        mtime = os.path.getmtime(db_path) if os.path.exists(db_path) else 0
    except Exception:
        mtime = 0
    cache_key = (root, mtime)

    if cache_key not in _EMB_PROTOTYPE_CACHE:
        try:
            store = _emb_store_load_all(root)
            data = load_index(root)
            type_vecs = {}  # type → list of vec
            for e in data.get("entries", []):
                if not isinstance(e, dict) or e.get("status") != "active":
                    continue
                mid = e.get("id")
                if mid not in store:
                    continue
                t = _entry_type(e) or e.get("category", "")
                t = _normalize_type(t)
                if t not in TYPE_CANON:
                    continue
                type_vecs.setdefault(t, []).append(store[mid][0])

            centroids = {}
            for t, vecs in type_vecs.items():
                if len(vecs) >= 3:  # 每 type 至少 3 条才建质心
                    centroids[t] = _np.mean(vecs, axis=0)
            _EMB_PROTOTYPE_CACHE[cache_key] = centroids
        except Exception:
            _EMB_PROTOTYPE_CACHE[cache_key] = {}

    centroids = _EMB_PROTOTYPE_CACHE.get(cache_key, {})
    if not centroids:
        return None

        # 嵌入新文本
    try:
        text = " ".join([summary or "", body or "", " ".join(tags or [])])
        q_vec = _emb.embed(text)
        q_arr = _np.array(q_vec, dtype=_np.float32)
        qn = float(_np.linalg.norm(q_arr)) or 1e-9
    except Exception:
        return None

        # 找最近质心
    best_type, best_sim = None, -1.0
    for t, centroid in centroids.items():
        cn = float(_np.linalg.norm(centroid)) or 1e-9
        sim = float(_np.dot(q_arr, centroid) / (qn * cn))
        if sim > best_sim:
            best_sim = sim
            best_type = t

    if best_type is None or best_sim < 0.3:
        return None  # 相似度太低，不做补判

        # 将余弦相似度映射到 0.5-0.7 的置信区间（不高于规则高置信 0.7）
    conf = min(0.7, 0.5 + best_sim * 0.2)
    return best_type, round(conf, 4), "cos=%.3f" % best_sim

    # scope 驱动「更深子记忆」策略：universal 永不自动归档；project 过期可归档；ephemeral 用过即归档

def _classify_scope(category, tags=None, body="", summary=""):
    """规则底噪分类器（零依赖）：输出 universal/project/ephemeral。
    现委托 classifier.base_scope 起），保持与旧行为一致；无学习模型时即纯规则。"""
    return _clf.base_scope(category, tags, body, summary)

class CorruptIndexError(Exception):
    """index.json 不是合法 JSON / 结构异常时抛出，便于调用方优雅降级。"""

class ConflictError(Exception):
    """Windows 大小写不敏感下，仅大小写不同的文件名会互相覆盖，拒绝静默写入。"""

class MemoryWriteGateError(Exception):
    """写入门禁：即将被覆盖的旧内容**没能留下版本快照**，故拒绝本次覆盖（fail-closed）。

    来源原则（恒忆 commit_task 的同名门禁）：快照 → 覆盖 → 记账，任一步失败即中止，
    绝不出现「没快照就覆盖」的路径。keeper 4.9.3 已把快照收口进写入真源，但快照发生在
    写完之后且异常被吞 —— 一旦快照失败（磁盘满/权限/加密错），旧内容已被覆盖、永久丢失，
    用户只看到一行 stderr 警告。4.9.5 起把顺序倒过来：先确认旧内容有快照，才允许覆盖。

    逃生通道：env KEEPER_WRITE_GATE=0 或 store/config.json 的 keeper.write_gate=false。
    """

class MemoryConflictError(Exception):
    """乐观并发守卫：同一记忆在「读取」与「写回」之间被另一个进程/窗口改动过，
    拒绝静默覆盖（否则两个窗口的修改会互相吞掉）。调用方应重读最新内容再合并写回。"""

    # ── 跨进程写锁（best-effort）：串行化 deposit/rebuild 等对 index.json 的批量写，
    # 避免多窗口同时 append 时一方索引被另一方原子替换而丢失。获取失败不阻塞——
    # 此时仅靠「原子替换 + mtime 乐观守卫」兜底，不会因锁异常而崩溃。 ──
_PROC_LOCK = threading.Lock()
# P4 修复：进程内全局状态锁，保护 _SCHEMA_INITIALIZED 等可变全局
_STATE_LOCK = threading.RLock()  # RLock: _db_conn holds this across _index_db_ensure -> _migrate_index_multiaxis -> _db_conn re-entry (P0 deadlock fix, found in test audit)
# Bug-1/Bug-4 修复：per-root 线程写锁，保护 deposit 的 gen_id→write→save_index 临界区。
# _store_lock 是跨进程文件锁（仅 CLI 层调用），但 deposit 直接被 Python 调用时
# 无保护——多线程同时 gen_id（scan-then-create 非原子）+ load/save_index（read-modify-write
# 非原子）导致 ID 冲突、丢数据、索引不一致。用 per-root RLock 允许同线程可重入
# （deposit 内部可能间接调用其他写操作），不同线程串行化。
_DEPOSIT_LOCKS = {}
_DEPOSIT_LOCKS_GUARD = threading.Lock()

_DEPOSIT_LOCKS_MAX = 64          # 复审修复（不妥-5）：上限，防止字典无限增长
_DEPOSIT_LOCKS_LAST_CLEANUP = 0  # 上次清理的 time.time()，每 300s 清一次

def _cleanup_deposit_locks():
    """复审修复（不妥-5）：定期清理 _DEPOSIT_LOCKS 中未被持有的锁。

    问题：每个不同 root 路径都会在字典里留一个 RLock 条目，长期运行
    （如 daemon 模式多租户）会导致字典无限增长。解决方案：
    - 每 300s 执行一次清理
    - 遍历字典，删除当前未被任何线程持有的锁
    - 保留 _DEPOSIT_LOCKS_MAX 条以内的活跃锁
    """
    import time
    now = time.time()
    global _DEPOSIT_LOCKS_LAST_CLEANUP
    if now - _DEPOSIT_LOCKS_LAST_CLEANUP < 300:
        return
    _DEPOSIT_LOCKS_LAST_CLEANUP = now
    to_remove = []
    for key, lk in _DEPOSIT_LOCKS.items():
        # 当前线程持有的锁不删（RLock._is_owned 返回 True 表示当前线程持有）
        if hasattr(lk, '_is_owned') and lk._is_owned():
            continue
            # 能 acquire(blocking=False) 说明无其他线程持有 → 可安全删除
        if lk.acquire(blocking=False):
            lk.release()
            to_remove.append(key)
            # 不能 acquire 说明其他线程正持有 → 保留
    for key in to_remove:
        del _DEPOSIT_LOCKS[key]

def _get_deposit_lock(root):
    """获取 per-root 的可重入线程锁（RLock），不存在则创建。"""
    key = os.path.abspath(root or _default_root())
    with _DEPOSIT_LOCKS_GUARD:
        # 复审修复（不妥-5）：定期清理，防止字典无限增长
        if len(_DEPOSIT_LOCKS) > _DEPOSIT_LOCKS_MAX:
            _cleanup_deposit_locks()
        lk = _DEPOSIT_LOCKS.get(key)
        if lk is None:
            lk = threading.RLock()
            _DEPOSIT_LOCKS[key] = lk
        return lk

_PROCESS_LOCKS = {}          # root_abs -> {"f": 文件句柄, "count": 嵌套计数}
_PROCESS_LOCKS_GUARD = threading.Lock()

# F10：跨进程锁 fail-open 计数 + 可选严格模式（KEEPER_LOCK_FAIL_CLOSED=1 时拿不到锁直接抛错）
_LOCK_FAIL_OPEN_COUNT = 0

def _open_lock_file(root):
    """创建/打开 store/.write.lock 并加排他锁，返回文件句柄。失败返回 None。

    4.5.58 修复（并发丢失根因）：原用 msvcrt LK_LOCK（最多重试 10s 即抛 OSError），
    而 _capture_dedup 在锁内首次调用 embedding 会懒加载模型 30s+ —— 持锁超过 10s 时
    其他进程抛错 → _get_process_lock 返回 None → fail-open 无锁裸奔 → save_index 的
    DELETE+全量重插 lost update（实测 4 进程 60 条 index 只剩 44）。改为 LK_NBLCK
    非阻塞循环重试 + 5 分钟总超时（覆盖 embedding 冷加载），失败仍告警而非静默。
    """
    lf = None
    try:
        if root is None:
            root = _default_root()
        lock_dir = os.path.join(os.path.abspath(root), "store")
        os.makedirs(lock_dir, exist_ok=True)
        lf = os.path.join(lock_dir, ".write.lock")
        f = open(lf, "a+b")
        if os.name == "nt":
            import msvcrt
            import time as _t
            if f.seek(0, os.SEEK_END) == 0:  # 字节锁要求文件至少 1 字节
                f.write(b"\x00")
                f.flush()
            f.seek(0)
            _deadline = _t.time() + 300.0  # 5min 总超时（embedding 冷加载最坏 2min）
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)  # 非阻塞尝试
                    break
                except OSError:
                    if _t.time() > _deadline:
                        raise
                    _t.sleep(1.0)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return f
    except Exception as _e:
        import sys as _sys
        global _LOCK_FAIL_OPEN_COUNT
        _LOCK_FAIL_OPEN_COUNT += 1
        _sys.stderr.write("[keeper] 警告(%d): 获取跨进程写锁失败 %s（并发写可能丢 index 条目）: %s\n"
                          % (_LOCK_FAIL_OPEN_COUNT, lf, _e))
        _log_struct("lock_fail_open", count=_LOCK_FAIL_OPEN_COUNT, lock=str(lf), err=str(_e))
        if os.environ.get("KEEPER_LOCK_FAIL_CLOSED") == "1":
            raise RuntimeError("跨进程写锁获取失败（KEEPER_LOCK_FAIL_CLOSED=1）: %s" % _e)
        return None

def _log_struct(event, **fields):
    """F20：结构化事件日志（单行 JSON 到 stderr），便于排障与采集。
    自身异常绝不外抛（日志不能让主流程崩）。"""
    try:
        import sys as _ls
        import time as _lt
        rec = {"ts": _lt.time(), "event": event}
        rec.update(fields)
        _ls.stderr.write("[keeper-json] " + json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

def _unlock_lock_file(f):
    """释放文件锁并关闭句柄。"""
    if f is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        f.close()
    except Exception:
        pass

def _get_process_lock(root):
    """获取 per-root 的**跨进程**文件锁 token（可重入，计数复用）。

    4.5.56 新增：memory_ops 以独立 CLI 进程运行（daemon 常驻 + WorkBuddy
    自动化 + 手动 CLI 可并发写同一库），此前只有 threading.RLock（进程内），
    load_index→修改→save_index 的 read-modify-write 竞态跨进程无保护——
    实测两进程各 deposit 30 条，index 仅剩 7 条（丢 53 条）。

    本进程嵌套调用（如 reflect → _sync_index）不重复加锁，只增计数，
    避免 Windows msvcrt 字节锁自锁死锁；最外层释放时真正解锁。
    Windows 用 msvcrt.locking 字节锁；POSIX 用 fcntl.flock 排他锁。
    锁不可用（只读/沙箱）返回 None → 降级为仅进程内锁（fail-open）。
    必须与 _release_process_lock 成对使用。
    """
    root = root or _default_root()  # 修复：root=None 时锁定默认库，否则 _open_lock_file(None) 崩溃→跨进程锁失效→并发写丢条目
    key = os.path.abspath(root)
    with _PROCESS_LOCKS_GUARD:
        ent = _PROCESS_LOCKS.get(key)
        if ent is not None:
            ent["count"] += 1
            return key  # 复用：句柄已在全局，防嵌套死锁
    f = _open_lock_file(root)
    if f is None:
        return None
    with _PROCESS_LOCKS_GUARD:
        _PROCESS_LOCKS[key] = {"f": f, "count": 1}
    return key

def _release_process_lock(token, root):
    """释放跨进程文件锁（_get_process_lock 的成对释放，计数归零才真解锁）。"""
    if token is None:
        return
    root = root or _default_root()  # 与 _get_process_lock 保持一致：None→默认库，否则释放的是错误 key 导致锁泄漏
    key = os.path.abspath(root)
    with _PROCESS_LOCKS_GUARD:
        ent = _PROCESS_LOCKS.get(key)
        if ent is None:
            return
        ent["count"] -= 1
        if ent["count"] > 0:
            return  # 外层仍持有，不真正解锁
        del _PROCESS_LOCKS[key]
    _unlock_lock_file(ent["f"])

def _with_deposit_lock(func):
    """装饰器：为索引修改函数自动加「线程锁 + 跨进程文件锁」。

    4.5.56：线程锁仅防同进程多线程；跨进程并发（daemon/CLI/自动化）由
    store/.write.lock 文件锁串行化，消除 read-modify-write 丢条目竞态。
    要求函数第一个位置参数为 root。
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        root = args[0] if args else kwargs.get("root")
        # 5.0.0：旧加密库 fail-closed 守卫置为**写路径的统一收口点**（在拿任何锁之前）。
        # 为什么必须放在这里、而不能只靠 _save_mem/_write_mem：G2 副作用实跑实测发现
        # `delete` 会先 `os.remove(fpath)` 再做后续整理，于是守卫只在 `_all_mems` 处触发 →
        # **被拒绝的 delete 已经把记忆删掉了**（fail-closed 变成了「先破坏再报错」）。
        # 本装饰器覆盖全部 18 个状态变更入口（含 delete/overwrite/archive/unarchive/
        # rollback/link/promote/reclassify/rebuild/cluster…），确保任何 mutation 之前就拒绝；
        # 同时顺带避免「被拒命令仍写下 memories/.write_lock」这类无谓副作用。
        assert_not_legacy_encrypted(root, op="写入本库")
        with _get_deposit_lock(root):
            plock = _get_process_lock(root)
            # 🔴#10 修复：跨进程写锁获取失败（plock is None）时默认 fail-closed，
            # 拒绝写盘以避免并发写静默损坏 index（P0 数据完整性）。
            # 仅当显式设置 KEEPER_LOCK_FAIL_OPEN=1（只读/沙箱等无法加锁环境）
            # 才降级放行。正常单进程/短暂竞争下锁会立即获取，不会触发此分支。
            if plock is None and os.environ.get("KEEPER_LOCK_FAIL_OPEN") != "1":
                raise RuntimeError(
                    "跨进程写锁获取失败，拒绝写盘以避免并发损坏 index（P0 数据完整性）。"
                    "若确属只读/无法加锁环境，请设置 KEEPER_LOCK_FAIL_OPEN=1 显式降级。"
                )
            try:
                return func(*args, **kwargs)
            finally:
                _release_process_lock(plock, root)
    return wrapper

@contextlib.contextmanager
def _store_lock(root):
    """跨进程写锁。获取失败（Windows 8s 超时 / POSIX flock 冲突）时**显式抛错**，
    绝不退化为无保护写盘——否则并发写会静默损坏 index（P0 数据完整性风险）。
    """
    lock_path = os.path.join(mem_dir(root), ".write_lock")
    os.makedirs(mem_dir(root), exist_ok=True)
    f = None
    acquired = False
    try:
        if _msvcrt is not None:
            f = open(lock_path, "a+")
            deadline = time.time() + 8.0
            while time.time() < deadline:
                try:
                    _msvcrt.locking(f.fileno(), _msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.05)
            if not acquired:
                raise RuntimeError(
                    "store lock timeout: 并发写竞争，另一进程持有 %s 的写锁超过 8s" % root
                )
        elif _fcntl is not None:
            f = open(lock_path, "w")
            try:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                acquired = True
            except OSError:
                raise RuntimeError(
                    "store lock timeout: 并发写竞争，无法获取 %s 的写锁" % root
                )
        with _PROC_LOCK:
            yield
    finally:
        if f is not None:
            try:
                if acquired and _msvcrt is not None:
                    _msvcrt.locking(f.fileno(), _msvcrt.LK_UNLCK, 1)
                elif acquired and _fcntl is not None:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                f.close()
            except OSError:
                pass

def _warn_destructive(op, mid, fpath, recover):
    """危险操作前的可操作提示（写 stderr，不污染 stdout 的 JSON）。
    给出：作用对象、具体文件、影响性质、如何恢复、如何预览/确认。"""
    sys.stderr.write(
        "\n[⚠ 危险操作预览] %s 将作用于记忆 %s\n"
        "  文件: %s\n"
        "  性质: 这是真正的磁盘文件操作（非逻辑标记），执行后 JSON 会被改写/移除。\n"
        "  恢复: %s\n"
        "  提示: 想先看看会动哪些文件，加 --dry-run；确认执行可加 --yes 关闭本提示。\n\n"
        % (op, mid, fpath, recover)
    )

def today() -> str:
    return datetime.date.today().isoformat()

def mem_dir(root: str) -> str:
    return os.path.join(root, "memories")

def archive_dir(root: str) -> str:
    """「更深子记忆」目录：被归档（非删除）的记忆物理存放于此。"""
    return os.path.join(root, "memories", "archive")

def _resolve_path(root: str, mid: str):
    """按 id 在 memories/ 与 memories/archive/ 两处查找真实文件（大小写不敏感）。"""
    if not _is_safe_mid(mid):
        return None  # 穿越型 id 一律视为「不存在」，保持 None 契约不惊扰上层
    cache_key = (root, mid)
    cached = _RESOLVE_PATH_CACHE.get(cache_key, _NOT_FOUND)
    if cached is not _NOT_FOUND:
        return cached if cached is not None else None  # 命中：正缓存返回路径，负缓存返回 None
    target = mid + ".json"
    target_low = target.lower()
    result = None
    for d in (mem_dir(root), archive_dir(root)):
        p = os.path.join(d, target)
        if os.path.exists(p):
            result = p
            break
        try:
            for fn in os.listdir(d):
                if fn.lower() == target_low:
                    result = os.path.join(d, fn)
                    break
            if result:
                break
        except FileNotFoundError:
            pass
    _RESOLVE_PATH_CACHE[cache_key] = result  # 负缓存也写入（用 None 区别于 _NOT_FOUND 哨兵）
    return result

def _actual_file(memdir: str, mid: str):
    """返回 mid 对应的真实文件路径（大小写不敏感回退）。"""
    target = mid + ".json"
    target_low = target.lower()
    if os.path.exists(os.path.join(memdir, target)):
        return os.path.join(memdir, target)
    try:
        for fn in os.listdir(memdir):
            if fn.lower() == target_low:
                return os.path.join(memdir, fn)
    except FileNotFoundError:
        pass
    return None

def _case_clash(memdir: str, mid: str):
    """返回与 mid 仅大小写不同的已存在文件名（不含 mid 自身），无则 None。"""
    target = mid + ".json"
    target_low = target.lower()
    try:
        for fn in os.listdir(memdir):
            if fn.lower() == target_low and fn != target:
                return fn
    except FileNotFoundError:
        pass
    return None

    # F18 阶段2 批4：持久化层（load_index/save_index/_db_conn/迁移/连接池代理）已移至 memory_ops/_persistence.py。
    # 原 __init__.py L1618-L2022 整簇，零行为变化。重导出与依赖注入见下方『_persistence 加载块』（插在 _graph 加载块之前，所有外部依赖定义完成后统一注入，避免循环 import）。

def _db_upsert_entry(root, entry):
    conn = _db_conn(root)
    try:
        _db_upsert_entries(conn, [entry], root)
        conn.commit()
    finally:
        conn.close()

        # ── store/meta.json：跨进程持久化的运行配置（衰减 λ、置信度校准、上次 reflect）──
        # 进程级冷启动（每次 CLI 独立进程）使进程内缓存清零，故「跨调用要生效的配置」必须落盘。
def _meta_path(root):
    return os.path.join(root, "store", "meta.json")

def _load_meta(root):
    p = _meta_path(root)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("decay_lambda", 0.03)
            d.setdefault("decay_fitted", False)
            d.setdefault("n_decay_samples", 0)
            d.setdefault("last_reflect", None)
            d.setdefault("last_decay_check", None)  # v3.1.4 P0-2：懒衰减检查时间戳
            d.setdefault("calibration", {"n_lowered": 0, "n_raised": 0})
            return d
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return {"decay_lambda": 0.03, "decay_fitted": False, "n_decay_samples": 0,
            "last_reflect": None, "last_decay_check": None,
            "calibration": {"n_lowered": 0, "n_raised": 0}}

def _save_meta(root, meta):
    p = _meta_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

    # ── P1-5a 元记忆：召回信号权重（多信号 RRF）可审计 / 可微调 ──
    # 默认权重可在 config.json 的 "recall" 块覆盖。
    # 落盘进 store/meta.json 供 dashboard/report 展示，让「召回为什么这么排」可解释、可纠。
RRF_DEFAULTS = {
    "sem_emb": 0.6,      # 语义混合分中 embedding 余弦的权重
    "sem_tf": 0.3,       # 语义混合分中 TF-IDF 的权重
    "sem_syn": 0.2,      # 语义混合分中同义词命中的权重
    "rrf_k": 60,         # RRF 融合的 k（1/(k+rank)）
    "min_score": 0.06,   # 语义召回地板
    "rrf_weak": 0.03,    # RRF 弱门（跨多路弱信号一致即召回）
    "rrf_jac_min": 0.05, # 弱门附加要求：记忆与 query 的词重叠需达此值，否则纯靠时间/置信撑分的无关记忆不召回
    # 🔴 2026-09-15 消融实测改默认 0.5 → 0.0（原 4.7.9 为修「RRF 压平语义信号导致换说法
    #   搜不到」而注入余弦 magnitude，副作用过大）。依据：原始余弦 emb_c 与 RRF 分**差一个
    #   数量级**（cos 0.3~0.5 vs RRF 0.006~0.033），β=0.5 时 (1-β)·rrf + β·cos ≈ β·cos，
    #   多信号 RRF 实际权重 <5% → 退化为「纯余弦排序」。真库实测（199 条 / 7 组查询）：
    #   β=0.5 时跨域查询「git-bash 路径被原生Python解析错位」top3 全部是与查询无关的投资域
    #   长文本（词法零重叠、仅语义余弦虚高 = hubness 假阳性）；β=0.0 后 top3 全部变为强相关
    #   技术记忆，而域内查询（84日均线/加密/IMA/小说）排序基本不退化。
    #   需要恢复旧「换说法」行为时，用 config.json 的 recall 块覆盖回 0.5 即可（无需改码）。
    "sem_magnitude_blend": 0.0,
    "sem_exempt_lowconf_cos": 0.5, # B（4.7.9）：原始余弦≥此值的 rule 分类记忆豁免 low_conf 降权（避免最相关项被砍半）
    "semantic_gate": 0.42,  # P1-3：离题绝对语义门控——神经/online 后端下，原始语义余弦 < 此值且无强信号命中的条目剔除（避免离题记忆注入）；词法后端自动关闭（=0 效果）
    "frequency_tracking": True,  # B5 (4.5.45)：recall 时统计召回频次到 store/recall_counts.json（轻量、不写记忆文件），供周期性 importance 加权
    # ── 5.0 修正：以下 3 键原为「死读取」──
    # 🔴 根因：`_load_recall_config` 的覆盖循环是 `for kk in cfg:`（只遍历本字典的键）
    #   → **任何不在本字典里的配置项，在 config.json 里写多少遍都不会生效**。
    #   而代码早就在读它们（下面标了行号），文档甚至明确写了怎么配（见 RECALL_CACHE_TTL_DEFAULT
    #   处注释）。属「文档/规则层承诺 ≠ 实现层可达」根因族（本会话第六次命中）。
    #   修法：把这三个键显式登记进本字典，覆盖循环自然就能生效（无需改循环逻辑）。
    "cache_ttl_seconds": 60,     # 召回缓存 TTL（秒）；_api.py 读，原注释已承诺可配但不可达
    "low_conf_downweight": 0.5,  # 低置信记忆的降权系数；_api.py:437 读，原不可配
    "ann_auto_large": False,     # 库规模 >256 时是否自动启用 ANN；_api.py:311 读，原不可配
    # ── 5.0/B1 cross-encoder 重排（默认关闭）──
    # ⚠️ 实测成本（2026-09-16，本机 CPU，**两轮实测，以第二轮为准**）：
    #   ① 体积：BAAI/bge-reranker-base = 1.04GB（嵌入模型 bge-small-zh 仅 90MB，即 11 倍）。
    #   ② 延迟：**成本主项是「候选文档总字符数」，约 1.2 ms/字符**（不是条数）。
    #      用真实记忆文本（1000+ 字正文）实测：top-20 × 1200 字截断 = **12~15 秒/次**
    #      （p50 11.65s / p95 14.60s，76 条真实 query 消融实测）。
    #      🔴 早期笔记里的「562ms / 745ms」是**用 30 字合成短文本**测的，低估约 20 倍——
    #      凡引用该数字处均已更正（`_rerank.py` 头注释 / CHANGELOG / FEATURES.md）。
    #   ③ 故**默认关闭**是硬结论，不是保守：11.6s/次 ≈ recall 自身（0.3s）的 38 倍。
    #      想开又嫌慢的取舍见 `rerank_top` / `rerank_doc_chars` 两项（成本 ≈ 1.2ms × top × 截断）。
    #   可选项（fastembed 0.8.0 支持列表内）：BAAI/bge-reranker-base（中文可用）/
    #   jinaai/jina-reranker-v2-base-multilingual（多语言）/ Xenova/ms-marco-MiniLM-L-6-v2（英文，80MB 快）。
    "rerank_enabled": False,           # 总开关（模型 1.04GB 需用户知情下载，故默认仍关）
    "rerank_model": "BAAI/bge-reranker-base",
    # 🔴 默认值 = 76 条真实 query 网格实测出的「便宜档」（2026-09-16，报告第十三节）：
    #                         hit@1    hit@3    MRR    p50 延迟
    #     不开重排              0.566    0.789   0.686    0.30s
    #     top=5  × 200 字   →   0.803    0.842   0.829    1.83s   ← 本默认（拿到 90% 质量增益）
    #     top=5  × 1200 字  →   0.816    0.855   0.837    4.08s
    #     top=20 × 200 字   →   0.816    0.855   0.838    3.95s
    #     top=20 × 1200 字  →   0.829    0.868   0.849   11.65s（约 6.4 倍成本换最后 2.6 个点）
    #   原默认 top=20/1200 字 = 12~15s/次，作为「开箱即用」的默认值不可接受（≈recall 自身的 38 倍），
    #   故默认改为便宜档；要满配自己调大这两项即可（成本 ≈ 1.1ms × top × 截断）。
    "rerank_top": 5,                   # 只对 RRF top-N 重排（成本线性于 N）
    "rerank_weight": 0.6,              # 重排分在融合中的权重（0=关闭效果，1=完全按重排排序）
    # 候选文档截断字符数。**这是成本主项**（≈1.1ms/字符），原为硬编码 1200 且不可配
    # ⇒ 用户即使想「用便宜档」也改不了。属「文档/规则层承诺 ≠ 实现层可达」根因族
    # （本会话第七次命中：代码里有成本参数，配置面却拿不到）。
    "rerank_doc_chars": 200,
}

def _load_recall_config(root):
    """读取召回策略配置：默认 RRF_DEFAULTS，config.json 的 recall 块可逐项覆盖。"""
    cfg = dict(RRF_DEFAULTS)
    try:
        for p in _keeper_config_paths(root):   # store/config.json 优先，root/config.json 兜底
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                c = json.load(f)
            rc = c.get("recall", {})
            kp = c.get("keeper", {})
            if not isinstance(rc, dict):
                rc = {}
            if not isinstance(kp, dict):
                kp = {}
            # 2026-09-15 审计补：兼容「召回参数误写进 keeper 块」的历史配置。
            # 实测本机 store/config.json 把 semantic_gate 写在 keeper 块 → **完全未生效**
            # （用户以为关了语义门控，实际仍走默认 0.42）。recall 块同名键优先，
            # keeper 块仅作缺失兜底，老配置行为不变。
            for kk in cfg:
                if kk in rc:
                    cfg[kk] = rc[kk]
                elif kk in kp:
                    cfg[kk] = kp[kk]
    except Exception as e:
        # P2 修复：config.json 损坏时静默用默认值——用户不知道自定义配置被忽略了
        import sys as _sys
        _sys.stderr.write("[⚠ config] 读取 config.json 失败，使用默认召回配置: %s\n" % e)
    return cfg

    # ── 配置收口：keeper 块（单一 config.json 入口，env 优先）──
    # 把分散在 memory_ops / embed / mem_bridge 的 KEEPER_* / AI_MEM_EMBED_* / AI_MEM_ANN_*
    # 等运行时开关统一收口到 store/config.json 的 "keeper" 块；环境变量仍可逐条覆盖（优先级最高）。
    # 安全/基础类变量【不】收口（仍只走 env，理由见下）：
    # · AI_MEMORY_STORE —— 库根定位，读 config 前就需先知道 root，循环依赖；
    # · KEEPER_LLM_KEY / AI_MEM_EMBED_ONLINE_KEY_ENV
    # —— 密钥/密钥 env 名，禁止落明文文件；
    # · AI_MEM_EMBED_MODEL —— 默认值随后端上下文（本地/online）变化，保留 env 优先。
KEEPER_DEFAULTS = {
# ：默认 fastembed（轻量本地 ONNX，CPU 推理，非“吃配置很多”的本地 LLM）。
# 首次用到中文语义时 embed.py 惰性自动安装 fastembed + 下载模型（一次，HF 不可达自动切国内镜像），
# 之后完全离线；无网络/无 pip 时优雅降级词法级，绝不卡死。满足“语义模型开箱即用、零配置”。
    "embed_backend": "fastembed",
    "embed_online_url": "",
    "inject_enabled": False,
    "inject_daily_cap": 6,
    "inject_dedup": True,
    "inject_dedup_days": 14,
    "feedback_session_cap": 3,
    "rehearsal_alpha": 0.05,
    "ann_min_memories": 50,
    "ann_auto_large": False,  # 大库(>256)opt-in 高召回 ANN：默认关，保持线性全量召回（不静默 tradeoff）
    # 写入门禁：覆盖前必须确认旧内容已留版本快照，留不下就中止写入（fail-closed）。
    # 默认**开**——门禁拦不住的代价是"少写一次"，不设门禁的代价是"旧内容永久丢失"，二者不对称。
    # 逃生通道：env KEEPER_WRITE_GATE=0（如只读快照库、CI 沙箱等确需绕过时）。
    "write_gate": True,
# ：开箱即用 · 对话内自动沉淀（converse）默认开启、阈值 20 轮。
# auto_capture=True → agent 每轮自动调 converse（无弹窗，走“自调”而非会弹窗的 UserPromptSubmit 钩子）；
# converse_threshold=20 → 每 20 轮自动跑一次 harvest+self-learn+reflect 整理闭环。
    "auto_capture": True,
    "converse_threshold": 20,
}
# env 名 → keeper 块键 的映射（env 优先级最高，可逐条覆盖 config.json）。
_KEEPER_ENV_MAP = {
    "embed_backend": "AI_MEM_EMBED_BACKEND",
    "embed_online_url": "AI_MEM_EMBED_ONLINE_URL",
    "inject_enabled": "KEEPER_INJECT_ENABLED",
    "inject_daily_cap": "KEEPER_INJECT_DAILY_CAP",
    "inject_dedup": "KEEPER_INJECT_DEDUP",
    "inject_dedup_days": "KEEPER_INJECT_DEDUP_DAYS",
    "feedback_session_cap": "KEEPER_FEEDBACK_SESSION_CAP",
    "rehearsal_alpha": "KEEPER_REHEARSAL_ALPHA",
    "ann_min_memories": "AI_MEM_ANN_MIN_MEMORIES",
    "ann_auto_large": "AI_MEM_ANN_AUTO_LARGE",
    "auto_capture": "KEEPER_AUTO_CAPTURE",
    "converse_threshold": "KEEPER_CONVERSE_THRESHOLD",
    "write_gate": "KEEPER_WRITE_GATE",
}
_KEEPER_CFG_CACHE = {}

def _keeper_coerce(key, val):
    """把 env 字符串按 KEEPER_DEFAULTS 的类型强制转换；转换失败抛异常（调用方回退 base）。"""
    default_val = KEEPER_DEFAULTS.get(key)
    if isinstance(default_val, bool):
        return val.strip().lower() in ("1", "true", "yes", "on", "y", "启用")
    if isinstance(default_val, (int, float)):
        return type(default_val)(val)
    return val

def _keeper_config_paths(root):
    """keeper 配置文件的候选路径，**按优先级从低到高**返回（后者覆盖前者）。

    历史坑（4.9.5 修）：`_load_keeper_config` 一直读 `<root>/config.json`，而
    `keeper_setup.py` 写的是 `<root>/store/config.json`、钩子 `recall_mode()` 读的也是
    `store/config.json` —— 同一个 keeper 块有**两个事实源**，文档说的 store 与代码读的
    root 对不上，导致 `keeper_setup --set-mode ...` 等设置被 memory_ops 静默忽略。
    现统一为：store/config.json（文档/工具标准位）优先，root/config.json 兜底兼容旧库。
    """
    return [os.path.join(root, "config.json"),
            os.path.join(root, "store", "config.json")]

def _load_keeper_config(root=None, force=False):
    """读取 keeper 配置：KEEPER_DEFAULTS → config.json 的 keeper 块 → 环境变量（最高优先）。

    配置文件同时认 `<root>/store/config.json`（标准位，优先）与 `<root>/config.json`
    （兼容旧库，兜底）；root 缺省用默认库根。带 per-root 缓存；force=True 强制重读
    （测试用）。返回 dict，键同 KEEPER_DEFAULTS。"""
    rk = os.path.abspath(root or _default_root())
    if not force and rk in _KEEPER_CFG_CACHE:
        base = _KEEPER_CFG_CACHE[rk]
    else:
        base = dict(KEEPER_DEFAULTS)
        try:
            for p in _keeper_config_paths(rk):
                if not os.path.exists(p):
                    continue
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
                kc = c.get("keeper", {}) or {}
                if isinstance(kc, dict):
                    for kk in KEEPER_DEFAULTS:
                        if kk in kc and kc[kk] is not None:
                            base[kk] = kc[kk]
        except Exception as e:
            import sys as _sys
            _sys.stderr.write("[⚠ config] 读取 keeper 配置失败，使用默认: %s\n" % e)
        _KEEPER_CFG_CACHE[rk] = base
        # env 实时优先；无效 env 值忽略并保留 base（config/default），不崩溃。
    out = dict(base)
    for kk, ev in _KEEPER_ENV_MAP.items():
        v = os.environ.get(ev)
        if v is not None:
            try:
                out[kk] = _keeper_coerce(kk, v)
            except (ValueError, TypeError):
                pass
    return out

def get_recall_strategy(root):
    """元记忆对外接口：返回当前召回信号权重 + 哪些项被 config 覆盖（供 dashboard/report 展示）。

    5.0 修正：`_overridden` 原先**只读 `root/config.json`**，而 `_load_recall_config` 是
    `store/config.json` 优先（真库确实把 `semantic_gate: 0.0` 写在 store/config.json）
    ⇒ **展示层看不到该项被覆盖**（报告与实际生效不一致；用户会以为自己在用默认值）。
    现改为遍历 `_keeper_config_paths` 的两个路径、并按 `recall`→`keeper` 两块的合并口径
    统计，与 `_load_recall_config` 完全对齐（含「参数误写进 keeper 块」的历史配置）。
    """
    cfg = _load_recall_config(root)
    overridden = {}
    try:
        merged = {}
        for p in _keeper_config_paths(root):   # 低优先 → 高优先，后者覆盖前者
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                c = json.load(f)
            for blk in ("recall", "keeper"):
                d = c.get(blk) or {}
                if isinstance(d, dict):
                    merged.update(d)
        for kk in RRF_DEFAULTS:
            if kk in merged and merged[kk] != RRF_DEFAULTS[kk]:
                overridden[kk] = merged[kk]
    except Exception:
        pass
    cfg["_overridden"] = overridden
    return cfg


# 改进 P0-4：ANN 增量更新阈值——变更量低于此比例时增量更新而非全量重建
ANN_INCREMENTAL_THRESHOLD = 0.15  # 15% 以下变更走增量，超过则全量重建

# ── 批量导入缓冲（A+D 性能优化，详见 selftest 性能段）──
# defer_index=True 的 deposit 进入批量模式：复用内存 index（不再每条 load_index）、
# 延迟 save_index 到 flush_memory_index 一次落盘（方案 A）；反向边回写记入进程内
# _PENDING_REVERSE，flush 时每个旧文件只 open 一次（方案 D）。单条 deposit
# （defer_index=False）行为完全不变，仍每条 save_index 保证索引立即可见（原子性）。
_BATCH_ROOT = None
_BATCH_DATA = None
_PENDING_REVERSE = {}  # oid -> set(mids)
_BULK_SEQ = {}  # root(abspath) -> 批量导入的当日序号游标（增量生成 id，避免 O(n²)）
_PENDING_EMBEDS = {}  # root(abspath) -> [(mid, summary, body, tags), ...] 批量 deposit 暂存，flush 时单连接单事务落盘
_RESOLVE_PATH_CACHE = {}  # (root, mid) -> path|_NOT_FOUND：recall 1000+ 条主循环去重，避负 listdir 风暴；写操作前 invalidate 即可
_NOT_FOUND = object()  # 哨兵值：区分"未缓存"vs"已缓存为不存在"（修 D3：原 None 无法区分→负缓存永不命中）
_MTIME_CACHE = {}  # (root, mid) -> (mt, ts)：短期 mtime 缓存，TTL 默认 50ms（recall 千条库省 1000 次 getmtime）
_MTIME_TTL = 0.05  # 50ms；写入路径极少，正确性由写操作清缓存保证

# ── 进程内「标签→记忆 id」倒排索引缓存（自动连边性能关键）──
# 旧实现：每次 deposit 都在 _auto_link_similar 里 load_index + 全量重建 by_tag，
# 千条库 = O(n²)（~100 万次迭代 + 1000 次 index 读）。改为进程内增量维护：
# 首次全量构建一次，之后每次 deposit 仅 O(1) upsert；archive/overwrite/delete/
# rebuild 等会改变索引结构/状态的写操作调用 _tag_index_reset 作废缓存，下次
# deposit 触发一次廉价全量重建。仅 deposit 热路径受益，其余读操作不受影响。
_TAG_INDEX = {}  # abspath(root) -> {"by_tag": {tag: [ids]}, "by_id": {id: entry}, "n": int}

def gen_id(root: str, data: dict, scan_dir=True) -> str:
    d = datetime.date.today().strftime("%Y%m%d")
    # 批量导入（defer_index=True）下 scan_dir=False：用进程内增量序号，避免每次 deposit
    # 重建「全量 taken 集合」(O(n)) 累积成 O(n²)（实测 1万条 bulk 因此慢到 371s）。
    if not scan_dir:
        key = os.path.abspath(root)
        seq = _BULK_SEQ.get(key, 0)
        if seq == 0:
            # 一次性播种：取 data 内 + 磁盘已有当日序号的最大值（含持久化高水位，防复用被删 id）
            seq_state = _seq_load(root)
            mx = int(seq_state.get(d) or 0)
            for e in (data.get("entries", []) or []):
                if isinstance(e, dict):
                    m = re.match(r"LRN-%s-(\d+)$" % d, e.get("id", ""))
                    if m:
                        mx = max(mx, int(m.group(1)))
            try:
                for fn in os.listdir(mem_dir(root)):
                    m = re.match(r"LRN-%s-(\d+)\.json$" % d, fn)
                    if m:
                        mx = max(mx, int(m.group(1)))
            except FileNotFoundError:
                pass
            seq = mx
        seq += 1
        _BULK_SEQ[key] = seq
        seq_state = _seq_load(root)
        seq_state[d] = max(int(seq_state.get(d) or 0), seq)  # 持久化当日高水位（删除不降序）
        _seq_save(root, seq_state)
        return "LRN-%s-%03d" % (d, seq)
    taken = {e.get("id") for e in data.get("entries", []) if isinstance(e, dict)}
    # 非批量：仍扫目录避免与已落盘文件冲突（单条场景 O(目录大小)，可接受）。
    # ⚠️ 必须同时扫 mem_dir + archive_dir：archive 后的 mid 仍在 archive/ 占位文件，
    # 若只扫 mem_dir，新 gen_id 会撞到 archive 区被 _resolve_path 拒（1500+300+deposit 复现）。
    scanned_max = 0
    for scan_dir_path in (mem_dir(root), archive_dir(root)):
        try:
            for fn in os.listdir(scan_dir_path):
                m = re.match(r"LRN-(\d{8})-(\d+)\.json$", fn)
                if m and m.group(1) == d:
                    taken.add("LRN-%s-%s" % (m.group(1), m.group(2)))
                    scanned_max = max(scanned_max, int(m.group(2)))
        except FileNotFoundError:
            pass
            # 删除记忆会释放当日序号槽位。若仅按「当前存在文件」取 max，下一次 deposit 会回退复用
            # 被删 id（如 LRN-001 删后又被新记忆占用）——既破坏 reclaim 两次运行冷却的候选身份
            # （旧 id 被复用→新记忆误判为「已报告」→首轮 apply 即被删，绕过冷却），也可能覆盖/撞车。
            # 因此把当日已用最大序号持久化进 store/seq.json（独立于 index 的高水位，因 load_index
            # 走 SQLite 权威源时会丢弃 data 上的附加字段），gen_id 只增不减（删除不参与降序号）。
    seq_state = _seq_load(root)
    stored_max = int(seq_state.get(d) or 0)
    seq = max(scanned_max, stored_max) + 1
    seq_state[d] = seq
    _seq_save(root, seq_state)
    return "LRN-%s-%03d" % (d, seq)

    # F18 阶段2 批5(部分)：内存文件 IO + 进程内缓存子系统（_load_mem/_save_mem/_MEM_CACHE/_cache_key/_mem_cache_put/_mem_cache_get/_all_mems）已移至 memory_ops/_core.py。
    # 原 __init__.py L3009-L3166 整段，零行为变化。外部依赖由 __init__.py 在加载末期注入（见下方 _core 加载块，位于 _graph 加载块之前保证 _graph 注入 _load_mem/_save_mem 时可解析）。

def _iter_all_mems(root):
    """流式逐条产出记忆（生成器），供 export / 大规模遍历对超大库（1万+ 文件）降低内存压力。
    与 _all_mems 内容等价，但不一次性全量入内存。"""
    # 5.0.0：旧加密库 fail-closed 守卫。本函数是**独立于 _all_mems 的第二条读路径**（自带
    # open/json.load），故必须各自设防 —— 只在 _all_mems 加门会让 export/keeper_sync 漏网。
    # 库级标志在生成器首次 next() 时检查一次；内容层逐条嗅探为零额外 IO（见 _legacy.py）。
    assert_not_legacy_encrypted(root, op="导出记忆库")
    for d in (mem_dir(root), archive_dir(root)):
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
            except (json.JSONDecodeError, UnicodeDecodeError):
                _quarantine_corrupt_file(fpath)
                continue
            if isinstance(mem, dict) and "id" in mem:
                if looks_like_legacy_ciphertext(mem):  # 零额外 IO：字段已在内存
                    assert_not_legacy_encrypted(root, op="导出记忆库", mem=mem)
                yield mem

                # F18 阶段2 批7：export_memories 已迁至 memory_ops/_api.py

def explain_memory(root, mid):
    """调试命令 explain：分解某条记忆的排序/召回 why 信号（importance / relevance /
    decay / 召回频次 / reason / 标签 / 元信息），便于审计「为何这样排序、为何被召回」。
    纯只读，零依赖。"""
    try:
        m, _path = _load_mem(root, mid)
    except (FileNotFoundError, OSError):
        return {"ok": False, "error": "not_found", "id": mid}
    if not m:
        return {"ok": False, "error": "not_found", "id": mid}
    rc = {}
    rp = os.path.join(root, "recall_counts.json")
    try:
        if os.path.exists(rp):
            rc = json.load(open(rp, encoding="utf-8")) or {}
    except Exception:
        rc = {}
    rcount = rc.get(mid, {}) if isinstance(rc.get(mid), dict) else {}
    return {
        "ok": True, "id": mid,
        "category": m.get("category", ""), "type": m.get("type", ""),
        "tier": m.get("tier", ""), "scope": m.get("scope", ""),
        "status": m.get("status", ""),
        "summary": (m.get("summary") or "")[:200],
        "tags": m.get("tags", []) or [],
        "importance": m.get("importance"),
        "relevance_score": m.get("relevance_score"),
        "decay": m.get("decay"),
        "created_at": m.get("created_at", ""),
        "accessed": m.get("accessed"),
        "accessed_count": rcount.get("count", 0),
        "last_recalled": rcount.get("last", ""),
        "reason": m.get("reason", ""),
        "recorded_by": m.get("recorded_by", ""),
    }

    # F18 阶段2 批7：stats 已迁至 memory_ops/_api.py

def vector_coverage(root):
    """F21：向量覆盖指标（已嵌入语义向量的条目数 / 总条目数）。
    只读且全程异常自吞：统计 index 条目数与 store/index.db 的 vectors 表行数。
    返回 {"embedded": int|None, "total": int, "coverage": float|None}。"""
    total = 0
    embedded = None
    try:
        idx = load_index(root)
        total = len(idx.get("entries", []))
    except Exception:
        pass
    try:
        conn = _db_conn(root)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM vectors")
            embedded = int(cur.fetchone()[0])
        finally:
            conn.close()
    except Exception:
        embedded = None
    cov = None
    if isinstance(embedded, int) and total:
        cov = round(embedded / total, 4)
    return {"embedded": embedded, "total": total, "coverage": cov}

@_with_deposit_lock
def _sync_index(root: str) -> None:
    """把 index entries 的**全部 recall 过滤字段**与磁盘文件对齐（reflect/taxonomy 等自动改动后调用）。

    recall 主路径只读索引镜像（SQLite data 列）做硬过滤，过滤字段共 9 个：
    status/tier/tag/category/scope/project/subdomain/scene/about_axis（见 _api.recall 562-597）。
    旧版只回灌 tier/status/scope/project 四个，导致 domain/subdomain/tags 等改动后索引陈旧、
    recall 的 --subdomain/--tag 静默错乱（taxonomy reclassify 即典型）；现补全全部过滤字段，
    使本函数成为真正的「文件→索引」单一对账点。"""
    data = load_index(root)
    mems = _all_mems(root)
    for e in data.get("entries", []):
        m = mems.get(e.get("id"))
        if not m:
            continue
        e["tier"] = m.get("tier", "working")
        e["status"] = m.get("status", "active")
        e["scope"] = m.get("scope", "universal")
        e["project"] = m.get("project", "")
        e["category"] = m.get("category", "")
        e["domain"] = m.get("domain")
        e["subdomain"] = m.get("subdomain")
        e["scene"] = m.get("scene")
        e["about_axis"] = m.get("about_axis")
        e["tags"] = m.get("tags", [])
    save_index(root, data)
    # 同步倒排索引（tag→id）：recall 的「纯标签、无 query」路径走 inverted 表（_inv_query），
    # 旧版 _sync_index 只更新 entries 表、不动 inverted → recall --tag 静默漏命中（假绿）。
    # 这里用自包含方式直接重建 inverted（避免跨模块依赖），与 _doctor 的重建逻辑一致。
    try:
        import sqlite3 as _sq
        _dbp = os.path.join(root, "store", "index.db")
        if os.path.exists(_dbp):
            _c = _sq.connect(_dbp)
            try:
                _c.execute("DELETE FROM inverted")
                _inv_rows = [(t, e.get("id")) for e in data.get("entries", [])
                             if isinstance(e, dict) for t in (e.get("tags") or []) if t]
                if _inv_rows:
                    _c.executemany("INSERT OR IGNORE INTO inverted(tag, id) VALUES (?, ?)", _inv_rows)
                _c.commit()
            finally:
                _c.close()
    except Exception as _e:
        # 2026-10-06：倒排索引重建失败不再静默。recall 的「纯标签、无 query」路径
        # 走 inverted 表（_inv_query），倒排写失败 → recall --tag 静默漏命中（假绿）。
        # 原 `except Exception: pass` 会把「标签召回失效」吞成静默；改为告警留痕，
        # 不阻断主流程（entries 表已通过 save_index 落盘，语义召回不受影响）。
        import sys as _sys
        _sys.stderr.write("[⚠ _sync_index] 倒排索引重建失败（recall --tag 可能漏命中，"
                          "建议跑 doctor --fix）：%s\n" % _e)

def _sync_index_one(root: str, mid: str, mem: dict) -> None:
    """增量同步**单条**记忆到索引（entries 行 + inverted 倒排）。

    根治 claim B 的双写漂移：_save_mem 每次写文件后调用本函数，使「写文件」即「同步索引」，
    调用方无需再手动 save_index/_sync_index（那是旧架构的脆弱点——任一调用点遗漏即静默漂移）。

    设计：
    - 增量：只重建并 upsert 该 id 的 entry（复用 _index_entry_from_mem，字段集与 rebuild 一致，
      含 auto_sourced/about_axis/scene/subdomain/attrs 等多轴过滤字段 + inverted 倒排），
      不重建全表，性能与 recall 触摸路径高频调用友好。
    - 索引同步：entry 由 _index_entry_from_mem 构造后直接 upsert（明文条目，与 save_index 一致）。
    - 幂等：INSERT OR REPLACE 单条，重复调用无副作用。
    - 安全：索引库不存在（首次 deposit 前）时静默跳过；删除(mem=None)时清该 id 行与倒排。
    - 与 _sync_index（全量对账）/rebuild（全量重建）共存：日常写入走增量，批量修正走全量。"""
    import os as _os
    import sqlite3 as _sq
    dbp = _os.path.join(root, "store", "index.db")
    if not _os.path.exists(dbp):
        return  # 首次 deposit 前索引库未建，deposit 流程会自行初始化，无需增量
    try:
        from ._persistence import _db_conn  # 走连接缓存（busy_timeout/WAL）
    except Exception:
        from memory_ops._persistence import _db_conn
    archived = (mem.get("status") == "archived") if mem else False
    fn = (mid or "") + ".json"
    if mem is None:
        # 删除场景：清 entries 行 + inverted
        conn = _db_conn(root)
        try:
            conn.execute("DELETE FROM entries WHERE id=?", (mid,))
            conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
            conn.commit()
        finally:
            conn.close()
        return
    entry = _index_entry_from_mem(mem, mid, fn, archived, mem.get("status", "active"))
    conn = _db_conn(root)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO entries"
            "(id,category,summary,body,tags,tier,status,scope,project,file,updated,data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry.get("id"), entry.get("category", ""), entry.get("summary", ""),
             entry.get("body", ""), json.dumps(entry.get("tags", []), ensure_ascii=False),
             entry.get("tier", "working"), entry.get("status", "active"),
             entry.get("scope", "universal"), entry.get("project", ""),
             entry.get("file", fn), today(), json.dumps(entry, ensure_ascii=False)))
        # 增量倒排：只清该 id 的旧 tag 行再插新的，不动其他条目
        tags = entry.get("tags") or []
        conn.execute("DELETE FROM inverted WHERE id=?", (mid,))
        if tags:
            conn.executemany("INSERT OR IGNORE INTO inverted(tag, id) VALUES (?, ?)",
                             [(t, mid) for t in tags])
        conn.commit()
    finally:
        conn.close()


def _sim(a: str, b: str) -> float:
    """极简 jaccard 相似度（按非中文/英文 token + 字符 bigram）。用于去重判定。"""
    def toks(s):
        s = (s or "").lower()
        ws = set(re.findall(r"[a-z0-9_]+", s))
        bg = set(s[i:i + 2] for i in range(len(s) - 1))
        return ws | bg
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def _similarity(a, b):
    """统一去重相似度（B2·修 H7）：优先 embedding 语义相似度，不可用时回退 jaccard。

    全库去重判定（capture / reflect / harvest WB 同步 / self_learn）统一走此函数，
    消除旧版「capture/reflect 用 emb 0.6、harvest 用 jaccard 0.5」的方法分裂——
    同一对文本在不同路径给出不同去重结论，正是 H7 根因。"""
    try:
        return float(_emb.semantic_similarity(a or "", b or ""))
    except Exception:
        return _sim(a, b)

def _rrf_fuse(signals, k=60):
    """Reciprocal Rank Fusion：多路信号各自降序排名，
    fused += 1/(k+rank)。不依赖重模型即可把多个弱信号融合成强排序，缓解『相似度≠相关性』。
    缺失某信号的候选按其信号长度+1 计最差排名（贡献≈0），不影响其他信号。"""
    fused = {}
    for sig in signals:
        if not sig:
            continue
        ranked = sorted(sig.keys(), key=lambda i: sig[i], reverse=True)
        for rank, mid in enumerate(ranked, start=1):
            fused[mid] = fused.get(mid, 0.0) + 1.0 / (k + rank)
    return fused

def _recency_score(m):
    """时间衰减（0..1）：accessed/created 越近越高，半衰期约 180 天。"""
    ds = m.get("accessed") or m.get("created") or today()
    try:
        d = datetime.date.fromisoformat(ds)
    except Exception:
        return 0.5
    days = max(0, (datetime.date.today() - d).days)
    return round(0.5 ** (days / 180.0), 4)

    # ── TF-IDF 语义召回 + token 估算（零依赖 vendored）──
_STOPWORDS = frozenset(
    "的 了 是 在 和 与 或 等 于 对 这 那 有 我 你 他 她 它 们 不 也 就 一个 我们 这个 什么 如何 怎么 没有 可以 需要 如果 因为 所以 但是 而且 已经 或者 以及 对于 关于 通过 使用 进行 所有 实现 完成 开始 结束 之后 之前 时候 目前 情况 问题 方法 内容 文件 功能 支持 提供 the a an is are was were be been being have has had do does did will would could should may might can shall to of in for on with at by from and or but not no so if as it this that these those its they them".split()
)

def _tokenize_mixed(text):
    """中英文混合分词：英文单词 + 中文 2-gram，去停用词。供 TF-IDF 召回。"""
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9_]+", text)
    bg = [text[i:i + 2] for i in range(len(text) - 1)
          if text[i] not in " \n\t\r，。、：；！？""''（）【】"]
    return [t for t in (toks + bg) if t not in _STOPWORDS and len(t) > 1]

def _tfidf_search(root, query, mems=None, include_superseded=False, include_archived=False, top_k=10, min_score=0.02):
    """TF-IDF 语义召回（零依赖）。返回 [(id, score)] 降序。
    解决 recall 仅子串匹配的局限（O5）——「怎么煮肉不柴」这类语义等价查询也能命中。
    mems 可外部传入（避免与 _rank_query 重复扫描全部记忆文件，千条库性能关键）。
    include_archived=True 时一并纳入已归档记忆（对应 recall --deep 的语义召回）。"""
    import math
    from collections import Counter
    if mems is None:
        mems = _all_mems(root)
    docs, ids = [], []
    for m in mems.values():
        st = m.get("status", "active")
        if st != "active" and not (include_superseded and st == "superseded") \
                and not (include_archived and st == "archived"):
            continue
        text = " ".join([m.get("summary", ""), m.get("body", ""),
                         " ".join(m.get("tags", []))])
        docs.append(_tokenize_mixed(text))
        ids.append(m["id"])
    if not docs or not query:
        return []
    N = len(docs)
    df = Counter()
    for d in docs:
        for t in set(d):
            df[t] += 1
    idf = {t: math.log((N + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    doc_vecs = []
    for d in docs:
        tf = Counter(d)
        tot = len(d) or 1
        doc_vecs.append({t: (tf.get(t, 0) / tot) * idf.get(t, 0) for t in tf})
    qt = _tokenize_mixed(query)
    if not qt:
        return []
    qtf = Counter(qt)
    qvec = {t: (qtf.get(t, 0) / len(qt)) * idf.get(t, 0) for t in qtf}
    qn = math.sqrt(sum(v * v for v in qvec.values()))
    if qn == 0:
        return []
    res = []
    for i, dv in enumerate(doc_vecs):
        dn = math.sqrt(sum(v * v for v in dv.values()))
        if dn == 0:
            continue
        dot = sum(qvec.get(t, 0) * dv.get(t, 0) for t in qvec)
        sim = dot / (qn * dn)
        if sim >= min_score:
            res.append((ids[i], round(sim, 4)))
    res.sort(key=lambda x: x[1], reverse=True)
    return res[:top_k]

    # F18 阶段2 批7：_rank_query 已迁至 memory_ops/_api.py

def token_estimate(mem):
    """基于字符数粗略估算记忆所占 token（约 1 token/2 字符 + 固定开销）。"""
    txt = " ".join([mem.get("summary", ""), mem.get("body", ""),
                    " ".join(mem.get("tags", []))])
    return len(txt) // 2 + 8

class SensitiveError(ValueError):
    """deposit 写入时检测到 secrets；按 SOUL 红线直接拒写。"""

    # ── P2 · 敏感 quarantine（修 H3：命中敏感不再静默丢弃，可逆隔离待审）──────────

def _capture_dedup(root, summary, body, tags, threshold=0.6, topk=5, include_archived=False):
    """ §7 · 自动汲取查重（capture-before-deposit）。

    直接复用 reflect 去重用的语义相似度（_emb.semantic_similarity），阈值 0.6 与
    reflect 去重口径一致——避免依赖 recall 的 TF-IDF 检索排序分（近重复文本也只打
    很低分，不适合做查重信号）。对 active 库逐条比对（include_archived=True 时一并
    扫 archived，用于 H2 复活复用），返回相似度 ≥ threshold 的 advisory 列表。
    调用方拿到 matches=[{mid, score, summary, status}] 后决定：合并 update /
    标 superseded / 复活复用 / 仍新建。返回 dict：{matches: [...], has_strong_match: bool}
    """
    new_text = " ".join([summary or "", body or ""]).strip()
    if not new_text:
        return {"matches": [], "has_strong_match": False}
    mems = _all_mems(root)
    out = []
    for mid, m in mems.items():
        st = m.get("status")
        if st != "active" and not (include_archived and st == "archived"):
            continue
        existing = " ".join([m.get("summary", ""), m.get("body", "")]).strip()
        if not existing:
            continue
        try:
            sc = float(_emb.semantic_similarity(new_text, existing))
        except Exception:
            continue
        if sc >= threshold:
            out.append({
                "mid": m.get("id") or mid,
                "score": round(sc, 4),
                "summary": (m.get("summary") or "")[:120],
                "status": st,
            })
    out.sort(key=lambda x: x["score"], reverse=True)
    return {"matches": out[:topk], "has_strong_match": bool(out)}

def _mem_quality_rank(m):
    """质量排序键（越大越该保留为 canonical）：来源显式度 > confidence > importance。"""
    is_explicit = (m.get("recorded_by") == "user") or (
        not m.get("auto_sourced", False)
        and m.get("confidence_basis") in ("explicit", None))
    conf = float(m.get("confidence") or 0.0)
    imp = float(m.get("importance") or 0.0)
    return (1 if is_explicit else 0, conf, imp)

_TIER_RANK = {"draft": 1, "working": 2, "curated": 3, "core": 4}

def _tier_rank(tier):
    return _TIER_RANK.get((tier or "working"), 2)

def _new_outranks_old(old_mem, new_confidence, new_importance, new_inferred,
                      new_auto_sourced, new_recorded_by, category, scope,
                      new_tier=None, old_tier=None):
    """新记忆质量是否严格高于旧记忆（用于近重复 supersede 决策）。

    返回 True  → 新记忆质量更高，取代旧记忆（corrects 路径，旧被 superseded）；
    返回 False → 旧记忆质量不低于新记忆，保留旧为 canonical、丢弃新低质重复。
    设计动机：修复「低置信的 auto_sourced/inferred 记忆把高置信 explicit 记忆挤出活跃库」缺陷。

    v4.7.0 增强：引入 tier 维度。当新记忆 tier 严格高于旧记忆（如 curated 取代 working）
    时，即使质量元组持平也允许其作为更高层抽象胜出（不靠 skips_dedup 粗暴绕过）。
    注意：evolve 等**派生记忆**已在调用方（_deposit_impl 查重守卫）经 derives_from 直接
    跳过查重，不会走到本函数；本函数只负责「非派生近重复」的质量裁决。
    """
    old_rank = _mem_quality_rank(old_mem)
    new_explicit = (new_recorded_by == "user") or (not new_auto_sourced and not new_inferred)
    new_conf = float(new_confidence) if new_confidence not in (None, 0.0) else (0.5 if new_inferred else 1.0)
    new_imp = float(new_importance) if new_importance is not None else _default_importance(category, scope)
    new_rank = (1 if new_explicit else 0, new_conf, new_imp)
    if new_rank > old_rank:
        return True
        # tier 严格升维：更高层抽象胜出（其余维度持平也允许）
    if new_tier is not None and old_tier is not None:
        if _tier_rank(new_tier) > _tier_rank(old_tier):
            return True
    return False

def _audit_log(root, op, mid=None, extra=None):
    # 无装饰器：调用方（_deposit_impl 等）已在跨进程锁内，避免重复加锁
    """ 变更审计：写操作 append 一行 JSON 到 store/audit.log（append-only）。

    记录 op/记忆 id/时间/来源(recorded_by)/额外信息，供追溯「谁在何时改了哪条」。
    日志文件只追加不覆盖；写入失败不影响主流程（审计是旁路，fail-open）。
    """
    try:
        p = os.path.join(root, "store", "audit.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
               "op": op, "id": mid or ""}
        if extra:
            rec.update(extra)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        # 2026-09-15 审计：审计仍属旁路（fail-open，不阻断业务），但**必须留痕**——
        # 否则「audit.log 缺条目」会被误读成「没发生过该操作」（本机曾据此做过使用面统计）。
        import sys as _sys
        _sys.stderr.write("[⚠ 审计] audit.log 写入失败（业务不受影响）：%s\n" % _e)

def _audit_log_tail(root, n=20, op_filter=None):
    """读取 store/audit.log 尾部 n 条（可选按 op 过滤），返回 list[dict]。"""
    out = []
    p = os.path.join(root, "store", "audit.log")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
        for ln in lines[-max(n * 3, 200):]:  # 只读尾部足够行，避免全量
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except (json.JSONDecodeError, ValueError):
                continue
            if op_filter and rec.get("op") != op_filter:
                continue
            out.append(rec)
            if len(out) >= n:
                break
    except OSError:
        pass
    return out

def _embedding_status_label():
    """返回当前 embedding 后端标签，供 deposit/recall 返回，让用户知道召回质量是真·语义还是降级词法。
    P-audit 修复：以 _emb._NEURAL 真实加载态为准（False=实际不可用），而非仅看配置后端，
    避免「实际降级却报 neural」的误导标签（F8）。"""
    try:
        _neural = _emb._NEURAL
    except Exception:
        _neural = None
    if _neural is False:
        return "lexical_degraded"          # 真实不可用 → 诚实报降级
    if isinstance(_neural, tuple):
        return "neural:%s" % _neural[0]    # 真实已加载 → 报神经后端
        # 尚未探测：回退配置后端标签（best-effort，不保证与实际一致）
    try:
        bid = _emb._backend_id()
    except Exception:
        return "unknown"
    if bid in ("lexical", "none", ""):
        return "lexical_degraded"
    return "neural:%s" % bid

    # F18 阶段2 批8：_deposit_impl 已迁至 memory_ops/_deposit.py

    # F18 阶段2 批8：deposit 已迁至 memory_ops/_deposit.py

@_with_deposit_lock
def migrate_v30_fields(root):
    """Phase 1 迁移：为既有记忆补 type/settled/probe_until/thermal（幂等、可重复跑）。

    - 旧记忆视为已沉淀（settled=True，避免冷启动死循环误伤真实知识）。
    - probe_until=None（已是验证过的旧知识，无需再观察）。
    - type 由 category 规范化（内容零损失，只补规范类型标签）。
    - thermal 由热度计算。
    不改记忆原文、不改 category、不删不改既有关系。返回迁移条数。"""
    mems = _all_mems(root)
    n = 0
    for mid, m in mems.items():
        if not isinstance(m, dict):
            continue
        changed = False
        if m.get("type") not in TYPE_CANON:
            m["type"] = _normalize_type(m.get("category", ""))
            changed = True
        if "settled" not in m:
            m["settled"] = True
            changed = True
        if "probe_until" not in m:
            m["probe_until"] = None
            changed = True
        if m.get("thermal") not in ("hot", "warm", "cold"):
            # 5.0/A1：热度判定改读单一热源（记忆内 access_count 真库恒 0，会一律判 cold）
            m["thermal"] = compute_thermal(m, access_n=_access_count_of(root, mid, m))
            changed = True
        if changed:
            _save_mem(root, mid, m)
            n += 1
            # 同步 index.json 的 entry（保持 mem 与 index 一致，recall 才看得到）
    try:
        data = load_index(root)
        by_id = {e.get("id"): e for e in data.get("entries", []) if isinstance(e, dict)}
        for mid, m in mems.items():
            e = by_id.get(mid)
            if e is not None:
                e["type"] = m.get("type")
                e["settled"] = m.get("settled")
                e["thermal"] = m.get("thermal")
        save_index(root, data)
    except Exception as _e:
        import sys as _sys
        _sys.stderr.write("[⚠ migrate_v30] 索引同步失败（记忆文件已写、索引可能滞后；请运行 rebuild / doctor --fix）：%s\n" % _e)
    return n

def _write_mem(root, mid, payload):
    _assert_safe_mid(mid)  # 路径穿越守卫：deposit 的落盘入口，阻断写出库外/覆盖同名文件
    # 5.0.0：旧加密库 fail-closed 守卫。**本函数是 deposit 的独立落盘真源**（不走
    # _save_mem），G1 覆盖面实跑实测：只守 _save_mem 时 `deposit` 会**静默写入明文**——
    # 正是「明文写进密文库 ⇒ 混库 ⇒ 降级后整库读不出」这条最危险的路径。必须两处都守。
    assert_not_legacy_encrypted(root, op="写入记忆 %s" % mid, mem=payload)
    os.makedirs(mem_dir(root), exist_ok=True)
    fpath = os.path.join(mem_dir(root), mid + ".json")
    # ── 写入门禁（4.9.5，与 _save_mem 对称；deposit 是第二个写入真源）──
    _gate_prewrite_snapshot(root, mid, fpath)
    tmp = fpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fpath)  # 原子替换
    _mem_cache_put(root, mid, payload, fpath)  # 缓存明文 payload（与调用方视角一致）
    _RESOLVE_PATH_CACHE.pop((root, mid), None)  # 修 D3：负缓存生效后，写文件必须清缓存（否则 _resolve_path 返回陈旧 None）
    # ── 版本历史收口（与 _save_mem 对称）──
    # _write_mem 是 deposit 的落盘入口（独立于 _save_mem），若不同步收口，新建记忆的 v1
    # 就永远留不下版本基线（实测：改前 147 条记忆仅 3 条有版本 = 2.0%）。
    # 语义与守卫同 _save_mem：幂等（同版本快照已存在则跳过）、异常吞掉不阻断主写入。
    try:
        _snapshot_version(root, mid, payload)
    except Exception as _e:
        sys.stderr.write("[⚠ _write_mem] 版本快照失败(已忽略，主写入成功): %s\n" % _e)
    return fpath

def _default_importance(category, scope):
    """默认重要性评分（0-1），由类别/范围推断。
    correction 最重要（纠正类经验），universal 通用经验次之，ephemeral 临时最低。"""
    if category == "correction":
        return 0.9
    if scope == "ephemeral":
        return 0.4
    if scope == "project":
        return 0.7
    if scope == "universal":
        return 0.6
    return 0.5

    # F18 阶段2 批8：_auto_link_similar 已迁至 memory_ops/_deposit.py

def _find_link_candidates(root, threshold=0.15, max_per=5):
    """全库扫描「主题相关但未连边」的记忆对（related_to 候选）。

    性能与正确性：复用 reflect 去重的「标签预分组 + 大组跳过(MAX_GROUP=150)」策略，
    只在共享具体标签的小组内做两两比较，避免千条库 O(n²) 爆炸；组内用廉价 `_sim`
    （jaccard，与 deposit 自动连边同口径）预筛，阈值 0.15（低于去重 0.6，专抓「相关
    但不重复」）。已存在双向 related_to 的边不重复推荐。仅考虑 active 记忆。
    返回 [{"a": id, "b": id, "score": float}]，每记忆最多 max_per 条候选（按相似度）。
    """
    MAX_GROUP = 150
    mems = {mid: m for mid, m in _all_mems(root).items()
            if m.get("status") == "active"}
    ids = list(mems)
    by_tag = {}
    for mid in ids:
        for t in (mems[mid].get("tags", []) or []):
            by_tag.setdefault(t, []).append(mid)
            # 预筛候选对（标签重叠 + 组不过大）
    cand_pairs = set()
    for _grp in by_tag.values():
        if len(_grp) < 2 or len(_grp) > MAX_GROUP:
            continue
        for i in range(len(_grp)):
            for j in range(i + 1, len(_grp)):
                cand_pairs.add((_grp[i], _grp[j]))
    linked = set()
    for mid in ids:
        for t in (mems[mid].get("relations", {}).get("related_to", []) or []):
            linked.add((mid, t))
            linked.add((t, mid))
    # 🔴 可复现性修复（2026-09-15 审计）：cand_pairs 是 set，若直接 `for ia, ib in cand_pairs`
    # 迭代，顺序取决于字符串哈希，而 PYTHONHASHSEED 每个进程都在变 → 顺序每次不同；
    # 叠加下面的 max_per「先到先得」截断，doctor 的 link_candidates 输出因此每次运行都变、
    # 无法复现（实测：PYTHONHASHSEED=0 时两次逐字节一致）。改为先算全部合格对并按
    # (-score, a, b) 排序，再按序贪心应用 max_per —— 输出完全确定，且每记忆保留的是
    # 高分候选（优于原先的随机先到先得）。
    _scored = []
    for ia, ib in cand_pairs:
        if (ia, ib) in linked or (ib, ia) in linked:
            continue
        a, b = mems[ia], mems[ib]
        ta = " ".join([a.get("summary", ""), a.get("body", ""),
                       " ".join(a.get("tags", []))]).strip()
        tb = " ".join([b.get("summary", ""), b.get("body", ""),
                       " ".join(b.get("tags", []))]).strip()
        if not ta or not tb:
            continue
        s = _sim(ta, tb)
        if s >= threshold:
            _scored.append((ia, ib, round(s, 4)))
    _scored.sort(key=lambda x: (-x[2], x[0], x[1]))
    results = []
    per_count = {}
    for ia, ib, s in _scored:
        if per_count.get(ia, 0) >= max_per or per_count.get(ib, 0) >= max_per:
            continue
        results.append({"a": ia, "b": ib, "score": s})
        per_count[ia] = per_count.get(ia, 0) + 1
        per_count[ib] = per_count.get(ib, 0) + 1
    return results

    # F18 阶段2 批8：flush_memory_index 已迁至 memory_ops/_deposit.py

    # ── Phase 2 检索管线（R → L0 → L1 → L2 → L3）（设计基线 §3/§4/§5）──────────────
    # 纯加性：完全不改 recall 本体，49 个已发布 op 零回归（Phase 2 检索管线）。
    # 注：历史上曾有 recall_v30/reflect_v30 引擎变体，已在 4.x 清理；CAP_HOT_* 常量名沿用 v30 旧称但当前真实生效。
CAP_HOT_PER_TYPE = 5        # 每 type 热常驻上限（recall_v30 与 reflect_v30 共用）
CAP_HOT_GLOBAL = 25         # 全局热常驻上限（recall_v30 与 reflect_v30 共用）
PHASE2_QUOTA_HOT = {"BP": CAP_HOT_PER_TYPE, "WF": CAP_HOT_PER_TYPE, "PF": CAP_HOT_PER_TYPE,
                    "PREF": CAP_HOT_PER_TYPE, "FACT": CAP_HOT_PER_TYPE, "DOC": CAP_HOT_PER_TYPE}
PHASE2_QUOTA_WARM = {"BP": 15, "WF": 15, "PF": 15, "PREF": 15, "FACT": 20, "DOC": 10}
PHASE2_GLOBAL_HOT_CAP = CAP_HOT_GLOBAL
PHASE2_COMFORT_QUOTA = 20          # auto 模式下触发 L3 的候选阈值（设计基线 §3.1）
PHASE2_IMPORTANCE_FLOOR = 0.8     # 可检保底（不占热配额，设计基线 §4.1）
PHASE2_PROBE_PERIOD_DAYS = 14
PHASE2_SETTLE_PROBE_DAILY_N = 20

# 改进：配额随库规模自适应（改进 2.1）
# 原硬编码 CAP_HOT_PER_TYPE=5/CAP_HOT_GLOBAL=25 在小库用不满、大库 L3 频繁触发。
# 自适应后：100条→base, 1000条→2×base, 10000条→3×base，用户可在 config.json 覆盖。
ADAPTIVE_QUOTA_ENABLED = True
ADAPTIVE_QUOTA_BASE_PER_TYPE = 5
ADAPTIVE_QUOTA_BASE_GLOBAL = 25
ADAPTIVE_QUOTA_MAX_PER_TYPE = 30
ADAPTIVE_QUOTA_MAX_GLOBAL = 150

def _adaptive_quota(total_active):
    """配额随库规模对数缩放，避免小库配额用不满 / 大库 L3 频繁触发。

    100条→5/25, 1000条→10/50, 10000条→15/75（对数缩放，平滑过渡）。
    用户可在 config.json 的 recall.quota 块覆盖 base_per_type/base_global/max_per_type/max_global。
    """
    if not ADAPTIVE_QUOTA_ENABLED:
        return ADAPTIVE_QUOTA_BASE_PER_TYPE, ADAPTIVE_QUOTA_BASE_GLOBAL
    try:
        import math
        scale = 1.0 + max(0.0, math.log10(max(total_active, 1) / 100.0))
    except Exception:
        scale = 1.0
    per_type = min(int(ADAPTIVE_QUOTA_BASE_PER_TYPE * scale), ADAPTIVE_QUOTA_MAX_PER_TYPE)
    global_cap = min(int(ADAPTIVE_QUOTA_BASE_GLOBAL * scale), ADAPTIVE_QUOTA_MAX_GLOBAL)
    return per_type, global_cap

def _entry_type(e):
    """从 index entry / mem 取规范化 type（优先 v3 type 字段，否则由 legacy category 归一）。"""
    t = e.get("type") or _normalize_type(e.get("category", ""))
    return t if t in TYPE_CANON else "FACT"

def route_type(root, query, type_hint=None, llm=None):
    """ [R] 路由层：判问题类型。返回 dict：
    {type, confidence, low_conf, fallback:[...], via, reasons:[...]}。
    - type_hint 显式给定且合法 → 直接采用（confidence=1.0）。
    - 否则 llm 可用 → 调 LLM 路由（JSON {type, confidence}）；解析失败/未知 → low_conf=True + fallback FACT+BP。
    - 否则规则兜底 classify_type；confidence<0.5 → low_conf=True + fallback FACT+BP。
    设计基线 §3：路由不确定时回退 FACT+BP 全量候选（不丢信息），记低置信路由。"""
    if type_hint:
        th = _normalize_type(type_hint)
        if th in TYPE_CANON:
            return {"type": th, "confidence": 1.0, "low_conf": False,
                    "fallback": [], "via": "hint", "reasons": ["explicit hint"]}
    chat, _ = _resolve_llm(root, llm)
    if chat is not None:
        try:
            system = ("你是记忆路由助手。将用户问题归类到唯一类型："
                      "BP(可复用最佳实践/方法)、WF(多步流程/操作顺序)、PF(坑/别做/反例)、"
                      "PREF(用户长期偏好/习惯)、FACT(客观事实/环境常量)、DOC(长文档/报告摘要)。"
                      "只输出 JSON：{\"type\":\"<之一>\",\"confidence\":0.0~1.0}。")
            user = "问题：%s" % (query or "")
            out = chat(system, user, temperature=0.0, max_tokens=200)
            obj = _parse_llm_json_obj(out)
            t = _normalize_type(obj.get("type", ""))
            conf = float(obj.get("confidence", 0.7))
            if t in TYPE_CANON and conf >= 0.5:
                return {"type": t, "confidence": conf, "low_conf": False,
                        "fallback": [], "via": "llm", "reasons": ["llm route"]}
            return {"type": t if t in TYPE_CANON else "FACT", "confidence": conf,
                    "low_conf": True, "fallback": ["FACT", "BP"], "via": "llm-low",
                    "reasons": ["llm low confidence/unknown -> fallback FACT+BP"]}
        except Exception:
            pass  # LLM 不可用 → 降级规则
    t, conf, reasons = classify_type(query or "", body=query or "")
    low = conf < 0.5
    return {"type": t, "confidence": conf, "low_conf": low,
            "fallback": ["FACT", "BP"] if low else [],
            "via": "rule", "reasons": reasons}

def _format_v30_entry(root, e, m, touch=False, scope=None, project=None):
    """把 (index entry, mem) 格式化为 recall 兼容 dict（含 v3 字段），与 recall 输出同构。

    5.0/A1：暴露的 `access_count` 取自**单一热源**（recall_counts.json），不再读记忆文件
    里那个恒 0 的僵尸字段——否则调用方（agent/UI/自动化）看到的「召回热度」永远是 0。"""
    fp = _resolve_path(root, e.get("id") or "")
    _mid = m.get("id") or e.get("id")
    _ac = _access_count_of(root, _mid, m)
    rec = {
        "id": m.get("id") or e.get("id"),
        "category": m.get("category", e.get("category", "")),
        "summary": m.get("summary", e.get("summary", "")),
        "tags": m.get("tags", e.get("tags", [])),
        "tier": m.get("tier", "working"),
        "scope": m.get("scope", "universal"),
        "status": m.get("status", "active"),
        "relations": m.get("relations", {}),
        "version": m.get("version", 1),
        "file": fp,
        "recorded_by": m.get("recorded_by", "agent"),
        "access_count": _ac,
        "accessed_from": m.get("accessed_from", []),
        "body": m.get("body", ""),
        "confidence": m.get("confidence", 1.0),
        "conf_alpha": m.get("conf_alpha"), "conf_beta": m.get("conf_beta"),
        "auto_sourced": m.get("auto_sourced", False),
        "type": m.get("type", _normalize_type(m.get("category", ""))),
        "secondary_types": m.get("secondary_types", []),
        "domain": m.get("domain"),
        "scene": m.get("scene") or e.get("scene"),  # v3.7.0 多轴 taxonomy 第二轴（与 topic 正交）
        "scene_confidence": m.get("scene_confidence") or e.get("scene_confidence"),
        "scene_via": m.get("scene_via") or e.get("scene_via"),
        "type_confidence": m.get("type_confidence", 1.0),
        "settled": m.get("settled", False),
        "thermal": m.get("thermal", "warm"),
    }
    if touch and m.get("status") == "active":
        m["accessed"] = today()
        # 🔴 5.0/A1 续修：**不得**在此自增 `m["access_count"]`。
        #   频次唯一权威是 `recall_counts.json`，写入点是 recall 末尾的批量段
        #   `_bump_recall_counts(root, [全部命中])`；本函数若也写，就是双写（且会重复计数）。
        #   注：本函数目前全仓**无调用点**（历史渲染入口），保留仅为兼容；
        #   静态守卫 tests/test_v50_access_count_single_source.py 会拦住任何文件侧自增。
        # B3·修 H8：被真正引用即「用出来的重要性」上调（不再只靠类别先验）。
        # importance 自此由 reuse 信号驱动；类别先验仅作初始值。封顶 1.0。
        _imp = float(m.get("importance", 0.5) or 0.5)
        m["importance"] = round(min(1.0, _imp + IMPORTANCE_USE_DELTA), 4)
        # #5 修复：recall touch 时实时重算 thermal 并持久化——此前 thermal 仅在
        # reflect_v30 时更新，两次 reflect 间高频访问的记忆仍显示旧 cold，被排除热配额。
        m["thermal"] = compute_thermal(m, access_n=_ac + 1)
        rec["thermal"] = m["thermal"]
        af = m.setdefault("accessed_from", [])
        ctx = {"date": today()}
        if project:
            ctx["project"] = project
            ctx["scope"] = "project"
        elif scope:
            ctx["scope"] = scope
        af.append(ctx)
        if len(af) > 12:
            del af[:len(af) - 12]
        _save_mem(root, rec["id"], m)
    return rec

    # =====================================================================
    # P0（3.9.x）：投资「指标自动收敛」 + 数值过滤 DSL（纯正则/A 方案）
    # --------------------------------------------------------------------
    # 设计原则（用户拍板）：
    # - 抽取走正则（零成本、离线、确定可测），不调模型；B 类「正则+LLM 兜底」
    # 作为可选增强留待后续，不阻塞主链路。
    # - --filter DSL 够用即可：数值比较(> >= < <= = !=) + AND/OR + 字符串
    # 等式(scene/domain/tag/type)，禁用 eval/exec，绝不执行任意表达式。
    # - attrs 是 mem 的纯加性 dict 字段 {指标名(str): 数值(float/int)}，
    # 旧库缺字段时返回空 dict，recall/导出均安全降级。
    # =====================================================================

    # F18 阶段2：DSL（数值过滤 / 指标抽取）子模块独立为 memory_ops/_dsl.py
    # 原整簇逻辑（L5465-L5697），零行为变化。
    # 重导出采用「文件绝对路径加载」而非相对导入：regression_v390.py 等用
    # spec_from_file_location("mo", __init__.py) 把本文件当独立模块加载（非包），
    # 此时相对导入 from ._dsl import 会报 ModuleNotFoundError。按路径加载子模块
    # 可兼容「作为包」与「作为独立模块」两种导入方式，调用方解析不变。
import importlib.util as _ilu
_dsl_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dsl.py")
_dsl_mod = _ilu.spec_from_file_location("memory_ops._dsl", _dsl_file)
_dsl = _ilu.module_from_spec(_dsl_mod); _dsl_mod.loader.exec_module(_dsl)
# 补注册包内名：让 `from memory_ops import _dsl` 拿到注入实例而非标准导入的未注入副本
# （与 _config/_core/_graph/_legacy/_persistence 一致；2026-09-27 实测此前遗漏，P1-1 同族）。
sys.modules.setdefault("memory_ops._dsl", _dsl)
_ATTR_METRIC_WHITELIST = _dsl._ATTR_METRIC_WHITELIST
_ATTR_METRIC_ALIAS = _dsl._ATTR_METRIC_ALIAS
_ATTR_BLACKLIST_TOKEN = _dsl._ATTR_BLACKLIST_TOKEN
_ATTR_NUM_RE = _dsl._ATTR_NUM_RE
_coerce_metric_value = _dsl._coerce_metric_value
_norm_attr_key = _dsl._norm_attr_key
_extract_attrs = _dsl._extract_attrs
_merge_attrs = _dsl._merge_attrs
_ATTR_FILTER_FIELDS = _dsl._ATTR_FILTER_FIELDS
_STR_FILTER_FIELDS = _dsl._STR_FILTER_FIELDS
_CMP_RE = _dsl._CMP_RE
_TOK_RE = _dsl._TOK_RE
parse_filter = _dsl.parse_filter
_cmp = _dsl._cmp
_match_clause = _dsl._match_clause
eval_filter = _dsl.eval_filter

# 改进 P1-5：recall 结果缓存（60s TTL）
# 进程级缓存，仅对同进程内多次 recall 同一 query 有效（CLI 每次新进程不命中）。
# touch/ann/mid 等有副作用的调用不缓存。可在 config.json 的 recall.cache_ttl_seconds 覆盖。
_RECALL_CACHE = {}  # key → (timestamp, results)
# 5.0：单一来源——默认值取自 RRF_DEFAULTS["cache_ttl_seconds"]（原先这里另写一个 60，
# 与 config 默认值是两份独立定义；一旦只改一处就会出现「默认值 vs 文档」不一致）。
RECALL_CACHE_TTL_DEFAULT = int(RRF_DEFAULTS["cache_ttl_seconds"])  # 秒

# #6：跨 type 联想——召回结果中缺少的 type，从全库找共享标签的同主题记忆补入。
_CROSS_TYPE_MAX_EXTRA = 4  # 最多补入条数（避免结果膨胀）
_CROSS_TYPE_TOP_SCAN = 5   # 从 top N 结果提取标签种子

def _cross_type_associate(root, data, out, scope, project, deep, include_superseded):
    """对已召回结果做跨 type 补全。

    从 top 结果提取标签种子，扫描全库 active 记忆中 type 未出现在 top 结果的条目，
    若共享 ≥1 标签则作为 associated 追加（低分、标记 associated=True）。
    补全不改变原有排序，仅追加到末尾。"""
    if not out:
        return out
        # 1) 收集 top 结果的 type 和标签种子
    top = out[:_CROSS_TYPE_TOP_SCAN]
    seen_types = set()
    seed_tags = set()
    seen_ids = set(e.get("id") for e in out)
    for e in top:
        t = e.get("type", "")
        if t:
            seen_types.add(t)
        for tag in (e.get("tags") or []):
            seed_tags.add(tag)
    if not seed_tags:
        return out  # 无标签种子，跳过

        # 2) 扫描全库找缺失 type 的同标签记忆
    extra = []
    for e in data.get("entries", []):
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not eid or eid in seen_ids:
            continue
        st = e.get("status")
        if st != "active" and not include_superseded:
            if not (deep and st == "archived"):
                continue
        et = e.get("type", "")
        if not et or et in seen_types:
            continue  # type 已在 top 结果中，不补
            # scope/project 过滤一致性
        es = e.get("scope", "universal")
        if scope:
            if scope == "project" and es not in ("project", "universal"):
                continue
            elif scope != "project" and es != scope:
                continue
        if project and e.get("project") != project and es != "universal":
            continue
            # 共享标签检查
        shared = set(e.get("tags", [])) & seed_tags
        if not shared:
            continue
            # 富化字段（从文件读取正文等）
        try:
            m, _ = _load_mem(root, eid)
            e = dict(e)
            e["body"] = m.get("body", "")
            e["relations"] = m.get("relations", {})
            e["type"] = m.get("type", et)
            e["settled"] = m.get("settled", False)
            e["thermal"] = m.get("thermal", "warm")
            e["confidence"] = m.get("confidence", 1.0)
            # 5.0/A1 续修：读**单一热源**（文件 `access_count` 在真库恒 0，
            # 会让「跨 type 联想补入」的条目在结果里恒显示频次 0）
            e["access_count"] = _access_count_of(root, eid, m)
            e["associated"] = True
            e["score"] = 0.0  # associated 条目零分，排末尾
            e["assoc_reason"] = "shared_tags:%s" % ",".join(sorted(shared)[:3])
            extra.append(e)
            seen_ids.add(eid)
            seen_types.add(et)  # 每个 type 只补一条
        except Exception:
            continue
        if len(extra) >= _CROSS_TYPE_MAX_EXTRA:
            break
    return out + extra

    # F18 阶段2 批7：recall_multi 已迁至 memory_ops/_api.py

    # F18 阶段2 批7：recall 已迁至 memory_ops/_api.py

    # ── B5 ：召回频率 → 重要性正反馈 ──
    # 独立于 touch 的「召回频次」计数器（落 store/recall_counts.json，不写记忆文件），
    # 周期性（doctor --fix / reflect）按频次幂等重算 importance：
    # recall_freq_score = log(1+count)/log(1+max_count) ∈ (0,1]
    # importance = clamp(prior + 0.3 * recall_freq_score)
    # 频繁被召回的记忆稳定升温；长期零召回（count=0）回到先验 → 自然降温（与 _lazy_importance_decay 互补）。
_RECALL_CNT_LOCK = threading.Lock()

def _recall_counts_path(root):
    return os.path.join(root, "recall_counts.json")

def _bump_recall_counts(root, ids):
    """B5：把本次 query recall 命中的 id 频次 +1，并记录最后召回日。幂等写、带锁，不写记忆文件。"""
    if not ids:
        return
    cfg = _load_recall_config(root)
    if not cfg.get("frequency_tracking", True):
        return
    p = _recall_counts_path(root)
    with _RECALL_CNT_LOCK:
        data = {}
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8") as _f:
                    data = json.load(_f) or {}
        except Exception:
            data = {}
        today_s = today()
        for mid in ids:
            if not mid:
                continue
            rec = data.get(mid) or {}
            rec["count"] = int(rec.get("count", 0)) + 1
            rec["last"] = today_s
            data[mid] = rec
        tmp = p + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as _f:
                json.dump(data, _f, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception:
            pass

_RC_COUNTS_CACHE = {}  # root → (mtime, {mid: count})：进程内热源缓存，mtime 变了自动失效

def _load_recall_counts(root):
    """一次性读热源 `recall_counts.json` → {mid: count}。

    供批量场景（decay / doctor / reflect 一次遍历全库）与逐条场景共用。
    带**进程内 mtime 缓存**：同一进程内重复调用只读盘一次，热源被写入后（mtime 变）
    自动重新加载，故不会读到过期计数。全程吞异常：缺失/损坏返回 {}，由调用方兜底。"""
    try:
        p = _recall_counts_path(root)
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    except Exception:
        return {}
    _ck = _root_key(root)
    _hit = _RC_COUNTS_CACHE.get(_ck)
    if _hit is not None and _hit[0] == mt:
        return _hit[1]
    out = {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f) or {}
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    out[k] = int(v.get("count", 0) or 0)
                elif isinstance(v, (int, float)):
                    out[k] = int(v)
    except Exception:
        out = {}
    _RC_COUNTS_CACHE[_ck] = (mt, out)
    return out

def _access_count_of(root, mid, mem=None, counts=None):
    """🔴 召回频次的**单一热源**读取入口（5.0/A1）。

    权威定义：一条记忆「被召回多少次」= `recall_counts.json[mid]["count"]`，
    **不是**记忆文件里的 `access_count` 字段。

    为什么必须收口（2026-09-16 真库实测）：
      · 热源侧 1214 条、中位数 82；记忆文件侧 211 条、**204 条恒为 0**、中位数 0；
      · 两处可比对的 142 条 **100% 不一致**；
      · 而下游 decay 的排序权重与沉淀门槛、doctor 的晋升筛选、reflect 的归档续命
        **原来全部读文件侧** → 三条治理链同时失效（沉淀永不触发 / 排序权重退化为
        常量 1 / 晋升筛选恒空）。这是本仓「规则层期待的字段 ≠ 写入侧实际产生的字段」
        根因族的第四次命中。
    本函数是上述所有下游的统一取数口。`mem["access_count"]` **仅作旧库过渡回退**，
    不再作为权威；缺失时返回 0。批量场景请先 `_load_recall_counts(root)` 再传入
    `counts=`，避免逐条开文件。
    """
    if mid and counts is not None:
        if mid in counts:
            return int(counts[mid] or 0)
    elif mid:
        try:
            _c = _load_recall_counts(root)
            if mid in _c:
                return int(_c[mid] or 0)
        except Exception:
            pass
    if mem is None and mid:
        try:
            mem, _ = _load_mem(root, mid)
        except Exception:
            mem = None
    return int((mem or {}).get("access_count", 0) or 0)

def _as_of_visible(m, as_of):
    """5.0/A3 双时序可见性：在 `as_of` 这个时点上，这条记忆是否「为真」。

    规则（日期为 YYYY-MM-DD，可直接字典序比较）：
      · `valid_at`（缺省回退 `created`；两者都缺 → 视为一直有效）必须 ≤ as_of；
      · `invalid_at` 缺失 → 仍然有效；有值且 ≤ as_of → 该时点已失效，不可见。

    与 `status` 的分工：`status` 表达「**现在**是什么状态」（active/superseded/archived），
    本函数表达「**某个过去时点**是否为真」——所以 as_of 查询会**绕过 status 过滤**，
    否则一条现在被 superseded 的记忆在过去时点就永远查不到了。"""
    if not as_of:
        return True
    _d = str(as_of)
    va = m.get("valid_at") or m.get("created")
    if va and str(va) > _d:
        return False
    ia = m.get("invalid_at")
    if ia and str(ia) <= _d:
        return False
    return True


def _apply_rehearsal_weight(mem, alpha=None):
    """（P3/C2）：复述自动加权——记忆被命中时 importance 小步上升。
    α 默认 0.05（可经 KEEPER_REHEARSAL_ALPHA env 调），recency_weight 随时间衰减：
    距离上次访问 d 天 → 衰减因子 = exp(-d/30)。与 decay 公式（《长期不命中拉低》）互补，
    形成「常命中升、久不命中降」的平衡。返回是否实际改动 importance。"""
    if alpha is None:
        alpha = _load_keeper_config().get("rehearsal_alpha")
    if alpha <= 0:
        return False
    try:
        cur = max(0.0, min(1.0, float(mem.get("importance", 0.5))))
    except (TypeError, ValueError):
        cur = 0.5
        # recency 衰减：越久没命中，这次复述的加权越小（避免历史陈旧项被反复轻触就饱和）
    try:
        last = mem.get("accessed") or mem.get("created")
        d = max(0, (datetime.date.today() - _parse_date(last)).days)
    except Exception:
        d = 0
    recency = math.exp(-d / 30.0)
    new = min(1.0, cur + alpha * recency)
    if new > cur + 1e-9:
        mem["importance"] = round(new, 4)
        return True
    return False

def touch(root, mid, scope=None, project=None):
    """显式记录「该记忆被使用」：刷新 accessed + 记录访问证据（scope/project 上下文）。
    与 recall 解耦——recall 默认不再隐式写盘（避免读操作有写副作用 + 千条库性能骤降）。
    C3 修复：补 mtime 乐观守卫，防止并发修改被静默覆盖。
    （P3）：命中时附加复述加权（importance 小步上升）。"""
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)  # C3 修复：读取 mtime 用于乐观守卫
    mem["accessed"] = today()
    # 5.0/A1 续修：频次只写**权威热源** `recall_counts.json`，不再自增记忆文件字段。
    # `touch` 与 `recall` 命中在语义上都是「这条被用了一次」，必须计入**同一个计数器**；
    # 写文件字段的旧做法正是「双写脱节」病根的一部分
    # （文件 `access_count` 在真库 204/211 条恒 0，而热源有真值 → 下游治理链全读错）。
    _bump_recall_counts(root, [mid])
    _apply_rehearsal_weight(mem)
    af = mem.setdefault("accessed_from", [])
    ctx = {"date": today()}
    if project:
        ctx["project"] = project
        ctx["scope"] = "project"
    elif scope:
        ctx["scope"] = scope
    af.append(ctx)
    if len(af) > 12:
        del af[:len(af) - 12]
    _save_mem(root, mid, mem, expect_mtime=mtime)  # C3 修复：传入 mtime 守卫
    _recall_cache_clear()  # D-new-1：recency 变化影响召回排序，失效进程内缓存
    return mid

def feedback(root, mid, signal, weight=1.0, discount=1.0):
    """显式正负反馈（自主校准核心）：good 升置信、bad 降置信，走 Beta 后验。
    返回最新 confidence 与 alpha/beta，供调用方观察校准效果。
    C3 修复：补 mtime 乐观守卫，防止并发修改被静默覆盖。
    v3.7.0 防自反馈循环：每会话内 feedback 调用超过 `KEEPER_FEEDBACK_SESSION_CAP`
    （默认 3 次）时直接返回 {limit_reached: True}，不再校准；目的是切断
    "模型自我确认 → 触发 feedback → 再确认" 的开放回路。可调环境变量关掉或放宽。
    """
    if signal not in ("good", "bad"):
        raise ValueError("signal 必须是 good|bad")
        # ：会话内 feedback 上限（防"模型反复自确认"循环）。
    _cap = _load_keeper_config(root)["feedback_session_cap"]
    if _cap <= 0:
        # 0=全关（防自反馈循环）：直接跳过校准，不读写计数、不写盘。
        return {"ok": True, "limit_reached": True, "session_cap": _cap,
                "id": mid, "signal": signal,
                "msg": ("feedback 已通过 env `KEEPER_FEEDBACK_SESSION_CAP=0` 关闭"
                        "（防『模型自我反复确认』循环）")}
    try:
        _cnt_path = os.path.join(root, ".feedback_count.json")
        try:
            with open(_cnt_path, "r", encoding="utf-8") as _f:
                _cd = json.load(_f) or {}
        except Exception:
            _cd = {}
        _now = today()
        if _cd.get("date") != _now:
            _cd = {"date": _now, "count": 0}
        _used = int(_cd.get("count", 0))
        if _used >= _cap:
            return {"ok": True, "limit_reached": True, "session_cap": _cap,
                    "used": _used, "id": mid, "signal": signal,
                    "msg": ("今日 feedback 已达上限 %d/%d 次（按日历日累计、跨进程共享，"
                            "次日 0 点自动重置），本次跳过校准以避免"
                            "『模型自我反复确认』循环。如需放宽/关闭：设 env "
                            "`KEEPER_FEEDBACK_SESSION_CAP=N`（0=全关防循环，正数=每日上限次数）"
                            % (_used, _cap))}
        _cd["count"] = int(_cd.get("count", 0)) + 1
        try:
            _tmp = _cnt_path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as _f:
                json.dump(_cd, _f, ensure_ascii=False)
            os.replace(_tmp, _cnt_path)
        except Exception:
            pass
    except Exception:
        pass
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)  # C3 修复：读取 mtime
    _apply_signal(mem, signal, weight=weight, discount=discount)
    # ：信念强度 + 召回效用 + 错误知识遗忘（让系统从"被否定"中真正学习）
    _bs = float(mem.get("belief_strength", 1.0))
    _us = float(mem.get("utility_score", 0.0))
    if signal == "good":
        _bs = min(1.0, _bs + (1.0 - _bs) * 0.1 * weight)
        _us = _us + weight
    else:  # bad：信念更快衰减，效用扣减
        _bs = max(0.0, _bs - _bs * 0.2 * weight)
        _us = _us - weight
        _BELIEF_FLOOR = 0.2
        if _bs < _BELIEF_FLOOR and not mem.get("erroneous"):
            # 错误知识遗忘：被反复否定且信念跌破阈值 → 判错并归档，停止召回
            mem["erroneous"] = True
            if mem.get("status") == "active":
                mem["status"] = "archived"
                mem["archived_at"] = today()
            mem.setdefault("accessed_from", []).append(
                {"action": "error_forgotten", "date": today(),
                 "reason": "belief_strength=%.3f < %.2f 且 bad 反馈" % (_bs, _BELIEF_FLOOR)})
            try:
                _data = load_index(root)
                for _e in _data.get("entries", []):
                    if _e.get("id") == mid:
                        _e["status"] = "archived"
                        _e["erroneous"] = True
                save_index(root, _data)
            except Exception as _err:
                import sys as _sys
                _sys.stderr.write("[⚠ feedback] 索引同步失败（erroneous/archived 状态可能滞后；doctor --fix 可修复）：%s\n" % _err)
                mark_dirty_safe(root, mid)
    mem["belief_strength"] = round(_bs, 4)
    mem["utility_score"] = round(_us, 4)
    mem.setdefault("accessed_from", [])
    mem["accessed_from"].append({"action": "feedback_%s" % signal, "date": today(),
                                 "weight": weight})
    if len(mem["accessed_from"]) > 12:
        del mem["accessed_from"][:len(mem["accessed_from"]) - 12]
    _save_mem(root, mid, mem, expect_mtime=mtime)  # C3 修复：传入 mtime 守卫
    _recall_cache_clear()  # D-new-1：importance 变化影响召回排序，失效进程内缓存
    return {"ok": True, "id": mid, "signal": signal,
            "confidence": mem.get("confidence"),
            "conf_alpha": mem.get("conf_alpha"), "conf_beta": mem.get("conf_beta"),
            "importance": mem.get("importance"),
            "belief_strength": mem.get("belief_strength"),
            "utility_score": mem.get("utility_score"),
            "erroneous": mem.get("erroneous"),
            "status": mem.get("status")}  # v4.6.13：回显信念强度/效用/判错状态

def _to_float(v):
    """尽力把 attrs 值转 float；失败返回 None。"""
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        import re as _re
        _m = _re.search(r"-?\d+(?:\.\d+)?", s)
        return float(_m.group(0)) if _m else None
    except Exception:
        return None

        # · 投资校验默认 sql_map 模板（bootstrap 用）：用户据此按自己的 DuckDB schema
        # 填充真实 SQL，使 verify_investment 从『条件缺失静默跳过』转为『明确 needs_setup + 引导』。
        # 键 = 记忆 attrs 中的 metric 名；值 = 在 DuckDB 中复算该指标的 SQL（须返回单值）。
_DEFAULT_INVESTMENT_SQL_MAP = {
# "close": "SELECT close FROM market_daily WHERE symbol = '<代码>' AND date = '<YYYY-MM-DD>'",
# "pe_ttm": "SELECT pe_ttm FROM valuation WHERE symbol = '<代码>' ORDER BY date DESC LIMIT 1",
# "pb": "SELECT pb FROM valuation WHERE symbol = '<代码>' ORDER BY date DESC LIMIT 1",
# "roe": "SELECT roe FROM fundamentals WHERE symbol = '<代码>' AND fiscal_year = <年>",
}

def verify_investment(root, duckdb_path=None, sql_map=None, dry_run=True, max_items=50):
    """ · 投资记忆 DuckDB 自动校验（关闭『只记不验』缺口，且消除静默 skip）。

    对 domain/area/category 属投资域、且 verified 非 true、且带数值 attrs 的记忆，
    若提供 DuckDB 路径 + metric→SQL 映射（sql_map），从数据库复算数值并与存储值比对
    （2% 容差），标记 verified true/false + verified_at + verified_source；复算不一致
    则下调 belief_strength（提示可能过时，不自动判错，留人工）。

    与 v4.6.13 的关键差异（相位 E）：**不再静默 skipped**。明确区分三种结局：
    · verified_true / verified_false —— 已复算并落 verdict；
    · skipped —— 已具备 DB+sql_map 但本记忆的指标无可用 SQL（属正常『无需复算』）；
    · needs_setup —— 记忆本应校验，但缺 DuckDB 或 sql_map，**条件缺失未校验**（此前被静默吞掉）。
    当存在 needs_setup 时，out 附带 default_sql_map_template + setup_hint 引导用户 bootstrap，
    并统计 needs_setup 总数，使 caller 能据此告警『有待校验记忆因环境未就绪而 pending』。
    fail-open 仍成立：任何异常不阻断，仅记录 error。
    """
    out = {"ok": True, "dry_run": bool(dry_run), "checked": 0, "verified_true": 0,
           "verified_false": 0, "skipped": 0, "needs_setup": 0,
           "needs_setup_items": [], "setup_ready": False,
           "target": duckdb_path or "",
           "default_sql_map_template": dict(_DEFAULT_INVESTMENT_SQL_MAP),
           "setup_hint": ""}
    try:
        _inv_keys = ("invest", "投资", "stock", "股票", "fund", "基金", "portfolio",
                     "选股", "回测", "估值")
        mems = _all_mems(root)
        targets = []
        for m in mems.values():
            if m.get("status") != "active" or m.get("verified") is True:
                continue
            _blob = " ".join([str(m.get("domain") or ""), str(m.get("area") or ""),
                              str(m.get("category") or ""), str(m.get("subdomain") or "")])
            if not any(k in _blob.lower() for k in _inv_keys):
                continue
            if not (m.get("attrs") or {}):
                continue
            targets.append(m)
        targets = targets[:max_items]
        out["checked"] = len(targets)
        _con = None
        _have_duckdb = False
        if duckdb_path:
            try:
                import duckdb as _ddb
                _con = _ddb.connect(duckdb_path, read_only=True)
                _have_duckdb = True
            except Exception:
                _have_duckdb = False
                # 就绪判定：DuckDB 可用「且」提供了 sql_map（哪怕为空）。
                # 注意区分「未提供 sql_map」（=None→环境未引导→needs_setup）与「提供了空 sql_map」
                # （={}→环境已就绪，但本记忆指标暂无可用 SQL→走 skipped 分支，而非 needs_setup）。
                # 此前用 bool(sql_map) 会把空 map 误判为未就绪，导致下方「就绪但无 SQL→skipped」
                # 分支对空 map 永远不可达。
        _setup_ready = bool(_have_duckdb and sql_map is not None)
        out["setup_ready"] = _setup_ready
        for m in targets:
            _attrs = m.get("attrs") or {}
            _verdict = None
            _src = None
            if _setup_ready:
                _all_ok = True
                _any_checked = False
                for metric, val in _attrs.items():
                    _sql = sql_map.get(metric)
                    if not _sql:
                        continue
                    try:
                        _r = _con.execute(_sql).fetchone()
                        _db_val = _to_float(_r[0]) if _r else None
                        _store_val = _to_float(val)
                        if _db_val is None or _store_val is None:
                            continue
                        _any_checked = True
                        if abs(_db_val - _store_val) / max(1.0, abs(_store_val)) > 0.02:
                            _all_ok = False
                    except Exception:
                        pass
                if _any_checked:
                    _verdict = _all_ok
                    _src = "duckdb:%s" % duckdb_path
            if _verdict is None:
                # 相位 E：区分结局，消除静默 skip
                if _setup_ready:
                    out["skipped"] += 1  # 已就绪，但本记忆指标无可用 SQL（正常无需复算）
                else:
                    out["needs_setup"] += 1  # 缺 DuckDB / sql_map：本应校验却未校验
                    out["needs_setup_items"].append(
                        {"id": m.get("id"), "metrics": list(_attrs.keys())})
                continue
            if dry_run:
                continue
            m["verified"] = bool(_verdict)
            m["verified_at"] = today()
            m["verified_source"] = _src
            _save_mem(root, m["id"], m)
            if _verdict:
                out["verified_true"] += 1
            else:
                out["verified_false"] += 1
                try:  # 复算不一致：下调信念强度，提示可能过时
                    _bs = float(m.get("belief_strength", 1.0))
                    m["belief_strength"] = round(max(0.0, _bs - 0.3), 4)
                    _save_mem(root, m["id"], m)
                except Exception:
                    pass
        if out["needs_setup"]:
            out["setup_hint"] = (
                "有 %d 条投资记忆待校验但因环境未就绪（缺 DuckDB 路径、sql_map 或 DuckDB 不可用）"
                "而 pending；请提供 duckdb_path 并按 default_sql_map_template 填充 metric→SQL "
                "映射后重跑，或显式置 verified=true 关闭其待校验状态。" % out["needs_setup"])
        if _con is not None:
            try:
                _con.close()
            except Exception:
                pass
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out

def forget(root, mid, reason="", dry_run=False):
    """ · 显式遗忘：标记某记忆为错误并归档（erroneous=True, belief_strength=0），
    停止召回。与 feedback bad 的自动遗忘互补——这是人工主动判错入口。

    P1-6 修复（#forget-dry-run）：补齐 --dry-run 预览，与 delete/archive/reclassify 等
    破坏性操作对齐——否则用户敲 `forget --dry-run` 本想预览，却会真实归档该记忆
    （原实现完全忽略 dry_run，连参数都没有）。dry_run=True 时只回显「将改动」，不写盘、
    不动索引、不清缓存。"""
    out = {"ok": True, "id": mid}
    try:
        mem, fp = _load_mem(root, mid)
        if dry_run:
            # 预览：绝不写盘
            out["dry_run"] = True
            out["current_status"] = mem.get("status")
            out["current_belief_strength"] = mem.get("belief_strength")
            out["current_erroneous"] = mem.get("erroneous")
            out["will_change"] = {
                "erroneous": True,
                "belief_strength": 0.0,
                "status": "archived",
                "action": "forgotten",
                "reason": reason or "manual",
            }
            out["file"] = fp
            return out
        mem["erroneous"] = True
        mem["belief_strength"] = 0.0
        mem["status"] = "archived"
        mem["archived_at"] = today()
        mem.setdefault("accessed_from", []).append(
            {"action": "forgotten", "date": today(), "reason": reason or "manual"})
        _save_mem(root, mid, mem)
        _data = load_index(root)
        for _e in _data.get("entries", []):
            if _e.get("id") == mid:
                _e["status"] = "archived"
                _e["erroneous"] = True
        save_index(root, _data)
        _recall_cache_clear()
        # ：被遗忘的记忆 → 打 dirty，self-heal 据此同步相关 skill/规则层
        try:
            from _self_heal import mark_dirty_safe
            mark_dirty_safe(root, mid)
        except Exception:
            pass
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out

@_with_deposit_lock
def reclassify(root, mid, scope=None, project=None, mem_type=None, scene=None,
              reason="", dry_run=False, yes=False):
    """显式重分类（用户/AI 判定归类错误时调用）：改 scope/project/type/scene，并**强学习**进分类器，
    使后续同标签记忆初判即对齐这条纠正，避免反复误判。
    #19 修复：新增 mem_type 参数——纠正 type 时强学习 tag→type 先验。
    4.5.58 ②：新增 scene 参数——供 reclassify --pending --suggest 的保守建议一键确认应用
    （此前 suggest 只读不写，建议无法落地）。scene 仅写文件+index，不强学习（scene 非分类器轴）。"""
    if scope is not None and scope not in SCOPES:
        raise ValueError("scope 必须是 %s 之一，收到: %s" % (SCOPES, scope))
    if mem_type is not None:
        mem_type = _normalize_type(mem_type)
        if mem_type not in TYPE_CANON:
            raise ValueError("type 必须是 %s 之一" % (TYPE_CANON,))
    mem, fp = _load_mem(root, mid)
    mtime = os.path.getmtime(fp)
    if dry_run:
        return {"dry_run": True, "op": "reclassify", "id": mid,
                "will_change": {"scope": scope, "project": project, "type": mem_type,
                                "scene": scene}, "file": fp}
    if not yes:
        _warn_destructive("reclassify(重分类)", mid, fp,
                          "重分类会改写该文件的 scope/project/type 字段。这是低风险操作，"
                          "但同样会改动磁盘文件；确认无误可加 --yes。")
    if scope is not None:
        mem["scope"] = scope
    if project is not None:
        mem["project"] = project
    if mem_type is not None:
        mem["category"] = mem_type
        mem["type"] = mem_type
    if scene is not None:
        mem["scene"] = scene
        mem["scene_confidence"] = 1.0
        mem["scene_via"] = "explicit"
    mem["scope_confidence"] = 1.0
    mem.setdefault("accessed_from", [])
    mem["accessed_from"].append({"scope": mem.get("scope"), "project": mem.get("project", ""),
                                 "action": "reclassify", "reason": reason, "date": today()})
    if len(mem["accessed_from"]) > 12:
        del mem["accessed_from"][:len(mem["accessed_from"]) - 12]
    mem["updated"] = today()
    _save_mem(root, mid, mem, expect_mtime=mtime)
    data = load_index(root)
    for e in data["entries"]:
        if e.get("id") == mid:
            if scope is not None:
                e["scope"] = scope
            if project is not None:
                e["project"] = project
            if mem_type is not None:
                e["category"] = mem_type
                e["type"] = mem_type
            if scene is not None:
                e["scene"] = scene
                e["scene_confidence"] = 1.0
                e["scene_via"] = "explicit"
    save_index(root, data)
    # 强学习：把这条纠正沉淀进分类器
    model = _clf.load_model(root)
    if scope is not None:
        _clf.learn_explicit(model, mem.get("tags", []), mem.get("category", ""),
                            mem.get("scope"), weight=3)
        # #19 修复：纠正 type 时强学习 tag→type 先验
    if mem_type is not None:
        _clf.learn_type(model, mem.get("tags", []), mem_type, weight=3)
    _clf.save_model(root, model)
    _audit_log(root, "reclassify", mid, {"scope": mem.get("scope"),
                                         "type": mem.get("type")})
    return mid

    # ── ：数据质量队列——列出「缺分类轴标注」的记忆（reclassify --pending）──
    # 背景：历史导入/早期版本写入的记忆常缺 scene/about_axis/domain 标注，而 recall 的
    # 轴过滤只对已标注条目生效（真实库 23 条活跃记忆全部缺至少一轴）。本视图只读，
    # 给出一条「待补标注」清单 + 保守关键词建议（仅命中明确关键词才给建议，避免错分类）。
_SCENE_HINT_KEYWORDS = {
    "debugging": ("debug", "调试", "修复", "bug", "报错", "错误", "排查", "异常", "崩溃"),
    "setup": ("配置", "安装", "初始化", "setup", "install", "配环境", "环境配置"),
    "release": ("发布", "上线", "release", "deploy", "灰度", "生产"),
    "incident": ("故障", "事故", "宕机", "incident", "告警"),
    "research": ("研究", "调研", "分析", "比较", "research", "评估"),
    "learning": ("学习", "教程", "上手", "入门", "learn", "练习"),
    "maintenance": ("维护", "升级", "清理", "迁移", "maintenance"),
    "conversation": ("对话", "沟通", "会议", "讨论", "协商"),
    "general": (),
}
_INV_SCENE_HINTS = {
    "inv:backtest": ("回测", "backtest", "策略验证", "参数优化"),
    "inv:rebalance": ("调仓", "仓位", "再平衡", "rebalance", "资产配置"),
    "inv:premarket": ("盘前", "premarket", "集合竞价"),
    "inv:intraday": ("盘中", "日内", "intraday", "分时"),
    "inv:postmarket": ("盘后", "复盘", "postmarket", "收盘"),
}

def _suggest_scene(mem):
    """极保守的场景建议：先投资关键词（inv: 前缀），再软件场景；未命中返回 None。"""
    text = " ".join([mem.get("summary", ""), mem.get("body", ""),
                     " ".join(mem.get("tags", []) or [])]).lower()
    for scene, kws in _INV_SCENE_HINTS.items():
        if any(k.lower() in text for k in kws):
            return scene
    for scene, kws in _SCENE_HINT_KEYWORDS.items():
        if any(k.lower() in text for k in kws):
            return scene
    return None

def reclassify_pending(root, suggest=False):
    """数据质量队列：列出活跃记忆中缺分类轴标注的条目（只读，不写盘）。

    缺失轴 = scene / about_axis / domain 任一未标注。suggest=True 时对**真正缺
    scene** 的条目给出保守场景建议（命中明确关键词才给，未命中为 None——宁缺勿错；
    已自动分类过 scene 的不重复建议）。返回 {total_active, n_pending, missing_summary,
    pending: [...]}。
    """
    mems = _all_mems(root)
    pending, missing = [], {}
    n_active = 0
    for mid, mem in mems.items():
        if mem.get("status") != "active":
            continue
        n_active += 1
        lack = [ax for ax in ("scene", "about_axis", "domain")
                if not mem.get(ax)]
        # §5.5：兜底域回填（domain:fallback）**不算「已归类」**——仍列进质量队列待人工指定
        # 真域；否则一开开关这些条目就从队列里静默消失（同族：静默滤掉 → 空被当正常态）。
        if "domain" not in lack and any(
                t == "domain:fallback" for t in (mem.get("tags") or [])):
            lack.append("domain")
        if not lack:
            continue
        missing[tuple(lack)] = missing.get(tuple(lack), 0) + 1
        entry = {
            "id": mid, "summary": (mem.get("summary") or "")[:60],
            "missing": lack, "tier": mem.get("tier", "working"),
            "category": mem.get("category", ""),
        }
        if suggest and "scene" in lack:
            entry["suggested_scene"] = _suggest_scene(mem)
        pending.append(entry)
    return {
        "ok": True, "op": "reclassify_pending", "read_only": True,
        "total_active": n_active, "n_pending": len(pending),
        "missing_summary": {("+".join(k)): v for k, v in missing.items()},
        "pending": sorted(pending, key=lambda x: (x["missing"], x["id"])),
        "hint": ("待补标注条目不影响语义召回（仅 --scene/--about-axis/--domain 轴过滤不命中）。"
                 "补标可逐条 `reclassify --id <mid>` 或重新 `deposit`；suggest 建议仅为提示，"
                 "请人工确认后再写。" if pending else "无缺轴记忆，数据质量良好。"),
    }

    # index entry 与记忆文件之间【可比】的内容字段集（doctor 漂移检测/回填共用）。
    # 严格取自 _index_entry_from_mem 的产出字段 —— index entry 是**精简镜像**，
    # 不含 body / importance。 的漂移检测误把这两者纳入签名，导致
    # e.get("body") 恒为 "" 而文件恒有值 → content_mismatch 对每条记忆 100% 全量误报，
    # 且 --fix 会照假漂移把整个记忆 JSON 灌进索引。 校正为仅比对真实存在的字段。
_INDEX_CONTENT_FIELDS = ("summary", "tags", "scope", "project", "status", "tier", "type")

def _index_entry_from_mem(mem, mid, fn, archived, st):
    """从记忆文件重建**完整** index entry（rebuild / 索引修复路径复用）。

    字段集必须与 deposit 写入的 entry 保持一致。原因：recall 的 L0 硬过滤
    （auto_sourced / about_axis / scene / subdomain / attrs）**只读 index entry
    不读盘**，任一字段在重建时丢失，对应轴查询会静默返回 0 命中且不报错。
    历史缺陷：旧 rebuild 只写 9 个基础字段，导致跑一次 rebuild 就把多轴分类
    （scene/subdomain/about_axis）全部打回 None，且 auto_sourced 暂存隔离失效。
    """
    return {
        "id": mid, "category": mem.get("category", ""),
        "summary": mem.get("summary", ""), "tags": mem.get("tags", []),
        "tier": mem.get("tier", "working"),
        "scope": mem.get("scope", "universal"),
        "project": mem.get("project", ""),
        "status": st, "file": ("archive/" + fn) if archived else fn,
    # 数据模型
        "type": mem.get("type", ""),
        "settled": bool(mem.get("settled", False)),
        "thermal": mem.get("thermal", "warm"),
    # 多轴 taxonomy（topic + scene）
        "domain": mem.get("domain"), "subdomain": mem.get("subdomain"),
        "scene": mem.get("scene"),
    # 场景置信度/来源
        "scene_confidence": mem.get("scene_confidence"),
        "scene_via": mem.get("scene_via"),
    # P0（3.9.x）结构化指标（--filter 数值过滤依赖）
        "attrs": mem.get("attrs") or {},
    # 状态机 / 优先级 / 领域
        "state": normalize_state(mem.get("state")),
        "priority": normalize_priority(mem.get("priority")),
        "area": normalize_area(mem.get("area")),
    # （P1/C1）四轴「关于谁」
        "about_axis": normalize_about_axis(mem.get("about_axis")),
    # （P5/B3）staging 隔离开关
        "auto_sourced": bool(mem.get("auto_sourced", False)),
    # 5.0/A3 双时序：镜像到 index entry，供 recall --as-of 在【索引-only 路径】判定可见性。
    # 缺这两个键的后果：invalidate 后回溯查询仍把该条当可见（静默错误结果，不报错）。
    # 与 _deposit.py 的 entry 字段集必须一致（契约对账，见 INDEX_CONTENT_FIELDS 注释）。
        "valid_at": mem.get("valid_at"),
        "invalid_at": mem.get("invalid_at"),
    }

def _prune_id_keyed_json(path, alive, dry_run=False):
    """把 `{mid: 任意值}` 形态的派生文件里不属于 alive 的键删掉；无变化则不写盘。"""
    try:
        if not os.path.exists(path):
            return {"dropped": 0, "kept": 0, "note": "missing"}
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {"dropped": 0, "kept": 0, "note": "unreadable"}
    if not isinstance(d, dict):
        return {"dropped": 0, "kept": 0, "note": "not_dict"}
    dead = [k for k in d.keys() if k not in alive]
    if not dead:
        return {"dropped": 0, "kept": len(d), "note": "clean"}
    for k in dead:
        d.pop(k, None)
    if dry_run:
        return {"dropped": len(dead), "kept": len(d), "dry_run": True}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        return {"dropped": 0, "kept": len(d), "note": "write_failed"}
    return {"dropped": len(dead), "kept": len(d)}


def _prune_list_field(path, field, alive, dry_run=False):
    """把 `{field: [mid, ...]}` 形态（maintenance_dirty）里的死 id 删掉。"""
    try:
        if not os.path.exists(path):
            return {"dropped": 0, "note": "missing"}
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {"dropped": 0, "note": "unreadable"}
    lst = d.get(field) if isinstance(d, dict) else None
    if not isinstance(lst, list):
        return {"dropped": 0, "note": "not_list"}
    kept = [x for x in lst if x in alive]
    dropped = len(lst) - len(kept)
    if not dropped:
        return {"dropped": 0, "kept": len(kept), "note": "clean"}
    if dry_run:
        return {"dropped": dropped, "kept": len(kept), "dry_run": True}
    d[field] = kept
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        return {"dropped": 0, "kept": len(kept), "note": "write_failed"}
    return {"dropped": dropped, "kept": len(kept)}


def _prune_cluster_members(path, alive, dry_run=False):
    """把 `clusters.json` 各簇 ids 里的死 id 删掉（簇本身与质心保留，簇序不变）。"""
    try:
        if not os.path.exists(path):
            return {"dropped": 0, "note": "missing"}
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {"dropped": 0, "note": "unreadable"}
    clusters = d.get("clusters") if isinstance(d, dict) else None
    if not isinstance(clusters, list):
        return {"dropped": 0, "note": "not_list"}
    dropped = 0
    for c in clusters:
        ids = c.get("ids") if isinstance(c, dict) else None
        if isinstance(ids, list):
            kept = [x for x in ids if x in alive]
            if len(kept) != len(ids):
                dropped += len(ids) - len(kept)
                if not dry_run:
                    c["ids"] = kept
    if not dropped:
        return {"dropped": 0, "note": "clean"}
    if dry_run:
        return {"dropped": dropped, "dry_run": True}
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        return {"dropped": 0, "note": "write_failed"}
    return {"dropped": dropped}


def prune_derived(root, alive_ids=None, dry_run=False):
    """🔴 派生文件幽灵键回收（5.0 根治）。

    为什么必须有（2026-09-16 真库实锤）：
      · `route_registry.json` **426 键** vs 真实记忆 **226 条** → 200 个幽灵键
        （会导致 doctor 的「跨层重复/晋升候选」聚合虚胖）；
      · `recall_counts.json` **1014 键** vs 存活 **142** → 872 个幽灵计数，且幽灵计数
        仅 2–7 而存活中位数 99 → 热度统计被整体拉偏；
      · `maintenance_dirty.json` / `clusters.json` 同病。
    根因：这些派生文件都是「按 id 增量写」的，**删除 / 归档路径从不回删其键**，
    而 `rebuild()` 只重建 `index.json` + `index.db`，**完全不碰派生文件**
    → 幽灵键只增不减、永不回收。这是「派生存储缺 GC」这一类问题的统一病根。

    修法：以「当前磁盘真实记忆 id 集合」为唯一口径做差集回收，并接入 `rebuild()` 收尾
    ——只要跑过一次全量重建，派生层就与真源对齐，不必再靠手工脚本清。

    🔴 安全阀：`alive` 为空（索引读失败 / 库空）时**直接返回 skipped**，
    绝不因一次读取异常把派生文件整体清空。
    """
    if alive_ids is None:
        try:
            alive = {e.get("id") for e in load_index(root).get("entries", []) if e.get("id")}
        except Exception:
            return {"skipped": "index_unreadable"}
    else:
        alive = {i for i in alive_ids if i}
    if not alive:
        return {"skipped": "empty_alive_set"}

    rep = {}
    rep["route_registry"] = _prune_id_keyed_json(
        os.path.join(root, "store", "route_registry.json"), alive, dry_run)
    rep["recall_counts"] = _prune_id_keyed_json(
        _recall_counts_path(root), alive, dry_run)
    rep["maintenance_dirty"] = _prune_list_field(
        os.path.join(root, "store", "maintenance_dirty.json"), "dirty_mids", alive, dry_run)
    rep["clusters"] = _prune_cluster_members(
        os.path.join(root, "store", "clusters.json"), alive, dry_run)
    rep["alive"] = len(alive)
    rep["dropped_total"] = sum(int(v.get("dropped", 0) or 0) for v in rep.values()
                               if isinstance(v, dict))
    return rep


@_with_deposit_lock
def rebuild(root, return_report=False):
    _tag_index_reset(root)  # 索引全量重建，作废增量缓存
    md = mem_dir(root)
    ad = archive_dir(root)
    os.makedirs(md, exist_ok=True)
    entries = []
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
                entries.append(_index_entry_from_mem(mem, mid, fn, archived, st))
            except (json.JSONDecodeError, UnicodeDecodeError):
                entries.append({
                    "id": fn[:-5], "category": "", "summary": "[unparseable]",
                    "tags": [], "tier": "working", "status": "corrupt", "file": fn,
                })
    # v4.9.2：磁盘文件是事实源 → full_replace=True 先清表，
    # 否则 scoped DELETE 只删这 156 个 id，索引里文件已不存在的僵尸条目会永久残留。
    save_index(root, {"version": 1, "updated": today(), "entries": entries},
               full_replace=True)
    # 🔴 5.0 根治：派生文件幽灵键回收。此前 rebuild 只重建 index.json/index.db，
    # 完全不碰 route_registry.json / recall_counts.json / maintenance_dirty.json /
    # clusters.json —— 它们的键由各写入路径增量添加、删除/归档路径从不回删，
    # 于是幽灵键只增不减（真库实测：route 426 vs 真实 226、recall_counts 1014 vs 142）。
    # 以「磁盘真实 id 集合」为唯一口径在此统一回收：跑过一次 rebuild 即对齐。
    _pruned = prune_derived(root, [e.get("id") for e in entries])
    _rebuild_index_db(root)  # 落盘索引层：从文件全量回填向量 + 倒排
    _ann_invalidate(root)   # 落盘 ANN 索引随 embeddings 全量重建而失效（下次 recall --ann 自动重建）
    if return_report:
        return {"ok": True, "rebuilt": len(entries), "pruned": _pruned}
    return len(entries)

    # F18 阶段2 批4：持久化层重导出 + 依赖注入（必须在 _graph 加载块之前，且所有外部依赖已定义）。
import importlib.util as _ilu
_persistence_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_persistence.py")
_persistence_spec = _ilu.spec_from_file_location("memory_ops._persistence", _persistence_path)
_persistence_mod = _ilu.module_from_spec(_persistence_spec)
sys.modules["memory_ops._persistence"] = _persistence_mod
# 依赖注入（持久化层调用加密/解密、记忆目录、迁移重建等本文件函数）
_persistence_mod.today = today
_persistence_mod._STATE_LOCK = _STATE_LOCK
_persistence_mod._log_struct = _log_struct
_persistence_mod.CorruptIndexError = CorruptIndexError
_persistence_mod.mem_dir = mem_dir
_persistence_mod.archive_dir = archive_dir
_persistence_mod._index_entry_from_mem = _index_entry_from_mem
_persistence_spec.loader.exec_module(_persistence_mod)
# 重导出（保证所有调用方解析不变）
load_index = _persistence_mod.load_index
save_index = _persistence_mod.save_index
_flush_index_json = _persistence_mod._flush_index_json
check_writable = _persistence_mod.check_writable
_db_path = _persistence_mod._db_path
_db_checkpoint_truncate = _persistence_mod._db_checkpoint_truncate
_index_db_ensure = _persistence_mod._index_db_ensure
_MIGRATING_ROOTS = _persistence_mod._MIGRATING_ROOTS
_migrate_index_multiaxis = _persistence_mod._migrate_index_multiaxis
_load_index_json_only = _persistence_mod._load_index_json_only
_SCHEMA_INITIALIZED = _persistence_mod._SCHEMA_INITIALIZED
_DB_CACHE = _persistence_mod._DB_CACHE
_ConnProxy = _persistence_mod._ConnProxy
_db_close_all = _persistence_mod._db_close_all
_db_conn = _persistence_mod._db_conn
_db_upsert_entries = _persistence_mod._db_upsert_entries
_db_load_entries_full = _persistence_mod._db_load_entries_full
_SAVE_INDEX_SQLITE_FAIL_COUNT = _persistence_mod._SAVE_INDEX_SQLITE_FAIL_COUNT

import importlib.util as _ilu

# 5.0.0：旧加密库 fail-closed 守卫（memory_ops/_legacy.py）。
# 与 _crypto.py 无关：这里**不含任何加解密能力**，只在检测到 4.9.25 加密库特征时拒绝
# 按明文读写，把「静默乱码」换成「响亮拒绝 + 可操作指引」。须在 _core 加载块之前装载，
# 以便向 _core 注入守卫函数（_core 内四个读写原语依赖它）。
_legacy_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_legacy.py")
_legacy_spec = _ilu.spec_from_file_location("memory_ops._legacy", _legacy_path)
_legacy_mod = _ilu.module_from_spec(_legacy_spec)
sys.modules["memory_ops._legacy"] = _legacy_mod
_legacy_spec.loader.exec_module(_legacy_mod)
LegacyEncryptedStoreError = _legacy_mod.LegacyEncryptedStoreError
assert_not_legacy_encrypted = _legacy_mod.assert_not_legacy_encrypted
raise_if_legacy_ciphertext = _legacy_mod.raise_if_legacy_ciphertext
legacy_store_markers = _legacy_mod.legacy_store_markers
looks_like_legacy_ciphertext = _legacy_mod.looks_like_legacy_ciphertext
looks_like_fernet_token = _legacy_mod.looks_like_fernet_token
# _persistence 加载块在前、且走**逐个注入**（非 batch update），故此处显式补注；
# _core / _graph / _dsl 等后续模块由其各自注入行或 _SUBMODULES 统一注入循环覆盖。
_persistence_mod.assert_not_legacy_encrypted = _legacy_mod.assert_not_legacy_encrypted
_persistence_mod.looks_like_legacy_ciphertext = _legacy_mod.looks_like_legacy_ciphertext

# F18 阶段2 批5(部分)：内存文件 IO + 缓存子系统重导出 + 依赖注入（须在 _graph 加载块之前）。
_core_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_core.py")
_core_spec = _ilu.spec_from_file_location("memory_ops._core", _core_path)
_core_mod = _ilu.module_from_spec(_core_spec)
sys.modules["memory_ops._core"] = _core_mod
# 依赖注入（IO 子系统调用路径解析/加解密/损坏隔离/缓存失效等本文件函数）
_core_mod._assert_safe_mid = _assert_safe_mid
_core_mod.assert_not_legacy_encrypted = _legacy_mod.assert_not_legacy_encrypted
_core_mod.raise_if_legacy_ciphertext = _legacy_mod.raise_if_legacy_ciphertext
_core_mod._resolve_path = _resolve_path
_core_mod.MemoryConflictError = MemoryConflictError
_core_mod.mem_dir = mem_dir
_core_mod.archive_dir = archive_dir
_core_mod._MTIME_CACHE = _MTIME_CACHE
_core_mod._RESOLVE_PATH_CACHE = _RESOLVE_PATH_CACHE
_core_mod._MTIME_TTL = _MTIME_TTL
_core_spec.loader.exec_module(_core_mod)
# 重导出（保证所有调用方解析不变）
_load_mem = _core_mod._load_mem
_save_mem = _core_mod._save_mem
_all_mems = _core_mod._all_mems
_MEM_CACHE = _core_mod._MEM_CACHE
_cache_key = _core_mod._cache_key
_mem_cache_get = _core_mod._mem_cache_get
_mem_cache_put = _core_mod._mem_cache_put

# F18 阶段2：关系管理（link / 成环检测 / 关系枚举）独立为 memory_ops/_graph.py
# 原整簇逻辑（L6822-L6921：_reaches + _LINK_ALLOWED/_REL_TYPES + link），零行为变化。
# 该簇依赖持久化层（_load_mem/_save_mem/load_index/save_index/_db_conn 等），故采用
# 「按文件绝对路径加载 + 依赖注入」而非相对导入，兼容 regression 以
# spec_from_file_location("mo", __init__.py) 独立加载本文件的场景（此时无 memory_ops 包）。
import importlib.util as _ilu
_graph_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_graph.py")
_graph_spec = _ilu.spec_from_file_location("memory_ops._graph", _graph_file)
_graph_mod = _ilu.module_from_spec(_graph_spec)
sys.modules["memory_ops._graph"] = _graph_mod
# 注入依赖（_graph 不 import 包，避免独立加载时 ModuleNotFoundError）
_graph_mod._with_deposit_lock = _with_deposit_lock
_graph_mod._load_mem = _load_mem
_graph_mod._save_mem = _save_mem
_graph_mod.today = today
_graph_mod._warn_destructive = _warn_destructive
_graph_mod.load_index = load_index
_graph_mod.save_index = save_index
_graph_mod._db_conn = _db_conn
_graph_mod._db_upsert_entries = _db_upsert_entries
_graph_mod._flush_index_json = _flush_index_json
_graph_mod._log_struct = _log_struct
_graph_spec.loader.exec_module(_graph_mod)
link = _graph_mod.link
_reaches = _graph_mod._reaches
_REL_TYPES = _graph_mod._REL_TYPES
_LINK_ALLOWED = _graph_mod._LINK_ALLOWED

@_with_deposit_lock
def _mark_recalled(root, mid):
    """回收豁免：记录归档记忆最近一次被深度召回的日期，使其免于被回收误删。"""
    if not mid:
        return
    try:
        m, _ = _load_mem(root, mid)
        if m.get("status") != "archived":
            return
        if m.get("last_recalled") == today():
            return
        m["last_recalled"] = today()
        _save_mem(root, mid, m)
    except Exception:
        pass

        # 向后兼容别名 前文档称 reclaim；现语义改为「归档+IMA镜像」，不再删除）

def _has_contradiction_signal(text_a, text_b):
    """#13 修复：检测两条记忆是否含对立信号（一个说做、一个说不做）。

    用于区分「同主题不同做法的矛盾」与「同主题的补充/重复」。
    返回 True 如果一条含正向标记、另一条含反向标记。"""
    la = (text_a or "").lower()
    lb = (text_b or "").lower()
    a_pos = any(m in la for m in _OPPOSITE_MARKERS["pos"])
    a_neg = any(m in la for m in _OPPOSITE_MARKERS["neg"])
    b_pos = any(m in lb for m in _OPPOSITE_MARKERS["pos"])
    b_neg = any(m in lb for m in _OPPOSITE_MARKERS["neg"])
    # 一条正向 + 另一条反向 → 疑似矛盾
    return (a_pos and b_neg) or (a_neg and b_pos)

    # ─────────────────────────────────────────────────────────────────────────────
    # Beta 置信校准内核（自主进化核心）：confidence 改为 Beta 后验
    # confidence = alpha / (alpha + beta)
    # - 存量记忆缺 alpha/beta 时按当前 confidence 反推（K=6 先验质量），向后兼容；
    # - good 信号 → alpha+，bad 信号 → beta+（带时间折扣），证据累积、自然饱和；
    # - 被反复验证→趋近 1，被推翻→趋近 0。替代原 +0.05 / *0.5 阶梯式粗暴校准。
    # #15 修复：per-type 差异化先验——不同 type 的记忆可信度基线不同：
    # PREF（用户偏好）→ 高基线（用户明确表态）、FACT（客观事实）→ 较高、
    # BP/WF/PF（经验/流程/坑）→ 中等、DOC（文档摘要）→ 低（中性待证）。
    # 格式：{type: (K, base_confidence)}，K=先验质量（越大越难偏移），base_conf=初始置信度。
_TYPE_BETA_PRIOR = {
    "PREF": (8.0, 0.90),
    "FACT": (8.0, 0.85),
    "BP":   (6.0, 0.70),
    "WF":   (6.0, 0.70),
    "PF":   (6.0, 0.75),
    "DOC":  (4.0, 0.50),
}

# ─────────────────────────────────────────────────────────────────────────────

def _ensure_beta(mem):
    """为 Beta 校准准备字段：存量记忆若缺 conf_alpha/conf_beta，按当前 confidence 反推。
    #15 修复：按 type 使用差异化先验——FACT/PREF 起点更高（更可信），
    DOC 起点更低（中性待证），BP/WF/PF 居中。无 type 时回退 K=6.0。"""
    if "conf_alpha" not in mem or "conf_beta" not in mem:
        c = float(mem.get("confidence", 1.0))
        c = min(max(c, 0.01), 0.99)
        _t = _normalize_type(mem.get("category") or mem.get("type") or "")
        _prior = _TYPE_BETA_PRIOR.get(_t, (6.0, 0.7))
        K, base_conf = _prior
        # 若记忆已有显式 confidence，以它为准；否则用 type 先验基线
        _c = c if mem.get("confidence") is not None else base_conf
        mem["conf_alpha"] = round(_c * K, 4)
        mem["conf_beta"] = round((1.0 - _c) * K, 4)
    return mem

def _recompute_conf(mem):
    a = mem.get("conf_alpha", 6.0)
    b = mem.get("conf_beta", 0.0)
    tot = a + b
    mem["confidence"] = round(a / tot, 4) if tot > 0 else 1.0
    return mem

def _apply_signal(mem, signal, weight=1.0, discount=1.0):
    """正负反馈：good→alpha+，bad→beta+（时间折扣）。重算 confidence 并记审计。
    #20 修复：bad 信号同时降低 importance——此前 bad 只降置信度不降重要度，
    导致「反复被用户标记 bad 的记忆」仍因高 importance 占据热配额/优先召回。"""
    _ensure_beta(mem)
    w = max(0.0, float(weight)) * max(0.0, float(discount))
    if signal == "good":
        mem["conf_alpha"] = round(mem.get("conf_alpha", 6.0) + w, 4)
    elif signal == "bad":
        mem["conf_beta"] = round(mem.get("conf_beta", 0.0) + w, 4)
        # #20：bad 信号降低 importance（与 recall touch 的 +IMPORTANCE_USE_DELTA 对称）
        _old_imp = float(mem.get("importance", 0.5) or 0.5)
        _new_imp = max(IMPORTANCE_DECAY_FLOOR, _old_imp - IMPORTANCE_USE_DELTA * w)
        mem["importance"] = round(_new_imp, 4)
    _recompute_conf(mem)
    return mem

    # ─────────────────────────────────────────────────────────────────────────────
    # #8 可选 LLM 自进化（安全版）：默认关闭、用户可选开启；内容冻结（只出建议、
    # 绝不改写记忆），本地 LLM 优先（记忆不出本机）。纯 stdlib urllib 调 OpenAI
    # 兼容端点，零新增第三方依赖；未配置/不可达则静默回退规则 reflect。
    # ─────────────────────────────────────────────────────────────────────────────
def _llm_config_path(root):
    return os.path.join(root, "config.json")

def _load_llm_config(root):
    """读取 config.json 的 llm 块；缺失或异常返回安全默认（enabled=False）。

    P0 升级（4.5.36）：支持环境变量覆盖，使 Agent 能直接注入「自己正在用的模型」——
    零用户配置即可复用云端/本地端点。覆盖变量（任一设置即生效，优先级高于 config.json）：
    KEEPER_LLM_ENABLED   = "1" 开启
    KEEPER_LLM_BACKEND   = "ollama" | "openai"
    KEEPER_LLM_BASE_URL  = OpenAI 兼容端点
    KEEPER_LLM_MODEL     = 模型名
    KEEPER_LLM_API_KEY   = 明文 key（或用 KEEPER_LLM_API_KEY_ENV 指定 env 名）
    KEEPER_LLM_API_KEY_ENV = 存放 key 的 env 变量名
    """
    default = {"enabled": False, "backend": "ollama",
               "base_url": "http://localhost:11434/v1",
               "model": "qwen2.5:7b", "api_key_env": "",
               "max_suggestions": 30, "batch_size": 20, "temperature": 0.2,
               "auto_apply_safe": True}  # v3.1.4 P0-3：安全子集(link/note)自动应用
    p = _llm_config_path(root)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            ll = cfg.get("llm", {})
            if isinstance(ll, dict):
                merged = dict(default)
                merged.update(ll)
                base = merged
            else:
                base = dict(default)
        except Exception:
            base = dict(default)
    else:
        base = dict(default)
        # P0 环境变量覆盖（Agent 注入「正在用的模型」用）
    env_enabled = os.environ.get("KEEPER_LLM_ENABLED")
    env_backend = os.environ.get("KEEPER_LLM_BACKEND")
    env_url = os.environ.get("KEEPER_LLM_BASE_URL")
    env_model = os.environ.get("KEEPER_LLM_MODEL")
    env_key = os.environ.get("KEEPER_LLM_API_KEY")
    env_key_env = os.environ.get("KEEPER_LLM_API_KEY_ENV")
    if any([env_enabled, env_backend, env_url, env_model, env_key, env_key_env]):
        if env_enabled in ("1", "true", "True"):
            base["enabled"] = True
        if env_backend:
            base["backend"] = env_backend
        if env_url:
            base["base_url"] = env_url
        if env_model:
            base["model"] = env_model
        if env_key_env:
            base["api_key_env"] = env_key_env
        elif env_key:
            # 明文 key 临时写入进程内 api_key_env 指向的变量（不落 config）
            os.environ["KEEPER_LLM_INJECTED_KEY"] = env_key
            base["api_key_env"] = "KEEPER_LLM_INJECTED_KEY"
        base["_env_overridden"] = True
    return base

def _parse_llm_json_array(text):
    """从 LLM 输出尽力提取 JSON 数组，容忍 ```代码块包裹或前后杂文字。
    仅保留含 action+source_id 的合法建议。"""
    if not text:
        return []
    s = text.strip()
    if "```" in s:
        import re as _re
        m = _re.search(r"```(?:json)?\s*(.*?)```", s, _re.DOTALL)
        if m:
            s = m.group(1).strip()
    a = s.find("[")
    b = s.rfind("]")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    try:
        arr = json.loads(s)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    ok = []
    for x in arr:
        if isinstance(x, dict) and x.get("action") and x.get("source_id"):
            ok.append({"action": x.get("action"), "source_id": x.get("source_id"),
                       "target_id": x.get("target_id"), "reason": x.get("reason", "")})
    return ok

def _parse_llm_json_arr(text):
    """ 从 LLM 输出尽力提取 JSON 数组（容忍 ```包裹/前后杂文字），返回 dict 元素列表。
    与 _parse_llm_json_array 不同：不强制 action/source_id（用于 L3 终判的 {id,keep,score} 数组）。"""
    if not text:
        return []
    s = text.strip()
    if "```" in s:
        import re as _re
        m = _re.search(r"```(?:json)?\s*(.*?)```", s, _re.DOTALL)
        if m:
            s = m.group(1).strip()
    a = s.find("[")
    b = s.rfind("]")
    if a >= 0 and b > a:
        s = s[a:b + 1]
        try:
            arr = json.loads(s)
        except Exception:
            return []
        return [x for x in arr if isinstance(x, dict)] if isinstance(arr, list) else []
    return []

def _parse_llm_json_obj(text):
    """ 从 LLM 输出尽力提取首个 JSON 对象（容忍 ```包裹/前后杂文字）。失败返回 {}。
    与 _parse_llm_json_array 互补：路由/L3/质检返回的是单对象而非数组。"""
    if not text:
        return {}
    s = text.strip()
    if "```" in s:
        import re as _re
        m = _re.search(r"```(?:json)?\s*(.*?)```", s, _re.DOTALL)
        if m:
            s = m.group(1).strip()
    a = s.find("{")
    b = s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}

def _llm_chat(cfg, system, user, temperature=None, max_tokens=None):
    """ 通用 LLM 聊天调用（复用 #8 通道：纯 stdlib urllib，OpenAI 兼容端点，零新增依赖）。
    返回模型输出文本字符串。不可达/配置缺失/异常一律向上抛 RuntimeError，由调用方决定降级。
    cfg 来自 _load_llm_config(root)。"""
    import urllib.request
    backend = cfg.get("backend", "ollama")
    base_url = cfg.get("base_url") or ("http://localhost:11434/v1" if backend == "ollama" else "")
    model = cfg.get("model") or ("qwen2.5:7b" if backend == "ollama" else "gpt-4o-mini")
    if not base_url:
        raise RuntimeError("LLM base_url 未配置（config.json llm.base_url 为空）")
    api_key = os.environ.get(cfg.get("api_key_env", ""), "") if cfg.get("api_key_env") else ""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    payload = {"model": model,
               "temperature": float(temperature if temperature is not None else cfg.get("temperature", 0.2)),
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "stream": False}
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]

def _resolve_llm(root, llm):
    """ 把 llm 参数归一为 (callable_or_None, cfg)。
    - False    → (None, cfg) 强制不用
    - True     → (configured_chat, cfg) 强制用配置 LLM（不可达抛错由上层降级）
    - None     → (configured_chat if enabled else None, cfg)
    - callable → (llm, cfg) 注入（测试/agent 自带 chat）
    """
    cfg = _load_llm_config(root)
    if llm is False:
        return None, cfg
    if callable(llm):
        return llm, cfg
    enabled = bool(cfg.get("enabled"))
    if llm is True or (llm is None and enabled):
        def _cfg_chat(system, user, temperature=None, max_tokens=None):
            return _llm_chat(cfg, system, user, temperature=temperature, max_tokens=max_tokens)
        return _cfg_chat, cfg
    return None, cfg

    # 改进 P0-3：LLM 建议 auto-apply 安全子集
_SAFE_ACTIONS = {"link", "note"}  # 仅这两种动作自动应用（纯加性、非破坏性）

# ─────────────────────────────────────────────────────────────────────────────
# #9 自主沉积 harvest（让工具"自己学习"）：从会话文本或现有记忆正文抽取学习点，
# 以 seed 态（auto_sourced）存入待观察；被使用则晋升、长期不用则自动归档。
# - LLM 抽取（复用 #8 通道，本地优先、记忆不出本机）质量高；
# - 无 LLM 时回退规则抽取（关键词/模式），零依赖可用。
# - --self 模式只读 body（截断），做跨记忆深层学习（矛盾/合成/抽取），绝不回写 body。
# ─────────────────────────────────────────────────────────────────────────────

# H9 修复：best_practice 抽取负向黑名单（日常动作，非可复用知识）
_BP_NEG_BLACKLIST = ("关灯", "开灯", "吃饭", "睡觉", "起床", "喝水", "吃药", "锁门",
                     "带伞", "倒垃圾", "充电", "关空调", "开窗", "关门", "洗手",
                     "洗澡", "上厕所", "买菜", "取快递", "遛狗", "喂猫", "关电脑",
                     "下班", "上班", "打卡", "接孩子", "做饭", "买饭")
# H9 修复：best_practice 抽取知识/命令共现词（与触发词同句才视为可沉淀经验）
_BP_KNOWLEDGE_WORDS = ("经验", "方法", "流程", "规则", "原则", "固定", "标准", "口径",
                       "规范", "做法", "步骤", "机制", "策略", "纪律", "方案", "用",
                       "做", "写", "运行", "调用", "配置", "部署", "设置", "采用",
                       "必须", "应该", "需要", "优先", "避免", "不要", "禁止", "一律")

# ── 与 WorkBuddy 原生记忆打通（自动读取对方记忆、自学沉淀）─────────────────
_KB_KEYWORDS = ("约定", "规则", "偏好", "习惯", "决策", "原则", "铁律", "必做",
                "禁止", "务必", "always", "never", "建议", "经验", "规范", "惯例",
                "统一", "固定", "口径", "标准", "要求", "流程", "机制", "策略",
                "纪律", "红线", "硬约束", "触发", "习惯", "默认", "长期")

# ── 对话内自主沉淀（无需 WorkBuddy 自动化）──────────────────────────────
def _round_state_path(root):
    return os.path.join(root, "_round_state.json")

def _load_round_state(root):
    p = _round_state_path(root)
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            d = {}
    else:
        d = {}
    d.setdefault("count", 0)
    d.setdefault("last_consolidated", 0)
    # ：默认阈值读 config（converse_threshold，开箱默认 20 轮）；用户显式 --set-threshold 后由该调用改写。
    try:
        _cfg = _load_keeper_config(root)
        d.setdefault("threshold", int(_cfg.get("converse_threshold", 20)))
    except Exception:
        d.setdefault("threshold", 20)
    d.setdefault("threshold_auto", True)  # v3.1.4 P1-4：自适应阈值开关（用户显式设置后变 False）
    d.setdefault("buffer", [])      # 本轮起累积的待沉淀要点（到阈值才真正沉积）
    d.setdefault("updated", today())
    return d

def _save_round_state(root, d):
    d["updated"] = today()
    p = _round_state_path(root)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)

def _rounds_until(round_no, n):
    """距离下一次自动整理还差几轮。"""
    rem = round_no % n
    nxt = (n - rem) % n
    return n if nxt == 0 else nxt

    # ── Phase 3 §8 · 双向 reflect + 超量自整理闭环 ─────────────────────────────
    # 纯加性：在原 reflect 之上包一层 demote/resurrect/self-organize；不动 reflect 本体。
    # R2 修复：CAP_HOT_PER_TYPE / CAP_HOT_GLOBAL 已在 Phase 2 区域统一定义，此处不再重复
RESURRECT_WINDOW_DAYS = 30  # 复活窗口：cold 在此期间被访问 → 回到 warm

def _parse_iso_date(s):
    """容错 ISO 日期解析；失败返 None。"""
    if not s:
        return None
    try:
        from datetime import date
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None

def _days_since(s, now=None):
    """s 距 now 多少天；解析失败返大数（视作久远）。"""
    from datetime import date
    if now is None:
        now = date.today()
    d = _parse_iso_date(s)
    if d is None:
        return 9999
    return max(0, (now - d).days)

    # ── 架构图补齐：Layer2 路由视图 + Layer3 树视图 + 自主晋升/合并 ──

    # ── 能力体检 + 开关顾问 ──
    # 用户问「帮我看看有哪些功能可以开启或关闭」时调用。针对当前记忆库规模与环境，
    # 逐项评估可选功能的开启/关闭/保持/按需建议（含优先级与可执行命令），便于有选择性地开关。

    # ── #6 聚类自标签（纯 Python，零依赖；可选装 sklearn 加速）──
    # 对落盘持久化向量做 k-means，涌现主题簇 → 建议新标签（自我发现知识结构）。
    # 完全离线、可选增强：不装 sklearn 时用内置轻量 k-means，规模适中（数百~数千）即可。

def _load_clusters(root):
    """读取落盘簇（store/clusters.json）：返回 {assign:{id:cid}, centroids:{cid:[float]}, k, generated}。
    文件不存在/损坏返回 None，调用方静默跳过聚类增强（#6→recall 增强的读取端）。"""
    p = os.path.join(root, "store", "clusters.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        assign = {}
        for cl in d.get("clusters", []):
            label = str(cl.get("label", ""))
            try:
                cid = int(label.split("-")[-1])
            except Exception:
                cid = label
            for mid in cl.get("ids", []):
                assign[mid] = cid
        cents = {int(k): v for k, v in d.get("centroids", {}).items()}
        return {"assign": assign, "centroids": cents, "k": d.get("k", 0),
                "generated": d.get("generated")}
    except Exception:
        return None

def init_store(root):
    """首次准备：创建 memories/ 与 memories/archive/ 目录 + 空 index.json。
    幂等：目录/索引已存在则不动。返回根路径。
    让非技术用户也能「跑一条命令就就绪」，无需理解环境变量。"""
    os.makedirs(mem_dir(root), exist_ok=True)
    os.makedirs(archive_dir(root), exist_ok=True)
    os.makedirs(quarantine_dir(root), exist_ok=True)  # P2 · 敏感隔离区
    idx = os.path.join(root, "index.json")
    if not os.path.exists(idx):
        save_index(root, {"version": 1, "updated": today(), "entries": []})
    return root

    # ：命令清单 + 一句话用途，解决"高级功能触发方式多、不看文档不知道"的评测痛点
_COMMAND_CATALOG = [
    ("记", "deposit", "记一条经验（category/summary/body/tags）"),
    ("查", "recall", "按 query/tag/domain 召回记忆"),
    ("改", "overwrite", "修改已有记忆（自动快照版本）"),
    ("纠", "deposit --corrects <id>", "新结论推翻旧结论"),
    ("删", "delete --yes", "真删除（不可逆）；建议先 archive"),
    ("归档", "archive", "软删除，可 unarchive 找回"),
    ("整理", "reflect --auto", "去重/纠错/晋升/归档（不删 active）"),
    ("衰减", "decay --apply", "给长期未用记忆降权沉底"),
    ("体检", "doctor", "索引/文件一致性检查（只读）"),
    ("修复", "doctor --fix", "自动修复索引↔文件不一致"),
    ("报告", "report", "健康摘要、后端状态、盲区"),
    ("审计", "audit", "按库规模推荐该开哪些功能"),
    ("聚类", "cluster --apply", "发现主题簇"),
    ("看板", "dashboard", "生成 store/dashboard.html"),
    ("连边", "link", "建立记忆间关系"),
    ("图谱", "graph --build", "自动推断 supports/refutes/is_a/part_of 关系边"),
    ("图谱", "graph --clean", "清理指向已删除记忆的悬空关系引用"),
    ("图谱", "graph --rebuild", "清空图衍生边并重算（干净重算，消除历史 noise 边）"),
    ("蒸馏", "distill --review", "把同域同型密集簇提炼成 principle 原则（离线预览候选）"),
    ("画像", "profile", "离线推断用户擅长/薄弱/当前重心画像"),
    ("晋升", "promote --tier core", "把重要记忆升层"),
    ("备份", "backup", "导出整库 ZIP（含完整性 manifest，可携带可校验）"),
    ("恢复", "restore <zip> --yes", "从 ZIP 恢复（自动校验完整性；--verify 仅校验）"),
    ("版本", "versions --id <id>", "看某记忆历史版本"),
    ("回滚", "rollback --id <id> --to-version N --yes", "恢复到某版本"),
    ("初始化", "init", "建库；加 --download-models 预装语义模型"),
    ("导出", "export --format md", "导出 Markdown / JSONL（跨工具可移植）"),
    ("萃取", "extract-skill", "把高频/已确认经验萃取成可复用 skill 脚手架（SKILL.md+refs+hooks）"),
    ("上手", "quickstart", "极简上手指引（三句话触发 + 新能力一句话触发）"),
    ("调试", "explain <id>", "分解单条记忆的排序/召回 why 信号（只读）"),
    ("分布", "stats", "召回热/温/冷分布 + Top 高频记忆（只读）"),
    ("撤销", "reflect --undo", "反向还原 --auto 自动重分类（dry-run 不落盘）"),
    ("增量", "decay --apply --incremental", "大库仅重算近期访问记忆（冷记忆不变）"),
    ("自调度", "schedule_self_heal --cron", "导出 systemd/cron 片段（脱离 WB 低频自愈）"),
    ("批量导入", "import --file <路径>", "JSONL/JSON/CSV/MD 批量灌入（复用 deposit 全流程）"),
    ("经验变 skill", "extract-skill --min-count 3 --out-dir my_skill", "高频经验→可复用 skill 脚手架（再经 skill-creator 打磨）"),
    ("性能基准", "benchmark --n 200", "测写入吞吐 + recall p50/p95 时延（--ann 走加速）"),
    ("MCP 服务", "mcp", "暴露为标准 MCP 服务（stdio，供 Claude/Cursor 连）"),
    ("发布核对", "release-audit", "对账 CHANGELOG 版本账 ↔ 平台真实发布版本（防多机「双主」）"),
    ("命令清单", "commands", "列出所有命令与常用组合"),
# ：智能进化 + 与 WorkBuddy 互补协同
    ("进化", "evolve --apply", "自我进化：复发印证→提炼可复用原则（provenance=auto，限期复核）"),
    ("回流", "distill-to-wb --apply", "把 keeper 高层原则蒸馏回写 ~/.workbuddy/MEMORY.md（互补而非镜像）"),
    ("校验", "verify-investment", "投资记忆 DuckDB 复算校验（关闭『只记不验』缺口）"),
    ("遗忘", "forget --id <id>", "显式判错并归档（错误知识遗忘，停止召回）"),
    ("信念", "feedback --id <id> --signal bad --weight N", "负反馈降信念强度，跌破阈值自动判错遗忘"),
]

_COMMAND_COMBOS = [
    ("日常三板斧", "init → deposit → recall"),
    ("每周整理", "decay --apply → reflect --auto → report"),
    ("大库加速", "report 看规模 → cluster --apply → recall --ann"),
    ("怀疑数据坏了", "doctor → doctor --fix → rebuild（仍坏再 rebuild）"),
    ("换说法搜不到", "report 看 embed.backend；若 lexical 则装 fastembed 并 init --download-models"),
    ("脱 WB 自愈", "schedule_self_heal --cron → 落 systemd/cron 片段，每日 reflect、周日矛盾扫描、每月 decay"),
]

# ---------- 钩子自装 · 根治「装完 skill 还要手跑 install_hooks.py」易忘点） ----------
# keeper 钩子文件清单（用于"已注册"精确检测；原 "keeper" in cmd 的判定漏掉了 user_prompt_recall.py 等）
# 注：旧版 bash_error_capture.py 因字段名 bug 且从未注册，自 起停带，
# 并于 复审时彻底删除（见 I13）；故此处不再登记，避免匹配器引用不存在的文件。
_KEEPER_HOOK_FILES = (
    "session_start_keeper_inject.py",
    "user_prompt_recall.py",
    "post_tool_use_error_capture.py",
    "memory_auto_capture.py",
)

# ── op 命令面（单源真相，R2 修复）──────────────────────────────────────────────
# 这是 memory_ops 全部 op 的权威清单。dispatch 的 if/elif 分支与 argparse choices
# 都从这里派生（见 main）。新增 op 必须在此登记 + 加对应 elif 分支；
# 三者（OP_NAMES / dispatch 分支 / argparse choices）一致性由开发实验室的 test_op_consistency.py 守护，
# 该脚本不随 SkillHub 发布包发布（.skillhubignore 排除）。OP_NAMES 为本文件权威清单，新增 op 须在此登记 + 加对应 elif 分支；
# 防止再出现「文档/choices 引用了不存在的命令」的幽灵（如 recall_v30、早期 taxonomy 误判）。
OP_NAMES = (
    "deposit", "recall", "overwrite", "delete", "archive",
    "unarchive", "invalidate", "uninvalidate", "rebuild", "link", "promote", "confirm", "reflect",
    "doctor", "touch", "reclassify", "init", "cluster",
    "token-report", "backup", "restore", "report", "llm-setup", "export", "explain",
    "harvest", "feedback", "converse", "schedule_reflect",
    "schedule_self_heal",
    "rollback", "versions", "dashboard", "audit",
    "decay", "recurrence", "summary-index", "tree-view",
    "export-rules", "hot-rules", "import-rules", "extract-skill", "quickstart",
    "list_quarantine", "review_quarantine", "reclaim",
    "commands",
    "graph", "distill", "profile", "stats", "audit-log", "timeline",
    "import", "benchmark", "mcp",
# 4.9.24：生命周期补口（发布账本核对）
    "release-audit",
# ：智能进化与互补协同新 op
    "evolve", "distill-to-wb", "verify-investment", "forget",
# ：统一自治循环（合并 reflect/evolve/decay/doctor/skill-sync/export-rules 调度）
    "self-heal",
)

# --- auto-loaded submodule: _taxonomy ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_taxonomy_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_taxonomy.py")
_taxonomy_spec = _ilu.spec_from_file_location("memory_ops_taxonomy", _taxonomy_file)
_taxonomy_mod = _ilu.module_from_spec(_taxonomy_spec)
_sys.modules["memory_ops_taxonomy"] = _taxonomy_mod
_taxonomy_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_taxonomy_spec.loader.exec_module(_taxonomy_mod)
_taxonomy_path = _taxonomy_mod._taxonomy_path
default_taxonomy = _taxonomy_mod.default_taxonomy
validate_taxonomy = _taxonomy_mod.validate_taxonomy
load_taxonomy = _taxonomy_mod.load_taxonomy
save_taxonomy = _taxonomy_mod.save_taxonomy
taxonomy_domain_keys = _taxonomy_mod.taxonomy_domain_keys
domain_heat_budget = _taxonomy_mod.domain_heat_budget
domain_retention = _taxonomy_mod.domain_retention
taxonomy_has_budget = _taxonomy_mod.taxonomy_has_budget
taxonomy_budget_map = _taxonomy_mod.taxonomy_budget_map
taxonomy_route = _taxonomy_mod.taxonomy_route
reclassify_by_taxonomy = _taxonomy_mod.reclassify_by_taxonomy

# --- auto-loaded submodule: _scene ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_scene_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_scene.py")
_scene_spec = _ilu.spec_from_file_location("memory_ops_scene", _scene_file)
_scene_mod = _ilu.module_from_spec(_scene_spec)
_sys.modules["memory_ops_scene"] = _scene_mod
_scene_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_scene_spec.loader.exec_module(_scene_mod)
_normalize_scene = _scene_mod._normalize_scene
_classify_scene = _scene_mod._classify_scene
_classify_scene_llm = _scene_mod._classify_scene_llm
classify_scene_v30 = _scene_mod.classify_scene_v30

# --- auto-loaded submodule: _embed ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_embed_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_embed.py")
_embed_spec = _ilu.spec_from_file_location("memory_ops_embed", _embed_file)
_embed_mod = _ilu.module_from_spec(_embed_spec)
_sys.modules["memory_ops_embed"] = _embed_mod
_embed_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_embed_spec.loader.exec_module(_embed_mod)
_emb_backend = _embed_mod._emb_backend
_emb_text_hash = _embed_mod._emb_text_hash
_emb_store_put = _embed_mod._emb_store_put
_emb_store_put_many = _embed_mod._emb_store_put_many
_emb_store_get = _embed_mod._emb_store_get
_emb_store_load_all = _embed_mod._emb_store_load_all
_backend_compatible = _embed_mod._backend_compatible
_emb_store_refresh_backend = _embed_mod._emb_store_refresh_backend
_inv_upsert = _embed_mod._inv_upsert
_inv_delete = _embed_mod._inv_delete
_inv_query = _embed_mod._inv_query
_ann_state_path = _embed_mod._ann_state_path
_ann_hnsw_path = _embed_mod._ann_hnsw_path
_ann_npy_path = _embed_mod._ann_npy_path
_ann_ids_path = _embed_mod._ann_ids_path
_ann_digest = _embed_mod._ann_digest
_ann_invalidate = _embed_mod._ann_invalidate
_ann_try_incremental = _embed_mod._ann_try_incremental
_ann_build_numpy = _embed_mod._ann_build_numpy
_ann_load_numpy = _embed_mod._ann_load_numpy
_ann_candidates = _embed_mod._ann_candidates
_persist_embed_and_inv = _embed_mod._persist_embed_and_inv
_persist_batch = _embed_mod._persist_batch
_ensure_embeddings = _embed_mod._ensure_embeddings
_rebuild_index_db = _embed_mod._rebuild_index_db
_tag_index_reset = _embed_mod._tag_index_reset
_tag_index_get = _embed_mod._tag_index_get
_tag_index_upsert = _embed_mod._tag_index_upsert
_seq_path = _embed_mod._seq_path
_seq_load = _embed_mod._seq_load
_seq_save = _embed_mod._seq_save

# --- auto-loaded submodule: _decay ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_decay_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_decay.py")
_decay_spec = _ilu.spec_from_file_location("memory_ops_decay", _decay_file)
_decay_mod = _ilu.module_from_spec(_decay_spec)
_sys.modules["memory_ops_decay"] = _decay_mod
_decay_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_decay_spec.loader.exec_module(_decay_mod)
compute_thermal = _decay_mod.compute_thermal
_days_since_accessed = _decay_mod._days_since_accessed
_pattern_key = _decay_mod._pattern_key
decay_apply = _decay_mod.decay_apply
recurrence_report = _decay_mod.recurrence_report
_lazy_importance_decay = _decay_mod._lazy_importance_decay
settle_probe = _decay_mod.settle_probe

# --- auto-loaded submodule: _quarantine ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_quarantine_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_quarantine.py")
_quarantine_spec = _ilu.spec_from_file_location("memory_ops_quarantine", _quarantine_file)
_quarantine_mod = _ilu.module_from_spec(_quarantine_spec)
_sys.modules["memory_ops_quarantine"] = _quarantine_mod
_quarantine_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_quarantine_spec.loader.exec_module(_quarantine_mod)
quarantine_dir = _quarantine_mod.quarantine_dir
_corrupt_dir_for = _quarantine_mod._corrupt_dir_for
_quarantine_corrupt_file = _quarantine_mod._quarantine_corrupt_file
_redact_sensitive = _quarantine_mod._redact_sensitive
_quarantine_candidate = _quarantine_mod._quarantine_candidate
list_quarantine = _quarantine_mod.list_quarantine
review_quarantine = _quarantine_mod.review_quarantine

# --- auto-loaded submodule: _recall_cache ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_recall_cache_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_recall_cache.py")
_recall_cache_spec = _ilu.spec_from_file_location("memory_ops_recall_cache", _recall_cache_file)
_recall_cache_mod = _ilu.module_from_spec(_recall_cache_spec)
_sys.modules["memory_ops_recall_cache"] = _recall_cache_mod
_recall_cache_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_recall_cache_spec.loader.exec_module(_recall_cache_mod)
_recall_cache_key = _recall_cache_mod._recall_cache_key
_recall_cache_cfg_sig = _recall_cache_mod._recall_cache_cfg_sig
_recall_cache_clear = _recall_cache_mod._recall_cache_clear
_recall_cache_file = _recall_cache_mod._recall_cache_file
_recall_cache_get = _recall_cache_mod._recall_cache_get
_recall_cache_set = _recall_cache_mod._recall_cache_set
_recall_cache_flush = _recall_cache_mod._recall_cache_flush

# --- auto-loaded submodule: _rerank ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_rerank_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_rerank.py")
_rerank_spec = _ilu.spec_from_file_location("memory_ops_rerank", _rerank_file)
_rerank_mod = _ilu.module_from_spec(_rerank_spec)
_sys.modules["memory_ops_rerank"] = _rerank_mod
_rerank_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_rerank_spec.loader.exec_module(_rerank_mod)
_rerank_apply = _rerank_mod._rerank_apply
_rerank_available = _rerank_mod._rerank_available
_rerank_encoder = _rerank_mod._rerank_encoder

# --- auto-loaded submodule: _versions ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_versions_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_versions.py")
_versions_spec = _ilu.spec_from_file_location("memory_ops_versions", _versions_file)
_versions_mod = _ilu.module_from_spec(_versions_spec)
_sys.modules["memory_ops_versions"] = _versions_mod
_versions_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_versions_spec.loader.exec_module(_versions_mod)
_db_delete_entry = _versions_mod._db_delete_entry
versions_dir = _versions_mod.versions_dir
_snapshot_version = _versions_mod._snapshot_version
_gate_prewrite_snapshot = _versions_mod._gate_prewrite_snapshot
_write_gate_enabled = _versions_mod._write_gate_enabled
timeline = _versions_mod.timeline
_list_versions = _versions_mod._list_versions
versions = _versions_mod.versions
rollback = _versions_mod.rollback
overwrite = _versions_mod.overwrite
delete = _versions_mod.delete

# --- auto-loaded submodule: _hooks ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_hooks_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_hooks.py")
_hooks_spec = _ilu.spec_from_file_location("memory_ops_hooks", _hooks_file)
_hooks_mod = _ilu.module_from_spec(_hooks_spec)
_sys.modules["memory_ops_hooks"] = _hooks_mod
_hooks_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_hooks_spec.loader.exec_module(_hooks_mod)
_keeper_hook_mode = _hooks_mod._keeper_hook_mode
_ensure_hooks = _hooks_mod._ensure_hooks
# 显式重导出：_doctor.py 是零 import 模块，只有在这里重导出的名字才会被注入它的 globals。
_skill_root = _hooks_mod._skill_root
_hooks_stale_reason = _hooks_mod._hooks_stale_reason
_hooks_deploy_dir = _hooks_mod._hooks_deploy_dir

# F18 阶段2 批7：_recall 读路径簇加载 + 全局灌入式依赖注入
# 用扁平模块名 memory_ops_api（无点），不依赖父包注册，兼容 import memory_ops 与
# spec_from_file_location 两种加载方式。
_api_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_api.py")
_api_spec = _ilu.spec_from_file_location("memory_ops_api", _api_file)
_api_mod = _ilu.module_from_spec(_api_spec)
sys.modules["memory_ops_api"] = _api_mod
_api_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_api_spec.loader.exec_module(_api_mod)
export_memories = _api_mod.export_memories
stats = _api_mod.stats
_rank_query = _api_mod._rank_query
recall_multi = _api_mod.recall_multi
recall = _api_mod.recall

# F18 阶段2 批8：_deposit 写路径簇加载 + 全局灌入式依赖注入
# 用扁平模块名 memory_ops_deposit（无点），不依赖父包注册，兼容两种加载方式。
# _with_deposit_lock 等共享装饰器由 __init__ 全局灌入，确保复用同一把锁。
_dep_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_deposit.py")
_dep_spec = _ilu.spec_from_file_location("memory_ops_deposit", _dep_file)
_dep_mod = _ilu.module_from_spec(_dep_spec)
sys.modules["memory_ops_deposit"] = _dep_mod
_dep_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_dep_spec.loader.exec_module(_dep_mod)
deposit = _dep_mod.deposit
_deposit_impl = _dep_mod._deposit_impl
_auto_link_similar = _dep_mod._auto_link_similar
flush_memory_index = _dep_mod.flush_memory_index

# --- auto-loaded submodule: _lifecycle ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_lifecycle_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_lifecycle.py")
_lifecycle_spec = _ilu.spec_from_file_location("memory_ops_lifecycle", _lifecycle_file)
_lifecycle_mod = _ilu.module_from_spec(_lifecycle_spec)
_sys.modules["memory_ops_lifecycle"] = _lifecycle_mod
_lifecycle_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_lifecycle_spec.loader.exec_module(_lifecycle_mod)
_move_to_dir = _lifecycle_mod._move_to_dir
archive = _lifecycle_mod.archive
unarchive = _lifecycle_mod.unarchive
invalidate = _lifecycle_mod.invalidate      # 5.0/A3 双时序软失效
uninvalidate = _lifecycle_mod.uninvalidate  # 5.0/A3 撤销软失效
_reclaim_state_path = _lifecycle_mod._reclaim_state_path
_reclaim_load_state = _lifecycle_mod._reclaim_load_state
_reclaim_save_state = _lifecycle_mod._reclaim_save_state
archive_sweep = _lifecycle_mod.archive_sweep
_archive_mirror_ima = _lifecycle_mod._archive_mirror_ima
_sha2gram = _lifecycle_mod._sha2gram
_topics_overlap = _lifecycle_mod._topics_overlap
archive_review = _lifecycle_mod.archive_review
promote = _lifecycle_mod.promote
confirm = _lifecycle_mod.confirm
reclaim = _lifecycle_mod.archive_sweep

# --- auto-loaded submodule: _reflect ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_reflect_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_reflect.py")
_reflect_spec = _ilu.spec_from_file_location("memory_ops_reflect", _reflect_file)
_reflect_mod = _ilu.module_from_spec(_reflect_spec)
_sys.modules["memory_ops_reflect"] = _reflect_mod
_reflect_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_reflect_spec.loader.exec_module(_reflect_mod)
_dedup_thresholds = _reflect_mod._dedup_thresholds
_classify_type_llm = _reflect_mod._classify_type_llm
_fit_decay_lambda = _reflect_mod._fit_decay_lambda
_write_related_edge = _reflect_mod._write_related_edge
_apply_link_candidates = _reflect_mod._apply_link_candidates
_subjects_overlap = _reflect_mod._subjects_overlap
_recent_access_count = _reflect_mod._recent_access_count
_relevance = _reflect_mod._relevance
_reflect_llm = _reflect_mod._reflect_llm
_persist_llm_suggestions = _reflect_mod._persist_llm_suggestions
_auto_apply_safe_suggestions = _reflect_mod._auto_apply_safe_suggestions
schedule_reflect = _reflect_mod.schedule_reflect
_reflect_impl = _reflect_mod._reflect_impl
reflect = _reflect_mod.reflect
reflect_undo_auto = _reflect_mod.reflect_undo_auto
_reclassify_lowconf_v30 = _reflect_mod._reclassify_lowconf_v30
cross_type_merge_candidates = _reflect_mod.cross_type_merge_candidates
_detect_aar_chains = _reflect_mod._detect_aar_chains
evolve = _reflect_mod.evolve  # v4.6.13：自我进化引擎

# --- auto-loaded submodule: _harvest ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_harvest_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_harvest.py")
_harvest_spec = _ilu.spec_from_file_location("memory_ops_harvest", _harvest_file)
_harvest_mod = _ilu.module_from_spec(_harvest_spec)
_sys.modules["memory_ops_harvest"] = _harvest_mod
_harvest_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_harvest_spec.loader.exec_module(_harvest_mod)
_harvest_llm = _harvest_mod._harvest_llm
_harvest_rule = _harvest_mod._harvest_rule
_find_similar_mem = _harvest_mod._find_similar_mem
_workbuddy_ws_memory_dir = _harvest_mod._workbuddy_ws_memory_dir
_split_md_chunks = _harvest_mod._split_md_chunks
_collect_workbuddy_memory = _harvest_mod._collect_workbuddy_memory
harvest = _harvest_mod.harvest
memory_hook_listen = _harvest_mod.memory_hook_listen
_parse_hhmm = _harvest_mod._parse_hhmm
_stagger_hhmm = _harvest_mod._stagger_hhmm
schedule_self_heal = _harvest_mod.schedule_self_heal
distill_to_wb = _harvest_mod.distill_to_wb  # v4.6.13：keeper→WB 蒸馏回流

# --- auto-loaded submodule: _converse ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_converse_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_converse.py")
_converse_spec = _ilu.spec_from_file_location("memory_ops_converse", _converse_file)
_converse_mod = _ilu.module_from_spec(_converse_spec)
_sys.modules["memory_ops_converse"] = _converse_mod
_converse_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_converse_spec.loader.exec_module(_converse_mod)
_save_llm_config = _converse_mod._save_llm_config
_probe_llm = _converse_mod._probe_llm
_llm_hardware_requirements = _converse_mod._llm_hardware_requirements
converse = _converse_mod.converse
llm_setup = _converse_mod.llm_setup

# --- auto-loaded submodule: _doctor ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_doctor_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_doctor.py")
_doctor_spec = _ilu.spec_from_file_location("memory_ops_doctor", _doctor_file)
_doctor_mod = _ilu.module_from_spec(_doctor_spec)
_sys.modules["memory_ops_doctor"] = _doctor_mod
_doctor_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_doctor_spec.loader.exec_module(_doctor_mod)
_repair_json_text = _doctor_mod._repair_json_text
_restore_corrupt_file = _doctor_mod._restore_corrupt_file
_recompute_importance_from_recall = _doctor_mod._recompute_importance_from_recall
_index_content_sig = _doctor_mod._index_content_sig
report = _doctor_mod.report
summary_index = _doctor_mod.summary_index
tree_view = _doctor_mod.tree_view
promote_auto = _doctor_mod.promote_auto
promote_candidates = _doctor_mod.promote_candidates
_neural_installable = _doctor_mod._neural_installable
_clusters_exist = _doctor_mod._clusters_exist
_audit_item = _doctor_mod._audit_item
_audit_readable = _doctor_mod._audit_readable
audit_features = _doctor_mod.audit_features
dashboard = _doctor_mod.dashboard
_render_dashboard_html = _doctor_mod._render_dashboard_html
_euclid2 = _doctor_mod._euclid2
_kmeans_fit = _doctor_mod._kmeans_fit
_top_tags_for_cluster = _doctor_mod._top_tags_for_cluster
cluster_memories = _doctor_mod.cluster_memories
_find_contradiction_candidates = _doctor_mod._find_contradiction_candidates
_doctor_embed_backend = _doctor_mod._doctor_embed_backend
_check_investment_invariants = _doctor_mod._check_investment_invariants
# 2026-09-15：doctor 建议项 ack 抑制（须在 _cli 块之前再导出，_cli 才能拿到裸名）
DOCTOR_ACK_FILE = _doctor_mod.DOCTOR_ACK_FILE
DOCTOR_ACK_TTL_DAYS = _doctor_mod.DOCTOR_ACK_TTL_DAYS
_ACK_SECTIONS = _doctor_mod._ACK_SECTIONS
doctor_ack = _doctor_mod.doctor_ack
doctor_ack_list = _doctor_mod.doctor_ack_list
doctor_ack_clear = _doctor_mod.doctor_ack_clear
_apply_doctor_ack = _doctor_mod._apply_doctor_ack
doctor = _doctor_mod.doctor
token_report = _doctor_mod.token_report
backup = _doctor_mod.backup
_prune_doctor_fix_backups = _doctor_mod._prune_doctor_fix_backups
_verify_backup_zip = _doctor_mod._verify_backup_zip
_safe_extract_member = _doctor_mod._safe_extract_member
restore = _doctor_mod.restore
backup_prune = _doctor_mod.backup_prune
release_audit = _doctor_mod.release_audit
_discover_daemon_roots = _doctor_mod._discover_daemon_roots
_volume_missing = _doctor_mod._volume_missing

# --- auto-loaded submodule: _self_heal 统一自治循环）---
# 注册为顶层 _self_heal 别名，使 deposit/forget/link/reflect 等兄弟模块可 `from _self_heal import mark_dirty_safe`
# 跨模块调用（scripts/memory_ops/ 不在 sys.path，只能靠 sys.modules 别名解析，与 memory_ops_reflect 等一致）。
import importlib.util as _ilu
import os as _os
import sys as _sys
_self_heal_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_self_heal.py")
_self_heal_spec = _ilu.spec_from_file_location("memory_ops_self_heal", _self_heal_file)
_self_heal_mod = _ilu.module_from_spec(_self_heal_spec)
_sys.modules["memory_ops_self_heal"] = _self_heal_mod
_sys.modules["_self_heal"] = _self_heal_mod
# 补注册带点包内名：让 `from memory_ops import _self_heal` 拿到注入实例而非新副本
# （2026-09-27 实测此前遗漏，P1-1 同族）。
_sys.modules.setdefault("memory_ops._self_heal", _self_heal_mod)
_self_heal_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_self_heal_spec.loader.exec_module(_self_heal_mod)
self_heal = _self_heal_mod.self_heal
mark_dirty = _self_heal_mod.mark_dirty
mark_dirty_safe = _self_heal_mod.mark_dirty_safe
get_dirty = _self_heal_mod.get_dirty
clear_dirty = _self_heal_mod.clear_dirty
register_skill = _self_heal_mod.register_skill


# --- ：批量导入 / 性能基准 / MCP 服务（独立脚本模块，绑定到引擎命名空间）---
# 这三个模块位于 scripts/ 同级目录（与 memory_ops 包并列），复用本引擎的 deposit/recall/doctor 全流程。
# 绑定到引擎命名空间后，_cli 的 dispatch 与文档都能以统一 op 面引用它们。
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR and _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
try:
    import keeper_import as _keeper_import
    import keeper_benchmark as _keeper_benchmark
    import keeper_mcp_server as _keeper_mcp_server
    keeper_import_run = _keeper_import.run_import
    run_benchmark = _keeper_benchmark.run_benchmark
    mcp_serve = _keeper_mcp_server.serve
    mcp_main = _keeper_mcp_server.main
    KEEPER_MCP_VERSION = _keeper_mcp_server.VERSION
except Exception:  # 极端的裁剪部署（不含这三个脚本）时降级，不影响核心引擎
    def keeper_import_run(*a, **k):
        raise RuntimeError("keeper_import 模块不可用（当前部署未包含 scripts/keeper_import.py）")
    def run_benchmark(*a, **k):
        raise RuntimeError("keeper_benchmark 模块不可用（当前部署未包含 scripts/keeper_benchmark.py）")
    def mcp_serve(*a, **k):
        raise RuntimeError("keeper_mcp_server 模块不可用（当前部署未包含 scripts/keeper_mcp_server.py）")
    def mcp_main(*a, **k):
        raise RuntimeError("keeper_mcp_server 模块不可用（当前部署未包含 scripts/keeper_mcp_server.py）")
    KEEPER_MCP_VERSION = "unknown"



    # --- auto-loaded submodule: _cli ---
import importlib.util as _ilu
import os as _os
import sys as _sys
_cli_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_cli.py")
_cli_spec = _ilu.spec_from_file_location("memory_ops_cli", _cli_file)
_cli_mod = _ilu.module_from_spec(_cli_spec)
_sys.modules["memory_ops_cli"] = _cli_mod
_cli_mod.__dict__.update({k: v for k, v in globals().items() if not k.startswith("__")})
_cli_spec.loader.exec_module(_cli_mod)
list_commands = _cli_mod.list_commands
main = _cli_mod.main

# F18 包级惰性解析（PEP 562）：删除人工反向注入后，早加载子模块的函数体改为
# `memory_ops.NAME` 调用；包属性缺失时走此处惰性解析（在已加载子模块中查找并缓存到
# 包 __dict__），彻底消除装载顺序依赖。与 loader 的 `mod.__dict__.update(globals)`
# 注入不冲突——__getattr__ 仅在常规查找失败后才触发，是兜底层。
_SUBMODULES = [
    _taxonomy_mod, _scene_mod, _embed_mod, _decay_mod,
    _quarantine_mod, _recall_cache_mod, _rerank_mod, _versions_mod, _hooks_mod,
    _api_mod, _dep_mod, _lifecycle_mod, _reflect_mod, _harvest_mod,
    _converse_mod, _doctor_mod, _cli_mod, _persistence_mod, _core_mod,
    _graph_mod, _dsl, _legacy_mod, _self_heal_mod,
]  # 共 23 个 auto-loaded 子模块（不含 _config——其以带点名字 memory_ops._config 独立注册；
   # 亦不含 hooks/keeper_hook_common 等外部模块）。2026-09-27 修复：此前 _dsl_mod 误写为
   # ModuleSpec（spec_from_file_location 的返回值），导致 P1-1 补注册循环对它拿到空 __name__ 静默跳过、
   # from memory_ops import _dsl 拿到未注入副本；同时漏列 _self_heal_mod。均已修正。

# F18 惰性解析自引用兜底：确保每个子模块命名空间都能解析 `memory_ops`，无论其 loader 块
# 用批量 `mod.__dict__.update(globals)` 还是逐个注入。`_core` / `_persistence` 两类
# loader 块走逐个注入、未自动带上 `memory_ops`，会导致子模块内 `memory_ops.NAME` 调用点
# 运行期 NameError。统一在此注入，消除个别 loader 块遗漏。
for _m in _SUBMODULES:
    _m.memory_ops = memory_ops
    # 5.0.0：旧加密库守卫统一注入（与 `memory_ops` 同时机 —— 在**全部** loader 块之后）。
    # 用途：`_persistence` / `_versions` 等早加载模块以裸名调用守卫，无需各自 import；
    # 新增子模块自动获得，不必记得手工补注入（防「新读原语忘设防」复发）。
    _m.assert_not_legacy_encrypted = assert_not_legacy_encrypted
    _m.raise_if_legacy_ciphertext = raise_if_legacy_ciphertext
    _m.looks_like_legacy_ciphertext = looks_like_legacy_ciphertext

# 5.0.x：把扁平名子模块同时注册到**包内名**（sys.modules["memory_ops._api"] 等），
# 让 `from memory_ops import _api` 这类**子模块导入**也拿到注入后实例，而非标准导入
# 新加载的未注入副本（后者缺全局名 → `_api._rank_query` 直接 NameError）。
# 只补注册、不改既有扁平名与 __getattr__ 惰性解析，向后兼容；setdefault 不覆盖任何已存在名。
for _m in _SUBMODULES:
    _flat = getattr(_m, "__name__", "")
    if _flat.startswith("memory_ops_"):
        _attr = "_" + _flat[len("memory_ops_"):]
        sys.modules.setdefault(__name__ + "." + _attr, _m)
        globals().setdefault(_attr, _m)


def __getattr__(name):
    for _mod in _SUBMODULES:
        if name in _mod.__dict__:
            _obj = _mod.__dict__[name]
            globals()[name] = _obj  # 缓存到包 __dict__，二次访问直取、不重复触发
            return _obj
    raise AttributeError("module 'memory_ops' has no attribute %r" % name)


    # F18 装载契约守卫（开发/CI 期）：MEMORY_OPS_STRICT=1 时在 import 期触发，
    # 验证关键公开名经惰性解析可达 + 反向注入残留即报错（防回归）。默认关闭，不挂 import 关键路径。
def _verify_load_contract():
    for _name in ("recall", "deposit", "backup", "rollback", "overwrite", "delete",
                  "_quarantine_corrupt_file", "_recall_cache_clear"):
        if not callable(getattr(sys.modules[__name__], _name, None)):
            raise ImportError(
                "F18 lazy-resolution violated: memory_ops.%s 不可达"
                "（子模块未定义或 __getattr__ 失效）" % _name)
            # 防回归：反向注入残留即报错（应已被一次性清除）
    for _mod, _name in ((_versions_mod, "recall"), (_quarantine_mod, "deposit"),
                        (_core_mod, "_quarantine_corrupt_file"),
                        (_core_mod, "_recall_cache_clear"), (_core_mod, "overwrite"),
                        (_core_mod, "delete"), (_persistence_mod, "rollback")):
        if hasattr(_mod, _name):
            raise ImportError("发现残留反向注入 %s.%s（应已清除）"
                              % (_mod.__name__, _name))


if os.environ.get("MEMORY_OPS_STRICT") == "1":
    _verify_load_contract()

if __name__ == "__main__":
    main()
