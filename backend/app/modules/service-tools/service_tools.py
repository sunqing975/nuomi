"""service-tools · ctx.tools 服务（Seam Definition + Provider）。

注册表：汇总全部 ACTIVE fiber 注册的工具（不持有工具，工具属于贡献插件）。
执行流水线：工具调用前走 waterfall('tools/pre-execute')（审批/改写可拦截），
执行后 emit('tools/result')。所有调用可观测。
"""

from __future__ import annotations

import logging

from app.core import FiberState

logger = logging.getLogger("nuomi.services.tools")


def apply(ctx):
    def list_tools():
        reg = ctx.app.state.registry
        out = []
        for f in reg.fibers.values():
            if f.state == FiberState.ACTIVE and f.ctx is not None:
                for t in f.ctx.tools:
                    if t not in out:
                        out.append(t)
        return out

    def by_name(name):
        for t in list_tools():
            if t.name == name:
                return t
        return None

    def schema_snapshot():
        """提示词组装用：{name: description+args} 摘要（不泄露完整 JSON）。"""

        out = {}
        for t in list_tools():
            desc = getattr(t, "description", "") or ""
            out[t.name] = {"description": desc[:400]}
        return out

    async def execute(name, args):
        payload = {"name": name, "args": dict(args or {})}
        tool = by_name(name)
        if tool is None:
            return {"error": f"未知工具: {name}"}
        # pre-execute waterfall：审批/重写可在此拦截（blocked 短路）
        decision = await ctx.waterfall("tools/pre-execute", payload, lambda: payload)
        if decision.get("blocked"):
            ctx.emit(
                "tools/result",
                name=name,
                args=args,
                result={"error": decision.get("reason", "调用被拦截")},
                blocked=True,
            )
            return {"error": decision.get("reason", "调用被拦截")}
        try:
            result = await tool.ainvoke(decision.get("args", args))
        except Exception as e:
            logger.exception("tool execute failed: %s", name)
            result = {"error": f"{e.__class__.__name__}: {e}"}
        ctx.emit("tools/result", name=name, args=args, result=result, blocked=False)
        return result

    svc = {"list": list_tools, "by_name": by_name, "execute": execute, "schema": schema_snapshot}
    ctx.provide("tools", svc)
