"""auth.py · Phase 4a 多用户鉴权：本地用户库（JSON + PBKDF2）+ JWT（HS256）。

端点由 main.py 挂载：
  POST /api/auth/register  {username, password}
  POST /api/auth/login     {username, password} → {token}
鉴权开启（settings.auth_enabled=True）后，/api/chat 需 Authorization: Bearer <token>。

安全说明（作品集如实标注）：本地开发实现——密码经 PBKDF2-HMAC-SHA256
（10 万次迭代 + 随机盐）哈希落盘，不存明文；JWT 用 settings.jwt_secret 签名。
生产环境应换 HTTPS + 正规用户体系（如 OAuth/OIDC）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt

from .config import settings

_ITERATIONS = 100_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _ITERATIONS
    ).hex()


class UserStore:
    """JSON 用户库：{username: {salt, hash, created_at}}。原子写入。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._users: dict = {}
        if self.path.exists():
            try:
                self._users = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._users = {}

    def register(self, username: str, password: str) -> None:
        username = username.strip().lower()
        if not username or not password:
            raise HTTPException(400, "用户名和密码不能为空")
        if username in self._users:
            raise HTTPException(409, "用户名已存在")
        if len(password) < 4:
            raise HTTPException(400, "密码至少 4 位")
        salt = secrets.token_hex(16)
        self._users[username] = {
            "salt": salt,
            "hash": _hash(password, salt),
            "created_at": time.time(),
        }
        self._save()

    def verify(self, username: str, password: str) -> bool:
        username = username.strip().lower()
        rec = self._users.get(username)
        if not rec:
            return False
        return hmac.compare_digest(_hash(password, rec["salt"]), rec["hash"])

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._users, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)


def create_token(username: str) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + settings.jwt_expire_days * 86400,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return str(payload["sub"])
    except JWTError:
        raise HTTPException(401, "登录态无效或已过期")


async def current_user(authorization: str | None = Header(default=None)) -> str | None:
    """FastAPI 依赖：开启鉴权时校验 Bearer token 并返回用户名。"""
    if not settings.auth_enabled:
        return None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "需要登录（Authorization: Bearer <token>）")
    return decode_token(authorization[7:])
