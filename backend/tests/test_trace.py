"""Phase 3 · trace 可观测：每轮写 jsonl，/logs 端点可读。"""

from __future__ import annotations

from pathlib import Path

from app.main import build_app
from app.storage.trace import TraceLogger
from fastapi.testclient import TestClient

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_trace_logger_writes_and_tails(tmp_path):
    p = tmp_path / "trace.jsonl"
    lg = TraceLogger(p)
    lg.log(thread_id="t1", user_message="hi", reply_chars=2, tools_called=[], latency_s=0.1)
    lg.log(
        thread_id="t2",
        user_message="hey",
        reply_chars=3,
        tools_called=["get_current_time"],
        latency_s=0.2,
    )
    entries = lg.tail(10)
    assert len(entries) == 2
    assert entries[1]["tools_called"] == ["get_current_time"]


def test_chat_writes_trace(tmp_path):
    trace_file = tmp_path / "trace.jsonl"

    # 覆盖 trace 路径：直接给 TraceLogger 指定路径，经 app.state 注入
    app = build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        plugins_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试：关闭团队路由
        app.state.trace_logger = TraceLogger(trace_file)
        r = client.post("/api/chat", json={"message": "你好", "thread_id": "trace-1"})
        assert r.status_code == 200
        entries = app.state.trace_logger.tail(5)
        assert entries and entries[-1]["thread_id"] == "trace-1"
        assert entries[-1]["reply_chars"] > 0
        assert "latency_s" in entries[-1]

        body = client.get("/logs?n=3").json()
        assert body["count"] >= 1
        assert body["entries"][0]["thread_id"] == "trace-1"
