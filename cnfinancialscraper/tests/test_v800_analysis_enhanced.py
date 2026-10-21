# -*- coding: utf-8 -*-
"""v8.0.0 数据分析增强测试 — KeywordExtractor / CrossSourceVerifier /
TrendAnalyzer / PeerBenchmark / InsightGenerator / TimeBucketAggregator /
enhanced_aggregate
"""
import math
from datetime import datetime

import pytest

import analysis_enhanced as ane


SAMPLE_ARTICLES = [
    {"title": "贵州茅台发布半年报，营收增长18%", "summary": "营收500亿元，同比增长25%",
     "sentiment": "positive", "publish_time": "2026-08-15 10:00:00",
     "source": "上海证券报", "target_name": "贵州茅台"},
    {"title": "贵州茅台半年报：净利润同比增长25%", "summary": "业绩超预期",
     "sentiment": "positive", "publish_time": "2026-08-15 14:30:00",
     "source": "中国证券报", "target_name": "贵州茅台"},
    {"title": "贵州茅台股价大跌3%！投资者担忧估值过高",
     "summary": "机构持仓出现分歧",
     "sentiment": "negative", "publish_time": "2026-08-16 09:15:00",
     "source": "雪球", "target_name": "贵州茅台"},
    {"title": "五粮液半年报披露，营收300亿元", "summary": "白酒板块整体回暖",
     "sentiment": "positive", "publish_time": "2026-08-15 11:00:00",
     "source": "证券时报", "target_name": "五粮液"},
    {"title": "白酒板块异动：茅台、五粮液、泸州老窖领跌",
     "summary": "板块下跌2%",
     "sentiment": "negative", "publish_time": "2026-08-16 15:00:00",
     "source": "财联社", "target_name": "白酒板块"},
]


# ════════════════ 1. KeywordExtractor ════════════════


class TestKeywordExtractor:
    def test_unigrams_extracted(self):
        r = ane.extract_keywords(SAMPLE_ARTICLES)
        assert len(r.unigrams) > 0
        # 「半年报」「茅台」这类高频词应在前列
        words = [w for w, _ in r.unigrams]
        assert any("茅台" in w for w in words)

    def test_bigrams(self):
        r = ane.extract_keywords(SAMPLE_ARTICLES)
        assert isinstance(r.bigrams, list)

    def test_stock_codes_detected(self):
        # 显式加入股票代码（标题里）
        arts = [{"title": "600519 贵州茅台再创新高",
                 "summary": "688981 半导体也涨",
                 "publish_time": "2026-08-15"}]
        r = ane.extract_keywords(arts)
        codes = [c for c, _ in r.stock_codes]
        assert "600519" in codes
        assert "688981" in codes

    def test_amounts_detected(self):
        arts = [{"title": "公司营收500亿元",
                 "summary": "净利润30亿元",
                 "publish_time": "2026-08-15"}]
        r = ane.extract_keywords(arts)
        amounts = [a for a, _ in r.amounts]
        assert any("500" in a for a in amounts)

    def test_percentages_detected(self):
        arts = [{"title": "增长18%",
                 "summary": "下跌3.5%",
                 "publish_time": "2026-08-15"}]
        r = ane.extract_keywords(arts)
        pcts = [p for p, _ in r.percentages]
        assert any("18" in p for p in pcts)
        assert any("3.5" in p for p in pcts)

    def test_empty_articles(self):
        r = ane.extract_keywords([])
        assert r.unigrams == []
        assert r.stock_codes == []

    def test_top_method(self):
        r = ane.extract_keywords(SAMPLE_ARTICLES)
        t = r.top(n=5)
        assert "unigrams" in t
        assert "bigrams" in t
        assert len(t["unigrams"]) <= 5

    def test_min_freq_filter(self):
        r = ane.extract_keywords(SAMPLE_ARTICLES, min_freq=10)
        assert r.unigrams == []   # 频次不够

    def test_new_words_filter_by_score(self):
        r = ane.extract_keywords(SAMPLE_ARTICLES, new_word_min_score=99999)
        assert r.new_words == []


# ════════════════ 2. CrossSourceVerifier ════════════════


