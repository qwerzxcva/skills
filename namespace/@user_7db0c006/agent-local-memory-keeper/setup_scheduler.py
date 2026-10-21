# -*- coding: utf-8 -*-
"""
setup_scheduler.py — keeper 调度器安装/卸载（v4.5.7）

解决什么问题：
- daemon "常驻"只是进程不退出，重启电脑后无人拉起 → 神经召回退化为每消息 +5s 冷加载。
- IMA "每周日23:00刷新"只是文档里的一句文案，并无真实调度 → 用户必须手动记着跑。

做什么：
1) 注册 daemon 开机/登录自启任务：Windows=计划任务「KeeperRecallDaemon」(ONLOGON)；
macOS=launchd plist (RunAtLoad+KeepAlive)；Linux=systemd --user 服务。
2) 注册 IMA 每周同步任务：Windows=计划任务「KeeperIMAWeeklySync」(每周日 23:00)；
macOS=launchd (StartCalendarInterval 周日23:00)；Linux=systemd --user timer。
3) 支持 --uninstall 移除任务；--dry-run 只打印不执行。

用法：
python setup_scheduler.py              # 安装两个调度任务（按当前平台自动选 Windows/macOS/Linux）
python setup_scheduler.py --dry-run    # 只打印将执行的命令
python setup_scheduler.py --uninstall  # 移除两个调度任务

跨平台：
Windows 用 schtasks；macOS 用 launchd (~/Library/LaunchAgents)；
Linux 用 systemd --user (~/.config/systemd/user)。三者同构（自启 daemon + 每周 IMA 同步）。

幂等：
Windows schtasks /Create /F 覆盖同名任务；macOS 先 unload 再 load；
Linux systemctl --user enable --now 重复运行安全。
"""

import os
import sys
import subprocess
import argparse
import platform

# ── 路径推导 ──────────────────────────────────────────────
SKILL = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
WB_HOME = os.path.join(HOME, ".workbuddy")
DAEMON_DST = os.path.join(WB_HOME, "keeper_daemon")
SCRIPTS_DIR = os.path.join(SKILL, "scripts")

# 任务名（固定前缀，便于识别/搜索）
TASK_DAEMON = "KeeperRecallDaemon"
TASK_IMA_SYNC = "KeeperIMAWeeklySync"
TASK_WEEKLY_SYNC = "KeeperWeeklySync"
TASK_SELF_HEAL = "KeeperSelfHeal"


def resolve_python():
    """探测 WorkBuddy managed Python 路径（与 install_hooks.py 同逻辑）。"""
    venv = os.path.join(WB_HOME, "binaries", "python", "envs", "default",
                        "Scripts", "python.exe").replace("\\", "/")
    if os.path.exists(venv):
        return venv
    base = os.path.join(WB_HOME, "binaries", "python", "versions")
    if os.path.isdir(base):
        for v in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, v, "python.exe").replace("\\", "/")
            if os.path.exists(cand):
                return cand
    return os.path.join(WB_HOME, "binaries", "python", "versions",
                         "3.13.12", "python.exe").replace("\\", "/")


PY = resolve_python()


def _reg_value(name):
    """读取 HKCU\\Environment 的字符串值（Windows）；非 Windows 或缺失返回 ''。"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        try:
            v, _ = winreg.QueryValueEx(k, name)
            return v or ""
        except Exception:
            return ""
        finally:
            winreg.CloseKey(k)
    except Exception:
        return ""


def _resolve_wb_workspace_mem():
    """解析工作区 .workbuddy/memory 目录（安装时一次性，烘焙进调度包装器）。
    
    优先级：env WB_WORKSPACE_MEM > 注册表 WB_WORKSPACE_MEM >
    env WB_WORKSPACE+.workbuddy/memory > 注册表 WB_WORKSPACE+.workbuddy/memory >
    当前 cwd+.workbuddy/memory（兜底）。
    与 mem_bridge._resolve_workspace_mem 同逻辑；此处解析一次后写死，避免调度任务
    运行时 cwd/环境不可靠导致读错工作区。
    """
    v = os.environ.get("WB_WORKSPACE_MEM") or _reg_value("WB_WORKSPACE_MEM")
    if v:
        return v
    ws = os.environ.get("WB_WORKSPACE") or _reg_value("WB_WORKSPACE")
    if ws:
        return os.path.join(ws, ".workbuddy", "memory")
    return os.path.join(os.getcwd(), ".workbuddy", "memory")


def _resolve_keeper_root():
    """解析 keeper 记忆库根（安装时一次性）。

    v4.9.2 修复：旧实现只认 env AI_MEMORY_STORE，非交互安装（schtasks / systemd /
    cron 由安装器调用）时该 env 通常为空 → 注册出的定时任务**不带** AI_MEMORY_STORE，
    跑起来就落到默认库，与用户真库不是同一个（实测：真库 <你的记忆库目录>，任务却写
    C:\\Users\\<uid>\\.ai-memory）。现补齐回退链，与
    memory_ops._config._default_root / hooks.keeper_hook_common._default_store 一致：
        env AI_MEMORY_STORE → ~/.keeper/store_root → ''（让 keeper 自行取默认根）
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
    return ""


