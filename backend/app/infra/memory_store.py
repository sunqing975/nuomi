"""记忆读写（记忆可视化后端）。

糯米定位是「记得你」，但记忆此前**只有文件系统里的几个 .md**，用户在控制台看不到
自己"被记住了什么"。这里把两处记忆来源都暴露出来：

1. **结构化记忆（atoms）** —— octop 的记忆引擎把对话提炼成原子断言表：
   每条含 ``assertion``（记住了什么）、``verbatim_quote``（原话）、
   ``importance`` / ``confidence``，以及经 ``quote_event_id`` 关联到
   ``raw_events.thread_id``（哪次对话）。这是"我记住了什么"的主体。
2. **人设/长期记忆文件** —— 工作区根目录的 ``*.md``（USER/SOUL/AGENTS/MEMORY 等），
   由 harness 每轮注入。这里允许直接查看与修正。

⚠️ **表名前缀不是固定的**：引擎按
``ns = re.sub(r"[^a-z0-9_]", "_", namespace.lower())`` 生成前缀，表名是 ``{ns}_atoms``。
而 harness 传的 namespace 是**专家名**（``cfg.memory_namespace or cfg.name``），实测：

    糯米（2 字）→ 前缀 ``__`` · 工作狂（3 字）→ ``___`` ·
    小通 · 通用助手 → ``_________`` · 热点记者（4 字）→ ``____``

所以任何硬编码 ``___atoms`` 的写法只对某一个专家成立。本模块一律先从前缀推导，
再把同一个前缀当 namespace 传回引擎（前缀字符集与 sanitize 规则一致，往返不变）。

**遗忘必须走引擎自己的 API**：``Memory.deprecate_atom()`` 会原子地
①写 ``deprecated_at`` ②把实体 ``atom_count`` 减一 ③把实体页标脏（下次重生成不再含它）
④追加 journal。直接 DELETE 行会绕过这些副作用，导致实体页仍带着"已被遗忘"的证据。
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from pathlib import Path

from app.storage.paths import agent_workspace_dir

MEMORY_DB_NAME = "memory.sqlite"

# 人设 / 长期记忆文件（工作区根目录，harness 每轮注入）
STANDARD_MEMORY_FILES = ("MEMORY.md", "USER.md", "SOUL.md", "AGENTS.md")

_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$")
MAX_FILE_BYTES = 512 * 1024  # 人设文件是"精简"的，512KB 远远够用


def memory_db_path(agent_id: str) -> Path:
    return agent_workspace_dir(agent_id) / MEMORY_DB_NAME


def workspace_dir(agent_id: str) -> Path:
    return agent_workspace_dir(agent_id)


def _connect(db_path: Path) -> sqlite3.Connection | None:
    """只读用途的连接（WAL + busy_timeout，避免与运行时写入瞬时冲突）。"""
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def atom_table_prefix(conn: sqlite3.Connection) -> str | None:
    """推导原子表前缀（``{prefix}_atoms`` 的 prefix）。

    不猜 namespace —— 不同专家前缀不同（见模块 docstring）。取不到说明这个工作区
    还没被记忆引擎初始化过。
    """
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    except sqlite3.Error:
        return None
    for row in rows:
        name = row["name"] if isinstance(row, sqlite3.Row) else row[0]
        if name.endswith("_atoms"):
            return str(name)[: -len("_atoms")]
    return None


def _count(conn: sqlite3.Connection, table: str, where: str = "") -> int:
    """计数；表不存在（老库/新库）时返回 0 而不是炸掉整页。"""
    try:
        sql = f"SELECT count(*) FROM {table}"  # noqa: S608 - table 由已校验前缀拼出
        if where:
            sql += f" WHERE {where}"
        return int(conn.execute(sql).fetchone()[0])
    except sqlite3.Error:
        return 0


def _tables(prefix: str) -> dict[str, str]:
    return {
        "atoms": f"{prefix}_atoms",
        "entities": f"{prefix}_entities",
        "raw_events": f"{prefix}_raw_events",
        "episodes": f"{prefix}_episodes",
    }


# ---------- 结构化记忆（atoms / entities） ----------


def memory_overview(
    agent_id: str, *, limit: int = 50, offset: int = 0, include_deprecated: bool = False
) -> dict:
    """记忆总览：统计 + 实体 + 分页断言列表（含来源对话与原话）。"""
    empty = {
        "exists": False,
        "stats": {"atoms": 0, "deprecated": 0, "entities": 0, "raw_events": 0, "episodes": 0},
        "entities": [],
        "atoms": [],
        "total": 0,
    }
    conn = _connect(memory_db_path(agent_id))
    if conn is None:
        return empty

    try:
        prefix = atom_table_prefix(conn)
        if prefix is None:
            return {**empty, "exists": True}
        t = _tables(prefix)

        stats = {
            "atoms": _count(conn, t["atoms"], "deprecated_at IS NULL"),
            "deprecated": _count(conn, t["atoms"], "deprecated_at IS NOT NULL"),
            "entities": _count(conn, t["entities"]),
            "raw_events": _count(conn, t["raw_events"]),
            "episodes": _count(conn, t["episodes"]),
        }
        if not stats["atoms"] and not stats["deprecated"]:
            return {**empty, "exists": True, "stats": stats}

        where = "" if include_deprecated else "WHERE a.deprecated_at IS NULL"
        try:
            total = int(conn.execute(f"SELECT count(*) FROM {t['atoms']} a {where}").fetchone()[0])
        except sqlite3.Error:
            return {**empty, "exists": True, "stats": stats}

        rows = conn.execute(
            f"""
            SELECT
                a.id, a.assertion, a.verbatim_quote, a.importance, a.confidence,
                a.occurred_at, a.created_at, a.entity_id, a.deprecated_at, a.superseded_by,
                e.canonical_name AS entity_name, e.entity_type AS entity_type,
                r.thread_id AS source_thread_id, r.timestamp AS source_at, r.content AS source_text
            FROM {t["atoms"]} a
            LEFT JOIN {t["entities"]} e ON e.id = a.entity_id
            LEFT JOIN {t["raw_events"]} r ON r.id = a.quote_event_id
            {where}
            ORDER BY a.occurred_at DESC, a.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()

        entity_rows = []
        # 实体表缺失（老库）不该让整页失败
        with contextlib.suppress(sqlite3.Error):
            entity_rows = conn.execute(
                f"""
                SELECT id, canonical_name, entity_type, atom_count, last_promoted_at
                FROM {t["entities"]} ORDER BY atom_count DESC, canonical_name LIMIT 100
                """
            ).fetchall()

        return {
            "exists": True,
            "stats": stats,
            "entities": [dict(r) for r in entity_rows],
            "atoms": [dict(r) for r in rows],
            "total": total,
        }
    finally:
        conn.close()


