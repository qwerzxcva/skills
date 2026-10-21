#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票介绍所 / The Stock Matchmaker — 技能包引用与合规校验脚本

用途：
  扫描本 skill 包中的 markdown 文件，校验：
  1. 关键文件是否缺失
  2. 跨文件引用是否指向真实存在的文件
  3. 引用的章节锚点是否真实存在
  4. SKILL.md 版本号是否有效
  5. 固定模板的关键锚点句是否仍然存在（防误删改导致回读保真漂移）
  6. 文件编码与平台兼容性：包内文本文件是否残留 UTF-8 BOM；SKILL.md 的
     frontmatter 能否被平台扫描器正常切分并解析出 name（残留 BOM 会导致
     frontmatter 整体读不到，技能名回落为安装目录名）

运行环境：Python 3.8+（无 Python 环境不影响技能包正常使用）。

完整的版权与许可声明见本文件尾部的「版权与许可声明」区块。
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# 关键文件（相对于 skill 根目录）
REQUIRED_FILES = [
    "SKILL.md",
    "LICENSE",
    "README.md",
    "scripts/license_guard.py",
]

# 必须存在的参考文件
REQUIRED_REFERENCES = [
    "references/data-sources.md",
    "references/risk-checklist.md",
    "references/analysis-framework.md",
    "references/methodology.md",
    "references/financial-indicators.md",
    "references/industry-specific-guides.md",
    "references/output-templates.md",
]

# 必须保留的版权与许可声明标记
REQUIRED_MARKERS = [
    "金曙（所长）",
    "股票介绍所",
    "The Stock Matchmaker",
    "CC BY-NC-SA 4.0",
]

# 固定模板必存锚点句（回读保真回归检查：
# “逐字照抄”类模板被误删改时由此报警；每个标记取自对应模板的特征句）
REQUIRED_TEMPLATE_MARKERS = {
    "references/output-templates.md": [
        "数据搜集与分析完成：",            # Phase 5 前置反馈块
        "基本面快速摘要",                  # Phase 5 摘要模板标题
        "快速摘要已输出",                  # Phase 5 确认门首句
        "初次印象分",                      # Phase 5 评分表
        "当前位置的胜率与赔率",            # Phase 5 参考意见内的拐点/胜率/赔率三栏标题
        "第二层次思维：与市场共识的差异",    # Phase 5 参考意见内的简版三栏标题
        "基本面完整分析报告",              # Phase 6 报告模板标题
        "完整报告已输出。查理·芒格常说",    # Phase 6 报告模板末尾收束句（芒格引言，仅首次输出完整报告时出现）
        "综合摸底分",                      # Phase 6 评分表
        "从角色列表中选择挑战角色发起挑战",  # Phase 6/7 确认门角色选择提示
        "逆向思维挑战：",                  # Phase 7 挑战报告模板标题
        "纠判结论依据",                    # 逐章质询表规则行
        "逆向思维挑战已完成。请选择下一步", # Phase 7 确认门首句
        "综合考察分",                      # Phase 7 评分表
        "降龙十八掌第 X 掌",               # 出口模块小贴士
        "仅供参考，投资判断由用户自行决定",  # 免责声明（Phase 5/6/7/出口模块共用表述）
    ],
}


# ---- 编码与平台兼容性检查常量 ----

# 与 WorkBuddy 平台扫描器同款的 frontmatter 切分正则
# （对应客户端实现 FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---/：
#  ^ 锚定字符串首、不做 BOM 容错。文件一旦以 BOM 开头，整段 frontmatter 失配，
#  技能名与描述会双双回落为安装目录名，例如 workbuddy-skill-1790038569454）
PLATFORM_FRONTMATTER_RE = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---")

# UTF-8 BOM 的三个字节
UTF8_BOM = b"\xef\xbb\xbf"

# 参与 BOM 检查的文本类扩展名（无扩展名的文件如 LICENSE 同样纳入）
TEXT_EXTENSIONS = {".md", ".py", ".txt", ".json", ".yml", ".yaml", ".svg", ".css", ".js"}


def get_skill_root() -> Path:
    """返回 skill 根目录。本脚本位于 scripts/ 下，因此向上两级即为根目录。"""
    return Path(__file__).resolve().parent.parent


def collect_markdown_files(root: Path) -> List[Path]:
    """收集 skill 包内所有 markdown 文件（不含 LICENSE，它通常是纯文本）。"""
    md_files = []
    for ext in ("*.md", "**/*.md"):
        md_files.extend(root.glob(ext))
    return sorted(md_files)


