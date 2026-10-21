# -*- coding: utf-8 -*-
"""v9.8.0 知识库交互引擎 — 12 适配器覆盖主流知识库，零 pip 依赖。

能力（双向）：
  1. 保存：把分析/预测结果渲染为知识笔记（Markdown + 内嵌机器可读 JSON），
     推送到指定知识库（save_analysis_to_kb）。
  2. 回读：从知识库检索历史笔记 → 解析内嵌价格序列 → 直接跑量化体检 +
     历史形态匹配预测（kb_quant_forecast），无需重新联网拉行情。

适配器（接口统一：available / push / search / read）：
  本地型：LocalKnowledgeAdapter（兜底库）/ ObsidianAdapter（Vault 直写）/
          SiyuanAdapter（思源笔记本地 API）/ LogseqAdapter（图谱目录直写）
  云端型：ImaAdapter（腾讯 IMA）/ YuqueAdapter（语雀）/
          FeishuAdapter（飞书知识库）/ NotionAdapter（Notion 页面）
  RAG 型：DifyAdapter / RagflowAdapter / FastGPTAdapter / MaxKBAdapter

凭证（全部环境变量优先，永不落盘明文）：
  IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY（或 ~/.config/ima/client_id、api_key）
  DIFY_API_KEY / DIFY_BASE_URL / DIFY_DATASET_ID
  OBSIDIAN_VAULT_PATH / LOGSEQ_GRAPH_PATH
  RAGFLOW_API_KEY / RAGFLOW_BASE_URL；FASTGPT_API_KEY / FASTGPT_BASE_URL
  MAXKB_API_KEY / MAXKB_BASE_URL；YUQUE_TOKEN / YUQUE_LOGIN / YUQUE_REPO_NAME
  FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_WIKI_SPACE_ID
  NOTION_API_KEY / NOTION_PARENT_PAGE_ID；SIYUAN_URL / SIYUAN_TOKEN / SIYUAN_NOTEBOOK
可选配置文件：config/knowledge_config.json（target 及各适配器子配置节）

HTTP 走 urllib（受包级代理防护约束：国内直连）。测试可注入
``http_fn(url, body, headers) -> dict`` 完全离线。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "KnowledgeBaseError", "KnowledgeNote",
    "load_kb_config", "save_kb_config",
    "KnowledgeAdapter", "LocalKnowledgeAdapter", "ObsidianAdapter",
    "ImaAdapter", "DifyAdapter",
    "RagflowAdapter", "FastGPTAdapter", "MaxKBAdapter",
    "YuqueAdapter", "FeishuAdapter", "NotionAdapter",
    "SiyuanAdapter", "LogseqAdapter",
    "ADAPTERS", "get_adapter",
    "build_analysis_note", "save_analysis_to_kb",
    "search_knowledge", "load_kb_data", "kb_quant_forecast", "kb_status",
]

SKILL_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = SKILL_DIR / "config" / "knowledge_config.json"
KB_DIR = SKILL_DIR / "data" / "knowledge_base"      # 本地兜底库
SYNC_LOG = SKILL_DIR / "data" / "knowledge_sync_log.json"

# 笔记内嵌机器可读数据的 schema 标记（回读时据此定位 JSON 块）
DATA_SCHEMA = "stock-researcher/analysis@1"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(\{[\s\S]*?\})\s*\n```")

from .constants import (KB_DEFAULT_TARGET, KB_MAX_NOTE_PRICES,
                        KB_MIN_POINTS, KB_LOG_KEEP)
MAX_NOTE_PRICES = KB_MAX_NOTE_PRICES   # 每篇笔记最多内嵌价格点数（控制体积）
LOG_KEEP = KB_LOG_KEEP                 # 同步日志保留条数


class KnowledgeBaseError(Exception):
    """知识库操作失败（凭证缺失 / 接口报错 / 路径无效 / 解析失败）。"""


@dataclass
class KnowledgeNote:
    """一篇知识笔记（适配器无关的统一载体）。"""
    title: str
    content: str                                   # Markdown 正文
    tags: List[str] = field(default_factory=list)
    category: str = "投研分析"

    def to_frontmatter_markdown(self) -> str:
        """带 YAML frontmatter 的 Markdown（Obsidian 风格）。"""
        fm = ["---", f"title: {self.title}", f"category: {self.category}"]
        if self.tags:
            fm.append("tags: [" + ", ".join(self.tags) + "]")
        fm.append(f"created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        fm.append("---")
        return "\n".join(fm) + "\n\n" + self.content


# ════════════════ 1. 配置 ════════════════

def load_kb_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载 config/knowledge_config.json（不存在/损坏返回空，不抛异常）。"""
    p = Path(path) if path else CONFIG_FILE
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def save_kb_config(cfg: Dict[str, Any], path: Optional[Path] = None) -> Path:
    p = Path(path) if path else CONFIG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _ima_credentials() -> Dict[str, str]:
    """IMA 凭证：环境变量优先，其次 ~/.config/ima/client_id|api_key。"""
    cid = os.environ.get("IMA_OPENAPI_CLIENTID", "").strip()
    key = os.environ.get("IMA_OPENAPI_APIKEY", "").strip()
    if not cid or not key:
        home = Path.home() / ".config" / "ima"
        if not cid and (home / "client_id").exists():
            cid = (home / "client_id").read_text(encoding="utf-8").strip()
        if not key and (home / "api_key").exists():
            key = (home / "api_key").read_text(encoding="utf-8").strip()
    return {"client_id": cid, "api_key": key}


def _default_http_json(url: str, body: Dict[str, Any],
                       headers: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    """urllib POST JSON → 解析响应 JSON（零依赖；测试可整体替换）。"""
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _default_http_get_json(url: str, headers: Dict[str, str],
                           timeout: int = 30) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _default_http_raw(url: str, data: bytes, headers: Dict[str, str],
                      method: str = "POST", timeout: int = 30) -> Dict[str, Any]:
    """原始字节请求（multipart 上传 / PATCH / DELETE 等，测试可整体替换）。"""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="replace")
        return json.loads(body) if body.strip() else {}


def _multipart_form(fields: Dict[str, Any], filename: str,
                    content: bytes) -> tuple:
    """构造 multipart/form-data 请求体（零依赖，RAGFlow 文档上传用）。"""
    boundary = "----srkb" + hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]
    parts: List[bytes] = []
    for k, v in fields.items():
        parts += [f'--{boundary}\r\nContent-Disposition: form-data; '
                  f'name="{k}"\r\n\r\n'.encode("utf-8"),
                  str(v).encode("utf-8"), b"\r\n"]
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
              f'filename="{filename}"\r\n'
              'Content-Type: text/markdown\r\n\r\n'.encode("utf-8"),
              content, f"\r\n--{boundary}--\r\n".encode("utf-8")]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ════════════════ 2. 适配器 ════════════════

