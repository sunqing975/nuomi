"""对话桥：ChatRequest → 标准化事件流（token / emotion / tool / usage / done）。

事件结构（前端桌宠消费）：
    {"type": "token",       "content": "你"}
    {"type": "emotion",     "name": "开心"}                 # 情绪事件（驱动表情）
    {"type": "tool_call",   "name": "what_to_eat", "args": "{...}"}
    {"type": "tool_result", "name": "what_to_eat", "content": "..."}
    {"type": "usage",       "input_tokens": 1, "output_tokens": 2}
    {"type": "done",        "answer": "完整回复"}
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from octop_harness import ChatRequest
from octop_harness.protocols.langgraph import AgentEventType

from app.infra.harness.manager import manager

# 桌宠情绪标签规范：与 openai_compat.MOOD_TAG_RULE 保持一致
MOOD_TAGS = ("开心", "生气", "难过", "惊讶", "害羞", "俏皮")
_MOOD_RE = re.compile(r"<(" + "|".join(MOOD_TAGS) + r")>")

# 追加到专家 system_prompt，驱动桌宠表情（原生对话端点也使用）
PET_MOOD_RULE = (
    "\n\n回复规范：每句话开头用情绪标签表达当前心情，选最符合的放句首："
    "<开心> <生气> <难过> <惊讶> <害羞> <俏皮>。不加标签就没有表情动画。"
)


def extract_emotion(answer: str) -> str | None:
    """从回复文本中提取第一个情绪标签；无标签返回 None。"""
    m = _MOOD_RE.search(answer)
    return m.group(1) if m else None


async def stream_chat(
    messages: str,
    thread_id: str,
    *,
    agent_id: str,
    name: str,
    system_prompt: str,
    plugin_tools: list | None = None,
    skills_dir=None,
    skills_disabled: frozenset[str] = frozenset(),
    mcp_server_configs: dict | None = None,
    mcp_default_servers: list[str] | None = None,
) -> AsyncIterator[dict]:
    """流式对话：把 harness 事件翻译成 nuomi 标准化事件。"""
    agent = manager.get_agent(
        agent_id,
        name=name,
        system_prompt=system_prompt,
        plugin_tools=plugin_tools,
        skills_dir=skills_dir,
        skills_disabled=skills_disabled,
        mcp_server_configs=mcp_server_configs,
        mcp_default_servers=mcp_default_servers,
    )
    request = ChatRequest(
        messages=messages,
        thread_id=thread_id,
        mcp_use_default=bool(mcp_default_servers),
    )

    text_parts: list[str] = []
    seen_tool_results: set[tuple] = set()
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
                    key = (getattr(m, "name", None), str(content)[:200])
                    if key in seen_tool_results:
                        break  # langgraph 会对同一工具结果重复发事件，去重
                    seen_tool_results.add(key)
                    yield {"type": "tool_result", "name": getattr(m, "name", None), "content": str(content)[:500]}
                    break  # messages 可能含多个带 content 的消息，只透出首个结果
        elif kind == AgentEventType.USAGE.value:
            yield {"type": "usage", **{k: v for k, v in (event.get("usage") or {}).items() if k in ("input_tokens", "output_tokens")}}

    answer = "".join(text_parts).strip()
    emotion = extract_emotion(answer)
    if emotion:
        yield {"type": "emotion", "name": emotion}
    yield {"type": "done", "answer": answer}


def format_sse(event: dict) -> str:
    """把事件格式化为 SSE 帧（data: JSON）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
