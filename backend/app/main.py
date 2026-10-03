"""FastAPI 入口：POST /api/chat（SSE 流式）+ GET /health。

启动即：打开 SQLite checkpointer → 加载伙伴人设 → 初始化记忆库 → 扫描 skills/
→ 组装 NuomiMiddleware（每轮注入人设+记忆+摘要）→ 构建 LangGraph agent。
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.language_models.chat_models import BaseChatModel

from .config import settings
from .domain.capabilities.service import CapabilityService
from .domain.experts.expert import assemble_system_prompt, load_expert
from .domain.experts.graph import build_llm, create_checkpointer
from .domain.experts.models import (
    build_model_llm,
    find_model,
)
from .infrastructure.engine.approval import ApprovalGate, set_gate
from .infrastructure.engine.composer import NuomiComposer
from .infrastructure.engine.loader import (
    collect_skill_catalog,
    scan_plugins,
    scan_skills,
)
from .storage.db import ensure_database
from .storage.knowledge import build_knowledge_store
from .storage.knowledge import set_store as set_knowledge_store
from .storage.memory import MemoryStore
from .storage.projects import ProjectStore
from .storage.trace import TraceLogger, set_logger
from .transport.api import build_router


def make_prompt_builder(
    expert, instructions: list[str], memory: MemoryStore, memory_enabled: bool = True, app=None
):
    """按"当前用户消息"检索记忆，组装每轮的 system prompt（闭包交给中间件）。

    Phase 4d+ 插件管理：memory_enabled=False（memory 插件被停用）时不注入记忆事实，
    模型表现为"失忆"——引擎注入与工具层一起受插件开关控制。
    skill_catalog 常驻注入（name+description 目录，正文按需读），对齐 Harness 会话目录。
    """

    def builder(last_user_msg: str) -> str:
        if not memory_enabled:
            merged: list = []
        else:
            store = memory
            facts = store.search(last_user_msg, top_k=3) + store.recent(top_k=3)
            seen: set[str] = set()
            merged = []
            for f in facts:
                if f.id not in seen:
                    seen.add(f.id)
                    merged.append(f)
        return assemble_system_prompt(
            expert,
            instructions,
            memory_facts=merged,
            skill_catalog=collect_skill_catalog(app.state.skills) if app else None,
        )

    return builder


def _expert_override(settings) -> str | None:
    """读取 workspace/experts.json 的专家覆盖（专家选择器持久化，重启生效）。"""
    f = Path(settings.workspace_dir) / "experts.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("expert_name")
    except (OSError, ValueError):
        return None


def build_app(
    llm: BaseChatModel | None = None,
    db_path: str | None = None,
    skills_dir: str | None = None,
    expert_name: str | None = None,
    experts_dir: str | None = None,
    memory_file: str | None = None,
    summarize_max_messages: int | None = None,
    summarize_keep_recent: int | None = None,
    knowledge_store_type: str | None = None,
    knowledge_dir: str | None = None,
    workspace_dir: str | None = None,
    plugins_dir: str | None = None,
    domain_roots: list[str] | None = None,
) -> FastAPI:
    # 扩展体系三区（v0.7 对齐 Octop）：插件=能力分发单元，技能=文档资产，模块=内核组成
    llm_cfg = llm or build_llm(settings)
    db_cfg = db_path or str(settings.db_file)
    pl_dir = plugins_dir or settings.plugins_dir
    dr_roots = domain_roots or settings.domain_roots
    skl_dir = skills_dir or settings.skills_dir
    # 专家来源优先级：启动参数 > workspace 覆盖（专家选择器写入 experts.json）> 默认
    p_name = expert_name or _expert_override(settings) or settings.expert_name
    p_dir = experts_dir or settings.experts_dir
    mem_file = memory_file or str(settings.memory_file)
    max_msgs = summarize_max_messages or settings.summarize_max_messages
    keep_recent = summarize_keep_recent or settings.summarize_keep_recent
    kb_type = knowledge_store_type or settings.knowledge_store
    kb_root = Path(knowledge_dir) if knowledge_dir else settings.knowledge_path
    # 工作区覆盖（测试注入 / 向导保存等价物）：优先级低于 NUOMI_WORKSPACE env
    if workspace_dir is not None:
        settings._workspace_override = workspace_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Path(db_cfg)
        ensure_database(db)  # 统一库：schema 版本（决策 3/5；全新环境，无遗留迁移）

        # 桌面 sidecar 本地 token（阶段 C）：打包（frozen）自动生成/复用 NUOMI_HOME/.api-token；
        # dev 源码运行默认不校验（不影响 vite 代理）；NUOMI_TOKEN env 可强制开关。
        app.state.api_token = _ensure_api_token(db.parent)

        async with create_checkpointer(db_cfg) as saver:
            # 专家 + 知识库 + 可观测 + 人机回环（决策 1：单用户，无 auth/users）
            expert = load_expert(p_dir, p_name)
            knowledge = build_knowledge_store(kb_type, kb_root)
            set_knowledge_store(knowledge)
            logger = TraceLogger(str(settings.trace_path))
            set_logger(logger)
            gate = ApprovalGate(auto_approve=settings.auto_approve)
            set_gate(gate)
            app.state.db_path = db_cfg
            app.state.projects = ProjectStore(db_cfg)
            app.state.projects.ensure_default_project()
            app.state.memory_file = mem_file
            app.state.last_emotion = "neutral"
            app.state.expert = expert
            app.state.kb_type = kb_type
            app.state.knowledge = knowledge
            app.state.trace_logger = logger
            app.state.gate = gate
            app.state.checkpointer = saver  # 提前：内核模块（sessions）依赖
            app.state.llm_cfg = llm_cfg
            app.state.model_name = "none" if llm is None else "custom"
            app.state.model_provider = "custom" if llm is None else "custom"
            # 领域模块：聚合扫描各领域根（domain/、transport/、engine/services/）
            mod_scans: list = []
            for root in dr_roots:
                mod_scans += scan_plugins(root, category="module")
            app.state.plugins = scan_plugins(pl_dir) + mod_scans  # 统一清单：插件 + 模块
            app.state.skills = scan_skills(skl_dir)  # 独立技能区（SKILL.md 文档资产）

            # --- V3：组合驱动（应用 = 插件树，nuomi.json） ---
            profile_path = Path(db_cfg).parent / "nuomi.json"
            composer = NuomiComposer(app, pl_dir, profile_path=profile_path, domain_roots=dr_roots)
            app.state.composer = composer
            app.state.capabilities = CapabilityService(composer)
            # 测试/兼容注入：build_app(llm=...) 优先于 llm 提供方插件（Seam 覆盖语义）
            if llm is not None:
                app.state.scope.register("llm", llm)
                app.state.llm_cfg = llm
                app.state.model_name = "custom"
                app.state.model_provider = "custom"
            composer.load()

            # 摘要参数注入 settings（build_app 参数优先），随后重建 agent 生效
            svc = app.state.scope.get("settings")
            if svc is not None:
                if summarize_max_messages is not None:
                    svc["store"].set("summarize_max_messages", max_msgs, persist=False)
                if summarize_keep_recent is not None:
                    svc["store"].set("summarize_keep_recent", keep_recent, persist=False)
                # 首启向导保存的工作区路径（settings.global.workspace_dir）→ 运行时覆盖默认
                saved_ws = svc["store"].get("workspace_dir")
                if isinstance(saved_ws, str) and saved_ws.strip():
                    settings._workspace_override = saved_ws.strip()

            # V2 兼容读点：rebuild_agents 委托给 agentLoop 服务（插件/设置变更事件已驱动重建）
            def rebuild_agents():
                loop = app.state.scope.get("agentLoop")
                return loop.build_all() if loop is not None else None

            # 恢复上次激活的模型（自定义供应商 + 设置内 API Key；测试注入 llm 时不覆盖）
            if llm is None and svc is not None:
                am = svc["store"].get("active_model")
                if isinstance(am, dict) and am.get("provider"):
                    cps = [
                        c
                        for c in (svc["store"].get("custom_providers", []) or [])
                        if isinstance(c, dict) and c.get("key")
                    ]
                    keys = {
                        k: v
                        for k, v in (svc["store"].all() if svc else {}).items()
                        if k.startswith("provider_") and isinstance(v, str) and v
                    }
                    try:
                        m = find_model(am["provider"], am["model"], cps, keys)
                        if m is not None:
                            effort = am.get("effort") if am.get("effort") in m["efforts"] else None
                            app.state.llm_cfg = build_model_llm(
                                am["provider"], am["model"], effort, cps, keys
                            )
                            app.state.scope.register("llm", app.state.llm_cfg)
                            app.state.model_provider = am["provider"]
                            app.state.model_name = am["model"]
                            app.state.llm_effort = effort
                            # llm 在 composer.load() 之后才注册（依赖 settings），scope.register 不发事件，
                            # 必须手动重建 agentLoop，否则重启后 agent=None、/api/chat 直接报错
                            rebuild_agents()
                    except Exception:  # noqa: BLE001 — 模型不可用则回退默认
                        pass

            app.state.rebuild_agents = rebuild_agents
            if svc is not None and (
                summarize_max_messages is not None or summarize_keep_recent is not None
            ):
                rebuild_agents()
            yield

    app = FastAPI(title="糯米 V2 · 陪伴型个人智能体", version="0.5.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # transport 层：HTTP 路由全部在 transport/api.py 装配（只做协议，不写业务）
    app.include_router(build_router(app))

    return app


def _ensure_api_token(data_root: Path) -> str | None:
    """桌面 sidecar 本地 token（阶段 C）。

    - NUOMI_TOKEN 环境变量显式指定 → 强制启用该校验值
    - 打包（sys.frozen）→ 自动生成/复用 NUOMI_HOME/.api-token（0600）
    - 源码运行（dev）→ 返回 None 不校验，vite 代理不受影响
    """
    env_token = os.environ.get("NUOMI_TOKEN", "").strip()
    if env_token:
        return env_token
    if getattr(sys, "frozen", False):
        token_path = data_root / ".api-token"
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_hex(24)
        token_path.write_text(token, encoding="utf-8")
        with suppress(OSError):
            token_path.chmod(0o600)
        return token
    return None


app = build_app()
