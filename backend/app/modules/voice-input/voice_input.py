"""voice-input · 内核模块（modules/，v0.7 三区：模块=内核组成部分）。

模块扩展"运行时"而非"模型能力"：apply(ctx) 注册语音输入服务，
并订阅 PLUGIN_TOGGLED 事件响应自身启停（开=前端显示麦克风按钮）。
与插件同构（module.json + entry），区别只在目录归属（modules/ = 内核）。
"""

from app.plugins.runtime import PLUGIN_TOGGLED

SETTINGS_KEY = "voice_input"


def apply(ctx) -> None:
    settings = ctx.app.state.plugin_settings.setdefault(SETTINGS_KEY, {"enabled": True})
    # 注册服务：前端/其他组件经 app.state.services["voice_input"] 读取
    ctx.provide("voice_input", settings)

    def _on_toggle(payload) -> None:
        if payload.get("plugin") == "voice-input":
            ctx.app.state.plugin_settings[SETTINGS_KEY] = {
                "enabled": bool(payload.get("enabled", False))
            }

    ctx.on(PLUGIN_TOGGLED, _on_toggle)
