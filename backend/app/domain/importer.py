"""插件/技能 zip 导入（解压到工作区对应目录）。

导入 = 安全解压 → 定位格式根（plugin.yaml / SKILL.md）→ 复制到
工作区 plugins/<id>/ 或 skills/<name>/ → 插件走 plugin_service.sync() 注册，
技能实时扫描自动可见（无需注册）。

安全（zip 是不可信输入）：
- 路径穿越防护：每个条目解压路径 resolve 后必须位于临时根内
- 解压总量 / 条目数上限（防 zip 炸弹）
- 目标目录已存在则拒绝（不覆盖用户数据）
- 跳过 __MACOSX / .DS_Store 等打包垃圾
"""

from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from pathlib import Path
from tempfile import mkdtemp

import yaml

from app.domain.plugins.service import plugin_service
from app.domain.skills.service import skill_service

_MAX_BYTES = 50 * 1024 * 1024  # 解压总量上限 50MB
_MAX_ENTRIES = 500  # 条目数上限
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_SKIP_PREFIXES = ("__MACOSX/", "._")
_SKIP_NAMES = {".DS_Store", ".gitkeep"}


class ZipImportError(ValueError):
    """zip 导入校验失败（调用方转 400）。"""


def _safe_extract(data: bytes) -> Path:
    """带安全防护地解压到临时目录，返回临时根。失败自动清理并抛出。"""
    tmp_root = Path(mkdtemp(prefix="nuomi-import-"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if len(names) > _MAX_ENTRIES:
                raise ZipImportError(f"zip 条目过多（>{_MAX_ENTRIES}），已拒绝")
            total = 0
            for name in names:
                norm = name.replace("\\", "/")
                if norm.endswith("/"):
                    continue
                if norm.startswith(_SKIP_PREFIXES) or Path(norm).name in _SKIP_NAMES:
                    continue
                info = zf.getinfo(name)
                total += info.file_size
                if total > _MAX_BYTES:
                    raise ZipImportError(
                        f"zip 解压总量超限（>{_MAX_BYTES // (1024 * 1024)}MB），已拒绝"
                    )
                target = (tmp_root / norm).resolve()
                if not target.is_relative_to(tmp_root.resolve()):
                    raise ZipImportError("zip 内含非法路径（路径穿越），已拒绝")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return tmp_root
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


def _find_root(tmp_root: Path, marker: str) -> Path:
    """在临时根下（深度 ≤1）定位含 marker 的目录（zip 根或一层嵌套目录）。"""
    for dirpath, dirnames, filenames in os.walk(tmp_root):
        rel = Path(dirpath).relative_to(tmp_root)
        if len(rel.parts) >= 2:
            dirnames[:] = []
            continue
        if marker in filenames:
            return Path(dirpath)
    raise ZipImportError(f"zip 内未找到 {marker}（插件需 plugin.yaml，技能需 SKILL.md）")


def import_plugin_zip(data: bytes) -> dict:
    """导入插件 zip → 工作区 plugins/<id>/，并同步注册到 DB。"""
    tmp = _safe_extract(data)
    try:
        root = _find_root(tmp, "plugin.yaml")
        manifest = yaml.safe_load((root / "plugin.yaml").read_text(encoding="utf-8")) or {}
        plugin_id = str(manifest.get("id") or "").strip()
        if not plugin_id or not _NAME_RE.match(plugin_id):
            raise ZipImportError("plugin.yaml 缺少合法 id（仅限字母/数字/_/-）")
        entry = str(manifest.get("entry") or "").strip()
        if not entry or not (root / entry).is_file():
            raise ZipImportError(f"plugin.yaml 的 entry 不存在: {entry or '(空)'}")
        target = plugin_service.plugins_dir() / plugin_id
        if target.exists():
            raise ZipImportError(f"插件已存在: {plugin_id}（请先删除再导入）")
        shutil.copytree(root, target)
        rows = plugin_service.sync()
        row = next((r for r in rows if r["plugin_id"] == plugin_id), None)
        if row is None:
            raise ZipImportError(f"插件导入后注册失败: {plugin_id}")
        return row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def import_skill_zip(data: bytes) -> dict:
    """导入技能 zip → 工作区 skills/<name>/（实时扫描自动可见）。"""
    tmp = _safe_extract(data)
    try:
        root = _find_root(tmp, "SKILL.md")
        skill = skill_service._read_skill(root)
        name = skill["name"]
        if not _NAME_RE.match(name):
            raise ZipImportError("SKILL.md 缺少合法 name frontmatter（仅限字母/数字/_/-）")
        target = skill_service.skills_dir() / name
        if target.exists():
            raise ZipImportError(f"技能已存在: {name}（请先删除再导入）")
        shutil.copytree(root, target)
        return skill_service._read_skill(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
