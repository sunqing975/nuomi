"""AgentService：agents 表的领域操作（CRUD + 状态）。

与 runtime 的关系：service 只管领域数据；HarnessAgent 实例的生命周期
（创建/释放）由 infra/harness/manager 承担，service 通过状态字段感知。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.agents.seed import default_system_prompt
from app.storage import db

# Agent 运行时状态（对齐 Octop last_state 状态机）
STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_ERROR = "error"

AGENT_FIELDS = (
    "agent_id",
    "name",
    "description",
    "persona_mbti",
    "default_model",
    "system_prompt",
    "enabled",
    "config_json",
    "last_state",
    "last_error",
    "icon_name",
    "icon_url",
    "color",
    "template_name",
    "welcome_message",
    "kind",
)


def _row_to_agent(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["config_json"] = json.loads(d.get("config_json") or "{}")
    except json.JSONDecodeError:
        d["config_json"] = {}
    return d


class AgentService:
    def list_all(self) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
        return [_row_to_agent(r) for r in rows]

    def get(self, agent_id: str) -> dict | None:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return _row_to_agent(row) if row else None

    def create(self, data: dict[str, Any]) -> dict:
        """创建 Agent；未传 system_prompt 时用默认专家人设（糯米）。"""
        agent_id = data.get("agent_id") or db.gen_agent_id()
        row = {
            "agent_id": agent_id,
            "name": data.get("name", agent_id),
            "description": data.get("description", ""),
            "persona_mbti": data.get("persona_mbti", ""),
            "default_model": data.get("default_model", "llm/deepseek-chat"),
            "system_prompt": data.get("system_prompt") or default_system_prompt(),
            "enabled": 1 if data.get("enabled", True) else 0,
            "config_json": json.dumps(data.get("config_json") or {}, ensure_ascii=False),
            "last_state": STATE_STOPPED,
            "last_error": "",
            "icon_name": data.get("icon_name", ""),
            "icon_url": data.get("icon_url", ""),
            "color": data.get("color", ""),
            "template_name": data.get("template_name", ""),
            "welcome_message": data.get("welcome_message", ""),
            "kind": data.get("kind", "expert"),
        }
        with db.connect() as conn:
            conn.execute(
                f"INSERT INTO agents ({', '.join(AGENT_FIELDS)}) VALUES ({', '.join('?' * len(AGENT_FIELDS))})",
                tuple(row[f] for f in AGENT_FIELDS),
            )
        return self.get(agent_id)  # type: ignore[return-value]

    def update(self, agent_id: str, patch: dict[str, Any]) -> dict | None:
        """按 patch 更新字段（运行时字段 last_state 由 start/stop 管理）。"""
        allowed = {
            "name",
            "description",
            "persona_mbti",
            "default_model",
            "system_prompt",
            "enabled",
            "config_json",
            "icon_name",
            "icon_url",
            "color",
            "welcome_message",
            "kind",
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, value in patch.items():
            if key not in allowed:
                continue
            if key == "config_json" and isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return self.get(agent_id)
        sets.append("updated_at = datetime('now')")
        values.append(agent_id)
        with db.connect() as conn:
            conn.execute(f"UPDATE agents SET {', '.join(sets)} WHERE agent_id = ?", values)
        return self.get(agent_id)

    def delete(self, agent_id: str) -> bool:
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        return cur.rowcount > 0

    def set_state(self, agent_id: str, state: str, error: str = "") -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE agents SET last_state = ?, last_error = ?, updated_at = datetime('now') WHERE agent_id = ?",
                (state, error, agent_id),
            )

    def default_agent_id(self) -> str:
        """默认专家（kind=expert 的第一个，或 enabled 的第一个）。"""
        with db.connect() as conn:
            row = conn.execute(
                "SELECT agent_id FROM agents WHERE enabled = 1 ORDER BY id LIMIT 1"
            ).fetchone()
        return row["agent_id"] if row else ""


agent_service = AgentService()