class KnowledgeAdapter:
    """知识库适配器基类：push 写入 / search 检索 / read 全文（回读用）。"""

    name = "base"

    def available(self) -> bool:                    # pragma: no cover - 子类覆盖
        raise NotImplementedError

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def read(self, ref: str) -> str:
        """按引用（路径/标题）读取全文；不支持时返回空串。"""
        return ""

    @staticmethod
    def note_digest(note: KnowledgeNote) -> str:
        return hashlib.md5((note.title + "\n" + note.content).encode("utf-8")
                           ).hexdigest()[:16]


class LocalKnowledgeAdapter(KnowledgeAdapter):
    """本地兜底知识库：data/knowledge_base/<category>/<title>.md + _index.json。"""

    name = "local"

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else KB_DIR
        self.index_file = self.base_dir / "_index.json"

    def available(self) -> bool:
        return True

    def _load_index(self) -> Dict[str, Any]:
        if self.index_file.exists():
            try:
                return json.loads(self.index_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"entries": []}

    def _save_index(self, idx: Dict[str, Any]) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(
            json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def _safe_name(title: str) -> str:
        return re.sub(r'[\\/:*?"<>|\r\n]+', "_", title).strip()[:80] or "untitled"

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        cat_dir = self.base_dir / self._safe_name(note.category)
        cat_dir.mkdir(parents=True, exist_ok=True)
        digest = self.note_digest(note)
        idx = self._load_index()
        for e in idx["entries"]:                    # 幂等：同摘要跳过
            if e.get("digest") == digest:
                return {"adapter": self.name, "status": "skipped",
                        "path": e.get("path"), "digest": digest}
        fp = cat_dir / (self._safe_name(note.title) + ".md")
        suffix = 1
        while fp.exists():
            fp = cat_dir / f"{self._safe_name(note.title)}_{suffix}.md"
            suffix += 1
        fp.write_text(note.to_frontmatter_markdown(), encoding="utf-8")
        idx["entries"].append({
            "title": note.title, "category": note.category,
            "tags": note.tags, "path": str(fp), "digest": digest,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._save_index(idx)
        return {"adapter": self.name, "status": "pushed",
                "path": str(fp), "digest": digest}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """标题/正文关键词检索（离线，按命中数排序）。"""
        kws = [w for w in re.split(r"[\s,，]+", query) if w]
        scored = []
        for e in self._load_index()["entries"]:
            path = Path(e.get("path", ""))
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            hay = (e.get("title", "") + "\n" + text).lower()
            hits = sum(hay.count(k.lower()) for k in kws)
            if hits:
                scored.append((hits, {"title": e.get("title", ""),
                                      "path": str(path),
                                      "snippet": text[:600],
                                      "category": e.get("category", "")}))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:limit]]

    def read(self, ref: str) -> str:
        p = Path(ref)
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return ""
        # ref 为标题时从索引兜底查找
        for e in self._load_index()["entries"]:
            if e.get("title") == ref and Path(e.get("path", "")).exists():
                return Path(e["path"]).read_text(encoding="utf-8")
        return ""


class ObsidianAdapter(LocalKnowledgeAdapter):
    """Obsidian Vault：直写 Markdown（Obsidian 自动索引），无 vault 时不可用。"""

    name = "obsidian"

    def __init__(self, vault_path: Optional[Path] = None):
        if vault_path is None:
            cfg = load_kb_config().get("obsidian") or {}
            vault_path = cfg.get("vault_path") or os.environ.get("OBSIDIAN_VAULT_PATH")
        super().__init__(vault_path)

    def available(self) -> bool:
        return bool(str(self.base_dir)) and Path(self.base_dir).is_dir()


class _RemoteAdapter(KnowledgeAdapter):
    """远程 JSON API 公共层：http_fn / http_get_fn / http_raw_fn 注入（测试离线）。"""

    def __init__(self, http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None,
                 http_raw_fn: Optional[Callable] = None):
        self.http_fn = http_fn or _default_http_json
        self.http_get_fn = http_get_fn or _default_http_get_json
        self.http_raw_fn = http_raw_fn or _default_http_raw

    def _post(self, url: str, body: Dict[str, Any],
              headers: Dict[str, str]) -> Dict[str, Any]:
        try:
            return self.http_fn(url, body, headers)
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(f"请求失败: {url[:90]} → {exc}") from exc

    def _get(self, url: str, headers: Dict[str, str]) -> Dict[str, Any]:
        try:
            return self.http_get_fn(url, headers)
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(f"请求失败: {url[:90]} → {exc}") from exc

    def _raw(self, url: str, data: bytes, headers: Dict[str, str],
             method: str = "POST") -> Dict[str, Any]:
        try:
            return self.http_raw_fn(url, data, headers, method)
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(f"请求失败: {url[:90]} → {exc}") from exc


class ImaAdapter(_RemoteAdapter):
    """腾讯 IMA OpenAPI：创建笔记 → 关联知识库；检索用于回读。

    端点（POST，Header: ima-openapi-clientid / ima-openapi-apikey）：
      /openapi/note/v1/import_doc        创建笔记（Markdown）
      /openapi/wiki/v1/add_knowledge     关联笔记到知识库（media_type=11）
      /openapi/wiki/v1/search_knowledge  知识库检索
    """

    name = "ima"
    BASE = "https://ima.qq.com"

    def __init__(self, client_id: str = "", api_key: str = "",
                 knowledge_base_id: str = "", http_fn: Optional[Callable] = None):
        super().__init__(http_fn)
        creds = _ima_credentials()
        self.client_id = client_id or creds["client_id"]
        self.api_key = api_key or creds["api_key"]
        self.knowledge_base_id = (
            knowledge_base_id
            or os.environ.get("IMA_KNOWLEDGE_BASE_ID", "")
            or (load_kb_config().get("ima") or {}).get("knowledge_base_id", ""))

    def available(self) -> bool:
        return bool(self.client_id and self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"ima-openapi-clientid": self.client_id,
                "ima-openapi-apikey": self.api_key}

    def _ensure_creds(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "IMA 凭证缺失：请设置 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY "
                "环境变量或 ~/.config/ima/client_id、api_key"
                "（https://ima.qq.com/agent-interface 获取）")

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure_creds()
        doc = self._post(self.BASE + "/openapi/note/v1/import_doc",
                         {"content_format": 1, "title": note.title,
                          "content": note.to_frontmatter_markdown()},
                         self._headers())
        if doc.get("code") not in (0, None):
            raise KnowledgeBaseError(f"IMA import_doc 失败: {doc}")
        note_id = (doc.get("data") or {}).get("note_id") or doc.get("note_id", "")
        result: Dict[str, Any] = {"adapter": self.name, "status": "pushed",
                                  "note_id": note_id}
        if self.knowledge_base_id and note_id:
            add = self._post(self.BASE + "/openapi/wiki/v1/add_knowledge",
                             {"media_type": 11, "title": note.title,
                              "knowledge_base_id": self.knowledge_base_id,
                              "note_id": note_id},
                             self._headers())
            result["linked"] = add.get("code") == 0
        return result

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure_creds()
        body: Dict[str, Any] = {"query": query, "cursor": "", "limit": limit}
        if self.knowledge_base_id:
            body["knowledge_base_id"] = self.knowledge_base_id
        doc = self._post(self.BASE + "/openapi/wiki/v1/search_knowledge",
                         body, self._headers())
        if doc.get("code") not in (0, None):
            raise KnowledgeBaseError(f"IMA search_knowledge 失败: {doc}")
        data = doc.get("data") or doc
        items = data.get("items") or data.get("list") or []
        return [{"title": it.get("title", ""),
                 "snippet": it.get("content", "") or it.get("summary", ""),
                 "source": "ima"} for it in items[:limit]]


class DifyAdapter(_RemoteAdapter):
    """Dify Knowledge API：create-by-text 写入 / 同名更新 / retrieve 语义检索。"""

    name = "dify"

    def __init__(self, api_key: str = "", base_url: str = "",
                 dataset_id: str = "", dataset_name: str = "stock-researcher",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn)
        cfg = load_kb_config().get("dify") or {}
        self.api_key = api_key or os.environ.get("DIFY_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DIFY_BASE_URL")
                         or cfg.get("base_url") or "https://api.dify.ai").rstrip("/")
        self.dataset_id = (dataset_id or os.environ.get("DIFY_DATASET_ID")
                           or cfg.get("dataset_id", ""))
        self.dataset_name = dataset_name or cfg.get("dataset_name",
                                                    "stock-researcher")

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _ensure_key(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "Dify API Key 缺失：请设置 DIFY_API_KEY 环境变量"
                "（Dify 控制台 → 知识库 → API 访问）")

    def _get(self, url: str) -> Dict[str, Any]:
        try:
            return self.http_get_fn(url, self._headers())
        except KnowledgeBaseError:
            raise
        except Exception as exc:
            raise KnowledgeBaseError(f"请求失败: {url[:90]} → {exc}") from exc

    def _resolve_dataset(self) -> str:
        """dataset_id 未配置时按名称查找，找不到则创建。"""
        if self.dataset_id:
            return self.dataset_id
        doc = self._get(f"{self.base_url}/v1/datasets?limit=100")
        for ds in (doc.get("data") or []):
            if ds.get("name") == self.dataset_name:
                self.dataset_id = ds["id"]
                return self.dataset_id
        created = self._post(f"{self.base_url}/v1/datasets",
                             {"name": self.dataset_name,
                              "indexing_technique": "high_quality"},
                             self._headers())
        self.dataset_id = created.get("id", "")
        if not self.dataset_id:
            raise KnowledgeBaseError(f"Dify 创建知识库失败: {created}")
        return self.dataset_id

    def _find_document(self, dataset_id: str, name: str) -> str:
        doc = self._get(f"{self.base_url}/v1/datasets/{dataset_id}"
                        f"/documents?keyword={name}&limit=20")
        for d in (doc.get("data") or []):
            if d.get("name") == name:
                return d.get("id", "")
        return ""

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure_key()
        ds = self._resolve_dataset()
        name = note.title[:80]
        existing = self._find_document(ds, name)
        text = note.to_frontmatter_markdown()
        rule = {"process_rule": {"mode": "automatic"}, "doc_language": "Chinese"}
        if existing:
            doc = self._post(f"{self.base_url}/v1/datasets/{ds}"
                             f"/documents/{existing}/update-by-text",
                             {"name": name, "text": text, **rule}, self._headers())
            status = "updated"
        else:
            doc = self._post(f"{self.base_url}/v1/datasets/{ds}"
                             "/document/create-by-text",
                             {"name": name, "text": text,
                              "indexing_technique": "high_quality", **rule},
                             self._headers())
            status = "pushed"
        if "document" not in doc and "result" not in doc and doc.get("code"):
            raise KnowledgeBaseError(f"Dify 写入失败: {doc}")
        return {"adapter": self.name, "status": status, "dataset_id": ds,
                "document_id": (doc.get("document") or {}).get("id", "")}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure_key()
        ds = self._resolve_dataset()
        doc = self._post(f"{self.base_url}/v1/datasets/{ds}/retrieve",
                         {"query": query,
                          "retrieval_model": {
                              "search_method": "semantic_search",
                              "reranking_enable": False,
                              "top_k": limit,
                              "score_threshold_enabled": False}},
                         self._headers())
        records = doc.get("records") or []
        return [{"title": (r.get("segment") or {}).get("document", {}).get("name", ""),
                 "snippet": (r.get("segment") or {}).get("content", ""),
                 "score": r.get("score"),
                 "source": "dify"} for r in records[:limit]]


