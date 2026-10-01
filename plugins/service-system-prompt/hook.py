"""service-system-prompt · ctx.systemPrompt 服务（Seam Provider）。

build(last_user_msg, user=None) → str：伙伴人设 + 插件 system_instruction +
技能目录（name+description 常驻，正文按需）+ 记忆事实（memory 服务）。
对齐 Harness systemPrompt 子系统：提示词由服务组装，消费方是 agent-loop。
"""
from __future__ import annotations

from app.core import FiberState
from app.partner import assemble_system_prompt

inject = ["memory"]  # 依赖声明：memory 服务未就绪 → PENDING，就绪后自动启动


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
        facts = []
        store = ctx.get("memory")  # 运行时取服务（apply 时序无关，服务消失自动降级）
        if store is not None:
            merged = store.search(last_user_msg, top_k=3) + store.recent(top_k=3)
            seen: set[str] = set()
            for f in merged:
                if f.id not in seen:
                    seen.add(f.id)
                    facts.append(f)
        return assemble_system_prompt(
            partner,
            _instructions(),
            memory_facts=facts,
            skill_catalog=_skill_catalog(),
        )

    ctx.provide("systemPrompt", {"build": build})
