# -*- coding: utf-8 -*-
"""_reflect.py 的 accessed_from 写入幂等回归（2026-09-15 审计修复）。

取证（真库 `D:\\AI记忆`，207 条记忆，只读统计）：
  | action              | 出现次数 | 净冗余 |
  |---------------------|---------:|-------:|
  | auto_flag_conflict  |      404 |    368 |
  | calibrated_up       |        6 |      5 |
多条记忆的 accessed_from 已顶满 12 条上限，内容全是**同一对矛盾**（仅 date 不同），
把真正有用的访问证据挤出去。根因：`_reflect.py` 的 `auto_flag_conflict` 分支
**无条件 append**，而同一对矛盾在每次 `reflect --auto` 都会被重新检出。

修法：按「对手 id」永久去重（结构化 `with` 字段 + 旧条目 reason 前缀兜底）；
`calibrated_up` 同日去重。

⚠️ fixture 设计要点（踩过的坑，勿改回去）：两条记忆的正文相似度必须落在
   `[CONTRADICTION_SEM_THRESHOLD(0.65), 词法去重阈值(0.99))` 之间——
   若用**完全相同**的正文，会先去重门被判重复并合并（其一 superseded），
   矛盾循环随即跳过该条，测试就永远测不到矛盾分支。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../scripts
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 正文相似度实测 0.7541（词法后端）：> 0.65 触发矛盾，< 0.99 不触发去重合并
TXT_X = "keeper \u7684 hooks \u76ee\u5f55\u5fc5\u987b\u663e\u5f0f\u58f0\u660e\u6392\u9664\u89c4\u5219\uff0c\u5426\u5219\u8fd0\u884c\u6001 json \u4f1a\u968f\u5305\u5916\u6cc4\u7ed9\u4f7f\u7528\u8005"
TXT_C = "hooks \u76ee\u5f55\u5fc5\u987b\u58f0\u660e\u6392\u9664\u89c4\u5219\uff0c\u8fd0\u884c\u6001 json \u4e0d\u5f97\u968f\u5305\u5916\u6cc4"
TAGS = ["zeta-tag", "omega-tag"]


class ReflectAccessedFromIdempotentTest(unittest.TestCase):
    def setUp(self):
        self._env_bak = os.environ.get("AI_MEM_EMBED_BACKEND")
        os.environ["AI_MEM_EMBED_BACKEND"] = "lexical"   # 不拉 90MB 模型，且阈值确定
        self.root = tempfile.mkdtemp(prefix="keeper_gate_refl_")
        os.makedirs(os.path.join(self.root, "memories"), exist_ok=True)
        import memory_ops
        self.M = memory_ops

    def tearDown(self):
        if self._env_bak is None:
            os.environ.pop("AI_MEM_EMBED_BACKEND", None)
        else:
            os.environ["AI_MEM_EMBED_BACKEND"] = self._env_bak
        try:
            shutil.rmtree(self.root)
        except Exception:
            pass

    # ── helpers ──────────────────────────────────────────────────────────────
    def _w(self, mid, cat, txt, af=None):
        p = os.path.join(self.root, "memories", mid + ".json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"id": mid, "category": cat, "status": "active", "tags": list(TAGS),
                       "summary": txt, "body": txt, "scope": "universal", "project": "",
                       "confidence": 0.6, "access_count": 1, "created": "2026-09-01",
                       "updated": "2026-09-01", "relations": {},
                       "accessed_from": af or []}, f, ensure_ascii=False)

    def _read(self, mid):
        with open(os.path.join(self.root, "memories", mid + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def _flags(self, mid):
        return [e for e in (self._read(mid).get("accessed_from") or [])
                if isinstance(e, dict) and e.get("action") == "auto_flag_conflict"]

    def _reflect(self):
        impl = getattr(self.M, "_reflect_impl", None)
        if impl is None:
            impl = self.M._reflect_mod._reflect_impl
        return impl(self.root, auto=True)

    def _seed_pair(self):
        """x=best_practice(被矛盾) / c=correction(纠正) —— 共享 2 个非泛化标签。"""
        self._w("LRN-9001", "best_practice", TXT_X)
        self._w("LRN-9002", "correction", TXT_C)

    # ── 1. 主用例：连跑多次不得累积重复 ────────────────────────────────────────
    def test_conflict_marker_not_duplicated_across_runs(self):
        self._seed_pair()
        counts, last = [], None
        for _ in range(3):
            last = self._reflect()
            counts.append(len(self._flags("LRN-9001")))
        self.assertTrue(last.get("contradictions"),
                        "测试前提失效：这对记忆未被判矛盾（fixture 的相似度/标签需复核）")
        self.assertEqual(counts, [1, 1, 1],
                         "同一对矛盾连跑 3 次 reflect 后应只留 1 条标记，实际 %s"
                         "（旧实现无条件 append → 实测真库净冗余 368 条）" % counts)

    # ── 2. 兼容旧条目：无 with 字段、靠 reason 前缀匹配也算已记过 ──────────────
    def test_legacy_entry_without_with_field_recognized(self):
        self._w("LRN-9001", "best_practice", TXT_X, af=[{
            "action": "auto_flag_conflict", "by": "reflect_auto",
            "reason": "possible contradiction with LRN-9002 (sem_sim=0.66)",
            "date": "2026-08-01"}])
        self._w("LRN-9002", "correction", TXT_C)
        self._reflect()
        self.assertEqual(len(self._flags("LRN-9001")), 1,
                         "旧格式条目（无 with 字段）应被识别为已记录，不得再追加一条")

    # ── 3. 反向：不同对手 id 仍应正常追加（防过度去重） ────────────────────────
    def test_different_counterpart_still_appends(self):
        self._w("LRN-9001", "best_practice", TXT_X, af=[{
            "action": "auto_flag_conflict", "by": "reflect_auto",
            "with": "LRN-9999",
            "reason": "possible contradiction with LRN-9999 (sem_sim=0.70)",
            "date": "2026-08-01"}])
        self._w("LRN-9002", "correction", TXT_C)
        self._reflect()
        self.assertEqual(len(self._flags("LRN-9001")), 2,
                         "换了一个对手 id 时应正常追加新标记（去重键必须是「对手 id」而非仅 action）")

    # ── 4. 源码契约 ─────────────────────────────────────────────────────────
    def test_source_has_idempotence_guard(self):
        p = os.path.join(HERE, "memory_ops", "_reflect.py")
        with open(p, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("_flag_dup", src, "缺 auto_flag_conflict 的去重判定")
        self.assertIn('"with": c["id"]', src, "缺结构化对手 id 字段（去重键）")
        self.assertIn("_af_u", src, "缺 calibrated_up 的同日去重")


if __name__ == "__main__":
    unittest.main()
