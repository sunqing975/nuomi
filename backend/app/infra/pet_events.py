"""桌宠动作事件总线：任意来源的对话产生工具调用时广播，桌宠壳长连接订阅播放。

控制台/壳/任何端发起的对话，只要触发模型插件工具（动作/表情），
都会经此总线推给桌宠壳播放——桌宠视觉与对话来源解耦。
"""
from __future__ import annotations

import asyncio


class PetEventBus:
    """内存广播（asyncio 队列）：publish 投递到全部订阅连接。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def publish(self, name: str) -> None:
        """广播一个工具调用事件（工具名 = 动作/表情名）。"""
        payload = {"type": "tool_call", "name": name}
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def stream(self):
        """SSE 生成器：注册订阅队列，持续产出事件（连接断开自动注销）。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)


pet_events = PetEventBus()
