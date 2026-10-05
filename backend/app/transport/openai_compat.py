"""OpenAI 兼容端点：/api/v1/chat/completions（AI 数字人壳（nuomi-avatar）零改动接入）。

协议：标准 OpenAI Chat Completions（stream: true 输出 SSE delta，data: [DONE] 结束）。
- model：默认专家；传 "agent:<agent_id>" 指定专家
- tools：接受但忽略（工具由 harness 运行时内部管理）
- 多轮 history：忽略（harness checkpointer 按 thread_id 管理上下文，thread 固定 desktop）
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.domain.agents.seed import default_system_prompt
from app.domain.agents.service import agent_service
from app.domain.chat.service import (
    PROJ_READY,
    thread_message_repo,
    thread_repo,
    turn_to_message_inputs,
)
from app.infra.harness.chat import stream_chat, stream_openai_sse
from app.transport.api import ensure_agent_runtime

router = APIRouter(prefix="/api/v1", tags=["openai"])


def _system_prompt_for(agent: dict) -> str:
    """专家人设（桌面 OpenAI 端点）。"""
    base = agent["system_prompt"] or default_system_prompt()
    return base


class OpenAIChatMessage(BaseModel):
    role: str
    content: str = ""


class StreamOptions(BaseModel):
    include_usage: bool = False


class OpenAIChatBody(BaseModel):
    model: str = "nuomi"
    messages: list[OpenAIChatMessage]
    stream: bool = False
    temperature: float | None = None
    stream_options: StreamOptions | None = None


def _resolve_agent(model: str) -> dict:
    """model 字段解析专家：默认专家 / agent:<agent_id>。"""
    if model.startswith("agent:"):
        agent_id = model.split(":", 1)[1]
        row = agent_service.get(agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        return row
    default_id = agent_service.default_agent_id()
    if not default_id:
        raise HTTPException(status_code=503, detail="尚无可用专家")
    row = agent_service.get(default_id)
    assert row is not None
    return row


def _last_user_text(messages: list[OpenAIChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user" and m.content.strip():
            return m.content
    raise HTTPException(status_code=400, detail="messages 缺少 user 内容")


def _chat_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


@router.post("/chat/completions")
async def chat_completions(body: OpenAIChatBody, request: Request) -> StreamingResponse:
    agent = _resolve_agent(body.model)
    user_text = _last_user_text(body.messages)
    system_prompt = _system_prompt_for(agent)
    include_usage = bool(body.stream_options and body.stream_options.include_usage)

    async def gen() -> AsyncIterator[str]:
        ensure_agent_runtime(agent)

        async def _persist_turn(turn: dict) -> None:
            """AI 数字人壳对话（thread=desktop）同样写消息投影（M4；失败不影响对话）。"""
            if thread_repo.get("desktop") is None:
                thread_repo.insert("desktop", agent["agent_id"], title="")
            if thread_message_repo.projection_status("desktop") != PROJ_READY:
                return
            inputs = turn_to_message_inputs(turn)
            if inputs:
                thread_message_repo.append("desktop", inputs)

        events = stream_chat(
            user_text,
            "desktop",
            agent_id=agent["agent_id"],
            name=agent["name"],
            system_prompt=system_prompt,
            agent_config=agent.get("config_json"),
            on_turn_complete=_persist_turn,
        )
        if body.stream:
            async for frame in stream_openai_sse(
                events,
                model=agent["name"],
                include_usage=include_usage,
            ):
                if await request.is_disconnected():
                    break
                yield frame
            return
        # 非流式：攒完整回答后一次性返回
        parts: list[str] = []
        async for event in events:
            if event["type"] == "token":
                parts.append(event["content"])
            if await request.is_disconnected():
                break
        answer = "".join(parts).strip()
        yield json.dumps(
            {
                "id": _chat_id(),
                "object": "chat.completion",
                "model": agent["name"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": answer},
                        "finish_reason": "stop",
                    }
                ],
            },
            ensure_ascii=False,
        )

    media = "text/event-stream" if body.stream else "application/json"
    return StreamingResponse(
        gen(), media_type=media, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
