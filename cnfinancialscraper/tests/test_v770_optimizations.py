# -*- coding: utf-8 -*-
"""v7.7.0 升级回归测试 — 四模块全面优化

覆盖：
1. 信息爬取：AdaptiveCrawlPolicy（早停/恢复解除/并发降级/全域沦陷）
   + batch_smart_crawl 自适应分批（早停跳过剩余/去重/统计）
2. 语音交互：知识库语音指令路由（总结/负面/机构名/检索/校对/帮助）
   + TTS 数字归一化
3. 下载：已存在跳过 / 断点续传（Range 206）/ 200 全量回落 /
   sha256 校验 / min_bytes 拒收 / batch_download 并发统计
4. 分析：Sortino/胜率/极值扩展指标 / 指标缓存命中 /
   nav_trend_analysis 趋势四档

全部离线（FakeSession / 纯函数 / monkeypatch），不发网络请求、
不写真实项目目录。
"""
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

import analyzer as az
import crawl_enhancer as ce
import http_utils as hu
import voice_interface as vi


# ──────────────── 通用假对象 ────────────────

class FakeResp:
    """鸭子类型模拟 StdlibResponse（download_file 成功分支读取的属性）。"""

    def __init__(self, code=200, content=b"", headers=None, encoding="utf-8"):
        self.code = code
        self.content = content
        self.headers = headers or {}
        self._encoding = encoding
        self.text = content.decode(encoding, errors="replace")


