"""OpenAI 兼容端点：/api/v1/chat/completions（AI 数字人壳（nuomi-avatar）零改动接入）。

协议：标准 OpenAI Chat Completions（stream: true 输出 SSE delta，data: [DONE] 结束）。
- model：默认专家；传 "agent:<agent_id>" 指定专家
- tools：接受但忽略（工具由 harness 运行时内部管理）
- 多轮 history：忽略（harness checkpointer 按 thread_id 管理上下文，thread 固定 desktop）
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing

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
from app.transport.runtime import ensure_agent_runtime
from app.transport.streaming import SSE_HEADERS, stream_response

router = APIRouter(prefix="/api/v1", tags=["openai"])

logger = logging.getLogger(__name__)


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
    # P0-5：先以完整参数构造运行时实例（可能抛 HTTPException，须在 gen 之前完成，
    # 否则进流后异常只会中断连接）。chat_api 同款根因与处理。
    ensure_agent_runtime(agent)

    async def gen() -> AsyncIterator[str]:
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
        try:
            if body.stream:
                # aclosing：客户端断连 break 时关闭本层 SSE 生成器。注意机制——
                # aclose 只把 GeneratorExit 抛进**本层**；这层没有 try/finally，
                # 所以不会同步传播到上游。上游（LLM 流）是在引用释放后由 async
                # generator 终结器异步关闭的（实测让出若干次事件循环后生效）。
                # 效果成立，但别指望「break 完上游立刻关」。
                frames = stream_openai_sse(
                    events,
                    model=agent["name"],
                    include_usage=include_usage,
                )
                async with aclosing(frames) as stream:
                    async for frame in stream:
                        if await request.is_disconnected():
                            break
                        yield frame
                return
            # 非流式：攒完整回答后一次性返回
            parts: list[str] = []
            async with aclosing(events) as turn_events:
                async for event in turn_events:
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
        except Exception as exc:
            # 中途失败必须给壳一个明确的终止信号：壳只解析 SSE，流被截断会让它永久等待
            logger.exception("AI 数字人对话流异常（agent=%s）", agent["agent_id"])
            message = str(exc) or exc.__class__.__name__
            if body.stream:
                yield f"data: {json.dumps({'error': {'message': message}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            else:
                yield json.dumps({"error": {"message": message}}, ensure_ascii=False)

    media = "text/event-stream" if body.stream else "application/json"
    return await stream_response(
        gen, media_type=media, headers=SSE_HEADERS
    )
