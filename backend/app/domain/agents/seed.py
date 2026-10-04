"""默认专家种子：system_prompt 兜底 + 专家 workspace 由 ensure_agent_workspace 从模板复制。

糯米 = 默认专家（AI 助手人格）。详细 persona（USER/SOUL/AGENTS/MEMORY.md）在
专家 workspace（data_root/agent-workspaces/<agent_id>/）由 harness 每轮自动注入；
此处只提供兜底短句（experts/<name>/ 模板复制见 agents/service.ensure_agent_workspace）。
"""

from __future__ import annotations


def default_system_prompt() -> str:
    """糯米默认人设兜底：详细 persona 由专家 workspace 的记忆文件注入（A2 对齐 octop）。"""
    return "你是糯米，住在用户电脑里的人工智能助手。中文回答，简洁友好。"


def default_welcome_message() -> str:
    return "你好，我是糯米。今天想让我帮你做什么？"
