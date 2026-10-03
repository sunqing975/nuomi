"""core/context.py · PluginContext v3（Python 版 Cordis Context）。

插件 = 模块导出 `apply(ctx)`；ctx 是"贡献 + 服务 + 事件 + 生命周期"容器：
- 依赖声明：模块导出 `inject = ['llm', 'tools']` 或 apply 内 `ctx.inject([...])`
  → 服务未就绪时插件停在 PENDING（不执行 apply），就绪后自动启动
- 服务注册：ctx.provide(name, impl)（Seam Provider）；ctx.service(name)/ctx.get(name) 消费
- 事件：ctx.on / ctx.emit / ctx.parallel / ctx.serial / ctx.bail / ctx.waterfall（5 种分发）
- 生命周期：ctx.effect(disposer)；停用时逆序清理
- 贡献：ctx.register_tools / ctx.register_skill（与 v0.6 兼容）
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import BaseTool

from .events import EventBus
from .skill import SkillContribution

logger = logging.getLogger("nuomi.core.context")


class PluginContext:
    def __init__(self, app, bus: EventBus, scope) -> None:
        self.app = app
        self.bus = bus
        self.scope = scope  # 分层服务注册表（Scope 实例）
        self.config: dict[str, Any] = {}  # 组合配置注入（profile entry 的 config）
        self.effects: list[Callable] = []
        self.tools: list[BaseTool] = []
        self.skills: dict[str, SkillContribution] = {}
        self.events: list[str] = []  # 订阅过的事件名（贡献视图）
        self.inject_decls: list[str] = []  # 声明需要的服务名

    # --- 依赖声明 ---
    def inject(self, services: list[str]) -> None:
        for s in services:
            if s not in self.inject_decls:
                self.inject_decls.append(s)

    def missing_services(self) -> list[str]:
        return [s for s in self.inject_decls if self.scope.get(s) is None]

    # --- 服务注册（Seam Provider） / 消费 ---
    def provide(self, name: str, impl: Any) -> None:
        self.scope.register(name, impl, owner=self)
        # v0.6 兼容：app.state.services 是旧读点（前端/旧插件经此取服务）
        if hasattr(self.app, "state") and hasattr(self.app.state, "services"):
            self.app.state.services[name] = impl

    def service(self, name: str) -> Any | None:
        return self.scope.get(name) or (
            getattr(self.app.state, "services", {}).get(name)
            if hasattr(self.app, "state")
            else None
        )

    # 可选依赖探测：不存在返回 None（与 inject 硬依赖互补）
    def get(self, name: str) -> Any | None:
        return self.service(name)

    # --- 事件（5 种分发） ---
    def on(self, event: str, handler: Callable) -> None:
        """订阅事件。handler 签名：handler(payload: dict)（与 v0.6 插件兼容；
        v3 新监听器若要 **kwargs，请直接使用 self.bus.on）。"""
        if event not in self.events:
            self.events.append(event)
        self.effects.append(self.bus.subscribe(event, handler))

    def on_kwargs(self, event: str, handler: Callable) -> None:
        """新式监听器：handler(**payload)。"""
        if event not in self.events:
            self.events.append(event)
        self.effects.append(self.bus.on(event, handler))

    def emit(self, event: str, **payload: Any) -> None:
        self.bus.emit(event, **payload)

    async def parallel(self, event: str, **payload: Any) -> list[Any]:
        return await self.bus.parallel(event, **payload)

    async def serial(self, event: str, **payload: Any) -> Any | None:
        return await self.bus.serial(event, **payload)

    def bail(self, event: str, **payload: Any) -> Any | None:
        return self.bus.bail(event, **payload)

    async def waterfall(
        self, event: str, payload: Any, default: Callable[[], Awaitable[Any] | Any]
    ) -> Any:
        return await self.bus.waterfall(event, payload, default)

    # --- 贡献：模型工具 / 技能 ---
    def register_tools(self, tools: list[BaseTool]) -> None:
        for t in tools:
            if t not in self.tools:
                self.tools.append(t)

    def register_skill(self, skill: SkillContribution) -> None:
        self.skills[skill.name] = skill

    # --- 生命周期 ---
    def effect(self, disposer: Callable) -> None:
        self.effects.append(disposer)

    def dispose(self) -> None:
        for disposer in reversed(self.effects):
            try:
                disposer()
            except Exception:
                logger.exception("effect disposer failed")
        self.effects.clear()
