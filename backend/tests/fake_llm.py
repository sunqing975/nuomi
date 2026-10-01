"""测试用假模型：不联网、不花 API 费用，验证 graph + checkpointer + SSE 全链路。"""
from __future__ import annotations

from typing import Any, AsyncIterator, ClassVar, Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class FakeChatModel(BaseChatModel):
    """把输入原样回显为“糯米(测试)”回复，逐字流式吐出。"""

    reply_prefix: ClassVar[str] = "糯米(测试)："

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def bind_tools(self, tools, **kwargs: Any):
        """create_agent 会对模型做工具绑定；假模型直接接受并返回自身。"""
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, *args: Any, **kwargs: Any
    ) -> ChatResult:
        text = self.reply_prefix + "收到，已记住这条对话。"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, *args: Any, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        text = self._generate(messages).generations[0].text
        for ch in text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))

    async def _astream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        text = self._generate(messages).generations[0].text
        for ch in text:
            yield ChatGenerationChunk(message=AIMessageChunk(content=ch))
