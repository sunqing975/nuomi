"""知识库文件布局（抄 Octop ``files``；目录在单根工作区下）。

```
{workspace}/knowledge/{kb_id}/docs/{doc_id}{suffix}   原始文档文件
{workspace}/knowledge/{kb_id}/index.sqlite            sidecar 向量索引（index.py）
```
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings


def knowledge_dir() -> Path:
    """知识库根目录（工作区 knowledge/）。"""
    path = settings.workspace_path / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_base_dir(kb_id: str) -> Path:
    path = knowledge_dir() / kb_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_dir(kb_id: str) -> Path:
    path = knowledge_base_dir(kb_id) / "docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def document_path(kb_id: str, doc_id: str, filename: str) -> Path:
    """原始文件路径：``docs/{doc_id}{suffix}``（suffix = 原文件扩展名）。"""
    suffix = Path(filename).suffix.lower()
    return documents_dir(kb_id) / f"{doc_id}{suffix}"


def write_document(kb_id: str, doc_id: str, filename: str, content: bytes) -> Path:
    dest = document_path(kb_id, doc_id, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def delete_document_file(kb_id: str, doc_id: str, filename: str) -> None:
    path = document_path(kb_id, doc_id, filename)
    if path.is_file():
        path.unlink(missing_ok=True)


def delete_knowledge_base_files(kb_id: str) -> None:
    """删除整个知识库目录（docs + index.sqlite）。"""
    path = knowledge_base_dir(kb_id)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
