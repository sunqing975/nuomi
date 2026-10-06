"""设置/系统路由：环境变量 + LLM Provider + Langfuse 观测 + 工作区总览 + 健康检查。

从 transport/api.py 拆出（P0-2，2026-10-06）——按域拆分，保持端点数不变。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.agents.service import agent_service
from app.domain.plugins.service import plugin_service
from app.domain.skills.service import skill_service
from app.infra import env_store
from app.infra.harness.manager import manager

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/session-token")
async def session_token() -> dict:
    """本机 API token（同源客户端获取，用于 ``/api/*`` 写操作）。

    守卫中间件只放行「无 Origin（同源/非浏览器客户端）」或「本机 Origin」的请求；
    跨站页面即便发起请求也拿不到响应（CORS 不放行），因此不构成 token 泄漏。
    """
    from app.infra.local_guard import api_token

    return {"token": api_token()}


class EnvSaveBody(BaseModel):
    """环境变量整体保存请求体（应用设置，对齐 octop）。"""

    values: dict[str, str] = Field(default_factory=dict)


@router.get("/settings/env")
async def get_app_env() -> dict[str, str]:
    """应用环境变量（技能/连接器 API key 等；存 {workspace}/env.json）。

    **疑似密钥的键名做脱敏返回**（``sk-2***fa1e``）：这些值会渲染进控制台 DOM，
    一旦有 XSS 或插件的同源脚本就能整包读走明文密钥。PUT 侧把含 ``***`` 的值
    当作「保持原值」，所以前端原样回写不会覆盖真实 key（与 providers 同语义）。
    """
    return env_store.mask_all(env_store.load())


@router.put("/settings/env")
async def put_app_env(body: EnvSaveBody) -> dict[str, str]:
    """整体保存环境变量：即时注入进程 env，并释放 agent 实例（下次对话生效）。

    返回脱敏视图（不把明文密钥回给前端）。
    """
    saved = env_store.save(body.values)
    manager.close()
    return env_store.mask_all(saved)


class ProviderBody(BaseModel):
    """大模型 Provider 保存请求体（对齐 octop providers 管理）。

    api_key 为空串 = 保持原值（编辑不显式改就不动）。
    """

    providers: list[dict] = Field(description="provider 列表（整体保存）")


def _validate_providers(providers: list[dict], existing: list[dict]) -> list[dict]:
    if not providers:
        raise HTTPException(status_code=400, detail="至少保留一个 Provider")
    ids: set[str] = set()
    out: list[dict] = []
    for i, p in enumerate(providers):
        pid = str(p.get("id") or "").strip()
        base_url = str(p.get("base_url") or "").strip()
        if not pid:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 个 Provider 缺少 id")
        if pid in ids:
            raise HTTPException(status_code=400, detail=f"Provider id 重复: {pid}")
        ids.add(pid)
        if not base_url:
            raise HTTPException(status_code=400, detail=f"Provider「{pid}」缺少 base_url")
        models = [
            {
                "id": str(m.get("id") or "").strip(),
                "name": str(m.get("name") or "").strip() or str(m.get("id") or "").strip(),
            }
            for m in (p.get("models") or [])
            if str(m.get("id") or "").strip()
        ]
        if not models:
            raise HTTPException(status_code=400, detail=f"Provider「{pid}」至少需要一个模型")
        # api_key 空串或脱敏串（含 ***）= 保持原值（按 id 匹配旧配置）
        # 防呆：GET 返回的脱敏串（sk-2***fa1e）若被前端回写，绝不能当真实 key 存
        api_key = str(p.get("api_key") or "").strip()
        if not api_key or "***" in api_key:
            old = next((x for x in existing if x.get("id") == pid), None)
            api_key = (old or {}).get("api_key") or ""
        if not api_key:
            raise HTTPException(
                status_code=400, detail=f"Provider「{pid}」缺少 API Key（harness 要求非空）"
            )
        out.append(
            {
                "id": pid,
                "name": str(p.get("name") or "").strip() or pid,
                "base_url": base_url,
                "api_key": api_key,
                "protocol": str(p.get("protocol") or "openai").strip() or "openai",
                "models": models,
            }
        )
    return out


class ProviderProbeBody(BaseModel):
    """Provider 模型探测请求体（不落盘，仅探测一次）。"""

    base_url: str = Field(description="OpenAI 兼容服务的 base_url")
    api_key: str = Field(default="", description="探测用 API Key（不落盘）")


@router.post("/settings/providers/probe")
async def probe_provider_models(body: ProviderProbeBody) -> dict:
    """探测服务的 /models 接口，返回可用模型 id 列表（新增 Provider 时拉取勾选用）。"""
    from app.infra.providers_store import probe_models

    try:
        models = await asyncio.to_thread(probe_models, body.base_url, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}


@router.get("/settings/providers")
async def get_providers() -> dict:
    """大模型 Provider 列表（api_key 脱敏；未配置过时返回 .env 种子）。"""
    from app.infra.providers_store import load, mask_key

    provs = []
    for p in load():
        provs.append({**p, "api_key": mask_key(p.get("api_key") or "")})
    return {"providers": provs}


@router.put("/settings/providers")
async def put_providers(body: ProviderBody) -> dict:
    """整体保存大模型 Provider：写 providers.json + 释放实例（下次对话生效）。

    模型不绑专家（2026-10-04）：不校验/重置任何专家字段，对话时 per-turn 选模型。
    """
    from app.infra.providers_store import load as load_providers
    from app.infra.providers_store import save

    existing = load_providers()
    providers = _validate_providers(body.providers, existing)
    save(providers)
    manager.close()
    return {"ok": True, "providers": len(providers)}


class LangfuseBody(BaseModel):
    """Langfuse 观测配置保存请求体（secret_key 为空串/脱敏串 = 保持原值）。"""

    enabled: bool = Field(description="启用 Langfuse 轨迹")
    host: str = Field(default="", description="Langfuse 服务地址（云或自托管）")
    public_key: str = Field(default="", description="Langfuse Public Key")
    secret_key: str = Field(default="", description="Langfuse Secret Key（留空保持原值）")


class LangfuseTestBody(BaseModel):
    """Langfuse 连接测试请求体（不落盘；secret 为脱敏串时复用已存值）。"""

    host: str = Field(default="")
    public_key: str = Field(default="")
    secret_key: str = Field(default="")


def _langfuse_probe(client) -> bool:
    """Langfuse 凭据校验 + 冲刷（同步网络调用，供 to_thread 调用）。"""
    ok = bool(client.auth_check())
    client.flush()
    return ok


@router.get("/settings/langfuse")
async def get_langfuse() -> dict:
    """Langfuse 观测配置（secret_key 脱敏展示）。"""
    from app.infra.harness.langfuse_store import load, mask_secret

    cfg = load()
    return {
        "enabled": cfg["enabled"],
        "host": cfg["host"],
        "public_key": cfg["public_key"],
        "secret_key": mask_secret(cfg["secret_key"]),
    }


@router.put("/settings/langfuse")
async def put_langfuse(body: LangfuseBody) -> dict:
    """保存 Langfuse 配置：写 langfuse.json + 热更新 harness tracer（即时生效）。

    启用时要求凭据齐全；停用则仅存开关，保留凭据供下次启用复用。
    """
    from octop_harness.observability.langfuse import LangfuseConfig

    from app.infra.harness.langfuse_store import load as load_langfuse_cfg
    from app.infra.harness.langfuse_store import save as save_langfuse_cfg

    existing = load_langfuse_cfg()
    host = (body.host or "").strip().rstrip("/")
    if not host:
        raise HTTPException(status_code=400, detail="Langfuse Host 必填")
    public_key = (body.public_key or "").strip()
    if not public_key:
        raise HTTPException(status_code=400, detail="Langfuse Public Key 必填")
    secret = (body.secret_key or "").strip()
    if not secret or "***" in secret:
        secret = existing.get("secret_key") or ""
    if body.enabled and not secret:
        raise HTTPException(
            status_code=400,
            detail="启用 Langfuse 需要 Secret Key（当前未配置且本次未填写）",
        )
    cfg = save_langfuse_cfg(
        {
            "enabled": bool(body.enabled),
            "host": host,
            "public_key": public_key,
            "secret_key": secret,
        }
    )
    manager.set_langfuse(LangfuseConfig(**cfg))
    return {"ok": True, "enabled": bool(body.enabled)}


@router.post("/settings/langfuse/test")
async def test_langfuse(body: LangfuseTestBody) -> dict:
    """用给定配置校验 Langfuse 凭据（auth_check；不落盘）。"""
    from langfuse import Langfuse

    from app.infra.harness.langfuse_store import load as load_langfuse_cfg

    host = (body.host or "").strip().rstrip("/")
    public_key = (body.public_key or "").strip()
    secret = (body.secret_key or "").strip()
    if "***" in secret:
        secret = (load_langfuse_cfg().get("secret_key") or "").strip()
    if not host or not public_key or not secret:
        raise HTTPException(status_code=400, detail="Host / Public Key / Secret Key 均为必填")
    try:
        client = Langfuse(host=host, public_key=public_key, secret_key=secret)
        # auth_check 与 flush 都是同步网络调用 —— 一起放线程，别只搬一个
        ok = bool(await asyncio.to_thread(_langfuse_probe, client))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"连接失败：{exc}") from exc
    if not ok:
        raise HTTPException(
            status_code=401, detail="Langfuse 凭据校验未通过（Public/Secret Key 或 Host 有误）"
        )
    return {"ok": True, "host": host}


@router.get("/workspace")
async def workspace_overview() -> dict:
    """工作区与能力总览（控制台「存储」板块）。"""
    return {
        "workspace": str(settings.workspace_path),
        "data_root": str(settings.data_root),
        "counts": {
            "experts": len(agent_service.list_all()),
            "plugins": len(plugin_service.list_all()),
            "skills": len(skill_service.list_all()),
            "connectors": len(settings.mcp_servers),
        },
    }
