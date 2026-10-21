#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed.py — embedding 与主体抽取（v3.8.0：词法级 + 可选神经级 + 在线云端级，统一接口，零破坏性）

为记忆系统提供语义能力，解决 O5（深度改写召回）、G1（去重短文本误判）、G2（矛盾检测泛化标签误判）三类问题：
- 词法级：零依赖、确定性、完全离线。
- 神经级：可选本地小模型（fastembed/sentence_transformers），需本机可跑模型。
- 在线级（v3.8.0）：走 OpenAI 兼容 /v1/embeddings 云端推理，**本地零模型、零算力**，
适用于「电脑配不了本地模型」的场景；向量落库缓存后，召回只做本地余弦，不再联网。

公开 API（接口稳定，v2.4 起未变）：
embed(text)          → 归一化稠密向量（默认 512 维；神经后端自动 pad 对齐）
embed_batch(texts)   → 批量向量（神经后端走批量推理，词法级逐条）
cosine(a, b)         → 余弦相似度
semantic_similarity(a, b) → 便捷封装
extract_subjects(text)   → 抽取主体实体候选（剔除方法/动作/泛化词）
GENERIC_TAGS         → 泛化标签集合（矛盾检测时排除）
expand_synonyms(text)    → 同义词桥接（缓解深度改写召回的词汇鸿沟）
backend_info()       → 当前生效的后端（lexical / fastembed / sentence_transformers / none）

两层实现（可切换、可离线）：
────────────────────────────────────────────────────────────────
① 词法级（默认，零依赖，确定性）：字符 bi-gram + 词 hashing → 512 维。
无需下载任何模型，任何环境直接可用；同一文本永远同向量。
② 神经级（可选，需捆绑/安装离线小模型）：
- 自动探测 fastembed（轻量 ONNX，无 torch）或 sentence_transformers。
- 默认模型 BAAI/bge-small-zh-v1.5（中文 512 维，质量好、体积小）。
- 通过环境变量切换：
AI_MEM_EMBED_BACKEND = fastembed(默认, 开箱即用·CPU推理) | auto | neural(=fastembed 别名) | sentence_transformers | lexical
AI_MEM_EMBED_MODEL   = 模型名（默认 BAAI/bge-small-zh-v1.5）
- 探测失败/未安装 → 自动回退词法级，绝不报错卡死。

