# -*- coding: utf-8 -*-
"""文档自检：SKILL.md 中被引用的章节标题必须真实存在。

锁定本次体检发现的断链根因：
- `references/QA.md` 指向 `SKILL.md「反模式清单」` 与 `SKILL.md「高级功能：何时调用」` 两节，
但这两节曾被删/改名、指针没回扫，导致"反模式没集中汇总""高级功能限制藏得深"两个真实问题。

本测试自动扫描 skill 根目录 + references/ 下所有 .md，提取「对 SKILL.md「章节名」」式引用，
断言被引用的「章节名」在 SKILL.md 的标题中确实存在（子串匹配，容忍 emoji/修饰符）。
新增/改名/删除 SKILL.md 章节后忘了回扫引用 -> 本测试 FAIL，作为发版门禁拦截。
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SKILL_ROOT = os.path.dirname(HERE)                                  # skill 根

# 装饰性前缀字符（emoji / 特殊符号），归一化标题时去除，便于子串匹配
_DECOR = "📌🕒⚡🎬🚀🩺💡🔑⚠️✅❌🔴🌐🔌→★•·•"

# 有意的非标题概念引用（不是 SKILL.md 章节，但文档用「」指向某个概念/子节）。
# 这些不应被视为"断链"：它们描述的是 SKILL.md 正文里的概念（如「A · 数据类红线」加粗子节、
# TUTORIAL 指向的「深读版」），而非可删除/重命名的顶层章节。
# 匹配使用归一化形式（已去除 🔴🌐🔌📌 等前缀 emoji），与 _norm_header 对齐。
# 若未来真的把某个概念升级为独立章节，请从这里移除。
# 注意：5.1.0 重构后，「会话钩子」→「钩子模式」、「3 项需手动开启」→「2 项需手动开」、
# 「模型能力灵活组合」「版本怎么选」等旧概念已被删除——不得再写进 allowlist 掩盖断链。
_ALLOWLIST = {
    "数据类红线",
    "质量类红线",
    "深读版",
}

# 引用捕获：`` `SKILL.md`「章节名」 `` 或 `SKILL.md`「章节名」。
# SKILL.md 后允许介于其间的「短修饰」——可选的 §N 编号（§4.3 / §六）、方位词（的/顶部/文末/开头/末尾/里/内/中）。
# 这样能抓到 ``SKILL.md §4.3「X」``、``SKILL.md 顶部「X」`` 这类带编号/带方位词的引用，
# 避免重构删掉 §N 章节后，残留的 §N 指针漏网（正是 5.1.0 重构时 LIMITS/COOKBOOK/ENABLEMENT/EVOLUTION/QA 断链漏抓的根因）。
# 仍排除"SKILL.md 标注的「…」"这类相隔较远、实为文档自身措辞的误匹配（「标注的」不在短修饰白名单内）。
_REF_MID = r"(?:(?:§\d+(?:\.\d+)*|的|顶部|文末|开头|末尾|里|内|中)\s*)?"
_REF_RE = re.compile(
    r"(?:`SKILL\.md`|SKILL\.md)\s*" + _REF_MID + r"「([^」]{1,50})」|"
    r"(?:`SKILL\.md`|SKILL\.md)\s*" + _REF_MID + r"《([^》]{1,50})》",
    re.IGNORECASE,
)


def _norm_header(text):
    """去掉 #、空白、装饰性 emoji，返回用于子串匹配的归一化标题。"""
    t = text.strip().lstrip("#").strip()
    # 去除开头连续装饰字符
    while t and t[0] in _DECOR:
        t = t[1:].strip()
    return t


def _collect_skill_headers():
    path = os.path.join(SKILL_ROOT, "SKILL.md")
    headers = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^#{1,6}\s+(.*)$", line)
            if m:
                headers.append(_norm_header(m.group(1)))
    return headers


def _find_referenced_sections():
    """返回 [(来源文件相对路径, 行号, 被引章节名)]。

    仅扫描 SKILL.md 本身 + QUICKSTART.md（根目录用户向文档）+ references/ 下的参考文档
    （这些是应当维护 SKILL.md 章节指针的文档）。刻意排除根目录的 CHANGELOG.md / 复审报告等
    版本历史/过程文件，它们里的「X」是自身历史措辞，不是指向 SKILL.md 章节的指针，会制造误报。
    """
    refs = []
    targets = [os.path.join(SKILL_ROOT, "SKILL.md")]
    # 根目录用户向文档：QUICKSTART.md（不含 CHANGELOG.md / AUDIT 报告等过程文件）
    _quick = os.path.join(SKILL_ROOT, "QUICKSTART.md")
    if os.path.exists(_quick):
        targets.append(_quick)
    ref_dir = os.path.join(SKILL_ROOT, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            if fn.endswith(".md"):
                targets.append(os.path.join(ref_dir, fn))
    for fp in targets:
        if not os.path.exists(fp):
            continue
        rel = os.path.relpath(fp, SKILL_ROOT)
        with open(fp, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if "SKILL.md" not in line:
                    continue
                for m in _REF_RE.finditer(line):
                    name = m.group(1) or m.group(2)
                    if name:
                        refs.append((rel, i, name.strip()))
    return refs


class DocSectionRefsTest(unittest.TestCase):
    def test_all_skill_md_section_refs_exist(self):
        headers = _collect_skill_headers()
        self.assertTrue(headers, "SKILL.md 未解析到任何标题，检查解析逻辑")
        refs = _find_referenced_sections()
        self.assertTrue(refs, "未在任何参考文档中发现对 SKILL.md 章节的「」/《》引用")

        # 归一化被引名（去装饰、去空白）后做子串匹配
        norm_headers = [_norm_header(h) for h in headers]
        missing = []
        seen = set()
        for rel, lineno, name in refs:
            key = (rel, lineno, name)
            if key in seen:
                continue
            seen.add(key)
            nname = _norm_header(name)
            if nname in _ALLOWLIST:
                continue  # 有意的概念引用，非章节断链
            if not any(nname in h for h in norm_headers):
                missing.append((rel, lineno, name))

        self.assertEqual(
            missing, [],
            "以下对 SKILL.md 章节的引用在 SKILL.md 中找不到对应标题（断链！）：\n"
            + "\n".join("  - %s:%d  «%s»" % (r, l, n) for r, l, n in missing)
            + "\n请回扫 SKILL.md：补回该章节，或修正引用处的章节名。")


if __name__ == "__main__":
    unittest.main()
