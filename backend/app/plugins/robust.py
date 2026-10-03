"""工具健壮性包装（Phase 3）：重试 / 超时 / fallback。

LangChain BaseTool 装饰器组合：
  - with_timeout(tool, seconds)   调用超时（同步工具放线程池执行并限时）
  - with_retry(tool, retries, backoff)  瞬时错误指数退避重试
  - with_fallback(tool, fallback, on)  失败时降级到备选工具/消息

设计：纯组合式包装（不改工具内部），在插件加载器 collect_tools 时按
plugin.json 的 robust 配置应用——"工具失败怎么办"从每个工具内部抽到统一层。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

# 视为"瞬时错误"、值得重试的异常类型（网络/服务端 5xx/超时）
_TRANSIENT = (TimeoutError, ConnectionError, OSError)


class RetryError(RuntimeError):
    """多次重试后仍失败。"""


def with_timeout(tool: BaseTool, seconds: float = 30.0) -> BaseTool:
    """给工具加调用超时（async 路径 asyncio.wait_for；sync 路径包进线程池）。"""

    async def _arun(**kwargs) -> Any:
        return await asyncio.wait_for(tool.ainvoke(kwargs), timeout=seconds)

    def _run(**kwargs) -> Any:
        return asyncio.run(_arun(**kwargs))

    return StructuredTool.from_function(
        coroutine=_arun,
        func=_run,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def with_retry(tool: BaseTool, retries: int = 2, backoff: float = 0.5) -> BaseTool:
    """瞬时错误指数退避重试。重试耗尽抛 RetryError（可由 fallback 层兜住）。"""

    async def _arun(**kwargs) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await tool.ainvoke(kwargs)
            except _TRANSIENT as e:
                last = e
                if attempt < retries:
                    await asyncio.sleep(backoff * (2**attempt))
        assert last is not None
        raise RetryError(f"{tool.name} 重试 {retries} 次仍失败: {last}") from last

    def _run(**kwargs) -> Any:
        return asyncio.run(_arun(**kwargs))

    return StructuredTool.from_function(
        coroutine=_arun,
        func=_run,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def with_fallback(tool: BaseTool, fallback: BaseTool | str) -> BaseTool:
    """失败时降级：另一工具，或一段兜底提示文本。"""

    async def _arun(**kwargs) -> Any:
        try:
            return await tool.ainvoke(kwargs)
        except Exception as e:
            if isinstance(fallback, BaseTool):
                return await fallback.ainvoke(kwargs)
            return f"{fallback}（原工具失败：{e.__class__.__name__}）"

    def _run(**kwargs) -> Any:
        return asyncio.run(_arun(**kwargs))

    return StructuredTool.from_function(
        coroutine=_arun,
        func=_run,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


def apply_robust(tool: BaseTool, cfg: dict | None) -> BaseTool:
    """按 plugin.json 的 robust 配置依次包装（fallback → retry → timeout 由外向内）。"""
    cfg = cfg or {}
    out = tool
    if cfg.get("timeout"):
        out = with_timeout(out, float(cfg["timeout"]))
    if cfg.get("retries"):
        out = with_retry(out, retries=int(cfg["retries"]))
    if cfg.get("fallback"):
        out = with_fallback(out, str(cfg["fallback"]))
    return out
