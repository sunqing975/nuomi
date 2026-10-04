"""SQLite 存储：单一数据根（NUOMI_HOME/nuomi.db），agents 表对齐 Octop schema。

v0.13 起不背历史数据：库文件不存在时全新创建，不写迁移脚本。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

AGENTS_DDL = """
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  persona_mbti TEXT DEFAULT '',
  system_prompt TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  config_json TEXT DEFAULT '{}',
  last_state TEXT DEFAULT 'stopped',
  last_error TEXT DEFAULT '',
  icon_name TEXT DEFAULT '',
  icon_url TEXT DEFAULT '',
  color TEXT DEFAULT '',
  template_name TEXT DEFAULT '',
  welcome_message TEXT DEFAULT '',
  kind TEXT DEFAULT 'expert',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

# —— 能力域：插件 / 技能（对齐 Octop 领域语言）——

PLUGINS_DDL = """
CREATE TABLE IF NOT EXISTS plugins (
  plugin_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT DEFAULT 'tool',
  version TEXT DEFAULT '',
  description TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

SKILLS_DDL = """
CREATE TABLE IF NOT EXISTS skills (
  skill_name TEXT PRIMARY KEY,
  enabled INTEGER DEFAULT 1,
  description TEXT DEFAULT ''
);
"""

SKILL_PACKAGES_DDL = """
CREATE TABLE IF NOT EXISTS skill_packages (
  id TEXT PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  icon_url TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

SKILL_PACKAGE_SKILLS_DDL = """
CREATE TABLE IF NOT EXISTS skill_package_skills (
  package_id TEXT NOT NULL,
  skill_slug TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  PRIMARY KEY (package_id, skill_slug),
  FOREIGN KEY (package_id) REFERENCES skill_packages(id) ON DELETE CASCADE
);
"""

# —— 知识库（M6；单用户裁剪 Octop schema：无 owner/shared/members）——

KNOWLEDGE_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  knowledge_base_id TEXT UNIQUE NOT NULL,
  name TEXT UNIQUE NOT NULL,
  description TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1,
  icon_name TEXT DEFAULT '',
  embedding_model TEXT DEFAULT '',
  embedding_dim INTEGER DEFAULT 0,
  doc_count INTEGER DEFAULT 0,
  max_documents INTEGER DEFAULT 100,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT UNIQUE NOT NULL,
  kb_id TEXT NOT NULL,
  path TEXT NOT NULL,
  filename TEXT DEFAULT '',
  is_dir INTEGER DEFAULT 0,
  content_type TEXT DEFAULT '',
  byte_size INTEGER DEFAULT 0,
  content_hash TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  error_message TEXT DEFAULT '',
  chunk_count INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE (kb_id, path)
);
"""


def db_path() -> Path:
    """统一 SQLite 文件（单一数据根）。"""
    return settings.data_root / "nuomi.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def init_db() -> None:
    """建表（幂等）+ 旧库字段清理。"""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(AGENTS_DDL)
        conn.executescript(PLUGINS_DDL)
        conn.executescript(SKILLS_DDL)
        conn.executescript(SKILL_PACKAGES_DDL)
        conn.executescript(SKILL_PACKAGE_SKILLS_DDL)
        conn.executescript(KNOWLEDGE_DDL)
        _drop_legacy_column(conn, "agents", "default_model")  # 模型不绑专家（2026-10-04 解耦）
        _drop_legacy_column(conn, "knowledge_bases", "default_open")  # 无默认打开一说（2026-10-04 对齐 Octop：显式指定才注入）
        _ensure_column(conn, "knowledge_bases", "enabled", "INTEGER DEFAULT 1")  # 库级启停（对齐插件）


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """旧库缺列补列（SQLite 3.35+ ADD COLUMN；新库建表已含）。

    列已存在则跳过；失败静默（列缺失时读写按默认值兜底，不阻塞启动）。
    """
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in cols:
        return
    with contextlib.suppress(Exception):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _drop_legacy_column(conn, table: str, column: str) -> None:
    """旧库残留列清理（SQLite 3.35+ DROP COLUMN；模型不绑专家后 default_model 死列）。

    先确认列存在再删；失败静默（旧 SQLite 不支持时靠重建新库兜底，列不读写即无害）。
    """
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        return
    with contextlib.suppress(Exception):
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def gen_agent_id() -> str:
    return uuid.uuid4().hex[:12]


def row_to_agent(row: sqlite3.Row) -> dict:
    d = dict(row)
    # JSON 字段反序列化；非法 JSON 视为空对象
    for key in ("config_json",):
        try:
            d[key] = json.loads(d.get(key) or "{}")
        except json.JSONDecodeError:
            d[key] = {}
    return d
