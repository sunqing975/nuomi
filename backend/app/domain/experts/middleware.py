"""NuomiMiddleware · 冻结快照注入 + 长对话自动摘要。

LangChain create_agent 的 middleware，用 `awrap_model_call` 钩子直接构造
发给模型的请求（不改 checkpointer 状态），承担两件事：

1. **冻结快照注入（记忆 v2，对齐 Hermes）**：每个 thread 首次构造模型输入时，
   从记忆后端取一次快照（含容量 header）拼入 system prompt 并缓存；会话内不变
   （保 LLM 前缀缓存、省每轮检索）。写操作即时落盘、下个会话才反映。
   记忆后端是 MemoryBackend 契约（内置 FileMemoryBackend / 外部 provider 插件）。
2. **上下文压缩**：历史消息超阈值时，把较早的消息用 LLM 压成一段摘要，
   只保留最近 keep_recent 条原文——模型输入 token 有界（长对话不爆 token）。

设计说明：
- 为什么不用 before_model 返回 state 更新：其 messages 更新被 add_messages
  语义合并（按 id 去重），旧消息删不掉，模型输入并未真正压缩（实测 21 条）。
  wrap_model_call 直接替换 request.messages，压缩对模型输入真实生效。
- 摘要缓存：内存 dict 按 thread_id 增量累计（covered 计数），避免每轮重复
  摘要已覆盖内容；进程重启后首次超阈值会重新摘要，可接受。
- 快照缓存：内存 dict 按 thread_id；middleware 重建（换模型/插件启停）即失效。
- 自有 system 提示以 PROMPT_MARK 标记；记忆快照以 MEMORY_MARK 标记；
  摘要以 SUMMARY_MARK 标记。
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from ...storage.memory import MemoryBackend

PROMPT_MARK = "【糯米系统提示】"
MEMORY_MARK = "【记忆快照】"
SUMMARY_MARK = "【历史摘要】"


def _render_snapshot(snapshot: dict) -> str:
    """Hermes 式快照文本：分段 header（容量百分比）+ § 分隔条目。"""
    parts = [MEMORY_MARK]
    for s in snapshot.get("sections", []):
        entries = s.get("entries") or []
        if not entries:
            continue
        limit = s.get("char_limit") or 1
        pct = round(s.get("total_chars", 0) / limit * 100)
        label = "我的笔记" if s.get("name") == "MEMORY" else "用户画像"
        header = f"{s['name']}（{label}）[{pct}% — {s.get('total_chars', 0):,}/{limit:,} 字符]"
        lines = [header]
        for e in entries:
            content = e.content if hasattr(e, "content") else e.get("content", "")
            lines.append(f"§ {content}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


class NuomiMiddleware(AgentMiddleware):
    def __init__(
        self,
        prompt_builder,  # (last_user_msg: str) -> str
        memory: MemoryBackend | None,
        llm: BaseChatModel,
        max_messages: int = 24,
        keep_recent: int = 8,
    ):
        super().__init__()
        self.prompt_builder = prompt_builder
        self.memory = memory
        self.llm = llm
        self.max_messages = max_messages
        self.keep_recent = keep_recent
        self._summaries: dict[str, dict] = {}  # thread_key -> {"summary": str, "covered": int}
        self._snapshots: dict[str, str] = {}  # thread_key -> 冻结快照文本（会话内不变）

    # ---------- 工具 ----------

    @staticmethod
    def _thread_key(request) -> str:
        try:
            cfg = getattr(request.runtime, "config", None) or {}
            tid = (cfg.get("configurable") or {}).get("thread_id")
            if tid:
                return str(tid)
        except Exception:
            pass
        return str(request.messages[0].id) if request.messages else "none"

    @staticmethod
    def _last_human(messages: list[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return str(m.content)
        return ""

    async def _summarize(self, delta_msgs: list[BaseMessage], existing: str) -> str:
        prompt = (
            "请把以下对话历史压缩成一份简洁的中文要点摘要。"
            "必须保留：用户说过的重要个人信息、偏好、习惯、约定、任务进展与结论。"
            "不要编造没有出现过的信息。输出纯摘要文本。\n\n"
        )
        if existing:
            prompt += f"已有摘要：\n{existing}\n\n"
        for m in delta_msgs:
            role = {HumanMessage: "用户", AIMessage: "糯米", ToolMessage: "工具结果"}.get(
                type(m), "其他"
            )
            prompt += f"{role}：{m.content}\n"
        res = await self.llm.ainvoke(prompt)
        return str(res.content).strip()

    # ---------- 冻结快照（Hermes 式） ----------

    def _memory_block(self, key: str) -> str:
        """该 thread 的记忆快照块：首次生成并缓存，会话内不变。"""
        if self.memory is None:
            return ""
        if key not in self._snapshots:
            try:
                self._snapshots[key] = _render_snapshot(self.memory.snapshot())
            except Exception:
                # provider 失败（如外部服务不可用）：降级为无快照，不阻断对话
                self._snapshots[key] = ""
        return self._snapshots[key]

    # ---------- 主钩子：直接构造模型输入 ----------

    async def awrap_model_call(self, request, handler):
        msgs = list(request.messages)
        last_human = self._last_human(msgs)
        prompt = self.prompt_builder(last_human)
        key = self._thread_key(request)
        memory_block = self._memory_block(key)
        hist = [m for m in msgs if isinstance(m, (HumanMessage, AIMessage, ToolMessage))]

        def sys_message(summary: str | None = None) -> SystemMessage:
            text = f"{PROMPT_MARK}\n{prompt}"
            if memory_block:
                text += f"\n\n{memory_block}"
            if summary:
                text += f"\n\n{SUMMARY_MARK}{summary}"
            return SystemMessage(content=text)

        out_msgs: list[BaseMessage] = msgs
        if len(hist) > self.max_messages and len(hist) - self.keep_recent >= 1:
            old, recent = hist[: len(hist) - self.keep_recent], hist[len(hist) - self.keep_recent :]
            cache = self._summaries.get(key, {"summary": "", "covered": 0})
            delta = old[cache["covered"] :]
            if delta:
                try:
                    summary = await self._summarize(delta, cache["summary"])
                    self._summaries[key] = {"summary": summary, "covered": len(old)}
                except Exception:
                    # 摘要失败：保留全部历史，不阻断对话
                    req = request.override(
                        messages=msgs,
                        system_message=sys_message(),
                    )
                    return await handler(req)
            else:
                summary = cache["summary"]
            out_msgs = [SystemMessage(content=f"{SUMMARY_MARK}{summary}")] + recent

        req = request.override(
            messages=out_msgs,
            system_message=sys_message(),
        )
        return await handler(req)
