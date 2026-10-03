"""agent-companion · Agent preset：陪伴伙伴。

preset 是"会话能力组装"的描述（对齐 Harness agent preset）：注册到 ctx.agents，
supervisor 路由/前端据此展示；同一引擎下换 preset = 换能力组合。
"""

inject = ["agents"]


def apply(ctx):
    agents = ctx.get("agents")
    agents["presets"]["companion"] = {
        "name": "companion",
        "label": "陪伴伙伴",
        "description": "糯米本体：日常聊天、记住你、用工具解决小事",
        "tools": None,  # None = 全部能力工具
        "system_prompt_hint": "你是糯米，一只住在电脑里的小猫伙伴。",
    }
    ctx.provide("preset:companion", agents["presets"]["companion"])
