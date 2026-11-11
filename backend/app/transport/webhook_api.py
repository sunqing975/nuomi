"""Webhook 端点：外部系统直接发起对话（纯本地部署，无鉴权）。

POST /api/webhook/{agent_id}，body ``{"message": "..."}``：
建线程 → 后台跑完整轮（stream_chat）→ 立即返回 ``{"thread_id"}``。
结果在控制台该专家的会话列表可见；命中工具审批时落台账，控制台批后续跑。

配方复用 OpenAI 兼容端点（openai_compat.py）：审批落台账 + 逐轮投影落库。
注意两处与 chat_api「控制台对话」的差异：
- 建线程直接写 thread_repo，不走 chat_sessions.new —— 不抢占控制台当前会话；
- 无 SSE 帧，纯消费事件流到结束。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import aclosing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.domain.agents.seed import default_system_prompt
from app.domain.agents.service import agent_service
from app.domain.chat.service import derive_thread_title, thread_repo, write_turn_projection
from app.infra.harness.chat import stream_chat
from app.transport.openai_compat import _record_approvals
from app.transport.runtime import ensure_agent_runtime

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

logger = logging.getLogger(__name__)

# 后台任务句柄：只防 GC（跑完自动消失），不做取消/查询
_background: set[asyncio.Task] = set()


class WebhookBody(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message 不能为空")
        return v


async def _run_turn(agent: dict, thread_id: str, user_text: str) -> None:
    """后台消费完整轮事件流：审批帧落台账，逐轮写消息投影（失败不影响对话）。"""
    agent_id = agent["agent_id"]

    async def _persist_turn(turn: dict) -> None:
        await write_turn_projection(
            agent_id=agent_id,
            thread_id=thread_id,
            turn=turn,
            load_history=lambda: ensure_agent_runtime(agent).aget_history(thread_id, limit=100_000),
        )

    events = _record_approvals(
        stream_chat(
            user_text,
            thread_id,
            agent_id=agent_id,
            name=agent["name"],
            system_prompt=agent["system_prompt"] or default_system_prompt(),
            agent_config=agent.get("config_json"),
            on_turn_complete=_persist_turn,
        ),
        agent_id=agent_id,
        source="webhook",
    )
    try:
        async with aclosing(events) as stream:
            async for _ in stream:
                pass
    except Exception:
        # 轮次失败：半截消息照常落库（stream_chat 内部处理），这里只留日志
        logger.exception("webhook 对话异常（thread=%s）", thread_id)


@router.post("/{agent_id}")
async def webhook_chat(agent_id: str, body: WebhookBody) -> dict:
    agent = agent_service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    # 可能抛 HTTPException 的运行时构造必须在进后台任务前做完（P0-5 同款根因）
    ensure_agent_runtime(agent)

    thread_id = f"{agent_id}:{uuid.uuid4().hex[:12]}"
    thread_repo.insert(thread_id, agent_id, title=f"Webhook · {derive_thread_title(body.message)}")

    task = asyncio.create_task(_run_turn(agent, thread_id, body.message))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"thread_id": thread_id, "status": "accepted"}
