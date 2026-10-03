"""MCP 插件（type=mcp, load=lazy）· 便签能力。

级3 资源按需：MCP 客户端连接与工具列表在**首次调用**时才建立（get_tools 一次，
之后按工具名缓存；每次调用由 adapter 自动开新会话）。启动零开销、零子进程。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool

SERVER_SCRIPT = Path(__file__).resolve().parent / "server.py"

_client = None
_tools_by_name: dict[str, object] = {}


async def _resolve(name: str):
    global _client, _tools_by_name
    if name not in _tools_by_name:
        if _client is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.sessions import StdioConnection

            _client = MultiServerMCPClient(
                {
                    "notes": StdioConnection(
                        transport="stdio",
                        command=sys.executable,
                        args=[str(SERVER_SCRIPT)],
                        env=dict(os.environ),  # 显式传环境（测试可用 NOTES_DATA 隔离数据）
                    )
                }
            )
        tools = await _client.get_tools(server_name="notes")
        _tools_by_name = {t.name: t for t in tools}
    return _tools_by_name.get(name)


async def _notes_add(content: str) -> str:
    t = await _resolve("notes_add")
    if t is None:
        return "便签服务不可用（notes_add 未注册）。"
    return str(await t.ainvoke({"content": content}))


async def _notes_search(keyword: str, limit: int = 5) -> str:
    t = await _resolve("notes_search")
    if t is None:
        return "便签服务不可用（notes_search 未注册）。"
    return str(await t.ainvoke({"keyword": keyword, "limit": limit}))


async def _notes_delete(index: int) -> str:
    t = await _resolve("notes_delete")
    if t is None:
        return "便签服务不可用（notes_delete 未注册）。"
    return str(await t.ainvoke({"index": index}))


TOOLS = [
    StructuredTool.from_function(
        coroutine=_notes_add,
        name="notes_add",
        description="新增一条便签（存入本地 MCP 便签服务），返回便签编号与内容。",
    ),
    StructuredTool.from_function(
        coroutine=_notes_search,
        name="notes_search",
        description="按关键词在便签服务中搜索，返回匹配的便签列表（可传 limit 控制条数）。",
    ),
    StructuredTool.from_function(
        coroutine=_notes_delete,
        name="notes_delete",
        description="按编号删除一条便签（不可恢复，需用户批准后执行）。",
    ),
]
