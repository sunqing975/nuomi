"""Phase 3 · human-in-the-loop：高风险工具审批门。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.tools import tool

from app.approval import ApprovalGate
from app.main import build_app

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


@tool
def risky_delete(name: str) -> str:
    """高风险删除工具（测试用）。"""
    return f"已删除 {name}"


def _make_app(tmp_path):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )


def test_gate_blocks_and_approve_executes():
    gate = ApprovalGate(auto_approve=False)
    wrapped = gate.wrap(risky_delete)
    gate.register_tools([risky_delete])

    async def go():
        r = await wrapped.ainvoke({"name": "notes.json"})
        assert "apv-" in r and "人工确认" in r  # 未执行，进入审批
        pid = gate.pending()[0]["id"]
        assert gate.pending()[0]["tool"] == "risky_delete"
        r2 = await gate.approve(pid)
        assert "已批准并执行" in r2 and "已删除" in r2

    asyncio.run(go())


def test_gate_reject():
    gate = ApprovalGate(auto_approve=False)
    wrapped = gate.wrap(risky_delete)
    gate.register_tools([risky_delete])

    async def go():
        await wrapped.ainvoke({"name": "x"})
        pid = gate.pending()[0]["id"]
        assert "已拒绝" in gate.reject(pid)
        assert gate.pending() == []

    asyncio.run(go())


def test_gate_auto_approve_skips():
    gate = ApprovalGate(auto_approve=True)
    wrapped = gate.wrap(risky_delete)
    gate.register_tools([risky_delete])

    async def go():
        r = await wrapped.ainvoke({"name": "y"})
        assert r == "已删除 y" and gate.pending() == []

    asyncio.run(go())


def test_loader_marks_risky_tool(tmp_path):
    """加载器把 plugin.json approval 列表中的工具包进审批门。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        gate = app.state.gate
        assert gate is not None
        assert "notes_delete" in {t.name for t in app.state.tools}
        # 经 gate 包装后：直接调用应返回"需人工确认"，不真正执行
        async def go():
            r = await next(t for t in app.state.tools if t.name == "notes_delete").ainvoke({"index": 1})
            assert "人工确认" in r or "apv-" in r

        asyncio.run(go())
