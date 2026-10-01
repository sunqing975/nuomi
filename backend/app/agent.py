"""LangGraph Agent 工厂：LLM + 插件工具 + SQLite checkpointer → create_agent。

Phase 0 打字核心；Phase 1 由 NuomiMiddleware 每轮注入人设+记忆+摘要，system_prompt 传 None；
Phase 2 挂插件调度。
"""
from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .config import Settings

# Phase 1：多伙伴人设由 partner.py 组装；中间件每轮注入。
# 注意（本地 2B 实测）：工具规则必须放在人设之前，否则小模型会进入"闲聊模式"
# 而不调用工具（见 AGENT.md 验证记录）。
DEFAULT_SYSTEM_PROMPT = (
    "你是糯米，一只住在电脑里的小猫伙伴兼智能助手。"
    "说话简短自然，像亲密朋友发消息一样，1-3 句。"
    "需要真实信息时使用工具获取，不要编造。"
)


def build_llm(settings: Settings) -> ChatOpenAI:
    from .models import DeepSeekChat

    # 无 temperature（对齐 dsh：不暴露温度，交给提供商默认）
    return DeepSeekChat(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        streaming=True,
    )


def create_checkpointer(db_file):
    """SQLite 持久化检查点（对话历史断点续跑）。

    返回 async 上下文管理器：`async with create_checkpointer(...) as saver:`，
    退出时自动关闭连接。db_file 为普通文件路径（本版本 from_conn_string
    直接透传给 aiosqlite，不接受 sqlite:/// URI 前缀），父目录须已存在。
    """
    return AsyncSqliteSaver.from_conn_string(str(Path(db_file)))


def create_pg_checkpointer(dsn: str):
    """PostgreSQL 检查点（Phase 4a 多用户）：AsyncPostgresSaver + 连接池。

    返回 async 上下文管理器，退出时关闭连接池。首次使用自动建表（setup）。
    """
    from contextlib import asynccontextmanager

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    @asynccontextmanager
    async def _cm():
        pool = AsyncConnectionPool(
            conninfo=dsn, max_size=10, open=False, kwargs={"autocommit": True}
        )
        await pool.open()
        try:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            yield saver
        finally:
            await pool.close()

    return _cm()


def build_graph(
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
    checkpointer: AsyncSqliteSaver | None = None,
    system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
    middleware: list[AgentMiddleware] | None = None,
):
    """middleware 提供时 system_prompt 应传 None（由中间件每轮注入动态提示）。"""
    return create_agent(
        model=llm,
        tools=tools or [],
        checkpointer=checkpointer,
        system_prompt=system_prompt,
        middleware=middleware or [],
    )
