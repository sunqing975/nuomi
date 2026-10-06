# 糯米 · 项目记忆（AGENT.md）

> 按用户记忆策略：本文件记录本项目全部细节与决策；系统记忆只记跨项目共性。

## 项目定位（2026-10-03 v0.13 推倒重来）

**桌面 AI 人格工作台**——灵感来自《魔幻手机》的"傻妞"：既是数字生命（有形象、有情绪、会变装），又能干活（工具/记忆/技能）。不是"个人助理"，是"住在你电脑里的 AI 人格"。

技术路线：**octop-harness（机制基础库）+ 业务层自研 + AI 数字人开源项目（形象层）**。

- 机制层：`octop-harness`（PyPI 1.0.0，Octop 的 Agent 运行时，LangChain Deep Agents）——Agent 循环/工具/记忆/checkpointer/技能/MCP 全部白拿，**不再自研 engine**（旧 composer/fiber/loader 四层已删除）。
- 业务层：nuomi 自己写——专家/会话/能力领域服务，向 Octop 领域设计靠拢（领域语言一等公民，机制语言当基础库）。
- 形象层：**nuomi-avatar**（github.com/sitwrrr/nuomi-avatar，MIT）二次开发——Electron AI 数字人壳 + Live2D/VRM 渲染 + 情绪标签驱动表情 + 流式字幕/TTS。备选：live2d-to-agent（MCP 控制AI 数字人）、OpenPets。

- **概念口径（从已删的 concepts.md 抢救出的仍成立部分，2026-10-06）**：①**不用 Octop 的 `kind`**
  （在一个分发单元内区分 tool/skill/hook）——nuomi 按职责分目录，**目录即分类**；②**依赖只允许向内**
  （transport → domain → infra/harness → octop-harness；`infra` 不得 import `domain`/`transport`）；
  ③**领域语言 vs 机制语言分开**（业务文案说"连接器"，不暴露 MCP 等协议术语）。
  已不成立、随文档删除的旧口径：概念文档自称"v0.8 唯一权威"（架构早已是 v0.13）、
  「插件市场/zip 安装器 ❌ 不做」（实际已上线在用）、「记忆 Provider 化对齐 Hermes/Mem0」
  （现为 octop-memory，代码里没有 `MemoryStore`/`facts` 抽象）。

## 已确定的关键决策（v0.13）

- **推倒重来**：删除旧 backend/app（自研 engine 四层）、旧 frontend/（antd 界面）、Tauri 壳、sidecar、部署文件；git 历史保留（`87baddf` 起新基线）。
- **不背历史数据**：新库起步，不写迁移脚本，旧会话/旧结构数据直接放弃。
- **页面不抄 Octop**：保留 nuomi 自己的设计，AI 数字人主界面 = 角色（卡通人物），不是聊天列表。
- **分层依赖**：`transport → domain → infra/harness → octop-harness`；infra 禁 import domain/transport。
- **仓库结构**：`backend/`（Python+FastAPI+harness）、`shells/nuomi-avatar/`（AI 数字人壳）、`frontend/`（控制台）、`assets/models/`（模型种子）、`docs/`、`experts/`。旧 nuomi-avatar 时代 `plugins/`、`skills/` 资产已于 2026-10-04 删除（harness 插件/技能由工作区 `plugins/`、`skills/` 承载，支持前端 zip 导入）。
- **LLM**：默认 DeepSeek（`LLM_API_KEY` > `DEEPSEEK_API_KEY` > `ARK_API_KEY`，base_url https://api.deepseek.com，model deepseek-chat）。本机真实 key 在环境变量 `DEEPSEEK_API_KEY`（.env 中 LLM_API_KEY 为空）。
- **知识库技术决策（2026-10-04，M6 前置调研完成）**：参照 Octop `infra/knowledge/` 实现（每 KB = docs 目录 + 主库元数据行 + `index.sqlite` sidecar 向量索引；异步 parse→chunk(800/120)→embed；内置 `search_knowledge` 工具 + 中间件每轮改写工具描述；引用标记 `<!--octop-kb-citations-->`）。**已拍板：①嵌入先做本地模型（远端 API 后置）；②OCR 进 M6（RapidOCR 本地，图片 png/jpg/jpeg/webp + 扫描 PDF）；③知识库绑定粒度 = 对话框 per-turn 选择，显式指定才注入（无「默认打开」；2026-10-04 用户拍板与技能/连接器同维度，default_open 全链路已删）；④模型目录 `models/ai/<type>/`（embedding + .downloaded 标记 / ocr 预留；`2D/` AI 数字人资产不动）；⑤嵌入实现 = **完全仿 Octop**：手写 HF 多源下载（官方+镜像竞速，Octop 自研逻辑）+ **fastembed 加载推理**（`TextEmbedding(cache_dir=models/ai/embedding)`，不手写 onnxruntime 管线）；默认模型 `BAAI/bge-small-zh-v1.5`**。方案/API 清单/工作量：`docs/knowledge-base-research.md`。
- **专家 workspace 模型（2026-10-04 A2 对齐 octop，用户拍板）**：每专家独立 workspace `数据根/agent-workspaces/<agent_id>/`。persona 走 harness 记忆文件标准（USER/SOUL/AGENTS/MEMORY.md 放 workspace 根，harness 每轮自动注入、改文件即生效；无 IDENTITY.md 概念，身份写 USER.md「关于我」）；manifest（`.octop/manifest.json`，octop 双语格式）为展示元数据权威（name/description/welcome_message/icon_name/color/quick_prompts，后端 `enrich_agent` 归一化，DB 字段兜底）；记忆/会话/技能按专家隔离（各自 memory.sqlite/sessions/_builtin_skills）。**模板匹配**：experts/<agent_id|name>/ 优先，再按 manifest（id/label.zh）匹配（糯米=experts/nuomi/，color #f59e0b）。
- **Octop 专家导入（2026-10-04 A2）**：`backend/scripts/import_octop_expert.py <source_dir> [--name 名]` 或 `POST /api/agents/import {source_dir}`；源 = `~/.octop/agents/<id>/`（已装）或 Octop 源码 `experts/library/<id>/`（模板）；复制 persona（含 BOOTSTRAP/PROACTIVE）+ skills/ + agents/（子智能体）+ manifest 到新专家 workspace，DB 注册（system_prompt 兜底、icon/color/welcome 取 manifest；**记忆不复制，从零开始**）。实测导入 general-assistant（小通·通用助手，4b97d68b698e）对话正常。
- **糯米人设变更（2026-10-04，用户拍板）**：猫 → 人工智能助手。experts/nuomi/ 全改 AI 助手（IDENTITY.md 删除、并入 USER.md「关于我」；MEMORY.md 新建）；DB system_prompt 降为兜底短句「你是糯米，住在用户电脑里的人工智能助手。中文回答，简洁友好。」（详细 persona 走文件注入）；全部会话与记忆已清空（备份 /tmp/memory-20261004.bak.sqlite、/tmp/nuomi-20261004.bak.db）。记忆由 harness `___atoms` 表承载（`nuomi_*` 表是废弃空表、facts 表无代码读写），清空后从零重建。

## 架构（v0.13）

```
transport/   FastAPI 路由：/api/health、/api/chat、/api/agents/{id}/chat（SSE 流式）、
             /api/avatar/*、/api/plugins/*、/api/settings/* 等
domain/      ✅ 已建成：agents/plugins/avatar/chat 等领域服务（原"待建"已过时）
infra/
  harness/   适配层：config.py（→ProviderConfig/HarnessAgentConfig）、
             manager.py（HarnessManager 单例）、chat.py（ChatRequest→事件流）、
             runtime_limits.py（agents.config_json → ChatRequest）
  storage/   ✅ 已建成：SQLite（agents/threads/thread_messages 投影表，对齐 Octop schema）
```

SSE 事件协议（当前完整）：`token` / `reasoning` / `tool_call_chunk`（带 plugin_id）/ `tool_result`（带 plugin_id）/ `done`；另由事件层（event_bus）发布 `conversation.started / conversation.completed`。

## 当前状态（R1-R3 已完成）

- R1 清理旧代码 ✅（commit `87baddf`）
- R2 新 backend 骨架 ✅：app/{main,config,transport/api,infra/harness/{config,manager,chat}}，ruff+mypy 全绿
- R3 最小对话 API ✅：`POST /api/chat` SSE 流式验证通过（token 流 + done；糯米人设生效）
- ~~工具调用：插件未接入（M5），模型无工具时诚实回答~~ **已过时**：M5 插件已完成（插件市场/三层能力/聊天卡片均落地），工具调用正常
- **AI 数字人开关（2026-10-04）**：控制台「AI 数字人」页开关 → `GET|PUT /api/avatar/status` → 壳 config.json `ui.avatar_enabled` → 壳 watch 创建/销毁AI 数字人窗口（关闭=完全停止窗口释放资源，壳进程与后端对话不受影响；启动时按开关决定是否创建）。~~开关联动模型插件：关闭→停用全部模型插件（LLM 工具集不再有动作工具），开启→恢复激活当前选中模型的插件（互斥）~~ **已过时（2026-10-04 方案 B）**：改为启停只绑定共享插件 vrm-avatar（见"方案 B 实施完成"）
- **AI 数字人=LLM 直接遥控身体（2026-10-04，M7 核心）**：不是预编程自动动画，是**把身体能力暴露成工具让 LLM 在对话中主动调用**。参考项目：claw-sama（Tauri+VRM，分部位触摸+情绪系统）、mitscherlich/live2d-mcp（pixi-live2d-display+工具表，跟我们栈一样）、clawatar（VRM WebSocket JSON 命令，set_expression 带 weight、speak+action+expression 原子绑定）。
  - ~~**语义动作清单**：每模型目录放 `actions.json`（...），后端 `generate_model_plugin` 有 manifest 时按语义名生成工具（wave/dance/nod...），无 manifest fallback 到按 motion group 名注册。aidang 已配 13 个语义动作~~ **已过时（2026-10-04 方案 B + 2026-10-05 删内置动作）**：单共享插件 vrm-avatar + 动态工具（do_action/set_expression），动作只以 VRMA 文件为准、表情以 VRM 模型 blend shape 为准
  - **事件协议**：SSE `/api/avatar/events` 推送 `{type:"avatar_action", motion:"main_1", expressions:[], label:"挥手"}`——后端 `_resolve_avatar_action(tool_name)` 根据当前模型 manifest 反查完整 payload，壳不再瞎猜 motion/expression。旧 `tool_call {name, kind}` 协议已废。
  - **表情自动恢复**：壳 `playAvatarExpression` 播表情后 5 秒自动 `model.expression()` 重置（pixi 不传参=清所有表情参数），连续表情刷新定时器。修复了之前表情卡死的 bug。
  - **instructions.md 自动注入（业务层创新，octop 不支持）**：插件生成时自动写 `instructions.md`（列出所有动作+使用原则）；chat API 检测到AI 数字人插件启用时，读 `plugins/<model_id>/instructions.md` 拼到 system_prompt 后面。**不污染专家人设**——人格在 DB/persona 文件，身体说明跟着插件走，关AI 数字人就不注入，换模型自动换动作清单。
  - **壳侧**：`playAvatarMotion(name)` / `playAvatarExpression(name)` / `playAvatarActionPayload(payload)`；删除死代码 `handleNuomiToolResult` / `playPetAction`（全项目无调用点）；`AVATAR_ACTION_MAP` 保留为语义映射雏形（P1 参考）。
