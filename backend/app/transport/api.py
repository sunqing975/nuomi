"""API 路由：健康检查 + Agent 生命周期 + SSE 流式对话 + 会话管理。

对话协议（桌宠前端/控制台消费）：
    POST /api/agents/{agent_id}/chat   body={"messages": "...", "thread_id": "..."}
    → OpenAI Chat Completions 流式格式（delta.content / delta.tool_calls / [DONE]）

会话：以工作区 nuomi-state.json 为权威（thread_id / threads，2026-10-04 起，
无 default 桌宠线程、无模型专属会话；桌宠=纯表现层，拦截工具调用播放动作）。
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.domain.agents.service import (
    STATE_RUNNING,
    STATE_STOPPED,
    agent_service,
)
from app.domain.chat.service import chat_sessions
from app.domain.plugins.service import plugin_service
from app.domain.skillpackages.service import skill_package_service
from app.domain.skills.service import skill_service
from app.infra import env_store, skillhub
from app.infra.harness.chat import stream_chat, stream_octop_sse
from app.infra.harness.manager import manager
from app.infra.pet_events import pet_events
from app.storage import db

router = APIRouter(prefix="/api", tags=["chat"])


def _slug_from_hub(name: str) -> str:
    """市场 slug → 本地目录名（小写 kebab，长度受限）。"""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s[:64] or "skill"


def _all_skills_dirs() -> list:
    """注入用技能根列表：工作区单技能 + 各已启用技能包内技能目录。"""
    return [skill_service.skills_dir(), *skill_package_service.skills_dirs()]


def _available_skill_keys() -> set[str]:
    """per-turn 可用的技能名/slug 集合（已启用工作区技能 + 已启用技能包内技能）。"""
    keys = {s["name"] for s in skill_service.list_all() if s.get("enabled")}
    for pkg in skill_package_service.list_all():
        if not pkg.get("enabled"):
            continue
        keys.update(s["slug"] for s in pkg.get("skills") or [] if s.get("enabled"))
    return keys


def _resolve_chat_abilities(skills, connectors) -> tuple[list[str] | None, list[str] | None]:
    """校验并归一化 per-turn 能力选择（skills / connectors），返回 (skills, connectors)。

    skills：None=全量技能；[]=禁用全部；列表=只启用这些（须存在于可用技能集合）。
    connectors：None=默认连接器（agent 配置）；[]=不挂载；列表=只挂载这些（须已配置）。
    """
    if skills is not None:
        for name in skills:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail="技能名不能为空")
        unknown = [n for n in skills if n not in _available_skill_keys()]
        if unknown:
            raise HTTPException(status_code=400, detail=f"技能不存在或未启用: {', '.join(unknown)}")
        skills = [s.strip() for s in skills]
    if connectors is not None:
        for name in connectors:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail="连接器名不能为空")
        unknown = [n for n in connectors if n not in settings.mcp_servers]
        if unknown:
            raise HTTPException(status_code=400, detail=f"连接器不存在: {', '.join(unknown)}")
        connectors = [c.strip() for c in connectors]
    return skills, connectors


# ---------- 对话 ----------


class ChatBody(BaseModel):
    messages: str = Field(description="用户输入文本")
    thread_id: str = Field(default="default", description="会话线程 ID（按线程隔离记忆）")
    skills: list[str] | None = Field(
        default=None,
        description="本次对话启用的技能（name/slug；None=全部，[]=禁用全部）",
    )
    connectors: list[str] | None = Field(
        default=None,
        description="本次对话挂载的连接器（None=默认，[]=不挂载）",
    )


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------- 会话管理（工作区 nuomi-state.json 权威，控制台读写） ----------


class ChatNewBody(BaseModel):
    agent_id: str


class ChatSwitchBody(BaseModel):
    agent_id: str
    thread_id: str


class ChatTouchBody(BaseModel):
    agent_id: str
    thread_id: str
    title: str | None = None


@router.get("/chat/state")
async def chat_state(agent_id: str) -> dict:
    """某专家的当前会话 + 会话列表。"""
    return chat_sessions.state(agent_id)


@router.post("/chat/new")
async def chat_new(body: ChatNewBody) -> dict:
    """新建会话并设为当前（控制台「新会话」）。"""
    return chat_sessions.new(body.agent_id)


@router.post("/chat/switch")
async def chat_switch(body: ChatSwitchBody) -> dict:
    """切换当前会话（写 nuomi-state.json，控制台会话列表）。"""
    ok = chat_sessions.switch(body.agent_id, body.thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"agent_id": body.agent_id, "thread_id": body.thread_id}


@router.post("/chat/touch")
async def chat_touch(body: ChatTouchBody) -> dict:
    """更新会话时间/标题。"""
    chat_sessions.touch(body.agent_id, body.thread_id, body.title)
    return {"ok": True}


@router.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(agent_id: str, thread_id: str) -> dict:
    """删除会话（含该线程的 LLM 对话上下文）。删除当前会话自动切到最近会话。"""
    if agent_service.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not chat_sessions.delete(agent_id, thread_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


async def _publish_actions(events):
    """转发内部事件流，并把工具调用（动作/表情）广播给桌宠壳。"""
    async for ev in events:
        if ev.get("type") == "tool_call" and ev.get("name"):
            pet_events.publish(ev["name"])
        yield ev


@router.get("/pet/events")
async def pet_events_sse(request: Request) -> StreamingResponse:
    """桌宠动作事件流（SSE 长连接）：任意对话产生的工具调用实时广播。"""

    async def gen():
        async for ev in pet_events.stream():
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agents/{agent_id}/chat/history")
async def chat_history(agent_id: str, thread_id: str, limit: int = 100) -> list[dict]:
    """按线程取对话历史（octop checkpointer）。"""
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    agent = manager.get_agent(
        agent_id,
        name=agent_row["name"],
        system_prompt=agent_row["system_prompt"] or "",
    )
    msgs = await agent.aget_history(thread_id, limit=limit)
    out: list[dict] = []
    for m in msgs:
        role = {"human": "user", "ai": "assistant"}.get(getattr(m, "type", ""))
        content = getattr(m, "content", None)
        if not role or not content:
            continue
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)
            except Exception:
                continue
        out.append({"role": role, "content": content})
    return out


@router.post("/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatBody, request: Request) -> StreamingResponse:
    agent_row = agent_service.get(agent_id)
    if agent_row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not agent_row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    # per-turn 能力校验必须在流开始前完成（generator 内抛错不会转成 400）
    skills, connectors = _resolve_chat_abilities(body.skills, body.connectors)

    async def gen():
        tools = plugin_service.tools()
        async for frame in stream_octop_sse(
            _publish_actions(
                stream_chat(
                    body.messages,
                    body.thread_id,
                    agent_id=agent_id,
                    name=agent_row["name"],
                    system_prompt=agent_row["system_prompt"] or "",
                    plugin_tools=tools,
                    skills_dir=_all_skills_dirs(),
                    skills_disabled=skill_service.disabled_set(),
                    mcp_server_configs=settings.mcp_servers,
                    mcp_default_servers=list(settings.mcp_servers.keys()) or None,
                    skills=skills,
                    connectors=connectors,
                )
            ),
            thread_id=body.thread_id,
        ):
            if await request.is_disconnected():
                break
            yield frame

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Agent 生命周期（对齐 Octop agents 语义） ----------


class AgentCreateBody(BaseModel):
    name: str
    description: str = ""
    persona_mbti: str = ""
    default_model: str = "llm/deepseek-chat"
    system_prompt: str = ""
    enabled: bool = True
    icon_name: str = ""
    icon_url: str = ""
    color: str = ""
    welcome_message: str = ""


class AgentPatchBody(BaseModel):
    name: str | None = None
    description: str | None = None
    persona_mbti: str | None = None
    default_model: str | None = None
    system_prompt: str | None = None
    enabled: bool | None = None
    icon_name: str | None = None
    icon_url: str | None = None
    color: str | None = None
    welcome_message: str | None = None


@router.get("/agents")
async def list_agents() -> list[dict]:
    return agent_service.list_all()


@router.post("/agents")
async def create_agent(body: AgentCreateBody) -> dict:
    return agent_service.create(body.model_dump())


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentPatchBody) -> dict:
    row = agent_service.update(agent_id, body.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return row


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    manager.release(agent_id)
    if not agent_service.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return {"ok": True}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not row.get("enabled"):
        raise HTTPException(status_code=400, detail="Agent 已停用")
    manager.get_agent(
        agent_id,
        name=row["name"],
        system_prompt=row["system_prompt"],
        plugin_tools=plugin_service.tools(),
        skills_dir=_all_skills_dirs(),
        skills_disabled=skill_service.disabled_set(),
        mcp_server_configs=settings.mcp_servers,
        mcp_default_servers=list(settings.mcp_servers.keys()) or None,
    )
    agent_service.set_state(agent_id, STATE_RUNNING)
    return {"ok": True, "state": STATE_RUNNING}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    manager.release(agent_id)
    agent_service.set_state(agent_id, STATE_STOPPED)
    return {"ok": True, "state": STATE_STOPPED}


@router.get("/agents/{agent_id}/status")
async def agent_status(agent_id: str) -> dict:
    row = agent_service.get(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    runtime = "running" if manager.has(agent_id) else "stopped"
    return {"agent_id": agent_id, "runtime": runtime, "last_state": row.get("last_state")}


# ---------- 插件（能力域：对齐 Octop 插件概念） ----------


class PluginPatchBody(BaseModel):
    enabled: bool | None = None


@router.get("/plugins")
async def list_plugins() -> list[dict]:
    return plugin_service.list_all()


@router.post("/plugins/sync")
async def sync_plugins() -> list[dict]:
    """重新扫描工作区 plugins/ 并加载（新插件默认启用）。"""
    return plugin_service.sync()


@router.post("/plugins/import")
async def import_plugin_zip(file: UploadFile = File(...)) -> dict:
    """从 zip 导入插件到工作区 plugins/<id>/（格式：plugin.yaml + entry 文件）。

    导入成功默认启用；释放全部 agent 实例，下次对话即可用新插件工具。
    """
    from app.domain.importer import import_plugin_zip as _import

    try:
        plugin = _import(await file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()  # 释放全部实例：下次对话重建，挂载新插件工具
    return {"ok": True, "plugin": plugin}


class GitImportBody(BaseModel):
    """git 仓库导入请求体。"""

    url: str = Field(..., min_length=4, description="仓库地址（https/ssh/git@）")


@router.post("/plugins/import-git")
async def import_plugin_git(body: GitImportBody) -> dict:
    """从 git 仓库导入插件到工作区 plugins/<id>/（浅克隆，50MB 上限）。"""
    from app.domain.importer import import_plugin_git as _import

    try:
        plugin = _import(body.url.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()
    return {"ok": True, "plugin": plugin}


@router.patch("/plugins/{plugin_id}")
async def patch_plugin(plugin_id: str, body: PluginPatchBody) -> dict:
    if body.enabled is not None and plugin_id in plugin_service.model_plugin_ids():
        raise HTTPException(
            status_code=400,
            detail="桌宠模型插件由「桌宠」页切换模型控制（同一时间只启用一个），不能手动启停",
        )
    row = (
        plugin_service.set_enabled(plugin_id, body.enabled)
        if body.enabled is not None
        else plugin_service.get(plugin_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    return row


@router.delete("/plugins/{plugin_id}")
async def delete_plugin(plugin_id: str) -> dict:
    """删除插件（含插件目录）。模型插件由「桌宠」删除模型时级联删除。"""
    if plugin_id in plugin_service.model_plugin_ids():
        raise HTTPException(
            status_code=400, detail="桌宠模型插件由「桌宠」页删除模型时级联删除，不能单独删除"
        )
    if not plugin_service.delete(plugin_id):
        raise HTTPException(status_code=404, detail="插件不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再携带被删插件工具
    return {"ok": True}


# ---------- 技能（能力域：对齐 Octop 技能概念） ----------


class SkillPatchBody(BaseModel):
    enabled: bool | None = None


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
    from app.domain.importer import import_skill_zip as _import

    try:
        skill = _import(await file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    manager.close()  # 释放全部实例：下次对话重建，注入新技能
    return {"ok": True, "skill": skill}


@router.post("/skills/import-git")
async def import_skill_git(body: GitImportBody) -> dict:
    """从 git 仓库导入技能到工作区 skills/<name>/（浅克隆，50MB 上限）。"""
    from app.domain.importer import import_skill_git as _import

    try:
        skill = _import(body.url.strip())
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
    return row


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str) -> dict:
    """删除技能（含技能目录）。"""
    if not skill_service.delete(skill_name):
        raise HTTPException(status_code=404, detail="技能不存在")
    manager.close()  # 释放全部实例：下次对话重建，不再注入被删技能
    return {"ok": True}


# ---------- SkillHub 技能市场 ----------


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


class EnvSaveBody(BaseModel):
    """环境变量整体保存请求体（应用设置，对齐 octop）。"""

    values: dict[str, str] = Field(default_factory=dict)


@router.get("/settings/env")
async def get_app_env() -> dict[str, str]:
    """应用环境变量（技能/连接器 API key 等；存 {workspace}/env.json）。"""
    return env_store.load()


@router.put("/settings/env")
async def put_app_env(body: EnvSaveBody) -> dict[str, str]:
    """整体保存环境变量：即时注入进程 env，并释放 agent 实例（下次对话生效）。"""
    saved = env_store.save(body.values)
    manager.close()
    return saved


@router.get("/skillhub/search")
async def skillhub_search(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return skillhub.search(q, page=page, page_size=page_size)


@router.get("/skillhub/rankings")
async def skillhub_rankings(
    ranking_type: str = "hot", page: int = 1, page_size: int = 20
) -> list[dict]:
    return skillhub.rankings(ranking_type, page=page, page_size=page_size)


@router.get("/skillhub/skillsets/{slug}")
async def skillhub_skillset(slug: str) -> dict:
    return skillhub.skillset_detail(slug)


@router.get("/skillhub/skillsets")
async def skillhub_skillset_list(q: str = "", page: int = 1, page_size: int = 20) -> list[dict]:
    return skillhub.skillset_list(q, page=page, page_size=page_size)


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
        files = skillhub.download(slug)
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
        return skill_package_service.install_from_skillhub(slug, name=body.name)
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
        import shutil

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
    return row


@router.delete("/skill-packages/{package_id}")
async def delete_skill_package(package_id: str) -> dict:
    """删除技能包（DB + 包目录）。"""
    if not skill_package_service.delete(package_id):
        raise HTTPException(status_code=404, detail="技能包不存在")
    manager.close()
    return {"ok": True}


# ---------- MCP 服务器（连接器：控制台增删改，写 data_root/connectors.json，manager.close 重载） ----------

_CONNECTOR_TRANSPORTS = ("stdio", "sse", "http")


class ConnectorBody(BaseModel):
    name: str | None = None  # POST 创建时必填；PUT 以路径名为准
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)


def _validate_connector_spec(body: ConnectorBody) -> dict:
    transport = (body.transport or "stdio").strip().lower()
    if transport not in _CONNECTOR_TRANSPORTS:
        raise HTTPException(
            status_code=400, detail=f"transport 仅支持 {', '.join(_CONNECTOR_TRANSPORTS)}"
        )
    if transport == "stdio" and not (body.command or "").strip():
        raise HTTPException(status_code=400, detail="stdio 传输需要 command")
    return {
        "transport": transport,
        "command": (body.command or "").strip(),
        "args": list(body.args or []),
    }


def _persist_connectors() -> None:
    """写 data_root/connectors.json（重启后由 main._sync_mcp_file 读回，json 为权威）。"""
    p = settings.data_root / "connectors.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.mcp_servers, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/connectors")
async def list_connectors() -> list[dict]:
    """连接器列表（配置来自 settings.mcp_servers，connectors.json 权威）。"""
    return [
        {
            "name": name,
            "transport": spec.get("transport", "stdio"),
            "command": spec.get("command", ""),
            "args": spec.get("args", []),
        }
        for name, spec in settings.mcp_servers.items()
    ]


@router.post("/connectors")
async def create_connector(body: ConnectorBody) -> dict:
    """新增连接器：写配置 + 释放实例，下次对话挂载其工具。"""
    name = (body.name or "").strip()
    if not name or not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise HTTPException(status_code=400, detail="连接器名仅限字母/数字/_/-")
    if name in settings.mcp_servers:
        raise HTTPException(status_code=400, detail=f"连接器已存在: {name}")
    spec = _validate_connector_spec(body)
    settings.mcp_servers[name] = spec
    _persist_connectors()
    manager.close()  # 重载：下次对话重建实例，挂载新 MCP 工具
    return {"ok": True, "name": name, **spec}


@router.put("/connectors/{name}")
async def update_connector(name: str, body: ConnectorBody) -> dict:
    """编辑连接器：更新配置 + 释放实例（下次对话生效）。"""
    if name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail="连接器不存在")
    spec = _validate_connector_spec(body)
    settings.mcp_servers[name] = spec
    _persist_connectors()
    manager.close()
    return {"ok": True, "name": name, **spec}


@router.delete("/connectors/{name}")
async def delete_connector(name: str) -> dict:
    """删除连接器：从运行配置移除并持久化（data_root/connectors.json），
    释放全部 agent 实例，下次对话重建后不再挂载该连接器工具。
    """
    if name not in settings.mcp_servers:
        raise HTTPException(status_code=404, detail="连接器不存在")
    settings.mcp_servers.pop(name)
    _persist_connectors()
    manager.close()
    return {"ok": True}


# ---------- 存储 / 工作区总览 ----------


@router.get("/workspace")
async def workspace_overview() -> dict:
    """工作区与能力总览（控制台「存储」板块）。"""
    from app.domain.skills.service import skill_service

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


# ---------- 桌宠模型（表现层资产） ----------


class PetModelSwitchBody(BaseModel):
    model_id: str = Field(description="模型 id（工作区 models/2D/ 下的目录名）")


@router.get("/pet/models")
async def list_pet_models() -> dict:
    """模型资产列表：每个模型的动作/表情清单 + 当前激活模型。"""
    from app.domain.pet.service import get_active_model, list_models

    return {"models": list_models(), "active": get_active_model()}


@router.get("/pet/status")
async def get_pet_status() -> dict:
    """桌宠开关状态（壳 config.json ui.pet_enabled）。"""
    from app.domain.pet.service import get_pet_enabled

    return {"enabled": get_pet_enabled()}


class PetStatusBody(BaseModel):
    enabled: bool = Field(description="桌宠开关：true=开（创建桌宠窗口），false=关（销毁窗口）")


@router.put("/pet/status")
async def set_pet_status(body: PetStatusBody) -> dict:
    """设置桌宠开关：写壳 config.json ui.pet_enabled，壳 watch 后创建/销毁桌宠窗口。"""
    from app.domain.pet.service import set_pet_enabled

    return {"enabled": set_pet_enabled(body.enabled)}


@router.post("/pet/models/switch")
async def switch_pet_model(body: PetModelSwitchBody) -> dict:
    """切换桌宠模型：更新壳 config.json + 插件互斥联动（只启用该模型的插件）。

    模型插件互斥走插件启停（热生效）：同一时间只启用激活模型的插件，
    其他模型插件禁用 → 工具未挂载自然不进 LLM 工具集，无需装配层过滤。
    专家不绑定插件（2026-10-04 解耦）：释放 shell agent 实例，下次对话重建
    即携带新模型插件的动作/表情工具。
    """
    from app.domain.pet.service import get_shell_agent_id, switch_model

    try:
        model = switch_model(body.model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    model_plugin_ids = plugin_service.model_plugin_ids()
    has_plugin = model["id"] in model_plugin_ids
    if has_plugin:
        for pid in model_plugin_ids:
            plugin_service.set_enabled(pid, pid == model["id"])
    agent_id = get_shell_agent_id()
    if agent_id:
        # 工具集随插件启停变化：释放 agent 实例，下次对话重建（带新模型插件工具）
        manager.release(agent_id)

    return {
        "ok": True,
        "model": model,
        "agent_id": agent_id,
        "activated_plugin": model["id"] if has_plugin else None,
    }


@router.delete("/pet/models/{model_id}")
async def delete_pet_model(model_id: str) -> dict:
    """删除桌宠模型：级联删模型插件 + 资产目录；删除激活模型自动切到剩余模型。

    内置模型（种子分发）页面不提供删除入口；即便绕过删除，启动播种也会自愈复原。
    """
    from app.domain.pet.service import delete_model

    try:
        result = delete_model(model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    agent_id = None
    if result["was_active"]:
        from app.domain.pet.service import get_shell_agent_id

        agent_id = get_shell_agent_id()
        if agent_id:
            manager.release(agent_id)  # 模型/插件已变，释放实例下次对话重建
    return {"ok": True, **result, "agent_id": agent_id}
