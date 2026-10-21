# -*- coding: utf-8 -*-
"""
keeper_hook_common.py — 各 keeper 钩子共享的工具层（端口化版）。

解决的问题（实测发现的真 bug）：
- WorkBuddy 的钩子子进程可能被净化 env，导致 AI_MEMORY_STORE 丢失 → 读到错误/空库。
本层统一 store_root()：回退链 AI_MEMORY_STORE → ~/.keeper/store_root → ~/.ai-memory。
- keeper recall 的 --min-relevance 在本机神经召回未激活时 score 恒≈0.064，
阈值 0.25 会把所有结果滤光；且任何 token 重叠的 query 都返回 ~6 条（库仅 7 条），
无法区分相关/无关。因此各钩子**不再信任 keeper 的 score/count 做相关性判定**，
改用本地词法重叠门控（tokenize + containment）。
- 所有钩子动作写入 hook_audit.log，便于重启后确认钩子真在 fire（用户最关心的验证手段）。

端口化（v4.5.2 起）：所有 ~/.workbuddy 路径用 expanduser 推导，不再硬编码具体 Windows 用户名主目录，
使 skill 装到任意用户名机器都能跑。PY 解析带 venv→managed 回退。

失败一律 fail-open：本模块任何异常都不应阻断主流程。
"""
import os
import re
import sys
import time
import json
import subprocess
import tempfile
import contextlib

# ---- 端口化根路径（替换旧版硬编码的用户主目录 .workbuddy）----
# 统一用正斜杠：与 live settings.json 命令约定一致，避免 Windows 反斜杠在 JSON/Shell 转义坑。
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy").replace("\\", "/")


def _keeper_scripts_dir():
    """定位 keeper 的 scripts 目录：兼容活跃副本带 .bak 后缀，且以含 memory_ops/__init__.py 为准。"""
    base = os.path.join(WB_HOME, "skills").replace("\\", "/")
    cands = [os.path.join(base, "agent-local-memory-keeper", "scripts").replace("\\", "/")]
    try:
        for d in sorted(os.listdir(base)):
            if d.startswith("agent-local-memory-keeper"):
                cands.append(os.path.join(base, d, "scripts").replace("\\", "/"))
    except Exception:
        pass
    for c in cands:
        if os.path.isfile(os.path.join(c, "memory_ops", "__init__.py").replace("\\", "/")):
            return c
    return cands[0]


SCR = _keeper_scripts_dir()


