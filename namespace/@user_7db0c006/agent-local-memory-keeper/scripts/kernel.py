# -*- coding: utf-8 -*-
"""kernel.py — 记忆系统的「纯函数 / 常量区」 从 memory_ops 包拆分）。

只含零业务依赖的确定性代码：敏感扫描正则 + 预检门 + 记忆 id 安全校验。
拆分动机：这些函数在 1.2 万行单体内无法独立单测/fuzz；搬出后 memory_ops 顶部
`from kernel import ...` 绑定同名符号，模块属性不变，所有调用方（含外部
`import memory_ops` 后用 m.xxx）行为完全一致。

⚠️ 维护纪律：本模块**禁止** import memory_ops（循环依赖）；只允许 stdlib。
新增无依赖纯函数可放这里；依赖 embedding/分类器/存储的逻辑必须留在 memory_ops。
"""
import os
import re

__all__ = [
    "_UNSAFE_MID_CHARS", "_is_safe_mid", "_assert_safe_mid",
    "_SENSITIVE_PATTERNS", "_SCAN_FAST_GATES", "_SCAN_CHAR_BUDGET", "_scan_sensitive",
]

_UNSAFE_MID_CHARS = ("/", "\\", ":", "\x00")


def _is_safe_mid(mid) -> bool:
    """记忆 id 是否为安全的纯文件名（不含路径分隔符/盘符/上跳段）。
    
    id 会被直接拼成 memories/<id>.json。未校验时：
    · deposit --id ../x 或 --id C:/abs/path → JSON 被写到库外，且会**静默覆盖**
    同名 .json（如误传 C:/proj/package 会清掉真实 package.json）；
    · recall --id <库外绝对路径> → 把库外任意 JSON 读进 agent 上下文，
    与云同步/推送功能叠加即构成外泄通道。
    """
    if not isinstance(mid, str) or not mid.strip():
        return False
    if mid.strip() in (".", ".."):
        return False
    if any(c in mid for c in _UNSAFE_MID_CHARS):
        return False
    return not os.path.isabs(mid)


def _assert_safe_mid(mid) -> None:
    """读写入口的硬校验：非法 id 直接拒绝，不做静默降级。"""
    if not _is_safe_mid(mid):
        raise ValueError(
            "非法记忆 id：%r（id 必须是纯文件名，不得含 / \\ : 或上跳段/绝对路径）" % (mid,))

        # ── Phase 3 §7 · 自动汲取保护器 ─────────────────────────────────────────
        # 纯加性、不动现有 deposit 签名；deposit 入口调用扫描失败 → 直接拒写。
        # 复审优化：预编译正则，避免每次 _scan_sensitive 调用重复编译（性能）。
