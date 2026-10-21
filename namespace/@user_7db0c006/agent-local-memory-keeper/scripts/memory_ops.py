#!/usr/bin/env python3
# 兼容垫片：agent-local-memory-keeper 已将 memory_ops 重构为 packages/memory_ops/ 包，
# 但外部（含每周自动化）仍硬编码 `python scripts/memory_ops.py <op>`。
# 这里用 runpy 以 __main__ 形态执行包内的 __init__.py，
# 其行为与原扁平 memory_ops.py 时代完全一致（__init__.py 会自将 scripts/ 加入 sys.path）。
import os
import runpy

_THIS = os.path.dirname(os.path.abspath(__file__))
_PKG_INIT = os.path.join(_THIS, "memory_ops", "__init__.py")

if __name__ == "__main__":
    runpy.run_path(_PKG_INIT, run_name="__main__")
