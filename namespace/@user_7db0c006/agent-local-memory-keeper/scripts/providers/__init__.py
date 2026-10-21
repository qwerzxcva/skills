"""EmbeddingProvider 抽象层（工程改进方案 阶段3: provider/store 抽象）。

目标：让 embedding 后端可插拔（fastembed / numpy 词法 / 本地 LLM / 云端），
并便于单测时 mock。当前仅 FastEmbedProvider 落地，委托给现有 embed 模块
（行为保持一致，不重复实现）；调用点（memory_ops/mem_bridge）可增量迁移到此接口。

迁移方式（增量、不一次性改写 11000+ 行）：
from providers import get_embedder
emb = get_embedder()          # 默认 fastembed
vecs = emb.embed_batch(texts)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class EmbeddingProvider(ABC):
    """向量化后端统一接口。"""

    name: str = "base"

    @abstractmethod
    def embed(self, text: str):
        """单条文本 → 向量。"""

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[list]:
        """批量文本 → 向量列表。"""

    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""

    @abstractmethod
    def is_available(self) -> bool:
        """后端当前是否可用（依赖/模型就绪）。"""


class FastEmbedProvider(EmbeddingProvider):
    """默认后端：委托现有 embed 模块（fastembed + 词法兜底）。"""

    name = "fastembed"

    def __init__(self, model: Optional[str] = None):
        self._model = model  # 保留扩展点；当前沿用 embed 模块默认模型

    def _emb(self):
        import embed as _emb  # 惰性委托，保持与现有行为一致
        return _emb

    def embed(self, text: str):
        return self._emb().embed(text, use_cache=True)

    def embed_batch(self, texts: List[str]) -> List[list]:
        return self._emb().embed_batch(texts, use_cache=True)

    def dim(self) -> int:
        return getattr(self._emb(), "EMB_DIM", 512)

    def is_available(self) -> bool:
        # 后端可用 = backend_info 能返回非空（神经 fastembed 或词法兜底任一就绪即算可用）
        # 注：embed.backend_info 返回形如 'fastembed:BAAI/bge-small-zh-' 的字符串
        try:
            info = self._emb().backend_info()
            return bool(info)
        except Exception:
            return False


_PROVIDERS = {
    "fastembed": FastEmbedProvider,
}


def get_embedder(name: str = "fastembed", **kwargs) -> EmbeddingProvider:
    """工厂：按名取 embedding 后端（可插拔点的统一入口）。"""
    if name not in _PROVIDERS:
        raise ValueError(f"未知 embedding 后端: {name}（可选: {sorted(_PROVIDERS)}）")
    return _PROVIDERS[name](**kwargs)


def register_provider(name: str, cls):
    """扩展点：插件可注册新后端。"""
    _PROVIDERS[name] = cls
