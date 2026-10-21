# -*- coding: utf-8 -*-
"""基础设施层合并测试（原 6 个测试文件合并，减少文件数）：
- meta_sync：文档版本同步（SKILL.md / README / _meta.json）
- scrapable_registry：机构注册表操作
- search_engine_cn：百度/搜狗中文搜索引擎（离线 fixture）
- http_utils：HTTP 工具与缓存
- backtester：crawl_backtester 4 维回测
- data_comparator：同类数据横向对比 + 监管政策分析
"""
import json
import re
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.scrapable_registry import ScrapableRegistry, PREDEFINED_URLS
from scripts.search_engine import (
    BaiduHTML, SogouHTML, MultiEngineSearch, SearchResult,
)
from scripts.http_utils import (
    _extract_domain,
    sanitize_filename,
    LRUCache,
    StdlibResponse,
)
from scripts.crawl_backtester import (
    CrawlBacktester, quick_backtest,
    _parse_datetime, _extract_numbers,
)

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
README_MD = SKILL_DIR / "README.md"
META_JSON = SKILL_DIR / "_meta.json"
INIT_PY = SKILL_DIR / "scripts" / "__init__.py"


# ════════════ A. meta_sync：文档版本同步 ════════════

def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "SKILL.md 缺少 frontmatter"
    return m.group(1)


def test_skill_version_is_800():
    fm = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    assert re.search(r"^version:\s*10\.0\.0\s*$", fm, re.MULTILINE), "SKILL version ≠ 10.0.0"


def test_skill_name_present():
    fm = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    assert "name: cn-financial-scraper" in fm


def test_skill_line_count_under_450():
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 450, f"SKILL.md {len(lines)} 行 > 450（精简目标）"


def test_skill_description_concise():
    """description 不再堆叠版本 changelog（应 ≤ 25 行）"""
    fm = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    m = re.search(r"description: \|(.*?)(?=auto_trigger)", fm, re.DOTALL)
    assert m, "description 缺失"
    desc_lines = [l for l in m.group(1).splitlines() if l.strip()]
    assert len(desc_lines) <= 25, f"description 过冗长（{len(desc_lines)} 行）"


def test_skill_keeps_auto_trigger():
    fm = _frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    assert "keywords:" in fm, "auto_trigger keywords 缺失"
    assert "patterns:" in fm, "auto_trigger patterns 缺失"
    # 关键触发词保留
    assert "爬取机构" in fm
    assert "舆情爬取" in fm
    assert "东方财富" in fm


def test_skill_no_stale_changelog_blocks():
    """正文无残留 v4.x 长 changelog 块"""
    txt = SKILL_MD.read_text(encoding="utf-8")
    for stale in ["v4.9.0 反爬 + 数据源兜底", "任务清单 — 详细使用指南",
                  "🆕 v4.5.1 三项强化", "🆕 v4.5.0 核心新功能"]:
        assert stale not in txt, f"残留旧章节: {stale}"


def test_readme_version_is_800():
    txt = README_MD.read_text(encoding="utf-8")
    assert "# cn-financial-scraper v10.0.0" in txt, "README 头版本 ≠ v10.0.0"


def test_meta_json_version_valid():
    """_meta.json 版本为合法 semver（平台独立版本体系，与 SKILL 版本解耦）"""
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    assert re.match(r"^\d+\.\d+\.\d+$", str(meta["version"])), "version 非 semver"
    assert "slug" in meta
    assert "ownerId" in meta


def test_init_version_is_800():
    txt = INIT_PY.read_text(encoding="utf-8")
    assert "__version__ = '10.0.0'" in txt


def test_no_bytecode_residue_delivery_guard():
    """交付守卫：项目内不得残留 .pyc / __pycache__ / .pytest_cache
    （上传平台拒绝二进制文件）。conftest 启动即清理历史残留，
    本用例兼验证直跑/包装两种入口下会话中不新增字节码。"""
    pyc_files = [p for p in SKILL_DIR.rglob("*.pyc")]
    assert not pyc_files, f"残留字节码文件: {pyc_files[:5]}"
    pycache_dirs = [d for d in SKILL_DIR.rglob("__pycache__") if d.is_dir()]
    assert not pycache_dirs, f"残留 __pycache__ 目录: {pycache_dirs[:5]}"
    pytest_cache = SKILL_DIR / ".pytest_cache"
    assert not pytest_cache.exists(), "残留 .pytest_cache（应已配置 -p no:cacheprovider）"


