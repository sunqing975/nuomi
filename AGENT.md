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
- **仓库结构**：`backend/`（Python+FastAPI+harness）、`shells/myspy/`（桌宠壳）、`frontend/`（控制台）、`assets/models/`（模型种子）、`docs/`、`experts/`。旧 myspy 时代 `plugins/`、`skills/` 资产已于 2026-10-04 删除（harness 插件/技能由工作区 `plugins/`、`skills/` 承载，支持前端 zip 导入）。
- **LLM**：默认 DeepSeek（`LLM_API_KEY` > `DEEPSEEK_API_KEY` > `ARK_API_KEY`，base_url https://api.deepseek.com，model deepseek-chat）。本机真实 key 在环境变量 `DEEPSEEK_API_KEY`（.env 中 LLM_API_KEY 为空）。
- **知识库技术决策（2026-10-04，M6 前置调研完成）**：参照 Octop `infra/knowledge/` 实现（每 KB = docs 目录 + 主库元数据行 + `index.sqlite` sidecar 向量索引；异步 parse→chunk(800/120)→embed；内置 `search_knowledge` 工具 + 中间件每轮改写工具描述；引用标记 `<!--octop-kb-citations-->`）。**已拍板：①嵌入先做本地模型（远端 API 后置）；②OCR 进 M6（RapidOCR 本地，图片 png/jpg/jpeg/webp + 扫描 PDF）；③知识库绑定粒度 = 全局默认注入（不做专家级绑定）；④模型目录 `models/ai/<type>/`（embedding + .downloaded 标记 / ocr 预留；`2D/` 桌宠资产不动）；⑤嵌入实现 = **完全仿 Octop**：手写 HF 多源下载（官方+镜像竞速，Octop 自研逻辑）+ **fastembed 加载推理**（`TextEmbedding(cache_dir=models/ai/embedding)`，不手写 onnxruntime 管线）；默认模型 `BAAI/bge-small-zh-v1.5`**。方案/API 清单/工作量：`docs/knowledge-base-research.md`。

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
- **桌宠开关（2026-10-04）**：控制台「桌宠」页开关 → `GET|PUT /api/pet/status` → 壳 config.json `ui.pet_enabled` → 壳 watch 创建/销毁桌宠窗口（关闭=完全停止窗口释放资源，壳进程与后端对话不受影响；启动时按开关决定是否创建）。**开关联动模型插件**：关闭→停用全部模型插件（LLM 工具集不再有动作工具），开启→恢复激活当前选中模型的插件（互斥）；桌宠关闭时切模型仅换形象不激活插件（返回 activated_plugin=null）
- **专家-插件解耦（2026-10-04）**：专家不再绑定插件（`agent_plugins` 表/绑定 API/前端「绑插件」UI 全删）。插件=全局启停（`plugins.enabled`），启用即对所有专家可用；工具装配 `PluginService.tools()` 只按全局启停 `build_plugin_tools(global_plugins=...)`。桌宠模型插件互斥保留（切换模型只 `set_enabled` 互斥 + `manager.release`，不再 bind 到 agent）
- **对话框大改动（2026-10-04）**：能力按 per-turn（每次请求）注入，对齐 octop 对话框语义。`POST /agents/{id}/chat` body 扩展 `{skills, connectors}`：skills=None 全量/[] 禁用全部/[name|slug] 只启用（校验存在性，400）；connectors=None 默认挂载/[] 不挂载/[name] 只挂载。底层走 harness 原生 `ChatRequest.skills`（SkillFilterMiddleware 白名单）+ `mcp_servers/mcp_use_default`，无需自研。前端对话框：技能/连接器选择器（Popover）+ 输入框上方能力 chips（可移除）+ 消息气泡内工具步骤折叠（tool_call→tool_result）+ 轨迹抽屉（当前会话工具时间线）。**踩坑：per-turn 能力校验必须在 StreamingResponse 的 generator 之外（端点函数体）执行，否则抛错不转 400**
- **大模型配置页（2026-10-04）**：LLM Provider 多配置管理（对齐 octop providers 管理）。存储 `工作区/providers.json`（运行时权威，.env LLM_* 仅种子回退；api_key 明文存工作区、不进 git）；`GET|PUT /settings/providers`（整体保存；api_key 空串=保持原值；GET 脱敏 sk-2***fa1e；校验 id 唯一/base_url/模型非空，400）。`build_providers()` 从 providers.json 构建 ProviderConfig 列表
- **模型不绑专家（2026-10-04）**：agents 表 `default_model` 字段删除（含旧库 DROP COLUMN 迁移），专家与模型解耦；模型在**对话框 per-turn 选择**（工具条「模型」Select，选项来自 providers×models），发送带 `model`（provider/model）字段，走 harness 原生 `ChatRequest.model`（优先于 default_model）；后端校验 model 存在于 providers（非法 400）。agent 默认模型 = providers[0] 默认
- **Provider 模型探测（2026-10-04）**：`POST /settings/providers/probe`（body base_url/api_key，不落盘）调 OpenAI 兼容 `/models` 拉取模型列表；新增 Provider 弹窗「探测模型」按钮 → 勾选列表（默认勾选第一个作为默认模型）→ 回填；探测失败 400 带原因
- **对话框输入区优化（2026-10-04）**：能力选择器（技能/连接器/模型）独立一行（输入框上方，提示「不选=全部技能/默认连接器/默认模型」），输入框独占整行 flex:1 + autoSize（1–6 行）；会话左栏 240→200、模型 Select 180→150、placeholder 缩短
- 后续：M3 Agent 生命周期 → M4 会话 → M5 插件 → M6 技能/连接器/知识库 → M7 桌宠前端 → M8 产品体验

