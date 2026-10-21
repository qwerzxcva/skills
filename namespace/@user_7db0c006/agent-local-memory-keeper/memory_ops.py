# -*- coding: utf-8 -*-
"""转发垫片：CLI 入口。

真实逻辑在 `scripts/memory_ops/__init__.py`（含 `main()` 与 `__main__` 引导）。
本文件只做一件事：以 `__main__` 身份运行那个模块，等价于
`python scripts/memory_ops/__init__.py <op>`，让文档里所有
`python memory_ops.py <op>` 写法都成立。
"""
import os
import runpy

_TARGET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scripts", "memory_ops", "__init__.py",
)

if __name__ == "__main__":
    runpy.run_path(_TARGET, run_name="__main__")
