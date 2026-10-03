"""domain/capabilities · 能力域：插件/模块（能力）的统一领域语义。

领域语言一等公民：路由（transport）只调本服务的领域 API，
不直接碰 engine 机制（composer / fiber / registry）。
本域回答"有哪些能力、怎么启停、怎么安装卸载"；engine 回答"怎么加载执行"。
"""

from __future__ import annotations

from pathlib import Path


class CapabilityService:
    """能力编排门面：挂 app.state.capabilities，供 transport 路由调用。"""

    def __init__(self, composer) -> None:
        self._composer = composer

    # ---------- 查询 ----------
    def list(self) -> dict:
        """能力清单（fiber 状态 + 贡献 + 元数据）+ 可导入候选。"""
        return {
            "plugins": self._composer.list_plugins(),
            "available": self._composer.available(),
        }

    # ---------- 启停 ----------
    def toggle(self, name: str) -> dict:
        """统一启停（配置组合语义）：改 nuomi.json → 挂载/卸载 fiber → 事件广播热更新。"""
        composer = self._composer
        entry = composer.entries.get(name)
        if entry is None:
            hit = [eid for eid, e in composer.entries.items() if e.plugin == name]
            if not hit:
                raise KeyError(name)
            name = hit[0]
            entry = composer.entries[name]
        return composer.toggle(name, entry.disabled)  # disabled=True → 启用

    # ---------- 安装 / 卸载 ----------
    def install(self, name: str, source: str | Path) -> dict:
        """从目录 / zip / git URL 安装能力。"""
        return self._composer.install(name, source)

    def uninstall(self, plugin_id: str) -> dict:
        """卸载并清理能力目录（保留 profile 记录）。"""
        return self._composer.uninstall(plugin_id)
