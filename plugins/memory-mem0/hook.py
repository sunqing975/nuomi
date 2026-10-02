"""memory-mem0 · 外部记忆 provider 插件（Mem0：对话级语义提取 + 向量检索）。

实现 MemoryBackend 契约，与内置 service-memory **互斥**：profile 停用
service-memory + 启用本插件 = 一行配置切换记忆后端。注入（冻结快照）与
工具（memory_write/read/replace/remove）只认契约，零改动。

mem0ai 为懒依赖：未安装时 apply 报错（fiber FAILED，UI 可见提示）。
安装：`cd backend && uv pip install mem0ai`。
配置：plugin.json settings schema 驱动（设置页）；也可 profile config /
环境变量（MEM0_API_KEY / DEEPSEEK_API_KEY / LLM_API_KEY）。
注意：mem0ai 配置格式随版本演进，接入时以 mem0 官方文档为准微调
`Memory.from_config` 参数（云/openmemory/本地向量库三种模式已给默认）。
"""
from __future__ import annotations

import os
import time
from typing import Any

from app.storage.memory import (
    MemoryBackend,
    MemoryEntry,
    SNAPSHOT_CHAR_LIMITS,
    USER_CATEGORIES,
    set_backend,
)

_DEFAULT_CFG = {
    "mode": "openmemory",  # openmemory | cloud | local
    "base_url": "http://localhost:8000",
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
}


def _entry_from_item(item: Any) -> MemoryEntry | None:
    """mem0 条目 → 契约条目（字段名随版本略有差异，尽量兼容）。"""
    if not isinstance(item, dict):
        return None
    content = item.get("memory") or item.get("text")
    if not content:
        return None
    meta = item.get("metadata") or {}
    return MemoryEntry(
        id=str(item.get("id") or item.get("memory_id") or item.get("hash") or ""),
        content=str(content),
        category=str(meta.get("category", "fact")),
        created_at=item.get("created_at") or time.time(),
        updated_at=item.get("updated_at") or time.time(),
    )


