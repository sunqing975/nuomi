"""V3 增强：项目 / 会话 API + chat 事件（标题/触摸/reasoning/usage）。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import build_app
from tests.fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )


def test_projects_crud_and_default(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        # 默认项目自动存在
        r = client.get("/api/projects")
        assert r.status_code == 200
        projects = r.json()["projects"]
        assert len(projects) >= 1
        # 新建
        r2 = client.post("/api/projects", json={"name": "求职作品集"})
        assert r2.status_code == 200
        pid = r2.json()["id"]
        names = {p["name"] for p in client.get("/api/projects").json()["projects"]}
        assert "求职作品集" in names
        # 删除
        r3 = client.delete(f"/api/projects/{pid}")
        assert r3.status_code == 200
        names = {p["name"] for p in client.get("/api/projects").json()["projects"]}
        assert "求职作品集" not in names


def test_threads_crud(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        pid = client.get("/api/projects").json()["projects"][0]["id"]
        r = client.post("/api/threads", json={"project_id": pid, "title": "第一课"})
        assert r.status_code == 200
        tid = r.json()["id"]
        # 重命名
        r2 = client.patch(f"/api/threads/{tid}", json={"title": "改个名"})
        assert r2.status_code == 200
        titles = [t["title"] for t in client.get("/api/threads").json()["threads"]]
        assert "改个名" in titles
        # 删除
        r3 = client.delete(f"/api/threads/{tid}")
        assert r3.status_code == 200
        tids = [t["id"] for t in client.get("/api/threads").json()["threads"]]
        assert tid not in tids


def test_delete_project_cascades_threads(tmp_path):
    """回归：删项目必须级联删其会话（外键 PRAGMA 未启用时会话成不可见孤儿）。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"name": "级联测试"}).json()["id"]
        t1 = client.post("/api/threads", json={"project_id": pid, "title": "a"}).json()["id"]
        t2 = client.post("/api/threads", json={"project_id": pid, "title": "b"}).json()["id"]
        assert client.delete(f"/api/projects/{pid}").status_code == 200
        threads = client.get("/api/threads").json()["threads"]
        tids = [t["id"] for t in threads]
        assert t1 not in tids and t2 not in tids
        assert not any(t["project_id"] == pid for t in threads)  # 无孤儿


def test_chat_creates_thread_and_auto_title(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "帮我规划求职时间线", "thread_id": None})
        assert r.status_code == 200
        # SSE 里 meta 事件返回 thread_id；标题由首条消息截断生成
        body = r.text
        tid = None
        for line in body.splitlines():
            if line.startswith("data: "):
                import json as _j

                d = _j.loads(line[6:])
                if "thread_id" in d:
                    tid = d["thread_id"]
        assert tid
        threads = client.get("/api/threads").json()["threads"]
        t = next(t for t in threads if t["id"] == tid)
        assert t["title"] == "帮我规划求职时间线"


def test_chat_touches_existing_thread_and_reuses_id(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/threads", json={"title": "已有会话"})
        tid = r.json()["id"]
        r2 = client.post("/api/chat", json={"message": "你好", "thread_id": tid})
        assert r2.status_code == 200
        assert tid in r2.text
        # thread 仍存在且 updated_at 更新
        threads = client.get("/api/threads").json()["threads"]
        t = next(t for t in threads if t["id"] == tid)
        assert t["title"] == "已有会话"


def test_chat_done_carries_usage_and_emotion(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "今天天气怎么样", "thread_id": "wx1"})
        assert r.status_code == 200
        done = [l for l in r.text.splitlines() if l.startswith("event: done")]
        assert done
        for i, line in enumerate(r.text.splitlines()):
            if line.startswith("event: done"):
                import json as _j

                payload = _j.loads(r.text.splitlines()[i + 1][6:])
                assert payload["thread_id"] == "wx1"
                assert "emotion" in payload
                assert "usage" in payload  # FakeChatModel 无 usage → None，但字段必在


def test_legacy_thread_id_registered_not_regenerated(tmp_path):
    """旧 thread_id（外部传入 key）应原样注册，不得重新生成。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "hello", "thread_id": "alice::legacy"})
        assert r.status_code == 200
        assert "alice::legacy" in r.text