class RagflowAdapter(_RemoteAdapter):
    """RAGFlow HTTP API（私有部署 RAG 知识库）。

    端点（Header: Authorization: Bearer <key>）：
      GET  /api/v1/datasets                知识库列表（按名定位）
      POST /api/v1/datasets                创建知识库
      POST /api/v1/datasets/{id}/documents multipart 上传 Markdown 文档
      POST /api/v1/retrieval               语义检索（回读）
    """

    name = "ragflow"

    def __init__(self, api_key: str = "", base_url: str = "",
                 dataset_id: str = "", dataset_name: str = "stock-researcher",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None,
                 http_raw_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn, http_raw_fn)
        cfg = load_kb_config().get("ragflow") or {}
        self.api_key = api_key or os.environ.get("RAGFLOW_API_KEY", "")
        self.base_url = (base_url or os.environ.get("RAGFLOW_BASE_URL")
                         or cfg.get("base_url") or "http://127.0.0.1:9380").rstrip("/")
        self.dataset_id = (dataset_id or os.environ.get("RAGFLOW_DATASET_ID")
                           or cfg.get("dataset_id", ""))
        self.dataset_name = (dataset_name or cfg.get("dataset_name",
                                                     "stock-researcher"))

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _ensure_key(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "RAGFlow API Key 缺失：请设置 RAGFLOW_API_KEY 环境变量"
                "（RAGFlow 控制台 → 头像 → API）")

    def _resolve_dataset(self) -> str:
        if self.dataset_id:
            return self.dataset_id
        doc = self._get(f"{self.base_url}/api/v1/datasets?page=1&page_size=100",
                        self._headers())
        for ds in ((doc.get("data") or {}).get("items") or []):
            if ds.get("name") == self.dataset_name:
                self.dataset_id = ds["id"]
                return self.dataset_id
        created = self._post(f"{self.base_url}/api/v1/datasets",
                             {"name": self.dataset_name}, self._headers())
        self.dataset_id = (created.get("data") or {}).get("id", "")
        if not self.dataset_id:
            raise KnowledgeBaseError(f"RAGFlow 创建知识库失败: {created}")
        return self.dataset_id

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure_key()
        ds = self._resolve_dataset()
        filename = re.sub(r'[\\/:*?"<>|\r\n]+', "_", note.title)[:60] + ".md"
        body, ctype = _multipart_form(
            {}, filename, note.to_frontmatter_markdown().encode("utf-8"))
        doc = self._raw(f"{self.base_url}/api/v1/datasets/{ds}/documents",
                        body, {**self._headers(), "Content-Type": ctype})
        if doc.get("code") not in (0, None):
            raise KnowledgeBaseError(f"RAGFlow 上传失败: {doc}")
        items = (doc.get("data") or [])
        doc_id = items[0].get("id", "") if isinstance(items, list) and items else ""
        return {"adapter": self.name, "status": "pushed",
                "dataset_id": ds, "document_id": doc_id}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure_key()
        ds = self._resolve_dataset()
        doc = self._post(f"{self.base_url}/api/v1/retrieval",
                         {"question": query, "dataset_ids": [ds],
                          "top_k": limit}, self._headers())
        chunks = (doc.get("data") or {}).get("chunks") or []
        return [{"title": c.get("document_keyword", ""),
                 "snippet": c.get("content_with_weight", "")
                            or c.get("content", ""),
                 "score": c.get("similarity"),
                 "source": "ragflow"} for c in chunks[:limit]]


