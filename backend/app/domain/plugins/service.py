"""插件领域服务：工作区 plugins/ ↔ octop-harness PluginRegistry ↔ SQLite 启停。

对齐 Octop 领域语言：
- 插件 = 工具注册（ctx.tool）+ 技能（ctx.skills）+ 钩子（ctx.middleware）
- 插件目录是 source of truth（plugin.yaml）；DB 只存启停状态与 agent 绑定
- 全局启用（plugins.enabled）后，工具默认对所有 agent 可用；agent 可按需禁用/配置
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from octop_harness.plugins import (
    PluginRegistry,
    build_plugin_tools,
    discover_plugin_dirs,
    load_all,
)

from app.config import settings
from app.storage import db

# OpenAI 兼容接口（DeepSeek 等）要求工具名只含 [a-zA-Z0-9_-]
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class PluginService:
    # ---------- 扫描 / 同步 ----------

    def plugins_dir(self) -> Path:
        """工作区插件目录（{workspace}/plugins）。"""
        d = settings.workspace_path / "plugins"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def sync(self) -> list[dict]:
        """扫描并加载工作区 plugins/，同步到 DB（新插件默认启用）。"""
        plugins_dir = self.plugins_dir()
        dirs = discover_plugin_dirs(plugins_dir)
        loaded = load_all(plugins_dir) if dirs else []
        rows = []
        with db.connect() as conn:
            for plugin in loaded:
                manifest = plugin.manifest
                conn.execute(
                    """INSERT OR IGNORE INTO plugins
                       (plugin_id, name, kind, version, description)
                       VALUES (?, ?, ?, ?, ?)""",
                    (manifest.id, manifest.name, manifest.kind, manifest.version, manifest.description),
                )
                rows.append(self._row_from_manifest(manifest))
        return rows

    # ---------- 查询 ----------

    def list_all(self) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
        registry = PluginRegistry()
        model_plugin_ids = self.model_plugin_ids()
        out = []
        for r in rows:
            d = dict(r)
            d["tool_count"] = sum(1 for t in registry.all_tools() if t.plugin_id == r["plugin_id"])
            d["model_plugin"] = r["plugin_id"] in model_plugin_ids
            out.append(d)
        return out

    def get(self, plugin_id: str) -> dict | None:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM plugins WHERE plugin_id = ?", (plugin_id,)).fetchone()
        return dict(row) if row else None

    # ---------- 启停 ----------

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict | None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE plugins SET enabled = ?, updated_at = datetime('now') WHERE plugin_id = ?",
                (1 if enabled else 0, plugin_id),
            )
            row = conn.execute("SELECT * FROM plugins WHERE plugin_id = ?", (plugin_id,)).fetchone()
        return dict(row) if row else None

    # ---------- agent 绑定 ----------

    def bind(self, agent_id: str, plugin_id: str, *, enabled: bool = True, tool_configs: dict | None = None) -> None:
        with db.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO agent_plugins (agent_id, plugin_id, enabled, tool_configs)
                   VALUES (?, ?, ?, ?)""",
                (agent_id, plugin_id, 1 if enabled else 0, json.dumps(tool_configs or {}, ensure_ascii=False)),
            )

    def unbind(self, agent_id: str, plugin_id: str) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM agent_plugins WHERE agent_id = ? AND plugin_id = ?", (agent_id, plugin_id))

    def delete(self, plugin_id: str) -> bool:
        """删除插件：DB 记录 + 全部 agent 绑定 + 插件目录（source of truth）。

        模型插件不在此删除（由「桌宠」删除模型时级联）——调用方先检查。
        删除后调用方应释放 agent 实例，避免缓存实例仍带旧插件工具。
        """
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM plugins WHERE plugin_id = ?", (plugin_id,))
            deleted = cur.rowcount > 0
            conn.execute("DELETE FROM agent_plugins WHERE plugin_id = ?", (plugin_id,))
        plugin_dir = self.plugins_dir() / plugin_id
        if plugin_dir.is_dir():
            import shutil

            shutil.rmtree(plugin_dir, ignore_errors=True)
        return deleted

    def agent_bindings(self, agent_id: str) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_plugins WHERE agent_id = ? ORDER BY plugin_id",
                (agent_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["tool_configs"] = json.loads(d.get("tool_configs") or "{}")
            except json.JSONDecodeError:
                d["tool_configs"] = {}
            out.append(d)
        return out

    # ---------- 工具装配（供对话端点） ----------

    def model_plugin_ids(self) -> set[str]:
        """桌宠模型插件 id 集合（pet 生成的插件：插件名 = 模型名）。

        以 pet 模型扫描为准（有动作/表情、生成过插件的模型）。
        模型插件互斥由插件启停层面保证（同一时间只启用一个），
        工具随插件启停热挂载，装配层无需二次过滤。
        """
        from app.domain.pet.service import list_models  # 局部 import，避免模块级循环

        return {m["id"] for m in list_models() if m["motions"] or m["expressions"]}

    def tools_for_agent(self, agent_id: str) -> list:
        """按 agent 绑定 + 全局启停，装配插件工具（StructuredTool 列表）。

        工具名做 slug 防御：非 ASCII 名（如中文）改名为 tool_{n}，
        中文原名拼进 description，保证 OpenAI 兼容接口不 400。
        """
        global_enabled = {r["plugin_id"]: bool(r["enabled"]) for r in self.list_all()}
        agent_cfg = {
            b["plugin_id"]: {"enabled": bool(b["enabled"]), "tools": b["tool_configs"]}
            for b in self.agent_bindings(agent_id)
        }
        tools = build_plugin_tools(agent_plugins=agent_cfg, global_plugins=global_enabled)
        return [self._sanitize_tool(t, i) for i, t in enumerate(tools)]

    @staticmethod
    def _sanitize_tool(tool, index: int):
        """工具名不合规时改名并保留中文语义。"""
        if _SLUG_RE.match(tool.name):
            return tool
        desc = tool.description or ""
        if tool.name not in desc:
            desc = f"【{tool.name}】{desc}"
        return tool.model_copy(update={"name": f"tool_{index}", "description": desc})

    @staticmethod
    def _row_from_manifest(manifest) -> dict:
        return {
            "plugin_id": manifest.id,
            "name": manifest.name,
            "kind": manifest.kind,
            "version": manifest.version,
            "description": manifest.description,
        }


plugin_service = PluginService()
