"""请求级线程上下文：stream 处理时设置当前 thread_id，供 fs 等插件工具读取。

背景：langchain 1.x 的 create_agent 工具执行路径不向 @tool 注入 RunnableConfig
（config 参数收到默认 None），因此改用 contextvars——agent.astream 在同一个
asyncio task 内执行，工具调用在同一 task 栈，ContextVar 可传播。
"""
from __future__ import annotations

import contextvars

current_thread_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "nuomi_current_thread_id", default=None
)


def get_thread_id() -> str | None:
    return current_thread_id.get()