_SENSITIVE_PATTERNS = [
# ── API Keys ──
    (re.compile(r"[s][k]-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "openai_sk_key"),
    (re.compile(r"[s][k]-ant-[A-Za-z0-9_\-]{20,}"), "anthropic_sk_key"),
    (re.compile(r"AKID[A-Za-z0-9]{16,}"), "aliyun_ak_id"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "github_pat"),
    (re.compile(r"gho_[A-Za-z0-9]{30,}"), "github_oauth"),
# S5 修复：补 GitHub PAT 新格式
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"), "github_pat_new"),
# S5 修复：补 GitLab PAT
    (re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"), "gitlab_pat"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{20,}"), "slack_token"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "jwt_token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private_key"),
    (re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]{20,}"), "bearer_token"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "google_api_key"),
# ── AWS ──
# Bug-2 修复：补 AWS Access Key ID
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key"),
# 复审修复：补 AWS STS 临时凭证
    (re.compile(r"ASIA[0-9A-Z]{16}"), "aws_sts_token"),
# Bug-2 修复：补 AWS Secret Access Key
# 复审修复：消费引号，避免带引号写法漏报
    (re.compile(r'(?i)aws_secret(?:_access)?_key[:=\s"\']+[A-Za-z0-9/+=]{40}'), "aws_secret_key"),
# ── Stripe ──
    (re.compile(r"sk_live_[0-9a-zA-Z]{24,}"), "stripe_live_key"),
    (re.compile(r"sk_test_[0-9a-zA-Z]{24,}"), "stripe_test_key"),
# 复审修复：补 Stripe Restricted Key
    (re.compile(r"rk_live_[0-9a-zA-Z]{24,}"), "stripe_restricted_live"),
    (re.compile(r"rk_test_[0-9a-zA-Z]{24,}"), "stripe_restricted_test"),
# ── Azure ──（复审新增）
# 修复：{8,} 无上界 + 无前置字面锚 → 在超长连续合法字符（如 1MB 纯字母）上
# 灾难性回溯（O(n²)），实测 1MB 文本卡死 >15s。加 {8,64} 上界 + _scan_sensitive 的
# 必要字面量预检（无 '@' 直接跳过本模式，行为完全等价）。
    (re.compile(r"[A-Za-z0-9_\-]{8,64}@[A-Za-z0-9_\-]{8,64}\.[A-Za-z0-9_\-]{8,64}"), "azure_connection_string"),
# ── 数据库连接串 ──（复审新增：含密码的 connection string）
    (re.compile(r"(?i)(?:postgres|mysql|mongodb|redis|amqp)://[^:]+:[^@]+@[^\s]+"), "db_connection_string"),
# ── Shopify ──（复审新增）
    (re.compile(r"shpat_[A-Za-z0-9]{32,}"), "shopify_pat"),
    (re.compile(r"shpss_[A-Za-z0-9]{32,}"), "shopify_secret"),
    (re.compile(r"shca_[A-Za-z0-9]{32,}"), "shopify_api_key"),
# ── Docker / CI/CD ──（复审新增）
# Docker config auth base64 (至少 40 字符 base64，真实 token 通常 40+ 字符)
    (re.compile(r'(?i)"auth"\s*:\s*"[A-Za-z0-9+/=]{40,}"'), "docker_auth_token"),
# ── PII（中国身份证 / 银行卡）──
    (re.compile(r"(?:身份证号|身份证)\D*\b([1-9]\d{16}[0-9Xx])\b"), "cn_id_card"),
    (re.compile(r"(?:银行卡|卡号|银行卡号)\D*\b([1-9]\d{15,18})\b"), "cn_bank_card"),
# ── 明文密码 ──
    (re.compile(r"(?i)(?:密码是|密码[:：]|password[:：=])\s*[A-Za-z0-9!@#$%^&*]{6,}"), "plaintext_password"),
]

# 修复：敏感扫描的「必要字面量预检」门。每个模式必须匹配到的必要子串
# （小写比对，缺失即跳过该模式）——根治无锚模式（如 azure_connection_string 的
# `[A-Za-z0-9_\-]{8,}`）在超长文本上的灾难性回溯（ReDoS）。键必须与模式字面量
# 一致，回归测试会校验「gate 子串确实出现在对应模式字符串中」防漂移。
_SCAN_FAST_GATES = {
    "openai_sk_key": "sk-",
    "anthropic_sk_key": "sk-ant-",
    "aliyun_ak_id": "akid",
    "github_pat": "ghp_",
    "github_oauth": "gho_",
    "github_pat_new": "github_pat_",
    "gitlab_pat": "glpat-",
    "slack_token": "xox",
    "jwt_token": "eyj",
    "private_key": "private key",
    "bearer_token": "bearer",
    "google_api_key": "aiza",
    "aws_access_key": "akia",
    "aws_sts_token": "asia",
    "aws_secret_key": "aws",
    "stripe_live_key": "sk_live_",
    "stripe_test_key": "sk_test_",
    "stripe_restricted_live": "rk_live_",
    "stripe_restricted_test": "rk_test_",
    "azure_connection_string": "@",
    "db_connection_string": "://",
    "shopify_pat": "shpat_",
    "shopify_secret": "shpss_",
    "shopify_api_key": "shca_",
    "docker_auth_token": '"auth"',
    "cn_id_card": "身份证",
    "cn_bank_card": ("银行卡", "卡号"),  # 模式含「银行卡|卡号」双分支
    "plaintext_password": ("password", "密码"),  # 模式含英文 password 与中文 密码 双分支
}

# 扫描总预算（字符 × 模式数）：超出即停止扫描（fail-open，宁可漏检也不让 deposit 卡死）。
# 防御未来新增模式再次引入无锚量词；正常文本（<100KB）远用不完。
_SCAN_CHAR_BUDGET = 8_000_000


def _scan_sensitive(text):
    """ §7 · 自动汲取敏感扫描（防 secrets 入库，遵守 SOUL 红线）。
    返回 (clean_text, hits)；hits 为命中的 (pattern_name, snippet) 列表。
    
    4.5.56 修复：加入必要字面量预检 + 扫描预算，根治大文本（1MB+）上无锚量词
    正则的灾难性回溯——此前实测 1MB 纯字母 body 会让 deposit 卡死 15s+ 且无
    traceback（进程被环境硬杀），已修复为线性时间。
    """
    if not text:
        return text, []
    hits = []
    low = text.lower()
    budget = _SCAN_CHAR_BUDGET
    for rx, name in _SENSITIVE_PATTERNS:
        gate = _SCAN_FAST_GATES.get(name)
        if gate is not None:
            _gates = gate if isinstance(gate, (tuple, list)) else (gate,)
            if not any(g in low for g in _gates):
                continue  # 必要字面量全部缺失 → 该模式必然不匹配，跳过（O(1) 剪枝）
        budget -= len(text)
        if budget < 0:
            break  # 预算耗尽：fail-open，停止扫描避免卡死（极端超大文本兜底）
        for m in rx.finditer(text):
            snip = m.group(0)
            if len(snip) > 24:
                snip = snip[:12] + "…"   # 复审修复：只暴露头部，不暴露尾部（更安全）
            hits.append((name, snip))
    return text, hits