设计取舍（诚实）：
- 词法级能显著改善「部分词汇重叠 / 同义词 / 短文本改写」召回，优于纯子串；
但对「词汇完全不相交的深度改写」（如无同义词桥接）弱于神经模型。
- 神经级解决上面的残余：语义向量能命中「不柴↔嫩」「焯水↔汆水」即便无同义词桥。
- 神经模型是**可选增强**：不安装时系统完全离线可用；安装后无需改任何调用方代码，
embed()/cosine() 接口不变，recall 的混合排序自动享受更高质量的语义向量。
"""

import re
import math
import hashlib
import os
import sys
import contextlib
import json as _json
import sqlite3
import time
import memory_ops as _mops  # v4.4.15 配置收口：embed 后端/online url 走 _load_keeper_config（config.json keeper 块 + env 优先）


def _ensure_hf_mirror():
    """国内适配：用户未显式设置 HF_ENDPOINT 时，探测 HuggingFace 原站可达性。
    2 秒内不可达则自动 fallback 到 hf-mirror，避免国内用户首次下载模型卡死。
    返回是否启用了镜像（用于 report 等上层回显）。"""
    cur = (os.environ.get("HF_ENDPOINT") or "").strip()
    if cur:
        # 2026-09-05 P0：显式配置必须带 http(s):// 协议前缀。裸域名（如 hf-mirror.com）
        # 会让 httpx 抛 UnsupportedProtocol，而本函数「尊重用户配置」直接 return →
        # 下载失败 → 静默降级词法级。更隐蔽的是 doctor 的 using_mirror 判据只查子串
        # "hf-mirror"，裸域名同样命中 → 验收显示绿灯、实际已降级（假绿灯）。
        if not re.match(r"^https?://", cur, re.I):
            fixed = "https://" + cur.lstrip("/")
            os.environ["HF_ENDPOINT"] = fixed
            sys.stderr.write(
                "[keeper] HF_ENDPOINT 缺少协议前缀，已自动补全：%s -> %s\n" % (cur, fixed))
        return False  # 用户已显式指定，尊重选择
    try:
        import urllib.request
        req = urllib.request.Request("https://huggingface.co", method="HEAD")
        with urllib.request.urlopen(req, timeout=2) as _:
            return False  # 原站可达，保持默认
    except Exception:
        pass
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    return True

    # R4 修复：可选 numpy 加速余弦计算（~100x 快于纯 Python 循环）
try:
    import numpy as _np
except ImportError:
    _np = None

    # ── 第三方库 stdout/stderr 污染抑制（REAL BUG #2 根因修复）──────────────
    # 神经后端（sentence_transformers / fastembed）及其依赖的 huggingface_hub
    # 会在「导入」和「模型加载」时向 stdout 打印 warning（如
    # Error importing huggingface_hub._snapshot_download: [WinError 10106] ...）
    # 这会污染 memory_ops 包的 JSON 输出契约，导致 harness 端 json.loads 崩溃。
    # 在神经后端探测与编码边界用 devnull 重定向吞掉这些噪声，确保只有最终
    # print(json.dumps(...)) 能到达 stdout。函数自身不依赖 stdout，安全。
@contextlib.contextmanager
def _quiet_io():
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err

        # ── 泛化标签：矛盾检测（G2）时仅共享这些标签不触发 ──────────────────────
GENERIC_TAGS = {
    "记账", "方法", "技巧", "注意", "经验", "思路", "心得", "总结", "记录", "备忘",
    "通用", "其他", "杂项", "问题", "方案", "笔记", "参考", "学习", "提升", "优化",
    "知识", "资料", "文档", "信息", "数据", "说明", "教程", "指南", "建议", "提醒",
    "方式", "做法", "要点", "诀窍", "心得",
}


# ── 方法/动作/泛化词：抽取主体时剔除 ───────────────────────────────────
METHOD_WORDS = set(
    "冷水 热水 温水 凉水 焯水 汆水 汆 去腥 翻炒 炖煮 炖 煮 炒 煎 蒸 炸 烤 切 洗 "
    "腌制 入味 下锅 入锅 出锅 做法 步骤 诀窍 要点 技巧 方法 注意 经验 通用 流程 "
    "顺序 比例 时间 火候 使用 运行 执行 调用 配置 设置 安装 卸载 打开 关闭 启动 "
    "停止 创建 删除 修改 更新 添加 移除 导入 导出 复制 粘贴 保存 加载 读取 写入 "
    "处理 计算 生成 检查 验证 调试 修复 测试 部署 发布 提交 合并 同步 备份 恢复 "
    "清理 扫描 搜索 查找 定位 推荐 选择 判断 分析 对比 评估 规划 设计 实现 完成 "
    "开始 结束 之后 之前 时候 目前 情况 内容 文件 功能 支持 提供 如何 怎么 没有 "
    "可以 需要 如果 因为 所以 但是 而且 已经 或者 以及 对于 关于 通过 进行 所有 "
    "这个 那个 我们 他们 自己 一般 通常 总是 必须".split()
)

# ── 品牌名诚实标注（P0）：默认词法向量场景下，把品牌/机构/专有产品名
# 当作原子 token 处理，避免被字符 bi-gram 拆碎后与普通词混淆。
# 例："苹果手机" 中的 "苹果" 若按普通字符处理，会和 "吃苹果" 共享大量维度；
# 标为 __BRAND__苹果 后，品牌维度与普通语义维度分离，实现"诚实标注"。
# 支持环境变量 AI_MEM_BRAND_NAMES 以逗号分隔追加自定义品牌。
_BRAND_CORE = {
# 国际科技/互联网
# 注："苹果"单独出现易误判为水果，故只保留 Compound/产品形态；小米同理。
    "apple", "苹果公司", "苹果手机", "苹果电脑", "iphone", "ipad", "macbook", "ios", "siri",
    "google", "谷歌", "alphabet", "android", "安卓", "youtube", "gmail", "chrome",
    "microsoft", "windows", "office", "azure", "github", "linkedin",
    "amazon", "aws", "alexa", "kindle",
    "meta", "facebook", "instagram", "whatsapp", "threads",
    "netflix", "spotify", "openai", "chatgpt", "gpt", "dalle", "sora",
    "nvidia", "tesla", "spacex", "starlink", "intel", "amd", "qualcomm",
# 中文科技/互联网
    "阿里巴巴", "阿里", "淘宝", "天猫", "支付宝", "阿里云", "钉钉", "闲鱼",
    "腾讯", "微信", "qq", "qq音乐", "腾讯视频", "腾讯云", "企业微信", "王者荣耀",
    "字节跳动", "抖音", "tiktok", "今日头条", "西瓜视频", "飞书",
    "百度", "百度搜索", "百度网盘", "文心一言", "apollo",
    "华为", "huawei", "荣耀", "honor", "鸿蒙", "harmonyos", "麒麟", "mate", "p系列",
    "小米手机", "小米公司", "小米汽车", "小米商城", "xiaomi", "红米", "redmi", "米家", "澎湃",
    "oppo", "vivo", "一加", "oneplus", "iqoo", "realme",
    "京东", "拼多多", "美团", "饿了么", "滴滴", "滴滴出行",
    "快手", "b站", "哔哩哔哩", "bilibli", "知乎", "小红书", "微博",
    "网易", "网易云音乐", "有道", "暴雪", "暴雪中国",
    "国家电网", "国网", "南方电网", "中石油", "中石化", "中国移动", "中国联通", "中国电信",
# 新能源汽车
    "比亚迪", "byd", "蔚来", "小鹏", "理想", "极氪", "问界", "智界", "特斯拉",
# 常见模型/平台
    "claude", "anthropic", "llama", "mistral", "gemini", "bard", "copilot",
}


def _load_brand_names():
    """读取核心品牌词表 + 环境变量追加，全部小写去重。"""
    brands = set(_BRAND_CORE)
    extra = os.environ.get("AI_MEM_BRAND_NAMES", "")
    if extra:
        for b in extra.split(","):
            b = b.strip()
            if b:
                brands.add(b.lower())
    return brands


BRAND_NAMES = _load_brand_names()


def extract_brands(text):
    """诚实标注：返回文本中出现的品牌名列表（去重、小写）。
    用于记忆元数据 brand_mentions，让系统明确知道"这里提到了某品牌"，
    而不是把品牌语义隐式地混进词法向量中。

    匹配规则：
    - 按长度降序，优先长品牌，避免 "apple" 截断 "apple inc"。
    - 英文/数字边界严格（避免 "apple" 命中 "pineapple"）。
    - 中文品牌相邻中文属于正常语境，不阻断匹配。
    - 短品牌（<=2 字）只在完整词边界或Compound形式出现；独立出现易误判的
    （如"苹果"可指水果）通过品牌词表以Compound为主来规避。"""
    if not text:
        return []
    t = text.lower()
    found = []
    # 优先匹配长词
    for b in sorted(BRAND_NAMES, key=len, reverse=True):
        if b not in t:
            continue
        idx = 0
        while True:
            idx = t.find(b, idx)
            if idx == -1:
                break
            left_ch = t[idx - 1] if idx > 0 else ""
            right_ch = t[idx + len(b)] if idx + len(b) < len(t) else ""
            is_ascii_brand = b.isascii() and b.isalpha()
            # 英文/数字端边界：ASCII 纯字母品牌允许右侧紧跟数字（型号后缀，如 iphone15/mate60）
            left_ok = idx == 0 or not (left_ch.isalnum() and left_ch.isascii())
            if is_ascii_brand:
                right_ok = idx + len(b) >= len(t) or not (right_ch.isalpha() and right_ch.isascii())
            else:
                right_ok = idx + len(b) >= len(t) or not (right_ch.isalnum() and right_ch.isascii())
                # 短中文品牌（<=2字）额外要求：不能在另一个更长品牌的内部被覆盖。
                # 这里通过"发现即 break + 后续品牌跳过已覆盖区域"间接保证。
            if left_ok and right_ok:
                found.append(b)
                # 记录覆盖区间，短品牌若被长品牌先覆盖则自然跳过
                break
            idx += max(1, len(b))
            # 按出现位置排序、去重（保持首次出现顺序）
    pos_brand = []
    for b in found:
        p = t.find(b)
        if p != -1:
            pos_brand.append((p, b))
    pos_brand.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _, b in pos_brand:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


    # ── 同义词桥接：缓解深度改写召回（O5）的词汇鸿沟 ───────────────────────
SYNONYMS = {
    "不柴": "嫩", "柴": "老", "老": "柴",
    "焯水": "汆水", "汆水": "焯水", "汆": "焯水",
    "热水": "温水", "温水": "热水",
    "冷水": "凉水", "凉水": "冷水",
    "下锅": "入锅", "入锅": "下锅",
    "炒": "爆炒", "爆炒": "炒",
    "记账": "记录收支", "记录收支": "记账",
    "省事": "高效", "高效": "省事",
    "麻烦": "繁琐", "繁琐": "麻烦",
    "记住": "记一下", "记一下": "记住",
    "报错": "异常", "异常": "报错",
    "超时": "timeout", "timeout": "超时",
    "连不上": "连接失败", "连接失败": "连不上",
# #18: English synonyms for cross-lingual bridging
    "error": "bug", "bug": "error",
    "fail": "failure", "failure": "fail",
    "config": "configuration", "configuration": "config",
    "deploy": "deployment", "deployment": "deploy",
    "repo": "repository", "repository": "repo",
    "quick": "fast", "fast": "quick",
    "simple": "easy", "easy": "simple",
    "important": "critical", "critical": "important",
    "update": "upgrade", "upgrade": "update",
    "delete": "remove", "remove": "delete",
    "start": "launch", "launch": "start",
    "stop": "halt", "halt": "stop",
}

_PUNCT = re.compile(
    r"[\s，。、；：！？\"'（）()\[\]【】《》<>/\\.,;:!?\"'`~@#$%^&*\-_=+0-9]+"
)

EMB_DIM = 512

# ── 神经后端探测（懒加载、可回退）────────────────────────────────────────
_NEURAL = None          # None=未探测；False=不可用；(kind, obj)=可用
_CACHE = {}             # 进程内向量缓存（key=文本md5），避免同会话重复计算
_CACHE_MAX = 2000       # #16：缓存上限，超出时 LRU 淘汰最久未访问的条目
_PROTOTYPE_CACHE = {}   # #16：标签原型缓存 {tag: (avg_vec, count)}，加速标签相似度


# ── 可选磁盘缓存（§5#4，默认开启；KEEPER_EMBED_DISK_CACHE=0 关闭）─────────────
# 设计：在【用户级缓存目录】落一份 SQLite LRU 缓存（key 已含 backend:model，见 _bkey），
# 跨 CLI 进程复用、跨 store 共享，省去重复模型加载（尤其 fastembed 首次加载 ~90MB ONNX 权重；完整 BAAI 原仓库约 182MB 但 fastembed 只下 Qdrant 优化变体，不会被下载）。
# 默认开启——重复查询/重复文本命中缓存即跳过模型加载，召回与 deposit 双提速；显式设 0 才关。
# 取舍（诚实）：磁盘缓存存储「记忆文本派生的向量」（非明文，但由明文推导），落在用户级
# 缓存目录；故文档注明仅建议本地/可信环境开启。
_DISK_CACHE = None            # sqlite.Connection or None
_DISK_CACHE_CAP = 20000       # 单库容量上限，超出 FIFO 淘汰最旧一批

def _disk_cache_db_path():
    env = os.environ.get("KEEPER_EMBED_DISK_CACHE_DIR")
    if env:
        d = os.path.abspath(env)
    else:
        wb_home = os.path.expanduser("~")
        d = os.path.join(wb_home, ".workbuddy", "cache", "agent-local-memory-keeper", "embed_disk_cache")
    return os.path.join(d, "embed_cache.db")

def _disk_cache_enabled():
    # 默认开启（env 未设 → True）；仅显式 0/false/no 才关闭
    v = os.environ.get("KEEPER_EMBED_DISK_CACHE", "")
    if v == "":
        return True
    return v not in ("0", "false", "False", "no", "NO")

def _disk_cache_open():
    """惰性打开；任何异常 → 返回 None（静默禁用，回退内存/计算，绝不报错卡死）。"""
    global _DISK_CACHE
    if _DISK_CACHE is not None:
        return _DISK_CACHE
    if not _disk_cache_enabled():
        return None
    try:
        p = _disk_cache_db_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        con = sqlite3.connect(p, timeout=10)
        con.execute("CREATE TABLE IF NOT EXISTS ecache "
                    "(key TEXT PRIMARY KEY, backend TEXT, vec TEXT, ts INTEGER)")
        _DISK_CACHE = con
    except Exception:
        _DISK_CACHE = None
    return _DISK_CACHE

def _disk_cache_get(key):
    con = _disk_cache_open()
    if con is None:
        return None
    try:
        row = con.execute("SELECT vec FROM ecache WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return [float(x) for x in _json.loads(row[0])]
    except Exception:
        return None

def _disk_cache_put(key, backend, vec):
    con = _disk_cache_open()
    if con is None:
        return
    try:
        con.execute("INSERT OR REPLACE INTO ecache(key,backend,vec,ts) VALUES(?,?,?,?)",
                    (key, backend, _json.dumps(vec), int(time.time())))
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM ecache").fetchone()[0]
        if n > _DISK_CACHE_CAP:
            cut = con.execute("SELECT key FROM ecache ORDER BY ts ASC LIMIT ?",
                              (n - _DISK_CACHE_CAP + 1000,)).fetchall()
            if cut:
                con.executemany("DELETE FROM ecache WHERE key=?", [(r[0],) for r in cut])
                con.commit()
    except Exception:
        pass

def _get_cache(k):
    """RAM → 磁盘 两级读取；返回向量或 None。"""
    v = _cache_get(k)
    if v is not None:
        return v
    return _disk_cache_get(k)

def _put_cache(k, backend, vec):
    """写 RAM + （开启时）写磁盘。"""
    _cache_put(k, vec)
    _disk_cache_put(k, backend, vec)


def _fastembed_cache_dir():
    """fastembed 模型缓存根目录（解析优先级）：

    1) 环境变量 FASTEMBED_CACHE_PATH（最高优先，便于用户自定义 / 跨机迁移）；
    2) 用户级缓存目录 ~/.workbuddy/cache/agent-local-memory-keeper/models
    —— 刻意放在 skill 目录【之外】：使发布包保持纯净（~2MB），且重装 /
    覆盖 skill 时永不波及约 90MB 的嵌入模型权重，避免反复搬运。
    """
    env = os.environ.get("FASTEMBED_CACHE_PATH")
    if env:
        return os.path.abspath(env)
        # 用户级缓存，独立于 skill 目录（离线优先，避免每次重装都重下）
    wb_home = os.path.expanduser("~")
    return os.path.join(wb_home, ".workbuddy", "cache", "agent-local-memory-keeper", "models")


def _canonical_model_dir():
    """skill 内附带的完整规范模型副本（fast-bge-small-zh-，Qdrant 优化 ONNX 变体，约 90MB）。"""
    return os.path.join(_fastembed_cache_dir(), "fast-bge-small-zh-v1.5")


def _ensure_fastembed_offline_cache():
    """离线优先：把 fastembed 缓存指向 skill 内模型目录；本地模型存在则设 HF_HUB_OFFLINE=1（绕开联网下载）。

    与 mem_bridge._ensure_env 同源逻辑，但下沉到 embed 模块本身，使任何直接 import embed 的进程
    （钩子子进程、keeper_daemon）都能确定性地离线加载，不依赖 env 是否被继承。"""
    cache = _fastembed_cache_dir()
    os.environ["FASTEMBED_CACHE_PATH"] = cache
    if os.path.isdir(os.path.join(cache, "fast-bge-small-zh-v1.5")):
        os.environ["HF_HUB_OFFLINE"] = "1"


def _selfheal_fastembed_model():
    """模型缓存损坏/缺失时，从 skill 内规范副本（完整 onnx）修复到 fastembed 缓存快照目录。

    返回 True 表示已尝试修复（文件已复制）；返回 False 表示无规范副本或快照目录不存在（需联网重下）。

    === P1-2 SELF-HEAL (anchor: fastembed except silent-degrade) ==="""
    canon = _canonical_model_dir()
    onnx = os.path.join(canon, "model_optimized.onnx")
    if not os.path.exists(onnx) or os.path.getsize(onnx) < 50_000_000:
        return False  # 无完整规范副本
    cache = _fastembed_cache_dir()
    if not os.path.isdir(cache):
        return False
    files = ("model_optimized.onnx", "config.json", "tokenizer.json",
             "tokenizer_config.json", "ort_config.json",
             "special_tokens_map.json", "vocab.txt")
    did = False
    # P1-2：扫描所有已存在的模型快照目录（兼容 AI_MEM_EMBED_MODEL 变更），
    # 仅修复本规范副本对应的 bge 模型快照（其他模型无规范副本可修，需联网重下）。
    for mdir in sorted(os.listdir(cache)):
        if not mdir.startswith("models--") or "bge-small-zh-v1.5" not in mdir:
            continue
        tree = os.path.join(cache, mdir, "snapshots")
        if not os.path.isdir(tree):
            continue
        for snap in os.listdir(tree):
            sdir = os.path.join(tree, snap)
            if not os.path.isdir(sdir):
                continue
            for fn in files:
                src = os.path.join(canon, fn)
                if os.path.exists(src):
                    try:
                        import shutil as _sh
                        _sh.copy2(src, os.path.join(sdir, fn))
                        did = True
                    except Exception:
                        pass
    return did


def verify_model_integrity():
    """自检 fastembed 模型缓存完整性：onnx 存在且 >=50MB 且能被 onnxruntime 加载。

    返回 (ok, detail)。供维护脚本与 daemon warmup 在加载前/后核验，避免「0 字节空壳静默降级」。

    === P1-2 INTEGRITY (anchor: no public integrity fn) ==="""
    cache = _fastembed_cache_dir()
    # P1-2：扫描所有模型快照目录（兼容非默认 AI_MEM_EMBED_MODEL），不再硬编码单一模型名
    if not os.path.isdir(cache):
        return False, "无模型缓存目录（首次需联网下载或运行 _p1_maintain.py）"
    best = None
    for mdir in sorted(os.listdir(cache)):
        if not mdir.startswith("models--"):
            continue
        tree = os.path.join(cache, mdir, "snapshots")
        if not os.path.isdir(tree):
            continue
        for snap in os.listdir(tree):
            onnx = os.path.join(tree, snap, "model_optimized.onnx")
            if os.path.exists(onnx) and os.path.getsize(onnx) >= 50_000_000:
                best = onnx
                break
        if best:
            break
    if not best:
        return False, "模型缓存缺失或 onnx < 50MB（可能 0 字节损坏）"
    try:
        import onnxruntime as _ort
        _ort.InferenceSession(best)
        return True, best
    except Exception as e:
        return False, "onnx 加载失败: %s" % e


def _try_install_fastembed():
    """懒安装 fastembed（一次性，fail-soft）：为当前解释器（sys.executable）安装轻量 ONNX 语义组件。
    - 受 AI_MEM_NO_AUTO_INSTALL 环境变量开关控制（设任意值即禁用，适合离线/隔离环境）。
    - 失败（无网络 / 无 pip / 被沙箱拦截）返回 False，调用方回退词法级，绝不报错卡死。
    - 成功后由调用方重试 import；只触发一次（进程内缓存 _tried_install 标记）。"""
    if os.environ.get("AI_MEM_NO_AUTO_INSTALL"):
        return False
    try:
        sys.stderr.write(
            "[⏬ embedding] 首次需要中文语义组件，正在自动安装 fastembed（一次性，约 10-60s）…\n")
        sys.stderr.flush()
        import subprocess as _sp
        r = _sp.run([sys.executable, "-m", "pip", "install", "--quiet",
                     "--disable-pip-version-check", "fastembed"],
                    capture_output=True, text=True, encoding="utf-8", timeout=420)
        ok = (r.returncode == 0)
        sys.stderr.write("[✓ embedding] fastembed 安装成功。\n" if ok
                         else "[! embedding] 自动安装失败（可能无网络），将降级词法级；可手动：pip install fastembed\n")
        return ok
    except Exception as _e:
        sys.stderr.write("[! embedding] 自动安装异常：%s；将降级词法级。\n" % _e)
        return False


def _probe_neural():
    """探测神经 embedding 后端。成功返回 True 并缓存句柄；失败回退 False。"""
    global _NEURAL
    if _NEURAL is not None:
        return _NEURAL is not False
    _ensure_fastembed_offline_cache()  # P1-2：确定性离线缓存，不依赖 env 继承
    # 禁用 HuggingFace Xet CAS：部分网络对 cas-server.xethub.hf.co 返回 401，导致大文件拉取失败；
    # 关闭后回退普通 LFS 下载，更稳定。用户若确需 Xet 可显式置 0。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    # 国内适配：未显式设 HF_ENDPOINT 时，HuggingFace 不可达自动 fallback hf-mirror
    used_mirror = _ensure_hf_mirror()
    # 避免 huggingface_hub 单文件下载无限挂起；仍允许模型完整下载（~50MB 需几分钟）
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "180")
    backend = _mops._load_keeper_config()["embed_backend"].lower()
    if backend == "lexical":
        _NEURAL = False
        return False
    model = os.environ.get("AI_MEM_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    # 1) fastembed（轻量 ONNX，无 torch，推荐）；"neural" 作为 fastembed 的别名（语义化）
    if backend in ("auto", "fastembed", "neural"):
        def _load_fe():
            with _quiet_io():
                from fastembed import TextEmbedding
                return ("fastembed", TextEmbedding(model))

        try:
            sys.stderr.write(
                "[↓ embedding] 首次加载中文语义模型（%s，约 90MB），可能需要 10s-2min；"
                "若网络慢已自动切换国内镜像 %s。请稍候…\n"
                % (model, "(hf-mirror.com)" if used_mirror else "(HuggingFace 原站)")
            )
            _NEURAL = _load_fe()
            sys.stderr.write("[✓ embedding] 中文语义模型加载完成。\n")
            return True
        except Exception as _e0:
            # 2026-09-05 P0 自愈增强：探测通道与下载通道不一致。
            # _ensure_hf_mirror 用 urllib HEAD huggingface.co 探测，2s 内「成功」便不切镜像；
            # 但真实下载走 httpx（沙箱 TLS 拦截 / 代理 / 协议缺失均只影响它）→ 失败后直接
            # 静默降级。故首次失败且尚未用镜像时强制切 hf-mirror 重试一次，堵住
            # 「探测说可达 → 不切镜像 → 降级」这条链路。ImportError 属缺包，重试无意义。
            if (not getattr(_probe_neural, "_tried_mirror", False)
                    and not isinstance(_e0, (ImportError, ModuleNotFoundError))):
                _probe_neural._tried_mirror = True
                sys.stderr.write(
                    "[↻ embedding] 首次加载失败（%s），强制切换国内镜像重试一次…\n"
                    % type(_e0).__name__)
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
                os.environ["HF_HUB_DISABLE_XET"] = "1"
                try:
                    _NEURAL = _load_fe()
                    sys.stderr.write("[✓ embedding] 镜像重试成功，中文语义模型加载完成。\n")
                    return True
                except Exception:
                    pass
            # 懒安装（一次性，fail-soft）：auto/fastembed 模式下 fastembed 缺失时，
            # 自动为当前解释器安装组件，免去用户手动「装个组件」的门槛（kill-switch: AI_MEM_NO_AUTO_INSTALL）。
            if not getattr(_probe_neural, "_tried_install", False):
                _probe_neural._tried_install = True
                if _try_install_fastembed():
                    try:
                        with _quiet_io():
                            _NEURAL = ("fastembed", TextEmbedding(model))
                        sys.stderr.write("[✓ embedding] 自动安装完成，中文语义模型加载成功。\n")
                        return True
                    except Exception:
                        pass
                        # P1-2 自愈：模型缓存损坏/缺失时，从 skill 内规范副本（完整 onnx）修复后重试一次；
                        # 仍失败则明确告警（不再静默降级），并回退词法级兜底（fail-open 但 fail-LOUD）。
            sys.stderr.write("[✗ embedding] fastembed 加载失败，尝试从本地规范副本自愈…\n")
            try:
                if _selfheal_fastembed_model():
                    with _quiet_io():
                        _NEURAL = ("fastembed", TextEmbedding(model))
                    sys.stderr.write("[✓ embedding] 自愈成功（已从本地规范副本重建模型缓存）。\n")
                    return True
            except Exception:
                pass
            if backend == "auto":
                # auto 模式：fastembed 不可用时不在此处降级词法级，继续尝试下方 sentence_transformers 分支
                sys.stderr.write("[↓ embedding] fastembed 不可用，auto 模式转试 sentence_transformers…\n")
                # 不 return，让下方 sentence_transformers 分支接管
            else:
                sys.stderr.write(
                    "[✗✗ embedding] fastembed 不可用且自愈失败：语义召回降级词法级(DEGRADED)。\n"
                    "   如需中文语义检索，手动：pip install fastembed"
                    " （或设 AI_MEM_NO_AUTO_INSTALL=1 关闭自动安装）。\n")
                _NEURAL = False
                return False
                # 2) sentence_transformers（功能全，但依赖 torch，较重）
    if backend in ("auto", "sentence_transformers"):
        try:
            sys.stderr.write(
                "[↓ embedding] 首次加载 sentence_transformers 模型（%s），可能需要 10s-2min。请稍候…\n"
                % model
            )
            with _quiet_io():
                from sentence_transformers import SentenceTransformer
                _NEURAL = ("st", SentenceTransformer(model))
            sys.stderr.write("[✓ embedding] sentence_transformers 模型加载完成。\n")
            return True
        except Exception:
            sys.stderr.write("[✗ embedding] sentence_transformers 加载失败，将回退词法级向量。\n")
    _NEURAL = False
    return False


def _backend_mode():
    """返回 embedding 后端模式：online / auto / fastembed / neural / sentence_transformers / lexical。"""
    return _mops._load_keeper_config()["embed_backend"].lower()


def backend_info():
    """返回当前生效后端的完整标识：'fastembed:BAAI/bge-small-zh-' / 'online:text-embedding-3-small' 等。
    R1 修复：纳入模型名，使同后端换模型也能被检测到（防止跨空间向量混算）。
    ：新增 online 模式（云端 embedding，本地零模型）。"""
    if _backend_mode() == "online":
        model = os.environ.get("AI_MEM_EMBED_MODEL", "text-embedding-3-small")
        return "online:%s" % model
    if _NEURAL is None:
        _probe_neural()
    if _NEURAL is False:
        return "lexical"
    if _NEURAL is None:
        return "none"
    model = os.environ.get("AI_MEM_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    return "%s:%s" % (_NEURAL[0], model)


def _backend_id():
    """后端标识（如 fastembed:BAAI/bge-small-zh- / online:text-embedding-3-small / lexical），
    **不触发模型加载**——供缓存键与缓存读取在 model probe 之前安全使用。
    与 backend_info() 同构（同输入下产出相同字符串），但绝不调用 _probe_neural()，
    故冷进程命中磁盘缓存时不会因 backend_info() 提前 probe 而被迫加载模型。

    P1-2 修复（#cache-poison）：神经后端已探测但**加载失败**（_NEURAL is False）时，
    实际退化为词法级兜底。此时必须返回 "lexical" 而非 "fastembed:..."，否则
    「fastembed 键」下会藏入词法向量；模型恢复后误命中旧词法向量，导致语义余弦失真、
    语义召回静默失效。原实现仅看配置 mode，与 backend_info() 的实际降级行为不一致，
    正是上一轮『语义召回看似坏掉』的根因（共享磁盘缓存被 broken 运行期的词法向量污染）。"""
    mode = _backend_mode()
    if mode == "online":
        model = os.environ.get("AI_MEM_EMBED_MODEL", "text-embedding-3-small")
        return "online:%s" % model
    if mode == "lexical":
        return "lexical"
        # 神经后端：已探测且加载失败 → 实际是词法级，缓存键必须标 lexical，杜绝『fastembed 键藏词法向量』
    if _NEURAL is False:
        return "lexical"
    kind = "fastembed" if mode in ("auto", "fastembed", "neural") else "st"
    model = os.environ.get("AI_MEM_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
    return "%s:%s" % (kind, model)


    # ── 在线 embedding 后端（云端推理，本地零模型/零算力）──────────────
    # 适用于「电脑配不了本地模型」的场景：语义向量由 OpenAI 兼容 /v1/embeddings 生成，
    # 落库缓存到本地 SQLite（model 列标记 online:<model>），召回时只做本地余弦，不再联网。
    # 配置（环境变量）：
    # AI_MEM_EMBED_BACKEND=online
    # AI_MEM_EMBED_ONLINE_URL=https://<你的在线端点>/v1 （如 OpenAI / DeepSeek / 自建兼容网关）
    # AI_MEM_EMBED_ONLINE_KEY_ENV=AI_MEM_EMBED_ONLINE_KEY （API key 所在环境变量名，绝不写进文件）
    # AI_MEM_EMBED_MODEL=text-embedding-3-small （复用已有模型名变量）
def online_embed(text):
    """在线单条 embedding（OpenAI 兼容 /v1/embeddings）。失败返 None（调用方回退词法级）。"""
    try:
        import urllib.request
        import urllib.error
        import json as _json
        base = _mops._load_keeper_config()["embed_online_url"].rstrip("/")
        if not base:
            return None
        model = os.environ.get("AI_MEM_EMBED_MODEL", "text-embedding-3-small")
        key_env = os.environ.get("AI_MEM_EMBED_ONLINE_KEY_ENV", "AI_MEM_EMBED_ONLINE_KEY")
        key = os.environ.get(key_env, "")
        req = _json.dumps({"input": [text], "model": model}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer %s" % key
        reqobj = urllib.request.Request(base + "/embeddings", data=req,
                                        headers=headers, method="POST")
        with urllib.request.urlopen(reqobj, timeout=20) as r:
            obj = _json.loads(r.read().decode("utf-8"))
        arr = obj["data"][0]["embedding"]
        vec = [float(x) for x in arr]
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec
    except Exception:
        return None


def online_embed_batch(texts):
    """在线批量 embedding；返回与 texts 等长的 list，单条失败为 None。"""
    try:
        import urllib.request
        import urllib.error
        import json as _json
        texts = list(texts)
        base = _mops._load_keeper_config()["embed_online_url"].rstrip("/")
        if not base:
            return [None] * len(texts)
        model = os.environ.get("AI_MEM_EMBED_MODEL", "text-embedding-3-small")
        key_env = os.environ.get("AI_MEM_EMBED_ONLINE_KEY_ENV", "AI_MEM_EMBED_ONLINE_KEY")
        key = os.environ.get(key_env, "")
        req = _json.dumps({"input": texts, "model": model}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer %s" % key
        reqobj = urllib.request.Request(base + "/embeddings", data=req,
                                        headers=headers, method="POST")
        with urllib.request.urlopen(reqobj, timeout=60) as r:
            obj = _json.loads(r.read().decode("utf-8"))
        out = [None] * len(texts)
        for item in obj.get("data", []):
            idx = item.get("index")
            if idx is not None and 0 <= idx < len(texts):
                vec = [float(x) for x in item["embedding"]]
                norm = math.sqrt(sum(x * x for x in vec))
                if norm > 0:
                    vec = [x / norm for x in vec]
                out[idx] = vec
        return out
    except Exception:
        return [None] * len(texts)


        # ── 词法级 embedding（零依赖、确定性）───────────────────────────────────
def _lexical_tokens(text):
    """英文/数字词 + 中文字符 bi-gram + 中文字符 uni-gram（uni-gram 让共享单字也贡献）。
    对品牌名做诚实标注：把匹配到的品牌替换为占位符，再生成 __BRAND__{name} 原子 token，
    使其与普通字符 n-gram 维度分离，降低品牌与普通实词的误撞。"""
    text = text or ""
    brands = extract_brands(text)
    # 按长度降序替换，避免短品牌截断长品牌；占位符用私用区字符，不会被 _PUNCT 清洗。
    MARK = "\uE000"
    working = text
    brand_map = {}  # placeholder -> brand name
    for i, b in enumerate(brands):
        # 中间字符用私用区，保证唯一性且不被 _PUNCT 误删
        ph = MARK + "B" + chr(0xE001 + (i % 0x0FFF)) + MARK
        brand_map[ph] = b
        # 仅替换完整词边界：英文/数字端严格，中文相邻属于正常语境；ASCII 纯字母品牌允许右侧数字型号后缀。
        is_ascii_brand = b.isascii() and b.isalpha()
        right_boundary = r"(?![A-Za-z])" if is_ascii_brand else r"(?![A-Za-z0-9])"
        pat = r"(?<![A-Za-z0-9])" + re.escape(b) + right_boundary
        working = re.sub(pat, ph, working, flags=re.IGNORECASE)
        # 把占位符从文本中分离，非占位符部分再正常清洗/分词
    parts = re.split(r"(\uE000B[\uE001-\uF8FF]\uE000)", working)
    grams = []
    for part in parts:
        if part in brand_map:
            grams.append("__BRAND__" + brand_map[part])
            continue
            # 英文/数字词
        for w in re.findall(r"[A-Za-z0-9_]+", part.lower()):
            grams.append(w)
            # 中文字符 n-gram（清洗标点后）
        cn = _PUNCT.sub("", part)
        chars = [c for c in cn if "\u4e00" <= c <= "\u9fff"]
        for i in range(len(chars)):
            grams.append(chars[i])                     # uni-gram
            if i + 1 < len(chars):
                grams.append(chars[i] + chars[i + 1])  # bi-gram
    return grams


def lexical_embed(text):
    """词法级离线 embedding：hashing trick 把 token 映射到 512 维有符号向量，L2 归一化。"""
    toks = _lexical_tokens(text)
    vec = [0.0] * EMB_DIM
    for g in toks:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        idx = h % EMB_DIM
        sign = 1.0 if (h & 1) else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _pad(vec, dim=EMB_DIM):
    v = list(vec)
    if len(v) >= dim:
        return v[:dim]
    return v + [0.0] * (dim - len(v))


def _neural_embed_one(text):
    """用神经后端算单条向量，归一化并 pad 到 EMB_DIM。无后端返回 None。"""
    if not _probe_neural():
        return None
    kind, model = _NEURAL
    if kind == "fastembed":
        with _quiet_io():
            arr = list(model.embed([text]))[0]
    elif kind == "st":
        with _quiet_io():
            arr = list(model.encode([text]))[0]
    else:
        return None
    vec = [float(x) for x in arr]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return _pad(vec, EMB_DIM)


    # ── 统一公开 API ────────────────────────────────────────────────────────
def _cache_get(key):
    """#16：LRU 读取——命中时把 key 移到末尾（最近使用），返回值或 None。"""
    if key not in _CACHE:
        return None
    val = _CACHE.pop(key)
    _CACHE[key] = val  # 重新插入到末尾（最近使用）
    return val


