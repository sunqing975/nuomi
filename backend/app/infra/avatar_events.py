"""AI 数字人动作事件总线：任意来源的对话产生工具调用时广播，AI 数字人壳长连接订阅播放。

控制台/壳/任何端发起的对话，只要触发模型插件工具（动作/表情），
都会经此总线推给AI 数字人壳播放——AI 数字人视觉与对话来源解耦。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress


class PetEventBus:
    """内存广播（asyncio 队列）：publish 投递到全部订阅连接。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def publish(self, payload: dict) -> None:
        """广播一个AI 数字人动作事件。

        payload 形如 {"motion": "main_1", "expressions": ["happy"], "label": "挥手"}，
        壳据此同时播动作和表情（原子组合）。
        """
        envelope = {"type": "avatar_action", **payload}
        for q in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                q.put_nowait(envelope)

    def publish_raw(self, payload: dict) -> None:
        """原样广播（不强制 type）：资源管理类事件（如 avatar_animations_changed，壳收到后刷新页面）。"""
        for q in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    def publish_status(self, status: str) -> None:
        """广播一个状态事件：thinking / working / idle。

        壳据此自动切表情（LLM 思考中→思考脸，工具执行中→忙碌脸，回复完→恢复）。
        """
        envelope = {"type": "avatar_status", "status": status}
        for q in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                q.put_nowait(envelope)

    async def stream(self):
        """SSE 生成器：注册订阅队列，持续产出事件（连接断开自动注销）。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)


avatar_events = PetEventBus()
