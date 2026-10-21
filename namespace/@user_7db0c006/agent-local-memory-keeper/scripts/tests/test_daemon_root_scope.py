# -*- coding: utf-8 -*-
"""STATE 按**记忆库**分隔 + 复用前核对库归属（客户端侧）。

背景（实锤）：
    `_ensure_daemon()` 曾只读单一 `.daemon.json` 并 `_ping` 探活就复用 → 已有 daemon
    服务于库 A 时，对库 B 的请求会**复用同一个** daemon：STATE.root 仍是 A，召回/写入
    全打到库 A。表现极其隐蔽：不报错，只是「记不住 / 想不起来」。
    更坏的推论：只在复用前加 root 校验也不够——两个库的客户端会反复覆盖同一份 STATE，
    谁也认不下对方，于是互相拒绝、反复重启（抖动）。

修复：① STATE 名带**库指纹**（每个库各持一份状态）；② 复用前向**活进程**核对 root，
    而不是信 STATE 里的纸面记录（端口被别人占用时，纸面记录恰恰是错的那方）；
    ③ 活进程不报 root（≤4.9.12 的 daemon）→ fail-closed 拒用。

核心断言：
    A. 两侧 `_root_key` 是**同一套算法**（直接跑两份源码里的真实实现比对，不是各抄一份）；
    B. 同一目录的书写差异（大小写 / 尾分隔符 / 斜杠方向）落到同一指纹；
    C. 不同库 → 不同 STATE 文件名；
    D. `_reuse_state` 正向复用同库，负向拒他库 / 拒不报 root / 拒死端口；
    E. 库选取按**当次** env 现算（不用 import 期快照，防两侧指纹打架）。
"""
import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/
SKILL = os.path.dirname(HERE)
DAEMON_DIR = os.path.join(SKILL, "keeper_daemon")
if DAEMON_DIR not in sys.path:
    sys.path.insert(0, DAEMON_DIR)
import keeper_recall_client as C  # noqa: E402  （轻量：不 import memory_ops）

CLIENT_SRC = os.path.join(DAEMON_DIR, "keeper_recall_client.py")
DAEMON_SRC = os.path.join(DAEMON_DIR, "daemon.py")


def _load_root_key(path):
    """取出该文件里 `_root_key` 的**真实实现**并 exec 出来。

    刻意不在这里另抄一份算法：抄一份的"一致性检查"是自证，改坏一边也照样通过。
    """
    src = io.open(path, encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_root_key":
            ns = {"os": os, "hashlib": __import__("hashlib")}
            exec(ast.get_source_segment(src, node), ns)
            return ns["_root_key"]
    raise AssertionError("未找到 `_root_key`（改名了？本测试需同步更新）: %s" % path)


class _FakeDaemon:
    """最小假 daemon：/ping 按需自报 root（None = 旧版形态）。

    与 test_daemon_residual_cleanup.py 里的同名类同构（两处各自可单跑，刻意不互相 import）。
    """

    def __init__(self, root_marker):
        self.root = root_marker
        outer = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = {"ok": True, "backend": "lexical"}
                if outer.root is not None:
                    body["root"] = outer.root
                raw = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), _H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        try:
            self.srv.shutdown()
            self.srv.server_close()
        except Exception:
            pass


