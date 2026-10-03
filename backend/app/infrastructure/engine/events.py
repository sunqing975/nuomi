"""core/events.py · 事件分发 5 模式（对齐 Cordis）。

| 模式     | 调用                          | 语义                                                       |
|---------|-------------------------------|-----------------------------------------------------------|
| emit    | bus.emit(name, **payload)     | 同步广播，不收集返回值                                      |
| parallel| await bus.parallel(name, **p) | 所有监听器并发运行并一起等待                                |
| serial  | await bus.serial(name, **p)   | 顺序运行；首个非 None/False 的返回值胜出并停止后续           |
| bail    | bus.bail(name, **p)           | serial 的同步版本                                          |
| waterfall| await bus.waterfall(name, payload, default) | 环绕中间件：监听器可转换 next() 返回值或短路（不调 next()） |

事件命名约定 namespace/action（如 plugin/toggled、agent/pre-step、response/done）。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger("nuomi.core.events")

Handler = Callable[..., Any]


class EventBus:
    """线程安全的事件总线（5 种分发模式）。监听器异常隔离：记日志不阻断主流程。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    # --- 注册（返回 disposer） ---
    def on(self, event: str, handler: Handler) -> Callable:
        """新式监听器：handler(**payload)。"""
        self._handlers[event].append(handler)

        def _off() -> None:
            with suppress(ValueError):
                self._handlers[event].remove(handler)

        return _off

    def subscribe(self, event: str, handler: Handler) -> Callable:
        """旧式兼容：handler(payload: dict)（v0.5/v0.6 插件与发布点）。"""

        def _adapter(**payload: Any) -> Any:
            return handler(payload)

        self._handlers[event].append(_adapter)

        def _off() -> None:
            with suppress(ValueError):
                self._handlers[event].remove(_adapter)

        return _off

    def publish(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """旧式发布点兼容：publish('event', {'k': v}) == emit('event', k=v)。"""
        self.emit(event, **(payload or {}))

    def off(self, event: str, handler: Handler) -> None:
        with suppress(ValueError):
            self._handlers[event].remove(handler)

    def listeners(self, event: str) -> list[Handler]:
        return list(self._handlers.get(event, []))

    # --- emit：同步广播（Fire-and-forget，不收集返回值） ---
    def emit(self, event: str, **payload: Any) -> None:
        for h in self.listeners(event):
            try:
                h(**payload)
            except Exception:
                logger.exception("event handler failed: %s", event)

    # --- parallel：并发等待所有监听器 ---
    async def parallel(self, event: str, **payload: Any) -> list[Any]:
        results: list[Any] = []
        coros = []
        for h in self.listeners(event):
            try:
                r = h(**payload)
            except Exception as e:
                logger.exception("event handler failed: %s", event)
                results.append(e)
                continue
            if asyncio.iscoroutine(r) or isinstance(r, Awaitable):
                coros.append(r)
            else:
                results.append(r)
        if coros:
            results.extend(await asyncio.gather(*coros, return_exceptions=True))
        return results

    # --- serial：顺序等待，首个非空返回值胜出并短路 ---
    async def serial(self, event: str, **payload: Any) -> Any | None:
        for h in self.listeners(event):
            try:
                r = h(**payload)
                if asyncio.iscoroutine(r) or isinstance(r, Awaitable):
                    r = await r
            except Exception:
                logger.exception("event handler failed: %s", event)
                continue
            if r not in (None, False):
                return r
        return None

    # --- bail：serial 的同步版本 ---
    def bail(self, event: str, **payload: Any) -> Any | None:
        for h in self.listeners(event):
            try:
                r = h(**payload)
            except Exception:
                logger.exception("event handler failed: %s", event)
                continue
            if r not in (None, False):
                return r
        return None

    # --- waterfall：环绕中间件（可转换 / 可短路否决） ---
    async def waterfall(
        self, event: str, payload: Any, default: Callable[[], Awaitable[Any] | Any]
    ) -> Any:
        """监听器签名：handler(payload, next)。next 调用下游（其他监听器或 default）。

        监听器必须调用 next() 委托下去；不调用 = 有意短路（返回自身结果）。
        适合拦截/装饰：记忆注入、审批策略、模型调用替换等。
        """
        chain = list(self.listeners(event))

        async def _invoke(index: int, value: Any) -> Any:
            if index >= len(chain):
                r = default()
                if asyncio.iscoroutine(r) or isinstance(r, Awaitable):
                    r = await r
                return r
            h = chain[index]
            try:
                r = h(value, lambda: _invoke(index + 1, value))
                if asyncio.iscoroutine(r) or isinstance(r, Awaitable):
                    r = await r
                return r
            except Exception:
                logger.exception("waterfall handler failed: %s", event)
                return await _invoke(index + 1, value)

        return await _invoke(0, payload)
