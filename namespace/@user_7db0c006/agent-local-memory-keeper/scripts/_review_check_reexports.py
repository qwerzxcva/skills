#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_review_check_reexports.py — 一次性审查脚本，**不进门禁**（命名以 `_review_` 开头即此意）。

用途：反查 `scripts/` 下所有脚本通过 `memory_ops.X` / `from memory_ops import X`
引用到的名字，是否都真实存在于 `memory_ops` 上。

⚠️ 覆盖边界（读结果前必看）：
1. 它扫不到「包内调用」——`memory_ops/_*.py` 子模块跳过，且包内根本不写
   `import memory_ops` 语句（依赖由 `__init__.py` 加载末期注入，避循环 import），
   所以基于 import 语句的静态分析抓不到它们。
2. 即使外部脚本引用了不存在的名字，**运行时也不一定报错**：`__init__.py` 末尾有
   PEP 562 模块级 `__getattr__` 兜底，会把属性动态捞出来。
   → 因此本脚本报「MISSING 0」**不等于**没问题，只能说明没抓到。

**自动化检查已由 `scripts/tests/test_reexports.py` 接管**（AST 精确扫描、进门禁、
有负向自测），本脚本仅保留用于人工排查时的辅助输出。
"""

import os, re, sys

# 动态推导 skill 根目录（避免硬编码用户名路径泄漏/本机必崩）
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL, "scripts"))

# --- import the package (this is the smoke test; import errors surface here) ---
try:
    import memory_ops as mo
except Exception as e:
    print("IMPORT_FAILED:", repr(e))
    sys.exit(2)

mo_names = set(dir(mo))

# --- discover every attribute accessed on memory_ops by external scripts ---
alias_re = re.compile(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(')  # func-style calls
attr_re  = re.compile(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)')        # any attr access
import_as_re = re.compile(r'import\s+memory_ops\s+as\s+([A-Za-z_]\w*)')
from_imp_re  = re.compile(r'from\s+memory_ops\s+import\s+(.+?)(?:$|\n)')

scripts_dir = os.path.join(SKILL, "scripts")
referenced = set()
checked_files = 0

for root, dirs, files in os.walk(scripts_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        full = os.path.join(root, f)
        rel_parts = os.path.relpath(full, scripts_dir).split(os.sep)
        # skip the package loader and its submodules (internal, not external callers)
        if rel_parts[0] == "memory_ops" and (rel_parts[-1] == "__init__.py" or rel_parts[-1].startswith("_")):
            continue
        try:
            src = open(full, encoding="utf-8").read()
        except Exception:
            continue
        checked_files += 1
        # aliases declared in this file
        aliases = set(import_as_re.findall(src))
        # also the canonical bare `import memory_ops` then used as memory_ops.X
        if re.search(r'(?m)^\s*import\s+memory_ops\s*$', src):
            aliases.add("memory_ops")
        for m in from_imp_re.finditer(src):
            chunk = m.group(1)
            for nm in re.findall(r'([A-Za-z_]\w*)', chunk):
                referenced.add(nm)
        for am in attr_re.finditer(src):
            alias, name = am.group(1), am.group(2)
            if alias in aliases:
                referenced.add(name)

                # remove python builtins / obvious non-symbols
referenced = {n for n in referenced if not n.isupper() or n in mo_names}

missing = sorted(n for n in referenced if n not in mo_names)
print("FILES_SCANNED:", checked_files)
print("EXTERNAL_NAMES_REFERENCED:", len(referenced))
print("MISSING (referenced but not present on memory_ops):")
for n in missing:
    print("  -", n)
print("DONE")
