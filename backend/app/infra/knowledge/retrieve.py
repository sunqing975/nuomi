"""知识库检索：一轮对话的跨库 top-k 检索（抄 Octop ``retrieve.py``，单用户裁剪）。

流程：查询向量 → 各选中库 ``KnowledgeIndex.search`` → 按分数排序 → 按字符预算
逐条拼接（引用头 + 文本）→ 追加 citations 标记。OCR 无关。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from app.infra.knowledge.citations import append_citations_marker, citations_from_ranked
from app.infra.knowledge.embed import embed_knowledge_texts
from app.infra.knowledge.index import Hit, KnowledgeIndex
from app.infra.knowledge.onnx_service import load_config
from app.infra.knowledge.repo import KnowledgeRepo

DEFAULT_RETRIEVAL_K = 8
DEFAULT_CONTEXT_CHAR_BUDGET = 6000

logger = logging.getLogger(__name__)

_PREAMBLE = "以下是知识库检索到的相关内容，供你参考："


async def retrieve_context(
    *,
    query: str | None,
    knowledge_base_ids: Sequence[str],
    k: int = DEFAULT_RETRIEVAL_K,
    char_budget: int = DEFAULT_CONTEXT_CHAR_BUDGET,
) -> str:
    """返回格式化可读上下文；检索不可用/无结果时返回空串。"""
    if not (query or "").strip() or not knowledge_base_ids or k <= 0 or char_budget <= 0:
        return ""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: _retrieve_context_sync(
                query=query,
                knowledge_base_ids=knowledge_base_ids,
                k=k,
                char_budget=char_budget,
            ),
        )
    except Exception:
        logger.warning("knowledge retrieval skipped", exc_info=True)
        return ""


def _retrieve_context_sync(
    *,
    query: str | None,
    knowledge_base_ids: Sequence[str],
    k: int,
    char_budget: int,
) -> str:
    cfg = load_config()
    if not (cfg.enabled and cfg.model):
        return ""
    query_vectors = embed_knowledge_texts([(query or "").strip()])
    if not query_vectors:
        return ""

    repo = KnowledgeRepo()
    selected_ids = _unique_ids(knowledge_base_ids)
    ranked: list[tuple[Any, Hit, Any]] = []
    for kb_id in selected_ids:
        base = repo.get_base(kb_id)
        if base is None:
            continue
        ready_documents = {
            document.id: document
            for document in repo.list_documents(kb_id)
            if document.status == "ready" and not document.is_dir
        }
        for hit in KnowledgeIndex(kb_id).search(query_vectors[0], k=k):
            document = ready_documents.get(hit.doc_id)
            if document is not None:
                ranked.append((base, hit, document))

    ranked.sort(key=lambda item: item[1].score, reverse=True)
    return _format_context(ranked[:k], char_budget=char_budget)


def _unique_ids(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(kb_id).strip() for kb_id in ids if str(kb_id).strip()))


def _format_context(
    ranked: Sequence[tuple[Any, Hit, Any]], *, char_budget: int
) -> str:
    sections: list[str] = []
    remaining = char_budget
    for base, hit, document in ranked:
        citation = f"[{base.name} · {document.filename} · 第 {hit.ordinal + 1} 段]"
        if remaining <= len(citation):
            break
        text = hit.text.strip()[: remaining - len(citation)]
        if not text:
            continue
        section = f"{citation}{text}"
        sections.append(section)
        remaining -= len(section)
    if not sections:
        return ""
    body = _PREAMBLE + "\n\n" + "\n\n".join(sections)
    return append_citations_marker(body, citations_from_ranked(ranked))
