#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票介绍所 / The Stock Matchmaker — 版权与许可声明自检脚本

用途：
  扫描本 skill 包中的关键文件，验证版权、作者、许可协议和品牌保留声明
  是否被删除或篡改。本脚本随 skill 分发，可被用户删除；删除后仅失去
  自检能力，不影响 LICENSE 与 SKILL.md 中的法律约束。

运行环境：Python 3.8+（无 Python 环境不影响技能包正常使用）。

完整的版权与许可声明见本文件尾部的「版权与许可声明」区块。
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


# 关键声明片段（用于内容匹配）
REQUIRED_MARKERS = [
    "金曙（所长）",
    "股票介绍所",
    "The Stock Matchmaker",
    "CC BY-NC-SA 4.0",
    "保留所有权利",
    "品牌保留",
    "商用授权",
    "alakin@qq.com",
]

# 品牌保留相关关键词
BRAND_RESERVED_MARKERS = [
    "不得占用",
    "不得混淆",
    "不得注册",
    "品牌 IP",
    "授权自动终止",
]

# 必须存在的文件（相对于 skill 根目录）
REQUIRED_FILES = [
    "SKILL.md",
    "LICENSE",
    "README.md",
]


def get_skill_root() -> Path:
    """
    返回 skill 根目录。
    本脚本位于 scripts/ 下，因此向上两级即为根目录。
    """
    return Path(__file__).resolve().parent.parent


def check_required_files(root: Path) -> List[str]:
    """检查关键文件是否缺失。"""
    failures = []
    for rel_path in REQUIRED_FILES:
        full_path = root / rel_path
        if not full_path.exists():
            failures.append(f"❌ 关键文件缺失：{rel_path}")
    return failures


def check_markers_in_file(file_path: Path, markers: List[str]) -> Tuple[List[str], List[str]]:
    """
    检查单个文件中是否包含所有指定标记。
    返回 (missing_markers, all_failures)。
    """
    missing = []
    failures = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        failures.append(f"❌ 无法读取文件：{file_path}，错误：{e}")
        return missing, failures

    for marker in markers:
        if marker not in content:
            missing.append(marker)
            failures.append(f"❌ 文件 {file_path} 缺少声明：「{marker}」")
    return missing, failures


def check_frontmatter(skill_md_path: Path) -> List[str]:
    """检查 SKILL.md 的 YAML frontmatter 中是否包含关键元数据（正则容忍引号/空格变体）。"""
    failures = []
    # (人类可读标签, 匹配正则)
    required_entries = [
        ("name: the-stock-matchmaker", r"name:\s*['\"]?the-stock-matchmaker['\"]?"),
        ("author: 金曙（所长）", r"author:\s*['\"]?金曙（所长）['\"]?"),
        ("copyright:", r"copyright:\s*\S"),
        ("license: CC BY-NC-SA 4.0", r"license:\s*['\"]?CC BY-NC-SA 4\.0['\"]?"),
        ("brand:", r"brand:\s*\S"),
        ("brand_reserved: true", r"brand_reserved:\s*['\"]?(true|True)['\"]?"),
        ("commercial_contact: alakin@qq.com", r"commercial_contact:\s*['\"]?alakin@qq\.com['\"]?"),
    ]

    try:
        content = skill_md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [f"❌ 无法读取 SKILL.md：{e}"]

    # 简单提取 frontmatter 区域
    if not content.startswith("---"):
        failures.append("❌ SKILL.md 未以 YAML frontmatter 开头")
        return failures

    end = content.find("\n---", 3)
    if end == -1:
        failures.append("❌ SKILL.md frontmatter 未正确结束")
        return failures

    frontmatter = content[:end]

    for label, pattern in required_entries:
        if not re.search(pattern, frontmatter):
            failures.append(f"❌ SKILL.md frontmatter 缺少或异常：{label}")

    return failures


def scan_files(root: Path) -> List[str]:
    """扫描所有需要检查的文件并汇总问题。"""
    all_failures = []

    # 1. 检查关键文件存在性
    all_failures.extend(check_required_files(root))

    # 2. 检查 SKILL.md frontmatter
    skill_md = root / "SKILL.md"
    if skill_md.exists():
        all_failures.extend(check_frontmatter(skill_md))
        _, fails = check_markers_in_file(skill_md, REQUIRED_MARKERS)
        all_failures.extend(fails)

    # 3. 检查 LICENSE 中的品牌保留
    license_file = root / "LICENSE"
    if license_file.exists():
        _, fails = check_markers_in_file(license_file, REQUIRED_MARKERS[:4])
        all_failures.extend(fails)
        _, brand_fails = check_markers_in_file(license_file, BRAND_RESERVED_MARKERS)
        all_failures.extend(brand_fails)

    # 4. 检查 README.md
    readme_file = root / "README.md"
    if readme_file.exists():
        _, fails = check_markers_in_file(readme_file, REQUIRED_MARKERS)
        all_failures.extend(fails)

    # 5. 检查 references 下的所有 .md 文件
    references_dir = root / "references"
    if references_dir.exists() and references_dir.is_dir():
        md_files = sorted(references_dir.glob("*.md"))
        if not md_files:
            all_failures.append("⚠️ references/ 目录下未找到 .md 文件")
        for md_file in md_files:
            _, fails = check_markers_in_file(md_file, REQUIRED_MARKERS[:4])
            all_failures.extend(fails)
    else:
        all_failures.append("❌ references/ 目录不存在")

    # 6. 检查 scripts 下的所有 .py 文件（含本脚本自身）
    scripts_dir = root / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        for py_file in sorted(scripts_dir.glob("*.py")):
            _, fails = check_markers_in_file(py_file, REQUIRED_MARKERS[:4])
            all_failures.extend(fails)

    return all_failures


def main() -> int:
    # 保护非 UTF-8 控制台（如 Windows GBK）下的中文输出
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = get_skill_root()
    print(f"🔍 正在检查 skill 目录：{root}")
    print("-" * 60)

    failures = scan_files(root)

    if not failures:
        print("✅ 所有版权与许可声明检查通过。")
        print("\n📜 本技能采用 CC BY-NC-SA 4.0 协议授权。")
        print("© 2026 金曙（所长）。保留所有权利。")
        print("品牌保留：「股票介绍所 / The Stock Matchmaker」品牌 IP 归金曙（所长）所有，未经授权不得占用、混淆或注册。")
        return 0

    print(f"❌ 发现 {len(failures)} 处异常：\n")
    for failure in failures:
        print(failure)

    print("\n⚠️ 提示：删除或篡改版权、许可、品牌保留声明，将违反 CC BY-NC-SA 4.0 授权条件。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

# 📜 版权与许可声明 / Copyright & License Notice
# 本文件是「股票介绍所 / The Stock Matchmaker」技能包的一部分。
# 
# 作者：金曙（所长）
# 版权所有 © 2026 金曙（所长）。保留所有权利。
# 许可协议：CC BY-NC-SA 4.0
# 品牌保留：「股票介绍所 / The Stock Matchmaker」品牌 IP 归金曙（所长）所有，任何衍生作品不得占用、混淆或注册该品牌。
# 商用授权：如需商业用途，请联系 alakin@qq.com 获得单独授权。
# 完整协议：https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh
# 修改要求：你可以自由修改本文件，但修改后的衍生作品必须采用相同的 CC BY-NC-SA 4.0 协议，并完整保留上述署名与品牌保留条款。
# 
# ⚠️ 删除、篡改或移除上述版权与许可声明，将构成对本作品授权条件的违反，授权自动终止。
