"""AI 数字人动作事件总线：任意来源的对话产生工具调用时广播，AI 数字人壳长连接订阅播放。

控制台/壳/任何端发起的对话，只要触发模型插件工具（动作/表情），
都会经此总线推给AI 数字人壳播放——AI 数字人视觉与对话来源解耦。

两个曾经的坑（2026-10-06 修）：

1. **队列满时静默丢最新事件**：原实现 ``with suppress(asyncio.QueueFull): put_nowait(...)``
   —— 队列一满，新事件直接丢掉且**没有任何日志**，表现为"数字人偶尔不动"，排查时无迹可寻。
   动作/状态是**最新有效**的语义，所以队列满应丢**最旧**的，并记录丢弃计数（首次 + 每 100 次
   打日志，避免刷屏）。
2. **长连接无心跳**：SSE 只在有事件时写数据，中间设备/浏览器会把长时间安静的连接判为空闲断开。
   ``stream(keepalive=N)`` 在空闲 N 秒后产出 ``None`` 占位，由传输层翻译成 SSE 注释帧。
   心跳的 ``wait_for`` 放在**生成器内部**（不是外面），否则超时取消会顺着 ``await q.get()``
   抛进生成器把它终结掉。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress

logger = logging.getLogger(__name__)

# 单订阅者缓冲上限：数字人只需要"最近的动作"，堆积无意义
QUEUE_MAXSIZE = 128


class PetEventBus:
    """内存广播（asyncio 队列）：publish 投递到全部订阅连接。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._dropped = 0

    # ---------- 广播 ----------

    def _offer(self, queue: asyncio.Queue, payload: dict) -> None:
        """投递一条；队列满则丢最旧的（保新），并计数 + 限频告警。"""
        try:
            queue.put_nowait(payload)
            return
        except asyncio.QueueFull:
            pass
        # 满：丢最旧，再塞新的（丢新会让"当前动作"被 128 条旧事件压在后面）
        with suppress(asyncio.QueueEmpty):
            queue.get_nowait()
        with suppress(asyncio.QueueFull):
            queue.put_nowait(payload)
        self._dropped += 1
        if self._dropped == 1 or self._dropped % 100 == 0:
            logger.warning(
                "数字人事件队列已满，丢弃最旧事件（累计 %d 次）——订阅端可能卡住或过慢",
                self._dropped,
            )

    def _broadcast(self, payload: dict) -> None:
        for queue in list(self._subscribers):
            self._offer(queue, payload)

    def publish(self, payload: dict) -> None:
        """广播一个AI 数字人动作事件。

        payload 形如 {"motion": "main_1", "expressions": ["happy"], "label": "挥手"}，
        壳据此同时播动作和表情（原子组合）。
        """
        self._broadcast({"type": "avatar_action", **payload})

    def publish_raw(self, payload: dict) -> None:
        """原样广播（不强制 type）：资源管理类事件（如 avatar_animations_changed，壳收到后刷新页面）。"""
        self._broadcast(payload)

    def publish_status(self, status: str) -> None:
        """广播一个状态事件：thinking / working / idle。

        壳据此自动切表情（LLM 思考中→思考脸，工具执行中→忙碌脸，回复完→恢复）。
        """
        self._broadcast({"type": "avatar_status", "status": status})

    # ---------- 订阅 ----------

    @property
    def dropped_events(self) -> int:
        """累计丢弃事件数（供诊断/测试观察）。"""
        return self._dropped

    async def stream(self, keepalive: float | None = None) -> AsyncIterator[dict | None]:
        """SSE 生成器：注册订阅队列，持续产出事件（连接断开自动注销）。

        ``keepalive`` 秒内没有事件时产出 ``None``（心跳占位，由传输层写成 SSE 注释帧）。
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        try:
            while True:
                if keepalive is None:
                    yield await queue.get()
                    continue
                try:
                    # wait_for 必须在生成器**内部**：放外面的话，超时取消会通过
                    # `await queue.get()` 抛进生成器，把它连带终结掉（长连接就断了）
                    yield await asyncio.wait_for(queue.get(), timeout=keepalive)
                except TimeoutError:
                    yield None
        finally:
            self._subscribers.discard(queue)


avatar_events = PetEventBus()
