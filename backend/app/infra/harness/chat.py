"""对话桥：ChatRequest → 标准化事件流（token / tool / usage / done）。

内部事件结构（OpenAI 格式翻译层消费）：
    {"type": "token",       "content": "你"}
    {"type": "tool_call",   "name": "touch_special", "args": "{}", "id": "call_0"}
    {"type": "tool_result", "name": "touch_special", "content": "..."}
    {"type": "usage",       "input_tokens": 1, "uncached_input_tokens": 1,
                            "cache_read_tokens": 0, "cache_write_tokens": 0,
                            "output_tokens": 2, "reasoning_tokens": 0, "total_tokens": 3}
    {"type": "done",        "answer": "完整回复"}

对外统一输出 OpenAI Chat Completions 格式（stream_openai_sse），
表情/动作由模型插件工具驱动（工具名即动作/表情名），不再有独立的 emotion 事件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator

from octop_harness import ChatRequest
from octop_harness.protocols.langgraph import AgentEventType

from app.infra.events import Events, event_bus
from app.infra.harness.manager import manager

logger = logging.getLogger(__name__)

# usage 事件透传白名单：对齐 octop normalize_usage_metadata 的规范化键。
# cache_read_tokens = 前缀缓存命中（DeepSeek prompt_cache_hit_tokens / OpenAI cached_tokens 归一化），
# uncached_input_tokens = 未命中部分——P0 缓存可观测（2026-10-08）的核心字段。
_USAGE_KEYS = (
    "input_tokens",
    "uncached_input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def friendly_stream_error(exc: BaseException) -> str:
    """把流中途的底层异常翻成用户能看懂的一句话（前端直接展示 message）。

    实测（2026-10-16，问「昨天 A 线生产情况怎么样？」）：MES 演示库最近几天是
    全 0 行，模型拿不到有效数字就一路换日期/换工具试，60 步撞上 LangGraph 的
    recursion_limit，前端收到的是一行英文
    ``Recursion limit of 60 reached without hitting a stop condition.``
    ——数字人产品不该把这种话甩给用户，所以这里做一个最小映射（不改写其它异常，
    未知异常仍然原样透出，便于排查）。
    """
    if exc.__class__.__name__ == "GraphRecursionError" or "Recursion limit" in str(exc):
        return (
            "这轮工具调用步数达到上限（60 步），任务没做完。"
            "请把要求拆小一点，或直接告诉我具体的日期/产线（例如「10 月 6 日 A 线」）。"
        )
    return str(exc) or exc.__class__.__name__


def _record_part(state: dict, part: dict) -> None:
    """按到达顺序记录本轮片段（text/reasoning/tool_call/tool_result）。

    历史回显原先只能用 turn 的汇总字段重建（正文 + 全部工具调用），于是工具卡片
    一律掉到正文下面，和用户刚看到的流式顺序对不上。这里把「模型实际产出的顺序」
    原样记下来，随 turn 一起交给投影层（additional_kwargs.display_segments）。

    合并规则与前端 ``appendStreamSegment`` 一致：相邻同类文本/思考才合并，工具
    调用与结果各自独立成段。
    """
    parts: list[dict] = state.setdefault("parts", [])
    last = parts[-1] if parts else None
    if (
        last is not None
        and part["type"] in ("text", "reasoning")
        and last.get("type") == part["type"]
    ):
        last["content"] = (last.get("content") or "") + (part.get("content") or "")
        return
    parts.append(part)


def _flush_pending_tools(pending: dict) -> list[dict]:
    """把当前累积的 tool_call 分块固化成完整调用，并清空累加器。

    必须在 flush 时就归档（`turn_tool_calls`）——原先只在流末尾从
    `pending_tools` 取，而 TOOL_RESULT 分支每次都会 `clear()`，导致
    done 时为空的 tool_calls 写进投影：对话历史里工具步骤时有时无
    （首次 backfill 有、之后增量追加没有）。
    """
    flushed: list[dict] = []
    for idx in sorted(pending):
        slot = pending[idx]
        flushed.append(
            {
                "id": slot["id"] or f"call_{idx}",
                "name": slot["name"],
                "args": slot["args"],
            }
        )
    pending.clear()
    return flushed


def _interrupted_turn(user: str | None, state: dict) -> dict:
    """把「已生成的一半」组织成 turn dict（与正常完成同构，标记 interrupted）。

    后端原先只在整轮跑完时才把 turn 交给上层投影；客户端断连（切页刷新/关窗口）
    或本轮抛错时什么都不写 —— 用户看到的后果是「会话还在，但刚才那一问一答全没了」。
    """
    state["turn_tool_calls"].extend(_flush_pending_tools(state["pending_tools"]))
    return {
        "user": user,
        "answer": "".join(state["text_parts"]).strip(),
        "reasoning": "".join(state["reasoning_parts"]).strip(),
        "tool_calls": state["turn_tool_calls"],
        "tool_results": state["tool_results"],
        "parts": state.get("parts") or [],
        "interrupted": True,
    }


def _report_archive_failure(task: asyncio.Task) -> None:
    """后台落库任务的异常只记日志（不能让它静默消失）。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("中断轮次投影写入失败（不影响连接清理）", exc_info=exc)


