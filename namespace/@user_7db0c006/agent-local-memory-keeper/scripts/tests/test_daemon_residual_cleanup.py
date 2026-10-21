# -*- coding: utf-8 -*-
"""守护进程 STATE 边界测试。

三组断言：
A. **残留清理**：陈旧 STATE（指向已死端口）在启动自检时被清理；优雅退出删除 STATE。
B. 🔴 **复用前必须核对库归属**：`_ping` 通过只证明「有个 daemon 活着」，不证明它服务于
   本库。修复前只探活不校验 root → 已有 daemon 服务于库 A 时，库 B 的请求被静默复用，
   召回/写入全打到库 A（不报错，只是「记不住 / 想不起来」）。
C. **升级回收**：≤4.9.12 的「全库共用一个 STATE」时代的遗留一次性收尾——仅当旧 daemon
   自报的 root 与本库一致才请它退出；他库或无法确认则不动它。

做法：不启动真守护进程（假 daemon 用最小 HTTP server 顶替），不触碰真实 ~/.workbuddy。
"""
import os
import sys
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

# 隔离运行态：本模块 import daemon 后，`_log()` 会写 `HOME/daemon.log`。
# 不隔离就会往源码树 keeper_daemon/ 里落运行态文件（手动单跑本模块时的坑）。
os.environ.setdefault("KEEPER_DAEMON_DIR",
                      os.path.join(tempfile.gettempdir(), "keeper_gate_daemon"))

for _p in (os.path.join(SKILL, "scripts"), os.path.join(SKILL, "keeper_daemon")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import daemon as D  # noqa: E402

# daemon.py 在 import 期把 AI_MEM_EMBED_BACKEND 钉成 fastembed（它的运行前提）。本模块
# 只验状态/复用判定、根本不加载模型，故**立刻还原**：否则门禁会报本模块「越权改动基线
# env」，且万一后续用例碰了 embedding 就会白拉 90MB 模型。
os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"

REAL_STATE = D.STATE
REAL_LEGACY = D.LEGACY_STATE


class _FakeDaemon:
    """最小假 daemon：/ping 按需自报 root（None = 旧版形态，不回 root），/quit 记账。"""

    def __init__(self, root_marker):
        self.root = root_marker
        self.quit_called = False
        outer = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/quit"):
                    outer.quit_called = True
                    raw = json.dumps({"ok": True}).encode("utf-8")
                else:
                    body = {"ok": True, "backend": "lexical"}
                    if outer.root is not None:
                        body["root"] = outer.root
                    raw = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):   # 静音
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), _H)
        self.port = self.srv.server_address[1]
        self._th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._th.start()

    def stop(self):
        try:
            self.srv.shutdown()
            self.srv.server_close()
        except Exception:
            pass


def _write_state(path, port, token="tok", root=None):
    body = {"port": port, "token": token, "pid": 999999, "started": 0}
    if root is not None:
        body["root"] = root
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_daemon_scope_")
        self._fakes = []

    def tearDown(self):
        D.STATE = REAL_STATE
        D.LEGACY_STATE = REAL_LEGACY
        for f in self._fakes:
            f.stop()

    def _fake(self, root_marker):
        f = _FakeDaemon(root_marker)
        self._fakes.append(f)
        return f

    def _state(self, name="st.json"):
        return os.path.join(self.tmp, name)


class ResidualCleanupTest(_Base):
    """A：残留清理（旧行为，防回归）。"""

    def test_stale_state_cleaned_on_already_running(self):
        st = self._state()
        _write_state(st, 1, root="/tmp/none")   # 端口 1 必连不上 = 手动 kill 残留
        D.STATE = st
        self.assertIsNone(D._already_running())
        self.assertFalse(os.path.exists(st), "陈旧 STATE 应被清理，而非残留")

    def test_cleanup_runtime_removes_state(self):
        st = self._state()
        with open(st, "w", encoding="utf-8") as f:
            f.write("{}")
        D.STATE = st
        D._cleanup_runtime()
        self.assertFalse(os.path.exists(st), "_cleanup_runtime 应删除 STATE")