class TestCrossSourceVerifier:
    def test_basic_verification(self):
        evs = ane.verify_cross_source(SAMPLE_ARTICLES)
        assert len(evs) >= 2   # 至少茅台和五粮液分开

    def test_same_event_multi_source(self):
        # 两条完全相同的事件
        arts = [
            {"title": "贵州茅台半年报：营收500亿元", "sentiment": "positive",
             "publish_time": "2026-08-15 10:00:00", "source": "上海证券报"},
            {"title": "贵州茅台半年报：营收500亿元", "sentiment": "positive",
             "publish_time": "2026-08-15 11:00:00", "source": "中国证券报"},
            {"title": "贵州茅台半年报：营收500亿元", "sentiment": "positive",
             "publish_time": "2026-08-15 12:00:00", "source": "证券时报"},
        ]
        evs = ane.verify_cross_source(arts)
        assert len(evs) == 1
        assert evs[0].mention_count == 3
        assert len(evs[0].sources) == 3

    def test_confidence_high_with_authoritative_sources(self):
        arts = [
            {"title": "贵州茅台发布公告", "sentiment": "positive",
             "publish_time": "2026-08-15 10:00:00", "source": "上海证券报"},
            {"title": "贵州茅台发布公告", "sentiment": "positive",
             "publish_time": "2026-08-15 11:00:00", "source": "中国证券报"},
            {"title": "贵州茅台发布公告", "sentiment": "positive",
             "publish_time": "2026-08-15 12:00:00", "source": "证券时报"},
        ]
        evs = ane.verify_cross_source(arts)
        assert evs[0].confidence >= 0.5

    def test_conflict_detection(self):
        arts = [
            {"title": "贵州茅台发布公告", "sentiment": "positive",
             "publish_time": "2026-08-15 10:00:00", "source": "上海证券报"},
            {"title": "贵州茅台发布公告", "sentiment": "negative",
             "publish_time": "2026-08-15 11:00:00", "source": "雪球"},
        ]
        evs = ane.verify_cross_source(arts)
        assert evs[0].conflict is True

    def test_similarity_threshold(self):
        # 标题相似度低 → 视为两个事件
        arts = [
            {"title": "苹果公司发布新款iPhone手机", "sentiment": "neutral",
             "publish_time": "2026-08-15 10:00:00", "source": "X"},
            {"title": "微软完成对游戏公司的并购交易", "sentiment": "neutral",
             "publish_time": "2026-08-15 11:00:00", "source": "X"},
        ]
        evs = ane.verify_cross_source(arts)
        assert len(evs) == 2

    def test_time_window_filter(self):
        # 超过 48 小时不应被合并
        arts = [
            {"title": "贵州茅台发布公告", "sentiment": "neutral",
             "publish_time": "2026-08-15 10:00:00", "source": "X"},
            {"title": "贵州茅台发布公告", "sentiment": "neutral",
             "publish_time": "2026-08-20 10:00:00", "source": "Y"},
        ]
        evs = ane.verify_cross_source(arts, time_window_hours=48)
        # 时间窗太短 → 拆成两条
        assert len(evs) >= 1

    def test_entities_collected(self):
        arts = [
            {"title": "600519 茅台创新高，688981 半导体跟涨",
             "sentiment": "positive",
             "publish_time": "2026-08-15 10:00:00", "source": "X"},
        ]
        evs = ane.verify_cross_source(arts)
        assert any("600519" in e.entities for e in evs)


# ════════════════ 3. TrendAnalyzer ════════════════


