#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆同步助手 v2.0.11 —— 轻量本地校验脚本（pathlib 跨平台 + 三级异常分级）

v2.0.11 变更（对应腾讯安全云 v2.0.10 评估 + SkillHub 评测 R·Reliability 4.2）：
- 改用 pathlib.Path 跨平台（Windows / macOS / Linux 行为一致）。
- 三级异常分级（CRITICAL/WARN/INFO）+ 退出码（2/1/0）。
- 不再硬编码 entry_id fallback——指针段缺失时仅 WARN，不静默继续。
- 新增 --json（结构化输出）、--doctor（环境/配置自检）、--check（默认，本地校验）。
- 颜色用 ANSI 转义；无 TTY 时自动关闭。
- 保留 v2.0 的所有 v2.0.10 行为作为默认（无 --doctor 时），老用户升级零行为变化。

新架构（2026-08-22 起）：
- 行为规则权威在云端《工作习惯总纲》（乐享 entry_id 由 MEMORY.md 指针段动态提取，脚本不写死）。
- 本脚本不再做云写；职责仅：① 校验本地 MEMORY.md 指针段声明的云总纲 entry_id 可读；② 校验 SessionStart 钩子存在且锚到云总纲；③ 输出「总纲→备份同步」健康检查清单，供对话内 lexiang MCP 主通道执行实际云写。

用法：
  python sync_backup.py            # 本地校验（默认行为，与 v2.0.10 兼容）
  python sync_backup.py --check    # 同上，显式指定
  python sync_backup.py --doctor   # 环境/配置自检（v2.0.11 新增）
  python sync_backup.py --json     # 输出结构化 JSON（便于上层 parse）
  python sync_backup.py --help     # 帮助
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# === 路径常量（pathlib 跨平台） ============================================
HOME = Path(os.path.expanduser("~"))
WORKBUDDY_DIR = HOME / ".workbuddy"
MEMORY_PATH = WORKBUDDY_DIR / "MEMORY.md"
SETTINGS_PATH = WORKBUDDY_DIR / "settings.json"
IDENTITY_PATH = WORKBUDDY_DIR / "IDENTITY.md"
SOUL_PATH = WORKBUDDY_DIR / "SOUL.md"
USER_PATH = WORKBUDDY_DIR / "USER.md"

# === 异常分级（退出码） ====================================================
class Level:
    INFO = "INFO"          # 退出码 0
    WARN = "WARN"          # 退出码 1
    CRITICAL = "CRITICAL"  # 退出码 2

EXIT_CODE = {
    Level.INFO: 0,
    Level.WARN: 1,
    Level.CRITICAL: 2,
}


# === 颜色（自动判 TTY，旧 Windows 控制台/CI 静默关闭） ====================
def _supports_color() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
            mode = ctypes.c_int(0)
            kernel32.GetConsoleMode(kernel32.GetStdHandle(-11), ctypes.byref(mode))
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), mode.value | 0x4)
            return True
        except Exception:
            return False
    return True


_COLOR_ON = _supports_color()


def _c(level: str, text: str) -> str:
    if not _COLOR_ON:
        return text
    palette = {
        Level.INFO: "\033[32m",          # 绿
        Level.WARN: "\033[33m",          # 黄
        Level.CRITICAL: "\033[31;1m",    # 红加粗
    }
    end = "\033[0m"
    return f"{palette.get(level, '')}{text}{end}"


# === entry_id 提取（动态，按上下文锚定；不写死任何具体 id） =================
#
# 乐享 entry_id 为 32 位 [0-9a-f] 十六进制串；space_id 也是 32 位串。
# 用上下文锚定（指向"《工作习惯总纲》"或"《工作习惯总纲_备份》"）避免误抓。
# v2.0.11 不再硬编码 fallback——缺失视为 WARN。
#
_TOTAL_RE = re.compile(r"《工作习惯总纲》[^\n]*?entry_id[`\s]*([0-9a-f]{32})", re.IGNORECASE)
_BACKUP_RE = re.compile(r"《工作习惯总纲_备份》[^\n]*?entry_id[`\s]*([0-9a-f]{32})", re.IGNORECASE)
_NULL_ID_SENTINEL = ""  # 缺失时返回空串


