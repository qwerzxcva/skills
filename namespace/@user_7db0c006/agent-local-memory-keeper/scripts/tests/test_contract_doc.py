import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", ".."))
CONTRACT = os.path.join(SKILL, "references", "CONTRACT.md")


class ContractDocTest(unittest.TestCase):
    def test_exists_and_states_caching_posture(self):
        self.assertTrue(os.path.isfile(CONTRACT), "references/CONTRACT.md 必须存在")
        with open(CONTRACT, encoding="utf-8") as f:
            txt = f.read()
        self.assertIn("PreInjector 不做召回结果缓存", txt)
        self.assertIn("memory_ops._recall_cache", txt)
        self.assertIn("单一真源", txt)


if __name__ == "__main__":
    unittest.main()
