"""SQLite 存储：单一数据根（NUOMI_HOME/nuomi.db），agents 表对齐 Octop schema。

v0.13 起不背历史数据：库文件不存在时全新创建，不写迁移脚本。
"""

from __future__ import annotations

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
  default_model TEXT DEFAULT 'llm/deepseek-chat',
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
    """建表（幂等）。"""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(AGENTS_DDL)
        conn.executescript(PLUGINS_DDL)
        conn.executescript(SKILLS_DDL)
        conn.executescript(SKILL_PACKAGES_DDL)
        conn.executescript(SKILL_PACKAGE_SKILLS_DDL)


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
