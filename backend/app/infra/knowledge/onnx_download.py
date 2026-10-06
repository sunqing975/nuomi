"""HF 多源竞速下载 ONNX 嵌入模型（抄 Octop ``onnx_download``，裁剪 COS）。

- 候选源：HF 官方 + hf-mirror（Octop 另有自家 COS 桶，nuomi 无，已裁）。
- 竞速：并行探测 TTFB（Range GET），首个成功者获胜，其余按序兜底。
- 落地：``huggingface_hub.snapshot_download`` 写 fastembed 兼容缓存
  （``models--<owner>--<name>/``，snapshot/blobs 形态），完成由调用方写
  ``.downloaded`` 标记（见 onnx_service）。
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.infra.knowledge.onnx_catalog import get_onnx_model_meta

logger = logging.getLogger(__name__)

HF_ENDPOINT_OFFICIAL = "https://huggingface.co"
HF_ENDPOINT_MIRROR = "https://hf-mirror.com"

_PROBE_TIMEOUT_S = 4.0
_USER_AGENT = "nuomi-onnx-download"
# 只拉推理必需文件：tokenizer/config/onnx 权重，跳过无关大文件。
_HF_ALLOW_PATTERNS = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "preprocessor_config.json",
    "vocab.txt",
    "vocab.json",
    "merges.txt",
    "sentencepiece.bpe.model",
    "*.onnx",
    "*.onnx_data",
    "onnx/*.onnx",
    "onnx/*.onnx_data",
    "onnx/*.json",
)


@dataclass(frozen=True)
class DownloadCandidate:
    """一个可探测、可拉取的下载源。"""

    kind: str
    probe_url: str
    hf_endpoint: str
    hf_repo: str


ProbeFn = Callable[[str, float], float]


def _hf_repo_id(model_name: str) -> str:
    """解析 HF 仓库：目录元数据 hf_source 优先，否则用模型 id 本身。"""
    meta = get_onnx_model_meta(model_name)
    hf_source = meta.get("hf_source")
    if not isinstance(hf_source, str) or not hf_source.strip():
        return model_name.strip()
    return hf_source.strip()


def build_download_candidates(model_name: str) -> list[DownloadCandidate]:
    """构造官方 HF + hf-mirror 两个候选（探测文件 config.json）。"""
    hf_repo = _hf_repo_id(model_name)
    probe_file = "config.json"
    return [
        DownloadCandidate(
            kind="hf",
            probe_url=f"{HF_ENDPOINT_OFFICIAL}/{hf_repo}/resolve/main/{probe_file}",
            hf_endpoint=HF_ENDPOINT_OFFICIAL,
            hf_repo=hf_repo,
        ),
        DownloadCandidate(
            kind="hf-mirror",
            probe_url=f"{HF_ENDPOINT_MIRROR}/{hf_repo}/resolve/main/{probe_file}",
            hf_endpoint=HF_ENDPOINT_MIRROR,
            hf_repo=hf_repo,
        ),
    ]


def probe_source(url: str, timeout_s: float = _PROBE_TIMEOUT_S) -> float:
    """返回 1 KiB Range GET 的 TTFB（秒）。HTTP/网络错误向上抛。"""
    import time

    started = time.monotonic()
    with httpx.Client(
        timeout=httpx.Timeout(timeout_s, connect=min(3.0, timeout_s)),
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = client.get(url, headers={"Range": "bytes=0-1023"})
        if response.status_code not in {200, 206}:
            response.raise_for_status()
        _ = response.content[:16]
    return time.monotonic() - started


def _first_probe_success(
    futures: dict[Future[float], DownloadCandidate],
) -> tuple[DownloadCandidate, float] | None:
    """等待直到有探测成功；失败忽略、继续等；全失败返回 None。"""
    pending: set[Future[float]] = set(futures)
    while pending:
        done, pending = wait(pending, return_when=FIRST_COMPLETED)
        finished: list[tuple[float, DownloadCandidate]] = []
        for fut in done:
            cand = futures[fut]
            try:
                ttfb = fut.result()
            except Exception as exc:
                logger.info("ONNX source probe failed (%s): %s", cand.kind, exc)
                continue
            if ttfb < 0:
                continue
            finished.append((ttfb, cand))
        if finished:
            finished.sort(key=lambda item: item[0])
            ttfb, cand = finished[0]
            return cand, ttfb
    return None


def race_download_sources(
    candidates: list[DownloadCandidate],
    *,
    probe: ProbeFn = probe_source,
    timeout_s: float = _PROBE_TIMEOUT_S,
) -> list[DownloadCandidate]:
    """并行探测，首个成功者获胜并排最前，其余按目录序兜底。

    未胜出的探测会被取消而不是 join——被卡住的官方源不能拖慢镜像。
    全部失败时按目录序返回，调用方仍可尝试完整下载。
    """
    if not candidates:
        return []
    pool = ThreadPoolExecutor(max_workers=min(len(candidates), 3))
    try:
        futures = {pool.submit(probe, cand.probe_url, timeout_s): cand for cand in candidates}
        result = _first_probe_success(futures)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if result is None:
        logger.info("ONNX source probes all failed; falling back to catalog order")
        return list(candidates)
    winner, winner_ttfb = result
    logger.info(
        "ONNX source race winner=%s ttfb=%.3fs (n=%d)", winner.kind, winner_ttfb, len(candidates)
    )
    return [winner] + [c for c in candidates if c.kind != winner.kind]


def download_model_raced(model_name: str, cache_dir: Path) -> str:
    """竞速下载 *model_name* 到 *cache_dir*。返回获胜源 kind；全部失败抛错。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    candidates = build_download_candidates(model_name)
    ordered = race_download_sources(candidates)
    errors: list[str] = []
    for cand in ordered:
        try:
            _download_hf_snapshot(cand, cache_dir)
            logger.info("ONNX model %s downloaded from %s", model_name, cand.kind)
            return cand.kind
        except Exception as exc:
            logger.warning("ONNX download via %s failed: %s", cand.kind, exc)
            errors.append(f"{cand.kind}: {exc}")
    detail = "; ".join(errors) if errors else "no sources"
    raise RuntimeError(f"All embedding download sources failed: {detail}")


_HF_HUB_DISABLE_XET = "HF_HUB_DISABLE_XET"


def _disable_hf_xet() -> None:
    """强制 HTTP 快照下载；Xet CAS 经 hf-mirror 会 401/不可达。"""
    os.environ[_HF_HUB_DISABLE_XET] = "1"
    constants = sys.modules.get("huggingface_hub.constants")
    if constants is not None and hasattr(constants, _HF_HUB_DISABLE_XET):
        setattr(constants, _HF_HUB_DISABLE_XET, True)


def _download_hf_snapshot(cand: DownloadCandidate, cache_dir: Path) -> None:
    _disable_hf_xet()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required for HF model downloads") from exc
    logger.info("ONNX HF snapshot %s via %s", cand.hf_repo, cand.kind)
    # 屏蔽 tqdm 进度条输出（进度由调用方/API 层呈现）。
    with (
        open(os.devnull, "w", encoding="utf-8") as sink,
        redirect_stdout(sink),
        redirect_stderr(sink),
    ):
        snapshot_download(
            repo_id=cand.hf_repo,
            cache_dir=str(cache_dir),
            endpoint=cand.hf_endpoint,
            allow_patterns=list(_HF_ALLOW_PATTERNS),
        )
