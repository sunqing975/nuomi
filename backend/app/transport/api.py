"""API 路由：健康检查 + Agent 生命周期 + SSE 流式对话。

对话协议（桌宠前端消费）：
    POST /api/agents/{agent_id}/chat   body={"messages": "...", "thread_id": "..."}
    → SSE 事件流：token / emotion / tool_call / tool_result / usage / done
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.domain.agents.service import (
    STATE_RUNNING,
    STATE_STOPPED,
    agent_service,
)
from app.infra.harness.chat import PET_MOOD_RULE, format_sse, stream_chat
from app.infra.harness.manager import manager

router = APIRouter(prefix="/api", tags=["chat"])


# ---------- 对话 ----------


class ChatBody(BaseModel):
    messages: str = Field(description="用户输入文本")
    thread_id: str = Field(default="default", description="会话线程 ID（按线程隔离记忆）")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatBody, request: Request) -> StreamingResponse:
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent_row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")

    async def gen():
        async for event in stream_chat(
            body.messages,
            body.thread_id,
            agent_id=agent_id,
            name=agent_row["name"],
            system_prompt=(agent_row["system_prompt"] or "") + PET_MOOD_RULE,
        ):
            if await request.is_disconnected():
                break
            yield format_sse(event)

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
    default_model: str = "llm/deepseek-chat"
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
    default_model: str | None = None
    system_prompt: str | None = None
    enabled: bool | None = None
    icon_name: str | None = None
    icon_url: str | None = None
    color: str | None = None
    welcome_message: str | None = None


@router.get("/agents")
async def list_agents() -> list[dict]:
    return agent_service.list()


@router.post("/agents")
async def create_agent(body: AgentCreateBody) -> dict:
    return agent_service.create(body.model_dump())


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentPatchBody) -> dict:
    row = agent_service.update(agent_id, body.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    manager.release(agent_id)
    if not agent_service.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return {"ok": True}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    manager.get_agent(agent_id, name=row["name"], system_prompt=row["system_prompt"])
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
