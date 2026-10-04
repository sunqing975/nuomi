"""连接器（MCP）测试：env 字段 API 透传 + 校验；env 注入 MCP stdio 子进程集成验证。

- API 层：create/list/update/delete 带 env，非法键名 400。
- 集成层：octop-harness `load_mcp_tools` 加载 fixtures/mcp_env_server.py，
  断言 spec env 出现在子进程环境变量（stdio 生效）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
ENV_SERVER = FIXTURES / "mcp_env_server.py"

# —— API 层 ——


def test_connector_crud_with_env(client: TestClient) -> None:
    # create（带 env）
    r = client.post(
        "/api/connectors",
        json={
            "name": "env_probe",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(ENV_SERVER)],
            "env": {"GITHUB_TOKEN": "ghp_test", "EMPTY_VAL": ""},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["env"] == {"GITHUB_TOKEN": "ghp_test", "EMPTY_VAL": ""}

    # list 返回 env
    servers = client.get("/api/connectors").json()
    row = next(s for s in servers if s["name"] == "env_probe")
    assert row["env"] == {"GITHUB_TOKEN": "ghp_test", "EMPTY_VAL": ""}

    # update 替换 env
    r = client.put(
        "/api/connectors/env_probe",
        json={"transport": "stdio", "command": sys.executable, "env": {"MY_KEY": "1"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["env"] == {"MY_KEY": "1"}

    # 非法键名 400
    r = client.put(
        "/api/connectors/env_probe",
        json={"transport": "stdio", "command": sys.executable, "env": {"1BAD KEY": "x"}},
    )
    assert r.status_code == 400
    assert "环境变量名不合法" in r.json()["detail"]

    # 空键过滤
    r = client.put(
        "/api/connectors/env_probe",
        json={"transport": "stdio", "command": sys.executable, "env": {"  ": "x", "OK": "y"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["env"] == {"OK": "y"}

    # delete 清场
    assert client.delete("/api/connectors/env_probe").status_code == 200
    assert all(s["name"] != "env_probe" for s in client.get("/api/connectors").json())


# —— 集成：env 注入 MCP stdio 子进程 ——


def test_mcp_stdio_env_injection() -> None:
    from octop_harness.mcp import load_mcp_tools

    tools = load_mcp_tools(
        {
            "env_probe": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(ENV_SERVER)],
                "env": {"NUOMI_TEST_ENV": "42"},
            }
        }
    )
    names = [t.name for t in tools]
    read_env = next((t for t in tools if t.name.startswith("env_probe_") and t.name.endswith("read_env")), None)
    assert read_env is not None, f"read_env 工具缺失: {names}"

    # spec env 注入
    async def _probe(key: str) -> str:
        result = await read_env.ainvoke({"key": key})
        # ToolMessage → 可能是 str，也可能是 [{'type':'text','text':...}] 内容块
        if isinstance(result, list):
            return "".join(str(b.get("text", "")) for b in result if isinstance(b, dict))
        return str(result)

    assert asyncio.run(_probe("NUOMI_TEST_ENV")) == "42"
    # 宿主 PATH 仍由 SDK 默认子集保留（未被 spec env 覆盖为空）
    assert asyncio.run(_probe("PATH")) != ""
