"""知识库服务：元数据行与文件的同步编排（单用户裁剪 Octop ``service``）。

单用户模式无 owner/shared/members：库与文档全量可读写。文件落盘走
``files``（docs/{doc_id}{suffix}），索引与删除与 repo 事务保持同步。
"""

from __future__ import annotations

from pathlib import Path

from app.infra.knowledge.files import (
    delete_document_file,
    delete_knowledge_base_files,
    document_path,
    write_document,
)
from app.infra.knowledge.index import KnowledgeIndex
from app.infra.knowledge.onnx_service import load_config
from app.infra.knowledge.parse import OCR_IMAGE_SUFFIXES, parse_document
from app.infra.knowledge.relpath import normalize_kb_path, path_basename, path_parent
from app.infra.knowledge.repo import (
    DEFAULT_MAX_DOCUMENTS,
    KnowledgeBaseRow,
    KnowledgeDocumentRow,
    KnowledgeRepo,
)

MAX_BASES = 20
MAX_KB_MAX_DOCUMENTS = 10_000
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024  # 100MB（对齐 Octop DEFAULT_MAX_UPLOAD_MB）
_MAX_PREVIEW_CHARS = 200_000

_EXT_TO_CONTENT_TYPE = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".rst": "text/x-rst",
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_ALLOWED_CONTENT_TYPES = set(_EXT_TO_CONTENT_TYPE.values())
_TEXT_CONTENT_TYPES = {"text/plain", "text/markdown"}
_TEXT_FORMAT_TO_EXT = {"md": ".md", "txt": ".txt"}
_TEXT_FORMAT_TO_CONTENT_TYPE = {"md": "text/markdown", "txt": "text/plain"}


