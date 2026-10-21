# -*- coding: utf-8 -*-
"""test_inject_include_auto.py — 锁定「启动即注入」真能注入（4.9.19）。

背景（真 bug，本机实测复现）：
    `recall` **默认隔离** `auto_sourced` 项（未 `confirm` 的被动捕获/蒸馏记忆），
    而很多用户（含本机）库里的记忆**全部**来自自动捕获 —— 于是两个注入钩子
    （SessionStart / UserPromptSubmit）调 `C.recall(...)` 时不带 `include_auto`
    → **恒召回为空**：钩子注册齐全、`inject_enabled=true` 也放行，却没有任何内容可注入。
    本机实测：库内 25 条记忆 100% `auto_sourced=True`；`recall` 空、`--include-auto` 有结果；
    SessionStart 审计长期只见 `empty no entries`，修复后变 `inject entries=5`。

本测试三层：
    A. 门控函数 `inject_include_auto()` 的优先级（env > 配置块 > 默认 True）；
    B. 静态契约：两个钩子的召回调用**必须**带 `include_auto=C.inject_include_auto()`；
    C. 端到端：临时库 + 一条 auto 记忆 → 真跑 SessionStart 钩子 → 断言**确实注入了内容**。

A/C 用临时库 + `lexical` 后端 → 零第三方依赖、零模型下载、确定性。
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/
SKILL_ROOT = os.path.dirname(HERE)                                    # 技能根
HOOKS_DIR = os.path.join(SKILL_ROOT, "hooks")
sys.path.insert(0, HOOKS_DIR)


def _load_common(store_root):
    """在受控 env 下加载 keeper_hook_common（不触发钩子自安装）。"""
    os.environ["AI_MEMORY_STORE"] = store_root
    os.environ["KEEPER_AUTO_INSTALL_HOOKS"] = "0"
    os.environ.pop("KEEPER_INJECT_INCLUDE_AUTO", None)
    os.environ.pop("KEEPER_INJECT_ENABLED", None)
    # 已加载则复用（模块级缓存），这里只需新 store 生效
    import keeper_hook_common as C
    return C


class InjectIncludeAutoGateTest(unittest.TestCase):
    """A：门控优先级。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keeper_inclauto_")
        self.C = _load_common(self.tmp)

    def tearDown(self):
        os.environ.pop("KEEPER_INJECT_INCLUDE_AUTO", None)
        os.environ.pop("AI_MEMORY_STORE", None)

    def _write_cfg(self, value, where="store"):
        d = os.path.join(self.tmp, "store") if where == "store" else self.tmp
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"keeper": {"inject_include_auto": value}}, f)

    def test_default_true_when_unset(self):
        """🔴 核心：缺配置时**默认 True** —— 否则 auto 库的注入恒空。"""
        self.assertTrue(self.C.inject_include_auto(),
                        "默认必须是 True（recall 默认隔离 auto 项，默认 False 会让注入恒空）")

    def test_config_false_respected(self):
        self._write_cfg(False)
        self.assertFalse(self.C.inject_include_auto(), "配置显式 false 必须生效")

    def test_env_overrides_config(self):
        self._write_cfg(False)
        os.environ["KEEPER_INJECT_INCLUDE_AUTO"] = "1"
        self.assertTrue(self.C.inject_include_auto(), "env 优先级必须高于配置")

    def test_env_false_wins(self):
        os.environ["KEEPER_INJECT_INCLUDE_AUTO"] = "0"
        self.assertFalse(self.C.inject_include_auto(), "env=0 必须关掉")


