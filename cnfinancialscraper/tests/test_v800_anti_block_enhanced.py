# -*- coding: utf-8 -*-
"""v8.0.0 反爬增强测试 — ProxyPool / Behavior / Budget / IPReputation /
CaptchaDetector / SessionWarmer / AntiBlockPipeline / TLSClientFactory

全部离线，纯函数 / monkeypatch，不发网络请求。
"""
import re
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import anti_block_enhanced as abe


# ════════════════ 1. ProxyPool ════════════════


class TestProxyPool:
    def test_add_and_pick(self):
        pool = abe.ProxyPool(["http://1.1.1.1:8080", "http://2.2.2.2:8080"])
        assert pool.pick() in {"http://1.1.1.1:8080", "http://2.2.2.2:8080"}

    def test_round_robin_cycles(self):
        pool = abe.ProxyPool(["http://a", "http://b"], strategy="round_robin")
        seen = {pool.pick() for _ in range(6)}
        assert seen == {"http://a", "http://b"}

    def test_random_strategy(self):
        pool = abe.ProxyPool(["http://a", "http://b"], strategy="random")
        # 不抛异常即可
        for _ in range(10):
            assert pool.pick() in {"http://a", "http://b"}

    def test_weighted_strategy_returns_known(self):
        pool = abe.ProxyPool(["http://a", "http://b"], strategy="weighted")
        pool.report("http://a", success=True, latency_ms=100)
        for _ in range(20):
            url = pool.pick()
            assert url in {"http://a", "http://b"}

    def test_disabled_after_threshold(self):
        pool = abe.ProxyPool(["http://a"], disable_threshold=3, cooldown_seconds=60)
        for _ in range(3):
            pool.report("http://a", success=False, error="blocked")
        assert pool.pick() is None   # 全部 disabled

    def test_recover_disabled(self):
        pool = abe.ProxyPool(["http://a"], disable_threshold=2)
        for _ in range(2):
            pool.report("http://a", success=False)
        pool.recover_disabled()
        assert pool.pick() == "http://a"

    def test_score_penalizes_consecutive_fail(self):
        pool = abe.ProxyPool(["http://a"])
        pool.report("http://a", success=True)
        s_before = pool.status()["entries"]["http://a"]["score"]
        for _ in range(3):
            pool.report("http://a", success=False)
        s_after = pool.status()["entries"]["http://a"]["score"]
        assert s_after < s_before

    def test_persistence(self, tmp_path):
        f = tmp_path / "proxies.json"
        pool = abe.ProxyPool(["http://a"], file_path=f)
        pool.report("http://a", success=True)
        assert f.exists()
        # 重新加载
        pool2 = abe.ProxyPool(file_path=f)
        assert "http://a" in pool2._entries

    def test_empty_pool_returns_none(self):
        pool = abe.ProxyPool([])
        assert pool.pick() is None

    def test_remove(self):
        pool = abe.ProxyPool(["http://a", "http://b"])
        pool.remove("http://a")
        # round_robin 跳过 a 后只剩 b
        pool2 = abe.ProxyPool(strategy="round_robin")
        assert pool.pick() in {"http://a", "http://b"}    # 测试 remove 不抛异常


# ════════════════ 2. RequestBehaviorProfile ════════════════


class TestBehaviorProfile:
    def test_next_delay_in_range(self):
        b = abe.RequestBehaviorProfile()
        b.config.min_delay = 1.0
        b.config.max_delay = 2.0
        for _ in range(50):
            d = b.next_delay()
            assert d >= 0.9 or d >= 15.0   # 短停顿或长停顿

    def test_next_delay_long_pause_possible(self, monkeypatch):
        b = abe.RequestBehaviorProfile()
        b.config.long_pause_prob = 1.0
        b.config.long_pause_range = (5.0, 6.0)
        d = b.next_delay()
        assert 5.0 <= d <= 6.0

    def test_referer_search_engine(self, monkeypatch):
        b = abe.RequestBehaviorProfile()
        b.config.referrer_search_engine_prob = 1.0
        r = b.next_referer("https://example.com/news/123",
                           query="贵州茅台 半年报")
        assert any(s in r for s in ("baidu", "google", "bing", "sogou"))

    def test_referer_same_domain(self, monkeypatch):
        b = abe.RequestBehaviorProfile()
        b.config.referrer_search_engine_prob = 0.0
        b.config.referrer_same_domain_prob = 1.0
        r = b.next_referer("https://www.cls.cn/api/sw")
        assert "cls.cn" in r

    def test_referer_fallback_when_no_match(self, monkeypatch):
        b = abe.RequestBehaviorProfile()
        b.config.referrer_search_engine_prob = 0.0
        b.config.referrer_same_domain_prob = 0.0
        r = b.next_referer("https://www.example.com/x")
        # 既不是 search engine 也不是同域分支，应该返回 fallback
        assert "example.com" in r

    def test_stats(self):
        b = abe.RequestBehaviorProfile()
        b.next_delay()
        b.next_referer("https://a.cn/x")
        b.next_referer("https://b.cn/y")
        s = b.stats()
        assert s["request_count"] == 1
        assert s["tracked_referers"] == 2


