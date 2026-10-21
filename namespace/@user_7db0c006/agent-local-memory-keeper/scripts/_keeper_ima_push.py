# -*- coding: utf-8 -*-
"""
_keeper_ima_push.py — 记忆库 → IMA 知识库 推送前处理器（v2，端口化版 v4.5.2）

相对旧版的关键升级（对应「IMA 内排版标签」设计）：
① 全量导出（active_only=False）：把 archived/superseded 也推上去，
让 IMA 成为「不遗忘的冷存储」，补 keeper stale_days=75 衰减的遗忘短板。
② 脱敏层（P0）：推送前 strip 凭证/真实路径/邮箱，IMA 是明文存储，必须前置防护。
③ 按 domain 拆文档：每条记忆 = 一个 `##` 段（IMA 按 H2 切 chunk，召回精准），
文档级用「稳定文件名 + DUPLICATE_NAME_STRATEGY=REPLACE」防堆积。
④ markdown 内结构化「标签」：元数据行（域/子域/类型/重要度/状态/创建）+ `**标签**:` 行，
替代 IMA 不支持的 API 级 tags。
⑤ 本地镜像缓存：同步写 <WB_HOME>/ima_mirror/<domain>.md，
供 SessionStart / UserPromptSubmit 钩子本地词法补充（钩子不能调 MCP）。

输出：
<PUSH_DIR>/<domain>.md                       每个域一个文档（供自动化上传）
<PUSH_DIR>/manifest.json                     域 → 文件/条数/生成时间
<WB_HOME>/ima_mirror/<domain>.md             本地镜像（供钩子）

端口化（v4.5.2）：所有 ~/.workbuddy / 用户主目录路径用 expanduser 推导；store 根走
AI_MEMORY_STORE 环境变量，缺失则读 ~/.keeper/store_root，再无则 ~/.ai-memory。

用法：
venv_python _keeper_ima_push.py [store_root] [push_dir]
"""
import sys
import os
import re
import json
import datetime

HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
SCRIPTS = os.path.join(WB_HOME, "skills", "agent-local-memory-keeper", "scripts")


def _user_store_override():
    """用户级显式指定：~/.keeper/store_root（一行路径）。不存在/为空 → None。"""
    try:
        p = os.path.join(HOME, ".keeper", "store_root")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8-sig") as f:
            v = (f.readline() or "").strip().strip('"').strip("'")
        return v or None
    except Exception:
        return None
DEFAULT_STORE = (os.environ.get("AI_MEMORY_STORE")
                 or _user_store_override()
                 or os.path.join(HOME, ".ai-memory"))
PUSH_DIR = os.path.join(WB_HOME, "ima_push")
MIRROR_DIR = os.path.join(WB_HOME, "ima_mirror")

sys.path.insert(0, SCRIPTS)
try:
    from memory_ops import _all_mems
except Exception as e:
    print("ERR: 无法导入 memory_ops: %s" % e)
    sys.exit(2)


def _store_root():
    return os.environ.get("AI_MEMORY_STORE") or DEFAULT_STORE


    # ---------- 脱敏层（P0） ----------
    # 顺序很重要：具体模式先跑，通用模式殿后，避免误伤正常文本。
_SKH = re.compile(r"skh_[A-Za-z0-9]{8,}")
_AK = re.compile(r"\bak_[A-Za-z0-9]{8,}")
_IMA_SECRET = re.compile(r"LY[A-Za-z0-9+/=]{12,}")
_GEN_SECRET = re.compile(
    r"(api[_-]?key|secret|token|password|access[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{8,}",
    re.IGNORECASE)
# 路径脱敏改由 desensitize 内做字符串替换（见下），避免正则反斜杠在本环境下不匹配的陷阱
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# 路径脱敏辅助：返回某路径的 / 与 \ 两种写法，字符串替换天然兼容任意分隔符
def _path_variants(base):
    if not base:
        return []
    return [base, base.replace("\\", "/"), base.replace("/", "\\")]


def desensitize(text):
    if not text:
        return text
    t = text
    t = _SKH.sub("<SKILLHUB_TOKEN>", t)
    t = _AK.sub("<API_KEY>", t)
    t = _IMA_SECRET.sub("<IMA_SECRET>", t)
    t = _GEN_SECRET.sub(lambda m: "%s=<REDACTED>" % m.group(1), t)
    # 路径脱敏：字符串替换（兼容 / 与 \，绕开正则反斜杠陷阱）；运行时推导，不再写死开发者路径
    for _v in _path_variants(HOME):
        t = t.replace(_v, "<user_home>/...")
    for _v in _path_variants(_store_root()):
        t = t.replace(_v, "<AI记忆库>")
        # 任意本地绝对路径脱敏：Windows 盘符路径 → 保留末级文件名/目录、去盘符与前导目录，
        # 避免泄露本地目录布局（IMA 明文存储）。例如 D:/<某项目>/数据.xlsx → <本地路径>/数据.xlsx。
        # 负向前瞻 (?!//) 排除 https?:// 等协议 URL，避免误伤公开链接。
    t = re.sub(r"[A-Za-z]:(?!//)[\\/]+([^\"\s`]+)",
               lambda m: "<本地路径>/" + m.group(1).replace("\\", "/").split("/")[-1], t)
    t = _EMAIL.sub("<email>", t)
    return t


    # ---------- 脱敏后复检 · P0 兜底，杜绝明文误推上云） ----------
