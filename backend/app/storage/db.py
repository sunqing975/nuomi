"""storage/db.py · 统一 SQLite（nuomi.db）——存储合一的唯一权威入口。

决策 3/5（见 docs/desktop-data-architecture.md）：
- LangGraph checkpoints + projects/threads + 记忆 facts + 设置 settings 全部收敛进同一文件。
- `PRAGMA user_version` 记录 schema 版本，启动按版本顺序迁移。
- 2026-10-02 用户拍板：废弃 backend/data，全新环境，无遗留数据迁移。

连接规范：所有连接设 WAL + busy_timeout（LangGraph 的 aiosqlite 与我们的
sqlite3 多连接并发读写同一文件时避免 database is locked）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: str | Path) -> sqlite3.Connection:
    """打开统一库连接（自动建目录、WAL、busy_timeout）。"""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """统一库表结构。与各存储类 DDL 保持一致（CREATE IF NOT EXISTS 幂等）；
    checkpoints 由 LangGraph checkpointer 自建。"""
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                partner TEXT NOT NULL DEFAULT 'nuomi',
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'fact',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                directory TEXT
            );
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                project_id INTEGER,
                title TEXT NOT NULL DEFAULT '新会话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )


def ensure_database(db_path: str | Path) -> None:
    """应用启动入口：确保统一库存在、schema 最新。

    全新环境语义（2026-10-02）：不做任何遗留数据导入。
    """
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(p)
    try:
        _ensure_schema(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            with conn:
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()
