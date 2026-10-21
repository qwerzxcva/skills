# -*- coding: utf-8 -*-
"""clean.py — 交付前清理脚本。

上传系统拒绝二进制文件（.pyc/.pdf/.png 等），Skill 包仅支持两级目录结构
（根目录/二级目录/文件，二级目录内不得再有子目录）、解压后总大小 ≤ 3MB。

用法：
  python clean.py --dry-run    # 只列出问题项（推荐先跑）
  python clean.py --full       # 删二进制/__pycache__/.pytest_cache/运行时缓存目录
                               # + 三级及以上嵌套目录兜底删除
  python clean.py --binary     # 只删已知二进制文件

注意：
  - 清理后不要再执行任何 import 项目代码的命令（会重新生成 .pyc）；
    必要验证请加 PYTHONDONTWRITEBYTECODE=1
  - 测试请走 runtests.py（自带 PYTHONDONTWRITEBYTECODE=1）
"""
import argparse
import shutil
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent

# 上传限制：解压后总大小 ≤ 3MB
SIZE_LIMIT = 3 * 1024 * 1024

# 运行时缓存目录（整目录删除，运行时自动重建）
RUNTIME_DIRS = [
    ".cache",
    "data",
]

# 已知二进制扩展名
BINARY_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".docx", ".xlsx",
    ".pptx", ".exe", ".bin", ".onnx", ".pyc", ".pyo", ".pyd", ".7z", ".rar",
}


def _scan_binary() -> list:
    return [f for f in SKILL_DIR.rglob("*")
            if f.is_file() and f.suffix.lower() in BINARY_EXTS]


def _scan_pycache() -> list:
    return [d for d in SKILL_DIR.rglob("__pycache__") if d.is_dir()]


def _scan_pytest_cache() -> list:
    return [d for d in SKILL_DIR.rglob(".pytest_cache") if d.is_dir()]


def _scan_deep_dirs() -> list:
    """三级及以上嵌套目录（相对路径 parts >= 2），上传校验只允许两级结构。

    注意：二级目录（如 stock_researcher/、tests/）内的任何子目录都违规；
    白名单外的新增运行时目录也会被兜底抓到。
    """
    hits = []
    for d in SKILL_DIR.rglob("*"):
        if d.is_dir() and len(d.relative_to(SKILL_DIR).parts) >= 2:
            hits.append(d)
    hits.sort(key=lambda p: len(p.relative_to(SKILL_DIR).parts), reverse=True)
    top, seen = [], []
    for d in hits:
        if not any(d.is_relative_to(s) for s in seen):
            top.append(d)
            seen.append(d)
    return top


def _package_size() -> int:
    return sum(f.stat().st_size for f in SKILL_DIR.rglob("*") if f.is_file())


def dry_run():
    print("== 二进制文件 ==")
    for f in _scan_binary():
        print(f"  {f.relative_to(SKILL_DIR)} ({f.stat().st_size} B)")
    print("== __pycache__ 目录 ==")
    for d in _scan_pycache():
        print(f"  {d.relative_to(SKILL_DIR)}/")
    print("== .pytest_cache 目录 ==")
    for d in _scan_pytest_cache():
        print(f"  {d.relative_to(SKILL_DIR)}/")
    print("== 违规嵌套目录（三级及以上，上传会被拒）==")
    for d in _scan_deep_dirs():
        print(f"  {d.relative_to(SKILL_DIR)}/")
    size = _package_size()
    flag = "⚠️ 超限！" if size > SIZE_LIMIT else "✅"
    print(f"== 包总大小 == {size} 字节 / 限制 {SIZE_LIMIT} {flag}")


def full():
    n = 0
    for f in _scan_binary():
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    for d in _scan_pycache() + _scan_pytest_cache():
        try:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
        except OSError:
            pass
    for rel in RUNTIME_DIRS:
        d = SKILL_DIR / rel
        if d.exists() and d.is_dir():
            try:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
            except OSError:
                pass
    for d in _scan_deep_dirs():
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    print(f"清理完成：{n} 项")
    dry_run()


def binary_only():
    n = 0
    for f in _scan_binary():
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    print(f"删除二进制文件 {n} 个")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="交付前清理（二进制/嵌套目录/体积守门）")
    ap.add_argument("--dry-run", action="store_true", help="只列出不删除")
    ap.add_argument("--full", action="store_true", help="全量清理（推荐）")
    ap.add_argument("--binary", action="store_true", help="只删二进制文件")
    args = ap.parse_args()
    if args.dry_run:
        dry_run()
    elif args.binary:
        binary_only()
    else:
        full()
