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
- **知识库技术决策（2026-10-04，M6 前置调研完成）**：参照 Octop `infra/knowledge/` 实现（每 KB = docs 目录 + 主库元数据行 + `index.sqlite` sidecar 向量索引；异步 parse→chunk(800/120)→embed；内置 `search_knowledge` 工具 + 中间件每轮改写工具描述；引用标记 `<!--octop-kb-citations-->`）。**已拍板：①嵌入先做本地模型（远端 API 后置）；②OCR 进 M6（RapidOCR 本地，图片 png/jpg/jpeg/webp + 扫描 PDF）；③知识库绑定粒度 = 对话框 per-turn 选择，显式指定才注入（无「默认打开」；2026-10-04 用户拍板与技能/连接器同维度，default_open 全链路已删）；④模型目录 `models/ai/<type>/`（embedding + .downloaded 标记 / ocr 预留；`2D/` 桌宠资产不动）；⑤嵌入实现 = **完全仿 Octop**：手写 HF 多源下载（官方+镜像竞速，Octop 自研逻辑）+ **fastembed 加载推理**（`TextEmbedding(cache_dir=models/ai/embedding)`，不手写 onnxruntime 管线）；默认模型 `BAAI/bge-small-zh-v1.5`**。方案/API 清单/工作量：`docs/knowledge-base-research.md`。
- **专家 workspace 模型（2026-10-04 A2 对齐 octop，用户拍板）**：每专家独立 workspace `数据根/agent-workspaces/<agent_id>/`。persona 走 harness 记忆文件标准（USER/SOUL/AGENTS/MEMORY.md 放 workspace 根，harness 每轮自动注入、改文件即生效；无 IDENTITY.md 概念，身份写 USER.md「关于我」）；manifest（`.octop/manifest.json`，octop 双语格式）为展示元数据权威（name/description/welcome_message/icon_name/color/quick_prompts，后端 `enrich_agent` 归一化，DB 字段兜底）；记忆/会话/技能按专家隔离（各自 memory.sqlite/sessions/_builtin_skills）。**模板匹配**：experts/<agent_id|name>/ 优先，再按 manifest（id/label.zh）匹配（糯米=experts/nuomi/，color #f59e0b）。
- **Octop 专家导入（2026-10-04 A2）**：`backend/scripts/import_octop_expert.py <source_dir> [--name 名]` 或 `POST /api/agents/import {source_dir}`；源 = `~/.octop/agents/<id>/`（已装）或 Octop 源码 `experts/library/<id>/`（模板）；复制 persona（含 BOOTSTRAP/PROACTIVE）+ skills/ + agents/（子智能体）+ manifest 到新专家 workspace，DB 注册（system_prompt 兜底、icon/color/welcome 取 manifest；**记忆不复制，从零开始**）。实测导入 general-assistant（小通·通用助手，4b97d68b698e）对话正常。
- **糯米人设变更（2026-10-04，用户拍板）**：猫 → 人工智能助手。experts/nuomi/ 全改 AI 助手（IDENTITY.md 删除、并入 USER.md「关于我」；MEMORY.md 新建）；DB system_prompt 降为兜底短句「你是糯米，住在用户电脑里的人工智能助手。中文回答，简洁友好。」（详细 persona 走文件注入）；全部会话与记忆已清空（备份 /tmp/memory-20261004.bak.sqlite、/tmp/nuomi-20261004.bak.db）。记忆由 harness `___atoms` 表承载（`nuomi_*` 表是废弃空表、facts 表无代码读写），清空后从零重建。

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
- **桌宠=LLM 直接遥控身体（2026-10-04，M7 核心）**：不是预编程自动动画，是**把身体能力暴露成工具让 LLM 在对话中主动调用**。参考项目：claw-sama（Tauri+VRM，分部位触摸+情绪系统）、mitscherlich/live2d-mcp（pixi-live2d-display+工具表，跟我们栈一样）、clawatar（VRM WebSocket JSON 命令，set_expression 带 weight、speak+action+expression 原子绑定）。
  - **语义动作清单**：每模型目录放 `actions.json`（`{"actions": {"wave": {"motion": "main_1", "expressions": [], "label_zh": "挥手"}, ...}}`），后端 `generate_model_plugin` 有 manifest 时按语义名生成工具（wave/dance/nod...），无 manifest fallback 到按 motion group 名注册。aidang 已配 13 个语义动作。
  - **事件协议**：SSE `/api/pet/events` 推送 `{type:"pet_action", motion:"main_1", expressions:[], label:"挥手"}`——后端 `_resolve_pet_action(tool_name)` 根据当前模型 manifest 反查完整 payload，壳不再瞎猜 motion/expression。旧 `tool_call {name, kind}` 协议已废。
  - **表情自动恢复**：壳 `playPetExpression` 播表情后 5 秒自动 `model.expression()` 重置（pixi 不传参=清所有表情参数），连续表情刷新定时器。修复了之前表情卡死的 bug。
  - **instructions.md 自动注入（业务层创新，octop 不支持）**：插件生成时自动写 `instructions.md`（列出所有动作+使用原则）；chat API 检测到桌宠插件启用时，读 `plugins/<model_id>/instructions.md` 拼到 system_prompt 后面。**不污染专家人设**——人格在 DB/persona 文件，身体说明跟着插件走，关桌宠就不注入，换模型自动换动作清单。
  - **壳侧**：`playPetMotion(name)` / `playPetExpression(name)` / `playPetActionPayload(payload)`；删除死代码 `handleNuomiToolResult` / `playPetAction`（全项目无调用点）；`PET_ACTION_MAP` 保留为语义映射雏形（P1 参考）。
