# -*- coding: utf-8 -*-
"""浏览器层合并测试（原 4 个测试文件合并，减少文件数）：
- browser_paginate：增强方法 + PageOperator 扩展（纯函数，无 IO）
- browser_fixes：v4.7 类人爬取加固（STEALTH_JS / humanlike_fetch / 资源泄漏）
- browser_enhancements：v5.0 广告拦截 / proxy / 重试 / 单例（离线 mock）
- humanlike：类人操作方法挂载与向后兼容（不依赖 Playwright）
完整 E2E 测试请在 playwright 环境运行。
"""
import inspect
import unittest

import pytest

# 注意：scripts/ 同时在 sys.path 上，`scripts.browser_scraper` 与 `browser_scraper`
# 会各自加载一份模块。本文件统一以 scripts 副本为唯一来源（别名回旧名），
# 否则 monkeypatch 补丁可能打不到被测函数/类所在的模块。
import scripts.browser_scraper as bs_mod
browser_scraper = bs_mod
from scripts.browser_scraper import (
    BrowserScraper,
    _strip_dynamic_markers, _guess_image_ext,
    _should_block_url, _get_browser_scraper, release_browser,
    AD_BLOCK_DOMAINS,
)


# ════════════ A. browser_paginate：增强方法 + PageOperator ════════════

class TestStripDynamic(unittest.TestCase):
    def test_strips_scripts(self):
        html = "<div>x<script>alert(1)</script></div>"
        out = _strip_dynamic_markers(html)
        self.assertNotIn("alert", out)

    def test_strips_timestamp_10_13(self):
        html = "<p>Published at 1700000000</p>"
        out = _strip_dynamic_markers(html)
        self.assertNotIn("1700000000", out)
        self.assertIn("TS", out)

    def test_strips_iso_datetime(self):
        html = "<p>2026-07-29T10:00:00</p>"
        out = _strip_dynamic_markers(html)
        self.assertNotIn("2026-07-29T10:00:00", out)

    def test_keeps_normal_content(self):
        html = "<p>Static content 123</p>"
        out = _strip_dynamic_markers(html)
        self.assertIn("Static content", out)


class TestGuessImageExt(unittest.TestCase):
    def test_jpg(self):
        self.assertEqual(_guess_image_ext("https://x.com/a.jpg"), ".jpg")

    def test_jpeg(self):
        self.assertEqual(_guess_image_ext("https://x.com/a.jpeg"), ".jpg")

    def test_png(self):
        self.assertEqual(_guess_image_ext("https://x.com/path/b.png"), ".png")

    def test_webp(self):
        self.assertEqual(_guess_image_ext("https://x.com/x.webp?v=1"), ".webp")

    def test_default(self):
        self.assertEqual(_guess_image_ext("https://x.com/noext"), ".jpg")


class TestBrowserMethodsExist(unittest.TestCase):
    """检查所有新方法都已挂载到 BrowserScraper 类。"""

    def test_all_methods_mounted(self):
        for name in ("paginate", "extract_links", "follow_links",
                     "download_images", "capture_canvas", "fetch_full_article"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(BrowserScraper, name),
                                f"BrowserScraper.{name} 未挂载")


class TestPageOperatorMethodsExist(unittest.TestCase):
    """检查 PageOperator 已扩展三个方法。"""

    def test_all_methods_exist(self):
        from scripts.web_parser import PageOperator
        for name in ("paginate", "extract_all_links", "follow_links"):
            with self.subTest(method=name):
                self.assertTrue(hasattr(PageOperator, name),
                                f"PageOperator.{name} 未实现")


# ════════════ B. browser_fixes：v4.7 类人爬取加固 ════════════

class TestStealthJsContent(unittest.TestCase):
    """STEALTH_JS 应覆盖主要反检测指纹。"""

    @classmethod
    def setUpClass(cls):
        cls.js = browser_scraper.STEALTH_JS

    def test_webdriver_hidden(self):
        self.assertIn("navigator", self.js)
        self.assertIn("webdriver", self.js)

    def test_plugins_spoof(self):
        self.assertIn("PluginArray", self.js)
        self.assertIn("namedItem", self.js)

    def test_languages_platform(self):
        self.assertIn("languages", self.js)
        self.assertIn("platform", self.js)

    def test_hardware_fingerprints(self):
        self.assertIn("hardwareConcurrency", self.js)
        self.assertIn("deviceMemory", self.js)

    def test_permissions_api(self):
        self.assertIn("permissions.query", self.js)

    def test_chrome_runtime(self):
        self.assertIn("chrome.runtime", self.js)

    def test_webgl_spoof(self):
        self.assertIn("37445", self.js)  # UNMASKED_VENDOR_WEBGL
        self.assertIn("37446", self.js)  # UNMASKED_RENDERER_WEBGL

    def test_window_outer(self):
        self.assertIn("outerWidth", self.js)
        self.assertIn("outerHeight", self.js)

    def test_phantom_cleanup(self):
        self.assertIn("callPhantom", self.js)

    def test_min_fingerprint_count(self):
        """覆盖至少 10 个指纹项。"""
        markers = ["webdriver", "PluginArray", "languages", "platform",
                   "hardwareConcurrency", "deviceMemory", "permissions.query",
                   "chrome.runtime", "37445", "outerWidth", "connection.rtt",
                   "callPhantom"]
        hits = sum(1 for m in markers if m in self.js)
        self.assertGreaterEqual(hits, 10, f"STEALTH_JS 指纹覆盖不足: {hits}/12")


