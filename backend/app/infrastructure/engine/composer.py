"""composer.py · V3 组合驱动器（对齐 Harness app-boot：应用 = 插件树）。

职责：
- 持有 V3 内核（EventBus v3 / Scope / Registry）并挂到 app.state
- 从 nuomi.json（profile）读取插件树 → 逐个挂载 Fiber（依赖驱动的加载/重试）
- toggle = 改组合 + 增量卸载/挂载 + 事件广播（订阅方热更新）
- install = 导入外部插件（#35 插件导入的落点）
- list = fiber 状态 + 贡献 + 清单元数据（前端能力面板 / 设置 schema 的数据源）
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import (
    EventBus,
    Fiber,
    FiberState,
    ProfileEntry,
    Registry,
    Scope,
    default_profile,
    load_profile,
)


class NuomiComposer:
    def __init__(
        self,
        app,
        plugins_dir: str | Path,
        profile_path: str | Path,
        domain_roots: Sequence[str | Path] | None = None,
    ) -> None:
        self.app = app
        self.plugins_dir = Path(plugins_dir)
        # 领域根（domain/ 各包 + transport/ + engine/services/）：内核模块的聚合扫描位置
        self.domain_roots: list[Path] = [Path(r) for r in (domain_roots or [])]
        self.profile_path = Path(profile_path)
        self.bus = EventBus()
        self.scope = Scope("global")
        self.registry = Registry(app, self.bus, self.scope)
        self.entries: dict[str, ProfileEntry] = {}  # entry_id -> ProfileEntry

        # 内核挂到 app.state（V2 兼容读点：event_bus 仍是发布点）
        app.state.bus = self.bus
        app.state.event_bus = self.bus
        app.state.scope = self.scope
        app.state.registry = self.registry
        app.state.services = {}
        app.state.plugin_ctx = {}
        app.state.plugin_settings = {}
        app.state.enabled_plugins = set()

    # ---------- 加载 ----------
    def load(self) -> None:
        if not self.profile_path.exists():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(
                json.dumps(default_profile(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        entries = load_profile(self.profile_path)
        for e in entries:
            self.entries[e.id] = e
            if e.disabled:
                continue
            self._mount(e)
        self.registry.reconcile()
        self._sync_enabled()
        # 全量挂载完成：通知关心方（agent-loop）重建（初始加载时依赖插件的 apply 在其后）
        self.bus.emit("plugins/loaded", count=len(self.registry.fibers))

    def _plugin_dir(self, name: str) -> Path | None:
        """定位插件/模块目录：内核模块在领域根（domain/、transport/、engine/services/），插件在 plugins/。"""
        for root in self.domain_roots:
            cand = root / name
            if cand.exists():
                return cand
        cand = self.plugins_dir / name
        return cand if cand.exists() else None

    @staticmethod
    def _read_manifest(plugin_dir: Path) -> dict:
        """读取目录清单（v0.7.1 双 manifest）：模块 module.json / 插件 plugin.json。"""
        pj = plugin_dir / "module.json"
        if not pj.exists():
            pj = plugin_dir / "plugin.json"
        if not pj.exists():
            return {}
        try:
            return json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _mount(self, entry) -> None:
        # 模块（内核组成部分）在 backend/app/modules/，插件在 plugins/
        plugin_dir = self._plugin_dir(entry.plugin)
        # 入口由清单的 entry 声明（默认 hook.py）；模块已改为唯一入口名
        entry_file = "hook.py"
        if plugin_dir is not None:
            entry_file = self._read_manifest(plugin_dir).get("entry", "hook.py") or "hook.py"
        fiber = Fiber(
            entry.id,
            entry.plugin,
            plugin_dir,
            {"config": dict(entry.config)},
            self.app,
            self.bus,
            self.scope,
            entry=entry_file,
        )
        self.registry.add(fiber)
        fiber.load()

    def _sync_enabled(self) -> None:
        active = {f.name for f in self.registry.fibers.values() if f.state == FiberState.ACTIVE}
        self.app.state.enabled_plugins = active

    def _save_profile(self) -> None:
        data: dict[str, Any] = {"layers": []}
        for e in self.entries.values():
            data["layers"].append({"id": "user", "plugins": [e.to_dict()]})
        self.profile_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 启停（配置组合语义） ----------
    def toggle(self, entry_id: str, enabled: bool) -> dict:
        entry = self.entries.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.disabled = not enabled
        self._save_profile()
        rebuilt: bool | None = None
        if enabled:
            self._mount(entry)
            self.registry.reconcile()
            self._sync_enabled()
            f = self.registry.get(entry_id)
            rebuilt = bool(f and f.ctx and f.ctx.tools)
            # 事件在挂载后发布（订阅刚注册可收到）
            self.bus.publish(
                "plugin_toggled", {"plugin": entry.plugin, "id": entry_id, "enabled": enabled}
            )
            self.bus.emit("plugin/toggled", id=entry_id, plugin=entry.plugin, enabled=enabled)
        else:
            # 顺序（对齐 V2 踩坑记录"改集合→publish→再 dispose"）：
            # 1) 先从注册表摘除（订阅方的 enabled/ACTIVE 视图立即更新）
            # 2) 发布事件（本插件 ctx 未 dispose，订阅仍存活，可自响应）
            # 3) 事件之后真正 dispose（清理 ctx 订阅/服务）
            f = self.registry.get(entry_id)
            had_tools = bool(f and f.ctx and f.ctx.tools)
            if f is not None:
                self.registry.fibers.pop(entry_id, None)
            self.registry.reconcile()
            self._sync_enabled()
            self.bus.publish(
                "plugin_toggled", {"plugin": entry.plugin, "id": entry_id, "enabled": enabled}
            )
            self.bus.emit("plugin/toggled", id=entry_id, plugin=entry.plugin, enabled=enabled)
            if f is not None:
                f.dispose()
            rebuilt = had_tools  # 停用有工具贡献的插件 → 重建 agent（V2 rebuilt 语义）
        result = self.list_entry(entry_id)
        if rebuilt is not None:
            result["rebuilt"] = rebuilt
        return result

    # ---------- 导入（参考 Harness dsh plugin：install/uninstall/list） ----------
    def install(self, name: str, source: str | Path, origin: str = "local") -> dict:
        """导入外部插件到 plugins/<name>/，并挂载进组合。

        source 支持：本地目录 / zip 文件 / git 仓库 URL。
        """
        target = self.plugins_dir / name
        if target.exists():
            raise FileExistsError(f"插件 {name} 已存在")
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        src = Path(source)
        if src.is_dir():
            shutil.copytree(src, target)
        elif src.is_file() and src.suffix == ".zip":
            with zipfile.ZipFile(src) as zf:
                members = zf.namelist()
                root = _zip_root(members)
                zf.extractall(target.parent)
                tmp = target.parent / root
                if tmp != target:
                    tmp.rename(target)
        elif str(source).startswith(("http://", "https://", "git@", "ssh://")):
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(
                    ["git", "clone", "--depth", "1", str(source), td],
                    check=True,
                    capture_output=True,
                )
                repo = Path(td)
                inner = repo / name if (repo / name).is_dir() else repo
                shutil.copytree(inner, target)
        else:
            raise ValueError(f"不支持的插件来源：{source}")

        # 校验清单
        if not (target / "plugin.json").exists():
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError("导入失败：插件缺少 plugin.json 清单")

        meta = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        self._save_profile()
        # 挂载新 entry
        entry = ProfileEntry(id=name, plugin=name, config={}, disabled=False, layer="user")
        self.entries[name] = entry
        self._mount(entry)
        self.registry.reconcile()
        self._sync_enabled()
        self.bus.publish("plugin_toggled", {"plugin": name, "id": name, "enabled": True})
        return {
            "id": name,
            "name": meta.get("name", name),
            "installed": True,
            "state": self.list_entry(name)["state"],
        }

    def uninstall(self, entry_id: str) -> dict:
        entry = self.entries.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        self.registry.remove(entry_id)
        del self.entries[entry_id]
        self._save_profile()
        self._sync_enabled()
        target = self.plugins_dir / entry.plugin
        if target.exists() and (target / "plugin.json").exists():
            shutil.rmtree(target, ignore_errors=True)
        return {"id": entry_id, "uninstalled": True}

    # ---------- 列表 ----------
    def list_plugins(self) -> list[dict]:
        return [self.list_entry(eid) for eid in self.entries]

    def list_entry(self, entry_id: str) -> dict:
        e = self.entries.get(entry_id)
        if e is None:
            raise KeyError(entry_id)
        fiber = self.registry.get(entry_id)
        meta = {}
        pdir = self._plugin_dir(e.plugin)
        if pdir is not None:
            meta = self._read_manifest(pdir)
        tools = [t.name for t in fiber.ctx.tools] if fiber and fiber.ctx else []
        skills = list(fiber.ctx.skills) if fiber and fiber.ctx else []
        # v0.7：技能独立在技能区（skills/），同名技能即关联展示
        if not skills:
            skill_names = {s.name for s in getattr(self.app.state, "skills", [])}
            if e.plugin in skill_names:
                skills = [e.plugin]
        # v0.7.1：服务/事件 = 声明式（module.json provides/hooks）∪ 运行时（fiber.ctx）
        services = (
            list(dict.fromkeys([*meta.get("provides", []), *self.scope.provided_by(fiber.ctx)]))
            if fiber and fiber.ctx
            else [*meta.get("provides", [])]
        )
        events = (
            list(dict.fromkeys([*meta.get("hooks", []), *fiber.ctx.events]))
            if fiber and fiber.ctx
            else [*meta.get("hooks", [])]
        )
        return {
            "id": entry_id,
            "name": meta.get("name", e.plugin),
            "plugin": e.plugin,
            "description": meta.get("description", ""),
            "version": meta.get("version", ""),
            "builtin": bool(meta.get("builtin", False))
            or e.plugin.startswith("service-")
            or any((root / e.plugin).is_dir() for root in self.domain_roots),
            "enabled": not e.disabled,
            "disabled": e.disabled,
            "config": dict(e.config),
            "settings": meta.get("settings", {}),
            "state": fiber.state.value if fiber else "missing",
            "error": fiber.error if fiber else None,
            "waiting_on": fiber.waiting_on if fiber else [],
            "tools": tools,
            "skills": skills,
            "services": services,
            "events": events,
            "rebuilt": len(tools) > 0,  # v0.6 兼容：工具贡献变化触发重建
            # v0.6 兼容字段（前端能力面板 / 旧测试）
            "contributions": {
                "skills": skills,
                "tools": tools,
                "services": services,
                "events": events,
            },
        }

    def available(self) -> list[dict]:
        """plugins/ 下已存在但不在组合里的目录（可作为导入候选/待挂载）。"""
        installed = {self.entries[eid].plugin for eid in self.entries}
        out = []
        for d in sorted(self.plugins_dir.iterdir()):
            if not d.is_dir() or not (d / "plugin.json").exists():
                continue
            if d.name in installed:
                continue
            try:
                meta = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            out.append(
                {
                    "plugin": d.name,
                    "name": meta.get("name", d.name),
                    "description": meta.get("description", ""),
                }
            )
        return out


def _zip_root(members: list[str]) -> str:
    """zip 顶层目录名（单根目录时解压到该目录）。"""
    first = members[0].split("/")[0] if members else ""
    if first and all(m.split("/")[0] == first for m in members):
        return first
    return ""