def _cache_put(key, val):
    """#16：LRU 写入——超出上限时淘汰最旧（dict 首项）。"""
    if key in _CACHE:
        _CACHE.pop(key)
    elif len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))  # 淘汰最久未访问
    _CACHE[key] = val


_MODEL_FP = None  # 模型内容指纹进程内缓存（仅在模型加载/首次需要时算一次）

def _neural_model_file():
    """定位当前神经模型权重文件（取最大的 model_optimized.onnx，避开 0 字节 LFS 指针）。
    找不到或损坏时返回 None（调用方退化为 backend_id 兜底，不报错）。"""
    try:
        cache = _fastembed_cache_dir()
        import glob
        pats = [
            os.path.join(cache, "models--*bge-small-zh-v1.5*", "snapshots", "*", "model_optimized.onnx"),
            os.path.join(cache, "models--*", "snapshots", "*", "model_optimized.onnx"),
        ]
        hits = []
        for p in pats:
            for f in glob.glob(p):
                try:
                    if os.path.getsize(f) >= 1_000_000:  # 跳过 0 字节/过小指针
                        hits.append(f)
                except OSError:
                    pass
        if not hits:
            return None
        hits.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return hits[0]
    except Exception:
        return None

def _model_fingerprint():
    """模型内容指纹（神经后端下 = backend:model#<size>.<mtime>；词法/online = backend_id）。
    使模型被替换/损坏/升级后，旧向量缓存的键自动变化而失效，避免『幽灵向量』静默破坏语义召回。
    结果进程内缓存（_MODEL_FP），仅算一次；任何异常退化为 _backend_id，保持旧行为不崩。"""
    global _MODEL_FP
    if _MODEL_FP is not None:
        return _MODEL_FP
    b = _backend_id()
    if b.startswith("fastembed:") or b.startswith("st:"):
        try:
            f = _neural_model_file()
            if f and os.path.exists(f):
                st = os.stat(f)
                _MODEL_FP = "%s#%d.%d" % (b, st.st_size, int(st.st_mtime))
                return _MODEL_FP
        except Exception:
            pass
    _MODEL_FP = b
    return _MODEL_FP

