# AI 数字人对话协议 v3（octop 原生事件帧）

AI 数字人（表现层）与 nuomi 后端（octop 大脑）之间的对话协议。
**`/chat` 端点输出 octop 原生事件帧**（对齐 octop dashboard WS 协议，SSE 承载），
消费者解析逻辑与未来切换 WebSocket 通道时完全一致（v3，2026-10-04）。

## 端点

| 端点 | 请求 | 说明 |
|---|---|---|
| `POST /api/agents/{agent_id}/chat` | `{"messages": "用户输入", "thread_id": "会话线程 ID"}` | 原生端点，按 `thread_id` 隔离记忆，**输出 octop 事件帧** |
| `POST /api/v1/chat/completions` | 标准 OpenAI 请求体（`model` 支持 `agent:<id>`） | OpenAI 兼容端点（外部客户端用），输出 OpenAI SSE |

## /chat 流式格式（octop 事件帧）

每个 `data:` 负载就是一个 octop 帧（JSON，`data: <json>\n\n`），done 帧后流关闭（无 `[DONE]`）：

```
data: {"type":"token","content":"你","node":"model","thread_id":"<会话ID>"}
data: {"type":"tool_call_chunk","id":"call_...","name":"TapBody","args":"{}","index":0,"node":"model","thread_id":"<会话ID>"}
data: {"type":"tool_result","node":"tools","messages":[{"type":"tool","name":"TapBody","content":"..."}],"thread_id":"<会话ID>"}
data: {"type":"usage","usage":{"input_tokens":25813,"output_tokens":15},"node":"model","thread_id":"<会话ID>"}
data: {"type":"done","conversation_mode":"craft","thread_id":"<会话ID>"}
```

| 帧 | 字段 | 说明 |
|---|---|---|
| `token` | `content` | 流式文本块（字幕逐字显示） |
| `tool_call_chunk` | `id/name/args/index` | 工具调用（工具名即动作/表情名，模型插件） |
| `tool_result` | `messages[{type,name,content}]` | 工具执行结果（壳一般不消费） |
| `usage` | `usage{input_tokens,output_tokens}` | 本轮 token 用量 |
| `done` | `conversation_mode,thread_id` | 结束帧（后关闭流） |

## 表情/动作驱动

表情/动作**统一由模型插件工具驱动**：专家绑定AI 数字人模型插件（aidang/cat/hiyori）后，
LLM 通过工具调用（工具名 = 动作/表情名）驱动AI 数字人。壳从 `tool_call_chunk.name`
直接播放动作/表情，无需等工具执行结果。不再有独立的 `emotion` 事件。

## 消费者

- 壳 `callNuomiSSE`（shells/nuomi-avatar/app.js）：`token`→字幕、`tool_call_chunk`→`playPetToolByName`、`done`→结束
- 控制台 `chatStream`（frontend/src/api.ts）：`token`/`tool_call_chunk`/`done` → ChatEvent

## 历史

- v1（2026-10-03）：自造事件流（token/emotion/tool_call/tool_result/usage/done），已废弃
- v1.1：移除 `emotion` 事件与情绪标签规则
- v2（2026-10-03）：OpenAI Chat Completions SSE（/chat 与 /v1 统一），已废弃（/v1 保留）
- v3（2026-10-04）：/chat 对齐 octop 原生事件帧；/v1 保留 OpenAI 兼容
