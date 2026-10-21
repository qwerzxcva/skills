# -*- coding: utf-8 -*-
"""v7.6.0 升级回归测试 — 知识库总结同步与校对

覆盖：
1. 按需总结：overall / target / negative 三种需求模式 + 自定义需求写入
2. 适配器：Local（幂等/检索）/ Obsidian（vault 落盘）/
   IMA（凭证校验/创建笔记/关联知识库/检索）/ Dify（定位库/新增/更新/检索）
3. 同步引擎：推送统计 + 同步日志落盘 + 单篇失败不阻断
4. 校对：数字事实抽取 + verified / conflict / no_match 判定
5. CLI：run_knowledge.py（--search / --output 预览，输出隔离到临时目录）
全部离线（FakeSession 注入 / 模块属性 monkeypatch），不发网络请求、
不写真实项目目录。
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import knowledge_sync as ks
from knowledge_sync import (KnowledgeNote, summarize_to_notes,
                            LocalKnowledgeAdapter, ObsidianAdapter,
                            ImaAdapter, DifyAdapter, get_adapter,
                            sync_to_knowledge_base, extract_facts,
                            verify_against_knowledge_base,
                            load_kb_config, save_kb_config,
                            KnowledgeBaseError)

SKILL_DIR = Path(__file__).resolve().parent.parent


# ──────────────── 通用假对象 ────────────────

class FakeResp:
    def __init__(self, payload, code=200):
        self.code = code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)
        self.content = self.text.encode("utf-8")
        self.headers = {}

    def json(self):
        return self._payload


class FakeSession:
    """按调用次序弹出响应的假 session（兼容 http_get/http_post）。"""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def _pop(self, url, record):
        self.calls.append(record)
        item = self.outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, headers=None, timeout=30, **kw):
        return self._pop(url, {"method": "GET", "url": url,
                               "headers": dict(headers or {})})

    def post(self, url, data=None, json_body=None, headers=None,
             timeout=30, **kw):
        return self._pop(url, {"method": "POST", "url": url,
                               "json": json_body,
                               "headers": dict(headers or {})})


def make_agg():
    """构造一个聚合结果（3 条文章，1 负面）。"""
    arts = [
        {"title": "招商银行因违规被处罚", "source": "东财",
         "sentiment": "negative", "severity": "重大",
         "sentiment_score": -0.8, "publish_time": "2026-08-20 10:00:00",
         "url": "https://a.cn/1", "target_name": "招商银行",
         "keywords_matched": ["处罚"], "content": "营收 100.5 亿元"},
        {"title": "招商银行发布中报业绩", "source": "新浪",
         "sentiment": "positive", "severity": "中性",
         "sentiment_score": 0.6, "publish_time": "2026-08-21 09:00:00",
         "url": "https://a.cn/2", "target_name": "招商银行",
         "keywords_matched": ["业绩"], "content": ""},
        {"title": "贵州茅台获机构调研", "source": "财联社",
         "sentiment": "neutral", "severity": "中性",
         "sentiment_score": 0.0, "publish_time": "2026-08-22 11:00:00",
         "url": "https://a.cn/3", "target_name": "贵州茅台",
         "keywords_matched": [], "content": ""},
    ]
    return {"generated_at": "2026-09-01 10:00:00", "snapshot_count": 2,
            "raw_count": 3, "dedup_count": 3, "dedup_removed": 0,
            "statistics": {"total": 3,
                           "sentiment": {"negative": 1, "positive": 1,
                                         "neutral": 1},
                           "severity": {"重大": 1, "中性": 2},
                           "source_top": [["东财", 1]],
                           "by_day": {"2026-08-20": 1},
                           "hot_keywords": [["处罚", 1]],
                           "avg_score": -0.067, "neg_ratio": 0.333,
                           "pos_ratio": 0.333},
            "by_target": [], "by_source": [], "articles": arts}


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("http_utils.time.sleep"):
        yield


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """同步日志/配置全部指向临时目录，且清空知识库相关环境变量。"""
    monkeypatch.setattr(ks, "SYNC_LOG", tmp_path / "_sync_log.json")
    monkeypatch.setattr(ks, "load_kb_config", lambda path=None: {})
    monkeypatch.setattr(ks, "_ima_credentials",
                        lambda: {"client_id": "", "api_key": ""})
    for ev in ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY",
               "IMA_KNOWLEDGE_BASE_ID", "DIFY_API_KEY", "DIFY_BASE_URL",
               "DIFY_DATASET_ID", "OBSIDIAN_VAULT_PATH"):
        monkeypatch.delenv(ev, raising=False)


# ════════════════ 1. 按需总结 ════════════════

class TestSummarize:
    def test_overall_contains_requirement(self):
        notes = summarize_to_notes(make_agg(), mode="overall",
                                   requirement="重点看处罚类事件")
        assert len(notes) == 1
        n = notes[0]
        assert "总体汇总" in n.title
        assert "重点看处罚类事件" in n.content
        assert "招商银行因违规被处罚" in n.content
        fm = n.to_frontmatter_markdown()
        assert fm.startswith("---") and "tags:" in fm

    def test_target_mode_filters(self):
        notes = summarize_to_notes(make_agg(), mode="target", target="招商银行")
        assert len(notes) == 1
        assert "招商银行" in notes[0].title
        assert "贵州茅台" not in notes[0].content
        assert "负面 1 条" in notes[0].content

    def test_target_requires_name(self):
        with pytest.raises(ValueError):
            summarize_to_notes(make_agg(), mode="target", target="")

    def test_negative_mode_sorted_by_severity(self):
        agg = make_agg()
        agg["articles"].append(
            {"title": "轻度负面事件", "source": "x", "sentiment": "negative",
             "severity": "一般", "sentiment_score": -0.2,
             "publish_time": "2026-08-23 10:00:00", "target_name": ""})
        notes = summarize_to_notes(agg, mode="negative")
        assert len(notes) == 1
        body = notes[0].content
        # 更严重（分数更低）的条目排在前面
        assert body.index("招商银行因违规被处罚") < body.index("轻度负面事件")
        assert "风险" in notes[0].tags

    def test_empty_returns_no_notes(self):
        empty = make_agg()
        empty["articles"] = []
        assert summarize_to_notes(empty) == []


# ════════════════ 2. Local / Obsidian 适配器 ════════════════

def _note(title="招商银行舆情总结 20260901", content="营收 100.5 亿元"):
    return KnowledgeNote(title=title, content=content, tags=["测试"],
                         category="机构舆情")


class TestLocalAdapter:
    def test_push_and_index(self, tmp_path):
        ad = LocalKnowledgeAdapter(tmp_path / "kb")
        r = ad.push(_note())
        assert r["status"] == "pushed" and Path(r["path"]).exists()
        text = Path(r["path"]).read_text(encoding="utf-8")
        assert "营收 100.5 亿元" in text and text.startswith("---")
        idx = json.loads((tmp_path / "kb" / "_index.json")
                         .read_text(encoding="utf-8"))
        assert len(idx["entries"]) == 1

    def test_idempotent_by_digest(self, tmp_path):
        ad = LocalKnowledgeAdapter(tmp_path / "kb")
        ad.push(_note())
        r2 = ad.push(_note())
        assert r2["status"] == "skipped"

    def test_name_collision_gets_suffix(self, tmp_path):
        ad = LocalKnowledgeAdapter(tmp_path / "kb")
        ad.push(_note(content="版本一"))
        r2 = ad.push(_note(content="版本二"))   # 同标题不同内容
        assert r2["status"] == "pushed"
        assert r2["path"].endswith("_1.md")

    def test_search_hits_keyword(self, tmp_path):
        ad = LocalKnowledgeAdapter(tmp_path / "kb")
        ad.push(_note())
        ad.push(_note(title="贵州茅台调研纪要", content="机构调研"))
        hits = ad.search("招商银行 处罚")
        assert hits and "招商银行" in hits[0]["title"]


class TestObsidianAdapter:
    def test_writes_into_vault(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ad = ObsidianAdapter(vault_path=vault)
        assert ad.available()
        r = ad.push(_note())
        assert r["status"] == "pushed"
        files = list(vault.rglob("*.md"))
        assert len(files) == 1 and files[0].name != "_index.json"

    def test_unavailable_without_vault(self, tmp_path):
        ad = ObsidianAdapter(vault_path=tmp_path / "not-exists")
        assert not ad.available()


# ════════════════ 3. IMA 适配器 ════════════════

class TestImaAdapter:
    def test_requires_credentials(self):
        ad = ImaAdapter()
        assert not ad.available()
        with pytest.raises(KnowledgeBaseError):
            ad.push(_note())

    def test_push_creates_note_and_links(self):
        fs = FakeSession([FakeResp({"code": 0, "data": {"note_id": "n1"}}),
                          FakeResp({"code": 0})])
        ad = ImaAdapter(client_id="cid", api_key="key",
                        knowledge_base_id="kb1", session=fs)
        r = ad.push(_note())
        assert r["note_id"] == "n1" and r.get("linked") is True
        # 第一步创建笔记，第二步关联知识库
        assert fs.calls[0]["url"].endswith("/openapi/note/v1/import_doc")
        assert fs.calls[0]["json"]["content_format"] == 1
        assert fs.calls[1]["url"].endswith("/openapi/wiki/v1/add_knowledge")
        assert fs.calls[1]["json"]["media_type"] == 11
        assert fs.calls[0]["headers"]["ima-openapi-clientid"] == "cid"

    def test_push_without_kb_id_skips_link(self):
        fs = FakeSession([FakeResp({"code": 0, "data": {"note_id": "n2"}})])
        ad = ImaAdapter(client_id="cid", api_key="key", session=fs)
        r = ad.push(_note())
        assert r["note_id"] == "n2" and "linked" not in r
        assert len(fs.calls) == 1

    def test_api_error_raises(self):
        fs = FakeSession([FakeResp({"code": 1001, "msg": "auth fail"})])
        ad = ImaAdapter(client_id="cid", api_key="bad", session=fs)
        with pytest.raises(KnowledgeBaseError):
            ad.push(_note())

    def test_search_parses_items(self):
        fs = FakeSession([FakeResp({"code": 0, "data": {"items": [
            {"title": "招商银行处罚通报", "content": "罚款 300 万元"}]}})])
        ad = ImaAdapter(client_id="cid", api_key="key",
                        knowledge_base_id="kb1", session=fs)
        hits = ad.search("招商银行", limit=5)
        assert hits[0]["title"] == "招商银行处罚通报"
        assert fs.calls[0]["json"]["knowledge_base_id"] == "kb1"


# ════════════════ 4. Dify 适配器 ════════════════

class TestDifyAdapter:
    def test_requires_key(self):
        ad = DifyAdapter()
        assert not ad.available()
        with pytest.raises(KnowledgeBaseError):
            ad.push(_note())

    def test_push_new_document(self):
        fs = FakeSession([
            FakeResp({"data": [{"id": "ds1", "name": "cn-financial-scraper"}]}),
            FakeResp({"data": []}),                       # 无同名文档
            FakeResp({"document": {"id": "doc1"}}),       # create-by-text
        ])
        ad = DifyAdapter(api_key="dk", session=fs)
        r = ad.push(_note())
        assert r["status"] == "pushed" and r["dataset_id"] == "ds1"
        assert fs.calls[2]["url"].endswith("/document/create-by-text")
        assert fs.calls[2]["headers"]["Authorization"] == "Bearer dk"
        assert fs.calls[2]["json"]["doc_language"] == "Chinese"

    def test_push_updates_existing_document(self):
        fs = FakeSession([
            FakeResp({"data": [{"id": "ds1", "name": "cn-financial-scraper"}]}),
            FakeResp({"data": [{"id": "doc9", "name": _note().title}]}),
            FakeResp({"document": {"id": "doc9"}}),       # update-by-text
        ])
        ad = DifyAdapter(api_key="dk", session=fs)
        r = ad.push(_note())
        assert r["status"] == "updated"
        assert "/documents/doc9/update-by-text" in fs.calls[2]["url"]

    def test_creates_dataset_when_absent(self):
        fs = FakeSession([
            FakeResp({"data": []}),                       # 列表为空
            FakeResp({"id": "ds-new"}),                   # 创建知识库
            FakeResp({"data": []}),                       # 无同名文档
            FakeResp({"document": {"id": "d1"}}),
        ])
        ad = DifyAdapter(api_key="dk", session=fs)
        r = ad.push(_note())
        assert r["dataset_id"] == "ds-new"
        assert fs.calls[1]["url"].endswith("/v1/datasets")

    def test_search_parses_records(self):
        fs = FakeSession([
            FakeResp({"data": [{"id": "ds1", "name": "cn-financial-scraper"}]}),
            FakeResp({"records": [{"segment": {
                "content": "营收 100.5 亿元",
                "document": {"name": "汇总笔记"}}, "score": 0.9}]}),
        ])
        ad = DifyAdapter(api_key="dk", session=fs)
        hits = ad.search("招商银行 营收")
        assert hits[0]["snippet"] == "营收 100.5 亿元"
        assert "/retrieve" in fs.calls[1]["url"]


# ════════════════ 5. 同步引擎 ════════════════

class TestSync:
    def test_sync_local_and_log(self, tmp_path):
        ad = LocalKnowledgeAdapter(tmp_path / "kb")
        res = sync_to_knowledge_base(agg=make_agg(), adapter=ad)
        assert res["pushed"] == 1 and not res["failed"]
        log = json.loads(ks.SYNC_LOG.read_text(encoding="utf-8"))
        assert log[-1]["target"] == "local" and log[-1]["pushed"] == 1

    def test_empty_data_short_circuits(self, tmp_path):
        empty = make_agg()
        empty["articles"] = []
        res = sync_to_knowledge_base(agg=empty,
                                     adapter=LocalKnowledgeAdapter(tmp_path))
        assert res["pushed"] == 0 and "快照为空" in res["message"]

    def test_single_note_failure_does_not_block(self, tmp_path):
        class Boom(LocalKnowledgeAdapter):
            def push(self, note):
                raise KnowledgeBaseError("模拟远端故障")
        agg = make_agg()
        res = sync_to_knowledge_base(agg=agg, mode="overall",
                                     adapter=Boom(tmp_path / "kb"))
        assert res["pushed"] == 0 and len(res["failed"]) == 1
        assert "模拟远端故障" in res["failed"][0]["error"]

    def test_get_adapter_unknown_name(self):
        with pytest.raises(KnowledgeBaseError):
            get_adapter("notion")

    def test_config_save_load(self, tmp_path):
        p = tmp_path / "cfg.json"
        save_kb_config({"target": "obsidian"}, p)
        assert load_kb_config(p)["target"] == "obsidian"


# ════════════════ 6. 知识库校对 ════════════════

class TestVerify:
    def test_extract_facts(self):
        facts = extract_facts("2026 中报营收 100.5 亿元，因违规被罚款 300 万元")
        labels = {f["label"] for f in facts}
        assert "营收" in labels and "罚款" in labels
        rev = [f for f in facts if f["label"] == "营收"][0]
        assert rev["value"] == "100.5"

    def test_verified_conflict_and_no_match(self, tmp_path):
        kb = LocalKnowledgeAdapter(tmp_path / "kb")
        kb.push(KnowledgeNote(title="招商银行因违规被处罚",
                              content="营收 100.5 亿元", category="机构舆情"))

        class Searcher(LocalKnowledgeAdapter):
            """返回知识库全文作为检索片段（模拟远端检索）。"""
            def search(self, query, limit=5):
                idx = self._load_index()
                out = []
                for e in idx["entries"]:
                    p = Path(e["path"])
                    out.append({"title": e["title"],
                                "snippet": p.read_text(encoding="utf-8")})
                return out[:limit]

        items = [
            {"title": "招商银行因违规被处罚", "content": "营收 100.5 亿元"},
            {"title": "平安银行无关新闻", "content": ""},
        ]
        report = verify_against_knowledge_base(items, adapter=Searcher(tmp_path / "kb"))
        assert report["verified"] == 1 and report["no_match"] == 1
        assert not [r for r in report["results"] if r["status"] == "conflict"]

    def test_number_conflict_detected(self, tmp_path):
        kb = LocalKnowledgeAdapter(tmp_path / "kb")
        kb.push(KnowledgeNote(title="招商银行因违规被处罚",
                              content="营收 999.0 亿元", category="机构舆情"))

        class Searcher(LocalKnowledgeAdapter):
            def search(self, query, limit=5):
                idx = self._load_index()
                return [{"title": e["title"],
                         "snippet": Path(e["path"]).read_text(encoding="utf-8")}
                        for e in idx["entries"][:limit]]

        # 注意：库中条目正文的“营收 999.0”与爬取的“营收 100.5”冲突
        items = [{"title": "招商银行因违规被处罚", "content": "营收 100.5 亿元"}]
        report = verify_against_knowledge_base(items, adapter=Searcher(tmp_path / "kb"))
        r = report["results"][0]
        assert r["status"] == "conflict"
        assert r["conflicts"][0]["label"] == "营收"
        assert r["conflicts"][0]["crawled"] == "100.5"
        assert r["conflicts"][0]["knowledge"] == ["999.0"]


# ════════════════ 7. CLI ════════════════

class TestCLI:
    def test_cli_search_with_patched_adapter(self, capsys):
        class FakeAdapter:
            name = "fake"
            def search(self, query, limit=5):
                return [{"title": "命中条目", "snippet": query}]
        import run_knowledge
        with patch.object(ks, "get_adapter", lambda name=None, **kw: FakeAdapter()):
            rc = run_knowledge.main(["--search", "招商银行", "--target", "local"])
        assert rc == 0
        assert "命中条目" in capsys.readouterr().out

    def test_cli_preview_output_isolated(self, tmp_path, capsys):
        """--output 必须落到调用方指定目录，不污染真实项目。"""
        snap_dir = tmp_path / "snaps"
        snap_dir.mkdir()
        (snap_dir / "s1.json").write_text(json.dumps({
            "articles": [{"title": "测试文章", "source": "src",
                          "sentiment": "positive", "severity": "中性",
                          "publish_time": "2026-08-30 10:00:00",
                          "sentiment_score": 0.5, "url": "https://x.cn",
                          "target_name": "测试机构"}]},
            ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "preview.md"
        # 直接调用 summarize（依赖 aggregate_snapshots 真实目录）→ 注入临时快照目录后 patch 返回值
        orig = ks.aggregate_snapshots
        agg = orig(snapshot_dir=snap_dir)
        with patch.object(ks, "aggregate_snapshots",
                          lambda snapshot_dir=None, days=0: agg):
            import run_knowledge
            rc = run_knowledge.main(["--mode", "overall", "--output", str(out)])
        assert rc == 0
        assert out.exists() and "总体汇总" in out.read_text(encoding="utf-8")
        assert not (SKILL_DIR / "preview.md").exists()

    def test_cli_verify(self, tmp_path, capsys):
        kb = LocalKnowledgeAdapter(tmp_path / "kb")
        kb.push(KnowledgeNote(title="测试文章", content="无数字", category="x"))
        items_file = tmp_path / "items.json"
        items_file.write_text(json.dumps(
            [{"title": "测试文章", "content": ""}], ensure_ascii=False),
            encoding="utf-8")
        with patch.object(ks, "get_adapter",
                          lambda name=None, **kw: LocalKnowledgeAdapter(tmp_path / "kb")):
            import run_knowledge
            rc = run_knowledge.main(["--verify", str(items_file),
                                     "--target", "local"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["verified"] == 1


# ════════════════ 8. 版本同步 ════════════════

class TestVersion:
    def test_skill_version_bumped(self):
        import scripts
        assert scripts.__version__ == "10.0.0"
        meta = json.loads((SKILL_DIR / "_meta.json").read_text(encoding="utf-8"))
        assert meta["version"] == "10.0.0"
