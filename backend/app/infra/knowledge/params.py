"""知识库高级参数（抄 Octop ``params``；默认值即 Octop 默认）。

可从 env.json 覆盖：``KNOWLEDGE_CHUNK_SIZE`` / ``KNOWLEDGE_CHUNK_OVERLAP`` /
``KNOWLEDGE_RETRIEVAL_K`` / ``KNOWLEDGE_CONTEXT_CHAR_BUDGET``。
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_RETRIEVAL_K = 8
DEFAULT_CONTEXT_CHAR_BUDGET = 6000


def _int_env(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def get_advanced_settings() -> dict[str, Any]:
    """返回分块/检索参数（env 覆盖 + 范围钳制，对齐 Octop 设置键语义）。"""
    size = _int_env("KNOWLEDGE_CHUNK_SIZE", DEFAULT_CHUNK_SIZE, lo=100, hi=8000)
    overlap = _int_env("KNOWLEDGE_CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP, lo=0, hi=size - 1)
    return {
        "chunk_size": size,
        "chunk_overlap": overlap,
        "retrieval_k": _int_env("KNOWLEDGE_RETRIEVAL_K", DEFAULT_RETRIEVAL_K, lo=1, hi=20),
        "context_char_budget": _int_env(
            "KNOWLEDGE_CONTEXT_CHAR_BUDGET", DEFAULT_CONTEXT_CHAR_BUDGET, lo=500, hi=50000
        ),
    }