- **专家-插件解耦（2026-10-04）**：专家不再绑定插件（`agent_plugins` 表/绑定 API/前端「绑插件」UI 全删）。插件=全局启停（`plugins.enabled`），启用即对所有专家可用；工具装配 `PluginService.tools()` 只按全局启停 `build_plugin_tools(global_plugins=...)`。桌宠模型插件互斥保留（切换模型只 `set_enabled` 互斥 + `manager.release`，不再 bind 到 agent）
- **对话框大改动（2026-10-04）**：能力按 per-turn（每次请求）注入，对齐 octop 对话框语义。`POST /agents/{id}/chat` body 扩展 `{skills, connectors}`：skills=None 全量/[] 禁用全部/[name|slug] 只启用（校验存在性，400）；connectors=None 默认挂载/[] 不挂载/[name] 只挂载。底层走 harness 原生 `ChatRequest.skills`（SkillFilterMiddleware 白名单）+ `mcp_servers/mcp_use_default`，无需自研。前端对话框：技能/连接器选择器（Popover）+ 输入框上方能力 chips（可移除）+ 消息气泡内工具步骤折叠（tool_call→tool_result）+ 轨迹抽屉（当前会话工具时间线）。**踩坑：per-turn 能力校验必须在 StreamingResponse 的 generator 之外（端点函数体）执行，否则抛错不转 400**
- **大模型配置页（2026-10-04）**：LLM Provider 多配置管理（对齐 octop providers 管理）。存储 `工作区/providers.json`（运行时权威，.env LLM_* 仅种子回退；api_key 明文存工作区、不进 git）；`GET|PUT /settings/providers`（整体保存；api_key 空串=保持原值；GET 脱敏 sk-2***fa1e；校验 id 唯一/base_url/模型非空，400）。`build_providers()` 从 providers.json 构建 ProviderConfig 列表
- **模型不绑专家（2026-10-04）**：agents 表 `default_model` 字段删除（含旧库 DROP COLUMN 迁移），专家与模型解耦；模型在**对话框 per-turn 选择**（工具条「模型」Select，选项来自 providers×models），发送带 `model`（provider/model）字段，走 harness 原生 `ChatRequest.model`（优先于 default_model）；后端校验 model 存在于 providers（非法 400）。agent 默认模型 = providers[0] 默认
- **Provider 模型探测（2026-10-04）**：`POST /settings/providers/probe`（body base_url/api_key，不落盘）调 OpenAI 兼容 `/models` 拉取模型列表；新增 Provider 弹窗「探测模型」按钮 → 勾选列表（默认勾选第一个作为默认模型）→ 回填；探测失败 400 带原因
- **对话框输入区优化（2026-10-04）**：能力选择器（技能/连接器/知识库/模型）独立一行（提示文案已移除，2026-10-04 用户要求不显示），输入框独占整行 flex:1 + autoSize（1–6 行）；会话左栏 240→200、模型 Select 180→150、placeholder 缩短
- **模型默认自动（2026-10-04）**：对话框「模型」Select 首项新增「自动（默认）」（value 哨兵 `auto`，前端 Chat.tsx `MODEL_AUTO`），默认选中；选中「自动」时请求体 `model=null`，由后端按 agent 默认模型解析（`stream_chat` model=None → 默认模型）；用户显式选择具体模型才覆盖，移除模型 chip 回到「自动」。`ChatStreamOptions.model` 类型放开为 `string | null`。替代原「模型必选」语义（必选校验已删）
- **形态与遗留清理（2026-10-04，用户拍板）**：默认形态 = **桌宠壳 shells/myspy**（Electron，`npm start`，经 config.json `llm.api_url` → 后端 :8000 `/api/v1` OpenAI 兼容端点对话）；**web 控制台只是调试形态**（:5173，vite 代理 /api → :8000）。Makefile 重写：`make start` 启动桌宠壳（替换已失效的 tauri desktop 目标，`desktop/` 目录 v0.13 已删）、`make web` 调试、stop/status/logs 同步改为桌宠壳；tauri 遗留（README desktop/ 引用、docs/demo-script tauri build 检查项、.logs/desktop.log）已清理，docs/desktop-data-architecture.md 加废弃标注（NUOMI_HOME/SQLite 决策仍有效，以 AGENT.md 为准）。桌宠壳重启 = 杀 Electron 进程后 `shells/myspy && npm start`
- 后续：M3 Agent 生命周期 → M4 会话 → M5 插件 → M6 技能/连接器/知识库 → M7 桌宠前端 → M8 产品体验

