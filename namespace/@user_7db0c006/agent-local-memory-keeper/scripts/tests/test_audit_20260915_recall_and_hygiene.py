# -*- coding: utf-8 -*-
"""2026-09-15 深度审计修复 · 契约回归。

锁定三项改动，防止后续误改回退：

1. **`sem_magnitude_blend` 默认必须为 0.0**
   依据（真库消融实测，199 条 / 7 组查询）：原始语义余弦 emb_c 与 RRF 分**差一个数量级**
   （cos 0.3~0.5 vs RRF 0.006~0.033）。β=0.5 时 `(1-β)·rrf + β·cos ≈ β·cos`，
   多信号 RRF 实际权重 <5% → 退化为「纯余弦排序」。
   症状：跨域查询「git-bash 路径被原生Python解析错位」的 top3 全是**与查询无关**的投资域
   长文本（词法零重叠、仅语义余弦虚高 = hubness 假阳性）；β=0.0 后 top3 全部变为强相关
   技术记忆，而域内查询（84日均线/IMA/小说）排序基本不退化。

2. **召回参数写在 config.json 的 `keeper` 块也要生效（兜底）**
   依据：本机 store/config.json 曾把 semantic_gate 写进 keeper 块 → **完全未生效**却无人察觉
   （用户以为关了语义门控，实际仍走默认 0.42）。`recall` 块同名键仍优先。

3. **`.skillhubignore` 必须排除 `.workbuddy/` 与历史版本归档**
   依据：`.workbuddy/` 是本机自动化记录/运行记忆（含会话痕迹），属**使用者私有数据**，
   不得随包分发给别人；changelog_archive.md 223KB 纯历史档案，随每次安装下载无价值。
   ⚠️ 该文件是**仓库级**声明，发布器刻意不打包它 → 干净副本/安装副本上此组用例
   **整类跳过**（见 PackHygieneTest docstring），不得让缺文件变成 ERROR 卡死发版门禁。

4. **通用 `*bak*` 后缀回退必须留在清单里**（2026-09-16 追加）
   依据：批次快照 `*.p32bak`（4 个 / 380KB 旧版源码）**两个收口同时漏掉**——
   发布器 `EXCLUDE_SUFFIX` 只认 `.bak`/`.bak.`，本清单旧规则只认 `*.bak_*`；
   经调发布器 `_should_exclude` 实测确认会被打进包。故加 `*bak`/`*bak.*`/`*.bak*` 三条。

⚠️ **行为层局限（诚实标注）**：β 的问题只在 **neural 语义后端**下显现，而门禁基线固定
   `AI_MEM_EMBED_BACKEND=lexical`（不拉 90MB 模型），故此处只能守**契约**（默认值 +
   配置读取 + 打包规则），无法在门禁内复现排序行为。手工验证配方：
      1) 备一份真库副本，设 AI_MEMORY_STORE 指向它；
      2) 查询「git-bash 路径被原生Python解析错位」「cygpath 原生 Windows Python 路径」；
      3) 断言 top5 内不出现与查询无关的投资域长文本（如 LRN-20260730-02x 系列）；
      4) 再查「84日均线 仓位 因子」确认投资域查询**仍**正常返回投资记忆（防过度矫正）。
"""
import datetime
import json
import os
import re
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../scripts
ROOT = os.path.dirname(HERE)                                        # 技能根


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class RecallRankingAuditTest(unittest.TestCase):
    """① 排序默认值契约。"""

    def test_sem_magnitude_blend_default_is_zero(self):
        src = _read(os.path.join(HERE, "memory_ops", "__init__.py"))
        m = re.search(r'"sem_magnitude_blend"\s*:\s*([0-9.]+)', src)
        self.assertIsNotNone(m, "未找到 sem_magnitude_blend 默认值定义")
        self.assertEqual(
            float(m.group(1)), 0.0,
            "默认值被改回 >0：原始余弦会压垮 RRF（量级差 10 倍），"
            "跨域查询会被长文本 hubness 假阳性霸占 top 位。"
            "如需恢复请先读 __init__.py 中 RRF_DEFAULTS 上方的实测依据。")

    def test_rrf_defaults_comment_records_evidence(self):
        """默认值是**实测结论**而非随手值——依据必须留在代码里。"""
        src = _read(os.path.join(HERE, "memory_ops", "__init__.py"))
        idx = src.find('"sem_magnitude_blend"')
        self.assertGreater(idx, 0)
        head = src[max(0, idx - 1200):idx]
        self.assertIn("hubness", head, "RRF_DEFAULTS 上方缺少本次实测依据说明（hubness）")
        self.assertIn("2026-09-15", head, "缺少依据日期标注")


