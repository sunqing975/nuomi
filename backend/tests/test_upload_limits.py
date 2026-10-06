"""上传限流测试（第 1 周遗留项：5 处裸 `await file.read()` 全量入内存）。

原实现是「全部读进内存之后再判大小」，知识库那个 100MB 上限甚至是读完才判。
现在统一走 `app/transport/uploads.read_upload`：先看 `file.size`（能不读就拒），
再分块读、超限立刻中断并 413。
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.transport.uploads import MAX_ARCHIVE_BYTES, MAX_DOCUMENT_BYTES, read_upload


def _upload(payload: bytes, *, size: int | None = None) -> UploadFile:
    return UploadFile(file=io.BytesIO(payload), size=len(payload) if size is None else size)


@pytest.mark.anyio
async def test_reads_within_limit() -> None:
    data = await read_upload(_upload(b"hello"), 1024, "插件包")
    assert data == b"hello"


@pytest.mark.anyio
async def test_declared_size_over_limit_rejected_without_reading() -> None:
    """file.size 已知时应当**不读内容**就拒绝（省掉整块内存分配）。"""

    class _NeverRead(io.BytesIO):
        def read(self, *a):  # pragma: no cover - 被调用即失败
            raise AssertionError("超限时不应再读内容")

    file = UploadFile(file=_NeverRead(b"x" * 10), size=10_000)
    with pytest.raises(HTTPException) as exc:
        await read_upload(file, 1024, "插件包")
    assert exc.value.status_code == 413
    assert "插件包过大" in exc.value.detail


@pytest.mark.anyio
async def test_streamed_size_over_limit_rejected_midway() -> None:
    """file.size 缺失（未知）时靠分块读取兜底 —— 不能因为拿不到 size 就放开。"""
    file = UploadFile(file=io.BytesIO(b"x" * 5000), size=None)
    with pytest.raises(HTTPException) as exc:
        await read_upload(file, 1024, "文档")
    assert exc.value.status_code == 413


def test_multipart_upload_over_limit_returns_413(client) -> None:
    """端到端：把包上限压到 1KB，传 2KB 的 zip 必须 413（而不是先吃进内存）。"""
    import app.transport.uploads as uploads

    original = uploads.MAX_ARCHIVE_BYTES
    try:
        uploads.MAX_ARCHIVE_BYTES = 1024
        r = client.post(
            "/api/plugins/import",
            files={"file": ("big.zip", b"x" * 2048, "application/zip")},
        )
        assert r.status_code == 413, r.text
        assert "过大" in r.json()["detail"]
    finally:
        uploads.MAX_ARCHIVE_BYTES = original


def test_limit_constants_are_sane() -> None:
    """上限之间要有一致的量级关系，别哪天被改成一个荒谬的值。"""
    assert 1024 * 1024 <= MAX_ARCHIVE_BYTES <= 200 * 1024 * 1024
    assert MAX_DOCUMENT_BYTES == 100 * 1024 * 1024  # 与 infra/knowledge/service 对齐
