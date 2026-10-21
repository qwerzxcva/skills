# -*- coding: utf-8 -*-
"""
v10.0.0 版本一致性测试 — 三处版本号同步校验。

验证：
- scripts.__version__ == "10.0.0"
- _meta.json version == "10.0.0"
- SKILL.md frontmatter version == 10.0.0
- README.md 标题含 v10.0.0
- 5 个历史版本 pin 测试断言 10.0.0
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

import scripts  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
README_MD = SKILL_DIR / "README.md"
INIT_PY = SKILL_DIR / "scripts" / "__init__.py"
META_JSON = SKILL_DIR / "_meta.json"


def _frontmatter(text: str) -> str:
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else ""


def test_init_version():
    assert scripts.__version__ == "10.0.0", (
        f"scripts.__version__ should be 10.0.0, got {scripts.__version__}"
    )


def test_meta_version():
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    assert meta["version"] == "10.0.0", (
        f"_meta.json version should be 10.0.0, got {meta['version']}"
    )


def test_skill_md_version():
    fm = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    m = re.search(r"^version:\s*(10\.0\.0)\s*$", fm, re.MULTILINE)
    assert m, "SKILL.md frontmatter version should be 10.0.0"


def test_readme_md_version():
    txt = README_MD.read_text(encoding="utf-8")
    assert "v10.0.0" in txt, "README.md should mention v10.0.0"


def test_init_py_content():
    txt = INIT_PY.read_text(encoding="utf-8")
    assert "__version__ = '10.0.0'" in txt, "scripts/__init__.py missing __version__ = '10.0.0'"


def test_skill_md_line_count_under_450():
    """SKILL.md 行数硬约束 ≤ 450。"""
    line_count = len(SKILL_MD.read_text(encoding="utf-8").splitlines())
    assert line_count <= 450, (
        f"SKILL.md has {line_count} lines (limit 450). "
        "v10 detail content should move to README.md."
    )


def test_v10_modules_importable():
    """v10.0.0 新增模块均可独立 import。"""
    from scripts.crawler_dispatcher import (  # noqa: F401
        CrawlerDispatcher, DispatchConfig, ScraperRegistry,
    )
    from scripts.web_operations_enhanced import (  # noqa: F401
        ShadowDOMPiercer, CookieBannerHandler,
        HumanBehaviorSimulator, WebSocketRecorder,
    )
    from scripts.mcp_data_expansion import (  # noqa: F401
        QueryCache, TushareAdapter, CoinGeckoAdapter,
        ExchangeRateAdapter, ExpansionAdapterSet,
    )
    from scripts.mcp_resources_prompts import (  # noqa: F401
        register_resources_and_prompts, RESOURCE_REGISTRY, PROMPT_REGISTRY,
    )


def test_resource_count_is_8():
    from scripts.mcp_resources_prompts import RESOURCE_REGISTRY
    assert len(RESOURCE_REGISTRY) == 8, f"Expected 8 resources, got {len(RESOURCE_REGISTRY)}"


def test_prompt_count_is_10():
    from scripts.mcp_resources_prompts import PROMPT_REGISTRY
    assert len(PROMPT_REGISTRY) == 10, f"Expected 10 prompts, got {len(PROMPT_REGISTRY)}"


if __name__ == "__main__":
    import unittest
    unittest.main()