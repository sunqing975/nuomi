"""本地 ONNX 嵌入服务：目录、下载生命周期与 fastembed 推理（抄 Octop ``onnx_service``）。

- 模型目录：``{workspace}/models/ai/embedding/``（单根工作区；`2D/` AI 数字人资产不动）。
- 缓存形态：fastembed 兼容 ``models--<owner>--<name>/``（snapshot/blobs）。
- 完成标记：``.downloaded/<name.replace('/','--')>``，能力门控就绪检查用。
- 推理：fastembed ``TextEmbedding(model_name, cache_dir=...)``（与 Octop 一致，不手写 onnxruntime 管线）。
- 配置：从 ``os.environ`` 读（env.json 已同步到进程环境）；键 ``KNOWLEDGE_EMBEDDING_MODEL``。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.infra.knowledge.onnx_catalog import (
    ONNX_PRESET_MODEL_IDS,
    get_onnx_model_meta,
    list_onnx_catalog_models,
)

DEFAULT_EMBEDDING_MODEL = ONNX_PRESET_MODEL_IDS[0]
_SETTINGS_MODEL_KEY = "KNOWLEDGE_EMBEDDING_MODEL"
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_LOCAL_PROBE_TEXT = "nuomi onnx probe"


def local_embedding_deps_available() -> bool:
    """True 当 fastembed 可导入（本地嵌入运行时）。"""
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def require_local_embedding_deps() -> None:
    """本地嵌入依赖缺失时报可区分错误（安装走 uv，不自动 pip）。"""
    if local_embedding_deps_available():
        return
    raise RuntimeError(
        "Local embedding components are not installed. "
        "Install via `uv pip install --python backend/.venv/bin/python fastembed huggingface_hub`."
    )


def normalize_onnx_model_id(model_name: str) -> str:
    """校验并规范化模型 id（防路径穿越）；不合法抛 ValueError。"""
    name = model_name.strip()
    if not name or len(name) > 200:
        raise ValueError("invalid model id")
    if ".." in name or "\\" in name or name.startswith("/") or name.endswith("/"):
        raise ValueError("invalid model id")
    if not _MODEL_ID_RE.fullmatch(name):
        raise ValueError("invalid model id")
    return name


def assert_catalog_model(model_name: str) -> str:
    """要求 *model_name* 是已知目录条目。"""
    name = normalize_onnx_model_id(model_name)
    catalog_ids = {str(m["id"]) for m in list_onnx_catalog_models()}
    if name not in catalog_ids:
        raise ValueError(f"model not in ONNX catalog: {name}")
    return name


@dataclass
class OnnxServiceConfig:
    enabled: bool = False
    model: str = DEFAULT_EMBEDDING_MODEL

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "model": self.model}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> OnnxServiceConfig:
        if not raw:
            return cls()
        model = str(raw.get("model") or DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
        return cls(enabled=bool(raw.get("enabled")), model=model)


def embedding_models_dir() -> Path:
    """本地嵌入模型根目录：``{workspace}/models/ai/embedding``。"""
    path = settings.workspace_path / "models" / "ai" / "embedding"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_cache_dir(model_name: str) -> Path:
    safe = "models--" + model_name.replace("/", "--")
    return embedding_models_dir() / safe


def _downloaded_marker_path(model_name: str) -> Path:
    return embedding_models_dir() / ".downloaded" / model_name.replace("/", "--")


def mark_model_downloaded(model_name: str) -> None:
    path = _downloaded_marker_path(model_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model_name, encoding="utf-8")


def _safe_under_cache(path: Path) -> Path | None:
    """路径必须位于模型目录内，否则返回 None（防误删）。"""
    root = embedding_models_dir().resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def _cache_has_onnx_weights(path: Path) -> bool:
    """目录内存在至少一个完整 onnx 权重文件（递归查找，兼容多布局）。

    ``is_file()`` 跟随 HF 缓存符号链接进 blobs/——下载中的快照条目不算。
    """
    if not path.is_dir():
        return False
    safe = _safe_under_cache(path)
    if safe is None:
        return False
    try:
        for weights in safe.rglob("*.onnx"):
            if weights.is_file():
                return True
    except OSError:
        return False
    return False


def _alias_cache_names(model_name: str) -> list[str]:
    """HF/fastembed 可能按 Qdrant 镜像 id 存储，需同时检查别名。"""
    names = [model_name]
    meta = get_onnx_model_meta(model_name)
    hf = meta.get("hf_source")
    if isinstance(hf, str) and hf.strip() and hf not in names:
        names.append(hf.strip())
    return names


def is_model_downloaded(model_name: str) -> bool:
    """仅当目录安全 id 在磁盘上有实际 onnx 权重文件时为真。"""
    try:
        model_name = normalize_onnx_model_id(model_name)
    except ValueError:
        return False
    for name in _alias_cache_names(model_name):
        if _cache_has_onnx_weights(model_cache_dir(name)):
            return True
        suffix = name.split("/")[-1] if "/" in name else name
        for candidate in (
            embedding_models_dir() / suffix,
            embedding_models_dir() / f"fast-{suffix}",
        ):
            if _cache_has_onnx_weights(candidate):
                return True
    return False


def list_downloaded_models() -> list[str]:
    """返回已下载（有 onnx 权重）的目录模型 id。"""
    found: set[str] = set()
    catalog_ids = {str(m["id"]) for m in list_onnx_catalog_models()}
    for mid in catalog_ids:
        if is_model_downloaded(mid):
            found.add(mid)
    marker_root = embedding_models_dir() / ".downloaded"
    if marker_root.is_dir():
        for child in marker_root.iterdir():
            if not child.is_file():
                continue
            try:
                mid = child.read_text(encoding="utf-8").strip()
            except OSError:
                mid = child.name.replace("--", "/", 1)
            if mid in catalog_ids and is_model_downloaded(mid):
                found.add(mid)
    return sorted(found)


def delete_downloaded_model(model_name: str) -> bool:
    """删除模型缓存与完成标记；返回是否删掉了东西。"""
    name = assert_catalog_model(model_name)
    removed = False
    targets = [model_cache_dir(name), _downloaded_marker_path(name)]
    for alias in _alias_cache_names(name):
        targets.append(model_cache_dir(alias))
        suffix = alias.split("/")[-1] if "/" in alias else alias
        targets.extend([embedding_models_dir() / suffix, embedding_models_dir() / f"fast-{suffix}"])
    for path in targets:
        safe = _safe_under_cache(path)
        if safe is None:
            continue
        if safe.is_file():
            safe.unlink(missing_ok=True)
            removed = True
        elif safe.is_dir():
            shutil.rmtree(safe, ignore_errors=True)
            removed = True
    return removed


def load_config() -> OnnxServiceConfig:
    """从进程环境读配置（env.json 已同步；缺失用默认模型）。"""
    raw = os.environ.get(_SETTINGS_MODEL_KEY, "").strip()
    if not raw:
        return OnnxServiceConfig()
    return OnnxServiceConfig(enabled=True, model=raw)


def embedding_prerequisites_ok_for_model(model: str) -> bool:
    """嵌入前置检查：依赖可导入 + 模型在目录 + 已下载。"""
    if not local_embedding_deps_available():
        return False
    if not model:
        return False
    try:
        model = assert_catalog_model(model)
    except ValueError:
        return False
    return is_model_downloaded(model)


def require_embedding_prerequisites_for_model(model: str) -> str:
    require_local_embedding_deps()
    if not model:
        raise RuntimeError("ONNX embedding model is not configured or not downloaded")
    model = assert_catalog_model(model)
    if not is_model_downloaded(model):
        raise RuntimeError("ONNX embedding model is not configured or not downloaded")
    return model


def embedding_prerequisites_ok() -> bool:
    return embedding_prerequisites_ok_for_model(load_config().model)


def require_embedding_prerequisites() -> OnnxServiceConfig:
    cfg = load_config()
    require_embedding_prerequisites_for_model(cfg.model)
    return cfg


def _build_text_embedding(model: str) -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model, cache_dir=str(embedding_models_dir()))


def embed_texts(model: str, texts: Sequence[str]) -> list[list[float]]:
    """本地嵌入一批文本（fastembed；结果与输入保序）。"""
    if not texts:
        return []
    require_local_embedding_deps()
    model = assert_catalog_model(model)
    emb = _build_text_embedding(model)
    out = [[float(x) for x in vec] for vec in emb.embed(list(texts))]
    if len(out) != len(texts):
        raise RuntimeError("embedding count mismatch")
    return out


async def probe_local_model(model: str) -> dict[str, Any]:
    """对一小段文本计时嵌入并报告向量宽度（全本地，不发网络请求）。"""
    if not model:
        return {"ok": False, "error": "no ONNX model selected"}
    try:
        model = assert_catalog_model(model)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not is_model_downloaded(model):
        return {"ok": False, "error": "model is not downloaded yet; download it before testing"}

    def _run() -> int:
        vectors = embed_texts(model, [_LOCAL_PROBE_TEXT])
        if not vectors:
            raise RuntimeError("embedding returned no vectors")
        return len(vectors[0])

    started = time.perf_counter()
    try:
        loop = asyncio.get_running_loop()
        dim = await loop.run_in_executor(None, _run)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "latency_ms": (time.perf_counter() - started) * 1000.0, "dim": dim}


def status_payload() -> dict[str, Any]:
    """嵌入服务状态（API 层用）。"""
    config = load_config()
    downloaded = is_model_downloaded(config.model) if config.model else False
    deps_ok = local_embedding_deps_available()
    return {
        "enabled": config.enabled,
        "model": config.model,
        "ready": bool(config.enabled and downloaded and deps_ok),
        "downloaded": downloaded,
        "cache_dir": str(embedding_models_dir()),
        "local_models": list_downloaded_models(),
        "presets": list(ONNX_PRESET_MODEL_IDS),
        "deps_available": deps_ok,
    }


def save_config(values: dict[str, Any]) -> dict[str, Any]:
    """保存嵌入服务配置到 env.json（模型/启停），返回保存后的键值。

    env_store 负责写盘与同步 os.environ；此处只构造 ``KNOWLEDGE_*`` 键。
    """
    from app.infra.env_store import load, save

    current = load()
    raw = values.get("config")
    config = OnnxServiceConfig.from_dict(raw if isinstance(raw, dict) else None)
    next_env = dict(current)
    if raw is not None or "enabled" in values:
        next_env[_SETTINGS_MODEL_KEY] = config.model
    next_env["KNOWLEDGE_EMBEDDING_ENABLED"] = "true" if config.enabled else "false"
    return save(next_env)
