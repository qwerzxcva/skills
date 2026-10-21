# -*- coding: utf-8 -*-
"""
gen_cookbook.py — COOKBOOK.md 与代码一致性校验（防文档漂移）

为什么需要：
COOKBOOK.md 是高级特性的「唯一真相源」，但它本质是手写文档。
一旦脚本改名 / 删除 / flag 变了，文档不会自动跟着变 → 新手照文档跑会踩空。
本脚本在发版前（publish 流程里）跑一次：
- 抽出 COOKBOOK.md 里所有 `python <脚本> [flags]` 命令
- 校验脚本文件是否还在
- 校验文档宣称的 flag 在脚本 docstring / 源码里是否真存在
- 校验 §3 / §4 是否含「⚠️ 关键限制」与 IMA「脚本不推送」红线
一致 → 退出 0；有漂移 → 打印明细（**默认仍退出 0**，加 `--strict` 才非零退出，
由 publish 门禁据此拦下）。

用法：
python scripts/gen_cookbook.py            # 校验，打印报告
python scripts/gen_cookbook.py --strict   # 漂移即非零退出（供发版门禁）
"""
import os
import re
import sys
import argparse

SKILL = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(SKILL)  # 上溯到 skill 根
COOKBOOK = os.path.join(SKILL, "references", "COOKBOOK.md")

# 文档里出现的「python <相对脚本> [flags]」命令模式
CMD_RE = re.compile(r"python\s+([\w./\\-]+)((?:--[\w-]+|\s+<[^>]+>|\s+[\w./\\-]+)*)")

# 需要在脚本里能找到的 flag（文档宣称的）
FLAG_RE = re.compile(r"(--[\w-]+)")

# 每个被引脚本必须存在的「行为关键字」（出现在 docstring 或源码即算通过）
EXPECTED_BEHAVIOR = {
    "setup_scheduler.py": ["KeeperRecallDaemon", "KeeperIMAWeeklySync", "--uninstall", "--dry-run"],
    "scripts/ima_sync.py": ["--open", "--kb-id", "脱敏", "推送指令"],
    "scripts/migrate_v30.py": ["AI_MEMORY_STORE", "幂等"],
    "install_hooks.py": ["--dry-run", "--setup-scheduler"],
    "keeper_daemon/daemon.py": ["warmup", "127.0.0.1", "token"],
}


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _src_with_package(script_path):
    """取脚本源码；若它是「包入口」，把包内子模块一并纳入。

    两种包入口都要跟：
    - **包内 `__init__.py`**：memory_ops 已拆成包，参数声明落在 `_cli.py` 等子模块里，
      `__init__.py` 只做重导出。只读它会把真实存在的 flag 误报成
      「文档宣称但代码里没有」——噪音会盖掉真正的漂移。
    - **根目录转发垫片**（`scripts/memory_ops.py` → `scripts/memory_ops/`）：
      文档里写的是 `python scripts/memory_ops.py backup --zip x`，而垫片只有 3 行
      `runpy.run_path`。不跟进去，主 CLI 入口的 flag 就**从来没人校验**——
      既是假红灯（实测 `--zip` / `--keep`），也意味着这条闸门对主入口是失效的。
    """
    src = _read(script_path)
    d = None
    if os.path.basename(script_path) == "__init__.py":
        d = os.path.dirname(script_path)
    else:
        base = script_path[:-3] if script_path.endswith(".py") else script_path
        if os.path.isdir(base):          # 同名包目录存在 → 这是转发垫片
            d = base
    if d:
        try:
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".py") and fn != os.path.basename(script_path):
                    src += "\n" + _read(os.path.join(d, fn))
        except Exception:
            pass
    return src


def check():
    problems = []
    cook = _read(COOKBOOK)
    if not cook:
        problems.append("COOKBOOK.md 读不到：%s" % COOKBOOK)
        return problems

        # 1) 抽取命令并校验脚本存在 + flag 真实
    for m in CMD_RE.finditer(cook):
        rel = m.group(1)
        rest = m.group(2)
        # 跳过明显非脚本（如 python3 / python 单独）
        if rel in ("python", "python3"):
            continue
        script_path = os.path.join(SKILL, rel.replace("/", os.sep))
        if not os.path.isfile(script_path):
            problems.append("[命令] 脚本不存在：%s（COOKBOOK 引用，但文件缺失）" % rel)
            continue
        src = _src_with_package(script_path)
        # flag 校验
        for fm in FLAG_RE.finditer(rest):
            flag = fm.group(1)
            if flag not in src:
                problems.append("[flag] %s 宣称的 %s 在 %s 里找不到" % (rel, flag, rel))

                # 2) 行为关键字校验（docstring/源码）
    for rel, keys in EXPECTED_BEHAVIOR.items():
        script_path = os.path.join(SKILL, rel.replace("/", os.sep))
        if not os.path.isfile(script_path):
            problems.append("[行为] 脚本缺失：%s" % rel)
            continue
        src = _read(script_path)
        for k in keys:
            if k not in src:
                problems.append("[行为] %s 缺少预期关键字 %r（文档/代码可能漂移）" % (rel, k))

                # 3) 关键限制块存在性
    if "## 3. 定时调度" in cook and "⚠️ 关键限制" not in cook[cook.find("## 3. 定时调度"):cook.find("## 4.")]:
        problems.append("[结构] §3 定时调度缺少 ⚠️ 关键限制 块")
    if "## 4. IMA 同步" in cook:
        sec4 = cook[cook.find("## 4. IMA 同步"):cook.find("## 5.")]
        if "⚠️ 关键限制" not in sec4:
            problems.append("[结构] §4 IMA 同步缺少 ⚠️ 关键限制 块")
        if "脚本不推送" not in sec4:
            problems.append("[红线] §4 未写明 IMA「脚本不推送」红线（最易踩坑项）")

    return problems


def main():
    ap = argparse.ArgumentParser(description="COOKBOOK.md 一致性校验")
    ap.add_argument("--strict", action="store_true", help="有漂移则非零退出")
    args = ap.parse_args()

    problems = check()
    if not problems:
        print("✅ COOKBOOK.md 与代码一致，无漂移。")
        return 0
    print("⚠️ 发现 %d 处可能的文档/代码漂移：" % len(problems))
    for p in problems:
        print("  - %s" % p)
    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
