"""agent-researcher · Agent preset：调研专员。"""
inject = ["agents"]


def apply(ctx):
    agents = ctx.get("agents")
    agents["presets"]["researcher"] = {
        "name": "researcher",
        "label": "调研专员",
        "description": "查资料、读网页、检索知识库，回答事实类问题",
        "tools": None,
        "system_prompt_hint": "你是严谨的调研专员，优先使用工具获取事实，不编造。",
    }
    ctx.provide("preset:researcher", agents["presets"]["researcher"])