class TestHumanlikeFetchSignature(unittest.TestCase):
    """humanlike_fetch 应支持新参数。"""

    def test_new_params(self):
        sig = inspect.signature(browser_scraper.BrowserScraper.humanlike_fetch)
        for param in ("mouse_simulation", "input_selector", "input_text"):
            self.assertIn(param, sig.parameters, f"缺少参数 {param}")
        self.assertEqual(sig.parameters["mouse_simulation"].default, True)

    def test_body_uses_mouse_and_type(self):
        """humanlike_fetch 方法体应调用 _human_mouse_move 与 _human_type。"""
        src = inspect.getsource(browser_scraper.BrowserScraper.humanlike_fetch)
        self.assertIn("_human_mouse_move", src)
        self.assertIn("_human_type", src)

    def test_finally_closes_page(self):
        src = inspect.getsource(browser_scraper.BrowserScraper.humanlike_fetch)
        self.assertIn("finally", src)
        self.assertIn("page.close", src)


class TestResourceLeakFixes(unittest.TestCase):
    """fetch/extract_text 等应使用 try/finally 关闭 page。"""

    def _src_of(self, func_name):
        cls = browser_scraper.BrowserScraper
        return inspect.getsource(getattr(cls, func_name))

    def test_fetch_has_finally(self):
        src = self._src_of("fetch")
        self.assertIn("finally", src)
        self.assertIn("page.close", src)

    def test_extract_text_has_finally(self):
        src = self._src_of("extract_text")
        self.assertIn("finally", src)
        self.assertIn("page.close", src)

    def test_extract_multiple_has_finally(self):
        src = self._src_of("extract_multiple")
        self.assertIn("finally", src)

    def test_extract_table_has_finally(self):
        src = self._src_of("extract_table")
        self.assertIn("finally", src)


class TestFetchRetry(unittest.TestCase):
    """fetch 应支持 retries 参数。"""

    def test_retries_param(self):
        sig = inspect.signature(browser_scraper.BrowserScraper.fetch)
        self.assertIn("retries", sig.parameters)
        self.assertEqual(sig.parameters["retries"].default, 2)


# ════════════ C. browser_enhancements：v5.0 广告拦截/代理/重试/单例 ════════════

def test_should_block_ad_image():
    assert _should_block_url("https://ad.doubleclick.net/banner.jpg", "image") is True


def test_should_block_baidu_track():
    assert _should_block_url("https://hm.baidu.com/hm.js?x=1", "script") is False  # script 不拦
    assert _should_block_url("https://hm.baidu.com/hm.js?x=1", "image") is True


def test_should_block_not_block_regular():
    assert _should_block_url("https://eastmoney.com/pic.png", "image") is False
    assert _should_block_url("https://example.com/article.html", "document") is False


def test_should_block_small_resources_kept():
    # 非 image/media/font 类型（脚本/样式）不拦截，避免破坏页面
    assert _should_block_url("https://doubleclick.net/x.js", "script") is False
    assert _should_block_url("https://doubleclick.net/x.css", "stylesheet") is False


def test_ad_block_domains_nonempty():
    assert len(AD_BLOCK_DOMAINS) >= 8


def test_resolve_proxy_string():
    assert BrowserScraper._resolve_proxy("http://127.0.0.1:8080") == {"server": "http://127.0.0.1:8080"}


def test_resolve_proxy_socks():
    assert BrowserScraper._resolve_proxy("socks5://1.2.3.4:1080") == {"server": "socks5://1.2.3.4:1080"}


def test_resolve_proxy_dict():
    assert BrowserScraper._resolve_proxy({"server": "http://x", "username": "u"}) == \
        {"server": "http://x", "username": "u"}


def test_init_accepts_new_params():
    if not bs_mod.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright 不可用")
    bs = BrowserScraper(headless=True, proxy="http://127.0.0.1:8080", ad_block=False, channel="chromium")
    assert bs.proxy == "http://127.0.0.1:8080"
    assert bs.ad_block is False
    assert bs.channel == "chromium"


def test_init_default_params():
    if not bs_mod.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright 不可用")
    bs = BrowserScraper(headless=True)
    assert bs.proxy is None
    assert bs.ad_block is True
    assert bs.channel == "chromium"


def test_extract_many_empty():
    bs = object.__new__(BrowserScraper)
    bs.timeout_ms = 30000
    assert bs.extract_many([]) == []


