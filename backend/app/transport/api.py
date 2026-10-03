"""API 路由：健康检查 + SSE 流式对话。

对话协议（桌宠前端消费）：
    POST /api/chat   body={"messages": "...", "thread_id": "..."}
    → SSE 事件流：token / tool_call / tool_result / usage / done
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.infra.harness.chat import format_sse, stream_chat

router = APIRouter(prefix="/api", tags=["chat"])


class ChatBody(BaseModel):
    messages: str = Field(description="用户输入文本")
    thread_id: str = Field(default="default", description="会话线程 ID（按线程隔离记忆）")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/chat")
async def chat(body: ChatBody, request: Request) -> StreamingResponse:
    async def gen():
        async for event in stream_chat(body.messages, body.thread_id):
            if await request.is_disconnected():
                break
            yield format_sse(event)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