## 环境事实（重要）

- **数据根/工作区（单根设计）**：`/Users/superman/Nuomi`，.env 仅设 `NUOMI_HOME`（无 NUOMI_WORKSPACE，workspace=数据根；2026-10-04 迁移自 ~/Documents/Nuomi + ~/Library/Application Support/Nuomi 合一）
- **桌宠模型资产**：工作区 `models/2D/<id>/`（aidang/cat/hiyori，版权受限不入库）；仓库 `assets/models/2D/hiyori` 为可分发种子，后端扫描时幂等播种；壳从后端拿绝对路径转 file:// 加载（app.js `toModelUrl`）。**models/ 分层（2026-10-04 设计）**：`2D/`=桌宠表现层资产，`ai/`=智能模型（`models/ai/embedding/` 嵌入 ONNX + `.downloaded` 标记、`models/ai/ocr/` OCR 预留），方案见 docs/knowledge-base-research.md §8
- **会话状态**：`nuomi-state.json`（threads/thread_id/agent_id，顶层即 nuomi.*；2026-10-04 起从壳 config.json 迁出）；壳 config.json 仅存 ui.* 表现层偏好（ui.model/ui.model_path/ui.pet_enabled 桌宠开关 2026-10-04 加入）
- **会话模型（2026-10-04 简化）**：会话=真实对话线程；**无 default 桌宠线程、无模型专属会话**——桌宠是纯表现层（订阅 /api/pet/events 拦截对话 tool_call 播放动作），切模型只换形象+插件工具集、**不换会话**（旧"一个桌宠一个会话"已废）
- **状态文件即用即清（2026-10-04 起强制）**：`nuomi-state.json` 等数据文件的字段一旦不再被代码读写，**当场删除**，不留兼容字段（例：threads[].model_id 已删）。禁止"先留着以后再说"——死数据会误导后续读写，直接成为屎山源头
- **后端启动**：`cd backend && nohup .venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/nuomi-backend.log 2>&1 &`
- **venv**：`backend/.venv`（uv 管理，无 pip；装包用 `uv pip install --python .venv/bin/python <pkg>`）
- **harness 验证基线**：`backend/.venv/bin/python backend/probe_harness.py`（harness 独立运行 + DeepSeek 对话 + Octop 插件 what-to-eat 加载）
- **harness 关键 API**：`HarnessAgent(cfg)`、`ChatRequest(messages, thread_id, ...)`、`agent.stream(request)` 返回事件 dict（type 为 `AgentEventType` StrEnum，import 自 `octop_harness.protocols.langgraph`）；`ProviderConfig(id, base_url, api_key, protocol="openai", models=[ModelConfig(id, name)])`；`default_model` 用 `"provider/model"` 复合串；`init_workspace(ws, language="zh", include_md_files=..., include_skills=...)` 建工作区布局（skills/_builtin_skills 目录缺失会 warning，无害）。
- **octop-harness 依赖**：langchain>=1.5 / langgraph<2 / deepagents 0.7 / octop-memory，版本由 harness 约束（venv 实测 langchain 1.4.3 / langgraph 1.2.12 / deepagents 0.7.21 / octop-memory 1.0.0）。
- **git 基线**：`87baddf`（v0.13 推倒重来）。历史版本 ca69992（v0.12）等可查。

