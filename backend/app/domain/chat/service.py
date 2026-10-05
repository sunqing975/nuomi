"""会话管理（M4）：会话列表落 SQLite threads 表，消息历史投影 thread_messages 表。

对齐 Octop 语义：
- threads 表 = 会话业务对象（标题/置顶/会话级模型），消息权威仍在 octop checkpointer
  （memory.sqlite）；thread_messages 表是「历史投影」——对话后 append 本轮消息、
  首次读取历史时从 checkpointer 全量 backfill（对齐 Octop dashboard 的
  thread_history_projection 机制）。
- 工作区 nuomi-state.json 只保留 current thread_id 单一字段（2026-10-05 起
  threads 列表迁入 DB；迁移幂等，成功后立即清理旧字段）。

对外 API 与旧版一致（state/new/switch/touch/delete），前端零改动。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.config import settings
from app.storage import db

STATE_PATH = settings.workspace_path / "nuomi-state.json"

# —— threads 表（ThreadRepo） ——


class ThreadRepo:
    """threads 表：会话元数据（thread_id/agent_id/title/last_active/pinned/model_ref）。"""

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        d["updated_at"] = d.pop("last_active", 0)  # 对外沿用旧字段名（毫秒时间戳）
        return d

    def insert(
        self,
        thread_id: str,
        agent_id: str,
        *,
        title: str = "",
        last_active: int | None = None,
        model_ref: str = "",
    ) -> None:
        now = int(time.time() * 1000)
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO threads "
                "(thread_id, agent_id, title, last_active, created_at, pinned, model_ref) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (
                    thread_id,
                    agent_id,
                    title,
                    now if last_active is None else last_active,
                    now,
                    model_ref,
                ),
            )

    def get(self, thread_id: str) -> dict | None:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return self._row(row) if row else None

    def list_by_agent(self, agent_id: str) -> list[dict]:
        """按专家列会话：置顶优先，再按活跃时间倒序（last_active=0 用 created_at 兜底）。"""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE agent_id = ? "
                "ORDER BY pinned DESC, "
                "CASE WHEN last_active > 0 THEN last_active ELSE created_at END DESC, "
                "thread_id DESC",
                (agent_id,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def update_title(self, thread_id: str, title: str) -> None:
        with db.connect() as conn:
            conn.execute("UPDATE threads SET title = ? WHERE thread_id = ?", (title, thread_id))

    def touch_last_active(self, thread_id: str) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE threads SET last_active = ? WHERE thread_id = ?",
                (int(time.time() * 1000), thread_id),
            )

    def set_pinned(self, thread_id: str, pinned: bool) -> None:
        with db.connect() as conn:
            conn.execute(
                "UPDATE threads SET pinned = ? WHERE thread_id = ?", (1 if pinned else 0, thread_id)
            )

    def delete(self, thread_id: str) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))


# —— thread_messages 投影（ThreadMessageRepo，对齐 Octop 简化版） ——

# 投影状态：pending=未 backfill（历史读 checkpointer）/ ready=已就绪（读表）
PROJ_PENDING = "pending"
PROJ_READY = "ready"


class ThreadMessageRepo:
    """thread_messages 投影表：role + message_json（langchain wire 格式）。"""

    @staticmethod
    def _row(row) -> dict:
        return dict(row)

    def head(self, thread_id: str) -> int:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM thread_messages WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return int(row[0])

    def append(self, thread_id: str, inputs: list[dict]) -> int:
        """追加本轮消息投影（message_id 去重；无 message_id 时全部追加）。"""
        if not inputs:
            return 0
        inserted = 0
        with db.connect() as conn:
            seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM thread_messages WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()[0]
            )
            for m in inputs:
                mid = m.get("message_id") or ""
                if mid:
                    dup = conn.execute(
                        "SELECT 1 FROM thread_messages WHERE thread_id = ? AND message_id = ?",
                        (thread_id, mid),
                    ).fetchone()
                    if dup is not None:
                        continue
                seq += 1
                conn.execute(
                    "INSERT INTO thread_messages "
                    "(thread_id, seq, message_id, role, message_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (thread_id, seq, mid, m["role"], m["message_json"], m.get("created_at") or 0),
                )
                inserted += 1
        return inserted

    def replace_all(self, thread_id: str, inputs: list[dict]) -> int:
        """全量 backfill（覆盖旧投影）。"""
        with db.connect() as conn:
            conn.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
            seq = 0
            for m in inputs:
                seq += 1
                conn.execute(
                    "INSERT INTO thread_messages "
                    "(thread_id, seq, message_id, role, message_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        seq,
                        m.get("message_id") or "",
                        m["role"],
                        m["message_json"],
                        m.get("created_at") or 0,
                    ),
                )
        return seq

    def page(self, thread_id: str, *, limit: int, offset: int = 0) -> tuple[list[dict], bool]:
        """倒序分页（seq 从新到旧），返回 (rows 正序, has_more)。"""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, message_id, role, message_json, created_at "
                "FROM thread_messages WHERE thread_id = ? "
                "ORDER BY seq DESC LIMIT ? OFFSET ?",
                (thread_id, limit + 1, max(0, offset)),
            ).fetchall()
        has_more = len(rows) > limit
        out = [self._row(r) for r in rows[:limit]]
        out.reverse()
        return out, has_more

    def delete_all(self, thread_id: str) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))

    # —— 投影状态（thread_history_projection） ——

    def projection_status(self, thread_id: str) -> str:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM thread_history_projection WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return str(row["status"]) if row else PROJ_PENDING

    def mark_projection(self, thread_id: str, status: str, *, error: str = "") -> None:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO thread_history_projection(thread_id, status, updated_at, error) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(thread_id) DO UPDATE SET "
                "status = excluded.status, updated_at = excluded.updated_at, error = excluded.error",
                (thread_id, status, int(time.time() * 1000), error),
            )

    def delete_projection(self, thread_id: str) -> None:
        with db.connect() as conn:
            conn.execute("DELETE FROM thread_history_projection WHERE thread_id = ?", (thread_id,))


thread_repo = ThreadRepo()
thread_message_repo = ThreadMessageRepo()


def turn_to_message_inputs(turn: dict) -> list[dict]:
    """把一轮对话（stream_chat on_turn_complete 的 turn dict）序列化为投影输入。

    对齐 Octop projection：role + message_json（langchain wire 格式，message_to_dict）。
    turn 结构：{user, answer, reasoning, tool_calls: [{id,name,args}], tool_results: [{name,content}]}。
    未产生任何内容时返回 []（不写空投影）。
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, message_to_dict

    inputs: list[dict] = []

    def _push(message) -> None:
        wire = message_to_dict(message)
        inputs.append(
            {
                "message_id": getattr(message, "id", None) or "",
                "role": wire.get("type") or getattr(message, "type", ""),
                "message_json": json.dumps(wire, ensure_ascii=False, default=str),
                "created_at": int(time.time() * 1000),
            }
        )

    user_text = str(turn.get("user") or "").strip()
    if user_text:
        _push(HumanMessage(content=user_text))

    answer = str(turn.get("answer") or "").strip()
    reasoning = str(turn.get("reasoning") or "").strip()
    tool_calls = turn.get("tool_calls") or []
    if answer or reasoning or tool_calls:
        kwargs: dict = {}
        if reasoning:
            kwargs["reasoning_content"] = reasoning
        _push(AIMessage(content=answer, additional_kwargs=kwargs, tool_calls=tool_calls))

    for tr in turn.get("tool_results") or []:
        name = tr.get("name") or ""
        content = tr.get("content") or ""
        if not content:
            continue
        try:
            _push(ToolMessage(content=content, name=name, tool_call_id=""))
        except TypeError:
            # 老版本 langchain 的 ToolMessage 不收 tool_call_id
            _push(ToolMessage(content=content, name=name))
    return inputs


