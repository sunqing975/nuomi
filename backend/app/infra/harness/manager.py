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

from octop_harness import ChatRequest, HarnessAgent
from octop_harness.observability.langfuse import LangfuseConfig, LangfuseTracer

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
        # Langfuse 轨迹（观测）：启动时按工作区 langfuse.json 配置挂载，PUT /settings/langfuse 热更新
        self._langfuse: LangfuseTracer | None = None

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
        if self._langfuse is not None:
            self._agents[agent_id].set_langfuse_callbacks(self._langfuse.callbacks)
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
        """关闭全部 agent 实例（插件/技能/连接器/Provider 变更后重建用）。

        注意：**不清理 Langfuse tracer**。close() 被 15 处配置类端点调用（开关插件、
        存 env、改 provider、切模型…），顺手把 ``_langfuse`` 置 None 会让轨迹观测在
        本进程内永久失效且毫无提示（要等下次 PUT /settings/langfuse 或重启才恢复）。
        Langfuse 生命周期只由 ``set_langfuse`` 与进程退出的 ``shutdown`` 管。
        """
        for agent_id in list(self._agents):
            self.release(agent_id)

    def apply_skills_disabled(
        self,
        disabled: frozenset[str],
        *,
        sync_running: bool = True,
    ) -> int:
        """把新的禁用技能集热更新到**全部存活实例**，返回更新到的实例数。

        为什么不调 ``close()``：octop 的 ``SkillFilterMiddleware`` 每轮模型调用都重读
        ``self._config.skills_disabled``（``middleware/skill_filter.py:200/:260``），
        ``HarnessAgent.set_skills_disabled``（``agent.py:334``）改的正是这个字段——
        所以启停技能**不需要重建实例**。重建的代价是 ~147ms/专家（带 MCP stdio 更高，
        且同步阻塞事件循环），另外还会把「运行中」徽标打回「已停止」。

        ``sync_running``：实例已存在时 harness 会忽略 ``get_agent`` 传入的
        ``skills_disabled``（见 ``get_agent`` docstring），所以「启动实例」端点在冷构造
        之外还要显式同步一次——否则用户先关技能再启动专家，启动请求会把禁用集打回
        构造时那份（可能为空）。默认关闭以免影响对话热路径（多一次全量遍历）。
        """
        count = 0
        for agent in list(self._agents.values()):
            try:
                agent.set_skills_disabled(disabled)
                count += 1
            except Exception:  # 单个实例失败不能带走整条链
                logger.exception("set_skills_disabled 失败，该实例保持旧配置")
        return count

    def shutdown(self) -> None:
        """进程退出：释放全部实例并冲刷 Langfuse（main lifespan 收尾调用）。"""
        self.close()
        if self._langfuse is not None:
            self._langfuse.flush()
            self._langfuse = None

    # ------------------------------------------------------------------
    # Langfuse 轨迹（对齐 octop HarnessAgentManager.set_langfuse 语义）

    def set_langfuse(self, config: LangfuseConfig | None) -> None:
        """热更新 Langfuse 配置并同步到全部已建实例（配置变更后即时生效）。

        config 未 fully configured（enabled 或凭据缺失）时停用 tracer。
        """
        if config is not None and config.configured:
            if self._langfuse is None:
                self._langfuse = LangfuseTracer(config)
            else:
                self._langfuse.set_config(config)
        elif self._langfuse is not None:
            self._langfuse.set_config(None)
            self._langfuse = None
        self._sync_langfuse_to_agents()

    def _sync_langfuse_to_agents(self) -> None:
        callbacks = self._langfuse.callbacks if self._langfuse is not None else None
        for agent in self._agents.values():
            agent.set_langfuse_callbacks(callbacks)

    def enrich_request(self, request: ChatRequest) -> ChatRequest:
        """对话请求挂 Langfuse trace metadata（user/thread/agent）；未启用时原样返回。"""
        if self._langfuse is not None:
            return self._langfuse.enrich_request(request)
        return request

    def flush_langfuse(self) -> None:
        """对话结束后冲刷 trace（启用时；失败静默，不阻断对话）。"""
        if self._langfuse is not None:
            self._langfuse.flush()


manager = HarnessManager()
