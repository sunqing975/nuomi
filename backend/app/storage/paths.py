"""路径解析层：所有"数据根 + 目录/agent_id 拼接"在这里定义。

分层边界（2026-10-06 修复，见 next-steps.md §1.1）：**路径解析属于 storage/config，
不属于 domain**。domain 与 infra 想算路径时都从这里取，禁止反向依赖 domain service
（此前 infra/memory_store 依赖 domain.agents.service.agent_workspace_dir、
infra/plugins/market 依赖 domain.plugins.service.plugin_service 均属违规）。
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings

# 专家工作区目录名（对齐 Octop ~/.octop/agents/<id>/）
AGENT_WORKSPACES_DIR = "agent-workspaces"


def agent_workspace_dir(agent_id: str) -> Path:
    """专家级工作区：persona 文件 + 独立记忆/sessions（对齐 octop ~/.octop/agents/<id>/）。"""
    return settings.data_root / AGENT_WORKSPACES_DIR / agent_id


def plugins_dir() -> Path:
    """工作区插件目录（{workspace}/plugins）。纯路径解析，不创建目录。"""
    return settings.workspace_path / "plugins"


def skills_dir() -> Path:
    """工作区技能目录（{workspace}/skills）。纯路径解析，不创建目录。"""
    return settings.workspace_path / "skills"
