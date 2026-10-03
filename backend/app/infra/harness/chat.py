"""对话桥：ChatRequest → 标准化事件流（token / tool / usage / done）。

事件结构（前端桌宠消费）：
    {"type": "token",       "content": "你"}
    {"type": "tool_call",   "name": "what_to_eat", "args": "{...}"}
    {"type": "tool_result", "name": "what_to_eat", "content": "..."}
    {"type": "usage",       "input_tokens": 1, "output_tokens": 2}
    {"type": "done",        "answer": "完整回复"}
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from octop_harness import ChatRequest
from octop_harness.protocols.langgraph import AgentEventType

from app.infra.harness.manager import manager


async def stream_chat(
    messages: str,
    thread_id: str,
    *,
    agent_id: str,
    name: str,
    system_prompt: str,
) -> AsyncIterator[dict]:
    """流式对话：把 harness 事件翻译成 nuomi 标准化事件。"""
    agent = manager.get_agent(agent_id, name=name, system_prompt=system_prompt)
    request = ChatRequest(messages=messages, thread_id=thread_id)

    text_parts: list[str] = []
    async for event in agent.stream(request):
        ev_type = event.get("type")
        kind = getattr(ev_type, "value", ev_type)

        if kind == AgentEventType.TOKEN.value and event.get("content"):
            text_parts.append(event["content"])
            yield {"type": "token", "content": event["content"]}
        elif kind == AgentEventType.TOOL_CALL_CHUNK.value and event.get("name"):
            # 工具调用的首个 chunk 带 name；聚合 args 由 done 前的完整事件承载
            yield {"type": "tool_call", "name": event["name"], "args": event.get("args") or ""}
        elif kind == AgentEventType.TOOL_RESULT.value:
            for m in event.get("messages") or []:
                content = getattr(m, "content", None)
                if content:
                    yield {"type": "tool_result", "name": getattr(m, "name", None), "content": str(content)[:500]}
        elif kind == AgentEventType.USAGE.value:
            yield {"type": "usage", **{k: v for k, v in (event.get("usage") or {}).items() if k in ("input_tokens", "output_tokens")}}

    yield {"type": "done", "answer": "".join(text_parts).strip()}


def format_sse(event: dict) -> str:
    """把事件格式化为 SSE 帧（data: JSON）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
