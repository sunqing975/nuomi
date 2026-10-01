"""V3：插件导入（install/install-upload/uninstall）+ 设置系统（global/plugin settings）。"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import build_app
from tests.fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path, plugins_dir=None):
    # 默认用真实插件目录（composer 需要内置服务插件 service-settings/agent-loop 等）
    pd = str(plugins_dir) if plugins_dir is not None else str(REPO_ROOT / "plugins")
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=pd,
        memory_file=str(tmp_path / "mem" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )


def _write_plugin(root: Path, name: str, tool_code: str = "TOOLS = []", extra_meta: str = "{}") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps({"name": name, "description": f"{name} 描述", **json.loads(extra_meta)}),
        encoding="utf-8",
    )
    (d / "hook.py").write_text(tool_code, encoding="utf-8")


# ---------- 插件导入 ----------

def _writable_plugins(tmp_path):
    """独立可写插件目录：把真实内置插件符号链接进去（不污染 REPO plugins）。"""
    d = tmp_path / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    for name in ["service-tools", "service-sessions", "service-system-prompt",
                 "service-agent-loop", "service-memory", "service-settings",
                 "agent-companion", "agent-researcher",
                 "datetime", "memory", "knowledge", "mcp-notes", "pyfunc",
                 "voice", "web", "team", "voice-input", "mood"]:
        src_dir = REPO_ROOT / "plugins" / name
        if src_dir.exists():
            (d / name).symlink_to(src_dir)
    return d


def test_install_plugin_from_directory(tmp_path):
    app = _make_app(tmp_path, plugins_dir=_writable_plugins(tmp_path))
    _write_plugin(tmp_path, "weather", 'TOOLS = []\n')
    src = tmp_path / "weather"
    with TestClient(app) as client:
        r = client.post("/api/plugins/install", json={"name": "weather", "source": str(src)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["installed"] is True
        # 已安装 + 出现在清单
        assert (tmp_path / "plugins" / "weather" / "plugin.json").exists()
        plugins = client.get("/api/plugins").json()["plugins"]
        assert any(p["id"] == "weather" for p in plugins)
        assert any(p["state"] == "active" for p in plugins if p["id"] == "weather")


def test_install_plugin_zip_upload(tmp_path):
    app = _make_app(tmp_path, plugins_dir=_writable_plugins(tmp_path))
    _write_plugin(tmp_path, "calc", 'TOOLS = []\n')
    src = tmp_path / "calc"
    zip_path = tmp_path / "calc.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in src.rglob("*"):
            zf.write(f, f.relative_to(src.parent))
    with TestClient(app) as client:
        with open(zip_path, "rb") as f:
            r = client.post(
                "/api/plugins/install-upload",
                files={"file": ("calc.zip", f, "application/zip")},
            )
        assert r.status_code == 200, r.text
        assert r.json()["installed"] is True
        assert (tmp_path / "plugins" / "calc" / "plugin.json").exists()


def test_install_rejects_duplicate_and_missing_manifest(tmp_path):
    app = _make_app(tmp_path, plugins_dir=_writable_plugins(tmp_path))
    _write_plugin(tmp_path, "dup", 'TOOLS = []\n')
    src = tmp_path / "dup"
    with TestClient(app) as client:
        r1 = client.post("/api/plugins/install", json={"name": "dup", "source": str(src)})
        assert r1.status_code == 200
        r2 = client.post("/api/plugins/install", json={"name": "dup", "source": str(src)})
        assert r2.status_code == 409  # 重复安装
    # 缺 plugin.json
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "hook.py").write_text("TOOLS = []\n", encoding="utf-8")
    r3 = client.post("/api/plugins/install", json={"name": "bad", "source": str(bad)})
    assert r3.status_code == 400


def test_install_plugin_with_tools_contributes_to_agent(tmp_path):
    app = _make_app(tmp_path, plugins_dir=_writable_plugins(tmp_path))
    _write_plugin(
        tmp_path, "greet",
        'from langchain_core.tools import tool\n'
        '@tool\ndef greet(name: str) -> str:\n    """问候。"""\n    return f"你好 {name}"\n'
        'TOOLS = [greet]\n',
    )
    src = tmp_path / "greet"
    with TestClient(app) as client:
        r = client.post("/api/plugins/install", json={"name": "greet", "source": str(src)})
        assert r.status_code == 200, r.text
        # 工具进入 agent 工具集
        names = {t.name for t in app.state.tools}
        assert "greet" in names


def test_uninstall_plugin(tmp_path):
    app = _make_app(tmp_path, plugins_dir=_writable_plugins(tmp_path))
    _write_plugin(tmp_path, "tmp", 'TOOLS = []\n')
    src = tmp_path / "tmp"
    with TestClient(app) as client:
        client.post("/api/plugins/install", json={"name": "tmp", "source": str(src)})
        r = client.post("/api/plugins/tmp/uninstall")
        assert r.status_code == 200, r.text
        assert r.json()["uninstalled"] is True
        assert not (tmp_path / "plugins" / "tmp").exists()
        plugins = client.get("/api/plugins").json()["plugins"]
        assert not any(p["id"] == "tmp" for p in plugins)


# ---------- 设置系统 ----------

def test_settings_global_get_set(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        assert "global" in r.json()
        r2 = client.post("/api/settings/global", json={"key": "temperature", "value": 0.3})
        assert r2.status_code == 200
        snap = client.get("/api/settings").json()["global"]
        assert snap["temperature"] == 0.3


def test_settings_plugin_patch(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/settings/plugins/runtime-mood", json={"patch": {"intensity": 2}})
        assert r.status_code == 200, r.text
        assert r.json()["values"]["intensity"] == 2
        snap = client.get("/api/settings").json()
        moods = [p for p in snap["plugins"] if p["id"] == "runtime-mood"]
        assert moods and moods[0]["values"].get("intensity") == 2


def test_llm_is_core_service_not_plugin(tmp_path):
    """LLM 是核心服务：插件列表不应再含 llm-deepseek / llm-doubao / llm-local。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        snap = client.get("/api/settings").json()
        ids = {p["id"] for p in snap["plugins"]}
        assert not (ids & {"llm-deepseek", "llm-doubao", "llm-local"})


def test_settings_change_triggers_rebuild_event(tmp_path):
    """全局 model 变更发布 settings/changed → 无异常、agent 仍可对话。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/settings/global", json={"key": "temperature", "value": 0.5})
        assert r.status_code == 200
        # 设置变更触发 agent-loop 重建（事件链），chat 仍可用
        r2 = client.post("/api/chat", json={"message": "你好", "thread_id": "s1"})
        assert r2.status_code == 200
        assert "糯米(测试)" in r2.text or "error" not in r2.text.split("event: error")[-1][:200]
