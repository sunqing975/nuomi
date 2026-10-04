"""默认专家种子：从 experts/<name>/ 模板资产组装 system_prompt（IDENTITY + SOUL）。

糯米 = 默认专家（小猫伙伴人格）。多专家时每个 Agent 可带自己的 system_prompt。
"""

from __future__ import annotations

from pathlib import Path

# backend/app/domain/agents/seed.py -> parents: [agents, domain, app, backend, nuomi]
EXPERTS_DIR = Path(__file__).resolve().parents[4] / "experts"


def _read(rel: str) -> str:
    p = EXPERTS_DIR / rel
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def default_system_prompt() -> str:
    """组装糯米默认人设（IDENTITY + SOUL，AGENTS.md 作为工作记忆由 workspace 承载）。"""
    identity = _read("nuomi/IDENTITY.md")
    soul = _read("nuomi/SOUL.md")
    parts = [p for p in (identity, soul) if p]
    if not parts:
        return "你是糯米，一个住在用户电脑里的桌面 AI 人格。中文回答，简洁友好。"
    return "\n\n".join(parts)


def default_welcome_message() -> str:
    return "你好，我是糯米。今天想让我帮你做什么？"
