#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9.7 回归测试 — 知识库双向交互（IMA / Dify / Obsidian / 本地，全离线）。

覆盖：
  1. KnowledgeNote / build_analysis_note：frontmatter 渲染 + 机读 JSON 块
  2. LocalKnowledgeAdapter：写入 / MD5 幂等 / 关键词检索 / 全文回读
  3. ObsidianAdapter：Vault 直写 / 无 Vault 不可用
  4. ImaAdapter：凭证缺失降级 / import_doc+add_knowledge / search（Fake HTTP）
  5. DifyAdapter：Key 缺失降级 / dataset 定位与创建 / 同名更新 / retrieve（Fake HTTP）
  6. 双向引擎：save_analysis_to_kb（含同步日志）/ load_kb_data / kb_quant_forecast
  7. 语音意图：知识库保存 / 检索 / 回读量化 解析
"""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from stock_researcher import knowledge_sync as ks
from stock_researcher.voice_interface import parse_voice_command


# ── 公共夹具 ─────────────────────────────────────────────────


@pytest.fixture
def tmp_log(monkeypatch, tmp_path):
    """同步日志重定向到临时目录，不污染真实 data/。"""
    log = tmp_path / "knowledge_sync_log.json"
    monkeypatch.setattr(ks, "SYNC_LOG", log)
    return log


@pytest.fixture
def sample_result():
    return {
        "name": "测试股", "code": "600519", "market": "cn",
        "signal": "看涨", "confidence": 0.72, "summary": "测试结论",
        "price": {"price": 1500.0, "chg_pct": 1.2, "pe": 22.5},
        "technical": {"ma5": 1498, "ma20": 1480, "ma60": 1450,
                      "rsi": 61, "vol_ratio": 1.1},
        "score": {"total": 71.5},
        "monte_carlo": {"5d": {"avg": 1.2, "up": 0.66},
                        "10d": {"avg": 2.0, "up": 0.61}},
    }


@pytest.fixture
def sample_prices():
    # 正弦叠加趋势：确定性序列，历史形态可匹配（离线可预测）
    return [100 * (1 + 0.001 * i) * (1 + 0.03 * math.sin(i / 5.0))
            for i in range(120)]


def _no_ima_creds(monkeypatch):
    monkeypatch.setattr(ks, "_ima_credentials",
                        lambda: {"client_id": "", "api_key": ""})
    monkeypatch.delenv("IMA_OPENAPI_CLIENTID", raising=False)
    monkeypatch.delenv("IMA_OPENAPI_APIKEY", raising=False)


# ── 1. 笔记构建 ─────────────────────────────────────────────


class TestNoteBuilding:
    def test_frontmatter_markdown(self):
        note = ks.KnowledgeNote(title="T", content="正文",
                                tags=["a", "b"], category="投研分析")
        md = note.to_frontmatter_markdown()
        assert md.startswith("---")
        assert "title: T" in md and "tags: [a, b]" in md
        assert md.endswith("正文")

    def test_build_note_contains_human_sections(self, sample_result,
                                               sample_prices):
        note = ks.build_analysis_note("600519", sample_result, sample_prices)
        assert "测试股" in note.title and "600519" in note.title
        assert "看涨" in note.content and "71.5" in note.content
        assert "蒙特卡洛" in note.content
        assert "不构成投资建议" in note.content      # 免责声明必随笔记
        assert "stock-researcher" in note.tags

    def test_build_note_embeds_machine_json(self, sample_result,
                                            sample_prices):
        note = ks.build_analysis_note("600519", sample_result, sample_prices)
        payload = ks._extract_payload(note.content)
        assert payload is not None
        assert payload["schema"] == ks.DATA_SCHEMA
        assert payload["code"] == "600519"
        assert len(payload["prices"]) == 120
        assert payload["score"]["total"] == 71.5

    def test_build_note_truncates_prices(self, sample_result):
        prices = [100.0 + i * 0.1 for i in range(300)]
        note = ks.build_analysis_note("600519", sample_result, prices)
        payload = ks._extract_payload(note.content)
        assert len(payload["prices"]) == ks.MAX_NOTE_PRICES

    def test_build_note_rejects_error_result(self):
        with pytest.raises(ks.KnowledgeBaseError):
            ks.build_analysis_note("600519", {"error": "行情获取失败"})


# ── 2. 本地兜底库 / Obsidian ────────────────────────────────


class TestLocalAdapter:
    def test_push_and_search(self, tmp_path, sample_result, sample_prices):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        assert ad.available() is True
        note = ks.build_analysis_note("600519", sample_result, sample_prices)
        res = ad.push(note)
        assert res["status"] == "pushed"
        assert Path(res["path"]).exists()
        hits = ad.search("600519")
        assert len(hits) == 1 and "测试股" in hits[0]["title"]

    def test_push_idempotent_by_digest(self, tmp_path, sample_result):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        note = ks.build_analysis_note("600519", sample_result, [])
        assert ad.push(note)["status"] == "pushed"
        assert ad.push(note)["status"] == "skipped"     # MD5 摘要幂等

    def test_read_by_path_and_title(self, tmp_path, sample_result):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        note = ks.build_analysis_note("600519", sample_result, [])
        res = ad.push(note)
        assert ks.DATA_SCHEMA in ad.read(res["path"])
        assert ks.DATA_SCHEMA in ad.read(note.title)
        assert ad.read("不存在的笔记") == ""

    def test_safe_filename(self, tmp_path):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        note = ks.KnowledgeNote(title='非法/字符:测试*?"', content="x")
        res = ad.push(note)
        assert Path(res["path"]).exists()


class TestObsidianAdapter:
    def test_vault_write(self, tmp_path, sample_result):
        vault = tmp_path / "my-vault"
        vault.mkdir()
        ad = ks.ObsidianAdapter(vault_path=vault)
        assert ad.available() is True
        note = ks.build_analysis_note("600519", sample_result, [])
        res = ad.push(note)
        assert res["status"] == "pushed"
        text = Path(res["path"]).read_text(encoding="utf-8")
        assert "tags:" in text                          # Obsidian frontmatter

    def test_unavailable_without_vault(self, tmp_path):
        ad = ks.ObsidianAdapter(vault_path=tmp_path / "not-exists")
        assert ad.available() is False


# ── 3. IMA 适配器（Fake HTTP 全离线）────────────────────────


class TestImaAdapter:
    def test_missing_credentials_raises(self, monkeypatch, tmp_path):
        _no_ima_creds(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ad = ks.ImaAdapter()
        assert ad.available() is False
        with pytest.raises(ks.KnowledgeBaseError, match="IMA 凭证缺失"):
            ad.push(ks.KnowledgeNote(title="t", content="c"))

    def test_push_import_and_link(self, monkeypatch):
        _no_ima_creds(monkeypatch)
        calls = []

        def fake_http(url, body, headers):
            calls.append((url, body))
            if "import_doc" in url:
                return {"code": 0, "data": {"note_id": "N123"}}
            if "add_knowledge" in url:
                return {"code": 0}
            return {"code": 1, "msg": "unexpected"}

        ad = ks.ImaAdapter(client_id="cid", api_key="key",
                           knowledge_base_id="KB1", http_fn=fake_http)
        res = ad.push(ks.KnowledgeNote(title="t", content="c"))
        assert res == {"adapter": "ima", "status": "pushed",
                       "note_id": "N123", "linked": True}
        assert calls[0][1]["content_format"] == 1
        assert calls[1][1]["media_type"] == 11
        assert calls[1][1]["knowledge_base_id"] == "KB1"

    def test_push_api_error_raises(self, monkeypatch):
        _no_ima_creds(monkeypatch)
        ad = ks.ImaAdapter(client_id="cid", api_key="key",
                           http_fn=lambda u, b, h: {"code": 40001})
        with pytest.raises(ks.KnowledgeBaseError, match="import_doc"):
            ad.push(ks.KnowledgeNote(title="t", content="c"))

    def test_search(self, monkeypatch):
        _no_ima_creds(monkeypatch)

        def fake_http(url, body, headers):
            assert "search_knowledge" in url
            assert body["query"] == "茅台"
            return {"code": 0, "data": {"items": [
                {"title": "茅台分析", "content": "评分 71"}]}}

        ad = ks.ImaAdapter(client_id="cid", api_key="key", http_fn=fake_http)
        hits = ad.search("茅台", limit=3)
        assert hits[0]["title"] == "茅台分析" and hits[0]["source"] == "ima"


# ── 4. Dify 适配器（Fake HTTP 全离线）───────────────────────


class TestDifyAdapter:
    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("DIFY_API_KEY", raising=False)
        ad = ks.DifyAdapter()
        assert ad.available() is False
        with pytest.raises(ks.KnowledgeBaseError, match="Dify API Key 缺失"):
            ad.push(ks.KnowledgeNote(title="t", content="c"))

    def test_push_creates_dataset_and_document(self, monkeypatch):
        monkeypatch.delenv("DIFY_API_KEY", raising=False)
        monkeypatch.delenv("DIFY_DATASET_ID", raising=False)

        def fake_get(url, headers):
            if "/v1/datasets?" in url:
                return {"data": []}                    # 无同名知识库
            if "/documents?" in url:
                return {"data": []}                    # 无同名文档
            return {}

        def fake_post(url, body, headers):
            if url.endswith("/v1/datasets"):
                return {"id": "DS1"}                   # 创建知识库
            if "create-by-text" in url:
                return {"document": {"id": "DOC1"}}
            return {}

        ad = ks.DifyAdapter(api_key="sk-x", http_fn=fake_post,
                            http_get_fn=fake_get)
        res = ad.push(ks.KnowledgeNote(title="t", content="c"))
        assert res["status"] == "pushed"
        assert res["dataset_id"] == "DS1" and res["document_id"] == "DOC1"

    def test_push_updates_existing_document(self, monkeypatch):
        monkeypatch.delenv("DIFY_DATASET_ID", raising=False)

        def fake_get(url, headers):
            if "/documents?" in url:
                return {"data": [{"name": "t", "id": "OLD1"}]}
            return {}

        def fake_post(url, body, headers):
            assert "update-by-text" in url and "OLD1" in url
            return {"document": {"id": "OLD1"}}

        ad = ks.DifyAdapter(api_key="sk-x", dataset_id="DS1",
                            http_fn=fake_post, http_get_fn=fake_get)
        res = ad.push(ks.KnowledgeNote(title="t", content="c"))
        assert res["status"] == "updated"

    def test_retrieve(self, monkeypatch):
        def fake_post(url, body, headers):
            assert "retrieve" in url
            return {"records": [{"score": 0.9, "segment": {
                "content": "评分71", "document": {"name": "茅台分析"}}}]}

        ad = ks.DifyAdapter(api_key="sk-x", dataset_id="DS1",
                            http_fn=fake_post)
        hits = ad.search("茅台")
        assert hits[0]["title"] == "茅台分析"
        assert hits[0]["score"] == 0.9 and hits[0]["source"] == "dify"


# ── 5. 路由与双向引擎 ───────────────────────────────────────


class TestRouting:
    def test_get_adapter_default_local(self, monkeypatch):
        monkeypatch.setattr(ks, "load_kb_config", lambda path=None: {})
        ad = ks.get_adapter()
        assert isinstance(ad, ks.LocalKnowledgeAdapter)

    def test_get_adapter_by_config_target(self, monkeypatch):
        monkeypatch.setattr(ks, "load_kb_config",
                            lambda path=None: {"target": "dify"})
        ad = ks.get_adapter()
        assert isinstance(ad, ks.DifyAdapter)

    def test_get_adapter_unknown_raises(self):
        with pytest.raises(ks.KnowledgeBaseError, match="未知知识库适配器"):
            ks.get_adapter("no_such_kb")

    def test_kb_status_lists_all_adapters(self):
        st = ks.kb_status()
        assert set(st["adapters"]) == {
            "local", "obsidian", "ima", "dify", "ragflow", "fastgpt",
            "maxkb", "yuque", "feishu", "notion", "siyuan", "logseq"}
        assert st["adapters"]["local"] is True
        assert st["local_dir"].endswith("knowledge_base")


class TestSyncEngine:
    def test_save_analysis_to_kb_writes_log(self, tmp_path, tmp_log,
                                            sample_result):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        res = ks.save_analysis_to_kb("600519", sample_result, [1.0, 2.0],
                                     adapter=ad)
        assert res["ok"] is True and res["status"] == "pushed"
        log = json.loads(tmp_log.read_text(encoding="utf-8"))
        assert log[-1]["action"] == "save" and log[-1]["code"] == "600519"

    def test_save_failure_returns_error_not_raise(self, tmp_log,
                                                  sample_result):
        class Broken(ks.KnowledgeAdapter):
            name = "broken"
            def available(self):
                return True
            def push(self, note):
                raise ks.KnowledgeBaseError("boom")
        res = ks.save_analysis_to_kb("600519", sample_result,
                                     adapter=Broken())
        assert res["ok"] is False and "boom" in res["error"]

    def test_load_kb_data_roundtrip(self, tmp_path, sample_result,
                                    sample_prices):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        note = ks.build_analysis_note("600519", sample_result, sample_prices)
        ad.push(note)
        payload = ks.load_kb_data("600519", adapter=ad)
        assert payload is not None
        assert payload["code"] == "600519"
        assert len(payload["prices"]) == 120

    def test_load_kb_data_missing_returns_none(self, tmp_path):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        assert ks.load_kb_data("不存在", adapter=ad) is None

    def test_kb_quant_forecast_offline(self, tmp_path, sample_result,
                                       sample_prices):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        ad.push(ks.build_analysis_note("600519", sample_result,
                                       sample_prices))
        rep = ks.kb_quant_forecast("600519", adapter=ad)
        assert rep["ok"] is True and rep["points"] == 120
        assert rep["metrics"]["total_return_pct"] is not None
        assert rep["archived_score"] == 71.5
        # 正弦序列存在重复形态，应能给出方向预测
        assert rep["pattern_forecast"]["data_mode"] == "ok"
        assert 0 <= rep["pattern_forecast"]["prob_up"] <= 100

    def test_kb_quant_insufficient_points(self, tmp_path, sample_result):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        ad.push(ks.build_analysis_note("600519", sample_result, [1.0] * 10))
        rep = ks.kb_quant_forecast("600519", adapter=ad)
        assert rep["ok"] is False and "价格点不足" in rep["error"]

    def test_kb_quant_no_match_query(self, tmp_path):
        ad = ks.LocalKnowledgeAdapter(base_dir=tmp_path)
        rep = ks.kb_quant_forecast("不存在的标的", adapter=ad)
        assert rep["ok"] is False and "未找到" in rep["error"]


# ── 6. 语音意图接入 ─────────────────────────────────────────


class TestVoiceIntents:
    def test_kb_save_with_alias(self):
        cmd = parse_voice_command("把茅台保存到知识库")
        assert cmd["intent"] == "kb_save" and cmd["code"] == "600519"

    def test_kb_save_without_code_prompts(self):
        cmd = parse_voice_command("保存到知识库")
        assert cmd["intent"] == "kb_save" and cmd["code"] is None
        assert "哪只股票" in cmd["echo"]

    def test_kb_search(self):
        cmd = parse_voice_command("查一下知识库里的宁德时代")
        assert cmd["intent"] == "kb_search"
        assert "宁德时代" in cmd["params"]["query"]

    def test_kb_quant(self):
        cmd = parse_voice_command("用知识库里的茅台数据做量化体检")
        assert cmd["intent"] == "kb_quant"
        assert cmd["params"]["query"]

    def test_kb_not_confused_with_predict(self):
        # 无知识库关键词时仍走预测意图
        assert parse_voice_command("预测茅台")["intent"] == "predict"
