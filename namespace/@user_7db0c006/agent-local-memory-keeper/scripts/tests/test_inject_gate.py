# -*- coding: utf-8 -*-
"""
test_inject_gate.py — 锁定「会话启动钩子遵守 inject_enabled 开关」（方案 A，4.9.3）。

背景：
    改前 `hooks/session_start_keeper_inject.py` **完全不读** `inject_enabled` /
    `inject_daily_cap` / `inject_dedup`（这些开关的检查点只在 `mem_bridge.py`），
    而 SKILL.md 又承诺该键「默认关，靠显式 `retrieve`」——文档承诺与实现不符：
    只要钩子模式不是 `off`，每会话启动都无条件注入至多 TOP_N=5 条 / 1600 字符。

修复：在 `keeper_hook_common` 新增 `inject_enabled()`（env > store/config.json > 默认 False，
    fail-closed），钩子 `main()` 守门；未开启时直接 `_emit()` 空上下文返回。

核心断言（防回归）：
    A. 默认（无配置 / 显式 false）→ 钩子**不注入**任何上下文；
    B. `store/config.json` 的 `keeper.inject_enabled=true` → **注入**；
    C. env `KEEPER_INJECT_ENABLED=1` 优先级最高，无需改文件即可开启。
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)
for _p in (SKILL, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HOOK = os.path.join(SKILL, "hooks", "session_start_keeper_inject.py")
MEM_OPS = os.path.join(SCRIPTS, "memory_ops.py")

# 隔离钩子运行态产物：本模块会真的 spawn 源码树里的钩子脚本，若不隔离，
# `_session_inject.json` / `hook_audit.log` 会写回源码树 → 可能随发布包外泄。
# 门禁 `run_gate.py` 会统一注入该 env，这里做「手动单跑本模块」的兜底
# （setdefault：不覆盖门禁已设的值）。
os.environ.setdefault("KEEPER_HOOKS_DIR",
                      os.path.join(tempfile.gettempdir(), "keeper_gate_hooks"))


def _run_hook(store, env_extra=None):
    """跑一次会话启动钩子，返回注入的 additionalContext（无则为 ""）。

    ⚠️ session_id 必须**每次唯一**：钩子按 session 记「已注入过的记忆 id」，并把该
    记录**持久化**到 `KEEPER_HOOKS_DIR`（门禁沙箱，跨运行保留）。用固定 id 时，
    第二次及以后的运行会整批被去重拦下 → 输出空 → 断言假红。实测症状：门禁里
    随机 1~2 条失败、同一模块单跑却过（典型跨运行状态污染）。

    ⚠️ 同样必须声明 `KEEPER_RECALL_MODE=inprocess`：默认的 daemon 模式让本用例依赖
    一个**跨模块共享**的常驻进程（共用沙箱 + idle 45s + 首次 warmup 数秒），前驱模块
    残留的 daemon 会导致召回静默为空。这是「测试必须自己声明前提」的直接体现——
    依赖共享资源而不声明，就会得到顺序依赖型的间歇假红。
    """
    env = dict(os.environ)
    env["AI_MEMORY_STORE"] = store
    env["AI_MEM_EMBED_BACKEND"] = "lexical"  # 避免拉 90MB 模型
    # ⚠️ 必须声明免 daemon（与姊妹模块 test_inject_include_auto 一致）。默认 recall_mode
    # = daemon，而 daemon 是**跨模块共享**的常驻进程（门禁把 KEEPER_DAEMON_DIR 钉到共用
    # 沙箱、idle 45s 不退出），首次就绪还要 fastembed warmup 数秒。前驱模块留下的 daemon
    # 被复用/抢跑时，recall 静默返回空 entries → 钩子输出空上下文 → 首条正向用例假红。
    # 实测症状：单跑本模块 3/3 绿，全量门禁里间歇 1 条红。
    env["KEEPER_RECALL_MODE"] = "inprocess"
    env.pop("KEEPER_INJECT_ENABLED", None)
    env.update(env_extra or {})
    evt = json.dumps({"source": "startup", "cwd": store,
                      "session_id": "gate-test-%s" % uuid.uuid4().hex[:8]},
                     ensure_ascii=False)
    p = subprocess.run([sys.executable, HOOK], input=evt, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, timeout=180)
    out = (p.stdout or "").strip()
    if not out:
        return ""
    d = json.loads(out)
    return (d.get("hookSpecificOutput") or {}).get("additionalContext") or ""


def _set_cfg(store, value):
    """写 keeper.inject_enabled；value=None 表示删除配置文件。"""
    p = os.path.join(store, "store", "config.json")
    if value is None:
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"keeper": {"inject_enabled": value}}, f)


class InjectGateTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(HOOK):
            raise unittest.SkipTest("钩子文件不存在：%s" % HOOK)
        cls.store = tempfile.mkdtemp(prefix="keeper_inj_gate_")
        os.makedirs(os.path.join(cls.store, "store"), exist_ok=True)
        # 预置一条记忆，保证「开启时确实有东西可注入」
        r = subprocess.run([sys.executable, MEM_OPS, "deposit", "--root", cls.store,
                            "--summary", "注入守门测试记忆", "--body", "验证 inject_enabled 守门"],
                           capture_output=True,
                           env={**os.environ, "AI_MEM_EMBED_BACKEND": "lexical",
                                "KEEPER_RECALL_MODE": "inprocess"}, timeout=180)
        # 原实现静默忽略失败：预置记忆没落盘时，「无东西可注入」会伪装成断言失败，
        # 把环境问题误报成功能缺陷。这里 fail loud，并带上 stderr 便于定位。
        if r.returncode != 0:
            raise AssertionError(
                "setUpClass 预置记忆失败（rc=%s）：%s"
                % (r.returncode, (r.stderr or r.stdout or "")[-400:]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.store, ignore_errors=True)

    # ── A. 默认关 ──
    def test_default_off_no_config(self):
        _set_cfg(self.store, None)
        self.assertEqual(_run_hook(self.store), "",
                         "无 store/config.json 时必须默认不注入（fail-closed）")

    def test_default_off_explicit_false(self):
        _set_cfg(self.store, False)
        self.assertEqual(_run_hook(self.store), "",
                         "keeper.inject_enabled=false 时必须不注入")

    # ── B. 配置文件开启 ──
    def test_config_true_enables(self):
        _set_cfg(self.store, True)
        ctx = _run_hook(self.store)
        self.assertTrue(ctx, "keeper.inject_enabled=true 时必须注入上下文")
        self.assertIn("keeper", ctx)

    # ── C. env 优先级最高 ──
    def test_env_overrides_config_false(self):
        _set_cfg(self.store, False)
        self.assertTrue(_run_hook(self.store, {"KEEPER_INJECT_ENABLED": "1"}),
                        "env KEEPER_INJECT_ENABLED=1 应覆盖文件里的 false")

    def test_env_off_overrides_config_true(self):
        _set_cfg(self.store, True)
        self.assertEqual(_run_hook(self.store, {"KEEPER_INJECT_ENABLED": "0"}), "",
                         "env KEEPER_INJECT_ENABLED=0 应覆盖文件里的 true")


if __name__ == "__main__":
    unittest.main()
