# -*- coding: utf-8 -*-
"""v7.3.0 升级回归测试 — 名单完善 + 爬取增强 + 内容识别 + 汇总分析 + 语音交互

覆盖：
1. 机构名单：11 类新增精选名录落盘、CATEGORY_MAP 接线、registry ≥2300 家/43 类
2. crawl_enhancer：classify_response / SmartFetcher 三级降级 / batch 统计与去重
3. web_recognizer：表格/KV/文章条目/分页/数字抽取/页面类型判别
4. data_aggregator：去重/统计/截面/快照聚合/机构简报/Markdown 导出
5. voice_interface：播报文本压缩 / VoiceChat 假回调闭环
全部离线（fake 注入），不发网络请求。
"""
import importlib.util
import json
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent


def _load_scripts_package():
    """以显式路径加载真实 scripts 包，避免工作区多 scripts 目录造成命名空间包冲突。"""
    init_py = SKILL_DIR / "scripts" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "scripts", init_py, submodule_search_locations=[str(SKILL_DIR / "scripts")])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

from crawl_enhancer import (SmartFetcher, FetchResult, batch_smart_crawl,
                            classify_response, STATUS_OK, STATUS_EMPTY,
                            STATUS_SOFT_BLOCKED, STATUS_ERROR)
from web_recognizer import (extract_tables, extract_kv_blocks,
                            extract_article_items, extract_numbers_with_context,
                            detect_pagination, recognize_page_type,
                            smart_extract, strip_tags)
from data_aggregator import (normalize_title, title_similarity, dedupe_articles,
                             sentiment_statistics, cross_section_summary,
                             aggregate_snapshots, build_institution_brief,
                             export_markdown, export_json)
from voice_interface import VoiceChat, summarize_for_speech

DATA_DIR = SKILL_DIR / "data"
CURATED_BUNDLE = DATA_DIR / "curated.json"

# ════════════════════════ 1. 机构名单完善 ════════════════════════

NEW_CURATED = ["securities_consulting", "local_amc", "payment", "credit_rating",
               "credit_service", "mutual_insurance", "pension_mgmt",
               "wm_subsidiary", "financial_infra", "internet_loan", "fund_sales"]


def test_new_curated_files_exist_and_valid():
    """11 个新增精选名录均在合并文件 curated.json 中且为合法非空字符串数组。"""
    assert CURATED_BUNDLE.exists(), "缺少精选名录合并文件 curated.json"
    bundle = json.loads(CURATED_BUNDLE.read_text(encoding="utf-8"))
    assert isinstance(bundle, dict) and bundle, "curated.json 非法"
    for name in NEW_CURATED:
        items = bundle.get(name)
        assert isinstance(items, list) and items, f"curated.json 缺少类别 {name}"
        for it in items:
            assert isinstance(it, str) and it.strip(), f"{name} 含非法条目"


def test_category_map_covers_new_curated():
    """扩充引擎 CATEGORY_MAP 已接线全部新增名录。"""
    from institution_expander import CATEGORY_MAP
    for name in NEW_CURATED:
        assert name in CATEGORY_MAP, f"CATEGORY_MAP 缺少 {name}"
        type_name, list_file, source = CATEGORY_MAP[name]
        assert type_name and list_file and source


def test_registry_expanded():
    """registry 总数 ≥2300 家 / ≥43 类，且含全部新增类型。"""
    doc = json.loads((DATA_DIR / "institution_registry.json").read_text(encoding="utf-8"))
    cols, rows = doc["c"], doc["d"]
    i_type = cols.index("type")
    types = {r[i_type] for r in rows}
    assert len(rows) >= 2300, f"registry 仅 {len(rows)} 家"
    assert len(types) >= 43, f"registry 仅 {len(types)} 类"
    for t in ("地方资产管理公司", "支付机构", "信用评级机构", "征信与商查机构",
              "相互保险组织", "养老金管理公司", "券商资管子公司",
              "金融基础设施机构", "互联网小贷公司", "证券投资咨询机构"):
        assert t in types, f"registry 缺少类型 {t}"


