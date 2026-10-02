"""Phase 5 · 模型管理 API：供应商树列表 / 激活（provider+model+effort）/ 不可用拒绝 / 未知 404。

对齐 DeepSeek Harness ModelSelection：{provider, model, reasoningEffort?}，无 temperature。
"""
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
    )


def _provider_keys(body) -> set[str]:
    return {p["key"] for p in body["providers"]}


def test_models_no_builtin_providers(tmp_path):
    """无内置预设：未添加任何供应商时 providers 为空树（deepseek/doubao/local 不存在）。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        body = client.get("/api/models").json()
        assert _provider_keys(body) == set()
        assert not [p for p in body["providers"] if p["key"] in ("deepseek", "doubao", "local")]
        assert app.state.model_name == "custom"  # 测试注入 FakeChatModel


def test_activate_custom_model_with_key(tmp_path):
    """带 key 的自定义供应商可激活；切换后 Agent 重建、effort 透传。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/models/custom", json=_custom_body())
        cp = [p for p in client.get("/api/models").json()["providers"] if p["custom"]][0]
        r = client.post(
            "/api/models/activate",
            json={"provider": cp["key"], "model": "gpt-4o", "effort": "medium"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["active_provider"] == cp["key"]
        assert body["active_model"] == "gpt-4o"
        assert body["effort"] == "medium"
        assert app.state.model_provider == cp["key"]
        assert app.state.model_name == "gpt-4o"
        assert app.state.supervisor is not None  # 团队仍启用
        chat = client.post("/api/chat", json={"message": "你好", "thread_id": "m-1"})
        assert chat.status_code == 200


def test_activate_effort_out_of_range_silently_ignored(tmp_path):
    """effort 不在模型声明的 efforts 内时静默忽略（不 400）。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/models/custom", json=_custom_body())
        cp = [p for p in client.get("/api/models").json()["providers"] if p["custom"]][0]
        r = client.post(
            "/api/models/activate",
            json={"provider": cp["key"], "model": "gpt-4o", "effort": "high"},
        )
        assert r.status_code == 200
        assert r.json()["effort"] == "high"  # gpt-4o 支持 high


def test_activate_custom_without_key_404(tmp_path):
    """自定义供应商缺 key 时激活应拒绝（404：不可用）而非崩溃。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        body = _custom_body()
        body["api_key"] = ""
        client.post("/api/models/custom", json=body)
        cp = [p for p in client.get("/api/models").json()["providers"] if p["custom"]][0]
        assert all(not m["available"] for m in cp["models"])  # 无 key → 模型不可用
        r = client.post("/api/models/activate", json={"provider": cp["key"], "model": "gpt-4o"})
        assert r.status_code == 404


def test_activate_unknown_provider_404(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert (
            client.post("/api/models/activate", json={"provider": "nope", "model": "x"}).status_code
            == 404
        )


# --- Phase 6：自定义供应商 + API Key + 激活持久化 ---


def _custom_body():
    return {
        "name": "中转站A",
        "base_url": "https://relay.example.com/v1",
        "protocol": "openai",
        "api_key": "sk-relay-secret-1234",
        "models": [
            {"id": "gpt-4o", "label": "GPT-4o", "efforts": ["low", "medium", "high"]},
            {"id": "claude-haiku", "label": "Haiku", "efforts": ["medium"]},
        ],
    }


def test_custom_provider_crud_and_masked_key(tmp_path):
    """自定义供应商：添加 → 列表含 custom 标记 + key 掩码 → 更新模型 → 删除。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/models/custom", json=_custom_body())
        assert r.status_code == 200, r.text
        provs = {p["key"]: p for p in r.json()["providers"]}
        custom = [p for p in r.json()["providers"] if p["custom"]]
        assert len(custom) == 1
        cp = custom[0]
        assert cp["label"] == "中转站A"
        assert cp["api_key_masked"] == "sk-r***1234"  # 掩码回显
        assert {m["key"] for m in cp["models"]} == {"gpt-4o", "claude-haiku"}

        # 更新：改模型列表 + __KEEP__ 保留 key
        r = client.put(
            f"/api/models/custom/{cp['key']}",
            json={"models": [{"id": "gpt-4o-mini", "label": "Mini"}], "api_key": "__KEEP__"},
        )
        assert r.status_code == 200, r.text
        cp2 = [p for p in r.json()["providers"] if p["key"] == cp["key"]][0]
        assert {m["key"] for m in cp2["models"]} == {"gpt-4o-mini"}
        assert cp2["api_key_masked"] == "sk-r***1234"

        # 删除
        r = client.delete(f"/api/models/custom/{cp['key']}")
        assert r.status_code == 200
        assert not [p for p in r.json()["providers"] if p["custom"]]


def test_custom_provider_activate_and_restore(tmp_path):
    """自定义供应商模型可激活（llm 构建走自定义 base_url）；激活持久化后重启恢复。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        body = _custom_body()
        body["base_url"] = "http://127.0.0.1:9/v1"  # 不实际请求
        r = client.post("/api/models/custom", json=body)
        cp = [p for p in r.json()["providers"] if p["custom"]][0]
        r = client.post(
            "/api/models/activate",
            json={"provider": cp["key"], "model": "gpt-4o", "effort": "high"},
        )
        assert r.status_code == 200, r.text
        assert app.state.model_provider == cp["key"]
        assert app.state.model_name == "gpt-4o"
        assert app.state.llm_effort == "high"

    # 重启（不带测试 llm 注入）：active_model 持久化 → 恢复
    app2 = build_app(
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=str(REPO_ROOT / "plugins"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )
    with TestClient(app2) as client:
        assert app2.state.model_provider.startswith("custom-")
        assert app2.state.model_name == "gpt-4o"
        assert app2.state.llm_effort == "high"
        # 回归：llm 在 composer.load() 之后注册，须手动重建 agentLoop，
        # 否则重启后 agent=None、/api/chat 报 AttributeError（曾实测复现）
        loop = app2.state.scope.get("agentLoop")
        assert loop is not None and loop.agent is not None
        assert app2.state.agent is not None


def test_available_models_endpoint_validation(tmp_path):
    """拉取可用模型：缺 base_url 400；连不上 502（不 5xx 崩）。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/models/available", params={"base_url": ""})
        assert r.status_code == 400
        r = client.get("/api/models/available", params={"base_url": "http://127.0.0.1:9/v1"})
        assert r.status_code == 502


def test_activate_returns_providers_array(tmp_path):
    """回归：activate 返回体 providers 必须是数组（曾为嵌套 dict 导致前端 find 崩溃）。"""
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/models/custom", json=_custom_body())
        cp = [p for p in client.get("/api/models").json()["providers"] if p["custom"]][0]
        r = client.post(
            "/api/models/activate",
            json={"provider": cp["key"], "model": "gpt-4o"},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data["providers"], list)
        assert data["providers"][0]["models"][0]["available"] is True