class FastGPTAdapter(_RemoteAdapter):
    """FastGPT OpenAPI（知识库集合 + 问答对入库 + 检索）。

    端点（Header: Authorization: Bearer <key>）：
      GET  /api/core/dataset/list             知识库列表
      POST /api/core/dataset/create           创建知识库
      POST /api/core/dataset/collection/create 创建虚拟集合（直接文本）
      POST /api/core/dataset/data/pushData    写入文本分片（q=全文）
      POST /api/core/dataset/search           语义检索
    """

    name = "fastgpt"

    def __init__(self, api_key: str = "", base_url: str = "",
                 dataset_id: str = "", dataset_name: str = "stock-researcher",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn)
        cfg = load_kb_config().get("fastgpt") or {}
        self.api_key = api_key or os.environ.get("FASTGPT_API_KEY", "")
        self.base_url = (base_url or os.environ.get("FASTGPT_BASE_URL")
                         or cfg.get("base_url")
                         or "https://api.fastgpt.cn").rstrip("/")
        self.dataset_id = (dataset_id or os.environ.get("FASTGPT_DATASET_ID")
                           or cfg.get("dataset_id", ""))
        self.dataset_name = (dataset_name or cfg.get("dataset_name",
                                                     "stock-researcher"))

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _ensure_key(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "FastGPT API Key 缺失：请设置 FASTGPT_API_KEY 环境变量"
                "（FastGPT 知识库 → API 管理）")

    def _resolve_dataset(self) -> str:
        if self.dataset_id:
            return self.dataset_id
        doc = self._get(f"{self.base_url}/api/core/dataset/list", self._headers())
        for ds in (doc.get("data") or []):
            if ds.get("name") == self.dataset_name:
                self.dataset_id = ds.get("_id", "")
                return self.dataset_id
        created = self._post(f"{self.base_url}/api/core/dataset/create",
                             {"name": self.dataset_name, "type": "dataset",
                              "avatar": "", "intro": "stock-researcher 投研分析"},
                             self._headers())
        self.dataset_id = (created.get("data") or {}).get("_id", "") \
            if isinstance(created.get("data"), dict) else str(created.get("data", ""))
        if not self.dataset_id:
            raise KnowledgeBaseError(f"FastGPT 创建知识库失败: {created}")
        return self.dataset_id

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure_key()
        ds = self._resolve_dataset()
        name = note.title[:80]
        coll = self._post(f"{self.base_url}/api/core/dataset/collection/create",
                          {"datasetId": ds, "name": name, "type": "virtual",
                           "trainingType": "chunk"}, self._headers())
        coll_id = (coll.get("data") or {}).get("_id", "") \
            if isinstance(coll.get("data"), dict) else str(coll.get("data", ""))
        if not coll_id:
            raise KnowledgeBaseError(f"FastGPT 创建集合失败: {coll}")
        text = note.to_frontmatter_markdown()
        # 全文作为一个问答对入库（q=全文），保证回读能拿到完整机读块
        push = self._post(f"{self.base_url}/api/core/dataset/data/pushData",
                          {"collectionId": coll_id, "trainingType": "chunk",
                           "data": [{"q": text}]}, self._headers())
        return {"adapter": self.name, "status": "pushed", "dataset_id": ds,
                "collection_id": coll_id,
                "inserted": (push.get("data") or {}).get("insertLen", 0)}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure_key()
        ds = self._resolve_dataset()
        doc = self._post(f"{self.base_url}/api/core/dataset/search",
                         {"datasetId": ds, "text": query, "limit": limit},
                         self._headers())
        return [{"title": (it.get("collectionId") or {}).get("name", "")
                 if isinstance(it.get("collectionId"), dict) else "",
                 "snippet": it.get("q", "") or it.get("content", ""),
                 "score": it.get("score"),
                 "source": "fastgpt"} for it in (doc.get("data") or [])[:limit]]