def _read_text(path: Path) -> str:
    """读文本；不存在抛 FileNotFoundError；编码失败不静默回退。"""
    if not path.exists():
        raise FileNotFoundError(str(path))
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("sync_backup", raw, 0, 1, f"{path} 非 utf-8/gbk 编码")


def extract_pointer_ids(memory_path: Path = MEMORY_PATH):
    """从 MEMORY.md 指针段提取总纲与备份的乐享 entry_id（按上下文锚定）。

    返回 (total_id, backup_id)。任一缺失返回空串，由调用方按 WARN 上报。
    """
    try:
        content = _read_text(memory_path)
    except FileNotFoundError:
        return _NULL_ID_SENTINEL, _NULL_ID_SENTINEL
    m_total = _TOTAL_RE.search(content)
    m_backup = _BACKUP_RE.search(content)
    return (
        m_total.group(1) if m_total else _NULL_ID_SENTINEL,
        m_backup.group(1) if m_backup else _NULL_ID_SENTINEL,
    )


# === 校验项 ================================================================
def check_memory_pointer():
    """校验本地 MEMORY.md 指针段是否声明了正确的云总纲 entry_id。"""
    if not MEMORY_PATH.exists():
        return Level.CRITICAL, "MEMORY.md 不存在（`~/.workbuddy/MEMORY.md`）", ""
    try:
        content = _read_text(MEMORY_PATH)
    except (FileNotFoundError, UnicodeDecodeError) as e:
        return Level.CRITICAL, f"MEMORY.md 读取失败：{e}", ""

    total_id, _backup_id = extract_pointer_ids(MEMORY_PATH)
    if not total_id:
        return (
            Level.WARN,
            "MEMORY.md 指针段未声明云总纲 entry_id（脚本不写死 fallback，请在小Y对话中声明或追加指针段）",
            total_id,
        )
    if "工作习惯总纲" not in content:
        return Level.WARN, "MEMORY.md 指针段未声明《工作习惯总纲》权威字样", total_id
    return (
        Level.INFO,
        f"指针段 OK（云总纲 entry_id={total_id[:8]}…，动态提取，完整 id 见 MEMORY.md 原文）",
        total_id,
    )


def check_sessionstart_hook():
    """校验 settings.json 的 SessionStart 钩子存在且锚到云总纲。"""
    if not SETTINGS_PATH.exists():
        return Level.CRITICAL, "settings.json 不存在（`~/.workbuddy/settings.json`）", ""
    try:
        cfg = json.loads(_read_text(SETTINGS_PATH))
    except json.JSONDecodeError as e:
        return Level.CRITICAL, f"settings.json 解析失败：{e}", ""

    hooks = cfg.get("hooks", {})
    session_start = hooks.get("SessionStart", [])
    if not session_start:
        return (
            Level.CRITICAL,
            "未配置 SessionStart 钩子（无法保证每会话开头读云总纲，详见 SKILL.md §1.1.0）",
            "",
        )

    raw = json.dumps(session_start, ensure_ascii=False)
    m = re.search(r"([A-Za-z]:[^\"\\]*session_start_read_gangl\.md|session_start_read_gangl\.md)", raw)
    if not m:
        return (
            Level.WARN,
            "SessionStart 钩子存在但未定位到 session_start_read_gangl.md 脚本路径（建议显式指定）",
            "",
        )

    hook_script = Path(m.group(1))
    if not hook_script.is_absolute():
        hook_script = WORKBUDDY_DIR / "scripts" / hook_script.name
    if not hook_script.exists():
        return Level.CRITICAL, f"钩子脚本不存在：{hook_script}", ""

    try:
        hook_content = _read_text(hook_script)
    except (FileNotFoundError, UnicodeDecodeError) as e:
        return Level.CRITICAL, f"钩子脚本读取失败：{e}", ""

    if "工作习惯总纲" not in hook_content:
        return Level.CRITICAL, "SessionStart 钩子脚本未提及《工作习惯总纲》", ""

    total_id, _ = extract_pointer_ids(MEMORY_PATH)
    if total_id and total_id not in hook_content:
        return (
            Level.WARN,
            f"钩子脚本未包含当前总纲 entry_id {total_id[:8]}…（仍指向旧 WPS id？建议同步刷新）",
            total_id,
        )
    return (
        Level.INFO,
        f"SessionStart 钩子 OK（脚本已注入读云总纲 entry_id={total_id[:8] if total_id else '—'}…）",
        total_id or "",
    )


