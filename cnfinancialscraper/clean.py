# -*- coding: utf-8 -*-
"""
clean.py — 交付前清理脚本（v7.0.0 补齐）

上传系统拒绝二进制文件（.pyc/.pdf/.png 等），且 Skill 包仅支持两级目录结构
（根目录/二级目录/文件）、解压后总大小 ≤ 3MB（3145728 字节），交付前必须清干净。

用法：
  python clean.py --dry-run    # 只列出将删除的内容（推荐先跑）
  python clean.py --full       # 删除 __pycache__/pytest_cache + 运行时产物目录/文件
                               # + 违规嵌套目录 + 紧凑化 data/*.json，保证两级结构与 3MB 限制
  python clean.py --binary     # 只删已知二进制文件（pdf/png/jpg/zip/docx 等）

注意：
  - 清理之后不要再执行任何 import 项目代码的命令（会重新生成 .pyc）；
    必要验证请加 PYTHONDONTWRITEBYTECODE=1
  - 测试请走 runtests.py（自带前后清理），不要直跑 python -m pytest
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent

# 上传限制：解压后总大小 ≤ 3MB
SIZE_LIMIT = 3 * 1024 * 1024

# 运行时产物目录（整目录删除；macros/ 是用户宏资产，不删）
RUNTIME_DIRS = [
    "data/exports", "data/reports", "data/generated_reports", "data/charts",
    "data/packages", "data/archives", "data/scheduler_logs",
    "data/sentiment_exports", "data/sentiment_snapshots",
    "data/backtest_conflicts", "data/overseas_cache", "data/scrape_cache",
    "data/browser_cache", "data/browser_state", "data/screenshots",
    "data/downloads", "data/selector_cache", "data/temp_packages",
    "tests/_test_data",
]

# 运行时大文件（体积超限主因；update_stock_list 工具可随时重新生成，
# 包内无任何读取方——测试 test_v700_enhancements 缺文件会自动 skip）
RUNTIME_FILES = [
    "data/listed_companies.json",
]

# 已知二进制扩展名
BINARY_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".docx", ".xlsx",
    ".pptx", ".exe", ".bin", ".onnx", ".pyc", ".pyo", ".pyd", ".7z", ".rar",
}


def _scan_binary() -> list:
    hits = []
    for f in SKILL_DIR.rglob("*"):
        if f.is_file() and f.suffix.lower() in BINARY_EXTS:
            hits.append(f)
    return hits


def _scan_pycache() -> list:
    return [d for d in SKILL_DIR.rglob("__pycache__") if d.is_dir()]


def _scan_pytest_cache() -> list:
    return [d for d in SKILL_DIR.rglob(".pytest_cache") if d.is_dir()]


def _scan_deep_dirs() -> list:
    """三级及以上嵌套目录（相对路径 parts >= 2），上传校验只允许两级结构。

    白名单 RUNTIME_DIRS 之外的运行时目录（如新增脚本的缓存目录）也会被兜底抓到。
    """
    hits = []
    for d in SKILL_DIR.rglob("*"):
        if d.is_dir() and len(d.relative_to(SKILL_DIR).parts) >= 2:
            hits.append(d)
    # 先删最深的，避免输出里出现"已随父目录删除"的重复项
    hits.sort(key=lambda p: len(p.relative_to(SKILL_DIR).parts), reverse=True)
    top = []
    seen = []
    for d in hits:
        if not any(d.is_relative_to(s) for s in seen):
            top.append(d)
            seen.append(d)
    return top


def _package_size() -> int:
    return sum(f.stat().st_size for f in SKILL_DIR.rglob("*") if f.is_file())


def _compact_data_json() -> int:
    """紧凑化 data/*.json（去掉缩进空格），语义不变，仅省交付体积。

    返回节省的字节数；解析失败的文件原样保留（宁大勿坏）。
    """
    saved = 0
    for p in sorted((SKILL_DIR / "data").glob("*.json")):
        try:
            raw = p.read_bytes()
            obj = json.loads(raw)
            compact = json.dumps(obj, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
        except (OSError, ValueError):
            continue
        if len(compact) < len(raw):
            p.write_bytes(compact)
            saved += len(raw) - len(compact)
    return saved


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
    for rel in RUNTIME_FILES:
        f = SKILL_DIR / rel
        if f.exists() and f.is_file():
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    for d in _scan_deep_dirs():
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    saved = _compact_data_json()
    print(f"清理完成：{n} 项；data/*.json 紧凑化节省 {saved} 字节")
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
    ap = argparse.ArgumentParser(description="交付前二进制清理")
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
