"""MemoryStore · 长期记忆（JSON 事实库）。

Phase 1 轻量实现，不上 PG：
- 事实粒度：一条 = 一个值得长期记住的信息（偏好/习惯/重要事件/约定）
- 去重：完全重复跳过；已包含重复跳过；相近语义靠 memory_write 的规则避免
- 检索：CJK 二元组词法打分（无需 embedding 模型，2B 本地模型场景友好）
- 上限：300 条，超出按"访问少 + 旧"淘汰
- 存储：backend/data/memories/<partner>/facts.json，原子写入

Phase 2 预留：换向量库（Chroma+embedding）= 换 search 实现，接口不变。
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_MAX_FACTS = 300
_CJK_BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]{2}")  # 中文字符二元组


@dataclass
class MemoryFact:
    id: str
    content: str
    category: str = "fact"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryFact":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.facts: list[MemoryFact] = []
        self._load()

    # ---------- 读写 ----------

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [MemoryFact.from_dict(f) for f in data.get("facts", [])]
        except (json.JSONDecodeError, OSError):
            self.facts = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "facts": [f.to_dict() for f in self.facts]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, content: str, category: str = "fact") -> MemoryFact | None:
        content = content.strip()
        if not content:
            return None
        # 去重：完全一致，或已存在包含新内容（近似重复不再存）
        for f in self.facts:
            if f.content == content or content in f.content:
                f.access_count += 1
                f.updated_at = time.time()
                self._save()
                return f
        fact = MemoryFact(id=uuid.uuid4().hex[:8], content=content, category=category)
        self.facts.append(fact)
        self._evict()
        self._save()
        return fact

    def remove(self, fact_id: str) -> bool:
        before = len(self.facts)
        self.facts = [f for f in self.facts if f.id != fact_id]
        if len(self.facts) != before:
            self._save()
            return True
        return False

    def _evict(self):
        if len(self.facts) <= _MAX_FACTS:
            return
        # 淘汰：访问少且旧的优先（稳定排序，不动刚写入的新事实）
        self.facts.sort(key=lambda f: (f.access_count, f.created_at))
        del self.facts[: len(self.facts) - _MAX_FACTS]

    # ---------- 检索 ----------

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        chars = re.sub(r"\s+", "", text)
        if not chars:
            return set()
        # 中文二元组；ASCII 词按整词处理
        grams = {chars[i : i + 2] for i in range(len(chars) - 1)}
        for word in re.findall(r"[a-zA-Z0-9_]{2,}", text):
            grams.add(word.lower())
        return grams

    @staticmethod
    def _score(query: str, fact: str) -> float:
        qg, fg = MemoryStore._bigrams(query), MemoryStore._bigrams(fact)
        if not qg:
            return 0.0
        overlap = len(qg & fg)
        if query in fact:
            overlap += 2.0
        if fact in query:
            overlap += 1.0
        return overlap

    def search(self, query: str, top_k: int = 3) -> list[MemoryFact]:
        scored = [(self._score(query, f.content), f) for f in self.facts]
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = [f for s, f in scored if s > 0][:top_k]
        for f in hits:
            f.access_count += 1
        if hits:
            self._save()
        return hits

    def recent(self, top_k: int = 3) -> list[MemoryFact]:
        return sorted(self.facts, key=lambda f: f.created_at, reverse=True)[:top_k]

    def snapshot(self) -> dict:
        return {"total": len(self.facts), "facts": [f.to_dict() for f in self.facts]}


# ---------- 应用内单例（由 lifespan 注入；插件工具通过 get_store 读取） ----------
# Phase 4a 多用户：注册表 keyed by user（None = 默认/开发模式）。
_store: MemoryStore | None = None
_user_stores: dict[str, MemoryStore] = {}
_user_base: Path | None = None


def set_store(store: MemoryStore):
    """设置默认（无用户）记忆库；同时记录 per-user 目录根。"""
    global _store, _user_base
    _store = store
    _user_base = Path(store.path).parent.parent  # data/memories/<partner>/facts.json → data/memories


def set_user_base(base: Path):
    global _user_base
    _user_base = base


def get_store(user: str | None = None) -> MemoryStore:
    """user 为 None 时返回默认库；否则按用户懒加载 data/memories/<user>/facts.json。"""
    if user:
        if user not in _user_stores:
            if _user_base is None:
                raise RuntimeError("per-user 记忆未初始化（需先 set_store/set_user_base）")
            _user_stores[user] = MemoryStore(str(_user_base / user / "facts.json"))
        return _user_stores[user]
    if _store is None:
        raise RuntimeError("MemoryStore 尚未初始化（需在 lifespan 中 set_store）")
    return _store
