"""技能领域服务：工作区 skills/（SKILL.md 目录）↔ DB 启停 ↔ HarnessAgentConfig。

对齐 Octop 技能概念：技能 = 目录下的 SKILL.md（frontmatter 定义 name/description），
内容注入 agent 系统提示词。技能目录是 source of truth，DB 只存启停状态。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.config import settings
from app.storage import db

_SKILL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class SkillService:
    def skills_dir(self) -> Path:
        """工作区技能目录（{workspace}/skills）。"""
        d = settings.workspace_path / "skills"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------- 扫描 ----------

    def scan(self) -> list[dict]:
        """扫描工作区 skills/ 下的技能（含 SKILL.md 的目录）。"""
        skills_dir = self.skills_dir()
        out: list[dict] = []
        for item in sorted(skills_dir.iterdir()):
            if not item.is_dir():
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.is_file():
                continue
            out.append(self._read_skill(item))
        return out

    def list_all(self) -> list[dict]:
        """合并目录扫描 + DB 启停状态。"""
        enabled_map = {r["skill_name"]: bool(r["enabled"]) for r in self._db_rows()}
        out = []
        for skill in self.scan():
            out.append({**skill, "enabled": enabled_map.get(skill["name"], True)})
        return out

    def set_enabled(self, name: str, enabled: bool) -> dict | None:
        with db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO skills (skill_name, enabled, description)
                   VALUES (?, ?, (SELECT description FROM skills WHERE skill_name = ?))""",
                (name, 1 if enabled else 0, name),
            )
        return self._get(name)

    def disabled_set(self) -> frozenset[str]:
        """启用的技能 → harness skills_disabled（禁用集合）。"""
        rows = self._db_rows()
        return frozenset(r["skill_name"] for r in rows if not r["enabled"])

    def delete(self, name: str) -> bool:
        """删除技能：DB 记录 + 技能目录（source of truth）。"""
        deleted = False
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM skills WHERE skill_name = ?", (name,))
            deleted = cur.rowcount > 0
        skill_dir = self.skills_dir() / name
        if skill_dir.is_dir():
            import shutil

            shutil.rmtree(skill_dir, ignore_errors=True)
            deleted = True
        return deleted

    # ---------- 内部 ----------

    def _db_rows(self) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM skills").fetchall()
        return [dict(r) for r in rows]

    def _get(self, name: str) -> dict | None:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE skill_name = ?", (name,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _read_skill(dir_path: Path) -> dict:
        """解析 SKILL.md frontmatter（name/description），fallback 目录名。"""
        content = (dir_path / "SKILL.md").read_text(encoding="utf-8")
        name = dir_path.name
        description = ""
        if content.startswith("---"):
            end = content.find("---", 4)
            if end > 0:
                try:
                    meta = yaml.safe_load(content[3:end]) or {}
                    slug = str(meta.get("name") or "").strip()
                    if slug and _SKILL_NAME_RE.match(slug):
                        name = slug
                    description = str(meta.get("description") or "").strip()
                except yaml.YAMLError:
                    pass
        return {"name": name, "path": str(dir_path), "description": description}


skill_service = SkillService()
