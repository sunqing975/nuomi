"""Phase 4a · PostgreSQL checkpointer（本地 PG 不可用时自动跳过）。

用真实 StateGraph 走编译→存储→读回路径，验证多线程隔离。
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from app.agent import create_pg_checkpointer

DSN = "postgresql://localhost:5432/nuomi"


def _pg_up() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_up(), reason="本地 PostgreSQL 未运行")


def _graph(saver):
    def node(state):
        last = state["messages"][-1]
        return {"messages": [HumanMessage(content=f"echo:{last.content}")]}

    g = StateGraph(MessagesState)
    g.add_node("n", node)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    return g.compile(checkpointer=saver)


def test_pg_saver_roundtrip(tmp_path):
    """真实 PG：建表 → 跑一轮 → 按 thread 读回消息。"""
    async def go():
        async with create_pg_checkpointer(DSN) as saver:
            graph = _graph(saver)
            config = {"configurable": {"thread_id": "pg-smoke-1", "checkpoint_ns": ""}}
            await graph.ainvoke({"messages": [HumanMessage(content="你好")]}, config)
            t = await saver.aget_tuple(config)
            assert t is not None
            msgs = t.checkpoint["channel_values"]["messages"]
            assert any("echo:你好" in str(m.content) for m in msgs)

    asyncio.run(go())


def test_pg_isolation_between_threads(tmp_path):
    """不同 thread 互不串扰。"""
    async def go():
        async with create_pg_checkpointer(DSN) as saver:
            graph = _graph(saver)
            cfg_a = {"configurable": {"thread_id": "a", "checkpoint_ns": ""}}
            cfg_b = {"configurable": {"thread_id": "b", "checkpoint_ns": ""}}
            await graph.ainvoke({"messages": [HumanMessage(content="A")]}, cfg_a)
            await graph.ainvoke({"messages": [HumanMessage(content="B")]}, cfg_b)
            ta = await saver.aget_tuple(cfg_a)
            tb = await saver.aget_tuple(cfg_b)
            texts_a = [str(m.content) for m in ta.checkpoint["channel_values"]["messages"]]
            texts_b = [str(m.content) for m in tb.checkpoint["channel_values"]["messages"]]
            assert "echo:A" in texts_a and "echo:B" not in texts_a
            assert "echo:B" in texts_b and "echo:A" not in texts_b

    asyncio.run(go())