- **专家-插件解耦（2026-10-04）**：专家不再绑定插件（`agent_plugins` 表/绑定 API/前端「绑插件」UI 全删）。插件=全局启停（`plugins.enabled`），启用即对所有专家可用；工具装配 `PluginService.tools()` 只按全局启停 `build_plugin_tools(global_plugins=...)`。AI 数字人模型插件互斥保留（切换模型只 `set_enabled` 互斥 + `manager.release`，不再 bind 到 agent）
- **对话框大改动（2026-10-04）**：能力按 per-turn（每次请求）注入，对齐 octop 对话框语义。`POST /agents/{id}/chat` body 扩展 `{skills, connectors}`：skills=None 全量/[] 禁用全部/[name|slug] 只启用（校验存在性，400）；connectors=None 默认挂载/[] 不挂载/[name] 只挂载。底层走 harness 原生 `ChatRequest.skills`（SkillFilterMiddleware 白名单）+ `mcp_servers/mcp_use_default`，无需自研。前端对话框：技能/连接器选择器（Popover）+ 输入框上方能力 chips（可移除）+ 消息气泡内工具步骤折叠（tool_call→tool_result）+ 轨迹抽屉（当前会话工具时间线）。**工具步骤折叠升级（2026-10-04 晚）**：工具调用/结果卡片标题改为可点击折叠头（▸/▾ 与深度思考一致，默认收起，点击展开参数/结果），复用 SegmentView 同一 open state；`search_knowledge` 引用随结果卡片展开显示。**正文 Markdown 渲染（2026-10-04 晚）**：正文 text 片段从纯文本 pre-wrap 升级为 react-markdown 渲染（前端新装 `react-markdown` 依赖）；`MarkdownText` 组件统一处理历史/流式正文——先 `parseKnowledgeCitations` 剥离 `<!--octop-kb-citations:-->` 引用标记再渲染 md，引用标签条复用新拆出的 `CitationsTags`；`KnowledgeCitations` 组件内部拆为 CitationsTags + 正文，工具结果行为不变；index.css 新增 `.md-body` 排版（h1-h6/p/ul-ol/li/code/pre/blockquote/a/table/hr/img）；react-markdown 默认不渲染原始 HTML、urlTransform 过滤危险协议，无 XSS 风险；**用户消息保持纯文本不渲染 md**。**踩坑（已结构性保证，2026-10-06）**：per-turn 能力校验必须在 StreamingResponse 的 generator 之外（端点函数体）执行，否则抛错不转 400。流式端点统一走 `app/transport/streaming.py::stream_response`（校验在 gen 前执行）；`tests/test_streaming_guard.py` 扫描锁定「transport 层禁止裸构造 StreamingResponse」「async def gen 内禁止 raise HTTPException」
- **大模型配置页（2026-10-04）**：LLM Provider 多配置管理（对齐 octop providers 管理）。存储 `工作区/providers.json`（运行时权威，.env LLM_* 仅种子回退；api_key 明文存工作区、不进 git）；`GET|PUT /settings/providers`（整体保存；api_key 空串=保持原值；GET 脱敏 sk-2***fa1e；校验 id 唯一/base_url/模型非空，400）。`build_providers()` 从 providers.json 构建 ProviderConfig 列表
- **模型不绑专家（2026-10-04）**：agents 表 `default_model` 字段删除（含旧库 DROP COLUMN 迁移），专家与模型解耦；模型在**对话框 per-turn 选择**（工具条「模型」Select，选项来自 providers×models），发送带 `model`（provider/model）字段，走 harness 原生 `ChatRequest.model`（优先于 default_model）；后端校验 model 存在于 providers（非法 400）。agent 默认模型 = providers[0] 默认
- **Provider 模型探测（2026-10-04）**：`POST /settings/providers/probe`（body base_url/api_key，不落盘）调 OpenAI 兼容 `/models` 拉取模型列表；新增 Provider 弹窗「探测模型」按钮 → 勾选列表（默认勾选第一个作为默认模型）→ 回填；探测失败 400 带原因
- **对话框输入区优化（2026-10-04）**：能力选择器（技能/连接器/知识库/模型）独立一行（提示文案已移除，2026-10-04 用户要求不显示），输入框独占整行 flex:1 + autoSize（1–6 行）；会话左栏 240→200、模型 Select 180→150、placeholder 缩短
- **模型默认自动（2026-10-04）**：对话框「模型」Select 首项新增「自动（默认）」（value 哨兵 `auto`，前端 Chat.tsx `MODEL_AUTO`），默认选中；选中「自动」时请求体 `model=null`，由后端按 agent 默认模型解析（`stream_chat` model=None → 默认模型）；用户显式选择具体模型才覆盖，移除模型 chip 回到「自动」。`ChatStreamOptions.model` 类型放开为 `string | null`。替代原「模型必选」语义（必选校验已删）
- **形态与遗留清理（2026-10-04，用户拍板）**：默认形态 = **AI 数字人壳 shells/nuomi-avatar**（Electron，`npm start`，经 config.json `llm.api_url` → 后端 :8000 `/api/v1` OpenAI 兼容端点对话）；**web 控制台只是调试形态**（:5173，vite 代理 /api → :8000）。Makefile 重写：`make start` 启动AI 数字人壳（替换已失效的 tauri desktop 目标，`desktop/` 目录 v0.13 已删）、`make web` 调试、stop/status/logs 同步改为AI 数字人壳；tauri 遗留（README desktop/ 引用、demo 脚本里的 tauri build 检查项、.logs/desktop.log）已清理；当时的桌面化设计文档已随本轮文档清理删除（其仍有效的决策——NUOMI_HOME 工作区、SQLite 合一、单用户、目录结构收敛——全部以本文件「环境事实」章节为准）。AI 数字人壳重启 = 杀 Electron 进程后 `shells/nuomi-avatar && npm start`
- **连接器 env 支持（2026-10-04）**：ConnectorBody 增 `env: dict[str,str]`（键名校验 `^[A-Za-z_][A-Za-z0-9_]*$`，非法 400，空键过滤）；spec 透传 harness——octop-harness `aload_mcp_tools` 原生合并 stdio env（SDK 默认子集 + spec env，PROTECTED_ENV_KEYS 不覆盖），**sse/http 传输不注入 env**；前端连接器表单加 key-value 环境变量编辑（Form.List，卡片仅显示键名不显示值）；测试 `tests/test_connectors_api.py`（API CRUD + `load_mcp_tools` 集成验证 env 注入子进程），pytest 26 项全过 + ruff/mypy 干净；端到端实测：对话调 `read_env` 返回连接器 env 配置值 ✓
- 后续：~~M3 Agent 生命周期 → M4 会话 → M5 插件 → M6 技能/连接器/知识库 → M7 AI 数字人前端 → M8 产品体验~~ **全部完成（2026-10-05）**，见路线图勾选；后续新功能一律插件化开发（2026-10-05 用户拍板）

## 环境事实（重要）

- **数据根/工作区**：`/Users/superman/Nuomi`（NUOMI_HOME；全局共享根：providers.json/env.json/knowledge/ 等）。**专家工作区（2026-10-04 A2）**：`agent-workspaces/<agent_id>/` = persona 文件 + `.octop/manifest.json` + 独立 memory.sqlite/sessions/_builtin_skills；harness 记忆注入目标 = 专家 workspace；全局根 memory.sqlite 为迁移期遗留（不再被新对话写入，删除线程上下文时双清兼容）。.env 仅设 `NUOMI_HOME`（2026-10-04 迁移自 ~/Documents/Nuomi + ~/Library/Application Support/Nuomi 合一）
- **AI 数字人模型资产**：工作区 `models/2D/<id>/`（aidang/cat/hiyori，版权受限不入库）；仓库 `assets/models/2D/hiyori` 为可分发种子，后端扫描时幂等播种；壳从后端拿绝对路径转 file:// 加载（app.js `toModelUrl`）。**models/ 分层（2026-10-04 设计）**：`2D/`=AI 数字人表现层资产，`ai/`=智能模型（`models/ai/embedding/` 嵌入 ONNX + `.downloaded` 标记、`models/ai/ocr/` OCR 预留），方案见 docs/knowledge-base-research.md §8
- **会话状态**：`nuomi-state.json`（threads/thread_id/agent_id，顶层即 nuomi.*；2026-10-04 起从壳 config.json 迁出）；壳 config.json 仅存 ui.* 表现层偏好（ui.model/ui.model_path/ui.avatar_enabled AI 数字人开关 2026-10-04 加入）
- **会话模型（2026-10-04 简化）**：会话=真实对话线程；**无 default AI 数字人线程、无模型专属会话**——AI 数字人是纯表现层（订阅 /api/avatar/events 拦截对话 tool_call 播放动作），切模型只换形象+插件工具集、**不换会话**（旧"一个AI 数字人一个会话"已废）
- **状态文件即用即清（2026-10-04 起强制）**：`nuomi-state.json` 等数据文件的字段一旦不再被代码读写，**当场删除**，不留兼容字段（例：threads[].model_id 已删）。禁止"先留着以后再说"——死数据会误导后续读写，直接成为屎山源头
- **后端启动**：**壳已自动拉起（ensureBackend，make start 一条命令）**；手动启动（排查/单独跑后端用）：`cd backend && nohup .venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/nuomi-backend.log 2>&1 &`（壳拉起时 stdout 丢弃，查后端日志需手动起后端）
- **venv**：`backend/.venv`（uv 管理，无 pip；装包用 `uv pip install --python .venv/bin/python <pkg>`）
- **harness 验证基线**：`backend/.venv/bin/python backend/probe_harness.py`（harness 独立运行 + DeepSeek 对话 + Octop 插件 what-to-eat 加载）
- **harness 关键 API**：`HarnessAgent(cfg)`、`ChatRequest(messages, thread_id, ...)`、`agent.stream(request)` 返回事件 dict（type 为 `AgentEventType` StrEnum，import 自 `octop_harness.protocols.langgraph`）；`ProviderConfig(id, base_url, api_key, protocol="openai", models=[ModelConfig(id, name)])`；`default_model` 用 `"provider/model"` 复合串；`init_workspace(ws, language="zh", include_md_files=..., include_skills=...)` 建工作区布局（skills/_builtin_skills 目录缺失会 warning，无害）。
- **octop-harness 依赖**：langchain>=1.5 / langgraph<2 / deepagents 0.7 / octop-memory，版本由 harness 约束（venv 实测 langchain 1.4.3 / langgraph 1.2.12 / deepagents 0.7.21 / octop-memory 1.0.0）。
- **git 基线**：`87baddf`（v0.13 推倒重来）。历史版本 ca69992（v0.12）等可查。

## 路线图（v0.13 之后）

- [x] M3 Agent 生命周期（2026-10-05 完成）：agents 表（对齐 Octop schema：agent_id/name/default_model/system_prompt/enabled/config_json/last_state...）+ 多专家实例管理（CRUD/start/stop/status + HarnessManager 单例 + 专家工作区）；**运行时参数接线（本次补全）**：agents.config_json 的 max_iters/temperature/top_p/max_tokens/max_input_length → ChatRequest 注入（`infra/harness/runtime_limits.py`，对齐 Octop runtime_limits：max_iters→recursion_limit、temperature 等→configurable[model_settings]（harness 默认 ModelSettingsMiddleware 消费）、max_input_length→configurable[max_input_tokens]；非法值过滤、per-turn 显式值优先）；PATCH /agents/{id} 支持 config_json；DELETE 级联清理专家工作区（对齐 Octop：rmtree 失败不阻断）
- [x] M4 会话通道（2026-10-05 完成）：**threads 表落库**（thread_id/agent_id/title/last_active/created_at/pinned/model_ref，对齐 Octop ThreadRow 单用户裁剪）+ **thread_messages 投影表**（seq/message_id/role/message_json/created_at，langchain wire 格式）+ **thread_history_projection 状态表**（pending/ready）；会话列表权威从 nuomi-state.json 迁到 SQLite（幂等迁移 + 迁移后清理旧 threads 字段；state 文件只留 thread_id + agent_id）；消息权威仍在 octop checkpointer——投影 = 历史加速层（**首次读历史全量 backfill → ready，之后每轮对话增量 append**，对齐 Octop dashboard projection 语义）；chat_history 端点投影优先读表（不依赖 harness 运行时实例），pending 时 backfill；删会话级联清 threads+投影+checkpointer；openai_compat（AI 数字人壳）同样接线
- [x] M5 插件接入 ✅（2026-10-05 完成）：插件市场机制（registry + zip 安装 + 启停 + 配置读写）+ **插件三层能力**（工具注册 / 事件订阅发布 / 聊天卡片 UI）；插件市场并入「插件」页（不占独立菜单）；harness 插件目录（plugin.yaml）+ 前端 zip 导入（工作区 plugins/）；weather-octop 验证插件
- [x] M6 技能/连接器/知识库 ✅（2026-10-05 完成，OCR 暂缓）：**2026-10-04 语义修正：知识库与技能/连接器同维度，不选=[]=不加载，无「默认打开」一说（default_open 列已 DROP 迁移），显式指定才注入**；实现进度 2026-10-04：嵌入服务（多源下载+fastembed 推理+就绪检查）、存储层（repo/parse/chunk/index.sqlite/service/jobs 状态机）、API 路由（knowledge_api.py：能力/模型/CRUD/文档 17 端点）、前端页（#knowledge 三区块 + 3 Modal）、检索工具 search_knowledge（tools.py）+ 引用标记协议（citations.py，`<!--octop-kb-citations:[...]-->` 沿用 Octop）+ 跨库检索（retrieve.py，k=8/6000 字符预算）+ 对话注入（default_open.py 显式指定才注入 + hint.py 中间件无库隐藏工具 + harness config/chat 接线 + ChatBody.knowledge_base_ids）+ Chat 引用展示（parseKnowledgeCitations.ts + KnowledgeCitations 组件）+ 对话框四选择器（技能/连接器/知识库/模型必选，消息必填）；技能选择器三分组（已启用的技能/内置技能/已启用的技能包，包级整包勾选=包内技能 slug 全进白名单，_available_skill_keys 补内置技能名）；知识库级联删除（delete_base 同事务清 knowledge_documents 行 + rmtree 目录）+ 库级启停（enabled 列迁移/停用库对话侧不可选/显式指定 400，对齐插件）+ 前端知识库页列表/详情双视图（点卡片进详情、返回回列表，详情内可删除库并自动回列表；loadDocs reqId 竞态保护 + loadBases 校正 stale 选中，根治删除后详情不同步/404）；pytest 24 项全过 + ruff/mypy 干净；真实环境验证：curl 显式 ids 触发 search_knowledge + 引用标记完整 + 模型引用回答，无 ids 不注入（0 次工具调用），白名单 [apple-notes+therapy-board] 200/未知技能 400，浏览器实测引用 Tag 渲染 + 知识库选择器 + 技能三分组 + 模型必选发送禁用；剩余：OCR（RapidOCR+扫描 PDF，用户叫停暂缓）**）
- [x] M7 AI 数字人前端 ✅（2026-10-05 完成）：nuomi-avatar 二次开发（VRM 3D / 情绪 / 字幕 / TTS）+ 控制面板（模型/动作资产管理、预览、热切换）
- [x] M8 产品体验 ✅（2026-10-05 完成）：工具执行可视化（thinking→working→idle 状态表情）+ 聊天卡片（octop 对齐）
- **待办（2026-10-04 用户拍板暂缓，仍待办）**：专家级默认绑定（对齐 octop agents 表 `skill_package_ids`/`knowledge_base_ids`/`mcp_servers` 三列）：nuomi agents 表加绑定列 + 对话时默认注入（per-turn 可覆盖，知识库仍保持显式指定才注入）+ 导入器读取 octop agent 记录的绑定字段；另：octop manifest `prompt_files` 声明的非标准文件（如 IDENTITY.md/HEARTBEAT.md，现已复制资产但不注入）内容合并进注入或 system_prompt
- ~~**待办（2026-10-04 用户拍板，稍后开工）——AI 数字人 3D 化 + 动态工具（方案 B）**~~ **已实施完成（见"方案 B 实施完成"章节）**：物理删 2D、表情单工具、动态工具装配（do_action/set_expression）
- ~~**待办（2026-10-04 方案 B 架构定稿，不动基础库）**~~ **已实施完成**：单共享插件 vrm-avatar（删模型插件互斥）、动作/表情中文元数据共享来源、清单版本变化自动 release

## 第 1 周正确性与体验修复（2026-10-06）

> 承接第 0 步（安全与门禁），本次做掉路线图 4–9 项。全部改动配套回归测试；`make check` 全绿（79 例）。