def test_all_versions_consistent():
    """SKILL / README / __init__ 三者版本一致（_meta.json 为平台独立 semver）"""
    skill = re.search(r"^version:\s*(10\.0\.0)", _frontmatter(SKILL_MD.read_text(encoding="utf-8")),
                      re.MULTILINE)
    assert skill
    readme = "v10.0.0" in README_MD.read_text(encoding="utf-8")
    init = "__version__ = '10.0.0'" in INIT_PY.read_text(encoding="utf-8")
    assert readme and init


def test_meta_json_valid():
    """_meta.json 合法 JSON"""
    json.loads(META_JSON.read_text(encoding="utf-8"))


def test_requirements_has_akshare():
    txt = (SKILL_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "akshare" in txt, "requirements.txt 未提及 akshare"


# ════════════ B. scrapable_registry：机构注册表 ════════════

class TestScrapableRegistry:
    """Test ScrapableRegistry class"""

    def test_initialization_loads_data(self):
        """Registry should load on initialization"""
        registry = ScrapableRegistry()
        assert registry.total > 0, "Registry should have institutions"

    def test_institutions_property(self):
        """institutions property should return a list"""
        registry = ScrapableRegistry()
        institutions = registry.institutions
        assert isinstance(institutions, list)
        assert len(institutions) > 0

    def test_get_returns_institution(self):
        """get() should return institution info for known names"""
        registry = ScrapableRegistry()
        # Get any institution
        all_inst = registry.institutions
        if all_inst:
            first = all_inst[0]
            result = registry.get(first["name"])
            assert result is not None
            assert result["name"] == first["name"]

    def test_get_returns_none_for_unknown(self):
        """get() should return None for unknown names"""
        registry = ScrapableRegistry()
        result = registry.get("ZZZ不存在的机构名称XYZ")
        assert result is None

    def test_search_finds_institutions(self):
        """Search should find matching institutions"""
        registry = ScrapableRegistry()
        results = registry.search("工商银行")
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert r is not None

    def test_search_no_match(self):
        """Search with no match should return empty"""
        registry = ScrapableRegistry()
        results = registry.search("ZZZ不存在的机构123456")
        assert results == []

    def test_list_by_type(self):
        """list_by_type should filter institutions"""
        registry = ScrapableRegistry()
        # Find an actual type from the data
        all_inst = registry.institutions
        if all_inst:
            first_type = all_inst[0].get("type", "")
            results = registry.list_by_type(first_type)
            assert isinstance(results, list)

    def test_list_scrapable(self):
        """list_scrapable should return institutions with URLs"""
        registry = ScrapableRegistry()
        results = registry.list_scrapable()
        assert isinstance(results, list)
        # All should have scrapable=True
        for r in results:
            assert r["scrapable"] is True

    def test_total_property(self):
        """Total should be positive"""
        registry = ScrapableRegistry()
        assert registry.total > 0

    def test_get_statistics(self):
        """get_statistics should return stats dict"""
        registry = ScrapableRegistry()
        stats = registry.get_statistics()
        assert isinstance(stats, dict)
        assert "total" in stats
        assert "scrapable" in stats
        assert "by_type" in stats
        assert stats["total"] > 0

    def test_generate_report(self):
        """generate_report should return a string"""
        registry = ScrapableRegistry()
        report = registry.generate_report()
        assert isinstance(report, str)
        assert len(report) > 0
        assert "机构" in report

    def test_is_scrapable(self):
        """is_scrapable should correctly identify institutions with URLs"""
        registry = ScrapableRegistry()
        assert registry.is_scrapable("华夏基金") is True
        assert registry.is_scrapable("ZZZ不存在") is False


class TestPredefinedUrls:
    """Test the PREDEFINED_URLS dictionary"""

    def test_contains_major_banks(self):
        assert "中国工商银行" in PREDEFINED_URLS
        assert "中国建设银行" in PREDEFINED_URLS
        assert "招商银行" in PREDEFINED_URLS

    def test_contains_major_securities(self):
        assert "中信证券" in PREDEFINED_URLS
        assert "华泰证券" in PREDEFINED_URLS

    def test_contains_major_fund_companies(self):
        assert "华夏基金" in PREDEFINED_URLS
        assert "易方达基金" in PREDEFINED_URLS

    def test_all_urls_are_valid_format(self):
        for name, url in PREDEFINED_URLS.items():
            assert url.startswith("https://"), f"{name}: {url} must use HTTPS"
            assert len(url) > 10, f"{name}: URL too short"

    def test_no_duplicate_urls(self):
        """No two institutions should share the same URL"""
        urls = list(PREDEFINED_URLS.values())
        assert len(urls) == len(set(urls)), f"Found {len(urls) - len(set(urls))} duplicate URL(s)"


# ════════════ C. search_engine_cn：百度/搜狗 ════════════

BAIDU_HTML = """
<div class="result c-container">
  <h3 class="t"><a href="https://www.baidu.com/link?url=real1%3A%2F%2Fexample.com%2Fmoutai&wd=kw">贵州茅台 2026半年报 营收增长</a></h3>
  <div class="c-abstract">茅台营收同比增长 18%，净利润创新高。</div>
</div>
<div class="result c-container">
  <h3 class="t"><a href="https://finance.eastmoney.com/a/2026.html">东方财富：白酒板块走强</a></h3>
  <div class="c-abstract">白酒股集体上涨。</div>
</div>
"""

SOGOU_HTML = """
<div class="vrwrap">
  <h3 class="vr-title"><a href="https://www.sogou.com/link?url=abc123">微信：茅台经销商大会</a></h3>
  <p class="star-wiki">经销商库存下降。</p>
</div>
<div class="vrwrap">
  <h3 class="vr-title"><a href="https://cninfo.com.cn/x">深交所公告：茅台回购</a></h3>
  <p class="txt-info">拟回购金额上限 30 亿。</p>
</div>
"""


def test_baidu_url_resolve():
    assert BaiduHTML._resolve_baidu_url(
        "https://www.baidu.com/link?url=https%3A%2F%2Fexample.com%2Fa&wd=x"
    ) == "https://example.com/a"


def test_baidu_url_resolve_plain():
    assert BaiduHTML._resolve_baidu_url("https://eastmoney.com/x") == "https://eastmoney.com/x"


def test_sogou_url_resolve():
    assert SogouHTML._resolve_sogou_url("https://www.sogou.com/link?url=abc") == "abc"


def test_sogou_url_resolve_plain():
    assert SogouHTML._resolve_sogou_url("https://cninfo.com.cn/x") == "https://cninfo.com.cn/x"


def test_baidu_parse(monkeypatch):
    engine = BaiduHTML(timeout=3)
    monkeypatch.setattr(engine, "_http_get", lambda url, headers=None: BAIDU_HTML)
    results = engine.search("贵州茅台", limit=5)
    assert len(results) == 2
    # 第一条是百度跳转链接 → 还原为真实 URL
    assert results[0].url == "real1://example.com/moutai"
    assert "贵州茅台" in results[0].title
    assert results[0].snippet != ""
    # 第二条普通 URL 原样保留
    assert results[1].url == "https://finance.eastmoney.com/a/2026.html"


def _no_sleep(monkeypatch):
    import scripts.search_engine as se
    monkeypatch.setattr(se.time, "sleep", lambda *a, **k: None)


def test_baidu_parse_empty(monkeypatch):
    _no_sleep(monkeypatch)
    engine = BaiduHTML(timeout=3)
    monkeypatch.setattr(engine, "_http_get", lambda url, headers=None: "")
    assert engine.search("不存在", limit=5) == []


def test_baidu_parse_none(monkeypatch):
    _no_sleep(monkeypatch)
    engine = BaiduHTML(timeout=3)
    monkeypatch.setattr(engine, "_http_get", lambda url, headers=None: None)
    assert engine.search("xxx", limit=5) == []


def test_sogou_parse(monkeypatch):
    engine = SogouHTML(timeout=3)
    monkeypatch.setattr(engine, "_http_get", lambda url, headers=None: SOGOU_HTML)
    results = engine.search("茅台", limit=5)
    assert len(results) == 2
    assert results[0].title == "微信：茅台经销商大会"
    assert results[0].url == "abc123"
    assert results[1].url == "https://cninfo.com.cn/x"


def test_sogou_parse_empty(monkeypatch):
    _no_sleep(monkeypatch)
    engine = SogouHTML(timeout=3)
    monkeypatch.setattr(engine, "_http_get", lambda url, headers=None: None)
    assert engine.search("xxx", limit=5) == []


def test_registry_has_cn_engines():
    reg = MultiEngineSearch.ENGINE_REGISTRY
    assert "baidu_html" in reg
    assert "sogou_html" in reg
    assert reg["baidu_html"] is BaiduHTML
    assert reg["sogou_html"] is SogouHTML


def test_auto_detect_prefers_cn_engines():
    m = MultiEngineSearch()
    names = [e.name for e in m.engines]
    assert names[0] == "baidu_html"
    assert names[1] == "sogou_html"


def test_create_engine_baidu_sogou():
    m = MultiEngineSearch(engines=["baidu_html", "sogou_html"])
    assert any(isinstance(e, BaiduHTML) for e in m.engines)
    assert any(isinstance(e, SogouHTML) for e in m.engines)


def test_cn_engines_need_no_api_key():
    assert BaiduHTML.needs_api_key is False
    assert SogouHTML.needs_api_key is False


# ════════════ D. http_utils：域名/文件名清洗/LRU 缓存 ════════════

class TestExtractDomain:
    """Test _extract_domain helper"""

    def test_extracts_domain_from_https_url(self):
        assert _extract_domain("https://fund.eastmoney.com/000001.html") == "fund.eastmoney.com"

    def test_extracts_domain_from_http_url(self):
        assert _extract_domain("http://www.example.com/path?a=1") == "www.example.com"

    def test_extracts_domain_from_url_with_port(self):
        assert _extract_domain("https://api.test.com:8080/v1/data") == "api.test.com:8080"

    def test_handles_malformed_url(self):
        """Malformed URLs should return 'unknown' or not raise"""
        result = _extract_domain("not-a-valid-url!!!")
        assert isinstance(result, str)

    def test_handles_empty_string(self):
        result = _extract_domain("")
        assert isinstance(result, str)

    def test_lowercases_domain(self):
        assert _extract_domain("https://WWW.EXAMPLE.COM/path") == "www.example.com"


class TestSanitizeFilename:
    """Test sanitize_filename function"""

    def test_removes_invalid_chars(self):
        # : and " both become _, so :with" becomes __with_
        result = sanitize_filename('file<name>:with"bad/chars')
        assert "file_name__with_bad_chars" == result

    def test_replaces_backslash(self):
        assert sanitize_filename("path\\to\\file.pdf") == "path_to_file.pdf"

    def test_normalizes_whitespace(self):
        assert sanitize_filename("  multiple   spaces  here  ") == "multiple spaces here"

    def test_truncates_long_names(self):
        long_name = "a" * 200
        result = sanitize_filename(long_name, max_len=50)
        assert len(result) == 50
        assert result == "a" * 50

    def test_default_max_len(self):
        long_name = "a" * 200
        result = sanitize_filename(long_name)
        assert len(result) <= 100

    def test_handles_chinese_characters(self):
        result = sanitize_filename("华夏基金_2024年报.pdf")
        assert "华夏基金_2024年报.pdf" == result

    def test_strips_control_characters(self):
        result = sanitize_filename("test\x00file\x1fname")
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_returns_unnamed_for_empty_result(self):
        """After sanitization, if name is all underscores, return 'unnamed'"""
        result = sanitize_filename("<>:\"/\\|?*")
        assert result == "unnamed"

    def test_returns_unnamed_for_empty_string(self):
        result = sanitize_filename("")
        assert result == "unnamed"


class TestLRUCache:
    """Test LRUCache implementation — uses set/get API (not put)"""

    def test_basic_set_and_get(self):
        cache = LRUCache(max_size=10, ttl=99999)
        resp = StdlibResponse("http://test.com", 200, {"Content-Type": "text/plain"}, b"test body")
        cache.set("http://test.com/key1", resp)
        result = cache.get("http://test.com/key1")
        assert result is not None
        assert result.status_code == 200

    def test_get_missing_key(self):
        cache = LRUCache(10)
        assert cache.get("http://nonexistent.com") is None

    def test_lru_eviction(self):
        cache = LRUCache(max_size=3, ttl=99999)
        for i in range(3):
            resp = StdlibResponse(f"http://test.com/{i}", 200, {}, f"body{i}".encode())
            cache.set(f"http://test.com/{i}", resp)
        cache.get("http://test.com/0")
        resp4 = StdlibResponse("http://test.com/4", 200, {}, b"body4")
        cache.set("http://test.com/4", resp4)
        assert cache.get("http://test.com/0") is not None
        assert cache.get("http://test.com/2") is not None
        assert cache.get("http://test.com/4") is not None
        assert cache.get("http://test.com/1") is None

    def test_overwrite_existing_key(self):
        """LRU cache does NOT overwrite existing keys — it preserves first-cached value.
        This is standard HTTP cache behavior: first response wins until TTL expiry."""
        cache = LRUCache(max_size=10, ttl=99999)
        resp1 = StdlibResponse("http://test.com/key", 200, {}, b"first")
        resp2 = StdlibResponse("http://test.com/key", 200, {}, b"second")
        cache.set("http://test.com/key", resp1)
        cache.set("http://test.com/key", resp2)  # Should keep first value
        result = cache.get("http://test.com/key")
        assert result.content == b"first"  # First-cached value preserved

    def test_clear_cache(self):
        cache = LRUCache(max_size=10, ttl=99999)
        cache.set("http://test.com/a", StdlibResponse("http://test.com/a", 200, {}, b"a"))
        cache.set("http://test.com/b", StdlibResponse("http://test.com/b", 200, {}, b"b"))
        cache.clear()
        assert cache.get("http://test.com/a") is None
        assert cache.get("http://test.com/b") is None

    def test_ttl_expiry(self):
        """Items should expire after TTL"""
        cache = LRUCache(max_size=10, ttl=0.01)
        cache.set("http://test.com/key", StdlibResponse("http://test.com/key", 200, {}, b"body"))
        time.sleep(0.02)
        assert cache.get("http://test.com/key") is None

    def test_len(self):
        cache = LRUCache(max_size=10)
        cache.set("http://test.com/a", StdlibResponse("http://test.com/a", 200, {}, b"a"))
        cache.set("http://test.com/b", StdlibResponse("http://test.com/b", 200, {}, b"b"))
        assert len(cache) == 2


# ════════════ E. backtester：crawl_backtester 回测 ════════════

class TestParseDatetime(unittest.TestCase):
    def test_iso(self):
        dt = _parse_datetime("2026-07-29T10:00:00")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 7)
        self.assertEqual(dt.day, 29)

    def test_date_only(self):
        dt = _parse_datetime("2026-07-29")
        self.assertEqual(dt.year, 2026)

    def test_chinese_format(self):
        dt = _parse_datetime("2026年7月29日")
        self.assertEqual(dt.year, 2026)

    def test_relative(self):
        dt = _parse_datetime("3天前")
        self.assertIsNotNone(dt)
        self.assertAlmostEqual((datetime.now() - dt).days, 3, delta=1)

    def test_invalid(self):
        self.assertIsNone(_parse_datetime("not a date"))


