"""连接器路由：MCP 服务器（控制台增删改，写 data_root/connectors.json，manager.close 重载）。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.infra.harness.manager import manager

router = APIRouter(prefix="/api", tags=["connectors"])

_CONNECTOR_TRANSPORTS = ("stdio", "sse", "http")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConnectorBody(BaseModel):
    name: str | None = None  # POST 创建时必填；PUT 以路径名为准
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)  # 子进程环境变量（harness 注入 MCP stdio）


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
    """写 data_root/connectors.json（重启后由 main._sync_connectors_file 读回，json 权威）。

    原子写 + 0600：连接器 spec 的 ``env`` 里常放 MCP 子进程的密钥。
    """
    from app.infra.secret_file import write_json

    write_json(settings.data_root / "connectors.json", settings.mcp_servers)


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
