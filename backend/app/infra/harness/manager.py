"""Agent 运行时生命周期：HarnessManager 单例，按 agent_id 管理实例。

对齐 Octop 的 HarnessAgentManager 语义（单例 + DB↔runtime 同步）。nuomi 版：
按 agent_id 缓存 HarnessAgent 实例，start=首次构造并置 running，stop=释放实例。

依赖规则：infra 禁 import domain/transport——manager 只接收构造参数
（name/system_prompt 由调用方从 agents 表取出传入），不做领域查询。
"""
from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from octop_harness import HarnessAgent

from app.config import settings
from app.infra.harness.config import build_agent_config

if TYPE_CHECKING:
    from pathlib import Path


class HarnessManager:
    """单例：持有各 Agent 的运行时实例。"""

    def __init__(self) -> None:
        self._agents: dict[str, HarnessAgent] = {}

    @property
    def workspace(self) -> Path:
        return settings.workspace_path

    def get_agent(
        self,
        agent_id: str,
        *,
        name: str,
        system_prompt: str,
        plugin_tools: list | None = None,
        skills_dir=None,
        skills_disabled: frozenset[str] = frozenset(),
    ) -> HarnessAgent:
        """按 agent_id 取实例；不存在则构造并缓存（start 语义）。

        plugin_tools / skills：随 agent 绑定变化；实例已存在时忽略（改绑定需重启实例）。
        """
        if agent_id not in self._agents:
            cfg = build_agent_config(
                self.workspace,
                name=name,
                system_prompt=system_prompt,
                plugin_tools=plugin_tools,
                skills_dir=skills_dir,
                skills_disabled=skills_disabled,
            )
            self._agents[agent_id] = HarnessAgent(cfg)
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def release(self, agent_id: str) -> None:
        """停止并释放实例（stop 语义）。"""
        agent = self._agents.pop(agent_id, None)
        if agent is not None:
            with suppress(Exception):
                agent.close()

    def close(self) -> None:
        """关闭全部实例（进程退出时调用）。"""
        for agent_id in list(self._agents):
            self.release(agent_id)


manager = HarnessManager()