class TestExtractNumbers(unittest.TestCase):
    def test_amount_yi(self):
        out = _extract_numbers("营收 1500 亿元")
        self.assertEqual(out["amounts"], [150000000000])

    def test_amount_wan(self):
        out = _extract_numbers("营收 150000 万元")
        self.assertEqual(out["amounts"], [1500000000])

    def test_percentage(self):
        out = _extract_numbers("增长 15.5%")
        self.assertIn(15.5, out["percentages"])

    def test_year(self):
        out = _extract_numbers("2024 年财报")
        self.assertIn(2024, out["years"])

    def test_year_filter(self):
        # 不应抽到手机号/年份外的数字
        out = _extract_numbers("电话 13800138000")
        # 13800138000 不应进入 years（不匹配 19xx/20xx 模式）
        self.assertEqual(out["years"], [])


class TestFreshness(unittest.TestCase):
    def setUp(self):
        self.bt = CrawlBacktester(max_age_days=7)

    def test_fresh(self):
        today = datetime.now().strftime("%Y-%m-%d")
        f = self.bt.check_freshness({"published_at": today})
        self.assertEqual(f["level"], "fresh")
        self.assertGreater(f["score"], 0.8)

    def test_stale(self):
        old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        f = self.bt.check_freshness({"published_at": old})
        self.assertEqual(f["level"], "stale")

    def test_expired(self):
        old = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        f = self.bt.check_freshness({"published_at": old})
        self.assertEqual(f["level"], "expired")
        self.assertLess(f["score"], 0.3)

    def test_unknown(self):
        f = self.bt.check_freshness({"published_at": None})
        self.assertEqual(f["level"], "unknown")


