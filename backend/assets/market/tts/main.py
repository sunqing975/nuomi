"""AI 数字人语音播报插件（market 内置，kind=tool 对齐 octop 插件语义）。

- 自动播报（主功能）：订阅 ``conversation.completed`` 事件，对话结束自动合成完整回复并广播给壳；
- ``tts_speak`` 工具：模型/用户显式朗读时调用（同一合成/广播通道）；
- 配置：``plugin.yaml`` 的 ``settings`` 段声明（控制台「设置」页动态渲染表单，存 plugins/tts/config.json）；
  同时映射为 ``ctx.tool(config_fields=...)``，对齐 octop 原生的工具配置字段语义。
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "enabled": False,
    "auto_speak": True,
    "api_url": "",
    "api_key": "",
    "model": "doubao-tts",
    "voice": "zh_female_...",
    "sample_rate": "24000",
}


def config_path(plugin_dir: Path) -> Path:
    return plugin_dir / "config.json"


def load_config(plugin_dir: Path) -> dict:
    """读插件配置（缺失字段用默认值；永不抛错）。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(config_path(plugin_dir).read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if v is not None})
    except (OSError, ValueError):
        pass
    return cfg


def is_ready(cfg: dict) -> bool:
    """播报前置条件：启用 + API 地址与 Key 齐全。"""
    return bool(cfg.get("enabled") and cfg.get("api_url") and cfg.get("api_key"))


def synthesize(text: str, cfg: dict) -> bytes:
    """调 OpenAI 兼容 /audio/speech，返回音频字节（mp3）。"""
    payload = {
        "model": cfg.get("model") or "doubao-tts",
        "input": text,
        "voice": cfg.get("voice") or "zh_female_...",
        "response_format": "mp3",
        "sample_rate": int(cfg.get("sample_rate") or 24000),
    }
    req = urllib.request.Request(
        str(cfg["api_url"]).rstrip("/"),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _broadcast_audio(audio: bytes) -> str:
    """存临时音频文件并广播给壳（avatar/events），返回音频访问路径。"""
    import uuid

    from app.config import settings as app_settings
    from app.infra.avatar_events import avatar_events

    d = app_settings.workspace_path / "tmp" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    (d / f"{name}.mp3").write_bytes(audio)
    url = f"/api/plugins/tts/audio/{name}"
    avatar_events.publish({"type": "tts", "audio_url": url})
    return url


def _speak(text: str, plugin_dir: Path) -> str:
    cfg = load_config(plugin_dir)
    if not is_ready(cfg):
        return "语音播报未启用：请先在「设置 → AI 数字人语音播报」配置 TTS API 地址与 Key 并启用"
    try:
        audio = synthesize(text, cfg)
    except Exception as exc:  # 网络 / API 错误，返回给模型转述
        return f"语音合成失败：{exc}"
    if not audio:
        return "语音合成无输出"
    _broadcast_audio(audio)
    return f"已播报（{len(audio) // 1024} KB）"


def setup(ctx) -> None:
    """注册 tts_speak 工具；config_fields 由 plugin.yaml settings 段映射（配置 schema 单源）。
    同时订阅 conversation.completed 事件实现对话结束自动播报（第 2 层插件能力）。"""
    import yaml

    from app.infra.events import Events, event_bus

    plugin_dir: Path = ctx.source_path
    try:
        manifest = yaml.safe_load((plugin_dir / "plugin.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        manifest = {}
    fields = [f for f in (manifest.get("settings") or []) if isinstance(f, dict)]

    def _speak_closed(text: str) -> str:
        return _speak(text, plugin_dir)

    ctx.tool(
        "tts_speak",
        _speak_closed,
        description="语音播报：把指定文本用 AI 数字人语音朗读出来（需先在「设置 → AI 数字人语音播报」配置 TTS API 并启用）",
        config_fields=[dict(f) for f in fields],
    )

    # —— 事件订阅：对话完成自动播报（订阅者异常由事件总线隔离，不阻断对话）——
    def _on_conversation_completed(e: dict) -> None:
        cfg = load_config(plugin_dir)
        if not (cfg.get("enabled") and cfg.get("auto_speak")):
            return
        answer = str(e.get("answer") or "").strip()
        if not answer:
            return
        try:
            audio = synthesize(answer, cfg)
        except Exception as exc:  # 未配置 / 网络 / API 错误：静默，不阻断对话
            logger.warning("TTS 自动播报合成失败（已静默）: %s", exc)
            return
        if audio:
            try:
                _broadcast_audio(audio)
            except Exception as exc:
                logger.warning("TTS 自动播报广播失败（已静默）: %s", exc)

    event_bus.on(Events.conversation_completed, _on_conversation_completed)
