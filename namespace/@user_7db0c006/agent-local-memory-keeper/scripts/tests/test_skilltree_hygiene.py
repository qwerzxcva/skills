# -*- coding: utf-8 -*-
"""活跃代码目录不得残留补丁快照（`*.bak_*` / `_retired_*` / `_bak_*`）。

为什么单列一条（来自本轮真实踩坑）：
  加密下线用了「补丁器 + 快照」模式，`.bak_20260915_*` 一度落在 `scripts/memory_ops/`
  与 `scripts/tests/`。`.skillhubignore` 虽已排除它们（不进包、无泄漏），但留在活跃路径上会：
    ① 被 grep / 审计扫到 → **误报为「加密残留」**（本轮 `_p25_full_audit` 实际踩过此坑）；
    ② 让人误以为存在多份真源。
  故用测试钉死：`scripts/`（活跃代码区）只放源码，快照一律搬 `_retired_*`。

边界（同样重要）：
  - 只扫 `scripts/` 下；技能根的 `_retired_tmp_*` 是**约定归档点**，允许存在。
  - 不扫 `__pycache__`（构建产物，发布链另有排除）。
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)      # .../agent-local-memory-keeper/scripts
SKILL = os.path.dirname(SCRIPTS)     # 技能根

_ALLOW_DIR_MARKER = "_retired_tmp_"   # 约定归档点（允许）
_SUFFIX_MARKERS = (".bak_", ".retired_")
_PREFIXES = ("_retired_", "_bak_")


def _is_snapshot(name):
    return any(m in name for m in _SUFFIX_MARKERS) or name.startswith(_PREFIXES)


class SkillTreeHygieneTest(unittest.TestCase):
    def _offenders(self):
        bad = []
        for dirpath, dirnames, filenames in os.walk(SCRIPTS):
            dirnames[:] = [
                d for d in dirnames
                if d != "__pycache__" and _ALLOW_DIR_MARKER not in d
            ]
            for fn in filenames:
                if _is_snapshot(fn):
                    bad.append(os.path.relpath(os.path.join(dirpath, fn), SKILL))
        return sorted(bad)

    def test_no_patch_snapshots_under_scripts(self):
        bad = self._offenders()
        self.assertEqual(
            bad, [],
            "scripts/ 下发现补丁快照（应先搬进 _retired_*）：\n  " + "\n  ".join(bad),
        )

    def test_detector_matches_snapshot_names(self):
        """负向对照：判定函数必须真的会命中，否则等于没有闸门。"""
        for n in (
            "_crypto.py.bak_20260915_194859",
            "_retired_stage2__bak_stage2_uninstall_20260915_212513.py",
            "_bak_stage2_uninstall.py",
            "foo.retired_2026.py",
        ):
            self.assertTrue(_is_snapshot(n), "应判定为快照：%s" % n)

    def test_detector_ignores_real_sources(self):
        """正向对照：正常源码名一律不得误判。"""
        for n in (
            "_crypto.py", "memory_ops.py", "__init__.py",
            "test_pack_ignore_gate.py", "_p25_full_audit.py",
        ):
            self.assertFalse(_is_snapshot(n), "不应判定为快照：%s" % n)


if __name__ == "__main__":
    unittest.main()