def test_new_list_files_synced():
    """新增类型对应的 *_list.json 已同步落盘且 count 一致。"""
    from institution_expander import CATEGORY_MAP
    for name in NEW_CURATED:
        _, list_file, _ = CATEGORY_MAP[name]
        path = DATA_DIR / list_file
        assert path.exists(), f"缺少 {list_file}"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["count"] == len(doc["institutions"])


# ════════════════════════ 2. 爬取增强 ════════════════════════════

class _FakeResp:
    def __init__(self, text):
        self.text = text


def test_classify_response_categories():
    long_html = "<html>" + "正文内容。" * 100 + "</html>"
    assert classify_response(long_html) == STATUS_OK
    assert classify_response(None) == STATUS_ERROR
    assert classify_response("   ") == STATUS_EMPTY
    assert classify_response("请完成人机验证") == STATUS_SOFT_BLOCKED
    assert classify_response('{"a": 1}') == STATUS_OK      # JSON 短响应有效
    assert classify_response("x" * 50) == STATUS_EMPTY      # 过短非 JSON


def _fetcher_factory(pages: dict, api=None, browser_pages=None):
    """构造注入 fake 依赖的 SmartFetcher。"""
    def fake_http(url, timeout=20):
        body = pages.get(url)
        return _FakeResp(body) if body is not None else None

    calls = {"browser": []}

    def fake_browser(url):
        calls["browser"].append(url)
        return (browser_pages or {}).get(url)

    return SmartFetcher(http_fetcher=fake_http,
                        browser_fetcher=fake_browser,
                        api_lookup=lambda u: api), calls


def test_smart_fetcher_http_ok():
    page = "https://a.com/news"
    html = "<html>" + "新闻内容。" * 100 + "</html>"
    f, calls = _fetcher_factory({page: html})
    r = f.fetch(page)
    assert r.ok and r.source == "http" and r.text_len == len(html)
    assert calls["browser"] == []


def test_smart_fetcher_browser_fallback():
    page = "https://a.com/blocked"
    blocked = "请完成人机验证"
    good = "<html>" + "真实内容。" * 100 + "</html>"
    f, calls = _fetcher_factory({page: blocked}, browser_pages={page: good})
    r = f.fetch(page)
    assert r.ok and r.source == "browser"
    assert calls["browser"] == [page]


def test_smart_fetcher_api_priority():
    page = "https://a.com/spa"
    api_url = "https://a.com/api/list?page=1"
    f, calls = _fetcher_factory({page: "壳页面"},
                                api={"url": api_url},
                                browser_pages={page: None})
    # api 直连返回有效 JSON
    f.http_fetcher_orig = f.http_fetcher

    def fake_http(url, timeout=20):
        if url == api_url:
            return _FakeResp('{"list": [1, 2, 3]}')
        return _FakeResp("壳页面")
    f.http_fetcher = fake_http
    r = f.fetch(page)
    assert r.ok and r.source == "api"
    assert r.extra.get("api_url") == api_url


def test_smart_fetcher_all_fail():
    f, _ = _fetcher_factory({})
    r = f.fetch("https://a.com/none")
    assert not r.ok and r.status in (STATUS_ERROR, STATUS_EMPTY)


def test_batch_smart_crawl_stats(tmp_path):
    ok_page = "https://a.com/1"
    html = "<html>" + "内容。" * 100 + "</html>"
    f, _ = _fetcher_factory({ok_page: html})

    def fake_work(url, timeout=20):
        if url == ok_page:
            return _FakeResp(html)
        return None
    f.http_fetcher = fake_work

    dedup_file = str(tmp_path / "seen.json")
    out = batch_smart_crawl(
        [ok_page, "https://a.com/bad", ok_page],   # 第 3 个为重复
        concurrency=2, dedup_file=dedup_file, fetcher=f)
    stats = out["stats"]
    assert stats["total"] == 3
    assert stats["skipped_dup"] == 1
    assert stats["fetched"] == 2
    assert stats["ok"] == 1
    assert stats["success_rate"] == 0.5
    assert stats["by_status"].get(STATUS_OK) == 1
    assert "a.com" in stats["by_domain"]
    # 去重文件已持久化
    assert Path(dedup_file).exists()


