# -*- coding: utf-8 -*-
"""
keeper_daemon.py — keeper 常驻召回服务（只读）

解决的问题（实测发现的 P0 性能债）：
- 方案 Y 激活神经召回后，每次钩子（独立子进程）冷加载 fastembed 模型 ≈4.9s。
UserPromptSubmit 钩子在你每条消息都同步触发 → 每条消息 +5s 阻塞。
- 本服务把模型常驻内存，钩子通过本地 HTTP 查询，冷加载只付一次。

设计要点：
- 仅做 recall（读），不处理 deposit（写）——读写分离，避免多进程写 SQLite 竞争。
- 绑定 127.0.0.1（不外暴露）；POST /recall 需 X-Token 校验。
- 启动前强制 AI_MEM_EMBED_BACKEND=fastembed，根治「env 未继承→降级 lexical」坑。
- 单实例：启动时若已有活实例则自行退出。
- 空闲退出：KEEPER_DAEMON_IDLE_SECONDS（默认 0=永不离线；设正整数=空闲秒数后退出，释放内存）。
- 由 keeper_recall_client.py 懒启动（DETACHED），独立于钩子子进程存活。

位置（v4.5.2 起）：随 skill 包分发（skills/agent-local-memory-keeper/keeper_daemon/），
由 install_hooks.py 部署到 ~/.workbuddy/keeper_daemon/。所有路径端口化推导，
装到任意用户名机器都能跑（见下方 WB_HOME / SCR）。
"""
import os
import sys
import json
import time
import socket
import signal
import atexit
import hashlib
import threading

# 端口化 修复）：scripts 目录相对 WB_HOME 推导，不再硬编码用户名路径
WB_HOME = os.path.join(os.path.expanduser("~"), ".workbuddy").replace("\\", "/")
SCR = os.path.join(WB_HOME, "skills", "agent-local-memory-keeper", "scripts").replace("\\", "/")
sys.path.insert(0, SCR)
# ★ 强制神经后端：必须在 import memory_ops 之前设置，确保配置/env 在导入期即生效
# （根治「env 未继承→降级 lexical」坑；backend_info 虽实时读 env，但前置可避免任何导入期读取分支误判）
os.environ["AI_MEM_EMBED_BACKEND"] = "fastembed"
import memory_ops as MOPS  # 导入即就绪；模型在首次 embed（warmup/首个 recall）时懒加载

# 守护进程绝不触发钩子自安装（与 CLI 解耦，避免循环/权限问题）
os.environ["KEEPER_AUTO_INSTALL_HOOKS"] = "0"

_HERE = os.path.dirname(os.path.abspath(__file__))
# 🔴 运行态落点（STATE / LOG）可被 env `KEEPER_DAEMON_DIR` 重定向——测试/门禁隔离时
#    不把 `.daemon-<库指纹>.json`（含端口与本机 token）与 daemon.log 写回源码树。
#    与 hooks 侧的 `KEEPER_HOOKS_DIR` 同一思路：**状态目录可重定向，代码目录不可**。
# 🔴 4.9.19 修复：**默认落点**也从「代码目录 _HERE」改为「用户运行态目录
#    <WB_HOME>/keeper_daemon」。旧默认下，凡从源码树直接运行（开发/测试/手动验证）
#    都会把状态文件写回仓库——污染源码树、可能随发布包外泄（含端口/token）、并让静态
#    闸门 `no_runtime_state_in_tree` 持续假红。部署态本就把代码放在 <WB_HOME>/keeper_daemon，
#    故本改动对部署行为**零变化**（_HERE 恰好等于新默认），只让源码态不再污染。
#    env `KEEPER_DAEMON_DIR` 仍最高优先（测试隔离用）。
HOME = os.environ.get("KEEPER_DAEMON_DIR") or os.path.join(WB_HOME, "keeper_daemon")
LOG = os.path.join(HOME, "daemon.log")
IDLE_SECONDS = int(os.environ.get("KEEPER_DAEMON_IDLE_SECONDS", "0"))  # 0=永不离线
TOKEN = os.urandom(16).hex()
_STARTED = time.time()   # 进程启动时刻（供 /health 算 uptime）
_PORT = None             # main() 绑定后写入，供 /health 回显
LOG_MAX_BYTES = 1_000_000  # daemon.log 超 1MB 自动截断，防无限增长残留


