"""SSE（Server-Sent Events）协议封装。

事件流协议（v1）：
  event: meta   data: {"thread_id": "..."}       —— 会话已确定（新建时由服务端生成）
  event: token  data: {"content": "你"}          —— 一个增量片段，前端逐字追加
  event: done   data: {"thread_id": "...", "content": "完整回复"}   —— 结束
  event: error  data: {"message": "..."}         —— 出错（流提前终止）
"""
from __future__ import annotations

import json


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
