"""team · 程序型插件（type: program）：智能体团队（Harness 形态）。

apply(ctx) 注册团队运行时：确保 Supervisor（companion + researcher + LLM 路由）存在，
订阅 PLUGIN_TOGGLED 事件挂/卸。停用后 /api/chat 自动退化为单 Agent——前端无感。
"""
from app.plugins.runtime import PLUGIN_TOGGLED


def apply(ctx) -> None:
    ctx.app.state.team_enabled = True
    # 不在 apply 时构建 Supervisor：rebuild_agents() 按 enabled 统一构建（避免空工具集浪费）

    def _on_toggle(payload) -> None:
        if payload.get("plugin") == "team":
            if payload.get("enabled"):
                _ensure_supervisor(ctx.app)
                ctx.app.state.team_enabled = True
            else:
                ctx.app.state.supervisor = None
                ctx.app.state.subagents = {}
                ctx.app.state.team_enabled = False

    ctx.on(PLUGIN_TOGGLED, _on_toggle)


def _ensure_supervisor(app) -> None:
    """确保 Supervisor 存在（rebuild 已按 enabled 构建时幂等跳过）。"""
    if getattr(app.state, "supervisor", None) is not None:
        return
    from app.agent.supervisor import build_supervisor

    app.state.supervisor, app.state.subagents = build_supervisor(
        llm=app.state.llm_cfg,
        tools=app.state.tools,
        checkpointer=app.state.checkpointer,
    )