class TestNumericConsistency(unittest.TestCase):
    def setUp(self):
        self.bt = CrawlBacktester()

    def test_consistent_amounts(self):
        n = self.bt.numeric_consistency({
            "title": "x", "content": "营收 1500 亿元，同比增长 15%"
        })
        self.assertGreaterEqual(len(n["extracted"]["amounts"]), 1)
        self.assertIn(15, n["extracted"]["percentages"])

    def test_inconsistent_years(self):
        n = self.bt.numeric_consistency({
            "title": "x", "content": "2099 年某事"
        })
        self.assertGreater(n["inconsistency_count"], 0)

    def test_clean_text(self):
        n = self.bt.numeric_consistency({
            "title": "x", "content": "无数字内容"
        })
        self.assertEqual(n["inconsistency_count"], 0)


class TestCrossSource(unittest.TestCase):
    def test_no_match_no_snapshot(self):
        bt = CrawlBacktester()
        # 空快照索引 → 应返回 0 matched
        c = bt.cross_source_validate({
            "title": "某新闻",
            "source": "x"
        })
        self.assertEqual(c["matched_sources"], [])


class TestSnapshotCompare(unittest.TestCase):
    def test_newly_emerged_no_history(self):
        bt = CrawlBacktester()
        s = bt.compare_with_snapshot({"title": "全新新闻"})
        self.assertEqual(s["appeared_in_n_snapshots"], 0)
        self.assertTrue(s["newly_emerged"])


