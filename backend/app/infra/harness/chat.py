"""对话桥：ChatRequest → 标准化事件流（token / tool / usage / done）。

内部事件结构（OpenAI 格式翻译层消费）：
    {"type": "token",       "content": "你"}
    {"type": "tool_call",   "name": "touch_special", "args": "{}", "id": "call_0"}
    {"type": "tool_result", "name": "touch_special", "content": "..."}
    {"type": "usage",       "input_tokens": 1, "output_tokens": 2}
    {"type": "done",        "answer": "完整回复"}

对外统一输出 OpenAI Chat Completions 格式（stream_openai_sse），
表情/动作由模型插件工具驱动（工具名即动作/表情名），不再有独立的 emotion 事件。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from octop_harness import ChatRequest
from octop_harness.protocols.langgraph import AgentEventType

from app.infra.harness.manager import manager


def _stamp_knowledge(request_kwargs: dict, *, explicit_ids: list[str] | None) -> None:
    """知识库启用时写入本轮 configurable（显式指定才注入，无默认打开一说）。

    未启用时不写 configurable——检索工具未挂载，中间件也无从改写。
    visible_bases 只含启用库：停用库不进检索工具描述（对话侧同样不展示）。
    """
    from app.infra.knowledge.default_open import stamp_turn_knowledge_config
    from app.infra.knowledge.onnx_service import load_config
    from app.infra.knowledge.repo import KnowledgeRepo

    if not load_config().enabled:
        return
    bases = [b for b in KnowledgeRepo().list_bases() if b.enabled]
    stamp_turn_knowledge_config(
        request_kwargs, visible_bases=bases, explicit_ids=explicit_ids
    )


async def stream_chat(
    messages: str,
    thread_id: str,
    *,
    agent_id: str,
    name: str,
    system_prompt: str,
    workspace_dir=None,
    plugin_tools: list | None = None,
    skills_dir=None,
    skills_disabled: frozenset[str] = frozenset(),
    mcp_server_configs: dict | None = None,
    mcp_default_servers: list[str] | None = None,
    skills: list[str] | None = None,
    connectors: list[str] | None = None,
    model: str | None = None,
    knowledge_base_ids: list[str] | None = None,
) -> AsyncIterator[dict]:
    """流式对话：把 harness 事件翻译成 nuomi 标准化事件。

    workspace_dir：专家级工作区（persona 文件自动注入、独立记忆/sessions）；None 用全局数据根。
    skills / connectors / model 为 per-turn 能力选择（对齐 octop 对话框语义）：
    - skills=None 全量技能；[] 禁用全部技能；[name/slug...] 只启用这些
    - connectors=None 用默认连接器（agent 配置的 mcp_default_servers）；
      [] 不挂载连接器；[name...] 只挂载这些连接器
    - model=None 用 agent 默认模型；[provider/model] 覆盖本次模型（harness 原生优先）
    - knowledge_base_ids=None 本轮不注入；[] 本轮不注入；[id...] 只检索这些库
      （显式指定才注入，无默认打开；未知 id 由路由层校验）
    """
    agent = manager.get_agent(
        agent_id,
        name=name,
        system_prompt=system_prompt,
        workspace_dir=workspace_dir,
        plugin_tools=plugin_tools,
        skills_dir=skills_dir,
        skills_disabled=skills_disabled,
        mcp_server_configs=mcp_server_configs,
        mcp_default_servers=mcp_default_servers,
    )
    if connectors is None:
        mcp_use_default = bool(mcp_default_servers)
        mcp_servers = None
    elif not connectors:
        mcp_use_default = False
        mcp_servers = []
    else:
        mcp_use_default = False
        mcp_servers = connectors
    request_kwargs: dict = {
        "messages": messages,
        "thread_id": thread_id,
        "skills": skills,
        "mcp_servers": mcp_servers,
        "mcp_use_default": mcp_use_default,
        "model": model,
    }
    _stamp_knowledge(request_kwargs, explicit_ids=knowledge_base_ids)
    request = ChatRequest(**request_kwargs)

    text_parts: list[str] = []
    seen_tool_results: set[tuple] = set()
    pending_tools: dict[int, dict] = {}  # index -> {id, name, args}（聚合分块）
    async for event in agent.stream(request):
        ev_type = event.get("type")
        kind = getattr(ev_type, "value", ev_type)

        if kind == AgentEventType.TOKEN.value and event.get("content"):
            text_parts.append(event["content"])
            yield {"type": "token", "content": event["content"]}
        elif kind == AgentEventType.REASONING.value and event.get("content"):
            # 深度思考（reasoner 模型）：单独事件流，不计入正文 answer
            yield {"type": "reasoning", "content": event["content"]}
        elif kind == AgentEventType.TOOL_CALL_CHUNK.value:
            # 聚合工具调用分块（name 首个 chunk 携带，args 分块累积）
            idx = event.get("index", 0)
            slot = pending_tools.setdefault(
                idx, {"id": event.get("id", ""), "name": "", "args": ""}
            )
            if event.get("name"):
                slot["name"] = event["name"]
            if event.get("args"):
                slot["args"] += event["args"]
        elif kind == AgentEventType.TOOL_RESULT.value:
            # 工具结果到达 = 本轮工具调用已提交，先 flush 完整 tool_call 事件
            for idx in sorted(pending_tools):
                slot = pending_tools[idx]
                yield {
                    "type": "tool_call",
                    "name": slot["name"],
                    "args": slot["args"],
                    "id": slot["id"] or f"call_{idx}",
                }
            pending_tools.clear()
            for m in event.get("messages") or []:
                content = getattr(m, "content", None)
                if content:
                    key = (getattr(m, "name", None), str(content)[:200])
                    if key in seen_tool_results:
                        break  # langgraph 会对同一工具结果重复发事件，去重
                    seen_tool_results.add(key)
                    yield {
                        "type": "tool_result",
                        "name": getattr(m, "name", None),
                        "content": str(content)[:500],
                    }
                    break  # messages 可能含多个带 content 的消息，只透出首个结果
        elif kind == AgentEventType.USAGE.value:
            yield {
                "type": "usage",
                **{
                    k: v
                    for k, v in (event.get("usage") or {}).items()
                    if k in ("input_tokens", "output_tokens")
                },
            }

    answer = "".join(text_parts).strip()
    yield {"type": "done", "answer": answer}


def format_sse(event: dict) -> str:
    """把事件格式化为 SSE 帧（data: JSON）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _openai_chunk(chat_id: str, model: str, delta: dict, finish: str | None = None) -> str:
    """构造 OpenAI Chat Completions 流式 chunk。"""
    return f"data: {json.dumps({'id': chat_id, 'object': 'chat.completion.chunk', 'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}, ensure_ascii=False)}\n\n"


