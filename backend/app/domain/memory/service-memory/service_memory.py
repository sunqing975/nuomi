"""service-memory · ctx.memory 服务（内置默认 provider：FileMemoryBackend）。

Seam Provider：把 SQLite MemoryStore 包装为 MemoryBackend 契约后注册——
上层（注入中间件 / memory 工具）只认契约，换 provider（如 memory-mem0）
= profile 停用本插件 + 启用目标插件，引擎与工具零改动。
"""

from __future__ import annotations

from app.storage.memory import (
    FileMemoryBackend,
    MemoryStore,
    set_backend,
    set_store,
)


def apply(ctx):
    mem_file = ctx.config.get("memory_file", str(ctx.app.state.memory_file))
    store = MemoryStore(mem_file)
    backend = FileMemoryBackend(store)
    set_store(store)  # 旧读点兼容（app.storage.memory.get_store / app.state.memory）
    set_backend(backend)  # 统一读点（记忆工具 / 注入中间件走 get_backend）
    ctx.app.state.memory = store
    ctx.provide("memory", backend)
