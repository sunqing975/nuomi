"""core/fiber.py · 插件实例状态机 + 依赖驱动加载器（对齐 Cordis）。

Fiber 状态机：
    PENDING → LOADING → ACTIVE → UNLOADING → DISPOSED
                 ↘ FAILED
- PENDING：已声明但所需服务（inject）尚不可用——合法状态，提供方稍后挂载时自动启动
- FAILED：apply 抛异常（明确报错，不静默跳过）
- 停用 = dispose：逆序清理全部 effect，服务随之撤销

依赖驱动：
- 插件模块导出 `inject = ['llm', ...]` 或 apply 内 ctx.inject([...])
- load 前检查依赖；缺失 → PENDING（记录缺失清单，前端可见）
- 服务提供方被卸载 → 依赖它的插件自动卸载；服务恢复 → 重载
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from .context import PluginContext

logger = logging.getLogger("nuomi.infrastructure.engine.fiber")


class FiberState(StrEnum):
    PENDING = "pending"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    UNLOADING = "unloading"
    DISPOSED = "disposed"


class Fiber:
    """一个已加载插件实例的运行时句柄。"""

    def __init__(
        self,
        entry_id: str,
        name: str,
        plugin_dir: Path | None,
        meta: dict,
        app,
        bus,
        scope,
        entry: str = "hook.py",
    ) -> None:
        self.id = entry_id
        self.name = name
        self.plugin_dir = plugin_dir
        self.meta = dict(meta)  # 组合 entry：{"config": {...}, ...}
        self.app = app
        self.bus = bus
        self.scope = scope
        self.entry = entry
        self.state = FiberState.PENDING
        self.ctx: PluginContext | None = None
        self.error: str | None = None
        self.waiting_on: list[str] = []
        self._merge_plugin_meta()

    def _merge_plugin_meta(self) -> None:
        """合并清单元数据（v0.7.1 双 manifest：插件 plugin.json / 模块 module.json）。

        name/description/system_instruction/robust/approval/provides/hooks/settings…
        entry 的 config 保留在 meta["config"]。"""
        if self.plugin_dir is None:
            return
        import json

        pj = self.plugin_dir / "module.json"
        if not pj.exists():
            pj = self.plugin_dir / "plugin.json"
        if not pj.exists():
            return
        try:
            pm = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            pm = {}
        for k, v in pm.items():
            if k not in self.meta or k == "config":
                self.meta[k] = v
        self.name = str(self.meta.get("name", self.name))

    # --- 加载 ---
    def load(self) -> FiberState:
        if self.state in (FiberState.ACTIVE, FiberState.LOADING):
            return self.state
        if self.plugin_dir is None:
            self.state = FiberState.FAILED
            self.error = "缺少插件目录"
            return self.state

        mod, err = self._load_module()
        if mod is None:
            self.state = FiberState.FAILED
            self.error = err
            return self.state

        ctx = PluginContext(self.app, self.bus, self.scope)
        ctx.config = dict(self.meta.get("config", {}))
        # 依赖声明：模块导出 inject 或 apply 内 ctx.inject([...])
        inject_decls = list(getattr(mod, "inject", []) or [])
        if hasattr(mod, "apply"):
            try:
                mod.apply(ctx)
            except Exception as e:
                ctx.dispose()
                self.state = FiberState.FAILED
                self.error = f"apply 失败: {e.__class__.__name__}: {e}"
                return self.state
        elif hasattr(mod, "TOOLS"):  # 兼容：函数形态（仅 TOOLS）
            from langchain_core.tools import BaseTool, tool

            for item in mod.TOOLS:
                if isinstance(item, BaseTool):
                    ctx.register_tools([item])
                elif callable(item):
                    ctx.register_tools([tool(item)])
        else:
            ctx.dispose()
            self.state = FiberState.FAILED
            self.error = "缺少 apply(ctx) 或 TOOLS"
            return self.state

        inject_decls.extend(ctx.inject_decls)
        ctx.inject_decls = list(dict.fromkeys(inject_decls))
        missing = ctx.missing_services()
        if missing:
            # 依赖未就绪：撤销副作用，停在 PENDING，等待服务就绪后重试
            ctx.dispose()
            self.state = FiberState.PENDING
            self.waiting_on = missing
            return self.state

        self.state = FiberState.ACTIVE
        self.ctx = ctx
        self.error = None
        self.waiting_on = []
        return self.state

    # --- 卸载 ---
    def dispose(self) -> None:
        if self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            return
        self.state = FiberState.UNLOADING
        if self.ctx is not None:
            # 撤销本插件注册的服务（依赖本插件的其他插件随后由 reconciler 处理）
            for svc in self.scope.provided_by(self.ctx):
                self.scope.unregister(svc)
            self.ctx.dispose()
            self.ctx = None
        self.state = FiberState.DISPOSED

    # --- 内部 ---
    def _load_module(self):
        mod_path = self.plugin_dir / self.entry
        if not mod_path.exists():
            return None, f"缺少入口模块 {self.entry}"
        spec = importlib.util.spec_from_file_location(
            f"nuomi_plugin_{self.plugin_dir.name}", mod_path
        )
        if spec is None or spec.loader is None:
            return None, "无法创建模块 spec"
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            return None, f"入口加载失败: {e.__class__.__name__}: {e}"
        return module, None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state.value,
            "error": self.error,
            "waiting_on": self.waiting_on,
            "tools": [t.name for t in (self.ctx.tools if self.ctx else [])],
            "skills": list((self.ctx.skills if self.ctx else {}).keys()),
            "services": self.scope.provided_by(self.ctx) if self.ctx else [],
            "events": list(self.ctx.events) if self.ctx else [],
            "config": self.meta.get("config", {}),
        }


class Registry:
    """插件注册表：持有全部 fiber，负责依赖驱动的加载/卸载/重试。"""

    def __init__(
        self, app, bus, scope, ctx_factory: Callable[..., PluginContext] | None = None
    ) -> None:
        self.app = app
        self.bus = bus
        self.scope = scope
        self.fibers: dict[str, Fiber] = {}

    def add(self, fiber: Fiber) -> None:
        self.fibers[fiber.id] = fiber

    def get(self, fiber_id: str) -> Fiber | None:
        return self.fibers.get(fiber_id)

    def remove(self, fiber_id: str) -> None:
        f = self.fibers.pop(fiber_id, None)
        if f is not None:
            f.dispose()

    def active(self) -> list[Fiber]:
        return [f for f in self.fibers.values() if f.state == FiberState.ACTIVE]

    def reconcile(self) -> None:
        """服务/组合变化后统一收敛：
        1. PENDING 的 fiber 重新尝试（依赖可能已就绪）
        2. ACTIVE 的 fiber 若依赖服务消失 → 卸载
        3. 服务变化扩散（A 卸载 → 依赖 A 的 B 卸载 → 依赖 B 的 C 卸载）
        """
        changed = True
        while changed:
            changed = False
            for f in list(self.fibers.values()):
                if f.state == FiberState.PENDING:
                    if f.load() != FiberState.PENDING:
                        changed = True
                elif f.state == FiberState.ACTIVE and f.ctx is not None:
                    missing = f.ctx.missing_services()
                    if missing:
                        f.dispose()
                        f.state = FiberState.PENDING
                        f.waiting_on = missing
                        changed = True
