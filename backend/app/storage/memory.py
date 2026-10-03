"""storage/memory.py · MemoryStore（长期记忆，SQLite facts 表）。

决策 3（存储合一）：记忆从 JSON 事实库改为统一库 nuomi.db 的 facts 表，
接口不变（add / remove / search / recent / snapshot / _MAX_FACTS 淘汰）。
- 去重：完全重复跳过；已包含重复跳过；相近语义靠 memory_write 的规则避免
- 检索：CJK 二元组词法打分（无需 embedding 模型，2B 本地模型场景友好）
- 上限：300 条，超出按"访问少 + 旧"淘汰
- 多用户已移除（决策 1）：单库单伙伴，不再有 per-user 目录
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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
    def from_dict(cls, d: dict) -> MemoryFact:
        return cls(
            id=str(d.get("id", "")),
            content=str(d.get("content", "")),
            category=str(d.get("category", "fact")),
            created_at=float(d.get("created_at", 0.0)),
            updated_at=float(d.get("updated_at", 0.0)),
            access_count=int(d.get("access_count", 0)),
        )


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            partner TEXT NOT NULL DEFAULT 'nuomi',
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'fact',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )


class MemoryStore:
    def __init__(self, db_path: str | Path, partner: str = "nuomi"):
        self.db_path = Path(db_path)
        self.partner = partner
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：lifespan（事件循环线程）创建、工具/测试线程使用；
        # 写操作统一走 _lock 串行化。
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        _ensure_table(self.db)
        self.facts: list[MemoryFact] = []
        self._load()

    # ---------- 读写 ----------

    def _load(self):
        rows = self.db.execute("SELECT * FROM facts WHERE partner = ?", (self.partner,)).fetchall()
        self.facts = [
            MemoryFact(
                id=r["id"],
                content=r["content"],
                category=r["category"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                access_count=r["access_count"],
            )
            for r in rows
        ]

    def _save(self):
        """全量落库（接口兼容：调用方语义不变）。"""
        with self._lock, self.db:
            self.db.execute("DELETE FROM facts WHERE partner = ?", (self.partner,))
            self.db.executemany(
                "INSERT OR REPLACE INTO facts "
                "(id, partner, content, category, created_at, updated_at, access_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        f.id,
                        self.partner,
                        f.content,
                        f.category,
                        f.created_at,
                        f.updated_at,
                        f.access_count,
                    )
                    for f in self.facts
                ],
            )

    def _touch(self, fact: MemoryFact):
        fact.updated_at = time.time()
        with self._lock, self.db:
            self.db.execute(
                "UPDATE facts SET updated_at = ?, access_count = ? WHERE id = ?",
                (fact.updated_at, fact.access_count, fact.id),
            )

    def add(self, content: str, category: str = "fact") -> MemoryFact | None:
        content = content.strip()
        if not content:
            return None
        # 去重：完全一致，或已存在包含新内容（近似重复不再存）
        for f in self.facts:
            if f.content == content or content in f.content:
                f.access_count += 1
                self._touch(f)
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
        overlap: float = float(len(qg & fg))
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
            self._touch(f)
        return hits

    def recent(self, top_k: int = 3) -> list[MemoryFact]:
        return sorted(self.facts, key=lambda f: f.created_at, reverse=True)[:top_k]

    def snapshot(self) -> dict:
        return {"total": len(self.facts), "facts": [f.to_dict() for f in self.facts]}


# ---------- 记忆 v2：MemoryBackend 契约（provider 可插拔，对齐 Hermes） ----------
# 设计：docs/memory-provider-design.md
# - 上层（注入中间件/记忆工具）只依赖 MemoryBackend，不感知 JSON/SQLite/Mem0 实现
# - 内置默认 = FileMemoryBackend（包装 SQLite facts 表，纯本地零依赖）
# - 外部 provider = 独立插件（如 memory-mem0），实现同一契约，profile 一行切换
# - 双档语义（对齐 Hermes）：category ∈ {user, preference} → USER 档（用户画像）；
#   其余 → MEMORY 档（agent 笔记）。快照注入带容量预算（char limit）。

# 快照注入预算（字符）：MEMORY 档 / USER 档
SNAPSHOT_CHAR_LIMITS = {"memory": 2000, "user": 1000}
# 归属 USER 档（用户画像）的 category 集合
USER_CATEGORIES = {"user", "preference"}


@dataclass
class MemoryEntry:
    """契约层条目（与存储实现解耦）。"""

    id: str
    content: str
    category: str = "fact"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class MemoryBackend(Protocol):
    """记忆后端契约。replace/remove 返回 (code, msg)：
    1=成功 / 0=未找到 / -1=多条匹配（需更精确的子串）。
    """

    def add(self, content: str, category: str = "fact") -> MemoryEntry | None: ...

    def replace(self, old_text: str, content: str) -> tuple[int, str]: ...

    def remove(self, old_text: str) -> tuple[int, str]: ...

    def search(self, query: str, top_k: int = 3) -> list[MemoryEntry]: ...

    def snapshot(self) -> dict:
        """注入快照（Hermes 式）：{sections: [{name, entries, total_chars, char_limit}]}。"""
        ...

    # 置于末尾：避免方法名 `list` 遮蔽内建 list，导致类内后续注解解析失败（mypy）
    def list(self) -> list[MemoryEntry]: ...


class FileMemoryBackend:
    """内置默认 provider：包装 SQLite MemoryStore（facts 表，纯本地）。

    - add：沿用去重（完全一致/已包含）+ 300 条淘汰
    - replace/remove：唯一子串定位（Hermes 语义；匹配多条报错要求更精确）
    - snapshot：双档 + char_limit 预算截取（常用/最新优先），供冻结快照注入
    """

    def __init__(self, store: MemoryStore, char_limits: dict[str, int] | None = None):
        self.store = store
        self.char_limits = {**SNAPSHOT_CHAR_LIMITS, **(char_limits or {})}

    # ---------- 契约实现 ----------

    @staticmethod
    def _entry(f: MemoryFact) -> MemoryEntry:
        return MemoryEntry(
            id=f.id,
            content=f.content,
            category=f.category,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )

    def add(self, content: str, category: str = "fact") -> MemoryEntry | None:
        f = self.store.add(content, category=category)
        return self._entry(f) if f else None

    def _unique_matches(self, old_text: str) -> list[MemoryFact]:
        return [f for f in self.store.facts if old_text and old_text in f.content]

    def replace(self, old_text: str, content: str) -> tuple[int, str]:
        content = content.strip()
        if not content:
            return 0, "新内容为空，未替换"
        matches = self._unique_matches(old_text)
        if not matches:
            return 0, f"未找到包含「{old_text}」的记忆"
        if len(matches) > 1:
            names = " / ".join(f"「{m.content[:24]}」" for m in matches[:3])
            return -1, f"「{old_text}」匹配到多条记忆（{names}…），请用更精确的片段"
        f = matches[0]
        f.content = content
        f.updated_at = time.time()
        self.store._save()
        return 1, f"已替换为：{content}"

    def remove(self, old_text: str) -> tuple[int, str]:
        matches = self._unique_matches(old_text)
        if not matches:
            return 0, f"未找到包含「{old_text}」的记忆"
        if len(matches) > 1:
            return -1, f"「{old_text}」匹配到多条记忆，请用更精确的片段"
        self.store.remove(matches[0].id)
        return 1, f"已删除：{matches[0].content}"

    def search(self, query: str, top_k: int = 3) -> list[MemoryEntry]:
        return [self._entry(f) for f in self.store.search(query, top_k=top_k)]

    def snapshot(self) -> dict:
        sections = []
        for key, name in (("memory", "MEMORY"), ("user", "USER")):
            entries: list[MemoryEntry] = []
            total = 0
            limit = self.char_limits.get(key, 2000)
            # 常用/最新优先；累计超出预算即止（至少保留一条）
            ranked = sorted(
                self.store.facts,
                key=lambda f: (f.access_count, f.updated_at),
                reverse=True,
            )
            for f in ranked:
                if (f.category in USER_CATEGORIES) != (key == "user"):
                    continue
                if entries and total + len(f.content) > limit:
                    break
                entries.append(self._entry(f))
                total += len(f.content)
            sections.append(
                {
                    "name": name,
                    "entries": entries,
                    "total_chars": total,
                    "char_limit": limit,
                }
            )
        return {"sections": sections}

    # 置于末尾：避免方法名 `list` 遮蔽内建 list，导致类内后续注解解析失败（mypy）
    def list(self) -> list[MemoryEntry]:
        return [self._entry(f) for f in self.store.facts]


# ---------- 应用内单例（由内核模块 service-memory / memory-mem0 注入；记忆工具经 get_backend 读取） ----------
_store: MemoryStore | None = None
_backend: MemoryBackend | None = None


def set_store(store: MemoryStore):
    global _store
    _store = store


def get_store() -> MemoryStore:
    if _store is None:
        raise RuntimeError("MemoryStore 尚未初始化（需在 lifespan 中 set_store）")
    return _store


def set_backend(backend: MemoryBackend | None):
    """切换记忆 provider（service-memory / memory-mem0 启动时调用；None=清空回退默认）。"""
    global _backend
    _backend = backend


def get_backend() -> MemoryBackend:
    """记忆工具/注入的统一读点；未显式 set_backend 时回退包装默认 store。"""
    if _backend is not None:
        return _backend
    if _store is not None:
        return FileMemoryBackend(_store)
    raise RuntimeError("记忆后端尚未初始化（需 service-memory 或 memory-mem0 插件提供）")