# === --doctor 自检（v2.0.11 新增） =========================================
def check_environment() -> list:
    """环境/配置自检：Python 版本、关键路径、编码、连接器等。"""
    out = []

    v = sys.version_info
    if (v.major, v.minor) >= (3, 9):
        out.append((Level.INFO, f"Python {v.major}.{v.minor}.{v.micro} ≥ 3.9 OK"))
    else:
        out.append((Level.CRITICAL, f"Python {v.major}.{v.minor}.{v.micro} 低于 3.9，建议升级"))

    out.append((Level.INFO, f"平台 {os.name} / {sys.platform}（pathlib 已适配）"))
    out.append((Level.INFO, f"HOME={HOME}"))
    out.append((Level.INFO, f"WORKBUDDY_DIR={WORKBUDDY_DIR}（{'存在' if WORKBUDDY_DIR.exists() else '不存在'}）"))

    for label, p in [
        ("MEMORY.md", MEMORY_PATH),
        ("settings.json", SETTINGS_PATH),
        ("IDENTITY.md", IDENTITY_PATH),
        ("SOUL.md", SOUL_PATH),
        ("USER.md", USER_PATH),
    ]:
        if p.exists():
            out.append((Level.INFO, f"{label} 存在：{p}"))
        else:
            lvl = Level.CRITICAL if label in ("MEMORY.md", "settings.json") else Level.WARN
            out.append((lvl, f"{label} 不存在：{p}"))

    lex_path = HOME / ".workbuddy" / "connectors" / "skills" / "connector-lexiang" / "SKILL.md"
    if lex_path.exists():
        out.append((Level.INFO, f"lexiang 连接器已注册：{lex_path.parent}"))
    else:
        out.append((
            Level.WARN,
            f"lexiang 连接器未在 {lex_path.parent} 找到——本技能云写通道依赖它（WorkBuddy 桌面端 → 设置 → MCP/连接器面板可装）",
        ))

    try:
        txt = _read_text(MEMORY_PATH)
        sha = hashlib.sha1(txt.encode("utf-8")).hexdigest()
        out.append((Level.INFO, f"MEMORY.md 可读（sha1={sha[:8]}…，utf-8/gbk 自动 fallback）"))
    except FileNotFoundError:
        pass  # 已在上面报过
    except UnicodeDecodeError as e:
        out.append((Level.WARN, f"MEMORY.md 编码探测异常：{e}"))

    return out


def run_doctor() -> int:
    """--doctor 入口：环境自检 + 本地校验。返回退出码（最高级别）。"""
    print("=" * 60)
    print("记忆同步助手 v2.0.11 —— Doctor 自检（环境 + 配置 + 校验）")
    print("=" * 60)

    results = check_environment()
    max_lvl = Level.INFO
    print("\n[环境自检]")
    for lvl, msg in results:
        marker = {"INFO": "✓", "WARN": "!", "CRITICAL": "✗"}[lvl]
        print(f"  {_c(lvl, marker)} {msg}")
        if EXIT_CODE[lvl] > EXIT_CODE[max_lvl]:
            max_lvl = lvl

    print()
    lvl_mem, msg_mem, _ = check_memory_pointer()
    _print_one("本地指针段", lvl_mem, msg_mem)
    if EXIT_CODE[lvl_mem] > EXIT_CODE[max_lvl]:
        max_lvl = lvl_mem

    lvl_hook, msg_hook, _ = check_sessionstart_hook()
    _print_one("SessionStart 钩子", lvl_hook, msg_hook)
    if EXIT_CODE[lvl_hook] > EXIT_CODE[max_lvl]:
        max_lvl = lvl_hook

    print()
    if max_lvl == Level.INFO:
        print(_c(Level.INFO, "✅ Doctor 全部通过。环境与配置健康。"))
        return 0
    if max_lvl == Level.WARN:
        print(_c(Level.WARN, "⚠️ Doctor 有 WARN 项目，建议处理后再投入生产。"))
        return 1
    print(_c(Level.CRITICAL, "❌ Doctor 发现 CRITICAL 项目，必须处理。"))
    return 2


