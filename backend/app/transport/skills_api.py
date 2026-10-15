"""技能路由：工作区技能启停/导入 + SkillHub 市场 + 技能包（skillset）。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import asyncio
import re
import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.domain.skillpackages.service import skill_package_service
from app.domain.skills.service import skill_service
from app.infra import skillhub
from app.infra.harness.manager import manager
from app.storage import db
from app.transport.models import GitImportBody

router = APIRouter(prefix="/api", tags=["skills"])


def _sync_skills_disabled() -> None:
    """技能/技能包启停后，把禁用集热更新到全部存活实例（回归防线）。

    两条曾经漏掉的路径，都由这一步收口：

    1. **运行中的专家**：``manager.get_agent`` 按 agent_id 单例缓存，实例已存在时
       **忽略**传入的 ``skills_disabled``（见其 docstring）。修复前这里的启停既不调
       ``close()`` 也不同步 → 只有重启后端才生效（控制台文案曾写「重启专家实例生效」，
       其实是错的，插件路径早就能自动生效）。这里走 harness 的热接口
       ``HarnessAgent.set_skills_disabled``——``SkillFilterMiddleware`` 每轮模型调用
       重读 ``config.skills_disabled``，所以不重建实例也能即时生效。
    2. **之后新建的实例**：``ensure_agent_runtime`` 冷构造时现算
       ``skill_service.disabled_set()``，本来就用最新值，无需处理。
    """
    manager.apply_skills_disabled(skill_service.disabled_set())


def _slug_from_hub(name: str) -> str:
    """市场 slug → 本地目录名（小写 kebab，长度受限）。"""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s[:64] or "skill"


class SkillPatchBody(BaseModel):
    enabled: bool | None = None


class SkillHubInstallBody(BaseModel):
    slug: str
    name: str | None = None


class SkillPackageBody(BaseModel):
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None


class SkillPackagePatchBody(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    icon_url: str | None = None


@router.get("/skills")
async def list_skills() -> list[dict]:
    return skill_service.list_all()


@router.get("/skills/builtin")
async def list_builtin_skills() -> list[dict]:
    """harness 包内置技能（只读展示，不可编辑/删除）。"""
    return skill_service.builtin()


@router.post("/skills/import")
async def import_skill_zip(file: UploadFile = File(...)) -> dict:
    """从 zip 导入技能到工作区 skills/<name>/（格式：SKILL.md，实时扫描自动可见）。

    释放全部 agent 实例，下次对话注入新技能。
    """
    from app.infra.importers import import_skill_zip as _import
    from app.transport.uploads import MAX_ARCHIVE_BYTES, read_upload

    try:
        data = await read_upload(file, MAX_ARCHIVE_BYTES, "技能包")
        skill = await asyncio.to_thread(_import, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()  # 释放全部实例：下次对话重建，注入新技能
    return {"ok": True, "skill": skill}


@router.post("/skills/import-git")
async def import_skill_git(body: GitImportBody) -> dict:
    """从 git 仓库导入技能到工作区 skills/<name>/（浅克隆，50MB 上限）。"""
    from app.infra.importers import import_skill_git as _import

    try:
        skill = await asyncio.to_thread(_import, body.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()
    return {"ok": True, "skill": skill}


@router.patch("/skills/{skill_name}")
async def patch_skill(skill_name: str, body: SkillPatchBody) -> dict:
    if body.enabled is not None:
        row = skill_service.set_enabled(skill_name, body.enabled)
    else:
        row = next((s for s in skill_service.list_all() if s["name"] == skill_name), None)
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    _sync_skills_disabled()
    return row


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str) -> dict:
    """删除技能（含技能目录）。"""
    if not skill_service.delete(skill_name):
        raise HTTPException(status_code=404, detail="技能不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再注入被删技能
    return {"ok": True}


# ---------- SkillHub 技能市场 ----------


@router.get("/skillhub/search")
async def skillhub_search(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return await asyncio.to_thread(skillhub.search, q, page=page, page_size=page_size)


@router.get("/skillhub/rankings")
async def skillhub_rankings(
    ranking_type: str = "hot", page: int = 1, page_size: int = 20
) -> list[dict]:
    return await asyncio.to_thread(skillhub.rankings, ranking_type, page=page, page_size=page_size)


@router.get("/skillhub/skillsets/{slug}")
async def skillhub_skillset(slug: str) -> dict:
    return await asyncio.to_thread(skillhub.skillset_detail, slug)


@router.get("/skillhub/skillsets")
async def skillhub_skillset_list(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return await asyncio.to_thread(skillhub.skillset_list, q, page=page, page_size=page_size)


@router.post("/skills/install")
async def install_skill_from_hub(body: SkillHubInstallBody) -> dict:
    """从 SkillHub 安装单个技能到 {workspace}/skills/<slug>/。"""
    slug = body.slug.strip().strip("/")
    if not slug:
        raise HTTPException(status_code=400, detail="slug 不能为空")
    safe = _slug_from_hub(slug)
    if not re.match(r"^[a-zA-Z0-9_-]+$", safe):
        raise HTTPException(status_code=400, detail=f"非法技能名: {slug}")
    target = skill_service.skills_dir() / safe
    if target.exists():
        raise HTTPException(status_code=409, detail=f"技能已存在: {safe}")
    try:
        files = await asyncio.to_thread(skillhub.download, slug)
    except skillhub.SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    target.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files:
        p = target / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    skill_service.set_enabled(safe, True)
    manager.close()  # 下次对话重建，注入新技能
    return next((s for s in skill_service.list_all() if s["name"] == safe), {})


@router.get("/skill-packages")
async def list_skill_packages() -> list[dict]:
    return skill_package_service.list_all()


@router.post("/skill-packages")
async def create_skill_package(body: SkillPackageBody) -> dict:
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="包名不能为空")
    try:
        return skill_package_service.create(body.name, body.description or "", body.icon_url or "")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/skill-packages/from-skillhub")
async def create_skill_package_from_hub(body: SkillHubInstallBody) -> dict:
    """从 SkillHub 技能集（skillset）安装技能包：包级整体启停。"""
    slug = body.slug.strip().strip("/")
    if not slug:
        raise HTTPException(status_code=400, detail="slug 不能为空")
    try:
        return await asyncio.to_thread(
            skill_package_service.install_from_skillhub, slug, name=body.name
        )
    except skillhub.SkillHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/skill-packages/{package_id}")
async def patch_skill_package(package_id: str, body: SkillPackagePatchBody) -> dict:
    row = skill_package_service.get(package_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能包不存在")
    if body.enabled is not None:
        skill_package_service.set_enabled(package_id, body.enabled)
    if body.name:
        # 改名仅当不与其他包冲突
        others = [p for p in skill_package_service.list_all() if p["id"] != package_id]
        if any(p["name"] == body.name.strip() for p in others):
            raise HTTPException(status_code=409, detail=f"技能包已存在: {body.name}")
        new_id = _slug_from_hub(body.name)
        with db.connect() as conn:
            conn.execute(
                "UPDATE skill_packages SET name = ?, id = ? WHERE id = ?",
                (body.name.strip(), new_id, package_id),
            )
            conn.execute(
                "UPDATE skill_package_skills SET package_id = ? WHERE package_id = ?",
                (new_id, package_id),
            )
        old_dir = skill_package_service.package_dir(package_id)
        if old_dir.is_dir():
            shutil.move(str(old_dir), str(skill_package_service.package_dir(new_id)))
        package_id = new_id
    row = skill_package_service.get(package_id)
    if row is None:
        raise HTTPException(status_code=404, detail="技能包不存在")
    _sync_skills_disabled()  # 包启停/改名后同步存活实例（改名可能换掉 slug）
    return row


@router.delete("/skill-packages/{package_id}")
async def delete_skill_package(package_id: str) -> dict:
    """删除技能包（DB + 包目录）。"""
    if not skill_package_service.delete(package_id):
        raise HTTPException(status_code=404, detail="技能包不存在")
    manager.close()
    return {"ok": True}
