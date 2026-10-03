"""Phase 3 · 工具健壮性：重试 / 超时 / fallback。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from app.infrastructure.engine.robust import RetryError, with_fallback, with_retry, with_timeout
from langchain_core.tools import tool

REPO_ROOT = Path(__file__).resolve().parents[2]
_state = {"flaky_calls": 0}


@tool
def _flaky(n: int, fail_times: int = 1) -> int:
    """模拟瞬时错误：前 fail_times 次抛 OSError，之后返回 n。"""
    _state["flaky_calls"] += 1
    if _state["flaky_calls"] <= fail_times:
        raise OSError("temporary")
    return n


@tool
def _slow(x: int) -> int:
    """慢工具：固定睡 1.5 秒，用于超时测试。"""
    import time

    time.sleep(1.5)
    return x


@tool
def _always_fail(x: int) -> int:
    """永远失败的工具，用于 fallback 测试。"""
    raise RuntimeError("boom")


@tool
def _backup(x: int) -> int:
    """备选工具：返回相反数。"""
    return -x


def test_retry_succeeds_after_transient_failures():
    _state["flaky_calls"] = 0
    t = with_retry(_flaky, retries=3)
    assert t.invoke({"n": 42, "fail_times": 2}) == 42
    assert _state["flaky_calls"] == 3


def test_retry_exhausts_raises():
    _state["flaky_calls"] = 0
    t = with_retry(_flaky, retries=1)
    with pytest.raises(RetryError):
        t.invoke({"n": 42, "fail_times": 5})


def test_timeout_aborts_slow_tool():
    t = with_timeout(_slow, seconds=0.3)
    with pytest.raises(asyncio.TimeoutError):
        t.invoke({"x": 1})


def test_fallback_on_error():
    t = with_fallback(_always_fail, _backup)
    assert t.invoke({"x": 7}) == -7


def test_fallback_text():
    t = with_fallback(_always_fail, "该能力暂不可用")
    r = t.invoke({"x": 1})
    assert "暂不可用" in r and "RuntimeError" in r
