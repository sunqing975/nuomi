"""会话管理：以工作区 nuomi-state.json 为唯一权威，维护「当前 thread_id」与会话列表。

核心语义（一个 thread_id 逻辑）：
- 控制台读写状态文件（`thread_id` = 当前会话，`threads` = 会话列表）
- 会话即真实对话线程；无「default 桌宠会话」、无「模型专属会话」（2026-10-04 起，
  桌宠=纯表现层，拦截对话工具调用播放动作，与会话解耦）
- 切模型不换会话；删空会话后 current 为 None

2026-10-04：会话状态从壳 config.json（nuomi.*）迁出到工作区 nuomi-state.json；
壳 config.json 仅保留表现层偏好（ui.*）。
"""

from __future__ import annotations

import json
import time
import uuid

from app.config import settings

STATE_PATH = settings.workspace_path / "nuomi-state.json"


class ChatSessionService:
    """工作区 nuomi-state.json（顶层即 nuomi.* 字段）的读写封装。"""

    def _read(self) -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, cfg: dict) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _nuomi(self, cfg: dict) -> dict:
        return cfg  # 状态文件顶层即 nuomi.*

    def _threads(self, cfg: dict, agent_id: str) -> list[dict]:
        return self._nuomi(cfg).setdefault("threads", [])

    def state(self, agent_id: str) -> dict:
        """返回某专家的当前会话与会话列表（threads 按 agent 过滤）。

        会话列表即真实会话；无「default 桌宠会话」合成（2026-10-04 起）。
        current 若不在该 agent 列表中（切换过 agent）→ 归位最近会话；无会话为 None。
        """
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        threads = [
            t
            for t in nuomi.get("threads", [])
            if not t.get("agent_id") or t.get("agent_id") == agent_id
        ]
        threads.sort(key=lambda t: t.get("updated_at") or 0, reverse=True)
        current = nuomi.get("thread_id")
        if current and not any(t.get("thread_id") == current for t in threads):
            current = threads[0].get("thread_id") if threads else None
        return {
            "agent_id": agent_id,
            "current": current,
            "sessions": threads,
        }

    def new(self, agent_id: str, title: str = "新会话") -> dict:
        """创建新会话并设为当前（壳「新会话」按钮与控制台共用）。"""
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        tid = f"{agent_id}:{uuid.uuid4().hex[:12]}"
        threads = nuomi.setdefault("threads", [])
        threads.insert(
            0,
            {
                "thread_id": tid,
                "title": title,
                "updated_at": int(time.time() * 1000),
                "agent_id": agent_id,
            },
        )
        nuomi["thread_id"] = tid
        self._write(cfg)
        return {"thread_id": tid, "title": title}

    def switch(self, agent_id: str, thread_id: str) -> bool:
        """切换当前会话（需在列表中）。"""
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        if not any(
            t.get("thread_id") == thread_id and t.get("agent_id") == agent_id
            for t in nuomi.get("threads", [])
        ):
            return False
        nuomi["thread_id"] = thread_id
        # 切换即更新该会话时间（反映最近使用）
        for t in nuomi.get("threads", []):
            if t.get("thread_id") == thread_id and t.get("agent_id") == agent_id:
                t["updated_at"] = int(time.time() * 1000)
        self._write(cfg)
        return True

    def touch(self, agent_id: str, thread_id: str, title: str | None = None) -> None:
        """更新会话时间/标题（标题仅在仍为「新会话」时替换）。"""
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        for t in nuomi.get("threads", []):
            if t.get("thread_id") == thread_id and t.get("agent_id") == agent_id:
                t["updated_at"] = int(time.time() * 1000)
                if title and t.get("title") in (None, "", "新会话"):
                    t["title"] = title
        self._write(cfg)

    def delete(self, agent_id: str, thread_id: str) -> bool:
        """删除会话：状态文件列表移除 + 检查点历史清除。

        删除当前会话自动切到最近会话（无则 None）。
        """
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        threads = nuomi.get("threads", [])
        existed = any(
            t.get("thread_id") == thread_id and t.get("agent_id") == agent_id for t in threads
        )
        if not existed:
            return False
        nuomi["threads"] = [
            t
            for t in threads
            if not (t.get("thread_id") == thread_id and t.get("agent_id") == agent_id)
        ]
        if nuomi.get("thread_id") == thread_id:
            remaining = [
                t
                for t in nuomi["threads"]
                if not t.get("agent_id") or t.get("agent_id") == agent_id
            ]
            nuomi["thread_id"] = (
                max(remaining, key=lambda t: t.get("updated_at") or 0).get("thread_id")
                if remaining
                else None
            )
        self._write(cfg)
        self._delete_checkpoint_history(thread_id, agent_id)
        return True

    @staticmethod
    def _delete_checkpoint_history(thread_id: str, agent_id: str | None = None) -> None:
        """清除该线程的 LLM 对话上下文（octop checkpointer 存于专家 workspace 的 memory.sqlite）。

        同时清理专家工作区与全局根的 memory.sqlite（兼容迁移期）。只清
        checkpoints/writes（thread_id 列直删）；hm_checkpoint_blobs 无
        thread_id 列、删除后成无害孤儿，不强求。历史清除失败不阻断列表删除。
        """
        from app.config import settings

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
                            conn.execute(
                                f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,)
                            )
            except Exception:
                pass


chat_sessions = ChatSessionService()