def _resolve_content_type(filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    mapped = _EXT_TO_CONTENT_TYPE.get(suffix)
    if mapped is not None:
        return mapped
    ct = (content_type or "").strip().lower()
    if ct in _ALLOWED_CONTENT_TYPES:
        return ct
    if ct in {"", "application/octet-stream"}:
        return ct
    return ct


class KnowledgeService:
    def __init__(self) -> None:
        self._repo = KnowledgeRepo()

    def create_base(
        self,
        *,
        name: str,
        description: str = "",
        icon_name: str = "",
        max_documents: int = DEFAULT_MAX_DOCUMENTS,
    ) -> KnowledgeBaseRow:
        if max_documents < 0 or max_documents > MAX_KB_MAX_DOCUMENTS:
            raise ValueError(f"max_documents must be between 0 and {MAX_KB_MAX_DOCUMENTS}")
        if self._repo.count_bases() >= MAX_BASES:
            raise ValueError(f"a user can own at most {MAX_BASES} knowledge bases")
        model = (load_config().model or "").strip()
        return self._repo.create_base(
            name=name,
            description=description,
            icon_name=icon_name,
            embedding_model=model,
            max_documents=max_documents,
        )

    def list_bases(self) -> list[KnowledgeBaseRow]:
        return self._repo.list_bases()

    def get_base(self, kb_id: str) -> KnowledgeBaseRow:
        base = self._repo.get_base(kb_id)
        if base is None:
            raise LookupError("knowledge base not found")
        return base

    def update_base(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        icon_name: str | None = None,
        max_documents: int | None = None,
    ) -> KnowledgeBaseRow:
        if max_documents is not None and (
            max_documents < 0 or max_documents > MAX_KB_MAX_DOCUMENTS
        ):
            raise ValueError(f"max_documents must be between 0 and {MAX_KB_MAX_DOCUMENTS}")
        self._repo.update_base(
            kb_id,
            name=name,
            description=description,
            enabled=enabled,
            icon_name=icon_name,
            max_documents=max_documents,
        )
        return self.get_base(kb_id)

    def delete_base(self, kb_id: str) -> None:
        self.get_base(kb_id)
        self._repo.delete_base(kb_id)
        delete_knowledge_base_files(kb_id)

    def list_documents(
        self, kb_id: str, *, prefix: str | None = None
    ) -> list[KnowledgeDocumentRow]:
        self.get_base(kb_id)
        if prefix is None:
            return self._repo.list_documents(kb_id)
        return self._repo.list_children(kb_id, prefix)

    def create_folder(self, kb_id: str, path: str) -> KnowledgeDocumentRow:
        self.get_base(kb_id)
        return self._repo.ensure_folder(kb_id, path)

    def preview_document(self, kb_id: str, doc_id: str) -> dict[str, str]:
        """返回提取的纯文本（供预览，最多 _MAX_PREVIEW_CHARS 字符）。"""
        document = self._require_document(kb_id, doc_id)
        path = document_path(kb_id, doc_id, document.filename)
        text = parse_document(path)
        if len(text) > _MAX_PREVIEW_CHARS:
            text = text[:_MAX_PREVIEW_CHARS]
        return {"id": document.id, "filename": document.filename, "text": text}

    def resolve_document_file(self, kb_id: str, doc_id: str) -> tuple[Path, str, str]:
        """返回 ``(path, filename, content_type)``；原文件丢失抛 FileNotFoundError。"""
        document = self._require_document(kb_id, doc_id)
        path = document_path(kb_id, doc_id, document.filename)
        if not path.is_file():
            raise FileNotFoundError("knowledge document original file not found")
        return path, document.filename, document.content_type

    def document_has_original(self, document: KnowledgeDocumentRow) -> bool:
        if document.is_dir:
            return False
        return document_path(document.kb_id, document.id, document.filename).is_file()

    def read_text_document(self, kb_id: str, doc_id: str) -> dict[str, str]:
        """返回可编辑 md/txt 文档的原始 UTF-8 文本。"""
        document = self._require_document(kb_id, doc_id)
        if document.content_type not in _TEXT_CONTENT_TYPES:
            raise ValueError("unsupported knowledge document content type: not editable text")
        raw = document_path(kb_id, doc_id, document.filename).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("knowledge document is not valid UTF-8 text") from exc
        return {
            "id": document.id,
            "filename": document.filename,
            "content_type": document.content_type,
            "text": text,
        }

    def create_text_document(
        self,
        kb_id: str,
        *,
        name: str,
        format: str,
        content: str = "",
        path: str | None = None,
    ) -> KnowledgeDocumentRow:
        """创建 md/txt 文档（可带草稿内容，随即入队索引）。"""
        fmt = (format or "").strip().lower().lstrip(".")
        if fmt not in _TEXT_FORMAT_TO_EXT:
            raise ValueError(f"unsupported knowledge document content type: {format}")
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            raise ValueError("invalid knowledge document filename")
        ext = _TEXT_FORMAT_TO_EXT[fmt]
        stem = Path(cleaned_name).name
        if Path(stem).suffix.lower() not in {".md", ".txt"}:
            stem = f"{stem}{ext}"
        elif Path(stem).suffix.lower() != ext:
            stem = f"{Path(stem).stem}{ext}"
        relative = f"{normalize_kb_path(path)}/{stem}" if path else stem
        relative = normalize_kb_path(relative)
        encoded = content.encode("utf-8")
        return self.upload_document(
            kb_id,
            filename=stem,
            content_type=_TEXT_FORMAT_TO_CONTENT_TYPE[fmt],
            content=encoded,
            path=relative,
        )

    def update_text_document(
        self, kb_id: str, doc_id: str, *, content: str
    ) -> KnowledgeDocumentRow:
        """覆盖 md/txt 内容并标记 pending（等待重索引）。"""
        document = self._require_document(kb_id, doc_id)
        if document.content_type not in _TEXT_CONTENT_TYPES:
            raise ValueError("unsupported knowledge document content type: not editable text")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise ValueError(
                f"knowledge document size exceeds maximum of {MAX_DOCUMENT_BYTES} bytes"
            )
        write_document(kb_id, document.id, document.filename, encoded)
        self._repo.update_document(
            doc_id,
            byte_size=len(encoded),
            status="pending",
            error_message="",
            chunk_count=0,
        )
        refreshed = self._repo.get_document(doc_id)
        if refreshed is None:
            raise LookupError("knowledge document not found")
        return refreshed

    def upload_document(
        self,
        kb_id: str,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        path: str | None = None,
    ) -> KnowledgeDocumentRow:
        base = self.get_base(kb_id)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError(
                f"knowledge document size exceeds maximum of {MAX_DOCUMENT_BYTES} bytes"
            )
        rel = normalize_kb_path(path or filename)
        name = path_basename(rel)
        if not name:
            raise ValueError("invalid knowledge document filename")
        if Path(name).suffix.lower() in OCR_IMAGE_SUFFIXES:
            # OCR 能力未接入前，图片文档直接拒绝（与 Octop 未启用 OCR 行为一致）。
            raise ValueError("knowledge OCR must be enabled for image documents")
        resolved_type = _resolve_content_type(name, content_type)
        if resolved_type not in _ALLOWED_CONTENT_TYPES:
            raise ValueError(f"unsupported knowledge document content type: {content_type}")
        document = self._repo.create_document(
            kb_id=kb_id,
            filename=name,
            path=rel,
            content_type=resolved_type,
            byte_size=len(content),
            max_documents=base.max_documents,
        )
        try:
            write_document(kb_id, document.id, name, content)
        except Exception:
            self._repo.delete_document(document.id)
            raise
        return document

    def delete_document(self, kb_id: str, doc_id: str) -> None:
        # 先校验文档存在（缺失/文件夹抛 LookupError），再删除行、索引与文件。
        self._require_document(kb_id, doc_id)
        removed = self._repo.delete_document(doc_id)
        for row in removed:
            if row.is_dir:
                continue
            KnowledgeIndex(kb_id).delete_doc(row.id)
            delete_document_file(kb_id, row.id, row.filename)

    def reindex_document(self, kb_id: str, doc_id: str) -> KnowledgeDocumentRow:
        document = self._require_document(kb_id, doc_id)
        if document.is_dir:
            raise ValueError("folders cannot be reindexed")
        self._repo.update_document(doc_id, status="pending", error_message="", chunk_count=0)
        refreshed = self._repo.get_document(doc_id)
        if refreshed is None:
            raise LookupError("knowledge document not found")
        return refreshed

    def rename_document(self, kb_id: str, doc_id: str, *, new_name: str) -> KnowledgeDocumentRow:
        document = self._require_document(kb_id, doc_id)
        cleaned = (new_name or "").strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned:
            raise ValueError("invalid knowledge document name")
        new_path = normalize_kb_path(f"{path_parent(document.path)}/{cleaned}")
        if new_path == document.path:
            return document
        if self._repo.get_document_by_path(kb_id, new_path) is not None:
            raise ValueError("a knowledge document with this name already exists")
        result = self._repo.rename_document(kb_id, doc_id, cleaned)
        if result is None:
            raise LookupError("knowledge document not found")
        return result

    def _require_document(self, kb_id: str, doc_id: str) -> KnowledgeDocumentRow:
        document = self._repo.get_document(doc_id)
        if document is None or document.kb_id != kb_id:
            raise LookupError("knowledge document not found")
        if document.is_dir:
            raise LookupError("knowledge document not found")
        return document
