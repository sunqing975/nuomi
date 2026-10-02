"""Phase 2 · MCP 插件：元数据常驻不建连 + 首次调用才连真实 server。"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.plugins.loader import scan_plugins

from .conftest import applied_tools

REPO_ROOT = Path(__file__).resolve().parents[2]


def _notes_tools():
    return {t.name: t for t in applied_tools(str(REPO_ROOT / "plugins"))}


def test_mcp_plugin_metadata_only(tmp_path, monkeypatch):
    """load_skills 阶段（级1）不应启动任何 MCP 子进程：入口尚未导入。"""
    plugins = scan_plugins(str(REPO_ROOT / "plugins"))
    mcp = next(s for s in plugins if s.name == "mcp-notes")
    assert mcp.tools == []  # 未导入入口
    assert mcp.error is None


def test_mcp_notes_add_search(tmp_path, monkeypatch):
    """真实拉起本地 MCP server（stdio 子进程），经 adapter 调用工具。"""
    data = tmp_path / "notes.json"
    monkeypatch.setenv("NOTES_DATA", str(data))
    tools = _notes_tools()
    assert "notes_add" in tools and "notes_search" in tools

    async def go():
        r1 = await tools["notes_add"].ainvoke({"content": "周五面试作品集展示"})
        assert "已添加便签" in r1
        r2 = await tools["notes_search"].ainvoke({"keyword": "面试"})
        assert "面试作品集" in r2
        r3 = await tools["notes_search"].ainvoke({"keyword": "不存在的词"})
        assert "没有找到" in r3

    asyncio.run(go())
    assert data.exists(), "MCP server 应把便签写进数据文件"