- **工具调用投影丢失（第 4 项，实测根因）**：`chat.py` 的 `pending_tools` 在 **TOOL_RESULT 分支就 `clear()`**，而 turn payload 在流末尾才从 `pending_tools` 取 → 正常 ReAct 轮次 `tool_calls` 恒为 `[]`。后果不是"整轮丢"，而是**同一会话历史因写入路径不同而不一致**：首次 backfill 走 `messages_to_inputs`（args 是 dict，正常）能显示工具卡片，之后增量追加的轮次没有。修法：flush 时即归档到 `turn_tool_calls`，末尾再补一次未 flush 的分块。另有**第二半**：`turn_to_message_inputs` 把分块拼出的 args **字符串**直传 `AIMessage(tool_calls=...)`，LangChain 要求 dict，会抛 `ValidationError` 并被上层吞成一行日志（那种情况才整轮丢）；新增 `_normalize_tool_calls` 解析 + 兜底（非 JSON/非 dict/缺 name 丢弃）。回归测试 `tests/test_tool_call_projection.py`（14 例，含"旧逻辑跑同一组事件会失败"的证伪）。
- **`start_agent` 绕过统一运行时入口（第 5 项）**：`POST /agents/{id}/start` 自行调 `manager.get_agent` 且漏传 `workspace_dir` —— 用户在「专家」页点一下「启动实例」就会把实例缓存到全局数据根（无 persona、写全局 memory.sqlite），正是 `ensure_agent_runtime` docstring 警告的那个坑（chat/history/openai_compat 都改了，唯独这里漏了）。回归测试 `tests/test_agent_runtime_entry.py` 断言三个入口都落到专家 workspace。
- **插件卡片 XSS（第 6a 项）**：`Chat.tsx` 原先只用正则剥 `<script>`，`<img onerror>`/`<svg onload>`/`<iframe src=javascript:>` 全部绕过 —— 实测 8 种 payload **7 种绕过**（jsdom + DOMPurify 验证）。改用 DOMPurify 白名单。**踩坑**：DOMPurify 在 DOM 不受支持时**静默原样返回**（linkedom 下 `isSupported=undefined`，实测 8/8 全部放行），所以必须显式判 `DOMPurify.isSupported`，否则等于没消毒 —— 不支持时降级为纯文本渲染。
- **`manager.close()` 不再清空 Langfuse（第 6b 项）**：`close()` 被 15 处配置类端点调用（开关插件/存 env/改 provider/切模型），顺手 `_langfuse = None` 会让轨迹观测在**本进程内永久失效且无提示**。拆出 `shutdown()` 供 lifespan 收尾用。
- **前端流式可控（第 7a 项）**：`chatStream` 接受 `AbortSignal`；新增「停止生成」按钮；**组件卸载即 abort**（原先切到别的页 LLM 继续跑完，token 照扣）。补 `done` 缺失兜底：无 done/error 时把已累积片段落成消息 + 提示条「回复中断 / 重试」（原实现只清 `streamSegments`，半截回复随刷新消失）。修中文输入法回车即发送（`e.nativeEvent.isComposing`）。后端配套新增 `error` 终止帧（见下）。
- **壳交互（第 7b 项）**：`controlPanel.on('closed')` 不再 `app.quit()`（原先「关掉控制台」= 整个桌宠消失），改成清引用常驻，并新增**双击角色显示/隐藏控制台**（`toggle-control-panel` IPC）作为再打开入口；退出走 Cmd+Q。
  - ⚠️ **更正一条审计结论**：上一轮报告中「数字人窗口永久点击穿透、`set-ignore-mouse-events` 无调用方」是**错的** —— 调用方在 `js/model/vrm-model-interaction.js`（首次 grep 只覆盖了 `main.js`/`app.js`）。实际链路完整：`_setupVRMInteractivity` 的 mousemove 命中 `_screenHitBox`（每帧由骨骼投影更新）→ 悬停时 `ignore:false`。窗口初始 `ignore:true` 是**正确**设计（全屏透明窗口不穿透会吞掉整个桌面点击）。**本次未改点击穿透逻辑。**
- **阻塞调用迁出事件循环（第 8a 项）**：全部 `asyncio.to_thread` —— git clone（`subprocess` timeout 120s）/ FBX→VRMA（node，180s）/ SkillHub 与 Provider 探测（`httpx` 15–60s）/ Langfuse `auth_check`+`flush` / zip 解包与插件落盘 / **知识库 19 处 `_guard` 改成 async**（原来同步 sqlite + 文件 IO 直跑在 async 端点，传个大 PDF 就能卡住整个后端含 SSE）/ 模型缓存删除（`rmtree` 100MB+）/ 模型目录扫描 / 每轮 `_available_skill_keys()`（实测 23–34ms，读全部 SKILL.md）。
  - 回归测试 `test_slow_endpoint_does_not_block_health` 断言慢操作期间 `/api/health` 秒回，**已用「临时改回同步直调」验证该测试确有鉴别力**（改回即失败）。
  - ⚠️ 我上一轮写的「长阻塞操作**全部** to_thread」**不准确**（审查指出只搬了便宜的那个）：`assert_catalog_model`（字典查表，微秒级）当初转了，而 `delete_downloaded_model`（rmtree）、`reindex_all_documents`、`status_payload`/`is_model_downloaded`（目录遍历）、`client.flush()`（网络）都还留在循环上 —— **本轮已补齐**。剩下的同步开销主要是每轮 `plugin_service.tools()`。**2026-10-06 校正：此处的「约 55ms」复现不出来** —— 真实工作区实测 **5.6ms**（`list_all` 1.6 + `tool_owners` 1.7 + VRM 表情解析 1.1）。因此**不加缓存**（为 5ms 引入「插件启停/切模型/动画增删」的失效逻辑不划算，漏失效就是工具集过期这种难查 bug）；转而修了两处无失效风险的真浪费，合计省约 7.3ms/轮，见下方「第二批审计修复」。
  - ⚠️ 另一条我写错的：**「注册」不能 offload**。见下方「审查发现与修正」的 P1 竞态。
- **SSE 终止契约（第 8b 项）**：两个对话端点（`/api/agents/{id}/chat`、`/api/v1/chat/completions`）加 `aclosing` + `except` → 断连时关闭本层 SSE 生成器，异常时补发 `error` 帧（前端 `ChatEvent` 增 `error` 类型并解析）。
  - ⚠️ **机制说明要准确**（我上一轮写错过）：`aclose(frames)` 只把 `GeneratorExit` 抛进**本层**；两个 SSE 转换器都没有 try/finally，所以**不会同步传播到上游**。上游 LLM 流是在引用释放后由 async generator 终结器**异步**关闭的（实测 break 后同 tick 未关，让出约 10 次事件循环才关）。**效果成立（模型不会跑完），但不是「break 完立刻关」**。
  - 另：harness 自身对 LLM 失败是优雅降级的（把错误当 token 发出来再 done），所以 error 帧是异常逸出的安全网而非常规路径。
  - **实测提示**：harness 自身对 LLM 失败是**优雅降级**的（把 "Model call failed after 3 attempts…" 当 token 发出来再 `done`），所以 error 帧不是常规路径而是异常逸出的安全网；测试用强制抛异常验证。
- **每轮重写插件文件（第 9a 项）**：`ensure_vrm_avatar_plugin()` 每轮对话被 `load_avatar_instructions()` 调用并无条件重写 3 个文件（还多一次 DB 查询）。改成存在即跳过；实测 mtime 不再变化、每轮从 3 次 write_text 降到 0.3–0.6ms。
  - 取舍：内容不自动升级（改了 instructions 文案后已有安装保持旧内容，也因此不覆盖用户手改）。要强制更新删掉该文件即可。
  - ⚠️ 我上一轮写的依据「会触发壳 fs.watch 误报动作变更」**是错的**：壳只 watch `config.json`（main.js）与 `assets/animations/`（vrm-model-setup.js），**不 watch 插件目录**。真正依据只有 IO 浪费。
- **密钥脱敏与落盘（第 9b/9c 项）**：`GET/PUT /settings/env` 按键名判决敏（`KEY|TOKEN|SECRET|PASSWORD|PWD|CREDENTIAL`），非密钥键照常可读；PUT 收到含 `***` 的值视为「保持原值」，所以前端拿脱敏值回写不会覆盖真 key（与 providers 同语义）。新增 `infra/secret_file.py`：**原子写 + 0600**（临时文件 → fsync → chmod → `os.replace`），四个明文密钥文件（providers/env/langfuse/connectors）全部接入，读时对旧文件补 0600。原实现非原子 + 0644，写一半被杀会截断，而读侧一律静默回退默认值。
- **顺手修**：知识库索引任务 `asyncio.create_task` 返回值被丢弃（asyncio 只持弱引用，任务可能被 GC；异常只打印 "Task exception was never retrieved"）→ 存强引用 + done-callback 消费异常并记 WARNING。实测确认修复前日志有该警告、修复后变成明确的「文档索引任务失败」告警且文档状态机不变。

## P0 地基（2026-10-06，用户指令「开始 P0 地基」）

> 依据 `docs/next-steps.md` P0 六项。全部完成后：后端 138 测试绿（原 136 + streaming guard 2）、前端 56 测试绿、build 成功、壳重启验证通过。**P0 全部改动仍在 working tree，尚未 commit**（提交粒度可每项一 commit 或合并，取决于后续决定）。

- **P0-1 分层违规清零**：grep 实测 infra 反向依赖 domain 实为 **3 处**（文档只记 2）：market.py 依赖 plugin_service + 内部 `app.domain.importer` 是同层违规。新建 `app/storage/paths.py` 统一路径解析；`domain/importer.py` 整体迁移为 `app/infra/importers.py`（文件操作属基础设施）；技能解析收敛到 `read_skill_manifest`；`list_market(installed)` 参数化。删旧文件含 pyc。
- **P0-2 transport/api.py 拆分**：1658 行 → 7 个域文件（chat/agents/avatar/connectors/plugins/settings/skills）+ `runtime.py`（ensure_agent_runtime/all_skills_dirs 共享）+ `models.py`。`git show HEAD` 与 7 文件正则端点 diff：**71 端点路径集合完全一致**。坑：删 plugins 段时误删 chat 域 `_sync_plugin_row`、settings 域 `_langfuse_probe`（已恢复）；agents 拆后 chat_api 残留 `_all_skills_dirs` 导致 5 个 NameError（改走 runtime 导入）。
- **P0-3 前端组件基元**：PageCard/EntityGrid/EmptyState/ErrorState/SectionToolbar + 12 条测试（新装 `@testing-library/react`、`@testing-library/user-event`）。坑：vitest 未开 globals 需手动 `afterEach(cleanup)`；antd 占位图是 SVG 非 img；EntityGrid 空数组泛型推断 never。
- **P0-4 拆 Chat.tsx**（983→~430 行）：`useChatStream`（流式状态机 hook + `nextSegmentId`/`MODEL_AUTO` 哨兵迁入 + abort 生命周期 + 重试发回原会话）/ `MessageBubble`（展示组件全量搬入，`SegmentView` 导出复用）/ `MessageList`（bodyRef 类型 `RefObject<HTMLDivElement>`，勿带 `| null`）/ `Composer`（Select onChange=选模型、chip 移除=回自动，分开回调）。56 前端测试绿 + build 成功。
- **P0-5 流式校验结构性保证**：新建 `app/transport/streaming.py::stream_response`（先校验可抛 HTTPException → 再进 gen；SSE_HEADERS 统一），三处 StreamingResponse（chat_api/openai_compat/avatar_api）全部改走该出口；`openai_compat` 的 `ensure_agent_runtime` **从 gen 内挪到 gen 前**（消除"进流后才构造运行时"隐患）。`tests/test_streaming_guard.py` 两条**源码扫描**测试（非假测试）：transport 层禁止裸构造 `StreamingResponse(`、`async def gen` 内禁止 `raise HTTPException`。HANDOVER.md §6 与 AGENT.md 坑条均改为「已由结构性保证覆盖」。
- **P0-6 记忆移入对话侧栏 + 导航三分组**：`App.tsx` 导航改三分组（对话 ｜ 能力：专家/插件/技能/连接器/知识库 ｜ 系统：AI 数字人/设置/存储），**记忆不再占平级菜单**；完整记忆管理抽成 `src/pages/memory/MemoryView.tsx`（遗忘/编辑记忆文件/统计/已遗忘审计全保留），Chat 页标题栏加「记忆」按钮 → 抽屉展示**当前对话专家**的记忆（核心承诺在主界面可见）。`MemoryPage` 留作 hash 直达兜底。注意：antd Menu items 类型要求 `data-*` 索引签名，NavLeaf 接口需带 `[k: \`data-${string}\`]: any`。

## 四流并行交付 + 第二批修复（2026-10-06 下午）

> 用户指令「这几个一起做」：提交 + 可移植性 + 打包 + 记忆可视化 + 设计 token + 零散风险。> 落地为 12 个 commit；测试基线 **后端 46→136 例、前端 0→44 例**；`make check` 全绿。

### 交付

- **可移植性**（`9187a96`）：`make start` 先构建前端（dist 不入库 → 否则全新克隆壳面板白屏）；
  README 的 `.env` 从 `backend/` 改回**仓库根**（`config.py` 的 `REPO_ROOT=parents[2]` 只读根 `.env`，
  而壳/uvicorn 的 cwd 都在 `backend/` → 放错位置会被静默忽略，表现为「配了 key 却提示未设置」）；
  补 `LICENSE`(MIT)；`probe_harness.py` 的 `.env` 路径算错一级（**从来没读到过仓库根 .env**）一并修；
  代码/配置个人绝对路径 24 处 → 0（`AGENT.md`/`docs` 历史记录故意保留）。
- **壳打包链 + 安全基线**（`6ec8f2a`）：electron-builder（`pack` 产出 `Nuomi.app` 249MB / asar 24MB，
  实测包内无 `tools/` 的 12MB FBX2glTF、无 `node_modules/electron`）；`npm run icon` 出 icns；
  **单实例锁用真双进程验证**；CSP 探针实测（`file://` 读本地 VRM 与 `127.0.0.1` fetch 放行，
  远端脚本/远端 fetch 被拒）；`will-navigate` + `setWindowOpenHandler` 导航封锁；
  **模型路径自解析**（config 里的绝对路径失效时向后端 `/api/avatar/models` 取激活模型并回写，
  打包态 config 只读则用 `--nuomi-model` 下发给渲染进程；都拿不到弹可读错误框而非静默白屏）。
  实机日志确认 `已从后端解析到激活模型 → 回写 → VRM 加载成功`。
- **记忆可视化**（`8dd7fdf`）：「记得你」是这个产品的定位，但记忆此前只有几个 `.md`、用户在控制台
  看不到自己"被记住了什么"。新增 `/api/agents/{id}/memory*` + 控制台「记忆」页（断言/原话/来源会话/
  实体/人设文件查看编辑）。**遗忘走引擎公开 API** `Memory.deprecate_atom`（不是删行）—— 它会原子地写
  `deprecated_at`、实体 `atom_count` 减一、实体页标脏、追加 journal；直接 DELETE 会让实体页继续带着
  "已被遗忘的证据"注入下一轮。真实数据实测：糯米 21 条 / 10 个对象 / 188 条原始事件。
  - ⚠️ **差点上线的坑**：记忆表前缀按**专家名**推导且各不相同（糯米 `__`、工作狂 `___`、
    小通 · 通用助手 `_________`）→ 硬编码 `___atoms` 只对一个专家成立。改为从 `sqlite_master` 推导，
    并加「不同名字的专家各自读得到」的回归测试。
- **设计 token**（`32fad76`）：`DESIGN.md` 描述的是**从未实现**的深色+DeepSeek 蓝+`styles.css` :root
  （实际是浅色+琥珀、全仓无 CSS 变量）→ 与 DESIGN.md 同样的病。现在 token **只在 `src/theme.ts` 定义一次**
  （TS 类型约束），启动注入成 CSS 变量，组件用 `var(--x)`；只有一个来源 → 漂移结构上不可能。
  `DESIGN.md` 重写为描述现实 + 如实欠账（60 处裸 hex / 278 处内联样式 / 装饰色板三份重复）。
