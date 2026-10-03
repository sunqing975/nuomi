"""robot · 内核模块（modules/，v0.7 三区：模块=内核组成部分）。

apply(ctx) 维护 robot_enabled 状态并订阅 PLUGIN_TOGGLED：
- 启用：app.state.robot_enabled = True（前端据此显示机器人模式入口与语音对话）
- 停用：app.state.robot_enabled = False（前端隐藏入口，通用模式不受影响）

机器人模式的语音闭环（前端录音 → /api/transcribe → /api/chat → /api/speak）由
后端语音端点在 main.py 提供（复用 voice 插件的 faster-whisper STT 与 macOS say TTS），
本模块只负责"这个模式存不存在"：关掉 robot = 机器人模式消失。
"""

from app.infrastructure.engine.runtime import PLUGIN_TOGGLED


def apply(ctx) -> None:
    ctx.app.state.robot_enabled = True

    def _on_toggle(payload) -> None:
        if payload.get("plugin") == "robot":
            ctx.app.state.robot_enabled = bool(payload.get("enabled"))

    ctx.on(PLUGIN_TOGGLED, _on_toggle)
