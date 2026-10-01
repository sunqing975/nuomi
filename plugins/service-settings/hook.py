"""service-settings · ctx.settings 服务（对齐 Harness ui-settings 的后端）。

设置分两层：
- 全局设置（model / temperature / partner / summarize...）
- 每插件设置（plugins/<plugin_id> 的 config，由插件在 plugin.json 声明 settings schema）

变更流程：set → 持久化 JSON → emit('settings/changed') → 关心方（llm 提供方、agent-loop 等）
订阅事件热更新。插件 apply 时 ctx.config = 组合配置（基础默认值），运行时设置覆盖。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()  # 可重入：set() 持锁时 save() 再取锁不卡死
        self.data: dict[str, Any] = {"plugins": {}}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {"plugins": {}}
        self.data.setdefault("plugins", {})

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 全局 ---
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        with self._lock:
            self.data[key] = value
            if persist:
                self.save()

    def all(self) -> dict:
        return {k: v for k, v in self.data.items() if k != "plugins"}

    # --- 每插件 ---
    def plugin_get(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self.data["plugins"].get(plugin_id, {}).get(key, default)

    def plugin_set(self, plugin_id: str, patch: dict, persist: bool = True) -> dict:
        with self._lock:
            self.data["plugins"].setdefault(plugin_id, {}).update(patch)
            if persist:
                self.save()
            return dict(self.data["plugins"][plugin_id])

    def plugin_all(self, plugin_id: str) -> dict:
        return dict(self.data["plugins"].get(plugin_id, {}))


def collect_plugin_settings_schema(ctx) -> list[dict]:
    """汇总全部 ACTIVE 插件的 settings schema + 运行时设置（前端渲染设置表单）。

    未声明 settings 的插件也列出（settings={}），values 展示已存的运行时设置。
    """
    from app.core import FiberState

    reg = ctx.app.state.registry
    out = []
    for f in reg.fibers.values():
        if f.state == FiberState.ACTIVE and f.ctx is not None:
            schema = (f.meta or {}).get("settings") or {}
            out.append({
                "id": f.id,
                "name": f.name,
                "settings": schema if isinstance(schema, dict) else {},
                "values": ctx.app.state.settings.plugin_all(f.id),
            })
    return out


def apply(ctx):
    path = ctx.config.get("path", str(Path(ctx.app.state.db_path).parent / "settings.json"))
    store = SettingsStore(path)
    ctx.app.state.settings = store

    def _api():
        return {
            "global": store.all(),
            "plugins": collect_plugin_settings_schema(ctx),
        }

    def _set_global(key, value):
        store.set(key, value)
        ctx.emit("settings/changed", scope="global", key=key, value=value)

    def _set_plugin(plugin_id, patch):
        merged = store.plugin_set(plugin_id, patch)
        ctx.emit("settings/changed", scope="plugin", plugin=plugin_id, patch=merged)
        return merged

    svc = {
        "store": store,
        "get": store.get,
        "set": _set_global,
        "plugin_get": store.plugin_get,
        "plugin_set": _set_plugin,
        "plugin_all": store.plugin_all,
        "snapshot": _api,
        "schema": collect_plugin_settings_schema,
    }
    ctx.provide("settings", svc)
