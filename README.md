# 糯米 Nuomi

**住在你电脑里的 AI 人格**——灵感来自《魔幻手机》：既是数字生命（有形象、有情绪、会变装），又能干活（工具、记忆、技能）。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 大脑（机制层） | [octop-harness](https://pypi.org/project/octop-harness/) | Agent 运行时（LangChain Deep Agents）：循环/工具/记忆/checkpointer/技能/MCP |
| 业务层 | Python + FastAPI | 专家/会话/能力领域服务（自研） |
| 形象层（AI 数字人壳） | shells/nuomi-avatar/（基于 nuomi-avatar，MIT） | 纯表现层：Live2D 渲染、情绪表情、流式字幕、输入；大脑全在 backend（详见 [shells/nuomi-avatar/README.md](shells/nuomi-avatar/README.md)） |
| 存储 | SQLite | agents/threads/messages（对齐 Octop schema，规划中） |

> **AI 数字人模型版权说明**：模型资产在工作区 `models/2D/<id>/`（本机 `/Users/superman/Nuomi/models/2D/`），
> 不入库。仓库仅保留可分发种子 `assets/models/2D/hiyori/`（首启/扫描时幂等播种到工作区）。
> aidang 来自游戏《碧蓝航线》提取的 Live2D 资产（来源 [Eikanya/Live2d-model](https://github.com/Eikanya/Live2d-model)，
> Cubism 3，14 个动作），**仅限个人自用，不可商用、不可再分发**；
> 若需分发项目请替换为官方宽松 License 的模型（如 Live2D 官方示例）。

## 快速开始（当前为后端最小对话）

```bash
cd backend
cp ../.env.example .env   # 配置 LLM（DeepSeek / 豆包 / 任意 OpenAI 兼容）
uv sync
uv run uvicorn app.main:app --port 8000
```

### 对话（SSE 流式）

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": "你好", "thread_id": "test"}'
```

事件流：`token`（流式文字）→ `tool_call`/`tool_result`（工具执行）→ `usage` → `done`（完整回答）。

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
- [ ] M3-M6：Agent 生命周期 / 会话存储 / 插件 / 技能+连接器+知识库
- [ ] M7-M8：AI 数字人形象层（nuomi-avatar）+ 人格/情绪体验

## 许可证

MIT（octop-harness 与 nuomi-avatar 均为开源依赖）
