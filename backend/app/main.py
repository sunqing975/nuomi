"""nuomi 后端入口（v0.13）：FastAPI 装配。

架构：transport（协议）→ domain（业务层）→ infra/harness（适配层）→ octop-harness。
启动时：建库 + 种子默认专家（糯米）；退出时：释放全部 Agent 实例。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.domain.agents.seed import default_system_prompt, default_welcome_message
from app.domain.agents.service import agent_service
from app.infra.harness.manager import manager
from app.storage.db import init_db
from app.transport.api import router


def seed_default_agent() -> None:
    """agents 表为空时创建默认专家（糯米，小猫伙伴人格）。"""
    if agent_service.list():
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
    yield
    manager.close()


app = FastAPI(title="nuomi", version="0.13.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
