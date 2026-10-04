"""会话管理：以壳 config.json 为唯一权威，维护「当前 thread_id」与会话列表。

核心语义（一个 thread_id 逻辑）：
- 桌宠壳与控制台读写同一份 config.json（`nuomi.thread_id` = 当前会话，`nuomi.threads` = 会话列表）
- 壳对话带当前 thread_id；控制台切会话 = 写配置 = 壳下一次对话自动跟随
- 两端对话落在同一线程，记忆互通
"""
from __future__ import annotations

import json
import time
import uuid

from app.config import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "shells" / "myspy" / "config.json"


class ChatSessionService:
    """壳 config.json 中 nuomi.* 会话字段的读写封装。"""

    def _read(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, cfg: dict) -> None:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def _nuomi(self, cfg: dict) -> dict:
        return cfg.setdefault("nuomi", {})

    def _threads(self, cfg: dict, agent_id: str) -> list[dict]:
        return self._nuomi(cfg).setdefault("threads", [])

    def state(self, agent_id: str) -> dict:
        """返回某专家的当前会话与会话列表（threads 按 agent 过滤）。

        始终保证「桌宠会话」（default 线程）在列表中——桌宠旧记忆延续。
        """
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        threads = [
            t for t in nuomi.get("threads", [])
            if not t.get("agent_id") or t.get("agent_id") == agent_id
        ]
        current = nuomi.get("thread_id") or "default"
        if not any(t.get("thread_id") == "default" for t in threads):
            threads = [
                {"thread_id": "default", "title": "桌宠会话", "updated_at": 0, "agent_id": agent_id},
                *threads,
            ]
        threads.sort(key=lambda t: t.get("updated_at") or 0, reverse=True)
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
        threads.insert(0, {
            "thread_id": tid,
            "title": title,
            "updated_at": int(time.time() * 1000),
            "agent_id": agent_id,
        })
        nuomi["thread_id"] = tid
        self._write(cfg)
        return {"thread_id": tid, "title": title}

    def switch(self, agent_id: str, thread_id: str) -> bool:
        """切换当前会话（default 恒可切；uuid 会话需在列表中）。"""
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        if thread_id != "default" and not any(
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

    def ensure_model_session(self, agent_id: str, model_id: str) -> str:
        """确保桌宠模型有专属会话并绑定为当前（一个桌宠一个会话）。

        不同桌宠（模型）工具集不同，上下文应互相隔离：
        - 已有该 model_id 的会话 → 绑定最近使用的
        - 没有 → 新建干净会话（不带旧模型记忆）
        default（桌宠会话）保持无归属，仅作旧记忆的独立列表项。
        """
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        threads = nuomi.setdefault("threads", [])
        now = int(time.time() * 1000)
        owned = [t for t in threads if t.get("model_id") == model_id]
        if owned:
            target = max(owned, key=lambda t: t.get("updated_at") or 0)
        else:
            tid = f"{agent_id}:{uuid.uuid4().hex[:12]}"
            target = {
                "thread_id": tid,
                "title": "新会话",
                "updated_at": now,
                "agent_id": agent_id,
                "model_id": model_id,
            }
            threads.insert(0, target)
        target["updated_at"] = now
        nuomi["thread_id"] = target["thread_id"]
        self._write(cfg)
        return target["thread_id"]

    # ---------- 删除 ----------

    def delete(self, agent_id: str, thread_id: str) -> bool:
        """删除会话：config 列表移除 + 检查点历史清除。

        删除当前会话自动切到最近会话（无则 default）。
        default 可删（= 清空桌宠旧记忆，列表重建空「桌宠会话」）。
        """
        cfg = self._read()
        nuomi = self._nuomi(cfg)
        threads = nuomi.get("threads", [])
        existed = thread_id == "default" or any(
            t.get("thread_id") == thread_id and t.get("agent_id") == agent_id
            for t in threads
        )
        if not existed:
            return False
        nuomi["threads"] = [
            t for t in threads
            if not (t.get("thread_id") == thread_id and (thread_id == "default" or t.get("agent_id") == agent_id))
        ]
        if nuomi.get("thread_id") == thread_id:
            remaining = [
                t for t in nuomi["threads"]
                if not t.get("agent_id") or t.get("agent_id") == agent_id
            ]
            nuomi["thread_id"] = (
                max(remaining, key=lambda t: t.get("updated_at") or 0).get("thread_id")
                if remaining else "default"
            )
        self._write(cfg)
        self._delete_checkpoint_history(thread_id)
        return True

    @staticmethod
    def _delete_checkpoint_history(thread_id: str) -> None:
        """清除该线程的 LLM 对话上下文（octop checkpointer 存于 memory.sqlite）。

        只清 checkpoints/writes（thread_id 列直删）；hm_checkpoint_blobs 无
        thread_id 列、删除后成无害孤儿，不强求。历史清除失败不阻断列表删除。
        """
        from app.config import settings

        db_path = settings.workspace_path / "memory.sqlite"
        if not db_path.is_file():
            return
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