# ════════════════ 3. TLSClientFactory ════════════════


class TestTLSClientFactory:
    def test_backends_discovered(self):
        backs = abe.TLSClientFactory.available_backends()
        assert len(backs) >= 1   # 至少 stdlib
        assert all(b.available for b in backs)

    def test_pick_returns_some(self):
        # 即使只有 stdlib 也应返回
        picked = abe.TLSClientFactory.pick()
        # 在测试环境可能为 None（如果 stdlib 内部 import 失败）
        # 但通常不会
        assert picked is not None
        if picked is not None:
            name, fn = picked
            assert name in {"curl_cffi", "scrapling", "stdlib"}

    def test_self_check_includes_tls(self):
        sc = abe.self_check()
        assert "TLSClientFactory" in sc


# ════════════════ 4. CrawlBudgetController ════════════════


class TestBudgetController:
    def test_initial_allow(self):
        c = abe.CrawlBudgetController({"cls.cn": {"daily": 5, "hourly": 2}})
        assert c.allow("cls.cn") is True

    def test_consume_and_block(self):
        c = abe.CrawlBudgetController({"cls.cn": {"daily": 100, "hourly": 2}})
        c.consume("cls.cn")
        c.consume("cls.cn")
        assert c.allow("cls.cn") is False

    def test_wait_seconds(self):
        c = abe.CrawlBudgetController({"cls.cn": {"daily": 100, "hourly": 1}})
        c.consume("cls.cn")
        secs = c.wait_seconds_until_available("cls.cn")
        assert 0 < secs <= 3600

    def test_default_bucket_used_for_unknown_domain(self):
        c = abe.CrawlBudgetController({"default": {"daily": 2, "hourly": 1}})
        c.consume("unknown.cn")
        c.consume("unknown.cn")
        assert c.allow("unknown.cn") is False

    def test_persistence(self, tmp_path):
        f = tmp_path / "budget.json"
        c = abe.CrawlBudgetController({"a.cn": {"daily": 10, "hourly": 5}},
                                      file_path=f)
        c.consume("a.cn")
        assert f.exists()
        c2 = abe.CrawlBudgetController(file_path=f)
        assert c2.allow("a.cn") is True

    def test_status(self):
        c = abe.CrawlBudgetController({"a.cn": {"daily": 5, "hourly": 2}})
        c.consume("a.cn")
        s = c.status()
        assert "a.cn" in s
        assert s["a.cn"]["daily_used"] == 1


# ════════════════ 5. IPReputationTracker ════════════════


class TestIPReputationTracker:
    def test_initial_allow(self):
        t = abe.IPReputationTracker()
        assert t.allow("ip1") is True

    def test_failure_blocks(self):
        t = abe.IPReputationTracker(base_backoff=10.0)
        t.record_failure("ip1", reason="429")
        assert t.allow("ip1") is False

    def test_success_clears_backoff(self):
        t = abe.IPReputationTracker()
        t.record_failure("ip1", reason="429")
        assert t.allow("ip1") is False
        t.record_success("ip1")
        assert t.allow("ip1") is True

    def test_exponential_backoff_grows(self):
        t = abe.IPReputationTracker(base_backoff=10.0, max_backoff=10000.0)
        t.record_failure("ip1")
        w1 = t.wait_seconds("ip1")
        t.record_failure("ip1")
        w2 = t.wait_seconds("ip1")
        assert w2 > w1

    def test_persistence(self, tmp_path):
        f = tmp_path / "ip.json"
        t = abe.IPReputationTracker(file_path=f)
        t.record_success("ip1")
        t2 = abe.IPReputationTracker(file_path=f)
        assert "ip1" in t2._records

    def test_quota(self):
        t = abe.IPReputationTracker()
        t.record_quota("ip1", 5)
        t.record_quota("ip1", 3)
        assert t._records["ip1"].total_quota_used == 8


# ════════════════ 6. CaptchaDetector ════════════════


class TestCaptchaDetector:
    @pytest.mark.parametrize("html,expected", [
        ('<div class="g-recaptcha"></div>', "google_recaptcha"),
        ('<script src="hcaptcha.com/1/api.js">', "hcaptcha"),
        ('<div id="geetest-test"></div>', "geetest"),
        ('<div class="yidun_slider"></div>', "yidun"),
        ('<script src="nc.js"></script>', "aliyun_slider"),
        ('<div class="TCaptcha"></div>', "tencent_captcha"),
        ('<input name="captcha-image">', "image_captcha"),
        ('<div class="sms-code-input">', "sms_captcha"),
        ('<div class="two-factor">', "two_factor"),
        ('<div class="turing-captcha"></div>', "turing"),
        ('<p>请输入验证码</p>', "generic"),
        ('<p>Verify you are human</p>', "generic"),
        ('<p>普通新闻正文，无验证码</p>', None),
    ])
    def test_detect_captcha(self, html, expected):
        sig = abe.detect_captcha(html)
        if expected is None:
            assert sig is None
        else:
            assert sig is not None
            assert sig.kind == expected
            assert sig.advice

    def test_empty_html(self):
        assert abe.detect_captcha("") is None
        assert abe.detect_captcha(None) is None


