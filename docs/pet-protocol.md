# 桌宠协议 v1（Pet Protocol）

桌宠（表现层）与 nuomi 后端（octop 大脑）之间的对话协议。

## 端点

```
POST /api/agents/{agent_id}/chat
body: { "messages": "用户输入", "thread_id": "会话线程 ID" }
→ SSE 事件流（text/event-stream，data: JSON）
```

- OpenAI 兼容端点 `POST /api/v1/chat/completions`（桌宠零改动接入）只转发 token/done；
  原生事件流端点是桌宠消费的完整协议。

## 事件

| type | 字段 | 含义 | 桌宠表现 |
|---|---|---|---|
| `token` | `content` | 流式文本块 | 字幕逐字显示 |
| `emotion` | `name` | 情绪（开心/生气/难过/惊讶/害羞/俏皮） | 驱动 Live2D 表情 |
| `tool_call` | `name`, `args` | 专家开始调用工具 | "正在{name}…"干活可视化 |
| `tool_result` | `name`, `content` | 工具执行结果 | 干活完成反馈 |
| `usage` | `input_tokens`, `output_tokens` | 本轮 token 用量 | 可选展示 |
| `done` | `answer` | 完整回复 | 结束 |

示例：

```json
{"type": "token", "content": "你"}
{"type": "emotion", "name": "开心"}
{"type": "tool_call", "name": "weather_query", "args": "{\"city\": \"嘉兴\"}"}
{"type": "tool_result", "name": "weather_query", "content": "晴 24°C"}
{"type": "usage", "input_tokens": 9739, "output_tokens": 16}
{"type": "done", "answer": "<开心>今天嘉兴是晴天哦。"}
```

## 情绪标签规范（PET_MOOD_RULE）

后端在专家 system_prompt 末尾追加情绪标签规则，强制回复带标签，再由协议层解析为
结构化 `emotion` 事件（实现：`app/infra/harness/chat.py`）。

- 标签：`<开心>` `<生气>` `<难过>` `<惊讶>` `<害羞>` `<俏皮>`
- 解析：取回复中第一个标签（`extract_emotion`），在 `done` 前发 `emotion` 事件
- 两个对话端点（原生 / OpenAI 兼容）共用 `PET_MOOD_RULE`，行为一致

## 壳侧消费（改造目标，P2 表现层阶段）

桌宠壳订阅 SSE，按事件类型驱动表现：

1. `token` → 字幕追加
2. `emotion` → 表情切换（不再自己解析文本标签）
3. `tool_call` → 显示"正在干活"（如"糯米正在查天气…"）
4. `tool_result` → 干活完成提示
5. `done` → 关闭干活指示，字幕完成

## 工具调用触发条件

`tool_call`/`tool_result` 事件由 octop-harness 运行时在专家**配置了工具/技能**时产生。
当前默认专家未绑定外部工具，故对话流中只有 token/emotion/usage/done；
绑定工具（能力域：专家 ↔ 插件/技能/MCP）后事件自然出现。

## 协议演进

- v1：事件流定型（2026-10-03，B-P2）
- 待定：`action` 事件（桌宠动作动画）、`audio` 事件（TTS 段落）、`thinking` 事件（思考展示）
