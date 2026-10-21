import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))                   # scripts/
HOOKS = os.path.abspath(os.path.join(HERE, "..", "..", "hooks"))  # skill 根/hooks/
for p in (SCR, HOOKS):
    if p not in sys.path:
        sys.path.insert(0, p)

import contract  # noqa: E402
import keeper_hook_common as H  # noqa: E402


class TokenizeDedupTest(unittest.TestCase):
    def test_tokenize_output_equals_contract(self):
        samples = ["电脑清理脚本路径", "decorator cache pattern",
                   "记忆 系统 设计", "A1 B2 c3", ""]
        for s in samples:
            self.assertEqual(H.tokenize(s), contract.tokenize(s), msg=repr(s))

    def test_containment_output_equals_contract(self):
        a = H.tokenize("电脑清理 脚本 路径 设计")
        b = H.tokenize("清理 脚本")
        self.assertEqual(H.containment(a, b), contract.containment(a, b))

    def test_tokenize_is_contract_single_source(self):
        # 正常环境钩子应直接引用契约层单一真源（而非本地副本）
        self.assertIs(H.tokenize, contract.tokenize)
        self.assertIs(H.containment, contract.containment)


if __name__ == "__main__":
    unittest.main()