## 环境事实（重要）

- **数据根/工作区**：`/Users/superman/Nuomi`（NUOMI_HOME；全局共享根：providers.json/env.json/knowledge/ 等）。**专家工作区（2026-10-04 A2）**：`agent-workspaces/<agent_id>/` = persona 文件 + `.octop/manifest.json` + 独立 memory.sqlite/sessions/_builtin_skills；harness 记忆注入目标 = 专家 workspace；全局根 memory.sqlite 为迁移期遗留（不再被新对话写入，删除线程上下文时双清兼容）。.env 仅设 `NUOMI_HOME`（2026-10-04 迁移自 ~/Documents/Nuomi + ~/Library/Application Support/Nuomi 合一）
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
- M6 技能/连接器/知识库：skills_dir 接入 + 连接器（MCP 协议）配置 + 知识库工具（调研完成，决策见上：本地 ONNX 嵌入 + OCR + 显式指定才注入；**2026-10-04 语义修正：知识库与技能/连接器同维度，不选=[]=不加载，无「默认打开」一说（default_open 列已 DROP 迁移），显式指定才注入**；实现进度 2026-10-04：嵌入服务（多源下载+fastembed 推理+就绪检查）、存储层（repo/parse/chunk/index.sqlite/service/jobs 状态机）、API 路由（knowledge_api.py：能力/模型/CRUD/文档 17 端点）、前端页（#knowledge 三区块 + 3 Modal）、检索工具 search_knowledge（tools.py）+ 引用标记协议（citations.py，`<!--octop-kb-citations:[...]-->` 沿用 Octop）+ 跨库检索（retrieve.py，k=8/6000 字符预算）+ 对话注入（default_open.py 显式指定才注入 + hint.py 中间件无库隐藏工具 + harness config/chat 接线 + ChatBody.knowledge_base_ids）+ Chat 引用展示（parseKnowledgeCitations.ts + KnowledgeCitations 组件）+ 对话框四选择器（技能/连接器/知识库/模型必选，消息必填）；技能选择器三分组（已启用的技能/内置技能/已启用的技能包，包级整包勾选=包内技能 slug 全进白名单，_available_skill_keys 补内置技能名）；知识库级联删除（delete_base 同事务清 knowledge_documents 行 + rmtree 目录）+ 库级启停（enabled 列迁移/停用库对话侧不可选/显式指定 400，对齐插件）+ 前端知识库页列表/详情双视图（点卡片进详情、返回回列表，详情内可删除库并自动回列表；loadDocs reqId 竞态保护 + loadBases 校正 stale 选中，根治删除后详情不同步/404）；pytest 24 项全过 + ruff/mypy 干净；真实环境验证：curl 显式 ids 触发 search_knowledge + 引用标记完整 + 模型引用回答，无 ids 不注入（0 次工具调用），白名单 [apple-notes+therapy-board] 200/未知技能 400，浏览器实测引用 Tag 渲染 + 知识库选择器 + 技能三分组 + 模型必选发送禁用；剩余：OCR（RapidOCR+扫描 PDF，用户叫停暂缓）**）
- M7 桌宠前端：myspy 二次开发（形象/情绪/字幕/TTS）+ 控制面板
- M8 产品体验：人格/情绪协议、工具执行可视化（"干活中"动画）
- **待办（2026-10-04 用户拍板暂缓）**：专家级默认绑定（对齐 octop agents 表 `skill_package_ids`/`knowledge_base_ids`/`mcp_servers` 三列）：nuomi agents 表加绑定列 + 对话时默认注入（per-turn 可覆盖，知识库仍保持显式指定才注入）+ 导入器读取 octop agent 记录的绑定字段；另：octop manifest `prompt_files` 声明的非标准文件（如 IDENTITY.md/HEARTBEAT.md，现已复制资产但不注入）内容合并进注入或 system_prompt
- **待办（2026-10-04 用户拍板，稍后开工）——桌宠 3D 化 + 动态工具（方案 B）**：用户决定：① **物理删 2D**（壳 Live2D 适配器/pixi 依赖/ModelScanner 2D 分支、后端 list_models 2D 扫描、前端桌宠页 2D tab；models/2D 的 aidang/cat/hiyori 资产直接删）；② **表情单工具** `set_expression(expression: enum)`，enum 由当前激活 VRM 模型的 blend shape 动态注入（替代现 set_expression_* 每表情一工具）；③ **直接方案 B（装配时动态）**：插件只留固定入口，工具 JSON Schema 在对话装配时动态构造——动作 enum 来自扫描 `assets/animations/*.vrma`，表情 enum 来自 Python 解析当前激活 VRM 模型 GLB（glTF JSON chunk `extensions.VRM.blendShapeMaster`，无需 three）——**改动点在项目源码 `PluginService.tools()`（backend/app/domain/plugins/service.py:126），在 `build_plugin_tools`（octop_harness.plugins 基础库，不动）返回结果上追加/替换动态桌宠工具**；切模型/新增 FBX 零重启。前置：后端加 VRM 表情枚举函数（Python 解析 GLB）+ 动作清单查询函数

