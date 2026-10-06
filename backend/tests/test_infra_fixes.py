"""基础设施修复的回归测试（2026-10-06 第 2 批）。

锁两件"坏了很难查"的事：
1. **``db.connect()`` 必须真正关闭连接**。``sqlite3.Connection`` 自带的 ``with`` 只提交/回滚，
   不关闭 —— 全仓 50+ 处 ``with db.connect() as conn:`` 曾经每次泄漏一个 fd，而服务是整天常驻的。
2. **数字人事件队列满时要丢最旧并计数**（原先静默丢最新、无日志），且长连接要有心跳占位。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3

import pytest

from app.infra.avatar_events import QUEUE_MAXSIZE, PetEventBus
from app.storage.db import connect

# ---------- 连接生命周期 ----------


def _open_fd_count() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.fixture
def own_db(tmp_path, monkeypatch):
    """把数据根指向 tmp_path：这些用例要**写行**，不能污染会话级共享库。

    （第一版直接写共享 nuomi.db，结果给别的用例留下一个没有目录的插件行，
    把 test_plugin_import 的"注册表 == DB"断言搞挂了。）
    """
    from app.config import settings
    from app.storage.db import init_db

    monkeypatch.setattr(settings, "nuomi_home", str(tmp_path), raising=False)
    init_db()
    return tmp_path


def test_connect_closes_connection(own_db) -> None:
    """200 次 with connect() 之后 fd 数不应增长（修复前每次 +1）。"""
    for _ in range(5):  # 预热
        with connect() as c:
            c.execute("SELECT count(*) FROM agents").fetchone()

    before = _open_fd_count()
    for _ in range(200):
        with connect() as c:
            c.execute("SELECT count(*) FROM agents").fetchone()
    after = _open_fd_count()

    assert after - before < 10, f"连接仍在泄漏：fd {before} → {after}"


def test_connect_commits_on_success(own_db) -> None:
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO plugins (plugin_id, name) VALUES ('t-commit', 'x')")
    with connect() as c:
        row = c.execute("SELECT name FROM plugins WHERE plugin_id='t-commit'").fetchone()
    assert row is not None and row["name"] == "x", "commit 语义丢了"


def test_connect_rolls_back_on_exception(own_db) -> None:
    with pytest.raises(RuntimeError), connect() as c:
        c.execute("INSERT OR REPLACE INTO plugins (plugin_id, name) VALUES ('t-rb', 'y')")
        raise RuntimeError("boom")
    with connect() as c:
        row = c.execute("SELECT name FROM plugins WHERE plugin_id='t-rb'").fetchone()
    assert row is None, "异常路径未回滚（rollback 语义丢了）"


def test_connect_returns_row_factory(own_db) -> None:
    with connect() as c:
        assert c.row_factory is sqlite3.Row
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# ---------- 事件总线 ----------


def test_stream_emits_keepalive_placeholder_when_idle() -> None:
    bus = PetEventBus()

    async def _read_three():
        out = []
        async for ev in bus.stream(keepalive=0.05):
            out.append(ev)
            if len(out) >= 3:
                break
        return out

    assert asyncio.run(asyncio.wait_for(_read_three(), timeout=3)) == [None, None, None]


def test_stream_keeps_generator_alive_across_keepalives() -> None:
    """心跳超时不能把生成器终结掉（wait_for 必须在生成器内部）。"""
    bus = PetEventBus()

    async def _scenario():
        agen = bus.stream(keepalive=0.05).__aiter__()
        assert await agen.__anext__() is None  # 先来一次心跳
        bus.publish_status("thinking")  # 心跳之后仍能收到真实事件
        return await agen.__anext__()

    ev = asyncio.run(asyncio.wait_for(_scenario(), timeout=3))
    assert ev == {"type": "avatar_status", "status": "thinking"}


def test_queue_full_drops_oldest_and_counts() -> None:
    """队列满：丢最旧保最新，并计数（不再静默）。"""
    bus = PetEventBus()

    async def _scenario():
        # 建一个只注册不消费的订阅者
        agen = bus.stream(keepalive=None).__aiter__()
        task = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0)  # 让订阅注册生效
        for i in range(QUEUE_MAXSIZE + 7):
            bus.publish_status(f"s{i}")
        task.cancel()
        return bus.dropped_events

    dropped = asyncio.run(asyncio.wait_for(_scenario(), timeout=3))
    assert dropped == 7, f"应记录 7 次丢弃，实际 {dropped}"


def test_publish_raw_keeps_payload_type() -> None:
    """publish_raw 不强制 type（资源变更事件自带 type）。"""
    bus = PetEventBus()

    async def _scenario():
        agen = bus.stream(keepalive=None).__aiter__()
        task = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0)
        bus.publish_raw({"type": "avatar_animations_changed", "reason": "delete"})
        return await task

    assert asyncio.run(asyncio.wait_for(_scenario(), timeout=3)) == {
        "type": "avatar_animations_changed",
        "reason": "delete",
    }