async def stream_openai_sse(
    events: AsyncIterator[dict],
    *,
    model: str = "nuomi",
    include_usage: bool = False,
    chat_id: str | None = None,
) -> AsyncIterator[str]:
    """把内部事件流翻译为 OpenAI Chat Completions SSE 帧（统一对外格式）。

    - token → delta.content
    - tool_call → delta.tool_calls（arguments 一次给全，流式客户端需自行累积）
    - usage → 末尾 usage chunk（仅当 include_usage，OpenAI stream_options 语义）
    - done → finish_reason="stop" + [DONE]
    """
    cid = chat_id or f"chatcmpl-{uuid.uuid4().hex[:24]}"
    usage: dict = {}
    async for ev in events:
        t = ev.get("type")
        if t == "token":
            yield _openai_chunk(cid, model, {"content": ev.get("content", "")})
        elif t == "tool_call":
            tool = {
                "index": 0,
                "id": ev.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                "function": {"name": ev.get("name", ""), "arguments": ev.get("args") or ""},
            }
            yield _openai_chunk(cid, model, {"tool_calls": [tool]})
        elif t == "usage":
            usage = {k: v for k, v in ev.items() if k in ("input_tokens", "output_tokens")}
        elif t == "done":
            yield _openai_chunk(cid, model, {}, finish="stop")
            if include_usage and usage:
                yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'model': model, 'choices': [], 'usage': {'prompt_tokens': usage.get('input_tokens', 0), 'completion_tokens': usage.get('output_tokens', 0), 'total_tokens': usage.get('input_tokens', 0) + usage.get('output_tokens', 0)}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"


async def stream_octop_sse(
    events: AsyncIterator[dict],
    *,
    thread_id: str,
    conversation_mode: str = "craft",
) -> AsyncIterator[str]:
    """把内部事件流翻译为 octop 原生事件帧（对齐 octop dashboard WS 协议）。

    通道仍是 HTTP SSE，但每个 ``data:`` 负载就是一个 octop 帧（JSON）：
    - token → {"type":"token","content","node":"model","thread_id"}
    - tool_call → {"type":"tool_call_chunk","id","name","args","index","node","thread_id"}
    - tool_result → {"type":"tool_result","node":"tools","messages":[{type,name,content}],"thread_id"}
    - usage → {"type":"usage","usage":{input_tokens,output_tokens},"node","thread_id"}
    - done → {"type":"done","conversation_mode","thread_id"}（后关闭流，无 [DONE]）

    消费者解析逻辑与未来切 WebSocket 时完全一致，只需换传输通道。
    """
    async for ev in events:
        t = ev.get("type")
        if t == "token":
            yield format_sse(
                {
                    "type": "token",
                    "content": ev.get("content", ""),
                    "node": "model",
                    "thread_id": thread_id,
                }
            )
        elif t == "reasoning":
            yield format_sse(
                {
                    "type": "reasoning",
                    "content": ev.get("content", ""),
                    "node": "model",
                    "thread_id": thread_id,
                }
            )
        elif t == "tool_call":
            yield format_sse(
                {
                    "type": "tool_call_chunk",
                    "id": ev.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    "name": ev.get("name", ""),
                    "args": ev.get("args") or "",
                    "index": 0,
                    "node": "model",
                    "thread_id": thread_id,
                }
            )
        elif t == "tool_result":
            yield format_sse(
                {
                    "type": "tool_result",
                    "node": "tools",
                    "messages": [
                        {"type": "tool", "name": ev.get("name"), "content": ev.get("content", "")}
                    ],
                    "thread_id": thread_id,
                }
            )
        elif t == "usage":
            yield format_sse(
                {
                    "type": "usage",
                    "usage": {
                        k: v for k, v in ev.items() if k in ("input_tokens", "output_tokens")
                    },
                    "node": "model",
                    "thread_id": thread_id,
                }
            )
        elif t == "done":
            yield format_sse(
                {
                    "type": "done",
                    "conversation_mode": conversation_mode,
                    "thread_id": thread_id,
                }
            )