def _bkey(text):
    """P1-2：向量缓存键纳入生效后端的完整标识（backend:model 或 lexical）+ 模型内容指纹，
    避免后端/模型切换后命中旧向量（错维/错语义的幽灵向量）。
    原实现仅 md5(text)，后端从 fastembed 退回 lexical、或换模型后仍命中旧缓存，导致语义召回失真。
    用 _backend_id/模型指纹（均不触发模型加载）避免缓存检查前被迫 probe 模型。"""
    fp = _model_fingerprint()
    return hashlib.md5((fp + "\u0000" + (text or "")).encode("utf-8")).hexdigest()


def embed(text, use_cache=True):
    """返回归一化稠密向量。：online 模式走云端 embedding（本地零模型），否则神经后端→词法级。
    进程内 LRU 缓存 + （开启时）磁盘缓存两级加速；在线失败自动回退词法级，绝不报错卡死。
    缓存检查在 backend_info（会触发模型加载）之前——命中即跳过模型加载，冷进程召回显著加速。"""
    k = _bkey(text)
    if use_cache:
        cached = _get_cache(k)
        if cached is not None:
            return cached
    binfo = backend_info()
    if _backend_mode() == "online":
        vec = online_embed(text)
        if vec is not None:
            if use_cache:
                _put_cache(k, binfo, vec)
            return vec
        vec = lexical_embed(text)  # 在线失败 → 词法级兜底
        if use_cache:
            _put_cache(k, binfo, vec)
        return vec
    vec = _neural_embed_one(text)
    if vec is None:
        vec = lexical_embed(text)
    if use_cache:
        _put_cache(k, binfo, vec)
    return vec