class RecallConfigBlockTest(unittest.TestCase):
    """② 配置块兼容（keeper 块兜底）。"""

    def _cfg_of(self, payload):
        tmp = tempfile.mkdtemp(prefix="keeper_gate_cfgblk_")
        os.makedirs(os.path.join(tmp, "store"), exist_ok=True)
        with open(os.path.join(tmp, "store", "config.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import memory_ops
        return memory_ops._load_recall_config(tmp)

    def test_keeper_block_fallback_takes_effect(self):
        cfg = self._cfg_of({"keeper": {"semantic_gate": 0.0}})
        self.assertEqual(
            cfg["semantic_gate"], 0.0,
            "写在 keeper 块的召回参数未生效——历史误写配置会静默失效（本机曾实际发生）")

    def test_recall_block_still_wins(self):
        cfg = self._cfg_of({"keeper": {"semantic_gate": 0.1},
                            "recall": {"semantic_gate": 0.7}})
        self.assertEqual(cfg["semantic_gate"], 0.7, "recall 块必须优先于 keeper 块兜底")

    def test_defaults_untouched_when_no_override(self):
        cfg = self._cfg_of({})
        self.assertEqual(cfg["sem_magnitude_blend"], 0.0)
        self.assertEqual(cfg["rrf_k"], 60)


class PackHygieneTest(unittest.TestCase):
    """③ 发布包排除规则。

    ⚠️ **本类只应在「源码仓」里跑**：`.skillhubignore` 是仓库级声明文件，SkillHub
    发布器**刻意不带它**（平台拒收该文件类型），故发布器复制出的干净副本
    （`%TEMP%/skillhub_pub_*`）与本技能的平台安装副本**都没有这个文件**。
    发布门禁 `publish_gate.py` 正是在那种干净副本上跑全量测试的 —— 若此处硬读文件，
    干净副本上会 `FileNotFoundError` 直接 ERROR，把「发版门禁」卡死（2026-09-16 实锤：
    手动跑 379 全绿，发布门禁跑 rc=1，三个用例全 ERROR）。

    修法：**文件不存在时整类跳过**（带可见理由），并在源码仓跑时照常断言。
    这也与发布器自身的口径一致 —— `publish_skill.py --dry-run-only` 的
    `pack_excludes_runtime_state` 项在无该文件时明确返回「本项不适用（干净副本会缺它）」。
    """

    _IG_PATH = os.path.join(ROOT, ".skillhubignore")

    def setUp(self):
        if not os.path.exists(self._IG_PATH):
            self.skipTest(
                "无 .skillhubignore（发布干净副本 / 平台安装副本）：本项为源码仓专用规则，"
                "与发布器 pack_excludes_runtime_state 的口径一致，此处不适用")
        self.ig = _read(self._IG_PATH)
        self.rules = [l.strip() for l in self.ig.splitlines()
                      if l.strip() and not l.strip().startswith("#")]

    def test_workbuddy_runtime_dir_excluded(self):
        self.assertIn(
            ".workbuddy/", self.rules,
            ".workbuddy/ 是本机自动化记录/运行记忆（含会话痕迹），属使用者私有数据，"
            "必须排除出发布包，否则随包外泄")

    def test_changelog_archive_excluded(self):
        self.assertTrue(
            any("changelog_archive" in r for r in self.rules),
            "历史版本归档（223KB 纯档案）应排除出包，需要时用 release-audit 查索引")

    def test_runtime_state_rules_kept(self):
        """老规则不得在本次改动中被误删（负向守护）。"""
        for must in ("memories/.write_lock", "*.bak_*", "_retired_*", "hooks_config.json"):
            self.assertIn(must, self.rules, "既有排除规则 %r 被误删" % must)

    def test_generic_bak_suffix_covered(self):
        """通用 bak 后缀回退必须留在清单里（2026-09-16 实测泄漏面）。

        真凶：改造期按批次留下的 `*.p32bak`（4 个文件 / 380KB 旧版源码）**两个收口都漏**——
          ① 发布器 `EXCLUDE_SUFFIX` 只有 `.bak` / `.bak.`，
             `"x.py.p32bak".endswith(".bak")` = False；
          ② 本清单旧规则是 `*.bak_*`（要求「点+bak+下划线」），`x.py.p32bak` 也不匹配。
        实测（直接调发布器 `_should_exclude`）：4 个文件全部 `排除=False` → 会被打进包。
        修法是加 `*bak` / `*bak.*` / `*.bak*` 三条通用回退；此处守住它们不被后人当冗余删掉。

        ⚠️ 只断言「规则在清单里」，不在此处 import 发布器（发布器不属本技能、不在测试环境保证可导入）。
        行为验证配方见 docstring 与 `_design/DEV_TESTING.md`。
        """
        for must in ("*bak", "*bak.*", "*.bak*"):
            self.assertIn(must, self.rules, "通用 bak 后缀回退 %r 被误删（会导致旧版源码随包外泄）" % must)


class InvestmentInvariantDowngradeTest(unittest.TestCase):
    """④ 投资域证据链 lint：从「违规」降级为「提示」（治本，而非加抑制机制）。

    依据（真库 216 条实读）：全库 26 类关系边均在正常产生，唯独 `validated_by` 仅 2 条
    （0.9%）；命中 18 条中 status 实为 active 15 / archived 2 / superseded 1。
    故：① 排除非 active；② 结果降级为 hints(severity=info)；`violations` 键保留且恒空。
    """

    def _make_store(self):
        root = tempfile.mkdtemp(prefix="keeper_gate_inv_")
        os.makedirs(os.path.join(root, "memories"), exist_ok=True)
        os.makedirs(os.path.join(root, "store"), exist_ok=True)
        entries = [
            {"id": "LRN-A", "domain": "investment", "subdomain": "factor",
             "status": "active", "tags": ["st:verified"], "summary": "active, no vb"},
            {"id": "LRN-B", "domain": "investment", "subdomain": "factor",
             "status": "archived", "tags": ["st:verified"], "summary": "archived"},
            {"id": "LRN-C", "domain": "investment", "subdomain": "system",
             "status": "active", "tags": ["st:verified"], "summary": "active, with vb"},
            {"id": "LRN-D", "domain": "tech", "subdomain": "factor",
             "status": "active", "tags": ["st:verified"], "summary": "non-investment"},
        ]
        with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False)
        for mid, rel in (("LRN-A", {}), ("LRN-B", {}),
                         ("LRN-C", {"validated_by": ["LRN-T"]}), ("LRN-D", {})):
            with open(os.path.join(root, "memories", mid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"id": mid, "relations": rel}, f, ensure_ascii=False)
        return root

    def _run(self):
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import memory_ops
        return memory_ops._check_investment_invariants(self._make_store())

    def test_missing_validated_by_is_hint_not_violation(self):
        out = self._run()
        self.assertEqual(out["violations"], [],
                         "缺 validated_by 已被降级为提示，不应再计入 violations（告警疲劳）")
        self.assertEqual([h["id"] for h in out["hints"]], ["LRN-A"])
        self.assertEqual(out["hints"][0]["severity"], "info")

    def test_inactive_entries_excluded(self):
        out = self._run()
        self.assertEqual(out["excluded_inactive"], 1, "archived/superseded 必须排除")
        self.assertEqual(out["checked"], 2, "只统计 active 的 factor/system")

    def test_violations_key_kept_for_backward_compat(self):
        out = self._run()
        self.assertIn("violations", out, "violations 键需保留（向后兼容既有读取方）")


class DoctorAckSuppressionTest(unittest.TestCase):
    """⑤ doctor 建议项 ack 抑制（治「告警疲劳」，2026-09-15 审计新增）。

    依据：`doctor` 每轮重复列出同一批建议类条目 → 恒定噪音淹没真信号。
    机制：`store/doctor_ack.json` 记录 `kind::id` → 默认不再显示。
    三条安全规约由本测试锁定：① 只抑制建议类；② TTL 过期复活；③ 完整性类永不可抑制。
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_gate_ack_")
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import memory_ops
        self.M = memory_ops

    @staticmethod
    def _sample():
        return {
            "link_candidates": [{"a": "A", "b": "B", "score": 0.5},
                                {"a": "C", "b": "D", "score": 0.4}],
            "type_mismatch_candidates": [{"id": "E", "suggest": "fact"}],
            "missing_files": ["X"],
            "dangling_relations": [{"id": "Y"}],
            "investment_invariants": {"hints": [{"id": "F", "severity": "info"}],
                                      "violations": [], "checked": 1},
        }

    def test_ack_suppresses_only_advisory(self):
        M = self.M
        M.doctor_ack(self.root, "link", "A~B", "known")
        M.doctor_ack(self.root, "type", "E", "known")
        r = self._sample()
        s = M._apply_doctor_ack(self.root, r)
        self.assertEqual(s["suppressed"], 2)
        self.assertEqual([c["a"] for c in r["link_candidates"]], ["C"],
                         "被 ack 的连接候选未被抑制")
        self.assertEqual(r["type_mismatch_candidates"], [])
        # 🔴 完整性类永不可抑制（真问题不能被「确认已知悉」藏掉）
        self.assertEqual(r["missing_files"], ["X"], "missing_files 被误抑制")
        self.assertEqual(r["dangling_relations"], [{"id": "Y"}], "dangling_relations 被误抑制")
        self.assertEqual(len(r["investment_invariants"]["hints"]), 1)

    def test_ack_all_shows_everything(self):
        M = self.M
        M.doctor_ack(self.root, "link", "A~B", "known")
        r = self._sample()
        s = M._apply_doctor_ack(self.root, r, ack_all=True)
        self.assertEqual(s["suppressed"], 0)
        self.assertEqual(len(r["link_candidates"]), 2, "--ack-all 应展开全部")

    def test_ack_ttl_expiry_revives(self):
        M = self.M
        old = datetime.datetime.now() - datetime.timedelta(days=M.DOCTOR_ACK_TTL_DAYS + 10)
        M.doctor_ack(self.root, "scope", "G", "stale", now=old)
        r = {"scope_mismatch_candidates": [{"id": "G"}]}
        s = M._apply_doctor_ack(self.root, r)
        self.assertEqual(len(r["scope_mismatch_candidates"]), 1,
                         "过期 ack 必须复活（防「抑制」变「永久静音」）")
        self.assertEqual(s["expired_revived"], 1)
        self.assertTrue({x["id"]: x for x in M.doctor_ack_list(self.root)}["G"]["expired"])

    def test_clear_removes_all(self):
        M = self.M
        M.doctor_ack(self.root, "link", "A~B", "x")
        M.doctor_ack(self.root, "scene", "H", "x")
        self.assertGreaterEqual(len(M.doctor_ack_clear(self.root)), 2)
        self.assertEqual(M.doctor_ack_list(self.root), [])

    def test_integrity_kinds_not_ackable(self):
        """负向守护：完整性类不得进入抑制面（否则真问题可被静音）。"""
        kinds = {k for (_r, k, _f) in self.M._ACK_SECTIONS}
        for bad in ("missing", "dangling", "corrupt", "status", "content", "index"):
            self.assertNotIn(bad, kinds, "完整性类 %r 不得可抑制" % bad)
        # 投资域证据链提示走嵌套路径（investment_invariants.hints），kind 为 invariant——
        # 用行为断言而非集合成员断言（它本就不在 _ACK_SECTIONS 里）。
        self.M.doctor_ack(self.root, "invariant", "F", "该结论暂无可测证据链，已知悉")
        r = {"investment_invariants": {"hints": [{"id": "F", "severity": "info"}],
                                       "violations": [], "checked": 1}}
        self.M._apply_doctor_ack(self.root, r)
        self.assertEqual(r["investment_invariants"]["hints"], [],
                         "投资域证据链提示应可被 ack 抑制")
        # CLI 的 kind 白名单必须包含 invariant
        cli = _read(os.path.join(HERE, "memory_ops", "_cli.py"))
        self.assertIn('+ ("invariant",)', cli, "CLI --ack 白名单缺 invariant")

    def test_cli_flags_registered(self):
        src = _read(os.path.join(HERE, "memory_ops", "_cli.py"))
        for flag in ("--ack-all", "--ack", "--ack-reason", "--ack-list", "--ack-clear"):
            self.assertIn('"%s"' % flag, src, "CLI 缺少参数 %s" % flag)


class LinkCandidateDeterminismTest(unittest.TestCase):
    """⑥ `doctor.link_candidates` 可复现性（2026-09-15 审计修复）。

    根因（实测 4 组对照）：`_find_link_candidates` 的 `cand_pairs` 是 **set**，直接迭代时
    顺序取决于字符串哈希，而 PYTHONHASHSEED 每进程都变 → 叠加 `max_per` 先到先得截断，
    输出每次运行都不同（PYTHONHASHSEED=0 时两次逐字节一致，即证）。
    修法：先算全部合格对 → `sort(key=(-score, a, b))` → 再按序贪心应用 max_per。
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="keeper_gate_link_")
        os.makedirs(os.path.join(self.root, "memories"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "store"), exist_ok=True)
        for mid, txt in (("LRN-1", "alpha beta gamma delta epsilon"),
                         ("LRN-2", "alpha beta gamma delta zeta"),
                         ("LRN-3", "alpha beta gamma delta eta")):
            with open(os.path.join(self.root, "memories", mid + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump({"id": mid, "summary": txt, "body": txt, "status": "active",
                           "tags": ["shared"], "relations": {}}, f)
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import memory_ops
        self.M = memory_ops

    def test_sorted_and_stable_across_calls(self):
        a = self.M._find_link_candidates(self.root)
        b = self.M._find_link_candidates(self.root)
        self.assertEqual(a, b, "同库同参两次调用结果不一致 → 不可复现")
        self.assertGreaterEqual(len(a), 2, "测试前提：共享标签的 3 条应产出 >=2 个候选对")
        keys = [(-c["score"], c["a"], c["b"]) for c in a]
        self.assertEqual(keys, sorted(keys), "结果未按 (-score, a, b) 确定性排序")

    def test_source_has_deterministic_sort(self):
        """源码契约：排序必须发生在 max_per 截断之前。"""
        src = _read(os.path.join(HERE, "memory_ops", "__init__.py"))
        i = src.find("def _find_link_candidates")
        self.assertGreater(i, 0, "未找到 _find_link_candidates")
        body = src[i:i + 5000]
        self.assertIn("_scored.sort(key=lambda x: (-x[2], x[0], x[1]))", body,
                      "缺确定性排序键：cand_pairs 是 set，迭代顺序随 PYTHONHASHSEED 变化，"
                      "叠加 max_per 先到先得 → doctor 输出每次不同")
        self.assertIn("for ia, ib, s in _scored:", body,
                      "应在排序后再按序贪心应用 max_per")

    def test_contradiction_candidates_have_tiebreaker(self):
        src = _read(os.path.join(HERE, "memory_ops", "_doctor.py"))
        self.assertIn('cands.sort(key=lambda c: (-c["score"], c["a"], c["b"]))', src,
                      "矛盾候选排序缺 (a, b) tiebreaker（同分对存留会不稳定）")


if __name__ == "__main__":
    unittest.main()
