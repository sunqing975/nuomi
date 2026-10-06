"""记忆可视化 API 测试。

覆盖四件事：
1. 读得到（统计/断言/实体/文件清单），空记忆库不报错
2. **表名前缀按专家推导** —— 这是差点上线的 bug：引擎按
   ``ns = re.sub(r"[^a-z0-9_]", "_", namespace.lower())`` 生成前缀，而 namespace 是
   **专家名**，所以每个专家的表名不同（糯米 ``__atoms``、工作狂 ``___atoms``…）。
   任何硬编码前缀的读法只对一个专家成立。
3. 文件改得对（合法名可写、非法名/越界/超限 400，改完能读回）
4. **遗忘走引擎 API**：软遗忘后可审计、默认列表消失、且实体计数同步
   （直接删行会漏掉计数与实体页标脏，导致"忘了却还被想起来"）
"""

from __future__ import annotations

import contextlib
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.infra.memory_store import (
    atom_table_prefix,
    forget_atom,
    memory_db_path,
    memory_overview,
)


@contextlib.contextmanager
def _fresh_agent(client: TestClient, name: str):
    """建一个全新专家并在结束时删掉。

    为什么必须全新：记忆引擎初始化某个库时会建 **FTS 触发器**（调用只注册在引擎连接上的
    C 扩展 ``hm_cjk_seg``），此后外部 sqlite3 连接再也插不进 ``_atoms`` / ``_raw_events``。
    会话级 client 共享 temp 工作区，所以任何"我自己造数据再让引擎处理"的用例都得用
    没被引擎碰过的库。
    """
    aid = client.post("/api/agents", json={"name": name}).json()["agent_id"]
    try:
        yield aid
    finally:
        client.delete(f"/api/agents/{aid}")


def _prefix_for(name: str) -> str:
    """复刻引擎的前缀规则（与 octop_memory storage/backends/sqlite.py:73 一致）。"""
    return re.sub(r"[^a-z0-9_]", "_", name.lower())


@pytest.fixture
def seeded_agent(client: TestClient) -> dict:
    agents = client.get("/api/agents").json()
    assert agents, "应有种子专家"
    return agents[0]