def embed_batch(texts, use_cache=True):
    """批量向量。：online 模式优先云端批量；其余走神经后端；最终未命中回退词法级。
    进程内 LRU 缓存 + （开启时）磁盘缓存两级加速。"""
    texts = list(texts)
    out = [None] * len(texts)
    need = []
    need_idx = []
    for i, t in enumerate(texts):
        if use_cache:
            k = _bkey(t)
            cached = _get_cache(k)
            if cached is not None:
                out[i] = cached
                continue
        need.append(t)
        need_idx.append(i)
    binfo = backend_info()
    # ：online 模式优先云端批量
    if need and _backend_mode() == "online":
        vecs = online_embed_batch(need)
        for j, v in enumerate(vecs):
            if v is not None:
                out[need_idx[j]] = v
                if use_cache:
                    _put_cache(_bkey(need[j]), binfo, v)
                    # 剩余未命中（非 online / 在线失败）→ 神经后端或词法级
    remaining = [need[j] for j in range(len(need)) if out[need_idx[j]] is None]
    remaining_idx = [need_idx[j] for j in range(len(need)) if out[need_idx[j]] is None]
    if remaining and _probe_neural():
        kind, model = _NEURAL
        if kind == "fastembed":
            arr_iter = model.embed(remaining)
            vecs = [list(x) for x in arr_iter]
        else:
            vecs = [list(x) for x in model.encode(remaining)]
        for j, v in enumerate(vecs):
            vv = _pad([float(x) for x in v])
            norm = math.sqrt(sum(x * x for x in vv))
            if norm > 0:
                vv = [x / norm for x in vv]
            out[remaining_idx[j]] = vv
            if use_cache:
                _put_cache(_bkey(remaining[j]), binfo, vv)
                # 最终兜底词法级
    for pos, i in enumerate(remaining_idx):
        if out[i] is None:
            vv = lexical_embed(remaining[pos])
            out[i] = vv
            if use_cache:
                _put_cache(_bkey(remaining[pos]), binfo, vv)
    return out


