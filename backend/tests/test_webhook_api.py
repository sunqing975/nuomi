"""Webhook 端点测试（``app/transport/webhook_api.py``）。

后台整轮对话依赖真实 LLM，测试里必然失败 —— 但 webhook 的契约是「受理即返回」：
建线程、返回 thread_id、不抢占控制台当前会话，这些与 LLM 无关，直接可测。
守卫豁免（webhook 免 token）也在这里一并锁住。
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _new_agent(client: TestClient) -> str:
    r = client.post("/api/agents", json={"name": "webhook测试专家"})
    assert r.status_code == 200
    return r.json()["agent_id"]


def test_webhook_no_token_needed(client: TestClient) -> None:
    """守卫豁免：webhook 写操作不带 X-Nuomi-Token 也放行（同机外部调用方免配置）。"""
    from app.infra.local_guard import requires_token

    assert not requires_token("POST", "/api/webhook/whatever")
    assert requires_token("POST", "/api/agents")  # 其余写操作照旧


def test_webhook_accepts_and_creates_thread(client: TestClient) -> None:
    aid = _new_agent(client)
    # 先建一个控制台会话：webhook 不应抢占它的 current
    own = client.post("/api/chat/new", json={"agent_id": aid}).json()["thread_id"]
    r = client.post(
        f"/api/webhook/{aid}", json={"message": "测试消息"}, headers={"X-Nuomi-Token": ""}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    tid = body["thread_id"]
    assert tid.startswith(f"{aid}:")

    # 会话列表可见（标题带 Webhook 前缀），且**不是**控制台当前会话
    st = client.get(f"/api/chat/state?agent_id={aid}").json()
    titles = [s["title"] for s in st["sessions"]]
    assert any(t.startswith("Webhook ·") for t in titles)
    assert st["current"] == own


def test_webhook_rejects_bad_input(client: TestClient) -> None:
    aid = _new_agent(client)
    # 空消息
    r = client.post(f"/api/webhook/{aid}", json={"message": "   "})
    assert r.status_code == 422
    # 不存在的专家
    r = client.post("/api/webhook/no-such-agent", json={"message": "hi"})
    assert r.status_code == 404
