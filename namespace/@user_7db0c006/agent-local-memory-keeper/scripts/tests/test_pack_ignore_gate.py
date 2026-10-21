# -*- coding: utf-8 -*-
"""静态闸门回归测试：发布包洁净度（运行态产物不得进包）。

锁定 2026-09-11 全量体检发现的实锤问题：
  · 待发布清单里躺着 3 个**运行态/遗留**文件——hooks/_session_inject.json（测试写的
    注入状态）、keeper_daemon 的 daemon STATE（含上一台机器的端口与本机 token）、
    hooks/_retired_2026-08-11_bash_error_capture.py（已退休件）。
  · 根因：发布器只按 .log/.lock/.pid/.jsonl 等**后缀**排除，不覆盖 .json 状态；
    而测试在源码树内跑钩子/守护进程会把状态写回源码目录。

闸门设计取舍：不扫"源码树里有没有这些文件"（钩子一跑就重生，publish_gate 先 tests 后
claims，扫了必然 flaky 红），改扫**技能级 .skillhubignore 是否声明了排除项、且语义能命中**。
判据与发布器（另一技能 skillhub-cli-publish 的 publish_skill.py）的排除语义对齐。

2026-09-13 补：`.bak_*` 这条排除过去**只声明、无人验**（本测试文件里搜不到 "bak"）——
开发期「改动前整文件快照」同样按后缀排除不到，会随包外泄。本次把它纳入探针 + 负向用例。

测试策略：搭最小 skill_root（只需一个 .skillhubignore）+ 正反双向断言：
  - 真实声明 → PASS（防闸门空转）；
  - 少一行 / 行被注释掉 → 必须 FAIL（防形同虚设）；缺整个文件 → 跳过（无从校验）；
  - 排除写太宽（把真源码也排掉）→ 必须 FAIL（防漏发）；
  - 用**等价通配**写法 → 不得被误杀（判据是语义覆盖，不是逐字匹配）。
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
SKILL_ROOT = os.path.dirname(HERE)                                   # 技能根
sys.path.insert(0, HERE)
import verify_claims as vc  # noqa: E402

_REQUIRED_LINES = (
    "memories/.write_lock\n"
    "hooks/_session_inject.json\n"
    "hooks/_auto_cap.json\n"
    "hooks/_errcap_state.json\n"
    "keeper_daemon/.daemon*.json\n"
    "_retired_*\n"
    "*.bak_*\n"
)
_DAEMON_LINE = "keeper_daemon/.daemon*.json\n"
_BAK_LINE = "*.bak_*\n"


class PackIgnoreGateTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_pack_")

    def tearDown(self):
        # 注：本环境删除类 API 受限，失败时残留临时目录不影响测试结论
        try:
            shutil.rmtree(self.root)
        except Exception:
            pass

    def _write_ignore(self, text):
        with open(os.path.join(self.root, ".skillhubignore"), "w", encoding="utf-8") as f:
            f.write(text)

    # ── 正向 1：真实技能的 .skillhubignore 必须 PASS ──
    def test_real_skillignore_passes(self):
        r = vc._static_pack_excludes_runtime_state(SKILL_ROOT)
        self.assertTrue(r["ok"], "真实 .skillhubignore 应覆盖全部运行态产物；实际: %s" % r.get("error"))

    # ── 正向 2：等价通配写法不得被误杀（判据=语义覆盖，非逐字匹配）──
    def test_equivalent_wildcard_passes(self):
        self._write_ignore(
            "# 用通配等价覆盖\n"
            "hooks/_*.json\n"
            "keeper_daemon/.daemon*.json\n"
            "_retired_*\n"
            "mem_bridge.py.bak_*\n"   # 等价于 *.bak_*（窄写法也应命中探针，判据是语义）
        )
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertTrue(r["ok"], "通配等价写法应通过；实际: %s" % r.get("error"))

    # ── 负向 0：写死旧文件名（.daemon.json）已覆盖不到按库命名的 STATE，必须 FAIL ──
    # 守护进程 STATE 自 4.9.13 起带**库指纹**（`.daemon-<指纹>.json`），只声明旧名会让
    # 新的状态文件进包（里面带着端口与 daemon token）——这正是要拦的一类。
    def test_hardcoded_legacy_name_fails(self):
        self._write_ignore(_REQUIRED_LINES.replace(_DAEMON_LINE,
                                                  "keeper_daemon/.daemon.json\n"))
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertFalse(r["ok"], "只写死旧名 .daemon.json 必须 FAIL（按库命名的 STATE 会漏排）")
        self.assertIn(".daemon-", str(r.get("actual")))

    # ── 负向 1：漏声明一项（daemon STATE）必须 FAIL ──
    def test_missing_daemon_state_fails(self):
        self._write_ignore(_REQUIRED_LINES.replace(_DAEMON_LINE, ""))
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertFalse(r["ok"], "漏掉 daemon STATE 必须 FAIL（否则会带着端口/token 发包）")
        self.assertIn(".daemon-", str(r.get("actual")))

    # ── 负向 2：整行被注释掉必须 FAIL（"看起来写了"不等于生效）──
    def test_commented_line_fails(self):
        self._write_ignore(_REQUIRED_LINES.replace(
            "hooks/_session_inject.json\n", "# hooks/_session_inject.json\n"))
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertFalse(r["ok"], "注释行不算排除声明，必须 FAIL")

    # ── 负向 3：排除写太宽把真源码也排掉必须 FAIL（防漏发）──
    def test_over_broad_exclude_fails(self):
        self._write_ignore(_REQUIRED_LINES + "hooks/\n")
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertFalse(r["ok"], "把整个 hooks/ 排掉会让钩子源码漏发，必须 FAIL")
        self.assertIn("over_excluded", str(r.get("actual")))

    # ── 负向 4 已改判（2026-09-13）："有 _meta.json 就算源码树"是错的 ──
    # `_meta.json` 由**平台注入下载产物**（对照实测：三个技能的下发包都含它），于是
    # "下载/安装副本"会被误判成源码树 → 本项在自家发布产物上恒报假红。
    # 现语义：**缺 .skillhubignore 就无从校验、本项跳过**，不得再靠 _meta.json 判别。
    def test_downloaded_copy_with_meta_is_skipped(self):
        with open(os.path.join(self.root, "_meta.json"), "w", encoding="utf-8") as f:
            f.write('{"version": "9.9.9"}')
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertTrue(r["ok"],
                        "下载/安装副本（平台注入 _meta.json、无仓库级 .skillhubignore）"
                        "必须放行；实际: %s" % r.get("error"))

    def test_missing_ignore_falls_back_to_skip_with_reason(self):
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertTrue(r["ok"], "缺声明文件应跳过而非判红")
        self.assertIn("无从校验", str(r.get("actual")),
                      "跳过必须是**显式说明**的，不能静默")

    # ── 负向 5：漏声明 .bak_ 快照必须 FAIL（开发期整文件回滚基线不得随包外泄）──
    # 2026-09-13 新增：`.skillhubignore` 里写着 *.bak_*，但此前**没有任何测试验它**
    # （本文件搜不到 "bak"）——「有人声明、没人验证」是同一个静默家族，故补探针 + 本用例。
    def test_missing_bak_snapshot_exclude_fails(self):
        self._write_ignore(_REQUIRED_LINES.replace(_BAK_LINE, ""))
        r = vc._static_pack_excludes_runtime_state(self.root)
        self.assertFalse(r["ok"], "漏掉 *.bak_* 必须 FAIL（开发期整文件快照会随包外泄）")
        self.assertIn(".bak_", str(r.get("actual")))

    # ── 防误杀 4：发布「干净副本」不得被误杀 ──
    # 发布器的上传载荷**必须**排除 .skillhubignore（SkillHub 拒收该文件类型），
    # 而它恰恰是在干净副本里跑本门禁 → 若此处判 FAIL，门禁会自己拦住每一次发版（真实踩过）。
    def test_clean_copy_is_skipped(self):
        r = vc._static_pack_excludes_runtime_state(self.root)  # 既无 .skillhubignore 也无 _meta.json
        self.assertTrue(r["ok"], "发布干净副本应放行；实际: %s" % r.get("error"))
        self.assertIn("干净副本", str(r.get("actual")),
                      "放行必须是**显式说明**的跳过，不能静默")


if __name__ == "__main__":
    unittest.main()
