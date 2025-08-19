# services/store.py
from typing import Dict, Any
from uuid import uuid4
from dataclasses import dataclass, field

@dataclass
class DataBundle:
    frames: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)
    trees: Dict[str, Any] = field(default_factory=dict)   # pruned trees per model
    index: Dict[str, Any] = field(default_factory=dict)   # paths/npaths per model

class InMemoryStore:
    def __init__(self) -> None:
        self._data: Dict[str, DataBundle] = {}

    def create(self, frames: Dict[str, Any], meta: Dict[str, Any], trees=None, index=None) -> str:
        ds_id = uuid4().hex
        self._data[ds_id] = DataBundle(frames=frames, meta=meta, trees=trees or {}, index=index or {})
        return ds_id

    def get(self, ds_id: str) -> DataBundle:
        return self._data[ds_id]

    def has(self, ds_id: str) -> bool:
        return ds_id in self._data

STORE = InMemoryStore()
