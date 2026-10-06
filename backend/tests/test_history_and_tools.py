"""对话历史分页 + 插件工具装配的回归测试（2026-10-06 第 2 批）。

1. **历史分页两条路径语义必须一致**：投影 ready 走 ``page()``（倒序分页：从最新往前），
   pending 走 checkpointer + 全量 backfill。原 backfill 用 ``msgs[-limit:]`` 忽略 offset，
   且投影为空时还会回落重算 → 翻页重复拿到同一批尾部消息。
2. **``tools_and_owners()`` 与 ``tools() + tool_owners()`` 等价**，但只查一次 ``list_all()``。
3. **``_publish_actions`` 的工具来源映射按请求传入**（原模块级全局会被并发对话互相覆盖）。
"""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.domain.chat.service import (
    PROJ_READY,
    thread_message_repo,
    thread_repo,
)
from app.domain.plugins.service import plugin_service

# ---------- 历史分页 ----------


def _seed_thread(client: TestClient, thread_id: str, count: int) -> str:
    """建线程 + 直接写投影 + 标 ready（绕过 harness，专注分页语义）。"""
    agent_id = client.get("/api/agents").json()[0]["agent_id"]
    thread_repo.insert(thread_id, agent_id, title="分页测试")
    inputs = [
        {
            "message_id": f"m{i}",
            "role": "human" if i % 2 == 0 else "ai",
            "message_json": json.dumps(
                {"type": "human" if i % 2 == 0 else "ai", "data": {"content": f"第{i}条"}}
            ),
            "created_at": 1_700_000_000_000 + i,
        }
        for i in range(count)
    ]
    thread_message_repo.append(thread_id, inputs)
    thread_message_repo.mark_projection(thread_id, PROJ_READY)
    return agent_id


def _texts(segments: list[dict], seg_type: str) -> list[str]:
    """取指定片段类型的文本。片段是扁平结构：{"type": "user"|"text"|"reasoning"|..., "content": ...}"""
    return [s["content"] for s in segments if s["type"] == seg_type]


def test_history_pagination_is_tail_based(client: TestClient) -> None:
    """从最新往前取：limit=4 → 最后 4 条；再 offset=4 → 再往前 4 条。"""
    tid = "hist-page-1"
    aid = _seed_thread(client, tid, 10)

    first = client.get(f"/api/agents/{aid}/chat/history?thread_id={tid}&limit=4").json()
    # 最后 4 条 = 索引 6..9 → user 是 6、8；ai 渲染成 text 片段 7、9
    assert _texts(first, "user") == ["第6条", "第8条"], first
    assert _texts(first, "text") == ["第7条", "第9条"], first

    second = client.get(f"/api/agents/{aid}/chat/history?thread_id={tid}&limit=4&offset=4").json()
    texts = _texts(second, "user")
    assert texts == ["第2条", "第4条"], f"offset 未生效或重复返回尾部：{texts}"


def test_history_offset_beyond_end_returns_empty(client: TestClient) -> None:
    """offset 越界应返回空 —— 原实现会回落到 backfill 把尾部消息又返回一遍。"""
    tid = "hist-page-2"
    aid = _seed_thread(client, tid, 4)
    r = client.get(f"/api/agents/{aid}/chat/history?thread_id={tid}&limit=10&offset=999")
    assert r.status_code == 200
    assert r.json() == [], "越界 offset 返回了尾部消息（回落 bug 复现）"


def test_history_limit_is_validated(client: TestClient) -> None:
    aid = client.get("/api/agents").json()[0]["agent_id"]
    assert client.get(f"/api/agents/{aid}/chat/history?thread_id=x&limit=0").status_code == 422
    assert client.get(f"/api/agents/{aid}/chat/history?thread_id=x&offset=-1").status_code == 422