def _run_schtasks(args, dry):
    """执行一条 schtasks 命令。返回 (success, stdout, stderr)。"""
    cmd = ["schtasks"] + args
    cmd_str = " ".join('"%s"' % a if " " in a or not a else a for a in cmd)
    print("  $ %s" % cmd_str)
    if dry:
        return True, "[dry-run]", ""
    try:
        # Windows schtasks 错误信息是系统本地编码（中文 GBK），不能默认 utf-8 解码
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           encoding="gbk", errors="replace")
        ok = r.returncode == 0
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if not ok:
            print("    ! 返回码 %s: %s" % (r.returncode, err or out))
        return ok, out, err
    except Exception as e:
        print("    ! 执行异常: %s" % e)
        return False, "", str(e)


def _install_daemon(dry):
    """注册 daemon 开机自启任务。"""
    daemon_py = os.path.join(DAEMON_DST, "daemon.py").replace("\\", "/")
    if not os.path.exists(daemon_py):
        print("  [跳过] daemon.py 不在 %s（请先运行 install_hooks.py）" % DAEMON_DST)
        return False

        # 动作：后台隐藏窗口运行 python daemon.py
    action = '"%s" "%s"' % (PY, daemon_py)

    ok, out, err = _run_schtasks([
        "/Create",
        "/TN", TASK_DAEMON,
        "/TR", action,
        "/SC", "ONLOGON",          # 用户登录时触发
        "/RL", "LIMITED",           # 最低权限（不需要管理员）
        "/F",                       # 幂等：存在则覆盖
    ], dry)

    if ok:
        print("  [OK] 已注册 %s → 用户登录时自动启动 keeper_daemon" % TASK_DAEMON)
    else:
        print("  [失败] %s 注册失败" % TASK_DAEMON)
    return ok


def _install_ima_sync(dry):
    """注册 IMA 每周同步任务。"""
    ima_py = os.path.join(SCRIPTS_DIR, "ima_sync.py").replace("\\", "/")
    if not os.path.exists(ima_py):
        print("  [跳过] ima_sync.py 不在 %s" % SCRIPTS_DIR)
        return False

    log_file = os.path.join(WB_HOME, "ima_push", "scheduler.log").replace("\\", "/")
    # schtasks /TR 经 CreateProcess 直接执行，不解释 shell 重定向 >>，
    # 故先写一个 .bat 包装器承接重定向，再让任务指向该 .bat
    wrapper = os.path.join(WB_HOME, "keeper_ima_sync_run.bat").replace("\\", "/")
    if not dry:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        # .bat 内用反斜杠更稳（cmd.exe）；PY/ima_py 当前是正斜杠，转回反斜杠
        py_bs = PY.replace("/", "\\")
        ima_bs = ima_py.replace("/", "\\")
        log_bs = log_file.replace("/", "\\")
        # 强制 UTF-8 输出：ima_sync 输出含中文（可能含 emoji），schtasks 控制台默认 GBK
        # 会导致 UnicodeEncodeError 使任务崩溃；chcp 65001 + PYTHONIOENCODING=utf-8 兜底
        # （与 _install_weekly_sync 的 .bat 保持一致）。
        bat = '@echo off\n@chcp 65001 >nul 2>&1\nSET "PYTHONIOENCODING=utf-8"\n"%s" "%s" >> "%s" 2>&1\n' % (py_bs, ima_bs, log_bs)
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(bat)

    ok, out, err = _run_schtasks([
        "/Create",
        "/TN", TASK_IMA_SYNC,
        "/TR", '"%s"' % wrapper,   # 指向 .bat 包装器
        "/SC", "WEEKLY",            # 每周触发
        "/D", "SUN",                # 周日
        "/ST", "23:00",             # 23:00 开始
        "/RL", "LIMITED",
        "/F",
    ], dry)

    if ok:
        print("  [OK] 已注册 %s → 每周日 23:00 自动导出 IMA 镜像" % TASK_IMA_SYNC)
        print("       日志: %s" % log_file)
        print("       包装器: %s" % wrapper)
    else:
        print("  [失败] %s 注册失败" % TASK_IMA_SYNC)
    return ok


