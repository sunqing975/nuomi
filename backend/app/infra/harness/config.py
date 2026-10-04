"""配置映射：nuomi settings / 专家定义 → octop-harness 配置对象。

对齐 Octop 的做法（src/octop/infra/agents/manager.py）：把领域配置翻译成
HarnessAgentConfig，再由 manager 负责生命周期。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from octop_harness import HarnessAgentConfig, init_workspace
from octop_harness.config import ModelConfig, ProviderConfig

from app.config import settings


def build_provider() -> ProviderConfig:
    """从 .env 的 LLM_* 配置构造 OpenAI 兼容 ProviderConfig。"""
    return ProviderConfig(
        id="llm",
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        protocol="openai",
        models=[ModelConfig(id=settings.llm_model, name=settings.llm_model)],
    )


def build_agent_config(
    workspace_dir: Path,
    *,
    name: str = "nuomi",
    system_prompt: str = "",
    plugin_tools: list | None = None,
    skills_dir: str | Path | Sequence[str | Path] | None = None,
    skills_disabled: frozenset[str] = frozenset(),
    mcp_server_configs: dict | None = None,
    mcp_default_servers: list[str] | None = None,
) -> HarnessAgentConfig:
    """构造单个 Agent 的运行时配置（工作区按 harness init_workspace 布局）。

    model_ref 使用 "provider/model" 复合串（Octop resolve_explicit_default_model 形态）。
    plugin_tools：插件注册的工具（build_plugin_tools 结果），经 cfg.tools 注入 agent。
    skills_dir / skills_disabled：自定义技能目录与禁用集合。
    mcp_server_configs / mcp_default_servers：MCP 服务器（对话请求经 mcp_use_default 启用）。
    """
    init_workspace(workspace_dir, language="zh", include_md_files=False, include_skills=True)
    return HarnessAgentConfig(
        name=name,
        workspace_dir=workspace_dir,
        providers=[build_provider()],
        default_model=f"llm/{settings.llm_model}",
        system_prompt=system_prompt
        or "你是糯米，一个住在用户电脑里的桌面 AI 人格。中文回答，简洁友好。",
        tools=plugin_tools,
        skills_dir=skills_dir,
        skills_disabled=skills_disabled,
        mcp_server_configs=mcp_server_configs or {},
        mcp_default_servers=mcp_default_servers,
    )
