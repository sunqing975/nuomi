"""service-system-prompt · ctx.systemPrompt 服务（Seam Provider）。

build(last_user_msg) → str：伙伴人设 + 插件 system_instruction +
技能目录（name+description 常驻，正文按需）。
对齐 Harness systemPrompt 子系统：提示词由服务组装，消费方是 agent-loop。

记忆注入（记忆 v2）：已从本服务**移除**——冻结快照由 NuomiMiddleware 负责
（会话开始取一次，含容量 header）。本服务不再依赖 memory 服务。
"""
from __future__ import annotations

from app.core import FiberState
from app.agent.partner import assemble_system_prompt


def apply(ctx):
    partner = ctx.app.state.partner

    def _instructions():
        reg = ctx.app.state.registry
        out = []
        for f in reg.fibers.values():
            if f.state == FiberState.ACTIVE and f.ctx is not None:
                ins = (f.meta or {}).get("system_instruction")
                if ins:
                    out.append(ins)
        return out

    def _skill_catalog():
        reg = ctx.app.state.registry
        out = []
        for f in reg.fibers.values():
            if f.state == FiberState.ACTIVE and f.ctx is not None:
                for s in f.ctx.skills.values():
                    out.append({"name": s.name, "description": s.description, "when_to_use": s.when_to_use})
        return out

    def build(last_user_msg: str, user: str | None = None) -> str:
        return assemble_system_prompt(
            partner,
            _instructions(),
            memory_facts=[],
            skill_catalog=_skill_catalog(),
        )

    ctx.provide("systemPrompt", {"build": build})
