"""插件领域服务：工作区 plugins/ ↔ octop-harness PluginRegistry ↔ SQLite 启停。

对齐 Octop 领域语言：
- 插件 = 工具注册（ctx.tool）+ 技能（ctx.skills）+ 钩子（ctx.middleware）
- 插件目录是 source of truth（plugin.yaml）；DB 只存启停状态
- 全局启用（plugins.enabled）：插件启用即对所有专家可用（2026-10-04 起
  不再有专家-插件绑定，专家不绑定插件；能力随对话请求注入见后续设计）
- AI 数字人（方案B，2026-10-04）：只有一个共享 VRM 插件（vrm-avatar），
  其启用/停用绑定AI 数字人开关；动作/表情工具在 tools() 装配时按当前模型动态构造
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
from app.domain.avatar.service import VRM_AVATAR_PLUGIN_ID  # 方案B：共享 AI 数字人插件（动态工具）
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
        """扫描并加载工作区 plugins/，同步到 DB（新插件默认启用）。

        ``install_deps=False``（安全）：不让插件在加载时隐式 ``pip install``
        ——插件是不可信输入（zip / git / 市场），自动装依赖等于把安装脚本
        的执行权交给插件作者。需要额外依赖的插件应显式声明并由用户自行安装。
        """
        plugins_dir = self.plugins_dir()
        dirs = discover_plugin_dirs(plugins_dir)
        loaded = load_all(plugins_dir, install_deps=False) if dirs else []
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

            # 清理"目录已消失"的残留行：本模块的设计原则是**插件目录即 source of truth**，
            # 而下面的 INSERT OR IGNORE 只会新增/保活、从不删除 —— 用户手动删掉插件目录后，
            # 控制台会留下一个点不开、也没工具的幽灵条目（enabled 为 1 却 tool_count=0）。
            removed = {
                r["plugin_id"] for r in conn.execute("SELECT plugin_id FROM plugins").fetchall()
            } - {p.manifest.id for p in loaded}
            if removed:
                conn.executemany(
                    "DELETE FROM plugins WHERE plugin_id = ?", [(pid,) for pid in removed]
                )
        return rows

    # ---------- 查询 ----------

    def list_all(self) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
        registry = PluginRegistry()
        out = []
        for r in rows:
            d = dict(r)
            if r["plugin_id"] == VRM_AVATAR_PLUGIN_ID:
                # 方案B：AI 数字人工具不走静态注册，由 tools() 装配时动态构造（do_action/set_expression）。
                # 启用时按当前动作/表情清单统计实际动态工具数，避免插件列表误显示"0 个工具"。
                from app.domain.avatar.service import list_avatar_actions, list_avatar_expressions

                n = (1 if list_avatar_actions() else 0) + (1 if list_avatar_expressions() else 0)
                d["tool_count"] = n if r["enabled"] else 0
            else:
                d["tool_count"] = sum(
                    1 for t in registry.all_tools() if t.plugin_id == r["plugin_id"]
                )
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

        模型插件不在此删除（由「AI 数字人」删除模型时级联）——调用方先检查。
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

    def _enabled_map(self) -> dict[str, bool]:
        """插件 id → 是否全局启用（一次 DB 查询）。"""
        return {r["plugin_id"]: bool(r["enabled"]) for r in self.list_all()}

    def tools_and_owners(self) -> tuple[list, dict[str, str]]:
        """一次 ``list_all()`` 同时装配工具与来源映射（对话热路径用这个）。

        ``tools()`` 与 ``tool_owners()`` 各自都会查一次 ``list_all()``（含 VRM 表情解析），
        对话里两者都要用 → 走这里可以省掉一遍。注意**不做结果缓存**：实测 ``tools()``
        在真实工作区约 5.6ms，而缓存需要按「插件启停 / 切模型 / 动画增删」失效，
        为 5ms 引入失效逻辑不划算（且一旦漏失效就是工具集过期这种难查的 bug）。
        """
        enabled = self._enabled_map()
        return self._build_tools(enabled), self._build_owners(enabled)

    def tools(self) -> list:
        """按全局启停装配插件工具 + AI 数字人动态工具（StructuredTool 列表）。

        专家不再绑定插件（2026-10-04 解耦）：插件启用即对所有专家可用。
        AI 数字人（方案B）：vrm-avatar 插件启用时，动态构造 do_action / set_expression——
        enum 清单按当前激活 VRM 模型（GLB blend shape）与 animations/*.vrma 实时生成，
        切模型 / 新增动画零重启（工具在每次对话装配时重算）。
        工具名做 slug 防御：非 ASCII 名（如中文）改名为 tool_{n}，
        中文原名拼进 description，保证 OpenAI 兼容接口不 400。
        同名工具去重（2026-10-05）：多个插件声明同名工具时保留最后注册的——
        octop build_plugin_tools 不去重，同名会进两个 StructuredTool 造成调用歧义。
        """
        return self._build_tools(self._enabled_map())

    def _build_tools(self, global_enabled: dict[str, bool]) -> list:
        tools = build_plugin_tools(global_plugins=global_enabled)
        tools = tools + self._avatar_dynamic_tools(global_enabled)
        # 同名去重：dict 键覆盖保留最后注册者（与 tool_owners() 的映射一致）
        seen: dict[str, StructuredTool] = {}
        for t in tools:
            seen[t.name] = t
        tools = list(seen.values())
        return [self._sanitize_tool(t, i) for i, t in enumerate(tools)]

    def tool_owners(self) -> dict[str, str]:
        """工具名 → 来源插件 id（同名工具保留最后注册者，与 tools() 去重顺序一致）。

        对话流工具帧据此附加 plugin_id，前端展示来源徽标（多插件同名工具时可辨识）。
        注意：_sanitize_tool 会把中文工具名改成 tool_{n}，中文名场景下映射会 miss（无徽标），
        本项目工具名均为英文（slug 化），可接受。
        """
        return self._build_owners(self._enabled_map())

    def _build_owners(self, global_enabled: dict[str, bool]) -> dict[str, str]:
        from octop_harness.plugins.registry import PluginRegistry

        owners: dict[str, str] = {}
        for reg in PluginRegistry().all_tools():
            if global_enabled.get(reg.plugin_id) is False:
                continue
            owners[reg.name] = reg.plugin_id
        return owners

    def _avatar_dynamic_tools(self, global_enabled: dict) -> list:
        """AI 数字人共享插件启用时，动态构造动作/表情工具（enum 随当前模型/动画实时变化）。"""
        from app.domain.avatar.service import (
            VRM_AVATAR_PLUGIN_ID,
            list_avatar_actions,
            list_avatar_expressions,
        )

        if not global_enabled.get(VRM_AVATAR_PLUGIN_ID):
            return []
        actions = list_avatar_actions()
        expressions = list_avatar_expressions()
        out: list = []
        if actions:
            out.append(
                StructuredTool.from_function(
                    func=_make_do_action(actions),
                    name="do_action",
                    description=(
                        "让AI 数字人做出一个动作（身体动画）。根据对话场景选最合适的动作，"
                        "可用动作：\n"
                        + "\n".join(f"- {a['name']}：{a['label_zh']}" for a in actions)
                    ),
                )
            )
        if expressions:
            out.append(
                StructuredTool.from_function(
                    func=_make_set_expression(expressions),
                    name="set_expression",
                    description=(
                        "切换AI 数字人的面部表情（blend shape）。根据对话情绪选最合适的表情，"
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
    """闭包工厂：do_action 工具函数（参数 action 返回AI 数字人播放 payload）。"""
    labels = {a["name"]: a["label_zh"] for a in actions}

    def _do(action: str) -> str:
        return json.dumps(
            {"motion": action, "expressions": [], "label": labels.get(action, action)},
            ensure_ascii=False,
        )

    _do.__doc__ = "让AI 数字人做出一个动作。"
    return _do


def _make_set_expression(expressions: list):
    """闭包工厂：set_expression 工具函数（参数 expression 返回表情播放 payload）。"""
    labels = {e["name"]: e["label_zh"] for e in expressions}

    def _set(expression: str) -> str:
        return json.dumps(
            {
                "motion": None,
                "expressions": [expression],
                "label": labels.get(expression, expression),
            },
            ensure_ascii=False,
        )

    _set.__doc__ = "切换AI 数字人的面部表情。"
    return _set


plugin_service = PluginService()
