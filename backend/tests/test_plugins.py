"""Phase 4d+ · 统一插件管理 API：清单 / 启停 / 程序插件（voice-input、team）。"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import build_app

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "nuomi" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
        users_file=str(tmp_path / "users.json"),
    )


def test_plugin_list_groups(tmp_path):
    """v0.6：能力面板视图——每个插件展示它贡献了什么（技能/工具/服务/事件），不再有 type/kind。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        body = client.get("/api/plugins").json()
        by_name = {p["name"]: p for p in body["plugins"]}
        assert all(p["enabled"] for p in body["plugins"])
        # 能力插件：贡献技能 + 工具
        assert "memory" in by_name["memory"]["contributions"]["skills"]
        assert "memory_write" in by_name["memory"]["contributions"]["tools"]
        # MCP/语音等能力插件：只贡献工具
        assert "notes_add" in by_name["mcp-notes"]["contributions"]["tools"]
        # 程序插件：贡献服务/事件（不再按类型区分，按贡献展示）
        assert "voice_input" in by_name["voice-input"]["contributions"]["services"]
        assert "response_done" in by_name["mood"]["contributions"]["events"]


def test_toggle_voice_input_program_plugin(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/plugins/voice-input/toggle").json()
        assert r["enabled"] is False and r["rebuilt"] is False
        body = client.get("/api/plugins").json()
        assert next(p for p in body["plugins"] if p["name"] == "voice-input")["enabled"] is False
        assert app.state.plugin_settings["voice_input"]["enabled"] is False
        # 翻回开
        client.post("/api/plugins/voice-input/toggle")


def test_toggle_skill_removes_tools_and_rebuilds(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        before = {t.name for t in app.state.tools}
        assert "memory_write" in before
        r = client.post("/api/plugins/memory/toggle").json()
        assert r["enabled"] is False and r["rebuilt"] is True
        after = {t.name for t in app.state.tools}
        assert "memory_write" not in after
        assert "get_current_time" in after  # 其他插件不受影响
        # Agent 已重建且仍可对话
        chat = client.post("/api/chat", json={"message": "你好", "thread_id": "plug-1"})
        assert chat.status_code == 200
        # 重新启用
        r2 = client.post("/api/plugins/memory/toggle").json()
        assert r2["enabled"] is True
        assert "memory_write" in {t.name for t in app.state.tools}


def test_toggle_team_plugin_controls_supervisor(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        # 默认团队启用
        assert app.state.supervisor is not None
        info = client.get("/api/supervisor/info").json()
        assert info["enabled"] is True and "companion" in info["agents"]
        # 停用：退化为单 Agent
        r = client.post("/api/plugins/team/toggle").json()
        assert r["enabled"] is False
        assert app.state.supervisor is None
        info2 = client.get("/api/supervisor/info").json()
        assert info2["enabled"] is False
        # 单 Agent 聊天正常
        chat = client.post("/api/chat", json={"message": "你好", "thread_id": "t-1"})
        assert chat.status_code == 200
        # 重新启用：Supervisor 恢复
        r2 = client.post("/api/plugins/team/toggle").json()
        assert r2["enabled"] is True
        assert app.state.supervisor is not None


def test_toggle_unknown_plugin_404(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/plugins/nope/toggle").status_code == 404
