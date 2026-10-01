"""Phase 5 · shell + fs 执行能力插件：沙箱三级、路径边界、加载器审批集成。

注意：shell/fs 工作区锚定 settings.workspace_dir，测试用 tmp_path 隔离，不碰真实 backend/data/workspace。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.skills import collect_tools
from .conftest import applied_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    app = applied_app(REPO_ROOT / "plugins")
    s = next(p for p in app.state.plugins if p.name == name)
    return {t.name: t for t in s.tools}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path / "ws"))
    return settings.workspace_path


# ---------- shell 沙箱 ----------


def test_shell_loaded_with_both_tools(ws):
    tools = _load("shell")
    assert {"bash", "bash_full"} <= set(tools)


def test_shell_readonly_rejects_write_cmd(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "touch x.txt", "mode": "read-only"})
    assert "沙箱拦截" in r and "read-only" in r


def test_shell_readonly_rejects_redirect(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "echo hi > f.txt", "mode": "read-only"})
    assert "沙箱拦截" in r


def test_shell_readonly_allows_query(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "echo hello", "mode": "read-only"})
    assert "hello" in r and "退出码 0" in r


def test_shell_workspace_write_writes_inside(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "echo data > f.txt && cat f.txt"})
    assert "data" in r
    assert (ws / "f.txt").read_text().strip() == "data"


def test_shell_workspace_write_blocks_abs_path(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "echo x > /tmp/nuomi_evil.txt"})
    assert "沙箱拦截" in r


def test_shell_workspace_write_blocks_traversal(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "echo x > ../evil.txt"})
    assert "沙箱拦截" in r


def test_shell_full_access_allows_outside(ws, tmp_path):
    tools = _load("shell")
    target = tmp_path / "outside.txt"
    r = tools["bash"].invoke(
        {"command": f"echo ok > {target}", "cwd": ".", "mode": "full-access"}
    )
    assert "退出码 0" in r and target.exists()


def test_shell_cwd_outside_workspace_rejected(ws):
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "pwd", "cwd": ".."})
    assert "工作区" in r


def test_shell_timeout(ws, monkeypatch):
    monkeypatch.setattr(settings, "shell_timeout", 0.5)
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "sleep 3"})
    assert "超时" in r


def test_shell_strips_sensitive_env(ws, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-123")
    tools = _load("shell")
    r = tools["bash"].invoke({"command": "env"})
    assert "sk-test-secret-123" not in r


# ---------- fs 工作区文件 ----------


def test_fs_write_read_roundtrip(ws):
    tools = _load("fs")
    r = tools["write_file"].invoke({"path": "notes/a.md", "content": "你好，糯米"})
    assert "已写入" in r
    r2 = tools["read_file"].invoke({"path": "notes/a.md"})
    assert "你好，糯米" in r2


def test_fs_append(ws):
    tools = _load("fs")
    tools["write_file"].invoke({"path": "log.txt", "content": "one\n"})
    tools["write_file"].invoke({"path": "log.txt", "content": "two\n", "mode": "append"})
    assert (ws / "log.txt").read_text() == "one\ntwo\n"


def test_fs_list_and_search(ws):
    tools = _load("fs")
    tools["write_file"].invoke({"path": "docs/guide.md", "content": "# g"})
    tools["write_file"].invoke({"path": "docs/readme.txt", "content": "t"})
    listing = tools["list_dir"].invoke({"path": "docs"})
    assert "guide.md" in listing and "readme.txt" in listing
    found = tools["search_files"].invoke({"pattern": "*.md", "path": "."})
    assert "docs/guide.md" in found


def test_fs_delete(ws):
    tools = _load("fs")
    p = ws / "tmp.txt"
    p.write_text("x")
    r = tools["delete_file"].invoke({"path": "tmp.txt"})
    assert "已删除" in r and not p.exists()


def test_fs_blocks_abs_outside(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret")
    tools = _load("fs")
    r = tools["read_file"].invoke({"path": str(secret)})
    assert "工作区" in r


def test_fs_blocks_dotdot(ws):
    tools = _load("fs")
    r = tools["read_file"].invoke({"path": "../secret.txt"})
    assert "工作区" in r
    r2 = tools["write_file"].invoke({"path": "../../evil.txt", "content": "x"})
    assert "工作区" in r2


def test_fs_missing_file_message(ws):
    tools = _load("fs")
    assert "不存在" in tools["read_file"].invoke({"path": "nope.txt"})


# ---------- 加载器集成：approval 审批门 ----------


def test_bash_full_wrapped_in_approval(ws):
    app = applied_app(REPO_ROOT / "plugins")
    tools = {t.name: t for t in collect_tools(app.state.plugins, None)}
    assert "bash_full" in tools
    assert "执行前需用户批准" in tools["bash_full"].description
    # bash 普通模式不进审批门（无审批门后缀）
    assert "执行前需用户批准" not in tools["bash"].description