- **前端测试基建 + 7 项体验软点**（`de72f9c`）：vitest+jsdom，XSS 净化 13 例（**鉴别力已验证**：
  换回旧「只正则剥 `<script>`」实现 → 9 例失败）、SSE 分帧 13 例、引用解析 5 例、片段合并 6 例。
  软点：`STATUS_TAG` 无兜底 + 顶层 ErrorBoundary、流式片段索引 key、原地改 state、每 token 都 `scrollTo`
  （用户无法上翻）、模型下载按钮永久 loading、多选上传 N 并发、编辑器静默失败 + 无请求守卫。
- **上传限流**：5 处裸 `await file.read()`（知识库那 100MB 上限甚至是**读完才判**）统一走 `read_upload`
  （先看 `file.size`，再分块、超限立刻 413）；实测 51MB → 413。

### 第二批审计修复（`a309a7d`）

- **SQLite 连接从不关闭（最要命）**：`sqlite3.Connection` 自带的 `with` 只提交/回滚、**不关闭连接** →
  全仓 50+ 处 `with db.connect() as conn:` 每次漏一个 fd，而服务整天常驻。`connect()` 改
  `@contextmanager`（提交/回滚/**必然 close**），57 处调用点零改动；`knowledge/index.py` sidecar 同修。
  实测 200 次调用 fd 稳定（改前每次 +1），commit/rollback 语义各有测试。
- **`_TOOL_OWNERS` 模块级全局 → 请求局部**：并发对话会互相覆盖工具→插件来源映射（A 的 tool_call 帧
  带上 B 的插件，前端徽标错乱）。
- **工具装配开销**：见上面对 55ms 的校正；修了「`ensure_agent_runtime` 即使命中缓存也**急切求值**
  `plugin_service.tools()`」与「`tools()`+`tool_owners()` 各查一次 `list_all()`」（新增
  `tools_and_owners()` 只查一次）。
- **数字人事件队列满静默丢最新** → 改丢**最旧**（动作是"最新有效"语义）+ 计数 + 限频告警；
  SSE 长连接加 15s 心跳注释帧。**坑**：`asyncio.wait_for` 不能包在 async generator **外面**做超时
  （取消会顺着 `await q.get()` 抛进生成器把它终结、长连接断），必须写在生成器内部。
- **历史分页两条路径语义不一致**：`page()` 是倒序分页（从最新往前），而 pending/backfill 路径
  `msgs[-limit:]` **忽略 offset**，且投影为空时还会回落重算 → 翻页重复拿同一批尾部消息。
  统一为「从最新往前取 limit 条，offset 再往前跳」+ `limit/offset` 校验。
  - ⚠️ **这条测试第一版没有鉴别力**：同一线程第二次请求已被标 ready，走的不是 pending 分支，
    把旧实现改回去照样通过 → 改成用**两个独立线程**逼出 pending 路径，并实测确认旧实现会失败。
- **顺手**：`plugin_service.sync()` 原只 `INSERT OR IGNORE`、从不清理目录已消失的残留行
  （手动删插件目录会留下点不开也没工具的幽灵条目，违背"目录即 source of truth"）→ 现在会清掉。
  实测用户现有库无幽灵行、清理不会误删。

### 文档治理

- 旧的 `placeholder-priorities.md` **已被 `docs/next-steps.md` 取代并删除（2026-10-06 晚）**：两份规划文档必然漂移，只留新的那一份。旧版是 v0.12 残留，排的 12 项里 Tauri 打包、`plugins/voice` STT、
  文件面板↔fs 工具、mem0、subagent、Supervisor 二层在 **v0.13 之后全部不存在**（逐项 grep 核实命中数为 0）。
  一份排着"不存在的东西"的待办表比没有更糟 → 改为按「对单机日用的实际影响」排序，并写死规矩：
  **写进待办前先 grep 确认落地点存在**。
- `docs/HANDOVER.md`：§7 补 7 行能力域、§8 重写为状态台账（本轮已完成 / 仍待办 / **明确不做**）、
  §6 补 10 条本轮踩坑、§9 补本轮 12 个 commit 与测试基线。
- `DESIGN.md` 重写为描述现实（见上）。

## 分发范围决策（2026-10-06 用户拍板）

- **不做分发。** 没有把糯米发布到其他 Mac 的计划；发布需要花钱买 Apple Developer 账号
  （codesign + notarize），因此**签名 / 公证 / 自动更新 / 首启向导一律不做**，不要再排这些待办。
- **打包链保留但只作本机验证**：electron-builder 能出 `Nuomi.app`（249MB，asar 24MB）、`npm run icon`
  能出 icns、单实例锁与 CSP 做过真实验证 —— 这些是有价值的回归手段。但**产物不是可独立运行的应用**：
  它不含后端，`ensureBackend()` 按 `__dirname/../../backend` 找 venv，打包态 `__dirname` 在 asar 内
  → 找不到 → 退回 `python3` 失败并等满 30s。所以**打包产物仅在「后端已在跑」时可用**。
- **日常使用一律 `make start`**（壳启动自动拉起后端），不走 `.app`。
- 若将来改主意要做独立 App，第一件事不是签名而是**自带 Python 运行时**（PyInstaller / embeddable
  Python），细节见 `shells/nuomi-avatar/README.md` 的「打包与分发」5 条前置。

## 审查发现与修正（2026-10-06，独立对抗性审查后）

- **P1 竞态（我引入的，已修）**：第 8a 项把 `plugin_service.sync()` 也丢进了 `asyncio.to_thread`，但 `PluginRegistry` 是进程级单例、`load_all()` 是「先 `clear()` 再逐个注册」→ 工作线程 sync 期间，事件循环上的 `plugin_service.tools()` 会读到**空注册表**。实测并发读观察到 `[0,1,2,3]`，即**该轮对话拿不到任何插件工具且无日志**。修复：**文件操作 offload、注册回到事件循环**（`_import_plugin_from_root` 只落盘返回 plugin_id；`transport/api.py` 的 `_sync_plugin_row` 在循环上 sync）。`tests/test_plugin_import.py` 用「记录两个阶段的线程名」锁死分工，并已验证把 sync 改回 to_thread 该用例立刻失败。
- **P2 脱敏哨兵曾误伤（已修）**：`env_store.save` 原用「值含 `***`」判断「前端未改动」，会把用户**真的**改成含 `***` 的新密钥静默还原成旧值。改为**精确等于 `mask_value(旧值)`**；`_SECRET_KEY_RE` 也补了词边界锚定（原先 `MONKEY`/`KEYWORD_X`/`TOKENIZER_PATH` 会被误判成密钥）。
- **P2 前端通知（已修）**：收到 `error` 帧后原会再叠加一条「未收到完成帧」横幅（且与事实相反）→ 已把 error 视为终态、只报一次；组件卸载触发的 abort 原会弹「已停止生成」假提示 → 用 `unmountedRef` 区分；「重试」原用 `activeThread` 而非该轮自己的 threadId → 切会话后会发错线程，已修。
- **P2 壳忽略 error 帧（已修）**：`app.js` 只解析 `chunk.choices?.[0]`，`{"error":...}` 被 `if(!choice) continue` 丢弃 → 对话失败时用户看不到任何原因。已加处理。
- **✅ 壳的定位（用户 2026-10-06 明确确认，勿改）**：壳**只订阅对话消息**，不做对话入口 —— 全仓唯一的 POST `callLLMStream` 是死代码，`index.html` 也没有输入控件，壳对后端的实时请求只有 `GET /api/avatar/events`（SSE 读，不需 token）。
  - **不要把「数字人不能主动/被搭话」当缺陷**，也不要在壳里加聊天输入 —— 这是产品决策：对话发生在控制台，壳只负责形象与表现（动作/表情/语音播报）。
  - 因此第 0 步给壳加的 token 接线是**预防性**的：恢复壳内对话、或外部 OpenAI 兼容客户端接 `/api/v1/chat/completions` 时会被守卫 403，届时必须带 `X-Nuomi-Token`（同源 `GET /api/session-token` 获取）。
  - 启动壳时注意：**从 Electron 宿主环境（如 DSH）的终端里 `npm start` 会崩** —— 宿主导出了 `ELECTRON_RUN_AS_NODE=1`，electron 会退化成纯 Node，报 `Cannot read properties of undefined (reading 'getAppPath')`。启动前 unset 该变量即可（本文件所在会话实测踩到）。
- **顺手修**：`app.on('activate')` 兜底（关面板不再退出后，若数字人开关为关会出现「进程活着但无窗口」，Dock 点击无反应）。

## 第 0 步安全与门禁加固（2026-10-06）

> 背景：三份只读审计（后端/前端/壳）交叉结论——架构分层真实落地，但**本机 API 零鉴权 + multipart 绕过 CORS 预检 + 插件隐式 pip install** 构成完整 RCE 链；且 HEAD 上门禁假绿。本次做掉「第 0 步」三项。

- **本机访问守卫（新增 `backend/app/infra/local_guard.py`）**：纯 ASGI 中间件（只读请求头，不碰 body，SSE/上传不受影响），三道防线——① `Host` 白名单（127.0.0.1/localhost/::1/[::1]，挡 DNS rebinding）；② 带 `Origin` 时必须本机来源（`Origin: null` 给 `file://` 壳放行，但 `/api/session-token` 连 `null` 也拒）；③ `/api/*` 的 POST/PUT/PATCH/DELETE 必须带 `X-Nuomi-Token`（或 `Authorization: Bearer`）。token 每进程随机生成，`NUOMI_API_TOKEN` 可覆盖；同源 `GET /api/session-token` 获取。**威胁模型只覆盖「浏览器里的第三方页面」**——本机其它进程本来就能读工作区明文密钥，不以此为目标。
- **为什么必须用 token 而不是只查 Origin**：`multipart/form-data` 属 CORS 简单请求，不触发预检，请求会真实到达；`Origin: null`（沙箱 iframe）又必须给壳放行 → 只有 token 能兜住这条路径。
- **客户端接线**：控制台 `api.ts` 懒取 token 并缓存（`authedFetch` 在 403 时清缓存重取重试一次）；壳走主进程 Node http（无 CORS 约束）取 token → `ipcMain.handle('api-token'/'refresh-api-token')` → `app.js` 的 `postJsonWithToken`。**重试逻辑是必需的**：token 每进程轮换，后端重启后不刷新会让所有写操作一直 403。
- **向后兼容已验证**：新 dist 对旧后端（`/api/session-token` 404）静默降级为不带 header，行为不变——所以先重启后端还是先换前端都不会互相打断。
- **插件加载不再隐式装依赖**：`plugin_service.sync()` 改 `load_all(plugins_dir, install_deps=False)`。octop loader 原本会在插件声明 `requires`/`requirements.txt` 时自动 `pip install`，等于把安装脚本执行权交给插件作者。
- **`main.py` 的 `logger` 未定义（ruff F821 + mypy 都报过）**：`_sync_langfuse` 的 except 分支引用未定义的 `logger` → 观测配置写错会把整个后端启动搞崩（该调用没被 try 包住）。已补 `logging.getLogger(__name__)` + lifespan 加 `_safe()` 单步兜底。
- **harness 日志重定向（顺手修「数据根不单一」）**：harness 默认写 `~/.octop-harness/logs`，在 NUOMI_HOME 之外；隔离数据根的测试会越界写用户 HOME（无权限直接 `PermissionError`，实测就是那 2 个失败用例的**第二层**根因）。新增 `configure_harness_logging()` 用 `setup_logging({data_root}/logs/octop-harness)`，**必须在首次构造 HarnessAgent 之前调用**（`ensure_logging()` 见到已有同包 handler 就不再装默认的）。
- **测试去网络化**：conftest 内建 `providers.json`（dummy base_url，不再依赖本机 `.env` 密钥）+ 固定 `NUOMI_API_TOKEN` + `base_url=http://127.0.0.1:8000`（过 Host 白名单）；新增 `stub_llm` fixture 替换两个 transport 模块里的 `stream_chat`——路由级用例本来只断言状态码（自述"不校验推理内容"），真实打模型让每个用例 30s+ 且真花钱。**全量 46→59 例，73s→4.5s**。
- **门禁变成真的**：`make check = lint + format-check + typecheck + test + build + shell-check`；前端 `build` 改回 `tsc -b && vite build`（CI 步骤名一直这么写、实际只跑 vite，3 个类型错误长期潜伏）；lint/format 覆盖范围从 `app` 扩到 `app tests`；CI 新增 shell job（`node --check` 15 个脚本）。**HEAD 修复前实测**：ruff 10 错、format 15 文件、mypy 2 错、pytest 2 failed。
- **顺手修掉的类型错误不是洁癖**：`AvatarModel` 少了 `expressions_have_data` → `AvatarModels.tsx` 里「该模型无表情变形数据」的告警**永远不显示**（真实功能失效）。

## 教训（保留，跨版本有效）

- **MCP（langchain-mcp-adapters 0.3.x）**：`MultiServerMCPClient({"<s>": StdioConnection(transport="stdio", command=..., args=..., env=...)})`；**不是上下文管理器**，直接 `tools = await client.get_tools()`；StdioConnection 必须带 `transport` 键；env 不默认继承，需显式 `env=dict(os.environ)`。
- **DeepSeek 工具调用可靠**；本地小模型（Qwen3.5-2B）工具调用不稳定，仅适合纯对话。
- **Agent 实例缓存必须统一构造入口（2026-10-04 会话历史丢失 bug）**：`HarnessManager.get_agent(agent_id)` 按 agent_id 单例缓存，构造参数（workspace_dir/插件工具/技能目录/MCP）只在首次构造生效。`GET /agents/{id}/chat/history` 曾漏传 `workspace_dir`，页面加载自动拉历史时抢先把「全局根 memory.sqlite + 无工具」的残缺实例缓存 → 专家工作区历史读不到、对话错写全局根库。**修复**：`transport/api.py` 加 `ensure_agent_runtime(agent_row)` 统一入口，控制台对话/历史/AI 数字人 OpenAI 兼容三端点都走它；manager 缓存命中时对 workspace_dir 漂移打 warning。
- **octop-memory checkpoint 迁移三表齐搬（2026-10-04）**：会话历史不是只存 `checkpoints`+`writes` 两表——checkpoint 内容 blob 按 digest 存在 `hm_checkpoint_blobs(digest PK, type, value)`。只搬前两表会报 `ValueError: Missing checkpoint content; restore the matching database backup`，且 aget_history 静默返回 []（对话一启动才炸）。跨库迁移会话必须 **checkpoints + writes + hm_checkpoint_blobs 三表**一起搬（blob 按 digest 主键，INSERT OR IGNORE 合并即可）。
- **`make stop` 会回收 :8000 后端进程**：重启AI 数字人壳前先 `make stop` 再补起后端（`cd backend && nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/nuomi-backend.log 2>&1 &`）。
- **壳与后端同命令重启会竞态（2026-10-04 实测）**：一条命令里 pkill 后端 + pkill 壳 + 同时启动，壳可能读到中间态 config（加载成错误的 Live2D 模型，日志"模型类型: live2d"但 config 是 vrm）。**规范：后端先起来（health ok），再单独启动壳**。壳正常日志看 `/tmp/nuomi-avatar-launch.log`（npm start 重定向，含 renderer 行）；`/tmp/nuomi-avatar-shell.log` 是另一份可能混杂旧段的日志，以 launch.log 为准。
- **消息流 = 有序片段（2026-10-04）**：对话不再是「正文气泡 + 气泡上方一堆工具折叠」。history 接口与前端统一返回/渲染 `Segment[]`：`user / reasoning（深度思考）/ tool_call / tool_result / text` 按真实时间顺序穿插（思考→调工具→看结果→正文）。harness 有 `reasoning` 事件类型（AgentEventType.REASONING），stream_chat/stream_octop_sse 已透传；history 端点从 BaseMessage 重建（human→user；ai→reasoning_content + content + tool_calls；ToolMessage→tool_result）。前端 Chat.tsx 流式累积时相邻同类合并（思考累积思考、正文累积正文），切会话回来工具链与思考不再丢失。
- **改前端后必须 `npm run build`（2026-10-04 踩坑）**：浏览器 :5173 走 vite dev（源码热更），但**AI 数字人壳控制台加载的是后端 :8000/console/，挂载 `frontend/dist` 静态包**（main.py StaticFiles）。只改源码不 build，壳里跑的还是旧 bundle，表现为"web 对、桌面壳不对"。前端改动后必跑 `cd frontend && npm run build`（StaticFiles 实时读盘，无需重启后端；壳控制台窗口重载即可）。

## VRM 3D 表现层进度（2026-10-04）

- **已打通**：three.js 0.169 + @pixiv/three-vrm 3.3.0 + three-vrm-animation 3.3.0
- **模型**：`/Users/superman/Nuomi/models/3D/6309260419351179234.vrm`（CC0，黑发水手服少女，VRM 0.x，17 个 blend shape）
- **后端**：`enrich_model` 加 VRM 分支——不走 AI 分析，直接生成通用动作插件（7 表情 + 16 动作：wave_hand/nod/shake_head/tilt_head/raise_right/left_hand/look_left/right/up/down/hands_on_hips/shrug/dance/jump/spin/stretch）
- **壳侧**：`vrm-model-adapter.js` 实现 motion() 骨骼动画（手写关键帧+easing）+ expression() blend shape 控制 + AnimationMixer 支持 .vrma 文件
- **SSE 广播**：`_resolve_avatar_action` 改成读 `plugins/<model_id>/actions.json`（VRM 模型 list_models() 里 actions={}）
- **插件互斥 bug 修复**：切到无插件模型时所有模型插件全禁用（之前只在新模型有插件时才互斥）
- **当前局限**：~~手写骨骼动画不自然（硬编码角度，无膝盖/手腕细节）~~ **已过时**：手写动画已删（2026-10-05"动作清单只以 VRMA 为准"），只播 VRMA 文件
- **Mixamo FBX → VRMA 转换链路已走通（2026-10-04）**：
  - 工具链：`shells/nuomi-avatar/tools/fbx2vrma/`（npm `fbx2vrma-converter` 1.0.2 + FBX2glTF 0.9.7 darwin-x64 二进制）。**arm64 机器无原生 FBX2glTF**（官方仅 darwin-x64），需 Rosetta 2（`softwareupdate --install-rosetta --agree-to-license` 已装）；npm install 用 `--ignore-scripts`（其 setup.sh postinstall 会失败）
  - 命令：`node node_modules/fbx2vrma-converter/fbx2vrma-converter.js -i <in.fbx> -o <out.vrma>`——自动 Mixamo→VRM humanoid 骨骼映射（mixamorig:* → hips/spine/chest...），默认 30fps
  - 产物：`shells/nuomi-avatar/assets/animations/elbow_punch.vrma`（2.25s、22 骨骼、55 帧、113KB）
  - 验证：`tools/fbx2vrma/verify-vrma.js`（Node 直跑，与壳 loadVRMA 同款加载链：GLTFLoader+VRMLoaderPlugin 载 VRM 模型 → VRMAnimationLoaderPlugin 载 .vrma → createVRMAnimationClip → 22 tracks 标准 humanoid 骨骼 + Head 采样四元数差异确认驱动）。**Node 环境需浏览器 polyfill：self/createImageBitmap/URL.createObjectURL/ProgressEvent**（脚本已内置，不渲染纹理）
- **VRMA 播放链路已接入（2026-10-04，端到端验证通过）**：
  - 壳 `vrm-model-setup.js` 初始化时自动扫描 `assets/animations/*.vrma`，文件名去扩展名注册（await loadVRMA）
  - `vrm-model-adapter.js`：loadVRMA 改为 **fs 读文件 + loader.parse**（与 _loadVRM 同模式，原 loadAsync 走 fetch 无法加载 file://，这是它一直没接上的根因）；`motion(name)` **优先播 animations[name]（vrma）**，无则回退手写骨骼动画；playAnimation 一次性动画播完自动 fadeOut 回 idle（不卡最后一帧）
  - 后端 `_enrich_vrm` 动作清单加 `elbow_punch`（肘击攻击），重启后 `enrich_model('6309260419351179234')` 重新生成插件（**注意：启动时 generate_all_model_plugins 只用现有 actions.json 生成插件、不重新 enrich**，改动作清单后需手动调 enrich_model 或删 actions.json 后切模型）
  - 端到端实测：对话"对我来一记肘击" → LLM 调 elbow_punch 工具 → tool_result {motion, expressions, label} → SSE avatar_action → 壳 [VRM动画] 播放 elbow_punch ✓
- **表情工具修复（2026-10-04）**：原 `_generate_semantic_plugin` 只生成动作工具、不读 actions.json 的 expressions——LLM 无表情接口（糯米反馈"只有动作，expressions 恒空"）。已修：
  - `_generate_semantic_plugin(model_id, actions, expressions)` 增加表情工具 `set_expression_<name>`（_make_expression_player 返回 {motion: None, expressions: [name], label}，与动作 payload 同构，壳播放链路零改动）；plugin.yaml/instructions.md 同步带表情清单
  - `_resolve_avatar_action`（api.py）加表情反查（tool_name.startswith("set_expression_")）
  - `generate_model_plugin` 表情以 **plugins/<id>/actions.json 的 expressions 为权威**（fallback model dict）
  - **教训：改动作/表情清单后要 enrich_model 重新生成插件（generate_all_model_plugins 不重新 enrich）**

## 方案 B 实施完成（2026-10-04，端到端验证通过）

- **单共享插件 vrm-avatar（删模型插件互斥）**：工作区 `plugins/vrm-avatar/`（plugin.yaml id=vrm-avatar + 空 main.py + instructions.md），由 `ensure_vrm_avatar_plugin()` 在启动时自动生成；**启停只绑定AI 数字人开关**（set_avatar_status → set_enabled(vrm-avatar) + release；启动时 `_ensure_model_plugins` 对齐 get_avatar_enabled()）。`switch_avatar_model` 不再遍历互斥，只 switch_model + release shell agent。DB 里 6 条旧模型插件记录已 DELETE（剩 weather + vrm-avatar）。**实测：关AI 数字人 → tools=[]，开AI 数字人 → [do_action, set_expression] 恢复**
- **动态工具装配（改 `PluginService.tools()` 源码，不动 octop 基础库）**：`_avatar_dynamic_tools(global_enabled)` 在 vrm-avatar 启用时构造 `do_action` + `set_expression` 两个 StructuredTool——动作 enum 来自 `list_avatar_actions()`（18 内置 + assets/animations/*.vrma 扫描，**放文件即出现、删即消失，零重启**）；表情 enum 来自 `list_avatar_expressions()`（GLB 12 字节头 + JSON chunk 解析，无 three 依赖）。`_resolve_avatar_action` 只认这两个工具名，解析 args 取 action/expression 字段
- **物理删 2D 全部完成**：壳（libs/ 5 个 live2d/pixi 文件、layer1-liveness.js、unified-interaction-controller.js、model-interaction.js×2、index.html 5 个 script、app.js 全部 Live2D/GIF/情绪映射/Layer1 死代码、unified-model-adapter.js 删 Live2D 兼容层只留 VRM 直通、model-scanner.js 重写只留 _scanVRM）；后端（list_models 2D 扫描、_seed_builtin_models、generate_model_plugin/_generate_semantic_plugin 整块删除）；前端（AvatarModels/Plugins 文案+删 model_plugin 字段，build 通过）；资产（/Users/superman/Nuomi/models/2D 物理删、仓库 assets/models/2D git rm、6 个旧模型插件目录删）。**app.js 兜底 modelType 已改 'vrm'**
- **表情映射关键事实（本次根因）**：壳端 three-vrm 的 ExpressionManager 键 = **VRM 1.0 标准名**（neutral/aa/ih/ou/ee/oh/blink/happy/angry/sad/relaxed/lookUp/lookDown/lookLeft/lookRight/blinkLeft/blinkRight）。three-vrm `_v0Import` 用 `v0v1PresetNameMap` 把 0.x preset 变体映射到标准名（a→aa、joy→happy、sorrow→sad、fun→relaxed、lookup→lookUp、blink_l→blinkLeft…），**非标准 preset（joy/sorrow/lookup）不在映射表则回退原始 name（Joy/…大写语义名）**。后端 `_vrm_expr_name()` 同步这张映射表（`_V0_TO_V1` + `_EXPRESSION_ALIASES` 兜底自定义名），保证后端 enum 与壳端 setValue 键一致——**这就是之前"表情看不出变化"的根因：后端返回 joy/sorrow/fun/lookup，壳 setValue 不命中**。壳适配器另加 `_exprByLower` 小写索引 + `_resolveExpression()`，大小写不敏感
- **端到端实测（2026-10-04）**：对话"做个生气的表情" → tool_call `set_expression {"expression":"angry"}` → tool_result `{"motion":null,"expressions":["angry"],"label":"生气"}` → 壳日志 `AI 数字人动作: 生气 / AI 数字人表情: angry`（无"不可用"报错）；"向我挥手打招呼" → `do_action {"action":"wave_hand"}` → `{"motion":"wave_hand","label":"挥手打招呼"}` ✓
- **重启规范（沿用）**：后端 pkill -9 杀干净再启（旧进程会占 8000 导致新进程 bind 失败）；**后端 health ok 后再单独启壳**（`cd shells/nuomi-avatar && nohup npm start > /tmp/nuomi-avatar-launch.log 2>&1 &`）；改壳代码后必须重启壳验证
- **遗留**：~~表情观感幅度（权重 setValue 1.0/恢复 3s）用户已搁置，后续可调 playAvatarExpression 的 EXPRESSION_RECOVERY_MS 与权重~~ → **已废弃（2026-10-05 用户拍板）**：不同模型表情数据不同（有/无 binds），幅度调整无统一意义，保持现状；Git 提交本次全部改动

## AI 数字人改名 + 丢弃 myspy + 导入预览 + 3D 观感（2026-10-04 深夜）

- **全量改名（桌宠→AI 数字人）**：后端 `app/domain/pet`→`avatar`、`app/infra/pet_events.py`→`avatar_events.py`（事件 type 改 `avatar_action`/`avatar_status`）、API `/api/pet/*`→`/api/avatar/*`；壳 `shells/myspy`→`shells/nuomi-avatar`（git mv，**myspy 完全丢弃**，自研壳）、IPC start-pet→start-avatar 等、petWindow→avatarWindow；前端 PetModels.tsx→AvatarModels.tsx、菜单「桌宠」→「AI 数字人」；插件 vrm-pet→vrm-avatar（目录 mv + DB UPDATE + plugin.yaml 手改）；docs/README/Makefile/AGENT.md 全量换词。54 文件 131 行变化，26 tests/ruff/mypy 全过，重启验证 `/api/avatar/models` 正常、壳从新目录加载 VRM 正常
- **改名遗漏修复（2 处）**：壳 app.js SSE 订阅 `ev.type === 'pet_action'`/`'pet_status'` 未换 → 改 `avatar_action`/`avatar_status`（不改则预览广播壳收不到）；playPetActionPayload→playAvatarActionPayload
- **3D 观感修复（#12）**：renderer.shadowMap(PCFSoft)+主光 castShadow(1024/bias -0.001)+暖色补光；vrmGroup 全 mesh castShadow/receiveShadow；渲染循环慢速自转（_orbitTheta += delta*0.1，鼠标悬停暂停、右键拖拽后暂停 8s）；右键旋转灵敏度 0.005→0.012。壳重启验证通过
- **导入/预览（#14，后端 3 端点 + 前端 UI + 壳 watch）**：
  - `POST /api/avatar/models/import`（UploadFile .vrm → 工作区 models/3D/，返回最新清单，切模型零重启）
  - `POST /api/avatar/animations/import`（UploadFile .fbx → 临时文件 → `node fbx2vrma-converter.js -i -o`（cwd=tools/fbx2vrma，180s 超时）→ assets/animations/<stem>.vrma；ValueError→400，FileNotFound/Timeout/RuntimeError→500）
  - `POST /api/avatar/preview`（body {kind:"action"|"expression", name} → preview_payload() → avatar_events.publish → SSE 广播，数字人窗口立即实播，无需对话）
  - 壳 vrm-model-setup.js **fs.watch assets/animations**：新 .vrma 自动 loadVRMA 注册（已存在跳过），导入动作零重启
  - 前端 AvatarModels.tsx：顶部「导入 VRM 模型」「导入动作（Mixamo FBX）」按钮（Upload + upload() 辅助函数）；激活模型卡片的动作/表情 Tag 内嵌 ▶ 预览按钮（stopPropagation + POST /avatar/preview）。**动作/表情预览只在激活模型卡片显示**（数字人窗口播的是激活模型）
  - 端到端实测：POST /avatar/preview action=wave_hand → 壳日志 `AI 数字人动作: 挥手打招呼 / [VRM动作] wave_hand` ✓；expression=angry → `AI 数字人表情: angry` ✓；导入 VRM（test_import_vrm 导入→清单出现→DELETE 清理）✓；导入 Body Block.fbx → 转换 → watch 注册 → 预览播放 `[VRM动画] 播放 Body Block` ✓
- **动作清单口径**：`/api/avatar/models` 的 models[].actions 仍恒 {}（list_models 硬编码），动作清单权威在 list_avatar_actions()（全局扫描 18 内置 + assets/animations/*.vrma）；预览按钮直接调 list_avatar_actions 覆盖的动作名。**已定论（2026-10-05）**：models[].actions 填**全局 VRMA 动作清单**（list_models 注释明确"所有模型共用，放文件即出现、删即消失"）——per-model vs 全局已决策为全局
- **遗留**：~~表情观感幅度（用户搁置）~~ → **已废弃（2026-10-05 用户拍板）**；动作名含空格（如 "Body Block"）可作 enum 值但较丑，后续可规范化（fbx stem 空格→下划线）→ **用户确认保持现状**；本轮已 git commit
- **遗留（2026-10-05 更新）**：VRMA_01~07（VRoid 官方免费动画）未导入 → **已废弃**（用户拍板"模型资产补全不需要做了，已抛弃"）；~~动作名空格规范化仍待办~~ → **已定论（2026-10-05）**：保持现状（Mixamo 原名，enum 合法可播）

## 删内置动作 + idle 待机动画（2026-10-05）

- **动作清单只以 VRMA 为准（用户拍板"之前的动作都删掉"）**：`list_avatar_actions()` 删 18 个内置手写动作（wave_hand/nod/dance/…），只扫 `assets/animations/*.vrma`（放文件即出现、删即消失）；ACTION_LABELS 降级为 label 中文映射（未知回退文件名）；壳 `motion()` 删手写骨骼动画 switch + animate 辅助（死代码），只播已注册 VRMA，缺失 console.warn
- **idle 待机（VRoid Hub 预览同款思路）**：VRM 文件本身**不带动画**（0.x/1.0 均无动画 clip），VRoid Hub 页面待机是网页额外加载的 vrma——壳同样处理：`assets/animations/idle.vrma` 存在时，`_updateIdleAnimation` 无动作播放即 `playAnimation('idle', true)` 循环待机；动作播完淡出自动回 idle；原呼吸+身体微晃仅作无 idle vrma 时的兜底
- **素材来源**：npm 开源包 `virtual-avatar`（MIT，unpkg 下载）`standard_idle.vrma`（8.22s/22 轨道）→ `idle.vrma`；`quick_formal_bow.vrma` → `bow.vrma`。同包还有 VRoid 官方免费 7 种动画（VRMA_01~07 全身/挨拶/Vサイン/撃つ/回る/ポーズ/屈伸），文件名日文需重命名后按需导入
- **端到端实测**：壳启动日志 `[VRM动画] 加载 idle 成功, 8.22s / 播放 idle`（循环待机）；预览 bow → `播放 bow` → 播完自动 `播放 idle` ✓；动作清单 = 5 个 VRMA（Body Block/bow/elbow_punch/idle/sitting_laughing），动态工具 enum 同源
- **清理**：删 `Illegal Elbow Punch.vrma`（与 elbow_punch.vrma 同字节重复）、`elbow_punch.fbx`（转换源文件残留）
- **遗留**：动作名=文件名（含空格如 "Body Block" 仍可播，后续可规范化空格→下划线）；VRMA_01~07 未导入

## 预览/自转/动作清单修复（2026-10-05 凌晨）

- **自转 bug 根因（用户反馈"一直360转"→"转到180°停住背朝我"）**：① 上一版 360 自转 `_orbitTheta += delta*0.1` 永续转；② 改成摆动后用了 canvas hover 暂停——**数字人窗口是全屏透明层，canvas 常驻全屏，鼠标永远"悬停"，摆动永不触发**，模型停在用户拖到的角度；③ 摆动目标围绕 **0** 而正面是 **π**（adapter `_orbitTheta=Math.PI // PI=front`），收敛方向错误会拉向背面。修复：摆动围绕 `Math.PI + sin(t*0.35)*0.25`（正面 ±14° 慢速往复），去掉 hover 暂停（仅右键拖拽后暂停 8s），收敛用 delta*2.0 + 到位钳制
- **表情预览"没效果"结论**：链路全通（前端按钮→POST /avatar/preview→SSE→壳 playAvatarActionPayload→setValue），壳日志有用户点击触发的 happy/sad/blink/neutral/aa 播放记录；看不到的根因 = ① 模型当时背朝用户（自转 bug 所致）；② 表情保持 3s 太短。修复：显式表情路径 `_playExpression(…, 3000)→8000`、app.js EXPRESSION_RECOVERY_MS 5000→8000
- **前端动作区空（用户反馈"下面没有动作可以预览"）**：`/api/avatar/models` 的 models[].motions 恒空（list_models 硬编码）——补为 `list_avatar_actions()` 全局 VRMA 清单（motions=[name]，actions={name:{label_zh,has_vrma}}），前端卡片动作区渲染 5 个动作 + ▶ 预览按钮
- **视觉验证限制**：数字人窗口透明全屏 + 控制台窗口遮挡，screencapture 拿不到模型画面（AX 树也无透明窗口），表情视觉验证依赖用户确认；模型 viewRect 默认 (1.0,0.6,0.5) = 屏幕右侧中部

## 表情预览"仍无效果"终极根因（2026-10-05 凌晨，已定性）

- **模型文件本身没有表情数据**：解包 6309260419351179234.vrm 的 GLB JSON，`blendShapeMaster.blendShapeGroups` 17 个 group（Neutral/A/Joy/Angry/Sorrow/…）**binds 全部为空数组**——VRoid 导出时去掉了表情 mesh 变形。three-vrm 验证脚本实测：`setValue('happy',1.0)` 后 `expression.weight=1` 但 `binds:0`，morph 权重变化数 0，mesh 纹丝不动
- 链路（前端→API→SSE→壳→setValue→_expressionMap['happy']）全部正确；**问题 100% 在模型资产**——任何表情预览/对话触发都不会有视觉变化
- 顺带确认 three-vrm v3 语义：`VRMExpression.name`=`VRMExpression_happy`（包装名）、`_expressionMap` 键=`expressionName`（'happy'），壳 `_exprByLower` 索引与 `_resolveExpression` 大小写匹配均正确
- **新增检测**：后端 `vrm_has_expression_data(model_path)` 解析 GLB 检查任一 group binds 非空（VRM1.0 查 morphTargetBinds）；`list_models` 返回 `expressions_have_data` 字段；前端模型卡片在无数据时显示警告"⚠ 该模型无表情变形数据…"并隐藏表情预览按钮（已 build，控制台刷新可见）
- **结论/建议**：~~更换带表情的 VRM 即可正常预览；当前模型仅适用于动作演示~~ **已过时（2026-10-05 用户已导入新模型 868274793854709131，angry 等表情 binds=1，表情预览已生效）**：多数 VRoid Studio 导出模型带表情

## 模型热切换修复（2026-10-05）

- **卡点**：壳 app.js switch-model IPC 原来只 log「VRM 模型切换需要重启AI 数字人生效」就返回——切模型必须重启壳，用户点切换"没反应"
- **方案**：页面重载热切换。后端 switch 已同步 config.ui.model_path → 壳收到 switch-model 后 `setTimeout(() => location.reload(), 400)` → 渲染进程 initialize 重跑读取新模型路径。窗口不关、进程不重启，约 1-2s 换模型
- **验证**：双向切换（630926↔868274）日志均出现「重载页面加载新模型 → 正在加载VRM模型: 新路径 → 糯米启动完成」；active/config 同步正确
- **表情数据实证**（three-vrm 壳同款加载链，非后端 JSON 解析）：868274793854709131.vrm 的 `angry` 表情 binds=1（有 morph 变形），旧 6309260419351179234.vrm 全部 binds=0——**用户已导入的新模型即有表情数据，切换后表情预览即可生效**（脚本 vrm_expr_check_tmp.js 已完成使命，删除）

## VRM 尺寸归一化（2026-10-05）

- **问题**：用户反馈新模型 868274793854709131 比旧模型 6309260419351179234 "大一倍"。实测包围盒高度：1.68m vs 1.17m（1.44 倍）——不同 VRM 导出比例/单位不一致
- **方案**：vrm-model-setup.js 加载后 `Box3().setFromObject(vrm.scene)` 测原始高度 → 统一缩放到 targetHeight=1.4m（`vrmGroup.scale`），脚底对齐 y=0（`vrmGroup.position.y = -box.min.y * scale`）。VRMA 骨骼动画随 scale 等比缩放，动作幅度一致
- **验证**：壳日志两个模型均输出「尺寸归一化: 1.68m→1.4m (scale=0.834)」「1.17m→1.4m (scale=1.199)」；热切换 3 次均正常

## 插件列表动态工具计数（2026-10-05）

- **问题**：方案B 下 vrm-avatar 插件工具不走静态注册（PluginRegistry.all_tools() 统计为 0），插件列表显示"0 个工具"，用户认为不合理
- **修复**：plugins/service.py `list_all()` 对 vrm-avatar 特殊处理——启用时按当前动作/表情清单统计动态工具数（do_action + set_expression = 2，有数据才各计 1）；未启用为 0。VRM_AVATAR_PLUGIN_ID 提升为模块级 import（函数内 import 会触发 UnboundLocalError）
- **验证**：/api/plugins 返回 vrm-avatar tools: 2（enabled=1）；weather 1

## VRMA 资源管理（删除）+ 导入/删除时数字人页面刷新（2026-10-05 晚）

- **删除**：`DELETE /api/avatar/animations/{name}`（service.delete_avatar_animation：仅允许简单文件名禁路径穿越、不存在 404、idle 可删待机降级呼吸微晃兜底）；壳 fs.watch 补**删除注销**（文件不存在时 delete model.animations[name]，双保险）；前端动作 Tag 加 Popconfirm 删除按钮（idle 特殊提示）+ 删除/导入后 load() 刷新列表
- **导入/删除时页面刷新**：后端端点用 `avatar_events.publish_raw()`（新方法，原样广播不强制 type——`publish()` 会强制 type=avatar_action 覆盖自定义 type，这是关键坑）广播 `{"type":"avatar_animations_changed","reason":"import|delete","action":...}`；壳 app.js SSE 收到该 type → `location.reload()`（复用模型热切换思路）
- **验证**：DELETE 成功/404/路径穿越拒；端到端日志「动作资产变更（delete x）→ watch 注销 → 糯米启动完成(reload)」；顺带用删除功能清掉重复资产 Sitting Laughing.vrma（与 sitting_laughing.vrma 内容一致）
- 动作清单现 6 个：Body Block/bow/elbow_punch/idle/Praying/sitting_laughing

## 动作资产 UI 重构：独立全局卡片（2026-10-05）

- **问题**：删除按钮放在每个模型卡片内（动作区重复渲染），用户反馈"每个卡片都有容易误解，让人觉得资产是独立的"——实际动作（VRMA）是全局共享的
- **重构**：①后端新增 `GET /api/avatar/animations`（全局动作清单独立入口）；②模型卡片**移除动作区**（只保留模型切换/表情/删除模型）；③新增独立卡片「动作资产（全局共享，所有 VRM 模型通用）」：动作 Tag + ▶预览 + 🗑Popconfirm 删除，文案明确"导入一次所有模型可调用、删除后数字人页面刷新"
- 前端已 build（12:26），后端已重启

## 控制面板窗口自动刷新（2026-10-05）

- **问题**：壳有两个窗口——数字人窗口（纯 3D 模型）+ 控制面板窗口（BrowserWindow 加载 /console/ 控制台）。用户反馈"桌面端看不到动作资产卡片"——控制面板窗口不自动刷新（Electron 缓存旧 JS bundle），浏览器强刷后能看到但桌面端看不到
- **修复**：①主进程 `ipcMain.on('reload-control-panel')` → `controlPanel.reload()`；②数字人渲染进程收到 `avatar_animations_changed` SSE 时 `ipcRenderer.send('reload-control-panel')`——动作资产导入/删除时控制面板窗口自动跟随刷新
- **验证**：DELETE panel_probe 端到端日志「动作资产变更 → 控制面板已刷新（动作资产变更）」

## M3 Agent 生命周期补全 + M4 会话存储（2026-10-05，36 tests/ruff/mypy 全绿）- **M3 补全（原 agents 表/CRUD/启停/运行时已有，本次补两块缺口）**：
  - **运行时参数接线**：新增 `backend/app/infra/harness/runtime_limits.py`（对齐 Octop runtime_limits.py）——agents.config_json 的 `max_iters`→ChatRequest.recursion_limit、`temperature/top_p/max_tokens`→configurable[model_settings]（harness 默认挂载 ModelSettingsMiddleware 消费）、`max_input_length`→configurable[max_input_tokens]；非法值过滤（bool/越界/非数字忽略）、per-turn 显式值优先。stream_chat 增加 `agent_config` 参数注入
  - **PATCH 支持 config_json**：AgentPatchBody 补 `config_json: dict | None`（此前 PATCH 会静默忽略该字段）
  - **DELETE 级联清工作区**：delete_agent 释放运行时 + 删 DB 行 + rmtree agent-workspaces/<id>（对齐 Octop manager.remove；失败不阻断）
- **M4 会话存储（threads/messages 表 + checkpointer 持久化 + 历史会话）**：
  - **threads 表**：thread_id/agent_id/title/last_active(ms)/created_at/pinned/model_ref（对齐 Octop ThreadRow 单用户裁剪）；会话列表权威从 nuomi-state.json 迁到 SQLite（幂等迁移 `_migrate_state_threads`：旧 threads 数组全量 INSERT OR IGNORE → 成功后清理 state 文件 threads 字段；state 文件只留 thread_id + agent_id（avatar 绑定消费））
  - **thread_messages 投影表**：seq/message_id/role/message_json/created_at（langchain `message_to_dict` wire 格式，与 Octop projection 完全一致）；**thread_history_projection 状态表**（pending/ready）标记 backfill 状态
  - **消息权威仍是 checkpointer**（octop memory.sqlite）；投影是历史加速层——**首次读历史全量 backfill → ready，之后每轮对话增量 append**（turn 完成回调 `on_turn_complete`：user+ai(+tool) 序列化追加，仅 ready 时写；回调失败不阻断对话）
  - **chat_history 端点改造**：投影 ready → 直接读表分页（`_segments_from_messages` 从 wire 重建 Segment，**不再依赖 harness 运行时实例**）；pending → checkpointer 读取 + 全量 backfill + mark ready；limit/offset 分页
  - **删会话级联**：threads 行 + 消息投影 + projection 状态 + checkpointer 历史（chat_sessions.delete）
  - **openai_compat（AI 数字人壳 thread=desktop）同样接线** agent_config + on_turn_complete
  - **旧库兼容**：v0.13 前遗留 threads 表（id/project_id/title/agent 空壳）→ init_db `_rebuild_legacy_threads` 检测缺 thread_id 列即 DROP 重建（符合"不背历史数据"决策）
- **端到端实测**：真实库 32 个旧会话全部迁移成功（threads 表 31+1），state 文件清理；历史 backfill 7 条 + 投影 ready；真实对话 2 轮增量 append（7→9→12）；M3 PATCH config_json 生效 + 带参数对话正常；state 文件死字段 enabled 已清（无消费方，agent_id 保留）
- **遗留**：format-check 基线红（项目原有 12+ 文件未 ruff format，非本次引入，未扩大范围）；前端无改动（/chat/state 返回结构兼容，sessions 新增 pinned/model_ref 字段）

## 壳自动拉起后端 uvicorn（2026-10-05）

- **目标**：`make start` 一条命令全自动——壳启动时检测后端 `/api/health`，未就绪则 spawn uvicorn（此前需手动先 make backend）
- **实现**：`shells/nuomi-avatar/main.js` 新增 `ensureBackend()`（app.whenReady 最先执行，`finally` 内再建窗口）：`http.get(origin + '/api/health')` 检测 → 未就绪 spawn `backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port <config.json llm.api_url 端口>`（cwd=backend，仓库根 .env 自动读入；stdio：stdout 丢弃防 uvicorn 访问日志刷屏、stderr 带 `[backend]` 前缀进壳日志；最多等 30s 健康检查）
- **设计决策**：退出壳后端**保持常驻**（与手动启动行为一致；浏览器/控制台不断连；下次启动检测到就绪直接复用不重复拉起）
- **验证**：①后端停 → npm start → 日志「后端未就绪，自动拉起 uvicorn … 后端已由壳拉起并就绪」+ health 200 + 数字人/控制面板正常；②壳退出后端仍在 → 再次 npm start → 日志「后端已就绪」（未重复拉起）；③测试后环境已清理（uvicorn/electron 0 残留）

## 待办核实与决策（2026-10-05）

- **已核实完成**：对话上下文保留（M4 投影含工具步骤）；模型插件工具语义（description 已含动作清单+中文标签）；models[].actions 已定论（全局 VRMA 清单）
- **用户拍板**：模型资产补全废弃（cat 动作/VRMA_01~07 不补）；AI 数字人模型升级废弃（已全 3D）；动作名空格保持现状（Mixamo 原名，enum 合法可播）；人设约束完成（改系统提示词后不再是小猫，尖括号标签自然消失）；bundle code-split 不做（本地加载收益低）
- **轨迹抽屉**：~~增强废弃——简版保持现状，后续轨迹能力集成 Langfuse（待办）~~ **Langfuse 已集成（2026-10-05）**：SDK 安装 + 后端配置持久化（工作区 langfuse.json，`GET|PUT /settings/langfuse`）+ 设置页 Langfuse 配置 UI + 对话轨迹上报验证通过（本地部署 localhost:3000，docker compose，数据不出本地）；~~**遗留 bug**：设置页 Secret Key 已保存但「测试连接」仍提示未输入~~ → **已修（2026-10-06 核实）**：根因就是本轮的脱敏哨兵问题——前端把 GET 回的脱敏串原样回传，后端按「含 `***` 即取已保存值」处理（`api.py` 的 `/settings/langfuse/test`）。实测：GET 返回 `sk-l***3995` → 用该串测连接 → **报的是连接失败而非「均为必填」**，证明已正确替换为真 key（旧行为会当成空值直接 400）

## 插件三层能力 + 事件层落地（2026-10-05）

- **插件能力模型对齐 dsh（DeepSeek Harness / Cordis「一切皆插件」）**：三层 = ① 工具注册（octop 原生，`ctx.tool(name, fn, description, config_fields)`）② 事件订阅/发布（薄 EventBus，框架定事件名，插件 `event_bus.on(...)` 报名）③ 前端页面/面板/主题（规划中；面板=聊天卡片去 octop ui/ 调研，主题低优先）
- **事件层已落地**：`backend/app/infra/events.py`——`Events` 枚举（conversation.started / conversation.completed）+ `EventBus.on/emit`（订阅者异常隔离）+ 全局单例 `event_bus`；`chat.py` 对话开始/完成后 emit；**TTS 自动播报改为插件订阅 `conversation.completed`**（合成→avatar/events 广播→壳播放，对话流不再产 tts 帧）。**用户否决过复杂方案**：事件注册表 + yaml subscribes 声明 + 安装校验（要极简对齐 Cordis）；无特权核心，订阅随插件卸载回滚
- **前端导航决策**：插件市场不占独立菜单——**并入「插件」页顶部按钮（Modal 内嵌 MarketPage）**；后续新功能一律插件化开发
- **设置页动态配置 tab**：只渲染 `enabled=true` 的插件（禁用后对应前端配置页销毁，已修：`Settings.tsx pluginTabs` 加 `if (!p.enabled) continue`）
- **save_config 修复**：secret 复用旧值时改读磁盘明文（原用 get_config 脱敏展示值回写，导致 config.json 存 `sk-t***-123` 污染）
- **规则：每次改动代码/配置后，壳（nuomi-avatar Electron 应用）也要一并重启验证**（前端 build 后同样重启壳，不只在浏览器刷新）

## AI 数字人语音播报（TTS）— Kokoro-FastAPI 本地部署（已验证 2026-10-05）

- **方案**：本地部署 [remsky/Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)（OpenAI 兼容 `/v1/audio/speech` 端点），nuomi 插件 HTTP 调用；声音只走本机，不依赖云端 TTS
- **部署步骤（macOS / UV 本地路线，Docker 非必需）**：
  1. `git clone https://github.com/remsky/Kokoro-FastAPI.git && cd Kokoro-FastAPI`
  2. `uv pip install -e ".[cpu]"`（依赖；如用 GPU：`[gpu]`，mac 可用 `./start-gpu_mac.sh` 走 MPS）
  3. 下载模型：`uv run --no-sync python docker/scripts/download_model.py --output api/src/models/v1_0`（默认走 HuggingFace，国内网络慢——用 hf-mirror.com 镜像下载 `kokoro-v1_0.pth` 到同目录即可，sha256 需与脚本 EXPECTED_SHA256 一致：`496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4`）
  4. **必改**：`api/src/core/config.py` 的 `model_dir/voices_dir` 默认是 `/app/...`（仅 Docker 挂载有效）→ 本地跑改为 `Path(__file__).resolve().parents[1] / "models"`（即 api/src/models）、`... / "voices" / "v1_0"`
  5. 启动：`uv run uvicorn api.src.main:app --host 127.0.0.1 --port 8880`（**勿带 reload**——带 reload 会在 8880 残留僵尸进程，需 pkill 后无 reload 重启）
- **验证**：`POST http://127.0.0.1:8880/v1/audio/speech` body `{"model":"kokoro","input":"文本","voice":"zf_xiaobei","response_format":"mp3"}` → HTTP 200 ~5s 返回 mp3；中文音色 `zf_xiaobei` 实测可用
- **nuomi 侧接线**（控制台 设置 → AI 数字人语音播报 插件配置）：api_url=`http://127.0.0.1:8880/v1/audio/speech`、api_key=任意占位（本地无鉴权）、model=kokoro、voice=zf_xiaobei、sample_rate=24000；对话结束自动播报走插件订阅 `conversation.completed` 事件（合成→avatar/events 广播→壳播放）
- **现状**：~~本机部署在 `/Users/superman/projects/code/kokoro-fastapi`，8880 常驻运行~~ **已停止（2026-10-05 测试结束）**：kokoro-fastapi 进程已停、TTS 插件已禁用；后续要用再按上面步骤重装拉起（部署步骤保留，别人看到可直接复用）

## 插件第三层 UI（聊天卡片）+ M8 工具执行可视化（2026-10-05，端到端验证通过）

- **聊天卡片协议对齐 octop ui/**：插件 `ui/manifest.json` 声明 `{"ui": {"tool": "<工具名>", "render": "<文件>"}}`，`ui/index.js` 为 ES module `export default { render(ctx) => HTML }`（ctx 含 result/args）。工具结果命中声明 → 前端动态加载 render 渲染成聊天卡片；未命中保持文本折叠
- **后端**：`GET /api/plugins/{id}/ui-manifest`（读 ui/manifest.json，无则 404）+ `GET /api/plugins/{id}/ui/{file}`（serve ui/ 目录，正则白名单 `[A-Za-z0-9._-]+` 防路径穿越）；均走 `market.plugin_dir`（工作区 plugins/）
- **前端（Chat.tsx）**：模块级 `pluginUiRegistry`（tool→{pluginId,render}，ChatPage mount 时 `loadPluginUiRegistry()` 拉取 enabled 插件 manifest）+ `PluginToolCard`（`import(/* @vite-ignore */ '/api/plugins/<id>/ui/<render>')` 运行时动态加载 → `render({result,args})` → 渲染，最小防护移 `<script>`；SegmentView tool_result 命中 registry 时展开显示卡片
- **M8 工具执行可视化补全**：原 working 状态只在动作工具触发——`_publish_actions` 改为**任何 tool_call 都 `publish_status("working")`**、tool_result → `publish_status("idle")` 恢复；壳 `playStatusExpression` 已有（thinking→Surprised / working→Angry / idle 重置，显式表情让位）。**端到端验证**：对话调 weather_query → 壳日志「AI 数字人状态: thinking → working → idle」+ 控制台工具结果渲染为卡片（weather-card div）
- **验证载体**：weather-octop 测试插件（weather_query 返回示例数据 + ui/ 声明）——octop 生态插件直接可用，兼容验证 ✓
- **安全边界**：卡片 HTML 由本地自装插件产生（与 octop 同信任模型），仅移 `<script>`；插件渲染器负责转义外部数据

## 同名工具去重 + 来源徽标 + 卡片默认展开（2026-10-05，用户反馈修复）

- **背景**：两个天气插件（weather 遗留测试 + weather-octop）都注册 weather_query——octop `build_plugin_tools` 同名不去重，两个 StructuredTool 都进工具集，模型调用结果不可控，用户"根本不知道调用了哪一个"；且卡片默认折叠看不到
- **修复**：① 删遗留 weather 插件（与 weather-octop 功能重复，市场外资产）；② `plugin_service.tools()` 同名去重（dict 键覆盖保留最后注册者）+ 新增 `tool_owners()`（name→plugin_id，遍历 PluginRegistry().all_tools()，与去重顺序一致）；③ api.py `_publish_actions` 对 tool_call/tool_result 内部帧附加 plugin_id（`_TOOL_OWNERS` 模块级缓存，agents/{id}/chat 端点每次对话开头刷新）；④ `stream_octop_sse` 对外帧透传（tool_call_chunk.plugin_id + tool_result.messages[].plugin_id）；⑤ 前端 ChatEvent/Segment 加 plugin_id，折叠头显示来源插件 Tag，**有聊天卡片的工具结果默认展开**（useState 初始值=hasCard）
- **验证**：curl 对话帧 `"plugin_id": "weather-octop"`；浏览器折叠头「⚙ 调用 weather_query [weather-octop]」+ 卡片默认展开显示天气内容；历史会话无 plugin_id 不显示徽标（可接受，投影未存来源）
- **遗留**：中文工具名经 _sanitize_tool 改名 tool_{n} 后 tool_owners 映射 miss（无徽标）——本项目工具名均英文，暂不处理

## 对话卡死排查修复（2026-10-05）

- **现象**：POST /api/agents/{id}/chat 挂起无输出（90s 无 token），health 秒回、DeepSeek API 直连正常、换 agent（工作狂）正常
- **定位**：糯米 agent 的 `default` 线程卡死，新 thread 与浏览器会话线程（`{agent}:{uuid}`）均正常 → 根因 = 该线程残留**半路 checkpoint**（对话流中断——curl `| grep | head` 提前关管道触发 SIGPIPE 断开 SSE——时写入的不完整状态），恢复时卡住
- **修复**：清理 `agent-workspaces/6a3b128b89e9/memory.sqlite` 中 thread_id='default' 的 checkpoints（191 条）+ writes（256 条），对话即恢复（done 正常）；壳+后端重启验证
- **经验**：① 排查对话卡死顺序：health → provider API 直连 → 换 agent → 换 thread → 查 memory.sqlite checkpoint；② 避免用 `curl | grep | head` 提前断流测试对话（会写半路 checkpoint）；③ 用户真实会话是 `{agent}:{uuid}` 格式线程，default 仅为 curl 测试残留
- **遗留（待办）**：harness（PyPI 包，勿改源码）流中断可能写半路 checkpoint 导致该线程下次恢复卡死——建议业务层加容错：对话首帧超时（如 90s）自动清该线程 checkpoints/writes 后重试一次

## 聊天卡片样式对齐 Octop + 对话循环卡死修复（2026-10-05，用户反馈"看不到卡片"）

- **octop 调研**（github.com/TencentCloud/Octop）：toolRenderers 系统（dashboard/src/plugins/toolRenderers/）——工具输出解析 octop_ui envelope → 按 renderer 匹配组件；内置 BuiltinOctopUiFallback 硬编码卡片样式（白底/圆角10/1px #d0d5dd 边框/padding 12x14/maxWidth 420/轻阴影/标题+工具名+键值对）；默认渲染 DefaultToolRenderer（折叠工具块+参数/结果段）；插件 demo-ui-card（工具返回 octop_ui JSON，前端按 renderer 渲染，host.patchResult 做 L2 刷新）
- **改造**：① 前端 PluginToolCard 容器对齐 octop builtin cardStyle（toolCardStyle：白底/圆角10/边框 #d0d5dd/maxWidth 480/阴影/13px）+ render ctx 传 data（JSON.parse result）/textFallback；② render 失败或空时兜底显示原始结果文本（保留卡片框，不再空白/null）；③ weather-octop 示例插件升级：main.py 返回结构化 JSON（city/temperature/description/condition_emoji/humidity/wind），ui/index.js 渲染真卡片（☁️ 大图标+城市·当前天气+温度大字+描述+键值表，值 escape 防注入）
- **对话卡死根因（新）**：langgraph `GraphRecursionError: Recursion limit of 30`——模型对"示例数据"天气结果陷入循环（记忆知道是 demo，坚持要真实数据，反复 reasoning/尝试）→ 30 轮超限抛错 → SSE 流中断（ERR_INCOMPLETE_CHUNKED_ENCODING）→ 前端无回复。**修复**：糯米 agents.config_json `max_iters: 30 → 60`（runtime_limits 映射 max_iters → recursion_limit）。验证：模型 weather_query(示例) → 判断不可信 → 调 web_fetch(wttr.in 真实数据) → 完整回答，不再卡死
- **验证**：对话完成 + 卡片 DOM 完整（☁️ 苏州·当前天气 24°C 多云(示例数据) humidity 65% wind 东南风3级）+ 来源徽标 + 默认展开；截图 weather-card-demo.png（OCR 弱但 DOM 证实）
- **遗留**：截图/OCR 对白底卡片识别弱（视觉正常）；harness 默认 recursion_limit 30 对循环敏感——max_iters 提高是当前方案，极端循环仍可能超限（可再提）

## 壳死代码清理（2026-10-05，用户指出 music-player 非插件后全量核查）

- **背景**：插件化咨询时误将壳内 music-player.js 列为"可抽插件"，用户纠正后全量核查——这些是 VRM 3D 化改造后未清干净的旧 2D/Windows 时代遗留，**不是插件（无 plugin.yaml/setup(ctx)/工具注册），且无任何调用入口**
- **删除文件/目录**：`js/services/music-player.js`（仅被 vrm-model-setup 构造挂 global，播放方法零调用）、`js/asr-client.js`（全壳无 require）、`js/live/`（LiveStreamModule/auto-chat 无外部引用）、`plugins-dlc/`（旧 MemOS 体系，untracked，main.js 检测的是 plugins/built-in 而非它）、壳根 Windows 启动脚本 `启动.bat/启动.vbs/2.ASR.bat`（untracked，引用不存在的 full-hub/GPT-SoVITS）
- **引用清理**：`vrm-model-setup.js`（删 MusicPlayer require/构造/返回值字段 + 签名去 asrEnabled 参数）、`app.js`（删 `config?.asr?.enabled` 传参——asrEnabled 参数函数体内未使用；删 voiceChat API_URL/KEY/MODEL 同步死段——sendToLLM 已空、auto-chat 已删）、`main.js`（删 PTT 快捷键管理+4 处注册/注销点——renderer 无 'ptt-key-down' 监听；删 check-plugin-health IPC——前端无调用且检测的 plugins/built-in 目录不存在；删 take-screenshot IPC——前端无调用；electron import 删 Menu/globalShortcut/desktopCapturer 死引用）、`events.js`（删 4 个 ASR 事件定义——无 emit/on）、`config.json`（删 asr 配置段——清理后无代码读取）
- **保留**：`vmc-sender.js`（VRM 模型真实使用）、`voiceChat` 空壳对象（vrm-model-setup 仍调 setModel）
- **验证**：node --check 4 个改动 JS 全过；config.json JSON 合法；全项目残留扫描（musicPlayer/asr/ptt/check-plugin-health/take-screenshot/plugins-dlc/globalShortcut 等关键词）0 命中；重启壳——VRM 模型/动画/VMC/表情加载正常，糯米启动完成，无报错
- **经验**：壳内 js/services、js/live 是旧 2D/Windows 时代资产区，清理前必须 grep 调用入口（有 require 不等于活着，要看播放/启动方法是否被触发）

## 前端视觉优化 L1 骨架统一（2026-10-06，commit 3e67d3f，端到端验证通过）

- **背景**：用户反馈"前端产品不好看、没有大厂感、自己做很粗糙"。逐页审计 9 页（Experts/Plugins/Skills/Connectors/Knowledge/AvatarModels/Settings/Storage/Chat + index.css/theme.ts/main.tsx）后定三层路径：L1 骨架统一 → L2 视觉统一 → L3 细节工艺；用户拍板"先做 L1，遇到适合抽组件就抽"
- **L1 内容**：① 新增页头基元 `PageLayout.tsx`（props title/description/extra/wide）：标题 20px/600 + 一句话 description + 主操作右对齐，内容区默认 maxWidth 1080 居中（对齐知识库页既有宽度），wide 全宽（对话页用）；② 主色定案：品牌亮档 `accent=#f59e0b` 只做点缀（logo/选中/高亮），**新增交互深档 `primary=#d97706`**（白字对比度达标，消灭"按钮发飘"），`link` 从 #1677ff → #d97706 彻底消灭 antd 蓝残留；③ 8 页接入（Experts/Plugins/Skills/Connectors/Knowledge/AvatarModels/Settings/Storage），散落说明 Paragraph 收敛进页头 description，操作按钮统一进页头 extra；④ 顺手清理：AvatarModels 开关卡片去掉与页头重复的 Switch、Settings 去掉无意义 Card 包裹
- **细节决策**：Skills 页导入按钮保留在"已安装" tab 工具栏（tab 内操作不上提页头）；Chat 页不动（对话主界面已有 SectionToolbar，页头式骨架不适用）；分类 Tag（蓝/紫/绿）是语义色不是主色，保留
- **验证**：tsc 过、vitest 59 全绿（components.test 新增 PageLayout 3 条：渲染/宽度约束 wide/缺省区块）、npm run build 成功、后端 /api/health + /console/ 200、壳重启"糯米启动完成"
- **遗留（L2 待做，等用户确认节奏）**：网格三套（Row/Col、List grid、Card 堆叠）统一；空态三种收敛；卡片语汇统一；品牌亮档点缀的应用面；L3 细节工艺（hover 反馈/间距节奏/字体层级）