def _cleanup_runtime():
    """优雅退出时清理运行态残留，避免手动 kill 后留下状态文件 / 过大日志。

    普通 kill -9 无法捕获，残留由下次启动时的 _already_running 陈旧清理兜底。"""
    try:
        if os.path.exists(STATE):
            os.remove(STATE)
            _log("已清理 STATE")
    except Exception as e:
        _log("cleanup STATE 失败: %s" % e)


def _graceful_exit(signum, frame):
    _log("收到退出信号 %s，清理运行态后退出" % signum)
    _cleanup_runtime()
    sys.exit(0)


def _default_store():
    """回退链：AI_MEMORY_STORE → ~/.keeper/store_root（用户级显式指定）→ ~/.ai-memory。

    机器特定路径不写进代码：库不在默认位置时，把路径写进 ~/.keeper/store_root
    （一行）即可，换盘/换机只改这个文件。
    """
    env = os.environ.get("AI_MEMORY_STORE")
    if env:
        return env
    try:
        p = os.path.join(os.path.expanduser("~"), ".keeper", "store_root")
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                v = (f.readline() or "").strip().strip('"').strip("'")
            if v:
                return v
    except Exception:
        pass
    _h = os.path.expanduser("~")
    if os.name == "nt":
        return os.path.join(_h, "AI记忆")
    return os.path.join(_h, ".ai-memory")


ROOT = os.environ.get("AI_MEMORY_STORE") or _default_store()


def _root_key(root):
    """记忆库路径 → 状态文件名指纹（12 位 hex）。

    🔴 与客户端 keeper_recall_client 里的 `_root_key` **必须是同一套算法**：两侧各自
    算出同一个指纹，才能找到同一份 STATE。不一致的症状很隐蔽——客户端永远认不出刚
    起来的 daemon，一路轮询到超时，最后静默跳过注入（不报错、只是「没记忆」）。
    一致性由测试 test_daemon_root_scope 逐字锁死，改这里必须同步改那边。
    """
    try:
        p = os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(root)))))
    except Exception:
        p = str(root)
    return hashlib.sha256(p.encode("utf-8", "replace")).hexdigest()[:12]


# 🔴 STATE 必须**按库分隔**，不能让所有库共用一份状态文件。
#    只做「复用前校验 root」是不够的：库 A 与库 B 的客户端会反复覆盖同一份 STATE，
#    谁也认不下对方的 daemon，于是各自重启、再覆盖（抖动），总有一方读不到自己的库。
#    按库指纹命名后，每个库各持一份 STATE，互不踩踏；同一台机器上多库各有常驻也成立。
STATE = os.path.join(HOME, ".daemon-%s.json" % _root_key(ROOT))
# ≤4.9.12 的单实例 STATE（无库指纹，已弃用）。升级后由 main() 一次性回收：
# 仅当那个旧 daemon 自报的 root 与本库一致（= 本库的陈旧孪生）才请它退出，
# 自报他库 / 无法确认时只当没看见——不替别的库做决定。
LEGACY_STATE = os.path.join(HOME, ".daemon.json")

_last = {"t": time.time()}


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s | %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _backend():
    try:
        return MOPS._emb_backend()
    except Exception:
        return "?"


def _stats():
    """可观测性（§6.8）：从 ROOT/recall_counts.json 汇总召回频次热/温/冷分布。
    只读、零模型依赖、不触盘（仅 SELECT/读 JSON），供 stats 端点与调试。"""
    p = os.path.join(ROOT, "recall_counts.json")
    data = {}
    try:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as _f:
                data = json.load(_f) or {}
    except Exception:
        data = {}
    counts = [int(v.get("count", 0)) if isinstance(v, dict) else 0 for v in data.values()]
    total = len(counts)
    hot = sum(1 for c in counts if c >= 5)
    warm = sum(1 for c in counts if 1 <= c < 5)
    cold = sum(1 for c in counts if c == 0)
    return {
        "recall_tracked": total,
        "hot": hot, "warm": warm, "cold": cold,
        "max_recall_count": max(counts) if counts else 0,
        "total_recall_events": sum(counts),
    }


def warmup():
    """预加载模型，使首个真实 recall 不付冷加载代价。"""
    try:
        t0 = time.time()
        MOPS.recall(ROOT, query="keeper-daemon-warmup")
        _log("warmup ok, backend=%s, cost=%.2fs" % (_backend(), time.time() - t0))
    except Exception as e:
        _log("warmup warn: %s" % e)