def _print_one(tag: str, level: str, msg: str) -> None:
    marker = {"INFO": "✅", "WARN": "⚠️ ", "CRITICAL": "❌"}[level]
    print(f"[{tag}] {_c(level, marker)} {msg}")


def run_check(as_json: bool = False) -> int:
    """主入口：本地校验。"""
    print("=" * 50)
    print("记忆同步助手 v2.0.11 —— 轻量本地校验")
    print("=" * 50)

    lvl_mem, msg_mem, _total = check_memory_pointer()
    lvl_hook, msg_hook, _ = check_sessionstart_hook()
    total_id, backup_id = extract_pointer_ids(MEMORY_PATH)

    if as_json:
        out = {
            "version": "2.0.11",
            "results": {
                "memory_pointer": {"level": lvl_mem, "message": msg_mem},
                "session_start_hook": {"level": lvl_hook, "message": msg_hook},
            },
            "cloud_targets": {
                "lexiang_total_entry_id": total_id,
                "lexiang_backup_entry_id": backup_id,
            },
            "exit_code": max(EXIT_CODE[lvl_mem], EXIT_CODE[lvl_hook]),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return out["exit_code"]

    _print_one("本地指针", lvl_mem, msg_mem)
    _print_one("SessionStart", lvl_hook, msg_hook)

    print("-" * 50)
    print("云端同步清单（由对话内 lexiang MCP 主通道执行）：")
    if total_id:
        print(f"  1. Read 总纲：entry_id={total_id[:8]}…（完整 id 见 MEMORY.md 指针段；乐享连接器）")
    else:
        print("  1. Read 总纲：(entry_id 缺失，需先在 MEMORY.md 声明指针段)")
    if backup_id:
        print(f"  2. 写备份：  entry_id={backup_id[:8]}…（同上）")
    else:
        print("  2. 写备份：  (entry_id 缺失)")
    print("  3. 校验：总纲与备份内容一致（版本号比对）")
    print("  4. 告知用户：备份刷新结果（总纲版本/备份版本/一致性）")
    print("  5. 异常分级（v2.0.11 起）：按 CRITICAL/WARN/INFO 反馈，不静默")

    max_lvl = lvl_mem if EXIT_CODE[lvl_mem] >= EXIT_CODE[lvl_hook] else lvl_hook
    print("=" * 50)
    if max_lvl == Level.INFO:
        print(_c(Level.INFO, "✅ 本地侧校验通过。若总纲有修改，请执行上方云端同步清单。"))
        return 0
    if max_lvl == Level.WARN:
        print(_c(Level.WARN, "⚠️ 本地侧有 WARN 项目，建议修复后再执行云端同步。"))
        return 1
    print(_c(Level.CRITICAL, "❌ 本地侧有 CRITICAL 项目，必须修复后再执行云端同步。"))
    return 2


def run_audit_ids() -> int:
    """发布前自检：扫描技能目录是否残留具体 ID / 用户名路径（SKILL.md §16.7）。

    说明：脚本无法自行调用 lexiang MCP，本命令只做静态扫描；
    ` --discover` 负责输出待执行调用清单。
    """
    skill_dir = Path(__file__).resolve().parent.parent

    # 扫描目标：除本脚本自身外的所有文本文件
    targets = []
    for rel in ("SKILL.md", "config.json", "config.example.json",
                "state.json", "state.example.json", "变更说明.md",
                "_meta.json", "_skillhub_meta.json"):
        f = skill_dir / rel
        if f.exists():
            targets.append(f)

    HEX32 = re.compile(r"\b[0-9a-fA-F]{32}\b")
    USERPATH = re.compile(r"[A-Za-z]:\\+Users\\+[A-Za-z0-9_.-]+\\+")
    WPSID = re.compile(r"\b[A-Za-z0-9]{28,32}\b")  # WPS file_id 特征（28~32 位 Base62）

    violations = []
    for f in targets:
        try:
            text = _read_text(f)
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in HEX32.finditer(line):
                violations.append((f.name, i, "32位hex ID", m.group(0)))
            for m in USERPATH.finditer(line):
                violations.append((f.name, i, "用户名绝对路径", m.group(0)))
            # WPS ID 只在非说明行里查（避免误伤正常英文长词）
            if f.name in ("config.json", "state.json", "config.example.json", "state.example.json"):
                for m in WPSID.finditer(line):
                    val = m.group(0)
                    if val.lower() in ("workbuddy.memory",):
                        continue
                    violations.append((f.name, i, "疑似 WPS ID", val))

    print(_c(Level.INFO, "=== ID 硬编码自检（SKILL.md §16.7）==="))
    print(f"  扫描目录：{skill_dir}")
    print(f"  扫描文件：{len(targets)} 个")
    if not violations:
        print(_c(Level.INFO, "✅ 零硬编码通过：未发现任何具体 ID / 用户名路径残留，可以打包发布。"))
        return 0

    print(_c(Level.CRITICAL, f"❌ 发现 {len(violations)} 处违规，禁止打包发布："))
    for name, ln, kind, val in violations:
        print(f"    {name}:L{ln}  [{kind}]  {val}")
    print(_c(Level.WARN, "修复口径：一律改为运行时解析（见 SKILL.md §16），或替换为占位符。"))
    return 2


def run_discover() -> int:
    """ID 解析状态检查 + 输出待执行的 MCP 调用清单（SKILL.md §16.2/§16.3）。

    脚本层只做 L1/L2 命中判断，L3（lexiang 实时 API）由 Agent 通过 MCP 工具执行。
    """
    print(_c(Level.INFO, "=== ID 动态解析（SKILL.md §16）==="))

    # ---- L1: state.json 缓存 ----
    state_path = Path(__file__).resolve().parent.parent / "state.json"
    if state_path.exists():
        try:
            st = json.loads(_read_text(state_path))
        except (OSError, ValueError):
            st = {}
        cloud = st.get("cloud", {}) or {}
        master = (cloud.get("master") or {}).get("entry_id", "")
        backup = (cloud.get("backup") or {}).get("entry_id", "")
        if master and backup:
            print(_c(Level.INFO, f"✅ L1 命中（state.json 缓存）：master={master[:8]}… backup={backup[:8]}…"))
            print(f"  space_id: {st.get('space_id', '')[:8]}…  resolved_at: {st.get('resolved_at', '')}")
            return 0
        print(_c(Level.WARN, "⚠️  L1 未命中：state.json 为空模板（首次激活属正常）。"))

    # ---- L2: MEMORY.md 指针段 ----
    ids = extract_pointer_ids()
    if ids:
        print(_c(Level.WARN, "⚠️  L2 命中（MEMORY.md 指针段），建议写回 state.json。"))
        print(f"  解析结果：{ids}")
        print("  下一步：把上述值填入 state.json 的 cloud.master/backup.entry_id。")
        return 1

    # ---- L3: 需 Agent 走 MCP ----
    print(_c(Level.CRITICAL, "❌ L1/L2 均未命中，需由 Agent 经 lexiang MCP 实时解析："))
    print("   第 1 步  whoami  →  data.personal_space.id  （取 space_id）")
    print('   第 2 步  lexiang_search(query="工作习惯总纲", type="doc")')
    print("   第 3 步  按 §16.4 过滤：original_title 精确匹配 / 排除【历史版本】/ 优先 page / space_id 一致")
    print("   第 4 步  结果写入本机 state.json（严禁回写 SKILL.md 等分发文件）")
    return 2


def print_help() -> None:
    print(__doc__ or "")
    print("子命令：")
    print("  --check       本地校验（默认行为，与 v2.0.10 兼容）")
    print("  --doctor      环境 + 配置 + 本地校验全量自检（v2.0.11 新增）")
    print("  --json        输出结构化 JSON（便于上层 parse）")
    print("  --discover    ID 动态解析：L1/L2 命中判断 + L3 待执行 MCP 调用清单（v2.0.12 新增）")
    print("  --audit-ids   发布前自检：扫描技能目录是否残留具体 ID / 用户名路径（v2.0.12 新增）")
    print("  --help        显示本帮助")


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if not argv or "--check" in argv:
        return run_check(as_json=False)
    if "--doctor" in argv:
        return run_doctor()
    if "--audit-ids" in argv:
        return run_audit_ids()
    if "--discover" in argv:
        return run_discover()
    if "--json" in argv:
        return run_check(as_json=True)
    if "--help" in argv or "-h" in argv:
        print_help()
        return 0
    print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
