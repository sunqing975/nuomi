"""本机访问守卫测试（``app/infra/local_guard.py``）。

覆盖三道防线：Host 白名单、Origin 白名单、写操作 token。这些是安全边界，
必须有回归保护——守卫一旦被改松，本机 RCE（multipart 插件导入）会重新打开。

约定：``client`` fixture 默认带 ``X-Nuomi-Token``；用空值覆盖即可模拟"无 token"，
不必另建一个 TestClient。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.infra.local_guard import (
    api_token,
    header_hostname,
    host_allowed,
    origin_allowed,
    requires_token,
)

NO_TOKEN = {"X-Nuomi-Token": ""}


# ---------- 纯函数 ----------


def test_header_hostname_handles_port_and_ipv6() -> None:
    assert header_hostname("127.0.0.1:8000") == "127.0.0.1"
    assert header_hostname("localhost") == "localhost"
    assert header_hostname("[::1]:8000") == "[::1]"
    assert header_hostname("") == ""


def test_host_allowed_only_loopback() -> None:
    assert host_allowed("127.0.0.1:8000")
    assert host_allowed("localhost:5173")
    assert host_allowed("[::1]:8000")
    assert not host_allowed("evil.com:8000")
    assert not host_allowed("192.168.1.5:8000")


def test_origin_allowed_only_local() -> None:
    assert origin_allowed("http://127.0.0.1:8000")
    assert origin_allowed("http://localhost:5173")
    assert origin_allowed("http://127.0.0.1:5173")
    assert not origin_allowed("https://evil.com")
    assert not origin_allowed("http://evil.com")
    assert not origin_allowed("null")  # file:// —— 全局放行由中间件单独判定
    assert not origin_allowed("")


def test_no_acao_for_dev_origins_by_default(client: TestClient) -> None:
    """CORS 默认留空：跨源请求拿不到 ACAO，本机 5173 也不例外。

    2026-10-15 审计发现的口子——``cors_origins`` 曾默认含 ``http://localhost:5173``，
    实测带 ``Origin: http://localhost:5173`` 打 ``GET /api/session-token`` 会回显
    ``access-control-allow-origin``：占住该端口的任意本机页面可跨源读走写操作 token，
    再 ``POST /api/plugins/import`` 即本机代码执行。dev 走 vite proxy、生产是同源
    ``/console``，两条路都不需要跨源，所以默认清空（要开用 ``CORS_ORIGINS=[...]``）。
    """
    assert settings.cors_origins == []
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"):
        r = client.get("/api/session-token", headers={"Origin": origin})
        assert r.status_code == 200, r.text  # 守卫仍认这是本机来源（读操作放行）
        assert "access-control-allow-origin" not in r.headers, origin


def test_requires_token_only_writes_under_api() -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert requires_token(method, "/api/agents")
    assert not requires_token("GET", "/api/agents")
    assert not requires_token("OPTIONS", "/api/agents")
    assert not requires_token("POST", "/console/")
    assert not requires_token("POST", "/openapi.json")


# ---------- 中间件（端到端） ----------


def test_write_without_token_rejected(client: TestClient) -> None:
    """写操作缺 token → 403（堵住 multipart 表单 CSRF / 插件导入 RCE）。"""
    r = client.post("/api/agents", json={"name": "x"}, headers=NO_TOKEN)
    assert r.status_code == 403
    assert "X-Nuomi-Token" in r.json()["detail"]


def test_write_with_token_accepted(client: TestClient) -> None:
    r = client.post("/api/agents", json={"name": "守卫生效专家"})
    assert r.status_code == 200
    assert r.json()["name"] == "守卫生效专家"


def test_write_with_bearer_token_accepted(client: TestClient) -> None:
    """脚本便利：Authorization: Bearer <token> 等价。"""
    r = client.post(
        "/api/agents",
        json={"name": "Bearer 专家"},
        headers={"X-Nuomi-Token": "", "Authorization": f"Bearer {api_token()}"},
    )
    assert r.status_code == 200


def test_read_does_not_require_token(client: TestClient) -> None:
    """读操作不需要 token：SSE 长连接与列表接口不受影响。"""
    assert client.get("/api/health", headers=NO_TOKEN).status_code == 200
    assert client.get("/api/agents", headers=NO_TOKEN).status_code == 200


def test_cross_site_origin_rejected(client: TestClient) -> None:
    """跨站 Origin → 403（即使把 token 也带上，Origin 不合法照样拒）。"""
    for path, kwargs in (
        ("/api/agents", {"json": {"name": "跨站"}}),
        ("/api/session-token", {}),
    ):
        r = client.request(
            "POST" if "json" in kwargs else "GET",
            path,
            headers={"Origin": "https://evil.com", "X-Nuomi-Token": api_token()},
            **kwargs,
        )
        assert r.status_code == 403, f"{path} 应拒绝跨站 Origin"
        assert "Origin" in r.json()["detail"]


def test_null_origin_write_requires_token(client: TestClient) -> None:
    """Origin: null（file:// 壳 / 沙箱 iframe）放行给壳，但必须带 token。

    —— 不带 token 的 null origin 写操作 = 沙箱 iframe 攻击，必须拒绝。
    """
    r = client.post(
        "/api/agents", json={"name": "沙箱 iframe"}, headers={**NO_TOKEN, "Origin": "null"}
    )
    assert r.status_code == 403

    r = client.post(
        "/api/agents",
        json={"name": "壳来源专家"},
        headers={"Origin": "null", "X-Nuomi-Token": api_token()},
    )
    assert r.status_code == 200


def test_session_token_endpoint_rejects_null_origin(client: TestClient) -> None:
    """token 端点比全局更严：连 null origin 也不放行（防沙箱 iframe 取走 token）。"""
    assert client.get("/api/session-token", headers={"Origin": "null"}).status_code == 403
    # 本机 origin / 无 origin 可取
    assert client.get("/api/session-token").status_code == 200
    assert (
        client.get("/api/session-token", headers={"Origin": "http://127.0.0.1:8000"}).status_code
        == 200
    )


def test_dns_rebinding_host_rejected(client: TestClient) -> None:
    """恶意域名解析到 127.0.0.1 时 Host 会是该域名 → 403。"""
    r = client.get("/api/health", headers={"Host": "evil.com:8000"})
    assert r.status_code == 403
    assert "Host" in r.json()["detail"]


def test_plugin_import_multipart_requires_token(client: TestClient) -> None:
    """真实 RCE 向量：multipart 插件导入（CORS 简单请求，不触发预检）。"""
    r = client.post(
        "/api/plugins/import",
        files={"file": ("evil.zip", b"PK\x03\x04", "application/zip")},
        headers=NO_TOKEN,
    )
    assert r.status_code == 403