class RootKeyTest(unittest.TestCase):
    """A–B：指纹算法与归一化。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_roots_key_")

    def test_two_modules_share_one_algorithm(self):
        """🔴 客户端与守护进程必须算出同一指纹（不一致 = 永远认不出自己起的 daemon）。"""
        kc, kd = _load_root_key(CLIENT_SRC), _load_root_key(DAEMON_SRC)
        store = os.path.join(self.tmp, "AI记忆")
        for cand in (store, store + os.sep, store.upper(), store.replace(os.sep, "/")):
            self.assertEqual(kc(cand), kd(cand),
                             "两侧对 %r 的指纹不一致：客户端 %s / daemon %s"
                             % (cand, kc(cand), kd(cand)))
        self.assertEqual(kc(store), kd(store + os.sep),
                         "书写差异也不该让两侧分道扬镳")

    def test_aliases_of_same_dir_share_key(self):
        k = _load_root_key(CLIENT_SRC)
        store = os.path.join(self.tmp, "store")
        variants = [store, store + os.sep, store.replace(os.sep, "/")]
        if os.name == "nt":
            variants.append(store.upper())      # 路径大小写只在 Windows 上等价
        keys = {k(v) for v in variants}
        self.assertEqual(len(keys), 1,
                         "同一目录的书写差异必须归一：%s" % sorted(keys))

    def test_different_dirs_differ(self):
        k = _load_root_key(CLIENT_SRC)
        a = os.path.join(self.tmp, "storeA")
        b = os.path.join(self.tmp, "storeB")
        self.assertNotEqual(k(a), k(b), "不同库不得共用同一份 STATE 名")
        self.assertRegex(k(a), r"^[0-9a-f]{12}$", "指纹形态是 12 位 hex（两侧共用）")


class StatePathPerRootTest(unittest.TestCase):
    """C + E：STATE 按库分隔、库按当次 env 现算。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_roots_state_")
        self._old = os.environ.get("AI_MEMORY_STORE")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("AI_MEMORY_STORE", None)
        else:
            os.environ["AI_MEMORY_STORE"] = self._old

    def test_state_file_per_store(self):
        a, b = os.path.join(self.tmp, "A"), os.path.join(self.tmp, "B")
        self.assertNotEqual(C._state_path(a), C._state_path(b),
                            "库 A / 库 B 必须各持一份 STATE，否则互相覆盖 → 抖动")
        self.assertEqual(os.path.dirname(C._state_path(a)), C.HOME,
                         "STATE 仍落在（可重定向的）状态目录里")
        self.assertNotEqual(os.path.basename(C._state_path(a)), ".daemon.json",
                            "不得退回单实例命名")

    def test_current_root_follows_env_at_call_time(self):
        """🔴 库要**当次现算**：STATE 走 import 期快照 + 子进程走 env 现值 = 指纹打架。"""
        a, b = os.path.join(self.tmp, "A"), os.path.join(self.tmp, "B")
        os.environ["AI_MEMORY_STORE"] = a
        self.assertEqual(os.path.normcase(C._current_root()), os.path.normcase(a))
        os.environ["AI_MEMORY_STORE"] = b
        self.assertEqual(os.path.normcase(C._current_root()), os.path.normcase(b),
                         "env 改了之后必须立刻生效（不能用 import 期快照）")