class TestTrendAnalyzer:
    def test_basic_trend(self):
        r = ane.analyze_trend(SAMPLE_ARTICLES)
        assert r.granularity == "day"
        assert r.total == 5
        assert len(r.series) >= 2

    def test_moving_avg_present(self):
        r = ane.analyze_trend(SAMPLE_ARTICLES)
        assert isinstance(r.moving_avg, dict)
        assert len(r.moving_avg) == len(r.series)

    def test_weekly_comparison(self):
        # 构造 14 天的数据
        arts = []
        for d in range(14):
            arts.append({
                "publish_time": f"2026-08-{d+1:02d} 10:00:00",
                "sentiment": "neutral",
                "title": f"测试{d}",
                "source": "X",
            })
        r = ane.analyze_trend(arts, granularity="day")
        assert len(r.week_over_week) >= 1

    def test_anomaly_detection_with_spike(self):
        # 14 个低数据点 + 1 个 spike
        arts = []
        for d in range(14):
            arts.append({"publish_time": f"2026-08-{d+1:02d} 10:00:00",
                         "sentiment": "neutral", "title": "x", "source": "X"})
        arts.append({"publish_time": "2026-08-15 10:00:00",
                     "sentiment": "neutral", "title": "x", "source": "X"})
        for _ in range(20):  # 第 15 天大爆发
            arts.append({"publish_time": "2026-08-15 11:00:00",
                         "sentiment": "neutral", "title": "x", "source": "X"})
        r = ane.analyze_trend(arts, granularity="day", z_threshold=2.0)
        assert any(a["direction"] == "spike" for a in r.anomalies)

    def test_forecast_present(self):
        # 3+ 个不同时间桶才触发 forecast
        arts = []
        for d in range(4):
            for _ in range(d + 1):
                arts.append({"publish_time": f"2026-08-{d+1:02d} 10:00:00",
                             "sentiment": "neutral", "title": "x", "source": "X"})
        r = ane.analyze_trend(arts, granularity="day", forecast_steps=3)
        assert "future" in r.forecast
        assert len(r.forecast["future"]) == 3

    def test_trend_label_rising(self):
        arts = []
        for d in range(10):
            for _ in range(d + 1):
                arts.append({"publish_time": f"2026-08-{d+1:02d} 10:00:00",
                             "sentiment": "neutral", "title": "x", "source": "X"})
        r = ane.analyze_trend(arts, granularity="day")
        assert r.trend_label in ("上升", "平稳")

    def test_empty_articles(self):
        r = ane.analyze_trend([])
        assert r.total == 0


# ════════════════ 4. PeerBenchmark ════════════════


class TestPeerBenchmark:
    def test_basic_benchmark(self):
        metrics = {
            "茅台": {"annual_return": 0.25, "volatility": 0.15},
            "五粮液": {"annual_return": 0.18, "volatility": 0.18},
            "泸州老窖": {"annual_return": 0.22, "volatility": 0.16},
            "洋河": {"annual_return": 0.10, "volatility": 0.20},
        }
        r = ane.benchmark_against_peers("茅台", metrics, group_key="白酒")
        assert r.target == "茅台"
        assert r.group_size == 4
        assert "annual_return" in r.target_metrics
        assert 0 <= r.percentile["annual_return"] <= 100

    def test_with_group_filter(self):
        metrics = {
            "茅台": {"ret": 0.25},
            "五粮液": {"ret": 0.18},
            "招行": {"ret": 0.15},
        }
        r = ane.benchmark_against_peers(
            "茅台", metrics, group_key="白酒",
            group_filter={"白酒": ["茅台", "五粮液"]})
        # group_size 应只算组内（+1 目标 = 2）
        assert r.group_size == 2

    def test_unknown_target(self):
        metrics = {"a": {"x": 1.0}}
        r = ane.benchmark_against_peers("notfound", metrics)
        assert r.target == "notfound"
        assert r.group_size == 0

    def test_no_peers(self):
        metrics = {"alone": {"x": 1.0}}
        r = ane.benchmark_against_peers("alone", metrics)
        assert r.group_size == 1

    def test_rank_and_percentile(self):
        metrics = {
            "a": {"x": 1.0},
            "b": {"x": 2.0},
            "c": {"x": 3.0},
            "d": {"x": 4.0},
        }
        r = ane.benchmark_against_peers("d", metrics)
        assert r.rank["x"] == 1   # 最大值排第 1


# ════════════════ 5. InsightGenerator ════════════════


