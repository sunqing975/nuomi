"""nuomi 后端入口（v0.13）：FastAPI 装配。

架构：transport（协议）→ domain（业务层）→ infra/harness（适配层）→ octop-harness。
启动时：建库 + 种子默认专家（糯米）；退出时：释放全部 Agent 实例。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT, settings
from app.domain.agents.seed import default_system_prompt, default_welcome_message
from app.domain.agents.service import agent_service
from app.infra.harness.manager import manager
from app.storage.db import init_db
from app.transport.api import router
from app.transport.knowledge_api import router as knowledge_router
from app.transport.openai_compat import router as openai_router


def seed_default_agent() -> None:
    """agents 表为空时创建默认专家（糯米，AI 助手人格）。"""
    if agent_service.list_all():
        return
    agent_service.create(
        {
            "name": "糯米",
            "description": "住在你电脑里的人工智能助手：能干、记得、在乎",
            "system_prompt": default_system_prompt(),
            "icon_name": "bot",
            "color": "#f59e0b",
            "welcome_message": default_welcome_message(),
            "kind": "expert",
        }
    )


def ensure_agent_workspaces() -> None:
    """启动时为全部专家补齐独立 workspace（persona 文件 + manifest）。"""
    from app.domain.agents.service import ensure_agent_workspace

    for row in agent_service.list_all():
        ensure_agent_workspace(row["agent_id"], row["name"])


@asynccontextmanager
async def lifespan(_: FastAPI):
    _sync_env_file()  # 应用设置 env（env.json）→ 进程环境，先于一切
    init_db()
    seed_default_agent()
    ensure_agent_workspaces()
    _ensure_model_plugins()
    _sync_plugins()
    _sync_connectors_file()
    _resume_knowledge_index_jobs()
    yield
    manager.close()


def _resume_knowledge_index_jobs() -> None:
    """启动时恢复中断的知识库索引任务（上次进程退出时 pending/processing 的文档）。"""
    from contextlib import suppress

    from app.infra.knowledge.jobs import resume_pending_index_jobs

    with suppress(Exception):
        resume_pending_index_jobs()


def _sync_env_file() -> None:
    """环境变量源：{workspace}/env.json（应用设置页维护）→ os.environ。"""
    from app.infra.env_store import apply

    apply()


def _sync_connectors_file() -> None:
    """连接器配置源：data_root/connectors.json 优先（控制台增删后持久化），无文件时用 env 种子。"""
    from app.config import settings

    p = settings.data_root / "connectors.json"
    if not p.is_file():
        return
    try:
        import json

        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            settings.mcp_servers = data
    except Exception:
        pass


def _ensure_model_plugins() -> None:
    """确保共享AI 数字人插件（vrm-avatar）存在，且启停对齐AI 数字人开关（方案B）。

    工具由 PluginService.tools() 装配时按当前激活模型/动画动态构造。
    """
    from contextlib import suppress

    from app.domain.avatar.service import (
        VRM_AVATAR_PLUGIN_ID,
        ensure_avatar_plugins,
        get_avatar_enabled,
    )
    from app.domain.plugins.service import plugin_service

    with suppress(Exception):
        ensure_avatar_plugins()
        plugin_service.sync()  # 保底：DB 无记录时 INSERT（幂等）
        plugin_service.set_enabled(VRM_AVATAR_PLUGIN_ID, get_avatar_enabled())


def _sync_plugins() -> None:
    """启动时加载工作区插件（失败不阻断启动，可在 /api/plugins/sync 重试）。"""
    from contextlib import suppress

    from app.domain.plugins.service import plugin_service

    with suppress(Exception):
        plugin_service.sync()


app = FastAPI(title="nuomi", version="0.13.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(openai_router)
app.include_router(knowledge_router)

# —— 前端控制台（frontend/dist 静态挂载，同源零 CORS；浏览器或壳内都访问 /console/）——
_FRONTEND_DIR = REPO_ROOT / "frontend" / "dist"
if not _FRONTEND_DIR.is_dir():
    _FRONTEND_DIR = REPO_ROOT / "frontend"  # 未构建时退回源码根（仅 dev 辅助）
if _FRONTEND_DIR.is_dir():
    app.mount("/console", StaticFiles(directory=_FRONTEND_DIR, html=True), name="console")