def _install_weekly_sync(dry):
    """注册每周 coach 体检 + to-l2 晋升草稿任务（WB↔keeper 协同的 keeper→WB 半自动侧）。
    
    只读（coach 体检 WB）/ 只写库内草稿（to-l2），零风险。工作区与记忆库根在安装时
    解析一次并写死进包装器，避免调度运行时 cwd/环境不可靠导致读错工作区或记忆库。
    """
    mem_bridge_py = os.path.join(SKILL, "mem_bridge.py").replace("\\", "/")
    if not os.path.exists(mem_bridge_py):
        print("  [跳过] mem_bridge.py 不在 %s" % SKILL)
        return False
    ws = _resolve_wb_workspace_mem()
    root = _resolve_keeper_root()
    log_dir = os.path.join(WB_HOME, "keeper_weekly_sync").replace("\\", "/")
    log_file = os.path.join(log_dir, "scheduler.log").replace("\\", "/")
    wrapper = os.path.join(WB_HOME, "keeper_weekly_sync_run.bat").replace("\\", "/")
    if not dry:
        os.makedirs(log_dir, exist_ok=True)
        py_bs = PY.replace("/", "\\")
        mb_bs = mem_bridge_py.replace("/", "\\")
        ws_bs = ws.replace("/", "\\")
        log_bs = log_file.replace("/", "\\")
        # 强制 UTF-8 输出：coach/to-l2 输出含中文与 emoji，schtasks 控制台默认 GBK
        # 会导致 UnicodeEncodeError 使任务崩溃；chcp 65001 + PYTHONIOENCODING=utf-8 兜底。
        lines = ["@echo off", "@chcp 65001 >nul 2>&1",
                 'SET "PYTHONIOENCODING=utf-8"']
        if root:
            lines.append('SET "AI_MEMORY_STORE=%s"' % root.replace("/", "\\"))
        lines.append('"%s" "%s" coach --workspace "%s" >> "%s" 2>&1'
                     % (py_bs, mb_bs, ws_bs, log_bs))
        lines.append('"%s" "%s" to-l2 >> "%s" 2>&1' % (py_bs, mb_bs, log_bs))
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    ok, out, err = _run_schtasks([
        "/Create",
        "/TN", TASK_WEEKLY_SYNC,
        "/TR", '"%s"' % wrapper,
        "/SC", "WEEKLY",
        "/D", "SAT",
        "/ST", "23:30",
        "/RL", "LIMITED",
        "/F",
    ], dry)
    if ok:
        print("  [OK] 已注册 %s → 每周六 23:30 自动 coach 体检 + to-l2 晋升草稿" % TASK_WEEKLY_SYNC)
        print("       日志: %s" % log_file)
        print("       包装器: %s" % wrapper)
    else:
        print("  [失败] %s 注册失败" % TASK_WEEKLY_SYNC)
    return ok


def _install_self_heal(dry):
    """注册统一自治循环（self-heal）每日定时任务。
    
    合并 reflect/evolve/decay/doctor/skill-sync/export-rules 的「长会话/调度兜底」维护。
    默认全开、离线、dirty-mark 驱动；记忆库根在安装时解析一次写死进包装器。
    """
    mops_py = os.path.join(SCRIPTS_DIR, "memory_ops.py").replace("\\", "/")
    if not os.path.exists(mops_py):
        print("  [跳过] memory_ops.py 不在 %s" % SCRIPTS_DIR)
        return False
    root = _resolve_keeper_root()
    log_dir = os.path.join(WB_HOME, "keeper_self_heal").replace("\\", "/")
    log_file = os.path.join(log_dir, "scheduler.log").replace("\\", "/")
    wrapper = os.path.join(WB_HOME, "keeper_self_heal_run.bat").replace("\\", "/")
    if not dry:
        os.makedirs(log_dir, exist_ok=True)
        py_bs = PY.replace("/", "\\")
        mops_bs = mops_py.replace("/", "\\")
        log_bs = log_file.replace("/", "\\")
        # 强制 UTF-8（与 weekly_sync 的 .bat 一致），避免中文输出致任务崩溃
        lines = ["@echo off", "@chcp 65001 >nul 2>&1",
                 'SET "PYTHONIOENCODING=utf-8"']
        if root:
            lines.append('SET "AI_MEMORY_STORE=%s"' % root.replace("/", "\\"))
        lines.append('"%s" "%s" self-heal >> "%s" 2>&1' % (py_bs, mops_bs, log_bs))
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    ok, out, err = _run_schtasks([
        "/Create",
        "/TN", TASK_SELF_HEAL,
        "/TR", '"%s"' % wrapper,
        "/SC", "DAILY",
        "/ST", "03:00",             # 每日 03:00（离线、低峰）
        "/RL", "LIMITED",
        "/F",
    ], dry)
    if ok:
        print("  [OK] 已注册 %s → 每日 03:00 统一自治循环（self-heal）" % TASK_SELF_HEAL)
        print("       日志: %s" % log_file)
        print("       包装器: %s" % wrapper)
    else:
        print("  [失败] %s 注册失败" % TASK_SELF_HEAL)
    return ok


