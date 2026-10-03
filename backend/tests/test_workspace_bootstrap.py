"""阶段 B/C/D 回归测试：工作区树、项目自动建目录、bootstrap、token 守卫。"""

from __future__ import annotations

from pathlib import Path

from app.main import build_app
from fastapi.testclient import TestClient


def _make_app(tmp_path: Path, workspace_dir: str | None = None, **kw):
    """构造 app；默认工作区 = conftest 的 NUOMI_WORKSPACE 临时目录。
    需要指定工作区时，清掉 env 覆盖（保证 build_app 的 workspace_dir 注入生效）。"""
    return build_app(
        db_path=str(tmp_path / "nuomi.db"),
        memory_file=str(tmp_path / "nuomi.db"),
        workspace_dir=workspace_dir,
        **kw,
    )


def test_workspace_tree_lists_only_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("NUOMI_WORKSPACE", raising=False)
    monkeypatch.delenv("WORKSPACE_DIR", raising=False)
    ws = tmp_path / "ws"
    (ws / "项目甲").mkdir(parents=True)
    (ws / "项目甲" / "笔记.md").write_text("hi", encoding="utf-8")
    (ws / "项目甲" / ".hidden").write_text("x", encoding="utf-8")
    (ws / "项目甲" / "node_modules").mkdir()
    (ws / "node_modules" / "pkg").mkdir(parents=True)  # 顶层依赖目录也应跳过
    (ws / ".DS_Store").write_text("x", encoding="utf-8")
    app = _make_app(tmp_path, workspace_dir=str(ws))
    with TestClient(app) as client:
        r = client.get("/api/workspace/tree")
    assert r.status_code == 200
    data = r.json()
    assert data["root"] == str(ws.resolve())
    names = [e["name"] for e in data["entries"]]
    assert names == ["项目甲"], f"应只列出可见目录，实际 {names}"
    child = data["entries"][0]["children"]
    assert [c["name"] for c in child] == ["笔记.md"]
    assert all(c["type"] == "file" for c in child)


def test_create_project_auto_makes_workspace_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("NUOMI_WORKSPACE", raising=False)
    monkeypatch.delenv("WORKSPACE_DIR", raising=False)
    ws = tmp_path / "ws"
    app = _make_app(tmp_path, workspace_dir=str(ws))
    with TestClient(app) as client:
        r = client.post("/api/projects", json={"name": "求职作品集"})
        assert r.status_code == 200
        proj = r.json()
        d = Path(proj["directory"])
        assert d.is_dir(), "应自动创建工作区目录"
        assert d.parent.resolve() == ws.resolve()
        # 项目名带非法字符 → 目录名安全化
        r2 = client.post("/api/projects", json={"name": "a/b:测试"})
        assert r2.status_code == 200
        assert Path(r2.json()["directory"]).is_dir()
        # 同名项目不重复建目录（幂等）
        r3 = client.post("/api/projects", json={"name": "求职作品集"})
        assert r3.status_code == 200
        assert r3.json()["id"] == proj["id"]
        # 恶意项目名拒绝
        assert client.post("/api/projects", json={"name": ".."}).status_code == 400


def test_bootstrap_setup_required_on_fresh_env(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/bootstrap")
        assert r.status_code == 200
        body = r.json()
        assert body["setup_required"] is True
        assert body["llm_configured"] is False

        # 保存工作区路径 → 返回 ok 且目录已创建
        ws = tmp_path / "my-workspace"
        r2 = client.post("/api/bootstrap/workspace", json={"workspace": str(ws)})
        assert r2.status_code == 200
        assert Path(r2.json()["workspace"]).is_dir()
        # settings 已持久化（lifespan 恢复逻辑读它）
        r3 = client.get("/api/settings")
        assert r3.json()["global"].get("workspace_dir") == str(ws)


def test_token_guard_disabled_in_dev(tmp_path):
    """dev（非 frozen、无 NUOMI_TOKEN）：不校验，vite 代理不受影响。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 200
        assert client.get("/api/health").status_code == 200


def test_token_guard_enforced_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("NUOMI_TOKEN", "test-token-123")
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/health").status_code == 200  # health 放行
        ok = client.get("/api/projects", headers={"X-Nuomi-Token": "test-token-123"})
        assert ok.status_code == 200
