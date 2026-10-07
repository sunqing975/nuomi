"""对话路由：SSE 流式对话 + 会话管理 + 对话历史 + 工具动作广播。

对话协议（AI 数字人前端/控制台消费）：
    POST /api/agents/{agent_id}/chat   body={"messages": "...", "thread_id": "..."}
    → OpenAI Chat Completions 流式格式（delta.content / delta.tool_calls / [DONE]）

会话：以工作区 nuomi-state.json 为权威（thread_id / threads，2026-10-04 起，
无 default AI 数字人线程、无模型专属会话；AI 数字人=纯表现层，拦截工具调用播放动作）。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import aclosing
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.domain.agents.service import (
    agent_service,
    ensure_agent_workspace,
)
from app.domain.chat.service import (
    PROJ_READY,
    chat_sessions,
    messages_to_inputs,
    thread_message_repo,
    thread_repo,
    turn_to_message_inputs,
)
from app.domain.plugins.service import plugin_service
from app.domain.skillpackages.service import skill_package_service
from app.domain.skills.service import skill_service
from app.infra.avatar_events import avatar_events
from app.infra.harness.chat import (
    format_sse,
    resume_chat,
    stream_chat,
    stream_octop_sse,
)
from app.transport.runtime import all_skills_dirs, ensure_agent_runtime
from app.transport.streaming import SSE_HEADERS, stream_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _available_skill_keys() -> set[str]:
    """per-turn 可用的技能名/slug 集合（已启用工作区技能 + 内置技能 + 已启用技能包内技能）。"""
    keys = {s["name"] for s in skill_service.list_all() if s.get("enabled")}
    keys.update(b["name"] for b in skill_service.builtin())
    for pkg in skill_package_service.list_all():
        if not pkg.get("enabled"):
            continue
        keys.update(s["slug"] for s in pkg.get("skills") or [] if s.get("enabled"))
    return keys


def _validate_knowledge_base_ids(ids: list[str] | None) -> None:
    """per-turn 知识库校验：非 None 时全部须存在且启用（对齐技能白名单语义）。

    空列表=明确不注入，跳过；显式指定已停用库 → 400（禁用库不出现在对话选择器）。
    """
    if not ids:
        return
    from app.infra.knowledge.repo import KnowledgeRepo

    repo = KnowledgeRepo()
    unknown = [kb_id for kb_id in ids if repo.get_base(kb_id) is None]
    if unknown:
        raise HTTPException(status_code=400, detail=f"知识库不存在: {', '.join(unknown)}")
    disabled = [kb_id for kb_id in ids if (b := repo.get_base(kb_id)) is not None and not b.enabled]
    if disabled:
        raise HTTPException(status_code=400, detail=f"知识库已停用: {', '.join(disabled)}")


async def _resolve_chat_abilities(skills, connectors) -> tuple[list[str] | None, list[str] | None]:
    """校验并归一化 per-turn 能力选择（skills / connectors），返回 (skills, connectors)。

    skills：None=全量技能；[]=禁用全部；列表=只启用这些（须存在于可用技能集合）。
    connectors：None=默认连接器（agent 配置）；[]=不挂载；列表=只挂载这些（须已配置）。

    async 的原因：``_available_skill_keys()`` 会读工作区 + 内置的全部 SKILL.md
    （实测 23–34ms，纯磁盘 IO）。留在事件循环上等于每轮对话白占 30ms，
    所以挪到线程池（校验结果不变）。
    """
    if skills is not None:
        for name in skills:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail="技能名不能为空")
        available = await asyncio.to_thread(_available_skill_keys)
        unknown = [n for n in skills if n not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"技能不存在或未启用: {', '.join(unknown)}")
        skills = [s.strip() for s in skills]
    if connectors is not None:
        for name in connectors:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail="连接器名不能为空")
        unknown = [n for n in connectors if n not in settings.mcp_servers]
        if unknown:
            raise HTTPException(status_code=400, detail=f"连接器不存在: {', '.join(unknown)}")
        connectors = [c.strip() for c in connectors]
    return skills, connectors


# ---------- 对话 ----------


class ChatBody(BaseModel):
    messages: str = Field(min_length=1, description="用户输入文本（必填）")
    thread_id: str = Field(default="default", description="会话线程 ID（按线程隔离记忆）")
    skills: list[str] | None = Field(
        default=None,
        description="本次对话启用的技能（name/slug；None=全部，[]=禁用全部）",
    )
    connectors: list[str] | None = Field(
        default=None,
        description="本次对话挂载的连接器（None=默认，[]=不挂载）",
    )
    model: str | None = Field(
        default=None,
        description="本次对话使用的模型（provider/model；None=默认模型）",
    )
    knowledge_base_ids: list[str] | None = Field(
        default=None,
        description="本次对话检索的知识库（None/[]=本轮不注入，[id...]=只检索这些库）",
    )

    @field_validator("messages")
    @classmethod
    def _messages_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("消息不能为空")
        return v


# ---------- 会话管理（工作区 nuomi-state.json 权威，控制台读写） ----------


class ChatNewBody(BaseModel):
    agent_id: str


class ChatSwitchBody(BaseModel):
    agent_id: str
    thread_id: str


class ChatTouchBody(BaseModel):
    agent_id: str
    thread_id: str
    title: str | None = None


@router.get("/chat/state")
async def chat_state(agent_id: str) -> dict:
    """某专家的当前会话 + 会话列表。"""
    return chat_sessions.state(agent_id)


@router.post("/chat/new")
async def chat_new(body: ChatNewBody) -> dict:
    """新建会话并设为当前（控制台「新会话」）。"""
    return chat_sessions.new(body.agent_id)


@router.post("/chat/switch")
async def chat_switch(body: ChatSwitchBody) -> dict:
    """切换当前会话（写 nuomi-state.json，控制台会话列表）。"""
    ok = chat_sessions.switch(body.agent_id, body.thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"agent_id": body.agent_id, "thread_id": body.thread_id}


@router.post("/chat/touch")
async def chat_touch(body: ChatTouchBody) -> dict:
    """更新会话时间/标题。"""
    chat_sessions.touch(body.agent_id, body.thread_id, body.title)
    return {"ok": True}


@router.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(agent_id: str, thread_id: str) -> dict:
    """删除会话（含该线程的 LLM 对话上下文）。删除当前会话自动切到最近会话。"""
    if agent_service.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not chat_sessions.delete(agent_id, thread_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


def _resolve_avatar_action(tool_name: str, args: str = "") -> dict | None:
    """根据工具名 + 参数解析AI 数字人播放 payload（方案B 动态工具）。

    - do_action：args.action → {"motion": action, "expressions": [], "label"}
    - set_expression：args.expression → {"motion": None, "expressions": [expression], "label"}
    返回 None 表示该工具不是AI 数字人动作工具（不广播给壳）。
    """
    import json as _json

    from app.domain.avatar.service import _action_label, _expression_label

    if tool_name not in ("do_action", "set_expression"):
        return None
    try:
        args_dict = _json.loads(args) if args else {}
    except (ValueError, TypeError):
        args_dict = {}
    if tool_name == "do_action":
        action = (args_dict.get("action") or "").strip()
        if not action:
            return None
        return {"motion": action, "expressions": [], "label": _action_label(action)}
    expression = (args_dict.get("expression") or "").strip()
    if not expression:
        return None
    return {"motion": None, "expressions": [expression], "label": _expression_label(expression)}


async def _publish_actions(events, tool_owners: dict[str, str]):
    """转发内部事件流，并把工具调用（动作/表情）广播给AI 数字人壳。

    ``tool_owners``（工具名→来源插件 id）**按请求传入**，不用模块级全局：
    它是每次对话装配 tools() 时算出来的，放全局会被并发对话互相覆盖 ——
    A 的 tool_call 帧会拿到 B 的插件映射（前端来源徽标错乱）。
    """
    async for ev in events:
        if ev.get("type") == "tool_call" and ev.get("name"):
            owner = tool_owners.get(ev["name"])
            if owner:
                ev["plugin_id"] = owner  # 前端展示来源徽标（多插件同名工具可辨识）
            payload = _resolve_avatar_action(ev["name"], ev.get("args") or "")
            if payload:
                avatar_events.publish(payload)
            # 任何工具调用都广播"干活中"（M8 工具执行可视化，不限于动作工具）
            avatar_events.publish_status("working")
        elif ev.get("type") == "tool_result":
            owner = tool_owners.get(ev.get("name") or "")
            if owner:
                ev["plugin_id"] = owner
            # 工具执行完成 → 恢复默认表情（连续工具会有 working→idle 抖动，可接受）
            avatar_events.publish_status("idle")
        yield ev


def _message_text(m) -> str:
    """BaseMessage.content 归一化为纯文本（可能是 str 或结构化块列表）。"""
    content = getattr(m, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts)
    return ""


def _segments_from_messages(msgs: list) -> list[dict]:
    """BaseMessage 列表 → 有序片段流（user/reasoning/tool_call/tool_result/text）。

    前端据此还原「思考→调工具→看结果→正文」的穿插顺序；checkpointer 与
    thread_messages 投影两种来源共用（两端产出同构 Segment）。
    """
    out: list[dict] = []
    for m in msgs:
        mtype = getattr(m, "type", "")
        if mtype == "human":
            text = _message_text(m)
            if text:
                out.append({"type": "user", "content": text})
        elif mtype == "ai":
            # 深度思考（reasoner 模型的 reasoning_content）
            reasoning = getattr(m, "reasoning_content", None) or (
                getattr(m, "additional_kwargs", {}) or {}
            ).get("reasoning_content")
            if reasoning:
                out.append({"type": "reasoning", "content": reasoning})
            text = _message_text(m)
            if text:
                out.append({"type": "text", "content": text})
            for tc in getattr(m, "tool_calls", None) or []:
                args = tc.get("args") or tc.get("args_dict") or {}
                out.append(
                    {
                        "type": "tool_call",
                        "name": tc.get("name", ""),
                        "args": json.dumps(args, ensure_ascii=False),
                    }
                )
        elif mtype == "tool":
            out.append(
                {
                    "type": "tool_result",
                    "name": getattr(m, "name", "") or "",
                    "content": _message_text(m),
                }
            )
    return out


def _wire_to_messages(wire_list: list[str]) -> list:
    """thread_messages 投影的 message_json（langchain wire）→ BaseMessage 列表。"""
    from langchain_core.messages import messages_from_dict

    out: list = []
    for wire in wire_list:
        try:
            out.extend(messages_from_dict([json.loads(wire)]))
        except Exception:
            continue
    return out


@router.get("/agents/{agent_id}/chat/history")
async def chat_history(
    agent_id: str,
    thread_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """按线程取对话历史，返回有序片段流（按真实时间顺序）。

    M4：thread_messages 投影已就绪（ready）时直接读表分页——历史读取不依赖
    harness 运行时实例；未就绪（pending，含迁移期老会话）时从 checkpointer
    读取并全量 backfill 投影，checkpointer 始终是消息权威。
    片段类型：user / reasoning（深度思考）/ tool_call / tool_result / text。

    **分页语义（两条路径必须一致）**：从**最新**往前取 ``limit`` 条，``offset`` 表示
    再往前跳过多少条（对齐 ``thread_message_repo.page`` 的「倒序分页」）。
    原 backfill 分支用 ``msgs[-limit:]`` 忽略了 offset，且投影为空时还会回落重算 →
    翻页会重复拿到同一批尾部消息。
    """
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    if thread_message_repo.projection_status(thread_id) == PROJ_READY:
        rows, _ = thread_message_repo.page(thread_id, limit=limit, offset=offset)
        # 投影是权威：即使为空（offset 越界）也直接返回，
        # 不要回落到 backfill —— 那会把尾部消息又当成"这一页"返回
        return _segments_from_messages(_wire_to_messages([r["message_json"] for r in rows]))

    # pending：checkpointer 权威 + 全量 backfill 投影（一次全量，之后每轮增量 append）
    agent = ensure_agent_runtime(agent_row)
    msgs = await agent.aget_history(thread_id, limit=100_000)
    thread_message_repo.replace_all(thread_id, messages_to_inputs(msgs))
    thread_message_repo.mark_projection(thread_id, PROJ_READY)
    end = max(0, len(msgs) - offset)
    start = max(0, end - limit)
    return _segments_from_messages(msgs[start:end])


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatBody, request: Request) -> StreamingResponse:
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent_row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    # per-turn 能力校验必须在流开始前完成（generator 内抛错不会转成 400）
    skills, connectors = await _resolve_chat_abilities(body.skills, body.connectors)
    model = body.model
    if model is not None:
        from app.infra.providers_store import model_refs

        if model not in model_refs():
            raise HTTPException(status_code=400, detail=f"模型不存在或未配置: {model}")
        model = model.strip()
    _validate_knowledge_base_ids(body.knowledge_base_ids)
    # 先以完整参数构造运行时实例（workspace/工具/技能/MCP 一次到位），
    # 避免 gen() 内首次构造时参数缺失把实例建到全局根（历史端点同款根因）。
    ensure_agent_runtime(agent_row)

    async def gen():
        # 工具装配与来源映射：请求局部（插件启停立即生效，且并发对话互不干扰）。
        # 一次 list_all() 同时算出两者 —— 原先各算一次要多查一遍 DB 与表情清单。
        tools, tool_owners = plugin_service.tools_and_owners()
        # AI 数字人插件启用时，自动拼入身体使用说明（不污染专家人设）
        from app.domain.avatar.service import load_avatar_instructions

        system_prompt = agent_row["system_prompt"] or ""
        avatar_instructions = load_avatar_instructions()
        if avatar_instructions:
            system_prompt = system_prompt.rstrip() + "\n\n" + avatar_instructions

        # 推状态：LLM 开始思考
        avatar_events.publish_status("thinking")

        async def _persist_turn(turn: dict) -> None:
            """本轮消息写入 thread_messages 投影（M4；失败不影响对话）。"""
            if thread_repo.get(body.thread_id) is None:
                # AI 数字人壳等直带任意 thread_id 对话时兜底登记会话
                thread_repo.insert(body.thread_id, agent_id, title="")
            # 仅已 backfill（ready）的投影增量 append；pending 由首次历史读取全量 backfill
            if thread_message_repo.projection_status(body.thread_id) != PROJ_READY:
                return
            inputs = turn_to_message_inputs(turn)
            if inputs:
                thread_message_repo.append(body.thread_id, inputs)

        frames = stream_octop_sse(
            _publish_actions(
                stream_chat(
                    body.messages,
                    body.thread_id,
                    agent_id=agent_id,
                    name=agent_row["name"],
                    system_prompt=system_prompt,
                    workspace_dir=ensure_agent_workspace(agent_id, agent_row["name"]),
                    plugin_tools=tools,
                    skills_dir=all_skills_dirs(),
                    skills_disabled=skill_service.disabled_set(),
                    mcp_server_configs=settings.mcp_servers,
                    mcp_default_servers=list(settings.mcp_servers.keys()) or None,
                    skills=skills,
                    connectors=connectors,
                    model=model,
                    knowledge_base_ids=body.knowledge_base_ids,
                    agent_config=agent_row.get("config_json"),
                    on_turn_complete=_persist_turn,
                ),
                tool_owners,
            ),
            thread_id=body.thread_id,
        )
        try:
            # aclosing：客户端断连 break 时关闭本层 SSE 生成器。注意机制——
            # aclose 只把 GeneratorExit 抛进**本层**；这层没有 try/finally，
            # 所以不会同步传播到上游。上游（LLM 流）是在引用释放后由 async
            # generator 终结器异步关闭的（实测让出若干次事件循环后生效）。
            # 效果成立，但别指望「break 完上游立刻关」。
            async with aclosing(frames) as stream:
                async for frame in stream:
                    if await request.is_disconnected():
                        break
                    yield frame
        except Exception as exc:  # 流中途失败：必须给客户端一个明确的终止帧
            # 没有 error 帧时，前端只看到被截断的流，既没有 done 也没有错误 → 永久转圈。
            logger.exception("对话流异常（thread=%s）", body.thread_id)
            yield format_sse(
                {
                    "type": "error",
                    "message": str(exc) or exc.__class__.__name__,
                    "thread_id": body.thread_id,
                }
            )
        finally:
            # 推状态：回复结束，恢复 idle
            avatar_events.publish_status("idle")

    # 结构性保证（P0-5）：校验全部在 gen 之前完成（见函数体上方），
    # StreamingResponse 统一走 stream_response 出口 —— gen 内不再允许抛 HTTPException。
    return await stream_response(
        gen,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


class ChatApprovalBody(BaseModel):
    """HITL 人工审批：approve 放行写工具 / reject 拒绝（可附理由）。"""

    thread_id: str
    decision: Literal["approve", "reject"]
    message: str | None = None


@router.post("/agents/{agent_id}/chat/approval")
async def chat_approval(
    agent_id: str, body: ChatApprovalBody, request: Request
) -> StreamingResponse:
    """HITL 人工审批：续跑被暂停的对话，返回与对话同构的 SSE 事件流。

    approve：harness 放行被 interrupt 挂起的工具调用（写入真实执行）；
    reject：harness 返回错误 ToolMessage（写操作不执行）。两者都会让
    LLM 在下一轮继续组织回复（token / tool_result / done 正常回流）。
    会话归属校验：thread 已存在时 agent_id 必须一致，避免跨 Agent 续跑。
    """
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent_row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    thread = thread_repo.get(body.thread_id)
    if thread is not None and str(thread.get("agent_id", "")) != str(agent_id):
        raise HTTPException(status_code=403, detail="会话不属于该 Agent")
    decisions: list[dict] = [{"type": body.decision}]
    if body.message:
        decisions[0]["message"] = body.message

    async def gen():
        tools, tool_owners = plugin_service.tools_and_owners()
        from app.domain.avatar.service import load_avatar_instructions

        system_prompt = agent_row["system_prompt"] or ""
        avatar_instructions = load_avatar_instructions()
        if avatar_instructions:
            system_prompt = system_prompt.rstrip() + "\n\n" + avatar_instructions

        avatar_events.publish_status("thinking")

        async def _persist_turn(turn: dict) -> None:
            """本轮消息写入 thread_messages 投影（M4；失败不影响对话）。"""
            if thread_repo.get(body.thread_id) is None:
                thread_repo.insert(body.thread_id, agent_id, title="")
            if thread_message_repo.projection_status(body.thread_id) != PROJ_READY:
                return
            inputs = turn_to_message_inputs(turn)
            if inputs:
                thread_message_repo.append(body.thread_id, inputs)

        frames = stream_octop_sse(
            _publish_actions(
                resume_chat(
                    body.thread_id,
                    decisions,
                    agent_id=agent_id,
                    name=agent_row["name"],
                    system_prompt=system_prompt,
                    workspace_dir=ensure_agent_workspace(agent_id, agent_row["name"]),
                    plugin_tools=tools,
                    skills_dir=all_skills_dirs(),
                    skills_disabled=skill_service.disabled_set(),
                    mcp_server_configs=settings.mcp_servers,
                    mcp_default_servers=list(settings.mcp_servers.keys()) or None,
                    on_turn_complete=_persist_turn,
                ),
                tool_owners,
            ),
            thread_id=body.thread_id,
        )
        try:
            async with aclosing(frames) as stream:
                async for frame in stream:
                    if await request.is_disconnected():
                        break
                    yield frame
        except Exception as exc:
            logger.exception("审批续流异常（thread=%s）", body.thread_id)
            yield format_sse(
                {
                    "type": "error",
                    "message": str(exc) or exc.__class__.__name__,
                    "thread_id": body.thread_id,
                }
            )
        finally:
            avatar_events.publish_status("idle")

    return await stream_response(
        gen,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