def forget_atom(agent_id: str, atom_id: str, *, reason: str = "") -> bool:
    """忘记一条记忆（软遗忘）。

    走 ``Memory.deprecate_atom``（引擎公开 API）而不是删行：它会同步把实体的
    atom_count 减一、把实体页标脏、并写 journal —— 少了这些副作用，实体页仍会
    带着这条已遗忘的证据被注入下一轮对话。

    namespace 用**推导出来的表前缀**（前缀字符集与 sanitize 规则一致，往返不变），
    这样才能落到该专家真正的表上。
    """
    db_path = memory_db_path(agent_id)
    conn = _connect(db_path)
    if conn is None:
        return False
    try:
        prefix = atom_table_prefix(conn)
    finally:
        conn.close()
    if not prefix:
        return False

    from octop_memory.core import Memory

    memory = Memory(
        namespace=prefix,
        backend="sqlite",
        backend_config={"db_path": str(db_path)},
    )
    try:
        return bool(memory.deprecate_atom(atom_id, actor="user", note=reason or "用户在控制台遗忘"))
    finally:
        close = getattr(memory, "close", None)
        if callable(close):
            close()


# ---------- 人设 / 长期记忆文件 ----------


def resolve_memory_file(agent_id: str, name: str) -> Path | None:
    """把文件名解析为工作区内的 .md 路径；非法名/越界/不存在返回 None。"""
    if not _FILE_NAME_RE.match(name or ""):
        return None
    root = workspace_dir(agent_id).resolve()
    target = (root / name).resolve()
    if target.parent != root:  # 双保险：正则已挡穿越，这里再确认落在根目录
        return None
    return target if target.is_file() else None


def list_memory_files(agent_id: str) -> list[dict]:
    """工作区根目录的 .md 文件（标准人设文件排前）。"""
    root = workspace_dir(agent_id)
    if not root.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(root.glob("*.md")):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append(
            {
                "name": path.name,
                "bytes": stat.st_size,
                "updated_at": int(stat.st_mtime),
                "standard": path.name in STANDARD_MEMORY_FILES,
            }
        )
    out.sort(key=lambda item: (not item["standard"], item["name"]))
    return out


def read_memory_file(agent_id: str, name: str) -> str | None:
    path = resolve_memory_file(agent_id, name)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_memory_file(agent_id: str, name: str, content: str) -> None:
    """写回人设文件。名字非法抛 ValueError（接口层转 400）；超限抛 ValueError。"""
    if not _FILE_NAME_RE.match(name or ""):
        raise ValueError("非法文件名（仅允许工作区根目录的 .md）")
    root = workspace_dir(agent_id).resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError("非法文件名（越界）")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"内容过大（上限 {MAX_FILE_BYTES // 1024}KB）")
    target.write_text(content, encoding="utf-8")
