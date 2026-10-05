"""Langfuse 观测配置 API 测试（隔离 NUOMI_HOME；test 端点 mock 掉真实网络）。"""

from __future__ import annotations

from unittest.mock import patch

from app.infra.harness.langfuse_store import path as langfuse_path


def test_get_langfuse_default_empty(client):
    """未配置时：enabled=false、secret 为空（默认 host 兜底）。"""
    r = client.get("/api/settings/langfuse")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False
    assert data["secret_key"] == ""
    assert data["host"]  # 默认 https://cloud.langfuse.com


def test_put_langfuse_requires_host(client):
    r = client.put("/api/settings/langfuse", json={"enabled": True, "host": "", "public_key": "pk-x", "secret_key": "sk-y"})
    assert r.status_code == 400
    assert "Host" in r.json()["detail"]


def test_put_langfuse_requires_public_key(client):
    r = client.put("/api/settings/langfuse", json={"enabled": True, "host": "https://x.langfuse.com", "public_key": "", "secret_key": "sk-y"})
    assert r.status_code == 400
    assert "Public Key" in r.json()["detail"]


def test_put_langfuse_enabled_requires_secret(client):
    r = client.put("/api/settings/langfuse", json={"enabled": True, "host": "https://x.langfuse.com", "public_key": "pk-x", "secret_key": ""})
    assert r.status_code == 400
    assert "Secret Key" in r.json()["detail"]


def test_put_langfuse_saves_and_masks(client):
    """保存成功：secret 落盘、GET 脱敏、且不触发真实网络（凭据无效时 tracer 停用）。"""
    r = client.put(
        "/api/settings/langfuse",
        json={"enabled": False, "host": "https://x.langfuse.com", "public_key": "pk-abc", "secret_key": "sk-abcdefgh1234"},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # 落盘校验
    import json

    saved = json.loads(langfuse_path().read_text(encoding="utf-8"))
    assert saved["secret_key"] == "sk-abcdefgh1234"
    assert saved["public_key"] == "pk-abc"

    # GET 脱敏
    data = client.get("/api/settings/langfuse").json()
    assert data["secret_key"] == "sk-a***1234"


def test_put_langfuse_masked_secret_keeps_original(client):
    """前端回写脱敏串时保持原值（不把 *** 当真实 key 存）。"""
    client.put(
        "/api/settings/langfuse",
        json={"enabled": False, "host": "https://x.langfuse.com", "public_key": "pk-abc", "secret_key": "sk-abcdefgh1234"},
    )
    r = client.put(
        "/api/settings/langfuse",
        json={"enabled": True, "host": "https://x.langfuse.com", "public_key": "pk-abc", "secret_key": "sk-a***1234"},
    )
    assert r.status_code == 200
    import json

    saved = json.loads(langfuse_path().read_text(encoding="utf-8"))
    assert saved["secret_key"] == "sk-abcdefgh1234"


def test_test_langfuse_invalid_credentials(client):
    """凭据错误 → 401（mock auth_check 为 False，不真连网）。"""
    with patch("langfuse.Langfuse") as mock_cls:
        mock_cls.return_value.auth_check.return_value = False
        r = client.post(
            "/api/settings/langfuse/test",
            json={"host": "https://x.langfuse.com", "public_key": "pk-bad", "secret_key": "sk-bad"},
        )
    assert r.status_code == 401
    assert "凭据校验未通过" in r.json()["detail"]


def test_test_langfuse_valid_credentials(client):
    """凭据有效 → 200（mock auth_check 为 True）。"""
    with patch("langfuse.Langfuse") as mock_cls:
        mock_cls.return_value.auth_check.return_value = True
        r = client.post(
            "/api/settings/langfuse/test",
            json={"host": "https://x.langfuse.com", "public_key": "pk-good", "secret_key": "sk-good"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_test_langfuse_missing_fields(client):
    r = client.post("/api/settings/langfuse/test", json={"host": "", "public_key": "", "secret_key": ""})
    assert r.status_code == 400


def test_test_langfuse_masked_secret_reuses_stored(client):
    """测试时传脱敏串：复用已存 secret_key 做校验。"""
    client.put(
        "/api/settings/langfuse",
        json={"enabled": False, "host": "https://x.langfuse.com", "public_key": "pk-abc", "secret_key": "sk-abcdefgh1234"},
    )
    with patch("langfuse.Langfuse") as mock_cls:
        mock_cls.return_value.auth_check.return_value = True
        r = client.post(
            "/api/settings/langfuse/test",
            json={"host": "https://x.langfuse.com", "public_key": "pk-abc", "secret_key": "sk-a***1234"},
        )
    assert r.status_code == 200
    # 传给 SDK 的是原值，不是脱敏串
    _, kwargs = mock_cls.call_args
    assert kwargs["secret_key"] == "sk-abcdefgh1234"
