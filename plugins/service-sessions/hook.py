"""service-sessions · ctx.sessions 服务（Seam Provider）。

checkpointer 是 async 资源：由启动器（main lifespan）在 async with 中打开后注入
holder["checkpointer"]。消费方（agent-loop / API）从 holder 读取。
"""
from __future__ import annotations


def apply(ctx):
    holder = {
        "db": ctx.config.get("db", str(ctx.app.state.db_path if hasattr(ctx.app.state, "db_path") else "data/sessions.sqlite")),
        "checkpointer": getattr(ctx.app.state, "checkpointer", None),
    }

    def get_checkpointer():
        if holder["checkpointer"] is None:
            holder["checkpointer"] = getattr(ctx.app.state, "checkpointer", None)
        return holder["checkpointer"]

    svc = {"db": holder["db"], "checkpointer": get_checkpointer, "state": holder}
    ctx.provide("sessions", svc)
