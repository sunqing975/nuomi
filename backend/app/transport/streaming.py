"""结构性保证（P0-5）：StreamingResponse 的 generator 里抛 HTTPException 不会转成 400。

FastAPI 只在「响应对象返回前」能把 HTTPException 转成错误响应；一旦进入
StreamingResponse 的 async generator，任何异常都只会中断连接，调用方看到"流断了"。

所以规矩是：**一切可能抛 HTTPException 的校验，必须在 gen() 之前、端点函数体内完成**。
本模块把这条规矩固定成唯一出口 ``stream_response()``：
  1. 先执行校验（校验可抛 HTTPException —— 此时还在端点函数体内，FastAPI 正常转 400/404）；
  2. 校验通过才构造 StreamingResponse 进流。

端点代码禁止直接 ``StreamingResponse(...)``（由 tests/test_streaming_guard.py 扫描锁定），
也禁止在 ``async def gen()`` 内 raise HTTPException（同一测试扫描锁定）。
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi.responses import StreamingResponse

# SSE 长连接统一响应头：Cache-Control 防代理缓存、X-Accel-Buffering 关 nginx 缓冲
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def stream_response(
    gen_factory: Callable[[], AsyncIterator[Any]],
    *,
    validate: Callable[[], Any] | None = None,
    media_type: str = "text/event-stream",
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """先校验（可抛 HTTPException），再构造 StreamingResponse 进流。

    - ``validate``：同步或异步的校验函数（可抛 HTTPException，FastAPI 会正常转错误响应）；
    - ``gen_factory``：返回 async generator 的工厂。**内部不许抛 HTTPException**，
      只做纯流式转发；中途异常必须以 SSE error 帧/日志形式呈现（见 chat_api / openai_compat）。
    """
    if validate is not None:
        result = validate()
        if inspect.isawaitable(result):
            await result
    return StreamingResponse(
        gen_factory(),
        media_type=media_type,
        headers=headers or SSE_HEADERS,
    )
