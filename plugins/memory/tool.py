"""memory 能力型插件：读写长期记忆。

展示"记忆是插件"：换记忆方案（如 Chroma+embedding）= 换这个插件，引擎不动。
工具通过 app.memory.get_store() 操作当前伙伴的 JSON 事实库。
Phase 4a 多用户：工具可收到隐藏的 RunnableConfig（不入模型 schema），
按 configurable.user 隔离每个用户的记忆库。
"""
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.memory import get_store


def _user(config: RunnableConfig | None) -> str | None:
    try:
        return (config.get("configurable") or {}).get("user")
    except Exception:
        return None


@tool
def memory_write(content: str, category: str = "fact", config: RunnableConfig = None) -> str:
    """把一条值得长期记住的用户信息写入记忆库。category 可选：fact（事实）/ preference（偏好）/ event（事件）。重复内容自动合并。"""
    fact = get_store(_user(config)).add(content, category=category)
    return f"已记住：{fact.content}" if fact else "内容为空，未保存"


@tool
def memory_read(query: str, top_k: int = 3, config: RunnableConfig = None) -> str:
    """按关键词检索记忆库，返回相关的长期记忆（可能有 0 条）。回答用户个人问题时先用它。"""
    hits = get_store(_user(config)).search(query, top_k=top_k)
    if not hits:
        return "（记忆库中没有相关内容）"
    lines = [f"- [{f.category}] {f.content}" for f in hits]
    return "\n".join(lines)


TOOLS = [memory_write, memory_read]
