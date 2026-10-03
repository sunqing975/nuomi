"""human-in-the-loop · 高风险工具审批门（Phase 3）。

机制：plugin.json 用 `approval: ["tool_name", ...]` 标记需要人工确认的工具。
加载器把这类工具包进 ApprovalGate：调用时不直接执行，而是：
  1) 登记为 pending（id + 工具名 + 参数）
  2) 返回给模型一条明确提示（"已提交人工确认，id=xxx，等用户批准后生效"）
  3) 用户在界面/API 批准或拒绝；批准后补执行并保存结果

对外 API：
  GET  /api/approvals            待审批列表
  POST /api/approvals/{id}/approve  批准并执行
  POST /api/approvals/{id}/reject   拒绝

auto_approve=True（env/测试）时直接执行，绕过审批。
"""

from __future__ import annotations

import itertools
import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool


class ApprovalGate:
    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self._pending: dict[str, dict] = {}
        self._ids = itertools.count(1)

    def wrap(self, tool: BaseTool) -> BaseTool:
        async def _arun(**kwargs) -> Any:
            if self.auto_approve:
                return await tool.ainvoke(kwargs)
            pid = f"apv-{next(self._ids):04d}"
            self._pending[pid] = {
                "id": pid,
                "tool": tool.name,
                "args": kwargs,
                "created_at": time.time(),
                "status": "pending",
            }
            return (
                f"⚠️ 该操作需要人工确认。已提交审批（编号 {pid}），"
                f"等待用户批准后执行，当前未生效。请告诉用户去批准。"
            )

        def _run(**kwargs) -> Any:
            import asyncio

            return asyncio.run(_arun(**kwargs))

        return StructuredTool.from_function(
            coroutine=_arun,
            func=_run,
            name=tool.name,
            description=tool.description + "（⚠️ 高风险操作，执行前需用户批准）",
            args_schema=tool.args_schema,
        )

    # ---------- 查询与处置 ----------

    def pending(self) -> list[dict]:
        return [p for p in self._pending.values() if p["status"] == "pending"]

    def get(self, pid: str) -> dict | None:
        return self._pending.get(pid)

    async def approve(self, pid: str) -> str:
        p = self._pending.get(pid)
        if not p or p["status"] != "pending":
            return f"审批 {pid} 不存在或已处理"
        tool = p["tool"]
        # 执行：通过本类持有的工具注册表找回工具
        t = self._tools.get(tool)
        if t is None:
            p["status"] = "error"
            return f"审批 {pid} 的工具 {tool} 已不可用"
        p["status"] = "approved"
        p["resolved_at"] = time.time()
        try:
            result = await t.ainvoke(p["args"])
            p["result"] = str(result)
            return f"已批准并执行：{result}"
        except Exception as e:
            p["status"] = "error"
            p["result"] = f"{e.__class__.__name__}: {e}"
            return f"已批准但执行失败：{e}"

    def reject(self, pid: str) -> str:
        p = self._pending.get(pid)
        if not p or p["status"] != "pending":
            return f"审批 {pid} 不存在或已处理"
        p["status"] = "rejected"
        p["resolved_at"] = time.time()
        return f"已拒绝 {pid}"

    def register_tools(self, tools: list[BaseTool]):
        """注册原始工具表（审批通过后补执行用）。"""
        self._tools = {t.name: t for t in tools}


# ---------- 应用内单例 ----------
_gate = ApprovalGate()


def get_gate() -> ApprovalGate:
    return _gate


def set_gate(gate: ApprovalGate):
    global _gate
    _gate = gate
