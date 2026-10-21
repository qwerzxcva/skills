"""契约层骨架测试（随包发布）。

验证 `scripts/contract` 模块可导入、接口契约存在，且 PreInjector 已实现真实可测行为
（slice 2 起取代 slice 1 的占位 NotImplementedError）：inject 对平凡输入返回结构化
InjectResult，而非伪装或抛未实现。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from contract import PreInjector  # noqa: E402


class ContractSkeletonTest(unittest.TestCase):
    def test_module_imports_and_exposes_interface(self):
        self.assertTrue(hasattr(PreInjector, "inject"))
        self.assertTrue(hasattr(PreInjector, "select"))
        self.assertTrue(hasattr(PreInjector, "format"))

    def test_inject_returns_result_for_trivial_input(self):
        inj = PreInjector()
        res = inj.inject("abc", "s1",
                         recall_fn=lambda q, n: {"entries": []},
                         session_injected_ids_fn=lambda s: set(),
                         mark_injected_fn=lambda s, ids: None)
        self.assertFalse(res.injected)  # prompt < 6 字 → 不注入
        self.assertEqual(res.reason, "prompt_too_short")


if __name__ == "__main__":
    unittest.main()
