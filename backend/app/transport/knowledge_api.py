"""知识库 API 路由（M6）：能力/模型管理 + 知识库 CRUD + 文档操作。

契约见 docs/knowledge-frontend-design.md §6。单用户：无 owner/shared 权限层。
模型下载为异步任务（不阻塞请求），前端轮询 /knowledge/capability 直到就绪。
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import asdict

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.infra.knowledge.jobs import enqueue_index_document, reindex_all_documents
from app.infra.knowledge.onnx_catalog import list_onnx_catalog_models
from app.infra.knowledge.onnx_download import download_model_raced
from app.infra.knowledge.onnx_service import (
    assert_catalog_model,
    delete_downloaded_model,
    embedding_models_dir,
    is_model_downloaded,
    load_config,
    mark_model_downloaded,
    save_config,
    status_payload,
)
from app.infra.knowledge.service import MAX_BASES, KnowledgeService

router = APIRouter(prefix="/api", tags=["knowledge"])

knowledge_service = KnowledgeService()

# 进行中的模型下载任务（避免重复下载）：model id → asyncio.Task。
_download_tasks: dict[str, asyncio.Task[None]] = {}


def _raise(exc: Exception) -> None:
    """service 异常 → HTTP 状态映射（detail 沿用服务层信息）。"""
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


async def _guard(call):
    """把同步的 knowledge_service 调用挪到线程池执行。

    知识库服务全是同步 sqlite + 文件 IO（上传写盘、解析、分块、重命名/删库动目录），
    在 async 端点里直接调 = 阻塞事件循环：传一个大 PDF 会让整个后端（含 /api/health
    与所有对话 SSE）失去响应。``asyncio.to_thread`` 不改变调用写法，只换执行线程。
    """
    try:
        return await asyncio.to_thread(call)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="同名知识库已存在") from None
    except Exception as exc:
        _raise(exc)
        raise  # pragma: no cover


# —— 能力 / 模型管理 ——


@router.get("/knowledge/capability")
async def capability() -> dict:
    payload = await asyncio.to_thread(status_payload)
    payload["max_bases"] = MAX_BASES
    payload["ocr_enabled"] = False  # OCR 能力接入后置（M6 已拍板，待实现）
    payload["downloading"] = sorted(_download_tasks)
    payload["presets_meta"] = list_onnx_catalog_models()
    return payload


class FeatureBody(BaseModel):
    enabled: bool | None = None
    model: str | None = None


@router.put("/knowledge/feature")
async def put_feature(body: FeatureBody) -> dict:
    cfg = load_config()
    next_model = (body.model or cfg.model).strip() if body.model is not None else cfg.model
    if next_model:
        next_model = await _guard(lambda: assert_catalog_model(next_model))
    enabled = body.enabled if body.enabled is not None else cfg.enabled
    model_changed = bool(next_model) and next_model != cfg.model
    if enabled and next_model and not await asyncio.to_thread(is_model_downloaded, next_model):
        raise HTTPException(status_code=400, detail=f"模型未下载，请先下载: {next_model}")
    await asyncio.to_thread(save_config, {"config": {"enabled": enabled, "model": next_model}})
    if model_changed and enabled:
        # 模型已切换：全部文档重置为 pending 并调度重索引（异步）。
        await asyncio.to_thread(reindex_all_documents, next_model)
    return await asyncio.to_thread(status_payload)


class DownloadBody(BaseModel):
    model: str = Field(min_length=1, max_length=200)


@router.post("/knowledge/onnx-download")
async def onnx_download(body: DownloadBody) -> dict:
    model = await _guard(lambda: assert_catalog_model(body.model))
    if await asyncio.to_thread(is_model_downloaded, model):
        return {"started": False, "reason": "already_downloaded", "model": model}
    if model in _download_tasks and not _download_tasks[model].done():
        return {"started": False, "reason": "already_running", "model": model}

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: download_model_raced(model, embedding_models_dir())
        )
        mark_model_downloaded(model)

    task = asyncio.create_task(_run())

    async def _cleanup(_task: asyncio.Task[None]) -> None:
        _download_tasks.pop(model, None)

    task.add_done_callback(_cleanup)
    _download_tasks[model] = task
    return {"started": True, "model": model}


@router.delete("/knowledge/onnx-model")
async def onnx_delete(model: str = Query(...)) -> dict:
    await _guard(lambda: assert_catalog_model(model))
    removed = await asyncio.to_thread(delete_downloaded_model, model)
    return {"ok": True, "removed": removed}


# —— 知识库 CRUD ——


class KnowledgeBaseBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    icon_name: str = Field(default="", max_length=100)
    max_documents: int | None = Field(default=None, ge=0, le=10_000)


@router.get("/knowledge-bases")
async def list_bases() -> list[dict]:
    bases = await asyncio.to_thread(knowledge_service.list_bases)
    return [asdict(b) for b in bases]


@router.post("/knowledge-bases")
async def create_base(body: KnowledgeBaseBody) -> dict:
    return await _guard(
        lambda: asdict(
            knowledge_service.create_base(
                name=body.name,
                description=body.description,
                icon_name=body.icon_name,
                max_documents=body.max_documents if body.max_documents is not None else 100,
            )
        )
    )


@router.get("/knowledge-bases/{kb_id}")
async def get_base(kb_id: str) -> dict:
    return asdict(await _guard(lambda: knowledge_service.get_base(kb_id)))


class KnowledgeBasePatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    icon_name: str | None = Field(default=None, max_length=100)
    max_documents: int | None = Field(default=None, ge=0, le=10_000)


@router.patch("/knowledge-bases/{kb_id}")
async def patch_base(kb_id: str, body: KnowledgeBasePatchBody) -> dict:
    return await _guard(
        lambda: asdict(
            knowledge_service.update_base(
                kb_id,
                name=body.name,
                description=body.description,
                enabled=body.enabled,
                icon_name=body.icon_name,
                max_documents=body.max_documents,
            )
        )
    )


@router.delete("/knowledge-bases/{kb_id}")
async def delete_base(kb_id: str) -> dict:
    await _guard(lambda: knowledge_service.delete_base(kb_id))
    return {"ok": True}


# —— 文档操作 ——


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(kb_id: str, prefix: str | None = None) -> list[dict]:
    docs = await _guard(lambda: knowledge_service.list_documents(kb_id, prefix=prefix))
    return [asdict(d) for d in docs]


class FolderBody(BaseModel):
    path: str = Field(min_length=1, max_length=500)


@router.post("/knowledge-bases/{kb_id}/folders")
async def create_folder(kb_id: str, body: FolderBody) -> dict:
    return asdict(await _guard(lambda: knowledge_service.create_folder(kb_id, body.path)))


class TextDocBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: str = Field(default="md", pattern="^(md|txt)$")
    content: str = ""
    path: str | None = Field(default=None, max_length=500)


@router.post("/knowledge-bases/{kb_id}/documents/text")
async def create_text_document(kb_id: str, body: TextDocBody) -> dict:
    row = await _guard(
        lambda: knowledge_service.create_text_document(
            kb_id, name=body.name, format=body.format, content=body.content, path=body.path
        )
    )
    enqueue_index_document(kb_id, row.id)
    return asdict(row)


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(kb_id: str, file: UploadFile = File(...)) -> dict:
    from app.transport.uploads import MAX_DOCUMENT_BYTES, read_upload

    # 边读边限流：原先 await file.read() 全量入内存，100MB 上限是读完才判
    content = await read_upload(file, MAX_DOCUMENT_BYTES, "文档")
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    row = await _guard(
        lambda: knowledge_service.upload_document(
            kb_id,
            filename=filename,
            content_type=file.content_type or "",
            content=content,
        )
    )
    enqueue_index_document(kb_id, row.id)
    return asdict(row)


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/preview")
async def preview_document(kb_id: str, doc_id: str) -> dict:
    return await _guard(lambda: knowledge_service.preview_document(kb_id, doc_id))


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/file")
async def document_file(kb_id: str, doc_id: str) -> FileResponse:
    path, filename, content_type = await _guard(
        lambda: knowledge_service.resolve_document_file(kb_id, doc_id)
    )
    return FileResponse(path, filename=filename, media_type=content_type)


class ContentBody(BaseModel):
    content: str


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/content")
async def read_content(kb_id: str, doc_id: str) -> dict:
    return await _guard(lambda: knowledge_service.read_text_document(kb_id, doc_id))


@router.put("/knowledge-bases/{kb_id}/documents/{doc_id}/content")
async def write_content(kb_id: str, doc_id: str, body: ContentBody) -> dict:
    row = await _guard(
        lambda: knowledge_service.update_text_document(kb_id, doc_id, content=body.content)
    )
    enqueue_index_document(kb_id, row.id)
    return asdict(row)


class RenameBody(BaseModel):
    new_name: str = Field(min_length=1, max_length=200)


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/rename")
async def rename_document(kb_id: str, doc_id: str, body: RenameBody) -> dict:
    return asdict(
        await _guard(
            lambda: knowledge_service.rename_document(kb_id, doc_id, new_name=body.new_name)
        )
    )


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
async def reindex_document(kb_id: str, doc_id: str) -> dict:
    row = await _guard(lambda: knowledge_service.reindex_document(kb_id, doc_id))
    enqueue_index_document(kb_id, row.id)
    return asdict(row)


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(kb_id: str, doc_id: str) -> dict:
    await _guard(lambda: knowledge_service.delete_document(kb_id, doc_id))
    return {"ok": True}