async def _archive_interrupted(on_turn_complete, user: str | None, state: dict) -> None:
    """断连/异常收尾：把半截轮次交给上层投影（失败只记日志，不阻断连接清理）。

    关键：断连时本协程所在的请求任务**已经处于取消状态**（Starlette/anyio 会在
    每个 await 处重新抛 CancelledError），直接 ``await on_turn_complete(...)`` 会被
    当场打断 —— 半截还是丢了。所以落库放进独立任务再 shield 等待：正常情况等它
    写完；被取消时任务照样跑完（DB 写入是毫秒级，用户下一次读历史就能看到）。
    """
    if on_turn_complete is None:
        return
    turn = _interrupted_turn(user, state)
    task = asyncio.get_running_loop().create_task(on_turn_complete(turn))
    task.add_done_callback(_report_archive_failure)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # 断连取消：任务已独立启动，不随本次取消丢失
        logger.info("断连收尾：半截轮次投影转入后台任务")


async def _translate_events(events, state: dict) -> AsyncGenerator[dict, None]:
    """把 harness 协议事件翻译成 nuomi 内部事件（token/tool/usage/approval）。

    HITL 命中时透出 ``approval_requested`` 后**立即终止**（不产生 done）——
    该轮对话暂停等待人工审批，后续由 ``resume_chat`` 续跑同一轮。
    """
    async for event in events:
        ev_type = event.get("type")
        kind = getattr(ev_type, "value", ev_type)

        if kind == AgentEventType.TOKEN.value and event.get("content"):
            state["text_parts"].append(event["content"])
            _record_part(state, {"type": "text", "content": event["content"]})
            yield {"type": "token", "content": event["content"]}
        elif kind == AgentEventType.REASONING.value and event.get("content"):
            state["reasoning_parts"].append(event["content"])
            _record_part(state, {"type": "reasoning", "content": event["content"]})
            yield {"type": "reasoning", "content": event["content"]}
        elif kind == AgentEventType.TOOL_CALL_CHUNK.value:
            # 聚合工具调用分块（name 首个 chunk 携带，args 分块累积）
            idx = event.get("index", 0)
            slot = state["pending_tools"].setdefault(
                idx, {"id": event.get("id", ""), "name": "", "args": ""}
            )
            if event.get("name"):
                slot["name"] = event["name"]
            if event.get("args"):
                slot["args"] += event["args"]
        elif kind == AgentEventType.TOOL_RESULT.value:
            # 工具结果到达 = 本轮工具调用已提交，先 flush 完整 tool_call 事件
            for call in _flush_pending_tools(state["pending_tools"]):
                state["turn_tool_calls"].append(call)
                _record_part(
                    state,
                    {
                        "type": "tool_call",
                        "name": call["name"],
                        "args": call["args"],
                        "id": call["id"],
                    },
                )
                yield {
                    "type": "tool_call",
                    "name": call["name"],
                    "args": call["args"],
                    "id": call["id"],
                }
            for m in event.get("messages") or []:
                content = getattr(m, "content", None)
                if content:
                    key = (getattr(m, "name", None), str(content)[:200])
                    if key in state["seen_tool_results"]:
                        break  # langgraph 会对同一工具结果重复发事件，去重
                    state["seen_tool_results"].add(key)
                    state["tool_results"].append(
                        {
                            "name": getattr(m, "name", None) or "",
                            "content": str(content)[:500],
                        }
                    )
                    _record_part(
                        state,
                        {
                            "type": "tool_result",
                            "name": getattr(m, "name", None) or "",
                            "content": str(content)[:500],
                        },
                    )
                    yield {
                        "type": "tool_result",
                        "name": getattr(m, "name", None),
                        "content": str(content)[:500],
                    }
                    break  # messages 可能含多个带 content 的消息，只透出首个结果
        elif kind == AgentEventType.USAGE.value:
            yield {
                "type": "usage",
                **{k: v for k, v in (event.get("usage") or {}).items() if k in _USAGE_KEYS},
            }
        elif kind == AgentEventType.HITL_REQUIRED.value:
            # 人工审批请求：透出审批卡片数据并终止本轮（对话暂停，等审批 API 续跑）
            yield {
                "type": "approval_requested",
                "request_id": uuid.uuid4().hex,
                "request": event.get("request") or {},
                "thread_id": state["thread_id"],
            }
            return


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
    stamp_turn_knowledge_config(request_kwargs, visible_bases=bases, explicit_ids=explicit_ids)


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
    agent_config: dict | None = None,
    on_turn_complete=None,
) -> AsyncGenerator[dict, None]:
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
    # 事件广播：对话开始（订阅者如会话日志在插件侧处理；异常由事件总线隔离）
    event_bus.emit(Events.conversation_started, thread_id=thread_id, agent_id=agent_id)
    _stamp_knowledge(request_kwargs, explicit_ids=knowledge_base_ids)
    # agents.config_json 运行时参数（max_iters/temperature/top_p/max_tokens/max_input_length）
    # 合并进 request（对齐 Octop runtime_limits；per-turn 显式值优先）
    if agent_config:
        from app.infra.harness.runtime_limits import apply_agent_runtime_to_stream_request

        request_kwargs = apply_agent_runtime_to_stream_request(request_kwargs, agent_config)
    request = ChatRequest(**request_kwargs)
    # Langfuse trace metadata（user/thread/agent；启用时注入，未启用原样返回）
    request = manager.enrich_request(request)

    state: dict = {
        "thread_id": thread_id,
        "text_parts": [],
        "reasoning_parts": [],
        "parts": [],
        "seen_tool_results": set(),
        "pending_tools": {},
        "turn_tool_calls": [],
        "tool_results": [],
    }
    paused = False
    finished = False
    try:
        async for ev in _translate_events(agent.stream(request), state):
            if ev.get("type") == "approval_requested":
                paused = True
                yield ev
                break
            yield ev
        finished = not paused
    finally:
        # 没跑完就退出（客户端断连 / 本轮异常）：先把已生成的部分落库，
        # 否则这一问一答会随着连接一起消失（后端只在整轮完成时投影）。
        if not finished:
            await _archive_interrupted(on_turn_complete, messages, state)
    if paused:
        # HITL 暂停：不投影、不发 done、不广播完成（对话在等人工审批，resume_chat 续跑）
        return

    answer = "".join(state["text_parts"]).strip()
    yield {"type": "done", "answer": answer}
    # 流结束时仍有未 flush 的分块（LLM 中断/异常等）→ 一并归档，避免丢工具调用
    state["turn_tool_calls"].extend(_flush_pending_tools(state["pending_tools"]))
    # 事件广播：对话完成（订阅者如 TTS 播报 / 记忆归档 / 观测在插件侧处理，
    # 对话流不写任何业务逻辑；订阅者异常由事件总线隔离，不阻断对话）。
    event_bus.emit(
        Events.conversation_completed, thread_id=thread_id, answer=answer, agent_id=agent_id
    )
    # 本轮完整消息投影（M4 messages 表）：对话结束后通知上层持久化；
    # 回调失败不阻断对话结果（投影只是历史展示加速层，checkpointer 仍是权威）。
    if on_turn_complete is not None:
        try:
            await on_turn_complete(
                {
                    "user": messages,
                    "answer": answer,
                    "reasoning": "".join(state["reasoning_parts"]).strip(),
                    # 本轮全部工具调用（flush 时归档，非从 pending_tools 现取）
                    "tool_calls": state["turn_tool_calls"],
                    "tool_results": state["tool_results"],
                    # 模型实际产出的片段顺序（历史回显据此还原工具与正文的穿插）
                    "parts": state["parts"],
                }
            )
        except Exception:
            logger.exception("turn 消息投影写入失败（不影响对话）")
    # Langfuse trace 落盘（启用时；flush 失败静默，不阻断对话结果）
    manager.flush_langfuse()


