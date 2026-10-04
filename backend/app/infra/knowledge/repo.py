"""知识库元数据仓库：knowledge_bases / knowledge_documents（单用户裁剪 Octop）。

- 无 owner/shared/members：库与文档全量可见。
- 文件夹支持：``is_dir`` 行 + ``path`` 前缀匹配（大小写敏感，避免 LIKE 通配符坑）。
- 文档上限：``max_documents``（默认 100，0=不限），``doc_count`` 随增删维护。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from app.infra.knowledge.relpath import (
    ancestor_dirs,
    normalize_kb_path,
    path_basename,
    path_is_direct_child,
    path_parent,
)
from app.storage.db import connect, now_iso

_DIR_CONTENT_TYPE = "application/x-directory"
DEFAULT_MAX_DOCUMENTS = 100


def new_ulid() -> str:
    """文档 id（对齐 Octop ulid 形态；此处用短随机 hex 足够且无依赖）。"""
    return uuid.uuid4().hex[:24]


def _new_short_id() -> str:
    return uuid.uuid4().hex[:10]


def _bool_int(value: bool) -> int:
    return 1 if value else 0


def _map_rows(rows: list[sqlite3.Row], row_cls: type[Any]) -> list[Any]:
    return [row_cls.from_row(r) for r in rows]  # type: ignore[attr-defined]


@dataclass(frozen=True)
class KnowledgeBaseRow:
    id: str
    pk: int
    name: str
    description: str
    enabled: bool
    icon_name: str
    embedding_model: str
    embedding_dim: int
    doc_count: int
    max_documents: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> KnowledgeBaseRow:
        return cls(
            id=str(r["knowledge_base_id"]),
            pk=int(r["id"]),
            name=str(r["name"]),
            description=str(r["description"] or ""),
            enabled=bool(r["enabled"]),
            icon_name=str(r["icon_name"] or ""),
            embedding_model=str(r["embedding_model"] or ""),
            embedding_dim=int(r["embedding_dim"] or 0),
            doc_count=int(r["doc_count"] or 0),
            max_documents=int(r["max_documents"] or DEFAULT_MAX_DOCUMENTS),
            created_at=str(r["created_at"] or ""),
            updated_at=str(r["updated_at"] or ""),
        )


@dataclass(frozen=True)
class KnowledgeDocumentRow:
    id: str
    pk: int
    kb_id: str
    path: str
    filename: str
    is_dir: bool
    content_type: str
    byte_size: int
    content_hash: str
    status: str
    error_message: str
    chunk_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> KnowledgeDocumentRow:
        return cls(
            id=str(r["document_id"]),
            pk=int(r["id"]),
            kb_id=str(r["kb_id"]),
            path=str(r["path"]),
            filename=str(r["filename"] or path_basename(str(r["path"]))),
            is_dir=bool(int(r["is_dir"])),
            content_type=str(r["content_type"] or ""),
            byte_size=int(r["byte_size"] or 0),
            content_hash=str(r["content_hash"] or ""),
            status=str(r["status"] or "pending"),
            error_message=str(r["error_message"] or ""),
            chunk_count=int(r["chunk_count"] or 0),
            created_at=str(r["created_at"] or ""),
            updated_at=str(r["updated_at"] or ""),
        )


class KnowledgeRepo:
    def _allocate_base_id(self) -> str:
        for _ in range(16):
            kb_id = _new_short_id()
            if self.get_base(kb_id) is None:
                return kb_id
        raise RuntimeError("failed to allocate unique knowledge base id")

    def create_base(
        self,
        *,
        name: str,
        description: str = "",
        icon_name: str = "",
        embedding_model: str = "",
        embedding_dim: int = 0,
        max_documents: int | None = None,
    ) -> KnowledgeBaseRow:
        kb_id = self._allocate_base_id()
        ts = now_iso()
        with connect() as conn:
            conn.execute(
                "INSERT INTO knowledge_bases("
                "knowledge_base_id, name, description, enabled, icon_name, "
                "embedding_model, embedding_dim, doc_count, max_documents, created_at, updated_at"
                ") VALUES (?, ?, ?, 1, ?, ?, ?, 0, ?, ?, ?)",
                (
                    kb_id,
                    name,
                    description,
                    icon_name,
                    embedding_model,
                    embedding_dim,
                    max_documents if max_documents is not None else DEFAULT_MAX_DOCUMENTS,
                    ts,
                    ts,
                ),
            )
        row = self.get_base(kb_id)
        if row is None:
            raise RuntimeError(f"knowledge base insert failed: {kb_id}")
        return row

    def list_bases(self) -> list[KnowledgeBaseRow]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM knowledge_bases ORDER BY name").fetchall()
        return _map_rows(rows, KnowledgeBaseRow)

    def count_bases(self) -> int:
        with connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM knowledge_bases").fetchone()
        return int(row["c"]) if row else 0

    def get_base(self, kb_id: str) -> KnowledgeBaseRow | None:
        with connect() as conn:
            r = conn.execute(
                "SELECT * FROM knowledge_bases WHERE knowledge_base_id = ?",
                (kb_id,),
            ).fetchone()
        return KnowledgeBaseRow.from_row(r) if r else None

    def update_base(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        icon_name: str | None = None,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
        doc_count: int | None = None,
        max_documents: int | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        for column, value in (
            ("name", name),
            ("description", description),
            ("enabled", _bool_int(enabled) if enabled is not None else None),
            ("icon_name", icon_name),
            ("embedding_model", embedding_model),
            ("embedding_dim", embedding_dim),
            ("doc_count", doc_count),
            ("max_documents", max_documents),
        ):
            if value is None:
                continue
            fields.append(f"{column} = ?")
            params.append(value)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(now_iso())
        params.append(kb_id)
        with connect() as conn:
            conn.execute(
                f"UPDATE knowledge_bases SET {', '.join(fields)} WHERE knowledge_base_id = ?",
                params,
            )

    def delete_base(self, kb_id: str) -> None:
        """删除知识库：级联清 knowledge_documents 行（文件目录由 service 层 rmtree）。"""
        with connect() as conn:
            conn.execute("DELETE FROM knowledge_documents WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM knowledge_bases WHERE knowledge_base_id = ?", (kb_id,))

    def _get_document_by_path(
        self, conn: sqlite3.Connection, kb_id: str, path: str
    ) -> KnowledgeDocumentRow | None:
        r = conn.execute(
            "SELECT * FROM knowledge_documents WHERE kb_id = ? AND path = ?",
            (kb_id, path),
        ).fetchone()
        return KnowledgeDocumentRow.from_row(r) if r else None

    def ensure_folder(self, kb_id: str, path: str) -> KnowledgeDocumentRow:
        rel = normalize_kb_path(path)
        if not rel:
            raise ValueError("invalid knowledge folder path")
        ts = now_iso()
        with connect() as conn:
            for folder in ancestor_dirs(rel) + [rel]:
                existing = self._get_document_by_path(conn, kb_id, folder)
                if existing is not None:
                    if not existing.is_dir:
                        raise ValueError(f"path exists and is not a folder: {folder}")
                    continue
                conn.execute(
                    "INSERT INTO knowledge_documents("
                    "document_id, kb_id, path, filename, is_dir, content_type, byte_size, "
                    "content_hash, status, error_message, chunk_count, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, 1, ?, 0, '', 'ready', '', 0, ?, ?)",
                    (new_ulid(), kb_id, folder, path_basename(folder), _DIR_CONTENT_TYPE, ts, ts),
                )
        row = self.get_document_by_path(kb_id, rel)
        if row is None:
            raise RuntimeError(f"knowledge folder insert failed: {rel}")
        return row

    def create_document(
        self,
        *,
        kb_id: str,
        filename: str,
        content_type: str,
        byte_size: int,
        content_hash: str = "",
        status: str = "pending",
        max_documents: int | None = None,
        path: str | None = None,
    ) -> KnowledgeDocumentRow:
        rel = normalize_kb_path(path or filename)
        if not rel:
            raise ValueError("invalid knowledge document path")
        name = path_basename(rel)
        for folder in ancestor_dirs(rel):
            self.ensure_folder(kb_id, folder)
        doc_id = new_ulid()
        ts = now_iso()
        # None（调用方未指定）与 0（每库"不限"哨兵）都视为不限。
        enforce_limit = max_documents is not None and max_documents > 0
        with connect() as conn:
            if enforce_limit:
                cursor = conn.execute(
                    "UPDATE knowledge_bases SET doc_count = doc_count + 1, updated_at = ? "
                    "WHERE knowledge_base_id = ? AND doc_count < ?",
                    (ts, kb_id, max_documents),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"knowledge bases support at most {max_documents} documents")
            conn.execute(
                "INSERT INTO knowledge_documents("
                "document_id, kb_id, path, filename, is_dir, content_type, byte_size, "
                "content_hash, status, error_message, chunk_count, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, '', 0, ?, ?)",
                (doc_id, kb_id, rel, name, content_type, byte_size, content_hash, status, ts, ts),
            )
            if not enforce_limit:
                conn.execute(
                    "UPDATE knowledge_bases SET doc_count = doc_count + 1, updated_at = ? "
                    "WHERE knowledge_base_id = ?",
                    (ts, kb_id),
                )
        row = self.get_document(doc_id)
        if row is None:
            raise RuntimeError(f"knowledge document insert failed: {doc_id}")
        return row

    def list_documents(self, kb_id: str) -> list[KnowledgeDocumentRow]:
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_documents WHERE kb_id = ? ORDER BY is_dir DESC, path",
                (kb_id,),
            ).fetchall()
        return _map_rows(rows, KnowledgeDocumentRow)

    def list_children(self, kb_id: str, prefix: str = "") -> list[KnowledgeDocumentRow]:
        parent = normalize_kb_path(prefix)
        return [row for row in self.list_documents(kb_id) if path_is_direct_child(row.path, parent)]

    def get_document(self, doc_id: str) -> KnowledgeDocumentRow | None:
        with connect() as conn:
            r = conn.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?",
                (doc_id,),
            ).fetchone()
        return KnowledgeDocumentRow.from_row(r) if r else None

    def get_document_by_path(self, kb_id: str, path: str) -> KnowledgeDocumentRow | None:
        rel = normalize_kb_path(path)
        with connect() as conn:
            r = conn.execute(
                "SELECT * FROM knowledge_documents WHERE kb_id = ? AND path = ?",
                (kb_id, rel),
            ).fetchone()
        return KnowledgeDocumentRow.from_row(r) if r else None

    def update_document(
        self,
        doc_id: str,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        byte_size: int | None = None,
        content_hash: str | None = None,
        status: str | None = None,
        error_message: str | None = None,
        chunk_count: int | None = None,
        path: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[object] = []
        for column, value in (
            ("filename", filename),
            ("path", normalize_kb_path(path) if path is not None else None),
            ("content_type", content_type),
            ("byte_size", byte_size),
            ("content_hash", content_hash),
            ("status", status),
            ("error_message", error_message),
            ("chunk_count", chunk_count),
        ):
            if value is None:
                continue
            fields.append(f"{column} = ?")
            params.append(value)
        if not fields:
            return
        fields.append("updated_at = ?")
        params.append(now_iso())
        params.append(doc_id)
        with connect() as conn:
            conn.execute(
                f"UPDATE knowledge_documents SET {', '.join(fields)} WHERE document_id = ?",
                params,
            )

    def delete_document(self, doc_id: str) -> list[KnowledgeDocumentRow]:
        """删除文件或文件夹（含后代）。返回被删的行。"""
        ts = now_iso()
        document = self.get_document(doc_id)
        if document is None:
            return []
        with connect() as conn:
            if document.is_dir:
                # 大小写敏感前缀匹配（避免 LIKE 通配符与大小写折叠坑）。
                prefix = f"{document.path}/"
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents WHERE kb_id = ? AND "
                    "(path = ? OR substr(path, 1, ?) = ?)",
                    (document.kb_id, document.path, len(prefix), prefix),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_documents WHERE document_id = ?",
                    (doc_id,),
                ).fetchall()
            removed = _map_rows(rows, KnowledgeDocumentRow)
            file_count = sum(1 for row in removed if not row.is_dir)
            ids = [row.id for row in removed]
            if ids:
                placeholders = ", ".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM knowledge_documents WHERE document_id IN ({placeholders})",
                    ids,
                )
            if file_count:
                conn.execute(
                    "UPDATE knowledge_bases SET doc_count = CASE "
                    "WHEN doc_count > ? THEN doc_count - ? ELSE 0 END, "
                    "updated_at = ? WHERE knowledge_base_id = ?",
                    (file_count, file_count, ts, document.kb_id),
                )
        return removed

    def count_documents(self, kb_id: str) -> int:
        with connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_documents WHERE kb_id = ? AND is_dir = 0",
                (kb_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def reindex_all_documents(self, embedding_model: str) -> list[KnowledgeDocumentRow]:
        """更换全局嵌入模型后重置全部文档为待索引。"""
        ts = now_iso()
        with connect() as conn:
            conn.execute(
                "UPDATE knowledge_bases SET embedding_model = ?, embedding_dim = 0, updated_at = ?",
                (embedding_model, ts),
            )
            conn.execute(
                "UPDATE knowledge_documents "
                "SET status = 'pending', error_message = '', chunk_count = 0, updated_at = ? "
                "WHERE is_dir = 0",
                (ts,),
            )
            rows = conn.execute(
                "SELECT * FROM knowledge_documents WHERE status = 'pending' AND is_dir = 0 "
                "ORDER BY kb_id, document_id"
            ).fetchall()
        return _map_rows(rows, KnowledgeDocumentRow)

    def rename_document(
        self, kb_id: str, doc_id: str, new_name: str
    ) -> KnowledgeDocumentRow | None:
        """重命名文件/文件夹；文件夹会级联改写全部后代路径。"""
        document = self.get_document(doc_id)
        if document is None or document.kb_id != kb_id:
            return None
        parent = path_parent(document.path)
        new_path = normalize_kb_path(f"{parent}/{new_name}")
        ts = now_iso()
        with connect() as conn:
            if document.is_dir:
                prefix = f"{document.path}/"
                conn.execute(
                    "UPDATE knowledge_documents SET "
                    "path = ? || substr(path, ?), updated_at = ? "
                    "WHERE kb_id = ? AND substr(path, 1, ?) = ?",
                    (new_path, len(document.path) + 1, ts, kb_id, len(prefix), prefix),
                )
            conn.execute(
                "UPDATE knowledge_documents SET "
                "filename = ?, path = ?, updated_at = ? "
                "WHERE document_id = ?",
                (new_name, new_path, ts, doc_id),
            )
        return self.get_document(doc_id)

    def resume_pending_documents(self) -> list[KnowledgeDocumentRow]:
        """返回待索引工作；中断在 processing 的任务重置回 pending。"""
        ts = now_iso()
        with connect() as conn:
            conn.execute(
                "UPDATE knowledge_documents "
                "SET status = 'pending', error_message = '', updated_at = ? "
                "WHERE status = 'processing' AND is_dir = 0",
                (ts,),
            )
            rows = conn.execute(
                "SELECT * FROM knowledge_documents WHERE status = 'pending' AND is_dir = 0 "
                "ORDER BY kb_id, document_id"
            ).fetchall()
        return _map_rows(rows, KnowledgeDocumentRow)
