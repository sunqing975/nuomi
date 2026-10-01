---
name: knowledge
description: 语义检索知识库资料（RAG：Chroma + embedding），查项目文档/资料
when_to_use: 用户问的资料属于知识库内容，或"查一下知识库里的 XXX"
---
# knowledge 技能

1. 用户要查知识库内容时，先用 `knowledge_search` 检索（传入关键词，返回最相关片段）
2. 没有命中时：换关键词再试一次；仍没有 → 如实说"知识库里没找到"，不要编造
3. 用户主动提供资料时可用 `knowledge_add` 存入（存标题 + 正文）
4. 返回给用户时：用自己的话概括 + 标注来源片段，保持简短
