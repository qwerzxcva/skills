# -*- coding: utf-8 -*-
"""
install_hooks.py — agent-local-memory-keeper 钩子/守护进程 安装器（v4.5.2）

为什么需要：
SkillHub 安装 skill 时**不会**自动把钩子注册进 ~/.workbuddy/settings.json，
也不会把守护进程放到 ~/.workbuddy/keeper_daemon/。本脚本补齐这一步，
让「装完 skill 即获得完整记忆辅助」可一键复现（尤其换电脑/全新安装）。

做什么：
1) 把 skill/hooks/*.py  →  ~/.workbuddy/hooks/        （覆盖同名 keeper 钩子，不动其他 hook）
2) 把 skill/keeper_daemon/* → ~/.workbuddy/keeper_daemon/  （钩子毫秒级 recall 的硬依赖）
3) 把 skill/scripts/_keeper_ima_push.py → 同包 scripts/   （已在包内，无需动作，仍校验）
4) 合并 settings.json 的 hooks.* 条目：仅幂等追加 keeper 条目，保留所有既有条目
（含 WorkBuddy 内置 leak_scan / code_lint / pre_tool_use_guard 等），绝不覆盖。
5) 清理「已退役钩子」的历史注册（见 RETIRED_HOOK_FILES）——旧实现只追加
   不清理，退役文件会永久残留并每次触发都空跑。

用法：
python install_hooks.py            # 真正安装（按持久模式 hooks_config.json；无配置则默认 silent）
python install_hooks.py --dry-run  # 只打印将做什么，不改任何文件
python install_hooks.py --start-daemon  # 安装后尝试启动 keeper_daemon（默认不启动）
python install_hooks.py --setup-scheduler  # 额外注册 Windows 计划任务（daemon 开机自启 + IMA 每周同步）
python install_hooks.py --set-mode full|silent|off  # 设置并应用钩子模式（持久化到 hooks_config.json）
python install_hooks.py --status   # 打印当前模式与已注册 keeper 钩子，不改文件

钩子模式（持久偏好，存 hooks_config.json，根治“手动关掉的钩子一更新就复活”）：
full   = 注册全部 5 个钩子（功能全，但 UserPromptSubmit/SessionStart 在每次提交/开场触发 WB 执行提示条=弹窗）
silent = 仅注册功能型钩子（PostToolUse/Stop/PreCompact，错误自动入库），关掉会弹窗的 SessionStart/UserPromptSubmit；
记忆自动注入改由 ~/.workbuddy/MEMORY.md 的“自提醒 pull”替代（按需 recall、top-N 上限，不灌爆上下文）
off    = 不注册任何 keeper 钩子（纯手动）
注：无参运行也读持久模式——首次自动注册（memory_ops._ensure_hooks）与重装都遵循，不会偷偷加回弹窗钩子。

幂等：重复运行安全；已存在的 keeper 条目不会被重复添加；模式禁止的 keeper 条目会被移除；
**已退役的 keeper 钩子条目会被主动清理**（跨所有事件，不限模式）；但 WorkBuddy 内置 hook 永远保留。
"""
import os
import sys
import json
import shutil
import argparse

SKILL = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
HOOKS_SRC = os.path.join(SKILL, "hooks")
DAEMON_SRC = os.path.join(SKILL, "keeper_daemon")
HOOKS_DST = os.path.join(WB_HOME, "hooks")
DAEMON_DST = os.path.join(WB_HOME, "keeper_daemon")
SETTINGS = os.path.join(WB_HOME, "settings.json")

# 仅复制这些 keeper 钩子文件（不动 WB 内置 hook）
# 注：旧版 bash_error_capture.py（字段 bug、未注册死文件）已于 彻底删除（I13），
# 其捕获职责由 post_tool_use_error_capture.py 承担，故此处不复制。
HOOK_FILES = [
    "keeper_hook_common.py",
    "session_start_keeper_inject.py",
    "user_prompt_recall.py",
    "post_tool_use_error_capture.py",
    "memory_auto_capture.py",
    "_async_deposit.py",  # memory_auto_capture 异步落盘助手（DETACHED 子进程调用）
]

