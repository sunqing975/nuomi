"""HITL 审批台账与续跑协议。

补的是此前完全没测试覆盖的一块：审批（approval_requested）链路只有
``scripts/e2e_hitl_test.py`` 手工脚本，改坏了没人报警。这里锁四件事：

1. **台账写入**：审批帧经过 ``_publish_actions`` 时落库 —— ``request_id`` 是
   harness 事件翻译层现生成的 uuid，原先只活在这一帧 SSE 里，刷新即失联。
2. **决策条数**：harness 要求决策数 == 待审动作数（langchain
   human_in_the_loop.py:484-489 条数不符直接 ``ValueError``，会话永久卡在中断上）。
   服务端必须在流开始**之前**用 400 挡住，而不是让前端收到一个看不懂的 error 帧。
3. **收口时机**：只有真的被 harness 消费（看到 done 或新的 approval_requested）
   才把台账标 resolved；报错/断连保持 pending，卡片留在原地。
4. **不留脏数据**：写台账失败不能把对话打成 error 帧（对话比留痕要紧）。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

import app.transport.chat_api as api_mod
from app.domain.approvals.service import (
    STATUS_PENDING,
    STATUS_RESOLVED,
    STATUS_SUPERSEDED,
    approval_ledger,
)
from app.storage import db


@pytest.fixture(autouse=True)
def _ensure_schema() -> None:
    """建表（幂等）。本文件有不调 HTTP 的用例，不能只靠 client 的 lifespan。"""
    db.init_db()


def _new_agent(client: TestClient) -> str:
    r = client.post("/api/agents", json={"name": f"审批测试{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    return r.json()["agent_id"]


def _request(payload: list[dict]) -> dict:
    """拼一个 HITLRequest 形状（action_requests + review_configs）。"""
    return {
        "action_requests": [{"name": p["name"], "args": p.get("args", {})} for p in payload],
        "review_configs": [
            {
                "action_name": p["name"],
                "allowed_decisions": p.get("allowed", ["approve", "reject"]),
            }
            for p in payload
        ],
    }


def _record(thread_id: str, agent_id: str, payload: list[dict], *, request_id: str = "") -> str:
    rid = request_id or f"req-{uuid.uuid4().hex[:8]}"
    approval_ledger.record_request(
        request_id=rid,
        thread_id=thread_id,
        agent_id=agent_id,
        request=_request(payload),
        source="console",
    )
    return rid


# ---------- 1. 台账写入 ----------


def test_ledger_records_approval_frame_from_event_stream() -> None:
    """审批帧经过转发层就进台账；缺 agent_id 的帧跳过写入而不是抛错。"""

    async def events():
        yield {
            "type": "approval_requested",
            "thread_id": "t-rec",
            "request_id": "r-rec",
            "request": _request([{"name": "write_file"}]),
        }
        yield {"type": "token", "content": "x"}

    frames = asyncio.run(_collect(events, agent_id="a-rec"))
    assert [f["type"] for f in frames] == ["approval_requested", "token"]
    row = approval_ledger.get("r-rec")
    assert row is not None and row["status"] == STATUS_PENDING
    assert row["thread_id"] == "t-rec" and row["agent_id"] == "a-rec"
    assert row["actions"][0]["name"] == "write_file"
    # review_configs 按 action_name 并进了动作清单：前端才知道该摆哪几个按钮
    assert row["actions"][0]["allowed_decisions"] == ["approve", "reject"]

    async def no_agent():
        yield {"type": "approval_requested", "thread_id": "t2", "request_id": "r2", "request": {}}

    asyncio.run(_collect(no_agent))
    assert approval_ledger.get("r2") is None


async def _collect(events, *, agent_id: str | None = None) -> list[dict]:
    return [ev async for ev in api_mod._publish_actions(events(), {}, agent_id=agent_id)]


def test_ledger_write_failure_does_not_break_stream(monkeypatch) -> None:
    """台账写失败只记日志：对话必须继续（否则用户看到的是「对话挂了」）。"""

    def boom(*_a, **_k):
        raise RuntimeError("table approvals is locked")

    monkeypatch.setattr(api_mod.approval_ledger, "record_request", boom)

    async def events():
        yield {
            "type": "approval_requested",
            "thread_id": "t-boom",
            "request_id": "r-boom",
            "request": _request([{"name": "x"}]),
        }
        yield {"type": "done", "answer": "ok"}

    frames = asyncio.run(_collect(events, agent_id="a1"))
    assert [f["type"] for f in frames] == ["approval_requested", "done"]


# ---------- 2/3. 续跑协议 + 收口 ----------


@pytest.fixture
def stub_resume(monkeypatch):
    """替换 resume_chat（nuomi 自己的边界），记录收到的决策数并跑完一轮。"""
    seen: dict = {}

    async def fake_resume(thread_id, decisions, **_kwargs):
        seen["decisions"] = decisions
        yield {"type": "token", "content": "stub"}
        yield {"type": "done", "answer": "stub"}

    monkeypatch.setattr(api_mod, "resume_chat", fake_resume)
    return seen


def test_multi_action_requires_matching_decisions(client: TestClient, stub_resume) -> None:
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    rid = _record(tid, aid, [{"name": "create_order"}, {"name": "close_order"}])

    # 逐条给但只给 1 条：harness 会 ValueError 卡死会话 → 必须在流开始**之前**挡住
    r = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"thread_id": tid, "decisions": [{"type": "approve"}]},
    )
    assert r.status_code == 400, r.text
    assert "2 个待审动作" in r.json()["detail"]
    assert "收到 1 条" in r.json()["detail"]
    assert r.headers["content-type"].startswith("application/json")  # 不是半截 SSE
    assert approval_ledger.get(rid)["status"] == STATUS_PENDING  # 没消费，卡片留在原地

    # 逐条给出 → 放行，且 harness 收到 2 条决策
    r2 = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={
            "thread_id": tid,
            "decisions": [{"type": "approve"}, {"type": "reject", "message": "先别关单"}],
        },
    )
    assert r2.status_code == 200, r2.text
    assert "text/event-stream" in r2.headers["content-type"]
    assert len(stub_resume["decisions"]) == 2
    assert stub_resume["decisions"][1] == {"type": "reject", "message": "先别关单"}

    # 消费完成（看到 done）→ 台账收口
    row = approval_ledger.get(rid)
    assert row["status"] == STATUS_RESOLVED
    assert row["decisions"][0]["type"] == "approve"
    assert row["resolved_at"] >= row["created_at"]


def test_legacy_single_decision_still_works(client: TestClient, stub_resume) -> None:
    """旧客户端（壳、scripts/e2e_hitl_test.py）只发 ``decision``：整批一个决定。

    两个动作时服务端复制成 2 条 —— 这是兼容的关键：老客户端不改也能续跑多动作
    打包的审批，而不是被 400 挡在门外（它压根不知道该发几条）。
    """
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    _record(tid, aid, [{"name": "write_file"}])
    r = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"thread_id": tid, "decision": "reject", "message": "不要写"},
    )
    assert r.status_code == 200, r.text
    assert stub_resume["decisions"] == [{"type": "reject", "message": "不要写"}]

    tid2 = f"thr-{uuid.uuid4().hex[:8]}"
    _record(tid2, aid, [{"name": "a"}, {"name": "b"}])
    r2 = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"thread_id": tid2, "decision": "approve"},
    )
    assert r2.status_code == 200, r2.text
    assert stub_resume["decisions"] == [{"type": "approve"}, {"type": "approve"}]


def test_respond_allowed_only_when_action_allows_it(client: TestClient, stub_resume) -> None:
    """ask_user 类动作只允许 respond（按钮摆错就是骗人）；普通动作拒绝 edit。"""
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    _record(tid, aid, [{"name": "ask_user", "allowed": ["respond"]}])
    r = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"thread_id": tid, "decisions": [{"type": "approve"}]},
    )
    assert r.status_code == 400, r.text
    assert "只允许" in r.json()["detail"]

    ok = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"thread_id": tid, "decisions": [{"type": "respond", "message": "选 A"}]},
    )
    assert ok.status_code == 200, ok.text
    assert stub_resume["decisions"] == [{"type": "respond", "message": "选 A"}]


def test_resubmitting_resolved_approval_is_rejected(client: TestClient, stub_resume) -> None:
    """卡片复活/重复点击：409 拒掉，别把同一个写工具跑第二遍。"""
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    rid = _record(tid, aid, [{"name": "create_order"}])
    first = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"request_id": rid, "thread_id": tid, "decision": "approve"},
    )
    assert first.status_code == 200, first.text
    again = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"request_id": rid, "thread_id": tid, "decision": "approve"},
    )
    assert again.status_code == 409, again.text


def test_failed_resume_keeps_card_pending(client: TestClient, monkeypatch) -> None:
    """续跑抛错时不写 resolved：卡片必须留在原地让人重批。"""
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    rid = _record(tid, aid, [{"name": "create_order"}])

    async def broken_resume(thread_id, decisions, **_kwargs):
        raise RuntimeError("harness 拒绝：条数不匹配")
        yield  # pragma: no cover 让它成为 async generator

    monkeypatch.setattr(api_mod, "resume_chat", broken_resume)
    r = client.post(
        f"/api/agents/{aid}/chat/approval",
        json={"request_id": rid, "thread_id": tid, "decision": "approve"},
    )
    assert r.status_code == 200  # 流已开始，错误以 error 帧回传
    assert '"type": "error"' in r.text or "error" in r.text
    assert approval_ledger.get(rid)["status"] == STATUS_PENDING


def test_new_message_supersedes_pending_card(client: TestClient, stub_llm) -> None:
    """用户不理卡片直接接着打字 → 旧 pending 作废，刷新后不该再弹出来。"""
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    rid = _record(tid, aid, [{"name": "create_order"}])
    r = client.post(
        f"/api/agents/{aid}/chat",
        json={"thread_id": tid, "messages": "换个方案"},
    )
    assert r.status_code == 200, r.text
    assert approval_ledger.get(rid)["status"] == STATUS_SUPERSEDED
    assert approval_ledger.pending_for_thread(tid) is None


# ---------- 4. 台账查询端点 ----------


def test_approvals_endpoint_lists_pending_then_history(client: TestClient) -> None:
    aid = _new_agent(client)
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    rid = _record(tid, aid, [{"name": "create_order", "args": {"id": 7}}])

    pending = client.get(f"/api/agents/{aid}/approvals", params={"status": "pending"}).json()
    assert len(pending["approvals"]) == 1
    row = pending["approvals"][0]
    assert row["request_id"] == rid and row["thread_id"] == tid
    assert row["actions"][0]["args"] == {"id": 7}
    assert "request" not in row  # 原始 HITLRequest 不外泄

    approval_ledger.resolve(rid, [{"type": "approve"}])
    assert client.get(f"/api/agents/{aid}/approvals", params={"status": "pending"}).json() == {
        "approvals": []
    }
    history = client.get(f"/api/agents/{aid}/approvals").json()["approvals"]
    assert history[0]["status"] == STATUS_RESOLVED
    assert history[0]["decisions"] == [{"type": "approve"}]

    assert client.get("/api/agents/nope/approvals").status_code == 404


def test_ledger_is_idempotent_on_request_id() -> None:
    """同一 request_id 重复记（重放/双写）不该覆盖已答复的决策。"""
    rid = f"req-{uuid.uuid4().hex[:8]}"
    tid = f"thr-{uuid.uuid4().hex[:8]}"
    _record(tid, "a1", [{"name": "x"}], request_id=rid)
    _record(tid, "a1", [{"name": "y"}], request_id=rid)
    assert approval_ledger.get(rid)["actions"][0]["name"] == "x"
    assert approval_ledger.resolve(rid, [{"type": "approve"}]) is True
    # 已 resolved 之后再来一次 resolve 不覆盖
    assert approval_ledger.resolve(rid, [{"type": "reject"}]) is False
    assert approval_ledger.get(rid)["decisions"] == [{"type": "approve"}]


# ---------------------------------------------------------------- 壳（OpenAI 兼容端点）


def _stub_compat_approval(monkeypatch, request: dict) -> None:
    async def fake_stream_chat(*args, **kwargs):  # noqa: ANN002, ANN003
        yield {"type": "token", "content": "先看一眼工单。"}
        yield {
            "type": "approval_requested",
            "request_id": "req-shell-1",
            "thread_id": "desktop",
            "request": request,
        }

    import app.transport.openai_compat as compat_mod

    monkeypatch.setattr(compat_mod, "stream_chat", fake_stream_chat)


def test_shell_approval_lands_in_ledger(client, monkeypatch) -> None:
    """壳里触发的审批要在台账留痕（控制台才能看见并代批）。

    数字人壳没有任何审批 UI，这一帧以前走到兼容端点就被丢掉：对话在壳里静默断掉，
    被 tool_guard 拦下的写操作等于凭空蒸发。
    """
    agent_id = _new_agent(client)
    _stub_compat_approval(monkeypatch, _request([{"name": "mes_report", "args": {"n": 1}}]))
    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        json={
            "model": f"agent:{agent_id}",
            "messages": [{"role": "user", "content": "帮我报工"}],
            "stream": True,
        },
    ) as res:
        assert res.status_code == 200
        for _ in res.iter_lines():
            pass

    rows = client.get(f"/api/agents/{agent_id}/approvals").json()["approvals"]
    assert [r["request_id"] for r in rows] == ["req-shell-1"]
    assert rows[0]["thread_id"] == "desktop"
    assert rows[0]["source"] == "shell"
    assert rows[0]["status"] == "pending"
