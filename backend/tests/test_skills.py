"""插件加载器 v0.6（Harness 形态）：元数据常驻 / apply(ctx) 贡献收集 / 资源按需。"""
from __future__ import annotations

from pathlib import Path

from app.plugins.runtime import PluginContext
from app.plugins.loader import (
    collect_instructions,
    collect_skill_catalog,
    collect_tools,
    scan_plugins,
)

from .conftest import applied_app

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = REPO_ROOT / "plugins"


def test_scan_is_metadata_only():
    """级1：scan_plugins 只读 plugin.json，即使入口损坏也不报错（不 import）。"""
    plugins = scan_plugins(PLUGINS_DIR)
    names = {p.name for p in plugins}
    assert {"datetime", "memory", "knowledge", "mcp-notes", "pyfunc"} <= names
    # 元数据常驻：此时工具/服务/事件贡献为空（apply 尚未执行）
    assert all(p.tools == [] for p in plugins)
    assert all(p.error is None for p in plugins)


def test_apply_collects_contributions():
    """v0.6：apply(ctx) 后，每个插件的贡献（工具/服务/事件/技能）被收集。"""
    app = applied_app(PLUGINS_DIR)
    by_name = {p.name: p for p in app.state.plugins}
    # 能力插件贡献工具
    assert {t.name for t in by_name["datetime"].tools} == {"get_current_time"}
    assert {t.name for t in by_name["memory"].tools} >= {"memory_write", "memory_read"}
    # 程序插件贡献服务/事件（不再有 type 区分）
    assert "voice_input" in by_name["voice-input"].services
    assert "response_done" in by_name["mood"].events
    # SKILL.md 自动成为技能（正文在描述符里，目录只注入 name+description）
    assert by_name["memory"].skill_body
    assert not by_name["team"].skill_body  # 无 SKILL.md 的程序插件


def test_collect_tools_after_apply():
    """级2：collect_tools 汇总 apply 后的全部工具（无类型过滤——一切皆插件）。"""
    app = applied_app(PLUGINS_DIR)
    tools = collect_tools(app.state.plugins, enabled=app.state.enabled_plugins)
    by_name = {t.name: t for t in tools}
    assert "get_current_time" in by_name
    assert "memory_write" in by_name and "memory_read" in by_name
    assert "knowledge_add" in by_name and "knowledge_search" in by_name
    assert "notes_add" in by_name and "notes_search" in by_name
    assert "calc_add" in by_name and "greeting" in by_name


def test_collect_instructions():
    app = applied_app(PLUGINS_DIR)
    instrs = collect_instructions(app.state.plugins)
    assert any("get_current_time" in i for i in instrs)
    assert any("knowledge_add" in i for i in instrs)


def test_skill_catalog_metadata_only():
    """目录只含 name+description，正文不进常驻上下文（对齐 Harness 会话目录）。"""
    app = applied_app(PLUGINS_DIR)
    catalog = collect_skill_catalog(app.state.plugins, app.state.enabled_plugins)
    assert "skill name=\"memory\"" in catalog
    assert "memory_write" not in catalog  # 正文不进目录
    assert "skill name=\"mood\"" not in catalog  # 无 SKILL.md 的插件不进目录


def test_apply_surfaces_entry_error(tmp_path):
    """入口报错时：scan 不报错，apply(ctx) 后 error 可见、插件不进组合。"""
    bad = tmp_path / "bad-plugin"
    bad.mkdir()
    (bad / "plugin.json").write_text('{"name":"bad","entry":"hook.py"}', encoding="utf-8")
    (bad / "hook.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    from app.plugins.lifecycle import load_plugins

    from .conftest import make_fake_app

    app = make_fake_app()
    app.state.plugins = scan_plugins(tmp_path)
    load_plugins(app)
    assert app.state.plugins[0].error and "boom" in app.state.plugins[0].error
    assert app.state.plugins[0].name not in app.state.enabled_plugins