def verify_desensitization(text):
    """扫描最终文本是否仍残留敏感信息。返回 [(类型, 片段), ...]；空=安全。
    覆盖：skillhub token / api key / IMA secret / 通用 secret kv / 绝对路径(兼容 \\ 与 /) / 邮箱。
    """
    if not text:
        return []
    leaks = []
    patterns = [
        ("SKILLHUB_TOKEN", re.compile(r"skh_[A-Za-z0-9]{8,}")),
        ("API_KEY", re.compile(r"\bak_[A-Za-z0-9]{8,}")),
        ("IMA_SECRET", re.compile(r"LY[A-Za-z0-9+/=]{12,}")),
        ("SECRET_KV", re.compile(
            r"(api[_-]?key|secret|token|password|access[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{8,}",
            re.IGNORECASE)),
        # (?!//) 负向前瞻排除 https?:// 等协议 URL，避免把公开链接误判为本地路径泄漏
        ("ABS_PATH", re.compile(r"[A-Za-z]:(?:" + re.escape("\\") + r"|/)(?!/)[^\"\s`]+")),
        ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ]
    for name, rx in patterns:
        for m in rx.finditer(text):
            snip = m.group(0)
            if len(snip) > 48:
                snip = snip[:45] + "..."
            leaks.append((name, snip))
    return leaks


    # ---------- 排版 / 标签 ----------
DOMAIN_LABEL = {
    "work": "技能开发·沙箱",
    "cleanup": "电脑清理工具",
    "investment": "量化投资",
}
DEFAULT_LABEL = "通用经验"


# ---------- 主题推断（domain 缺失时的补救分组） ----------
# 中文关键词直接包含；英文短词必须用 \b 词边界，否则 wind⊂windows、pb/roe 误伤。
_TOPIC_PAT = {
    "investment": [
        "量化", "投资", "仓位", "均线", "回测", "五维", "84日", "万得", "通达信",
        "申万", "两融", "选股", "因子", "股息率", "市盈率", "指数",
        r"\bwind\b", r"\betf\b", r"\broe\b", r"\bp\b",
    ],
    "cleanup": [
    # 只用无歧义的 PC/文件清理专属词；避免「清理/临时文件/扫描」误命中
    # 沙箱删除、会话恢复等语境（它们也会说「滚动清理」「临时文件无残留」）。
        "空文件夹", "重复文件", "垃圾文件", "磁盘空间", "清理工具", "磁盘清理",
        r"\bscanner\b",
    ],
    "work": [
        "沙箱", "技能", "记忆", "脱敏", "脚本", "钩子", "自动化",
        r"\bsandbox\b", r"\bskill", r"\bskillhub\b", r"\bkeeper\b", r"\bhook\b",
        r"\bctypes\b", r"\bfastembed\b", r"\bmcp\b", r"\breact\b", r"\bjsonl\b",
        r"\bworkbuddy\b", r"\bpipeline\b", r"\bredis\b",
    ],
}


def _topic_hit(topic, text):
    import re as _re
    for p in _TOPIC_PAT[topic]:
        if _re.search(p, text, _re.IGNORECASE):
            return True
    return False


def infer_topic(m):
    """domain 已填则优先；否则按内容关键词推断分桶。"""
    dom = (m.get("domain") or "").strip()
    if dom and dom != "-":
        return dom
    text = " ".join([
        (m.get("summary") or ""), (m.get("body") or ""),
        " ".join(m.get("tags", []) or [])
    ])
    for topic in ("investment", "cleanup", "work"):
        if _topic_hit(topic, text):
            return topic
    return "general"


def _is_junk(m):
    """剔除测试探针 / 明显噪声条目，不污染 IMA。"""
    s = (m.get("summary") or "")
    if s.startswith("ZZZPROBE") or "临时探针" in s or "PROBE_" in s:
        return True
    return False


def _meta_line(m):
    domain = m.get("domain") or "-"
    sub = m.get("subdomain") or "-"
    mtype = m.get("type") or m.get("category") or "-"
    imp = m.get("importance")
    imp = ("%.2f" % float(imp)) if isinstance(imp, (int, float)) else "-"
    status = m.get("status") or "active"
    created = m.get("created") or "-"
    archived_at = m.get("archived_at") or m.get("superseded_at") or "-"
    return "> 域:%s · 子域:%s · 类型:%s · 重要度:%s · 状态:%s · 创建:%s · 归档日:%s" % (
        domain, sub, mtype, imp, status, created, archived_at)


