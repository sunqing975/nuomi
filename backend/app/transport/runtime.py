"""transport 层共享运行时 helper：确保某专家的 HarnessAgent 实例以完整参数构造。

从 transport/api.py 拆出（P0-2，2026-10-06）——``ensure_agent_runtime`` 被
chat 与 agents 两个域共用，抽成 transport 内部共享模块，避免域间互相 import。
"""

from __future__ import annotations

from app.config import settings
from app.domain.agents.service import ensure_agent_workspace
from app.domain.plugins.service import plugin_service
from app.domain.skillpackages.service import skill_package_service
from app.domain.skills.service import skill_service
from app.infra.harness.manager import manager


def all_skills_dirs() -> list:
    """注入用技能根列表：工作区单技能 + 各已启用技能包内技能目录。"""
    return [skill_service.skills_dir(), *skill_package_service.skills_dirs()]


def ensure_agent_runtime(agent_row: dict, *, sync_skills: bool = False):
    """统一构造/获取某专家的 HarnessAgent 运行时实例。

    所有端点（控制台对话 / 历史加载 / AI 数字人壳 OpenAI 兼容 / 启动实例）必须经此入口，
    禁止各自调 manager.get_agent 传残缺参数。原因：manager 按 agent_id 单例缓存，
    构造参数（workspace_dir / 插件工具 / 技能目录 / MCP）只在首次构造时生效；
    若历史端点先到（页面加载自动拉历史）而漏传 workspace_dir，会把「全局根
    memory.sqlite + 无工具」的残缺实例缓存下来，导致专家工作区的对话历史读不到、
    后续对话全部错写到全局根库。

    ``sync_skills``：仅「启动实例」端点传 True。缓存命中时 ``get_agent`` 会**忽略**
    ``skills_disabled``（见其 docstring），用户「先停技能 → 再点启动」就会让实例带着
    旧的禁用集上岗；启动后显式热同步一次（对话热路径不传，免得每轮多一次遍历）。
    """
    agent_id = agent_row["agent_id"]
    # 缓存命中就直接返回：这些实参是**急切求值**的，即使 manager 内部命中缓存也会被算一遍
    # （实测 plugin_service.tools() ~5.6ms/次，白算还占着事件循环）。
    # 释放实例的路径（插件启停/切模型/改 provider 端点）都会调 manager.close()/release()，
    # 所以"不存在于缓存"就等于"参数需要重算"。
    if manager.has(agent_id):
        agent = manager.get_agent(
            agent_id, name=agent_row["name"], system_prompt=agent_row["system_prompt"] or ""
        )
        if sync_skills:
            manager.apply_skills_disabled(skill_service.disabled_set())
        return agent

    return manager.get_agent(
        agent_id,
        name=agent_row["name"],
        system_prompt=agent_row["system_prompt"] or "",
        workspace_dir=ensure_agent_workspace(agent_id, agent_row["name"]),
        plugin_tools=plugin_service.tools(),
        skills_dir=all_skills_dirs(),
        skills_disabled=skill_service.disabled_set(),
        mcp_server_configs=settings.mcp_servers,
        mcp_default_servers=list(settings.mcp_servers.keys()) or None,
    )
