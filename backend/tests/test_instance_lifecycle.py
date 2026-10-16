"""实例生命周期与共享记忆后端（2026-10-16 补的回归测试）。

锁三件审计里被点名「无测试覆盖」的事：

1. **同一工作区的多个实例共用一份记忆后端**——``octop_harness.memory.store`` 按
   ``(namespace, backend, location)`` 在进程内共享 ``Memory``。nuomi 的
   ``manager.close()`` 有 15 处调用点（开关插件 / 存连接器 env / 改 Provider…），
   close-all 那一瞬间老实例可能仍在飞、新实例已经建好，两边都会写
   ``memory.sqlite``。断言它们指向**同一个**后端对象，而不是各开一份 SQLite 句柄。
2. **重建立刻成功且记忆不丢**——句柄没释放干净时，紧接着的重建会 ``database is
   locked`` 或读到空记忆。用「写一条 → close-all → 重建 → 读回」把这个行为锁住。
3. **close() 不许顺手清 Langfuse**——``manager.close()`` 的 docstring 特意写了这个
   坑（清了会让轨迹观测在本进程内永久失效，且毫无提示）。测试防回归。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from app.infra.harness.manager import manager


@pytest.fixture(autouse=True)
def _harness_logging() -> None:
    """把 harness 的文件日志收进临时数据根（等价 main lifespan 里的那次调用）。

    本模块直接构造 HarnessAgent、不走 ``client`` fixture，所以不会经过 lifespan。
    不显式配置的话 harness 默认写 ``~/.octop-harness/logs``——既破坏「单一数据根」，
    在限制写 HOME 的环境里（CI、沙箱）还会直接 ``PermissionError``。harness 的
    ``ensure_logging()`` 见到已有同包 handler 就复用，因此重复调用是安全的。
    """
    from app.infra.harness.config import configure_harness_logging

    configure_harness_logging()


def _instance(agent_id: str, *, name: str = "生命周期测试专家"):
    """按 nuomi 的正常入口建一个实例（不触发任何 LLM 调用，纯构造）。

    ``name`` 默认全部相同：记忆后端的共享键是 ``(namespace, backend, location)``，
    而 nuomi 没设 ``memory_namespace``，namespace 就取专家名。同一个专家（改名以外
    都一样）重建时才命中同一份记忆——这正是 close-all 重建期间新老实例并存的场景。
    """
    return manager.get_agent(
        agent_id,
        name=name,
        system_prompt="你是测试用的专家，只用于生命周期测试。",
    )


def test_two_live_instances_share_one_memory_backend() -> None:
    """两个存活实例（同一工作区）必须共用一份记忆后端。"""
    a1 = _instance("life-share-1")
    a2 = _instance("life-share-2")
    try:
        assert a1.memory is not None, "记忆后端没启用，测试前提不成立"
        assert a1.memory is a2.memory, (
            "同一工作区的两个实例各开了一份记忆后端——close-all 重建期间会变成"
            "两套 SQLite 句柄写同一个 memory.sqlite"
        )
    finally:
        manager.release("life-share-1")
        manager.release("life-share-2")


def test_writes_through_two_instances_are_visible_to_both() -> None:
    """经实例 A 写的记忆，实例 B 立刻读得到（共享后端而不只是共享文件）。"""
    a1 = _instance("life-share-3")
    a2 = _instance("life-share-4")
    try:
        ids = [a1.memory.store(f"共享后端样本 {i}", topic="lifecycle-share").id for i in range(4)]
        ids += [a2.memory.store(f"另一端样本 {i}", topic="lifecycle-share").id for i in range(4)]
        missing = [nid for nid in ids if a2.memory.get(nid) is None]
        assert not missing, f"另一个实例读不到 {len(missing)} 条刚写入的记忆：{missing[:3]}"
    finally:
        manager.release("life-share-3")
        manager.release("life-share-4")


def test_concurrent_writes_through_shared_backend_all_land() -> None:
    """两个实例并发写记忆：不静默丢数据、后端不损坏。

    **已知限制（上游 octop_memory）**：并发写同一 ``memory.sqlite`` 时实测会抛
    ``sqlite3.OperationalError: database is locked``（伴随 ``cannot rollback - no
    transaction is active``）。这不是超时——``SQLITE_BUSY_TIMEOUT_MS = 30_000``
    （octop_memory/storage/backends/sqlite.py:49）对「锁升级」这类 SQLITE_BUSY
    不生效，属于 sqlite 自身的即时返回。nuomi 侧无法在应用层消除（写在 harness
    的 MemoryMiddleware 内部），所以这里锁的是**能保证的部分**：报错只允许是这一类、
    写入成功的每条都读得回、风暴过后后端仍可正常写入。

    真实触发窗口很窄：只有「close-all 时老实例仍在飞 + 新实例已经开始跑下一轮」
    才会出现两个实例同时写同一个记忆库。
    """
    a1 = _instance("life-conc-1")
    a2 = _instance("life-conc-2")
    errors: list[BaseException] = []
    node_ids: list[str] = []
    guard = threading.Lock()

    def _write(agent, tag: str) -> None:
        for i in range(8):
            try:
                node = agent.memory.store(f"并发写入样本 {tag}-{i}", topic="lifecycle-conc")
            except Exception as exc:  # noqa: BLE001 —— 线程里的异常要带回主线程断言
                with guard:
                    errors.append(exc)
                continue
            with guard:
                node_ids.append(node.id)

    threads = [
        threading.Thread(target=_write, args=(a1, "a")),
        threading.Thread(target=_write, args=(a2, "b")),
    ]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in threads), "并发写在 120s 内没结束（疑似锁等待）"

        # 1) 失败只允许是 sqlite 的忙错误（其它异常说明真的坏了）
        unexpected = [e for e in errors if not isinstance(e, sqlite3.OperationalError)]
        assert not unexpected, f"并发写入出现非 sqlite 忙错误：{unexpected!r}"
        # 2) 不能一条都没成功
        assert node_ids, f"16 条并发写全失败：{errors[:2]!r}"
        # 3) 成功的每条都读得回（没有静默丢数据）
        missing = [nid for nid in node_ids if a1.memory.get(nid) is None]
        assert not missing, f"有 {len(missing)} 条写成功却读不回来：{missing[:3]}"
        # 4) 风暴过后后端仍然可用（没有损坏 / 没留下卡死的事务）
        after = a1.memory.store("并发风暴之后仍可写入", topic="lifecycle-conc")
        assert a2.memory.get(after.id) is not None
    finally:
        manager.release("life-conc-1")
        manager.release("life-conc-2")


def test_close_all_then_rebuild_keeps_memory() -> None:
    """close-all（15 处配置端点的口径）之后立刻重建：不报错，记忆读得回。

    ``manager.close()`` 会关掉**所有**实例（包括别的测试建的），这是刻意的——它就是
    配置端点真正走的那条路径；后续需要的实例各测试会自己重建。
    """
    first = _instance("life-rebuild")
    node = first.memory.store("close-all 之后仍然读得到", topic="lifecycle-rebuild")

    manager.close()
    assert not manager.has("life-rebuild")

    second = _instance("life-rebuild")
    try:
        assert second is not first, "重建立刻命中了旧实例缓存"
        assert second.memory.get(node.id) is not None, (
            "close-all 重建后记忆读不回来——句柄没释放干净或重建落到了别的库"
        )
    finally:
        manager.release("life-rebuild")


def test_close_does_not_drop_langfuse(monkeypatch) -> None:
    """close() 只管实例，不许动 Langfuse tracer（清了轨迹观测会永久失效）。"""
    tracer = object()
    monkeypatch.setattr(manager, "_langfuse", tracer)
    manager.close()
    assert manager._langfuse is tracer, (
        "manager.close() 顺手清了 Langfuse——开关插件/存 env 之后轨迹观测会静默失效"
    )


def test_release_is_idempotent() -> None:
    """release 重复调用不得抛（stop 端点与 close 路径可能撞车）。"""
    _instance("life-release")
    manager.release("life-release")
    manager.release("life-release")
    assert not manager.has("life-release")
