# -*- coding: utf-8 -*-
"""doctor 自检字段不得「静默失败」回归测试。

背景（2026-09-10 实测）：`doctor` 输出的 `scheduler` 字段长期是
`{"error": "scheduler status check failed"}`，一直被当成「本机 schtasks 被安全策略拦了」。
实跑取证后发现根因是 **`_doctor.py` 里 `subprocess` 未定义**——本模块是零 import 文件
（符号靠运行期注入），而 subprocess 从不在注入集合里，于是 `_check_scheduler_status()`
每次调用都抛 NameError，被上层 `except Exception` 吞成一句没有根因的"检查失败"。
结果：调度自检**从未真正执行过**，schtasks 一次都没被调用。

这类失效最危险的地方是它长得像"环境问题"，不会有人去查。本文件把「自检字段必须真的跑出
结果、且失败时必须带根因」锁死，防止以后再退化成无根因的假失败。
"""
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)          # scripts/
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import memory_ops as mo  # noqa: E402


class TestDoctorSelfcheckFields(unittest.TestCase):
    """hooks / scheduler 两个自检字段：跑得出来，失败要带根因。"""

    @classmethod
    def setUpClass(cls):
        # 必须落在系统临时目录：建在技能目录里会被打进发布包。
        cls.base = tempfile.mkdtemp(prefix="keeper_docself_")
        cls.root = os.path.join(cls.base, "lib")
        mo.deposit(cls.root, category="best_practice", tags=[],
                   summary="doctor 自检字段测试条目",
                   body="用于验证 doctor 的 hooks / scheduler 自检不会静默失败。",
                   tier="working", mid="LRN-DOCSELF-001")
        mo.flush_memory_index(cls.root)
        cls.data = mo.doctor(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_doctor_returns_dict(self):
        self.assertIsInstance(self.data, dict, "doctor 应返回 dict")

    def test_hooks_field_not_error(self):
        hooks = self.data.get("hooks")
        self.assertIsNotNone(hooks, "doctor 输出缺 hooks 字段")
        self.assertNotIn("error", hooks,
                         "hooks 自检静默失败（异常被吞）：%s" % hooks)

    def test_scheduler_field_not_error(self):
        sched = self.data.get("scheduler")
        self.assertIsNotNone(sched, "doctor 输出缺 scheduler 字段")
        self.assertNotIn("error", sched,
                         "scheduler 自检静默失败（异常被吞）：%s" % sched)

    def test_scheduler_has_tasks(self):
        """真跑过就有 tasks 列表；查不到也要给出可诊断的说明，而不是空字典。"""
        sched = self.data.get("scheduler") or {}
        self.assertIn("tasks", sched, "scheduler 缺 tasks 字段：%s" % sched)
        self.assertIsInstance(sched["tasks"], list)
        self.assertTrue(len(sched["tasks"]) >= 1,
                        "tasks 不应为空（无任务时也要有占位说明）：%s" % sched)

    def test_error_field_carries_detail(self):
        """若将来真的失败，必须带 detail（根因），不许只剩一句'检查失败'。

        这里直接构造一次失败：把 scheduler 的异常分支文案要求写死为含 detail。
        用源码级断言，避免为了触发一次真失败去破坏环境。
        """
        src_path = os.path.join(_SCRIPTS, "memory_ops", "_doctor.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        idx = src.find('"error": "scheduler status check failed"')
        self.assertNotEqual(idx, -1, "找不到 scheduler 失败分支，可能已被改写")
        window = src[idx:idx + 200]
        self.assertIn("detail", window,
                      "scheduler 失败分支必须带 detail（暴露根因），实际：%s" % window[:120])


if __name__ == "__main__":
    unittest.main()
