"""本地 MCP server：便签服务（notes_add / notes_search）。

演示"外部能力经 MCP 接入"：这个 server 独立于糯米后端，任何 MCP 客户端都能连。
数据存本目录 data/notes.json。用 `python server.py` 启动（stdio 传输）。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# 数据路径可用环境变量覆盖（测试隔离用）；默认存本目录 data/notes.json
DATA = Path(
    os.environ.get("NOTES_DATA", str(Path(__file__).resolve().parent / "data" / "notes.json"))
)


def _load() -> list[dict]:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return []


def _save(notes: list[dict]) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


server = Server("nuomi-notes")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="notes_add",
            description="新增一条便签，返回便签编号",
            inputSchema={
                "type": "object",
                "properties": {"content": {"type": "string", "description": "便签内容"}},
                "required": ["content"],
            },
        ),
        Tool(
            name="notes_search",
            description="按关键词搜索便签，返回匹配列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "number", "description": "最多返回条数，默认 5"},
                },
            },
        ),
        Tool(
            name="notes_delete",
            description="按编号删除一条便签（不可恢复，高风险操作）",
            inputSchema={
                "type": "object",
                "properties": {"index": {"type": "number", "description": "便签编号（1 起）"}},
                "required": ["index"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, args: dict) -> list[TextContent]:
    notes = _load()
    if name == "notes_add":
        content = args.get("content", "").strip()
        if not content:
            return [TextContent(type="text", text="内容为空，未保存。")]
        notes.append({"content": content, "ts": int(time.time())})
        _save(notes)
        return [TextContent(type="text", text=f"已添加便签 #{len(notes)}：{content[:40]}")]
    if name == "notes_search":
        kw = args.get("keyword", "").strip()
        limit = int(args.get("limit", 5))
        hits = [n for n in notes if kw in n["content"]][:limit]
        if not hits:
            return [TextContent(type="text", text="没有找到匹配的便签。")]
        return [TextContent(type="text", text=json.dumps(hits, ensure_ascii=False))]
    if name == "notes_delete":
        idx = int(args.get("index", 0)) - 1
        if idx < 0 or idx >= len(notes):
            return [TextContent(type="text", text=f"便签编号 {args.get('index')} 不存在。")]
        removed = notes.pop(idx)
        _save(notes)
        return [
            TextContent(
                type="text", text=f"已删除便签 #{args.get('index')}：{removed['content'][:40]}"
            )
        ]
    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