## 教训（保留，跨版本有效）

- **MCP（langchain-mcp-adapters 0.3.x）**：`MultiServerMCPClient({"<s>": StdioConnection(transport="stdio", command=..., args=..., env=...)})`；**不是上下文管理器**，直接 `tools = await client.get_tools()`；StdioConnection 必须带 `transport` 键；env 不默认继承，需显式 `env=dict(os.environ)`。
- **DeepSeek 工具调用可靠**；本地小模型（Qwen3.5-2B）工具调用不稳定，仅适合纯对话。
- **Agent 实例缓存必须统一构造入口（2026-10-04 会话历史丢失 bug）**：`HarnessManager.get_agent(agent_id)` 按 agent_id 单例缓存，构造参数（workspace_dir/插件工具/技能目录/MCP）只在首次构造生效。`GET /agents/{id}/chat/history` 曾漏传 `workspace_dir`，页面加载自动拉历史时抢先把「全局根 memory.sqlite + 无工具」的残缺实例缓存 → 专家工作区历史读不到、对话错写全局根库。**修复**：`transport/api.py` 加 `ensure_agent_runtime(agent_row)` 统一入口，控制台对话/历史/桌宠 OpenAI 兼容三端点都走它；manager 缓存命中时对 workspace_dir 漂移打 warning。
- **octop-memory checkpoint 迁移三表齐搬（2026-10-04）**：会话历史不是只存 `checkpoints`+`writes` 两表——checkpoint 内容 blob 按 digest 存在 `hm_checkpoint_blobs(digest PK, type, value)`。只搬前两表会报 `ValueError: Missing checkpoint content; restore the matching database backup`，且 aget_history 静默返回 []（对话一启动才炸）。跨库迁移会话必须 **checkpoints + writes + hm_checkpoint_blobs 三表**一起搬（blob 按 digest 主键，INSERT OR IGNORE 合并即可）。
- **`make stop` 会回收 :8000 后端进程**：重启桌宠壳前先 `make stop` 再补起后端（`cd backend && nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/nuomi-backend.log 2>&1 &`）。
- **壳与后端同命令重启会竞态（2026-10-04 实测）**：一条命令里 pkill 后端 + pkill 壳 + 同时启动，壳可能读到中间态 config（加载成错误的 Live2D 模型，日志"模型类型: live2d"但 config 是 vrm）。**规范：后端先起来（health ok），再单独启动壳**。壳正常日志看 `/tmp/myspy-launch.log`（npm start 重定向，含 renderer 行）；`/tmp/myspy-shell.log` 是另一份可能混杂旧段的日志，以 launch.log 为准。
- **消息流 = 有序片段（2026-10-04）**：对话不再是「正文气泡 + 气泡上方一堆工具折叠」。history 接口与前端统一返回/渲染 `Segment[]`：`user / reasoning（深度思考）/ tool_call / tool_result / text` 按真实时间顺序穿插（思考→调工具→看结果→正文）。harness 有 `reasoning` 事件类型（AgentEventType.REASONING），stream_chat/stream_octop_sse 已透传；history 端点从 BaseMessage 重建（human→user；ai→reasoning_content + content + tool_calls；ToolMessage→tool_result）。前端 Chat.tsx 流式累积时相邻同类合并（思考累积思考、正文累积正文），切会话回来工具链与思考不再丢失。
- **改前端后必须 `npm run build`（2026-10-04 踩坑）**：浏览器 :5173 走 vite dev（源码热更），但**桌宠壳控制台加载的是后端 :8000/console/，挂载 `frontend/dist` 静态包**（main.py StaticFiles）。只改源码不 build，壳里跑的还是旧 bundle，表现为"web 对、桌面壳不对"。前端改动后必跑 `cd frontend && npm run build`（StaticFiles 实时读盘，无需重启后端；壳控制台窗口重载即可）。