class ReuseStateTest(unittest.TestCase):
    """D：复用判据 = 活着 **且** 服务本库。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_roots_reuse_")
        self.fakes = []

    def tearDown(self):
        for f in self.fakes:
            f.stop()

    def _fake(self, root_marker):
        f = _FakeDaemon(root_marker)
        self.fakes.append(f)
        return f

    def _write(self, port, token="tok", root=None, name="st.json", pid=None):
        p = os.path.join(self.tmp, name)
        body = {"port": port, "token": token}
        if root is not None:
            body["root"] = root
        if pid is not None:
            body["pid"] = pid
        with open(p, "w", encoding="utf-8") as f:
            json.dump(body, f)
        return p

    def _store(self, name="store"):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d

    def test_reuses_same_root(self):
        """正向对照：同库必须复用（否则下面几条负向断言可能恒真）。"""
        store = self._store()
        f = self._fake(store)
        st = self._write(f.port, root=store)
        self.assertEqual(C._reuse_state(st, store), (f.port, "tok"),
                         "同库活实例必须复用")

    def test_rejects_foreign_root(self):
        """🔴 核心负向：活着的 daemon 在服务别的库 → 绝不复用。"""
        mine, other = self._store("mine"), self._store("other")
        f = self._fake(other)
        st = self._write(f.port, root=other)
        self.assertIsNone(C._reuse_state(st, mine),
                          "库 A 的 daemon 不得被库 B 复用（否则静默读错库）")

    def test_rejects_when_live_daemon_reports_no_root(self):
        """旧版 daemon 不回 root → 拒用：纸面 root 不能替代活进程的自述。"""
        mine = self._store()
        f = self._fake(None)
        st = self._write(f.port, root=mine)     # 文件里写着本库，活进程却不自报
        self.assertIsNone(C._reuse_state(st, mine),
                          "活进程不自报 root 时必须拒用（fail-closed）")

    def test_rejects_dead_port(self):
        store = self._store()
        st = self._write(1, root=store)          # 端口 1 必连不上
        self.assertIsNone(C._reuse_state(st, store), "进程已死不得复用")

    def test_dead_state_is_cleaned_up(self):
        """🔴 4.9.19：ping 失败（进程已死）时必须**清理陈旧 STATE**，不留在磁盘上。

        旧实现只 return None、不删除 → 陈旧文件长期残留：客户端每轮都要白等一次 ping
        超时；端口稍后被别的服务复用时还会被反复试探。daemon 侧早有同样清理，客户端侧
        （热路径，每轮注入都读它）此前漏了。
        """
        store = self._store()
        st = self._write(1, root=store)          # 端口 1 必连不上 = 死实例残留
        self.assertIsNone(C._reuse_state(st, store))
        self.assertFalse(os.path.exists(st),
                         "陈旧 STATE（进程已死）应被当场清理，而非长期残留")

    def test_live_foreign_root_state_not_deleted(self):
        """分寸边界：活实例（即使服务他库）不算"死残留"，不得删 STATE。

        删了会让本库下轮重新起 daemon（多此一举）；活着 = 不是「不自失效」要治的场景。
        """
        mine, other = self._store("mine"), self._store("other")
        f = self._fake(other)
        st = self._write(f.port, root=other)
        self.assertIsNone(C._reuse_state(st, mine))
        self.assertTrue(os.path.exists(st),
                        "活实例不算死残留：STATE 必须保留（清理只针对 ping 失败）")

    def test_missing_state_returns_none(self):
        store = self._store()
        self.assertIsNone(C._reuse_state(os.path.join(self.tmp, "nope.json"), store))

    def test_corrupt_state_returns_none(self):
        store = self._store()
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        self.assertIsNone(C._reuse_state(p, store), "坏 STATE 必须当场放弃，而不是抛异常")


class BusyDaemonStateGuardTest(unittest.TestCase):
    """🔴 4.9.19 二次修复：**ping 失败 ≠ 进程已死**。

    背景（本机实测复现，用户提问被 30s 钩子超时拦掉）：
        daemon 是**先 listening、后 warmup**（实测 warmup 0.8~1.0s，见 daemon.log 的
        `listening` → `warmup ok` 两行）。warmup 窗口内端口已在听、但 handler 阻塞在模型
        加载上 → 0.5s 的 ping **必然超时**。上一版 `_reuse_state` 把「ping 失败」直接当成
        「进程已死」→ 当场删 STATE → 客户端**亲手毁掉自己刚 spawn 的 daemon 的会合点**；
        且客户端删完不补写（daemon 侧会补写，故 daemon 侧无此害）→ **不自愈**：之后每轮
        轮询都读到「文件不存在」→ 白等满 DAEMON_START_TIMEOUT(30s) → 钩子超 30s 被掐死
        （实测 UserPromptSubmit 31.1s / SessionStart 60.7s）。
    正确判据：STATE 里记的 `pid` 是否**真的存活**（daemon.py 写 STATE 时已带 pid）。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_busy_state_")
        self.fakes = []

    def tearDown(self):
        for f in self.fakes:
            f.stop()

    def _fake(self, root_marker):
        f = _FakeDaemon(root_marker)
        self.fakes.append(f)
        return f

    def _write(self, port, token="tok", root=None, name="st.json", pid=None):
        p = os.path.join(self.tmp, name)
        body = {"port": port, "token": token}
        if root is not None:
            body["root"] = root
        if pid is not None:
            body["pid"] = pid
        with open(p, "w", encoding="utf-8") as f:
            json.dump(body, f)
        return p

    @staticmethod
    def _dead_pid():
        """拿一个**确定已死**的 pid：起个短命子进程并等它退出。"""
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_busy_daemon_state_not_deleted_on_ping_timeout(self):
        """★ 回归锁：端口不可达但 **pid 存活**（= 正 warmup / 正忙）→ STATE 必须保留。

        这条挂了就说明「自毁会合点」复发：钩子又会白等 30s 被掐死。
        """
        store = os.path.join(self.tmp, "store")
        os.makedirs(store, exist_ok=True)
        st = self._write(1, root=store, pid=os.getpid())   # 端口 1 必连不上；pid 是本进程=活
        self.assertIsNone(C._reuse_state(st, store))
        self.assertTrue(os.path.exists(st),
                        "pid 仍存活 ⇒ 只是暂时不可达（warmup/忙），STATE 必须保留，"
                        "否则客户端自毁会合点 → 每轮白等 30s → 钩子被掐死")

    def test_dead_pid_state_is_deleted(self):
        """对照组：pid 确已消失 → 才算真陈旧残留，清理。"""
        store = os.path.join(self.tmp, "store")
        os.makedirs(store, exist_ok=True)
        st = self._write(1, root=store, pid=self._dead_pid())
        self.assertIsNone(C._reuse_state(st, store))
        self.assertFalse(os.path.exists(st),
                         "pid 已消失 ⇒ 真陈旧残留，应清理（否则残留文件长期躺盘）")

    def test_genuinely_dead_process_pid_helper(self):
        """`_pid_alive` 自身：本进程 True，已退出子进程 False。"""
        self.assertTrue(C._pid_alive(os.getpid()), "本进程必然存活")
        self.assertFalse(C._pid_alive(self._dead_pid()), "已退出的子进程必须判死")
        self.assertFalse(C._pid_alive(None), "无 pid ⇒ 判死（fail-closed）")
        self.assertFalse(C._pid_alive("not-a-pid"), "非法 pid ⇒ 判死，不抛异常")

    def test_start_timeout_leaves_headroom_under_hook_budget(self):
        """🔴 预算余量：客户端等待上限必须**严格小于**钩子 timeout，否则必然踩线被掐死。

        settings.json 里 keeper 的 SessionStart / UserPromptSubmit 钩子 timeout=30。
        """
        self.assertLess(C.DAEMON_START_TIMEOUT, 30.0,
                        "DAEMON_START_TIMEOUT 必须 < 钩子 timeout(30s)，否则零余量必踩线")
        self.assertGreaterEqual(30.0 - C.DAEMON_START_TIMEOUT, 10.0,
                                "至少要留 10s 余量给钩子自身逻辑 + 子进程启动开销")

    def test_both_sides_share_same_pid_judgement(self):
        """两侧同一把尺：daemon.py 也必须按 PID 判，而不是 ping 失败就删。"""
        for src, label in ((CLIENT_SRC, "client"), (DAEMON_SRC, "daemon")):
            tree = ast.parse(io.open(src, encoding="utf-8").read())
            names = {n.name for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)}
            self.assertIn("_pid_alive", names,
                          "%s 侧缺 _pid_alive（判据会漂移）" % label)

        dtree = ast.parse(io.open(DAEMON_SRC, encoding="utf-8").read())
        fn = next((n for n in ast.walk(dtree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_already_running"), None)
        self.assertIsNotNone(fn, "daemon.py 应有 _already_running")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_pid_alive", called,
                      "daemon._already_running 必须用 _pid_alive 兜底，不能 ping 失败就删 STATE")


if __name__ == "__main__":
    unittest.main()
