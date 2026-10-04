"""本地嵌入服务最小验证（smoke test）：目录状态 + 模型下载 + fastembed 推理。

用法（backend/ 下）：`.venv/bin/python probe_embeddings.py [模型id]`
默认模型：BAAI/bge-small-zh-v1.5（Octop 默认推荐，中文小模型）。

验证目标：
1. 依赖（fastembed/onnxruntime）与模型目录就绪
2. 多源竞速下载（HF 官方 + hf-mirror）→ .downloaded 标记
3. fastembed 本地推理：向量维度、延迟、两个句子的相似度 sanity
"""
from __future__ import annotations

import asyncio
import sys

from app.infra.knowledge.onnx_catalog import list_onnx_catalog_models
from app.infra.knowledge.onnx_download import download_model_raced
from app.infra.knowledge.onnx_service import (
    DEFAULT_EMBEDDING_MODEL,
    embed_texts,
    embedding_models_dir,
    is_model_downloaded,
    list_downloaded_models,
    local_embedding_deps_available,
    mark_model_downloaded,
    model_cache_dir,
    probe_local_model,
    status_payload,
)


async def main() -> None:
    model = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMBEDDING_MODEL).strip()
    payload = status_payload()
    print(f"[info] 嵌入服务: enabled={payload['enabled']} model={payload['model']}")
    print(f"[info] 依赖可用: {payload['deps_available']}")
    print(f"[info] 模型目录: {payload['cache_dir']}")
    print(f"[info] 目录模型: {payload['presets']}")
    print(f"[info] 已下载: {payload['local_models']}")
    assert local_embedding_deps_available(), "fastembed 未安装"

    catalog_ids = {str(m["id"]) for m in list_onnx_catalog_models()}
    assert model in catalog_ids, f"模型不在目录: {model}"

    if not is_model_downloaded(model):
        print(f"[download] 下载 {model} …")
        winner = download_model_raced(model, embedding_models_dir())
        mark_model_downloaded(model)
        print(f"[ok] 下载完成（源={winner}）: {model_cache_dir(model)}")
    assert is_model_downloaded(model), "下载后仍检测不到 onnx 权重"
    print(f"[ok] 就绪: {model} → {list_downloaded_models()}")

    result = await probe_local_model(model)
    print(f"[probe] {result}")
    assert result.get("ok"), f"嵌入探测失败: {result}"

    def _similarity() -> float:
        vectors = embed_texts(model, ["糯米是住在电脑里的 AI 人格", "今天天气不错"])
        va, vb = vectors[0], vectors[1]
        dot = sum(x * y for x, y in zip(va, vb, strict=True))
        na = sum(x * x for x in va) ** 0.5
        nb = sum(x * x for x in vb) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    sim = await asyncio.get_running_loop().run_in_executor(None, _similarity)
    print(f"[sanity] 相似度(同语种句子): {sim:.4f}")
    assert sim > 0.1, "相似度异常（向量退化）"
    print("[ok] 验证全部通过 —— 下载/标记/本地推理链路正常")


if __name__ == "__main__":
    asyncio.run(main())
