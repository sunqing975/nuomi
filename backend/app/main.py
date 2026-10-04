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
from app.transport.openai_compat import router as openai_router


def seed_default_agent() -> None:
    """agents 表为空时创建默认专家（糯米，小猫伙伴人格）。"""
    if agent_service.list_all():
        return
    agent_service.create(
        {
            "name": "糯米",
            "description": "住在电脑里的默认专家：能干、记得、在乎",
            "system_prompt": default_system_prompt(),
            "icon_name": "cat",
            "color": "#f59e0b",
            "welcome_message": default_welcome_message(),
            "kind": "expert",
        }
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_default_agent()
    _ensure_model_plugins()
    _sync_plugins()
    _sync_mcp_file()
    yield
    manager.close()


def _sync_mcp_file() -> None:
    """MCP 配置源：data_root/mcp_servers.json 优先（控制台增删后持久化），无文件时用 env 种子。"""
    from app.config import settings

    p = settings.data_root / "mcp_servers.json"
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
    """确保每个有动作/表情的桌宠模型都有对应插件（插件名 = 模型名）。

    模型资产补齐/替换后重启即自动重新生成；无能力的模型跳过。
    """
    from contextlib import suppress

    from app.domain.pet.service import generate_all_model_plugins

    with suppress(Exception):
        generate_all_model_plugins()


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

# —— 前端控制台（frontend/dist 静态挂载，同源零 CORS；浏览器或壳内都访问 /console/）——
_FRONTEND_DIR = REPO_ROOT / "frontend" / "dist"
if not _FRONTEND_DIR.is_dir():
    _FRONTEND_DIR = REPO_ROOT / "frontend"  # 未构建时退回源码根（仅 dev 辅助）
if _FRONTEND_DIR.is_dir():
    app.mount("/console", StaticFiles(directory=_FRONTEND_DIR, html=True), name="console")
