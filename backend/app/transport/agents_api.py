"""Agent 路由：专家生命周期（CRUD + 启停 + 状态）。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
对话端点（/agents/{id}/chat、/chat/history）归 chat_api。
"""

from __future__ import annotations

import contextlib
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.domain.agents.service import (
    STATE_RUNNING,
    STATE_STOPPED,
    agent_service,
    enrich_agent,
    ensure_agent_workspace,
)
from app.infra.harness.manager import manager
from app.storage.paths import agent_workspace_dir
from app.transport.runtime import ensure_agent_runtime

router = APIRouter(prefix="/api", tags=["agents"])


def _enrich(row: dict) -> dict:
    """enrich + 实时运行时状态。

    last_state 是 DB 持久化旧值（start/stop 时写入，进程崩溃或后端重启后不复位，
    会显示陈旧「运行中」）；实时状态以 manager 内存缓存为准。
    domain 层不依赖 infra（P0-1 分层约束），故在 transport 层合并。
    """
    return {
        **enrich_agent(row),
        "runtime": "running" if manager.has(row["agent_id"]) else "stopped",
    }


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
    config_json: dict | None = (
        None  # M3：运行时参数（max_iters/temperature/top_p/max_tokens/max_input_length）
    )


class AgentImportBody(BaseModel):
    source_dir: str
    name: str | None = None


@router.get("/agents")
async def list_agents() -> list[dict]:
    return [_enrich(r) for r in agent_service.list_all()]


@router.post("/agents/import")
async def import_agent(body: AgentImportBody) -> dict:
    """从 Octop 专家目录导入（~/.octop/agents/<id>/ 或 Octop library/<id>/）。"""
    from app.domain.agents.importer import import_octop_expert

    try:
        row = import_octop_expert(body.source_dir, name=body.name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _enrich(row)


@router.post("/agents")
async def create_agent(body: AgentCreateBody) -> dict:
    data = body.model_dump()
    row = agent_service.create(data)
    ensure_agent_workspace(row["agent_id"], row["name"])
    return _enrich(row)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _enrich(row)


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
    ws = agent_workspace_dir(agent_id)
    if ws.is_dir():
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
    # 必须走统一入口：manager 按 agent_id 单例缓存，构造参数只在首次生效。
    # 这里曾自行调 manager.get_agent 且漏传 workspace_dir —— 用户在「专家」页点
    # 「启动实例」会把实例建到全局数据根（无 persona 文件、写全局 memory.sqlite），
    # 之后该专家的对话/历史全部错位（详见 ensure_agent_runtime 的 docstring）。
    ensure_agent_runtime(row)
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