## 前端视觉优化 L2 视觉统一（2026-10-06，commit 11202ca，端到端验证通过）

- **背景**：L1（页头骨架 + 主色）完成后用户继续 L2。审计遗留三大粗糙源：网格三套（Row/Col、List grid、手写 grid）、空态三种（locale emptyText / 手写 Empty / Card 包 Empty）、卡片语汇不统一（size、手写加粗标题、硬编码色）
- **L2 内容**：① EntityGrid 增强：新增 `loading` prop（居中 Spin），网格/加载/空态一体化（此前 P0-3 抽了 EntityGrid 但没有任何页面在用——历史欠账，本轮铺开）；② 网格三套归一：Experts/Knowledge/AvatarModels 的 Row/Col、Plugins/Skills/Connectors 的 List grid、Market 手写 grid div 全部换成 EntityGrid（auto-fill minmax 自适应 + 等高），并去掉卡片无谓的 List.Item 包裹；③ 空态统一全部走 EntityGrid emptyText / EmptyState；④ 卡片语汇统一：全部卡片 size="small"，AvatarModels 去掉手写 `<b>` 加粗标题、选中态 borderColor 硬编码 #f59e0b → var(--accent)，Experts 头像底色硬编码 → var(--accent)，Market 去掉 Modal 内重复 level-4 大标题（市场名合进描述）
- **死代码清理（用户偏好当场清）**：index.css 的 `.nuomi-grid` 等高 hack 规则（List/Row 时代遗留，兼容两种挂载的 hack）全量删除——页面已无引用（EntityGrid CSS grid 天然等高）
- **验证**：tsc 过、vitest 60 全绿（新增 EntityGrid loading 1 条）、npm run build 成功、后端 /api/health + /console/ 200、壳重启"糯米启动完成"；提交未包含 shells/nuomi-avatar/config.json（壳运行时写入 avatar_enabled 状态的现场改动，不混入）
- **遗留（L3 待做，等用户确认节奏）**：hover 反馈/间距节奏/字体层级/选中态微交互等细节工艺；antd Modal/Form/Table 等表单语汇未动；Chat 对话页未做视觉统一（全宽主界面，L1/L2 未触碰）