class MaxKBAdapter(_RemoteAdapter):
    """MaxKB OpenAPI（私有部署知识库，Header: AUTHORIZATION: <key>）。

    端点：
      GET  /api/dataset                      知识库列表（按名定位）
      POST /api/dataset                      创建知识库（web 文档形态）
      POST /api/dataset/{id}/document/web    网页/文本入库（Markdown）
      POST /api/dataset/{id}/hit_test        命中测试（语义检索回读）
    """

    name = "maxkb"

    def __init__(self, api_key: str = "", base_url: str = "",
                 dataset_id: str = "", dataset_name: str = "stock-researcher",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn)
        cfg = load_kb_config().get("maxkb") or {}
        self.api_key = api_key or os.environ.get("MAXKB_API_KEY", "")
        self.base_url = (base_url or os.environ.get("MAXKB_BASE_URL")
                         or cfg.get("base_url")
                         or "http://127.0.0.1:8080").rstrip("/")
        self.dataset_id = (dataset_id or os.environ.get("MAXKB_DATASET_ID")
                           or cfg.get("dataset_id", ""))
        self.dataset_name = (dataset_name or cfg.get("dataset_name",
                                                     "stock-researcher"))

    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"AUTHORIZATION": self.api_key}

    def _ensure_key(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "MaxKB API Key 缺失：请设置 MAXKB_API_KEY 环境变量"
                "（MaxKB 平台 → 系统设置 → API 密钥）")

    def _resolve_dataset(self) -> str:
        if self.dataset_id:
            return self.dataset_id
        doc = self._get(f"{self.base_url}/api/dataset?page=1&page_size=100",
                        self._headers())
        for ds in ((doc.get("data") or {}).get("records") or []):
            if ds.get("name") == self.dataset_name:
                self.dataset_id = ds.get("id", "")
                return self.dataset_id
        created = self._post(f"{self.base_url}/api/dataset",
                             {"name": self.dataset_name,
                              "desc": "stock-researcher 投研分析",
                              "embedding_mode_id": ""}, self._headers())
        self.dataset_id = (created.get("data") or {}).get("id", "")
        if not self.dataset_id:
            raise KnowledgeBaseError(f"MaxKB 创建知识库失败: {created}")
        return self.dataset_id

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure_key()
        ds = self._resolve_dataset()
        doc = self._post(f"{self.base_url}/api/dataset/{ds}/document/web",
                         {"source_url": "",
                          "selector": "",
                          "title": note.title,
                          "content": note.to_frontmatter_markdown()},
                         self._headers())
        if doc.get("code") not in (200, 0, None):
            raise KnowledgeBaseError(f"MaxKB 入库失败: {doc}")
        return {"adapter": self.name, "status": "pushed", "dataset_id": ds}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure_key()
        ds = self._resolve_dataset()
        doc = self._post(f"{self.base_url}/api/dataset/{ds}/hit_test",
                         {"query_text": query, "top_number": limit,
                          "similarity": 0.0}, self._headers())
        return [{"title": (it.get("document") or {}).get("name", ""),
                 "snippet": it.get("content", ""),
                 "score": it.get("similarity"),
                 "source": "maxkb"} for it in (doc.get("data") or [])[:limit]]


class YuqueAdapter(_RemoteAdapter):
    """语雀 OpenAPI（个人/团队知识库）。

    端点（Header: X-Auth-Token）：
      GET  /api/v2/repos/{namespace}/docs       文档列表（同名定位）
      POST /api/v2/repos/{namespace}/docs       新建文档（Markdown）
      PUT  /api/v2/repos/{namespace}/docs/{id}  更新文档（需 _raw PATCH 替身）
      GET  /api/v2/search?q=...&type=doc        全站检索（回读）
    """

    name = "yuque"
    BASE = "https://www.yuque.com"

    def __init__(self, token: str = "", repo: str = "",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None,
                 http_raw_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn, http_raw_fn)
        cfg = load_kb_config().get("yuque") or {}
        self.token = token or os.environ.get("YUQUE_TOKEN", "")
        login = cfg.get("login") or os.environ.get("YUQUE_LOGIN", "")
        repo_name = cfg.get("repo_name") or os.environ.get("YUQUE_REPO_NAME", "")
        self.repo = repo or os.environ.get("YUQUE_REPO", "") \
            or cfg.get("repo", "")
        if not self.repo and login and repo_name:
            self.repo = f"{login}/{repo_name}"

    def available(self) -> bool:
        return bool(self.token and self.repo)

    def _headers(self) -> Dict[str, str]:
        return {"X-Auth-Token": self.token}

    def _ensure(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "语雀凭证缺失：请设置 YUQUE_TOKEN + YUQUE_REPO（如 user/repo）"
                "或 YUQUE_LOGIN + YUQUE_REPO_NAME 环境变量"
                "（语雀 → 个人设置 → Token）")

    def _find_doc(self, title: str) -> int:
        doc = self._get(f"{self.BASE}/api/v2/repos/{self.repo}/docs?limit=100",
                        self._headers())
        for d in (doc.get("data") or []):
            if d.get("title") == title:
                return int(d.get("id", 0))
        return 0

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure()
        title = note.title[:100]
        body = {"title": title, "slug": "",
                "format": "markdown", "public": 0,
                "body": note.to_frontmatter_markdown()}
        existing = self._find_doc(title)
        if existing:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            doc = self._raw(f"{self.BASE}/api/v2/repos/{self.repo}/docs/{existing}",
                            payload, {**self._headers(),
                                      "Content-Type": "application/json"},
                            method="PUT")
            status = "updated"
        else:
            doc = self._post(f"{self.BASE}/api/v2/repos/{self.repo}/docs",
                             body, self._headers())
            status = "pushed"
        doc_id = (doc.get("data") or {}).get("id", "")
        if not doc_id:
            raise KnowledgeBaseError(f"语雀写入失败: {doc}")
        return {"adapter": self.name, "status": status, "repo": self.repo,
                "doc_id": doc_id}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure()
        import urllib.parse
        q = urllib.parse.quote(query)
        doc = self._get(f"{self.BASE}/api/v2/search?q={q}&type=doc",
                        self._headers())
        return [{"title": it.get("title", ""),
                 "snippet": it.get("summary", "") or it.get("description", ""),
                 "path": it.get("url", ""),
                 "source": "yuque"} for it in (doc.get("data") or [])[:limit]]