# ════════════════════════ 3. 网页内容识别 ════════════════════════

LIST_HTML = """
<html><body>
<ul>
<li><a href="/news/1001.html">央行宣布下调存款准备金率</a>
    <span class="time">2026-08-20 09:30</span></li>
<li><a href="/news/1002.html">多家银行下调存款利率引发关注</a>
    <span>2026-08-19</span></li>
<li><a href="/news/1003.html">基金发行市场回暖迹象明显</a><span>昨天</span></li>
<li><a href="/news/1004.html">券商资管新规征求意见稿发布</a></li>
<li><a href="/news/1005.html">保险资金入市规模持续扩大</a></li>
<li><a href="/news/1006.html">信托行业转型方向逐渐清晰</a></li>
<li><a href="javascript:void(0)">登录</a></li>
<li><a href="/about">关于我们</a></li>
</ul>
<a href="/news?page=2">下一页</a>
<a href="/news?page=5">5</a>
</body></html>
"""

DATA_HTML = """
<html><body>
<div class="fund_info">最新净值: 1.2345　日增长率: +0.85%　基金规模: 120.5亿元</div>
<dl><dt>成立日期</dt><dd>2015-03-01</dd><dt>基金经理</dt><dd>张三</dd></dl>
<table><tr><th>年度</th><th>收益率</th></tr>
<tr><td>2024</td><td>12.5%</td></tr>
<tr><td>2025</td><td>-3.2%</td></tr></table>
</body></html>
"""

ARTICLE_HTML = "<html><body>" + (
    "<p>贵州茅台2026年上半年实现营业收入819.3亿元，同比增长17.8%。"
    "净利润416.96亿元，同比增长15.2%。公司表示将继续加大市场投入。</p>"
    * 6) + "</body></html>"


def test_strip_tags():
    assert strip_tags("<p>hello <b>world</b></p>") == "hello world"
    assert strip_tags("<script>a=1</script>x") == "x"


def test_extract_tables():
    tables = extract_tables(DATA_HTML)
    assert len(tables) == 1
    t = tables[0]
    assert t["headers"] == ["年度", "收益率"]
    assert t["n_rows"] == 2 and t["n_cols"] == 2
    assert t["rows"][0] == ["2024", "12.5%"]


def test_extract_kv_blocks():
    kv = extract_kv_blocks(DATA_HTML)
    assert kv.get("成立日期") == "2015-03-01"
    assert kv.get("基金经理") == "张三"
    assert kv.get("最新净值") == "1.2345"
    assert kv.get("基金规模") == "120.5亿元"


def test_extract_article_items():
    items = extract_article_items(LIST_HTML, base_url="https://news.example.com")
    titles = [i["title"] for i in items]
    assert "央行宣布下调存款准备金率" in titles
    assert "登录" not in titles          # javascript 链接过滤
    assert "关于我们" not in titles       # 过短标题过滤
    first = items[0]
    assert first["url"].startswith("https://news.example.com/news/")
    dated = [i for i in items if i.get("date")]
    assert any(d["date"].startswith("2026-08-20") for d in dated)


def test_detect_pagination():
    pag = detect_pagination(LIST_HTML, base_url="https://news.example.com")
    assert pag["has_page_param"] is True
    assert pag["max_page"] == 5
    assert pag["next_url"] and "page=2" in pag["next_url"]


def test_extract_numbers_with_context():
    nums = extract_numbers_with_context(ARTICLE_HTML)
    raws = [n["raw"] for n in nums]
    assert any("819.3" in r and "亿" in r for r in raws)
    assert any("17.8" in r and "%" in r for r in raws)
    for n in nums:
        assert n["context"]


