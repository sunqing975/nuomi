"""voice · 能力插件入口（Harness 形态：apply(ctx) 声明贡献：工具 + SKILL.md 技能）。"""
import importlib.util
import sys
from pathlib import Path

from langchain_core.tools import BaseTool, tool


def apply(ctx) -> None:
    # 加载同目录 tool.py 的 TOOLS 并注册为模型工具（级3 资源在工具内部按需初始化）
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
