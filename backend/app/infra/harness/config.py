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


def build_providers() -> list[ProviderConfig]:
    """从 providers.json 构造 ProviderConfig 列表（缺省回退 .env 的 LLM_* 种子）。"""
    from app.infra.providers_store import load as load_providers

    out: list[ProviderConfig] = []
    for p in load_providers():
        models = [ModelConfig(id=m["id"], name=m.get("name") or m["id"]) for m in (p.get("models") or []) if m.get("id")]
        out.append(
            ProviderConfig(
                id=p["id"],
                base_url=p.get("base_url") or "",
                # harness 硬性要求 api_key 非空；本地服务（llama.cpp 等）无鉴权，
                # 用占位 key 满足校验，请求头被服务端忽略
                api_key=p.get("api_key") or "sk-local",
                protocol=p.get("protocol") or "openai",
                models=models,
            )
        )
    return out


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
    模型不绑专家（2026-10-04）：默认模型 = providers[0] 的 models[0]；
    对话时由 ChatRequest.model per-turn 覆盖（harness 原生优先于 default_model）。
    plugin_tools：插件注册的工具（build_plugin_tools 结果），经 cfg.tools 注入 agent。
    skills_dir / skills_disabled：自定义技能目录与禁用集合。
    mcp_server_configs / mcp_default_servers：MCP 服务器（对话请求经 mcp_use_default 启用）。
    """
    init_workspace(workspace_dir, language="zh", include_md_files=False, include_skills=True)
    providers = build_providers()
    default_model = None
    if providers and providers[0].models:
        default_model = f"{providers[0].id}/{providers[0].models[0].id}"
    return HarnessAgentConfig(
        name=name,
        workspace_dir=workspace_dir,
        providers=providers,
        default_model=default_model or f"llm/{settings.llm_model}",
        system_prompt=system_prompt
        or "你是糯米，一个住在用户电脑里的桌面 AI 人格。中文回答，简洁友好。",
        tools=plugin_tools,
        skills_dir=skills_dir,
        skills_disabled=skills_disabled,
        mcp_server_configs=mcp_server_configs or {},
        mcp_default_servers=mcp_default_servers,
    )