def _install_weekly_sync_posix(dry):
    """macOS/Linux 每周协同任务：launchd StartCalendarInterval (Darwin) / systemd timer (Linux)。"""
    mem_bridge_py = os.path.join(SKILL, "mem_bridge.py")
    if not os.path.exists(mem_bridge_py):
        print("  [跳过] mem_bridge.py 不在 %s" % SKILL)
        return False
    ws = _resolve_wb_workspace_mem()
    root = _resolve_keeper_root()
    log_dir = os.path.join(WB_HOME, "keeper_weekly_sync")
    log_file = os.path.join(log_dir, "scheduler.log")
    sh = os.path.join(WB_HOME, "keeper_weekly_sync_run.sh")
    if not dry:
        os.makedirs(log_dir, exist_ok=True)
        lines = ["#!/bin/sh", 'PY="%s"' % PY, 'MB="%s"' % mem_bridge_py,
                 'WS="%s"' % ws, 'LOG="%s"' % log_file,
                 'export PYTHONIOENCODING=utf-8']
        if root:
            lines.append('export AI_MEMORY_STORE="%s"' % root)
        lines.append('"$PY" "$MB" coach --workspace "$WS" >> "$LOG" 2>&1')
        lines.append('"$PY" "$MB" to-l2 >> "$LOG" 2>&1')
        with open(sh, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(sh, 0o755)
        except Exception:
            pass
    sysname = platform.system()
    if sysname == "Darwin":
        plist_path = os.path.join(HOME, "Library", "LaunchAgents",
                                  "com.keeper.weekly-sync.plist")
        plist = _LAUNCHD_WEEKLY_TMPL.format(label="com.keeper.weekly-sync",
                                            py=PY, sh=sh, log=log_file)
        _write_file(plist_path, plist, dry)
        ok, out, err = _run(["launchctl", "load", plist_path], dry)
        if ok:
            print("  [OK] 已注册 launchd 每周六 23:30 协同 (%s)" % plist_path)
        else:
            print("  [提示] launchctl load 失败，可手动：launchctl bootstrap gui/%d %s"
                  % (os.getuid(), plist_path))
        return ok
    elif sysname == "Linux":
        svc_path = os.path.join(HOME, ".config", "systemd", "user",
                                "keeper-weekly-sync.service")
        timer_path = os.path.join(HOME, ".config", "systemd", "user",
                                  "keeper-weekly-sync.timer")
        _write_file(svc_path, _SYSTEMD_WEEKLY_SERVICE_TMPL.format(sh=sh), dry)
        _write_file(timer_path, _SYSTEMD_WEEKLY_TIMER_TMPL, dry)
        ok, out, err = _run(["systemctl", "--user", "enable", "--now",
                             "keeper-weekly-sync.timer"], dry)
        if ok:
            print("  [OK] 已注册 systemd --user 每周六 23:30 协同定时 (%s)" % timer_path)
        else:
            print("  [提示] systemctl --user 失败（需 loginctl enable-linger 或已登录会话）。"
                  " 可手动：systemctl --user start keeper-weekly-sync.timer")
        return ok
    print("  [不支持] 未知 POSIX 平台: %s" % sysname)
    return False


_LAUNCHD_WEEKLY_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{label}</string>
	<key>ProgramArguments</key>
	<array>
		<string>{py}</string>
		<string>{sh}</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Weekday</key>
		<integer>6</integer>
		<key>Hour</key>
		<integer>23</integer>
		<key>Minute</key>
		<integer>30</integer>
	</dict>
	<key>StandardOutPath</key>
	<string>{log}</string>
	<key>StandardErrorPath</key>
	<string>{log}</string>
</dict>
</plist>
"""

_SYSTEMD_WEEKLY_SERVICE_TMPL = """[Unit]
Description=Keeper weekly sync (coach health check + to-l2 promotion draft)

[Service]
Type=oneshot
ExecStart={sh}
"""

_SYSTEMD_WEEKLY_TIMER_TMPL = """[Unit]
Description=Keeper weekly sync timer (every Saturday 23:30)

[Timer]
OnCalendar=Sat *-*-* 23:30:00
Persistent=true
Unit=keeper-weekly-sync.service

[Install]
WantedBy=timers.target
"""



def _install_self_heal_posix(dry):
    """macOS/Linux 统一自治循环：launchd StartCalendarInterval (Darwin) / systemd timer (Linux)，每日 03:00。"""
    mops_py = os.path.join(SCRIPTS_DIR, "memory_ops.py")
    if not os.path.exists(mops_py):
        print("  [跳过] memory_ops.py 不在 %s" % SCRIPTS_DIR)
        return False
    root = _resolve_keeper_root()
    log_dir = os.path.join(WB_HOME, "keeper_self_heal")
    log_file = os.path.join(log_dir, "scheduler.log")
    sh = os.path.join(WB_HOME, "keeper_self_heal_run.sh")
    if not dry:
        os.makedirs(log_dir, exist_ok=True)
        lines = ["#!/bin/sh", 'PY="%s"' % PY, 'MOPS="%s"' % mops_py, 'LOG="%s"' % log_file, 'export PYTHONIOENCODING=utf-8']
        if root:
            lines.append('export AI_MEMORY_STORE="%s"' % root)
        lines.append('"$PY" "$MOPS" self-heal >> "$LOG" 2>&1')
        with open(sh, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        try:
            os.chmod(sh, 0o755)
        except Exception:
            pass
    sysname = platform.system()
    if sysname == "Darwin":
        plist_path = os.path.join(HOME, "Library", "LaunchAgents",
                                  "com.keeper.self-heal.plist")
        plist = _LAUNCHD_SELF_HEAL_TMPL.format(label="com.keeper.self-heal",
                                                py=PY, sh=sh, log=log_file)
        _write_file(plist_path, plist, dry)
        ok, out, err = _run(["launchctl", "load", plist_path], dry)
        if ok:
            print("  [OK] 已注册 launchd 每日 03:00 自治循环 (%s)" % plist_path)
        else:
            print("  [提示] launchctl load 失败，可手动：launchctl bootstrap gui/%d %s"
                  % (os.getuid(), plist_path))
        return ok
    elif sysname == "Linux":
        svc_path = os.path.join(HOME, ".config", "systemd", "user",
                                "keeper-self-heal.service")
        timer_path = os.path.join(HOME, ".config", "systemd", "user",
                                  "keeper-self-heal.timer")
        _write_file(svc_path, _SYSTEMD_SELF_HEAL_SERVICE_TMPL.format(sh=sh), dry)
        _write_file(timer_path, _SYSTEMD_SELF_HEAL_TIMER_TMPL, dry)
        ok, out, err = _run(["systemctl", "--user", "enable", "--now",
                             "keeper-self-heal.timer"], dry)
        if ok:
            print("  [OK] 已注册 systemd --user 每日 03:00 自治循环定时 (%s)" % timer_path)
        else:
            print("  [提示] systemctl --user 失败（需 loginctl enable-linger 或已登录会话）。"
                  " 可手动：systemctl --user start keeper-self-heal.timer")
        return ok
    print("  [不支持] 未知 POSIX 平台: %s" % sysname)
    return False

_LAUNCHD_SELF_HEAL_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{label}</string>
	<key>ProgramArguments</key>
	<array>
		<string>{py}</string>
		<string>{sh}</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>3</integer>
		<key>Minute</key>
		<integer>0</integer>
	</dict>
	<key>StandardOutPath</key>
	<string>{log}</string>
	<key>StandardErrorPath</key>
	<string>{log}</string>
</dict>
</plist>
"""

_SYSTEMD_SELF_HEAL_SERVICE_TMPL = """[Unit]
Description=Keeper self-heal (unified maintenance: reflect/evolve/decay/doctor/skill-sync/export-rules)

[Service]
Type=oneshot
ExecStart={sh}
"""

_SYSTEMD_SELF_HEAL_TIMER_TMPL = """[Unit]
Description=Keeper self-heal timer (daily 03:00)

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=keeper-self-heal.service

[Install]
WantedBy=timers.target
"""

def _uninstall_task(name, dry):
    """删除单个计划任务（不存在也不报错）。"""
    ok, out, err = _run_schtasks([
        "/Delete",
        "/TN", name,
        "/F",                       # 强制删除，不确认提示
    ], dry)
    if dry:
        # 干跑必须说「将做」而不是「已做」——否则用户以为任务真被删了（实测踩过）
        print("  [dry] 将移除 %s" % name)
        return True
    if ok or "错误: 找不到" in err or "not found" in err.lower():
        print("  [OK] 已移除 %s" % name)
        return True
    else:
        print("  [警告] %s 移除可能未成功: %s" % (name, err or out))
        return False


# ── 跨平台实现 ────────────────────────────────────────────
def _write_file(path, content, dry):
    print("  $ 写文件 %s" % path)
    if dry:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _run(cmd, dry, enc="utf-8"):
    """执行一条命令（非 schtasks 的通用版本，UTF-8 编码）。返回 (success, stdout, stderr)。"""
    cmd_str = " ".join('"%s"' % a if " " in a or not a else a for a in cmd)
    print("  $ %s" % cmd_str)
    if dry:
        return True, "[dry-run]", ""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, encoding=enc, errors="replace")
        ok = r.returncode == 0
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if not ok:
            print("    ! 返回码 %s: %s" % (r.returncode, err or out))
        return ok, out, err
    except Exception as e:
        print("    ! 执行异常: %s" % e)
        return False, "", str(e)


