"""AI 数字人路由：表现层资产（模型/动作）+ 开关 + SSE 动作事件流。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.domain.plugins.service import plugin_service
from app.infra.avatar_events import avatar_events
from app.infra.harness.manager import manager
from app.transport.streaming import SSE_HEADERS, stream_response

router = APIRouter(prefix="/api", tags=["avatar"])

# AI 数字人 SSE 长连接的心跳间隔（秒）：空闲时写注释帧，防被判空闲断开
_SSE_KEEPALIVE_SECONDS = 15.0


class AvatarModelSwitchBody(BaseModel):
    model_id: str = Field(description="模型 id（工作区 models/2D/ 下的目录名）")


class AvatarStatusBody(BaseModel):
    enabled: bool = Field(
        description="AI 数字人开关：true=开（创建AI 数字人窗口），false=关（销毁窗口）"
    )


class AvatarPreviewBody(BaseModel):
    kind: str = Field(description="预览类型：action=动作，expression=表情")
    name: str = Field(description="动作名 / 表情名（当前激活模型的清单内）")


@router.get("/avatar/events")
async def avatar_events_sse(request: Request) -> StreamingResponse:
    """AI 数字人动作事件流（SSE 长连接）：任意对话产生的工具调用实时广播。

    空闲 ``_SSE_KEEPALIVE_SECONDS`` 秒写一个 SSE **注释帧**（``: ping``）：
    SSE 只在有事件时才有数据，长时间安静的连接会被浏览器/中间设备判为空闲而断开，
    表现为"数字人偶尔收不到动作"。注释帧对客户端不可见（壳的解析器跳过非 ``data:`` 行）。
    """

    async def gen():
        async for ev in avatar_events.stream(keepalive=_SSE_KEEPALIVE_SECONDS):
            if await request.is_disconnected():
                break
            if ev is None:
                yield ": ping\n\n"  # 心跳（注释帧）
                continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return await stream_response(
        gen,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/avatar/models")
async def list_avatar_models() -> dict:
    """模型资产列表：每个模型的动作/表情清单 + 当前激活模型。"""
    from app.domain.avatar.service import get_active_model, list_models

    return {"models": list_models(), "active": get_active_model()}


@router.get("/avatar/status")
async def get_avatar_status() -> dict:
    """AI 数字人开关状态（壳 config.json ui.avatar_enabled）。"""
    from app.domain.avatar.service import get_avatar_enabled

    return {"enabled": get_avatar_enabled()}


@router.put("/avatar/status")
async def set_avatar_status(body: AvatarStatusBody) -> dict:
    """设置AI 数字人开关：写壳 config.json ui.avatar_enabled + 共享 VRM 插件联动。

    方案B（2026-10-04）：只有一个共享AI 数字人插件 vrm-avatar——
    关闭 → 停用（动作/表情工具不再进 LLM 工具集）；开启 → 启用。
    工具随插件启停装配；释放 shell agent 实例，下次对话重建。
    """
    from app.domain.avatar.service import (
        VRM_AVATAR_PLUGIN_ID,
        get_shell_agent_id,
        set_avatar_enabled,
    )

    enabled = set_avatar_enabled(body.enabled)
    plugin_service.set_enabled(VRM_AVATAR_PLUGIN_ID, enabled)
    agent_id = get_shell_agent_id()
    if agent_id:
        # 工具集随插件启停变化：释放 agent 实例，下次对话重建
        manager.release(agent_id)
    return {
        "enabled": enabled,
        "agent_id": agent_id,
        "activated_plugin": VRM_AVATAR_PLUGIN_ID if enabled else None,
    }


@router.post("/avatar/models/switch")
async def switch_avatar_model(body: AvatarModelSwitchBody) -> dict:
    """切换AI 数字人模型：更新壳 config.json（方案B：不碰插件启停）。

    工具动态化：do_action/set_expression 的 enum 按当前激活模型 GLB 与
    animations/*.vrma 实时装配（PluginService.tools()），切模型后释放
    shell agent 实例，下次对话重建即携带新模型的动态工具。
    """
    from app.domain.avatar.service import (
        get_shell_agent_id,
        switch_model,
    )

    try:
        model = switch_model(body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    agent_id = get_shell_agent_id()
    if agent_id:
        # 表情 enum 随激活模型变化：释放实例，下次对话重建（零重启）
        manager.release(agent_id)

    return {
        "ok": True,
        "model": model,
        "agent_id": agent_id,
        "enrich": "skipped",
    }


@router.delete("/avatar/models/{model_id}")
async def delete_avatar_model(model_id: str) -> dict:
    """删除AI 数字人模型：删资产目录；删除激活模型自动切到剩余模型（方案B：无插件级联）。

    内置模型（种子分发）页面不提供删除入口。
    """
    from app.domain.avatar.service import delete_model

    try:
        result = delete_model(model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    agent_id = None
    if result["was_active"]:
        from app.domain.avatar.service import get_shell_agent_id

        agent_id = get_shell_agent_id()
        if agent_id:
            manager.release(agent_id)  # 激活模型已变，释放实例下次对话重建
    return {"ok": True, **result, "agent_id": agent_id}


@router.post("/avatar/models/import")
async def import_avatar_model(file: UploadFile = File(...)) -> dict:
    """导入 VRM 模型：写入工作区 models/3D/，自动出现在模型清单（切模型零重启）。"""
    from app.domain.avatar.service import import_vrm
    from app.transport.uploads import MAX_MODEL_BYTES, read_upload

    data = await read_upload(file, MAX_MODEL_BYTES, "模型文件")
    try:
        return await asyncio.to_thread(import_vrm, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/avatar/animations/import")
async def import_avatar_animation(file: UploadFile = File(...)) -> dict:
    """导入 Mixamo FBX 动作：转 .vrma 进壳 assets/animations/（壳 watch 自动注册，动作工具零重启生效）。"""
    from app.domain.avatar.service import import_animation_fbx
    from app.transport.uploads import MAX_ANIMATION_BYTES, read_upload

    data = await read_upload(file, MAX_ANIMATION_BYTES, "动作文件")
    try:
        result = await asyncio.to_thread(import_animation_fbx, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (FileNotFoundError, TimeoutError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    # 广播：壳收到后刷新页面（保证新动作可播、播放器状态干净）
    avatar_events.publish_raw(
        {"type": "avatar_animations_changed", "reason": "import", "action": result["action"]}
    )
    return result


@router.delete("/avatar/animations/{name}")
async def delete_avatar_animation(name: str) -> dict:
    """删除动作资产（VRMA 资源管理）：移除 assets/animations/{name}.vrma，壳 watch 注销 + SSE 刷新页面。"""
    from app.domain.avatar.service import delete_avatar_animation

    try:
        result = delete_avatar_animation(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    avatar_events.publish_raw(
        {"type": "avatar_animations_changed", "reason": "delete", "action": name}
    )
    return result


@router.get("/avatar/animations")
async def list_avatar_animations() -> dict:
    """全局动作资产清单（所有 VRM 模型共用同一套 VRMA，资源管理独立入口）。"""
    from app.domain.avatar.service import list_avatar_actions

    return {"actions": list_avatar_actions()}


@router.post("/avatar/preview")
async def avatar_preview(body: AvatarPreviewBody) -> dict:
    """预览动作/表情：构造 payload 经 SSE 广播，数字人窗口立即播放（无需对话）。"""
    from app.domain.avatar.service import preview_payload

    try:
        payload = preview_payload(body.kind, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    avatar_events.publish(payload)
    return {"ok": True, "payload": payload}