def test_recognize_page_type():
    assert recognize_page_type(LIST_HTML, "https://news.example.com/news") == "list"
    assert recognize_page_type(DATA_HTML, "https://fund.example.com/fund/123") == "data"
    assert recognize_page_type(ARTICLE_HTML, "https://x.com/a/1.html") == "article"
    assert recognize_page_type("", "") == "unknown"


def test_smart_extract_list_page():
    out = smart_extract(LIST_HTML, url="https://news.example.com/news")
    assert out["page_type"] == "list"
    assert len(out["articles"]) >= 5
    assert out["pagination"]["max_page"] == 5


def test_smart_extract_data_page():
    out = smart_extract(DATA_HTML, url="https://fund.example.com/fund/1")
    assert out["page_type"] == "data"
    assert out["tables"] and out["kv"]


# ════════════════════════ 4. 数据分析汇总 ════════════════════════

def _mk_articles():
    return [
        {"title": "招商银行因违规被处罚", "target_name": "招商银行",
         "source": "财联社", "sentiment": "negative", "sentiment_score": -20.0,
         "severity": "中度舆情", "publish_time": "2026-08-20 10:00:00",
         "keywords_matched": ["处罚", "违规"]},
        {"title": "招商银行因违规被处罚（转发）", "target_name": "招商银行",
         "source": "新浪财经", "sentiment": "negative", "sentiment_score": -18.0,
         "severity": "中度舆情", "publish_time": "2026-08-20 11:00:00",
         "keywords_matched": ["处罚"]},
        {"title": "招商银行业绩稳健获机构增持", "target_name": "招商银行",
         "source": "财联社", "sentiment": "positive", "sentiment_score": 15.0,
         "severity": "低度利好", "publish_time": "2026-08-21 09:00:00",
         "keywords_matched": ["增持"]},
        {"title": "华夏基金新发产品受热捧", "target_name": "华夏基金",
         "source": "东方财富", "sentiment": "positive", "sentiment_score": 10.0,
         "severity": "低度利好", "publish_time": "2026-08-21 12:00:00",
         "keywords_matched": ["新发"]},
    ]


def test_title_similarity_and_dedupe():
    assert normalize_title("招商银行 因违规被处罚！") == "招商银行因违规被处罚"
    assert title_similarity("招商银行因违规被处罚",
                            "招商银行因违规被处罚（转发）") > 0.85
    assert title_similarity("完全不同的标题", "招商银行因违规被处罚") < 0.3
    kept = dedupe_articles(_mk_articles())
    assert len(kept) == 3     # 转发条目被去掉


def test_sentiment_statistics():
    st = sentiment_statistics(dedupe_articles(_mk_articles()))
    assert st["total"] == 3
    assert st["sentiment"]["negative"] == 1
    assert st["sentiment"]["positive"] == 2
    assert st["by_day"]["2026-08-21"] == 2
    assert ("处罚", 1) in st["hot_keywords"]   # 转发条目已去重
    assert st["neg_ratio"] == pytest.approx(1 / 3, abs=0.01)


def test_cross_section_summary():
    rows = cross_section_summary(dedupe_articles(_mk_articles()))
    cmb = next(r for r in rows if r["target_name"] == "招商银行")
    assert cmb["count"] == 2 and cmb["negative"] == 1
    # 负面占比高的排前面
    assert rows[0]["target_name"] == "招商银行"


