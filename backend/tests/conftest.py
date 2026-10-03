"""pytest 共享工具：v0.7 三区（插件/技能/模块）加载器测试用 fake app（无 FastAPI 也能 apply(ctx)）。

单一数据根隔离（决策 5）：在**任何 app 模块导入之前**把 NUOMI_HOME / NUOMI_WORKSPACE
指向 pytest 专属临时目录——测试不写用户真实数据目录，也不触发遗留数据迁移。
注意：本文件顶层禁止 import app 模块（否则 settings 会在 env 覆盖前实例化）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("NUOMI_HOME", tempfile.mkdtemp(prefix="nuomi-test-"))
os.environ.setdefault("NUOMI_WORKSPACE", tempfile.mkdtemp(prefix="nuomi-test-ws-"))

REPO_ROOT = Path(__file__).resolve().parents[2]  # nuomi 仓库根
PLUGINS_DIR = REPO_ROOT / "plugins"
MODULES_DIR = REPO_ROOT / "backend" / "app" / "modules"
SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture
def fake_app():
    """轻量 app：PluginContext 依赖的 state 字段齐备。"""
    return make_fake_app()


def make_fake_app():
    from app.plugins.runtime import EventBus

    return SimpleNamespace(
        state=SimpleNamespace(
            event_bus=EventBus(),
            services={},
            plugin_ctx={},
            enabled_plugins=set(),
            plugin_settings={},
            tools=[],
            skills=[],
        )
    )


def applied_app(plugins_dir=None, modules_dir=None, skills_dir=None):
    """扫描（插件 + 模块 + 技能）+ apply 全部，返回已填充贡献的 fake app。

    参数可覆盖三区目录；默认扫仓库 plugins/、backend/app/modules/、skills/。
    """
    from app.plugins.lifecycle import load_plugins
    from app.plugins.loader import scan_plugins, scan_skills

    app = make_fake_app()
    app.state.plugins = scan_plugins(plugins_dir or PLUGINS_DIR) + scan_plugins(
        modules_dir or MODULES_DIR, category="module"
    )
    app.state.skills = scan_skills(skills_dir or SKILLS_DIR)
    load_plugins(app)
    return app


def applied_tools(plugins_dir=None):
    """v0.7 便捷版 collect_tools(load_skills(...))：apply 后取全部工具。"""
    from app.plugins.loader import collect_tools

    app = applied_app(plugins_dir)
    return collect_tools(app.state.plugins, enabled=app.state.enabled_plugins)
