#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock-theme-radar 结构校验脚本（prompt-only Skill 的自动化硬门槛）。

校验项：
  1. SKILL.md 存在且含合法 YAML frontmatter（name/description/version/license 必备）。
  2. frontmatter 含 trigger_words，且 description 长度合理。
  3. SKILL.md 正文覆盖关键能力声明：双模式路由、联网检测、证据强度、非投资建议。
  4. 两个输出模板（tracking-card.md / mapping-table.md）存在且含必要区块。
  5. references/ 下 5 个参考手册齐全。

用法：python tests/run_tests.py
退出码：0 通过，1 存在结构性问题。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fail(msg):
    print(f"[FAIL] {msg}")
    return False


def ok(msg):
    print(f"[ OK ] {msg}")
    return True


def read_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    fm = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def main():
    passed = True
    skill_path = os.path.join(ROOT, "SKILL.md")
    if not os.path.isfile(skill_path):
        print("[FAIL] SKILL.md 缺失")
        return 1

    with open(skill_path, encoding="utf-8") as f:
        skill_text = f.read()

    # 1. frontmatter
    fm = read_frontmatter(skill_text)
    if fm is None:
        passed = fail("SKILL.md 缺少合法 YAML frontmatter")
    else:
        for field in ("name", "description", "version", "license"):
            if field not in fm or not fm[field]:
                passed = fail(f"frontmatter 缺少字段: {field}")
            else:
                ok(f"frontmatter 字段 {field} 存在")
        tw = fm.get("trigger_words", "")
        if len(tw) < 10:
            passed = fail("trigger_words 过短或缺失")
        else:
            ok(f"trigger_words 存在（{len(tw)} 字符）")
        if len(fm.get("description", "")) < 30:
            passed = fail("description 过短")
        else:
            ok("description 长度合理")

    # 2. 关键能力声明
    checks = {
        "双模式": "双模式自动路由",
        "联网检测": "联网检测",
        "证据强度": "证据强度",
        "非投资建议": "不构成投资建议",
    }
    for label, kw in checks.items():
        if kw in skill_text:
            ok(f"正文含能力声明: {label}")
        else:
            passed = fail(f"正文缺少能力声明: {label}")

    # 3. 模板完整性
    card = os.path.join(ROOT, "templates", "tracking-card.md")
    table = os.path.join(ROOT, "templates", "mapping-table.md")
    if os.path.isfile(card):
        ct = open(card, encoding="utf-8").read()
        need = ["一句话定义", "驱动因素", "关联标的", "关键来源", "近期动态", "追踪建议"]
        miss = [s for s in need if s not in ct]
        if miss:
            passed = fail(f"追踪卡模板缺区块: {miss}")
        else:
            ok("追踪卡模板六段齐全")
    else:
        passed = fail("templates/tracking-card.md 缺失")

    if os.path.isfile(table):
        tt = open(table, encoding="utf-8").read()
        need = ["结论清单", "传导链", "相关个股", "证据强度", "逻辑补充说明"]
        miss = [s for s in need if s not in tt]
        if miss:
            passed = fail(f"映射表模板缺区块: {miss}")
        else:
            ok("映射表模板区块齐全")
    else:
        passed = fail("templates/mapping-table.md 缺失")

    # 4. references 齐全
    refs = {
        "dual-mode-routing.md",
        "evidence-strength.md",
        "three-layer-transmission.md",
        "web-degradation.md",
        "image-event-extraction.md",
    }
    ref_dir = os.path.join(ROOT, "references")
    missing = [r for r in refs if not os.path.isfile(os.path.join(ref_dir, r))]
    if missing:
        passed = fail(f"references 缺失: {missing}")
    else:
        ok("references 五个手册齐全")

    print("\n=== 结构校验 {} ===".format("通过 ✅" if passed else "未通过 ❌"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