def _create_memory_schema(
    agent_id: str,
    name: str,
    atom_id: str,
    assertion: str = "用户喜欢简短回答",
    *,
    with_raw_event: bool = True,
) -> str:
    """按该专家的真实前缀建表并插一条 atom，返回前缀。

    ``with_raw_event=False``：记忆引擎一旦初始化过这个库，就会给 raw_events 建
    **调用 C 扩展函数 ``hm_cjk_seg`` 的 FTS 触发器**（该函数只注册在引擎自己的连接上），
    外部 sqlite3 连接再往 raw_events 插数据会 ``no such function``。所以"要来源对话"
    的用例必须用**全新、未被引擎碰过**的工作区；只关心 atom/实体计数的用例则应跳过。
    """
    prefix = _prefix_for(name)
    db = memory_db_path(agent_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {prefix}_entities (
              id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, canonical_name TEXT NOT NULL,
              aliases TEXT NOT NULL DEFAULT '[]', atom_count INTEGER NOT NULL DEFAULT 0,
              last_promoted_at TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS {prefix}_atoms (
              id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
              raw_event_ids TEXT NOT NULL, assertion TEXT NOT NULL, verbatim_quote TEXT NOT NULL,
              quote_event_id TEXT NOT NULL, search_terms TEXT NOT NULL, occurred_at TEXT NOT NULL,
              confidence TEXT NOT NULL, importance TEXT NOT NULL, superseded_by TEXT,
              deprecated_at TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS {prefix}_raw_events (
              id TEXT PRIMARY KEY, host TEXT NOT NULL, session_id TEXT, thread_id TEXT,
              user TEXT, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
              content TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{{}}');
            """
        )
        conn.execute(
            f"INSERT OR REPLACE INTO {prefix}_entities VALUES (?,?,?,?,?,?,?)",
            ("ent1", "person", "用户", "[]", 1, None, "2026-10-06T00:00:00+00:00"),
        )
        if with_raw_event:
            conn.execute(
                f"INSERT OR REPLACE INTO {prefix}_raw_events VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "evt1",
                    "octop-harness",
                    None,
                    "thread-42",
                    None,
                    "2026-10-06T00:00:00+00:00",
                    "user_message",
                    "你回答短一点",
                    "{}",
                ),
            )
        conn.execute(
            f"INSERT OR REPLACE INTO {prefix}_atoms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                atom_id,
                "ent1",
                "cand1",
                "[]",
                assertion,
                "你回答短一点",
                "evt1",
                '["简短"]',  # search_terms/raw_event_ids 是 JSON 列（引擎会 json.loads）
                "2026-10-06T00:00:00+00:00",
                "high",
                "high",
                None,
                None,
                "2026-10-06T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return prefix


# ---------- 基础读取 ----------


def test_overview_on_empty_memory_is_graceful(client: TestClient, seeded_agent: dict) -> None:
    r = client.get(f"/api/agents/{seeded_agent['agent_id']}/memory")
    assert r.status_code == 200
    data = r.json()
    assert set(data["stats"]) == {"atoms", "deprecated", "entities", "raw_events", "episodes"}
    assert isinstance(data["atoms"], list)
    assert any(f["name"] == "MEMORY.md" for f in data["files"]), data["files"]


def test_overview_unknown_agent_404(client: TestClient) -> None:
    assert client.get("/api/agents/nope/memory").status_code == 404


def test_overview_reads_atoms_with_source(client: TestClient) -> None:
    """断言列表要带原话与来源对话（UI 才能显示"我因为哪句话记住了它"）。

    用全新专家：这样工作区未被记忆引擎初始化，raw_events 还没有 FTS 触发器，
    外部连接才能插入来源事件（见 helper 说明）。
    """
    name = "记忆来源测试"
    aid = client.post("/api/agents", json={"name": name}).json()["agent_id"]
    try:
        _create_memory_schema(aid, name, "atom-read-1", assertion="用户偏好简短回答")

        data = memory_overview(aid)
        atom = next(a for a in data["atoms"] if a["id"] == "atom-read-1")
        assert atom["assertion"] == "用户偏好简短回答"
        assert atom["verbatim_quote"] == "你回答短一点"
        assert atom["source_thread_id"] == "thread-42"
        assert atom["entity_name"] == "用户"
        assert data["stats"]["atoms"] >= 1
    finally:
        client.delete(f"/api/agents/{aid}")


# ---------- 前缀推导（差点上线的 bug） ----------


def test_prefix_is_derived_from_agent_name(client: TestClient) -> None:
    """前缀必须按专家名推导 —— 硬编码 `___atoms` 只对某一个专家成立。

    用全新专家：种子专家（糯米）的记忆库在别的用例构造 HarnessAgent 时已被引擎初始化
    （建了 FTS 触发器），外部连接就再也插不进去了（见 helper 说明）。
    """
    name = "前缀推导测试"
    with _fresh_agent(client, name) as aid:
        prefix = _create_memory_schema(aid, name, "atom-prefix-1", with_raw_event=False)
        assert prefix == _prefix_for(name)

        conn = sqlite3.connect(memory_db_path(aid))
        try:
            assert atom_table_prefix(conn) == prefix, "推导出的前缀与引擎规则不一致"
        finally:
            conn.close()


def test_overview_works_for_a_differently_named_agent(client: TestClient) -> None:
    """换一个名字（不同前缀）也必须读到 —— 直接锁死「不能硬编码前缀」。"""
    created = client.post("/api/agents", json={"name": "Bob", "description": "前缀回归用"}).json()
    aid = created["agent_id"]
    try:
        prefix = _create_memory_schema(
            aid, "Bob", "atom-bob-1", assertion="Bob 喜欢咖啡", with_raw_event=False
        )
        assert prefix == "bob", f"预期前缀 bob，实际 {prefix!r}"

        data = memory_overview(aid)
        assert any(a["id"] == "atom-bob-1" for a in data["atoms"]), (
            "不同前缀的表没被读到 —— 说明前缀被硬编码了"
        )
    finally:
        client.delete(f"/api/agents/{aid}")


def test_two_agents_have_independent_prefixes(client: TestClient) -> None:
    """两个前缀不同的专家不能互相串数据。"""
    a = client.post("/api/agents", json={"name": "张三丰"}).json()["agent_id"]
    b = client.post("/api/agents", json={"name": "Li"}).json()["agent_id"]
    try:
        _create_memory_schema(a, "张三丰", "atom-a", assertion="张三丰的断言", with_raw_event=False)
        _create_memory_schema(b, "Li", "atom-b", assertion="Li 的断言", with_raw_event=False)
        assert any(x["id"] == "atom-a" for x in memory_overview(a)["atoms"])
        assert not any(x["id"] == "atom-b" for x in memory_overview(a)["atoms"])
        assert any(x["id"] == "atom-b" for x in memory_overview(b)["atoms"])
    finally:
        client.delete(f"/api/agents/{a}")
        client.delete(f"/api/agents/{b}")


# ---------- 人设文件 ----------


def test_memory_file_round_trip(client: TestClient, seeded_agent: dict) -> None:
    aid = seeded_agent["agent_id"]
    original = client.get(f"/api/agents/{aid}/memory/files/MEMORY.md").json()["content"]
    try:
        r = client.put(
            f"/api/agents/{aid}/memory/files/MEMORY.md",
            json={"content": "# MEMORY · 长期记忆\n\n- 用户喜欢简洁的回答。\n"},
        )
        assert r.status_code == 200, r.text
        assert (
            client.get(f"/api/agents/{aid}/memory/files/MEMORY.md").json()["content"]
            == "# MEMORY · 长期记忆\n\n- 用户喜欢简洁的回答。\n"
        )
    finally:
        client.put(f"/api/agents/{aid}/memory/files/MEMORY.md", json={"content": original})


@pytest.mark.parametrize("bad", ["../USER.md", "sub/USER.md", "USER.txt", ".md", "a b.md"])
def test_memory_file_name_is_validated(client: TestClient, seeded_agent: dict, bad: str) -> None:
    r = client.put(
        f"/api/agents/{seeded_agent['agent_id']}/memory/files/{bad}", json={"content": "x"}
    )
    assert r.status_code in (400, 404), f"{bad} 应被拒，实际 {r.status_code}"


def test_memory_file_read_missing_404(client: TestClient, seeded_agent: dict) -> None:
    assert (
        client.get(f"/api/agents/{seeded_agent['agent_id']}/memory/files/NOPE.md").status_code
        == 404
    )


def test_memory_file_too_large_rejected(client: TestClient, seeded_agent: dict) -> None:
    r = client.put(
        f"/api/agents/{seeded_agent['agent_id']}/memory/files/AGENTS.md",
        json={"content": "x" * (513 * 1024)},
    )
    assert r.status_code == 400
    assert "过大" in r.json()["detail"]


# ---------- 遗忘 ----------


def test_forget_unknown_atom_404(client: TestClient) -> None:
    with _fresh_agent(client, "遗忘404测试") as aid:
        r = client.delete(f"/api/agents/{aid}/memory/atoms/does-not-exist")
        assert r.status_code == 404


def test_forget_is_soft_and_auditable(client: TestClient) -> None:
    with _fresh_agent(client, "软遗忘测试") as aid:
        _create_memory_schema(aid, "软遗忘测试", "atom-forget-1", with_raw_event=False)
        assert any(a["id"] == "atom-forget-1" for a in memory_overview(aid)["atoms"])

        assert forget_atom(aid, "atom-forget-1", reason="测试遗忘") is True

        default = memory_overview(aid)
        assert not any(a["id"] == "atom-forget-1" for a in default["atoms"]), (
            "遗忘后不应出现在默认列表"
        )
        assert default["stats"]["deprecated"] >= 1

        audited = memory_overview(aid, include_deprecated=True)
        row = next(a for a in audited["atoms"] if a["id"] == "atom-forget-1")
        assert row["deprecated_at"], "应保留 deprecated_at 供审计"


def test_forget_via_api_and_idempotent_404(client: TestClient) -> None:
    with _fresh_agent(client, "遗忘接口测试") as aid:
        _create_memory_schema(aid, "遗忘接口测试", "atom-forget-2", with_raw_event=False)
        r = client.delete(f"/api/agents/{aid}/memory/atoms/atom-forget-2?reason=控制台遗忘")
        assert r.status_code == 200, r.text
        # 重复遗忘 → 404（引擎对已 deprecated 的行返回 False）
        assert client.delete(f"/api/agents/{aid}/memory/atoms/atom-forget-2").status_code == 404


def test_forget_keeps_engine_invariants(client: TestClient) -> None:
    """关键：遗忘必须同步实体计数 —— 直接删行会漏掉，实体页就会继续带着这条证据。"""
    with _fresh_agent(client, "不变式测试") as aid:
        prefix = _create_memory_schema(aid, "不变式测试", "atom-invariant-1", with_raw_event=False)

        conn = sqlite3.connect(memory_db_path(aid))
        before = conn.execute(
            f"SELECT atom_count FROM {prefix}_entities WHERE id='ent1'"
        ).fetchone()[0]
        conn.close()

        assert forget_atom(aid, "atom-invariant-1", reason="invariant") is True

        conn = sqlite3.connect(memory_db_path(aid))
        after = conn.execute(
            f"SELECT atom_count FROM {prefix}_entities WHERE id='ent1'"
        ).fetchone()[0]
        conn.close()
        assert after == before - 1, f"实体计数未同步：{before} → {after}"