def _resolve_python():
    """优先用 keeper 的 venv python（带依赖），否则回退 managed 版（可能缺包但至少能跑）。"""
    venv = os.path.join(WB_HOME, "binaries", "python", "envs", "default", "Scripts", "python.exe").replace("\\", "/")
    if os.path.exists(venv):
        return venv
        # 回退：探测已安装 managed python 版本（优先最新），避免写死 在版本升级后失效
    base = os.path.join(WB_HOME, "binaries", "python", "versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, v, "python.exe").replace("\\", "/")
            if os.path.exists(cand):
                return cand
    return os.path.join(WB_HOME, "binaries", "python", "versions", "3.13.12", "python.exe").replace("\\", "/")


PY = _resolve_python()

_HERE = os.path.dirname(os.path.abspath(__file__))

# 运行态产物落点（hook_audit.log / _session_inject.json / ._dep_*.tmp 等）。
# 🔴 可用 env `KEEPER_HOOKS_DIR` 覆盖——与 scripts/memory_ops/_hooks.py 的
#    `_hooks_deploy_dir()` 同语义。必要性：测试若直接 import 源码树里的本模块
#    而不隔离，运行态产物会写回源码树 → 可能随发布包外泄（守护进程的状态文件曾因
#    同类路径把本机端口与 token 带进包）。未设该 env 时行为与旧版完全一致。
HOOKS_DIR = os.environ.get("KEEPER_HOOKS_DIR") or _HERE
AUDIT = os.path.join(HOOKS_DIR, "hook_audit.log")
_AUDIT_MAX = 200_000  # 审计日志超过此大小则截断保留尾部的 50%


def _default_store():
    """回退链：AI_MEMORY_STORE → ~/.keeper/store_root（用户级显式指定）→ ~/.ai-memory。

    机器特定路径不写进代码：库不在默认位置时，把路径写进 ~/.keeper/store_root
    （一行）即可，换盘/换机只改这个文件。
    """
    env = os.environ.get("AI_MEMORY_STORE")
    if env:
        return env
    try:
        p = os.path.join(HOME, ".keeper", "store_root")
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                v = (f.readline() or "").strip().strip('"').strip("'")
            if v:
                return v
    except Exception:
        pass
    if os.name == "nt":
        return os.path.join(HOME, "AI记忆")
    return os.path.join(HOME, ".ai-memory")


DEFAULT_STORE = _default_store()

# ---- keeper 常驻 daemon 召回客户端集成（方案 A / Plan Z）----
# 钩子进程内直接调用，避免再 spawn 一个子进程；daemon 不存在时懒启动并自愈，
# 彻底消除「每条消息冷加载模型 + recall 内部冷成本」的 ~5s 阻塞（实测热路径降至 ~100ms）。
import sys as _sys
# 🔴 锚定 `_HERE`（代码真实位置）而非 `HOOKS_DIR`：后者可被 env 重定向到临时目录，
#    若跟着走，sys.path 会插进一个不存在的路径 → keeper_recall_client 直接 import 失败。
_DAEMON_HOME = os.path.normpath(os.path.join(_HERE, "..", "keeper_daemon"))
_sys.path.insert(0, _DAEMON_HOME)
try:
    import keeper_recall_client as _KRC
    def recall_via_daemon(query=None, top_n=10, include_auto=False, semantic_gate=None):
        """透明替换 memory_ops recall 子进程调用；返回与 CLI 相同的 JSON 字符串。
        semantic_gate=None → 走 config 默认（神经后端下 0.30 离题门控）；
        传 0 可显式关闭（如自动蒸馏查重需看到全部候选）。"""
        return _KRC.recall_proxy(query=query, top_n=top_n, include_auto=include_auto,
                                 semantic_gate=semantic_gate)
except Exception as _e:
    # 客户端缺失 → 降级为空（绝不阻塞，语义召回待 daemon 恢复后自动回来）
    def recall_via_daemon(query=None, top_n=10, include_auto=False, semantic_gate=None):
        audit("recall_via_daemon", "error", "client import failed: %s" % _e)
        return json.dumps({"ok": True, "count": 0, "entries": []})


def _keeper_cfg_block():
    """合并读取 keeper 配置块：`<root>/store/config.json`（标准位）优先，`<root>/config.json`（旧库兜底）次之。

    🔴 4.9.17 修复（同族：钩子侧配置源与 memory_ops 不同源 → 读到假值）：
    旧实现（recall_mode/inject_enabled/neural_recall_active）**只读 `store/config.json` 一处**，
    而 memory_ops._load_keeper_config 认「store 优先 + root 兜底」。当某个键只写在
    `<root>/config.json`（被 memory_ops 认可的兼容位）时，钩子侧读不到 → 门控静默误判。
    本机实测复现：`embed_backend` 只在 root 配 → `neural_recall_active()` 恒 False，
    而真实后端是 fastembed（钩子门控与真实后端不一致）。
    现与 `_keeper_config_paths` 同源：先 root、后 store，后者覆盖（store 优先）。
    fail-open → 任一读取异常仅跳过该文件，绝不抛。
    """
    merged = {}
    try:
        _sr = store_root()
    except Exception:
        return merged
    for _p in (os.path.join(_sr, "config.json"),
               os.path.join(_sr, "store", "config.json")):
        try:
            if not os.path.exists(_p):
                continue
            with open(_p, encoding="utf-8") as _f:
                _c = json.load(_f)
            _kc = (_c.get("keeper") or {}) if isinstance(_c, dict) else {}
            if isinstance(_kc, dict):
                merged.update({k: v for k, v in _kc.items() if v is not None})
        except Exception:
            continue
    return merged


def recall_mode():
    """召回模式：daemon（常驻进程，毫秒级）或 inprocess（钩子进程内直接 recall，无独立进程）。
    优先级：env KEEPER_RECALL_MODE > keeper 配置块 recall_mode（store 优先 + root 兜底）> 默认 daemon。"""
    env = os.environ.get("KEEPER_RECALL_MODE")
    if env in ("daemon", "inprocess"):
        return env
    try:
        m = _keeper_cfg_block().get("recall_mode")
        if m in ("daemon", "inprocess"):
            return m
    except Exception:
        pass
    return "daemon"


def inject_enabled():
    """会话钩子是否允许自动注入记忆（方案 A，4.9.3）。

    背景：此前 `hooks/session_start_keeper_inject.py` 完全不读 `inject_enabled`，
    而 SKILL.md 又承诺该键「默认关，靠显式 retrieve」——文档承诺与实现不符：
    只要钩子模式不是 off，每会话启动都无条件注入至多 TOP_N 条。
    现在把开关收口到此函数，钩子守门后文档承诺即兑现。

    优先级（与 recall_mode 同范式）：env KEEPER_INJECT_ENABLED > keeper 配置块
    inject_enabled（store 优先 + root 兜底，与 memory_ops 同源）> 默认 False（默认关，与 KEEPER_DEFAULTS 一致）。
    fail-closed：解析异常/配置损坏时按 False 处理（宁可不注入，不越权注入）。
    """
    env = (os.environ.get("KEEPER_INJECT_ENABLED") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        v = _keeper_cfg_block().get("inject_enabled")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        pass
    return False  # 默认关（与 memory_ops.KEEPER_DEFAULTS["inject_enabled"] 一致）


def inject_include_auto():
    """会话注入的召回是否**包含自动捕获但未 confirm 的暂存记忆**（默认 True）。

    🔴 4.9.19 修复（真 bug，本机实测复现）：`recall` 默认隔离 `auto_sourced` 项
    （设计上要求显式 `--include-auto`），而很多用户（含本机）库里**全部**记忆都来自
    自动捕获 / 蒸馏、从未 `confirm`。于是两个注入钩子（SessionStart / UserPromptSubmit）
    调 `C.recall(...)` 不传该开关 → **恒召回为空**：SessionStart 审计只见 `empty no entries`，
    「启动即注入」钩子注册齐全、门控也放行，却没有任何内容可注入（名存实亡）。
    本机实测：库内 25 条记忆 100% `auto_sourced=True`；`recall` 空、`recall --include-auto` 有结果。

    为什么默认 True（而非保持隔离）：注入文案本身已自带
    「仅供参考；如有冲突以当前事实为准」免责声明，且有 `TOP_N` + 字符预算双重限流；
    反之若默认隔离，对「库内全是自动捕获」的主流场景等于功能不可用。

    优先级：env `KEEPER_INJECT_INCLUDE_AUTO` > 配置块 `inject_include_auto` > 默认 **True**。
    """
    env = (os.environ.get("KEEPER_INJECT_INCLUDE_AUTO") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        v = _keeper_cfg_block().get("inject_include_auto")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        pass
    return True


def recall_inprocess(query=None, top_n=10, include_auto=False, semantic_gate=None):
    """进程内召回：直接跑 memory_ops recall 子进程，无独立守护进程。
    实测冷加载 ~1.7s/次（fastembed 从磁盘缓存加载），在 30s 钩子超时内。
    返回与 daemon recall_proxy 相同的 JSON 字符串，可透明替换。fail-open。"""
    store = store_root()
    cmd = [PY, os.path.join(SCR, "memory_ops", "__init__.py"), "recall",
           "--root", store, "--query", query or "", "--top-n", str(top_n)]
    if include_auto:
        cmd.append("--include-auto")
    try:
        env = prepare_env()
        _kw = {}
        if os.name == "nt":
            # CREATE_NO_WINDOW：父进程是 pythonw（无控制台）时，若不显式指定，
            # Windows 会给控制台子进程新建一个可见窗口（inprocess 召回每次弹窗）。
            _kw["creationflags"] = 0x08000000
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=30, **_kw)
        out = p.stdout.decode("utf-8", "replace")
        json.loads(out)  # 合法性校验，失败走 except
        return out
    except Exception as e:
        audit("recall_inprocess", "error", str(e))
        return json.dumps({"ok": True, "count": 0, "entries": []})


def recall(query=None, top_n=10, include_auto=False, semantic_gate=None):
    """透明召回分发器：按 recall_mode 选 daemon 或 inprocess。钩子统一调本函数。"""
    if recall_mode() == "inprocess":
        return recall_inprocess(query=query, top_n=top_n, include_auto=include_auto,
                                semantic_gate=semantic_gate)
    return recall_via_daemon(query=query, top_n=top_n, include_auto=include_auto,
                             semantic_gate=semantic_gate)


def store_root():
    """AI_MEMORY_STORE 缺失时回退到用户真实库位置。"""
    return os.environ.get("AI_MEMORY_STORE") or DEFAULT_STORE


def prepare_env(extra=None):
    """构造传给 keeper 子进程的环境，强制带上 store_root，避免净化 env 读到错库。"""
    env = dict(os.environ)
    env["AI_MEMORY_STORE"] = store_root()
    env["PYTHONPATH"] = SCR + os.pathsep + env.get("PYTHONPATH", "")
    if extra:
        env.update(extra)
    return env


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


# 单一真源：tokenize/containment 来自契约层 contract（与 PreInjector 同包），
# 消除钩子↔契约层的重复实现。contract 不可导入时回退本地等价实现（fail-open）。
try:
    if SCR not in sys.path:
        sys.path.insert(0, SCR)
    from contract import tokenize, containment
except Exception:
    def tokenize(text):
        """中英文混合分词：ASCII 词(>=2) + 中文相邻 2-gram。返回 set。"""
        text = text or ""
        toks = set(_TOKEN_RE.findall(text.lower()))
        cjk = re.findall(r"[一-鿿]", text)
        for i in range(len(cjk) - 1):
            toks.add(cjk[i] + cjk[i + 1])
        return {t for t in toks if len(t) >= 2 or (len(t) == 2 and not t.isdigit())}

    def containment(hay, needle):
        """needle 的词表中有多少比例出现在 hay 中；返回 (比例, 交集绝对数)。"""
        if not hay or not needle:
            return 0.0, 0
        inter = hay & needle
        return (len(inter) / len(needle), len(inter))


# ---- 文本消毒：清除 UTF-8 模式读 stdin 产生的半代理码点 ----
# 背景（实测：hook_audit.log 中 502 条 deposit_error 全部为此）：Python 在 UTF-8 模式下
# sys.stdin 用 errors='surrogateescape'，WorkBuddy 传来的 Bash 输出里若含非法字节
# （git-bash 中文/GBK 混排最常见），会被解成 '\udcXX'。json.load 不报错——它是合法 str
# 字符——但后续 json.dump / 写文件 / 编码 HTTP 一律抛 UnicodeEncodeError，
# 自动捕获因此**静默失效**（用户只看到"没沉淀"，看不到报错）。
# 故在"读 stdin"这一层就地替换为 U+FFFD，从源头掐断，而不是在每个写盘点打补丁。
# ⚠️ 实现约束：源码里**不能**出现 "\ud800" 这类转义字面量——CPython 3.13 在编译期就会抛
# UnicodeEncodeError（'surrogates not allowed'），模块直接 import 不了。故一律用 chr() 运行期构造。
_LO_SUR = 0xD800
_HI_SUR = 0xDFFF
_REPL = chr(0xFFFD)  # U+FFFD 替换字符（非代理区，可安全出现在源码字面量里）


def sanitize_text(s):
    """把半代理码点（chr(0xDC80)~chr(0xDCFF) 等）替换为 U+FFFD；非 str 原样返回。"""
    if not isinstance(s, str):
        return s
    try:
        s.encode("utf-8")  # 快路径：绝大多数文本一次 C 调用即通过，零遍历开销
        return s
    except UnicodeEncodeError:
        pass
    return "".join(c if not (_LO_SUR <= ord(c) <= _HI_SUR) else _REPL for c in s)


def sanitize_obj(o):
    """递归消毒 dict/list/tuple/str（钩子事件体可任意嵌套）；其余类型原样返回。"""
    if isinstance(o, dict):
        return {sanitize_text(k) if isinstance(k, str) else k: sanitize_obj(v)
                for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize_obj(x) for x in o]
    return sanitize_text(o)


def read_event():
    """读钩子 stdin 事件并消毒；读不到/非 dict 返回 {}（fail-open）。

    直接读**字节流**再自行解码，而不是 `json.load(sys.stdin)`：
    stdin 的解码行为随 PYTHONUTF8/ locale 变化——有时是 surrogateescape（解出半代理码点、
    写盘时才炸），有时是 strict（**json.load 当场抛** UnicodeDecodeError，钩子直接 return，
    连错误信息都没有）。两种模式都导致「静默不沉积」，故统一走 bytes → decode(replace)，
    从源头保证事件体永远是干净可编码的 str。
    """
    try:
        buf = getattr(sys.stdin, "buffer", None)
        raw = (buf if buf is not None else sys.stdin).read()
        # 字节流自行解码：surrogateescape 对任何字节都不抛，非法字节解成半代理码点，
        # 随后由 sanitize_obj 统一换成**一个** U+FFFD（用 errors='replace' 则会按字节
        # 产出多个替换符，与"文本流入口"的行为不一致）。文本流（测试注入）直接用。
        txt = raw.decode("utf-8", "surrogateescape") if isinstance(raw, bytes) else raw
        evt = json.loads(txt)
    except Exception:
        return {}
    if not isinstance(evt, dict):
        return {}
    return sanitize_obj(evt)


def audit(event, action, detail=""):
    """追加一行审计；超限则原地截断（保留尾部）。fail-open。"""
    try:
        if os.path.exists(AUDIT) and os.path.getsize(AUDIT) > _AUDIT_MAX:
            with open(AUDIT, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            with open(AUDIT, "w", encoding="utf-8") as f:
                f.write("".join(lines[-2000:]))
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write("%s | %-14s | %-10s | %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), event, action,
                (detail or "").replace("\n", " ")[:200]))
    except Exception:
        pass


        # ---- 状态文件原子写 + 跨平台排他锁 加固）----
        # 钩子状态文件（_auto_cap.json / _errcap_state.json / _session_inject.json）此前是
        # read-modify-write 直接覆盖，Stop+PreCompact 同会话并发或连续 UserPromptSubmit 可能 race，
        # 崩溃还会写出半截 JSON → 下次 load 回默认（当日上限/去重指纹丢失）。
        # 这里统一 temp 写 + os.replace 原子替换；并加一把建议锁防止并发覆盖。
def atomic_write_json(path, obj):
    """原子写 JSON：同目录 temp 写 → fsync → os.replace 替换，杜绝半截写入/崩溃损坏。
    fail-open：任何异常静默忽略。"""
    try:
        d = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix="._tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
    except Exception:
        pass


_try_fcntl = None
try:
    import fcntl as _try_fcntl
except Exception:
    _try_fcntl = None


@contextlib.contextmanager
def locked(path):
    """跨平台排他建议锁（POSIX fcntl / Windows msvcrt.locking），围绕 read-modify-write 临界区。
    获取不到锁时仍继续（fail-open，绝不阻塞钩子），仅降低并发覆盖概率。"""
    lf = path + ".lock"
    fd = None
    got = False
    try:
        fd = open(lf, "a+b")
    except Exception:
        fd = None
    if fd is not None:
        try:
            if _try_fcntl is not None:
                _try_fcntl.flock(fd, _try_fcntl.LOCK_EX | _try_fcntl.LOCK_NB)
                got = True
            else:
                import msvcrt
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
                got = True
        except Exception:
            got = False
    try:
        yield got
    finally:
        if fd is not None:
            try:
                if _try_fcntl is not None and got:
                    _try_fcntl.flock(fd, _try_fcntl.LOCK_UN)
                elif got:
                    import msvcrt
                    msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                fd.close()
            except Exception:
                pass


def neural_recall_active():
    """语义召回后端是否可用（已配置语义后端且对应包可加载）。钩子门控据此自适应：
    可用时优先 score 门控，否则回退本地词法门控。fail-open → 异常时按不可用处理（回退词法）。

    🔴 4.9.17 修复（同族：读到的值与真实后端不一致）：
    ① 优先级与 memory_ops._load_keeper_config **完全同源**：
       env `AI_MEM_EMBED_BACKEND` > keeper 配置块（store 优先 + root 兜底）> 默认 fastembed。
       旧实现只读 `store/config.json` → 当 `embed_backend` 只配在 root 时恒返回 False；
       本机实测：root 配 fastembed、真实后端 fastembed，函数却返回 False（钩子门控误判）。
       新增 env 分支：用户用 env 强制 lexical（如测试隔离）时，真实后端是 lexical，
       门控也必须按 lexical——否则又是「钩子判定 ≠ 真实后端」。
    ② 白名单补齐**真实取值**：auto / fastembed / neural(别名) / sentence_transformers / online / local。
       旧实现只认 fastembed/local，把默认/normal 的 auto、别名 neural 一律误判为「无语义后端」。
    ③ online（云端语义）本地无需模型包，直接视为可用；auto 在 fastembed 缺失时回退 st 再判。
    """
    try:
        be = (os.environ.get("AI_MEM_EMBED_BACKEND") or "").strip().lower()
        if not be:
            be = (_keeper_cfg_block().get("embed_backend") or "").strip().lower()
        if not be:
            be = "fastembed"  # 与 memory_ops.KEEPER_DEFAULTS["embed_backend"] 一致
        if be in ("", "lexical"):
            return False
        if be == "online":
            return True  # 云端语义后端：本地零模型依赖
        if be in ("sentence_transformers", "st"):
            try:
                import importlib
                importlib.import_module("sentence_transformers")
                return True
            except Exception:
                return False
        if be in ("fastembed", "local", "auto", "neural"):
            try:
                import importlib
                importlib.import_module("fastembed")
                return True
            except Exception:
                if be == "auto":  # auto 模式可回退 sentence_transformers
                    try:
                        import importlib
                        importlib.import_module("sentence_transformers")
                        return True
                    except Exception:
                        return False
                return False
        return False
    except Exception:
        return False


        # ---- 跨钩子会话级去重（P2）：SessionStart 注入过的 entry id，UserPromptSubmit 不再重复注入 ----
_SESS_INJECT = os.path.join(HOOKS_DIR, "_session_inject.json")


def load_session_inject():
    try:
        return json.load(open(_SESS_INJECT, encoding="utf-8"))
    except Exception:
        return {}


def save_session_inject(state):
    with locked(_SESS_INJECT):
        atomic_write_json(_SESS_INJECT, state)


def session_injected_ids(session_id):
    return set(load_session_inject().get(session_id, []))


def mark_session_injected(session_id, ids):
    if not ids:
        return
        # I9 修复：read-modify-write 整段持锁，避免 SessionStart 与 UserPromptSubmit
        # 并发（不同钩子进程）各读旧值后互覆盖 → 丢去重 / 重复注入。
    with locked(_SESS_INJECT):
        st = load_session_inject()
        st[session_id] = list(set(st.get(session_id, [])) | set(ids))
        atomic_write_json(_SESS_INJECT, st)


if __name__ == "__main__":
    # 自测
    a = tokenize("沙箱 safe-delete 要用 ctypes 真删兜底")
    b = tokenize("沙箱删除必须 ctypes 兜底")
    print("containment(a in b)=", containment(a, b))
    print("tokenize sample=", sorted(a)[:10])
    print("WB_HOME=", WB_HOME)
    print("PY=", PY)
    print("DEFAULT_STORE=", DEFAULT_STORE)
