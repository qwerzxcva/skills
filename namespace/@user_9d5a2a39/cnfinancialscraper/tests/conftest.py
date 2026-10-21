# -*- coding: utf-8 -*-
"""cn-financial-scraper 测试根 conftest.

设计要点：
  1. 第一时间禁用 Python 字节码生成（设置 sys.dont_write_bytecode = True），
     同时通过环境变量 PYTHONDONTWRITEBYTECODE=1 让子进程继承。
     注意：conftest.py 自身的 pyc 在 pytest import 它时已先于本文件执行而写入，
     无法阻止，因此启动时主动清理历史残留（兼兜底 `py -m pytest` 直跑场景）。
  2. 把 scripts/ 加入 sys.path，方便 `import sentiment_crawler` 等绝对导入。
"""
import os
import sys
import shutil
from pathlib import Path

# ---- 1) 阻止字节码生成 ----
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

# ---- 1.5) 启动即清理历史 __pycache__/.pyc 残留 ----
# 直跑 `py -m pytest`（未设环境变量）时本次仍会生成 conftest 自身 pyc，
# 但历史残留在此被清除；本次新生成的由 pytest_sessionfinish 收尾清理。
_project_root = Path(__file__).resolve().parent.parent
for _cache_dir in _project_root.rglob("__pycache__"):
    try:
        shutil.rmtree(_cache_dir)
    except OSError:
        pass
for _pyc in _project_root.rglob("*.pyc"):
    try:
        _pyc.unlink()
    except OSError:
        pass

# ---- 2) 确保 scripts/ 可导入 ----
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))


def pytest_configure(config):
    """pytest 启动时再次确认字节码关闭。"""
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def pytest_load_initial_conftests(early_config, parser, args):
    """在加载其他 conftest 之前强制设置（无需 pytest hook 装饰器）。"""
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束后清理本次运行生成的字节码残留（含 conftest 自身 pyc）。

    兜底直跑 `py -m pytest`（未走 runtests.py 包装、无环境变量）的场景，
    保证无论哪种方式跑完测试，交付目录都不残留 __pycache__/.pyc。"""
    for cache_dir in _project_root.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
        except OSError:
            pass
    for pyc in _project_root.rglob("*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass