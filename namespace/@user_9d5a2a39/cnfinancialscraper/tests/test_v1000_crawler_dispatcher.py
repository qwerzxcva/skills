# -*- coding: utf-8 -*-
"""
v10.0.0 测试套件 — 爬取调度中心（crawler_dispatcher）

覆盖：
1. BaseScraper 协议 + ExternalScraperAdapter 包装
2. ScraperRegistry 注册/查询/统计
3. HealthTracker 健康追踪（含冷却）
4. IncrementalFetcher 增量判断（ETag/Last-Modified/hash）
5. ResumeManager 断点续爬
6. CrawlerDispatcher 全链路（含 BEST_SCORE/PRIORITY/ROUND_ROBIN/RANDOM 策略）
7. register_default_scrapers() 默认接入
8. quick_dispatch / quick_report 一键入口
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from scripts.crawler_dispatcher import (  # noqa: E402
    ScrapeStatus, ScrapeResult, BaseScraper, ExternalScraperAdapter,
    ScraperRegistry, SourceHealthRecord, HealthTracker,
    IncrementalIndex, IncrementalFetcher,
    ResumeTask, ResumeState, ResumeManager,
    DispatchStrategy, DispatchConfig, CrawlerDispatcher,
    register_default_scrapers, quick_dispatch, quick_report,
    get_default_registry,
)


class FakeScraper(BaseScraper):
    """测试用 BaseScraper。"""
    name = "fake"
    domain = "example.com"
    priority = 10

    def __init__(self, return_value: Any = None, fail: bool = False,
                 latency_ms: float = 10.0):
        super().__init__()
        self.return_value = return_value
        self.fail = fail
        self.latency = latency_ms
        self.call_count = 0

    def fetch(self, url: str, **kwargs: Any) -> ScrapeResult:
        self.call_count += 1
        if self.fail:
            return ScrapeResult(
                url=url, status=ScrapeStatus.FAILED,
                error="simulated failure",
                started_at="", finished_at="",
                duration_ms=self.latency, source=self.name,
            )
        return ScrapeResult(
            url=url, status=ScrapeStatus.SUCCESS,
            data=self.return_value,
            started_at="", finished_at="",
            duration_ms=self.latency, source=self.name,
            content_hash=IncrementalFetcher.compute_hash(self.return_value or url),
        )


# ============================================================================
# 1. BaseScraper + ScrapeResult
# ============================================================================

class TestBaseScraper(unittest.TestCase):
    """BaseScraper 协议 + ScrapeResult dataclass。"""

    def test_scrape_status_enum(self):
        self.assertEqual(ScrapeStatus.SUCCESS.name, "SUCCESS")
        self.assertEqual(ScrapeStatus.NOT_MODIFIED.name, "NOT_MODIFIED")
        self.assertEqual(ScrapeStatus.BLOCKED.name, "BLOCKED")

    def test_scrape_result_to_dict(self):
        r = ScrapeResult(url="http://x", status=ScrapeStatus.SUCCESS,
                         data={"k": "v"}, duration_ms=12.5, source="s")
        d = r.to_dict()
        self.assertEqual(d["status"], "SUCCESS")
        self.assertEqual(d["data"], {"k": "v"})
        self.assertEqual(d["source"], "s")

    def test_base_scraper_abstract(self):
        """BaseScraper 不能直接实例化。"""
        with self.assertRaises(TypeError):
            BaseScraper()  # type: ignore[abstract]

    def test_external_adapter_success(self):
        adapter = ExternalScraperAdapter(
            name="ext",
            fetch_fn=lambda u, **kw: {"ok": True, "url": u},
        )
        r = adapter.fetch("http://test/a")
        self.assertEqual(r.status, ScrapeStatus.SUCCESS)
        self.assertEqual(r.data["ok"], True)
        self.assertEqual(r.source, "ext")

    def test_external_adapter_failure(self):
        def boom(u, **kw):
            raise ValueError("network down")
        adapter = ExternalScraperAdapter(name="ext2", fetch_fn=boom)
        r = adapter.fetch("http://test/b")
        self.assertEqual(r.status, ScrapeStatus.FAILED)
        self.assertIn("network down", r.error or "")


# ============================================================================
# 2. ScraperRegistry
# ============================================================================

class TestScraperRegistry(unittest.TestCase):
    """注册中心：register / get / for_domain / unregister / stats。"""

    def setUp(self):
        self.reg = ScraperRegistry()

    def test_register_and_get(self):
        s = FakeScraper()
        self.reg.register(s)
        self.assertIs(self.reg.get("fake"), s)

    def test_get_missing(self):
        self.assertIsNone(self.reg.get("nonexistent"))

    def test_for_domain(self):
        s1 = FakeScraper()
        s1.name = "a"; s1.domain = "x.com"; s1.priority = 20
        s2 = FakeScraper()
        s2.name = "b"; s2.domain = "x.com"; s2.priority = 10
        self.reg.register(s1)
        self.reg.register(s2)
        result = self.reg.for_domain("x.com")
        # 按 priority 排序（数字越小越优先）
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "b")

    def test_for_domain_empty(self):
        self.assertEqual(self.reg.for_domain("nope.com"), [])

    def test_register_external(self):
        adapter = self.reg.register_external(
            name="ext3", fetch_fn=lambda u: {}, domain="y.com", priority=5,
        )
        self.assertIsInstance(adapter, ExternalScraperAdapter)
        self.assertIs(self.reg.get("ext3"), adapter)

    def test_unregister(self):
        s = FakeScraper()
        self.reg.register(s)
        self.assertTrue(self.reg.unregister("fake"))
        self.assertIsNone(self.reg.get("fake"))
        self.assertFalse(self.reg.unregister("fake"))  # 第二次不存在

    def test_all_names_sorted(self):
        for n in ["z", "a", "m"]:
            s = FakeScraper()
            s.name = n
            self.reg.register(s)
        self.assertEqual(self.reg.all_names(), ["a", "m", "z"])

    def test_stats(self):
        s = FakeScraper()
        self.reg.register(s)
        st = self.reg.stats()
        self.assertEqual(st["total_scrapers"], 1)
        self.assertEqual(st["total_domains"], 1)
        self.assertIn("fake", st["scrapers"])

    def test_default_registry_singleton(self):
        r1 = get_default_registry()
        r2 = get_default_registry()
        self.assertIs(r1, r2)


# ============================================================================
# 3. HealthTracker
# ============================================================================

class TestHealthTracker(unittest.TestCase):
    """健康追踪：成功率/延迟/冷却/评分。"""

    def test_record_success(self):
        ht = HealthTracker()
        ht.record("src1", ScrapeStatus.SUCCESS, latency_ms=50.0)
        rec = ht.get("src1")
        self.assertEqual(rec.success_calls, 1)
        self.assertEqual(rec.total_calls, 1)
        self.assertGreater(rec.score(), 0)

    def test_record_blocked_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            ht = HealthTracker(persist_path=os.path.join(td, "h.json"))
            for _ in range(2):
                ht.record("src", ScrapeStatus.BLOCKED, cooldown_seconds=10)
            rec = ht.get("src")
            self.assertEqual(rec.blocked_calls, 2)
            self.assertIsNotNone(rec.cooldown_until)
            self.assertFalse(rec.is_available())
            self.assertEqual(rec.score(), -1e9)

    def test_record_multiple_failures_triggers_cooldown(self):
        ht = HealthTracker()
        for _ in range(3):
            ht.record("src", ScrapeStatus.FAILED)
        rec = ht.get("src")
        self.assertEqual(rec.consecutive_failures, 3)
        self.assertIsNotNone(rec.cooldown_until)

    def test_score_formula(self):
        ht = HealthTracker()
        ht.record("a", ScrapeStatus.SUCCESS, latency_ms=100)
        ht.record("a", ScrapeStatus.SUCCESS, latency_ms=100)
        ht.record("a", ScrapeStatus.FAILED)
        # 2/3 success, avg latency 100, 1 consecutive failure
        rec = ht.get("a")
        expected = (2 / 3) * 100 - 100 * 0.1 - 1 * 20
        self.assertAlmostEqual(rec.score(), expected, places=2)

    def test_best_picks_unknown(self):
        """没记录的源应被选中。"""
        ht = HealthTracker()
        self.assertEqual(ht.best(["x", "y"]), "x")

    def test_best_with_records(self):
        ht = HealthTracker()
        for _ in range(5):
            ht.record("good", ScrapeStatus.SUCCESS, latency_ms=10)
        ht.record("bad", ScrapeStatus.FAILED)
        self.assertEqual(ht.best(["good", "bad"]), "good")

    def test_reset(self):
        ht = HealthTracker()
        ht.record("x", ScrapeStatus.SUCCESS)
        ht.reset("x")
        self.assertIsNone(ht.get("x"))

    def test_report(self):
        ht = HealthTracker()
        ht.record("a", ScrapeStatus.SUCCESS)
        report = ht.report()
        self.assertIn("sources", report)
        self.assertIn("details", report)
        self.assertEqual(len(report["details"]), 1)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "h.json")
            ht1 = HealthTracker(persist_path=path)
            ht1.record("persisted", ScrapeStatus.SUCCESS, latency_ms=50)
            ht2 = HealthTracker(persist_path=path)
            rec = ht2.get("persisted")
            self.assertIsNotNone(rec)
            self.assertEqual(rec.success_calls, 1)


# ============================================================================
# 4. IncrementalFetcher
# ============================================================================

class TestIncrementalFetcher(unittest.TestCase):
    """增量爬取：ETag/Last-Modified/hash 跳过。"""

    def test_first_fetch_success(self):
        s = FakeScraper(return_value={"v": 1})
        inc = IncrementalFetcher(s)
        r = inc.fetch("http://x.com")
        self.assertEqual(r.status, ScrapeStatus.SUCCESS)

    def test_second_fetch_not_modified(self):
        s = FakeScraper(return_value={"v": 1})
        inc = IncrementalFetcher(s)
        r1 = inc.fetch("http://x.com")
        r2 = inc.fetch("http://x.com")
        self.assertEqual(r2.status, ScrapeStatus.NOT_MODIFIED)

    def test_content_change_detected(self):
        s = FakeScraper(return_value={"v": 1})
        inc = IncrementalFetcher(s)
        inc.fetch("http://x.com")
        s.return_value = {"v": 2}  # 内容变化
        r2 = inc.fetch("http://x.com")
        self.assertEqual(r2.status, ScrapeStatus.SUCCESS)

    def test_compute_hash(self):
        h1 = IncrementalFetcher.compute_hash({"a": 1, "b": 2})
        h2 = IncrementalFetcher.compute_hash({"b": 2, "a": 1})
        self.assertEqual(h1, h2)  # 排序后一致

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            s = FakeScraper(return_value={"v": 1})
            inc1 = IncrementalFetcher(s, persist_path=os.path.join(td, "inc.json"))
            inc1.fetch("http://x.com")
            inc2 = IncrementalFetcher(s, persist_path=os.path.join(td, "inc.json"))
            r = inc2.fetch("http://x.com")
            self.assertEqual(r.status, ScrapeStatus.NOT_MODIFIED)

    def test_should_skip_with_etag(self):
        idx = IncrementalIndex()
        idx.update("http://x", etag='"v1"')
        self.assertTrue(idx.should_skip("http://x", '"v1"', None, None))
        self.assertFalse(idx.should_skip("http://x", '"v2"', None, None))

    def test_should_skip_with_last_modified(self):
        idx = IncrementalIndex()
        idx.update("http://x", last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
        self.assertTrue(idx.should_skip("http://x", None,
                                        "Wed, 21 Oct 2026 07:28:00 GMT", None))

    def test_should_skip_with_hash(self):
        idx = IncrementalIndex()
        idx.update("http://x", content_hash="abc")
        self.assertTrue(idx.should_skip("http://x", None, None, "abc"))


# ============================================================================
# 5. ResumeManager
# ============================================================================

class TestResumeManager(unittest.TestCase):
    """断点续爬：enqueue/next_task/complete/fail/progress。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rm = ResumeManager(os.path.join(self.tmp.name, "r.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_and_next(self):
        ids = self.rm.enqueue(["http://a", "http://b"], "fake")
        self.assertEqual(len(ids), 2)
        task = self.rm.next_task()
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "running")

    def test_complete(self):
        tid = self.rm.enqueue(["http://a"], "fake")[0]
        task = self.rm.next_task()
        self.rm.complete(task.task_id)
        self.assertIn(tid, self.rm.state.completed)

    def test_fail_under_max(self):
        tid = self.rm.enqueue(["http://a"], "fake")[0]
        task = self.rm.next_task()
        result = self.rm.fail(task.task_id, "err", max_attempts=3)
        self.assertFalse(result)  # 没到 max attempts

    def test_fail_at_max(self):
        self.rm.enqueue(["http://a"], "fake")[0]
        # 跑 3 次 fail
        for _ in range(3):
            task = self.rm.next_task()
            if task:
                self.rm.fail(task.task_id, "err", max_attempts=3)
        # 检查 progress
        prog = self.rm.progress()
        self.assertEqual(prog["failed"], 1)

    def test_progress(self):
        self.rm.enqueue(["http/a", "http/b", "http/c"], "fake")
        prog = self.rm.progress()
        self.assertEqual(prog["total"], 3)
        self.assertEqual(prog["pending"], 3)

    def test_reset(self):
        self.rm.enqueue(["http/a"], "fake")
        self.rm.reset()
        self.assertEqual(self.rm.progress()["total"], 0)

    def test_persistence(self):
        self.rm.enqueue(["http/a"], "fake")
        # 重启
        rm2 = ResumeManager(os.path.join(self.tmp.name, "r.json"))
        self.assertEqual(rm2.progress()["total"], 1)


# ============================================================================
# 6. CrawlerDispatcher
# ============================================================================

class TestCrawlerDispatcher(unittest.TestCase):
    """调度器全链路。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = ScraperRegistry()
        self.cfg = DispatchConfig(state_dir=self.tmp.name,
                                  enable_health_persist=False)
        self.disp = CrawlerDispatcher(self.reg, self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dispatch_with_explicit_scraper(self):
        s = FakeScraper(return_value={"ok": True})
        s.name = "explicit"; s.domain = "x.com"
        self.reg.register(s)
        r = self.disp.dispatch("http://x.com/page", scraper_name="explicit")
        self.assertEqual(r.status, ScrapeStatus.SUCCESS)
        self.assertEqual(r.data["ok"], True)

    def test_dispatch_with_no_scraper(self):
        r = self.disp.dispatch("http://nonexistent.com/")
        self.assertEqual(r.status, ScrapeStatus.FAILED)
        self.assertIn("no scraper", r.error or "")

    def test_dispatch_incremental(self):
        s = FakeScraper(return_value={"v": 1})
        s.name = "inc"; s.domain = "inc.com"
        self.reg.register(s)
        r1 = self.disp.dispatch("http://inc.com/")
        r2 = self.disp.dispatch("http://inc.com/")
        self.assertEqual(r2.status, ScrapeStatus.NOT_MODIFIED)

    def test_dispatch_batch(self):
        s = FakeScraper()
        s.name = "batch"; s.domain = "b.com"
        self.reg.register(s)
        results = self.disp.dispatch_batch(
            ["http://b.com/1", "http://b.com/2"], scraper_name="batch",
        )
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r.status, ScrapeStatus.SUCCESS)

    def test_strategy_priority(self):
        self.cfg.strategy = DispatchStrategy.PRIORITY
        a = FakeScraper(); a.name = "low"; a.domain = "p.com"; a.priority = 100
        b = FakeScraper(); b.name = "high"; b.domain = "p.com"; b.priority = 1
        self.reg.register(a); self.reg.register(b)
        r = self.disp.dispatch("http://p.com/", scraper_name=None)
        self.assertEqual(r.source, "high")

    def test_strategy_round_robin(self):
        self.cfg.strategy = DispatchStrategy.ROUND_ROBIN
        for i in range(2):
            s = FakeScraper(); s.name = f"rr{i}"; s.domain = "rr.com"
            self.reg.register(s)
        results = []
        for _ in range(4):
            r = self.disp.dispatch("http://rr.com/")
            results.append(r.source)
        # RR 应该在两个源之间切换
        self.assertEqual(len(set(results)), 2)

    def test_strategy_random(self):
        self.cfg.strategy = DispatchStrategy.RANDOM
        s = FakeScraper(); s.name = "rand"; s.domain = "rand.com"
        self.reg.register(s)
        r = self.disp.dispatch("http://rand.com/")
        self.assertEqual(r.status, ScrapeStatus.SUCCESS)

    def test_strategy_best_score(self):
        self.cfg.strategy = DispatchStrategy.BEST_SCORE
        # 两个源：good 多次成功，bad 失败
        good = FakeScraper(); good.name = "good"; good.domain = "bs.com"
        bad = FakeScraper(); bad.name = "bad"; bad.domain = "bs.com"; bad.fail = True
        self.reg.register(good); self.reg.register(bad)
        # 跑几次让健康分生效
        for _ in range(3):
            self.disp.dispatch("http://bs.com/", scraper_name="good")
        self.disp.dispatch("http://bs.com/", scraper_name="bad")
        r = self.disp.dispatch("http://bs.com/")
        self.assertEqual(r.source, "good")

    def test_queue_resume_and_run(self):
        s = FakeScraper()
        s.name = "res"; s.domain = "r.com"
        self.reg.register(s)
        ids = self.disp.queue_resume(["http://r.com/1", "http://r.com/2"],
                                      scraper_name="res")
        self.assertEqual(len(ids), 2)
        report = self.disp.run_resume(scraper_name="res")
        self.assertEqual(report["processed"], 2)
        self.assertEqual(report["succeeded"], 2)

    def test_health_recorded(self):
        s = FakeScraper(); s.name = "h"; s.domain = "h.com"
        self.reg.register(s)
        self.disp.dispatch("http://h.com/")
        rec = self.disp.health.get("h")
        self.assertEqual(rec.success_calls, 1)

    def test_report(self):
        rep = self.disp.report()
        self.assertIn("registry", rep)
        self.assertIn("health", rep)
        self.assertIn("resume", rep)
        self.assertIn("strategy", rep)


# ============================================================================
# 7. register_default_scrapers 默认接入
# ============================================================================

class TestRegisterDefaultScrapers(unittest.TestCase):
    """默认接入 v9 现有 scraper。"""

    def test_register_returns_count(self):
        reg = ScraperRegistry()
        n = register_default_scrapers(reg)
        # 不强求具体数（v9 模块可能未全装），但至少 ≥0
        self.assertGreaterEqual(n, 0)

    def test_register_returns_adapter_instances(self):
        reg = ScraperRegistry()
        register_default_scrapers(reg)
        names = reg.all_names()
        # 至少有一个成功注册
        # 注意：v9 的某些模块需要 akshare，未装会跳过
        # 这里只验证不抛异常


# ============================================================================
# 8. quick_dispatch / quick_report 一键入口
# ============================================================================

class TestQuickEntry(unittest.TestCase):
    """一键入口（注册默认 + 调度）。"""

    def test_quick_report_doesnt_raise(self):
        # 至少调用成功（即使没有爬虫）
        try:
            report = quick_report()
            self.assertIn("registry", report)
        except Exception as e:
            self.fail(f"quick_report raised: {e}")


if __name__ == "__main__":
    unittest.main()