class HookShipsIncludeAutoStaticTest(unittest.TestCase):
    """B：静态契约——召回调用必须带该开关（防未来重构悄悄丢回旧行为）。"""

    def _src(self, name):
        return io.open(os.path.join(HOOKS_DIR, name), encoding="utf-8").read()

    def test_session_start_passes_include_auto(self):
        t = self._src("session_start_keeper_inject.py")
        self.assertIn("include_auto=C.inject_include_auto()", t,
                      "SessionStart 的 recall 必须带 include_auto，否则 auto 库恒空")

    def test_user_prompt_passes_include_auto(self):
        t = self._src("user_prompt_recall.py")
        self.assertIn("include_auto=C.inject_include_auto()", t,
                      "UserPromptSubmit 的 recall 必须带 include_auto")


class SessionStartEndToEndTest(unittest.TestCase):
    """C：端到端——临时库放一条 auto 记忆，真跑钩子，断言注入非空。"""

    def test_session_start_injects_from_auto_memory(self):
        tmp = tempfile.mkdtemp(prefix="keeper_ss_e2e_")
        env = dict(os.environ)
        env.update({
            "AI_MEMORY_STORE": tmp,
            "AI_MEM_EMBED_BACKEND": "lexical",
            "AI_MEM_NO_AUTO_INSTALL": "1",
            "KEEPER_AUTO_INSTALL_HOOKS": "0",
            "KEEPER_RECALL_MODE": "inprocess",   # 免 daemon，确定性
            "KEEPER_INJECT_ENABLED": "1",
            "KEEPER_HOOKS_DIR": os.path.join(tmp, "hooks_run"),
            "PYTHONIOENCODING": "utf-8",
        })
        os.makedirs(env["KEEPER_HOOKS_DIR"], exist_ok=True)

        # 写一条经验（默认即 auto_sourced=True，正是会被默认隔离的那类）
        dep = subprocess.run(
            [sys.executable, os.path.join(HERE, "memory_ops.py"), "deposit",
             "--summary", "端到端：启动注入必须带 include_auto",
             "--body", "keeper 注入钩子若不带 include_auto，auto 库恒空。",
             "--category", "best_practice"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=180)
        self.assertEqual(dep.returncode, 0, "deposit 失败: %s" % (dep.stderr or "")[:300])

        # 真跑 SessionStart 钩子
        evt = json.dumps({"source": "startup", "cwd": SKILL_ROOT,
                          "session_id": "e2e-inclauto"})
        hook = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "session_start_keeper_inject.py")],
            input=evt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=180)
        self.assertEqual(hook.returncode, 0, "钩子异常: %s" % (hook.stderr or "")[:300])

        out = (hook.stdout or "").strip().splitlines()
        self.assertTrue(out, "钩子无输出；stderr=%s" % (hook.stderr or "")[:300])
        d = json.loads(out[-1])
        ctx = ((d.get("hookSpecificOutput") or {}).get("additionalContext") or "")
        self.assertTrue(ctx.strip(),
                        "🔴 启动注入为空 —— include_auto 未生效（回归了 4.9.19 修的 bug）")
        self.assertIn("启动注入必须带 include_auto", ctx,
                      "注入内容应含刚写入的那条 auto 记忆")


class RuntimeDirNotInTreeTest(unittest.TestCase):
    """D：守护进程默认落点不得在源码树（4.9.19）。"""

    def test_client_default_home_not_in_skill_tree(self):
        code = ("import sys, os;"
                "sys.path.insert(0, r'%s');"
                "import keeper_recall_client as C;"
                "print(C.HOME)" % os.path.join(SKILL_ROOT, "keeper_daemon"))
        env = dict(os.environ)
        env.pop("KEEPER_DAEMON_DIR", None)
        env["AI_MEM_EMBED_BACKEND"] = "lexical"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=120)
        home = (p.stdout or "").strip()
        self.assertTrue(home, "探针无输出: %s" % (p.stderr or "")[:300])
        self.assertNotEqual(os.path.normcase(os.path.normpath(home)),
                            os.path.normcase(os.path.normpath(
                                os.path.join(SKILL_ROOT, "keeper_daemon"))),
                            "🔴 client 默认状态目录不得落在源码树 keeper_daemon/")


if __name__ == "__main__":
    unittest.main()
