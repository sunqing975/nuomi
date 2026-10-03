"""memory 能力型插件：读写长期记忆（记忆 v2，对齐 Hermes 工具语义）。

展示"记忆是插件"：换记忆 provider（内置 file / Mem0 等）= 换服务插件，
引擎与工具不动。工具经 app.storage.memory.get_backend() 访问契约层，
不感知底层实现（SQLite / 外部向量库）。
- memory_write   = Hermes add：写入一条（去重自动合并）
- memory_read    = Hermes search：按需补充查询（快照外的细节）
- memory_replace = Hermes replace：唯一子串定位并替换
- memory_remove  = Hermes remove：唯一子串定位并删除
单用户形态（2026-10-02）：不再有 per-user 隔离参数。
"""

from app.storage.memory import get_backend
from langchain_core.tools import tool


@tool
def memory_write(content: str, category: str = "fact") -> str:
    """把一条值得长期记住的用户信息写入记忆库。category 可选：fact（事实）/ preference（偏好，归入用户画像）/ event（事件）。重复内容自动合并。"""
    entry = get_backend().add(content, category=category)
    return f"已记住：{entry.content}" if entry else "内容为空，未保存"


@tool
def memory_read(query: str, top_k: int = 3) -> str:
    """按关键词检索记忆库，返回相关的长期记忆（可能有 0 条）。回答用户个人问题时，先看已注入的记忆快照，不足再用它补充查询。"""
    hits = get_backend().search(query, top_k=top_k)
    if not hits:
        return "（记忆库中没有相关内容）"
    lines = [f"- [{e.category}] {e.content}" for e in hits]
    return "\n".join(lines)


@tool
def memory_replace(old_text: str, content: str) -> str:
    """把一条旧记忆替换为新内容。old_text 是旧记忆里的唯一片段（子串定位）；若匹配到多条，需提供更精确的片段。"""
    code, msg = get_backend().replace(old_text, content)
    return msg


@tool
def memory_remove(old_text: str) -> str:
    """删除一条记忆。old_text 是要删除记忆里的唯一片段（子串定位）；若匹配到多条，需提供更精确的片段。"""
    code, msg = get_backend().remove(old_text)
    return msg


TOOLS = [memory_write, memory_read, memory_replace, memory_remove]
