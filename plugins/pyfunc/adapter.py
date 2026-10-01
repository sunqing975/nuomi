"""adapter（适配器）· 复用外部插件格式。

场景：外部生态（Codex/Claude 技能、开源仓库）的能力是普通函数 + 轻量注册标记，
没有 LangChain 依赖。adapter 扫描 tools_external/ 目录，把注册过的函数统一
转成 LangChain BaseTool——"外部插件 = 放进目录即被适配，自家格式不变"。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from langchain_core.tools import StructuredTool

_EXTERNAL_DIR = Path(__file__).resolve().parent / "tools_external"


def _load_external_funcs() -> list:
    funcs = []
    for py in sorted(_EXTERNAL_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"nuomi_external_{py.stem}", py)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        for obj in vars(module).values():
            if callable(obj) and getattr(obj, "_registered", False):
                funcs.append(obj)
    return funcs


def _adapt(fn) -> StructuredTool:
    doc = (fn.__doc__ or fn.__name__).strip().splitlines()[0] if fn.__doc__ else fn.__name__
    return StructuredTool.from_function(
        func=fn,
        name=fn.__name__,
        description=doc,
    )


TOOLS = [_adapt(f) for f in _load_external_funcs()]
