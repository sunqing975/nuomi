"""插件领域服务：工作区 plugins/ ↔ octop-harness PluginRegistry ↔ SQLite 启停。

对齐 Octop 领域语言：
- 插件 = 工具注册（ctx.tool）+ 技能（ctx.skills）+ 钩子（ctx.middleware）
- 插件目录是 source of truth（plugin.yaml）；DB 只存启停状态
- 全局启用（plugins.enabled）：插件启用即对所有专家可用（2026-10-04 起
  不再有专家-插件绑定，专家不绑定插件；能力随对话请求注入见后续设计）
- 桌宠（方案B，2026-10-04）：只有一个共享 VRM 插件（vrm-pet），
  其启用/停用绑定桌宠开关；动作/表情工具在 tools() 装配时按当前模型动态构造
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import StructuredTool
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
                    (
                        manifest.id,
                        manifest.name,
                        manifest.kind,
                        manifest.version,
                        manifest.description,
                    ),
                )
                rows.append(self._row_from_manifest(manifest))
        return rows

    # ---------- 查询 ----------

    def list_all(self) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
        registry = PluginRegistry()
        out = []
        for r in rows:
            d = dict(r)
            d["tool_count"] = sum(1 for t in registry.all_tools() if t.plugin_id == r["plugin_id"])
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

    def delete(self, plugin_id: str) -> bool:
        """删除插件：DB 记录 + 插件目录（source of truth）。

        模型插件不在此删除（由「桌宠」删除模型时级联）——调用方先检查。
        删除后调用方应释放 agent 实例，避免缓存实例仍带旧插件工具。
        """
        with db.connect() as conn:
            cur = conn.execute("DELETE FROM plugins WHERE plugin_id = ?", (plugin_id,))
            deleted = cur.rowcount > 0
        plugin_dir = self.plugins_dir() / plugin_id
        if plugin_dir.is_dir():
            import shutil

            shutil.rmtree(plugin_dir, ignore_errors=True)
        return deleted

    # ---------- 工具装配（供对话端点） ----------

    def tools(self) -> list:
        """按全局启停装配插件工具 + 桌宠动态工具（StructuredTool 列表）。

        专家不再绑定插件（2026-10-04 解耦）：插件启用即对所有专家可用。
        桌宠（方案B）：vrm-pet 插件启用时，动态构造 do_action / set_expression——
        enum 清单按当前激活 VRM 模型（GLB blend shape）与 animations/*.vrma 实时生成，
        切模型 / 新增动画零重启（工具在每次对话装配时重算）。
        工具名做 slug 防御：非 ASCII 名（如中文）改名为 tool_{n}，
        中文原名拼进 description，保证 OpenAI 兼容接口不 400。
        """
        global_enabled = {r["plugin_id"]: bool(r["enabled"]) for r in self.list_all()}
        tools = build_plugin_tools(global_plugins=global_enabled)
        tools = tools + self._pet_dynamic_tools(global_enabled)
        return [self._sanitize_tool(t, i) for i, t in enumerate(tools)]

    def _pet_dynamic_tools(self, global_enabled: dict) -> list:
        """桌宠共享插件启用时，动态构造动作/表情工具（enum 随当前模型/动画实时变化）。"""
        from app.domain.pet.service import (
            VRM_PET_PLUGIN_ID,
            list_pet_actions,
            list_pet_expressions,
        )

        if not global_enabled.get(VRM_PET_PLUGIN_ID):
            return []
        actions = list_pet_actions()
        expressions = list_pet_expressions()
        out: list = []
        if actions:
            out.append(
                StructuredTool.from_function(
                    func=_make_do_action(actions),
                    name="do_action",
                    description=(
                        "让桌宠做出一个动作（身体动画）。根据对话场景选最合适的动作，"
                        "可用动作：\n" + "\n".join(f"- {a['name']}：{a['label_zh']}" for a in actions)
                    ),
                )
            )
        if expressions:
            out.append(
                StructuredTool.from_function(
                    func=_make_set_expression(expressions),
                    name="set_expression",
                    description=(
                        "切换桌宠的面部表情（blend shape）。根据对话情绪选最合适的表情，"
                        "可用表情：\n"
                        + "\n".join(f"- {e['name']}：{e['label_zh']}" for e in expressions)
                    ),
                )
            )
        return out

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


def _make_do_action(actions: list):
    """闭包工厂：do_action 工具函数（参数 action 返回桌宠播放 payload）。"""
    labels = {a["name"]: a["label_zh"] for a in actions}

    def _do(action: str) -> str:
        return json.dumps(
            {"motion": action, "expressions": [], "label": labels.get(action, action)},
            ensure_ascii=False,
        )

    _do.__doc__ = "让桌宠做出一个动作。"
    return _do


def _make_set_expression(expressions: list):
    """闭包工厂：set_expression 工具函数（参数 expression 返回表情播放 payload）。"""
    labels = {e["name"]: e["label_zh"] for e in expressions}

    def _set(expression: str) -> str:
        return json.dumps(
            {"motion": None, "expressions": [expression], "label": labels.get(expression, expression)},
            ensure_ascii=False,
        )

    _set.__doc__ = "切换桌宠的面部表情。"
    return _set


plugin_service = PluginService()