## 前端视觉优化 L3 细节工艺 + 全站文案优化（2026-10-06，commit 2312dd8，端到端验证通过）

- **L3 视觉**：全部管理页卡片统一 `hoverable`（Experts/Plugins/Skills×2/Connectors/Market；Knowledge/AvatarModels 此前已有），hover 阴影反馈一致
- **文案优化（用户偏好硬约束落实：连接器命名，不向用户暴露 MCP 等协议术语）**：
  - **Connectors 页 MCP 术语全清**：页头描述「接入 MCP 服务器」→「接入外部服务器能力」；「如何接入」卡片删除 MCP 协议/langchain-mcp-adapters/data_root connectors.json/NUOMI_CONNECTORS 首次播种等内部细节（播种机制保留在 AGENT.md 层面，不进用户文案）；传输方式选项 stdio/sse/http 标签中文化（本地进程/HTTP 流/HTTP，**value 不变**，后端字段不受影响）；卡片 transport 徽标显示中文名（TRANSPORT_LABEL 映射）；校验消息中文化；「新增连接器」→「新建连接器」统一动词
  - **AvatarModels**：页头描述/使用说明卡/Alert 去 vrm-avatar、.vrma、LLM 术语并精简（「AI 数字人」重复 4 次→1 次）；修复「对AI 数字人」「所有AI 数字人」中英混排缺空格；blend shape → 形象自带预设；「自动转 VRMA」→「自动转换」
  - **App 导航** tooltip「连接器（MCP 协议）」→「连接器（外部服务器接入）」
  - **Plugins**：描述「工具由 LLM 按需调用」→「AI 按需调用」；页脚删 ctx.tool 术语
  - **Knowledge/Experts/Settings** 页头描述精简；Knowledge 空态「点击右上角」→「点「新建知识库」创建」
