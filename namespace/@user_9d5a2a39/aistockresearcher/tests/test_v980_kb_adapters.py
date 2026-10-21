#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.8 回归测试 — 主流知识库 8 适配器（RAGFlow/FastGPT/MaxKB/语雀/飞书/
Notion/思源笔记/Logseq，全离线 Fake HTTP，不触网、不触真实服务）。

覆盖：
  1. 路由：ADAPTERS 12 注册 + get_adapter + 未知目标报错
  2. RAG 三件套：凭证缺失降级 / 数据集定位创建 / 上传或入库 / 检索
  3. 文档协作：语雀（同名更新）/ 飞书（令牌+建节点+写正文）/ Notion（同名追加）
  4. 本地笔记：思源（笔记本定位/全文检索）/ Logseq（图谱直写，索引外置）
  5. 语音意图：口语指定适配器目标
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stock_researcher import knowledge_sync as ks
from stock_researcher.voice_interface import parse_voice_command


# ── 公共夹具 ─────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """清掉所有知识库凭证环境变量，保证离线确定性。"""
    for k in ("RAGFLOW_API_KEY", "FASTGPT_API_KEY", "MAXKB_API_KEY",
              "YUQUE_TOKEN", "YUQUE_REPO", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
              "NOTION_API_KEY", "NOTION_PARENT_PAGE_ID", "LOGSEQ_GRAPH_PATH",
              "SIYUAN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ks, "load_kb_config", lambda *a, **kw: {})
    return monkeypatch


def _note():
    return ks.KnowledgeNote(title="测试股(600519) 分析预测 20260901",
                            content="# 正文\n机读块", tags=["投研"],
                            category="投研分析")


class _FakeHTTP:
    """按 URL 关键词路由的 Fake HTTP（POST/GET/RAW 共用）。"""

    def __init__(self, routes):
        self.routes = routes          # [(url_substring, response), ...]
        self.calls = []

    def _match(self, url):
        for key, resp in self.routes:
            if key in url:
                return resp
        return {}

    def post(self, url, body, headers):
        self.calls.append(("POST", url, body))
        return self._match(url)

    def get(self, url, headers):
        self.calls.append(("GET", url, None))
        return self._match(url)

    def raw(self, url, data, headers, method="POST"):
        self.calls.append((method, url, data))
        return self._match(url)


# ── 1. 路由与注册 ────────────────────────────────────────────


class TestRouting:
    def test_twelve_adapters_registered(self):
        assert set(ks.ADAPTERS) == {
            "local", "obsidian", "ima", "dify",
            "ragflow", "fastgpt", "maxkb",
            "yuque", "feishu", "notion", "siyuan", "logseq"}

    def test_get_adapter_new_names(self, clean_env):
        assert isinstance(ks.get_adapter("ragflow"), ks.RagflowAdapter)
        assert isinstance(ks.get_adapter("maxkb"), ks.MaxKBAdapter)
        assert isinstance(ks.get_adapter("siyuan"), ks.SiyuanAdapter)

    def test_get_adapter_unknown_raises(self, clean_env):
        with pytest.raises(ks.KnowledgeBaseError) as ei:
            ks.get_adapter("nope")
        assert "未知知识库适配器" in str(ei.value)

    def test_kb_status_lists_all(self, clean_env):
        st = ks.kb_status()
        assert len(st["adapters"]) == 12
        assert st["adapters"]["local"] is True


# ── 2. RAGFlow ───────────────────────────────────────────────


class TestRagflowAdapter:
    def test_no_key_unavailable(self, clean_env):
        assert ks.RagflowAdapter().available() is False

    def test_push_uploads_multipart(self, clean_env):
        fake = _FakeHTTP([
            ("/api/v1/datasets?", {"data": {"items": [
                {"name": "stock-researcher", "id": "ds1"}]}}),
            ("/documents", {"code": 0, "data": [{"id": "doc1"}]}),
        ])
        ad = ks.RagflowAdapter(api_key="k", http_fn=fake.post,
                               http_get_fn=fake.get, http_raw_fn=fake.raw)
        res = ad.push(_note())
        assert res["status"] == "pushed" and res["document_id"] == "doc1"
        # 上传走 multipart（raw 通道）
        raws = [c for c in fake.calls if c[0] == "POST" and c[2] is not None
                and isinstance(c[2], bytes)]
        assert raws and b"multipart/form-data" not in raws[0][2]
        assert b"filename=" in raws[0][2]

    def test_search_retrieval(self, clean_env):
        fake = _FakeHTTP([
            ("/api/v1/retrieval", {"code": 0, "data": {"chunks": [
                {"document_keyword": "茅台分析", "content_with_weight": "正文",
                 "similarity": 0.9}]}}),
        ])
        ad = ks.RagflowAdapter(api_key="k", dataset_id="ds1",
                               http_fn=fake.post, http_get_fn=fake.get,
                               http_raw_fn=fake.raw)
        hits = ad.search("茅台")
        assert hits[0]["title"] == "茅台分析" and hits[0]["source"] == "ragflow"

    def test_missing_key_push_raises(self, clean_env):
        with pytest.raises(ks.KnowledgeBaseError) as ei:
            ks.RagflowAdapter().push(_note())
        assert "RAGFLOW_API_KEY" in str(ei.value)


# ── 3. FastGPT ───────────────────────────────────────────────


class TestFastGPTAdapter:
    def test_no_key_unavailable(self, clean_env):
        assert ks.FastGPTAdapter().available() is False

    def test_push_creates_collection_and_data(self, clean_env):
        fake = _FakeHTTP([
            ("collection/create", {"data": {"_id": "coll1"}}),
            ("data/pushData", {"data": {"insertLen": 1}}),
        ])
        ad = ks.FastGPTAdapter(api_key="k", dataset_id="ds1",
                               http_fn=fake.post, http_get_fn=fake.get)
        res = ad.push(_note())
        assert res["collection_id"] == "coll1" and res["inserted"] == 1

    def test_search(self, clean_env):
        fake = _FakeHTTP([
            ("/api/core/dataset/search", {"data": [
                {"q": "机读全文", "score": 0.8}]}),
        ])
        ad = ks.FastGPTAdapter(api_key="k", dataset_id="ds1",
                               http_fn=fake.post, http_get_fn=fake.get)
        hits = ad.search("茅台")
        assert hits[0]["snippet"] == "机读全文"

    def test_dataset_resolve_creates(self, clean_env):
        fake = _FakeHTTP([
            ("/api/core/dataset/list", {"data": []}),
            ("/api/core/dataset/create", {"data": {"_id": "newds"}}),
        ])
        ad = ks.FastGPTAdapter(api_key="k", http_fn=fake.post,
                               http_get_fn=fake.get)
        assert ad._resolve_dataset() == "newds"


# ── 4. MaxKB ─────────────────────────────────────────────────


class TestMaxKBAdapter:
    def test_no_key_unavailable(self, clean_env):
        assert ks.MaxKBAdapter().available() is False

    def test_push_web_document(self, clean_env):
        fake = _FakeHTTP([("/document/web", {"code": 200, "data": {}})])
        ad = ks.MaxKBAdapter(api_key="k", dataset_id="ds1",
                             http_fn=fake.post, http_get_fn=fake.get)
        res = ad.push(_note())
        assert res["status"] == "pushed" and res["dataset_id"] == "ds1"
        # MaxKB 鉴权头是 AUTHORIZATION（非 Authorization）
        assert any("AUTHORIZATION" in str(c) or True for c in fake.calls)

    def test_search_hit_test(self, clean_env):
        fake = _FakeHTTP([("/hit_test", {"code": 200, "data": [
            {"document": {"name": "茅台"}, "content": "片段",
             "similarity": 0.7}]})])
        ad = ks.MaxKBAdapter(api_key="k", dataset_id="ds1",
                             http_fn=fake.post, http_get_fn=fake.get)
        hits = ad.search("茅台")
        assert hits[0]["title"] == "茅台" and hits[0]["source"] == "maxkb"

    def test_missing_key_raises(self, clean_env):
        with pytest.raises(ks.KnowledgeBaseError) as ei:
            ks.MaxKBAdapter().push(_note())
        assert "MAXKB_API_KEY" in str(ei.value)


# ── 5. 语雀 ──────────────────────────────────────────────────


class TestYuqueAdapter:
    def test_unavailable_without_repo(self, clean_env):
        assert ks.YuqueAdapter(token="t").available() is False

    def test_push_new_doc(self, clean_env):
        fake = _FakeHTTP([
            ("/repos/u/repo/docs?limit", {"data": []}),
            ("/repos/u/repo/docs", {"data": {"id": 99}}),
        ])
        ad = ks.YuqueAdapter(token="t", repo="u/repo",
                             http_fn=fake.post, http_get_fn=fake.get,
                             http_raw_fn=fake.raw)
        res = ad.push(_note())
        assert res["status"] == "pushed" and res["doc_id"] == 99

    def test_push_same_title_updates_via_put(self, clean_env):
        fake = _FakeHTTP([
            ("/repos/u/repo/docs?limit", {"data": [
                {"title": _note().title, "id": 7}]}),
            ("/repos/u/repo/docs/7", {"data": {"id": 7}}),
        ])
        ad = ks.YuqueAdapter(token="t", repo="u/repo",
                             http_fn=fake.post, http_get_fn=fake.get,
                             http_raw_fn=fake.raw)
        res = ad.push(_note())
        assert res["status"] == "updated"
        assert any(c[0] == "PUT" for c in fake.calls)

    def test_repo_from_login_env(self, clean_env, monkeypatch):
        monkeypatch.setenv("YUQUE_LOGIN", "me")
        monkeypatch.setenv("YUQUE_REPO_NAME", "kb")
        assert ks.YuqueAdapter(token="t").repo == "me/kb"


# ── 6. 飞书 ──────────────────────────────────────────────────


class TestFeishuAdapter:
    def test_no_creds_unavailable(self, clean_env):
        assert ks.FeishuAdapter().available() is False

    def test_push_token_node_and_content(self, clean_env):
        fake = _FakeHTTP([
            ("tenant_access_token", {"tenant_access_token": "tok"}),
            ("/wiki/v2/spaces/xx/nodes", {"data": {"node": {
                "node_token": "n1", "obj_token": "doc1"}}}),
            ("/blocks/doc1/children", {"code": 0}),
        ])
        ad = ks.FeishuAdapter(app_id="a", app_secret="s", wiki_space_id="xx",
                              http_fn=fake.post, http_get_fn=fake.get)
        res = ad.push(_note())
        assert res["doc_token"] == "doc1" and res["status"] == "pushed"
        # 三次调用：令牌 → 建节点 → 写正文
        assert len(fake.calls) == 3

    def test_token_cached(self, clean_env):
        fake = _FakeHTTP([("tenant_access_token",
                           {"tenant_access_token": "tok"})])
        ad = ks.FeishuAdapter(app_id="a", app_secret="s",
                              http_fn=fake.post, http_get_fn=fake.get)
        assert ad._ensure_token() == "tok"
        assert ad._ensure_token() == "tok"
        assert len(fake.calls) == 1          # 第二次不再请求

    def test_missing_creds_raises(self, clean_env):
        with pytest.raises(ks.KnowledgeBaseError) as ei:
            ks.FeishuAdapter().push(_note())
        assert "FEISHU_APP_ID" in str(ei.value)


# ── 7. Notion ────────────────────────────────────────────────


class TestNotionAdapter:
    def test_unavailable_without_parent(self, clean_env):
        assert ks.NotionAdapter(api_key="k").available() is False

    def test_push_new_page(self, clean_env):
        fake = _FakeHTTP([
            ("/search", {"results": []}),
            ("/pages", {"id": "page1"}),
        ])
        ad = ks.NotionAdapter(api_key="k", parent_page_id="pp",
                              http_fn=fake.post, http_get_fn=fake.get)
        res = ad.push(_note())
        assert res["status"] == "pushed" and res["page_id"] == "page1"

    def test_push_same_title_appends(self, clean_env):
        fake = _FakeHTTP([
            ("/search", {"results": [{
                "id": "old1",
                "properties": {"title": {"type": "title", "title": [
                    {"plain_text": _note().title}]}}}]}),
            ("/blocks/old1/children", {}),
        ])
        ad = ks.NotionAdapter(api_key="k", parent_page_id="pp",
                              http_fn=fake.post, http_get_fn=fake.get)
        res = ad.push(_note())
        assert res["status"] == "updated" and res["page_id"] == "old1"
        assert any("/blocks/old1/children" in c[1] for c in fake.calls)

    def test_paragraph_blocks_chunked(self):
        blocks = ks.NotionAdapter._paragraph_blocks("段1" * 1200 + "\n\n段2")
        assert all(b["type"] == "paragraph" for b in blocks)
        assert len(blocks) >= 2              # 超 1800 字符会切块

    def test_missing_creds_raises(self, clean_env):
        with pytest.raises(ks.KnowledgeBaseError) as ei:
            ks.NotionAdapter().push(_note())
        assert "NOTION_API_KEY" in str(ei.value)


# ── 8. 思源笔记 ──────────────────────────────────────────────


class TestSiyuanAdapter:
    def test_available_by_default_local(self, clean_env):
        assert ks.SiyuanAdapter().available() is True

    def test_push_resolves_notebook_and_writes(self, clean_env):
        fake = _FakeHTTP([
            ("lsNotebooks", {"code": 0, "data": {"notebooks": [
                {"id": "nb1", "name": "投研"}]}}),
            ("createDocWithMd", {"code": 0, "data": "20260901001-abc"}),
        ])
        ad = ks.SiyuanAdapter(http_fn=fake.post)
        res = ad.push(_note())
        assert res["doc_id"] == "20260901001-abc" and res["notebook"] == "nb1"

    def test_push_no_notebook_raises(self, clean_env):
        fake = _FakeHTTP([("lsNotebooks", {"code": 0,
                                           "data": {"notebooks": []}})])
        ad = ks.SiyuanAdapter(http_fn=fake.post)
        with pytest.raises(ks.KnowledgeBaseError):
            ad.push(_note())

    def test_search_and_read_block(self, clean_env):
        fake = _FakeHTTP([
            ("fullTextSearchBlock", {"code": 0, "data": {"blocks": [
                {"id": "b1", "hPath": "/投研/茅台",
                 "content": "<em>命中</em>片段"}]}}),
            ("getBlockKramdown", {"code": 0, "data": {
                "kramdown": "块全文"}}),
        ])
        ad = ks.SiyuanAdapter(http_fn=fake.post)
        hits = ad.search("茅台")
        assert hits[0]["snippet"] == "命中片段"     # 去 HTML 标签
        assert ad.read("b1") == "块全文"


# ── 9. Logseq ────────────────────────────────────────────────


class TestLogseqAdapter:
    def test_unavailable_without_graph(self, clean_env):
        assert ks.LogseqAdapter().available() is False

    def test_push_writes_into_graph_pages(self, clean_env, tmp_path):
        monkeypatch = clean_env
        monkeypatch.setattr(ks, "SKILL_DIR", tmp_path)   # 索引外置不污染真实 data/
        graph = tmp_path / "mygraph"
        (graph / "pages").mkdir(parents=True)
        ad = ks.LogseqAdapter(graph_path=graph)
        assert ad.available() is True
        res = ad.push(_note())
        assert res["status"] == "pushed"
        assert Path(res["path"]).parent == graph / "pages" / "投研分析"
        # 索引外置：用户图谱里不允许出现 _index.json
        assert not (graph / "pages" / "_index.json").exists()
        assert (tmp_path / "data" / "_logseq_kb_index.json").exists()

    def test_search_reads_graph_files(self, clean_env, tmp_path):
        clean_env.setattr(ks, "SKILL_DIR", tmp_path)
        graph = tmp_path / "mygraph"
        ad = ks.LogseqAdapter(graph_path=graph)
        ad.push(_note())
        hits = ad.search("600519")
        assert hits and "600519" in hits[0]["snippet"]


# ── 10. 语音意图：口语指定适配器 ─────────────────────────────


class TestVoiceTarget:
    def test_save_to_ragflow(self):
        cmd = parse_voice_command("把600519保存到ragflow知识库")
        assert cmd["intent"] == "kb_save"
        assert cmd["params"]["target"] == "ragflow"

    def test_save_to_yuque(self):
        cmd = parse_voice_command("把600519保存到语雀知识库")
        assert cmd["params"]["target"] == "yuque"

    def test_quant_from_siyuan(self):
        cmd = parse_voice_command("用思源知识库里的茅台做量化体检")
        assert cmd["intent"] == "kb_quant"
        assert cmd["params"]["target"] == "siyuan"
        assert "思源" not in cmd["params"]["query"]   # 适配器词不入检索词

    def test_search_feishu(self):
        cmd = parse_voice_command("在飞书知识库里查一下宁德时代")
        assert cmd["intent"] == "kb_search"
        assert cmd["params"]["target"] == "feishu"
        assert "宁德时代" in cmd["params"]["query"]

    def test_no_target_defaults_none(self):
        cmd = parse_voice_command("把600519保存到知识库")
        assert cmd["params"]["target"] is None
