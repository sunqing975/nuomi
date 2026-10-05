"""API 路由：健康检查 + Agent 生命周期 + SSE 流式对话 + 会话管理。

对话协议（AI 数字人前端/控制台消费）：
    POST /api/agents/{agent_id}/chat   body={"messages": "...", "thread_id": "..."}
    → OpenAI Chat Completions 流式格式（delta.content / delta.tool_calls / [DONE]）

会话：以工作区 nuomi-state.json 为权威（thread_id / threads，2026-10-04 起，
无 default AI 数字人线程、无模型专属会话；AI 数字人=纯表现层，拦截工具调用播放动作）。
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.domain.agents.service import (
    STATE_RUNNING,
    STATE_STOPPED,
    agent_service,
    enrich_agent,
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
from app.infra import env_store, skillhub
from app.infra.avatar_events import avatar_events
from app.infra.harness.chat import stream_chat, stream_octop_sse
from app.infra.harness.manager import manager
from app.storage import db

router = APIRouter(prefix="/api", tags=["chat"])


def _slug_from_hub(name: str) -> str:
    """市场 slug → 本地目录名（小写 kebab，长度受限）。"""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s[:64] or "skill"


def _all_skills_dirs() -> list:
    """注入用技能根列表：工作区单技能 + 各已启用技能包内技能目录。"""
    return [skill_service.skills_dir(), *skill_package_service.skills_dirs()]


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


def ensure_agent_runtime(agent_row: dict):
    """统一构造/获取某专家的 HarnessAgent 运行时实例。

    所有端点（控制台对话 / 历史加载 / AI 数字人壳 OpenAI 兼容）必须经此入口，
    禁止各自调 manager.get_agent 传残缺参数。原因：manager 按 agent_id 单例缓存，
    构造参数（workspace_dir / 插件工具 / 技能目录 / MCP）只在首次构造时生效；
    若历史端点先到（页面加载自动拉历史）而漏传 workspace_dir，会把「全局根
    memory.sqlite + 无工具」的残缺实例缓存下来，导致专家工作区的对话历史读不到、
    后续对话全部错写到全局根库。
    """
    return manager.get_agent(
        agent_row["agent_id"],
        name=agent_row["name"],
        system_prompt=agent_row["system_prompt"] or "",
        workspace_dir=ensure_agent_workspace(agent_row["agent_id"], agent_row["name"]),
        plugin_tools=plugin_service.tools(),
        skills_dir=_all_skills_dirs(),
        skills_disabled=skill_service.disabled_set(),
        mcp_server_configs=settings.mcp_servers,
        mcp_default_servers=list(settings.mcp_servers.keys()) or None,
    )


def _resolve_chat_abilities(skills, connectors) -> tuple[list[str] | None, list[str] | None]:
    """校验并归一化 per-turn 能力选择（skills / connectors），返回 (skills, connectors)。

    skills：None=全量技能；[]=禁用全部；列表=只启用这些（须存在于可用技能集合）。
    connectors：None=默认连接器（agent 配置）；[]=不挂载；列表=只挂载这些（须已配置）。
    """
    if skills is not None:
        for name in skills:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail="技能名不能为空")
        unknown = [n for n in skills if n not in _available_skill_keys()]
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


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


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


async def _publish_actions(events):
    """转发内部事件流，并把工具调用（动作/表情）广播给AI 数字人壳。"""
    async for ev in events:
        if ev.get("type") == "tool_call" and ev.get("name"):
            payload = _resolve_avatar_action(ev["name"], ev.get("args") or "")
            if payload:
                avatar_events.publish(payload)
                avatar_events.publish_status("working")
        yield ev


@router.get("/avatar/events")
async def avatar_events_sse(request: Request) -> StreamingResponse:
    """AI 数字人动作事件流（SSE 长连接）：任意对话产生的工具调用实时广播。"""

    async def gen():
        async for ev in avatar_events.stream():
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    agent_id: str, thread_id: str, limit: int = 100, offset: int = 0
) -> list[dict]:
    """按线程取对话历史，返回有序片段流（按真实时间顺序）。

    M4：thread_messages 投影已就绪（ready）时直接读表分页——历史读取不依赖
    harness 运行时实例；未就绪（pending，含迁移期老会话）时从 checkpointer
    读取并全量 backfill 投影，checkpointer 始终是消息权威。
    片段类型：user / reasoning（深度思考）/ tool_call / tool_result / text。
    """
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if thread_message_repo.projection_status(thread_id) == PROJ_READY:
        rows, _ = thread_message_repo.page(thread_id, limit=limit, offset=offset)
        if rows:
            return _segments_from_messages(_wire_to_messages([r["message_json"] for r in rows]))
    # pending：checkpointer 权威 + 全量 backfill 投影（一次全量，之后每轮增量 append）
    agent = ensure_agent_runtime(agent_row)
    msgs = await agent.aget_history(thread_id, limit=100_000)
    thread_message_repo.replace_all(thread_id, messages_to_inputs(msgs))
    thread_message_repo.mark_projection(thread_id, PROJ_READY)
    return _segments_from_messages(msgs[-limit:] if limit else msgs)


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatBody, request: Request) -> StreamingResponse:
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent_row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    # per-turn 能力校验必须在流开始前完成（generator 内抛错不会转成 400）
    skills, connectors = _resolve_chat_abilities(body.skills, body.connectors)
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
        tools = plugin_service.tools()
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

        try:
            async for frame in stream_octop_sse(
                _publish_actions(
                    stream_chat(
                        body.messages,
                        body.thread_id,
                        agent_id=agent_id,
                        name=agent_row["name"],
                        system_prompt=system_prompt,
                        workspace_dir=ensure_agent_workspace(agent_id, agent_row["name"]),
                        plugin_tools=tools,
                        skills_dir=_all_skills_dirs(),
                        skills_disabled=skill_service.disabled_set(),
                        mcp_server_configs=settings.mcp_servers,
                        mcp_default_servers=list(settings.mcp_servers.keys()) or None,
                        skills=skills,
                        connectors=connectors,
                        model=model,
                        knowledge_base_ids=body.knowledge_base_ids,
                        agent_config=agent_row.get("config_json"),
                        on_turn_complete=_persist_turn,
                    )
                ),
                thread_id=body.thread_id,
            ):
                if await request.is_disconnected():
                    break
                yield frame
        finally:
            # 推状态：回复结束，恢复 idle
            avatar_events.publish_status("idle")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Agent 生命周期（对齐 Octop agents 语义） ----------


class AgentCreateBody(BaseModel):
    name: str
    description: str = ""
    persona_mbti: str = ""
    system_prompt: str = ""
    enabled: bool = True
    icon_name: str = ""
    icon_url: str = ""
    color: str = ""
    welcome_message: str = ""


class AgentPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None
    persona_mbti: str | None = None
    system_prompt: str | None = None
    enabled: bool | None = None
    icon_name: str | None = None
    icon_url: str | None = None
    color: str | None = None
    welcome_message: str | None = None
    config_json: dict | None = None  # M3：运行时参数（max_iters/temperature/top_p/max_tokens/max_input_length）


class AgentImportBody(BaseModel):
    source_dir: str
    name: str | None = None


@router.get("/agents")
async def list_agents() -> list[dict]:
    return [enrich_agent(r) for r in agent_service.list_all()]


@router.post("/agents/import")
async def import_agent(body: AgentImportBody) -> dict:
    """从 Octop 专家目录导入（~/.octop/agents/<id>/ 或 Octop library/<id>/）。"""
    from app.domain.agents.importer import import_octop_expert

    try:
        row = import_octop_expert(body.source_dir, name=body.name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return enrich_agent(row)


@router.post("/agents")
async def create_agent(body: AgentCreateBody) -> dict:
    data = body.model_dump()
    row = agent_service.create(data)
    ensure_agent_workspace(row["agent_id"], row["name"])
    return enrich_agent(row)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return enrich_agent(row)


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentPatchBody) -> dict:
    row = agent_service.update(agent_id, body.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    """删除 Agent：释放运行时 + 删 DB 行 + 清理专家工作区（对齐 Octop：rmtree 失败不阻断）。"""
    manager.release(agent_id)
    if not agent_service.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent 不存在")
    from app.domain.agents.service import agent_workspace_dir

    ws = agent_workspace_dir(agent_id)
    if ws.is_dir():
        import contextlib
        import shutil

        # 文件占用等清理失败：agent 已从 DB 删除，工作区残留不阻断
        with contextlib.suppress(OSError):
            shutil.rmtree(ws)
    return {"ok": True}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    manager.get_agent(
        agent_id,
        name=row["name"],
        system_prompt=row["system_prompt"],
        plugin_tools=plugin_service.tools(),
        skills_dir=_all_skills_dirs(),
        skills_disabled=skill_service.disabled_set(),
        mcp_server_configs=settings.mcp_servers,
        mcp_default_servers=list(settings.mcp_servers.keys()) or None,
    )
    agent_service.set_state(agent_id, STATE_RUNNING)
    return {"ok": True, "state": STATE_RUNNING}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    manager.release(agent_id)
    agent_service.set_state(agent_id, STATE_STOPPED)
    return {"ok": True, "state": STATE_STOPPED}


@router.get("/agents/{agent_id}/status")
async def agent_status(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    runtime = "running" if manager.has(agent_id) else "stopped"
    return {"agent_id": agent_id, "runtime": runtime, "last_state": row.get("last_state")}


# ---------- 插件（能力域：对齐 Octop 插件概念） ----------


class PluginPatchBody(BaseModel):
    enabled: bool | None = None


@router.get("/plugins")
async def list_plugins() -> list[dict]:
    return plugin_service.list_all()


@router.post("/plugins/sync")
async def sync_plugins() -> list[dict]:
    """重新扫描工作区 plugins/ 并加载（新插件默认启用）。"""
    return plugin_service.sync()


@router.post("/plugins/import")
async def import_plugin_zip(file: UploadFile = File(...)) -> dict:
    """从 zip 导入插件到工作区 plugins/<id>/（格式：plugin.yaml + entry 文件）。

    导入成功默认启用；释放全部 agent 实例，下次对话即可用新插件工具。
    """
    from app.domain.importer import import_plugin_zip as _import

    try:
        plugin = _import(await file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()  # 释放全部实例：下次对话重建，挂载新插件工具
    return {"ok": True, "plugin": plugin}


class GitImportBody(BaseModel):
    """git 仓库导入请求体。"""

    url: str = Field(..., min_length=4, description="仓库地址（https/ssh/git@）")


@router.post("/plugins/import-git")
async def import_plugin_git(body: GitImportBody) -> dict:
    """从 git 仓库导入插件到工作区 plugins/<id>/（浅克隆，50MB 上限）。"""
    from app.domain.importer import import_plugin_git as _import

    try:
        plugin = _import(body.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()
    return {"ok": True, "plugin": plugin}


@router.patch("/plugins/{plugin_id}")
async def patch_plugin(plugin_id: str, body: PluginPatchBody) -> dict:
    row = (
        plugin_service.set_enabled(plugin_id, body.enabled)
        if body.enabled is not None
        else plugin_service.get(plugin_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    if body.enabled is not None:
        # 工具集随插件启停变化：释放全部实例，下次对话重建（参考技能启停做法）
        manager.close()
    return row


@router.delete("/plugins/{plugin_id}")
async def delete_plugin(plugin_id: str) -> dict:
    """删除插件（含插件目录）。"""
    if not plugin_service.delete(plugin_id):
        raise HTTPException(status_code=404, detail="插件不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再携带被删插件工具
    return {"ok": True}


# ---------- 技能（能力域：对齐 Octop 技能概念） ----------


class SkillPatchBody(BaseModel):
    enabled: bool | None = None


@router.get("/skills")
async def list_skills() -> list[dict]:
    return skill_service.list_all()


@router.get("/skills/builtin")
async def list_builtin_skills() -> list[dict]:
    """harness 包内置技能（只读展示，不可编辑/删除）。"""
    return skill_service.builtin()


@router.post("/skills/import")
async def import_skill_zip(file: UploadFile = File(...)) -> dict:
    """从 zip 导入技能到工作区 skills/<name>/（格式：SKILL.md，实时扫描自动可见）。

    释放全部 agent 实例，下次对话注入新技能。
    """
    from app.domain.importer import import_skill_zip as _import

    try:
        skill = _import(await file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()  # 释放全部实例：下次对话重建，注入新技能
    return {"ok": True, "skill": skill}


@router.post("/skills/import-git")
async def import_skill_git(body: GitImportBody) -> dict:
    """从 git 仓库导入技能到工作区 skills/<name>/（浅克隆，50MB 上限）。"""
    from app.domain.importer import import_skill_git as _import

    try:
        skill = _import(body.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()
    return {"ok": True, "skill": skill}


@router.patch("/skills/{skill_name}")
async def patch_skill(skill_name: str, body: SkillPatchBody) -> dict:
    if body.enabled is not None:
        row = skill_service.set_enabled(skill_name, body.enabled)
    else:
        row = next((s for s in skill_service.list_all() if s["name"] == skill_name), None)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return row


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str) -> dict:
    """删除技能（含技能目录）。"""
    if not skill_service.delete(skill_name):
        raise HTTPException(status_code=404, detail="技能不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再注入被删技能
    return {"ok": True}


# ---------- SkillHub 技能市场 ----------


class SkillHubInstallBody(BaseModel):
    slug: str
    name: str | None = None


class SkillPackageBody(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None


class SkillPackagePatchBody(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None


class EnvSaveBody(BaseModel):
    """环境变量整体保存请求体（应用设置，对齐 octop）。"""

    values: dict[str, str] = Field(default_factory=dict)


@router.get("/settings/env")
async def get_app_env() -> dict[str, str]:
    """应用环境变量（技能/连接器 API key 等；存 {workspace}/env.json）。"""
    return env_store.load()


@router.put("/settings/env")
async def put_app_env(body: EnvSaveBody) -> dict[str, str]:
    """整体保存环境变量：即时注入进程 env，并释放 agent 实例（下次对话生效）。"""
    saved = env_store.save(body.values)
    manager.close()
    return saved


class ProviderBody(BaseModel):
    """大模型 Provider 保存请求体（对齐 octop providers 管理）。

    api_key 为空串 = 保持原值（编辑不显式改就不动）。
    """

    providers: list[dict] = Field(description="provider 列表（整体保存）")


def _validate_providers(providers: list[dict], existing: list[dict]) -> list[dict]:
    if not providers:
        raise HTTPException(status_code=400, detail="至少保留一个 Provider")
    ids: set[str] = set()
    out: list[dict] = []
    for i, p in enumerate(providers):
        pid = str(p.get("id") or "").strip()
        base_url = str(p.get("base_url") or "").strip()
        if not pid:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 个 Provider 缺少 id")
        if pid in ids:
            raise HTTPException(status_code=400, detail=f"Provider id 重复: {pid}")
        ids.add(pid)
        if not base_url:
            raise HTTPException(status_code=400, detail=f"Provider「{pid}」缺少 base_url")
        models = [
            {
                "id": str(m.get("id") or "").strip(),
                "name": str(m.get("name") or "").strip() or str(m.get("id") or "").strip(),
            }
            for m in (p.get("models") or [])
            if str(m.get("id") or "").strip()
        ]
        if not models:
            raise HTTPException(status_code=400, detail=f"Provider「{pid}」至少需要一个模型")
        # api_key 空串或脱敏串（含 ***）= 保持原值（按 id 匹配旧配置）
        # 防呆：GET 返回的脱敏串（sk-2***fa1e）若被前端回写，绝不能当真实 key 存
        api_key = str(p.get("api_key") or "").strip()
        if not api_key or "***" in api_key:
            old = next((x for x in existing if x.get("id") == pid), None)
            api_key = (old or {}).get("api_key") or ""
        if not api_key:
            raise HTTPException(
                status_code=400, detail=f"Provider「{pid}」缺少 API Key（harness 要求非空）"
            )
        out.append(
            {
                "id": pid,
                "name": str(p.get("name") or "").strip() or pid,
                "base_url": base_url,
                "api_key": api_key,
                "protocol": str(p.get("protocol") or "openai").strip() or "openai",
                "models": models,
            }
        )
    return out


class ProviderProbeBody(BaseModel):
    """Provider 模型探测请求体（不落盘，仅探测一次）。"""

    base_url: str = Field(description="OpenAI 兼容服务的 base_url")
    api_key: str = Field(default="", description="探测用 API Key（不落盘）")


@router.post("/settings/providers/probe")
async def probe_provider_models(body: ProviderProbeBody) -> dict:
    """探测服务的 /models 接口，返回可用模型 id 列表（新增 Provider 时拉取勾选用）。"""
    from app.infra.providers_store import probe_models

    try:
        models = probe_models(body.base_url, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}


@router.get("/settings/providers")
async def get_providers() -> dict:
    """大模型 Provider 列表（api_key 脱敏；未配置过时返回 .env 种子）。"""
    from app.infra.providers_store import load, mask_key

    provs = []
    for p in load():
        provs.append({**p, "api_key": mask_key(p.get("api_key") or "")})
    return {"providers": provs}


@router.put("/settings/providers")
async def put_providers(body: ProviderBody) -> dict:
    """整体保存大模型 Provider：写 providers.json + 释放实例（下次对话生效）。

    模型不绑专家（2026-10-04）：不校验/重置任何专家字段，对话时 per-turn 选模型。
    """
    from app.infra.providers_store import load as load_providers
    from app.infra.providers_store import save

    existing = load_providers()
    providers = _validate_providers(body.providers, existing)
    save(providers)
    manager.close()
    return {"ok": True, "providers": len(providers)}


class LangfuseBody(BaseModel):
    """Langfuse 观测配置保存请求体（secret_key 为空串/脱敏串 = 保持原值）。"""

    enabled: bool = Field(description="启用 Langfuse 轨迹")
    host: str = Field(default="", description="Langfuse 服务地址（云或自托管）")
    public_key: str = Field(default="", description="Langfuse Public Key")
    secret_key: str = Field(default="", description="Langfuse Secret Key（留空保持原值）")


class LangfuseTestBody(BaseModel):
    """Langfuse 连接测试请求体（不落盘；secret 为脱敏串时复用已存值）。"""

    host: str = Field(default="")
    public_key: str = Field(default="")
    secret_key: str = Field(default="")


@router.get("/settings/langfuse")
async def get_langfuse() -> dict:
    """Langfuse 观测配置（secret_key 脱敏展示）。"""
    from app.infra.harness.langfuse_store import load, mask_secret

    cfg = load()
    return {
        "enabled": cfg["enabled"],
        "host": cfg["host"],
        "public_key": cfg["public_key"],
        "secret_key": mask_secret(cfg["secret_key"]),
    }


@router.put("/settings/langfuse")
async def put_langfuse(body: LangfuseBody) -> dict:
    """保存 Langfuse 配置：写 langfuse.json + 热更新 harness tracer（即时生效）。

    启用时要求凭据齐全；停用则仅存开关，保留凭据供下次启用复用。
    """
    from app.infra.harness.langfuse_store import load as load_langfuse_cfg
    from app.infra.harness.langfuse_store import save as save_langfuse_cfg
    from octop_harness.observability.langfuse import LangfuseConfig

    existing = load_langfuse_cfg()
    host = (body.host or "").strip().rstrip("/")
    if not host:
        raise HTTPException(status_code=400, detail="Langfuse Host 必填")
    public_key = (body.public_key or "").strip()
    if not public_key:
        raise HTTPException(status_code=400, detail="Langfuse Public Key 必填")
    secret = (body.secret_key or "").strip()
    if not secret or "***" in secret:
        secret = existing.get("secret_key") or ""
    if body.enabled and not secret:
        raise HTTPException(
            status_code=400,
            detail="启用 Langfuse 需要 Secret Key（当前未配置且本次未填写）",
        )
    cfg = save_langfuse_cfg(
        {"enabled": bool(body.enabled), "host": host, "public_key": public_key, "secret_key": secret}
    )
    manager.set_langfuse(LangfuseConfig(**cfg))
    return {"ok": True, "enabled": bool(body.enabled)}


@router.post("/settings/langfuse/test")
async def test_langfuse(body: LangfuseTestBody) -> dict:
    """用给定配置校验 Langfuse 凭据（auth_check；不落盘）。"""
    from app.infra.harness.langfuse_store import load as load_langfuse_cfg
    from langfuse import Langfuse

    host = (body.host or "").strip().rstrip("/")
    public_key = (body.public_key or "").strip()
    secret = (body.secret_key or "").strip()
    if "***" in secret:
        secret = (load_langfuse_cfg().get("secret_key") or "").strip()
    if not host or not public_key or not secret:
        raise HTTPException(status_code=400, detail="Host / Public Key / Secret Key 均为必填")
    try:
        client = Langfuse(host=host, public_key=public_key, secret_key=secret)
        ok = bool(client.auth_check())
        client.flush()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"连接失败：{exc}") from exc
    if not ok:
        raise HTTPException(
            status_code=401, detail="Langfuse 凭据校验未通过（Public/Secret Key 或 Host 有误）"
        )
    return {"ok": True, "host": host}


@router.get("/skillhub/search")
async def skillhub_search(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return skillhub.search(q, page=page, page_size=page_size)


@router.get("/skillhub/rankings")
async def skillhub_rankings(
    ranking_type: str = "hot", page: int = 1, page_size: int = 20
) -> list[dict]:
    return skillhub.rankings(ranking_type, page=page, page_size=page_size)


@router.get("/skillhub/skillsets/{slug}")
async def skillhub_skillset(slug: str) -> dict:
    return skillhub.skillset_detail(slug)


@router.get("/skillhub/skillsets")
async def skillhub_skillset_list(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return skillhub.skillset_list(q, page=page, page_size=page_size)


@router.post("/skills/install")
async def install_skill_from_hub(body: SkillHubInstallBody) -> dict:
    """从 SkillHub 安装单个技能到 {workspace}/skills/<slug>/。"""
    slug = body.slug.strip().strip("/")
    if not slug:
        raise HTTPException(status_code=400, detail="slug 不能为空")
    safe = _slug_from_hub(slug)
    if not re.match(r"^[a-zA-Z0-9_-]+$", safe):
        raise HTTPException(status_code=400, detail=f"非法技能名: {slug}")
    target = skill_service.skills_dir() / safe
    if target.exists():
        raise HTTPException(status_code=409, detail=f"技能已存在: {safe}")
    try:
        files = skillhub.download(slug)
    except skillhub.SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    target.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files:
        p = target / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    skill_service.set_enabled(safe, True)
    manager.close()  # 下次对话重建，注入新技能
    return next((s for s in skill_service.list_all() if s["name"] == safe), {})


@router.get("/skill-packages")
async def list_skill_packages() -> list[dict]:
    return skill_package_service.list_all()


@router.post("/skill-packages")
async def create_skill_package(body: SkillPackageBody) -> dict:
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="包名不能为空")
    try:
        return skill_package_service.create(body.name, body.description or "", body.icon_url or "")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/skill-packages/from-skillhub")
async def create_skill_package_from_hub(body: SkillHubInstallBody) -> dict:
    """从 SkillHub 技能集（skillset）安装技能包：包级整体启停。"""
    slug = body.slug.strip().strip("/")
    if not slug:
        raise HTTPException(status_code=400, detail="slug 不能为空")
    try:
        return skill_package_service.install_from_skillhub(slug, name=body.name)
    except skillhub.SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/skill-packages/{package_id}")
async def patch_skill_package(package_id: str, body: SkillPackagePatchBody) -> dict:
    row = skill_package_service.get(package_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能包不存在")
    if body.enabled is not None:
        skill_package_service.set_enabled(package_id, body.enabled)
    if body.name:
        # 改名仅当不与其他包冲突
        others = [p for p in skill_package_service.list_all() if p["id"] != package_id]
        if any(p["name"] == body.name.strip() for p in others):
            raise HTTPException(status_code=409, detail=f"技能包已存在: {body.name}")
        import shutil

        new_id = _slug_from_hub(body.name)
        with db.connect() as conn:
            conn.execute(
                "UPDATE skill_packages SET name = ?, id = ? WHERE id = ?",
                (body.name.strip(), new_id, package_id),
            )
            conn.execute(
                "UPDATE skill_package_skills SET package_id = ? WHERE package_id = ?",
                (new_id, package_id),
            )
        old_dir = skill_package_service.package_dir(package_id)
        if old_dir.is_dir():
            shutil.move(str(old_dir), str(skill_package_service.package_dir(new_id)))
        package_id = new_id
    row = skill_package_service.get(package_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能包不存在")
    return row


@router.delete("/skill-packages/{package_id}")
async def delete_skill_package(package_id: str) -> dict:
    """删除技能包（DB + 包目录）。"""
    if not skill_package_service.delete(package_id):
        raise HTTPException(status_code=404, detail="技能包不存在")
    manager.close()
    return {"ok": True}


# ---------- MCP 服务器（连接器：控制台增删改，写 data_root/connectors.json，manager.close 重载） ----------

_CONNECTOR_TRANSPORTS = ("stdio", "sse", "http")


class ConnectorBody(BaseModel):
    name: str | None = None  # POST 创建时必填；PUT 以路径名为准
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # 子进程环境变量（harness 注入 MCP stdio）


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_connector_spec(body: ConnectorBody) -> dict:
    transport = (body.transport or "stdio").strip().lower()
    if transport not in _CONNECTOR_TRANSPORTS:
        raise HTTPException(
            status_code=400, detail=f"transport 仅支持 {', '.join(_CONNECTOR_TRANSPORTS)}"
        )
    if transport == "stdio" and not (body.command or "").strip():
        raise HTTPException(status_code=400, detail="stdio 传输需要 command")
    env = {k.strip(): v for k, v in (body.env or {}).items() if k and k.strip()}
    invalid = [k for k in env if not _ENV_KEY_RE.match(k)]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"环境变量名不合法（须字母/数字/下划线且以字母或 _ 开头）: {', '.join(sorted(invalid))}",
        )
    return {
        "transport": transport,
        "command": (body.command or "").strip(),
        "args": list(body.args or []),
        "env": env,
    }


def _persist_connectors() -> None:
    """写 data_root/connectors.json（重启后由 main._sync_mcp_file 读回，json 为权威）。"""
    p = settings.data_root / "connectors.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.mcp_servers, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/connectors")
async def list_connectors() -> list[dict]:
    """连接器列表（配置来自 settings.mcp_servers，connectors.json 权威）。"""
    return [
        {
            "name": name,
            "transport": spec.get("transport", "stdio"),
            "command": spec.get("command", ""),
            "args": spec.get("args", []),
            "env": spec.get("env") or {},
        }
        for name, spec in settings.mcp_servers.items()
    ]


@router.post("/connectors")
async def create_connector(body: ConnectorBody) -> dict:
    """新增连接器：写配置 + 释放实例，下次对话挂载其工具。"""
    name = (body.name or "").strip()
    if not name or not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise HTTPException(status_code=400, detail="连接器名仅限字母/数字/_/-")
    if name in settings.mcp_servers:
        raise HTTPException(status_code=400, detail=f"连接器已存在: {name}")
    spec = _validate_connector_spec(body)
    settings.mcp_servers[name] = spec
    _persist_connectors()
    manager.close()  # 重载：下次对话重建实例，挂载新 MCP 工具
    return {"ok": True, "name": name, **spec}


@router.put("/connectors/{name}")
async def update_connector(name: str, body: ConnectorBody) -> dict:
    """编辑连接器：更新配置 + 释放实例（下次对话生效）。"""
    if name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail="连接器不存在")
    spec = _validate_connector_spec(body)
    settings.mcp_servers[name] = spec
    _persist_connectors()
    manager.close()
    return {"ok": True, "name": name, **spec}


@router.delete("/connectors/{name}")
async def delete_connector(name: str) -> dict:
    """删除连接器：从运行配置移除并持久化（data_root/connectors.json），
    释放全部 agent 实例，下次对话重建后不再挂载该连接器工具。
    """
    if name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail="连接器不存在")
    settings.mcp_servers.pop(name)
    _persist_connectors()
    manager.close()
    return {"ok": True}


# ---------- 存储 / 工作区总览 ----------


@router.get("/workspace")
async def workspace_overview() -> dict:
    """工作区与能力总览（控制台「存储」板块）。"""
    from app.domain.skills.service import skill_service

    return {
        "workspace": str(settings.workspace_path),
        "data_root": str(settings.data_root),
        "counts": {
            "experts": len(agent_service.list_all()),
            "plugins": len(plugin_service.list_all()),
            "skills": len(skill_service.list_all()),
            "connectors": len(settings.mcp_servers),
        },
    }


# ---------- AI 数字人模型（表现层资产） ----------


class AvatarModelSwitchBody(BaseModel):
    model_id: str = Field(description="模型 id（工作区 models/2D/ 下的目录名）")


@router.get("/avatar/models")
async def list_avatar_models() -> dict:
    """模型资产列表：每个模型的动作/表情清单 + 当前激活模型。"""
    from app.domain.avatar.service import get_active_model, list_models

    return {"models": list_models(), "active": get_active_model()}


@router.get("/avatar/status")
async def get_avatar_status() -> dict:
    """AI 数字人开关状态（壳 config.json ui.avatar_enabled）。"""
    from app.domain.avatar.service import get_avatar_enabled

    return {"enabled": get_avatar_enabled()}


class AvatarStatusBody(BaseModel):
    enabled: bool = Field(
        description="AI 数字人开关：true=开（创建AI 数字人窗口），false=关（销毁窗口）"
    )


class AvatarPreviewBody(BaseModel):
    kind: str = Field(description="预览类型：action=动作，expression=表情")
    name: str = Field(description="动作名 / 表情名（当前激活模型的清单内）")


@router.put("/avatar/status")
async def set_avatar_status(body: AvatarStatusBody) -> dict:
    """设置AI 数字人开关：写壳 config.json ui.avatar_enabled + 共享 VRM 插件联动。

    方案B（2026-10-04）：只有一个共享AI 数字人插件 vrm-avatar——
    关闭 → 停用（动作/表情工具不再进 LLM 工具集）；开启 → 启用。
    工具随插件启停装配；释放 shell agent 实例，下次对话重建。
    """
    from app.domain.avatar.service import (
        VRM_AVATAR_PLUGIN_ID,
        get_shell_agent_id,
        set_avatar_enabled,
    )

    enabled = set_avatar_enabled(body.enabled)
    plugin_service.set_enabled(VRM_AVATAR_PLUGIN_ID, enabled)
    agent_id = get_shell_agent_id()
    if agent_id:
        # 工具集随插件启停变化：释放 agent 实例，下次对话重建
        manager.release(agent_id)
    return {
        "enabled": enabled,
        "agent_id": agent_id,
        "activated_plugin": VRM_AVATAR_PLUGIN_ID if enabled else None,
    }


@router.post("/avatar/models/switch")
async def switch_avatar_model(body: AvatarModelSwitchBody) -> dict:
    """切换AI 数字人模型：更新壳 config.json（方案B：不碰插件启停）。

    工具动态化：do_action/set_expression 的 enum 按当前激活模型 GLB 与
    animations/*.vrma 实时装配（PluginService.tools()），切模型后释放
    shell agent 实例，下次对话重建即携带新模型的动态工具。
    """
    from app.domain.avatar.service import (
        get_shell_agent_id,
        switch_model,
    )

    try:
        model = switch_model(body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    agent_id = get_shell_agent_id()
    if agent_id:
        # 表情 enum 随激活模型变化：释放实例，下次对话重建（零重启）
        manager.release(agent_id)

    return {
        "ok": True,
        "model": model,
        "agent_id": agent_id,
        "enrich": "skipped",
    }


@router.delete("/avatar/models/{model_id}")
async def delete_avatar_model(model_id: str) -> dict:
    """删除AI 数字人模型：删资产目录；删除激活模型自动切到剩余模型（方案B：无插件级联）。

    内置模型（种子分发）页面不提供删除入口。
    """
    from app.domain.avatar.service import delete_model

    try:
        result = delete_model(model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    agent_id = None
    if result["was_active"]:
        from app.domain.avatar.service import get_shell_agent_id

        agent_id = get_shell_agent_id()
        if agent_id:
            manager.release(agent_id)  # 激活模型已变，释放实例下次对话重建
    return {"ok": True, **result, "agent_id": agent_id}


# ==================== AI 数字人导入与预览（2026-10-04 新增） ====================


@router.post("/avatar/models/import")
async def import_avatar_model(file: UploadFile = File(...)) -> dict:
    """导入 VRM 模型：写入工作区 models/3D/，自动出现在模型清单（切模型零重启）。"""
    from app.domain.avatar.service import import_vrm

    data = await file.read()
    try:
        return import_vrm(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/avatar/animations/import")
async def import_avatar_animation(file: UploadFile = File(...)) -> dict:
    """导入 Mixamo FBX 动作：转 .vrma 进壳 assets/animations/（壳 watch 自动注册，动作工具零重启生效）。"""
    from app.domain.avatar.service import import_animation_fbx

    data = await file.read()
    try:
        result = import_animation_fbx(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (FileNotFoundError, TimeoutError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    # 广播：壳收到后刷新页面（保证新动作可播、播放器状态干净）
    avatar_events.publish_raw(
        {"type": "avatar_animations_changed", "reason": "import", "action": result["action"]}
    )
    return result


@router.delete("/avatar/animations/{name}")
async def delete_avatar_animation(name: str) -> dict:
    """删除动作资产（VRMA 资源管理）：移除 assets/animations/{name}.vrma，壳 watch 注销 + SSE 刷新页面。"""
    from app.domain.avatar.service import delete_avatar_animation

    try:
        result = delete_avatar_animation(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    avatar_events.publish_raw(
        {"type": "avatar_animations_changed", "reason": "delete", "action": name}
    )
    return result


@router.get("/avatar/animations")
async def list_avatar_animations() -> dict:
    """全局动作资产清单（所有 VRM 模型共用同一套 VRMA，资源管理独立入口）。"""
    from app.domain.avatar.service import list_avatar_actions

    return {"actions": list_avatar_actions()}


@router.post("/avatar/preview")
async def avatar_preview(body: AvatarPreviewBody) -> dict:
    """预览动作/表情：构造 payload 经 SSE 广播，数字人窗口立即播放（无需对话）。"""
    from app.domain.avatar.service import preview_payload

    try:
        payload = preview_payload(body.kind, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    avatar_events.publish(payload)
    return {"ok": True, "payload": payload}
