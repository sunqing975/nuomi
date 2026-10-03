---
name: mcp-notes
description: 便签管理（本地 MCP server 经 langchain-mcp-adapters 接入）：添加/查询便签
when_to_use: 用户说"记个便签/备忘/待办"或"查我的便签"
---
# mcp-notes 技能

经 MCP 协议连接的本地便签服务，工具：notes_add / notes_search / notes_delete。
1. 添加：notes_add(title, content)——标题简短，内容完整
2. 查询：notes_search(keyword)——列出匹配便签，按时间排序概述
3. 删除：notes_delete(id)——先确认 id 再删，删除不可恢复
4. 这是 MCP 插件的示例：换 MCP server = 换能力，加载器无感