async def resume_chat(
    thread_id: str,
    decisions: list[dict],
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
    on_turn_complete=None,
) -> AsyncGenerator[dict, None]:
    """人工审批后继续被暂停的对话（HITL resume）。

    与 stream_chat 同构：取同一 agent 实例（缓存命中参数被忽略），以
    Command(resume=decisions) 续跑被 interrupt 暂停的 graph，翻译出 nuomi
    内部事件流（含最终的 done 与投影）。审批拒绝时 harness 直接产出错误
    ToolMessage，本层与正常工具结果同路径透出。
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
    state: dict = {
        "thread_id": thread_id,
        "text_parts": [],
        "reasoning_parts": [],
        "parts": [],
        "seen_tool_results": set(),
        "pending_tools": {},
        "turn_tool_calls": [],
        "tool_results": [],
    }
    paused = False
    finished = False
    try:
        async for ev in _translate_events(agent.resume_hitl(thread_id, decisions), state):
            if ev.get("type") == "approval_requested":
                paused = True
                yield ev
                break
            yield ev
        finished = not paused
    finally:
        # 同 stream_chat：续跑中途断连也要把已生成的部分落库
        if not finished:
            await _archive_interrupted(on_turn_complete, None, state)
    if paused:
        return

    answer = "".join(state["text_parts"]).strip()
    yield {"type": "done", "answer": answer}
    state["turn_tool_calls"].extend(_flush_pending_tools(state["pending_tools"]))
    event_bus.emit(
        Events.conversation_completed, thread_id=thread_id, answer=answer, agent_id=agent_id
    )
    if on_turn_complete is not None:
        try:
            # user 传 None：turn_to_message_inputs 对空 user 安全，避免重复插入用户消息
            await on_turn_complete(
                {
                    "user": None,
                    "answer": answer,
                    "reasoning": "".join(state["reasoning_parts"]).strip(),
                    "tool_calls": state["turn_tool_calls"],
                    "tool_results": state["tool_results"],
                    # 模型实际产出的片段顺序（历史回显据此还原工具与正文的穿插）
                    "parts": state["parts"],
                }
            )
        except Exception:
            logger.exception("turn 消息投影写入失败（不影响对话）")
    manager.flush_langfuse()


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
) -> AsyncGenerator[str, None]:
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
            usage = {k: v for k, v in ev.items() if k in _USAGE_KEYS}
        elif t == "done":
            yield _openai_chunk(cid, model, {}, finish="stop")
            if include_usage and usage:
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'model': model, 'choices': [], 'usage': {'prompt_tokens': input_tokens, 'completion_tokens': output_tokens, 'total_tokens': input_tokens + output_tokens, 'prompt_tokens_details': {'cached_tokens': usage.get('cache_read_tokens', 0)}}}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"


async def stream_octop_sse(
    events: AsyncIterator[dict],
    *,
    thread_id: str,
    conversation_mode: str = "craft",
) -> AsyncGenerator[str, None]:
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
                    "plugin_id": ev.get("plugin_id"),
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
                        {
                            "type": "tool",
                            "name": ev.get("name"),
                            "content": ev.get("content", ""),
                            "plugin_id": ev.get("plugin_id"),
                        }
                    ],
                    "thread_id": thread_id,
                }
            )
        elif t == "usage":
            yield format_sse(
                {
                    "type": "usage",
                    "usage": {k: v for k, v in ev.items() if k in _USAGE_KEYS},
                    "node": "model",
                    "thread_id": thread_id,
                }
            )
        elif t == "tts":
            yield format_sse(
                {
                    "type": "tts",
                    "audio_url": ev.get("audio_url", ""),
                    "thread_id": thread_id,
                }
            )
        elif t == "approval_requested":
            # HITL 人工审批请求（对话暂停，前端应展示审批卡片）
            yield format_sse(
                {
                    "type": "approval_requested",
                    "request_id": ev.get("request_id", ""),
                    "request": ev.get("request") or {},
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
