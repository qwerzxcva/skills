# Auto-extracted submodule: _hooks
# Source: agent-local-memory-keeper scripts/memory_ops/__init__.py
# Loaded via dependency-injection (globals injected by __init__ loader block).
# Shared helpers (_audit_log, _with_deposit_lock, _save_mem, caches, etc.) resolve
# through the injected namespace; do NOT re-define them here.

def _skill_root():
    """定位技能根目录（应含 SKILL.md 与 hooks_config.json）。

    🔴 防路径错位：本模块位于 <skill>/scripts/memory_ops/，技能根需**上溯三层**。
    旧实现只上溯两层（落在 <skill>/scripts/），导致 hooks_config.json 永远找不到。
    这里改成"逐级上溯探测特征文件"——即使 __file__ 来源变化（DI 注入 / 直接 import）
    也能稳定命中，防止同类错位复发。
    """
    try:
        _probe = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return ""
    for _ in range(5):
        if (os.path.exists(os.path.join(_probe, "hooks_config.json"))
                or os.path.exists(os.path.join(_probe, "SKILL.md"))):
            return _probe
        _up = os.path.dirname(_probe)
        if _up == _probe:
            break
        _probe = _up
    try:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        return ""


def _keeper_hook_mode():
    """读 keeper 钩子持久模式（hooks_config.json）；缺失/非法 → 默认 full。

    ⚠️ 历史 bug（已修）：旧实现按 `<skill>/scripts/hooks_config.json` 探测，
    而真实文件在**技能根**，故恒返回 "full"——用户持久化的 silent/off 被静默忽略
    （连 off 的短路保护也失效）。后改走 `_skill_root()` 修复该错位。
    🔴 4.9.19：偏好文件进一步从**源码树**迁到**用户配置域** <WB_HOME>/hooks/hooks_config.json
    （源码树那份会随发布包外泄）。读取顺序：配置域优先 → 源码树旧位置兜底 → 默认 full。
    与 `keeper_hook_common.HOOKS_DIR` 同规则（env `KEEPER_HOOKS_DIR` 可覆盖），
    故测试隔离时两边一起走临时目录，天然互不污染。
    """
    _pref_base = os.environ.get("KEEPER_HOOKS_DIR") or os.path.join(
        os.path.expanduser("~"), ".workbuddy", "hooks")
    for _cfg in (os.path.join(_pref_base, "hooks_config.json"),
                 os.path.join(_skill_root(), "hooks_config.json")):
        try:
            if os.path.exists(_cfg):
                with open(_cfg, encoding="utf-8") as _f:
                    _d = json.load(_f)
                _m = _d.get("hooks_mode")
                if _m in ("full", "silent", "off"):
                    return _m
        except Exception:
            pass
    return "full"


def _read_skill_version():
    """读 SKILL.md frontmatter 的 `version:`（版本单一真源）。失败返回 ''。"""
    try:
        with open(os.path.join(_skill_root(), "SKILL.md"), encoding="utf-8") as _f:
            for _line in _f:
                _s = _line.strip()
                if _s.startswith("version:"):
                    return _s.split(":", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _hooks_deploy_dir():
    """钩子部署目录（默认 `~/.workbuddy/hooks`）。

    可用 env `KEEPER_HOOKS_DIR` 覆盖——供测试隔离与非默认安装使用
    （测试若不隔离，会读写真实用户目录，污染环境）。
    """
    try:
        _o = os.environ.get("KEEPER_HOOKS_DIR")
        if _o:
            return _o
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), ".workbuddy", "hooks")


def _deploy_state_path():
    return os.path.join(_hooks_deploy_dir(), ".keeper_deploy_state.json")


def _refresh_marker_path():
    return os.path.join(_hooks_deploy_dir(), ".keeper_refresh_attempt.json")