## VRM 3D 表现层进度（2026-10-04）

- **已打通**：three.js 0.169 + @pixiv/three-vrm 3.3.0 + three-vrm-animation 3.3.0
- **模型**：`/Users/superman/Nuomi/models/3D/6309260419351179234.vrm`（CC0，黑发水手服少女，VRM 0.x，17 个 blend shape）
- **后端**：`enrich_model` 加 VRM 分支——不走 AI 分析，直接生成通用动作插件（7 表情 + 16 动作：wave_hand/nod/shake_head/tilt_head/raise_right/left_hand/look_left/right/up/down/hands_on_hips/shrug/dance/jump/spin/stretch）
- **壳侧**：`vrm-model-adapter.js` 实现 motion() 骨骼动画（手写关键帧+easing）+ expression() blend shape 控制 + AnimationMixer 支持 .vrma 文件
- **SSE 广播**：`_resolve_pet_action` 改成读 `plugins/<model_id>/actions.json`（VRM 模型 list_models() 里 actions={}）
- **插件互斥 bug 修复**：切到无插件模型时所有模型插件全禁用（之前只在新模型有插件时才互斥）
- **当前局限**：手写骨骼动画不自然（硬编码角度，无膝盖/手腕细节）
- **Mixamo FBX → VRMA 转换链路已走通（2026-10-04）**：
  - 工具链：`shells/myspy/tools/fbx2vrma/`（npm `fbx2vrma-converter` 1.0.2 + FBX2glTF 0.9.7 darwin-x64 二进制）。**arm64 机器无原生 FBX2glTF**（官方仅 darwin-x64），需 Rosetta 2（`softwareupdate --install-rosetta --agree-to-license` 已装）；npm install 用 `--ignore-scripts`（其 setup.sh postinstall 会失败）
  - 命令：`node node_modules/fbx2vrma-converter/fbx2vrma-converter.js -i <in.fbx> -o <out.vrma>`——自动 Mixamo→VRM humanoid 骨骼映射（mixamorig:* → hips/spine/chest...），默认 30fps
  - 产物：`shells/myspy/assets/animations/elbow_punch.vrma`（2.25s、22 骨骼、55 帧、113KB）
  - 验证：`tools/fbx2vrma/verify-vrma.js`（Node 直跑，与壳 loadVRMA 同款加载链：GLTFLoader+VRMLoaderPlugin 载 VRM 模型 → VRMAnimationLoaderPlugin 载 .vrma → createVRMAnimationClip → 22 tracks 标准 humanoid 骨骼 + Head 采样四元数差异确认驱动）。**Node 环境需浏览器 polyfill：self/createImageBitmap/URL.createObjectURL/ProgressEvent**（脚本已内置，不渲染纹理）