## 路线图（v0.13 之后）

- M3 Agent 生命周期：agents 表（对齐 Octop schema：agent_id/name/default_model/system_prompt/enabled/config_json/last_state...）+ 多专家实例管理
- M4 会话通道：threads/messages 表 + checkpointer 持久化 + 历史会话
- M5 插件接入：harness 插件目录（plugin.yaml）+ 前端 zip 导入（工作区 plugins/）；旧 myspy plugins//skills/ 资产已删（2026-10-04）；旧 service-* 概念废弃（harness 原生替代）
- M6 技能/连接器/知识库：skills_dir 接入 + 连接器（MCP 协议）配置 + 知识库工具（调研完成，决策见上：本地 ONNX 嵌入 + OCR + 全局默认注入；**2026-10-04 语义修正：知识库与技能/连接器同维度，不选=[]=不加载，无「默认打开」一说（default_open 列已 DROP 迁移），显式指定才注入**；实现进度 2026-10-04：嵌入服务（多源下载+fastembed 推理+就绪检查）、存储层（repo/parse/chunk/index.sqlite/service/jobs 状态机）、API 路由（knowledge_api.py：能力/模型/CRUD/文档 17 端点）、前端页（#knowledge 三区块 + 3 Modal）、检索工具 search_knowledge（tools.py）+ 引用标记协议（citations.py，`<!--octop-kb-citations:[...]-->` 沿用 Octop）+ 跨库检索（retrieve.py，k=8/6000 字符预算）+ 对话注入（default_open.py 显式指定才注入 + hint.py 中间件无库隐藏工具 + harness config/chat 接线 + ChatBody.knowledge_base_ids）+ Chat 引用展示（parseKnowledgeCitations.ts + KnowledgeCitations 组件）+ 对话框四选择器（技能/连接器/知识库/模型必选，消息必填）；pytest 21 项全过 + ruff/mypy 干净；真实环境验证：curl 显式 ids 触发 search_knowledge + 引用标记完整 + 模型引用回答，无 ids 不注入（0 次工具调用），浏览器实测引用 Tag 渲染 + 知识库选择器 + 模型必选发送禁用；剩余：OCR（RapidOCR+扫描 PDF，用户叫停暂缓）**）
- M7 桌宠前端：myspy 二次开发（形象/情绪/字幕/TTS）+ 控制面板
- M8 产品体验：人格/情绪协议、工具执行可视化（"干活中"动画）

## 教训（保留，跨版本有效）

- **MCP（langchain-mcp-adapters 0.3.x）**：`MultiServerMCPClient({"<s>": StdioConnection(transport="stdio", command=..., args=..., env=...)})`；**不是上下文管理器**，直接 `tools = await client.get_tools()`；StdioConnection 必须带 `transport` 键；env 不默认继承，需显式 `env=dict(os.environ)`。
- **DeepSeek 工具调用可靠**；本地小模型（Qwen3.5-2B）工具调用不稳定，仅适合纯对话。