class FeishuAdapter(_RemoteAdapter):
    """飞书知识库（Wiki）：tenant_access_token → 建节点 → 写入正文。

    端点（open.feishu.cn）：
      POST /open-apis/auth/v3/tenant_access_token/internal  取应用令牌
      GET  /open-apis/wiki/v2/spaces                        知识空间列表
      POST /open-apis/wiki/v2/spaces/{id}/nodes             新建文档节点（docx）
      POST /open-apis/docx/v1/documents/{id}/blocks/{id}/children  写入正文
      POST /open-apis/suite/docs-api/search/object          文档检索（回读）
    """

    name = "feishu"
    BASE = "https://open.feishu.cn"

    def __init__(self, app_id: str = "", app_secret: str = "",
                 wiki_space_id: str = "", parent_node_token: str = "",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn)
        cfg = load_kb_config().get("feishu") or {}
        self.app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
        self.wiki_space_id = (wiki_space_id
                              or os.environ.get("FEISHU_WIKI_SPACE_ID", "")
                              or cfg.get("wiki_space_id", ""))
        self.parent_node_token = (parent_node_token
                                  or os.environ.get("FEISHU_PARENT_NODE", "")
                                  or cfg.get("parent_node_token", ""))
        self._token = ""

    def available(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def _ensure_token(self) -> str:
        if self._token:
            return self._token
        if not self.available():
            raise KnowledgeBaseError(
                "飞书凭证缺失：请设置 FEISHU_APP_ID / FEISHU_APP_SECRET"
                "（飞书开放平台创建自建应用并开通云文档/知识库权限）")
        doc = self._post(self.BASE + "/open-apis/auth/v3/tenant_access_token/internal",
                         {"app_id": self.app_id, "app_secret": self.app_secret}, {})
        self._token = doc.get("tenant_access_token", "")
        if not self._token:
            raise KnowledgeBaseError(f"飞书取令牌失败: {doc}")
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def _resolve_space(self) -> str:
        if self.wiki_space_id:
            return self.wiki_space_id
        doc = self._get(self.BASE + "/open-apis/wiki/v2/spaces?page_size=50",
                        self._headers())
        items = (doc.get("data") or {}).get("items") or []
        if items:
            self.wiki_space_id = items[0].get("space_id", "")
        if not self.wiki_space_id:
            raise KnowledgeBaseError("飞书无可用知识空间：请在飞书知识库先建空间"
                                     "或设置 FEISHU_WIKI_SPACE_ID")
        return self.wiki_space_id

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        space = self._resolve_space()
        body: Dict[str, Any] = {"obj_type": "docx", "title": note.title}
        if self.parent_node_token:
            body["parent_node_token"] = self.parent_node_token
        node = self._post(f"{self.BASE}/open-apis/wiki/v2/spaces/{space}/nodes",
                          body, self._headers())
        n = (node.get("data") or {}).get("node") or {}
        obj_token = n.get("obj_token", "")
        if not obj_token:
            raise KnowledgeBaseError(f"飞书建节点失败: {node}")
        block = {"block_type": 2,
                 "text": {"elements": [{"text_run": {
                     "content": note.to_frontmatter_markdown()}}]}}
        self._post(f"{self.BASE}/open-apis/docx/v1/documents/{obj_token}"
                   f"/blocks/{obj_token}/children",
                   {"children": [block]}, self._headers())
        return {"adapter": self.name, "status": "pushed",
                "space_id": space, "node_token": n.get("node_token", ""),
                "doc_token": obj_token}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        doc = self._post(self.BASE + "/open-apis/suite/docs-api/search/object",
                         {"search_key": query, "count": limit,
                          "offset": 0, "docs_types": []}, self._headers())
        items = (doc.get("data") or {}).get("docs_entities") or []
        return [{"title": it.get("docs_link", {}).get("title", "")
                 or it.get("title", ""),
                 "snippet": it.get("docs_link", {}).get("url", ""),
                 "path": it.get("docs_link", {}).get("url", ""),
                 "source": "feishu"} for it in items[:limit]]


class NotionAdapter(_RemoteAdapter):
    """Notion API（写入父页面下的新页面，同名则追加内容幂等更新）。

    端点（Header: Authorization + Notion-Version）：
      POST /v1/pages                  新建页面（标题+正文块）
      POST /v1/search                 全库检索（同名定位）
      POST /v1/blocks/{id}/children   同名页面追加正文（更新形态）
    """

    name = "notion"
    BASE = "https://api.notion.com/v1"
    API_VERSION = "2022-06-28"

    def __init__(self, api_key: str = "", parent_page_id: str = "",
                 http_fn: Optional[Callable] = None,
                 http_get_fn: Optional[Callable] = None):
        super().__init__(http_fn, http_get_fn)
        cfg = load_kb_config().get("notion") or {}
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self.parent_page_id = (parent_page_id
                               or os.environ.get("NOTION_PARENT_PAGE_ID", "")
                               or cfg.get("parent_page_id", ""))

    def available(self) -> bool:
        return bool(self.api_key and self.parent_page_id)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}",
                "Notion-Version": self.API_VERSION}

    def _ensure(self) -> None:
        if not self.available():
            raise KnowledgeBaseError(
                "Notion 凭证缺失：请设置 NOTION_API_KEY + NOTION_PARENT_PAGE_ID"
                "（Notion Integrations 创建 integration 并邀请进目标页面）")

    @staticmethod
    def _paragraph_blocks(text: str) -> List[Dict[str, Any]]:
        """正文按段落切块（Notion 单块 ≤2000 字符）。"""
        blocks = []
        for para in (text or "").split("\n\n"):
            para = para.strip()
            if not para:
                continue
            for i in range(0, len(para), 1800):
                blocks.append({"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": [{"type": "text",
                                   "text": {"content": para[i:i + 1800]}}]}})
        return blocks[:100]

    def _find_page(self, title: str) -> str:
        doc = self._post(self.BASE + "/search",
                         {"query": title, "page_size": 10,
                          "filter": {"value": "page", "property": "object"}},
                         self._headers())
        for page in (doc.get("results") or []):
            props = page.get("properties") or {}
            for v in props.values():
                if v.get("type") != "title":
                    continue
                t = "".join(x.get("plain_text", "")
                            for x in (v.get("title") or []))
                if t == title:
                    return page.get("id", "")
        return ""

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        self._ensure()
        text = note.to_frontmatter_markdown()
        existing = self._find_page(note.title)
        if existing:                        # 同名追加 → 幂等更新形态
            self._post(f"{self.BASE}/blocks/{existing}/children",
                       {"children": self._paragraph_blocks(text)},
                       self._headers())
            return {"adapter": self.name, "status": "updated",
                    "page_id": existing}
        doc = self._post(self.BASE + "/pages",
                         {"parent": {"type": "page_id",
                                     "page_id": self.parent_page_id},
                          "properties": {"title": [{"type": "text",
                              "text": {"content": note.title[:200]}}]},
                          "children": self._paragraph_blocks(text)},
                         self._headers())
        page_id = doc.get("id", "")
        if not page_id:
            raise KnowledgeBaseError(f"Notion 建页失败: {doc}")
        return {"adapter": self.name, "status": "pushed", "page_id": page_id}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self._ensure()
        doc = self._post(self.BASE + "/search",
                         {"query": query, "page_size": limit}, self._headers())
        out = []
        for it in (doc.get("results") or []):
            title = ""
            for v in (it.get("properties") or {}).values():
                if v.get("type") == "title":
                    title = "".join(x.get("plain_text", "")
                                    for x in (v.get("title") or []))
            out.append({"title": title or it.get("id", ""),
                        "snippet": "",
                        "source": "notion"})
        return out[:limit]


