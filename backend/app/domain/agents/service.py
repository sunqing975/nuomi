"""AgentService：agents 表的领域操作（CRUD + 状态）。

与 runtime 的关系：service 只管领域数据；HarnessAgent 实例的生命周期
（创建/释放）由 infra/harness/manager 承担，service 通过状态字段感知。

专家工作区（A2 对齐 octop）：每个 agent 一个独立 workspace 目录
（data_root/agent-workspaces/<agent_id>/），persona 文件（USER/SOUL/AGENTS/
MEMORY.md）放目录根，由 harness 每轮自动注入；manifest.json 存专家元数据。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT
from app.domain.agents.seed import default_system_prompt
from app.storage import db
from app.storage.paths import agent_workspace_dir

# Agent 运行时状态（对齐 Octop last_state 状态机）
STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_ERROR = "error"

PERSONA_FILES = ("USER.md", "SOUL.md", "AGENTS.md", "MEMORY.md")
MANIFEST_RELS = (".octop/manifest.json", "manifest.json")


def read_agent_manifest(agent_id: str) -> dict:
    """读取专家 workspace 的 manifest（.octop/manifest.json 优先，兼容根 manifest.json）。"""
    ws = agent_workspace_dir(agent_id)
    for rel in MANIFEST_RELS:
        p = ws / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def _write_generic_persona(ws: Path, name: str) -> None:
    """无模板专家：生成通用 AI 助手 persona（对齐 harness 记忆文件标准）。"""
    (ws / "USER.md").write_text(
        f"# USER · 用户档案与 Agent 设定\n\n## 关于我（{name}）\n\n- **名字：** {name}\n"
        "- **形态：** 人工智能助手（住在用户电脑里）\n- **气质：** 简洁、直接、靠谱\n"
        "- **Emoji：** ✨\n- **头像：** 🤖\n\n## 关于用户\n\n- *（待补充）*\n",
        encoding="utf-8",
    )
    (ws / "SOUL.md").write_text(
        f"# SOUL · 性格与灵魂\n\n你是{name}，一个住在用户电脑里的人工智能助手。\n\n"
        "- 简洁务实，先给结论再给理由。\n- 拿不到真实信息就直说不知道，绝不编造。\n"
        "- 有工具就用工具拿真实信息。\n",
        encoding="utf-8",
    )
    (ws / "AGENTS.md").write_text(
        "# AGENTS · 行为准则\n\n## 语气\n- 短而自然：1-3 句，像朋友发消息，不写小作文。\n"
        "- 用「我」而不是「本 AI」；用「你」而不是「用户」。\n\n## 边界\n"
        "- 有工具就用工具拿真实信息，拿不到就直说「我现在还不知道」，绝不编造。\n",
        encoding="utf-8",
    )
    (ws / "MEMORY.md").write_text(
        "# MEMORY · 长期记忆\n\n> 项目级长期决策、约定、约束、环境配置。由模型按对话事实维护，保持精简。\n",
        encoding="utf-8",
    )
    (ws / "manifest.json").write_text(
        json.dumps(
            {
                "id": ws.name,
                "label": {"zh": name, "en": name},
                "description": {"zh": "人工智能助手", "en": "AI assistant"},
                "welcome_message": {"zh": f"你好，我是{name}。", "en": f"Hi, I'm {name}."},
                "icon_name": "bot",
                "color": "#6366f1",
                "prompt_files": ["SOUL.md"],
                "quick_prompts": [],
                "task_examples": {"zh": [], "en": []},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _find_template_dir(agent_id: str, name: str) -> Path | None:
    """定位专家模板目录：experts/<agent_id|name>/ 优先，再按 manifest（id / label.zh）匹配。"""
    for key in (agent_id, name):
        cand = REPO_ROOT / "experts" / key
        if cand.is_dir():
            return cand
    experts_root = REPO_ROOT / "experts"
    if experts_root.is_dir():
        for d in experts_root.iterdir():
            m = d / "manifest.json"
            if not m.is_file():
                continue
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("id") == agent_id:
                return d
            label = data.get("label") or {}
            if isinstance(label, dict) and label.get("zh") == name:
                return d
    return None


def ensure_agent_workspace(agent_id: str, name: str) -> Path:
    """确保专家 workspace 存在；不存在则从 experts/<id|name>/ 模板复制 persona 文件。

    模板缺失时生成通用 AI 助手 persona。返回 workspace 路径。
    """
    ws = agent_workspace_dir(agent_id)
    if ws.exists() and any((ws / f).is_file() for f in PERSONA_FILES):
        return ws
    ws.mkdir(parents=True, exist_ok=True)
    template = _find_template_dir(agent_id, name)
    if template is not None:
        for f in PERSONA_FILES + ("manifest.json",):
            src = template / f
            if src.is_file():
                shutil.copy2(src, ws / f)
        # 模板 manifest 落到 .octop/ 下，与 octop 导入专家布局一致
        src_manifest = template / "manifest.json"
        if src_manifest.is_file():
            (ws / ".octop").mkdir(exist_ok=True)
            shutil.copy2(src_manifest, ws / ".octop" / "manifest.json")
    else:
        _write_generic_persona(ws, name)
    return ws


AGENT_FIELDS = (
    "agent_id",
    "name",
    "description",
    "persona_mbti",
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


def enrich_agent(row: dict) -> dict:
    """用专家 workspace manifest 覆盖展示字段（octop 双语 → nuomi 单语归一化）。

    manifest 是权威：description / welcome_message / icon_name / color /
    quick_prompts 以 workspace 的 .octop/manifest.json 为准，DB 字段兜底。
    """
    m = read_agent_manifest(row.get("agent_id", ""))
    if not m:
        return row
    out = dict(row)
    label = m.get("label") or {}
    desc = m.get("description") or {}
    wm = m.get("welcome_message") or {}
    if isinstance(label, dict) and label.get("zh"):
        out["name"] = label["zh"]
        out["label"] = label["zh"]
    if isinstance(desc, dict) and desc.get("zh"):
        out["description"] = desc["zh"]
    if isinstance(wm, dict) and wm.get("zh"):
        out["welcome_message"] = wm["zh"]
    if m.get("icon_name"):
        out["icon_name"] = m["icon_name"]
    if m.get("color"):
        out["color"] = m["color"]
    out["quick_prompts"] = m.get("quick_prompts") or out.get("quick_prompts") or []
    out["manifest"] = m
    return out


agent_service = AgentService()
