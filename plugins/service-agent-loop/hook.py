"""service-agent-loop · ctx.agents 注册表 + ctx.agentLoop 驱动器（Seam Provider）。

agentLoop 消费 llm / tools / sessions / systemPrompt / memory 服务，构建 LangGraph
agent（NuomiMiddleware 每轮注入人设+记忆+摘要）；team 插件启用时构建 Supervisor。
settings/changed 或插件启停变化 → rebuild_all()（幂等，热更新）。
"""
from __future__ import annotations

from app.agent.graph import build_graph
from app.plugins.approval import get_gate
from app.agent.middleware import NuomiMiddleware
from app.plugins.lifecycle import build_skill_tool
from app.plugins.robust import apply_robust
from app.agent.supervisor import build_supervisor


def _collect_tools_from_fibers(ctx):
    """从 ACTIVE fiber 汇总工具（fiber.ctx.tools），按 plugin.json robust/approval 包装
    （V3 取代 V2 collect_tools：descriptor 在 composer 下不持有工具）。"""
    from app.core import FiberState

    reg = ctx.app.state.registry
    out: list = []
    for f in reg.fibers.values():
        if f.state != FiberState.ACTIVE or f.ctx is None:
            continue
        robust = (f.meta or {}).get("robust") or {}
        approval_names = set((f.meta or {}).get("approval") or [])
        gate = get_gate()
        for t in f.ctx.tools:
            wrapped = apply_robust(t, robust)
            if t.name in approval_names:
                gate.register_tools([wrapped])
                wrapped = gate.wrap(wrapped)
            out.append(wrapped)
    return out


class AgentLoop:
    def __init__(self, ctx):
        self.ctx = ctx
        self.agent = None
        self.supervisor = None
        self.subagents = {}
        self.middleware = None

    # --- 状态 ---
    def _enabled(self) -> set[str]:
        from app.core import FiberState

        reg = self.ctx.app.state.registry
        return {f.name for f in reg.fibers.values() if f.state == FiberState.ACTIVE}

    def _tune(self):
        settings_svc = self.ctx.get("settings")
        if settings_svc:
            return (
                settings_svc["store"].get("summarize_max_messages", 24),
                settings_svc["store"].get("summarize_keep_recent", 8),
            )
        return 24, 8

    # --- 构建（幂等） ---
    def build_all(self):
        app = self.ctx.app
        llm = self.ctx.get("llm")
        if llm is None:
            return None
        saver = self.ctx.get("sessions")["checkpointer"]()
        sp = self.ctx.get("systemPrompt")
        memory = self.ctx.get("memory")
        enabled = self._enabled()

        tools = _collect_tools_from_fibers(self.ctx)
        skill_tool = build_skill_tool(app.state.plugins, enabled_getter=lambda: enabled)
        if skill_tool not in tools:
            tools = [skill_tool, *tools]

        max_msgs, keep_recent = self._tune()
        self.middleware = NuomiMiddleware(
            prompt_builder=sp["build"],
            memory=memory,
            llm=llm,
            max_messages=max_msgs,
            keep_recent=keep_recent,
        )
        self.agent = build_graph(
            llm=llm, tools=tools, checkpointer=saver,
            system_prompt=None, middleware=[self.middleware],
        )

        if "team" in enabled:
            self.supervisor, self.subagents = build_supervisor(
                llm=llm, tools=tools, checkpointer=saver
            )
        else:
            self.supervisor = None
            self.subagents = {}

        # 同步到 app.state（V2 API/测试兼容读点）
        app.state.agent = self.agent
        app.state.supervisor = self.supervisor
        app.state.subagents = self.subagents
        app.state.tools = tools
        return tools

    # --- 对话驱动器 ---
    def resolve(self, use_team=None):
        """返回 (agent, stream_mode)：team 启用走 Supervisor（updates），否则单 Agent（messages）。"""
        if use_team is None:
            use_team = self.supervisor is not None
        agent = self.supervisor if use_team else self.agent
        return agent, "updates" if use_team else "messages"

    async def astream(self, messages, config, use_team=None):
        return self.resolve(use_team)


def apply(ctx):
    agents = {"presets": {}, "supervisor": None}
    ctx.provide("agents", agents)
    loop = AgentLoop(ctx)
    ctx.provide("agentLoop", loop)

    def _rebuild(payload=None):
        try:
            tools = loop.build_all()
            agents["supervisor"] = loop.supervisor
            if tools is not None:
                ctx.emit("agents/rebuild", tools=[t.name for t in tools], team=loop.supervisor is not None)
        except Exception as e:  # 依赖尚不齐（llm 未就绪等）：保持 PENDING 语义由 reconcile 重试
            ctx.emit("agents/rebuild", error=str(e))

    ctx.on("settings/changed", _rebuild)
    ctx.on("plugin/toggled", _rebuild)
    ctx.on("plugins/loaded", _rebuild)
    # 插件启停也走旧事件名（v0.6 兼容）
    ctx.on("plugin_toggled", _rebuild)

    # llm 切换后重建（提供方已重新 provide 新实例）
    def _on_llm_switched(payload):
        _rebuild(None)

    ctx.on("llm/switched", _on_llm_switched)

    # 首次构建（inject 服务齐备时本插件才 ACTIVE，此处 llm/tools/sessions 已就绪）
    _rebuild(None)
