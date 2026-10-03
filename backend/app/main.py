"""nuomi 后端入口（v0.13）：FastAPI 装配。

架构：transport（协议）→ domain（业务层，待建）→ infra/harness（适配层）→ octop-harness。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.infra.harness.manager import manager
from app.transport.api import router


@asynccontextmanager
async def lifespan(_: FastAPI):
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
