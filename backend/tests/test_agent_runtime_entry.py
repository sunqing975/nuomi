"""Agent 运行时构造入口的回归测试。

背景：``HarnessManager.get_agent`` 按 agent_id 单例缓存，**构造参数只在首次生效**。
历史 bug：``/chat/history`` 漏传 ``workspace_dir``，把实例建到全局数据根后，
该专家的历史读不到、对话错写到全局 memory.sqlite。

修复方式是统一走 ``ensure_agent_runtime(agent_row)``。但 ``POST /agents/{id}/start``
（控制台「启动实例」按钮）**漏改了**——用户点一下按钮就会先占住缓存。
这里锁住「所有会构造实例的端点都必须落到专家 workspace」。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.domain.agents.service import agent_workspace_dir
from app.infra.harness.manager import manager


def _first_agent(client: TestClient) -> dict:
    return client.get("/api/agents").json()[0]


def test_start_endpoint_uses_expert_workspace(client: TestClient) -> None:
    """POST /agents/{id}/start 构造的实例必须落在专家 workspace，而非全局数据根。"""
    agent = _first_agent(client)
    aid = agent["agent_id"]
    manager.release(aid)  # 清掉可能已存在的缓存，保证首次构造发生在本用例内

    assert client.post(f"/api/agents/{aid}/start").status_code == 200

    assert manager.has(aid)
    assert manager._workspaces[aid] == agent_workspace_dir(aid)
    assert manager._workspaces[aid] != settings.data_root


def test_chat_endpoint_uses_expert_workspace(client: TestClient, stub_llm) -> None:
    """对话端点同样必须落到专家 workspace（与 start 一致）。"""
    agent = _first_agent(client)
    aid = agent["agent_id"]
    manager.release(aid)

    client.post(f"/api/agents/{aid}/chat", json={"messages": "hi", "thread_id": "ws-check"})

    assert manager._workspaces[aid] == agent_workspace_dir(aid)


def test_history_endpoint_uses_expert_workspace(client: TestClient) -> None:
    """历史端点（历史 bug 的起点）也必须落到专家 workspace。"""
    agent = _first_agent(client)
    aid = agent["agent_id"]
    manager.release(aid)

    client.get(f"/api/agents/{aid}/chat/history?thread_id=ws-check")

    assert manager._workspaces[aid] == agent_workspace_dir(aid)
