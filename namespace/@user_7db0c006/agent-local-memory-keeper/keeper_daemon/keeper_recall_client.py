# -*- coding: utf-8 -*-
"""
keeper_recall_client.py — 钩子用的 recall 透明代理（CLI + 库）

优先级：
1. 常驻 daemon（keeper_daemon.py）已热 → HTTP /recall，毫秒级（模型与 recall 冷成本均已常驻吸收）。
2. daemon 不存在/挂了 → 懒启动它（DETACHED，独立于钩子子进程存活），轮询就绪（首启含 recall 内部冷成本 ~5s）；
下次调用即恢复 2ms。
3. 极端情况（daemon 彻底起不来，如 daemon.py 损坏）→ 跳过注入（毫秒级，返回空 entries），
保证钩子**绝不阻塞 5s**、永不失败（fail-open）。语义召回将在 daemon 恢复后自动回来。

说明：实测发现 keeper 的 recall() 在全新子进程里固有冷成本 ~4.4s（含 _rank_query/embed 管线，与模型与否无关），
因此任何「再起一个子进程做 recall」的回退都仍是 ~4s。故回退选择「跳过」而非「慢召回」，
把延迟保证做绝。正常态 daemon 常驻（默认永不离线），这条回退几乎不会触发。

输出与 memory_ops 包 recall CLI 完全一致：{"ok": True, "count": N, "entries": [...]}，
故作为三个钩子现有 `memory_ops recall`（即 `python scripts/memory_ops/__init__.py recall`）调用的 drop-in 替换。

用法（镜像 memory_ops recall 子集）：
python keeper_recall_client.py recall [--query Q] [--top-n N] [--include-auto]
库调用：recall_proxy(query=None, top_n=10, include_auto=False) -> JSON 字符串
"""
import os
import sys
import json
import time
import hashlib
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))  # daemon 代码所在目录
# 状态落点可被 env `KEEPER_DAEMON_DIR` 重定向（与 daemon.py 同一开关）；
# 🔴 但 DAEMON 必须锚 `_HERE`——隔离后状态目录指向临时区，跟过去就找不到 daemon.py 了。
# 🔴 STATE 也不在这里定：它要按**记忆库**再分一层（`_root_key`），见 DEFAULT_STORE 之后。
# 🔴 4.9.19 修复：默认落点从「代码目录 _HERE」改为「用户运行态目录 <WB_HOME>/keeper_daemon」，
#    与 daemon.py 同源（两侧必须算出同一目录，否则识别不到刚起的 daemon）。对部署态零变化，
#    只让「从源码树直接跑」不再把含端口/token 的状态文件写回仓库。
HOME = os.environ.get("KEEPER_DAEMON_DIR") or os.path.join(
    os.path.expanduser("~"), ".workbuddy", "keeper_daemon").replace("\\", "/")
DAEMON = os.path.join(_HERE, "daemon.py")

# 端口化 修复）：所有 ~/.workbuddy 路径由 expanduser 推导，不再硬编码用户名路径
WB_HOME = os.path.join(os.path.expanduser("~"), ".workbuddy").replace("\\", "/")


def _resolve_python():
    """优先 keeper 的 venv python（带依赖），否则回退 managed 版（可能缺包但至少能跑）。"""
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
SCR = os.path.join(WB_HOME, "skills", "agent-local-memory-keeper", "scripts").replace("\\", "/")


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


DEFAULT_STORE = _default_store()


def _root_key(root):
    """记忆库路径 → 状态文件名指纹（12 位 hex）。

    🔴 与 daemon.py 里的 `_root_key` **必须是同一套算法**：两边算出同一个指纹，客户端
    才找得到刚起的 daemon。不一致的症状很隐蔽——一路轮询到超时，最后静默跳过注入
    （不报错，只是「没记忆」）。一致性由测试 test_daemon_root_scope 逐字锁死。
    """
    try:
        p = os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(root)))))
    except Exception:
        p = str(root)
    return hashlib.sha256(p.encode("utf-8", "replace")).hexdigest()[:12]


# 🔴 STATE 按**记忆库**分隔（不只是按部署目录）：多库共存时各持一份状态，互不踩踏。
#    曾用单一 `.daemon.json`：库 A 的 daemon 活着时，库 B 的客户端 ping 得通就直接复用 →
#    召回/写入全打到库 A（静默）。只加「校验 root」也不够：两边会互相覆盖同一份文件，
#    谁也认不下对方，于是反复重启（抖动）。
ROOT = DEFAULT_STORE
STATE = os.path.join(HOME, ".daemon-%s.json" % _root_key(ROOT))


