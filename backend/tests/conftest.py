"""pytest 共享工具：v0.6 加载器测试用 fake app（无 FastAPI 也能 apply(ctx)）。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.plugin_runtime import EventBus


@pytest.fixture
def fake_app():
    """轻量 app：PluginContext 依赖的 state 字段齐备。"""
    return make_fake_app()


def make_fake_app():
    return SimpleNamespace(
        state=SimpleNamespace(
            event_bus=EventBus(),
            services={},
            plugin_ctx={},
            enabled_plugins=set(),
            plugin_settings={},
            tools=[],
        )
    )


def applied_app(plugins_dir):
    """扫描 + apply 全部插件，返回已填充贡献的 fake app（测试便捷入口）。"""
    from app.plugins import load_plugins
    from app.skills import scan_plugins

    app = make_fake_app()
    app.state.plugins = scan_plugins(plugins_dir)
    load_plugins(app)
    return app


def applied_tools(plugins_dir):
    """v0.6 便捷版 collect_tools(load_skills(...))：apply 后取全部工具。"""
    from app.skills import collect_tools

    app = applied_app(plugins_dir)
    return collect_tools(app.state.plugins, enabled=app.state.enabled_plugins)