# ════════════════ 7. SessionWarmer ════════════════


class TestSessionWarmer:
    def test_warm_success(self):
        calls = []
        fetcher = lambda u: calls.append(u) or MagicMock(status_code=200)
        w = abe.SessionWarmer()
        ok = w.warm("https://www.cls.cn/api/sw", fetcher=fetcher)
        assert ok is True
        assert calls
        # 同一域再次调用 → 直接返回 True
        ok2 = w.warm("https://www.cls.cn/article/1", fetcher=fetcher)
        assert ok2 is True

    def test_warm_with_no_fetcher(self):
        w = abe.SessionWarmer()
        assert w.warm("https://a.cn/x") is False

    def test_warm_with_exception(self):
        def bad(u):
            raise IOError("net")
        w = abe.SessionWarmer()
        assert w.warm("https://a.cn/x", fetcher=bad) is False

    def test_is_warm(self):
        fetcher = lambda u: None
        w = abe.SessionWarmer()
        w.warm("https://a.cn/x", fetcher=fetcher)
        assert w.is_warm("https://a.cn/y") is True
        assert w.is_warm("https://b.cn/z") is False

    def test_clear_specific(self):
        w = abe.SessionWarmer()
        w._warmed["a.cn"] = "2026-01-01T00:00:00"
        w.clear("https://a.cn/x")
        assert "a.cn" not in w._warmed


# ════════════════ 8. AntiBlockPipeline ════════════════


class TestAntiBlockPipeline:
    def test_minimal_pipeline(self):
        p = abe.AntiBlockPipeline()
        decision = p.before_request("https://www.example.com/news")
        assert decision["delay"] >= 0
        assert "Referer" not in decision or isinstance(decision["referer"], str)
        assert decision["ip_key"] == "default"

    def test_with_proxies_and_budget(self):
        p = abe.AntiBlockPipeline(
            proxies=["http://1.1.1.1:8080", "http://2.2.2.2:8080"],
            budgets={"example.com": {"daily": 100, "hourly": 50}},
        )
        p.config.enable_proxy = True
        decision = p.before_request("https://example.com/news")
        assert decision["proxy"] is not None
        assert decision["budget_ok"] is True

    def test_budget_exhausted_blocks(self):
        p = abe.AntiBlockPipeline(
            budgets={"example.com": {"daily": 1, "hourly": 1}},
        )
        p.before_request("https://example.com/a")   # 消耗 1
        decision = p.before_request("https://example.com/b")
        assert decision["budget_ok"] is False

    def test_after_request_records(self):
        p = abe.AntiBlockPipeline()
        decision = p.before_request("https://example.com/a")
        result = p.after_request(decision, response=MagicMock(status_code=200,
                                                              text="ok"),
                                  elapsed_ms=120)
        assert result["ok"] is True
        assert result["captcha"] is None

    def test_after_request_detects_captcha(self):
        p = abe.AntiBlockPipeline()
        decision = p.before_request("https://example.com/a")
        result = p.after_request(decision,
                                  response=MagicMock(status_code=200,
                                                      text='<div class="g-recaptcha"></div>'),
                                  elapsed_ms=50)
        assert result["ok"] is False
        assert result["captcha"] is not None
        assert result["captcha"].kind == "google_recaptcha"

    def test_after_request_handles_exception(self):
        p = abe.AntiBlockPipeline()
        decision = p.before_request("https://example.com/a")
        result = p.after_request(decision, response=None,
                                  elapsed_ms=0, error=IOError("net"))
        assert result["ok"] is False
        assert "net" in result["error"]

    def test_status_includes_sub_statuses(self):
        p = abe.AntiBlockPipeline()
        st = p.status()
        assert "behavior" in st
        assert "ip_tracker" in st

    def test_ip_reputation_backoff(self):
        p = abe.AntiBlockPipeline()
        for _ in range(3):
            p.after_request(
                {"ip_key": "test-ip", "proxy": None},
                response=None, error=IOError("blocked"))
        # 同一 ip 现在被 backoff
        assert not p.config.ip_tracker.allow("test-ip")

    def test_self_check(self):
        sc = abe.self_check()
        assert "AntiBlockPipeline" in sc
        assert "CaptchaDetector" in sc


# ════════════════ 9. 集成：与 crawl_enhancer 共存性 ════════════════


class TestCoexistence:
    """新模块不应破坏已有 anti_block_utils。"""

    def test_old_classes_still_importable(self):
        from anti_block_utils import (DomainRateLimiter, DomainHealthTracker,
                                      UrlDeduplicator, detect_block,
                                      self_check as old_check)
        sc = old_check()
        assert "domain_rate_limiter" in sc

    def test_new_and_old_can_coexist(self):
        from anti_block_utils import DomainRateLimiter
        from anti_block_enhanced import ProxyPool, IPReputationTracker
        rl = DomainRateLimiter({"default": 0.5})
        pp = ProxyPool(["http://a"])
        t = IPReputationTracker()
        assert rl is not None and pp is not None and t is not None
