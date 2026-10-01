"""shell · 能力插件入口（Harness 形态：apply(ctx) 声明贡献：工具 + SKILL.md 技能）。

运行时把「设置 → 行为 → Shell 沙箱模式」注入工具默认值：
settings.global["shell_default_mode"] 变更 → set_default_mode 热更新。
"""
import importlib.util
import sys
from pathlib import Path

from langchain_core.tools import BaseTool, tool

MODES = ("read-only", "workspace-write", "full-access")


def apply(ctx) -> None:
    # 加载同目录 tool.py 的 TOOLS 并注册为模型工具
    mod_path = Path(__file__).resolve().parent / "tool.py"
    spec = importlib.util.spec_from_file_location(f"nuomi_tools_{Path(__file__).parent.name}", mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for item in getattr(mod, "TOOLS", []):
        if isinstance(item, BaseTool):
            ctx.register_tools([item])
        elif callable(item):
            ctx.register_tools([tool(item)])

    # 初始默认模式：settings 已存值优先，否则插件 config（plugin.json）
    initial = None
    try:
        initial = ctx.app.state.settings.get("shell_default_mode")
    except Exception:  # noqa: BLE001
        initial = None
    if initial not in MODES:
        initial = ctx.config.get("shell_default_mode")
    if initial in MODES:
        mod.set_default_mode(initial)

    # 设置变更热更新（service-settings 全局键写入时触发）
    def _on_settings(payload) -> None:
        if payload.get("scope") == "global" and payload.get("key") == "shell_default_mode":
            if payload.get("value") in MODES:
                mod.set_default_mode(payload["value"])

    ctx.on("settings/changed", _on_settings)