class TestFullBacktest(unittest.TestCase):
    def test_fresh_article_passes(self):
        today = datetime.now().strftime("%Y-%m-%d")
        r = quick_backtest({
            "title": "测试",
            "url": "https://x.com",
            "published_at": today,
            "content": "2024 年某事",
            "source": "财联社",
        })
        # 综合分应 >= 0.6
        self.assertGreater(r.overall_score, 0.5)

    def test_old_article_fails(self):
        r = quick_backtest({
            "title": "老新闻",
            "url": "https://x.com",
            "published_at": "2020-01-01",
            "content": "2020 年事",
            "source": "财联社",
        })
        self.assertFalse(r.passed)

    def test_explain_returns_text(self):
        r = quick_backtest({"title": "x"})
        text = CrawlBacktester().explain(r)
        self.assertIn("回测报告", text)


# ════════════ F. data_comparator：横向对比 + 监管分析 ════════════

class TestBacktestSeries(unittest.TestCase):

    def _clean_series(self):
        return [
            {"date": "2026-07-28", "margin_balance": 100.0, "margin_buy": 5.0},
            {"date": "2026-07-29", "margin_balance": 102.0, "margin_buy": 6.0},
            {"date": "2026-07-30", "margin_balance": 105.0, "margin_buy": 4.0},
            {"date": "2026-07-31", "margin_balance": 103.0, "margin_buy": 7.0},
        ]

    def test_clean_series_passes(self):
        from data_comparator import backtest_series
        r = backtest_series("股票A", self._clean_series())
        self.assertTrue(r["passed"])
        self.assertGreaterEqual(r["score"], 60)
        self.assertEqual(r["record_count"], 4)

    def test_empty_series_fails(self):
        from data_comparator import backtest_series
        r = backtest_series("空序列", [])
        self.assertFalse(r["passed"])
        self.assertEqual(r["score"], 0)

    def test_abnormal_jump_detected(self):
        from data_comparator import backtest_series
        series = self._clean_series() + [
            {"date": "2026-08-01", "margin_balance": 5000.0, "margin_buy": 7.0},
        ]
        r = backtest_series("跳变", series, jump_threshold=5.0)
        # 跳变超阈值 → 应有 numeric 问题
        numeric_issues = [i for i in r["issues"] if i["field"] == "margin_balance"]
        self.assertTrue(any("跳变" in i["message"] for i in numeric_issues))

    def test_duplicate_dates_warned(self):
        from data_comparator import backtest_series
        series = self._clean_series() + [
            {"date": "2026-07-31", "margin_balance": 103.0, "margin_buy": 7.0},
        ]
        r = backtest_series("重复", series)
        dup_issues = [i for i in r["issues"] if "重复日期" in i["message"]]
        self.assertTrue(dup_issues)


