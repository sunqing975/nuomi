---
name: memory-mem0
description: 外部记忆 provider（Mem0）：对话级语义提取 + 向量检索；与内置 service-memory 互斥，profile 一行切换
when_to_use: 记忆后端已切换到 Mem0 时，模糊回想/跨话题联想/语义检索用 memory_read
---
# memory-mem0 技能

记忆服务由内置 file provider 切换到 Mem0 后，本插件生效：

## 与内置的差异
- **写入**：memory_write 走 Mem0 语义提取（从你的话里抽取记忆），可能自动拆成多条
- **查询**：memory_read 走向量语义检索——模糊回想（"上次聊过的那个项目"）比内置子串更准
- **改/删**：memory_replace / memory_remove 语义不变（唯一子串定位）
- **快照注入**：不变（冻结快照 + 容量 header，会话开始一次）

## 配置（设置 → 插件 → memory-mem0）
- mode=openmemory（默认，本地自托管，数据不出本机）/ cloud（Mem0 云，需 api_key）/ local（全本地向量库+LLM 提取）
- LLM 提取配置复用 OpenAI 兼容端点（默认 DeepSeek；留空继承环境变量）

## 注意事项
- 需要先安装依赖：`cd backend && uv pip install mem0ai`（未装时插件显示失败状态）
- 云模式记忆数据存 Mem0 服务端，请确认隐私可接受