class Mem0Backend(MemoryBackend):
    """Mem0 后端：mem0ai SDK 懒加载（首次调用才 import/连接并缓存实例）。"""

    def __init__(self, cfg: dict):
        self.cfg = {**_DEFAULT_CFG, **cfg}
        self._mem: Any = None

    # ---------- 客户端（懒加载） ----------

    def _client(self):
        if self._mem is not None:
            return self._mem
        try:
            from mem0 import Memory  # 懒依赖：不启用本插件则不必安装
        except ImportError as e:
            raise RuntimeError(
                "mem0ai 未安装：`cd backend && uv pip install mem0ai` 后重启；"
                "或停用 memory-mem0 切回内置 service-memory"
            ) from e
        cfg = self.cfg
        mode = cfg.get("mode", "openmemory")
        api_key = cfg.get("api_key") or os.environ.get("MEM0_API_KEY")
        llm_key = (
            cfg.get("llm_api_key")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )
        if mode == "cloud":
            config = {"provider": "mem0", "config": {"api_key": api_key}}
        elif mode == "local":
            # 全本地：向量库（chroma）+ LLM 提取（OpenAI 兼容端点）
            import tempfile

            config = {
                "vector_store": {
                    "provider": "chroma",
                    "config": {
                        "collection_name": "nuomi_memory",
                        "path": os.path.join(tempfile.gettempdir(), "nuomi_mem0_chroma"),
                    },
                },
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": cfg.get("llm_model"),
                        "api_key": llm_key or "local-no-key",
                        "base_url": cfg.get("llm_base_url"),
                    },
                },
            }
        else:  # openmemory（默认）：本地自托管服务
            config = {
                "provider": "openmemory",
                "config": {"url": cfg.get("base_url") or "http://localhost:8000"},
            }
        self._mem = Memory.from_config(config)
        return self._mem

    # ---------- 契约实现 ----------

    @staticmethod
    def _collect(data: Any) -> list[MemoryEntry]:
        raw = data
        if isinstance(data, dict):
            raw = data.get("results") or data.get("memories") or data.get("data") or []
        return [e for e in (_entry_from_item(i) for i in raw) if e is not None]

    def list(self) -> list[MemoryEntry]:
        return self._collect(self._client().get_all())

    def add(self, content: str, category: str = "fact") -> MemoryEntry | None:
        content = content.strip()
        if not content:
            return None
        # mem0.add 对输入做语义提取（可能产出多条）；契约按"写入一条"返回
        self._client().add(content, user_id=None, metadata={"category": category})
        return MemoryEntry(id="", content=content, category=category)

    def _substring_matches(self, old_text: str) -> list[MemoryEntry]:
        """语义检索 + 子串过滤：保证契约的"唯一子串定位"语义。"""
        if not old_text:
            return []
        try:
            hits = self._collect(self._client().search(old_text, user_id=None, limit=20))
        except Exception:
            return []
        return [h for h in hits if old_text in h.content]

    def replace(self, old_text: str, content: str) -> tuple[int, str]:
        content = content.strip()
        if not content:
            return 0, "新内容为空，未替换"
        matches = self._substring_matches(old_text)
        if not matches:
            return 0, f"未找到包含「{old_text}」的记忆"
        if len(matches) > 1:
            return -1, f"「{old_text}」匹配到多条记忆，请用更精确的片段"
        self._client().update(matches[0].id, data={"memory": content})
        return 1, f"已替换为：{content}"

    def remove(self, old_text: str) -> tuple[int, str]:
        matches = self._substring_matches(old_text)
        if not matches:
            return 0, f"未找到包含「{old_text}」的记忆"
        if len(matches) > 1:
            return -1, f"「{old_text}」匹配到多条记忆，请用更精确的片段"
        self._client().delete(matches[0].id)
        return 1, f"已删除：{matches[0].content}"

    def search(self, query: str, top_k: int = 3) -> list[MemoryEntry]:
        try:
            hits = self._collect(self._client().search(query, user_id=None, limit=max(top_k, 10)))
        except Exception:
            return []
        return hits[:top_k]

    def snapshot(self) -> dict:
        entries = self.list()
        sections = []
        for key, name in (("memory", "MEMORY"), ("user", "USER")):
            picked: list[MemoryEntry] = []
            total = 0
            limit = SNAPSHOT_CHAR_LIMITS.get(key, 2000)
            for e in entries:
                if (e.category in USER_CATEGORIES) != (key == "user"):
                    continue
                if picked and total + len(e.content) > limit:
                    break
                picked.append(e)
                total += len(e.content)
            sections.append(
                {
                    "name": name,
                    "entries": picked,
                    "total_chars": total,
                    "char_limit": limit,
                }
            )
        return {"sections": sections}


def apply(ctx):
    # 1) 依赖探测：mem0ai 未装 → 插件 FAILED（fiber 状态机，UI 可见明确提示）
    try:
        import mem0  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "memory-mem0 需要 mem0ai：`cd backend && uv pip install mem0ai` 后重启；"
            "或停用本插件切回内置 service-memory"
        ) from e

    # 2) 配置合并：profile config（ctx.config）← 插件设置（settings 服务）
    cfg = dict(ctx.config)
    settings_svc = ctx.get("settings")
    if settings_svc is not None:
        stored = settings_svc["store"].plugin_get("memory-mem0", None, {})
        cfg = {**cfg, **stored}

    # 3) 注册 provider：统一读点 + ctx.memory 服务
    backend = Mem0Backend(cfg)
    set_backend(backend)
    ctx.app.state.memory = None  # 统一库 provider 无 MemoryStore；health 走 get_backend().list()
    ctx.provide("memory", backend)

    # 4) 卸载恢复：停用本插件时清空单例（回退内置 service-memory 提供的默认后端）
    def _dispose():
        set_backend(None)

    ctx.effect(_dispose)
