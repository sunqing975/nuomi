"""本地 ONNX 嵌入模型目录（对齐 Octop ``onnx_catalog``：推荐清单 + fastembed 元数据）。

- 推荐模型：Octop Finnie Memory 默认（中文优先）。
- 元数据：优先 fastembed ``TextEmbedding.list_supported_models()``；
  不可用（未安装/异常）时回退到内置表，保证下载/就绪检查仍可工作。
"""

from __future__ import annotations

from typing import Any

# 推荐模型（Octop Finnie Memory 默认）。
ONNX_PRESET_MODEL_IDS: tuple[str, ...] = (
    "BAAI/bge-small-zh-v1.5",
    "jinaai/jina-embeddings-v2-base-zh",
    "intfloat/multilingual-e5-large",
)

# fastembed 元数据缺失时回退的 HF 仓库 id（Qdrant ONNX 镜像等）。
_HF_SOURCE_FALLBACK: dict[str, str] = {
    "BAAI/bge-small-zh-v1.5": "Qdrant/bge-small-zh-v1.5",
    "jinaai/jina-embeddings-v2-base-zh": "xenova/jina-embeddings-v2-base-zh",
    "intfloat/multilingual-e5-large": "qdrant/multilingual-e5-large-onnx",
}

# fastembed 元数据缺失时回退的模型体积（GB，仅展示用）。
_FALLBACK_SIZE_GB: dict[str, float] = {
    "BAAI/bge-small-zh-v1.5": 0.09,
    "jinaai/jina-embeddings-v2-base-zh": 0.32,
    "intfloat/multilingual-e5-large": 1.2,
}


def _fastembed_meta_map() -> dict[str, dict[str, Any]]:
    """模型 id → fastembed 元数据条目（未安装/异常时返回空）。"""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return {}
    try:
        raw = TextEmbedding.list_supported_models()
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        model = item.get("model") or item.get("model_name") or item.get("id")
        if not isinstance(model, str) or not model:
            continue
        out[model] = item
    return out


def _hf_repo_from_sources(sources: object) -> str | None:
    """从 fastembed ``sources``（dict 或 ModelSource）读 HF 仓库 id。"""
    raw = sources.get("hf") if isinstance(sources, dict) else getattr(sources, "hf", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def get_onnx_model_meta(model_id: str) -> dict[str, Any]:
    """返回模型体积 / HF 仓库元数据（缺省用内置回退表）。"""
    meta = _fastembed_meta_map().get(model_id) or {}
    size = meta.get("size_in_GB")
    try:
        size_gb = float(size) if size is not None else None
    except (TypeError, ValueError):
        size_gb = None
    if size_gb is None:
        size_gb = _FALLBACK_SIZE_GB.get(model_id)
    hf_source = _hf_repo_from_sources(meta.get("sources")) or _HF_SOURCE_FALLBACK.get(model_id)
    return {
        "id": model_id,
        "size_gb": size_gb,
        "hf_source": hf_source,
        "supported": bool(meta),
    }


def list_onnx_catalog_models() -> list[dict[str, Any]]:
    """返回目录条目（推荐在前，其余按 fastembed 支持列表顺序）。"""
    recommended = set(ONNX_PRESET_MODEL_IDS)

    def enrich(model_id: str, *, rec: bool) -> dict[str, Any]:
        meta = _fastembed_meta_map().get(model_id)
        size_gb: float | None
        if meta:
            size = meta.get("size_in_GB")
            try:
                size_gb = float(size) if size is not None else None
            except (TypeError, ValueError):
                size_gb = None
            if size_gb is None:
                size_gb = _FALLBACK_SIZE_GB.get(model_id)
            hf = _hf_repo_from_sources(meta.get("sources")) or _HF_SOURCE_FALLBACK.get(model_id)
        else:
            info = get_onnx_model_meta(model_id)
            size_gb = info.get("size_gb")
            hf = info.get("hf_source")
        entry: dict[str, Any] = {
            "id": model_id,
            "name": model_id,
            "recommended": rec,
            "supported": True,
        }
        if size_gb is not None:
            entry["size_gb"] = size_gb
        if hf:
            entry["hf_source"] = hf
        return entry

    meta_map = _fastembed_meta_map()
    if meta_map:
        ordered = list(ONNX_PRESET_MODEL_IDS) + sorted(
            mid for mid in meta_map if mid not in recommended
        )
        return [enrich(mid, rec=mid in recommended) for mid in ordered]
    return [enrich(mid, rec=True) for mid in ONNX_PRESET_MODEL_IDS]
