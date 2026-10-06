"""内置知识库检索工具 ``search_knowledge``（抄 Octop ``tools.py``，单用户裁剪）。

工具从运行上下文 ``configurable.knowledge_base_ids`` 读取本轮选中的库；
工具描述由中间件按本轮 attached KB 改写（无选中库时从模型工具列表移除）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import Field

from app.infra.knowledge.retrieve import DEFAULT_RETRIEVAL_K, retrieve_context

SEARCH_KNOWLEDGE_TOOL = "search_knowledge"

_MAX_CATALOG_DESC_CHARS = 240

_SEARCH_DESC_BASE = (
    "在下列知识库中检索与用户问题相关的段落。当用户问题涉及其中任一主题时使用本工具。"
    "把 ``query`` 写成聚焦的检索串（关键词、名称、同义词），不要写成聊天回复。"
    "不得编造引用，只能使用返回的段落。"
)

_SEARCH_DESC_NONE = "本轮没有可用的知识库。"


def _clip_catalog_text(text: str, limit: int = _MAX_CATALOG_DESC_CHARS) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + "..."


def format_search_knowledge_description(
    catalog: Sequence[Mapping[str, str]] | None,
) -> str:
    """构造模型可见的工具描述：附上本轮 attached 的库名/描述。"""
    entries: list[str] = []
    for item in catalog or ():
        name = _clip_catalog_text(str(item.get("name") or item.get("id") or ""), 80)
        if not name:
            continue
        description = _clip_catalog_text(str(item.get("description") or ""))
        if description:
            entries.append(f"- {name}: {description}")
        else:
            entries.append(f"- {name}")
    if not entries:
        return _SEARCH_DESC_NONE
    listed = "\n".join(entries)
    return f"{_SEARCH_DESC_BASE}\n本轮可用:\n{listed}"


def _tool_kb_ids() -> list[str]:
    cfg = get_config().get("configurable") or {}
    raw_ids = cfg.get("knowledge_base_ids")
    ids: list[str] = []
    if isinstance(raw_ids, list):
        ids = [str(item).strip() for item in raw_ids if str(item).strip()]
    return ids


def build_knowledge_tools() -> list[StructuredTool]:
    """返回内置知识库检索工具（经 HarnessAgentConfig.tools 注入）。"""

    async def search_knowledge(
        query: Annotated[
            str,
            Field(
                description=(
                    "针对所选知识库的聚焦检索串：来自用户问题的关键词、名称与同义词。不是聊天回复。"
                ),
            ),
        ],
        k: Annotated[
            int,
            Field(
                description="最多返回的段落数（默认 8）。",
                ge=1,
                le=20,
            ),
        ] = DEFAULT_RETRIEVAL_K,
    ) -> str:
        try:
            kb_ids = _tool_kb_ids()
            if not kb_ids:
                return "本轮没有选中的知识库。"
            context = await retrieve_context(
                query=query,
                knowledge_base_ids=kb_ids,
                k=k,
            )
            if not context:
                return "没有检索到相关段落。"
            return context
        except Exception as exc:
            return f"知识库检索失败: {exc}"

    return [
        StructuredTool.from_function(
            coroutine=search_knowledge,
            name=SEARCH_KNOWLEDGE_TOOL,
            # 静态兜底；每轮由中间件改写或隐藏。
            description=format_search_knowledge_description([]),
        )
    ]
