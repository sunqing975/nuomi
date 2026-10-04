# 糯米 · 项目记忆（AGENT.md）

> 按用户记忆策略：本文件记录本项目全部细节与决策；系统记忆只记跨项目共性。

## 项目定位（2026-10-03 v0.13 推倒重来）

**桌面 AI 人格工作台**——灵感来自《魔幻手机》的"傻妞"：既是数字生命（有形象、有情绪、会变装），又能干活（工具/记忆/技能）。不是"个人助理"，是"住在你电脑里的 AI 人格"。

技术路线：**octop-harness（机制基础库）+ 业务层自研 + 桌宠开源项目（形象层）**。

- 机制层：`octop-harness`（PyPI 1.0.0，Octop 的 Agent 运行时，LangChain Deep Agents）——Agent 循环/工具/记忆/checkpointer/技能/MCP 全部白拿，**不再自研 engine**（旧 composer/fiber/loader 四层已删除）。
- 业务层：nuomi 自己写——专家/会话/能力领域服务，向 Octop 领域设计靠拢（领域语言一等公民，机制语言当基础库）。
- 形象层：**myspy**（github.com/sitwrrr/myspy，MIT）二次开发——Electron 桌宠壳 + Live2D/VRM 渲染 + 情绪标签驱动表情 + 流式字幕/TTS。备选：live2d-to-agent（MCP 控制桌宠）、OpenPets。

## 已确定的关键决策（v0.13）

- **推倒重来**：删除旧 backend/app（自研 engine 四层）、旧 frontend/（antd 界面）、Tauri 壳、sidecar、部署文件；git 历史保留（`87baddf` 起新基线）。
- **不背历史数据**：新库起步，不写迁移脚本，旧会话/旧结构数据直接放弃。
- **页面不抄 Octop**：保留 nuomi 自己的设计，桌宠主界面 = 角色（卡通人物），不是聊天列表。
- **分层依赖**：`transport → domain → infra/harness → octop-harness`；infra 禁 import domain/transport。
- **仓库结构**：`backend/`（Python+FastAPI+harness）、`desktop/`（未来 myspy 二次开发）、`docs/`、`experts/`、`skills/`、`plugins/`（资产保留，后续迁移 harness 格式）。
- **LLM**：默认 DeepSeek（`LLM_API_KEY` > `DEEPSEEK_API_KEY` > `ARK_API_KEY`，base_url https://api.deepseek.com，model deepseek-chat）。本机真实 key 在环境变量 `DEEPSEEK_API_KEY`（.env 中 LLM_API_KEY 为空）。

## 架构（v0.13）

```
transport/   FastAPI 路由：/api/health、POST /api/chat（SSE 流式）
domain/      （待建）专家/会话/能力领域服务
infra/
  harness/   适配层：config.py（→ProviderConfig/HarnessAgentConfig）、
             manager.py（HarnessManager 单例）、chat.py（ChatRequest→事件流）
  storage/   （待建）SQLite（agents/threads/messages，对齐 Octop schema）
```

SSE 事件协议（桌宠前端消费）：`token` / `tool_call` / `tool_result` / `usage` / `done`（answer=完整回复）。

## 当前状态（R1-R3 已完成）

- R1 清理旧代码 ✅（commit `87baddf`）
- R2 新 backend 骨架 ✅：app/{main,config,transport/api,infra/harness/{config,manager,chat}}，ruff+mypy 全绿
- R3 最小对话 API ✅：`POST /api/chat` SSE 流式验证通过（token 流 + done；糯米人设生效）
- 工具调用：插件未接入（M5），模型无工具时诚实回答
- 后续：M3 Agent 生命周期 → M4 会话 → M5 插件 → M6 技能/MCP/知识库 → M7 桌宠前端 → M8 产品体验

## 环境事实（重要）

- **数据根/工作区（单根设计）**：`/Users/superman/Nuomi`，.env 仅设 `NUOMI_HOME`（无 NUOMI_WORKSPACE，workspace=数据根；2026-10-04 迁移自 ~/Documents/Nuomi + ~/Library/Application Support/Nuomi 合一）
- **桌宠模型资产**：工作区 `models/2D/<id>/`（aidang/cat/hiyori，版权受限不入库）；仓库 `assets/models/2D/hiyori` 为可分发种子，后端扫描时幂等播种；壳从后端拿绝对路径转 file:// 加载（app.js `toModelUrl`）
- **会话状态**：`nuomi-state.json`（threads/thread_id/agent_id，顶层即 nuomi.*；2026-10-04 起从壳 config.json 迁出）；壳 config.json 仅存 ui.* 表现层偏好
- **会话模型（2026-10-04 简化）**：会话=真实对话线程；**无 default 桌宠线程、无模型专属会话**——桌宠是纯表现层（订阅 /api/pet/events 拦截对话 tool_call 播放动作），切模型只换形象+插件工具集、**不换会话**（旧"一个桌宠一个会话"已废）
- **后端启动**：`cd backend && nohup .venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/nuomi-backend.log 2>&1 &`
- **venv**：`backend/.venv`（uv 管理，无 pip；装包用 `uv pip install --python .venv/bin/python <pkg>`）
- **harness 验证基线**：`backend/.venv/bin/python backend/probe_harness.py`（harness 独立运行 + DeepSeek 对话 + Octop 插件 what-to-eat 加载）
- **harness 关键 API**：`HarnessAgent(cfg)`、`ChatRequest(messages, thread_id, ...)`、`agent.stream(request)` 返回事件 dict（type 为 `AgentEventType` StrEnum，import 自 `octop_harness.protocols.langgraph`）；`ProviderConfig(id, base_url, api_key, protocol="openai", models=[ModelConfig(id, name)])`；`default_model` 用 `"provider/model"` 复合串；`init_workspace(ws, language="zh", include_md_files=..., include_skills=...)` 建工作区布局（skills/_builtin_skills 目录缺失会 warning，无害）。
- **octop-harness 依赖**：langchain>=1.5 / langgraph<2 / deepagents 0.7 / octop-memory，版本由 harness 约束（venv 实测 langchain 1.4.3 / langgraph 1.2.12 / deepagents 0.7.21 / octop-memory 1.0.0）。
- **git 基线**：`87baddf`（v0.13 推倒重来）。历史版本 ca69992（v0.12）等可查。

## 路线图（v0.13 之后）

- M3 Agent 生命周期：agents 表（对齐 Octop schema：agent_id/name/default_model/system_prompt/enabled/config_json/last_state...）+ 多专家实例管理
- M4 会话通道：threads/messages 表 + checkpointer 持久化 + 历史会话
- M5 插件接入：harness 插件目录（plugin.yaml）+ 现有 plugins/ 资产迁移；旧 service-* 概念废弃（harness 原生替代）
- M6 技能/MCP/知识库：skills_dir 接入 + MCP server 配置 + 知识库工具
- M7 桌宠前端：myspy 二次开发（形象/情绪/字幕/TTS）+ 控制面板
- M8 产品体验：人格/情绪协议、工具执行可视化（"干活中"动画）

## 教训（保留，跨版本有效）

- **MCP（langchain-mcp-adapters 0.3.x）**：`MultiServerMCPClient({"<s>": StdioConnection(transport="stdio", command=..., args=..., env=...)})`；**不是上下文管理器**，直接 `tools = await client.get_tools()`；StdioConnection 必须带 `transport` 键；env 不默认继承，需显式 `env=dict(os.environ)`。
- **DeepSeek 工具调用可靠**；本地小模型（Qwen3.5-2B）工具调用不稳定，仅适合纯对话。
