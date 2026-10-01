"""Phase 4a · 多用户：JWT 鉴权 + per-user 会话/记忆隔离。"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import UserStore, create_token, decode_token
from app.main import build_app

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _auth_app(tmp_path, auth=True):
    from app.config import settings

    old = settings.auth_enabled
    settings.auth_enabled = auth
    try:
        app = build_app(
            llm=FakeChatModel(),
            db_path=str(tmp_path / "t.sqlite"),
            skills_dir=str(REPO_ROOT / "plugins"),
            memory_file=str(tmp_path / "mem" / "nuomi" / "facts.json"),
            knowledge_store_type="lexical",
            knowledge_dir=str(tmp_path / "kb"),
            users_file=str(tmp_path / "users.json"),
        )
        with TestClient(app) as client:
            yield app, client
    finally:
        settings.auth_enabled = old


def test_user_store_register_and_verify(tmp_path):
    us = UserStore(tmp_path / "users.json")
    us.register("Alice", "pw1234")
    assert us.verify("alice", "pw1234")  # 大小写归一
    assert not us.verify("alice", "wrong")
    assert not us.verify("bob", "pw1234")


def test_token_roundtrip():
    t = create_token("alice")
    assert decode_token(t) == "alice"


def test_auth_chat_requires_login(tmp_path):
    with _auth_app(tmp_path) as (app, client):
        r = client.post("/api/chat", json={"message": "hi"})
        assert r.status_code == 401


def test_register_login_and_chat_with_token(tmp_path):
    from app.memory import get_store

    with _auth_app(tmp_path) as (app, client):
        assert client.post("/api/auth/register", json={"username": "alice", "password": "pw1234"}).status_code == 200
        assert client.post("/api/auth/register", json={"username": "alice", "password": "pw1234"}).status_code == 409
        tok = client.post("/api/auth/login", json={"username": "alice", "password": "pw1234"}).json()["token"]
        r = client.post("/api/chat", json={"message": "你好", "thread_id": "s1"}, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        # per-user 记忆库：alice 与 bob 是不同实例、不同文件
        sa, sb = get_store("alice"), get_store("bob")
        assert sa is not sb
        sa.add("偏好：燕麦拿铁不加糖")
        assert (tmp_path / "mem" / "alice" / "facts.json").exists()
        assert not (tmp_path / "mem" / "bob" / "facts.json").exists()


def test_thread_namespace_isolation(tmp_path):
    """同一 thread_id，不同用户走不同 checkpoint 键（互不可见）。"""
    with _auth_app(tmp_path) as (app, client):
        client.post("/api/auth/register", json={"username": "alice", "password": "pw1234"})
        client.post("/api/auth/register", json={"username": "bob", "password": "pw1234"})
        ta = client.post("/api/auth/login", json={"username": "alice", "password": "pw1234"}).json()["token"]
        tb = client.post("/api/auth/login", json={"username": "bob", "password": "pw1234"}).json()["token"]
        hd_a = {"Authorization": f"Bearer {ta}"}
        hd_b = {"Authorization": f"Bearer {tb}"}
        client.post("/api/chat", json={"message": "你好", "thread_id": "shared"}, headers=hd_a)
        client.post("/api/chat", json={"message": "你好", "thread_id": "shared"}, headers=hd_b)
        # checkpoint 里应有两个独立键：alice::shared 和 bob::shared
        keys = set()
        async def scan():
            for t in ["alice::shared", "bob::shared"]:
                tr = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": t}})
                if tr:
                    keys.add(t)
        asyncio.run(scan())
        assert keys == {"alice::shared", "bob::shared"}