def extract_links(content: str) -> Set[Tuple[str, str]]:
    """
    从 markdown 文本中提取两类引用：
    1. `references/xxx.md` 或 `references/xxx.md#锚点`
    2. `references/xxx.md`「章节标题」
    返回 (target_file, anchor_or_section) 集合。
    """
    links: Set[Tuple[str, str]] = set()

    # 1. 标准 markdown 链接或裸引用：references/xxx.md[#[锚点]]
    pattern1 = re.compile(r"references/([a-zA-Z0-9_\-]+\.md)(?:#([^\s\)\]\"]+))?")
    for match in pattern1.finditer(content):
        file_name = match.group(1)
        anchor = match.group(2) or ""
        links.add((file_name, anchor))

    # 2. 中文引用：references/xxx.md「章节标题」
    pattern2 = re.compile(r'references/([a-zA-Z0-9_\-]+\.md)「([^"」]+)」')
    for match in pattern2.finditer(content):
        file_name = match.group(1)
        section = match.group(2)
        links.add((file_name, section))

    return links


def extract_headings(content: str) -> Set[str]:
    """提取 markdown 文件中的所有标题（# / ## / ### 后的文本）。"""
    headings: Set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # 去除前导 # 和空格
            heading = stripped.lstrip("#").strip()
            headings.add(heading)
    return headings


def check_required_files(root: Path) -> List[str]:
    """检查关键文件是否缺失。"""
    failures = []
    for rel_path in REQUIRED_FILES + REQUIRED_REFERENCES:
        full_path = root / rel_path
        if not full_path.exists():
            failures.append(f"❌ 关键文件缺失：{rel_path}")
    return failures


def check_copyright_markers(root: Path, md_files: List[Path]) -> List[str]:
    """检查所有 markdown 文件是否包含必要的版权标记。"""
    failures = []
    for md_file in md_files:
        # 跳过 README.md / LICENSE，它们由 license_guard.py 负责
        if md_file.name == "README.md":
            continue
        content = md_file.read_text(encoding="utf-8", errors="replace")
        for marker in REQUIRED_MARKERS:
            if marker not in content:
                rel = md_file.relative_to(root)
                failures.append(f"❌ 文件 {rel} 缺少版权标记：「{marker}」")
    return failures


def check_cross_references(root: Path, md_files: List[Path]) -> List[str]:
    """检查跨文件引用是否有效。"""
    failures = []
    references_dir = root / "references"

    # 缓存每个参考文件的标题
    headings_cache: Dict[str, Set[str]] = {}
    for ref_file in references_dir.glob("*.md"):
        content = ref_file.read_text(encoding="utf-8", errors="replace")
        headings_cache[ref_file.name] = extract_headings(content)

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8", errors="replace")
        links = extract_links(content)
        rel = md_file.relative_to(root)

        for file_name, anchor in links:
            target = references_dir / file_name
            if not target.exists():
                failures.append(f"❌ 死链：{rel} 引用 {file_name}，但该文件不存在")
                continue

            # 如果存在章节/锚点引用，校验标题是否存在
            if anchor:
                # 将 anchor 中的 - 替换为空格后再比较，同时支持原始标题
                normalized_anchor = anchor.replace("-", " ").strip()
                headings = headings_cache.get(file_name, set())
                if normalized_anchor not in headings:
                    # 也尝试完全匹配原始 anchor（有些标题本身带 -）
                    if anchor not in headings:
                        failures.append(
                            f"❌ 锚点缺失：{rel} 引用 {file_name}「{anchor}」，该标题不存在"
                        )

    return failures


def check_template_markers(root: Path) -> List[str]:
    """检查固定模板的关键锚点句是否仍然存在（防误删改）。"""
    failures = []
    for rel_path, markers in REQUIRED_TEMPLATE_MARKERS.items():
        full_path = root / rel_path
        if not full_path.exists():
            # 文件缺失已由 check_required_files 报告，此处不重复报
            continue
        content = full_path.read_text(encoding="utf-8", errors="replace")
        for marker in markers:
            if marker not in content:
                failures.append(
                    f"❌ 模板标记缺失：{rel_path} 应包含「{marker}」——固定模板可能被误删改"
                )
    return failures


def check_version(root: Path) -> List[str]:
    """检查 SKILL.md frontmatter 中版本号是否有效。"""
    failures = []
    skill_md = root / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8", errors="replace")

    if not content.startswith("---"):
        failures.append("❌ SKILL.md 未以 YAML frontmatter 开头")
        return failures

    end = content.find("\n---", 3)
    if end == -1:
        failures.append("❌ SKILL.md frontmatter 未正确结束")
        return failures

    frontmatter = content[:end]
    version_match = re.search(r"^version:\s*(\S+)", frontmatter, re.MULTILINE)
    if not version_match:
        failures.append("❌ SKILL.md frontmatter 缺少 version 字段")
    else:
        version = version_match.group(1)
        # 简单校验：主版本.次版本.修订号
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            failures.append(f"⚠️ SKILL.md version 格式异常：{version}")

    return failures