class ReuseRequiresSameRootTest(_Base):
    """B：库归属核对——本次修复的核心。"""

    def test_reuses_live_daemon_of_same_root(self):
        """正向对照：同库活实例必须被复用（否则下面的负向断言可能恒真）。"""
        f = self._fake(D.ROOT)
        st = self._state()
        _write_state(st, f.port, root=D.ROOT)
        D.STATE = st
        self.assertEqual(D._already_running(), f.port,
                         "同库活实例必须复用；否则每次调用都白起一个新 daemon")

    def test_rejects_live_daemon_of_foreign_root(self):
        """🔴 负向：活着的 daemon 在服务**别的库** → 绝不复用（否则静默读错库）。"""
        f = self._fake(D.ROOT + "_other_store")
        st = self._state()
        _write_state(st, f.port, root=D.ROOT + "_other_store")
        D.STATE = st
        self.assertIsNone(D._already_running(),
                          "ping 通 ≠ 服务本库：他库的 daemon 不得被复用")

    def test_rejects_daemon_without_root_report(self):
        """🔴 旧版 daemon 不在 /ping 里回 root → fail-closed 拒用。

        纸面上的 root 字段不能替代证据：端口被别人占用时，纸面记录恰恰是错的一方。
        """
        f = self._fake(None)
        st = self._state()
        _write_state(st, f.port, root=D.ROOT)   # 文件里写着本库，活进程却不自报
        D.STATE = st
        self.assertIsNone(D._already_running(),
                          "活进程不自报 root 时必须拒绝复用（fail-closed）")


class LegacyReapTest(_Base):
    """C：升级回收 ≤4.9.12 的单实例 STATE。"""

    def test_quits_legacy_daemon_of_same_root(self):
        f = self._fake(D.ROOT)
        lp = self._state("legacy.json")
        _write_state(lp, f.port, root=D.ROOT)
        D.LEGACY_STATE = lp
        D._reap_legacy()
        self.assertTrue(f.quit_called, "服务本库的旧 daemon 应被请退（否则白占端口与内存）")

    def test_leaves_legacy_daemon_of_foreign_root(self):
        f = self._fake(D.ROOT + "_other_store")
        lp = self._state("legacy.json")
        _write_state(lp, f.port, root=D.ROOT + "_other_store")
        D.LEGACY_STATE = lp
        D._reap_legacy()
        self.assertFalse(f.quit_called, "别的库的 daemon 不替它做决定")
        self.assertTrue(os.path.exists(lp), "他库的 STATE 也不得删除（那是它的记录）")

    def test_removes_dead_legacy_state(self):
        lp = self._state("legacy.json")
        _write_state(lp, 1, root="/tmp/none")
        D.LEGACY_STATE = lp
        D._reap_legacy()
        self.assertFalse(os.path.exists(lp), "进程已不在的旧 STATE 应被清掉")


class CrossModuleAgreementTest(_Base):
    """值守两侧必须对**同一个库**算出同一份 STATE 文件名。

    不一致 = 客户端永远认不出刚起的 daemon（一路轮询到超时 → 静默跳过注入）。
    算法逐字一致的证明在 test_daemon_root_scope（直接跑两份源码实现比对），这里验
    「同一环境下两个模块各自算出来的路径确实相同」——端到端那一步。
    """

    def test_daemon_and_client_agree_on_state_name(self):
        import keeper_recall_client as C
        self.assertEqual(os.path.basename(D.STATE),
                         os.path.basename(C._state_path(D.ROOT)),
                         "daemon 与客户端对同一个库必须选中同一个 STATE 文件")
        self.assertEqual(os.path.dirname(D.STATE), os.path.dirname(C._state_path(D.ROOT)),
                         "两侧的状态目录也必须一致（同一个 KEEPER_DAEMON_DIR）")
        self.assertNotEqual(C._state_path(D.ROOT + "_x"), C._state_path(D.ROOT),
                            "换个库必须换一份 STATE（否则跨库互相覆盖）")


if __name__ == "__main__":
    unittest.main()