def cosine(a, b):
    """R4 修复：优先用 numpy 向量化点积（~100x 快于纯 Python 循环），无 numpy 时回退。
    v3.8.0：维度不一致（如后端切换期间存量向量未重嵌）返回 0.0，避免 numpy dot 维度报错崩溃。
    v4.4.12 修复：向量可能为 numpy 数组，`not a`/`not b` 对数组会抛
    "ValueError: The truth value of an array with more than one element is ambiguous"。
    改为显式 None/空/维度判定，并统一 asarray，确保 list 与 numpy 数组都安全。"""
    if a is None or b is None:
        return 0.0
    if _np is not None:
        try:
            a = _np.asarray(a, dtype=float)
            b = _np.asarray(b, dtype=float)
        except Exception:
            return 0.0
        if a.size == 0 or b.size == 0 or a.shape != b.shape:
            return 0.0
        return float(_np.dot(a, b))   # 向量已 L2 归一化（embed 输出），dot == 余弦
        # 无 numpy 回退路径
    if len(a) == 0 or len(b) == 0 or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def semantic_similarity(a, b):
    """两条文本的语义相似度（余弦，[-1,1]，通常 >=0）。"""
    return cosine(embed(a), embed(b))


    # ── #16：标签原型缓存 ────────────────────────────────────────────────────
