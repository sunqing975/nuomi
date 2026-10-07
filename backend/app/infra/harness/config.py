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
        models = [
            ModelConfig(id=m["id"], name=m.get("name") or m["id"])
            for m in (p.get("models") or [])
            if m.get("id")
        ]
        out.append(
            ProviderConfig(
                id=p["id"],
                base_url=p.get("base_url") or "",
                api_key=p.get("api_key") or "",
                protocol=p.get("protocol") or "openai",
                models=models,
            )
        )
    return out


# 工具护栏默认规则目录：仓库 connectors/rules（mes 写操作审批规则；不启用内置 shell 规则）
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_TOOL_GUARD_RULES_DIR = _REPO_ROOT / "connectors" / "rules"


def configure_harness_logging() -> Path:
    """把 octop-harness 的文件日志收进数据根（``{NUOMI_HOME}/logs/octop-harness``）。

    harness 默认写 ``~/.octop-harness/logs``——在 NUOMI_HOME 之外，破坏「单一数据根」
    的可迁移性；隔离数据根的测试还会因此越界写用户 HOME（无权限时直接 PermissionError）。
    harness 的 ``ensure_logging()`` 见到已有同包 handler 就复用，所以**必须在首次
    构造 HarnessAgent 之前调用一次**（main lifespan 里已接线）。
    """
    from octop_harness.observability.logging import setup_logging

    return setup_logging(settings.data_root / "logs" / "octop-harness")


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
    tool_guard_enabled: bool = True,
    tool_guard_mode: str = "require_approval",
    tool_guard_rules_dir: str | Path | None = None,
) -> HarnessAgentConfig:
    """构造单个 Agent 的运行时配置（工作区按 harness init_workspace 布局）。

    model_ref 使用 "provider/model" 复合串（Octop resolve_explicit_default_model 形态）。
    模型不绑专家（2026-10-04）：默认模型 = providers[0] 的 models[0]；
    对话时由 ChatRequest.model per-turn 覆盖（harness 原生优先于 default_model）。
    plugin_tools：插件注册的工具（build_plugin_tools 结果），经 cfg.tools 注入 agent。
    知识库启用时（KNOWLEDGE_EMBEDDING_ENABLED=true）额外注入 search_knowledge 工具
    与 KnowledgeSearchHintMiddleware（每轮改写工具描述；无选中库时隐藏工具）。
    skills_dir / skills_disabled：自定义技能目录与禁用集合。
    mcp_server_configs / mcp_default_servers：MCP 服务器（对话请求经 mcp_use_default 启用）。
    tool_guard_enabled / mode / rules_dir：工具调用护栏。mode="require_approval" 时，
    命中 connectors/rules 审批规则的写工具（mes_submit_work_report）暂停等人工审批（HITL）。
    """
    init_workspace(workspace_dir, language="zh", include_md_files=False, include_skills=True)
    providers = build_providers()
    default_model = None
    if providers and providers[0].models:
        default_model = f"{providers[0].id}/{providers[0].models[0].id}"
    tools, middleware = _knowledge_capabilities(plugin_tools)
    resolved_rules_dir = tool_guard_rules_dir or _DEFAULT_TOOL_GUARD_RULES_DIR
    return HarnessAgentConfig(
        name=name,
        workspace_dir=workspace_dir,
        providers=providers,
        default_model=default_model or f"llm/{settings.llm_model}",
        system_prompt=system_prompt
        or "你是糯米，一个住在用户电脑里的桌面 AI 人格。中文回答，简洁友好。",
        tools=tools,
        middleware=middleware,
        skills_dir=skills_dir,
        skills_disabled=skills_disabled,
        mcp_server_configs=mcp_server_configs or {},
        mcp_default_servers=mcp_default_servers,
        tool_guard_enabled=tool_guard_enabled,
        tool_guard_mode=tool_guard_mode,
        tool_guard_rules_dir=resolved_rules_dir,
    )


def _knowledge_capabilities(
    plugin_tools: list | None,
) -> tuple[list | None, list | None]:
    """知识库启用时挂载检索工具与提示中间件（未启用不挂，避免无谓开销）。"""
    from app.infra.knowledge.hint import KnowledgeSearchHintMiddleware
    from app.infra.knowledge.onnx_service import load_config
    from app.infra.knowledge.tools import build_knowledge_tools

    if not load_config().enabled:
        return plugin_tools, None
    tools = list(plugin_tools or [])
    tools.extend(build_knowledge_tools())
    return tools, [KnowledgeSearchHintMiddleware()]
