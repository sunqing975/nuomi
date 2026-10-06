"""M3/M4 测试：Agent 运行时参数映射（runtime_limits）+ 会话存储（threads/messages 投影）。

- M3：agents.config_json 运行时参数（max_iters/temperature/top_p/max_tokens/max_input_length）
  → ChatRequest 注入（对齐 Octop runtime_limits）。
- M4：会话列表落 SQLite threads 表；历史端点投影优先（ready 读表 / pending backfill）；
  删会话级联清理（threads + thread_messages + projection + checkpointer）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.chat.service import (
    PROJ_READY,
    thread_message_repo,
    thread_repo,
    turn_to_message_inputs,
)
from app.infra.harness.runtime_limits import apply_agent_runtime_to_stream_request

# —— M3：运行时参数映射 ——


def test_runtime_limits_apply() -> None:
    req = apply_agent_runtime_to_stream_request(
        {"messages": "hi", "thread_id": "t1"},
        {
            "max_iters": 25,
            "max_input_length": 100_000,
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 2048,
        },
    )
    assert req["recursion_limit"] == 25
    assert req["configurable"]["model_settings"] == {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 2048,
    }
    assert req["configurable"]["max_input_tokens"] == 100_000


def test_runtime_limits_invalid_values_filtered() -> None:
    req = apply_agent_runtime_to_stream_request(
        {"messages": "hi", "thread_id": "t1"},
        {
            "max_iters": 0,  # 非正 → 忽略
            "temperature": 3.0,  # 超界 → 忽略
            "top_p": True,  # bool → 忽略
            "max_tokens": "abc",  # 非数字 → 忽略
            "max_input_length": "8000",  # 数字字符串 → 接受
        },
    )
    assert "recursion_limit" not in req
    assert "configurable" not in req or "model_settings" not in req["configurable"]
    assert req["configurable"]["max_input_tokens"] == 8000


def test_runtime_limits_turn_explicit_wins() -> None:
    req = apply_agent_runtime_to_stream_request(
        {"messages": "hi", "thread_id": "t1", "recursion_limit": 5},
        {"max_iters": 25, "temperature": 0.7},
    )
    # per-turn 显式 recursion_limit 优先于 agent 配置
    assert req["recursion_limit"] == 5


# —— M3：Agent 生命周期 API ——


def test_agent_patch_config_json(client: TestClient) -> None:
    """PATCH /agents/{id} 支持 config_json（运行时参数落库；M3）。"""
    aid = _new_agent(client)
    r = client.patch(
        f"/api/agents/{aid}",
        json={"config_json": {"temperature": 0.8, "max_iters": 30, "max_tokens": 1500}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["config_json"] == {
        "temperature": 0.8,
        "max_iters": 30,
        "max_tokens": 1500,
    }
    # 不传 config_json 的 PATCH 不清空它
    r = client.patch(f"/api/agents/{aid}", json={"name": "改名"})
    assert r.json()["config_json"]["max_iters"] == 30


# —— M4：会话存储 API ——


def _new_agent(client: TestClient) -> str:
    """建独立专家，隔离各测试的会话状态（client 为 session 级，共享 DB）。"""
    r = client.post("/api/agents", json={"name": f"测试专家{__import__('uuid').uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()["agent_id"]


def test_chat_state_empty(client: TestClient) -> None:
    aid = _new_agent(client)
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert st["agent_id"] == aid
    assert st["current"] is None
    assert st["sessions"] == []


def test_chat_new_switch_touch(client: TestClient) -> None:
    aid = _new_agent(client)

    r = client.post("/api/chat/new", json={"agent_id": aid})
    assert r.status_code == 200, r.text
    tid = r.json()["thread_id"]
    assert tid.startswith(f"{aid}:")

    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert st["current"] == tid
    assert len(st["sessions"]) == 1

    # 新建第二个会话 → current 切换
    tid2 = client.post("/api/chat/new", json={"agent_id": aid}).json()["thread_id"]
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert st["current"] == tid2
    assert {s["thread_id"] for s in st["sessions"]} == {tid, tid2}

    # switch 回第一个
    assert (
        client.post("/api/chat/switch", json={"agent_id": aid, "thread_id": tid}).status_code == 200
    )
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert st["current"] == tid
    # switch 非法 thread → 404
    r = client.post("/api/chat/switch", json={"agent_id": aid, "thread_id": "nope"})
    assert r.status_code == 404

    # touch 标题（仅「新会话」可替换）
    r = client.post(
        "/api/chat/touch", json={"agent_id": aid, "thread_id": tid, "title": "我的会话"}
    )
    assert r.status_code == 200
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    row = next(s for s in st["sessions"] if s["thread_id"] == tid)
    assert row["title"] == "我的会话"


def test_chat_delete_cascades(client: TestClient) -> None:
    aid = _new_agent(client)
    tid = client.post("/api/chat/new", json={"agent_id": aid}).json()["thread_id"]

    # 直接写投影 + 标记 ready，验证删除级联
    turn = {
        "user": "你好",
        "answer": "你好呀",
        "reasoning": "",
        "tool_calls": [],
        "tool_results": [],
    }
    assert thread_message_repo.append(tid, turn_to_message_inputs(turn)) == 2
    thread_message_repo.mark_projection(tid, PROJ_READY)
    assert thread_message_repo.projection_status(tid) == PROJ_READY

    r = client.delete(f"/api/chat/threads/{tid}?agent_id={aid}")
    assert r.status_code == 200
    assert thread_repo.get(tid) is None
    assert thread_message_repo.head(tid) == 0
    assert thread_message_repo.projection_status(tid) != PROJ_READY
    # 删除当前会话后 current 归位 None
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert st["current"] is None

    # 重复删除 404
    assert client.delete(f"/api/chat/threads/{tid}?agent_id={aid}").status_code == 404


def test_migrate_state_file_threads(client: TestClient) -> None:
    """旧 nuomi-state.json 的 threads 列表 → SQLite 表（幂等迁移 + 旧字段清理）。"""

    from app.config import settings

    state = settings.workspace_path / "nuomi-state.json"
    aid = _new_agent(client)
    old = {
        "thread_id": "legacy:tid1",
        "threads": [
            {
                "thread_id": "legacy:tid1",
                "title": "旧会话",
                "updated_at": 1700000000000,
                "agent_id": aid,
            },
            {
                "thread_id": "legacy:tid2",
                "title": "另一个",
                "updated_at": 1700000001000,
                "agent_id": aid,
            },
        ],
    }
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(__import__("json").dumps(old), encoding="utf-8")

    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert {s["thread_id"] for s in st["sessions"]} == {"legacy:tid1", "legacy:tid2"}
    assert st["current"] == "legacy:tid1"

    # 迁移后 state 文件清理旧 threads 字段（状态文件即用即清）
    import json as _json

    cleaned = _json.loads(state.read_text(encoding="utf-8"))
    assert "threads" not in cleaned
    assert cleaned["thread_id"] == "legacy:tid1"

    # 幂等：再次访问不重复迁移
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    assert len(st["sessions"]) == 2


# —— M4：历史端点投影（pending backfill → ready 读表） ——


class _FakeAgent:
    """假运行时：aget_history 返回固定消息（避免测试依赖真实 LLM）。"""

    def __init__(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        self._msgs = [
            HumanMessage(content="你好"),
            AIMessage(
                content="我来查一下",
                tool_calls=[{"id": "c1", "name": "touch_special", "args": {"x": 1}}],
            ),
            ToolMessage(content="结果", name="touch_special", tool_call_id="c1"),
            AIMessage(content="完成"),
        ]

    async def aget_history(self, thread_id: str, limit: int = 50):
        return self._msgs[-limit:]


def test_history_projection_backfill_then_table(client: TestClient, monkeypatch) -> None:

    from app.transport import chat_api as api_mod

    aid = _new_agent(client)
    tid = client.post("/api/chat/new", json={"agent_id": aid}).json()["thread_id"]

    # pending → 走 checkpointer backfill（fake），写投影并标记 ready
    monkeypatch.setattr(api_mod, "ensure_agent_runtime", lambda row: _FakeAgent())
    r = client.get(f"/api/agents/{aid}/chat/history", params={"thread_id": tid})
    assert r.status_code == 200, r.text
    segments = r.json()
    assert [s["type"] for s in segments] == ["user", "text", "tool_call", "tool_result", "text"]
    assert segments[0]["content"] == "你好"
    assert segments[2]["name"] == "touch_special"

    # 投影已 ready 且落库
    assert thread_message_repo.projection_status(tid) == PROJ_READY
    rows, _ = thread_message_repo.page(tid, limit=10)
    assert len(rows) == 4
    # 落库的是 langchain wire 格式（可回读为 BaseMessage）
    from langchain_core.messages import messages_from_dict

    msgs = messages_from_dict([__import__("json").loads(r2["message_json"]) for r2 in rows])
    assert msgs[0].type == "human"

    # 再次读取走投影表（monkeypatch 移除 fake，若走 checkpointer 会因无实例而失败）
    monkeypatch.undo()
    r = client.get(f"/api/agents/{aid}/chat/history", params={"thread_id": tid})
    assert r.status_code == 200, r.text
    assert [s["type"] for s in r.json()] == ["user", "text", "tool_call", "tool_result", "text"]


def test_history_projection_after_turn_append(client: TestClient, monkeypatch) -> None:
    """ready 投影下每轮对话增量 append（turn_to_message_inputs 序列化 human+ai）。"""
    from app.transport import chat_api as api_mod

    aid = _new_agent(client)
    tid = client.post("/api/chat/new", json={"agent_id": aid}).json()["thread_id"]

    monkeypatch.setattr(api_mod, "ensure_agent_runtime", lambda row: _FakeAgent())
    client.get(f"/api/agents/{aid}/chat/history", params={"thread_id": tid})  # backfill → ready

    inputs = turn_to_message_inputs(
        {"user": "再问", "answer": "回答", "reasoning": "", "tool_calls": [], "tool_results": []}
    )
    assert len(inputs) == 2
    assert thread_message_repo.append(tid, inputs) == 2
    assert thread_message_repo.head(tid) == 6  # 4 backfill + 2 增量

    # 重复 append 同一 message_id 不重复（本轮无 message_id → 全量追加；此断言验证计数）
    assert thread_message_repo.append(tid, inputs) == 2
