"""core/scope.py · 分层服务注册表（对齐 Cordis scope 分层）。

注册落入调用方上下文所在的层（global 或具名 scope）；读取时合并全局层与观察 scope 的链：
最近层的条目直接赢得重名服务。用于"多伙伴/多 agent 各有独立服务实例"。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nuomi.core.scope")


class Scope:
    def __init__(self, name: str = "global", parent: Scope | None = None) -> None:
        self.name = name
        self.parent = parent
        self._services: dict[str, Any] = {}
        self._owners: dict[str, Any] = {}  # 服务名 → 注册它的插件 ctx（依赖跟踪用）

    # --- 注册 ---
    def register(self, name: str, impl: Any, owner: Any | None = None) -> None:
        self._services[name] = impl
        if owner is not None:
            self._owners[name] = owner

    def unregister(self, name: str) -> None:
        self._services.pop(name, None)
        self._owners.pop(name, None)

    # --- 读取：合并全局层与自身链（最近层胜出） ---
    def get(self, name: str) -> Any | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope._services:
                return scope._services[name]
            scope = scope.parent
        return None

    def names(self) -> set[str]:
        names: set[str] = set(self._services)
        scope = self.parent
        while scope is not None:
            names |= set(scope._services)
            scope = scope.parent
        return names

    def owner_of(self, name: str) -> Any | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope._services:
                return scope._owners.get(name)
            scope = scope.parent
        return None

    # --- 子树（某插件提供的全部服务名，卸载时清理） ---
    def provided_by(self, owner: Any) -> list[str]:
        return [n for n, o in self._owners.items() if o is owner]
