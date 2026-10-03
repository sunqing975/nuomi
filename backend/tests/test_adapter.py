"""Phase 2 · adapter：外部格式插件（普通函数）适配成 LangChain 工具。"""

from __future__ import annotations

from pathlib import Path

from .conftest import applied_tools

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyfunc_adapter_tools():
    tools = {t.name: t for t in applied_tools(str(REPO_ROOT / "plugins"))}
    assert "calc_add" in tools and "greeting" in tools


def test_pyfunc_calc_add():
    tools = {t.name: t for t in applied_tools(str(REPO_ROOT / "plugins"))}
    assert tools["calc_add"].invoke({"a": 2, "b": 3}) == 5


def test_pyfunc_greeting():
    tools = {t.name: t for t in applied_tools(str(REPO_ROOT / "plugins"))}
    r = tools["greeting"].invoke({"name": "小超"})
    assert "小超" in r
