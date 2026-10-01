"""端到端测试：假模型 → LangGraph agent → SQLite checkpointer → SSE 接口。

不依赖任何真实 LLM key，验证：流式逐字输出、会话持久化（两轮对话共享 thread_id）、
skills 加载与 /health、出错时返回 error 事件。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import build_app
from app.skills import scan_plugins

from .fake_llm import FakeChatModel

# tests/ -> backend -> nuomi 仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "plugins"


def _make_app(tmp_path):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "test.sqlite"),
        skills_dir=str(SKILLS_DIR),
        memory_file=str(tmp_path / "mem" / "facts.json"),
    )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event, data = "message", "{}"
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        events.append((event, json.loads(data)))
    return events


def test_streaming_and_persistence(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        # 单 Agent 流式测试：先停用智能体团队插件（否则 /api/chat 走 Supervisor 路由）
        client.post("/api/plugins/team/toggle")
        # 第一轮：新建 thread
        r1 = client.post("/api/chat", json={"message": "你好，我是谁不重要"})
        assert r1.status_code == 200
        ev1 = _parse_sse(r1.text)
        assert ev1[0][0] == "meta"
        thread_id = ev1[0][1]["thread_id"]
        assert thread_id
        tokens = [e[1]["content"] for e in ev1 if e[0] == "token"]
        assert tokens, "应有逐字 token 事件"
        assert "".join(tokens) == ev1[-1][1]["content"]  # done 完整回复 = token 拼接
        assert ev1[-1][0] == "done"

        # 第二轮：复用 thread_id，验证 checkpointer 记住了上轮
        r2 = client.post("/api/chat", json={"message": "还记得刚才吗", "thread_id": thread_id})
        ev2 = _parse_sse(r2.text)
        assert ev2[0][1]["thread_id"] == thread_id
        assert ev2[-1][0] == "done"


def test_health_reports_loaded_skills(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        names = {s["name"] for s in body["plugins"]}
        assert "datetime" in names
        dt = next(s for s in body["plugins"] if s["name"] == "datetime")
        assert dt["tools"] >= 1  # v0.6 贡献视图：无 type 字段
        assert dt["error"] is None


def test_invalid_request_rejected(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"message": ""}).status_code == 422
        assert client.post("/api/chat", json={"thread_id": "x"}).status_code == 422


def test_skills_loader_detects_bad_plugin(tmp_path):
    bad = tmp_path / "skills_bad" / "broken"
    bad.mkdir(parents=True)
    (bad / "plugin.json").write_text("{not json", encoding="utf-8")
    loaded = scan_plugins(tmp_path / "skills_bad")
    assert len(loaded) == 1
    assert loaded[0].error and "plugin.json" in loaded[0].error
    assert loaded[0].tools == []