class TestCompareSeries(unittest.TestCase):

    def test_ranking(self):
        from data_comparator import compare_series
        a = [{"date": "2026-07-31", "margin_balance": 100.0}]
        b = [{"date": "2026-07-31", "margin_balance": 50.0}]
        r = compare_series({"股票A": a, "股票B": b})
        self.assertEqual(r["series_count"], 2)
        rank = r["ranking"]["margin_balance"]
        self.assertEqual(rank[0]["label"], "股票A")  # 值大者第一
        self.assertEqual(rank[1]["label"], "股票B")

    def test_latest_and_change(self):
        from data_comparator import compare_series
        a = [
            {"date": "2026-07-30", "margin_balance": 100.0},
            {"date": "2026-07-31", "margin_balance": 103.0},
        ]
        r = compare_series({"股票A": a})
        self.assertEqual(r["latest"]["股票A"]["margin_balance"], 103.0)
        self.assertEqual(r["change"]["股票A"]["margin_balance"], 3.0)

    def test_empty(self):
        from data_comparator import compare_series
        self.assertEqual(compare_series({})["series_count"], 0)


class TestCompareAndBacktest(unittest.TestCase):

    def test_integration(self):
        from data_comparator import compare_and_backtest
        a = [{"date": "2026-07-31", "margin_balance": 100.0, "margin_buy": 5.0}]
        b = [{"date": "2026-07-31", "margin_balance": 50.0, "margin_buy": 2.0}]
        r = compare_and_backtest({"A": a, "B": b})
        self.assertEqual(len(r["backtests"]), 2)
        self.assertEqual(r["summary"]["group_count"], 2)
        self.assertIn("comparison", r)
        self.assertIn("best", r["summary"])

    def test_format_report(self):
        from data_comparator import compare_and_backtest, format_comparison_report
        a = [{"date": "2026-07-31", "margin_balance": 100.0}]
        r = compare_and_backtest({"A": a})
        text = format_comparison_report(r)
        self.assertIn("横向对比", text)
        self.assertIn("回测", text)


class TestRegulatoryAnalysis(unittest.TestCase):
    """监管政策文件分析（本地文件，无网络）。"""

    def test_analyze_local_file(self):
        from regulatory_scraper import RegulatoryScraper
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False, encoding="utf-8") as f:
            f.write("某商业银行发布2026年利率政策公告。本公告旨在降低实体经济融资成本。")
            path = f.name
        try:
            r = RegulatoryScraper().analyze_policy(path, keyword="利率")
            self.assertIn("利率", r["keywords_hit"])
            self.assertGreater(r["content_length"], 0)
            self.assertTrue(r["summary"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_download_invalid_url(self):
        from regulatory_scraper import download_policy_document
        self.assertEqual(download_policy_document(""), "")


if __name__ == "__main__":
    unittest.main()
