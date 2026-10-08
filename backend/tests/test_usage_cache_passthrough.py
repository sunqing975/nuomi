"""usage 事件缓存字段透传（P0：缓存经济性可观测，2026-10-08）。

锁三件事：
1. ``_translate_events`` 把 octop 归一化的 usage 全量键透传——此前只留 input/output，
   DeepSeek 的 prompt_cache_hit_tokens 被归一化成 cache_read_tokens 后会被丢弃。
2. OpenAI 兼容 SSE 的 usage chunk 按 OpenAI 线格式带 prompt_tokens_details.cached_tokens。
3. octop SSE 帧的 usage 同样带缓存命中/未命中字段。

数值为真实探针（probe_cache_fields.py，2026-10-08）第二轮 DeepSeek 实测：
input 11371 = 命中 11136 + 未命中 235。
"""

from __future__ import annotations

import asyncio
import json

from app.infra.harness.chat import _translate_events, stream_octop_sse, stream_openai_sse

_USAGE = {
    "input_tokens": 11371,
    "uncached_input_tokens": 235,
    "cache_read_tokens": 11136,
    "cache_write_tokens": 0,
    "output_tokens": 18,
    "reasoning_tokens": 16,
    "total_tokens": 11389,
}


def _collect(agen):
    return asyncio.run(_collect_async(agen))


async def _collect_async(agen):
    return [ev async for ev in agen]


async def _agen(items):
    """把合成事件列表包装成 SSE 翻译层要求的异步迭代器。"""
    for item in items:
        yield item


def test_translate_events_passes_cache_fields() -> None:
    """内部 usage 事件透传缓存命中/未命中（此前只留 input/output 两个键）。"""
    events = _collect(
        _translate_events(_agen([{"type": "usage", "usage": dict(_USAGE)}]), {"pending_tools": {}})
    )
    assert len(events) == 1
    usage = events[0]
    assert usage["type"] == "usage"
    assert usage["input_tokens"] == 11371
    assert usage["uncached_input_tokens"] == 235
    assert usage["cache_read_tokens"] == 11136
    assert usage["cache_write_tokens"] == 0
    assert usage["output_tokens"] == 18
    assert usage["reasoning_tokens"] == 16
    assert usage["total_tokens"] == 11389


def test_openai_sse_usage_chunk_carries_cached_tokens() -> None:
    """OpenAI 兼容线格式：usage chunk 带 prompt_tokens_details.cached_tokens。"""
    frames = _collect(
        stream_openai_sse(
            _agen([{"type": "usage", **_USAGE}, {"type": "done", "answer": "ok"}]),
            include_usage=True,
        )
    )
    chunk = json.loads(frames[-2].removeprefix("data: ").removesuffix("\n\n"))
    usage = chunk["usage"]
    assert usage["prompt_tokens"] == 11371
    assert usage["completion_tokens"] == 18
    assert usage["total_tokens"] == 11389
    assert usage["prompt_tokens_details"]["cached_tokens"] == 11136
    assert frames[-1] == "data: [DONE]\n\n"


def test_openai_sse_without_cache_still_emits_zero_cached() -> None:
    """没有缓存字段（非缓存 provider）时 cached_tokens 兜底为 0，不破坏兼容格式。"""
    frames = _collect(
        stream_openai_sse(
            _agen(
                [
                    {"type": "usage", "input_tokens": 5, "output_tokens": 3},
                    {"type": "done", "answer": "ok"},
                ]
            ),
            include_usage=True,
        )
    )
    chunk = json.loads(frames[-2].removeprefix("data: ").removesuffix("\n\n"))
    assert chunk["usage"]["prompt_tokens_details"]["cached_tokens"] == 0


def test_octop_sse_usage_frame_carries_cache_fields() -> None:
    """octop 原生帧：usage 负载带缓存命中/未命中字段。"""
    frames = _collect(stream_octop_sse(_agen([{"type": "usage", **_USAGE}]), thread_id="t1"))
    payload = json.loads(frames[0].removeprefix("data: ").removesuffix("\n\n"))
    assert payload["type"] == "usage"
    assert payload["thread_id"] == "t1"
    assert payload["usage"]["cache_read_tokens"] == 11136
    assert payload["usage"]["uncached_input_tokens"] == 235
