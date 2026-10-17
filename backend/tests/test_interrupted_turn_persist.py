"""断连中断的轮次也要落库（切页刷新 / 关窗口不该把这一问一答一起丢掉）。

背景（2026-10-16 用户报障）：发完消息、模型还在生成时切到别的页面再回来，会话还在
但刚才那一问一答全没了。根因是后端只在**整轮跑完**时才把 turn 交给投影
（``stream_chat`` 的 ``on_turn_complete``），客户端断连把生成器关掉就什么都不写。

修法：``stream_chat``/``resume_chat`` 在没跑完就退出（GeneratorExit / 本轮异常）时，
把已生成的部分打上 ``interrupted`` 交给投影；``write_turn_projection`` 负责在
「投影还没 backfill」的新会话上先回填再补写，避免被下一次全量 backfill 覆盖。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage


class _FakeAgent:
    """只产出几个 token 的假 agent（stream_chat 拿它当 harness 运行时）。"""

    def __init__(self, chunks: tuple[str, ...]) -> None:
        self.chunks = chunks

    async def stream(self, request):  # noqa: ANN001, ANN201 - 贴合 harness 协议，不需要类型
        for chunk in self.chunks:
            yield {"type": "token", "content": chunk}


@pytest.mark.anyio
async def test_stream_chat_archives_partial_when_closed(monkeypatch) -> None:
    """客户端断连 = 生成器被 aclose：已生成的半截要交给 on_turn_complete 落库。"""
    import app.infra.harness.chat as chat_mod

    monkeypatch.setattr(
        chat_mod.manager, "get_agent", lambda *a, **k: _FakeAgent(("半截", "回", "复"))
    )
    monkeypatch.setattr(chat_mod.manager, "enrich_request", lambda req: req)
    monkeypatch.setattr(chat_mod.manager, "flush_langfuse", lambda: None)
    captured: dict = {}

    async def _on_turn(turn: dict) -> None:
        captured.update(turn)

    gen = chat_mod.stream_chat(
        "在吗",
        "thread-interrupted-1",
        agent_id="agent-x",
        name="测试",
        system_prompt="",
        on_turn_complete=_on_turn,
    )
    for _ in range(3):
        await gen.__anext__()
    await gen.aclose()  # 就是 chat_api 里 aclosing(frames) 在客户端断连时做的事

    assert captured["interrupted"] is True
    assert captured["user"] == "在吗"
    assert captured["answer"] == "半截回复"


@pytest.mark.anyio
@pytest.mark.anyio
async def test_close_through_sse_wrappers_still_archives(monkeypatch) -> None:
    """回归：断连关的是**最外层** SSE 翻译器，GeneratorExit 不会自动穿透。

    曾经这里只在 stream_chat 自己身上测过 aclose，于是「关最外层」的线上路径
    （``stream_octop_sse(_publish_actions(stream_chat(...)))``）根本没把半截落库：
    真正的 bug 就在这一层。现在 chat_api 在 finally 里显式 aclose 生产者。
    """
    import app.infra.harness.chat as chat_mod
    from app.transport.chat_api import _publish_actions

    monkeypatch.setattr(
        chat_mod.manager, "get_agent", lambda *a, **k: _FakeAgent(("半截", "回", "复"))
    )
    monkeypatch.setattr(chat_mod.manager, "enrich_request", lambda req: req)
    monkeypatch.setattr(chat_mod.manager, "flush_langfuse", lambda: None)
    captured: dict = {}

    async def _on_turn(turn: dict) -> None:
        captured.update(turn)

    events = chat_mod.stream_chat(
        "在吗",
        "thread-interrupted-wrapped",
        agent_id="agent-x",
        name="测试",
        system_prompt="",
        on_turn_complete=_on_turn,
    )
    frames = chat_mod.stream_octop_sse(
        _publish_actions(events, {}, agent_id="agent-x"),
        thread_id="thread-interrupted-wrapped",
    )
    try:
        for _ in range(2):
            await frames.__anext__()
    finally:
        # 这就是 chat_api 客户端断连时的收尾顺序
        await frames.aclose()
        await events.aclose()

    assert captured.get("interrupted") is True
    assert captured.get("answer") == "半截回"


@pytest.mark.anyio
async def test_completed_turn_is_not_marked_interrupted(monkeypatch) -> None:
    """正常跑完的一轮不能被标成 interrupted（否则历史里每条回复都挂「已中断」）。"""
    import app.infra.harness.chat as chat_mod

    monkeypatch.setattr(chat_mod.manager, "get_agent", lambda *a, **k: _FakeAgent(("完整", "回复")))
    monkeypatch.setattr(chat_mod.manager, "enrich_request", lambda req: req)
    monkeypatch.setattr(chat_mod.manager, "flush_langfuse", lambda: None)
    captured: dict = {}

    async def _on_turn(turn: dict) -> None:
        captured.update(turn)

    frames = [
        frame
        async for frame in chat_mod.stream_chat(
            "在吗",
            "thread-completed-1",
            agent_id="agent-x",
            name="测试",
            system_prompt="",
            on_turn_complete=_on_turn,
        )
    ]

    assert any(isinstance(frame, dict) and frame.get("type") == "done" for frame in frames)
    assert captured["answer"] == "完整回复"
    assert "interrupted" not in captured


@pytest.mark.anyio
async def test_interrupted_turn_backfills_pending_projection(client: TestClient) -> None:
    """新会话（投影还 pending）断连：先回填 checkpointer，再补半截，用户消息不重复。"""
    from app.domain.chat.service import (
        PROJ_READY,
        thread_message_repo,
        thread_repo,
        write_turn_projection,
    )

    thread_id = "interrupted-pending-1"
    thread_repo.insert(thread_id, "agent-x", title="")
    # checkpointer 里已经有这条用户消息（harness 在轮次开始时落检查点）
    history = [HumanMessage(content="在吗")]
    load_calls: list[int] = []

    async def _load() -> list:
        load_calls.append(1)
        return history

    await write_turn_projection(
        agent_id="agent-x",
        thread_id=thread_id,
        turn={"user": "在吗", "answer": "半截回复", "interrupted": True},
        load_history=_load,
    )

    assert load_calls == [1], "pending 投影必须先回填，否则半截会被下一次 backfill 覆盖"
    assert thread_message_repo.projection_status(thread_id) == PROJ_READY
    rows, _ = thread_message_repo.page(thread_id, limit=100)
    # 用户消息只在回填里出现一次 + 半截助手回复
    assert [r["role"] for r in rows] == ["human", "ai"]
    assert json.loads(rows[1]["message_json"])["data"]["additional_kwargs"]["interrupted"] is True


@pytest.mark.anyio
async def test_normal_turn_skips_pending_projection(client: TestClient) -> None:
    """正常轮次维持原口径：pending 时段不 append，等首次读历史全量 backfill。"""
    from app.domain.chat.service import (
        PROJ_PENDING,
        thread_message_repo,
        thread_repo,
        write_turn_projection,
    )

    thread_id = "normal-pending-1"
    thread_repo.insert(thread_id, "agent-x", title="")

    async def _load() -> list:  # pragma: no cover - 正常轮次不该回填
        raise AssertionError("正常轮次不应触发回填")

    await write_turn_projection(
        agent_id="agent-x",
        thread_id=thread_id,
        turn={"user": "在吗", "answer": "完整回复"},
        load_history=_load,
    )

    assert thread_message_repo.projection_status(thread_id) == PROJ_PENDING
    rows, _ = thread_message_repo.page(thread_id, limit=100)
    assert rows == []


def test_segments_mark_interrupted_reply() -> None:
    """历史片段带上 interrupted 标记，前端才能提示「这条回复被中断了」。"""
    from app.transport.chat_api import _segments_from_messages

    segs = _segments_from_messages(
        [
            HumanMessage(content="在吗"),
            AIMessage(content="半截", additional_kwargs={"interrupted": True}),
            AIMessage(content="完整"),  # 正常回复不许带标记
        ]
    )

    assert segs[0] == {"type": "user", "content": "在吗"}
    assert segs[1] == {"type": "text", "content": "半截", "interrupted": True}
    assert segs[2] == {"type": "text", "content": "完整"}


def test_segments_mark_interrupted_without_text() -> None:
    """断连时一个字都没吐出来：也要给一个空片段做「已中断」标记位。"""
    from app.transport.chat_api import _segments_from_messages

    segs = _segments_from_messages([AIMessage(content="", additional_kwargs={"interrupted": True})])
    assert segs == [{"type": "text", "content": "", "interrupted": True}]