class SiyuanAdapter(_RemoteAdapter):
    """思源笔记（本地内核 HTTP API，默认 127.0.0.1:6806）。

    端点（Header: Authorization: Token xxx，可选）：
      POST /api/notebook/lsNotebooks            笔记本列表（按名/ID 定位）
      POST /api/filetree/createDocWithMd        新建文档（Markdown 直写）
      POST /api/search/fullTextSearchBlock      全文检索（回读）
      POST /api/block/getBlockKramdown          读块全文（read）
    """

    name = "siyuan"

    def __init__(self, url: str = "", token: str = "", notebook: str = "",
                 http_fn: Optional[Callable] = None):
        super().__init__(http_fn)
        cfg = load_kb_config().get("siyuan") or {}
        self.url = (url or os.environ.get("SIYUAN_URL")
                    or cfg.get("url") or "http://127.0.0.1:6806").rstrip("/")
        self.token = token or os.environ.get("SIYUAN_TOKEN", "") \
            or cfg.get("token", "")
        self.notebook = (notebook or os.environ.get("SIYUAN_NOTEBOOK")
                         or cfg.get("notebook") or "投研")
        self._notebook_id = ""

    def available(self) -> bool:
        # 本地服务，无凭证也可用（默认无鉴权）；实际可达性由调用时报错反馈
        return bool(self.url)

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Token {self.token}"
        return h

    def _resolve_notebook(self) -> str:
        if self._notebook_id:
            return self._notebook_id
        doc = self._post(f"{self.url}/api/notebook/lsNotebooks", {}, self._headers())
        for nb in (doc.get("data") or {}).get("notebooks") or []:
            if self.notebook in (nb.get("name"), nb.get("id")):
                self._notebook_id = nb.get("id", "")
                return self._notebook_id
        # 未命中时以首本兜底（避免写入失败）
        nbs = (doc.get("data") or {}).get("notebooks") or []
        if nbs:
            self._notebook_id = nbs[0].get("id", "")
        if not self._notebook_id:
            raise KnowledgeBaseError("思源笔记无可用笔记本：请先在思源建一本笔记本")
        return self._notebook_id

    def push(self, note: KnowledgeNote) -> Dict[str, Any]:
        nb = self._resolve_notebook()
        safe_title = re.sub(r'[\\/:*?"<>|\r\n]+', "_", note.title)[:80]
        safe_cat = re.sub(r'[\\/:*?"<>|\r\n]+', "_", note.category)
        path = f"/{safe_cat}/{safe_title}"
        doc = self._post(f"{self.url}/api/filetree/createDocWithMd",
                         {"notebook": nb, "path": path,
                          "markdown": note.to_frontmatter_markdown()},
                         self._headers())
        doc_id = doc.get("data", "")
        if doc.get("code") not in (0, None) or not doc_id:
            raise KnowledgeBaseError(f"思源写入失败: {doc}")
        return {"adapter": self.name, "status": "pushed",
                "notebook": nb, "doc_id": doc_id}

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        doc = self._post(f"{self.url}/api/search/fullTextSearchBlock",
                         {"query": query, "page": 1}, self._headers())
        blocks = (((doc.get("data") or {}).get("blocks")) or [])
        return [{"title": b.get("hPath", ""),
                 "snippet": re.sub(r"<[^>]+>", "", b.get("content", ""))[:600],
                 "block_id": b.get("id", ""),
                 "source": "siyuan"} for b in blocks[:limit]]

    def read(self, ref: str) -> str:
        if not ref:
            return ""
        try:
            doc = self._post(f"{self.url}/api/block/getBlockKramdown",
                             {"id": ref}, self._headers())
            return (doc.get("data") or {}).get("kramdown", "")
        except Exception:
            return ""


class LogseqAdapter(LocalKnowledgeAdapter):
    """Logseq 图谱：直写 <graph>/pages/*.md（Logseq 自动索引）。

    索引文件放在 skill 自身 data/ 目录，避免在用户图谱里留 _index.json。
    """

    name = "logseq"

    def __init__(self, graph_path: Optional[Path] = None):
        if graph_path is None:
            cfg = load_kb_config().get("logseq") or {}
            graph_path = (cfg.get("graph_path")
                          or os.environ.get("LOGSEQ_GRAPH_PATH") or "")
        self._configured = bool(graph_path)
        gp = Path(graph_path) if graph_path else KB_DIR
        super().__init__(gp / "pages")
        if self._configured:
            self.index_file = SKILL_DIR / "data" / "_logseq_kb_index.json"

    def available(self) -> bool:
        return self._configured and Path(self.base_dir).parent.is_dir()


ADAPTERS: Dict[str, type] = {
    "local": LocalKnowledgeAdapter,
    "obsidian": ObsidianAdapter,
    "ima": ImaAdapter,
    "dify": DifyAdapter,
    "ragflow": RagflowAdapter,
    "fastgpt": FastGPTAdapter,
    "maxkb": MaxKBAdapter,
    "yuque": YuqueAdapter,
    "feishu": FeishuAdapter,
    "notion": NotionAdapter,
    "siyuan": SiyuanAdapter,
    "logseq": LogseqAdapter,
}


def get_adapter(name: Optional[str] = None, **kwargs) -> KnowledgeAdapter:
    """按名称取适配器（默认读配置 target，未配置兜底 local）。"""
    name = (name or load_kb_config().get("target") or KB_DEFAULT_TARGET).lower()
    cls = ADAPTERS.get(name)
    if cls is None:
        raise KnowledgeBaseError(f"未知知识库适配器: {name}"
                                 f"（支持 {'/'.join(ADAPTERS)}）")
    return cls(**kwargs)


# ════════════════ 3. 分析结果 → 知识笔记 ════════════════

