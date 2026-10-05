"""事件总线（对齐 dsh/Cordis 的极薄版本）：广播站 + 事件枚举。

- 事件名由框架（本模块）预先定义，是唯一的契约源；
- 任何代码可以 ``emit``（广播），任何插件可以 ``on``（订阅）；
- 订阅者异常被隔离，不影响广播方；
- 插件在 ``setup(ctx)`` 里通过 ``event_bus.on(...)`` 报名订阅。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Events:
    """对话生命周期事件（广播站公告清单）。有订阅者才加，别铺一堆。"""

    conversation_started = "conversation.started"
    conversation_completed = "conversation.completed"


class EventBus:
    """极薄广播站：dict[event -> handlers]，emit 时依次调用。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        """订阅一个事件（插件 setup 时调用；不校验事件名，保持极简）。"""
        self._handlers[event].append(handler)

    def emit(self, event: str, **payload: Any) -> None:
        """广播事件；单个订阅者抛错不影响其它订阅者与广播方。"""
        for handler in list(self._handlers.get(event, [])):
            try:
                handler(payload)
            except Exception:
                logger.exception("事件订阅者异常: %s", event)


# 全局单例（模块级）：对话流 emit、插件 on 都引用它
event_bus = EventBus()