# 已退役钩子文件名：这些文件已从技能彻底删除（职责由其它钩子承担），
# 但历史安装可能仍把它们注册在 settings.json ——若不主动清理，每次
# 事件触发都会去执行一个不存在的文件（静默失败，且可能造成
# Bash 错误双份捕获）。清理跨所有事件、不限模式（因为它所在事件
# 可能正好在启用名单内，模式禁止清理不会碰它）。
# 注：只删命中退役文件的那一条 hook，同组的其他 hook 原样保留。
RETIRED_HOOK_FILES = [
    "bash_error_capture.py",   # I13 已删；职责由 post_tool_use_error_capture.py 承担
]
# 注：守护进程的运行态 STATE 已从此表移除——它记端口/token/pid（旧名单实例 `.daemon.json`，
# 现按记忆库命名 `.daemon-<库指纹>.json`），由 daemon.py 启动时自建、优雅退出时自清、
# 检测到陈旧时自愈清理。把它当"源码"复制会：
#   ① 把上一台机器的陈旧端口/pid（甚至测试遗留的临时 root）带到新部署目录；
#   ② 该文件本就不该进发布包（见 .skillhubignore）。
DAEMON_FILES = ["daemon.py", "keeper_recall_client.py", "_selftest.py"]

# 钩子模式（持久偏好，存于 hooks_config.json）
# full = 注册全部 5 个钩子（功能全，但 UserPromptSubmit/SessionStart 触发 WB 执行提示条=弹窗）
# silent = 仅注册功能型钩子（PostToolUse/Stop/PreCompact，错误自动入库），关掉会弹窗的 SessionStart/UserPromptSubmit；
# 记忆自动注入改由 ~/.workbuddy/MEMORY.md 的“自提醒 pull”替代（按需 recall、top-N 上限，不灌爆上下文）
# off = 不注册任何 keeper 钩子（纯手动）
# 默认 silent：开箱即用、零弹窗。首次自动注册（memory_ops._ensure_hooks）与重装都遵循此默认，
# 不会偷偷把弹窗钩子加回来；想全开用 `keeper_setup.py hooks --mode full`。
# 🔴 4.9.19 修复：用户偏好**不再写回源码树**。
#    旧位置 `SKILL/hooks_config.json` 位于代码目录 → 会随发布包外泄、并让仓库带着
#    「本机偏好」（如 silent）发给别人。新位置放**用户配置域** <WB_HOME>/hooks/hooks_config.json
#    （与钩子部署目录同级：偏好跟钩子走，语义清晰）。
#    向后兼容：读取时**新位置优先、旧位置兜底**（老用户不丢已持久化的模式）。
HOOKS_CONFIG = os.path.join(HOOKS_DST, "hooks_config.json")
LEGACY_HOOKS_CONFIG = os.path.join(SKILL, "hooks_config.json")
MODES = ("full", "silent", "off")
ACTIVE_BY_MODE = {
    "full":   {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop", "PreCompact"},
    "silent": {"PostToolUse", "Stop", "PreCompact"},
    "off":    set(),
}
DEFAULT_MODE = "silent"

import datetime as _dt

def load_mode():
    """读持久模式：**新位置优先，旧位置（源码树）兜底**；缺失/非法 → 默认 silent。

    4.9.19 起偏好文件迁到用户配置域，这里保留旧路径兜底读取——老用户（只有旧文件）
    不会丢偏好；新安装一律写新位置。
    """
    for _p in (HOOKS_CONFIG, LEGACY_HOOKS_CONFIG):
        try:
            if os.path.exists(_p):
                with open(_p, encoding="utf-8") as f:
                    d = json.load(f)
                m = d.get("hooks_mode")
                if m in MODES:
                    return m
        except Exception:
            pass
    return DEFAULT_MODE

def save_mode(mode):
    """把模式持久化到 hooks_config.json（4.9.19：新位置=用户配置域）。返回是否成功。"""
    try:
        _d = os.path.dirname(HOOKS_CONFIG)
        if _d and not os.path.isdir(_d):
            os.makedirs(_d, exist_ok=True)  # 首次安装时部署目录可能尚未创建
        with open(HOOKS_CONFIG, "w", encoding="utf-8") as f:
            json.dump({
                "hooks_mode": mode,
                "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "note": "full=全部钩子(含弹窗源); silent=仅功能钩子+MEMORY.md自提醒; off=无钩子",
            }, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("  [警告] 写 hooks_config.json 失败: %s" % e)
        return False


def _prefer_pythonw(py_exe):
    """优先返回同目录 pythonw.exe（GUI 子系统，去 Windows 钩子闪窗）；父进程管道仍能捕获 stdout，功能不丢。"""
    if py_exe.lower().endswith("python.exe"):
        pyw = py_exe[:-len("python.exe")] + "pythonw.exe"
        return pyw if os.path.exists(pyw) else py_exe
    return py_exe


def resolve_python():
    venv = os.path.join(WB_HOME, "binaries", "python", "envs", "default", "Scripts", "python.exe").replace("\\", "/")
    if os.path.exists(venv):
        return _prefer_pythonw(venv)
        # 回退：探测已安装 managed python 版本（优先最新），避免写死 在版本升级后失效
    base = os.path.join(WB_HOME, "binaries", "python", "versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, v, "python.exe").replace("\\", "/")
            if os.path.exists(cand):
                return _prefer_pythonw(cand)
    return _prefer_pythonw(os.path.join(WB_HOME, "binaries", "python", "versions", "3.13.12", "python.exe").replace("\\", "/"))


PY = resolve_python()

# (事件, 钩子文件, matcher|None, 额外参数|None, timeout)
HOOK_DEFS = [
    ("SessionStart", "session_start_keeper_inject.py", None, None, 30),
    ("UserPromptSubmit", "user_prompt_recall.py", None, None, 30),
    ("PostToolUse", "post_tool_use_error_capture.py", "Bash", None, 30),
    ("Stop", "memory_auto_capture.py", None, "Stop", 60),
    ("PreCompact", "memory_auto_capture.py", None, "PreCompact", 60),
]


def _build_command(file, arg):
    hook_path = os.path.join(HOOKS_DST, file).replace("\\", "/")
    py = PY.replace("\\", "/")
    cmd = '"%s" "%s"' % (py, hook_path)
    if arg:
        cmd += " " + arg
    return cmd


def _copy_files(src_dir, dst_dir, files, dry):
    os.makedirs(dst_dir, exist_ok=True)
    copied = []
    for fn in files:
        s = os.path.join(src_dir, fn)
        d = os.path.join(dst_dir, fn)
        if not os.path.exists(s):
            print("  [跳过] 源缺失: %s" % s)
            continue
        if dry:
            print("  [dry] 将复制 %s -> %s" % (s, d))
        else:
            shutil.copy2(s, d)
            copied.append(d)
    return copied


def _merge_settings(dry, mode):
    """按模式幂等合并/移除 keeper 钩子条目。返回 (changed, detail)。
    - 模式内允许的钩子：确保注册（新增或更新命令路径）。
    - 模式禁止的 keeper 钩子：从 settings.json 移除对应 keeper 条目，但**保留 WorkBuddy 内置**条目。
    """
    settings = {}
    if os.path.exists(SETTINGS):
        try:
            with open(SETTINGS, encoding="utf-8") as f:
                settings = json.load(f)
        except Exception as e:
            print("  [错误] settings.json 解析失败，跳过合并: %s" % e)
            return False, []
    if not isinstance(settings, dict):
        settings = {}
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    active = ACTIVE_BY_MODE.get(mode, ACTIVE_BY_MODE[DEFAULT_MODE])
    detail = []

    # 1) 确保允许的钩子已注册（复用原幂等逻辑）
    for event, file, matcher, arg, timeout in HOOK_DEFS:
        if event not in active:
            continue
        cmd = _build_command(file, arg)
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            groups = []
            hooks[event] = groups
            # 是否已存在同文件(+同参数)的条目
        present = False
        for g in groups:
            if not isinstance(g, dict):
                continue
            for h in g.get("hooks", []):
                c = h.get("command", "")
                if file in c and (arg is None or (" " + arg) in c or c.rstrip().endswith(arg)):
                    present = True
                    # 若命令路径变了（如换机器/换 python），就地更新为最新解析值
                    if not dry and c != cmd:
                        h["command"] = cmd
                        detail.append("更新命令:%s/%s" % (event, file))
                    break
            if present:
                break
        if present:
            continue
            # 新增条目
        group = {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
        detail.append("新增:%s/%s%s" % (event, file, (" (%s)" % matcher) if matcher else ""))

        # 2) 移除模式禁止的 keeper 钩子（只动 keeper 自己的条目，保留 WB 内置）
    for event, file, matcher, arg, timeout in HOOK_DEFS:
        if event in active:
            continue
        if event not in hooks:
            continue
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        before = len(groups)
        kept = []
        for g in groups:
            if not isinstance(g, dict):
                kept.append(g)
                continue
            is_keeper = False
            for h in g.get("hooks", []):
                c = h.get("command", "")
                if file in c:
                    is_keeper = True
                    break
            if is_keeper:
                detail.append("移除(模式禁止):%s/%s" % (event, file))
            else:
                kept.append(g)
        if len(kept) != before:
            hooks[event] = kept if kept else []

    # 3) 清理「已退役钩子」的历史注册（跨所有事件，不受模式限制）
    #    与第 2 步的区别：第 2 步只看「模式未启用」的事件，而退役文件
    #    所在事件可能正在启用名单内（如 PostToolUse）→ 必须独立扫全量。
    for _ev, _groups in list(hooks.items()):
        if not isinstance(_groups, list):
            continue
        _new_groups = []
        for _g in _groups:
            if not isinstance(_g, dict) or not isinstance(_g.get("hooks"), list):
                _new_groups.append(_g)
                continue
            _kept_h = []
            for _h in _g["hooks"]:
                _c = str(_h.get("command", "")) if isinstance(_h, dict) else ""
                _hit = next((rf for rf in RETIRED_HOOK_FILES if rf in _c), None)
                if _hit:
                    detail.append("移除(已退役):%s/%s" % (_ev, _hit))
                else:
                    _kept_h.append(_h)
            if _kept_h or not _g["hooks"]:
                _g2 = dict(_g)
                _g2["hooks"] = _kept_h
                _new_groups.append(_g2)
        if _new_groups != _groups:
            hooks[_ev] = _new_groups

    if not dry:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    return (len(detail) > 0), detail


def _backup_settings():
    """写前备份 settings.json（带时间戳，绝不覆盖既有备份）。

    ⚠️ 加固：**内容与任一既有备份相同则跳过**——否则反复运行安装器
    （如"更新后自动刷新部署副本"）会把 settings.json.bak_* 堆成一片。
    """
    try:
        import shutil as _sh
        import glob as _g
        if not os.path.exists(SETTINGS):
            return
        try:
            cur = open(SETTINGS, "rb").read()
            for _c in _g.glob(SETTINGS + ".bak*"):
                try:
                    if open(_c, "rb").read() == cur:
                        print("  [备份] settings.json 与既有备份内容一致，跳过")
                        return
                except Exception:
                    continue
        except Exception:
            pass
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = SETTINGS + ".bak_" + ts
        _sh.copy2(SETTINGS, dst)
        print("  [备份] settings.json → %s" % dst)
    except Exception as e:
        print("  [警告] 备份失败(继续): %s" % e)


def _write_deploy_state():
    """记录本次"部署副本指纹"（技能版本 + 各钩子文件 sha256）到 hooks 部署目录。

    用途：`memory_ops/_hooks.py` 的 `_hooks_stale_reason()` 靠它判断
    "技能更新后本机部署副本是否滞后"，从而在更新后**自动刷新 + 引导重启**。
    旧版不写此文件 → 更新后本机钩子永远停在旧版且完全静默（这是"更新完感觉没生效"的根因）。
    """
    import hashlib
    try:
        ver = ""
        try:
            with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("version:"):
                        ver = s.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            ver = ""
        files = {}
        for fn in HOOK_FILES:
            p = os.path.join(HOOKS_SRC, fn)
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    files[fn] = hashlib.sha256(fh.read()).hexdigest()
        # 守护进程副本也记指纹——调度项直接指向 ~/.workbuddy/keeper_daemon/daemon.py，
        # 技能升级后它同样会滞后（不改它，更新后跑的仍是旧守护）。
        daemon = {}
        for fn in DAEMON_FILES:
            # 只记 .py：daemon 的 STATE 是运行时状态文件（端口等），内容会变，
            # 记进指纹会造成"副本滞后"假告警。
            if not fn.endswith(".py"):
                continue
            p = os.path.join(DAEMON_SRC, fn)
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    daemon[fn] = hashlib.sha256(fh.read()).hexdigest()
        os.makedirs(HOOKS_DST, exist_ok=True)
        st = os.path.join(HOOKS_DST, ".keeper_deploy_state.json")
        with open(st, "w", encoding="utf-8") as f:
            json.dump({"version": ver, "files": files, "daemon": daemon,
                       "updated_at": _dt.datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        print("  [指纹] 部署状态已记录 (version=%s, hooks=%d, daemon=%d)"
              % (ver or "?", len(files), len(daemon)))
    except Exception as e:
        print("  [警告] 写部署指纹失败（不影响钩子本身）: %s" % e)


def _print_status():
    """打印当前模式与 settings.json 实际注册的 keeper 钩子。"""
    mode = load_mode()
    print("=== keeper 钩子状态 ===")
    print("持久模式 (hooks_config.json): %s" % mode)
    print("该模式应注册: %s" % (", ".join(sorted(ACTIVE_BY_MODE.get(mode, set()))) or "(无)"))
    reg = []
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        hooks = data.get("hooks", {})
        for event, groups in (hooks or {}).items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                if not isinstance(g, dict):
                    continue
                for h in g.get("hooks", []):
                    c = h.get("command", "")
                    for fn in HOOK_FILES:
                        if fn in c:
                            reg.append("%s/%s" % (event, fn))
    except Exception as e:
        print("  [警告] 读 settings.json 失败: %s" % e)
    print("settings.json 实际 keeper 钩子: %s" % (", ".join(sorted(set(reg))) or "(无)"))
    retired = []
    try:  # hooks 仅在上方 try 内绑定；警告路径下未绑定会 NameError
        for event, groups in (hooks or {}).items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                if not isinstance(g, dict):
                    continue
                for h in g.get("hooks", []):
                    c = str(h.get("command", ""))
                    for rf in RETIRED_HOOK_FILES:
                        if rf in c:
                            retired.append("%s/%s" % (event, rf))
    except Exception:
        pass
    if retired:
        print("⚠ 已退役但仍注册（下次安装将自动清理）: %s"
              % ", ".join(sorted(set(retired))))
    print("注: 改模式后需重启 WorkBuddy 生效。")


def _start_daemon(dry):
    if dry:
        print("  [dry] 将尝试后台启动 keeper_daemon")
        return
    try:
        py = PY
        daemon_py = os.path.join(DAEMON_DST, "daemon.py")
        if not os.path.exists(daemon_py):
            print("  [跳过] daemon.py 未在 %s" % DAEMON_DST)
            return
        import subprocess
        # 后台启动，避免阻塞安装脚本；POSIX 用 start_new_session（无 creationflags 概念）。
        # ⚠️ Windows 必须用 CREATE_NO_WINDOW(0x08000000)：受控实验（pythonw 父进程 + python.exe 子进程
        #    + DEVNULL 重定向，即本处真实形态）实测——
        #      不设 flags → GetConsoleWindow()=722416 可见；CREATE_NEW_PROCESS_GROUP(0x200) → 984144 可见；
        #      而 CREATE_NO_WINDOW / DETACHED_PROCESS → 0 不可见。
        #    此前用 0x200，等于每次安装/后台刷新都弹一个黑窗（4.9.11 修了钩子那处，漏了本处）。
        if os.name == "nt":
            subprocess.Popen(
                '"%s" "%s"' % (py, daemon_py),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW（静默，绝不弹窗）
                close_fds=True,
            )
        else:
            subprocess.Popen(
                [py, daemon_py],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        print("  [完成] 已尝试后台启动 keeper_daemon")
    except Exception as e:
        print("  [警告] 启动 daemon 失败（可手动启动）: %s" % e)


def main():
    ap = argparse.ArgumentParser(description="安装 keeper 钩子与守护进程")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不改动")
    ap.add_argument("--start-daemon", action="store_true", help="安装后后台启动 keeper_daemon")
    ap.add_argument("--setup-scheduler", action="store_true", help="额外注册计划任务（daemon 开机自启 + IMA 每周同步）")
    ap.add_argument("--set-mode", choices=MODES, default=None,
                    help="设置并应用钩子模式 full/silent/off（持久化到 hooks_config.json）")
    ap.add_argument("--status", action="store_true", help="打印当前模式与已注册 keeper 钩子，不改文件")
    args = ap.parse_args()

    if args.status:
        _print_status()
        return

    mode = args.set_mode if args.set_mode else load_mode()
    if not args.dry_run:
        _backup_settings()

    print("=== keeper 钩子/守护进程安装器 (dry=%s, mode=%s) ===" % (args.dry_run, mode))
    print("WB_HOME = %s" % WB_HOME)
    print("PY      = %s" % PY)

    print("[1] 复制钩子 → %s" % HOOKS_DST)
    _copy_files(HOOKS_SRC, HOOKS_DST, HOOK_FILES, args.dry_run)

    print("[2] 复制守护进程 → %s" % DAEMON_DST)
    _copy_files(DAEMON_SRC, DAEMON_DST, DAEMON_FILES, args.dry_run)

    if not args.dry_run:
        # 记录部署指纹：供更新后"副本滞后"检测 + 自动刷新（_hooks.py::_hooks_stale_reason）
        _write_deploy_state()

    print("[3] 合并 settings.json 钩子条目（模式=%s，幂等，保留内置）" % mode)
    changed, detail = _merge_settings(args.dry_run, mode)
    for line in detail:
        print("    - %s" % line)
    if not detail:
        print("    - 无变更（条目已符合模式）")

    if args.set_mode and not args.dry_run:
        save_mode(args.set_mode)
        print("  [持久化] hooks_config.json → mode=%s" % args.set_mode)

    if args.start_daemon:
        print("[4] 启动守护进程")
        _start_daemon(args.dry_run)

    if args.setup_scheduler:
        print("[5] 注册计划任务（daemon 自启 + IMA 周同步）")
        try:
            # 同目录导入，避免依赖 subprocess
            sched_path = os.path.join(SKILL, "setup_scheduler.py")
            if os.path.exists(sched_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("setup_scheduler", sched_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                # 复用 dry-run 标志
                old_argv = sys.argv[:]
                sys.argv = ["setup_scheduler.py", "--dry-run"] if args.dry_run else ["setup_scheduler.py"]
                mod.main()
                sys.argv = old_argv
            else:
                print("  [跳过] setup_scheduler.py 不存在")
        except Exception as e:
            print("  [警告] 调度器注册失败（可手动运行 python setup_scheduler.py）: %s" % e)

    print("=== 完成 ===")
    if args.dry_run:
        print("（dry-run：以上均未实际改动。去掉 --dry-run 重新运行以真正安装）")


if __name__ == "__main__":
    main()
