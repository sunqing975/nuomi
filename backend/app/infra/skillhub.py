"""SkillHub（腾讯技能市场 https://api.skillhub.cn）HTTP 客户端。

对齐 Octop 的 SkillHub 集成（octop/infra/skills/skillhub_market.py），
仅实现 nuomi 需要的最小面：
- search：市场搜索（返回技能/技能集条目列表）
- rankings：榜单（hot/featured/newest/recommended/trending/paid）
- skillset_detail：技能集详情（含 skill_slugs，供建技能包）
- download：下载 zip（解压 + 全套安全校验，要求根 SKILL.md）

安全边界（与 Octop 一致）：路径防穿越、文件数/字节/压缩比上限。
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SKILLHUB_HOST = "https://api.skillhub.cn"

# —— 安全上限（对齐 Octop skillhub_common）——
MAX_SKILL_FILES = 2_000
MAX_SKILL_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200

SEARCH_ENDPOINT = "/api/v1/search"
DOWNLOAD_ENDPOINT = "/api/v1/download"
SKILLSET_ENDPOINT = "/api/v1/skillsets/{slug}"
RANKING_ENDPOINTS = {
    "hot": "/api/v1/showcase/hot",
    "featured": "/api/v1/showcase/featured",
    "newest": "/api/v1/showcase/newest",
    "recommended": "/api/v1/showcase/recommended",
    "trending": "/api/v1/showcase/trending",
    "paid": "/api/v1/showcase/paid",
}


class SkillHubError(RuntimeError):
    """SkillHub 市场请求失败。"""


class SkillHubPackageError(SkillHubError):
    """下载的技能包不合法（结构/安全）。"""


def _host() -> str:
    return (settings.skillhub_host or DEFAULT_SKILLHUB_HOST).rstrip("/")


def _get(
    path: str, *, params: dict[str, Any] | None = None, timeout: float = 15.0
) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{_host()}{path}",
            params=params,
            timeout=timeout,
            headers={"User-Agent": "nuomi-skillhub/1.0", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise SkillHubError(f"SkillHub 请求失败 {path}: {exc}") from exc


# SkillHub /search 服务端固定每页 10 条（忽略 page_size），
# 一次展示更多需客户端循环翻页：从服务端 page=1 起拉，按窗口截取 (page, page_size)。
_MAX_SEARCH_PAGES = 10  # 最多循环 10 页（100 条），防止拉爆


def search(query: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    """市场搜索：返回条目列表（slug/displayName/summary/scene/icon_url/downloads…）。

    服务端固定 10 条/页：内部循环翻页凑够 page_size（对齐 octop 一次展示更多）。
    跨页去重（服务端分页抖动会重复返回同一技能，如「编程专家.Skill」）。
    """
    items: list[dict] = []
    seen: set[str] = set()
    for sp in range(1, _MAX_SEARCH_PAGES + 1):
        data = _get(SEARCH_ENDPOINT, params={"q": query, "page": sp})
        results = data.get("results") or []
        for item in results:
            norm = _normalize_item(item)
            if norm["slug"] in seen:
                continue
            seen.add(norm["slug"])
            items.append(norm)
        if len(results) < 10:  # 服务端尽头
            break
    start = (page - 1) * page_size
    return items[start : start + page_size]


def rankings(ranking_type: str = "hot", page: int = 1, page_size: int = 20) -> list[dict]:
    """榜单：hot/featured/newest/recommended/trending/paid。"""
    path = RANKING_ENDPOINTS.get(ranking_type)
    if path is None:
        raise SkillHubError(f"不支持的榜单类型: {ranking_type}")
    data = _get(path, params={"page": page, "page_size": page_size})
    items = data.get("skills") or []
    return [_normalize_item(item) for item in items]


def skillset_detail(slug: str) -> dict:
    """技能集详情（含 skill_slugs，供从市场建技能包）。"""
    safe = slug.strip().strip("/")
    if not safe:
        raise SkillHubError("技能集 slug 不能为空")
    data = _get(SKILLSET_ENDPOINT.format(slug=safe))
    item = _normalize_item(data)
    if not item.get("slug") and not item.get("skill_slugs"):
        raise SkillHubError(f"SkillHub 技能集 {safe!r} 不存在或格式异常")
    return item


def skillset_list(query: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    """技能集（技能包来源）列表：/api/v1/skillsets 分页 + 本地关键词过滤。"""
    data = _get(
        "/api/v1/skillsets",
        params={"page": page, "pageSize": max(page_size, 100)},
    )
    raw = data.get("skillSets") or []
    seen: set[str] = set()
    items = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        norm = _normalize_item(x)
        if norm["slug"] in seen:
            continue
        seen.add(norm["slug"])
        items.append(norm)
    q = query.strip().lower()
    if q:
        items = [
            it
            for it in items
            if q in it["slug"].lower()
            or q in it["display_name"].lower()
            or q in it["summary"].lower()
        ]
    return items[:page_size]


def _normalize_item(raw: dict) -> dict:
    """把市场条目字段归一为 nuomi 前端展示结构。"""
    slug = str(raw.get("slug") or raw.get("name") or "")
    skill_slugs = raw.get("skill_slugs") or raw.get("skillSlugs") or []
    if isinstance(skill_slugs, list):
        skill_slugs = [str(s) for s in skill_slugs]
    ns = raw.get("namespace") or {}
    return {
        "slug": slug,
        "display_name": str(
            raw.get("displayName") or raw.get("display_name") or raw.get("name") or slug
        ),
        "summary": str(raw.get("summary") or raw.get("summary_zh") or raw.get("description") or ""),
        "description": str(raw.get("description_zh") or raw.get("description") or ""),
        "scene": str(raw.get("scene") or raw.get("category") or ""),
        "icon_url": str(raw.get("icon_url") or ""),
        "downloads": raw.get("downloads") or 0,
        "stars": raw.get("stars") or 0,
        "publisher": str((raw.get("publisher") or {}).get("name") or raw.get("owner_name") or ""),
        "namespace": str(ns.get("canonicalName") or ""),
        "skill_slugs": skill_slugs,
        "skill_count": len(skill_slugs) or None,
        # SkillHub 条目带 labels.requires_api_key（"true"/"false"）→ 前端展示「需 API Key」标签
        "requires_api_key": str((raw.get("labels") or {}).get("requires_api_key", "")).lower()
        == "true",
    }


def download(slug: str) -> list[tuple[str, bytes]]:
    """下载单个市场技能 zip，解压并安全校验，返回 [(相对路径, 字节)]。

    要求压缩包内含根 SKILL.md（Octop 同规则）；zip 内若所有文件在单一
    顶层目录下，自动去掉该前缀（技能包常见打包方式）。
    """
    safe = slug.strip().strip("/")
    if not safe:
        raise SkillHubError("技能 slug 不能为空")
    try:
        resp = httpx.get(
            f"{_host()}{DOWNLOAD_ENDPOINT}",
            params={"slug": safe},
            timeout=60.0,
            follow_redirects=True,
            headers={
                "User-Agent": "nuomi-skillhub/1.0",
                "Accept": "application/zip,application/octet-stream,*/*",
            },
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SkillHubError(f"SkillHub 下载失败 {safe}: {exc}") from exc
    return parse_skillhub_zip(resp.content, source=slug)


def parse_skillhub_zip(payload: bytes, *, source: str) -> list[tuple[str, bytes]]:
    """解压 SkillHub 技能 zip，做安全校验，返回归一化文件列表。"""
    if not payload:
        raise SkillHubPackageError(f"SkillHub 包 {source!r} 为空")
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SkillHubPackageError(f"SkillHub 包 {source!r} 不是有效 zip") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise SkillHubPackageError(f"SkillHub 包 {source!r} 文件数超限")
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise SkillHubPackageError(f"SkillHub 包 {source!r} 解压后过大")

        raw_files: list[tuple[str, bytes]] = []
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename
            if info.file_size > 0 and info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise SkillHubPackageError(f"SkillHub 包 {source!r} 压缩比异常")
            raw_files.append((name, zf.read(info.filename)))

    if not raw_files:
        raise SkillHubPackageError(f"SkillHub 包 {source!r} 无文件")

    # 单一顶层目录：去掉前缀（技能 zip 常整体包在 <技能名>/ 下）
    top_dirs = {PurePosixPath(name).parts[0] for name, _ in raw_files}
    if len(top_dirs) == 1 and not any(name.startswith("/") for name, _ in raw_files):
        prefix = next(iter(top_dirs)) + "/"
        if all(name.startswith(prefix) for name, _ in raw_files):
            raw_files = [(name[len(prefix) :], content) for name, content in raw_files]

    files = _normalize_files(raw_files)
    if not files:
        raise SkillHubPackageError(f"SkillHub 包 {source!r} 校验后无文件")
    if "SKILL.md" not in {name for name, _content in files}:
        raise SkillHubPackageError(f"SkillHub 包 {source!r} 不含根 SKILL.md")
    return files


def _normalize_files(raw: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """路径安全校验（防穿越/绝对路径/大小写窗口盘符），总量限制。"""
    out: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    total = 0
    for name, content in raw:
        norm = name.replace("\\", "/")
        if not norm or "\x00" in norm or norm.startswith("/") or ":" in norm.split("/")[0]:
            raise SkillHubPackageError(f"非法技能包路径: {name!r}")
        p = PurePosixPath(norm)
        if p.is_absolute() or ".." in p.parts or p.parts and p.parts[0].endswith(":"):
            raise SkillHubPackageError(f"非法技能包路径: {name!r}")
        key = p.as_posix()
        if key in seen:
            continue
        seen.add(key)
        total += len(content)
        if len(out) > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
            raise SkillHubPackageError("技能包超过安全上限（文件数或字节）")
        out.append((key, content))
    return out
