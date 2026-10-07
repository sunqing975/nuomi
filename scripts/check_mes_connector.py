#!/usr/bin/env python3
"""验证只读 MES 连接器：以 MCP 客户端身份拉起连接器进程，逐个调用工具并打印结果。

用法（确保 backend 依赖已装）：
    backend/.venv/bin/python scripts/check_mes_connector.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
CONNECTOR = REPO / "connectors" / "mes_connector.py"


async def main() -> None:
    params = StdioServerParameters(
        command=str(REPO / "backend" / ".venv" / "bin" / "python"),
        args=[str(CONNECTOR)],
        cwd=str(REPO),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        print(f"== 工具清单（{len(tools)} 个）==")
        for t in tools:
            print(f"  - {t.name}: {t.description.splitlines()[0]}")

        calls = [
            ("get_daily_production", {"query_date": "2026-09-23", "line": ""}),
            ("get_yield_trend", {"date_from": "2026-09-20", "date_to": "2026-09-26", "line": ""}),
            ("get_alarms", {"query_date": "2026-09-30", "line": ""}),
            ("get_equipment_status", {}),
            ("get_work_orders", {"status": "done", "line": "A", "limit": 3}),
            ("get_oee_summary", {"query_date": "2026-09-23"}),
        ]
        for name, args in calls:
            print(f"\n== {name}({json.dumps(args, ensure_ascii=False)}) ==")
            result = await session.call_tool(name, args)
            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text[:1200])
                else:
                    print(item)


if __name__ == "__main__":
    asyncio.run(main())