def test_history_pending_path_respects_offset(client: TestClient, monkeypatch) -> None:
    """pending 路径（checkpointer + backfill）必须与 ready 路径同语义。"""

    from langchain_core.messages import HumanMessage

    class _FakeAgent:
        async def aget_history(self, _thread_id, limit=0):
            # 必须是真的 BaseMessage：backfill 走 messages_to_inputs → message_to_dict，
            # 假对象会被它静默跳过（投影写 0 行，第二次调用读投影就成空）
            return [HumanMessage(content=f"第{i}条") for i in range(10)]

    import app.transport.chat_api as api_mod

    monkeypatch.setattr(api_mod, "ensure_agent_runtime", lambda _row: _FakeAgent())
    aid = client.get("/api/agents").json()[0]["agent_id"]

    # 关键：offset 必须用**另一个新线程**请求 —— 同一个线程第一次请求就会被标成 ready，
    # 第二次就走 ready 分支了，pending 的 offset 逻辑根本没被执行到（这条测试的第一版
    # 就是这样，把旧实现改回去也照样通过，等于没测）。
    tid_a, tid_b = "hist-pending-a", "hist-pending-b"

    first = client.get(f"/api/agents/{aid}/chat/history?thread_id={tid_a}&limit=4").json()
    assert _texts(first, "user") == ["第6条", "第7条", "第8条", "第9条"], (
        f"pending 未取尾部：{first}"
    )

    second = client.get(f"/api/agents/{aid}/chat/history?thread_id={tid_b}&limit=4&offset=6").json()
    assert _texts(second, "user") == ["第0条", "第1条", "第2条", "第3条"], (
        f"pending 路径忽略 offset（应为最前面 4 条）：{second}"
    )

    # backfill 之后同一线程应变成 ready，两条路径给同一答案
    assert thread_message_repo.projection_status(tid_a) == PROJ_READY
    assert thread_message_repo.projection_status(tid_b) == PROJ_READY


# ---------- 工具装配 ----------


def test_tools_and_owners_matches_separate_calls() -> None:
    tools = plugin_service.tools()
    owners = plugin_service.tool_owners()
    both_tools, both_owners = plugin_service.tools_and_owners()

    assert [t.name for t in both_tools] == [t.name for t in tools]
    assert both_owners == owners


def test_tools_and_owners_queries_plugins_once(monkeypatch) -> None:
    """对话热路径只该查一次 list_all()（原先 tools() 与 tool_owners() 各查一次）。"""
    calls = {"n": 0}
    real = plugin_service.list_all

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(plugin_service, "list_all", counting)
    plugin_service.tools_and_owners()
    assert calls["n"] == 1, f"list_all 被调用 {calls['n']} 次"

    calls["n"] = 0
    plugin_service.tools()
    plugin_service.tool_owners()
    assert calls["n"] == 2, "单独调用时各查一次是预期的"


# ---------- 事件转发：来源映射按请求传入 ----------


def test_publish_actions_uses_passed_owner_map() -> None:
    """来源映射是请求局部参数，不再读模块级全局（并发对话会互相覆盖）。"""
    import app.transport.chat_api as api_mod

    async def _events():
        yield {"type": "tool_call", "name": "weather", "args": "{}"}
        yield {"type": "tool_result", "name": "weather", "messages": [{"content": "晴"}]}

    async def _collect(owners):
        out = []
        async for ev in api_mod._publish_actions(_events(), owners):
            out.append(ev)
        return out

    out = asyncio.run(_collect({"weather": "weather-octop"}))
    assert out[0]["plugin_id"] == "weather-octop"
    assert out[1]["plugin_id"] == "weather-octop"

    # 传空映射 → 不附加 plugin_id（证明没有回落到全局）
    out2 = asyncio.run(_collect({}))
    assert "plugin_id" not in out2[0]


def test_no_module_level_tool_owners_global() -> None:
    """防回退：模块级不应该再有 _TOOL_OWNERS 全局。"""
    import app.transport.chat_api as api_mod

    assert not hasattr(api_mod, "_TOOL_OWNERS")
