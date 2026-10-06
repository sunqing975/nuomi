"""记忆路由：查看/修正"我记住了什么"。

拆成独立 router（而不是继续堆进 transport/api.py —— 那已经 1600 行了）。
写操作同样受 `/api/*` 的 token 守卫保护（见 infra/local_guard.py）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.domain.agents.service import agent_service
from app.infra.memory_store import (
    MAX_FILE_BYTES,
    forget_atom,
    list_memory_files,
    memory_overview,
    read_memory_file,
    write_memory_file,
)

router = APIRouter(prefix="/api", tags=["memory"])


def _require_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.get("/agents/{agent_id}/memory")
async def get_memory(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_deprecated: bool = Query(default=False),
) -> dict:
    """记忆总览：统计 + 实体 + 断言列表（含来源对话与原话）+ 人设文件清单。

    ``include_deprecated=true`` 可以看到"已遗忘"的条目（UI 用来给撤销/审计留痕）。
    """
    row = _require_agent(agent_id)
    overview = memory_overview(
        agent_id, limit=limit, offset=offset, include_deprecated=include_deprecated
    )
    return {
        "agent_id": agent_id,
        "agent_name": row.get("name") or "",
        **overview,
        "files": list_memory_files(agent_id),
        "max_file_bytes": MAX_FILE_BYTES,
    }


@router.get("/agents/{agent_id}/memory/files/{name}")
async def get_memory_file(agent_id: str, name: str) -> dict:
    """读一个记忆/人设文件（工作区根目录的 .md）。"""
    _require_agent(agent_id)
    content = read_memory_file(agent_id, name)
    if content is None:
        raise HTTPException(status_code=404, detail="文件不存在或不可读")
    return {"agent_id": agent_id, "name": name, "content": content}


class MemoryFileBody(BaseModel):
    content: str = Field(default="", description="文件全文（整体覆盖）")


@router.put("/agents/{agent_id}/memory/files/{name}")
async def put_memory_file(agent_id: str, name: str, body: MemoryFileBody) -> dict:
    """修正一个记忆/人设文件。

    改完**下一轮对话即生效**：这些文件由 harness 每轮从工作区注入，无需重启实例。
    """
    _require_agent(agent_id)
    try:
        write_memory_file(agent_id, name, body.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "name": name, "bytes": len(body.content.encode("utf-8"))}


@router.delete("/agents/{agent_id}/memory/atoms/{atom_id}")
async def forget_memory_atom(agent_id: str, atom_id: str, reason: str = "") -> dict:
    """忘记一条记忆（软遗忘，可审计）。

    走 octop 记忆引擎的 ``deprecate_atom``：写 deprecated_at + 实体计数减一 +
    实体页标脏 + 追加 journal，所以下一轮不会再被想起来。
    """
    _require_agent(agent_id)
    if not forget_atom(agent_id, atom_id, reason=reason):
        raise HTTPException(status_code=404, detail="记忆条目不存在或已被遗忘")
    return {"ok": True, "atom_id": atom_id}
