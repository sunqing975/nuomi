"""Agent 运行时生命周期：HarnessManager 单例，按 agent_id 管理实例。

对齐 Octop 的 HarnessAgentManager 语义（单例 + DB↔runtime 同步）。nuomi 版：
按 agent_id 缓存 HarnessAgent 实例，start=首次构造并置 running，stop=释放实例。

依赖规则：infra 禁 import domain/transport——manager 只接收构造参数
（name/system_prompt 由调用方从 agents 表取出传入），不做领域查询。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from octop_harness import HarnessAgent

from app.config import settings
from app.infra.harness.config import build_agent_config

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class HarnessManager:
    """单例：持有各 Agent 的运行时实例。"""

    def __init__(self) -> None:
        self._agents: dict[str, HarnessAgent] = {}
        # 首次构造时的工作区目录：缓存命中时据此发现调用方参数漂移
        # （历史上 history 端点漏传 workspace_dir，把实例建到全局根导致历史读空）。
        self._workspaces: dict[str, Path] = {}

    @property
    def workspace(self) -> Path:
        """默认工作区（全局数据根；专家级 workspace 由 get_agent 的 workspace_dir 指定）。"""
        return settings.workspace_path

    def get_agent(
        self,
        agent_id: str,
        *,
        name: str,
        system_prompt: str,
        workspace_dir: Path | None = None,
        plugin_tools: list | None = None,
        skills_dir=None,
        skills_disabled: frozenset[str] = frozenset(),
        mcp_server_configs: dict | None = None,
        mcp_default_servers: list[str] | None = None,
    ) -> HarnessAgent:
        """按 agent_id 取实例；不存在则构造并缓存（start 语义）。

        workspace_dir：专家级工作区（persona 文件 + 独立记忆/sessions）。None 时用全局数据根。
        plugin_tools / skills / mcp：随 agent 绑定变化；实例已存在时忽略（改绑定需重启实例）。
        模型不绑专家（2026-10-04）：agent 默认模型 = providers 默认；对话时由
        ChatRequest.model per-turn 覆盖。
        """
        if agent_id in self._agents:
            expected = self._workspaces.get(agent_id)
            if workspace_dir is not None and expected is not None and workspace_dir != expected:
                logger.warning(
                    "agent %s workspace_dir 漂移：缓存=%s 本次请求=%s（参数被忽略，"
                    "请改走统一运行时入口）",
                    agent_id,
                    expected,
                    workspace_dir,
                )
            return self._agents[agent_id]
        ws = workspace_dir or self.workspace
        cfg = build_agent_config(
            ws,
            name=name,
            system_prompt=system_prompt,
            plugin_tools=plugin_tools,
            skills_dir=skills_dir,
            skills_disabled=skills_disabled,
            mcp_server_configs=mcp_server_configs,
            mcp_default_servers=mcp_default_servers,
        )
        self._agents[agent_id] = HarnessAgent(cfg)
        self._workspaces[agent_id] = ws
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def release(self, agent_id: str) -> None:
        """停止并释放实例（stop 语义）。"""
        agent = self._agents.pop(agent_id, None)
        self._workspaces.pop(agent_id, None)
        if agent is not None:
            with suppress(Exception):
                agent.close()

    def close(self) -> None:
        """关闭全部实例（进程退出时调用）。"""
        for agent_id in list(self._agents):
            self.release(agent_id)


manager = HarnessManager()
