"""技能领域服务：工作区 skills/（SKILL.md 目录）↔ DB 启停 ↔ HarnessAgentConfig。

对齐 Octop 技能概念：技能 = 目录下的 SKILL.md（frontmatter 定义 name/description），
内容注入 agent 系统提示词。技能目录是 source of truth，DB 只存启停状态。
"""

from __future__ import annotations

from pathlib import Path

from app.infra.importers import read_skill_manifest
from app.storage import db, paths


class SkillService:
    def skills_dir(self) -> Path:
        """工作区技能目录（{workspace}/skills）。"""
        d = paths.skills_dir()
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
        """解析 SKILL.md frontmatter（name/description/requires_env），fallback 目录名。

        实现统一在 infra/importers.read_skill_manifest（导入与扫描共用单一来源）。
        """
        return read_skill_manifest(dir_path)

    def builtin(self) -> list[dict]:
        """harness 包内置技能（只读，随包分发，不可编辑/删除）。

        扫描 octop_harness/builtin/skills/{zh,en}/*/SKILL.md，按目录名去重
        （zh/en 同名技能只展示一次，zh 优先）。
        """
        import importlib.util

        spec = importlib.util.find_spec("octop_harness")
        if spec is None or spec.submodule_search_locations is None:
            return []
        pkg_root = Path(spec.submodule_search_locations[0])
        builtin_root = pkg_root / "builtin" / "skills"
        out: dict[str, dict] = {}
        for lang in ("zh", "en"):
            lang_dir = builtin_root / lang
            if not lang_dir.is_dir():
                continue
            for item in sorted(lang_dir.iterdir()):
                skill_md = item / "SKILL.md"
                if not skill_md.is_file():
                    continue
                info = self._read_skill(item)
                name = info["name"]
                if name not in out:  # zh 优先（先遍历 zh）
                    out[name] = {**info, "builtin": True, "lang": lang}
        return list(out.values())


skill_service = SkillService()
