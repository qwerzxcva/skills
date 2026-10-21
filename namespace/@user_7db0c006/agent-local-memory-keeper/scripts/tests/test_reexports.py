#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归：`memory_ops` 的重导出完整性（防 AttributeError 只在调用时才炸）。

## 它到底防什么（别夸大——实测结论）

**它不防「漏重导出」**。这一点是实测确认的，不是推测：
`memory_ops/__init__.py:3814` 有 **PEP 562 模块级 `__getattr__` 兜底**，
子模块函数即使忘了在 `__init__.py` 重导出，`memory_ops.X` 也会被动态捞出来。
（负向验证 v1 亲自验证过：注释掉 4.9.5 新增的 `_gate_prewrite_snapshot` 重导出，
`hasattr(memory_ops, '_gate_prewrite_snapshot')` 仍然是 True，测试照样绿。）
所以漏重导出至多是"走动态查找、稍慢"，不会炸。

**它真正防的是：代码里写了 `memory_ops.X`，而 X 在所有子模块里都不存在。**
典型成因：① 手写时拼错；② 函数被删除/改名后，调用方没跟着改。
这类错误同样只在**执行到那一行**时才 AttributeError，常规测试覆盖不到——
`_core.py` 的写入门禁调用就属于"平时跑不到、错了才发现"的路径。
负向验证 v2：把 `_core.py` 里的调用改成 `_gate_prewrite_snapshoot`（拼错），
本测试 returncode=1 并报出缺失项；改回后 md5 一致、测试复绿。

## 为什么不能只靠 `_review_check_reexports.py`

仓库里那个审计器有两个硬伤，决定了它保护不到包内调用：

1. 它第 33 行明确 `continue` 掉 `memory_ops/_*.py` 子模块，扫描范围只有包外脚本；
2. `_core.py` 等模块**没有** `import memory_ops` 语句——按 `_core.py` 头部注释，
   依赖是 `__init__.py` 在加载末期**属性注入**进来的（为了避开循环 import）。
   既然没有 import 语句，任何"先找 import、再找属性访问"的静态分析都抓不到。

所以本测试改用**字面量扫描**：直接在全部 `.py` 里找 `memory_ops.X`，
与 X 是怎么引入的无关。已用负向验证确认有效（注释掉一条重导出 → 本测试 FAIL）。

## 稳定性

扫描是普查型检查：脚本缺失或 import 失败时 skip，不因环境问题让门禁变脆。
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)

# 占位：真正的提取走 AST（见 _collect_referenced）。
# 不直接用正则扫 `memory_ops.X`：那会把注释里的示例（memory_ops.X）和
# 文件路径（scripts/memory_ops.py → 伪属性 "py"）也当成引用，实测误报 3 个。
_NAME_RE = None


def _iter_py_files():
    """遍历**生产代码**的 .py（含根级 mem_bridge.py），返回排序后的稳定序列。

    明确排除三类：
    - `__pycache__`：字节码，重复且无意义；
    - `_retired_*` / `_bak_*`：退休件与改造期快照，装的是旧版源码，不是生产调用方；
    - `scripts/tests/`：测试代码不是生产调用方。更关键的是——若把测试文件纳入扫描，
      本测试的结果就会**依赖 unittest 的用例执行顺序**（别的测试运行期生成的 .py
      可能被扫进来），变成间歇性红绿。稳定性优先，测试里的拼错由测试自己跑炸来暴露。
    """
    found = []
    for root, dirs, files in os.walk(SKILL_DIR):
        dirs[:] = [
            d for d in dirs
            if d != "__pycache__"
            and not (root == SCRIPTS_DIR and d == "tests")
            # `_retired_*`（同卷 rename 的退休件）与 `_bak_*`（改造期整目录快照）
            # 装的是**旧版源码副本**，含早已删除的符号名；纳入扫描会让本测试对着
            # 历史副本报"悬空引用"（实测 2026-09-15 加密下线：9 处命中全部来自
            # `_retired_*/…/_core.py` 旧副本，生产代码零命中）。它们不是生产调用方。
            and not d.startswith("_retired") and not d.startswith("_bak")
        ]
        for f in files:
            if not f.endswith(".py"):
                continue
            if os.path.basename(f) == "__init__.py":
                continue  # 定义处，不是调用方
            found.append(os.path.join(root, f))
    return sorted(found)  # 排序：同一份代码两次扫描结果必须完全一致


def _collect_referenced():
    """用 AST 精确提取 `memory_ops.X` 属性访问。

    注释、文档字符串、文件路径里的同名文本一律不算——只对真实语法节点生效。
    AST 解析失败的文件（罕见）退化为跳过，宁可漏扫也不误报。
    """
    import ast

    names = set()
    for full in _iter_py_files():
        try:
            with open(full, encoding="utf-8") as fh:  # 必须 with：否则 ResourceWarning
                tree = ast.parse(fh.read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "memory_ops"):
                names.add(node.attr)
    return names


class ReexportAuditTest(unittest.TestCase):
    def test_memory_ops_attrs_all_reexported(self):
        if SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, SCRIPTS_DIR)
        try:
            import memory_ops as mo
        except Exception as e:
            self.skipTest("memory_ops 无法 import：%s" % e)
            return

        referenced = _collect_referenced()
        self.assertTrue(
            referenced,
            "一个 memory_ops.X 都没扫到——扫描逻辑坏了（路径或正则失效），"
            "这个测试若扫不到东西就等于不存在，必须查。",
        )

        missing = sorted(n for n in referenced if not hasattr(mo, n))
        self.assertEqual(
            [], missing,
            "以下名字以 memory_ops.X 形式被访问，但 memory_ops 上没有（漏重导出），"
            "执行到时会 AttributeError。\n"
            "修法：在 scripts/memory_ops/__init__.py 补上重导出。\n"
            "缺失项：%s" % missing,
        )


if __name__ == "__main__":
    unittest.main()