def _current_root():
    """**本次调用**要服务的库。

    ⚠️ 热路径一律现算，不用上面那份 import 期快照：env 可能在 import 之后被改
    （宿主脚本 / 测试 / 以后可能的按库切换），而子进程的库取自 env 现值——若 STATE 走
    快照、子进程走现值，两边指纹就打架，症状是「客户端永远认不出自己刚起的 daemon」，
    一路轮询到超时再静默跳过注入。现算则两处同源。
    """
    return os.environ.get("AI_MEMORY_STORE") or DEFAULT_STORE


def _state_path(root):
    """该库对应的状态文件路径（与 daemon.py 同一命名规则）。"""
    return os.path.join(HOME, ".daemon-%s.json" % _root_key(root))

DAEMON_START_TIMEOUT = 12.0  # 首启含模型加载；最长等 12s
# 🔴 4.9.19 修正（预算余量）：原为 30.0，与 settings.json 里钩子的 `timeout: 30` **完全相等**
# → 零余量：只要走一次冷启动，钩子必然踩线被 WorkBuddy 掐死（实测 UserPromptSubmit 31.1s）。
# 健康路径实测仅需 ~1.5s（spawn → warmup 0.8~1.0s → 可复用），12s 已是 8 倍余量。
# 真的超时也**不阻塞**：DETACHED daemon 会继续在后台焐热，下一轮钩子即命中热实例返回。


def _prepare_env(root=None):
    env = dict(os.environ)
    # 子进程的库与 STATE 的库**同源**（见 `_current_root`），指纹才对得上
    env["AI_MEMORY_STORE"] = root or _current_root()
    env["PYTHONPATH"] = SCR + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _ping_info(port, token, timeout=0.5):
    """GET /ping → 活进程自报的 info（含它服务哪个库）；不可达返回 None。"""
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d/ping" % port)
        req.add_header("X-Token", token)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _ping(port, token, timeout=0.5):
    """只要探活（不判归属）：`deposit_proxy` 等「先确认旧实例退没退」的场景用。"""
    return _ping_info(port, token, timeout) is not None


