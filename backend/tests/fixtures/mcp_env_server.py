"""MCP stdio 探针服务器：read_env 返回子进程环境变量。

用于验证连接器 env 字段确实注入到 MCP stdio 子进程（octop-harness
`merge_host_stdio_env` 行为：SDK 默认子集 + spec env）。
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("env-probe")


@mcp.tool()
def read_env(key: str) -> str:
    return os.environ.get(key, "")


if __name__ == "__main__":
    mcp.run(transport="stdio")
