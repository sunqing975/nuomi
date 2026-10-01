"""service-memory · ctx.memory 服务（Seam Provider：MemoryStore 实现）。"""
from __future__ import annotations

from app.memory import MemoryStore, get_store, set_store


def apply(ctx):
    mem_file = ctx.config.get("memory_file", str(ctx.app.state.memory_file))
    store = MemoryStore(mem_file)
    set_store(store)  # 旧读点兼容（app.memory.get_store）
    ctx.app.state.memory = store
    ctx.provide("memory", store)