class _Handler:
    def __init__(self, request, client_address, server):
        self.request = request
        self.client_address = client_address
        self.server = server
        self.rfile = request.makefile("rb")
        self.wfile = request.makefile("wb")
        self.headers = {}

    def handle(self):
        try:
            self._parse_request()
        except Exception:
            self._send(400, {"ok": False, "error": "bad_request"})
            return
        _last["t"] = time.time()
        if self.command == "GET" and self.path.startswith("/ping"):
            # 除了「活着」，还必须自报**在服务哪个库**：客户端只有拿到这个字段才能判断
            # 复用是否安全。仅凭 STATE 文件里的记录不够——端口可能已被另一个库的 daemon
            # 占用，那时纸面记录与本机事实不符，复用就把召回打到错误的库（静默）。
            self._send(200, {"ok": True, "backend": _backend(), "root": ROOT})
        elif self.command == "GET" and self.path.startswith("/health"):
            # 本地只读健康态（与 /ping 同级别，不需 token；仅 .1 可达）
            self._send(200, {"ok": True, "backend": _backend(),
                             "status": "running",
                             "uptime_s": int(time.time() - _STARTED),
                             "pid": os.getpid(), "port": _PORT, "root": ROOT})
        elif self.command == "GET" and self.path.startswith("/stats"):
            # 召回频次可观测性（§6.8），本地只读
            self._send(200, {"ok": True, **_stats()})
        elif self.command == "GET" and self.path.startswith("/quit"):
            # P1-1：与 /recall 一致，需 X-Token 校验，防止本机任意进程杀守护进程（本地 DoS）
            if self.headers.get("x-token") != TOKEN:
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True})
            # 优雅退出：先清理运行态残留（本库的 STATE），再退出（不再用 os._exit 跳过清理）
            threading.Thread(target=lambda: (time.sleep(0.2), _cleanup_runtime(), os._exit(0))).start()
        elif self.command == "POST" and self.path.startswith("/recall"):
            if self.headers.get("x-token") != TOKEN:
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            try:
                n = int(self.headers.get("content-length", "0") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                payload = json.loads(raw or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad_request"})
                return
            try:
                q = payload.get("query")
                inc = bool(payload.get("include_auto", False))
                sg = payload.get("semantic_gate", None)
                res = MOPS.recall(ROOT, query=q, include_auto=inc, semantic_gate=sg)
                self._send(200, {"ok": True, "count": len(res), "entries": res})
            except Exception as e:
                _log("handler error: %s" % e)
                self._send(500, {"ok": False,
                                 "error": "处理请求时出错，已记入守护进程日志（daemon.log）；如持续失败，可对 AI 说「embedding 降级了」由它跑 doctor 定位。"})
        elif self.command == "POST" and self.path.startswith("/deposit"):
            # §6.7：程序化捕获端点。默认关闭（守护进程保持只读姿态），
            # 需设 KEEPER_DAEMON_ALLOW_DEPOSIT=1 启用；并与 /recall 同级别 X-Token 校验。
            # 写操作经 MOPS.deposit 内部的 per-root 锁串行化；仍建议仅在确需程序化写入时启用，
            # 避免与 CLI 并发写产生 SQLite 竞争（设计上读写分离为默认）。
            if not os.environ.get("KEEPER_DAEMON_ALLOW_DEPOSIT"):
                self._send(403, {"ok": False, "error": "deposit_disabled",
                                 "msg": "守护进程默认只读；设 KEEPER_DAEMON_ALLOW_DEPOSIT=1 启用 /deposit"})
                return
            if self.headers.get("x-token") != TOKEN:
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            try:
                n = int(self.headers.get("content-length", "0") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                payload = json.loads(raw or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad_request"})
                return
            try:
                mid = MOPS.deposit(ROOT, payload.get("category", "") or "note",
                                   payload.get("summary", "") or "",
                                   tags=payload.get("tags", "") or "",
                                   body=payload.get("body", "") or "",
                                   scope=payload.get("scope", "") or "universal",
                                   project=payload.get("project", "") or "",
                                   recorded_by=payload.get("recorded_by", "agent") or "agent")
                self._send(200, {"ok": True, "id": mid})
            except Exception as e:
                _log("handler error: %s" % e)
                self._send(500, {"ok": False,
                                 "error": "处理请求时出错，已记入守护进程日志（daemon.log）；如持续失败，可对 AI 说「embedding 降级了」由它跑 doctor 定位。"})
        else:
            self._send(404, {"ok": False, "error": "unknown"})

    def _parse_request(self):
        line = self.rfile.readline().decode("iso-8859-1").rstrip("\r\n")
        if not line:
            raise ValueError("empty")
        parts = line.split()
        self.command, self.path = parts[0], parts[1]
        while True:
            h = self.rfile.readline().decode("iso-8859-1").rstrip("\r\n")
            if not h:
                break
            k, _, v = h.partition(":")
            self.headers[k.strip().lower()] = v.strip()

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.request.sendall(
            ("HTTP/1.1 %d OK\r\nContent-Type: application/json; charset=utf-8\r\n"
             "Content-Length: %d\r\nConnection: close\r\n\r\n" % (code, len(body))).encode("iso-8859-1")
            + body)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _pid_alive(pid):
    """进程是否存活。与 keeper_recall_client._pid_alive **同一套语义**（见其 docstring）。

    🔴 4.9.19：daemon 是**先 listening、后 warmup**，warmup 窗口内 0.5s 的 ping 必然超时。
    因此「ping 失败」不能当「进程已死」——必须回落到 PID 存活性判别，否则会把正在 warmup
    的活实例的 STATE 当陈旧残留删掉（客户端侧就是因为这个自毁会合点）。
    """
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == STILL_ACTIVE
            finally:
                k.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _already_running():
    """若已有**服务本库**的活实例，返回其 port，否则 None。

    🔴 ping 通过只证明「有个 daemon 活着」，**不证明它服务于本库**。故必须比对活进程
    自报的 root；不一致/不报 → 不复用（宁可多起一个，也不能把召回打到别的库上）。
    不复用时**不删**那份 STATE：同名文件属本库，交给 main() 按新事实重写。

    🔴 旧版 daemon 不在 /ping 里回 `root` → 一律**拒绝复用**（fail-closed）。纸面上的
    root 字段不能当替代证据：端口被别人占用时，纸面记录恰恰就是错的那一方。

    若 STATE 存在但 ping 失败（进程已死），说明是手动 kill 留下的陈旧残留，
    主动删除避免状态文件一直留在磁盘；随后由本进程写新 STATE。"""
    if not os.path.exists(STATE):
        return None
    try:
        st = json.load(open(STATE, encoding="utf-8"))
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d/ping" % st["port"])
        req.add_header("X-Token", st.get("token", ""))
        with urllib.request.urlopen(req, timeout=0.5) as r:
            if r.status == 200:
                live_root = json.loads(r.read().decode("utf-8") or "{}").get("root")
                if live_root is None:
                    _log("已有实例在 %s 但不自报 root（旧版），拒绝复用，本进程另起"
                         % st.get("port"))
                    return None
                if _root_key(live_root) != _root_key(ROOT):
                    _log("已有实例在 %s 但在服务别的库（%s ≠ 本库 %s），拒绝复用"
                         % (st.get("port"), live_root, ROOT))
                    return None
                return st["port"]
    except Exception:
        pass
    # ping 失败 ≠ 进程已死：daemon 先 listening 后 warmup，warmup 窗口内 ping 必超时。
    # 仅当 STATE 记的 pid **确已消失**，才认定陈旧残留并清理；进程仍在就保留，交给 main()
    # 按新事实覆盖重写。（与客户端 _reuse_state 同一判据，避免两侧语义漂移。）
    try:
        _st_pid = st.get("pid") if isinstance(st, dict) else None
        _st_port = st.get("port") if isinstance(st, dict) else "?"
    except Exception:
        _st_pid, _st_port = None, "?"
    if _st_pid and _pid_alive(_st_pid):
        _log("已有实例在 %s 但 ping 失败（进程仍在，可能正 warmup），保留其 STATE"
             % _st_port)
        return None
    try:
        if os.path.exists(STATE):
            os.remove(STATE)
            _log("检测到陈旧 STATE（进程已不在），已清理残留")
    except Exception:
        pass
    return None


def _ping_state(path, timeout=0.5):
    """读 STATE → ping → 返回活进程自报的 (status_ok, root)。仅用于一次性回收旧实例。"""
    try:
        st = json.load(open(path, encoding="utf-8"))
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d/ping" % st["port"])
        req.add_header("X-Token", st.get("token", ""))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
            return True, body.get("root"), st
    except Exception:
        return False, None, None


def _reap_legacy():
    """一次性回收升级前遗留的单实例 STATE 与那个旧 daemon（4.9.13 起 STATE 按库分隔）。

    不回收的后果：旧 daemon 没人再用，却因默认 `IDLE_SECONDS=0`（永不离线）一直占着
    端口与模型内存，用户在任务管理器里会看到两个 keeper 进程。

    分寸（宁可留着，也不替别的库做决定）：
    - 旧 STATE 指向的进程已死 → 只删陈旧文件；
    - 活着且自报 root == 本库 → 它是本库的陈旧孪生，`/quit` 请它退出（之后本进程接管）；
    - 活着但自报**他库**、或旧版不回 root → 原样留着，本进程只当没看见。
    """
    if not os.path.exists(LEGACY_STATE):
        return
    alive, legacy_root, st = _ping_state(LEGACY_STATE)
    if not alive:
        try:
            os.remove(LEGACY_STATE)
            _log("清理升级前遗留的陈旧 STATE（进程已不在）")
        except Exception:
            pass
        return
    if legacy_root is None or _root_key(legacy_root) != _root_key(ROOT):
        _log("升级前遗留的 daemon 仍在（root=%s），不属本库，保留不动" % legacy_root)
        return
    try:
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:%d/quit" % st["port"],
            headers={"X-Token": st.get("token", "")}), timeout=3)
        _log("旧版 daemon（单实例 STATE）服务本库 → 已请其退出，本进程接管")
    except Exception as e:
        _log("回收旧版 daemon 失败（不影响本次启动）: %s" % e)


def main():
    live = _already_running()
    if live is not None:
        _log("已有实例在 %d，本进程退出" % live)
        sys.exit(0)
    # 升级收尾：回收 ≤4.9.12 那种「全库共用一个 STATE」时代的遗留（见 `_reap_legacy`）
    _reap_legacy()
    # 日志轮转：超阈值则截断，避免 daemon.log 无限增长残留
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX_BYTES:
            open(LOG, "w", encoding="utf-8").close()
            _log("daemon.log 超过 %d 字节，已轮转截断" % LOG_MAX_BYTES)
    except Exception:
        pass
    # 注册优雅退出（kill -TERM / Ctrl-C 均清理运行态残留）
    try:
        signal.signal(signal.SIGTERM, _graceful_exit)
        signal.signal(signal.SIGINT, _graceful_exit)
        atexit.register(_cleanup_runtime)
    except Exception:
        pass
    port = _free_port()
    global _PORT
    _PORT = port
    # 状态目录可能由 env 指定（如门禁沙箱）且尚未创建——先确保它在，否则 STATE 落不了盘，
    # 客户端会一直等内容到超时（表现为「daemon 起不来」）。
    try:
        _sd = os.path.dirname(STATE)
        if _sd and not os.path.isdir(_sd):
            os.makedirs(_sd, exist_ok=True)
    except OSError:
        pass
    with open(STATE, "w", encoding="utf-8") as _sf:
        json.dump({"port": port, "token": TOKEN, "pid": os.getpid(),
                   "started": time.time(), "root": ROOT}, _sf)
    try:
        os.chmod(STATE, 0o600)  # P1-1：token 落盘仅属主可读写，防本机其他用户/进程读取
    except OSError:
        pass
    threading.Thread(target=warmup, daemon=True).start()

    def watcher():
        if IDLE_SECONDS <= 0:
            return
        while True:
            time.sleep(30)
            if time.time() - _last["t"] > IDLE_SECONDS:
                _log("空闲 %ds，清理运行态后退出" % IDLE_SECONDS)
                _cleanup_runtime()
                os._exit(0)

    threading.Thread(target=watcher, daemon=True).start()
    _log("listening 127.0.0.1:%d backend-expected=fastembed idle=%s" % (port, IDLE_SECONDS))
    # 极简单线程轮询服务器（只读、低并发，单线程足够；用 threading 让 warmup/watcher 并行）
    import select
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(8)
    sock.settimeout(1.0)
    while True:
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        try:
            _Handler(conn, ("127.0.0.1",), None).handle()
        except Exception as e:
            _log("handler err: %s" % e)
        finally:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
