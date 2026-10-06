"""一轮对话的知识库选择（对齐 Octop：显式指定才注入）。

语义：``knowledge_base_ids`` 显式非 None 时全权使用（含 [] 表示本轮明确
不注入）；None 同样不注入（无「默认打开」自动注入一说，与技能/连接器同
维度：不选就不启用）。选中结果同时写入 ``configurable.knowledge_base_ids``
（工具读取）与 ``knowledge_base_catalog``（中间件改写工具描述）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.infra.knowledge.hint import catalog_for_selected_bases
from app.infra.knowledge.repo import KnowledgeBaseRow


def resolve_knowledge_base_ids(
    explicit_ids: list[str] | None,
) -> list[str]:
    """显式列表全权使用；None（未选）视为不注入。"""
    return list(explicit_ids) if explicit_ids is not None else []


def stamp_turn_knowledge_config(
    request: dict[str, Any],
    *,
    visible_bases: Sequence[KnowledgeBaseRow],
    explicit_ids: list[str] | None,
) -> list[str]:
    """把本轮知识库选择写入 harness 请求的 configurable。"""
    selected_ids = resolve_knowledge_base_ids(explicit_ids)
    configurable = dict(request.get("configurable") or {})
    configurable["knowledge_base_ids"] = selected_ids
    configurable["knowledge_base_catalog"] = catalog_for_selected_bases(visible_bases, selected_ids)
    request["configurable"] = configurable
    return selected_ids
