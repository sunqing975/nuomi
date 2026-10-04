"""技能包领域服务：{workspace}/skill_packages/<name>/skills/<slug>/ + DB 启停。

对齐 Octop 技能包概念：技能包 = SkillHub 技能集（skillset）的本地安装，
一个包含多个技能（每个技能一个 SKILL.md 目录）。包级整体启停/删除，
包内技能不可单独启停（类似模型插件只读）；注入 agent 时包内技能目录
作为额外技能根（skills_dir 列表）与工作区单技能平级生效。
"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.infra.skillhub import SkillHubError, download, skillset_detail
from app.storage import db

logger = logging.getLogger(__name__)

# 包名 → 目录名：slug 化（小写字母数字中划线）
_PACKAGE_SLUG_RE = __import__("re").compile(r"^[a-z0-9_-]{1,64}$")


def _slugify(name: str) -> str:
    import re

    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s[:64] if s else ""


def _new_package_id(name: str) -> str:
    """目录 id：优先 kebab 化包名，纯非 ASCII 名退化为 pkg-<随机>（避免冲突）。"""
    package_id = _slugify(name)
    if not _PACKAGE_SLUG_RE.match(package_id):
        package_id = f"pkg-{uuid.uuid4().hex[:10]}"
    return package_id


class SkillPackageService:
    # ---------- 存储 ----------

    def packages_root(self) -> Path:
        d = settings.workspace_path / "skill_packages"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def package_dir(self, package_id: str) -> Path:
        return self.packages_root() / package_id

    def package_skills_dir(self, package_id: str) -> Path:
        return self.package_dir(package_id) / "skills"

    def skills_dirs(self) -> list[Path]:
        """所有「已启用」包内技能目录（供 /chat 注入：与工作区 skills/ 平级）。

        包级整体启停：禁用的包不注入 → 其技能不挂载。包内技能不可单独启停。
        """
        root = self.packages_root()
        out = []
        enabled_ids = {
            r["id"] for r in self._rows("SELECT id FROM skill_packages WHERE enabled = 1")
        }
        for item in sorted(root.iterdir()):
            if not item.is_dir() or item.name not in enabled_ids:
                continue
            skills_dir = item / "skills"
            if skills_dir.is_dir():
                out.append(skills_dir)
        return out

    # ---------- DB ----------

    def _rows(self, sql: str, *params) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _row(self, sql: str, *params) -> dict | None:
        rows = self._rows(sql, *params)
        return rows[0] if rows else None

    # ---------- 查询 ----------

    def list_all(self) -> list[dict]:
        rows = self._rows("SELECT * FROM skill_packages ORDER BY created_at DESC")
        out = []
        for r in rows:
            skills = self._rows(
                "SELECT skill_slug, enabled FROM skill_package_skills WHERE package_id = ? ORDER BY skill_slug",
                r["id"],
            )
            out.append(
                {
                    **r,
                    "enabled": bool(r["enabled"]),
                    "skills": [
                        {"slug": s["skill_slug"], "enabled": bool(s["enabled"])} for s in skills
                    ],
                    "skill_count": len(skills),
                    "path": str(self.package_dir(r["id"])),
                }
            )
        return out

    def get(self, package_id: str) -> dict | None:
        row = self._row("SELECT * FROM skill_packages WHERE id = ?", package_id)
        if row is None:
            return None
        return next((p for p in self.list_all() if p["id"] == package_id), None)

    # ---------- 写操作 ----------

    def create(self, name: str, description: str = "", icon_url: str = "") -> dict:
        """本地创建空技能包。"""
        name = name.strip()
        if not name:
            raise ValueError("包名不能为空")
        existing = self._row("SELECT id FROM skill_packages WHERE name = ?", name)
        if existing:
            raise ValueError(f"技能包已存在: {name}")
        package_id = _new_package_id(name)
        self.package_dir(package_id).mkdir(parents=True, exist_ok=True)
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO skill_packages (id, name, description, icon_url, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
                (package_id, name, description, icon_url),
            )
        return self.get(package_id)

    def install_from_skillhub(self, slug: str, name: str | None = None) -> dict:
        """从 SkillHub 技能集建包：取详情 → 逐个技能下载 → 写入包内。"""
        item = skillset_detail(slug)
        skill_slugs = item.get("skill_slugs") or []
        if not skill_slugs:
            raise SkillHubError(f"技能集 {slug} 没有可安装的技能")
        package_name = (name or item.get("display_name") or slug).strip()
        existing = self._row("SELECT id FROM skill_packages WHERE name = ?", package_name)
        if existing:
            raise ValueError(f"技能包已存在: {package_name}")
        package_id = _new_package_id(package_name)
        skills_dir = self.package_skills_dir(package_id)
        skills_dir.mkdir(parents=True, exist_ok=True)

        installed: list[str] = []
        for skill_slug in skill_slugs:
            files = download(skill_slug)
            target = skills_dir / skill_slug
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            for rel_path, content in files:
                p = target / rel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)
            installed.append(skill_slug)

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO skill_packages (id, name, description, icon_url, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (
                    package_id,
                    package_name,
                    str(item.get("summary") or "")[:500],
                    str(item.get("icon_url") or ""),
                    now,
                    now,
                ),
            )
            for skill_slug in installed:
                conn.execute(
                    """INSERT INTO skill_package_skills (package_id, skill_slug, enabled)
                       VALUES (?, ?, 1)""",
                    (package_id, skill_slug),
                )
        logger.info("技能包已安装: %s (%d 个技能)", package_name, len(installed))
        return self.get(package_id)

    def set_enabled(self, package_id: str, enabled: bool) -> dict | None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE skill_packages SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
                (1 if enabled else 0, package_id),
            )
        return self.get(package_id)

    def delete(self, package_id: str) -> bool:
        """删除技能包：DB 记录 + 包目录（source of truth）。"""
        deleted = False
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM skill_packages WHERE id = ?", (package_id,))
            deleted = cur.rowcount > 0
            conn.execute("DELETE FROM skill_package_skills WHERE package_id = ?", (package_id,))
        pkg_dir = self.package_dir(package_id)
        if pkg_dir.is_dir():
            shutil.rmtree(pkg_dir, ignore_errors=True)
            deleted = True
        return deleted


skill_package_service = SkillPackageService()
