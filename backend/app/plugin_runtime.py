"""plugin_runtime.py · 插件运行时内核（移植 DeepSeek Harness / Cordis 设计）。

对齐 Cordis 的插件形态（v0.6：不再区分"程序型/能力型"——一切皆插件）：
- 插件 = 一个模块，导出 `apply(ctx)`；加载器用上下文 ctx 调用它
- ctx 是"贡献 + 服务 + 事件 + 生命周期"容器，apply(ctx) 里声明它贡献的一切：
    ctx.register_tools([...])    → 贡献模型工具（进 agent 工具集）
    ctx.register_skill(...)      → 贡献技能（SKILL.md：目录只给 name+description，正文按需读）
    ctx.provide(name, impl)      → 贡献运行时服务（其他插件 / 前端可读取）
    ctx.on(event, handler)       → 订阅事件（响应核心流程）
    ctx.effect(disposer)         → 生命周期（停用时清理）
- 启停 = 配置组合：启用时 apply(ctx)，停用时 dispose 并重建
- 事件：message_received / response_done / tool_called / plugin_toggled / model_switched / approval_created
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import BaseTool

logger = logging.getLogger("nuomi.plugin_runtime")

# --- 事件名常量（核心流程发布点） ---
MESSAGE_RECEIVED = "message_received"
RESPONSE_DONE = "response_done"
TOOL_CALLED = "tool_called"
PLUGIN_TOGGLED = "plugin_toggled"
MODEL_SWITCHED = "model_switched"
APPROVAL_CREATED = "approval_created"


@dataclass
class SkillContribution:
    """插件贡献的技能（对齐 Harness SkillSummary/Definition：摘要常驻、正文按需）。"""

    name: str
    description: str
    when_to_use: str = ""
    body: str = ""


class EventBus:
    """事件总线：subscribe / publish。处理器异常只记日志，不影响主流程。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, handler: Callable) -> Callable:
        self._handlers[event].append(handler)

        def _unsubscribe() -> None:
            try:
                self._handlers[event].remove(handler)
            except ValueError:
                pass

        return _unsubscribe

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> None:
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(payload or {})
            except Exception:
                logger.exception("event handler failed: %s", event)


class PluginContext:
    """插件上下文（Python 版 Cordis Context）：声明贡献 / 注册服务 / 订阅事件 / 生命周期。

    插件通过它声明自己贡献的一切（工具/技能/服务/事件）；插件被停用时 effects 全部执行。
    """

    def __init__(self, app) -> None:
        self.app = app
        self.bus: EventBus = app.state.event_bus
        self.services: dict[str, Any] = {}
        self.effects: list[Callable] = []
        self.tools: list[BaseTool] = []
        self.skills: dict[str, SkillContribution] = {}
        self.events: list[str] = []  # 订阅过的事件名（贡献视图用）

    # --- 贡献：模型工具 ---
    def register_tools(self, tools: list[BaseTool]) -> None:
        for t in tools:
            if t not in self.tools:
                self.tools.append(t)

    # --- 贡献：技能（SKILL.md：目录只给 name+description，正文按需） ---
    def register_skill(self, skill: SkillContribution) -> None:
        self.skills[skill.name] = skill

    # --- 贡献：运行时服务（其他插件 / 前端经 app.state.services[name] 读取） ---
    def provide(self, name: str, impl: Any) -> None:
        self.services[name] = impl
        self.app.state.services[name] = impl

    def service(self, name: str) -> Any | None:
        return self.app.state.services.get(name)

    # --- 事件订阅 ---
    def on(self, event: str, handler: Callable) -> None:
        if event not in self.events:
            self.events.append(event)
        self.effects.append(self.bus.subscribe(event, handler))

    # --- 生命周期 ---
    def effect(self, disposer: Callable) -> None:
        self.effects.append(disposer)

    def dispose(self) -> None:
        for disposer in reversed(self.effects):
            try:
                disposer()
            except Exception:
                logger.exception("effect disposer failed")


def create_event_bus() -> EventBus:
    return EventBus()