def compute_tag_prototype(tag, texts):
    """计算标签原型向量：该标签下所有文本 embedding 的平均向量（归一化）。

    用于快速标签相似度查询——不必逐一 embed 全库记忆，只需比较 query 与原型。
    结果缓存在 _PROTOTYPE_CACHE 中，同标签同批次不重算。"""
    if tag in _PROTOTYPE_CACHE:
        return _PROTOTYPE_CACHE[tag]
    if not texts:
        return None
    vecs = embed_batch(texts)
    dim = len(vecs[0]) if vecs and vecs[0] else EMB_DIM
    avg = [0.0] * dim
    for v in vecs:
        if v:
            for i in range(dim):
                avg[i] += v[i]
    n = len(vecs)
    avg = [x / n for x in avg]
    norm = math.sqrt(sum(x * x for x in avg))
    if norm > 0:
        avg = [x / norm for x in avg]
    _PROTOTYPE_CACHE[tag] = (avg, n)
    return avg, n


def tag_similarity(query, tag, texts):
    """query 与标签原型的相似度（0~1）。texts 为该标签下的文本列表。
    原型已缓存时直接复用，否则现场计算并缓存。"""
    proto = compute_tag_prototype(tag, texts)
    if proto is None:
        return 0.0
    return cosine(embed(query), proto[0])