def messages_to_inputs(messages: list) -> list[dict]:
    """把 BaseMessage 列表序列化为投影输入（对齐 Octop message_input：跳过 system/空 role）。"""
    from langchain_core.messages import message_to_dict

    inputs: list[dict] = []
    for m in messages:
        mtype = getattr(m, "type", "")
        if mtype in ("", "system"):
            continue
        try:
            wire = message_to_dict(m)
        except Exception:
            continue
        inputs.append(
            {
                "message_id": getattr(m, "id", None) or "",
                "role": wire.get("type") or mtype,
                "message_json": json.dumps(wire, ensure_ascii=False, default=str),
                "created_at": int(time.time() * 1000),
            }
        )
    return inputs


def _migrate_state_threads() -> None:
    """nuomi-state.json 旧 threads 列表 → SQLite threads 表（幂等）。

    迁移成功（全部落库）后立即把 state 文件的 threads 字段清理掉，
    只保留 current thread_id——状态文件即用即清（2026-10-04 起强制）。
    """
    try:
        cfg = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    old_threads = cfg.get("threads")
    if not isinstance(old_threads, list) or not old_threads:
        return
    migrated = 0
    for t in old_threads:
        if not isinstance(t, dict) or not t.get("thread_id"):
            continue
        agent_id = t.get("agent_id") or ""
        thread_repo.insert(
            t["thread_id"],
            agent_id,
            title=t.get("title") or "",
            last_active=int(t.get("updated_at") or 0) or None,
        )
        migrated += 1
    if migrated == len(old_threads):
        cfg.pop("threads", None)
        cfg.pop("enabled", None)  # 死字段（无代码读写，即用即清）
        STATE_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class ChatSessionService:
    """会话列表权威 = SQLite threads 表；current thread_id 存 nuomi-state.json 单字段。"""

    def _read_current(self) -> str | None:
        try:
            cfg = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
        return cfg.get("thread_id")

    def _write_current(self, thread_id: str | None) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cfg: dict[str, Any] = {}
        try:
            cfg = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        cfg.pop("threads", None)  # 旧字段残留防御（正常迁移后已无）
        cfg.pop("enabled", None)  # 死字段清理（即用即清）
        cfg["thread_id"] = thread_id
        STATE_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def state(self, agent_id: str) -> dict:
        """某专家的当前会话与会话列表（threads 按 agent 过滤，活跃倒序）。

        current 若不在该 agent 列表中（切换过 agent）→ 归位最近会话；无会话为 None。
        """
        _migrate_state_threads()
        threads = thread_repo.list_by_agent(agent_id)
        current = self._read_current()
        if current and not any(t.get("thread_id") == current for t in threads):
            current = threads[0].get("thread_id") if threads else None
        return {
            "agent_id": agent_id,
            "current": current,
            "sessions": [
                {
                    "thread_id": t["thread_id"],
                    "title": t.get("title") or "",
                    "updated_at": t.get("updated_at") or 0,
                    "agent_id": t.get("agent_id") or "",
                    "pinned": bool(t.get("pinned")),
                    "model_ref": t.get("model_ref") or "",
                }
                for t in threads
            ],
        }

    def new(self, agent_id: str, title: str = "新会话") -> dict:
        """创建新会话并设为当前（壳「新会话」按钮与控制台共用）。"""
        tid = f"{agent_id}:{uuid.uuid4().hex[:12]}"
        thread_repo.insert(tid, agent_id, title=title)
        self._write_current(tid)
        return {"thread_id": tid, "title": title}

    def switch(self, agent_id: str, thread_id: str) -> bool:
        """切换当前会话（需在该专家列表中）。"""
        t = thread_repo.get(thread_id)
        if t is None or t.get("agent_id") != agent_id:
            return False
        self._write_current(thread_id)
        thread_repo.touch_last_active(thread_id)  # 切换即更新最近使用
        return True

    def touch(self, agent_id: str, thread_id: str, title: str | None = None) -> None:
        """更新会话时间/标题（标题仅在仍为「新会话」时替换）。"""
        t = thread_repo.get(thread_id)
        if t is None or t.get("agent_id") != agent_id:
            return
        thread_repo.touch_last_active(thread_id)
        if title and t.get("title") in (None, "", "新会话"):
            thread_repo.update_title(thread_id, title)

    def delete(self, agent_id: str, thread_id: str) -> bool:
        """删除会话：threads 行 + 消息投影 + 检查点历史全部清除。

        删除当前会话自动切到最近会话（无则 None）。
        """
        t = thread_repo.get(thread_id)
        if t is None or t.get("agent_id") != agent_id:
            return False
        thread_repo.delete(thread_id)
        thread_message_repo.delete_all(thread_id)
        thread_message_repo.delete_projection(thread_id)
        if self._read_current() == thread_id:
            remaining = thread_repo.list_by_agent(agent_id)
            self._write_current(remaining[0].get("thread_id") if remaining else None)
        self._delete_checkpoint_history(thread_id, agent_id)
        return True

    @staticmethod
    def _delete_checkpoint_history(thread_id: str, agent_id: str | None = None) -> None:
        """清除该线程的 LLM 对话上下文（octop checkpointer 存于专家 workspace 的 memory.sqlite）。

        同时清理专家工作区与全局根的 memory.sqlite（兼容迁移期）。只清
        checkpoints/writes（thread_id 列直删）；hm_checkpoint_blobs 无
        thread_id 列、删除后成无害孤儿，不强求。历史清除失败不阻断列表删除。
        """
        db_paths = [settings.workspace_path / "memory.sqlite"]
        if agent_id:
            from app.domain.agents.service import agent_workspace_dir

            db_paths.insert(0, agent_workspace_dir(agent_id) / "memory.sqlite")
        for db_path in db_paths:
            if not db_path.is_file():
                continue
            try:
                import sqlite3

                with sqlite3.connect(db_path) as conn:
                    for table in ("checkpoints", "writes"):
                        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                        if "thread_id" in cols:
                            conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
            except Exception:
                pass


chat_sessions = ChatSessionService()