- **VRMA 播放链路已接入（2026-10-04，端到端验证通过）**：
  - 壳 `vrm-model-setup.js` 初始化时自动扫描 `assets/animations/*.vrma`，文件名去扩展名注册（await loadVRMA）
  - `vrm-model-adapter.js`：loadVRMA 改为 **fs 读文件 + loader.parse**（与 _loadVRM 同模式，原 loadAsync 走 fetch 无法加载 file://，这是它一直没接上的根因）；`motion(name)` **优先播 animations[name]（vrma）**，无则回退手写骨骼动画；playAnimation 一次性动画播完自动 fadeOut 回 idle（不卡最后一帧）
  - 后端 `_enrich_vrm` 动作清单加 `elbow_punch`（肘击攻击），重启后 `enrich_model('6309260419351179234')` 重新生成插件（**注意：启动时 generate_all_model_plugins 只用现有 actions.json 生成插件、不重新 enrich**，改动作清单后需手动调 enrich_model 或删 actions.json 后切模型）
  - 端到端实测：对话"对我来一记肘击" → LLM 调 elbow_punch 工具 → tool_result {motion, expressions, label} → SSE pet_action → 壳 [VRM动画] 播放 elbow_punch ✓
- **表情工具修复（2026-10-04）**：原 `_generate_semantic_plugin` 只生成动作工具、不读 actions.json 的 expressions——LLM 无表情接口（糯米反馈"只有动作，expressions 恒空"）。已修：
  - `_generate_semantic_plugin(model_id, actions, expressions)` 增加表情工具 `set_expression_<name>`（_make_expression_player 返回 {motion: None, expressions: [name], label}，与动作 payload 同构，壳播放链路零改动）；plugin.yaml/instructions.md 同步带表情清单
  - `_resolve_pet_action`（api.py）加表情反查（tool_name.startswith("set_expression_")）
  - `generate_model_plugin` 表情以 **plugins/<id>/actions.json 的 expressions 为权威**（fallback model dict）
  - **教训：改动作/表情清单后要 enrich_model 重新生成插件（generate_all_model_plugins 不重新 enrich）**
