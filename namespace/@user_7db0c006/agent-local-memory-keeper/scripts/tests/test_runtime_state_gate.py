# -*- coding: utf-8 -*-
"""test_runtime_state_gate.py — 锁定「测试/门禁不得把运行态产物写回源码树」（4.9.13）。

背景：
    钩子状态文件（hook_audit.log / _session_inject.json / ._dep_*.tmp）的落点由
    `keeper_hook_common.HOOKS_DIR` 决定，而它取自 `__file__`——**与 HOME/USERPROFILE
    无关**，所以「把 HOME 设到临时目录」这类隔离根本救不了它。测试又确实会 spawn
    源码树里的钩子脚本（test_inject_gate 跑 session_start_keeper_inject.py）→ 运行态
    文件必然写回源码树，进而可能随发布包外泄（`.daemon.json` 曾带着上一台机器的
    端口与本机 token 躺进待发布清单）。

修复（4.9.13）：
    1) `keeper_hook_common.HOOKS_DIR` 支持 env `KEEPER_HOOKS_DIR` 覆盖（未设时行为与旧版一致）；
    2) 🔴 `_DAEMON_HOME`（sys.path 锚点）**不跟随**该 env——否则会插进一个不存在的
       路径，直接把 keeper_recall_client 的 import 打断；
    3) `run_gate.py` 对每个测试模块统一注入该 env（一处收口）；
    4) `_async_deposit.py` 的 failed/ 落点共用同一开关；
    5) 新增静态闸门 `no_runtime_state_in_tree` 实扫源码树（修复前扫了必 flaky 假红）。

核心断言：
    A. env 生效 → HOOKS_DIR 指向临时目录（**子进程端到端**验证，不污染本进程）；
    B. 未设 env → 回退到源码树 hooks/（不改变默认行为）；
    C. 🔴 `_DAEMON_HOME` 恒指向真实 keeper_daemon 且该目录存在；
    D. run_gate 的沙箱目录可用（基线注入点）；
    E. 闸门：残留 → FAIL；干净 / 真源码文件 → PASS（防误杀）。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SKILL_ROOT = os.path.dirname(HERE)                                   # 技能根
sys.path.insert(0, HERE)
import verify_claims as vc  # noqa: E402

_PROBE_CODE = (
    "import sys, os, json;"
    "sys.path.insert(0, os.path.join(%r, 'hooks'));"
    "import keeper_hook_common as C;"
    "print(json.dumps({'hooks_dir': C.HOOKS_DIR,"
    " 'daemon_home': C._DAEMON_HOME,"
    " 'daemon_is_dir': os.path.isdir(C._DAEMON_HOME)}))"
) % SKILL_ROOT


_DAEMON_PROBE_CODE = (
    "import sys, os, json;"
    "sys.path.insert(0, os.path.join(%r, 'keeper_daemon'));"
    "import keeper_recall_client as K;"
    "print(json.dumps({'state': K.STATE, 'daemon': K.DAEMON}))"
) % SKILL_ROOT


def _run_probe(code, env_extra=None):
    """在子进程里跑探针并解析其 JSON 输出。端到端，且不污染本进程的 env。"""
    env = dict(os.environ)
    env["AI_MEM_EMBED_BACKEND"] = "lexical"
    for k, v in (env_extra or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    p = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=120)
    out = (p.stdout or "").strip().splitlines()
    if not out:
        raise AssertionError("探针无输出；stderr=%s" % (p.stderr or "")[:400])
    return json.loads(out[-1])


def _probe(env_extra=None):
    return _run_probe(_PROBE_CODE, env_extra)


def _probe_daemon(env_extra=None):
    return _run_probe(_DAEMON_PROBE_CODE, env_extra)


def _nc(p):
    return os.path.normcase(os.path.abspath(p))


class HookStateIsolationTest(unittest.TestCase):
    """A–D：env 开关的实际生效面与「不该跟着走」的边界。"""

    def test_env_redirects_hooks_dir(self):
        tmp = tempfile.mkdtemp(prefix="keeper_hooksdir_")
        d = _probe({"KEEPER_HOOKS_DIR": tmp})
        self.assertEqual(_nc(d["hooks_dir"]), _nc(tmp),
                         "设了 KEEPER_HOOKS_DIR 后 HOOKS_DIR 必须跟随（否则运行态仍写源码树）")

    def test_default_falls_back_to_skill_tree(self):
        d = _probe({"KEEPER_HOOKS_DIR": None})
        self.assertEqual(_nc(d["hooks_dir"]), _nc(os.path.join(SKILL_ROOT, "hooks")),
                         "未设 env 时必须回退源码树 hooks/（不得改变默认行为）")

    def test_daemon_home_does_not_follow_env(self):
        """🔴 关键设计点：_DAEMON_HOME 是 sys.path 锚点，必须锚真实代码位置。"""
        tmp = tempfile.mkdtemp(prefix="keeper_hooksdir_")
        d = _probe({"KEEPER_HOOKS_DIR": tmp})
        self.assertEqual(_nc(d["daemon_home"]), _nc(os.path.join(SKILL_ROOT, "keeper_daemon")),
                         "_DAEMON_HOME 不得跟随 KEEPER_HOOKS_DIR —— 跟随会插进不存在的 "
                         "sys.path 条目，直接打断 keeper_recall_client 的 import")
        self.assertTrue(d["daemon_is_dir"], "锚点目录必须真实存在")

    def test_daemon_state_redirects_but_daemon_path_is_fixed(self):
        """daemon 侧同一开关：状态落点可重定向，代码定位（DAEMON）必须锚真实位置。

        STATE 名带**库指纹**（`.daemon-<12位hex>.json`），故这里只锁「落在隔离目录里、
        且不是旧的无指纹名」；指纹算法两侧一致由 test_daemon_root_scope 锁死。
        """
        tmp = tempfile.mkdtemp(prefix="keeper_daemondir_")
        d = _probe_daemon({"KEEPER_DAEMON_DIR": tmp})
        self.assertEqual(_nc(os.path.dirname(d["state"])), _nc(tmp),
                         "设了 KEEPER_DAEMON_DIR 后 STATE 必须跟随，否则状态文件"
                         "（含端口与 token）仍会写回源码树")
        self.assertRegex(os.path.basename(d["state"]),
                         r"^\.daemon-[0-9a-f]{12}\.json$",
                         "STATE 名必须带库指纹（按库分隔），不能退回单实例命名")
        self.assertEqual(_nc(d["daemon"]),
                         _nc(os.path.join(SKILL_ROOT, "keeper_daemon", "daemon.py")),
                         "DAEMON 必须锚真实代码位置——跟随隔离目录后会找不到 daemon.py")

    def test_daemon_state_default_goes_to_user_runtime_dir(self):
        """4.9.19：未设 env 时，STATE 默认落**用户运行态目录**，🔴 绝不落源码树。

        旧默认是 `_HERE`（= 代码目录）：凡从源码树直接运行（开发/测试/手动验证），
        都会把 `.daemon-<库指纹>.json`（含端口与本机 token）与 daemon.log 写回仓库
        —— 既污染源码树、又可能随发布包外泄，还让静态闸门 no_runtime_state_in_tree
        持续假红。现默认改为 `<WB_HOME>/keeper_daemon`：部署态 `_HERE` 恰等于该值
        （零行为变化），源码态则不再写回仓库。
        """
        d = _probe_daemon({"KEEPER_DAEMON_DIR": None})
        runtime_dir = os.path.join(os.path.expanduser("~"), ".workbuddy", "keeper_daemon")
        self.assertEqual(_nc(os.path.dirname(d["state"])), _nc(runtime_dir),
                         "未设 env 时必须回退用户运行态目录 <WB_HOME>/keeper_daemon")
        self.assertNotEqual(_nc(os.path.dirname(d["state"])),
                            _nc(os.path.join(SKILL_ROOT, "keeper_daemon")),
                            "🔴 默认落点**不得**是源码树 keeper_daemon/（状态文件会写回仓库）")
        self.assertNotEqual(os.path.basename(d["state"]), ".daemon.json",
                            "不得退回 ≤4.9.12 的单实例命名（会跨库串味）")


class GateSandboxTest(unittest.TestCase):
    """D：run_gate 的收口点必须可用。"""

    def test_gate_sandbox_dir_exists(self):
        import run_gate
        d = run_gate._sandbox_hooks_dir()
        self.assertTrue(os.path.isdir(d), "门禁沙箱目录应被创建：%s" % d)
        self.assertIn("KEEPER_HOOKS_DIR", run_gate._SAFE_ENV_BASELINE,
                      "门禁基线必须注入 KEEPER_HOOKS_DIR（一处收口所有测试模块）")

    def test_hooks_dir_not_in_leak_checked(self):
        """KEEPER_HOOKS_DIR 允许被模块临时改写，不该计入越权告警。"""
        import run_gate
        self.assertNotIn("KEEPER_HOOKS_DIR", run_gate._LEAK_CHECKED)


class RuntimeStateInTreeGateTest(unittest.TestCase):
    """E：闸门正反双向。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_state_")

    def _touch(self, rel):
        p = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")

    def test_clean_tree_passes(self):
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertTrue(r["ok"], "无运行态产物必须 PASS；实际: %s" % r.get("error"))

    def test_source_file_not_flagged(self):
        self._touch("hooks/keeper_hook_common.py")
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertTrue(r["ok"], "真源码文件不得被误判为运行态产物")

    def test_hook_audit_log_fails(self):
        self._touch("hooks/hook_audit.log")
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertFalse(r["ok"], "源码树残留 hook_audit.log 必须 FAIL")
        self.assertIn("hook_audit.log", r["error"])

    def test_session_inject_json_fails(self):
        self._touch("hooks/_session_inject.json")
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertFalse(r["ok"], "源码树残留 _session_inject.json 必须 FAIL")

    def test_daemon_state_fails(self):
        self._touch("keeper_daemon/.daemon.json")
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertFalse(r["ok"],
                         "守护进程运行态（含端口/token）残留必须 FAIL —— 这是最该拦住的一类")

    def test_fingerprinted_daemon_state_fails(self):
        """按库指纹命名的新 STATE 也必须被逮住（判据用通配，不写死单个名字）。"""
        self._touch("keeper_daemon/.daemon-0f1e2d3c4b5a.json")
        r = vc._static_no_runtime_state_in_tree(self.root)
        self.assertFalse(r["ok"], "按库命名的 daemon STATE 残留必须 FAIL（通配要覆盖它）")
        self.assertIn(".daemon-0f1e2d3c4b5a.json", r["error"])

    def test_real_skill_root_passes(self):
        """正向：当前源码树必须干净（门禁跑完后的真实判据）。"""
        r = vc._static_no_runtime_state_in_tree(SKILL_ROOT)
        self.assertTrue(r["ok"], "源码树应干净；实际: %s" % r.get("error"))


if __name__ == "__main__":
    unittest.main()
