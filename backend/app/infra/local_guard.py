"""本机 API 访问守卫（安全边界）：Host/Origin 白名单 + 进程级随机 token。

威胁模型（本机回环服务）：
- 浏览器里的任意网页都能向 ``127.0.0.1:8000`` 发请求。真正危险的是 **CORS 简单请求**
  ——``multipart/form-data`` 表单上传不触发预检，请求会真实到达并被服务端执行
  （``POST /api/plugins/import`` → 插件顶层 ``exec_module`` → 本机任意代码执行）。
- DNS rebinding：恶意页面把自己的域名解析到 127.0.0.1，从而把「跨站」变成「同源」，
  绕过 CORS 限制读取 ``/api/session-token`` 等接口 → 用 Host 白名单挡住。

三道防线（互相兜底，任一条生效即可断链）：
1. **Host 白名单**：只接受回环主机名（挡 DNS rebinding / 反代转发）。
2. **Origin 白名单**：带 Origin 且非本机来源 → 403（挡跨站表单与 fetch）。
   ``Origin: null``（``file://`` 壳渲染进程）放行——壳的写操作另有 token 兜底；
   但 ``/api/session-token`` 连 ``null`` 也拒绝，避免沙箱 iframe 取走 token。
3. **进程级随机 token**：``/api/*`` 的写方法（POST/PUT/PATCH/DELETE）必须携带
   ``X-Nuomi-Token``（或 ``Authorization: Bearer <token>``）。token 每次进程启动
   重新生成，可用 ``NUOMI_API_TOKEN`` 覆盖（测试/脚本固定用）。
   跨站页面拿不到它：``/api/session-token`` 拒绝非本机 Origin，且响应受 CORS 限制。

边界说明：token 只防「浏览器里的第三方页面」。本机其它进程本来就能读工作区文件
（API key 就明文躺在那里），本模块不以它们为防护对象，也不声称能做到。
"""

from __future__ import annotations

import json
import os
import secrets
from urllib.parse import urlsplit

from starlette.datastructures import Headers

from app.config import settings

TOKEN_HEADER = "x-nuomi-token"
TOKEN_PATH = "/api/session-token"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
NULL_ORIGIN = "null"

# 回环主机名（+ 测试用 TestClient 的默认 host，便于用例自带 base_url 之外的情形）
_DEFAULT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"})

_token: str | None = None


def api_token() -> str:
    """进程级 API token：``NUOMI_API_TOKEN`` 优先，否则随机生成（进程内缓存）。"""
    global _token
    if _token is None:
        env_token = (os.environ.get("NUOMI_API_TOKEN") or "").strip()
        _token = env_token if len(env_token) >= 8 else secrets.token_urlsafe(32)
    return _token


def reset_token_cache() -> None:
    """清空 token 缓存（测试用；正常进程不必调用）。"""
    global _token
    _token = None


def _env_set(name: str) -> frozenset[str]:
    raw = os.environ.get(name) or ""
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def allowed_hosts() -> frozenset[str]:
    """允许的 Host 主机名（``NUOMI_ALLOWED_HOSTS`` 可追加）。"""
    return _DEFAULT_HOSTS | _env_set("NUOMI_ALLOWED_HOSTS")


def header_hostname(host_header: str) -> str:
    """从 Host 头取出主机名（去掉端口；兼容 ``[::1]:8000`` 形式）。"""
    host = (host_header or "").strip()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def host_allowed(host_header: str) -> bool:
    return header_hostname(host_header) in allowed_hosts()


def origin_allowed(origin: str) -> bool:
    """Origin 是否为本机来源（含配置的 CORS 源与 ``NUOMI_ALLOWED_ORIGINS``）。

    仅接受 http/https 且主机名为本机（任意端口）：``http://127.0.0.1:8000``、
    ``http://localhost:5173`` 等放行；``http://evil.com``、``null`` 一律不放行。
    """
    candidate = (origin or "").strip()
    if not candidate:
        return False
    if candidate in settings.cors_origins or candidate in _env_set("NUOMI_ALLOWED_ORIGINS"):
        return True
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https"):
        return False
    return (parts.hostname or "") in allowed_hosts()


def requires_token(method: str, path: str) -> bool:
    """``/api/*`` 的写方法需要 token（读方法放行：SSE 长连接与静态资源不受影响）。"""
    return method.upper() in WRITE_METHODS and path.startswith("/api/")


def _presented_token(headers: Headers) -> str:
    direct = headers.get(TOKEN_HEADER)
    if direct:
        return direct.strip()
    auth = headers.get("authorization") or ""
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer":
        return value.strip()
    return ""


def token_matches(presented: str) -> bool:
    return bool(presented) and secrets.compare_digest(presented, api_token())


async def _deny(send, detail: str, status: int = 403) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class LocalGuardMiddleware:
    """纯 ASGI 中间件：只读请求头，不读/不改请求体（SSE 流式与上传不受影响）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        path = scope.get("path", "")
        method = scope.get("method", "")

        if not host_allowed(headers.get("host", "")):
            await _deny(send, "Host 不在本机白名单内（可能是 DNS rebinding 或跨机访问）")
            return

        origin = headers.get("origin")
        if origin is not None:
            # /api/session-token 最严格：file:// 的 null origin 也不放行
            strict = path == TOKEN_PATH
            if not origin_allowed(origin) and not (origin == NULL_ORIGIN and not strict):
                await _deny(send, "Origin 不在白名单内（跨站请求已拒绝）")
                return

        if requires_token(method, path) and not token_matches(_presented_token(headers)):
            await _deny(
                send,
                "缺少或无效的 X-Nuomi-Token（本机写操作需要 token，"
                f"可从同源 GET {TOKEN_PATH} 获取；shell 与 curl 脚本需显式携带）",
            )
            return

        await self.app(scope, receive, send)
