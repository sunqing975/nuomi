"""每知识库一个 SQLite sidecar 向量索引（抄 Octop ``index``）。

``{workspace}/knowledge/{kb_id}/index.sqlite``，chunks 表存 chunk 文本与
float32 小端 BLOB 向量；检索 = 进程内全表余弦 top-k（文档量小场景够用）。
"""

from __future__ import annotations

import contextlib
import json
import math
import sqlite3
import struct
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.infra.knowledge.files import knowledge_base_dir
from app.infra.knowledge.keyword import bm25_scores


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    score: float
    metadata: dict[str, object]


class KnowledgeIndex:
    """每个知识库一个本地 SQLite 向量索引。"""

    def __init__(self, kb_id: str) -> None:
        self._path = knowledge_base_dir(kb_id) / "index.sqlite"
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """索引 sidecar（index.sqlite）的裸连接。

        注意与 ``app.storage.db.connect`` 的区别：那个是上下文管理器（会关闭），
        这个是普通工厂 —— 因此**每个 with 块都要用** ``contextlib.closing`` 包住，
        否则同样会漏 fd。本文件的用法统一走 ``_session()``。
        """
        return sqlite3.connect(self._path)

    @contextlib.contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """连接 + 提交 + 关闭（替代裸 ``with self._connect()``，后者不关闭连接）。"""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
                """
            )

    def replace_doc_chunks(
        self,
        doc_id: str,
        texts: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        *,
        metadata: Sequence[dict[str, object]] | None = None,
    ) -> None:
        """原子替换一个文档的全部 chunk（先删后插，单事务）。"""
        if len(texts) != len(embeddings):
            raise ValueError("texts and embeddings must have the same length")
        if metadata is not None and len(metadata) != len(texts):
            raise ValueError("metadata and texts must have the same length")
        rows: list[tuple[str, str, int, str, bytes, str]] = []
        for ordinal, (text, embedding) in enumerate(zip(texts, embeddings, strict=True)):
            vector = [float(value) for value in embedding]
            if not vector:
                raise ValueError("embedding cannot be empty")
            meta = metadata[ordinal] if metadata is not None else {}
            rows.append(
                (
                    f"{doc_id}:{ordinal}",
                    doc_id,
                    ordinal,
                    text,
                    struct.pack(f"<{len(vector)}f", *vector),
                    json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
                )
            )
        with self._session() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.executemany(
                "INSERT INTO chunks(chunk_id, doc_id, ordinal, text, embedding, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def delete_doc(self, doc_id: str) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))

    def search(self, query_vec: Sequence[float], k: int) -> list[Hit]:
        """进程内余弦相似度，返回得分最高的 ``k`` 个 chunk。"""
        if k <= 0:
            return []
        query = [float(value) for value in query_vec]
        if not query:
            raise ValueError("query vector cannot be empty")
        query_norm = math.sqrt(sum(value * value for value in query))
        if query_norm == 0:
            raise ValueError("query vector cannot be zero")
        with self._session() as conn:
            rows = conn.execute(
                "SELECT chunk_id, doc_id, ordinal, text, embedding, meta_json FROM chunks"
            ).fetchall()
        hits: list[Hit] = []
        for chunk_id, doc_id, ordinal, text, blob, meta_json in rows:
            embedding = struct.unpack(f"<{len(blob) // 4}f", blob)
            if len(embedding) != len(query):
                continue
            norm = math.sqrt(sum(value * value for value in embedding))
            score = (
                0.0
                if norm == 0
                else sum(a * b for a, b in zip(query, embedding, strict=True)) / (query_norm * norm)
            )
            decoded = json.loads(meta_json)
            hits.append(
                Hit(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    ordinal=ordinal,
                    text=text,
                    score=score,
                    metadata=decoded if isinstance(decoded, dict) else {},
                )
            )
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:k]

    def keyword_search(self, query: str, k: int) -> list[Hit]:
        """BM25 关键词召回：与 ``search`` 同表、同 ``Hit`` 结构、同 top-k 语义。

        分数是 BM25 原值（无界正数），归一与加权由 ``fusion.fuse`` 负责。
        """
        if k <= 0:
            return []
        with self._session() as conn:
            rows = conn.execute(
                "SELECT chunk_id, doc_id, ordinal, text, meta_json FROM chunks"
            ).fetchall()
        if not rows:
            return []
        scores = bm25_scores(query, [(row[0], row[3]) for row in rows])
        if not scores:
            return []
        by_chunk = {row[0]: row for row in rows}
        hits: list[Hit] = []
        for chunk_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]:
            _, doc_id, ordinal, text, meta_json = by_chunk[chunk_id]
            decoded = json.loads(meta_json)
            hits.append(
                Hit(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    ordinal=ordinal,
                    text=text,
                    score=score,
                    metadata=decoded if isinstance(decoded, dict) else {},
                )
            )
        return hits