- **保留（刻意不动的）**：Storage 表现层接入协议说明（开发者技术页，SSE/API 端点保留）；Settings Tab 内 Provider 字段名（配置标识，改名会破坏字段语义）；SkillHub/Mixamo 品牌名
- **验证**：tsc 过、vitest 60 全绿、build 成功、后端 /api/health + /console/ 200、壳重启「糯米启动完成」；未提交 shells/nuomi-avatar/config.json（壳运行时状态写入 avatar_enabled，与代码无关）
- **经验**：MCP 术语中文化只动「用户可见文案层」（label/description/徽标），协议字段值（transport: stdio/sse/http）与 API 契约不动——展示层翻译、数据层不动，避免破坏前后端契约

## 管理页内容架构精简：卡片信息模型 + 页脚说明处置（2026-10-06，commit 7b0e6d9，端到端验证通过）

- **背景**：用户反馈两个信息架构问题——① 卡片内容是否合适（如专家卡的「expert」tag）；② 页面底部说明文字（插件/技能页脚、连接器「如何接入」卡、数字人「使用说明」卡）放置是否合理
- **定案原则**：卡片统一四区模型（A 身份区：头像+名称+类型 tag【仅当有区分度】/ B 属性区：1~2 条核心元信息 / C 状态区：动态状态统一右上角 / D 操作区：主操作+次操作）；说明文字三类处置（行为说明→就近放操作旁 tooltip/行内；技术细节→删除或收敛进操作 Modal；状态说明→状态 UI 承载）
- **落地**：专家卡删恒真「expert」tag（kind 恒为 expert=噪声）、「运行中」上移身份行尾（右上角），名字加溢出省略；插件页脚整条删（技术路径+行为说明，行为信息已在卡片行内「全局启停」）；技能页脚整条删（目录细节导入 Modal 已承载）、内置卡删「lang:」显示、密钥状态 tag 保留；连接器「如何接入」卡整张删（页头 description + 卡片底部「工具名带前缀」已承载）、传输方式 tag 保留；数字人「使用说明」Card 删→行为说明进页头开关 tooltip（关闭销毁窗口/停用能力，后端对话不受影响）、Alert（模型资产+用法）保留
- **结果**：每个管理页 = 页头一句话 + 卡片区 + 必要状态 UI，无底部技术脚注
- **验证**：tsc 过、vitest 60 全绿、build 成功、后端+壳重启「糯米启动完成」；config.json 运行时改动未提交