def test_extract_many_playwright_missing(monkeypatch):
    monkeypatch.setattr(bs_mod, "PLAYWRIGHT_AVAILABLE", False)
    bs = object.__new__(BrowserScraper)
    bs.timeout_ms = 30000
    out = bs.extract_many(["https://a.com/1", "https://b.com/2"])
    assert out == [("https://a.com/1", None), ("https://b.com/2", None)]


def test_with_retry_success():
    if not bs_mod.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright 不可用")
    bs = BrowserScraper(headless=True)
    assert bs._with_retry(lambda: 42, retries=2) == 42


def test_with_retry_failure(monkeypatch):
    if not bs_mod.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright 不可用")
    monkeypatch.setattr(bs_mod.time, "sleep", lambda *a, **k: None)
    bs = BrowserScraper(headless=True)

    def _boom():
        raise ValueError("x")

    assert bs._with_retry(_boom, retries=1) is None


def test_singleton_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(bs_mod, "PLAYWRIGHT_AVAILABLE", False)
    assert _get_browser_scraper(headless=True) is None


def test_release_browser_safe():
    release_browser()  # 不应抛异常


def test_singleton_idempotent_release(monkeypatch):
    """连续 release 幂等"""
    release_browser()
    release_browser()


def test_is_soft_blocked_detects_captcha():
    from scripts.sentiment_crawler import SentimentCrawler
    c = SentimentCrawler()
    html = "<html><body>访问频率过高，请稍后再试，请输入验证码</body></html>"
    assert c._is_soft_blocked(html) is True


def test_is_soft_blocked_false_for_normal():
    from scripts.sentiment_crawler import SentimentCrawler
    c = SentimentCrawler()
    assert c._is_soft_blocked("<html>正常新闻内容</html>") is False


def test_is_soft_blocked_empty():
    from scripts.sentiment_crawler import SentimentCrawler
    c = SentimentCrawler()
    assert c._is_soft_blocked("") is False


# ════════════ D. humanlike：类人操作方法挂载与兼容 ════════════

class TestHumanlikeMethodsExist(unittest.TestCase):
    """验证类人操作方法已挂载到 BrowserScraper 类。"""

    @classmethod
    def setUpClass(cls):
        cls.methods = [m for m in dir(BrowserScraper) if not m.startswith("__")]

    def test_human_mouse_move_exists(self):
        self.assertIn("_human_mouse_move", self.methods)

    def test_human_type_exists(self):
        self.assertIn("_human_type", self.methods)

    def test_human_dwell_exists(self):
        self.assertIn("_human_dwell", self.methods)

    def test_random_scroll_exists(self):
        self.assertIn("_random_scroll", self.methods)

    def test_random_viewport_exists(self):
        self.assertIn("_random_viewport", self.methods)

    def test_humanlike_fetch_exists(self):
        self.assertIn("humanlike_fetch", self.methods)

    def test_legacy_methods_still_present(self):
        """确保重构后原有方法仍然存在。"""
        legacy = ["fetch", "extract_text", "screenshot", "paginate",
                   "extract_links", "follow_links", "download_images",
                   "capture_canvas", "fetch_full_article", "smart_fetch"]
        for m in legacy:
            self.assertIn(m, self.methods, f"Missing legacy method: {m}")


class TestHumanlikeDesign(unittest.TestCase):
    """测试类人操作设计的合理性（参数验证等）。"""

    def test_humanlike_fetch_accepts_all_params(self):
        """验证 humanlike_fetch 接受预期参数。"""
        sig = inspect.signature(BrowserScraper.humanlike_fetch)
        params = list(sig.parameters.keys())
        self.assertIn("url", params)
        self.assertIn("scroll", params)
        self.assertIn("dwell", params)
        self.assertIn("random_viewport", params)

    def test_no_new_dependencies(self):
        """验证类人操作不引入新依赖（全部基于标准库 + Playwright）。"""
        from pathlib import Path as _Path
        source = _Path(browser_scraper.__file__).read_text(encoding="utf-8")
        # 确认不使用 AI/ML 库
        self.assertNotIn("import torch", source)
        self.assertNotIn("import tensorflow", source)
        self.assertNotIn("import opencv", source)
        self.assertNotIn("import cv2", source)
        self.assertNotIn("from PIL", source)
        self.assertNotIn("import selenium", source)


class TestBackwardCompatibility(unittest.TestCase):
    """确保增强后向后兼容。"""

    def test_original_fetch_still_works(self):
        """原始 fetch 方法签名不变。"""
        sig = inspect.signature(BrowserScraper.fetch)
        params = list(sig.parameters.keys())
        self.assertIn("url", params)
        # 仍支持 wait_until, wait_selector, scroll, dismiss_cookies
        self.assertIn("wait_until", params)
        self.assertIn("scroll", params)
        self.assertIn("dismiss_cookies", params)

    def test_extract_text_unchanged(self):
        """extract_text 方法签名不变。"""
        sig = inspect.signature(BrowserScraper.extract_text)
        params = list(sig.parameters.keys())
        self.assertIn("url", params)
        self.assertIn("selector", params)


if __name__ == "__main__":
    unittest.main()
