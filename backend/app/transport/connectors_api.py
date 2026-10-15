"""连接器路由：MCP 服务器（控制台增删改，写 data_root/connectors.json，manager.close 重载）。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.infra.env_store import is_masked_sentinel, mask_all
from app.infra.harness.manager import manager

router = APIRouter(prefix="/api", tags=["connectors"])

_CONNECTOR_TRANSPORTS = ("stdio", "sse", "http")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_env(spec: dict) -> dict[str, str]:
    """**读侧脱敏**：连接器 spec 的 ``env`` 里常放 MCP 子进程密钥（见
    ``_persist_connectors`` docstring），而 GET/POST/PUT 的响应会被前端原样填进表单
    并渲进 DOM（``Connectors.tsx``）。全仓其它密钥出口都早脱敏了
    （``env_store.mask_all`` / ``providers_store.mask_key`` / ``langfuse_store``），
    这是最后一个漏的。非密钥键原样返回，不影响普通配置可见性。
    """
    env = spec.get("env") or {}
    if not isinstance(env, dict):
        return {}
    return mask_all({k: str(v) for k, v in env.items()})


def _merge_env(name: str, incoming: dict[str, str]) -> dict[str, str]:
    """写侧回填：表单里没动过的密钥会带着掩码形态回来（``sk-1***3456``），
    必须原样保留旧值——否则一次「只改 command」的保存就把密钥写成了掩码串。

    判据用 ``is_masked_sentinel``（精确等于 ``mask_value(当前值)``）而不是「值里含
    ``***``」：后者会让用户真想把值改成含 ``***`` 的字符串时被静默还原（``env_store``
    里已论证过这一点，别再退回去）。
    """
    current = (settings.mcp_servers.get(name) or {}).get("env") or {}
    merged: dict[str, str] = {}
    for k, v in incoming.items():
        old = str(current.get(k) or "") if isinstance(current, dict) else ""
        merged[k] = old if is_masked_sentinel(v, old) else v
    return merged


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
    if transport == "stdio":
        _reject_missing_paths(body.command, list(body.args or []))
    return {
        "transport": transport,
        "command": (body.command or "").strip(),
        "args": list(body.args or []),
        "env": env,
    }


def _reject_missing_paths(command: str, args: list[str]) -> None:
    """stdio 连接器的**绝对路径**不存在 → 保存时就 400，别拖到每轮对话。

    MCP 子进程是对话时按需拉起的，路径写错时界面只表现为「这个连接器的工具凭空少了
    几个」，错误沉在日志里。曾经真踩过：``.env`` 首启种子指向
    ``backend/examples/pet_mood_server.py``，而仓库里只有 ``avatar_mood_server.py``
    （2026-10-15 审计发现，种子已注释）。

    判定范围刻意收窄（宁漏不误杀）：
    - ``command`` 含 ``/`` → 视为显式路径，必须是真实文件；纯命令名（python/npx/uvx）
      交给 PATH，不判。
    - ``args`` 里**以 / 开头且以脚本后缀结尾**的项才判；其余（相对路径、开关值、
      ``--config foo`` 之类）一律放过，因为相对路径的解析基准是 harness 的 spawn cwd，
      不由我们掌控，按它报错会误杀 ``python examples/x.py`` 这种合法写法。
    """
    script_suffix = (".py", ".js", ".mjs", ".cjs", ".sh")
    missing: list[str] = []
    cmd = command.strip()
    if "/" in cmd and not Path(cmd).is_file():
        missing.append(cmd)
    for raw in args:
        entry = str(raw)
        if entry.startswith("/") and entry.endswith(script_suffix) and not Path(entry).is_file():
            missing.append(entry)
    if missing:
        raise HTTPException(
            status_code=400,
            detail="连接器路径不存在：" + "、".join(missing) + "（stdio 的绝对路径必须真实存在）",
        )


def _persist_connectors() -> None:
    """写 data_root/connectors.json（重启后由 main._sync_connectors_file 读回，json 权威）。

    原子写 + 0600：连接器 spec 的 ``env`` 里常放 MCP 子进程的密钥。
    """
    from app.infra.secret_file import write_json

    write_json(settings.data_root / "connectors.json", settings.mcp_servers)


@router.get("/connectors")
async def list_connectors() -> list[dict]:
    """连接器列表（配置来自 settings.mcp_servers，connectors.json 权威）。

    ``env`` 走 ``_read_env`` 脱敏——真实值只留在内存配置与 0600 的 connectors.json。
    """
    return [
        {
            "name": name,
            "transport": spec.get("transport", "stdio"),
            "command": spec.get("command", ""),
            "args": spec.get("args", []),
            "env": _read_env(spec),
        }
        for name, spec in settings.mcp_servers.items()
    ]


def _public(name: str, spec: dict) -> dict:
    """写端点的响应：结构同 GET，env 一律脱敏（前端回写由 ``_merge_env`` 兜住）。"""
    return {
        "ok": True,
        "name": name,
        **spec,
        "env": _read_env(spec),
    }


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
    return _public(name, spec)


@router.put("/connectors/{name}")
async def update_connector(name: str, body: ConnectorBody) -> dict:
    """编辑连接器：更新配置 + 释放实例（下次对话生效）。"""
    if name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail="连接器不存在")
    spec = _validate_connector_spec(body)
    spec["env"] = _merge_env(name, spec["env"])  # 掩码回填：没动过的密钥保持原值
    settings.mcp_servers[name] = spec
    _persist_connectors()
    manager.close()
    return _public(name, spec)


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
