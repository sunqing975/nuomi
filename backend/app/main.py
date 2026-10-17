"""nuomi 后端入口（v0.13）：FastAPI 装配。

架构：transport（协议）→ domain（业务层）→ infra/harness（适配层）→ octop-harness。
启动时：建库 + 种子默认专家（糯米）；退出时：释放全部 Agent 实例。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT, settings
from app.domain.agents.seed import default_system_prompt, default_welcome_message
from app.domain.agents.service import agent_service
from app.infra.harness.manager import manager
from app.infra.local_guard import LocalGuardMiddleware
from app.storage.db import init_db
from app.transport.agents_api import router as agents_router
from app.transport.avatar_api import router as avatar_router
from app.transport.chat_api import router
from app.transport.connectors_api import router as connectors_router
from app.transport.knowledge_api import router as knowledge_router
from app.transport.memory_api import router as memory_router
from app.transport.openai_compat import router as openai_router
from app.transport.plugins_api import router as plugins_router
from app.transport.settings_api import router as settings_router
from app.transport.skills_api import router as skills_router

logger = logging.getLogger(__name__)


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
    # harness 文件日志收进数据根（必须在首次构造 HarnessAgent 之前）
    from app.infra.harness.config import configure_harness_logging

    _safe(configure_harness_logging, "harness 日志目录初始化失败（沿用 harness 默认）")
    # 记忆质量策略（捕获只取用户消息 / 抽取规则 / 召回地域过滤）：必须早于任何
    # Agent 实例——Agent 构造时 MemoryService 已按上游默认配置就绪。
    from app.infra.memory_policy import install_memory_policies

    _safe(install_memory_policies, "记忆策略初始化失败（沿用上游默认）")
    init_db()
    seed_default_agent()
    ensure_agent_workspaces()
    _ensure_model_plugins()
    _sync_plugins()
    _sync_connectors_file()
    _resume_knowledge_index_jobs()
    _safe(_sync_langfuse, "Langfuse 初始化失败（继续启动，观测未启用）")
    yield
    manager.shutdown()  # 释放实例 + 冲刷 Langfuse（close() 已不再动观测）


def _safe(fn: Callable[[], object], message: str) -> None:
    """启动步骤兜底：单步失败只记日志，不阻断后端启动。"""
    try:
        fn()
    except Exception:
        logger.exception(message)


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


def _sync_langfuse() -> None:
    """启动时按 {workspace}/langfuse.json 配置 harness Langfuse tracer（未配置则保持停用）。"""
    from octop_harness.observability.langfuse import LangfuseConfig

    from app.infra.harness.langfuse_store import load as load_langfuse_cfg
    from app.infra.harness.manager import manager

    try:
        manager.set_langfuse(LangfuseConfig(**load_langfuse_cfg()))
    except Exception:
        logger.exception("Langfuse 初始化失败（继续启动，观测未启用）")


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
# 本机访问守卫（最外层）：Host/Origin 白名单 + /api/* 写操作 token。
# 必须最后注册（Starlette 后注册者在外层），保证任何路由/静态挂在执行前先过守卫。
app.add_middleware(LocalGuardMiddleware)
app.include_router(router)
app.include_router(agents_router)
app.include_router(avatar_router)
app.include_router(connectors_router)
app.include_router(openai_router)
app.include_router(plugins_router)
app.include_router(settings_router)
app.include_router(skills_router)
app.include_router(knowledge_router)
app.include_router(memory_router)

# —— 前端控制台（frontend/dist 静态挂载，同源零 CORS；浏览器或壳内都访问 /console/）——
_FRONTEND_DIR = REPO_ROOT / "frontend" / "dist"
if not _FRONTEND_DIR.is_dir():
    _FRONTEND_DIR = REPO_ROOT / "frontend"  # 未构建时退回源码根（仅 dev 辅助）
if _FRONTEND_DIR.is_dir():
    app.mount("/console", StaticFiles(directory=_FRONTEND_DIR, html=True), name="console")
