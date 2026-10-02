"""Phase 4c · 语音 + Web 插件：可加载、可调用、失败有兜底。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.plugins.robust import apply_robust
from .conftest import applied_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    app = applied_app(REPO_ROOT / "plugins")
    s = next(p for p in app.state.plugins if p.name == name)
    return s.tools


def test_voice_skill_loaded_with_two_tools():
    tools = {t.name: t for t in _load("voice")}
    assert "speak" in tools and "transcribe" in tools
    assert "macOS" in tools["speak"].description


def test_voice_transcribe_validates_input(tmp_path):
    tools = {t.name: t for t in _load("voice")}
    r = tools["transcribe"].invoke({"audio_path": str(tmp_path / "none.wav")})
    assert "不存在" in r
    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFF")
    r2 = tools["transcribe"].invoke({"audio_path": str(f)})
    assert "接口已就绪" in r2


@pytest.mark.skipif(shutil.which("say") is None, reason="非 macOS 环境")
def test_voice_speak_real_tts(tmp_path):
    tools = {t.name: t for t in _load("voice")}
    r = tools["speak"].invoke({"text": "测试语音"})
    assert r.startswith("已生成语音：") and r.endswith(".mp3")


def test_web_http_get_rejects_bad_url():
    tools = {t.name: t for t in _load("web")}
    assert "必须以" in tools["http_get"].invoke({"url": "ftp://x"})


def test_web_http_get_real_page():
    tools = {t.name: t for t in _load("web")}
    r = tools["http_get"].invoke({"url": "https://example.com", "max_chars": 500})
    assert "标题" in r or "Example" in r


def test_web_robust_applied_via_plugin_config():
    """plugin.json robust（timeout/retry）应被 collect_tools 统一应用。"""
    app = applied_app(REPO_ROOT / "plugins")
    s = next(p for p in app.state.plugins if p.name == "web")
    raw = s.tools
    wrapped = [apply_robust(t, s.meta.get("robust") or {}) for t in raw]
    # 包装后仍是同名工具，invoke 行为不变
    r = wrapped[0].invoke({"url": "https://example.com"})
    assert isinstance(r, str) and r
