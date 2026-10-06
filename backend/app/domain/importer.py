"""插件/技能导入（zip / git，落到工作区对应目录）。

导入 = 获取来源 → 定位格式根（plugin.yaml / SKILL.md）→ 复制到
工作区 plugins/<id>/ 或 skills/<name>/ → 插件走 plugin_service.sync() 注册，
技能实时扫描自动可见（无需注册）。

安全（zip / git 均是不可信输入）：
- 路径穿越防护：zip 每个条目 resolve 后必须位于临时根内
- 总量 / 条目数上限（防 zip 炸弹 / 超大仓库）
- 目标目录已存在则拒绝（不覆盖用户数据）
- 跳过 __MACOSX / .DS_Store / .git 等打包垃圾
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from tempfile import mkdtemp

import yaml

from app.domain.plugins.service import plugin_service
from app.domain.skills.service import skill_service

_MAX_BYTES = 50 * 1024 * 1024  # 解压/clone 总量上限 50MB
_MAX_ENTRIES = 500  # 条目数上限
_GIT_URL_RE = re.compile(r"^(https?://|ssh://|git@)[^\s]+$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_SKIP_PREFIXES = ("__MACOSX/", "._")
_SKIP_NAMES = {".DS_Store", ".gitkeep"}


class ZipImportError(ValueError):
    """zip 导入校验失败（调用方转 400）。"""


class GitImportError(ValueError):
    """git 导入校验失败（调用方转 400）。"""


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


def _import_plugin_from_root(root: Path) -> str:
    """从已就绪的本地根（zip 解压 / git clone）把插件**落盘**到 plugins/<id>/，返回 plugin_id。

    **只做文件操作，不在这里注册**。``octop_harness`` 的 ``PluginRegistry`` 是进程级
    单例，而 ``load_all()`` 是「先 clear 再逐个注册」；本函数会被 ``asyncio.to_thread``
    调用（zip 解包 / git clone 是秒级阻塞），若同时在这里注册，并发对话就会在窗口期
    读到**空注册表** → 该轮静默丢失全部插件工具（实测观察到 0）。
    注册必须回到事件循环上做，见 ``transport/api.py`` 的 ``_sync_plugin_row``。
    """
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
    shutil.copytree(root, target, ignore=shutil.ignore_patterns(".git", ".gitkeep"))
    return plugin_id


def _import_skill_from_root(root: Path) -> dict:
    """从已就绪的本地根（zip 解压 / git clone）导入技能 → 工作区 skills/<name>/。"""
    skill = skill_service._read_skill(root)
    name = skill["name"]
    if not _NAME_RE.match(name):
        raise ZipImportError("SKILL.md 缺少合法 name frontmatter（仅限字母/数字/_/-）")
    target = skill_service.skills_dir() / name
    if target.exists():
        raise ZipImportError(f"技能已存在: {name}（请先删除再导入）")
    shutil.copytree(root, target, ignore=shutil.ignore_patterns(".git", ".gitkeep"))
    return skill_service._read_skill(target)


def import_plugin_zip(data: bytes) -> str:
    """解压插件 zip 并落盘到 plugins/<id>/，返回 plugin_id（不做注册；调用方在事件循环上 sync）。"""
    tmp = _safe_extract(data)
    try:
        root = _find_root(tmp, "plugin.yaml")
        return _import_plugin_from_root(root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def import_skill_zip(data: bytes) -> dict:
    """导入技能 zip → 工作区 skills/<name>/（实时扫描自动可见）。"""
    tmp = _safe_extract(data)
    try:
        root = _find_root(tmp, "SKILL.md")
        return _import_skill_from_root(root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _clone_git(url: str) -> Path:
    """浅克隆 git 仓库到临时目录，校验体积，返回临时根（调用方负责清理）。"""
    if not _GIT_URL_RE.match(url):
        raise GitImportError("git 地址不合法（仅支持 https:// / ssh:// / git@）")
    if shutil.which("git") is None:
        raise GitImportError("系统未安装 git，无法从仓库导入")
    tmp_root = Path(mkdtemp(prefix="nuomi-git-"))
    try:
        # 优先浅克隆；dumb http 等不支持 shallow 的远端回退全量克隆（体积校验兜底）
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", url, str(tmp_root / "repo")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0 and "shallow" in (proc.stderr or "").lower():
            proc = subprocess.run(
                ["git", "clone", url, str(tmp_root / "repo")],
                capture_output=True,
                text=True,
                timeout=120,
            )
        if proc.returncode != 0:
            raise GitImportError(f"git clone 失败: {(proc.stderr or '').strip()[:200]}")
        repo = tmp_root / "repo"
        total = sum(
            f.stat().st_size for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts
        )
        if total > _MAX_BYTES:
            raise GitImportError(f"仓库体积超限（>{_MAX_BYTES // (1024 * 1024)}MB），已拒绝")
        return repo
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise GitImportError("git clone 超时（>120s），已取消") from exc
    except Exception:
        shutil.rmtree(tmp_root, ignore_errors=True)
        raise


def import_plugin_git(url: str) -> str:
    """克隆 git 仓库并落盘插件到 plugins/<id>/，返回 plugin_id。

    不做注册（调用方在事件循环上 ``plugin_service.sync()``，理由见
    ``_import_plugin_from_root`` 的 docstring）。
    """
    repo = _clone_git(url)
    try:
        root = _find_root(repo, "plugin.yaml")
        return _import_plugin_from_root(root)
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def import_skill_git(url: str) -> dict:
    """从 git 仓库导入技能 → 工作区 skills/<name>/。"""
    repo = _clone_git(url)
    try:
        root = _find_root(repo, "SKILL.md")
        return _import_skill_from_root(root)
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)