def collect_text_files(root: Path) -> List[Path]:
    """收集包内文本类文件（BOM 检查范围），跳过隐藏目录与脚本缓存。"""
    files: List[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if path.suffix.lower() in TEXT_EXTENSIONS or not path.suffix:
            files.append(path)
    return sorted(files)


def check_utf8_bom(root: Path) -> List[str]:
    """
    检查包内文本文件是否残留 UTF-8 BOM。

    这是发布前的必查项：SKILL.md 一旦带 BOM，平台的 frontmatter 正则
    （^ 锚定字符串首）即失配，技能名与描述会双双回落为安装目录名，
    用户看到的技能名就不再是 the-stock-matchmaker。
    """
    failures = []
    for path in collect_text_files(root):
        try:
            head = path.read_bytes()[:3]
        except OSError as exc:
            failures.append(f"❌ 无法读取文件：{path.relative_to(root)}（{exc}）")
            continue
        if head == UTF8_BOM:
            rel = path.relative_to(root)
            note = "——预览发布后会显示为安装目录名的风险，务必清除" if path.name == "SKILL.md" else ""
            failures.append(f"❌ UTF-8 BOM 残留：{rel} 以 EF BB BF 开头{note}")
    return failures


def check_platform_frontmatter(root: Path) -> Tuple[List[str], str]:
    """
    按平台扫描器的切分规则校验 SKILL.md：
    1. frontmatter 能否被 PLATFORM_FRONTMATTER_RE 命中
    2. 能否解析出非空的 name 字段（技能名的唯一来源）

    返回 (failures, 解析出的技能名)。
    """
    failures: List[str] = []
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        # 文件缺失已由 check_required_files 报告，此处不重复
        return failures, ""

    try:
        content = skill_md.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        failures.append(f"❌ SKILL.md 不是合法 UTF-8 编码：{exc}")
        return failures, ""

    match = PLATFORM_FRONTMATTER_RE.match(content)
    if not match:
        failures.append(
            "❌ SKILL.md frontmatter 无法被平台正则命中（^---\\r?\\n...\\r?\\n---）"
            "：常见原因是文件残留 BOM、开头有空行或首个 --- 前有不可见字符"
        )
        return failures, ""

    name_match = re.search(r"^name:\s*(.+?)\s*$", match.group(1), re.MULTILINE)
    if not name_match:
        failures.append("❌ SKILL.md frontmatter 缺少 name 字段（技能名将回落为安装目录名）")
        return failures, ""

    name = name_match.group(1).strip().strip("\"'")
    if not name:
        failures.append("❌ SKILL.md frontmatter 的 name 为空（技能名将回落为安装目录名）")
        return failures, ""

    if re.match(r"^workbuddy-skill-\d+$", name):
        failures.append(f"⚠️ SKILL.md 的 name 疑似安装目录名：{name}，请改为技能正式名称")

    return failures, name


def main() -> int:
    # 保护非 UTF-8 控制台（如 Windows GBK）下的中文输出
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = get_skill_root()
    print(f"🔍 正在校验 skill 目录：{root}")
    print("-" * 60)

    md_files = collect_markdown_files(root)
    failures: List[str] = []

    failures.extend(check_required_files(root))
    failures.extend(check_utf8_bom(root))
    frontmatter_failures, skill_name = check_platform_frontmatter(root)
    failures.extend(frontmatter_failures)
    failures.extend(check_copyright_markers(root, md_files))
    failures.extend(check_cross_references(root, md_files))
    failures.extend(check_template_markers(root))
    failures.extend(check_version(root))

    if failures:
        print(f"❌ 发现 {len(failures)} 处异常：\n")
        for failure in failures:
            print(failure)
        return 1

    print("✅ 所有引用与合规校验通过。")
    if skill_name:
        print(f"🔎 平台 frontmatter 校验通过，技能名 name = {skill_name}")
    print("\n📜 本技能采用 CC BY-NC-SA 4.0 协议授权。")
    print("© 2026 金曙（所长）。保留所有权利。")
    print("品牌保留：「股票介绍所 / The Stock Matchmaker」品牌 IP 归金曙（所长）所有，未经授权不得占用、混淆或注册。")
    return 0


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
