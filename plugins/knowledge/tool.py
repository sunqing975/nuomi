"""知识库插件（type=knowledge）· RAG 语义检索。

工具层只面对 KnowledgeStore 接口（app.knowledge）；具体实现（Chroma+fastembed /
词法兜底）由 lifespan 按配置注入——"换 RAG 方案 = 换插件/配置"。
"""
from __future__ import annotations

from langchain_core.tools import tool

from app.storage.knowledge import get_store


@tool
def knowledge_add(content: str, category: str = "fact") -> str:
    """把一段资料、文章或知识点存入长期知识库（RAG），之后可用 knowledge_search 语义检索。"""
    content = content.strip()
    if not content:
        return "内容为空，未保存。"
    get_store().add(content, category)
    return f"已存入知识库（{category}）：{content[:60]}{'…' if len(content) > 60 else ''}"


@tool
def knowledge_search(query: str, top_k: int = 3) -> str:
    """在长期知识库中按语义检索与 query 最相关的资料（top_k 条，默认 3）。"""
    hits = get_store().search(query, top_k=min(top_k, 8))
    if not hits:
        return "知识库中没有找到相关内容。"
    return "\n".join(
        f"[{h['category']}]({h['score']:.2f}) {h['content']}" for h in hits
    )


TOOLS = [knowledge_add, knowledge_search]