_LAUNCHD_DAEMON_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{label}</string>
	<key>ProgramArguments</key>
	<array>
		<string>{py}</string>
		<string>{daemon_py}</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>StandardOutPath</key>
	<string>{log}</string>
	<key>StandardErrorPath</key>
	<string>{log}</string>
</dict>
</plist>
"""

_LAUNCHD_IMA_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{label}</string>
	<key>ProgramArguments</key>
	<array>
		<string>{py}</string>
		<string>{ima_py}</string>
	</array>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Weekday</key>
		<integer>0</integer>
		<key>Hour</key>
		<integer>23</integer>
		<key>Minute</key>
		<integer>0</integer>
	</dict>
	<key>StandardOutPath</key>
	<string>{log}</string>
	<key>StandardErrorPath</key>
	<string>{log}</string>
</dict>
</plist>
"""

_SYSTEMD_DAEMON_TMPL = """[Unit]
Description=Keeper Recall Daemon (persistent semantic recall cache)

[Service]
Type=simple
ExecStart={py} {daemon_py}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

_SYSTEMD_IMA_SERVICE_TMPL = """[Unit]
Description=Keeper IMA weekly sync (export + desensitize)

[Service]
Type=oneshot
ExecStart={py} {ima_py}
"""

_SYSTEMD_IMA_TIMER_TMPL = """[Unit]
Description=Keeper IMA weekly sync timer (every Sunday 23:00)