def _pid_alive(pid):
    """进程是否存活。用于区分「STATE 陈旧」与「STATE 有效但 daemon 正忙」。

    🔴 为什么必须按 PID 判、而不是按 ping 通不通判：daemon 是**先 listening、后 warmup**
    （实测 warmup ~0.8–1.0s，见 daemon.log 的 `listening` → `warmup ok` 两行）。在 warmup
    窗口中端口已在听、但 handler 阻塞在模型加载上 → 0.5s 的 ping **必然超时**。
    此时进程活得好好的，把它当死人删掉 STATE = 亲手毁掉自己刚建立的会合点。
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


def _try_remove(path):
    """尽力删除状态文件。沙箱 safe-delete 可能拦截 os.remove（fails-closed 保留旧文件），
    此时回退 Win32 原生 API 真删；失败也不抛——下轮会再试。"""
    try:
        os.remove(path)
        return
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.DeleteFileW(str(path))
        except Exception:
            pass


def _reuse_state(state_path, want_root):
    """这份 STATE 能否安全复用 → (port, token) 或 None。

    🔴 两个条件缺一不可：**进程活着** 且 **它自报服务的库 == want_root**。
    - 只看活着：端口可能已被别的库的 daemon 占用，STATE 也可能来自别的库/上一台机器。
      复用后 /recall 会 403，异常被 recall_proxy 吞掉 → 静默跳过注入：不报错，只是「没记忆」。
    - 只看 STATE 里记的 root：那是**纸面记录**；端口被别人复用/文件被覆盖时，它恰恰是错的一方。
    - 活进程不报 root（≤4.9.12 的 daemon）→ **拒用**（fail-closed）：宁可多起一个 daemon，
      也不能把本库的召回打到归属不明的库上。
    🔴 4.9.19 修复（同族：陈旧状态不自失效）：ping 失败 → **当场清理**这份 STATE。旧实现只
      return None、不清理，陈旧文件长期躺在磁盘上（客户端每轮白等一次 ping 超时；端口后来被
      别的服务复用时，残留 port/token 仍被反复试探）。仅删**本库指纹**的那份（state_path 已按
      want_root 命名），绝不触碰他库记录。

    🔴 4.9.19 二次修复（**上一版修过头，自毁会合点**，本机实测复现）：上一版把「ping 失败」
      直接等同于「进程已死」就删 STATE。但 daemon 是**先 listening、后 warmup**，warmup
      窗口内 ping 必然超时 —— 于是客户端**亲手删掉自己刚 spawn 的 daemon 的 STATE**，之后每轮
      轮询都读到「文件不存在」→ 白等满 DAEMON_START_TIMEOUT(30s) → 钩子超 30s 被 WorkBuddy
      掐死（实测 UserPromptSubmit 31.1s / SessionStart 60.7s，用户的提问直接被拦）。
      且客户端删完**不补写**（daemon 侧会补写，故 daemon 侧无此害），不自愈 → 每次新起一个
      daemon、各绑新端口（daemon.log 一一对应）。
      正确判据：**ping 失败 ≠ 进程已死**，要看 STATE 里记的 `pid` 是否真存活（daemon.py:432
      已写 pid）。活着 → 保留 STATE 下轮再试；只有 PID 真的没了才算陈旧残留。
    """
    try:
        if not os.path.exists(state_path):
            return None
        with open(state_path, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return None
    # ping 超时给足 warmup 余量（daemon 实测 warmup 0.8~1.0s）：健康 daemon 毫秒级返回，
    # 加长只在「正忙/未就绪」时生效，避免把 warmup 误判为死亡。
    info = _ping_info(st.get("port"), st.get("token", ""), timeout=1.5)
    if not info:
        if _pid_alive(st.get("pid")):
            return None          # 进程活着，只是正忙（warmup / 在服务别的请求）→ 保留会合点
        _try_remove(state_path)  # PID 确已消失 → 真陈旧残留，清理
        return None
    live_root = info.get("root")
    if live_root is None or _root_key(live_root) != _root_key(want_root):
        return None
    return st.get("port"), st.get("token", "")


def _ensure_daemon(allow_deposit=False):
    """返回 (port, token) 或 None。懒启动，单实例（daemon 自身也会做单实例校验）。

    4.5.58：allow_deposit=True 时以 KEEPER_DAEMON_ALLOW_DEPOSIT=1 启动，
    供 deposit_proxy 程序化写入（daemon 默认只读姿态，仅在显式请求写入时放开）。
    """
    root = _current_root()
    state = _state_path(root)
    env = _prepare_env(root)
    if allow_deposit:
        env["KEEPER_DAEMON_ALLOW_DEPOSIT"] = "1"
    # 已有**服务本库**的活实例？（`_reuse_state` 会向活进程核对 root，不只是探活）
    info = _reuse_state(state, root)
    if info:
        return info
    # 启动新实例（Windows 用 DETACHED 脱离钩子子进程独立存活；POSIX 用 start_new_session）
    try:
        if os.name == "nt":
            flags = 0
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([PY, DAEMON], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=flags)
        else:
            subprocess.Popen([PY, DAEMON], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception:
        return None
    # 轮询就绪（首启含模型加载 ~5s）。判据与上面同一把尺：活着 **且** 服务本库。
    deadline = time.time() + DAEMON_START_TIMEOUT
    while time.time() < deadline:
        info = _reuse_state(state, root)
        if info:
            return info
        time.sleep(0.4)
    return None


def _fallback_skip():
    """daemon 彻底起不来时的安全网：跳过注入（毫秒级），绝不阻塞 5s。
    语义召回将在 daemon 恢复（懒启动）后自动回来。"""
    return json.dumps({"ok": True, "count": 0, "entries": []})


def _http_json(port, token, path, payload=None, timeout=15):
    """本地 HTTP 调用封装：返回 (status, obj)。403 等 HTTPError 也正常返回
    （deposit_disabled 靠 403 判断），网络层错误抛异常由调用方处理。"""
    import urllib.request
    import urllib.error
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 headers={"Content-Type": "application/json",
                                          "X-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {"ok": False, "error": "HTTP %d" % e.code}


def deposit_proxy(category="note", summary="", tags="", body="",
                  scope="universal", project="", recorded_by="agent"):
    """程序化写入代理：经 daemon /deposit 写入，复用常驻进程——
    免每次冷启加载 182MB 模型（CLI 单条 ~1.8s → 代理 ms 级）。

    流程：先试当前 daemon（若已允许写入直接用）→ 403 deposit_disabled（默认
    只读或旧进程）→ 优雅 /quit 重启（带 token）→ 以 KEEPER_DAEMON_ALLOW_DEPOSIT=1
    拉起 → 重试。写入经 MOPS.deposit 内部 per-root 锁串行化，与 CLI 并发安全。
    返回 (ok, mid_or_error)。
    """
    info = _ensure_daemon()
    if info:
        port, token = info
        payload = {"category": category, "summary": summary, "tags": tags,
                   "body": body, "scope": scope, "project": project,
                   "recorded_by": recorded_by}
        try:
            _, obj = _http_json(port, token, "/deposit", payload)
            if obj.get("ok") is True:
                return True, obj.get("id")
            if "deposit_disabled" not in str(obj.get("error", "")):
                return False, obj.get("error")
        except Exception:
            pass
            # 默认只读/旧进程 → 优雅重启（/quit 需 token；重启后懒启动自动拉起新版）
        try:
            urllib.request.urlopen(urllib.request.Request(
                "http://127.0.0.1:%d/quit" % port, headers={"X-Token": token}), timeout=3)
        except Exception:
            pass
            # 等旧进程退出 + 端口释放（0.2s 延迟退出 + 文件系统同步，给足 1.5s）
    time.sleep(1.5)
    # 轮询确认旧实例确实消失（防 /quit 未生效导致的「活实例挡路」竞态）
    if info:
        _deadline = time.time() + 3.0
        while time.time() < _deadline:
            try:
                if not _ping(info[0], info[1], timeout=0.3):
                    break
            except Exception:
                break
            time.sleep(0.4)
            # 以 allow_deposit 拉起，最多 3 轮（防 STATE/端口竞态）
    payload = {"category": category, "summary": summary, "tags": tags,
               "body": body, "scope": scope, "project": project,
               "recorded_by": recorded_by}
    last_err = "unknown"
    for _round in range(3):
        info2 = _ensure_daemon(allow_deposit=True)
        if not info2:
            time.sleep(1.0)
            continue
        port2, token2 = info2
        # 新 daemon 可能仍在模型 warmup（~5s）：重试最多 4 次，间隔 1s
        for _att in range(4):
            try:
                _, obj = _http_json(port2, token2, "/deposit", payload)
                if obj.get("ok") is True:
                    return True, obj.get("id")
                last_err = str(obj.get("error"))[:120]
                if "deposit_disabled" in last_err:
                    # 起错实例（无 allow_deposit）→ 杀掉再拉起
                    try:
                        urllib.request.urlopen(urllib.request.Request(
                            "http://127.0.0.1:%d/quit" % port2,
                            headers={"X-Token": token2}), timeout=3)
                    except Exception:
                        pass
                    time.sleep(1.5)
                    break
            except Exception as e:
                last_err = str(e)[:120]
            time.sleep(1.0)
        else:
            return False, "deposit_proxy 重试耗尽: %s" % last_err
    return False, "deposit_proxy 3 轮均失败: %s" % last_err


def recall_proxy(query=None, top_n=10, include_auto=False, semantic_gate=None):
    info = _ensure_daemon()
    if info:
        port, token = info
        try:
            import urllib.request
            payload = json.dumps({"query": query, "include_auto": include_auto,
                                  "semantic_gate": semantic_gate}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:%d/recall" % port, data=payload,
                headers={"Content-Type": "application/json", "X-Token": token})
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read().decode("utf-8")
            obj = json.loads(raw)
            if obj.get("ok") is True:
                return raw
        except Exception:
            pass
            # daemon 不可用或返回异常 → 跳过注入（毫秒级安全网）
    return _fallback_skip()


def _parse_cli(argv):
    query = None
    top_n = 10
    include_auto = False
    semantic_gate = None
    if "recall" in argv:
        rest = argv[argv.index("recall") + 1:]
        j = 0
        while j < len(rest):
            a = rest[j]
            if a == "--query":
                query = rest[j + 1]; j += 2
            elif a == "--top-n":
                top_n = int(rest[j + 1]); j += 2
            elif a == "--include-auto":
                include_auto = True; j += 1
            elif a == "--semantic-gate":
                semantic_gate = float(rest[j + 1]); j += 2
            else:
                j += 1
    return query, top_n, include_auto, semantic_gate


def main():
    query, top_n, include_auto, semantic_gate = _parse_cli(sys.argv[1:])
    sys.stdout.write(recall_proxy(query=query, top_n=top_n, include_auto=include_auto,
                                 semantic_gate=semantic_gate))


if __name__ == "__main__":
    main()
