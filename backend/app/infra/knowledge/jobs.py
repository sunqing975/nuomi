"""进程内文档索引任务（抄 Octop ``jobs``；并发 2 + 线程池）。

上传/编辑后 ``enqueue_index_document`` 入队；``process_document`` 同步执行
parse → chunk → embed → 原子替换索引，并维护文档状态机
pending → processing → ready / failed。启动时 ``resume_pending_index_jobs``
恢复中断任务。
"""

from __future__ import annotations

import asyncio
import logging

from app.infra.knowledge.chunk import chunk_text
from app.infra.knowledge.embed import embed_knowledge_texts
from app.infra.knowledge.files import document_path
from app.infra.knowledge.index import KnowledgeIndex
from app.infra.knowledge.params import get_advanced_settings
from app.infra.knowledge.parse import parse_document
from app.infra.knowledge.repo import KnowledgeRepo

logger = logging.getLogger(__name__)

INDEX_CONCURRENCY = 2
_index_semaphore: asyncio.Semaphore | None = None

# 在飞任务强引用（防被 GC 提前回收）+ 异常消费。
# asyncio 只持弱引用：不保存返回值的话，任务可能被 GC 掉 → 文档永远卡 pending；
# 而没人 await 的任务异常只会打印一句 "Task exception was never retrieved"，
# 业务侧（文档状态）看起来却是"什么都没发生"。
_pending_tasks: set[asyncio.Task[None]] = set()


def _get_index_semaphore() -> asyncio.Semaphore:
    global _index_semaphore
    if _index_semaphore is None:
        _index_semaphore = asyncio.Semaphore(INDEX_CONCURRENCY)
    return _index_semaphore


def process_document(kb_id: str, doc_id: str) -> None:
    """同步 parse/chunk/embed 并原子替换一个文档的 chunk。"""
    repo = KnowledgeRepo()
    document = repo.get_document(doc_id)
    base = repo.get_base(kb_id)
    if document is None or document.kb_id != kb_id or base is None:
        raise LookupError("knowledge document or base not found")
    if document.is_dir:
        return
    repo.update_document(doc_id, status="processing", error_message="")
    try:
        path = document_path(kb_id, doc_id, document.filename)
        text = parse_document(path)
        knobs = get_advanced_settings()
        chunks = chunk_text(text, size=knobs["chunk_size"], overlap=knobs["chunk_overlap"])
        if not (text or "").strip() or not chunks:
            raise ValueError("knowledge document has no extractable text")
        embeddings = embed_knowledge_texts(chunks)
        KnowledgeIndex(kb_id).replace_doc_chunks(doc_id, chunks, embeddings)
        dimension = len(embeddings[0]) if embeddings else 0
        repo.update_document(doc_id, status="ready", error_message="", chunk_count=len(chunks))
        if dimension and base.embedding_dim != dimension:
            repo.update_base(kb_id, embedding_dim=dimension)
    except Exception as exc:
        repo.update_document(doc_id, status="failed", error_message=str(exc), chunk_count=0)
        raise


def enqueue_index_document(kb_id: str, doc_id: str) -> asyncio.Task[None]:
    """把 CPU/IO 密集的索引调度到事件循环之外。

    任务引用存进 ``_pending_tasks``（asyncio 只持弱引用，否则可能被 GC），
    完成后消费异常并记日志——``process_document`` 已把失败写进文档状态，
    这里只保证「异常不静默」且「不出现 Task exception was never retrieved」。
    """
    loop = asyncio.get_running_loop()
    sem = _get_index_semaphore()

    async def _run() -> None:
        async with sem:
            await loop.run_in_executor(None, process_document, kb_id, doc_id)

    task = asyncio.create_task(_run())
    _pending_tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        _pending_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("文档索引任务失败（文档状态已置 failed）: %s", exc)

    task.add_done_callback(_done)
    return task


def reindex_all_documents(embedding_model: str) -> None:
    """重置全部文档使用新嵌入模型并调度新工作。"""
    repo = KnowledgeRepo()
    documents = repo.reindex_all_documents(embedding_model)
    for document in documents:
        enqueue_index_document(document.kb_id, document.id)


def resume_pending_index_jobs() -> None:
    """恢复待索引工作（含上次进程中断时卡在 processing 的文档）。"""
    repo = KnowledgeRepo()
    documents = repo.resume_pending_documents()
    for document in documents:
        enqueue_index_document(document.kb_id, document.id)
