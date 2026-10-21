# -*- coding: utf-8 -*-
"""CLI 调用与**并行取数**助手（唯一实现；各脚本不要再各写一份 subprocess 调用）。

为什么需要它（2026-09-21 实测）：
- 单次 `hithink-finance` 调用固定开销约 **1.1~1.6s**（node 启动 ~1s + 网络），
  与查询本身的大小几乎无关；
- 日更链路里「27 条板块指数历史」串行 ≈ **38s**、「10 只候选财务指标」串行 ≈ **13s**，
  两项合计约 **51s**，是除 `data sync` 之外的最大耗时；
- 它们彼此**完全独立** → 并行 8 路后降到 **3~5s**（实测见 `--selftest`）。

用法：
    import ths_cli
    j   = ths_cli.run(["special", "limit-up-pool", "--date-ms", ms, "--format", "json"])
    res = ths_cli.run_many([[["index","history","--thscode",c, ...]] for c in codes], workers=8)
    # res 与输入同序；每项是解析后的 dict，失败项为 {"ok": False, "error": {...}}

🔴 铁律：
1. 输出**不要接管道**（`| tail`/`head`）——CLI 可能留驻子进程继承 stdout，父进程等不到 EOF 会挂死；
   本模块一律 capture_output，不经过 shell 管道。
2. 单次调用固定开销 ~1.2s → **只要 ≥3 个独立调用就该并行**（`run_many`）。
3. 本模块**不写死任何个人路径**：CLI 与本地库位置一律运行时解析（见 `cli_command()` / `duckdb_path()`）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

__all__ = ["cli_command", "run", "run_many", "duckdb_path", "ok", "selftest", "DEFAULT_WORKERS"]

HOOK = "HITHINK_CLI"                 # 显式覆盖：`HITHINK_CLI="node /abs/path/main.js"`
PKG = "@hithink-tech/hithink-finance-cli"
REL = os.path.join("dist", "cli", "main.js")
DEFAULT_WORKERS = 8
_CACHE: dict[str, object] = {}


def _works(prefix: list[str]) -> bool:
    try:
        r = subprocess.run(prefix + ["--version"], capture_output=True, timeout=40,
                           stdin=subprocess.DEVNULL)
        return r.returncode == 0
    except Exception:
        return False


def _node_root() -> str:
    """WorkBuddy 的 node 根目录（版本无关的那一层）。

    布局：`~/.workbuddy/binaries/node/{versions/,cli-shared/,workspace/}`
    —— `versions/current` 是个**纯文本指针文件**（内容是版本号），
    说明 WorkBuddy 靠「每个版本一个目录 + 指针文件」管理 node：
    **版本一升级，旧版本目录被删除，装在里面的 npm 全局包就跟着消失**
    （PATH 与 `npm root -g` 却都指向新目录、看着完全正常 → 极易误判成「环境变量配错」）。
    """
    return os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "node")


def _node_from_pointer() -> str | None:
    """node 不在 PATH 时，用 `versions/current` 指针文件解析真实 node.exe。"""
    root = _node_root()
    ptr = os.path.join(root, "versions", "current")
    try:
        with open(ptr, encoding="utf-8", errors="replace") as f:
            ver = f.read().strip()
    except OSError:
        return None
    exe = os.path.join(root, "versions", ver, "node.exe")
    return exe if os.path.exists(exe) else None


def cli_command() -> list[str]:
    """定位 CLI 调用前缀（返回可执行 + 参数前缀列表）。

    解析顺序：① 环境变量 `HITHINK_CLI`（可含 "node /path/main.js" 两段）
    ② `PATH` 上的 `hithink-finance` ③ `node` 同级 node_modules 里的 main.js
    ④ **版本无关目录**（`<node根>/cli-shared/node_modules`、`/workspace/node_modules`）——
       这是防「node 版本升级导致全局包丢失」的关键一层，见 `_node_root()` 的注释
    ⑤ `npm root -g` 下的 main.js。**禁止写死个人绝对路径**（坑 10 同类）。
    """
    if "cli" in _CACHE:
        return _CACHE["cli"]  # type: ignore[return-value]
    cands: list[list[str]] = []
    env = os.environ.get(HOOK)
    if env:
        cands.append(env.split())
    exe = shutil.which("hithink-finance")
    if exe:
        cands.append([exe])
    # 稳定启动器（cli-shared/hithink-finance.cmd）：即使 node 版本换了也能用
    shim = os.path.join(_node_root(), "cli-shared", "hithink-finance.cmd")
    if os.path.exists(shim):
        cands.append([shim])
    node = shutil.which("node") or _node_from_pointer()
    bases: list[str] = []
    if shutil.which("node"):
        bases.append(os.path.join(os.path.dirname(shutil.which("node")), "node_modules"))  # type: ignore[arg-type]
    # 版本无关目录优先于全局目录（全局目录会随 node 版本目录一起被删）
    for sub in ("cli-shared", "workspace"):
        bases.append(os.path.join(_node_root(), sub, "node_modules"))
    try:
        npm = shutil.which("npm")
        if npm:
            out = subprocess.run([npm, "root", "-g"], capture_output=True, timeout=40,
                                 stdin=subprocess.DEVNULL)
            root = (out.stdout or b"").decode("utf-8", "replace").strip()
            if root:
                bases.append(root)
    except Exception:
        pass
    for b in bases:
        js = os.path.join(b, PKG, REL)
        if os.path.exists(js) and node:
            cands.append([node, js])
    for c in cands:
        if _works(c):
            _CACHE["cli"] = c
            return c
    raise RuntimeError(
        f"找不到可用的 hithink-finance CLI。已尝试：{cands or '（无候选）'}。"
        f"请确认 `hithink-finance --version` 可用，或设 `{HOOK}=...` 显式指定。"
        f"⚠️ 若刚升级过 node：npm 全局包装在 node 版本目录内、会随旧版本目录一起消失；"
        f"用国内镜像重装即可（官方源会卡死）："
        f"npm install --prefix \"{os.path.join(_node_root(), 'cli-shared')}\" "
        f"@hithink-tech/hithink-finance-cli")


def ok(j) -> bool:
    """统一判成功：`{"ok": true}`。"""
    return bool(isinstance(j, dict) and j.get("ok"))


def _once(args: list[str], timeout: int) -> dict:
    try:
        cmd = cli_command() + list(args)
    except Exception as e:
        return {"ok": False, "error": {"code": "CLI_NOT_FOUND", "message": str(e)}}
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "TIMEOUT", "message": f">{timeout}s: {' '.join(args[:3])}"}}
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    # ⚠️ CLI 在**校验失败**（如命令名非法、参数错）时把 JSON 信封写到 **stderr**，
    #    stdout 为空、rc=2 —— 旧实现只解析 stdout，于是退化成 `code=PARSE`，
    #    把结构化错误降级成一段纯文本，**连 CLI 自带的 error.code / hint 都丢了**。
    #    （2026-10-04 实测：`lhb list` 的 `CLI_UNKNOWN_COMMAND` 就是这么被吞掉的，
    #     进而让我把「命令名写错」误读成「接口没有数据」。）
    #    → 两个流都试；CLI 的进度信息可能混在 JSON 前面（如 data sync），故从 `{"ok"` 起截取。
    for src in (out, err):
        i = src.find('{"ok"')
        if i > 0:
            src = src[i:]
        if not src.strip():
            continue
        try:
            j = json.loads(src)
        except Exception:
            continue
        if isinstance(j, dict):
            return j
    return {"ok": False,
            "error": {"code": "PARSE", "rc": r.returncode,
                      "message": (out[:300] + err[:200]) or "空输出"}}


def _explain_unknown_command(env: dict, args: list) -> None:
    """失败原因是「命令名不存在」时，就地补上**正确命令名**并打印醒目提示。

    为什么（2026-10-04 实测）：
    ⚠️ **技能脚本里从来没错过** —— `daily_prep.py` 自 2026-09-22 起就一直写的是
    `special dragon-tiger --date <日>`（+ `--board-type org`），每天的 `lhb_MMDD.json` 都是真数据。
    错的是**我临时写的探测脚本**：为确认「09-30（非交易日、隔了 4 天）的特色数据能不能取」，
    我凭记忆手打了 `lhb list`（正确是 `special dragon-tiger`），CLI 只回 `CLI_UNKNOWN_COMMAND` + 空列表，
    于是我误读成「龙虎榜接口没有历史数据」，差点放弃整个证据维度。
    → 让 CLI 的报错**自带纠正信息**：任何调用方（含临时脚本）都能当场发现自己写错了命令名，
      而不是把「命令名错」误判成「接口没数据」。这条与 `verify_commands()` 互补：
      前者管"已知路径的静态校验"，后者管"任意临时调用的即时纠偏"。
    """
    code = str(((env.get("error") or {}).get("code") or "")).upper()
    if "UNKNOWN_COMMAND" not in code or not args:
        return
    try:
        valid = capability_commands()
    except Exception:                                   # noqa: BLE001
        return
    head = str(args[0])
    exact = sorted(" ".join(p) for p in valid if len(p) > 1 and p[0] == head)
    tail = next((str(a) for a in args[1:] if not str(a).startswith("-")), "")
    similar = (sorted(" ".join(p) for p in valid
                      if tail and tail.replace("-", "") in "".join(p)) if tail else [])
    # ③ 别名表（技能自己的简写，如 `lhb` → `special dragon-tiger`）
    alias = _COMMAND_ALIASES.get(head.lower(), "")
    groups = sorted({p[0] for p in valid if p})
    hint = (f"命令 `{' '.join(str(a) for a in args[:2])}` 不存在"
            + (f"；`{head}` 组下的真实命令 → {', '.join(exact[:10])}" if exact
               else f"；没有 `{head}` 这个命令组（可用的组 → {', '.join(groups)}）")
            + (f"；你是不是想用 → {', '.join(similar[:5])}" if similar else "")
            + (f"；本技能里 `{head}` 指的是 → **{alias}**" if alias else "")
            + "　⚠️ 别把它误读成「该接口没有数据」")
    env["error"]["hint"] = hint
    print(f"  ⚠️  {hint}")


def run(args: list[str], timeout: int = 90, retries: int = 0, backoff: float = 2.0) -> dict:
    """单次调用 → 解析后的 JSON dict；永不抛异常。

    `retries` > 0 时对失败**重试**（每次等待 `backoff × 尝试序号`）。
    ⚠️ 上游 `special`（特色数据）接口并发高会返回 `FUYAO_5002 timeout` —— 见 `run_many` 的分组并发建议。
    ⚠️ 命令名写错时（`CLI_UNKNOWN_COMMAND`）会**自动补上正确命令名**并打印提示，见 `_explain_unknown_command`。
    """
    last: dict = {}
    for k in range(retries + 1):
        last = _once(list(args), timeout)
        if ok(last):
            if k:
                last["_retried"] = k
            return last
        if k < retries:
            time.sleep(backoff * (k + 1))
    _explain_unknown_command(last, list(args))
    return last


def run_many(arg_lists, workers: int = DEFAULT_WORKERS, timeout: int = 90,
             retries: int = 0, backoff: float = 2.0) -> list[dict]:
    """**并行**执行多个 CLI 调用（顺序与输入一致，单项失败不影响其他）。

    实测：27 条指数历史串行 ≈42s → workers=8 并行 ≈12s。

    🔴 **并发上限取决于接口**（2026-09-21 实测教训）：
    - `index history` / `index snapshot` / `valuation snapshot` / `fund snapshot` 这类**行情/基础接口**：
      workers=8 稳定；
    - `special`（特色数据：涨停池/跌停池/炸板池/龙虎榜）**并发高会被上游限流**
      （返回 `FUYAO_5002 ... timeout`）→ 用 **workers ≤ 3**，并给 `retries=1~2`；
      其中 `special dragon-tiger`（整张龙虎榜）单次可能 >90s → `timeout≥180`。
    """
    arg_lists = [list(a) for a in arg_lists]
    if not arg_lists:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(arg_lists)))) as ex:
        return list(ex.map(lambda a: run(a, timeout=timeout, retries=retries, backoff=backoff), arg_lists))


def duckdb_path() -> str:
    """本地 DuckDB 路径：① `HITHINK_DUCKDB` ② `%LOCALAPPDATA%\\hithink-finance\\data\\market.duckdb`
    ③ `~/.local/share/hithink-finance/...`（非 Windows）。**不写死个人路径**。"""
    env = os.environ.get("HITHINK_DUCKDB")
    if env and os.path.exists(env):
        return env
    cands = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(os.path.join(la, "hithink-finance", "data", "market.duckdb"))
    home = os.path.expanduser("~")
    cands += [os.path.join(home, "AppData", "Local", "hithink-finance", "data", "market.duckdb"),
              os.path.join(home, ".local", "share", "hithink-finance", "data", "market.duckdb")]
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0] if cands else "market.duckdb"


# --------------------------------------------------------------------------- #
# --selftest：证明「并行确实更快」且「顺序与输入一致」
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 命令名校验：本技能依赖的 CLI 命令路径 + 权威清单比对
#
# 事情经过（2026-10-04，**必须先看清楚责任在哪**）：
#   ✅ **技能脚本从来没犯过这个错**：`daily_prep.py:131-132` 自它诞生（2026-09-22）起就一直写的是
#      `special dragon-tiger --date <日>`（+ `--board-type org`）；每天的 `lhb_MMDD.json` 都是真数据
#      （09-28 61 条 / 09-30 79 条），历史报告每天都有龙虎榜证据。
#   ❌ **错的是"临时探测脚本"**：为确认「09-30 是非交易日、隔了 4 天，特色数据还能不能取」，
#      我**凭记忆手打**了 `lhb list`（正确的组名是 `special`，命令是 `dragon-tiger`），
#      CLI 回 `CLI_UNKNOWN_COMMAND` + 空列表 → 我误读成「龙虎榜接口没有历史数据」，差点放弃这个证据维度。
#      真正没有 date 参数的只有 `anomaly-list` / `anomaly-stock` / `hot-stock`（见坑 77③）。
#
# 于是补两道闸（互补）：
#   ① 静态：`SKILL_COMMANDS` + `verify_commands()` —— 对照 `hithink-finance capabilities` 的权威清单逐条校验；
#   ② 动态：`_explain_unknown_command()` —— 任何调用（**含临时脚本**）写错命令名时，
#      报错里直接给出「可用命令组 + 本技能的别名指向」，杜绝"命令名错"被误读成"接口没数据"。
# ⚠️ 加了新命令后请同步 `SKILL_COMMANDS`，`--selftest` 会逐条校验。
# --------------------------------------------------------------------------- #
SKILL_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("data", "init"), ("data", "sync"), ("data", "status"),
    ("db", "export"), ("db", "query"),
    ("symbol", "search"),
    ("market", "snapshot"), ("market", "history"), ("market", "calendar"),
    ("index", "catalog"), ("index", "constituents"), ("index", "history"),
    ("financials", "income"), ("financials", "indicators"),
    ("valuation", "snapshot"),
    ("fund", "snapshot"), ("fund", "holdings"),
    ("special", "limit-up-pool"), ("special", "limit-down-pool"),
    ("special", "limit-break-pool"), ("special", "limit-up-ladder"),
    ("special", "dragon-tiger"), ("special", "anomaly-list"),
)

_CAP_CACHE: dict[str, set] = {}

# 本技能自己的**口头/文件名惯用简写 → 真实命令路径**。
# 为什么需要（2026-10-04）：技能产物叫 `lhb_MMDD.json`，我照着这个名字手打了 `lhb list` 去探测，
# 而 CLI 里根本没有 `lhb` 这个命令组（正确的是 `special dragon-tiger`），
# 且两者**没有任何字面相似度**，靠字符串匹配找不到 → 别名表补这一刀。
_COMMAND_ALIASES: dict[str, str] = {
    "lhb": "special dragon-tiger", "longhu": "special dragon-tiger",
    "zt": "special limit-up-pool", "limit-up": "special limit-up-pool",
    "dt": "special limit-down-pool", "zbg": "special limit-break-pool",
    "ladder": "special limit-up-ladder",
    "kline": "market history", "quote": "market snapshot", "calendar": "market calendar",
    "pe": "valuation snapshot", "fin": "financials indicators",
    "snapshot": "market snapshot", "pools": "market panel",
}


def capability_commands(refresh: bool = False) -> set[tuple[str, ...]]:
    """CLI **官方声明的全部合法命令路径**（`hithink-finance capabilities`，机器可读）。

    返回形如 `{("special","dragon-tiger"), ("market","history"), …}`。
    覆盖 remote 与本地命令（`data` / `db` 也在内），可直接用于校验。
    """
    if _CAP_CACHE.get("cmds") and not refresh:
        return _CAP_CACHE["cmds"]  # type: ignore[return-value]
    rows = run(["capabilities", "--format", "json"], timeout=90)
    paths = {tuple(it.get("command") or []) for it in (rows.get("data") or [])
             if isinstance(it, dict) and it.get("command")}
    _CAP_CACHE["cmds"] = paths
    return paths


def verify_commands(cmds=None) -> tuple[list[tuple[str, ...]], list[str]]:
    """校验命令路径是否合法 → (未知命令, 逐条提示)。

    提示里会给出**同组的真实子命令**，避免再去猜。
    """
    want = list(cmds if cmds is not None else SKILL_COMMANDS)
    valid = capability_commands()
    unknown = [tuple(c) for c in want if tuple(c) not in valid]
    msgs: list[str] = []
    for c in unknown:
        near = sorted(" ".join(p) for p in valid if p and p[0] == c[0])
        tail = c[-1].replace("-", "") if c else ""
        similar = sorted(" ".join(p) for p in valid if tail and tail in "".join(p))
        msgs.append(f"未知命令 `{' '.join(c)}`"
                    + (f"；同组可用 → {', '.join(near[:8])}" if near else "（该命令组不存在）")
                    + (f"；相近 → {', '.join(similar[:5])}" if similar else ""))
    return unknown, msgs


# --------------------------------------------------------------------------- #
def selftest() -> int:
    print("=" * 72)
    print("ths_cli 自检")
    print("=" * 72)
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            fails += 1

    # 1) CLI 定位
    try:
        cmd = cli_command()
        chk(True, f"CLI 定位成功：{' '.join(x if len(x) < 40 else '…/' + os.path.basename(x) for x in cmd)}")
    except Exception as e:
        chk(False, f"CLI 定位失败：{e}")
        return 1

    # 2) 本地库路径：解析是运行时算的，所以**源码里不能写死个人路径**（查源码，而非查解析结果）
    import re as _re
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    hard = _re.findall(r"[A-Za-z]:[\\/]Users[\\/][^\"'\s]+", src)
    chk(not hard, f"源码里没有写死个人绝对路径（命中：{hard or '无'}）")
    p = duckdb_path()
    chk(os.path.exists(p), f"本地库可解析：{p}")

    # 3) 顺序一致性 + 并行加速
    ms = lambda d: str(int(time.mktime(time.strptime(d, "%Y-%m-%d")) * 1000))
    codes = ["881101.TI", "881102.TI", "881103.TI", "881105.TI", "881108.TI", "881121.TI"]
    calls = [["index", "history", "--thscode", c, "--start-ms", ms("2026-09-01"),
              "--end-ms", ms("2026-09-21"), "--source", "remote", "--format", "json"] for c in codes]

    t0 = time.time()
    ser = [run(c) for c in calls]
    t_ser = time.time() - t0
    t0 = time.time()
    par = run_many(calls, workers=6)
    t_par = time.time() - t0
    print(f"  ⏱ {len(calls)} 次调用：串行 {t_ser:.1f}s → 并行 {t_par:.1f}s"
          f"（加速 {t_ser/max(t_par,0.01):.1f}×）")
    chk(all(ok(x) for x in par), f"并行结果全部 ok（{sum(1 for x in par if ok(x))}/{len(par)}）")
    same = all((a.get("data") or {}).get("item") == (b.get("data") or {}).get("item")
               for a, b in zip(ser, par))
    chk(same, "并行结果与串行**同序**（按输入顺序返回）")
    chk(t_par < t_ser * 0.7, f"并行确实更快（{t_par:.1f}s < {t_ser*0.7:.1f}s）")

    # 4) 失败不抛异常
    bad = run(["__not_a_command__"])
    chk(ok(bad) is False, "非法子命令返回 ok=False（不抛异常）")

    # 5) 命令名校验：先查 capabilities 权威清单，不再靠"猜子命令"
    valid = capability_commands()
    chk(len(valid) > 50, f"capabilities 权威清单拉取成功（{len(valid)} 条命令路径）")
    unknown, msgs = verify_commands()
    chk(not unknown, f"技能依赖的 {len(SKILL_COMMANDS)} 条命令全部合法"
                     + ("" if not unknown else " ｜ " + " ｜ ".join(msgs)))
    # 负例：故意写错必须被检出，且要给出正确建议（否则这条检查等于没有）
    bad_unknown, bad_msgs = verify_commands([("lhb", "list"), ("special", "limit-up"), ("__nope__",)])
    hint_ok = any("dragon-tiger" in m for m in bad_msgs)          # 能指到正确命令
    all_have_msg = len(bad_msgs) == len(bad_unknown)
    chk(len(bad_unknown) == 3 and all_have_msg and hint_ok,
        f"负例：错误命令名能被检出并给出正确建议（检出 {len(bad_unknown)} 条，"
        f"含 `dragon-tiger` 提示={hint_ok}）")
    # 任意临时调用写错命令名时，报错必须**自带正确命令名**（防「命令名错」被误读成「接口没数据」）
    env_bad = run(["lhb", "list"])
    _hint = str(((env_bad.get("error") or {}).get("hint") or ""))
    chk(ok(env_bad) is False and "dragon-tiger" in _hint,
        f"未知命令的报错自带纠正提示（含 `dragon-tiger`={'dragon-tiger' in _hint}）")

    # 6) 稳定启动器必须是 CRLF + 纯 ASCII（LF-only 会被 cmd.exe 解析异常 → 实测直接挂死）
    shim = os.path.join(_node_root(), "cli-shared", "hithink-finance.cmd")
    if os.path.exists(shim):
        raw = open(shim, "rb").read()
        bare = raw.count(b"\n") - raw.count(b"\r\n")
        chk(all(b < 128 for b in raw), "稳定启动器内容为纯 ASCII")
        chk(bare == 0, f"稳定启动器行尾全为 CRLF（裸 LF {bare} 处）")
    else:
        print("  ℹ️  未发现 cli-shared/hithink-finance.cmd（可选，不影响本机）")

    print(f"\n自检结果：{'全部通过 ✅' if not fails else f'{fails} 项失败 ❌'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="hithink-finance CLI 调用与并行取数助手")
    ap.add_argument("--selftest", action="store_true", help="自检：定位 CLI / 本地库 / 并行加速")
    ap.add_argument("--where", action="store_true", help="打印解析到的 CLI 与本地库路径")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.where:
        print("CLI  :", " ".join(cli_command()))
        print("DuckDB:", duckdb_path())
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
