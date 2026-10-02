"""项目 / 会话元数据存储（V3 增强：Harness workspace/session 概念的轻量版）。

- projects：对话分组（Harness workspace 类比）
- threads：会话，含自动标题（首条用户消息截断）、updated_at、消息数
- 存储合一（决策 3）：建在统一库 nuomi.db（与 checkpointer / facts / settings 同文件），
  WAL + busy_timeout 保证多连接并发。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

# 会话占位标题（模型命名前的默认值）：命中则视为"未命名"，需要调用模型生成
PLACEHOLDER_TITLES = {"", "新会话", "新建会话"}


def is_placeholder_title(title: str | None) -> bool:
    return (title or "") in PLACEHOLDER_TITLES


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts or time.time()))


class ProjectStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 统一库并发：WAL + busy_timeout + 外键
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # 启用外键：threads.project_id 有 ON DELETE CASCADE，
        # 不开启的话删项目会把会话留在库里成为不可见孤儿（曾实测复现）
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
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
            # 清理历史孤儿会话（外键启用前删项目遗留的 dangling project_id）
            self._conn.execute(
                "DELETE FROM threads WHERE project_id IS NOT NULL "
                "AND project_id NOT IN (SELECT id FROM projects)"
            )
            # 迁移：项目绑定本机真实目录（V2 需求：agent 可操作项目目录中的文件）
            cols = [r["name"] for r in self._conn.execute("PRAGMA table_info(projects)").fetchall()]
            if "directory" not in cols:
                self._conn.execute("ALTER TABLE projects ADD COLUMN directory TEXT")

    # ---------- 项目 ----------
    def list_projects(self) -> list[dict]:
        with self._conn:
            rows = self._conn.execute(
                """
                SELECT p.id, p.name, p.created_at, p.directory,
                       (SELECT COUNT(*) FROM threads t WHERE t.project_id = p.id) AS thread_count
                FROM projects p ORDER BY p.id
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def create_project(self, name: str, directory: str | None = None) -> dict:
        name = name.strip() or "默认项目"
        directory = (directory or "").strip() or None
        with self._conn:
            try:
                cur = self._conn.execute(
                    "INSERT INTO projects (name, directory, created_at) VALUES (?, ?, ?)",
                    (name, directory, _iso()),
                )
            except sqlite3.IntegrityError:
                cur = self._conn.execute("SELECT id FROM projects WHERE name = ?", (name,))
                pid = cur.fetchone()["id"]
                return {"id": pid, "name": name, "directory": directory, "created_at": self._iso_of(pid)}
            pid = cur.lastrowid
        return {"id": pid, "name": name, "directory": directory, "created_at": self._iso_of(pid), "thread_count": 0}

    def set_directory(self, project_id: int, directory: str | None) -> dict:
        """绑定 / 解绑（传 None 或空串解绑）项目目录，返回更新后的项目。"""
        directory = (directory or "").strip() or None
        with self._conn:
            self._conn.execute("UPDATE projects SET directory = ? WHERE id = ?", (directory, project_id))
        proj = next((p for p in self.list_projects() if p["id"] == project_id), None)
        return proj or {"id": project_id, "directory": directory}

    def directory_of_thread(self, thread_id: str) -> str | None:
        """会话所属项目的绑定目录；未绑定返回 None。"""
        with self._conn:
            row = self._conn.execute(
                "SELECT p.directory FROM threads t JOIN projects p ON p.id = t.project_id "
                "WHERE t.id = ?",
                (thread_id,),
            ).fetchone()
        d = row["directory"] if row else None
        return (d or "").strip() or None

    def ensure_default_project(self) -> dict:
        with self._conn:
            row = self._conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()
        if row:
            return self.list_projects()[0]
        return self.create_project("默认项目")

    def delete_project(self, project_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def _iso_of(self, project_id: int) -> str:
        with self._conn:
            row = self._conn.execute("SELECT created_at FROM projects WHERE id = ?", (project_id,)).fetchone()
        return row["created_at"] if row else _iso()

    # ---------- 会话 ----------
    def list_threads(self, project_id: int | None = None) -> list[dict]:
        q = "SELECT id, project_id, title, created_at, updated_at FROM threads"
        args: list[Any] = []
        if project_id is not None:
            q += " WHERE project_id = ?"
            args.append(project_id)
        q += " ORDER BY updated_at DESC"
        with self._conn:
            rows = self._conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def create_thread(self, project_id: int | None, title: str = "") -> dict:
        pid = project_id or self.ensure_default_project()["id"]
        thread_id = _new_thread_id()
        now = _iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO threads (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, pid, title, now, now),
            )
        return {"id": thread_id, "project_id": pid, "title": title, "created_at": now, "updated_at": now}

    def get_thread(self, thread_id: str) -> dict | None:
        with self._conn:
            row = self._conn.execute(
                "SELECT id, project_id, title, created_at, updated_at FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_thread(self, thread_id: str, project_id: int | None = None) -> dict:
        """以指定 id 注册会话（兼容旧 thread_id / 外部传入的 checkpointer key）。"""
        pid = project_id or self.ensure_default_project()["id"]
        now = _iso()
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO threads (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, pid, "", now, now),
            )
        return self.get_thread(thread_id)  # type: ignore[return-value]

    def touch_thread(self, thread_id: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (_iso(), thread_id))

    def rename_thread(self, thread_id: str, title: str) -> None:
        title = (title or "").strip()
        if not title:
            return
        with self._conn:
            self._conn.execute("UPDATE threads SET title = ? WHERE id = ?", (title, thread_id))

    def auto_title(self, thread_id: str, first_user_message: str) -> None:
        """首条用户消息截断生成标题（Harness 用 LLM 生成，MVP 用截断，可后续换）。"""
        title = first_user_message.strip().replace("\n", " ")[:24] or "新会话"
        self.rename_thread(thread_id, title)

    def delete_thread(self, thread_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))

    def close(self) -> None:
        self._conn.close()


def _new_thread_id() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
