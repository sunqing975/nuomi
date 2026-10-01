"""Phase 6 · Shell 沙箱模式：settings.global["shell_default_mode"] 驱动 bash 默认权限。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path("/Users/superman/projects/code/nuomi")
TOOL_PATH = REPO / "plugins" / "shell" / "tool.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("nuomi_tool_shell_test", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_shell_default_mode_follows_setting(tmp_path, monkeypatch):
    mod = _load_tool()
    mod.set_default_mode("workspace-write")
    # 未显式 mode → 用运行时默认
    out = mod.bash.invoke({"command": "echo ok", "cwd": "."}) if hasattr(mod.bash, "invoke") else None
    # 直接函数调用路径
    assert mod._effective_mode(None) == "workspace-write"
    mod.set_default_mode("read-only")
    assert mod._effective_mode(None) == "read-only"
    # 显式 mode 优先
    assert mod._effective_mode("full-access") == "full-access"
    # 非法值回退默认
    mod.set_default_mode("nonsense")
    assert mod._effective_mode(None) == "read-only"