## 专家「运行中」状态真实性修复 + 数字人页 Alert 去重（2026-10-06，commit fec1187）

- **用户质疑**：「运行中」是真的吗，不会是前端状态吧；数字人「模型资产（工作区 models/3D/）」组件和页头描述重复
- **核实结论（质疑成立）**：`last_state` 是 DB 持久化值——`/start` 写 running、`/stop` 写 stopped，**进程崩溃或后端重启后不复位**；实时状态在 manager 内存缓存（`manager.has`）。后端 `/agents/{id}/status` 早已有 `runtime` 实时字段，但列表接口一直返回旧 `last_state` → 前端显示陈旧「运行中」
- **修复**：后端 transport 层新增 `_enrich()`（列表/单查/创建/导入统一），在 enrich 后补 `runtime: running|stopped`（domain 层不依赖 infra，P0-1 分层约束，合并放 transport）；`last_state` 保留但不再用于 UI。前端 Agent 类型加 `runtime?`，Experts 页运行中 tag 与「重启/启动实例」判断全改 runtime
- **实测**：curl /api/agents → 糯米/工作狂 `last_state=running` 但 `runtime=stopped`（后端重启后实例已不在），修复前必然误导
- **数字人页**：删除与页头描述重复的 Alert；独有信息已覆盖：全局共享→动作资产 Card、表情预览▶→模型卡片、语言驱动→页头 description、无需重启→导入资产行内
- **验证**：后端 138 测试、前端 tsc/vitest 60/build 全绿、后端+壳重启 OK；config.json 运行时改动未提交

## 删除专家卡「启动/重启实例」按钮（2026-10-06，commit 62d4547）

- **背景**：用户问专家卡两个「启动」（Switch 启停 + 启动实例按钮）是否合理。核实后端：① `enabled`（Switch）= DB 配置总闸，停用则 chat/start 均 400；② `POST /agents/{id}/start` = ensure_agent_runtime（manager 单例缓存命中即 no-op）+ 写 last_state=running——**「重启实例」名不副实（从不真正重建）**；③ 对话端点每次自动 ensure_agent_runtime 拉起实例 → 手动预热冗余
- **落地**：删前端 startAgent 函数与按钮；专家卡操作区 = 启用/停用 Switch + 编辑 + 删除，运行中 tag（实时 runtime）保留；后端 start/stop 端点**保留**（对外 API 契约：HANDOVER 文档化 + tests/test_agent_runtime_entry.py 回归锁定 workspace 落点，删除会破坏契约与测试）
- **验证**：前端 tsc/vitest 60/build 全绿、后端+壳重启「糯米启动完成」

## 消除「双标题」：顶栏改面包屑（2026-10-06，commit 5787757）

- **问题**：用户截图指出专家页顶部有两个「专家」标题——App Header 左侧 Typography.Title(level=4) 显示当前页 title，Content 内 PageLayout 页头又是同一标题（含描述+新建按钮），重复
- **修复（大厂模式）**：主标题唯一化给 PageLayout；Header 左侧改为面包屑「能力 / 专家」（chat 顶级显示「对话」，知识库详情显示「能力 / 知识库 / 详情」），右侧「后端在线」Tag 保留
- **清理**：NavLeaf.title 字段废弃（原顶栏标题专用），9 个 NAV 条目 title 值全删；面包屑由 BREADCRUMB 常量（NAV 展开时拼 group.label / label）驱动
- **验证**：前端 tsc/vitest 60/build 全绿、壳重启「糯米启动完成」