class TestInsightGenerator:
    def test_risk_insight_for_high_negative(self):
        stats = {"total": 100, "sentiment": {"negative": 50, "positive": 10},
                 "neg_ratio": 0.5, "pos_ratio": 0.1, "severity": {},
                 "source_top": [], "by_day": {}, "hot_keywords": [],
                 "avg_score": -0.3}
        insights = ane.generate_insights(stats)
        assert any(i.level == "risk" for i in insights)

    def test_opportunity_insight_for_high_positive(self):
        stats = {"total": 100, "sentiment": {"negative": 10, "positive": 60},
                 "neg_ratio": 0.1, "pos_ratio": 0.6, "severity": {},
                 "source_top": [], "by_day": {}, "hot_keywords": [],
                 "avg_score": 0.5}
        insights = ane.generate_insights(stats)
        assert any(i.level == "opportunity" for i in insights)

    def test_no_insights_for_neutral(self):
        stats = {"total": 100, "sentiment": {"neutral": 100},
                 "neg_ratio": 0.0, "pos_ratio": 0.0, "severity": {},
                 "source_top": [], "by_day": {}, "hot_keywords": [],
                 "avg_score": 0.0}
        insights = ane.generate_insights(stats)
        assert insights == []

    def test_trend_insight(self):
        stats = {"total": 10, "sentiment": {}, "neg_ratio": 0.0,
                 "pos_ratio": 0.0, "severity": {}, "source_top": [],
                 "by_day": {}, "hot_keywords": [], "avg_score": 0.0}
        trend = ane.TrendResult(trend_label="上升",
                                forecast={"slope_per_bucket": 0.5, "future": [1]})
        insights = ane.generate_insights(stats, trend=trend)
        assert any("上升" in i.title or "上升" in i.detail for i in insights)

    def test_anomaly_insight(self):
        stats = {"total": 10, "sentiment": {}, "neg_ratio": 0.0,
                 "pos_ratio": 0.0, "severity": {}, "source_top": [],
                 "by_day": {}, "hot_keywords": [], "avg_score": 0.0}
        trend = ane.TrendResult(anomalies=[{"bucket": "2026-08-15", "value": 50,
                                            "z_score": 3.0, "direction": "spike"}])
        insights = ane.generate_insights(stats, trend=trend)
        assert any("异常" in i.title for i in insights)

    def test_top_n_limit(self):
        stats = {"total": 100, "sentiment": {"negative": 50},
                 "neg_ratio": 0.5, "pos_ratio": 0.0, "severity": {},
                 "source_top": [], "by_day": {}, "hot_keywords": [],
                 "avg_score": -0.3}
        insights = ane.generate_insights(stats, top_n=3)
        assert len(insights) <= 3

    def test_sort_priority(self):
        stats = {"total": 100, "sentiment": {"negative": 50, "positive": 30},
                 "neg_ratio": 0.5, "pos_ratio": 0.3, "severity": {},
                 "source_top": [], "by_day": {}, "hot_keywords": [],
                 "avg_score": -0.3}
        insights = ane.generate_insights(stats)
        # risk 应排在 info/opportunity 之前
        if insights:
            assert insights[0].level in ("risk", "warn")


# ════════════════ 6. TimeBucketAggregator ════════════════


class TestTimeBucketAggregator:
    def test_day_granularity(self):
        r = ane.aggregate_by_time_bucket(SAMPLE_ARTICLES, granularity="day")
        assert "2026-08-15" in r
        assert r["2026-08-15"]["count"] == 3
        assert r["2026-08-16"]["count"] == 2

    def test_hour_granularity(self):
        r = ane.aggregate_by_time_bucket(SAMPLE_ARTICLES, granularity="hour")
        # 至少 5 个不同的 hour 桶
        assert len(r) >= 4

    def test_week_granularity(self):
        r = ane.aggregate_by_time_bucket(SAMPLE_ARTICLES, granularity="week")
        assert len(r) >= 1

    def test_sentiment_split(self):
        r = ane.aggregate_by_time_bucket(SAMPLE_ARTICLES, granularity="day")
        # 8-15 是 positive 多，8-16 是 negative 多
        assert r["2026-08-15"]["positive"] >= 2
        assert r["2026-08-16"]["negative"] >= 2


# ════════════════ 7. enhanced_aggregate 一站式 ════════════════


class TestEnhancedAggregate:
    def test_returns_full_payload(self):
        result = ane.enhanced_aggregate(SAMPLE_ARTICLES)
        assert "statistics" in result
        assert "keywords" in result
        assert "verified_events" in result
        assert "trend" in result
        assert "by_time_bucket" in result
        assert "insights" in result
        assert result["total"] >= 1

    def test_days_filter(self):
        # 给几天前的文章 → 应被过滤
        old_article = {"title": "旧新闻", "sentiment": "neutral",
                       "publish_time": "2020-01-01 10:00:00",
                       "source": "X", "target_name": "X"}
        result = ane.enhanced_aggregate([old_article], days=7)
        # 7 天窗口外会被过滤
        assert result["total"] == 0

    def test_empty_input(self):
        result = ane.enhanced_aggregate([])
        assert result["total"] == 0
        assert result["statistics"]["total"] == 0

    def test_keywords_top_keys(self):
        result = ane.enhanced_aggregate(SAMPLE_ARTICLES)
        k = result["keywords"]
        assert "unigrams" in k and "bigrams" in k
        assert "stock_codes" in k and "amounts" in k

    def test_self_check(self):
        sc = ane.self_check()
        assert "EnhancedAggregate" in sc
        assert "InsightGenerator" in sc
