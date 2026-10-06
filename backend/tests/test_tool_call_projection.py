"""工具调用投影回归测试（turn → thread_messages 投影）。

背景：``thread_messages`` 是历史展示的加速层，一旦某线程标记 ``ready``，
``GET /chat/history`` 就只读投影（`transport/api.py`）。所以增量投影丢工具调用
= 用户看到的历史里工具步骤时有时无（首次 backfill 有、之后新增的轮次没有）。

这里锁住两个环节，缺一个这个 bug 就会回来：
1. ``stream_chat`` 在 flush 工具调用时就归档（不能等到流末尾从 pending 里取——
   TOOL_RESULT 分支每次都 clear）；
2. ``turn_to_message_inputs`` 把字符串 args 解析成 dict（LangChain 硬要求）。
"""

from __future__ import annotations

import json

import pytest
from octop_harness.protocols.langgraph import AgentEventType

from app.domain.chat.service import _normalize_tool_calls, turn_to_message_inputs

# ---------- 环节 2：turn → 投影输入 ----------


def test_string_args_are_parsed_to_dict() -> None:
    """核心回归：字符串 args 必须转 dict，否则 AIMessage 抛 ValidationError。"""
    inputs = turn_to_message_inputs(
        {
            "user": "做个动作",
            "answer": "好",
            "tool_calls": [{"id": "call_1", "name": "do_action", "args": '{"action": "bow"}'}],
        }
    )
    ai = next(i for i in inputs if i["role"] == "ai")
    wire = json.loads(ai["message_json"])
    assert wire["data"]["tool_calls"] == [
        {"id": "call_1", "name": "do_action", "args": {"action": "bow"}, "type": "tool_call"}
    ]


def test_tool_calls_survive_with_dict_args_untouched() -> None:
    inputs = turn_to_message_inputs(
        {"user": "hi", "answer": "ok", "tool_calls": [{"id": "c", "name": "t", "args": {"k": 1}}]}
    )
    wire = json.loads(next(i for i in inputs if i["role"] == "ai")["message_json"])
    assert wire["data"]["tool_calls"][0]["args"] == {"k": 1}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", {}),
        ("   ", {}),
        ("not json", {}),  # 被截断/非法的分块拼接 → 兜底空 dict，不让整轮丢
        ("[1, 2]", {}),  # 合法 JSON 但不是 dict
        ('"str"', {}),
        (None, {}),
        ({"a": 1}, {"a": 1}),
    ],
)
def test_args_fallback_never_raises(raw, expected) -> None:
    assert _normalize_tool_calls([{"id": "c", "name": "t", "args": raw}])[0]["args"] == expected


def test_entries_without_name_are_dropped() -> None:
    """name 为空的 tool_call 不是合法调用（LangChain 也要求 name）→ 丢弃而非报错。"""
    assert _normalize_tool_calls([{"id": "c", "args": "{}"}]) == []
    assert _normalize_tool_calls([{"id": "c", "name": "  ", "args": "{}"}]) == []
    assert _normalize_tool_calls(None) == []
    assert _normalize_tool_calls([None, "x", 3]) == []


def test_ai_message_still_emitted_with_only_tool_calls() -> None:
    """只有工具调用、没有正文的轮次也要落库（否则工具卡片没有宿主消息）。"""
    inputs = turn_to_message_inputs(
        {"user": "hi", "answer": "", "tool_calls": [{"id": "c", "name": "t", "args": "{}"}]}
    )
    assert [i["role"] for i in inputs] == ["human", "ai"]


# ---------- 环节 1：stream_chat 的归档时机 ----------


class _FakeAgent:
    """最小假 agent：只回放给定事件（不打模型、不联网）。"""

    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def stream(self, _request):
        for event in self._events:
            yield event


def _tool_events() -> list[dict]:
    return [
        {"type": AgentEventType.TOKEN.value, "content": "好"},
        {
            "type": AgentEventType.TOOL_CALL_CHUNK.value,
            "index": 0,
            "id": "call_abc",
            "name": "do_action",
            "args": '{"action": ',
        },
        {"type": AgentEventType.TOOL_CALL_CHUNK.value, "index": 0, "args": '"bow"}'},
        {
            "type": AgentEventType.TOOL_RESULT.value,
            "messages": [type("M", (), {"name": "do_action", "content": "ok"})()],
        },
    ]


async def _run_turn(monkeypatch, events: list[dict]) -> dict:
    import app.infra.harness.chat as chat_mod

    monkeypatch.setattr(chat_mod.manager, "get_agent", lambda *a, **k: _FakeAgent(events))
    monkeypatch.setattr(chat_mod.manager, "enrich_request", lambda req: req)
    monkeypatch.setattr(chat_mod.manager, "flush_langfuse", lambda: None)

    captured: dict = {}

    async def _on_turn(turn: dict) -> None:
        captured.update(turn)

    frames = [
        frame
        async for frame in chat_mod.stream_chat(
            "做个动作",
            "t-tool",
            agent_id="a",
            name="n",
            system_prompt="p",
            on_turn_complete=_on_turn,
        )
    ]
    captured["_frames"] = frames
    return captured


@pytest.mark.anyio
async def test_stream_chat_archives_tool_calls_before_clearing(monkeypatch) -> None:
    """TOOL_RESULT 会清空累加器 —— 工具调用必须在那一刻就归档并进 turn。"""
    turn = await _run_turn(monkeypatch, _tool_events())
    assert turn["tool_calls"] == [
        {"id": "call_abc", "name": "do_action", "args": '{"action": "bow"}'}
    ]
    # 且照常透出 tool_call / tool_result 帧
    types = [f["type"] for f in turn["_frames"]]
    assert "tool_call" in types and "tool_result" in types and types[-1] == "done"


@pytest.mark.anyio
async def test_stream_chat_keeps_pending_calls_at_stream_end(monkeypatch) -> None:
    """流在工具调用中途结束（异常/中断）：未 flush 的分块也要归档，不能丢。"""
    events = [
        {"type": AgentEventType.TOKEN.value, "content": "嗯"},
        {
            "type": AgentEventType.TOOL_CALL_CHUNK.value,
            "index": 0,
            "id": "call_z",
            "name": "set_expression",
            "args": '{"expression": "happy"}',
        },
    ]
    turn = await _run_turn(monkeypatch, events)
    assert turn["tool_calls"] == [
        {"id": "call_z", "name": "set_expression", "args": '{"expression": "happy"}'}
    ]


@pytest.mark.anyio
async def test_turn_projects_end_to_end_without_validation_error(monkeypatch) -> None:
    """端到端：stream_chat 的 turn 直接喂给 turn_to_message_inputs 不能抛错且带上工具调用。"""
    turn = await _run_turn(monkeypatch, _tool_events())
    turn.pop("_frames")
    inputs = turn_to_message_inputs(turn)
    wire = json.loads(next(i for i in inputs if i["role"] == "ai")["message_json"])
    assert wire["data"]["tool_calls"][0]["name"] == "do_action"
    assert wire["data"]["tool_calls"][0]["args"] == {"action": "bow"}
    assert any(i["role"] == "tool" for i in inputs)