def _fmt(v: Any, suffix: str = "", nd: int = 2) -> str:
    try:
        return f"{float(v):.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def build_analysis_note(code: str, result: Dict[str, Any],
                        prices: Optional[List[float]] = None) -> KnowledgeNote:
    """把 stock_predict.predict() 结果渲染为知识笔记。

    正文含人读概览 + 机读 JSON 块（schema=DATA_SCHEMA，内嵌价格序列/
    评分/蒙特卡洛），供 load_kb_data 回读后离线量化分析。
    """
    if not result or "error" in result:
        raise KnowledgeBaseError(f"{code} 无有效分析结果，拒绝写入知识库")
    p = result.get("price", {}) or {}
    t = result.get("technical", {}) or {}
    s = result.get("score", {}) or {}
    mc = result.get("monte_carlo", {}) or {}
    name = result.get("name") or code
    closes = [float(x) for x in (prices or [])][-MAX_NOTE_PRICES:]

    lines = [f"# {name}({code}) 涨跌预测存档", ""]
    lines += [f"- 时间：{datetime.now():%Y-%m-%d %H:%M}",
              f"- 现价：{_fmt(p.get('price'))}  涨跌：{_fmt(p.get('chg_pct'), '%')}  "
              f"PE：{_fmt(p.get('pe'), nd=1)}",
              f"- 信号：**{result.get('signal', '—')}**"
              f"（置信度 {_fmt((result.get('confidence') or 0) * 100, '%', 0)}）",
              f"- 综合评分：{_fmt(s.get('total'), nd=1)}/100", ""]
    lines += ["## 技术指标", "",
              f"MA5={t.get('ma5', '—')} MA20={t.get('ma20', '—')} "
              f"MA60={t.get('ma60', '—')} RSI={t.get('rsi', '—')} "
              f"量比={t.get('vol_ratio', '—')}", ""]
    if mc:
        lines += ["## 蒙特卡洛概率", "", "| 周期 | 平均涨跌 | 上涨概率 |",
                  "|---|---|---|"]
        for hor in ("5d", "10d"):
            m = mc.get(hor) or {}
            if m:
                lines.append(f"| {hor} | {_fmt(m.get('avg'), '%')} | "
                             f"{_fmt((m.get('up') or 0) * 100, '%', 0)} |")
        lines.append("")
    if result.get("summary"):
        lines += ["## 结论", "", str(result["summary"]), ""]

    # 机读数据块：回读量化分析的载体
    payload = {
        "schema": DATA_SCHEMA,
        "code": code, "name": name,
        "market": result.get("market", ""),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": {"price": p.get("price"), "chg_pct": p.get("chg_pct"),
                  "pe": p.get("pe")},
        "score": {"total": s.get("total"),
                  "signal": result.get("signal"),
                  "confidence": result.get("confidence")},
        "prices": closes,
    }
    lines += ["## 机读数据（自动内嵌，可回读量化分析）", "",
              "```json",
              json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
              "```", ""]
    from .constants import SCORE_MEANING, DISCLAIMER
    lines += [f"> ⚠️ {SCORE_MEANING}；{DISCLAIMER}"]

    return KnowledgeNote(
        title=f"{name}({code}) 分析预测 {datetime.now():%Y%m%d}",
        content="\n".join(lines),
        tags=["投研", "stock-researcher", str(code)],
        category="投研分析")


# ════════════════ 4. 双向同步引擎 ════════════════

def _append_sync_log(entry: Dict[str, Any],
                       log_file: Optional[Path] = None) -> None:
    log_file = Path(log_file) if log_file else SYNC_LOG
    try:
        log = (json.loads(log_file.read_text(encoding="utf-8"))
               if log_file.exists() else [])
        if not isinstance(log, list):
            log = []
    except Exception:
        log = []
    log.append(entry)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log[-LOG_KEEP:], ensure_ascii=False, indent=1),
                        encoding="utf-8")


def save_analysis_to_kb(code: str, result: Dict[str, Any],
                        prices: Optional[List[float]] = None,
                        target: Optional[str] = None,
                        adapter: Optional[KnowledgeAdapter] = None) -> Dict[str, Any]:
    """分析结果 → 知识笔记 → 推送知识库，写同步日志。单适配器失败不抛给调用方。"""
    ad = adapter or get_adapter(target)
    try:
        note = build_analysis_note(code, result, prices)
        res = ad.push(note)
        entry = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "action": "save", "target": ad.name, "code": code,
                 "status": res.get("status", "pushed")}
        _append_sync_log(entry)
        return {"ok": True, "adapter": ad.name, **res, "title": note.title}
    except KnowledgeBaseError as exc:
        _append_sync_log({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          "action": "save", "target": ad.name, "code": code,
                          "status": "failed", "error": str(exc)})
        return {"ok": False, "adapter": ad.name, "error": str(exc)}


def search_knowledge(query: str, target: Optional[str] = None,
                     adapter: Optional[KnowledgeAdapter] = None,
                     limit: int = 5) -> List[Dict[str, Any]]:
    """从知识库检索笔记（标题/正文/语义，取决于适配器）。"""
    ad = adapter or get_adapter(target)
    return ad.search(query, limit=limit)


def _extract_payload(text: str) -> Optional[Dict[str, Any]]:
    """从笔记全文提取机读 JSON 块（按 schema 标记定位）。"""
    for m in _JSON_BLOCK_RE.finditer(text or ""):
        try:
            doc = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("schema") == DATA_SCHEMA:
            return doc
    return None


def load_kb_data(query: str, adapter: Optional[KnowledgeAdapter] = None,
                 target: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """检索知识库并提取第一条命中的机读分析数据（含价格序列）。"""
    ad = adapter or get_adapter(target)
    for hit in ad.search(query, limit=5):
        text = ""
        if hit.get("path"):
            text = ad.read(hit["path"]) or hit.get("snippet", "")
        elif hit.get("block_id"):           # 块级引用（思源）：读块全文
            text = ad.read(hit["block_id"]) or hit.get("snippet", "")
        else:
            text = hit.get("snippet", "")
        payload = _extract_payload(text)
        if payload:
            payload["_source_title"] = hit.get("title", "")
            return payload
    return None


def kb_quant_forecast(query: str, horizon: int = 5,
                      adapter: Optional[KnowledgeAdapter] = None,
                      target: Optional[str] = None) -> Dict[str, Any]:
    """从知识库回读价格序列 → 离线量化体检 + 历史形态匹配预测。

    完全不联网：量化所需数据全部来自知识库笔记内嵌的机读块。
    """
    payload = load_kb_data(query, adapter=adapter, target=target)
    if not payload:
        return {"ok": False,
                "error": f"知识库未找到 “{query}” 的可回读分析数据"
                         "（需先用 --kb-save 保存过带机读块的笔记）"}
    prices = [float(x) for x in (payload.get("prices") or []) if x is not None]
    if len(prices) < KB_MIN_POINTS:
        return {"ok": False,
                "error": f"知识库数据价格点不足（{len(prices)}<{KB_MIN_POINTS}），无法量化分析",
                "code": payload.get("code")}
    from .quantitative.metrics import compute_quant_metrics
    from .quantitative.pattern_predictor import quick_pattern_forecast
    metrics = dataclasses.asdict(compute_quant_metrics(prices))
    pf = quick_pattern_forecast(prices, horizon=horizon)
    return {"ok": True,
            "code": payload.get("code"), "name": payload.get("name"),
            "source_title": payload.get("_source_title", ""),
            "saved_at": payload.get("saved_at", ""),
            "points": len(prices),
            "metrics": metrics,
            "pattern_forecast": pf,
            "archived_score": (payload.get("score") or {}).get("total")}


def kb_status() -> Dict[str, Any]:
    """各适配器可用性总览（--kb status 用，纯离线）。"""
    out = {"adapters": {}}
    for name, cls in ADAPTERS.items():
        try:
            out["adapters"][name] = cls().available()
        except Exception:
            out["adapters"][name] = False
    out["default_target"] = load_kb_config().get("target", "local")
    out["local_dir"] = str(KB_DIR)
    return out