def render_domain(domain, mems):
    label = DOMAIN_LABEL.get(domain, DEFAULT_LABEL if domain in ("-", "") else domain)
    lines = [
        "# 🧠 AI记忆镜像 · %s" % label,
        "",
        "> 自动镜像自本地 keeper 记忆库（<AI记忆库>）。由 `python setup_scheduler.py` 注册的 Windows 计划任务自动刷新（默认每周日 23:00）；也可随时手动运行 `python scripts/ima_sync.py` 触发。",
        "> 用途：跨设备检索 / 换电脑还原 / 本地记忆衰减后的冷存储兜底。非权威源，以本地库为准。",
        "> 检索示例：用自然语言提问（如「沙箱删除报错怎么办」）即可命中相关条目。",
        "",
        "## 目录",
    ]
    # 目录（同样走脱敏，避免 summary 含本地路径时目录列表泄露，导致整文档复检失败）
    summaries = []
    for m in mems:
        s = desensitize((m.get("summary") or "(无摘要)").strip())
        summaries.append(s)
    for i, s in enumerate(summaries, 1):
        lines.append("%d. %s" % (i, s))
    lines.append("")

    # 每条记忆
    for i, m in enumerate(mems, 1):
        is_arch = m.get("status") in ("archived", "superseded")
        raw_summary = (m.get("summary") or "(无摘要)").strip()
        # 归档/被取代记忆在 IMA 里加【归档】前缀 + #归档 标签，与活跃记忆区分但仍可检索
        if is_arch and not raw_summary.startswith("【归档】"):
            raw_summary = "【归档】" + raw_summary
        summary = desensitize(raw_summary)
        body = desensitize((m.get("body") or "").strip())
        tags = list(m.get("tags", []) or [])
        if is_arch and "归档" not in tags:
            tags = tags + ["归档"]
        tag_str = ", ".join(tags)
        lines.append("---")
        lines.append("")
        lines.append("## %d. %s" % (i, summary))
        lines.append(_meta_line(m))
        lines.append("")
        if body:
            lines.append(body)
            lines.append("")
        if tag_str:
            lines.append("**标签**: %s" % tag_str)
            lines.append("")
    return "\n".join(lines)


def main():
    store_root = sys.argv[1] if len(sys.argv) > 1 else _store_root()
    push_dir = sys.argv[2] if len(sys.argv) > 2 else PUSH_DIR

    # 先清掉上次生成的旧文档（避免修分类/修 bug 前的陈旧版本被自动化重复上传）
    for d in (push_dir, MIRROR_DIR):
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith("keeper-镜像-") and fn.endswith(".md"):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass

    mems = _all_mems(store_root)
    if not isinstance(mems, dict):
        print("ERR: _all_mems 返回异常: %r" % type(mems))
        sys.exit(2)

        # 按 domain/主题 分组，剔除测试探针 + 同内容去重
    groups = {}
    seen = set()
    for mid, m in mems.items():
        if not isinstance(m, dict) or not m.get("id"):
            continue
        if _is_junk(m):
            continue
        key = ((m.get("summary") or "").strip(), (m.get("body") or "").strip())
        if key in seen:  # 去重（如 superseded 与 active 同内容的 Redis 条目）
            continue
        seen.add(key)
        bucket = infer_topic(m)
        groups.setdefault(bucket, []).append(m)
    for d in groups:
        groups[d].sort(key=lambda x: x.get("id", ""))

    os.makedirs(push_dir, exist_ok=True)
    os.makedirs(MIRROR_DIR, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    manifest = {"generated": stamp, "domains": {}}
    total = 0
    for domain, dmems in sorted(groups.items()):
        doc = render_domain(domain, dmems)
        push_path = os.path.join(push_dir, "keeper-镜像-%s.md" % domain)
        mirror_path = os.path.join(MIRROR_DIR, "%s.md" % domain)
        # ：脱敏后复检——任何残留敏感信息都 fail-loud，绝不写出可被自动化误推的明文文件
        leaks = verify_desensitization(doc)
        if leaks:
            print("❌ [脱敏复检失败] 域[%s] 文档仍残留敏感信息，已拒绝生成推送文件：" % domain)
            for _n, _s in leaks[:10]:
                print("   - %s: %s" % (_n, _s))
            sys.exit(2)
        with open(push_path, "w", encoding="utf-8") as f:
            f.write(doc)
        with open(mirror_path, "w", encoding="utf-8") as f:
            f.write(doc)
        manifest["domains"][domain] = {
            "file": "keeper-镜像-%s.md" % domain,
            "count": len(dmems),
            "label": DOMAIN_LABEL.get(domain, DEFAULT_LABEL if domain in ("-", "") else domain),
        }
        total += len(dmems)
        print("域[%s] %d 条 → %s" % (domain, len(dmems), push_path))

    with open(os.path.join(push_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("=== 完成：共 %d 条记忆，%d 个域文档，生成于 %s ===" % (total, len(groups), stamp))
    print("本地镜像目录: %s" % MIRROR_DIR)


if __name__ == "__main__":
    main()
