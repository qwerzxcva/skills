"""Store 抽象层（工程改进方案 阶段3: provider/store 抽象）。

目标：让记忆存储后端可插拔（本地 sqlite/WAL / 远程 IMA），便于 mock 测试。
当前仅 SqliteStore 落地，委托现有 memory_ops 的存储函数（行为一致）；
调用点可增量迁移到此接口，无需一次性改写主模块。

迁移方式（增量）：
from store import get_store
store = get_store(root)
mems = store.all_mems()
store.write_mem(mid, payload)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class Store(ABC):
    """记忆库读写统一接口（root 为库根目录）。"""

    def __init__(self, root: str):
        self.root = root

    @abstractmethod
    def all_mems(self) -> Dict[str, dict]:
        """返回全部 active 记忆（mid -> payload）。"""

    @abstractmethod
    def write_mem(self, mid: str, payload: dict) -> None:
        """写入/覆盖一条记忆。"""

    @abstractmethod
    def load_index(self) -> dict:
        """加载倒排/元数据索引。"""

    @abstractmethod
    def save_index(self, data: dict) -> None:
        """保存索引。"""

    @abstractmethod
    def db_path(self) -> str:
        """底层数据库文件路径。"""


class SqliteStore(Store):
    """默认后端：委托现有 memory_ops 存储函数（sqlite/WAL + 文件记忆）。"""

    def _m(self):
        import memory_ops as _m  # 惰性委托，保持与现有行为一致
        return _m

    def all_mems(self) -> Dict[str, dict]:
        return self._m()._all_mems(self.root)

    def write_mem(self, mid: str, payload: dict) -> None:
        self._m()._write_mem(self.root, mid, payload)

    def load_index(self) -> dict:
        return self._m().load_index(self.root)

    def save_index(self, data: dict) -> None:
        self._m().save_index(self.root, data)

    def db_path(self) -> str:
        return self._m()._db_path(self.root)


_STORES = {
    "sqlite": SqliteStore,
}


def get_store(root: str, kind: str = "sqlite", **kwargs) -> Store:
    """工厂：按名取存储后端（可插拔点的统一入口）。"""
    if kind not in _STORES:
        raise ValueError(f"未知存储后端: {kind}（可选: {sorted(_STORES)}）")
    return _STORES[kind](root, **kwargs)


def register_store(name: str, cls):
    """扩展点：插件可注册新存储后端。"""
    _STORES[name] = cls
