"""知识库引用标记：检索结果的机器可读标注（前端 Chat 解析渲染来源）。

抄 Octop ``infra/knowledge/citations.py``；单用户无权限字段。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, TypedDict

CITATIONS_MARKER_PREFIX = "<!--octop-kb-citations:"
CITATIONS_MARKER_SUFFIX = "-->"


class KnowledgeCitation(TypedDict):
    kb_id: str
    kb_name: str
    doc_id: str
    filename: str
    path: str


def citations_from_ranked(ranked: Sequence[tuple[Any, Any, Any]]) -> list[KnowledgeCitation]:
    """按检索顺序去重：每个文档只保留一条引用。"""
    seen: set[str] = set()
    out: list[KnowledgeCitation] = []
    for base, _hit, document in ranked:
        doc_id = str(getattr(document, "id", "") or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append(
            {
                "kb_id": str(getattr(base, "id", "") or ""),
                "kb_name": str(getattr(base, "name", "") or ""),
                "doc_id": doc_id,
                "filename": str(getattr(document, "filename", "") or doc_id),
                "path": str(getattr(document, "path", "") or ""),
            }
        )
    return out


_CITATIONS_MARKER_RE = re.compile(
    r"\n*\s*"
    + re.escape(CITATIONS_MARKER_PREFIX)
    + r"\[.*?\]"
    + re.escape(CITATIONS_MARKER_SUFFIX)
    + r"\s*$",
    re.DOTALL,
)


def append_citations_marker(text: str, citations: Sequence[KnowledgeCitation]) -> str:
    """在检索结果末尾追加引用标记（HTML 注释形态，LLM 通常忽略，前端解析）。"""
    body = (text or "").rstrip()
    if not body or not citations:
        return body
    payload = json.dumps(list(citations), ensure_ascii=False, separators=(",", ":"))
    return f"{body}\n\n{CITATIONS_MARKER_PREFIX}{payload}{CITATIONS_MARKER_SUFFIX}"


def strip_citations_marker(text: str) -> str:
    """从工具输出中移除引用标记（模型上下文不需要）。"""
    if not text or CITATIONS_MARKER_PREFIX not in text:
        return text
    return _CITATIONS_MARKER_RE.sub("", text).rstrip()
