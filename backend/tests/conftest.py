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
SKILLS_DIR = REPO_ROOT / "skills"
# 领域根（P2 领域归位后）：内核模块按领域分散在 domain/、transport/、engine/services/
DOMAIN_ROOTS = [
    REPO_ROOT / "backend" / "app" / "domain" / "experts",
    REPO_ROOT / "backend" / "app" / "domain" / "memory",
    REPO_ROOT / "backend" / "app" / "domain" / "behavior",
    REPO_ROOT / "backend" / "app" / "transport",
    REPO_ROOT / "backend" / "app" / "infrastructure" / "engine" / "services",
]


@pytest.fixture
def fake_app():
    """轻量 app：PluginContext 依赖的 state 字段齐备。"""
    return make_fake_app()


def make_fake_app():
    from app.infrastructure.engine.runtime import EventBus

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


def applied_app(plugins_dir=None, domain_roots=None, skills_dir=None):
    """扫描（插件 + 领域模块 + 技能）+ apply 全部，返回已填充贡献的 fake app。

    参数可覆盖三区目录；默认扫仓库 plugins/、领域根 DOMAIN_ROOTS、skills/。
    """
    from app.infrastructure.engine.lifecycle import load_plugins
    from app.infrastructure.engine.loader import scan_plugins, scan_skills

    app = make_fake_app()
    scans = list(scan_plugins(plugins_dir or PLUGINS_DIR))
    for root in domain_roots or DOMAIN_ROOTS:
        scans += scan_plugins(root, category="module")
    app.state.plugins = scans
    app.state.skills = scan_skills(skills_dir or SKILLS_DIR)
    load_plugins(app)
    return app


def applied_tools(plugins_dir=None):
    """v0.7 便捷版 collect_tools(load_skills(...))：apply 后取全部工具。"""
    from app.infrastructure.engine.loader import collect_tools

    app = applied_app(plugins_dir)
    return collect_tools(app.state.plugins, enabled=app.state.enabled_plugins)
