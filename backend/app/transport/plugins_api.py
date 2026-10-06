"""插件路由：插件市场 + 启停 + zip/git 导入 + 配置读写 + 聊天面板静态文件。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.plugins.service import plugin_service
from app.infra.harness.manager import manager
from app.transport.models import GitImportBody

router = APIRouter(prefix="/api", tags=["plugins"])

_UUID_RE = re.compile(r"^[0-9a-f]{32}$")  # TTS 临时音频文件名（uuid4().hex）


class PluginPatchBody(BaseModel):
    enabled: bool | None = None


class MarketInstallBody(BaseModel):
    plugin_id: str = Field(..., min_length=1, description="市场插件 id")


class PluginSettingsBody(BaseModel):
    values: dict = Field(default_factory=dict)


def _sync_plugin_row(plugin_id: str) -> dict:
    """在**事件循环线程**上把工作区插件注册进 PluginRegistry，并返回插件行。

    为什么必须留在循环上：``PluginRegistry`` 是进程级单例，``load_all()`` 是
    「先 clear 再逐个注册」。一旦把注册放进 ``asyncio.to_thread``（zip 解包 / git
    clone 的落盘部分确实该 offload），并发对话就会在 clear→register 的窗口期读到
    空注册表 —— 实测该轮会拿到 0 个插件工具且无任何日志。
    所以分工是：**文件操作 offload，注册留在循环上**（sync 内部无 await，对其他
    协程是原子的）。
    """
    plugin_service.sync()
    row = next((p for p in plugin_service.list_all() if p["plugin_id"] == plugin_id), None)
    if row is None:
        raise HTTPException(status_code=400, detail=f"插件导入后注册失败: {plugin_id}")
    return row


@router.get("/plugins")
async def list_plugins() -> list[dict]:
    return plugin_service.list_all()


@router.get("/plugins/{plugin_id}/ui-manifest")
async def plugin_ui_manifest(plugin_id: str) -> dict:
    """插件聊天面板声明：ui/manifest.json（tool→render 映射，octop ui/ 协议兼容）。

    未声明面板（无 ui/manifest.json）返回 404，前端据此跳过文本折叠以外的渲染。
    """

    from app.infra.plugins.market import plugin_dir

    m = plugin_dir(plugin_id) / "ui" / "manifest.json"
    if not m.is_file():
        raise HTTPException(status_code=404, detail="插件未声明聊天面板（无 ui/manifest.json）")
    try:
        return json.loads(m.read_text(encoding="utf-8"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail="ui/manifest.json 不是合法 JSON") from e


@router.get("/plugins/{plugin_id}/ui/{file_name}")
async def plugin_ui_file(plugin_id: str, file_name: str) -> FileResponse:
    """插件聊天面板静态文件：serve 插件 ui/ 目录内文件（白名单防路径穿越）。"""
    from app.infra.plugins.market import plugin_dir

    if not re.fullmatch(r"[A-Za-z0-9._-]+", file_name):
        raise HTTPException(status_code=400, detail="非法 ui 文件路径")
    f = plugin_dir(plugin_id) / "ui" / file_name
    if not f.is_file():
        raise HTTPException(status_code=404, detail="ui 文件不存在")
    media = {
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json",
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
    }.get(f.suffix.lower(), "application/octet-stream")
    return FileResponse(f, media_type=media)


@router.post("/plugins/sync")
async def sync_plugins() -> list[dict]:
    """重新扫描工作区 plugins/ 并加载（新插件默认启用）。

    刻意**不** offload：``load_all()`` 会 clear 整个进程级注册表再逐个重填，
    放到工作线程会让并发对话在窗口期读到空注册表（实测 0 个插件工具）。
    真正耗时的文件操作（zip 解包 / git clone）在导入端点里已单独 offload。
    """
    return plugin_service.sync()


@router.post("/plugins/import")
async def import_plugin_zip(file: UploadFile = File(...)) -> dict:
    """从 zip 导入插件到工作区 plugins/<id>/（格式：plugin.yaml + entry 文件）。

    导入成功默认启用；释放全部 agent 实例，下次对话即可用新插件工具。
    """
    from app.infra.importers import import_plugin_zip as _import
    from app.transport.uploads import MAX_ARCHIVE_BYTES, read_upload

    try:
        data = await read_upload(file, MAX_ARCHIVE_BYTES, "插件包")
        plugin_id = await asyncio.to_thread(_import, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    plugin = _sync_plugin_row(plugin_id)  # 注册必须回事件循环（见 helper 说明）
    manager.close()  # 释放全部实例：下次对话重建，挂载新插件工具
    return {"ok": True, "plugin": plugin}


@router.post("/plugins/import-git")
async def import_plugin_git(body: GitImportBody) -> dict:
    """从 git 仓库导入插件到工作区 plugins/<id>/（浅克隆，50MB 上限）。"""
    from app.infra.importers import import_plugin_git as _import

    try:
        plugin_id = await asyncio.to_thread(_import, body.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    plugin = _sync_plugin_row(plugin_id)
    manager.close()
    return {"ok": True, "plugin": plugin}


@router.patch("/plugins/{plugin_id}")
async def patch_plugin(plugin_id: str, body: PluginPatchBody) -> dict:
    row = (
        plugin_service.set_enabled(plugin_id, body.enabled)
        if body.enabled is not None
        else plugin_service.get(plugin_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    if body.enabled is not None:
        # 工具集随插件启停变化：释放全部实例，下次对话重建（参考技能启停做法）
        manager.close()
    return row


@router.delete("/plugins/{plugin_id}")
async def delete_plugin(plugin_id: str) -> dict:
    """删除插件（含插件目录）。"""
    if not plugin_service.delete(plugin_id):
        raise HTTPException(status_code=404, detail="插件不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再携带被删插件工具
    return {"ok": True}


@router.get("/plugins/market")
async def market_plugins() -> dict:
    """市场清单 + 已安装状态。

    ``installed`` 由 transport 组装传入（infra/market 不反向依赖 domain）。
    """
    from app.infra.plugins.market import list_market

    return list_market(plugin_service.list_all())


@router.post("/plugins/market/install")
async def install_market_plugin(body: MarketInstallBody) -> dict:
    """从内置市场安装插件（zip → 工作区 plugins/，默认启用）。"""
    from app.infra.plugins.market import install as market_install

    try:
        plugin_id = await asyncio.to_thread(market_install, body.plugin_id.strip())
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    plugin = _sync_plugin_row(plugin_id)
    manager.close()
    return {"ok": True, "plugin": plugin}


@router.get("/plugins/{plugin_id}/settings")
async def get_plugin_settings(plugin_id: str) -> dict:
    """读插件配置（settings 声明 + 已存值；secret 脱敏展示）。"""
    from app.infra.plugins.market import get_config

    try:
        return get_config(plugin_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/plugins/{plugin_id}/settings")
async def put_plugin_settings(plugin_id: str, body: PluginSettingsBody) -> dict:
    """保存插件配置（类型校验；secret 留空/脱敏串复用旧值）。"""
    from app.infra.plugins.market import save_config

    try:
        return save_config(plugin_id, body.values or {})
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/plugins/tts/audio/{name}")
async def tts_audio(name: str) -> FileResponse:
    """TTS 合成音频临时文件（uuid 白名单，防路径穿越）。"""
    from fastapi.responses import FileResponse

    if not _UUID_RE.match(name):
        raise HTTPException(status_code=400, detail="音频名不合法")
    p = settings.workspace_path / "tmp" / "tts" / f"{name}.mp3"
    if not p.is_file():
        raise HTTPException(status_code=404, detail="音频不存在或已过期")
    return FileResponse(p, media_type="audio/mpeg", filename=f"{name}.mp3")