def clear_prototype_cache():
    """清空原型缓存（记忆内容变更后调用）。"""
    _PROTOTYPE_CACHE.clear()


def extract_subjects(text):
    """抽取文本主体实体候选：剔除方法/动作/泛化词后的中英文实词片段。
    用于 G1（去重主体豁免）与 G2（矛盾主体一致性）。"""
    t = text or ""
    for w in METHOD_WORDS:
        t = t.replace(w, " ")
    subs = []
    for m in re.findall(r"[A-Za-z][A-Za-z0-9_+#]*", t):
        subs.append(m.lower())
    cn = _PUNCT.sub(" ", t)
    for m in re.findall(r"[\u4e00-\u9fff]{2,}", cn):
        subs.append(m)
    seen, out = set(), []
    for s in subs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def expand_synonyms(text):
    """返回查询的多种表面形式（原句 + 同义词替换句），用于子串桥接。"""
    forms = [text]
    for k, v in SYNONYMS.items():
        if k in text:
            forms.append(text.replace(k, v))
    return forms


def is_generic_tag(tag):
    return tag in GENERIC_TAGS


if __name__ == "__main__":
    a = embed("红烧肉冷水焯水去腥")
    b = embed("排骨冷水焯水去腥")
    print("backend:", backend_info(), "emb dim:", len(a), "norm:", round(math.sqrt(sum(x * x for x in a)), 3))
    print("红烧肉 vs 排骨 语义相似:", round(semantic_similarity("红烧肉冷水焯水去腥", "排骨冷水焯水去腥"), 3))
    print("红烧肉 vs 红烧肉 语义相似:", round(semantic_similarity("红烧肉冷水焯水去腥", "红烧肉热水会柴"), 3))
    print("subjects(红烧肉...):", extract_subjects("红烧肉冷水焯水去腥"))
    print("subjects(排骨...):", extract_subjects("排骨冷水焯水去腥"))
    print("expand(怎么煮肉不柴):", expand_synonyms("怎么煮肉不柴"))
