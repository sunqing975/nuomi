"""知识库嵌入路由（对齐 Octop ``knowledge/embed``，先本地 ONNX，远端 API 后置）。

当前只实现本地后端：配置模型（``KNOWLEDGE_EMBEDDING_MODEL``，默认
``BAAI/bge-small-zh-v1.5``）→ fastembed 本地推理。远端 OpenAI 兼容
``/embeddings`` 后端按拍板后置，接入时在此扩展 ``backend == "remote"`` 分支。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.infra.knowledge.onnx_service import (
    embed_texts,
    require_embedding_prerequisites,
)


def embed_knowledge_texts(
    texts: Sequence[str],
    *,
    model: str | None = None,
) -> list[list[float]]:
    """通过本地嵌入后端向量化文本（保序）。

    调用方（索引/检索）需先满足前置（依赖 + 模型已下载）；此处再次校验，
    以便单测与直接调用能拿到可区分错误。
    """
    if not texts:
        return []
    cfg = require_embedding_prerequisites()
    selected = model.strip() if model and model.strip() else cfg.model
    return embed_texts(selected, texts)
