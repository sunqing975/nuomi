"""transport/api · HTTP 接入薄层（对齐 Octop api/routers：只做协议，不写业务）。

路由只做 HTTP 校验 → 调 app.state 上已装配的服务 → 映射错误；
transport 层不 import 领域/引擎实现，不写业务规则。
服务对象由装配根（main.build_app）挂到 app.state，路由经 app.state 取用。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel, Field

from ..config import settings
from ..domain.experts.models import (
    build_model_llm,
    custom_key,
    fetch_available_models,
    find_model,
    list_providers,
)
from ..domain.experts.thread_ctx import current_thread_id as thread_ctx
from ..infrastructure.engine.runtime import MESSAGE_RECEIVED, MODEL_SWITCHED, RESPONSE_DONE
from ..sse import SSE_HEADERS, sse
from ..storage.projects import is_placeholder_title
from ..storage.workspace import list_tree, safe_project_dirname


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: str | None = None
    project_id: int | None = None
    effort: str | None = None  # 思考强度（Harness ModelSelect effort 的轻量版）


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=400)


class ActivateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    effort: str | None = None  # 在模型声明的 efforts 内才生效


class CustomModelRow(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    label: str | None = None
    efforts: list[str] | None = None
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)  # 上下文窗口（tokens）
    max_output: int | None = Field(default=None, ge=1, le=10_000_000)  # 单次最大输出（tokens）


class CustomProviderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=500)
    protocol: str = "openai"  # openai 兼容（anthropic 预留）
    api_key: str = Field(default="", max_length=500)
    models: list[CustomModelRow] = []


class CustomProviderUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    protocol: str | None = None
    api_key: str | None = None  # "__KEEP__"=不改；""=清除；其他=覆盖
    models: list[CustomModelRow] | None = None


class InstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=2000)  # 目录 / zip / git URL


class GlobalSettingRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: Any = None


class PluginSettingRequest(BaseModel):
    patch: dict[str, Any] = {}


class NewProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    directory: str | None = Field(
        default=None, max_length=2048, description="绑定的本机目录（绝对路径，可选）"
    )


class BootstrapWorkspaceRequest(BaseModel):
    workspace: str = Field(min_length=1, max_length=2048, description="工作区根目录绝对路径")


class ShellExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4000, description="要执行的命令（沙箱保护）")


class SetProjectDirectoryRequest(BaseModel):
    directory: str | None = Field(
        default=None, max_length=2048, description="要绑定的本机目录绝对路径；传空串/None 解绑"
    )


class NewThreadRequest(BaseModel):
    project_id: int | None = None
    title: str = Field(default="", max_length=64)


class RenameThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=64)


def _chunk_text(chunk) -> str:
    """AIMessageChunk.content 可能是 str 或 content-block 列表，统一取纯文本。"""
    c = getattr(chunk, "content", chunk)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "".join(parts)
    return str(c)


def _chunk_reasoning(chunk) -> str:
    """DeepSeek 流式 chunk 的思考过程（reasoning_content），无则返回空串。"""
    for src in ("reasoning_content", "reasoning"):
        v = getattr(chunk, src, None)
        if v:
            return v if isinstance(v, str) else str(v)
    kw = getattr(chunk, "additional_kwargs", None) or {}
    v = kw.get("reasoning_content")
    return v if isinstance(v, str) else (v or "")


def _chunk_tools(chunk) -> list[str]:
    """流式 chunk 中正在调用的工具名（增量片段；去重由调用方累积）。

    单 Agent（messages 模式）产出 AIMessageChunk，工具调用增量在 tool_call_chunks；
    团队（updates 模式）产出完整 AIMessage，工具调用在 tool_calls。
    """
    names: list[str] = []
    tcc = getattr(chunk, "tool_call_chunks", None)
    if tcc:
        for c in tcc:
            if isinstance(c, dict) and c.get("name"):
                names.append(c["name"])
    if names:
        return names
    tcs = getattr(chunk, "tool_calls", None)
    if tcs:
        for c in tcs:
            name = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
            if name:
                names.append(name)
    return names


def _chunk_tool_events(chunk, acc: dict) -> list[tuple[str, str]]:
    """返回本 chunk 中「首次出现」的工具调用 [(name, args_json)]。

    - messages 模式：AIMessageChunk.tool_call_chunks 是跨 chunk 的累积视图，
      每个 index 的 args_fragment 是「自上次以来新增的部分」，需按 index 累积；
      sent 标记保证同一调用只在首次出现时发事件。
    - updates 模式：完整 AIMessage.tool_calls 一次到位，直接取完整 args。
    """
    import json as _json

    events: list[tuple[str, str]] = []
    tcc = getattr(chunk, "tool_call_chunks", None)
    if tcc:
        for i, c in enumerate(tcc):
            if not isinstance(c, dict):
                continue
            entry = acc.setdefault(i, {"name": "", "args": "", "sent": False})
            frag = c.get("args_fragment")
            if frag:
                entry["args"] += frag
            nm = c.get("name")
            if nm and not entry["sent"]:
                entry["sent"] = True
                entry["name"] = nm
                args = entry["args"].strip()
                events.append((nm, args if args else "{}"))
    tcs = getattr(chunk, "tool_calls", None)
    if tcs:
        for c in tcs:
            nm = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
            if not nm:
                continue
            args = {}
            if isinstance(c, dict):
                args = c.get("args") or {}
            elif hasattr(c, "args") and c.args is not None:
                args = c.args
            events.append((nm, _json.dumps(args, ensure_ascii=False)))
    return events


def _merge_usage(acc: dict, chunk) -> None:
    """从最后一个 chunk 的 usage_metadata 提取 token 统计（取累计值即最终值）。"""
    um = getattr(chunk, "usage_metadata", None) or {}
    if not um:
        return
    acc["input_tokens"] = um.get("input_tokens", 0)
    acc["output_tokens"] = um.get("output_tokens", 0)
    acc["total_tokens"] = um.get("total_tokens", 0)


async def _trace_turn(
    app: FastAPI, thread_id: str, user_msg: str, reply: str, error: str, started: float
):
    """对话结束后写一行 trace：时间/会话/用户消息/工具调用/回复长度/耗时。"""
    import time as _t

    from langchain_core.messages import AIMessage

    tools_called: list[str] = []
    try:
        tuple_ = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
        msgs = tuple_.checkpoint["channel_values"].get("messages", [])
        for m in msgs:
            if isinstance(m, AIMessage) and m.tool_calls:
                tools_called.extend(tc["name"] for tc in m.tool_calls)
    except Exception:
        pass
    app.state.trace_logger.log(
        thread_id=thread_id,
        user_message=user_msg[:200],
        reply_chars=len(reply),
        tools_called=tools_called,
        error=error or None,
        latency_s=round(_t.time() - started, 3),
    )


def _tar_root(names: list[str]) -> str:
    first = names[0].split("/")[0] if names else ""
    if first and all(n.split("/")[0] == first for n in names):
        return first
    return ""


def _sanitize_plugin_name(name: str) -> str:
    """插件目录名安全化：仅允许小写字母/数字/下划线/连字符。"""
    import re

    cleaned = re.sub(r"[^a-z0-9_-]", "-", name.strip().lower()).strip("-")
    if not cleaned:
        raise ValueError("插件名不合法（仅允许字母、数字、-、_）")
    return cleaned


def build_router(app: FastAPI) -> APIRouter:
    """装配全部 HTTP 路由到 app（服务对象一律从 app.state 取）。"""
    router = APIRouter()

    @app.middleware("http")
    async def token_guard(request: Request, call_next):
        """桌面 sidecar 本地 token 校验（阶段 C）：app.state.api_token 非 None 时启用，
        /api/* 均需 X-Nuomi-Token（health 与静态页面放行）。dev 默认不启用。"""
        if (
            app.state.api_token
            and request.url.path.startswith("/api")
            and not request.url.path.startswith("/api/health")
            and request.headers.get("X-Nuomi-Token") != app.state.api_token
        ):
            return JSONResponse({"detail": "未授权：缺少有效 token"}, status_code=401)
        return await call_next(request)

    @router.get("/health")
    @router.get("/api/health")  # Vite /api 代理下的别名（前端设置面板探活）
    async def health():
        from ..storage.memory import get_backend

        try:
            memory_count = len(get_backend().list())
        except Exception:
            memory_count = 0
        return {
            "status": "ok",
            "model": app.state.model_name,
            "expert": app.state.expert.display_name,
            "memory_facts": memory_count,
            "knowledge": {
                "store": app.state.kb_type,
                "documents": app.state.knowledge.count(),
            },
            "plugins": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "state": p["state"],
                    "error": p["error"],
                    "tools": len(p["tools"]),
                    "services": p["services"],
                }
                for p in app.state.capabilities.list()["plugins"]
            ],
            "team": getattr(app.state, "supervisor", None) is not None,
        }

    # ---------- 机器人模式语音端点（复用 voice 插件的本地 STT/TTS） ----------

    @lru_cache(maxsize=1)
    def _voice_tool_module():
        """加载 plugins/voice/tool.py 为独立模块（缓存，保证 faster-whisper 模型只加载一次）。"""
        mod_path = Path(settings.plugins_dir) / "voice" / "tool.py"
        spec = importlib.util.spec_from_file_location("nuomi_voice_runtime", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @router.post("/api/transcribe")
    async def transcribe_audio(audio: UploadFile):
        """上传音频（webm/mp3/wav…）→ 本地 faster-whisper 转写 → {"text": ...}。"""
        if not audio.filename:
            raise HTTPException(400, "缺少音频文件")
        suffix = Path(audio.filename).suffix or ".webm"
        if suffix.lower() not in {".webm", ".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}:
            raise HTTPException(400, f"不支持的音频格式: {suffix}")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            shutil.copyfileobj(audio.file, tmp)
        try:
            model = _voice_tool_module()._get_model()
            segments, info = model.transcribe(
                tmp_path,
                language="zh",
                vad_filter=True,
                beam_size=5,
            )
            text = "".join(s.text for s in segments).strip()
            if not text:
                raise HTTPException(400, "未识别到语音内容，请再说一次")
            return {
                "text": text,
                "language": info.language,
                "language_probability": round(float(info.language_probability), 3),
            }
        finally:
            with suppress(OSError):
                os.remove(tmp_path)

    @router.post("/api/speak")
    async def speak_audio(req: SpeakRequest):
        """文本 → macOS say 合成 → 返回 audio/mpeg 音频流（前端 Audio 直接播放）。

        与 plugins/voice/tool.py 的 speak 同源实现（say + ffmpeg），独立于插件格式包装。
        """
        import subprocess

        tmp_dir = Path(tempfile.mkdtemp(prefix="nuomi_speak_"))
        aiff = tmp_dir / "speak.aiff"
        mp3 = tmp_dir / "speak.mp3"
        try:
            r = subprocess.run(
                ["say", "-v", "Ting-Ting", "-o", str(aiff), req.text],
                timeout=30,
                capture_output=True,
            )
            if r.returncode != 0:
                raise HTTPException(
                    502,
                    f"语音合成失败（say 返回 {r.returncode}）：{r.stderr.decode('utf-8', errors='replace').strip()[:200] or '未知错误'}",
                )
            r2 = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(aiff),
                    "-codec:a",
                    "libmp3lame",
                    "-qscale:a",
                    "2",
                    str(mp3),
                ],
                timeout=60,
                capture_output=True,
            )
            if r2.returncode != 0 or not mp3.exists():
                raise HTTPException(
                    502, "音频转码失败（需要 ffmpeg，可用 brew install ffmpeg 安装）"
                )
            return Response(content=mp3.read_bytes(), media_type="audio/mpeg")
        except HTTPException:
            raise
        except subprocess.TimeoutExpired as e:
            raise HTTPException(502, f"语音合成超时: {e}") from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @router.get("/api/plugins")
    async def plugins():
        """能力管理清单（领域语义：能力=fiber 状态 + 贡献 + 元数据）+ 可导入候选。"""
        return app.state.capabilities.list()

    @router.post("/api/plugins/{name}/toggle")
    async def toggle_plugin_ep(name: str):
        """统一启停（领域语义：改 nuomi.json → 挂载/卸载 fiber → 事件广播热更新）。"""
        try:
            return app.state.capabilities.toggle(name)
        except KeyError:
            raise HTTPException(404, f"未知能力：{name}") from None

    # --- 模型管理（Phase 6：内置 + 自定义供应商；API Key；激活持久化） ---
    def _keys_of(svc) -> dict:
        """settings 全局里所有 provider_*_api_key（非空）→ 供模型构建优先使用。"""
        return {
            k: v
            for k, v in (svc["store"].all() if svc else {}).items()
            if k.startswith("provider_") and isinstance(v, str) and v
        }

    def _model_ctx(svc) -> tuple[list[dict], dict]:
        """模型上下文：自定义供应商列表 + 设置内 API Key。"""
        if svc is None:
            return [], {}
        cps = svc["store"].get("custom_providers", []) or []
        return [c for c in cps if isinstance(c, dict) and c.get("key")], _keys_of(svc)

    async def _generate_thread_title(user_msg: str, reply: str) -> str | None:
        """调用当前激活模型为会话生成简短标题（对齐 Harness LLM 命名）。

        - 无激活模型 / 模型不可用 / 调用失败 → 返回 None（调用方回退截断标题）
        - 非流式短调用：max_tokens=32、timeout=10s，不阻塞主回复（在 done 之后执行）
        """
        provider = getattr(app.state, "model_provider", None)
        model = getattr(app.state, "model_name", None)
        if not provider or provider == "none" or not model or model == "none":
            return None
        svc = app.state.scope.get("settings")
        cps, keys = _model_ctx(svc)
        try:
            if find_model(provider, model, cps, keys) is None:
                return None
            llm = build_model_llm(provider, model, None, cps, keys, streaming=False, max_tokens=32)
            sample_user = (user_msg or "").strip().replace("\n", " ")[:120]
            sample_reply = (reply or "").strip().replace("\n", " ")[:200]
            prompt = (
                "为下面的对话起一个简短的会话标题。要求：4-12 个字，概括对话主题，"
                "不要引号、不要标点、不要“标题”字样、不要英文。\n"
                f"用户消息：{sample_user}\n"
                + (f"回复摘要：{sample_reply}\n" if sample_reply else "")
                + "标题："
            )
            resp = await asyncio.wait_for(llm.ainvoke([("user", prompt)]), timeout=10)
            title = (getattr(resp, "content", "") or "").strip()
            title = title.strip("\"'“”《》").splitlines()[0].strip()[:20]
            return title or None
        except Exception:  # noqa: BLE001 — 命名失败回退截断，不影响主流程
            return None

    @router.get("/api/models")
    async def models():
        svc = app.state.scope.get("settings")
        cps, keys = _model_ctx(svc)
        return list_providers(app.state.model_provider, app.state.model_name, cps, keys)

    @router.post("/api/models/activate")
    async def activate_model(req: ActivateRequest):
        svc = app.state.scope.get("settings")
        cps, keys = _model_ctx(svc)
        m = find_model(req.provider, req.model, cps, keys)
        if m is None:
            raise HTTPException(404, f"未知或不可用：{req.provider}/{req.model}")
        effort = req.effort if req.effort in m["efforts"] else None
        new_llm = build_model_llm(req.provider, req.model, effort, cps, keys)
        # 更新 scope 服务（agent-loop 等经 ctx.llm 消费）+ V2 兼容读点
        app.state.scope.register("llm", new_llm)
        app.state.llm_cfg = new_llm
        app.state.model_provider = req.provider
        app.state.model_name = req.model
        app.state.llm_effort = effort
        app.state.rebuild_agents()
        if svc is not None:
            svc["store"].set(
                "active_model",
                {"provider": req.provider, "model": req.model, "effort": effort},
            )
        app.state.event_bus.publish(
            MODEL_SWITCHED,
            {
                "provider": req.provider,
                "model": req.model,
                "effort": effort,
                "tools": [t.name for t in app.state.tools],
            },
        )
        return {
            "active_provider": req.provider,
            "active_model": req.model,
            "effort": effort,
            "providers": list_providers(req.provider, req.model, cps, keys)["providers"],
            "tools": [t.name for t in app.state.tools],
        }

    # --- 自定义供应商（设置面板：增删改 + 模型目录 + 拉取可用模型） ---

    @router.post("/api/models/custom")
    async def custom_provider_add(req: CustomProviderRequest):
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        cps, _ = _model_ctx(svc)
        key = custom_key(req.base_url, req.name)
        cps.append(
            {
                "key": key,
                "name": req.name.strip(),
                "base_url": req.base_url.strip().rstrip("/"),
                "protocol": req.protocol,
                "api_key": (req.api_key or "").strip(),
                "models": [
                    {
                        "id": mm.id.strip(),
                        "label": (mm.label or mm.id).strip(),
                        "efforts": mm.efforts or ["medium"],
                        "context_window": mm.context_window,
                        "max_output": mm.max_output,
                    }
                    for mm in req.models
                ],
            }
        )
        svc["store"].set("custom_providers", cps)
        return list_providers(app.state.model_provider, app.state.model_name, cps, _keys_of(svc))

    @router.put("/api/models/custom/{key}")
    async def custom_provider_update(key: str, req: CustomProviderUpdate):
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        cps, _ = _model_ctx(svc)
        target = next((c for c in cps if c["key"] == key), None)
        if target is None:
            raise HTTPException(404, f"未知自定义供应商：{key}")
        if req.name is not None:
            target["name"] = req.name.strip()
        if req.base_url is not None:
            target["base_url"] = req.base_url.strip().rstrip("/")
        if req.protocol is not None:
            target["protocol"] = req.protocol
        if req.models is not None:
            target["models"] = [
                {
                    "id": mm.id.strip(),
                    "label": (mm.label or mm.id).strip(),
                    "efforts": mm.efforts or ["medium"],
                    "context_window": mm.context_window,
                    "max_output": mm.max_output,
                }
                for mm in req.models
            ]
        # api_key：显式传值（非 __KEEP__）才覆盖；传空串 = 清除
        if req.api_key and req.api_key != "__KEEP__":
            target["api_key"] = req.api_key.strip()
        elif req.api_key == "":
            target["api_key"] = ""
        svc["store"].set("custom_providers", cps)
        return list_providers(app.state.model_provider, app.state.model_name, cps, _keys_of(svc))

    @router.delete("/api/models/custom/{key}")
    async def custom_provider_delete(key: str):
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        cps, _ = _model_ctx(svc)
        before = len(cps)
        cps = [c for c in cps if c["key"] != key]
        if len(cps) == before:
            raise HTTPException(404, f"未知自定义供应商：{key}")
        svc["store"].set("custom_providers", cps)
        return list_providers(app.state.model_provider, app.state.model_name, cps, _keys_of(svc))

    @router.get("/api/models/available")
    async def models_available(base_url: str, api_key: str = ""):
        """拉取 OpenAI 兼容供应商的可用模型 id 列表（自定义供应商设置用）。"""
        if not base_url:
            raise HTTPException(400, "缺少 base_url")
        try:
            ids = fetch_available_models(base_url, api_key)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"拉取失败：{e}") from e
        return {"models": ids}

    # --- V3 插件导入（参考 Harness dsh plugin：install / uninstall） ---

    @router.post("/api/plugins/install")
    async def install_plugin(req: InstallRequest):
        name = _sanitize_plugin_name(req.name)
        try:
            return app.state.capabilities.install(name, req.source)
        except FileExistsError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"{e.__class__.__name__}: {e}") from e

    @router.post("/api/plugins/install-upload")
    async def install_upload(file: UploadFile):
        """浏览器上传 zip 安装插件（Harness dsh plugin 的 GUI 对应物）。"""
        import tempfile

        raw = file.filename or "plugin.zip"
        name = _sanitize_plugin_name(Path(raw).stem)
        suffix = Path(raw).suffix.lower()
        if suffix not in (".zip", ".tar", ".gz", ".tgz"):
            raise HTTPException(400, "仅支持 .zip 或 .tar.gz 插件包")
        tmp = Path(tempfile.mkdtemp(prefix="nuomi_import_")) / raw
        tmp.write_bytes(await file.read())
        try:
            if suffix == ".zip":
                return app.state.capabilities.install(name, tmp)
            if suffix in (".tar", ".gz", ".tgz"):
                import tarfile

                with tarfile.open(tmp) as tf:
                    root = _tar_root(tf.getnames())
                    extract_dir = tmp.parent / "x"
                    extract_dir.mkdir(exist_ok=True)
                    tf.extractall(extract_dir)
                    src = extract_dir / root if root else extract_dir
                    return app.state.capabilities.install(name, src)
            raise HTTPException(400, "不支持的包格式")
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    @router.post("/api/plugins/{plugin_id}/uninstall")
    async def uninstall_plugin(plugin_id: str):
        try:
            return app.state.capabilities.uninstall(plugin_id)
        except KeyError:
            raise HTTPException(404, f"未知插件：{plugin_id}") from None

    # --- V3 设置系统（参考 Harness ui-settings） ---

    @router.get("/api/settings")
    async def settings_get():
        svc = app.state.scope.get("settings")
        if svc is None:
            return {"global": {}, "plugins": []}
        return svc["snapshot"]()

    @router.post("/api/settings/global")
    async def settings_set_global(req: GlobalSettingRequest):
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        svc["set"](req.key, req.value)
        return {"ok": True, "key": req.key, "value": req.value}

    @router.post("/api/settings/plugins/{plugin_id}")
    async def settings_set_plugin(plugin_id: str, req: PluginSettingRequest):
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        merged = svc["plugin_set"](plugin_id, req.patch)
        return {"ok": True, "plugin": plugin_id, "values": merged}

    # --- V3 增强：项目 / 会话（Harness workspace/session 轻量版） ---
    @router.get("/api/projects")
    async def projects_list():
        return {"projects": app.state.projects.list_projects()}

    @router.post("/api/projects")
    async def projects_create(req: NewProjectRequest):
        """新建项目：显式给了 directory 则按指定绑定；否则在工作区自动创建目录并绑定
        （阶段 B：一个项目 = 工作区里的一个目录）。"""
        if req.directory:
            return app.state.projects.create_project(req.name, req.directory)
        try:
            safe = safe_project_dirname(req.name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        d = settings.workspace_path / safe
        d.mkdir(parents=True, exist_ok=True)
        return app.state.projects.create_project(req.name, str(d))

    @router.patch("/api/projects/{project_id}/directory")
    async def projects_set_directory(project_id: int, req: SetProjectDirectoryRequest):
        """绑定/解绑项目目录。绑定路径必须存在且是目录。"""
        directory = (req.directory or "").strip() or None
        if directory is not None:
            p = Path(directory).expanduser().resolve()
            if not p.is_dir():
                raise HTTPException(400, f"目录不存在或不是文件夹：{directory}")
        return app.state.projects.set_directory(project_id, directory)

    @router.delete("/api/projects/{project_id}")
    async def projects_delete(project_id: int):
        # 只删库记录与级联会话；工作区目录是用户文件，保留（不静默删数据）
        app.state.projects.delete_project(project_id)
        return {"ok": True}

    # --- 阶段 B：工作区（前端项目树 = 工作区目录） ---
    @router.get("/api/workspace/tree")
    async def workspace_tree():
        """安全列出工作区目录树（隐藏项/依赖目录跳过，深度与条目数有上限）。"""
        return list_tree(settings.workspace_path)

    @router.get("/api/projects/{project_id}/tree")
    async def project_tree(project_id: int):
        """项目绑定的本地目录文件树（一个项目 = 一个目录）。
        未绑定目录或路径失效 → 404；树规则复用 list_tree（隐藏/依赖跳过、深度条数上限）。"""
        proj = app.state.projects.get_project(project_id)
        if proj is None:
            raise HTTPException(404, "项目不存在")
        directory = (proj.get("directory") or "").strip()
        if not directory:
            raise HTTPException(404, "项目未绑定目录")
        d = Path(directory).expanduser()
        if not d.is_dir():
            raise HTTPException(404, f"目录不存在或不是文件夹：{directory}")
        return list_tree(d)

    _shell_tool_mod: Any | None = None

    def _load_shell_tool() -> Any:
        """动态加载 shell 插件（仓库 plugins/shell/tool.py），复用其沙箱执行。"""
        nonlocal _shell_tool_mod
        if _shell_tool_mod is None:
            from importlib.util import module_from_spec, spec_from_file_location

            path = Path(settings.plugins_dir) / "shell" / "tool.py"
            spec = spec_from_file_location("nuomi_shell_tool", path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载 shell 工具模块：{path}")
            mod = module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            _shell_tool_mod = mod
        return _shell_tool_mod

    @router.post("/api/projects/{project_id}/shell/exec")
    async def project_shell_exec(project_id: int, req: ShellExecRequest):
        """在项目目录执行一条命令（复用 shell 插件沙箱：workspace-write 锚定工作区，
        黑名单/超时/截断与 agent 的 bash 工具一致；项目目录在工作区外时返回沙箱提示）。"""
        proj = app.state.projects.get_project(project_id)
        if proj is None:
            raise HTTPException(404, "项目不存在")
        directory = (proj.get("directory") or "").strip()
        if not directory:
            raise HTTPException(404, "项目未绑定目录")
        d = Path(directory).expanduser()
        if not d.is_dir():
            raise HTTPException(404, f"目录不存在或不是文件夹：{directory}")
        out = await asyncio.to_thread(
            _load_shell_tool()._run, req.command, str(d), "workspace-write"
        )
        return {"output": out, "cwd": str(d)}

    # --- 阶段 D：首启向导 ---
    @router.post("/api/experts/{name}/activate")
    async def expert_activate(name: str):
        """切换专家（领域语义：写入 workspace 覆盖 → 重启后生效）。"""
        from ..domain.experts.expert import list_experts

        if name not in list_experts(settings.experts_dir):
            raise HTTPException(404, f"未知专家：{name}")
        f = Path(settings.workspace_dir) / "experts.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps({"expert_name": name}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ok": True, "name": name, "restart_required": True}

    @router.get("/api/skills")
    async def skills_list():
        """技能清单（领域语义：独立文档资产 SKILL.md，全量注入 system prompt）。"""
        return {
            "skills": [{"name": s.name, "description": s.description} for s in app.state.skills]
        }

    @router.get("/api/experts")
    async def experts_list():
        """专家库清单（领域语义：专家 = 人格 + 能力模板资产，对齐 Octop 专家库）。"""
        from ..domain.experts.expert import list_experts, load_expert

        names = list_experts(settings.experts_dir)
        current = app.state.expert
        out = []
        for n in sorted(names):
            try:
                ex = load_expert(n, settings.experts_dir)
            except Exception:
                ex = None
            out.append(
                {
                    "id": n,
                    "name": n,
                    "display_name": ex.display_name
                    if ex
                    else (current.display_name if n == current.name else n),
                    "description": ex.description if ex else "",
                    "icon_name": ex.icon_name if ex else "",
                    "color": ex.color if ex else "",
                    "default": ex.default
                    if ex
                    else (current.default if n == current.name else False),
                }
            )
        return {"experts": out, "current": current.name}

    @router.get("/api/bootstrap")
    async def bootstrap():
        """首启判定：未配置任何可用 LLM 供应商且未激活模型 → 需要走向导。"""
        svc = app.state.scope.get("settings")
        if svc is None:
            return {
                "setup_required": False,
                "workspace": str(settings.workspace_path),
                "llm_configured": False,
            }
        s = svc["store"]
        cps = s.get("custom_providers", []) or []
        am = s.get("active_model")
        llm_configured = bool(cps and isinstance(am, dict) and am.get("provider"))
        return {
            "setup_required": not llm_configured,
            "workspace": str(settings.workspace_path),
            "llm_configured": llm_configured,
        }

    @router.post("/api/bootstrap/workspace")
    async def bootstrap_workspace(req: BootstrapWorkspaceRequest):
        """向导保存工作区路径：写入 settings（lifespan 启动时自动恢复）。"""
        svc = app.state.scope.get("settings")
        if svc is None:
            raise HTTPException(503, "settings 服务未加载")
        p = Path(req.workspace).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(400, f"无法创建工作区目录：{e}") from e
        svc["store"].set("workspace_dir", str(p))
        settings._workspace_override = str(p)
        return {"ok": True, "workspace": str(p)}

    @router.get("/api/threads")
    async def threads_list(project_id: int | None = None):
        return {"threads": app.state.projects.list_threads(project_id)}

    @router.post("/api/threads")
    async def threads_create(req: NewThreadRequest):
        return app.state.projects.create_thread(req.project_id, req.title)

    @router.patch("/api/threads/{thread_id}")
    async def threads_rename(thread_id: str, req: RenameThreadRequest):
        app.state.projects.rename_thread(thread_id, req.title)
        return {"ok": True}

    @router.delete("/api/threads/{thread_id}")
    async def threads_delete(thread_id: str):
        app.state.projects.delete_thread(thread_id)
        return {"ok": True}

    @router.get("/api/threads/{thread_id}/messages")
    async def thread_messages(thread_id: str):
        """读取会话历史（checkpointer 消息 → [{role, content, reasoning?, toolCalls?}]），
        供切换会话时加载。reasoning = DeepSeek 深度思考原文；toolCalls = 工具调用
        （name + args + result，result 按 tool_call_id 与 ToolMessage 配对）。"""
        key = thread_id
        tr = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": key}})
        if tr is None:
            return {"messages": []}
        msgs = tr.checkpoint.get("channel_values", {}).get("messages") or tr.checkpoint.get(
            "messages", []
        )
        # 预收集 ToolMessage：tool_call_id → 结果文本
        tool_results: dict = {}
        for m in msgs:
            if type(m).__name__ == "ToolMessage":
                tid = getattr(m, "tool_call_id", None)
                if tid:
                    tool_results[tid] = _chunk_text(m)
        out = []
        pending: dict | None = None  # 工具调用轮（无正文）暂存，等下一个正文轮合并
        for m in msgs:
            c = _chunk_text(m)
            name = type(m).__name__
            if name == "HumanMessage":
                out.append({"role": "user", "content": c})
            elif name in ("AIMessage", "AIMessageChunk"):
                item: dict[str, Any] = {"role": "assistant", "content": c}
                r = _chunk_reasoning(m)
                if r:
                    item["reasoning"] = r
                tcs = []
                for tc in getattr(m, "tool_calls", None) or []:
                    tid = tc.get("id")
                    tcs.append(
                        {
                            "name": tc.get("name", ""),
                            "args": json.dumps(tc.get("args", {}), ensure_ascii=False),
                            "result": tool_results.get(tid),
                        }
                    )
                if tcs:
                    item["toolCalls"] = tcs
                if tcs and not c:
                    # 工具调用轮（正文为空）：暂存，与后续回复轮合并为一条
                    pending = item
                    continue
                if pending is not None and c and not tcs:
                    # 回复轮：合并工具卡片（豆包式：卡片 + 正文同一条消息）
                    item["toolCalls"] = pending.get("toolCalls")
                    if not item.get("reasoning") and pending.get("reasoning"):
                        item["reasoning"] = pending["reasoning"]
                    pending = None
                out.append(item)
        if pending is not None:
            out.append(pending)
        return {"messages": out}

    @router.post("/api/chat")
    async def chat(req: ChatRequest):
        """统一聊天入口：智能体团队（team 插件）启用时自动走 Supervisor 路由，否则单 Agent。"""
        # --- 会话元数据（V3 增强：项目/会话概念） ---
        store = app.state.projects
        is_new = False
        if req.thread_id and store.get_thread(req.thread_id):
            store.touch_thread(req.thread_id)
        elif req.thread_id:
            # 兼容旧 thread_id（外部传入的 key）：原样注册，不重新生成
            store.upsert_thread(req.thread_id, req.project_id)
            is_new = True
        else:
            t = store.create_thread(req.project_id)
            req.thread_id = t["id"]
            is_new = True
        thread_id = req.thread_id
        key = thread_id
        config = {"configurable": {"thread_id": key}}
        # 请求级上下文：fs 等插件工具经 contextvars 读取当前会话 thread_id（langchain
        # create_agent 的工具执行不注入 RunnableConfig，见 app/thread_ctx.py）
        _thread_ctx = thread_ctx.set(thread_id)
        loop = app.state.scope.get("agentLoop")
        agent, stream_mode = loop.resolve() if loop else (None, "messages")
        use_team = loop is not None and loop.supervisor is not None
        started = __import__("time").time()
        last_usage: dict = {}

        async def event_stream():
            yield sse("meta", {"thread_id": thread_id})
            app.state.event_bus.publish(
                MESSAGE_RECEIVED, {"message": req.message, "thread_id": thread_id}
            )
            # 需要模型命名的会话：回复流开始前并行启动标题生成（只基于用户消息），
            # 回复完成（done）后取结果回传 title 事件，标题几乎零等待回显
            cur_title = (store.get_thread(thread_id) or {}).get("title")
            need_title = is_new or is_placeholder_title(cur_title)
            title_task = (
                asyncio.create_task(_generate_thread_title(req.message, "")) if need_title else None
            )
            full = ""
            reasoning = ""
            tool_names: set[str] = set()
            tool_tracker: dict = {}
            try:
                async for ev in agent.astream(
                    {"messages": [{"role": "user", "content": req.message}]},
                    config=config,
                    stream_mode=stream_mode,
                ):
                    if use_team:
                        # 团队模式也用 "messages" 流：ev=(chunk, meta)。主图 router 的
                        # 路由决策（{"next": "..."}）不是最终回复，按 langgraph_node 过滤；
                        # 子 Agent 的 LLM chunk 与 ToolMessage 与单 Agent 同一套逻辑
                        chunk, meta = ev
                        node = (meta or {}).get("langgraph_node", "")
                        if node == "router":
                            continue
                        if type(chunk).__name__ == "ToolMessage":
                            yield sse(
                                "tool_result",
                                {
                                    "name": getattr(chunk, "name", ""),
                                    "result": _chunk_text(chunk),
                                },
                            )
                            continue
                        # subgraph（子 Agent）在旧版 LangGraph 的 messages 模式下产出
                        # 完整 AIMessage（每节点一轮一块），单 Agent 产出 AIMessageChunk
                        # 流式增量——两者统一处理：正文/思考/工具调用都透传
                        if type(chunk).__name__ not in ("AIMessage", "AIMessageChunk"):
                            continue
                        text = _chunk_text(chunk)
                        if text:
                            full += text
                            yield sse("token", {"content": text})
                        r = _chunk_reasoning(chunk)
                        if r:
                            reasoning += r
                            yield sse("reasoning", {"content": r})
                        for tname, targs in _chunk_tool_events(chunk, tool_tracker):
                            if tname and tname not in tool_names:
                                tool_names.add(tname)
                                yield sse("tool", {"name": tname, "args": targs})
                        _merge_usage(last_usage, chunk)
                    else:
                        # messages 模式：astream 产出 (chunk, metadata) 元组；只流模型回复（AI 片段）
                        chunk = ev[0] if isinstance(ev, tuple) else ev
                        if type(chunk).__name__ == "ToolMessage":
                            yield sse(
                                "tool_result",
                                {
                                    "name": getattr(chunk, "name", ""),
                                    "result": _chunk_text(chunk),
                                },
                            )
                            continue
                        if not isinstance(chunk, AIMessageChunk):
                            continue
                        text = _chunk_text(chunk)
                        if text:
                            full += text
                            yield sse("token", {"content": text})
                        r = _chunk_reasoning(chunk)
                        if r:
                            reasoning += r
                            yield sse("reasoning", {"content": r})
                        for tname, targs in _chunk_tool_events(chunk, tool_tracker):
                            if tname and tname not in tool_names:
                                tool_names.add(tname)
                                yield sse("tool", {"name": tname, "args": targs})
                        _merge_usage(last_usage, chunk)
                app.state.event_bus.publish(
                    RESPONSE_DONE,
                    {
                        "reply": full,
                        "thread_id": thread_id,
                        "latency_s": round(__import__("time").time() - started, 3),
                    },
                )
                yield sse(
                    "done",
                    {
                        "thread_id": thread_id,
                        "content": full,
                        "emotion": getattr(app.state, "last_emotion", "neutral"),
                        "usage": last_usage or None,
                        "latency_s": round(__import__("time").time() - started, 3),
                    },
                )
                if title_task is not None:
                    # 并行任务结果：通常已完成（回复期间已算好），失败回退首条消息截断
                    try:
                        title = title_task.result() if title_task.done() else await title_task
                    except Exception:  # noqa: BLE001 — 命名失败回退
                        title = None
                    if title:
                        store.rename_thread(thread_id, title)
                    else:
                        store.auto_title(thread_id, req.message)
                    yield sse(
                        "title",
                        {
                            "thread_id": thread_id,
                            "title": title or (store.get_thread(thread_id) or {}).get("title", ""),
                        },
                    )
                await _trace_turn(app, key, req.message, full, "", started)
            except Exception as e:  # 流中途出错：告知前端而非挂死
                if title_task is not None and not title_task.done():
                    title_task.cancel()
                yield sse("error", {"message": f"{e.__class__.__name__}: {e}"})
                await _trace_turn(app, key, req.message, "", str(e), started)

        return StreamingResponse(
            event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    @router.post("/api/supervisor/chat")
    async def supervisor_chat(req: ChatRequest):
        """Supervisor 多智能体入口（兼容保留）：LLM 路由 → companion/researcher 子 Agent。"""
        thread_id = req.thread_id or str(uuid.uuid4())
        key = f"sup::{thread_id}"
        config = {"configurable": {"thread_id": key}}
        _thread_ctx = thread_ctx.set(thread_id)
        if app.state.supervisor is None:
            raise HTTPException(400, "智能体团队插件未启用")
        agent: object = app.state.supervisor
        started = __import__("time").time()

        async def event_stream():
            yield sse("meta", {"thread_id": thread_id})
            full = ""
            try:
                async for ev in agent.astream(
                    {"messages": [{"role": "user", "content": req.message}]},
                    config=config,
                    stream_mode="updates",
                ):
                    # updates 模式：每个节点一轮 {"node": {...}}；子 Agent 输出含 AIMessage
                    for node, payload in ev.items():
                        if node in ("companion", "researcher"):
                            msgs = (payload or {}).get("messages", [])
                            for m in msgs:
                                if isinstance(m, AIMessageChunk) or type(m).__name__ == "AIMessage":
                                    text = _chunk_text(m)
                                    if text:
                                        full += text
                                        yield sse("token", {"content": text})
                                    break
                yield sse("done", {"thread_id": thread_id, "content": full})
                await _trace_turn(app, key, req.message, full, "", started)
            except Exception as e:
                yield sse("error", {"message": f"{e.__class__.__name__}: {e}"})
                await _trace_turn(app, key, req.message, "", str(e), started)

        return StreamingResponse(
            event_stream(), media_type="text/event-stream", headers=SSE_HEADERS
        )

    @router.get("/api/supervisor/info")
    async def supervisor_info():
        return {
            "enabled": app.state.supervisor is not None,
            "agents": (
                {
                    "companion": {"tools": app.state.subagents["companion"]["tools"]},
                    "researcher": {"tools": app.state.subagents["researcher"]["tools"]},
                }
                if app.state.supervisor is not None
                else {}
            ),
        }

    @router.get("/logs")
    async def logs(n: int = 20):
        """最近 n 条调用 trace（本地开发用，无鉴权）。"""
        return {
            "count": len(app.state.trace_logger.tail(n)),
            "entries": app.state.trace_logger.tail(n),
        }

    @router.get("/api/approvals")
    async def approvals():
        return {"pending": app.state.gate.pending()}

    @router.post("/api/approvals/{pid}/approve")
    async def approve(pid: str):
        return {"result": await app.state.gate.approve(pid)}

    @router.post("/api/approvals/{pid}/reject")
    async def reject(pid: str):
        return {"result": app.state.gate.reject(pid)}

    return router
