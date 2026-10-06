"""上传读取的统一入口：**边读边限流**。

原实现是 5 处裸 ``await file.read()``（插件/技能 zip、VRM 模型、FBX 动作、知识库文档），
全量进内存之后才判大小 —— 知识库那个 100MB 上限甚至是「读完再判」。后果：

- 任何人都能让后端为一个超大上传分配等量内存（本机回环服务，但没有理由不设边界）；
- Starlette 的 ``UploadFile`` 超出阈值会落到磁盘临时文件，但 ``read()`` 仍会把它整个读回内存。

这里统一成：先看 ``file.size``（multipart 解析时已知，能**不读就拒**），再分块读并在
超限时立刻中断（``413``）。上限按用途区分，见各常量。
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

# 插件 / 技能 zip：与 importer._MAX_BYTES（解压后 50MB）同量级；zip 本身同样按 50MB 卡
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
# VRM 模型：常见 10–50MB，留足余量
MAX_MODEL_BYTES = 200 * 1024 * 1024
# Mixamo FBX 动作：通常几 MB
MAX_ANIMATION_BYTES = 100 * 1024 * 1024
# 知识库文档：与 infra/knowledge/service.MAX_DOCUMENT_BYTES 对齐（100MB）
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024

_CHUNK = 1024 * 1024


async def read_upload(file: UploadFile, max_bytes: int, label: str) -> bytes:
    """读取上传内容；超过 ``max_bytes`` 抛 413（不把超限内容读进内存）。"""
    declared = getattr(file, "size", None)
    if declared is not None and declared > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{label}过大：{declared / 1048576:.1f}MB 超过上限 {max_bytes // 1048576}MB",
        )

    parts: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{label}过大：超过上限 {max_bytes // 1048576}MB",
            )
        parts.append(chunk)
    return b"".join(parts)
