"""知识库检索：一轮对话的跨库 top-k 检索（抄 Octop ``retrieve.py``，单用户裁剪）。

流程：**两路召回**（向量 ``KnowledgeIndex.search`` + BM25 ``keyword_search``，各自过取
候选池）→ ``fusion.fuse`` 归一加权 → 按融合分取 top-k → 按字符预算逐条拼接
（引用头 + 文本）→ 追加 citations 标记。OCR 无关。

只走向量时关键词等于弃权，反之亦然：嵌入模型未就绪或查询向量化失败时自动退化为
纯关键词召回，不让整条链路空手而归。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from app.infra.knowledge.citations import append_citations_marker, citations_from_ranked
from app.infra.knowledge.embed import embed_knowledge_texts
from app.infra.knowledge.fusion import fuse
from app.infra.knowledge.index import Hit, KnowledgeIndex
from app.infra.knowledge.onnx_service import load_config
from app.infra.knowledge.params import get_advanced_settings
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
    keyword_weight: float | None = None,
) -> str:
    """返回格式化可读上下文；检索不可用/无结果时返回空串。

    ``keyword_weight`` 为关键词这一路的权重（0-1），不传则取高级参数里的
    ``KNOWLEDGE_HYBRID_KEYWORD_WEIGHT``。
    """
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
                keyword_weight=keyword_weight,
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
    keyword_weight: float | None = None,
) -> str:
    cfg = load_config()
    if not (cfg.enabled and cfg.model):
        return ""

    query_text = (query or "").strip()
    weight = (
        get_advanced_settings()["hybrid_keyword_weight"]
        if keyword_weight is None
        else keyword_weight
    )
    pool = max(k * 3, k + 8)

    query_vector: list[float] = []
    try:
        vectors = embed_knowledge_texts([query_text])
        query_vector = list(vectors[0]) if vectors else []
    except Exception:
        logger.warning("query embedding failed; keyword-only recall", exc_info=True)
    if not query_vector:
        logger.info("knowledge recall degraded to keyword-only")

    repo = KnowledgeRepo()
    vector_hits: dict[tuple[str, str], Hit] = {}
    keyword_hits: dict[tuple[str, str], Hit] = {}
    owners: dict[tuple[str, str], tuple[Any, Any]] = {}

    def _collect(
        target: dict[tuple[str, str], Hit],
        kb_id: str,
        base: Any,
        ready_documents: dict[str, Any],
        hits: list[Hit],
    ) -> None:
        for hit in hits:
            document = ready_documents.get(hit.doc_id)
            if document is None:
                continue
            key = (kb_id, hit.chunk_id)
            target[key] = hit
            owners[key] = (base, document)

    for kb_id in _unique_ids(knowledge_base_ids):
        base = repo.get_base(kb_id)
        if base is None:
            continue
        ready_documents = {
            document.id: document
            for document in repo.list_documents(kb_id)
            if document.status == "ready" and not document.is_dir
        }
        index = KnowledgeIndex(kb_id)
        if query_vector:
            _collect(vector_hits, kb_id, base, ready_documents, index.search(query_vector, pool))
        _collect(keyword_hits, kb_id, base, ready_documents, index.keyword_search(query_text, pool))

    if not owners:
        return ""

    fused = fuse(
        {key: hit.score for key, hit in vector_hits.items()},
        {key: hit.score for key, hit in keyword_hits.items()},
        keyword_weight=weight,
    )
    ranked: list[tuple[Any, Hit, Any]] = [
        (
            owners[key][0],
            vector_hits.get(key) or keyword_hits[key],
            owners[key][1],
        )
        for key, _score in fused[:k]
    ]
    return _format_context(ranked, char_budget=char_budget)


def _unique_ids(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(kb_id).strip() for kb_id in ids if str(kb_id).strip()))


def _format_context(ranked: Sequence[tuple[Any, Hit, Any]], *, char_budget: int) -> str:
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