def _hooks_stale_reason():
    """部署的钩子副本是否落后于技能源？返回 (stale: bool, reason: str)。

    为什么必须查：`install_hooks.py` 只在"settings.json 里还没有 keeper 钩子"时才被触发
    （见 `_ensure_hooks`）。于是**技能一更新，~/.workbuddy/hooks/ 下的副本就永远停在旧版**——
    新版修好的钩子问题用户享受不到，且完全静默。这里用「版本 + 逐文件 sha256」双重检测。
    覆盖 helper（keeper_hook_common / _async_deposit）——历史上正是 helper 漏拷导致静默失效。
    """
    import hashlib
    try:
        _src = os.path.join(_skill_root(), "hooks")
        if not os.path.isdir(_src):
            return False, ""
        _state = {}
        _st = _deploy_state_path()
        if os.path.exists(_st):
            try:
                with open(_st, encoding="utf-8") as _f:
                    _state = json.load(_f) or {}
            except Exception:
                _state = {}
        _ver_now = _read_skill_version()
        _ver_old = str(_state.get("version") or "")
        if _ver_now and _ver_old and _ver_now != _ver_old:
            return True, "版本变化 %s → %s" % (_ver_old, _ver_now)
        _hashes = _state.get("files") or {}
        _daemon_hashes = _state.get("daemon") or {}
        if not _hashes:
            return True, "无部署记录（无法确认副本是否为最新）"
        # 只比对"当初确实部署过的文件"（state 记录的键），**不 glob 整个目录**——
        # 因为目录里可能有**故意不部署**的文件（如 keeper_daemon/keeper_api.py：
        # 它按 dirname(dirname(__file__)) 定位技能根，部署到 ~/.workbuddy 下会路径错位）。
        # glob 会把这类文件误判成"滞后"，制造假告警。
        _dirs = {"files": os.path.join(_skill_root(), "hooks"),
                 "daemon": os.path.join(_skill_root(), "keeper_daemon")}
        for _key, _dir in _dirs.items():
            _recorded = _state.get(_key) or {}
            if not _recorded:
                continue
            _label = "钩子" if _key == "files" else "守护进程"
            for _fn, _want in _recorded.items():
                _p = os.path.join(_dir, _fn)
                if not os.path.exists(_p):
                    continue
                try:
                    with open(_p, "rb") as _fh:
                        _h = hashlib.sha256(_fh.read()).hexdigest()
                except Exception:
                    continue
                if _want != _h:
                    return True, "%s副本滞后: %s" % (_label, _fn)
        return False, ""
    except Exception:
        return False, ""


def _should_attempt_refresh(version):
    """同一版本 6 小时内只尝试刷新一次——防"刷新失败 → 每条命令都重试"的静默风暴。"""
    import time as _t
    try:
        _p = _refresh_marker_path()
        if os.path.exists(_p):
            with open(_p, encoding="utf-8") as _f:
                _d = json.load(_f) or {}
            if str(_d.get("version") or "") == str(version):
                if (_t.time() - float(_d.get("ts") or 0)) < 6 * 3600:
                    return False
    except Exception:
        pass
    return True


def _mark_refresh_attempt(version):
    import time as _t
    try:
        _p = _refresh_marker_path()
        os.makedirs(os.path.dirname(_p), exist_ok=True)
        with open(_p, "w", encoding="utf-8") as _f:
            json.dump({"version": str(version), "ts": _t.time()}, _f)
    except Exception:
        pass


def _maybe_refresh_stale_hooks():
    """已注册但部署副本滞后 → 后台重跑安装器刷新，并给出**更新后引导**。

    静默边界：任何异常都吞掉，绝不阻断主流程（钩子是增强，不是必需）。
    绝不弹窗：Windows 用 CREATE_NO_WINDOW（0x08000000），**不用** DETACHED_PROCESS
    （后者会让 pythonw 父进程为控制台子进程新建可见控制台）。
    """
    try:
        _stale, _why = _hooks_stale_reason()
        if not _stale:
            return
        _ver = _read_skill_version() or "?"
        if not _should_attempt_refresh(_ver):
            return
        _mark_refresh_attempt(_ver)
        import subprocess as _sp
        _installer = os.path.join(_skill_root(), "install_hooks.py")
        if not os.path.exists(_installer):
            return
        _kwargs = {"stdout": _sp.DEVNULL, "stderr": _sp.DEVNULL, "close_fds": True}
        if sys.platform.startswith("win"):
            _kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW（静默，绝不弹窗）
        _sp.Popen('"%s" "%s"' % (sys.executable, _installer), **_kwargs)
        print("🔁 [keeper] 检测到部署副本滞后（%s），已在后台刷新钩子/守护副本。"
              % _why, file=sys.stderr)
        print("    如本次是**版本升级**，请重启 WorkBuddy 让新钩子生效；"
              "手动收口：python scripts/keeper_setup.py hooks --scheduler", file=sys.stderr)
    except Exception:
        pass

