# 糯米 Nuomi

**住在你电脑里的 AI 人格**——灵感来自《魔幻手机》：既是数字生命（有形象、有情绪、会变装），又能干活（工具、记忆、技能）。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 大脑（机制层） | [octop-harness](https://pypi.org/project/octop-harness/) | Agent 运行时（LangChain Deep Agents）：循环/工具/记忆/checkpointer/技能/MCP |
| 业务层 | Python + FastAPI | 专家/会话/能力领域服务（自研）；插件三层能力（工具注册 / 事件订阅发布 / 聊天卡片 UI） |
| 形象层（AI 数字人壳） | shells/nuomi-avatar/（基于 nuomi-avatar，MIT） | 纯表现层：three.js + VRM 3D 渲染、情绪表情、流式字幕、工具执行状态；大脑全在 backend（详见 [shells/nuomi-avatar/README.md](shells/nuomi-avatar/README.md)） |
| 存储 | SQLite | agents/threads/thread_messages 投影表（对齐 Octop schema，已建成） |

> **AI 数字人模型版权说明**：VRM 模型资产在工作区 `models/3D/`（本机 `/Users/superman/Nuomi/models/3D/`），不入库。
> 用户自导入模型按各自 License 使用（示例模型 6309260419351179234.vrm 为 CC0）；
> 若需分发项目请使用宽松 License 的模型。动作资产为 Mixamo 导出的 `.vrma` 动画文件（`shells/nuomi-avatar/assets/animations/`）。

## 快速开始

```bash
make start   # 一键启动 AI 数字人壳（Electron 数字人窗口 + 控制面板），后端自动拉起（ensureBackend）
make web     # 调试控制台（vite dev，:5173，代理 /api → :8000）
```

首次使用需配置 LLM：复制 `backend/.env.example` 为 `backend/.env` 设置 `DEEPSEEK_API_KEY`（或任意 OpenAI 兼容 key），
或在控制台「设置 → 大模型」页面配置 Provider（`工作区/providers.json` 为运行时权威）。

- 控制面板：http://127.0.0.1:8000/console/（壳内嵌窗口 / 浏览器访问均可）
- AI 数字人开关：控制台「AI 数字人」页，关闭即销毁数字人窗口（开关联动 vrm-avatar 插件启停）

### 对话（SSE 流式）

```bash
curl -N -X POST http://127.0.0.1:8000/api/agents/{agent_id}/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": "你好", "thread_id": "test"}'
```

事件流：`token`（流式文字）→ `reasoning`（深度思考）→ `tool_call_chunk`/`tool_result`（工具执行，带 `plugin_id`）→ `done`（完整回答）。
插件事件层另发布 `conversation.started / conversation.completed`（供 TTS 播报等订阅）。

### 验证

```bash
cd backend && .venv/bin/python probe_harness.py   # harness 冒烟：DeepSeek 对话 + Octop 插件加载
```

## 架构

```
transport（FastAPI 路由） → domain（领域服务） → infra/harness（适配层） → octop-harness（运行时）
```

领域语言一等公民（专家/会话/能力），机制语言当基础库（harness）。详见 `docs/architecture-refactor-harness.md`。

## 路线图

- [x] R1-R3：推倒重来 + harness 适配层 + SSE 对话 API
- [x] M3-M5：Agent 生命周期 / 会话存储（threads+消息投影表）/ 插件（2026-10-05）
- [x] M6：技能+连接器+知识库（2026-10-04；OCR 用户叫停暂缓）
- [x] M7-M8：AI 数字人形象层（VRM 3D / 模型与动作资产管理 / 热切换）+ 工具执行可视化（2026-10-05）
- [x] 插件三层能力：工具注册 / 事件订阅发布（EventBus）/ 聊天卡片 UI（对齐 octop，2026-10-05）
- [x] 轨迹可观测性：Langfuse 集成（本地自托管，设置页配置，2026-10-05）
- [ ] 待办：专家级默认绑定（skill/知识库/连接器三列）；Langfuse 设置页测试连接 bug

## 许可证

MIT（octop-harness 与 nuomi-avatar 均为开源依赖）