class FakeSession:
    """按调用次序逐个弹出响应/异常的假 session。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, headers=None, timeout=30, **kw):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _nav_series(n, base=1.0, step=0.002):
    """单调上行净值序列（dict 形态）。"""
    return [{"date": f"2026-01-{(i % 28) + 1:02d}",
             "nav": base * (1 + step * i)} for i in range(n)]


# ════════════════ 1. 爬取自适应策略 ════════════════

class TestAdaptiveCrawlPolicy:
    def _fail(self, url="http://x.cn/a"):
        return ce.FetchResult(url=url, status=ce.STATUS_ERROR, error="blocked")

    def _ok(self, url="http://x.cn/a"):
        return ce.FetchResult(url=url, status=ce.STATUS_OK, html="ok", text_len=2)

    def test_early_stop_when_all_failed(self):
        p = ce.AdaptiveCrawlPolicy(min_samples=3)
        for _ in range(3):
            p.record(self._fail(), set())
        assert p.should_stop() is True
        assert p.snapshot()["stop_reason"] == "all_failed"

    def test_no_early_stop_below_min_samples(self):
        p = ce.AdaptiveCrawlPolicy(min_samples=8)
        for _ in range(5):
            p.record(self._fail(), set())
        assert p.should_stop() is False

    def test_success_clears_early_stop(self):
        p = ce.AdaptiveCrawlPolicy(min_samples=2)
        p.record(self._fail(), set())
        p.record(self._fail(), set())
        assert p.should_stop() is True
        p.record(self._ok(), set())
        assert p.should_stop() is False
        assert p.snapshot()["early_stopped"] is False

    def test_consecutive_fail_triggers_downgrade(self):
        p = ce.AdaptiveCrawlPolicy(downgrade_after=3)
        for _ in range(3):
            p.record(self._fail(), set())
        assert p.should_downgrade() is True
        assert p.snapshot()["downgrades"] == 1
        assert p.should_downgrade() is False      # 计数已清零

    def test_degraded_concurrency_floor(self):
        assert ce.AdaptiveCrawlPolicy.degraded_concurrency(4) == 2
        assert ce.AdaptiveCrawlPolicy.degraded_concurrency(1) == 1

    def test_all_domains_disabled_stops(self):
        p = ce.AdaptiveCrawlPolicy()

        class DeadHealth:
            def is_available(self, d):
                return False

        assert p.should_stop(DeadHealth(), {"a.cn", "b.cn"}) is True
        assert p.snapshot()["stop_reason"] == "domains_disabled"


class FakeFetcher:
    """按 URL 标记决定成败的注入抓取器。"""

    def __init__(self):
        self.fetched = []

    def fetch(self, url, use_api=True, use_browser=False):
        self.fetched.append(url)
        if "#ok" in url:
            return ce.FetchResult(url=url, status=ce.STATUS_OK,
                                  html="x" * 300, text_len=300, source="http")
        return ce.FetchResult(url=url, status=ce.STATUS_ERROR, error="blocked")


class TestBatchSmartCrawlV77:
    def test_stats_and_adaptive_snapshot(self):
        urls = ["http://a1.cn/#ok", "http://a2.cn/#ok",
                "http://a3.cn/#ok", "http://a4.cn/fail"]
        out = ce.batch_smart_crawl(urls, concurrency=2,
                                   rate_map={"default": 0.0},
                                   fetcher=FakeFetcher())
        st = out["stats"]
        assert st["ok"] == 3 and st["total"] == 4
        assert st["success_rate"] == 0.75
        assert st["elapsed"] >= 0 and st["avg_elapsed"] >= 0
        assert st["adaptive"]["early_stopped"] is False

    def test_early_stop_skips_remaining(self):
        urls = [f"http://d{i}.cn/fail" for i in range(30)]
        out = ce.batch_smart_crawl(urls, concurrency=2,
                                   rate_map={"default": 0.0},
                                   fetcher=FakeFetcher(),
                                   early_stop_min_samples=4)
        st = out["stats"]
        assert st["fetched"] < 30
        assert st["skipped_stopped"] > 0
        assert st["adaptive"]["early_stopped"] is True

    def test_dedup_skips_repeated_url(self, tmp_path):
        dedup = tmp_path / "seen.json"
        urls = ["http://dup.cn/a#ok", "http://dup.cn/a#ok",
                "http://dup.cn/b#ok"]
        out = ce.batch_smart_crawl(urls, concurrency=1,
                                   rate_map={"default": 0.0},
                                   dedup_file=str(dedup),
                                   fetcher=FakeFetcher())
        assert out["stats"]["skipped_dup"] == 1
        assert out["stats"]["fetched"] == 2


# ════════════════ 2. 语音知识库指令 ════════════════

class TestVoiceKnowledgeRouting:
    def test_non_kb_text_returns_none(self):
        assert vi.handle_knowledge_command("爬一下贵州茅台最近7天的舆情") is None
        assert vi.handle_knowledge_command("") is None

    def test_sync_overall_command(self):
        with patch.object(vi, "_kb_cmd_sync",
                          side_effect=lambda t, m, n: f"{t}|{m}|{n}") as m:
            assert vi.handle_knowledge_command("总结到知识库") == "None|overall|"
            m.assert_called_once()

    def test_sync_negative_into_dify(self):
        with patch.object(vi, "_kb_cmd_sync",
                          side_effect=lambda t, m, n: f"{t}|{m}|{n}"):
            assert vi.handle_knowledge_command("负面总结进dify") == "dify|negative|"

    def test_sync_target_name_extracted(self):
        with patch.object(vi, "_kb_cmd_sync",
                          side_effect=lambda t, m, n: f"{t}|{m}|{n}"):
            assert vi.handle_knowledge_command(
                "总结贵州茅台到知识库") == "None|target|贵州茅台"

    def test_sync_ima_target(self):
        with patch.object(vi, "_kb_cmd_sync",
                          side_effect=lambda t, m, n: f"{t}|{m}|{n}"):
            assert vi.handle_knowledge_command("同步到 ima") == "ima|overall|"

    def test_search_keyword_extracted(self):
        with patch.object(vi, "_kb_cmd_search",
                          side_effect=lambda k: f"SEARCH:{k}"):
            assert vi.handle_knowledge_command(
                "查一下知识库里的招商银行") == "SEARCH:招商银行"

    def test_search_without_keyword_falls_through(self):
        assert vi.handle_knowledge_command("查一下知识库") is None

    def test_verify_command(self):
        with patch.object(vi, "_kb_cmd_verify", return_value="VERIFY"):
            assert vi.handle_knowledge_command("用知识库校对") == "VERIFY"
            assert vi.handle_knowledge_command("和知识库比对一下") == "VERIFY"

    def test_handle_text_routes_help(self):
        vc = vi.VoiceChat(tts=False, chat=lambda t: {"reply": "CHAT"})
        assert vc.handle_text("命令") == vi.VOICE_HELP
        assert vc.handle_text("帮助") == vi.VOICE_HELP

    def test_handle_text_routes_kb_before_chat(self):
        vc = vi.VoiceChat(tts=False, chat=lambda t: {"reply": "CHAT"})
        with patch.object(vi, "_kb_cmd_verify", return_value="VERIFY"):
            assert vc.handle_text("用知识库校对") == "VERIFY"
        assert vc.handle_text("茅台舆情") == "CHAT"

    def test_tts_number_normalization(self):
        assert vi._normalize_numbers_for_tts("涨幅82.5%，新增+5家") == \
            "涨幅百分之82.5，新增5家"

    def test_summarize_for_speech_strips_markdown_url(self):
        reply = "**要点**：详情见 https://example.com/x 的内容"
        out = vi.summarize_for_speech(reply)
        assert "https" not in out and "**" not in out

    def test_kb_cmd_sync_no_data_message(self):
        class FakeKs:
            @staticmethod
            def sync_to_knowledge_base(**kw):
                return {"target": "local", "pushed": 0, "skipped": 0,
                        "failed": [], "message": "无可总结的数据（快照为空）"}
        with patch.object(vi, "_kb_import", return_value=FakeKs):
            assert "快照为空" in vi._kb_cmd_sync(None, "overall", "")

    def test_kb_cmd_verify_empty_snapshots(self):
        class FakeKs:
            @staticmethod
            def aggregate_snapshots():
                return {"articles": []}
        with patch.object(vi, "_kb_import", return_value=FakeKs):
            assert "快照为空" in vi._kb_cmd_verify()


# ════════════════ 3. 下载优化 ════════════════

class TestDownloadV77:
    PDF_HEADERS = {"Content-Type": "application/pdf"}

    def test_skip_existing_without_http_call(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF-old")
        fs = FakeSession([])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs)
        assert got == str(tmp_path / "a.pdf")
        assert fs.calls == []                      # 未发任何请求

    def test_overwrite_forces_redownload(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF-old")
        fs = FakeSession([FakeResp(content=b"%PDF-new", headers=self.PDF_HEADERS)])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs, overwrite=True)
        assert got and Path(got).read_bytes() == b"%PDF-new"

    def test_resume_range_206_appends(self, tmp_path):
        (tmp_path / "a.pdf.part").write_bytes(b"head")
        fs = FakeSession([FakeResp(code=206, content=b"tail",
                                   headers=self.PDF_HEADERS)])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs)
        assert got and Path(got).read_bytes() == b"headtail"
        assert not (tmp_path / "a.pdf.part").exists()
        assert fs.calls[0]["headers"]["Range"] == "bytes=4-"

    def test_resume_unsupported_falls_back_full(self, tmp_path):
        (tmp_path / "a.pdf.part").write_bytes(b"head")
        fs = FakeSession([FakeResp(code=200, content=b"%PDF-full",
                                   headers=self.PDF_HEADERS)])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs)
        assert got and Path(got).read_bytes() == b"%PDF-full"

    def test_no_part_file_no_range_header(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"%PDF-1.4", headers=self.PDF_HEADERS)])
        hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                         filename="a.pdf", session=fs)
        assert "Range" not in fs.calls[0]["headers"]

    def test_sha256_mismatch_rejects_and_cleans(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"abc", headers=self.PDF_HEADERS)])
        wrong = hashlib.sha256(b"xyz").hexdigest()
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs,
                               expect_sha256=wrong)
        assert got is None
        assert not (tmp_path / "a.pdf").exists()

    def test_sha256_match_passes(self, tmp_path):
        body = b"%PDF-1.4 good"
        fs = FakeSession([FakeResp(content=body, headers=self.PDF_HEADERS)])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs,
                               expect_sha256=hashlib.sha256(body).hexdigest())
        assert got is not None

    def test_min_bytes_rejects_too_small(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"%PDF", headers=self.PDF_HEADERS)])
        got = hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                               filename="a.pdf", session=fs, min_bytes=100)
        assert got is None

    def test_atomic_write_leaves_no_part_on_success(self, tmp_path):
        fs = FakeSession([FakeResp(content=b"%PDF-1.4", headers=self.PDF_HEADERS)])
        hu.download_file("http://a.cn/x.pdf", save_dir=str(tmp_path),
                         filename="a.pdf", session=fs)
        assert list(tmp_path.glob("*.part")) == []

    def test_file_sha256_helper(self, tmp_path):
        p = tmp_path / "x.bin"
        p.write_bytes(b"hello")
        assert hu.file_sha256(str(p)) == hashlib.sha256(b"hello").hexdigest()


class TestBatchDownload:
    def test_batch_ok_and_failed(self, tmp_path):
        fs = FakeSession([
            FakeResp(content=b"%PDF-1", headers={"Content-Type": "application/pdf"}),
            ConnectionError("refused"),
        ])
        out = hu.batch_download(["http://bd1.cn/x.pdf", "http://bd2.cn/y.pdf"],
                                save_dir=str(tmp_path), concurrency=2,
                                session=fs)
        assert out["total"] == 2
        assert out["ok"] == 1
        assert out["failed"] == ["http://bd2.cn/y.pdf"]
        ok_path = out["files"]["http://bd1.cn/x.pdf"]
        assert Path(ok_path).read_bytes() == b"%PDF-1"

    def test_batch_empty(self, tmp_path):
        out = hu.batch_download([], save_dir=str(tmp_path))
        assert out == {"total": 0, "ok": 0, "failed": [], "files": {},
                       "elapsed": out["elapsed"]}


# ════════════════ 4. 分析优化 ════════════════

class TestRiskMetricsV77:
    def test_extended_metrics_present(self):
        m = az.calculate_risk_metrics(_nav_series(120))
        for key in ("sortino_ratio", "win_rate", "best_day", "worst_day",
                    "sharpe_ratio", "calmar_ratio"):
            assert key in m, f"缺少指标 {key}"
        assert 0.0 < m["win_rate"] <= 1.0
        assert m["best_day"] >= m["worst_day"]

    def test_sortino_not_below_sharpe_for_uptrend(self):
        # 带回调的震荡上行（存在下行波动，下行偏差 ≥ 总体波动的下限成立）
        series = [{"date": f"d{i}", "nav": 1.0 + 0.002 * i
                   - (0.006 if i % 7 == 0 else 0.0)} for i in range(120)]
        m = az.calculate_risk_metrics(series)
        assert m["sortino_ratio"] >= m["sharpe_ratio"] - 0.01

    def test_metrics_cache_hit(self):
        series = _nav_series(80, step=0.001)
        az.calculate_risk_metrics(series)          # 预热入缓存
        with patch.object(az, "_pct_changes",
                          wraps=az._pct_changes) as spy:
            m2 = az.calculate_risk_metrics(list(series))
        assert spy.call_count == 0                 # 命中缓存，未重算
        assert "annualized_return" in m2

    def test_cache_does_not_share_across_rf(self):
        series = _nav_series(60, step=0.003)
        m1 = az.calculate_risk_metrics(series, risk_free_rate=0.02)
        m2 = az.calculate_risk_metrics(series, risk_free_rate=0.05)
        assert m1["sharpe_ratio"] != m2["sharpe_ratio"]

    def test_legacy_dict_path_still_estimate(self):
        m = az.calculate_risk_metrics({"1year": 15.67})
        assert m.get("estimate") is True


class TestNavTrendAnalysis:
    def test_uptrend_label(self):
        t = az.nav_trend_analysis(_nav_series(120, step=0.002))
        assert t["trend"] in ("强上行", "缓步上行")
        assert t["annualized_slope"] > 0
        assert t["at_high"] is True and t["off_peak"] == 0.0

    def test_downtrend_label(self):
        down = [{"date": f"d{i}", "nav": 1.0 - 0.004 * i} for i in range(120)]
        t = az.nav_trend_analysis(down)
        assert t["trend"] == "下行"
        assert t["off_peak"] > 0.05

    def test_window_returns(self):
        t = az.nav_trend_analysis(_nav_series(120, step=0.002))
        assert "return_20d" in t and "return_60d" in t
        assert t["return_20d"] > 0

    def test_vol_ratio_recent(self):
        t = az.nav_trend_analysis(_nav_series(120))
        assert "vol_ratio_recent20" in t

    def test_insufficient_data(self):
        t = az.nav_trend_analysis(_nav_series(5))
        assert t == {"insufficient_data": True, "points": 5}

    def test_report_includes_trend_section(self):
        product = {
            "product_name": "测试成长", "product_code": "000001",
            "historical_nav": _nav_series(120, step=0.002),
            "holdings": {},
        }
        report = az.analyze_product(product)
        assert "趋势（v7.7）" in report
        assert "索提诺比率" in report


# ════════════════ 5. 版本一致性 ════════════════

class TestVersion:
    def test_package_version_770(self):
        import scripts
        assert scripts.__version__ == "10.0.0"

    def test_new_exports(self):
        import scripts
        for name in ("nav_trend_analysis", "AdaptiveCrawlPolicy",
                     "handle_knowledge_command", "batch_download",
                     "file_sha256"):
            assert name in scripts.__all__, f"__all__ 缺少 {name}"
            assert hasattr(scripts, name)
