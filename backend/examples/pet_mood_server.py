"""示例 MCP 服务器：桌宠状态查询（官方 mcp 包低层 API，stdio transport）。

验证 MCP 接入用：nuomi 通过 langchain-mcp-adapters 连接此服务器，
工具名带 pet_mood_ 前缀，对话时经 mcp_use_default 暴露给模型。
"""
from __future__ import annotations

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("pet-mood-server")

_TOOLS = [
    types.Tool(
        name="get_pet_status",
        description="查询桌宠（糯米）当前状态：心情、电量、今日陪伴时长",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="add_reminder",
        description="给糯米添加一条今日提醒（写入 /tmp/nuomi_mcp_reminders.txt）",
        inputSchema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "提醒内容"}},
            "required": ["text"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_pet_status":
        return [types.TextContent(type="text", text="心情：开心（电量 87%，今日已陪伴 3 小时）")]
    if name == "add_reminder":
        text = str(arguments.get("text", ""))
        with open("/tmp/nuomi_mcp_reminders.txt", "a", encoding="utf-8") as f:
            f.write(text + "\n")
        return [types.TextContent(type="text", text=f"已记住：{text}")]
    return [types.TextContent(type="text", text=f"未知工具 {name}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