[Timer]
OnCalendar=Sun *-*-* 23:00:00
Persistent=true
Unit=keeper-ima-weekly.service

[Install]
WantedBy=timers.target
"""


def _install_daemon_posix(dry):
    """macOS/Linux daemon 自启：launchd plist (Darwin) / systemd --user (Linux)。"""
    daemon_py = os.path.join(DAEMON_DST, "daemon.py")
    if not os.path.exists(daemon_py):
        print("  [跳过] daemon.py 不在 %s（请先运行 install_hooks.py）" % DAEMON_DST)
        return False
    sysname = platform.system()
    if sysname == "Darwin":
        return _install_daemon_darwin(dry, daemon_py)
    elif sysname == "Linux":
        return _install_daemon_linux(dry, daemon_py)
    print("  [不支持] 未知 POSIX 平台: %s" % sysname)
    return False


def _install_daemon_darwin(dry, daemon_py):
    launchd_dir = os.path.join(HOME, "Library", "LaunchAgents")
    plist_path = os.path.join(launchd_dir, "com.keeper.recall-daemon.plist")
    log = os.path.join(WB_HOME, "keeper_daemon", "daemon.log")
    plist = _LAUNCHD_DAEMON_TMPL.format(
        label="com.keeper.recall-daemon", py=PY, daemon_py=daemon_py, log=log)
    _write_file(plist_path, plist, dry)
    ok, out, err = _run(["launchctl", "load", plist_path], dry)
    if ok:
        print("  [OK] 已注册 launchd 自启 (%s)，登录时自动启动 keeper_daemon" % plist_path)
    else:
        print("  [提示] launchctl load 失败，可手动：launchctl bootstrap gui/%d %s"
              % (os.getuid(), plist_path))
    return ok


def _install_daemon_linux(dry, daemon_py):
    unit_dir = os.path.join(HOME, ".config", "systemd", "user")
    unit_path = os.path.join(unit_dir, "keeper-recall-daemon.service")
    unit = _SYSTEMD_DAEMON_TMPL.format(py=PY, daemon_py=daemon_py)
    _write_file(unit_path, unit, dry)
    ok, out, err = _run(["systemctl", "--user", "enable", "--now",
                         "keeper-recall-daemon.service"], dry)
    if ok:
        print("  [OK] 已注册 systemd --user 自启 (%s)，登录时自动启动 keeper_daemon" % unit_path)
    else:
        print("  [提示] systemctl --user 失败（需 loginctl enable-linger 或已登录会话）。"
              " 可手动：systemctl --user start keeper-recall-daemon")
    return ok


def _install_ima_sync_posix(dry):
    """macOS/Linux 每周同步：launchd StartCalendarInterval (Darwin) / systemd timer (Linux)。"""
    ima_py = os.path.join(SCRIPTS_DIR, "ima_sync.py")
    if not os.path.exists(ima_py):
        print("  [跳过] ima_sync.py 不在 %s" % SCRIPTS_DIR)
        return False
    sysname = platform.system()
    if sysname == "Darwin":
        return _install_ima_sync_darwin(dry, ima_py)
    elif sysname == "Linux":
        return _install_ima_sync_linux(dry, ima_py)
    print("  [不支持] 未知 POSIX 平台: %s" % sysname)
    return False


def _install_ima_sync_darwin(dry, ima_py):
    launchd_dir = os.path.join(HOME, "Library", "LaunchAgents")
    plist_path = os.path.join(launchd_dir, "com.keeper.ima-weekly.plist")
    log = os.path.join(WB_HOME, "ima_push", "scheduler.log")
    plist = _LAUNCHD_IMA_TMPL.format(
        label="com.keeper.ima-weekly", py=PY, ima_py=ima_py, log=log)
    _write_file(plist_path, plist, dry)
    ok, out, err = _run(["launchctl", "load", plist_path], dry)
    if ok:
        print("  [OK] 已注册 launchd 每周日 23:00 同步 (%s)" % plist_path)
    else:
        print("  [提示] launchctl load 失败，可手动：launchctl bootstrap gui/%d %s"
              % (os.getuid(), plist_path))
    return ok


def _install_ima_sync_linux(dry, ima_py):
    unit_dir = os.path.join(HOME, ".config", "systemd", "user")
    svc_path = os.path.join(unit_dir, "keeper-ima-weekly.service")
    timer_path = os.path.join(unit_dir, "keeper-ima-weekly.timer")
    _write_file(svc_path, _SYSTEMD_IMA_SERVICE_TMPL.format(py=PY, ima_py=ima_py), dry)
    _write_file(timer_path, _SYSTEMD_IMA_TIMER_TMPL, dry)
    ok, out, err = _run(["systemctl", "--user", "enable", "--now",
                         "keeper-ima-weekly.timer"], dry)
    if ok:
        print("  [OK] 已注册 systemd --user 每周日 23:00 同步定时 (%s)" % timer_path)
    else:
        print("  [提示] systemctl --user 失败（需 loginctl enable-linger 或已登录会话）。"
              " 可手动：systemctl --user start keeper-ima-weekly.timer")
    return ok


def _uninstall_posix(dry):
    """macOS/Linux 卸载：unload 并删除 plist / systemd unit。"""
    sysname = platform.system()
    if sysname == "Darwin":
        targets = [
            os.path.join(HOME, "Library", "LaunchAgents", "com.keeper.recall-daemon.plist"),
            os.path.join(HOME, "Library", "LaunchAgents", "com.keeper.ima-weekly.plist"),
            os.path.join(HOME, "Library", "LaunchAgents", "com.keeper.weekly-sync.plist"),
            os.path.join(HOME, "Library", "LaunchAgents", "com.keeper.self-heal.plist"),
        ]
        for p in targets:
            if os.path.exists(p) or dry:
                _run(["launchctl", "unload", p], dry)
                if not dry:
                    try:
                        os.remove(p)
                        print("  [OK] 已删除 %s" % p)
                    except Exception as e:
                        print("  [警告] 删除失败: %s" % e)
    elif sysname == "Linux":
        _run(["systemctl", "--user", "disable", "--now", "keeper-ima-weekly.timer"], dry)
        _run(["systemctl", "--user", "disable", "--now", "keeper-recall-daemon.service"], dry)
        _run(["systemctl", "--user", "disable", "--now", "keeper-weekly-sync.timer"], dry)
        _run(["systemctl", "--user", "disable", "--now", "keeper-self-heal.timer"], dry)
        unit_dir = os.path.join(HOME, ".config", "systemd", "user")
        for fn in ("keeper-ima-weekly.service", "keeper-ima-weekly.timer",
                   "keeper-recall-daemon.service", "keeper-weekly-sync.service",
                   "keeper-weekly-sync.timer", "keeper-self-heal.service",
                   "keeper-self-heal.timer"):
            p = os.path.join(unit_dir, fn)
            if os.path.exists(p):
                if dry:
                    print("  [dry] 将删除 %s" % p)
                else:
                    try:
                        os.remove(p)
                        print("  [OK] 已删除 %s" % p)
                    except Exception as e:
                        print("  [警告] 删除失败: %s" % e)
    else:
        print("  [不支持] 未知 POSIX 平台: %s" % sysname)


# ── 主入口 ─────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="安装/卸载 keeper 调度任务")
    ap.add_argument("--uninstall", action="store_true", help="移除已注册的调度任务")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不执行")
    args = ap.parse_args()

    print("=== keeper 调度器设置 (dry=%s, uninstall=%s) ===" % (args.dry_run, args.uninstall))
    print("平台: %s | PY: %s" % (platform.system(), PY))

    if args.uninstall:
        print("[卸载] 移除计划任务")
        if platform.system() == "Windows":
            _uninstall_task(TASK_DAEMON, args.dry_run)
            _uninstall_task(TASK_IMA_SYNC, args.dry_run)
            _uninstall_task(TASK_WEEKLY_SYNC, args.dry_run)
            _uninstall_task(TASK_SELF_HEAL, args.dry_run)
            # 顺手删 .bat 包装器
            for wname in ("keeper_ima_sync_run.bat", "keeper_weekly_sync_run.bat",
                          "keeper_self_heal_run.bat"):
                wrapper = os.path.join(WB_HOME, wname).replace("\\", "/")
                if os.path.exists(wrapper):
                    if args.dry_run:
                        print("  [dry] 将删除 %s" % wrapper)
                    else:
                        try:
                            os.remove(wrapper)
                            print("  [OK] 已删除包装器 %s" % wrapper)
                        except Exception as e:
                            print("  [警告] 删除包装器失败: %s" % e)
        else:
            _uninstall_posix(args.dry_run)
        print("=== 卸载完成 ===")
        return

    # 安装路径
    print("[1] 注册 daemon 开机自启 (%s)" % TASK_DAEMON)
    if platform.system() == "Windows":
        _install_daemon(args.dry_run)
    else:
        _install_daemon_posix(args.dry_run)

    print("[2] 注册 IMA 每周同步 (%s)" % TASK_IMA_SYNC)
    if platform.system() == "Windows":
        _install_ima_sync(args.dry_run)
    else:
        _install_ima_sync_posix(args.dry_run)

    print("[3] 注册每周协同（coach 体检 + to-l2 晋升草稿）(%s)" % TASK_WEEKLY_SYNC)
    if platform.system() == "Windows":
        _install_weekly_sync(args.dry_run)
    else:
        _install_weekly_sync_posix(args.dry_run)
    print("[4] 注册统一自治循环 self-heal 每日定时 (%s)" % TASK_SELF_HEAL)
    if platform.system() == "Windows":
        _install_self_heal(args.dry_run)
    else:
        _install_self_heal_posix(args.dry_run)

    print("=== 完成 ===")
    if args.dry_run:
        print("（dry-run：以上均未实际执行。去掉 --dry-run 重新运行以真正注册）")
        print("\n提示：安装后 daemon 会在下次用户登录时自动启动；")
        print("      如需立即启动 daemon，请运行：python install_hooks.py --start-daemon")


if __name__ == "__main__":
    main()
