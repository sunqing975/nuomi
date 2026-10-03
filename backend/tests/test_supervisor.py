"""Phase 4b · Supervisor 多智能体：路由 + 子 Agent 分派。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.domain.experts.supervisor import build_supervisor
from app.main import build_app
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


class Router:
    """确定性路由（测试注入）：next 由构造参数固定。"""

    def __init__(self, nxt: str):
        self.nxt = nxt

    async def ainvoke(self, msgs):
        return type("R", (), {"next": self.nxt})()


@pytest.fixture
def sup(tmp_path):
    app = build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        plugins_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "nuomi" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )
    with TestClient(app) as client:
        yield app, client


def test_supervisor_builds_with_subagents(sup):
    app, _client = sup
    assert set(app.state.subagents.keys()) == {"companion", "researcher"}
    names = app.state.subagents["companion"]["tools"]
    assert "memory_write" in names and "get_current_time" in names
    rnames = app.state.subagents["researcher"]["tools"]
    assert "knowledge_search" in rnames and "calc_add" in rnames


def test_supervisor_routes_to_companion(sup):
    app, _client = sup
    graph, _ = build_supervisor(
        llm=FakeChatModel(), tools=list(app.state.tools), router=Router("companion")
    )

    async def go():
        out = await graph.ainvoke(
            {"messages": [HumanMessage(content="我今天好累")]},
            {"configurable": {"thread_id": "sup-t1"}},
        )
        texts = [str(m.content) for m in out["messages"]]
        assert any("你好" in t or "累" in t for t in texts)  # FakeChatModel 固定回复

    asyncio.run(go())


def test_supervisor_routes_to_researcher(sup):
    app, _client = sup
    graph, _ = build_supervisor(
        llm=FakeChatModel(), tools=list(app.state.tools), router=Router("researcher")
    )

    async def go():
        out = await graph.ainvoke(
            {"messages": [HumanMessage(content="查一下知识库")]},
            {"configurable": {"thread_id": "sup-t2"}},
        )
        assert len(out["messages"]) > 0

    asyncio.run(go())


def test_supervisor_endpoint_streams(sup):
    _app, client = sup
    r = client.post("/api/supervisor/chat", json={"message": "帮我查资料", "thread_id": "s1"})
    assert r.status_code == 200
    assert "data:" in r.text
    info = client.get("/api/supervisor/info").json()
    assert set(info["agents"].keys()) == {"companion", "researcher"}
