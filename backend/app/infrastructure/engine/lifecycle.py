"""plugins.py · 插件/模块加载与启停（v0.7，对齐 Octop：插件 / 技能 / 模块三区）。

v0.7 形态（回应"插件概念模糊"）：
- **插件（plugins/）** = 分发单元：给 LLM 注册工具（Octop 插件语义）。
- **模块（backend/app/modules/）** = 内核组成部分：service-* / preset / hook 类，
  概念上常驻内核，加载机制与插件一致（apply(ctx) 声明贡献）。
- **技能（skills/）** = 独立文档资产，由加载器统一注册（目录只给 name+description，正文按需读）。
- 启停 = 配置组合：启用 apply，停用 dispose，工具贡献变化时重建 Agent。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from .runtime import PLUGIN_TOGGLED, PluginContext


def load_plugins(app) -> None:
    """启动：对每个插件/模块执行入口 apply(ctx)，收集贡献（幂等：已注册的跳过）。"""
    for p in app.state.plugins:
        if p.error or not p.path:
            continue
        if p.name in app.state.plugin_ctx:
            continue
        _apply(app, p)


def _apply(app, p) -> bool:
    """执行 apply(ctx) 并收集贡献到 app.state。兼容遗留：无 hook.py 时自动用 tool.py 的 TOOLS。"""
    mod, err = _load_module(p.path, p.meta.get("entry", "hook.py"))
    ctx = PluginContext(app)
    # 与 fiber 加载一致：config 由 profile entry 的 config 合并（插件 hook.py 依赖 ctx.config）
    ctx.config = dict(p.meta.get("config", {}))
    if mod is None or not (hasattr(mod, "apply") or hasattr(mod, "TOOLS")):
        # 遗留形态（仅 tool.py）：自动注册 TOOLS + SKILL.md（技能由加载器统一处理）
        mod2, err2 = _load_module(p.path, "tool.py")
        if mod2 is None or not getattr(mod2, "TOOLS", None):
            ctx.dispose()
            p.error = err or err2 or "缺少入口模块（hook.py 的 apply(ctx) 或 tool.py 的 TOOLS）"
            return False
        _register_raw_tools(ctx, mod2.TOOLS)
    elif hasattr(mod, "apply"):
        try:
            mod.apply(ctx)
        except Exception as e:
            ctx.dispose()
            p.error = f"apply 失败: {e.__class__.__name__}: {e}"
            return False
    else:  # 有 TOOLS 无 apply（函数形态的简化插件）
        _register_raw_tools(ctx, mod.TOOLS)

    _collect(app, p, ctx)
    return True


def _register_raw_tools(ctx: PluginContext, raw: list) -> None:
    """把 @tool 函数 / BaseTool / StructuredTool 列表注册进 ctx。"""
    tools: list[BaseTool] = []
    for item in raw:
        if isinstance(item, BaseTool):
            tools.append(item)
        elif callable(item):
            tools.append(tool(item))
        else:
            continue
    ctx.register_tools(tools)


def _collect(app, p, ctx: PluginContext) -> None:
    """apply 成功后：注册 ctx、加入启用组合、回填贡献到描述符。

    服务/事件 = 声明式（manifest provides/hooks）∪ 运行时（ctx.provide/ctx.on）。
    """
    app.state.plugin_ctx[p.name] = ctx
    app.state.enabled_plugins.add(p.name)
    p.tools = ctx.tools
    p.services = _dedupe(p.provides + list(ctx.services))
    p.events = _dedupe(p.hooks + list(ctx.events))
    p.error = None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _unload(app, name: str) -> None:
    """停用：dispose（卸载事件订阅/服务）并从组合中移除。"""
    ctx = app.state.plugin_ctx.pop(name, None)
    if ctx is not None:
        ctx.dispose()
    app.state.enabled_plugins.discard(name)


def toggle_plugin(app, name: str) -> dict:
    """统一启停（配置组合语义）：
    启用 = apply(ctx) 重新贡献；停用 = dispose 移除；工具贡献变化 → 重建 Agent。
    模块（无工具，如 team/voice-input/robot）经 PLUGIN_TOGGLED 事件自响应运行时状态。
    """
    plugins = {s.name: s for s in app.state.plugins}
    if name not in plugins:
        raise KeyError(name)

    p = plugins[name]
    enabled = name not in app.state.enabled_plugins

    if enabled:
        ok = _apply(app, p)
        if not ok:
            return {"name": name, "enabled": False, "rebuilt": False, "error": p.error}
    else:
        app.state.enabled_plugins.discard(name)

    # 发布事件（启用时订阅刚注册、停用时订阅仍存活）：插件自己响应自身状态（team 挂/卸、voice-input 设置）
    app.state.event_bus.publish(PLUGIN_TOGGLED, {"plugin": name, "enabled": enabled})
    if not enabled:
        _unload(app, name)  # dispose 在事件之后：处理器已执行完毕再清理订阅

    rebuilt = None
    if p.has_tools():
        rebuilt = app.state.rebuild_agents() is not None
    return {
        "name": name,
        "enabled": enabled,
        "rebuilt": rebuilt is not None,
        "tools": [t.name for t in app.state.tools],
        "error": None,
    }


def _load_module(plugin_dir: Path, entry: str):
    """按路径加载插件入口模块（每次新建，避免命名冲突）。返回 (module, error)。"""
    mod_path = plugin_dir / entry
    if not mod_path.exists():
        return None, f"缺少入口模块 {entry}"
    spec = importlib.util.spec_from_file_location(f"nuomi_plugin_{plugin_dir.name}", mod_path)
    if spec is None or spec.loader is None:
        return None, "无法创建模块 spec"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[plugins] 加载 {plugin_dir.name}/{entry} 失败: {e}", file=sys.stderr)
        return None, f"入口加载失败: {e.__class__.__name__}: {e}"
    return module, None


def build_plugin_list(app) -> list[dict]:
    """能力面板视图：每个插件/模块展示它贡献了什么（技能/工具/服务/事件），并标注来源。

    技能已独立成概念（skills/ 技能区）：插件的 skills 贡献 = 技能区里同名技能（关联展示）。
    """
    plugins: list[dict] = []
    enabled: set[str] = app.state.enabled_plugins
    skill_names = {s.name for s in getattr(app.state, "skills", [])}

    for p in app.state.plugins:
        contributions: dict = {"skills": [], "tools": [], "services": [], "events": []}
        if p.name in skill_names:
            contributions["skills"] = [p.name]
        contributions["tools"] = [t.name for t in p.tools]
        contributions["services"] = p.services
        contributions["events"] = p.events
        plugins.append(
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "category": p.category,  # plugin（可选用能力）| module（内核组成部分）
                "enabled": p.name in enabled,
                "error": p.error,
                "contributions": contributions,
                "settings": app.state.plugin_settings.get(p.name, {}),
            }
        )
    return plugins


def build_skill_tool(skills, enabled_getter=None):
    """对齐 Harness 的 dsh-tool-skill：模型按需读取 SKILL.md 全文的 skill 工具。

    目录（<available_skills>）只给 name+description；正文经此工具按需加载。
    技能来自独立技能区（skills/），enabled_getter 保留参数用于将来按需过滤。
    """

    @tool
    def skill_doc(name: str) -> str:
        """读取技能说明书（SKILL.md 全文）。

        当 <available_skills> 目录中的技能看起来适用于当前任务、但你不确定具体怎么做时，
        调用本工具读取完整说明书：它会告诉你该技能的完整步骤、规则与注意事项。
        参数 name：技能名（如 "memory"、"datetime"）。若技能不存在返回错误说明。
        """
        by_name = {s.name: s for s in skills}
        s = by_name.get(name)
        if s is None:
            return f"未知技能：{name}。可用技能见 <available_skills> 目录。"
        if enabled_getter is not None and name not in enabled_getter():
            return f"技能 {name} 当前已停用。"
        if not s.body:
            return f"技能 {name} 没有 SKILL.md 正文。"
        return f'<skill_content name="{s.name}">\n{s.body}\n</skill_content>'

    return skill_doc