def test_aggregate_snapshots(tmp_path):
    snap = {"snapshot_id": "s1", "created_at": "2026-08-22",
            "articles": _mk_articles()}
    (tmp_path / "snap1.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    agg = aggregate_snapshots(tmp_path)
    assert agg["snapshot_count"] == 1
    assert agg["raw_count"] == 4
    assert agg["dedup_count"] == 3
    assert agg["dedup_removed"] == 1
    assert agg["by_target"] and agg["statistics"]["total"] == 3


def test_build_institution_brief(tmp_path):
    snap = {"snapshot_id": "s1", "created_at": "2026-08-22",
            "articles": _mk_articles()}
    (tmp_path / "snap1.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    brief = build_institution_brief("招商银行", snapshot_dir=tmp_path)
    assert brief["name"] == "招商银行"
    assert brief["sentiment"] and brief["sentiment"]["total"] == 2
    assert brief["recent_titles"]


def test_export_markdown_and_json(tmp_path):
    agg = aggregate_snapshots.__wrapped__ if hasattr(
        aggregate_snapshots, "__wrapped__") else None
    snap_dir = tmp_path / "snaps"
    snap_dir.mkdir()
    (snap_dir / "s.json").write_text(
        json.dumps({"snapshot_id": "s", "articles": _mk_articles()},
                   ensure_ascii=False), encoding="utf-8")
    agg = aggregate_snapshots(snap_dir)
    md_path = tmp_path / "report.md"
    md = export_markdown(agg, md_path)
    assert md_path.exists()
    assert "# 金融数据爬取汇总报告" in md
    assert "情感分布" in md and "目标机构截面" in md
    assert "招商银行" in md
    json_path = export_json(agg, tmp_path / "agg.json")
    assert json.loads(json_path.read_text(encoding="utf-8"))["dedup_count"] == 3


# ════════════════════════ 5. 语音交互 ════════════════════════════

def test_summarize_for_speech_strips_markdown():
    reply = "## 爬取结果\n**共 32 条**\n- 负面 5 条，详见：https://x.com/a"
    out = summarize_for_speech(reply)
    assert "http" not in out
    assert "#" not in out and "**" not in out
    assert "共32条" in out or "共 32 条" in out   # 中文播报文本会去空白


def test_summarize_for_speech_truncates():
    reply = "。".join(f"第{i}条舆情内容比较长" for i in range(60))
    out = summarize_for_speech(reply, max_chars=100)
    assert len(out) <= 120
    assert out.endswith("（更多内容见终端输出）")


def test_summarize_for_speech_empty():
    assert summarize_for_speech("") == ""


def test_voice_chat_handle_text():
    spoken = []
    vc = VoiceChat(
        listen=lambda timeout=8: None,
        speak_fn=lambda t: spoken.append(t) or True,
        chat=lambda t: {"reply": f"已处理: {t}"},
        tts=True)
    reply = vc.handle_text("爬取贵州茅台最近7天的舆情")
    assert "已处理" in reply
    assert vc.history[-1]["user"] == "爬取贵州茅台最近7天的舆情"
    assert spoken, "TTS 未被调用"


def test_voice_chat_no_tts():
    vc = VoiceChat(chat=lambda t: {"reply": "ok"}, tts=False)
    assert vc.handle_text("你好") == "ok"


def test_voice_chat_run_with_fake_listen(monkeypatch):
    """max_turns 限制下，假 STT 输入能驱动完整循环。"""
    inputs = iter(["爬一下舆情", "退出"])
    spoken = []
    vc = VoiceChat(
        listen=lambda timeout=8: next(inputs, None),
        speak_fn=lambda t: spoken.append(t) or True,
        chat=lambda t: {"reply": f"回复: {t}"},
        tts=True)
    monkeypatch.setattr("voice_interface.stt_available", lambda: True)
    vc.run(max_turns=1)
    assert len(vc.history) == 1
    assert spoken


def test_voice_chat_default_engine():
    """chat=None 时自动降级内置对话引擎（sentiment_chat），返回非空回复。"""
    vc = VoiceChat(chat=None, tts=False)
    reply = vc.handle_text("你好")
    assert reply, "默认对话引擎未返回回复"


# ════════════════════════ 6. 版本一致性 ══════════════════════════

def test_init_version_is_730():
    scripts = _load_scripts_package()
    assert scripts.__version__ == "10.0.0"


def test_new_modules_importable_from_package():
    scripts = _load_scripts_package()
    for name in ("batch_smart_crawl", "smart_extract", "aggregate_snapshots",
                 "VoiceChat", "speak", "extract_tables"):
        assert hasattr(scripts, name), f"scripts 缺少导出 {name}"