def _ensure_hooks():
    """
    装完 skill 首次使用时，若 settings.json 尚未注册 keeper 会话钩子，则自动调 install_hooks.py 注册。
    - 环境变量 KEEPER_AUTO_INSTALL_HOOKS=0 可关闭（默认开启）。
    - 持久模式（hooks_config.json）：off 直接跳过；full/silent 按模式注册（silent 不含弹窗钩子）。
    模式持久化使"更新/重装不会偷偷把弹窗钩子加回来"。
    - 已注册则跳过（幂等）；install_hooks.py 内部保留 WorkBuddy 内置 hook，绝不覆盖。
    - 任何异常都静默吞掉，绝不阻断主流程（钩子是增强，不是必需）。
    """
    import subprocess as _sp
    if os.environ.get("KEEPER_AUTO_INSTALL_HOOKS", "1") == "0":
        return
    _mode = _keeper_hook_mode()
    if _mode == "off":
        return
    try:
        settings = os.path.join(os.path.expanduser("~"), ".workbuddy", "settings.json")
        if os.path.exists(settings):
            try:
                with open(settings, encoding="utf-8") as _f:
                    _data = json.load(_f)
                _hooks = _data.get("hooks", {}) if isinstance(_data, dict) else {}
                _registered = False
                for _grp in (_hooks or {}).values():
                    if not isinstance(_grp, list):
                        continue
                    for _g in _grp:
                        if not isinstance(_g, dict):
                            continue
                        for _h in _g.get("hooks", []):
                            _cmd = (_h.get("command", "") or "") if isinstance(_h, dict) else ""
                            if any(_fn in _cmd for _fn in _KEEPER_HOOK_FILES):
                                _registered = True
                                break
                        if _registered:
                            break
                    if _registered:
                        break
                if _registered:
                    # 已注册 ≠ 已最新：技能更新后副本会滞后，这里顺带自愈 + 引导
                    _maybe_refresh_stale_hooks()
                    return
            except Exception:
                pass
                # 未注册 → 调用安装器（detached，不阻塞主命令）。无参运行即按持久模式安装。
        # 🔴 必须用 _skill_root() 定位技能根：本模块在 <skill>/scripts/memory_ops/ 下，
        # 旧实现按 dirname(__file__) 上溯一层 → 落在 <skill>/scripts/memory_ops/ →
        # 那里没有 install_hooks.py → 上面那个 `if not os.path.exists` 直接 return，
        # 于是**「装完首次跑命令自动注册钩子」这条路径从未生效**（与 hooks_config.json 路径错位同类）。
        # 2026-09-11 实探：旧值指向 ...\scripts\memory_ops\install_hooks.py（不存在），
        # _skill_root() 指向 ...\agent-local-memory-keeper\install_hooks.py（存在）。
        _installer = os.path.join(_skill_root(), "install_hooks.py")
        if not os.path.exists(_installer):
            return
        _py = sys.executable
        _kwargs = {"stdout": _sp.DEVNULL, "stderr": _sp.DEVNULL, "close_fds": True}
        if sys.platform.startswith("win"):
            _kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW（静默，绝不弹窗）
        _sp.Popen('"%s" "%s"' % (_py, _installer), **_kwargs)
        print("🔌 [keeper] 首次自动注册会话钩子（模式=%s；如需关闭设 KEEPER_AUTO_INSTALL_HOOKS=0；重启 WorkBuddy 后生效）"
              % _mode, file=sys.stderr)
        # E2：安装后回读 settings.json 确认注册成功（避免"发了但没装上"的静默失败）
        try:
            import time as _t; _t.sleep(1.5)  # 等 install_hooks.py 写盘
            if os.path.exists(settings):
                with open(settings, encoding="utf-8") as _f2:
                    _data2 = json.load(_f2)
                _hooks2 = _data2.get("hooks", {}) if isinstance(_data2, dict) else {}
                _ok = False
                for _grp2 in (_hooks2 or {}).values():
                    if not isinstance(_grp2, list): continue
                    for _g2 in _grp2:
                        if not isinstance(_g2, dict): continue
                        for _h2 in _g2.get("hooks", []):
                            if any(_fn in (_h2.get("command") or "") for _fn in _KEEPER_HOOK_FILES):
                                _ok = True; break
                        if _ok: break
                    if _ok: break
                if not _ok:
                    sys.stderr.write("[keeper] ⚠️ 钩子安装可能未生效——settings.json 未发现 keeper 条目。\n"
                                  "  手动修复：python \"%s\"\n" % _installer)
        except Exception:
            pass  # 验证本身失败不阻断
    except Exception:
        pass

