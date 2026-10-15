"""审批台账（HITL）：谁在什么时候被要求批哪个写操作、人最后怎么答的。

背景（实测/harness 调研结论，2026-10-16）：
- 待审动作（``action_requests``）由 harness 的 tool_guard 产出，随
  ``AgentEventType.HITL_REQUIRED`` 事件透出；nuomi 只在 SSE 帧里见过它，
  ``request_id`` 是 uuid4 现生成的**一次性 id，哪都不落**。
- 恢复靠 ``agent.resume_hitl(thread_id, decisions)`` → graph checkpoint
  （``{data_root}/.system/checkpoints.sqlite``）里那个 interrupt 是**持久的**，
  进程重启也能续跑；但 harness **没有**「列出当前 pending 审批」的公开 API。
  于是刷新页面 = 卡片永远找不回来，用户只看到一条戛然而止的回复。
- 也没有台账：harness 侧只往滚动日志打一行 ``Tool guard paused ... for approval``
  （octop_harness/middleware/tool_guard.py:91-95），决策内容本身不留痕。

所以这张表同时解决两件事：把「请求 + 决策」落在 nuomi 自己的库里，
读它能恢复卡片，翻它能追责「这条 MES 报工是谁批的」。

**不碰 harness 私有 ``_graph.aget_state()``**：跨版本不稳（上界已锁
``octop-harness<2.0.0``，但内部属性不在契约里）。代价是极端情况下可能与 checkpoint
不同步（比如台账写成功、审批没提交）——``/chat/approvals`` 因此只是「卡片来源」，
真正的放行判定权仍在 harness：拿着过期 request_id 续跑会正常走完或报错，不会
绕过审批执行任何工具。

分层：本模块是 domain，只依赖 ``app.storage.db``；由 transport（chat_api）调用。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.storage import db

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_SUPERSEDED = "superseded"

# 决策类型对齐 harness 契约（security/models.py:38 DecisionType），
# 但 nuomi 目前只暴露 approve/reject（tool_guard 通道只认这两个：
# octop_harness/middleware/tool_guard.py:96-119，非 approve 一律回错误 ToolMessage）。
DECISION_TYPES = ("approve", "reject", "edit", "respond")


def _actions_from_request(request: dict) -> list[dict]:
    """把 harness 的 HITLRequest 摊平成 [{name, args, description, allowed_decisions}]。

    ``review_configs`` 是按 ``action_name`` 平行的策略列表（langchain
    human_in_the_loop.py:64-77），这里并到每条动作上，前端才知道该显示哪些按钮
    （比如 ask_user 类工具只允许 ``respond``，给「批准执行」就是骗人）。
    """
    requests = request.get("action_requests") or []
    configs = {
        str(c.get("action_name") or ""): list(c.get("allowed_decisions") or [])
        for c in (request.get("review_configs") or [])
        if isinstance(c, dict)
    }
    out: list[dict] = []
    for item in requests:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        out.append(
            {
                "name": name,
                "args": item.get("args") or {},
                "description": str(item.get("description") or ""),
                "allowed_decisions": configs.get(name) or ["approve", "reject"],
            }
        )
    return out


class ApprovalLedger:
    """approvals 表：一次审批请求一行。"""

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        d["actions"] = json.loads(d.get("actions_json") or "[]")
        d["decisions"] = json.loads(d.get("decisions_json") or "[]")
        d["request"] = json.loads(d.get("raw_json") or "{}")
        return d

    def record_request(
        self,
        *,
        request_id: str,
        thread_id: str,
        agent_id: str,
        request: dict,
        source: str = "console",
    ) -> dict:
        """记下一次待审请求（幂等：同 request_id 重复进来不覆盖已有决策）。"""
        now = int(time.time() * 1000)
        actions = _actions_from_request(request or {})
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO approvals "
                "(request_id, thread_id, agent_id, status, actions_json, raw_json, "
                " decisions_json, source, created_at, resolved_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, '', ?, ?, 0)",
                (
                    request_id,
                    thread_id,
                    agent_id,
                    json.dumps(actions, ensure_ascii=False),
                    json.dumps(request or {}, ensure_ascii=False),
                    source,
                    now,
                ),
            )
        return {
            "request_id": request_id,
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": STATUS_PENDING,
            "actions": actions,
            "decisions": [],
            "created_at": now,
            "resolved_at": None,
            "source": source,
        }

    def get(self, request_id: str) -> dict | None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._row(row) if row else None

    def pending_for_thread(self, thread_id: str) -> dict | None:
        """该会话当前挂着的那条（刷新恢复卡片用）。"""
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE thread_id = ? AND status = 'pending' "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self._row(row) if row else None

    def query(
        self,
        *,
        agent_id: str | None = None,
        status: str | None = None,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """按条件取台账记录（新→旧）。"""
        sql = "SELECT * FROM approvals WHERE 1=1"
        args: list[Any] = []
        if agent_id is not None:
            sql += " AND agent_id = ?"
            args.append(agent_id)
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        if thread_id is not None:
            sql += " AND thread_id = ?"
            args.append(thread_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(limit, 500)))
        with db.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [self._row(r) for r in rows]

    def resolve(
        self,
        request_id: str,
        decisions: list[dict],
        *,
        status: str = STATUS_RESOLVED,
    ) -> bool:
        """写入决策并终结这条记录。返回是否真的更新了一行。

        只更新仍处于 pending 的记录：harness 那边如果因为条数不匹配报错，
        调用方**不该**调这里（卡片要留在原地让人重批）。
        """
        now = int(time.time() * 1000)
        with db.connect() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status = ?, decisions_json = ?, resolved_at = ? "
                "WHERE request_id = ? AND status = 'pending'",
                (status, json.dumps(decisions, ensure_ascii=False), now, request_id),
            )
            return cur.rowcount > 0

    def supersede_pending(self, thread_id: str) -> int:
        """同一会话又发起了新一轮对话 → 旧的待审审批作废。

        不作废的话：用户在审批卡片出来后不管它、直接接着打字，几分钟后刷新页面
        会看到一张"复活"的旧卡片，而那时对话上下文早就不在那次中断上了。
        """
        now = int(time.time() * 1000)
        with db.connect() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status = 'superseded', resolved_at = ? "
                "WHERE thread_id = ? AND status = 'pending'",
                (now, thread_id),
            )
            return cur.rowcount


approval_ledger = ApprovalLedger()


def record_from_event(ev: dict, *, agent_id: str | None, source: str) -> bool:
    """把一帧 ``approval_requested`` 事件写进台账；返回是否落库。

    失败只记日志、不抛：对话比留痕要紧 —— 台账坏了顶多是刷新后卡片找不回来，
    异常抛出去会让整条 SSE 变成 error 帧，用户看到的是「对话挂了」。

    两个 transport 都用它（控制台 chat_api、数字人壳 openai_compat）：壳里跑的
    是同一套 tool_guard，触发的审批同样要能被控制台看到并代批。
    """
    request_id = str(ev.get("request_id") or "")
    thread_id = str(ev.get("thread_id") or "")
    if not request_id or not thread_id or not agent_id:
        logger.warning(
            "审批帧缺字段，跳过台账：request_id=%r thread_id=%r agent_id=%r",
            request_id,
            thread_id,
            agent_id,
        )
        return False
    try:
        approval_ledger.record_request(
            request_id=request_id,
            thread_id=thread_id,
            agent_id=agent_id,
            request=ev.get("request") or {},
            source=source,
        )
    except Exception:
        logger.exception("审批台账写入失败（thread=%s）", thread_id)
        return False
    return True
