# -*- coding: utf-8 -*-
"""release-audit 契约回归（4.9.24）。

锁住的五条口径——既防**漏报**「双主」，也防**假红灯**：
1. 平台有、日志无（窗口内）→ `missing_log` → **drift**（有人绕过日志发布）；
2. 窗口**外**的平台独有版本 → `legacy_missing`，**不算 drift**（历史 CHANGELOG 会轮转归档）；
3. 区间标题 `## 4.8.2–4.8.7` 覆盖该区间所有版本（不要求逐版单列）；
4. 「日志有、平台无、且不早于平台最新版」= 本地改了没发 → `unreleased_local`，**不算 drift**。
   ★ 本条是**实测纠正**的回归锁：首版把它判成 `pending`→drift，在本机「累积两个未发布
   版本」的正常状态下报了红灯——本项目约定「未经用户明确要求不主动发布」，那是日常态；
5. 本地版本**落后**线上 → **drift**，且提示指出「双主」前兆。

另锁「离线安全」：拿不到平台数据（断网 / 超时 / 平台返回空 / `--offline`）一律
`verdict="unknown"`（CLI 退出码 3），**绝不是 drift**——「不知道」不等于「有问题」。

全部用注入参数或 mock，**不发真实网络请求**、不碰真实记忆库。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import memory_ops as M  # noqa: E402

RA = M.release_audit


# 临时目录统一回收：门禁有 `keeper_` 前缀兜底（`run_gate.py` 跑完清本轮），但**单独跑
# 本文件**不经过门禁 ⇒ 会留残渣（实测一次 `discover` 留 16 个 `keeper_ra_skill_*`）。
_TMPDIRS = []


def tearDownModule():
    for _d in _TMPDIRS:
        shutil.rmtree(_d, ignore_errors=True)
    del _TMPDIRS[:]


def _mk_skill(version="4.9.24", changelog=None, slug="agent-local-memory-keeper"):
    """最小技能目录：`_meta.json`（带 slug/version）+ `SKILL.md`，可选 `CHANGELOG.md`。"""
    d = tempfile.mkdtemp(prefix="keeper_ra_skill_")
    _TMPDIRS.append(d)
    with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: x\nversion: %s\n---\n\n# x\n" % version)
    with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"slug": slug, "version": version}, f)
    if changelog is not None:
        with open(os.path.join(d, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write(changelog)
    return d


CL_BASIC = (
    "# CHANGELOG\n\n"
    "## 4.9.24 · 2026-09-13\n\n> x\n\n"
    "## 4.8.1 · 2026-08-12\n\n> y\n")


class _Resp(object):
    """urlopen 的假响应（上下文管理器 + read）。"""

    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BucketTest(unittest.TestCase):
    """分桶判定（注入版本集，不读 CHANGELOG 文件、不联网）。"""

    def test_platform_ahead_is_drift_and_flags_double_master(self):
        fx = _mk_skill(version="4.9.21")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.20", "4.9.21"],
               platform_versions=["4.9.20", "4.9.21", "4.9.22"])
        self.assertEqual(r["verdict"], "drift")
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing_log"], ["4.9.22"])
        joined = " ".join(r["hints"])
        self.assertIn("双主", joined, "本地落后线上时必须点明「双主」前兆")

    def test_legacy_missing_is_not_drift(self):
        """窗口外的早年平台版本只算信息项——否则会常年误报。"""
        fx = _mk_skill(version="4.9.2")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.1", "4.9.2"],
               platform_versions=["1.3.0", "2.8.0", "4.9.1", "4.9.2"])
        self.assertEqual(r["missing_log"], [])
        self.assertEqual(sorted(r["legacy_missing"]), ["1.3.0", "2.8.0"])
        self.assertEqual(r["verdict"], "ok")

    def test_multiple_unreleased_local_versions_are_not_drift(self):
        """★ 实测纠正的回归锁：本地累积多个未发布版本 = 正常态，不是 drift。"""
        fx = _mk_skill(version="4.9.24")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.22", "4.9.23", "4.9.24"],
               platform_versions=["4.9.22"])
        self.assertEqual(sorted(r["unreleased_local"]), ["4.9.23", "4.9.24"])
        self.assertEqual(r["bundled"], [])
        self.assertEqual(r["verdict"], "ok", "「改了没发」不得判成 drift（假红灯教训）")
        self.assertNotIn("pending", r, "已废弃的 pending 桶不应再出现")

    def test_bundled_is_not_drift(self):
        """日志有、平台无，但平台已越过它 → 改动随更晚版本发出，仅提示。"""
        fx = _mk_skill(version="4.9.22")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.14", "4.9.22"],
               platform_versions=["4.9.22"])
        self.assertEqual(r["bundled"], ["4.9.14"])
        self.assertEqual(r["unreleased_local"], [])
        self.assertEqual(r["verdict"], "ok")

    def test_version_compare_is_numeric_not_string(self):
        """4.9.10 > 4.9.9：按字符串比会得出反的结论（假 drift）。"""
        fx = _mk_skill(version="4.9.10")
        r = RA(skill_root=fx,
               changelog_versions=["4.9.9", "4.9.10"],
               platform_versions=["4.9.9"])
        self.assertEqual(r["unreleased_local"], ["4.9.10"])
        self.assertEqual(r["bundled"], [], "4.9.10 不早于平台最新版，不该进 bundled")
        self.assertEqual(r["verdict"], "ok")

    def test_local_ahead_only_hints_not_drift(self):
        fx = _mk_skill(version="4.9.30")
        r = RA(skill_root=fx, changelog_versions=["4.9.30"],
               platform_versions=["4.9.29"])
        self.assertEqual(r["verdict"], "ok")
        self.assertTrue(any("高于线上" in h for h in r["hints"]))
        self.assertFalse(any("双主" in h and "前兆" in h and "落后" in h for h in r["hints"]))


class ChangelogParseTest(unittest.TestCase):
    """真实 CHANGELOG 文件解析：区间标题 + 窗口 + 无版本时报错。"""

    def test_range_heading_covers_whole_range(self):
        cl = ("# CHANGELOG\n\n"
              "## 4.9.24 · 2026-09-13\n\n> x\n\n"
              "## 4.8.2–4.8.7 · 2026-08-31\n\n> 区间补记\n\n"
              "## 4.8.1 · 2026-08-12\n\n> y\n")
        fx = _mk_skill(version="4.9.24", changelog=cl)
        r = RA(skill_root=fx,
               platform_versions=["4.8.1", "4.8.2", "4.8.3", "4.8.7", "4.9.24"])
        self.assertEqual(r["changelog_ranges"], ["4.8.2–4.8.7"])
        self.assertEqual(r["missing_log"], [], "区间标题应覆盖 4.8.2~4.8.7 全部版本")
        self.assertEqual(r["verdict"], "ok")

    def test_without_range_heading_same_versions_are_missing(self):
        """负向对照：去掉区间标题，同样六个版本必须被判为 missing（证明上一条不是空绿）。"""
        cl = ("# CHANGELOG\n\n"
              "## 4.9.24 · 2026-09-13\n\n> x\n\n"
              "## 4.8.1 · 2026-08-12\n\n> y\n")
        fx = _mk_skill(version="4.9.24", changelog=cl)
        r = RA(skill_root=fx,
               platform_versions=["4.8.1", "4.8.2", "4.8.3", "4.8.7", "4.9.24"])
        self.assertEqual(r["changelog_ranges"], [])
        self.assertEqual(r["missing_log"], ["4.8.2", "4.8.3", "4.8.7"])
        self.assertEqual(r["verdict"], "drift")

    def test_window_since_is_earliest_in_main_changelog(self):
        cl = ("# CHANGELOG\n\n"
              "## 4.9.24 · 2026-09-13\n\n> x\n\n"
              "## 4.7.11 · 2026-08-11\n\n> y\n")
        fx = _mk_skill(version="4.9.24", changelog=cl)
        r = RA(skill_root=fx, platform_versions=["4.7.11", "4.9.24"])
        self.assertEqual(r["window_since"], "4.7.11")

    def test_changelog_without_version_headings_reports_error(self):
        """格式变了要显式报错，不能静默当「全一致」。"""
        fx = _mk_skill(version="4.9.24", changelog="# CHANGELOG\n\n> 没有任何版本标题\n")
        r = RA(skill_root=fx, platform_versions=["4.9.24"])
        self.assertEqual(r["error"], "changelog_no_versions")
        self.assertEqual(r["verdict"], "unknown")

    def test_missing_skill_root_reports_error(self):
        r = RA(skill_root=os.path.join(tempfile.gettempdir(), "keeper_ra_no_such_dir_zz"))
        self.assertEqual(r["error"], "skill_root_not_found")
        self.assertEqual(r["verdict"], "unknown")


class OfflineSafetyTest(unittest.TestCase):
    """「不知道」绝不当作「有问题」。"""

    def test_offline_flag_yields_unknown(self):
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC)
        r = RA(skill_root=fx, offline=True)
        self.assertEqual(r["mode"], "offline")
        self.assertEqual(r["verdict"], "unknown")
        self.assertFalse(r["ok"])
        self.assertTrue(any("无法判定" in h for h in r["hints"]))

    def test_network_failure_yields_unknown_not_drift(self):
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC)
        with mock.patch("urllib.request.urlopen", side_effect=OSError("net down")):
            r = RA(skill_root=fx, timeout=1)
        self.assertEqual(r["error"], "network_unavailable")
        self.assertEqual(r["verdict"], "unknown")
        self.assertNotEqual(r["verdict"], "drift")

    def test_platform_returning_empty_yields_unknown(self):
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC)
        with mock.patch("urllib.request.urlopen", return_value=_Resp({"versions": []})):
            r = RA(skill_root=fx, timeout=1)
        self.assertEqual(r["error"], "platform_empty")
        self.assertEqual(r["verdict"], "unknown")

    def test_online_success_parses_platform_versions(self):
        """正向对照：mock 一个正常平台响应，必须真的走通联网分支。"""
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC)
        payload = {"versions": [{"version": "4.8.1"}, {"version": "4.9.24"}]}
        with mock.patch("urllib.request.urlopen", return_value=_Resp(payload)):
            r = RA(skill_root=fx, timeout=1)
        self.assertIsNone(r["error"])
        self.assertEqual(r["mode"], "online")
        self.assertEqual(r["platform_latest"], "4.9.24")
        self.assertEqual(r["missing_log"], [])
        self.assertEqual(r["verdict"], "ok")

    def test_online_response_missing_a_logged_version_is_drift(self):
        """联网分支的负向对照：平台发了一个日志里没有的版本 → missing_log → drift。"""
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC)
        payload = {"versions": [{"version": "4.8.1"}, {"version": "4.9.23"}]}
        with mock.patch("urllib.request.urlopen", return_value=_Resp(payload)):
            r = RA(skill_root=fx, timeout=1)
        self.assertEqual(r["missing_log"], ["4.9.23"])
        self.assertEqual(r["verdict"], "drift")

    def test_slug_missing_offline_reports_error(self):
        """没有 slug 就拼不出查询地址——显式报错，不是静默 ok。"""
        fx = _mk_skill(version="4.9.24", changelog=CL_BASIC, slug="")
        r = RA(skill_root=fx, timeout=1)
        self.assertEqual(r["error"], "slug_unknown")
        self.assertEqual(r["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
