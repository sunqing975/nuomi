# 糯米 V2 · 项目记忆（AGENT.md）

> 按用户记忆策略：本文件记录本项目的全部细节与决策；系统记忆只记跨项目共性。

## 项目定位（2026-10-01 转型：陪伴 → 全能）
全能型个人智能体（对齐 DeepSeek Harness 方向），打字为核心，能力全部插件化；面向求职作品集。
主线：LangChain/LangGraph + FastAPI + React；Cordis 风格插件内核（一切皆插件）+ 执行能力（shell/fs/subagent）+ 上下文工程（compaction/spill）+ 记忆/知识/协作。
演进决策：v1/v2 的陪伴资产（伙伴人格、情绪表情层）**保留为可选"人格层"插件**，不再是产品主定位；能力重心转向 dsh 式全能 agent（会执行、会读写文件、会协作、会自我压缩）。

## 已确定的关键决策
- **重构落点**：`/Users/superman/projects/code/nuomi` 就地改为 V2；v1 已备份（`nuomi-v1-backup-20260930`，另保留旧 `nuomi-v1-backup`）。
- **v1 资产**：伙伴人格文件在 `nuomi-home/`（SOUL.md / USER.md / MEMORY.md / journal/ / logs/），Phase 1 人设复用；AI 宠物图在备份 assets/。
- **路线图**：Phase 0（打字核心）✅ → Phase 1（伙伴+记忆）✅ → Phase 2（插件化★）✅ → Phase 3（健壮+评测）✅ → Phase 4（部署扩展）✅ → **Phase 5（全能化★：执行能力 shell/fs/subagent、上下文 compaction/spill、交互 user-questions、产物 attachment/credentials）→ 当前推进**。
- **LLM**：默认 DeepSeek（env: `LLM_API_KEY` > `DEEPSEEK_API_KEY` > `ARK_API_KEY`，base_url https://api.deepseek.com，model deepseek-chat）；换豆包 = 改 .env 的 base_url/model。本机已配 DEEPSEEK_API_KEY。
- **LLM 现状（2026-09-30 实测后定）**：测试主力 = DeepSeek（工具调用可靠）；本地 Qwen3.5-2B（llama.cpp :8080）仅适合纯对话，工具调用不稳定。.env 里两种配置都留好，注释切换即可。
- **存储**：对话历史用 SQLite checkpointer（backend/data/nuomi.sqlite）；记忆 JSON（backend/data/memories/<partner>/facts.json，MemoryStore）；知识库 Chroma 在 Phase 2。
- **流式**：`POST /api/chat` → SSE（meta/token/done/error 四事件）。**只流 AI 片段**（isinstance AIMessageChunk），工具原始输出不进聊天流。
- **上下文压缩（Phase 1 关键坑）**：LangChain `create_agent` 的 before_model 中间件返回 `{"messages": ...}` 会被 add_messages 语义**按消息 id 合并**，删掉的旧消息会被还原，模型输入不压缩（实测 21 条持续增长）。**正解：用 `awrap_model_call` 钩子**，通过 `request.override(messages=..., system_message=...)` 直接构造模型输入（system 提示 + 裁剪后的历史），模型输入有界（实测 21→4）；摘要按 thread_id 在内存增量缓存（covered 计数），进程重启后重新摘要可接受。
- **中间件选型**：AgentMiddleware（`langchain.agents.middleware`），`abefore_model(state, runtime)` 返回状态更新（会被 reducer 合并）；`awrap_model_call(request, handler)` 直接改模型输入（当前用这个）。改 request 字段要用 `request.override(...)`（不可变模式），直接赋值已废弃（DeprecationWarning）。
- **插件规范 v0.3（Phase 2 升级）**：skills/<name>/{plugin.json, entry.py, 其他资源}；entry 须导出 `TOOLS` 列表；type=capability(能力型)/procedural(程序型)/knowledge(知识型)/mcp(外部能力)；plugin.json 可带 `system_instruction`（插件自述"什么时候该用我"，注入 system prompt）；`load=eager|lazy`（默认 eager）。**三级加载**：级1 元数据常驻（load_skills 只读 plugin.json，不 import 任何代码，health 即技能目录）→ 级2 指令触发（collect_tools 按需 ensure_loaded 导入入口）→ 级3 资源按需（MCP 会话/embedding 模型/向量库首次调用才初始化并缓存）。
- **MCP 接入（langchain-mcp-adapters 0.3.x 实测 API，勿凭旧教程）**：
  - `MultiServerMCPClient({"<server>": StdioConnection(transport="stdio", command=..., args=..., env=...)})
  - **不是上下文管理器**（0.1.0 起废弃 async with）：直接 `tools = await client.get_tools()`；每次工具调用自动开新会话（docstring 明示）
  - `StdioConnection` 是 TypedDict，**必须带 `transport` 键**（漏了报 "Missing 'transport' key"）
  - **env 不默认继承**：子进程只拿显式传的 env；测试隔离用 `NOTES_DATA` 环境变量（server.py 支持），adapter 侧 `env=dict(os.environ)`
- **RAG 知识库（Phase 2）**：`app/knowledge.py` 定义接口（add/search/count），ChromaStore（Chroma PersistentClient + fastembed BAAI/bge-small-zh-v1.5，512 维；客户端与模型都懒加载）与 LexicalStore（CJK 二元组，离线/测试兜底）可插拔；`knowledge_store=chroma|lexical` 配置切换；数据在 backend/data/knowledge/<partner>/。**embedding 模型下载必须走 HF 镜像**（`HF_ENDPOINT=https://hf-mirror.com`，实测直连 huggingface 超时；config.hf_endpoint 默认已设）。
- **system prompt 组装顺序（重要设计）**：插件使用规则（最高优先级）在前，人设在后。实测 2B 模型人设在前会压掉工具调用（详见验证记录）。
- **多用户后置**：Phase 4 才做 PG+JWT；当前无鉴权，thread_id 即会话键。

## 环境事实（重要）
- 后端 Python 3.12（uv 管理，`backend/.venv`）；前端 Node 22 / Vite 5 / React 18 / TS。
- **LangGraph 已升到 1.2.12 + LangChain 1.4.2，API 与教程旧代码不同**：
  - `create_agent` 现在从 `langchain.agents` 导入（`langgraph.prebuilt.create_react_agent` 已废弃）
  - 参数名是 `system_prompt`（不是 `state_modifier`/`prompt`）
  - `AsyncSqliteSaver.from_conn_string` 直接透传路径给 aiosqlite，**不能带 `sqlite:///` 前缀**，且是 async 上下文管理器（`async with`）
  - stream_mode="messages" 的 chunk `.type` 是类名（如 AIMessageChunk）而非 "ai"，判断用 isinstance
- 后端启动：`cd backend && uv run uvicorn app.main:app --reload --port 8000`（uv sync 首次装依赖）
- 前端：`cd frontend && npm run dev`（5173，vite proxy /api→8000）

## 验证记录（2026-09-30）
- Phase 0：pytest 4 项全绿；真实 DeepSeek：SSE 逐字流式 ✓ / datetime 插件调用 ✓ / 工具输出过滤 ✓ / 同 thread 跨轮记忆 ✓；前端 `tsc -b && vite build` 通过 ✓
- Phase 1：**pytest 18 项全绿**（新增 test_memory 6、test_partner 4、test_context 4 等）；真实 DeepSeek 端到端：
  - 跨会话记忆：thread A 记"喜欢美式咖啡不加糖" → 全新 thread B 问"你还记得关于我的什么"能答出（含 USER.md 画像：嘉兴/AI 产品/加班/求职作品集）✓
  - datetime 插件回归：答复与真实时间吻合（2026-09-30 21:26 周三）✓；前端代理（vite 5174 → 8000）+ SSE 逐字流式 ✓
  - 摘要压缩：中间件 spy 显示模型输入从持续增长（21 条）→ 稳定 ≤4 条，摘要增量生成 ✓
- Phase 2：**pytest 33 项全绿**（新增 15：加载器 v0.3 5 项、知识库 5 项、MCP 2 项、adapter 3 项）；真实 DeepSeek 端到端：MCP 便签存取 ✓（notes.json 落盘、关键词检索）、RAG 存取 ✓（重复存入 upsert 自动合并，语义检索答出"元数据常驻/指令触发/资源按需"）、adapter 计算 137+265=402 ✓
- **本地 Qwen3.5-2B 实测（重要）**：
  - 纯对话/流式/记忆：正常（约 50 token/s）
  - 工具调用：不稳定。直接 bind_tools 有时成功有时失败；带"糯米宠物"人设时几乎不调工具（模型进入闲聊模式）
  - 调优：把插件规则放 system prompt 最前（"最高优先级"）+ 人设改"伙伴兼智能助手"后，绑定时测试 3/3 成功；但经 create_agent 全链路仍会复现失败（如问时间答"18 点"）
  - 结论：**2B 工具调用不可靠，不能作为演示依赖**；纯对话可本地，工具关键路径用 DeepSeek。此问题在 Phase 2 可通过"模型能力分级"或 MCP 增强缓解，也是面试可讲的真实工程取舍

## Phase 5 全能化规划（2026-10-01 起，当前推进）
1. **执行能力层（核心）**：shell 执行器 + 逻辑沙箱（read-only/workspace-write/full-access 三级）、fs 工作区文件工具（read/write/list/search，路径限工作区防穿越）——agent 从"聊天"到"干活"
2. **subagent 委托**：现有 Supervisor 是 LLM 路由；补"模型主动 spawn 子 agent"工具（tool-subagent）+ 可继续子会话
3. **上下文工程**：compaction 事件化（start/summary/end + 锁 + tool-result-pruner）、spill 溢出存储（大输出落盘 + 定位符）、token-meter 回放计量
4. **交互**：user-questions（工具问用户：选项/表单）、permission-presets（沙箱×审批组合预设）
5. **产物与持久化**：credentials 凭据 seam（env 引用 + 热轮换）、attachment 附件（内容寻址）、deliverables
6. **调度**：todo 清单、schedule 定时提醒（绑定会话到点投递）
7. 前端联动：文件面板 → 真实 fs 工具、权限选择器、消息反馈（赞/踩→eval 回流）
对齐依据：deepseek-harness docs/subsystems（shell/sandbox/fs/subagent/compaction/spill/user-questions/credentials/attachment…），差距分析见会话内可视化图。

## 面试表达要点
- 插件化："技能+工具+MCP 打包成一个插件，加载器按 type 分发，加能力=放目录，换 RAG 方案=换插件，贴合 Codex/豆包行业形态"
- 记忆："人设做成配置而非写死，预置可爱/御姐伙伴只是加配置文件"；记忆双通道（模型主动写 + 系统被动注入），跨会话能想起
- 健壮性（Phase 3）：工具失败重试/fallback；写操作 human-in-the-loop；评分集 Eval
- 上下文压缩："中间件直接改模型输入而不是改 state——create_agent 的 add_messages 合并会还原裁剪"（真实踩坑，面试讲得出细节）
- MCP："外部能力=MCP server + adapter；客户端连接懒加载，每次调用自动开新会话"（实测 API 细节，讲得出版本差异）
- adapter："外部插件放 tools_external/ 即被适配成自家工具，无 LangChain 依赖也能复用"
- 全能化（Phase 5）："对齐 DeepSeek Harness 的'一切皆插件'，agent loop 本身也是插件；执行能力按沙箱分级（read-only/workspace-write/full-access），写命令黑名单 + 路径防穿越 + 全量命令进审批，安全模型可讲三层"

## Phase 3 已落地（2026-09-30）

- **robust.py**：with_timeout/with_retry/with_fallback + apply_robust（plugin.json `robust` 字段统一应用）
- **approval.py**：ApprovalGate 审批门（`approval` 字段标记高风险工具；/api/approvals 审批 API；AUTO_APPROVE 环境变量跳过）
- **trace.py**：TraceLogger 每轮写 data/logs/trace.jsonl；/logs 端点读取
- **eval**：scripts/eval.py + eval_scenarios.json，10 场景真实 DeepSeek 100%（报告在 backend/data/logs/）
- 测试 44+5(robust/approval/trace)+... 全绿
- 踩坑：@tool 必须有 docstring；Eval 场景的回复格式属模型表达（时间格式中文/整点），rubric 校准后 100%

## Phase 4 已落地（2026-09-30）

- **auth.py 多用户**：JWT(HS256, python-jose) + PBKDF2 用户库（data/users.json）；AUTH_ENABLED=1 后 /api/chat 需 Bearer token；thread 按 `user::thread_id` 隔离；记忆按 `data/memories/<user>/` 分目录（memory.py get_store(user)，插件工具经隐藏 RunnableConfig 取 user）
- **supervisor.py 多智能体**：LLM 路由器(结构化输出 function_calling) → companion/researcher 子 Agent（create_agent 作 subgraph 节点）；/api/supervisor/chat(SSE) + /api/supervisor/info
- **skills/voice**：say TTS→mp3（真实可用）；transcribe STT 接口化占位（adapter 形态）
- **skills/web**：http_get 抓网页正文（stdlib HTMLParser；robust: timeout 10s + retry 1）
- **部署**：Dockerfile.backend/frontend + docker-compose（postgres+backend+frontend，端口 5433/8001/8080 避开本机）；frontend PWA（manifest + sw.js）；desktop/ Tauri2 薄壳脚手架
- **踩坑**：DeepSeek 不支持 response_format=json_schema → with_structured_output(method="function_calling")；create_agent 返回 CompiledStateGraph 无 .tools → build_supervisor 返回工具名清单；PostgresSaver.aput 需 checkpoint_ns 键 + 完整 Checkpoint → 测试用真实 StateGraph 走图路径
- **本地 PG**：brew postgresql@16，initdb 后 pg 自启（5432）；测试自动跳过（PG 不在时）

## 前端改版 + 插件管理（后续迭代 2026-09-30）

- 后端 app/plugins.py：PROGRAM_PLUGINS（voice-input）+ build_plugin_list；main.py 加 GET /api/plugins、POST /api/plugins/{name}/toggle（技能插件 toggle 后 rebuild_agents：collect_tools(enabled=...) + 重建 agent/supervisor）；make_prompt_builder 加 memory_enabled——停用 memory 插件时中间件不注入记忆（真失忆）
- 前端：移除登录 UI；App.tsx 三栏布局（角色/聊天/插件面板）+ 语音输入（webkitSpeechRecognition，voice-input 开关控制麦克风）；CatAvatar.tsx（SVG 猫 + 4 状态表情 + 尾巴动画）；PluginPanel.tsx（程序/功能/MCP 分组 + switch）
- 测试 65 passed（+4 test_plugins）
- 踩坑：DeepSeek 记忆中"引擎注入层"与"工具层"是两回事——插件开关要管住能力必须两层都控制，不能只删工具

## 统一插件体系 + 团队 + 模型管理（后续迭代 2026-09-30 第二轮）
- 目录 skills/ → plugins/（物理统一）；app/skills.py 加载器按 type 分发：capability 系列→tools，program→运行时钩子；app/plugins.py 删除硬编码 PROGRAM_PLUGINS，统一 build_plugin_list + toggle_plugin（程序型调 on_toggle，能力型重建）
- 新程序插件：plugins/voice-input（语音开关 settings）、plugins/team（Supervisor 挂卸；on_toggle 控制 app.state.supervisor；/api/chat 统一路由 use_team）
- 模型管理 app/models.py：MODELS 预设（deepseek/doubao/llama-local，OpenAI 兼容），GET /api/models + POST /api/models/{key}/activate（切换重建 Agent）；llm 改存 app.state.llm_cfg 支持运行时切换
- 前端：react-ai-pet（PetBuddy.tsx，mochi 形状=糯米），移除模式按钮（团队=插件开关），PluginPanel 顶部加模型切换；删除 CatAvatar.tsx
- 测试 70 passed（+test_models 4 + team 用例）
- 踩坑1：messages 流模式 astream 产出 (chunk, metadata) 元组，单变量遍历会丢 token
- 踩坑2：重启后端必须杀干净所有 LISTEN PID（awk 全部），残留旧进程会导致开关状态不一致的假象

## 插件规范 v0.5：移植 DeepSeek Harness / Cordis（2026-09-30 第三轮）
- 设计依据：/Users/superman/projects/code/deepseek-harness（docs/cordis-tutorial/01-first-plugin.zh.md + docs/subsystems/skills.zh.md）——插件=导出 apply(ctx)；ctx=服务+事件+生命周期容器；skill 目录只给模型 name+description（正文按需）；启停=配置组合
- backend/app/plugin_runtime.py：EventBus（subscribe/publish，异常隔离）+ PluginContext（provide/on/effect/dispose）+ 事件常量 MESSAGE_RECEIVED/RESPONSE_DONE/TOOL_CALLED/PLUGIN_TOGGLED/MODEL_SWITCHED/APPROVAL_CREATED
- backend/app/skills.py v0.5：LoadedSkill 增加 skill_body/when_to_use；load_skills 解析 SKILL.md frontmatter；collect_skill_catalog（<available_skills> 目录只含 name+description+何时用，正文不进常驻上下文）；collect_program_plugins
- backend/app/plugins.py：load_program_plugins（启动对程序型逐个 apply(ctx)）；unload_program_plugin（dispose）；toggle_plugin 事件驱动（改集合→apply/dispose→发布 PLUGIN_TOGGLED→停用再 dispose，插件自己响应自身状态：team 挂/卸 Supervisor、voice-input 翻设置）；build_skill_tool（skill_doc 工具：模型按需读 SKILL.md 全文，未知/停用/程序型有明确返回）
- 程序插件重写为 apply(ctx)：plugins/voice-input（provide 服务 + 订阅 toggle）、plugins/team（确保 Supervisor + 订阅 toggle 挂卸）、plugins/mood 新建（订阅 RESPONSE_DONE → analyze_emotion 关键词规则 excited/happy/curious/surprised/shy/proud/sad/neutral → app.state.last_emotion）
- 7 个能力插件各加 SKILL.md（frontmatter name/description/when_to_use + 正文说明书）
- main.py 接线：lifespan 初始化 event_bus/services/plugin_ctx/last_emotion；rebuild_agents 工具集并入 skill_doc（系统内置）；system prompt 注入 skill 目录；/api/chat done 事件携带 emotion；activate_model 发布 MODEL_SWITCHED
- 前端：PetBuddy EMOTION_MAP（情绪→表情+reaction，react-ai-pet 合法值 sparkle/ponder/shocked/nuzzle/nod/gloom）；App.tsx onDone 收到 emotion 播放 2.6s 后回 idle
- 测试 79 passed（+test_harness_v05 9 项：事件总线/PluginContext/mood 规则/情绪联动/停用即卸载/skill_doc/目录纯净性/事件驱动设置）
- 踩坑：mood 规则"！"太宽泛吞掉"居然"（surprised）→ 惊讶词排到 excited 前；react-ai-pet ReactionId 无 shock/blush/cry（是 shocked/nuzzle/gloom）

## 插件架构 v0.6：去掉 type，完整对齐 Harness（2026-09-30 第四轮）
- 回应两个架构问题：① 还需要区分程序/功能插件吗 → **不需要**（Harness 无 type，一切皆插件，区别只在 apply(ctx) 注册什么）；② 页面显示的是插件还是工具 → **都不是**，改为"能力面板"（每个插件展示它贡献的技能/服务/工具/事件）
- app/plugin_runtime.py：PluginContext 增加 register_tools / register_skill / 事件记录；SkillContribution dataclass
- app/skills.py：scan_plugins（只读 plugin.json+SKILL.md 建注册表，不 import）；PluginDescriptor 无 type 字段（兼容遗留 is_program=False）
- app/plugins.py：load_plugins（启动对全部插件 apply(ctx) 收集贡献）；_apply 兼容旧 tool.py 形态（无 hook.py 自动注册 TOOLS）；toggle 顺序修正：改集合→**publish PLUGIN_TOGGLED（处理器活着响应）→ 再 dispose**；build_plugin_list 改为贡献视图 {skills,tools,services,events}
- 7 个能力插件补 hook.py（apply 里 spec 加载同目录 tool.py 注册 TOOLS）；全部 plugin.json 移除 type 字段
- main.py：lifespan 先 load_plugins(app) 再 rebuild_agents()（工具集来自 apply 后贡献）；app.state.checkpointer 提前（team apply 依赖）；chat/supervisor 两处 payload 判空（None node payload）
- 前端：PluginPanel 改为能力面板（技能型能力 / 运行时扩展 两组，技能/服务/事件 彩色 chip）；api.ts PluginInfo 改 contributions
- 测试 80 passed（test_skills 重写为 v0.6 语义：apply 收集贡献/目录纯净性/入口错误；test_plugins 改贡献视图断言）
- 踩坑1：lifespan 顺序——rebuild_agents 若在 load_plugins 之前会拿到空工具集（v0.5 是自动 import，v0.6 依赖 apply 后贡献）
- 踩坑2：toggle 必须先发布事件再 dispose，否则插件自己的 on_toggle 已被卸载收不到（supervisor 摘不掉）
- 踩坑3：team apply 里构建 Supervisor 依赖 app.state.checkpointer，必须提前赋值

## V3 完整重构：Cordis 内核 + 一切皆插件（2026-09-30 第五轮，最终架构）
- 完整移植 DeepSeek Harness 设计（docs/architecture.zh.md）：**无特权内核**——agent loop 本身也是插件；插件=目录+plugin.json+模块导出 apply(ctx)；inject=[...] 声明服务依赖，未就绪停在 PENDING，提供方卸载→依赖自动卸载→恢复重载；事件 5 分发（emit/parallel/serial/bail/waterfall，waterfall=环绕中间件可短路）；Profile+有序 patch 层叠=应用插件树（换能力=改配置行）；Seam=Definition/Provider/Consumer 三件套；"模型可见即已记录"
- **backend/app/core/**（V3 内核）：
  - events.py：EventBus 5 分发 + v0.6 兼容 subscribe/publish 双接口
  - scope.py：分层服务注册表 + owner 跟踪（provide_by）
  - context.py：PluginContext v3（inject/config/provide/service/get/on/5 分发/注册工具技能/effect/dispose；provide 双写 app.state.services 兼容旧读点）
  - fiber.py：Fiber 状态机（PENDING→LOADING→ACTIVE→FAILED→UNLOADING→DISPOSED）+ Registry.reconcile（依赖驱动收敛）+ plugin.json 元数据合并 + ctx.config 注入
  - composition.py：resolve_profile（分层 patch 覆盖语义）+ default_profile（base 服务+模型/agent preset/team+10 个能力插件+runtime）
  - skill.py：SkillContribution/SkillDefinition
- **plugins/**（项目根，Seam 形态）：
  - service-tools（ctx.tools：ACTIVE fiber 汇总 + tools/pre-execute waterfall 审批 + tools/result 事件）、service-sessions（checkpointer holder）、service-system-prompt（inject=["memory"]）、service-memory、service-settings（全局+每插件设置，settings/changed 热更新）、service-agent-loop（ctx.agents 注册表 + AgentLoop.resolve()：team 启用→Supervisor/updates，否则单 Agent/messages；订阅 settings/changed、plugin/toggled、plugins/loaded 重建）
  - llm-deepseek/doubao/local（llm_provider.py provide_llm 共享实现）、agent-companion/researcher（Agent preset）
- **backend/app/composer.py**：NuomiComposer（load/toggle/install/uninstall/list/available）；toggle=改 profile→挂/摘 fiber→reconcile→事件；install 支持目录/zip/git（校验 plugin.json、失败回滚）
- **main.py**：lifespan 改 composer 驱动；/api/plugins（fiber 状态+贡献+available）、install/install-upload/uninstall、/api/settings（GET+全局+每插件 schema）全部新路由；chat 走 AgentLoop.resolve()
- **前端 V3（Harness client 模块化）**：src/modules/{ui-avatar,ui-chat,ui-input,ui-sidebar,ui-plugin-manager,ui-settings}；表情层保留（react-ai-pet，done 事件 emotion→表情 2.6s 回 idle）；插件页=清单+状态 chip+开关/卸载+**导入**（zip 上传/目录/git）；设置页=全局参数+**schema 驱动插件设置表单**（plugin.json settings 声明）+模型切换
- 测试 101 passed（+test_core_v3 12 + test_v3_import_settings 9）；真实 smoke 全通（chat 流式/plugins/settings/导入 weather 后卸载）
- 踩坑1：Pydantic `from __future__ import annotations` 下**函数内 class BaseModel 是 ForwardRef 解析失败**（当 query 参数→422）→ 请求模型一律模块级 + main.py 必须 import Any
- 踩坑2：SettingsStore 用 threading.Lock 在 set()→save() 二次取锁**死锁**（POST /api/settings/global 挂死）→ 改 RLock
- 踩坑3：测试 REPO_ROOT=parents[1] 指向 backend 而非项目根（plugins 目录不存在→服务插件全没挂载→503）；install 测试 source 传外层目录导致复制后 plugin.json 缺失
- 踩坑4：路由注册顺序 OK，但新 body 模型若未解析会被 FastAPI 当成 query（见踩坑1）——以 openapi spec 验证 requestBody 是否存在为准

## V3 增强：项目/会话 + 输入栏模型选择 + 展示（2026-10-01 第一轮）
- 调研 deepseek-harness client（50+ ui-* 模块）后补齐糯米缺的核心功能：模型+思考强度选择（ui-model-selection）、项目/会话（workspace/session 槽位 + session.new 新建按钮）、会话自动标题、思考过程折叠（ReasoningRow）、每轮 token 用量（TurnUsagePanel 轻量版）
- 后端 backend/app/projects.py：ProjectStore（SQLite data/threads.db，projects/threads 表，独立于 checkpointer）；API GET/POST /api/projects、DELETE、GET/POST /api/threads、PATCH 重命名、DELETE、GET /api/threads/{id}/messages（checkpointer 历史）；lifespan ensure_default_project
- chat 增强：thread 自动注册（兼容旧 thread_id upsert 不重新生成）、首条消息 auto_title（截断 24 字，Harness 用 LLM 生成可后续换）、reasoning 事件（DeepSeek reasoning_content 流式透传）、done 携带 usage（usage_metadata 真实 token 统计）、req 支持 project_id/effort
- 前端：api.ts 加 projects/threads/messages 端点 + reasoning/usage 事件；ui-model-selection/ModelSelect.tsx（模型+思考强度两级菜单，trigger 显示 模型名+effort，参考 Harness ModelSelect Pane root/model/effort）；InputBar 嵌入 ModelSelect；SideBar 加会话区（项目选择下拉+新建项目、＋新增会话、会话列表含时间/重命名✎/删除🗑，hover 显示）；ChatWindow 加标题头（点击重命名）+ ReasoningRow 折叠 + UsagePill
- 测试 107 passed（+test_projects_threads 6）；真实 smoke：项目/会话/chat effort/自动标题/会话历史 5 条全通
- 踩坑1：LangGraph 新版 checkpoint 结构是 channel_values.messages（不是顶层 messages）→ 历史读取必须兼容两者
- 踩坑2：V2 supervisor.py router_node 对路由 LLM 返回 None（弱模型/FakeChatModel）直接 res.get 崩 → 加 None 回退 companion
- 踩坑3：main.py _chunk_reasoning 里 additional_kwargs 可能为 None（Supervisor 子 Agent 输出）→ (getattr(...) or {}) 兜底
- 踩坑4：测试全量跑时 lifespan 未 seed 默认项目导致 GET /api/projects 空 → ensure_default_project 放 lifespan

## V3 前端视觉重构：对齐 DeepSeek Harness dsw 设计系统（2026-10-01 第二轮）
- 用户否定旧暖橙卡片风（"不够清爽、没有大厂感"），要求参考 deepseek-harness 设计
- 调研 Harness ui-theme/src/styles/design-platform.css + base.css + ConversationRoot/InputBar/ChatView 等 *.module.css，提取 dsw 设计 token：浅色 bluish 中性板（neutral-50 #f9fafb 底 / neutral-1000 #0f1115 字 / blue-500 #3b82f6 强调 / blue-600 #2563eb 深强调）、hairline 边框 rgba(0,0,0,.04/.1)、软阴影、系统字体栈
- 布局对齐：聊天列居中 clamp(680px, 64vw, 920px)、输入框卡片 max = 聊天列 + 32px、滚动区全宽 + scrollbar-gutter stable + 极简滚动条（2px 偏移语义）
- styles.css 全量重写（824 → 560 行）：中性蓝主视觉；保留全部 class 名兼容组件；App.tsx 包一层 main（两栏 grid：232px 侧栏 + 主区）
- 组件细节：user 气泡蓝底白字右对齐、assistant 灰底左对齐、输入卡片 focus 蓝环、模型菜单/项目菜单/会话选中态 blue-50/blue-600、switch/芯片/状态徽章全部中性化
- 保留：左侧表情层（react-ai-pet 果冻橙，产品角色本体）+ 三 tab + 会话区 + 模型选择 + 表情联动
- 验证：npm run build 通过（CSS 15.27 kB）；vite 5173 + uvicorn 8000 均健康

## V3 前端布局重构：抄 Harness AppFrame 三栏骨架（2026-10-01 第三轮）
- 用户要求"布局也大胆抄 Harness"（现布局仍像自研卡片风）
- 调研 ui-layout/AppFrame.module.css + ui-sidebar/SidebarRoot.module.css + HeaderLeadingControls：整体 grid 三列（rail 窄图标列 | sidebar 会话列 | center 主区），sidebar 结构 = 品牌行 logoRow + newSession 按钮 + 会话树 regionArea（scrollbar-gutter stable）+ 底部 footArea；图标按钮 28-36px、hover 用 rgba(38,49,72,.06)
- 糯米落地：.app grid 52px rail | 250px sidebar | 1fr main；新增 modules/ui-rail/Rail.tsx（垂直图标导航 聊天/插件/设置）；SideBar 重写为 Harness 结构（品牌行"糯米·陪伴智能体"+右上角新建会话＋、项目选择 workspace-picker、会话树分组头+计数、底部 footArea tab 指示）；表情层从侧栏移到主区顶部 partner-bar（PetBuddy size 92 + 名字/状态，仍随回答情绪变化）
- 侧栏底色 = Harness sidebar-fill 语义（浅灰 surface-2 #ebeeF2），主区白；会话选中态 blue-50/blue-600；chat-header 去 sticky
- 验证：tsc + vite build 通过（CSS 16.55 kB）；vite 5173 健康

## V3 前端第 4 轮：内置/外部插件分组 + 工作区文件面板（2026-10-01）
- 调研 Harness ui-plugin-manager：页头（标题+说明+刷新+添加插件）、分组卡片（Official/Installed，groupHead + count）、卡片=图标+名称+描述+Switch、点击行展开配置（row.config 独立表单页）；内置 profile bundles 不在页面
- 调研 ui-sidebar-files/FilesBody + SidebarRoot panelList：rail 是 sidebar 面板视图切换（文件/会话/…）；文件树=路径头（38px，border l3）+ 目录/文件行（图标+名称，hover rgba(38,49,72,.06)，子级缩进 18px，2px 滚动条 + scrollbar-gutter stable）
- 后端：composer.list_entry 加 builtin 字段（plugin.json builtin 或 service-* 前缀）→ 19 插件 = 6 内置 + 13 外部
- 前端：Rail 改为 4 视图导航（💬会话/📁文件切 sidebar 面板，🧩插件/⚙️设置切主区）；SideBar 加 panel=sessions|files，files 面板 = Harness FilesBody 视觉（路径头 糯米/项目 + 工作区树：新建项目/项目目录/会话文件行，缩进+hover+时间戳）；PluginManager 重写为 Harness 分组卡片（内置组🔒不可停用仅展示 + 外部组可开关、点击展开 schema 参数表单保存 /api/settings/plugins/{id}、卸载）；页头 + 添加插件展开式导入
- 验证：pytest 107 passed；tsc+vite build 通过（CSS 20.15 kB）；api 分组正确；vite/uvicorn 健康

## V3 前端第 5 轮：深色主题 + 单栏布局 + 左下角设置（2026-10-01，用户贴 Harness 深色截图）
- 用户贴 DeepSeek Harness 深色客户端截图："抄都不会抄、是你现在的样子吗"；明确"没有登录，左下角直接放设置"
- 截图揭示 Harness 展开态：单栏侧边栏（非 rail+sidebar 双栏）——品牌行 + 新会话全宽按钮 + 插件导航 + 工作区分组（项目=工作区项）+ 会话列表 + 底部用户区(SUN)；主区聊天；右侧"开始"面板
- 深色 token（design-platform.css dark）：bg-base bluish-950 #151517、sidebar-fill bluish-900 #1b1b1c、layer-2 #2c2c2e、文字 bluish-50/300/400、边框 rgba(255,255,255,.06/.12/.16)、hover rgba(255,255,255,.08)、DeepSeek 蓝 400 #7aaaff / 450 #5686fe / 500 #4176e6
- 落地：styles.css 全量换深色（删除 rail/files-pane 样式）；.app 改单栏 grid 264px+1fr；删除 modules/ui-rail/Rail.tsx；SideBar 重写为截图结构（品牌行🍡糯米可点回对话 + ＋新会话蓝按钮 + 插件导航项 + 工作区头+项目下拉+会话列表 + 底部⚙️设置按钮）；App.tsx 去 panel/Rail，tab=chat|plugins|settings
- 深色细节：输入卡片 surface+line-2、assistant 气泡 surface+细边、user 气泡 deepseek-450 蓝、模型菜单/项目菜单 overlay surface、滚动条白色 20%
- 验证：tsc+vite build 通过（CSS 18.61 kB）；vite 5173 + uvicorn 8000 健康

## V3 前端第 6 轮：设置改弹窗（对齐 Harness SettingsRoot）（2026-10-01）
- 用户："黑色是因为主题，点击设置应该弹出一个弹窗，看看 harness 是怎么样的"
- 调研 Harness ui-settings-general/SettingsRoot：sidebar-foot trigger 点击 → body-portal 居中模态（760x500，full-viewport mask）+ 左侧 section nav rail（账户/模型/预设/插件/归档）+ 右侧内容区；Esc/遮罩/× 关闭
- 落地：新建 ui-settings/SettingsModal.tsx（modal-mask 遮罩 + 居中 760x500 面板 + 160px 左导航 模型🧠/全局🌐/插件🧩 + 右侧内容区；Esc/遮罩/× 关闭）；复用 SettingField schema 渲染 + 全局键添加 + 模型切换
- App：tab 收敛为 chat|plugins（settings 不再整页），settingsOpen state；SideBar foot-settings → onOpenSettings 弹窗；删 SettingsPanel 使用
- 验证：tsc+vite build 通过（CSS 20.49 kB）；vite/uvicorn 健康

## Phase 5 第一轮：定位转型 + 执行能力（shell/fs）（2026-10-01）
- **定位转型**：陪伴型 → 全能型（对齐 DeepSeek Harness）；AGENT.md 定位段、README 路线图/目录结构同步更新；陪伴资产（伙伴人格/表情层）保留为可选人格层
- **plugins/shell**（新）：bash + bash_full 双工具；逻辑沙箱三级 read-only（写命令黑名单+重定向拦截）/ workspace-write（cwd 锚定工作区+绝对路径写/..穿越拦截）/ full-access（bash_full 独立工具，plugin.json approval 进审批门）；环境白名单（剥离 DEEPSEEK_API_KEY 等敏感变量）、超时（settings.shell_timeout）、输出截断（shell_max_output）、bash -c 不加载用户配置
- **plugins/fs**（新）：read_file/write_file/list_dir/search_files/delete_file 五工具；路径 resolve 后必须落在工作区根内（防 .. 穿越/绝对路径逃逸）
- **config.py**：新增 workspace_dir（backend/data/workspace，默认）/ shell_default_mode / shell_timeout / shell_max_output + workspace_path property
- **profile**：default_profile + data/nuomi.json 都补 cap-shell/cap-fs（data/nuomi.json 是持久化 profile，load 只读不覆盖——新增插件必须同时改两处）
- **supervisor.py 全能化**：子 agent 工具从硬编码角色白名单（companion 5 个/researcher 5 个）改为共享全量 tools；角色差异保留在 system prompt
- **修复既有 bug（main.py updates 透传）**：use_team 分支 `for m in msgs` 内 break 导致只透传子 agent 第一条 AI 消息（常是工具调用、text 空），后续回复被吞（done.content 空、无 token 事件）——去掉 break 后流式/回复/usage 全正常
- 测试 126 passed（+19 test_shell_fs：沙箱拦截/路径边界/审批包装/环境剥离/超时）；真实 DeepSeek：fs 写读 ✓（notes/smoke2.txt 落盘）、shell date ✓（回复真实时间）、流式 ✓
- 踩坑1：新插件不进 health——profile 白名单机制（default_profile + 已存在的 data/nuomi.json）两层都要加
- 踩坑2：Supervisor 子 agent 工具看不到新插件——V2 硬编码 pick() 白名单，全能化改为全量
- 待办：前端文件面板接 fs 工具、bash 的 tool 事件前端展示、permission 选择器（P1）
## Phase 5 第二轮：模型管理重构（供应商 → 模型 → 思考强度，去温度）（2026-10-01）
- **backend/app/models.py 重写**：PROVIDERS 供应商树（deepseek / doubao / local），每供应商多模型，每模型声明 efforts（如 deepseek-chat: low/medium/high、local-llama: medium）；无 temperature（对齐 dsh ModelSelection={provider, model, reasoningEffort?}）；build_model_llm(provider, model, effort) effort 仅在模型 efforts 内经 extra_body 透传；list_providers() 返回供应商树（含 active/available）；MODELS 保留为兼容读点
- **llm_provider.py**：provide_llm(ctx, provider)；去 temperature；settings 的 model 键不再承担切换（统一走 /api/models/activate）
- **main.py**：GET /api/models 返回 providers 树；POST /api/models/activate（body {provider,model,effort}，替换旧 /api/models/{key}/activate）；ActivateRequest 模块级定义（避免函数内 BaseModel ForwardRef）；activate 更新 scope.llm 服务 + rebuild_agents + MODEL_SWITCHED 事件；lifespan 初始化 model_provider/model_name
- **前端**：api.ts 重写 fetchProviders/activateModel(provider,model,effort)；ModelSelect 三级菜单（供应商分组模型 + 当前模型 efforts）；App.tsx/InputBar/SettingsModal 全部切新 API；SettingsModal globalOrder 移除 temperature；删除死文件 frontend/src/PluginPanel.tsx、ui-settings/SettingsPanel.tsx（均无引用）
- 测试：backend 127 passed（test_models 重写为供应商树语义：列表树/activate local+effort 透传/effort 越界静默忽略/缺 key 404/未知 provider 404）；tsc --noEmit 通过；运行时验证 /api/models 新结构 + activate 往返 + 真实 DeepSeek 聊天 ✓
- 踩坑：重启后端时旧 uvicorn 进程未被 SIGTERM 释放端口（bind already in use），需 kill -9 后重启
- 待办：#6 指令系统 / #7 主题切换 / #8 项目结构清理（backend 旧模块核验）/ #9 Tauri 桌面版
## Phase 5 第三轮：指令系统 + 主题切换 + 结构清理（2026-10-01）
- **指令系统（对齐 dsh commands 子系统）**：前端 modules/ui-input/commands.ts——CommandDef（name 无斜杠小写/description/hint/handler）+ parseCommand（/ 单独输入显示全部命令）+ 发现视图；InputBar 集成 '/' 菜单（Enter 执行 / Tab 补全 / ↑↓ 选择 / Esc 关闭），命令**直接执行不创建模型消息**，结果经 .cmd-feedback 条呈现；内置命令 /help /new /clear /theme /settings /plugins /model（App 组装 handler 闭包）
- **深浅主题（CSS 变量化）**：styles.css 已有 dsw 深色变量集，新增 [data-theme="light"] 浅色 bluish 变量覆盖（白底/深字/深色边框），6 处 #fff 与滚动条等残留硬编码替换为 var()；data-theme 挂 **document.documentElement**（挂 .app 上 body 不继承背景，已踩坑修复）；侧边栏底部主题切换按钮 + localStorage 持久化（nuomi-theme）
- **结构清理**：删除无引用死文件——frontend/src/PluginPanel.tsx、frontend/src/modules/ui-settings/SettingsPanel.tsx（零引用）、backend/app/events.py（事件总线在 core/events.py，零引用）；plugin_runtime/context/skills/plugins 均被引用保留；scripts/smoke.sh 保留（冒烟有用）
- 浏览器实测：命令菜单 7 条渲染 ✓、/theme 执行换主题 + 反馈条 ✓、浅色 bg rgb(255,255,255) ✓、localStorage 持久化 ✓；tsc 通过；后端 127 passed
- 待办：#9 Tauri 桌面版评估与搭建
## Phase 5 第四轮：Tauri 桌面版搭建（2026-10-01）
- **结论：可以开始用 Tauri 桌面版做开发测试**。rustc/cargo 1.97.1 + cargo-tauri 2.3.0 可用；desktop/src-tauri 薄壳（Tauri2）已跑通
- 修复 4 个编译问题：① 缺 src/lib.rs（Tauri2 模板要求 lib 目标，main.rs 调 lib::run）② tauri.conf.json 顶层 name/description 不被接受（改 productName/identifier）③ frontendDist 相对路径错（../../frontend/dist）④ 缺 icons/icon.png（python 手写 PNG 生成 512x512 蓝底团子）
- 验证：cargo check ✓；cargo-tauri dev 编译并启动 ✓（target/debug/nuomi-desktop 进程持续运行、WebKit 子进程正常，17 分钟无崩溃；当时屏幕锁屏无法截图窗口，解锁即可看到）
- 架构：窗口加载 frontend/dist（Vite build 产物）+ API 走 http://127.0.0.1:8000 后端（CSP connect-src 已放行）；Rust 层极薄
- 用户判断确认：web 端确实"打不开 shell"（浏览器沙箱）；但 nuomi 的 bash/fs 由后端 Python 执行，web 能用 shell 能力；Tauri 的价值 = 本地应用形态 + 未来 sidecar 打包免起后端 / Rust 本地执行沙箱
- 下一步（按需）：tauri-plugin-http 本地 fetch 绕过 CORS；Python 后端 sidecar；Rust 侧 shell/fs 直达
- 运行时进程：后端 8000 + 前端 5173 + tauri dev 均在跑

## Phase 5 · 第七轮 · 输入栏重做（对齐 Harness Composer）

用户批"输入框不好看，抄都不会抄"；对照 dsh `ui-conversation/skeleton/InputBar.module.css`（418 行）重做输入栏：

- **结构对齐**：一张卡片（输入区 + 工具行同卡），删除旧的"控制行(.input-controls) + 矩形按钮(.input-row)"两层结构
- **输入区**：auto-grow（`field-sizing: content`）+ max-height 280（~14 行 cap 内部滚动）；min-height 36（停靠）/ 52（hero 空态）；padding 4px 14px 0；蓝色光标（caret-color accent-strong）；hero 双行 clamp 占位
- **工具行**：flex space-between，gap 12，padding 2px 8px 6px；左 `/` 命令入口（28px 圆 selector 底），右 模型 chip（28px 高 13px/500 透明底 hover 抬升）+ 语音（28px 圆）+ 发送键（34px 圆蓝底白 ↑，disabled 0.4，translateY(-2px) 对齐）
- **卡片**：border 0 + outline 1px hairline + radius-lg + surface 抬升面 + shadow-pop 柔和阴影
- **菜单**：cmd-menu 加 max-height 内部滚动（防超高溢出视口）
- 文件：`frontend/src/modules/ui-input/InputBar.tsx`、`frontend/src/styles.css`（.composer-* 段替换 .input-* 段）、`App.tsx`（hero={messages.length===0}）
- 验证：tsc ✓；浏览器实测 auto-grow 4 行 100px ✓、发送键 disabled 联动 ✓、/ 按钮呼出 7 条命令 ✓、hero 空态 52px 双行占位 ✓；dist 已重建（桌面版加载）

## Phase 5 · 第八轮 · 输入栏修复（沉底 + 发送清空）

用户反馈两问题，根因与修复：

1. **输入框不沉底**：`.chat` 缺 `flex: 1 1 0`，聊天内容增长时聊天区不占满剩余高度，`.inputbar` 被内容顶出视口。修复：`.chat { flex: 1 1 0; min-height: 0; overflow-y: auto }` → 聊天区内部滚动，输入栏恒定视口底部。
2. **发送后输入框未清空（体验）**：清空逻辑本在父级 send()；改为输入栏自身保证——`handleSend()`（清空 + 调用 onSend + requestAnimationFrame 焦点回 textarea），Enter 与发送按钮统一走此路径；发送后焦点恢复输入框（此前点发送后焦点留在按钮）。
- 验证：浏览器实测发送后 value=''、焦点回输入框、输入栏 837/837 恒定沉底、chat 溢出（30 条注入消息）时输入栏仍固定底部；tsc ✓；dist 已重建并重启 tauri dev（桌面版加载最新）。

## Phase 5 · 第九轮 · 侧边栏品牌非交互化

用户反馈"左侧糯米 全能智能体不应该是按钮"：`.sidebar-brand` 由 `<button onClick=回对话>` 改为纯展示 `<div>`，去掉 cursor:pointer / hover 背景 / title。
- 验证：DOM 中 tagName=DIV、cursor=auto、元素列表不再出现品牌按钮；tsc ✓；dist 重建并重启 tauri dev。

## Phase 6 · 设置面板补齐（对齐 dsh ui-settings；不做登录/多用户）

用户要求 P0+P1 全做、明确不做登录与多用户。对照 dsh 8 分区，落地 4 分区（通用/模型/行为/插件）：

**后端**
- models.py 重构：BUILTIN_PROVIDERS（deepseek/doubao/local）+ 自定义供应商（settings.global["custom_providers"]，OpenAI 兼容：base_url+protocol+api_key+models[]）
- API：POST/PUT/DELETE /api/models/custom（增删改，key 唯一 custom-<host>-<name>-<rand>）、POST /api/models/provider-key（内置供应商 key，优先于环境变量）、GET /api/models/available（拉取 /models 可用列表）
- 激活持久化：active_model 写入 settings，启动恢复（build_app 无测试 llm 注入时）
- API Key 掩码回显（sk-r***1234）；明文不进任何响应
- Shell 沙箱模式：settings.global["shell_default_mode"] → plugins/shell（hook 监听 settings/changed 热更新 set_default_mode；bash 工具 mode 默认 None → _effective_mode）
- /api/health 别名（Vite /api 代理可达，设置面板探活用）
- 团队模式如实说明：单层 supervisor 无递归/并行概念 → 不提供假设置项

**前端**
- SettingsModal 重写：分区 通用(主题/后端连接/版本)/模型(供应商树+API Key 行+自定义供应商增删改+模型目录 textarea+拉取可用模型)/行为(Shell 三档 radio+团队说明)/插件（保留）
- 删除「全局」JSON 分区（用户要求）；侧边栏主题按钮移除（主题并入设置-通用，用户要求）
- api.ts：+addCustomProvider/updateCustomProvider/deleteCustomProvider/setProviderKey/fetchAvailableModels

**验证**：pytest 132 passed（+custom CRUD/掩码/持久化恢复/provider-key/available 校验/shell 模式）；tsc ✓；浏览器实测：分区 4 项、health ● 正常、API Key 行、添加自定义供应商成功并持久化、shell 三档切换生效；dist 重建 + 桌面重启。

## 模型设置统一供应商管理（用户要求：不要"一个供应商一个插件"）

设置-模型分区重写为统一供应商列表：内置（DeepSeek/豆包/本地）标「预设」、自定义标「自定义」，同一卡片形态（头部展开 ▾ + 模型列表 + API Key 行内保存），同一个「＋ 添加供应商（OpenAI 兼容）」入口；顶部显示当前激活模型概览。自定义 key 行内保存走 updateCustomProvider 全量（models 转回文本行，api_key 空传 __KEEP__ 不变）；内置走 provider-key API。

## LLM 收为核心服务（用户要求：不该有 llm-deepseek / llm-doubao / llm-local 插件）

用户明确指出"这些插件都只是一个供应商"：删除 plugins/llm-deepseek、llm-doubao、llm-local 三个目录与 backend/app/llm_provider.py；LLM 由核心服务提供（models.py BUILTIN_PROVIDERS + custom_providers + active_model 启动恢复 + /api/models/activate 切换），供应商只是配置维度。default_profile 与 backend/data/nuomi.json 移除 llm 条目；测试断言更新（新增 test_llm_is_core_service_not_plugin 回归：插件列表不含 llm-*）。133 passed；health 插件列表已无 llm-*。

## 移除内置供应商（用户要求：deepseek/doubao/local 都不该内置，全部手动添加）

models.py 删除 BUILTIN_PROVIDERS（deepseek/doubao/local）与 PROVIDERS/MODELS 兼容读点、_resolve_model_id/_is_available/_builtin_models；供应商树 = 纯 custom_providers（settings.global）。find_model 校验 API Key（无 key → 404，输入栏只列可用）；无供应商时 health model="none"。main.py 删 POST /api/models/provider-key 与 ProviderKeyRequest；默认 model 名改 "none"。前端删 setProviderKey、"预设"徽标，模型分区只显示手动添加的供应商（空态提示添加 DeepSeek 示例）；key 行内保存统一走 updateCustomProvider。测试重写为纯自定义语义（无内置树/带 key 激活/缺 key 404/回归），132 passed。

## 前端架构分层（docs/frontend-architecture.md）

- 样式四层：Token(tokens.css) → 基元(primitives.css) → 组件(components.css，未来逐模块拆) → 布局(layout.css)；main.tsx 按序 import，vite 合并为一个产物。
- tokens.css 新增语义 token --ok/--warn；硬编码色值清零（components.css 无 hex 色值）；设置-模型行类名 plugin-name→model-name 清扫。
- 主题机制：data-theme 属性 + 主题包覆盖原始 token（未来 themes/<name>.css 注册）。
- 国际化：i18n/ 字典 + t() 预留（~89 处中文按模块分批迁移，新代码禁硬编码中文）。
- 纪律：新样式进基元/模块，禁新色值，新文案走 i18n。

## 前端架构落地（P1+P2 已完成，详见 docs/frontend-architecture.md）

- 样式拆分：components.css 已拆为 modules/ui-input/input.css、ui-model-selection/model.css、ui-plugin-manager/plugin.css、ui-settings/settings.css；mini-btn/icon-btn 提升到 primitives.css；滚动条/窄屏归 layout.css。
- i18n：i18n/index.ts（t(key,params) + setLocale + localStorage nuomi-locale）+ zh-CN.ts（MessageKey 类型强约束）；全部 UI 文案 t() 化（硬编码清零，注释除外）；SideBar 因局部变量 t 冲突用 `import { t as tr }`。
- 主题注册：styles/themes/light.css 独立主题包；frontend/src/themes.ts THEMES 清单驱动设置-通用 radio；新增主题=加 css + 加清单行。
- 注意：JSX 属性中文迁移必须写成 `title={t("key")}`（曾因漏花括号/多括号反复修）；多行 import 后插入 import 会被劈开（插入点在 import 块末尾行）。

## 工作区对齐 dsh ui-workspace（纯前端，2026-10）

- 会话列表参考 dsh WorkspaceBrowser：默认折叠 5 条（COLLAPSED_SESSION_LIMIT）+「展开其余 {n} 个会话 / 收起」（localStorage nuomi.sidebar.expanded 按项目持久化）。
- 置顶：行 hover 出现 📌 按钮，置顶会话排最前且标题前常驻 📌 标记；localStorage nuomi.sidebar.pinned 按项目持久化。
- 排序：置顶在前，其余按 updated_at 降序（最近更新，对齐 dsh orderBy.updated）。
- 搜索：会话列表上方搜索框，过滤 title，搜索激活时不折叠；空态区分「无匹配会话 / 还没有会话」。
- 空标题显示「未命名」（对齐 dsh Untitled）。项目选择器 = Workspace 选择器（保留下拉 + 新建项目）。

## 工作区改分组树（去掉项目下拉，对齐 dsh WorkspaceBrowser）

- 侧栏不再有项目下拉框；项目（Workspace）直接铺为可折叠分组：📁 名称 + 计数 + ▾/▴（点击组头=切换工作区并展开，点箭头=折叠），组折叠状态持久化（nuomi.sidebar.groupExpanded）。
- 未分组会话为独立组（dsh Ungrouped，project_id=null）。底部「＋ 新建项目」入口。
- App 线程改为全量拉取（fetchThreads(null)），侧栏前端按 project_id 分组；selectProject 支持 null（未分组）。
- 组内保留：置顶、5 条折叠+展开其余、重命名/删除；搜索为全局跨组过滤。

## Awwwards 级视觉重构（2026-10-01，八维自检迭代）

- **设计红线（沿用）**：tokens.css `:root` 是设计唯一权威；不引入新色值/新圆角/新阴影；深浅主题自动跟随（light.css 覆盖）。
- **Token 体系重写（tokens.css）**：字体三栈（--font/--font-display/--font-mono）+ 9 级字阶 + 流体标题（--fs-hero clamp(24,4vw,34)）；8 级间距刻度；动效 token（--ease-out/--ease-spring/--dur-*）；圆角体系含 --radius-pill；阴影体系（--shadow-pop/float/glow）；环境背景 token（--aurora-*/--noise-opacity）；::selection + :focus-visible 环 + prefers-reduced-motion 收敛。
- **环境背景**：.app::before 极光漂移（blur+opacity 动画）+ ::after 噪点；**关键坑：.app 原 overflow:hidden 使 inset:-12% 伪元素把 .app 变成可滚动容器（scrollIntoView 把整页滚偏 126px、宠物滚出视口）→ 改 overflow:clip 修复**。
- **原创视觉**：icons.tsx 自绘 18 个 SVG 图标（24 网格、1.8px 圆头描边、currentColor，含 LogoMark/MochiOutline 等）替换全站 emoji；favicon 渐变蓝底白糯米团子；manifest 名称/主题色更新；sw.js CACHE nuomi-v3。
- **hero 空态**：partner-bar（PetBuddy 92 + 状态点脉冲 + busy 换色）+ 垂直居中 hint（hero-title 800 字重 + hero-sub + 3 建议芯片 stagger rise + hover 蓝辉光 + hint-sub 脚注）；建议芯片点击直接 onSuggestion 发送（修复了原 t("...") 未翻译文案 bug）。
- **移动端**：≤1024 抽屉（min(300px,86vw)）+ 汉堡（MenuIcon）+ 遮罩 backdrop；≤720 间距收敛；桌面 ≥1024 侧栏 264px 列 + 主区（1180 档收窄 228px）。
- **浏览器实测**（mac_computer_use_tool plane="bu"，视口 702×837）：抽屉/汉堡/遮罩、hero、真实聊天流、插件面板+开关弹簧、设置弹窗（通用/模型分区+主题切换）、模型下拉（effort pill+选中 ✓）、/ 命令菜单（7 条+键盘提示）、浅色主题全站、toast 反馈、hover 微交互计算值（border/color/bg/translateY/glow 全部命中）均 ✓；桌面 ≥1024 用注入桌面断点+DOM 几何验证（侧栏 264 列 + 主区 + hero 居中），**注：强制注入态下主区截图空白属 CNGC 截图合成伪影（elementFromPoint/计算样式均正常，非真实渲染问题），真窗口宽度下待用户肉眼确认**。
- **已探明死路（勿重试）**：bu.cdp Emulation 域报 Session not found（Page 域可用）；window.resizeTo 无效；cu 平面控制 Chrome 报 MAC_GUI_ERROR_7_0（用户操作中勿争抢）；bu.screenshot 固定覆盖 /var/folders/.../gac-runtime/shot.png。
- 验证：npm run build 全绿（CSS 46.9kB / JS 317.7kB）；dist 已重建（桌面版加载）。

## 交互修正轮（2026-10-01，用户反馈三项）

- **双加号修复**：`sidebar.newSession` 文案自带"＋" + JSX PlusIcon 双重渲染 → 文案改纯"新会话"（图标承担加号语义）。
- **工作区分组头整行可点**：`.group-head` 由 button+嵌套 caret 改 div[role=button]，整行 onClick=toggleGroup（展开/收起），移除原"点组头=切换项目并关抽屉"行为；caret 变为纯视觉旋转指示。项目选择改为点会话时 `onSelectProject(g.projectId)` 同步（保持高亮与顶栏新会话目标正确）。
- **项目内新建会话**：组头右侧 `.group-new`（＋ 图标按钮，hover 浮现 opacity 0→1 + scale，focus-visible/当前项目常显），点击 stopPropagation + `onNewThreadIn(projectId)`（App 新增 newThreadIn：setCurrentProjectId(pid) + createThread(pid) + 进入新会话）。
- **设置-模型卡片重设计（对齐 dsh ui-settings-models）**：供应商卡片 = 细描边卡（--line-2，hover 提 border+shadow-pop）+ 头部（名称 + 自定义 mono 标签 + 8px 凭证状态点：已配置=--ok 绿点+柔光、缺失=灰点，title 提示）+ ChevronDown 旋转 caret；展开编辑面 = 内嵌模块填充（surface-2 55% mix + 顶部 hairline，不再双层描边）；添加按钮 = 全宽虚线占位卡（44px，dashed line-3，hover 蓝化），去文案"＋"换 PlusIcon。
- 验证：npm run build 全绿（CSS 48.8kB / JS 318.3kB）；浏览器实测：顶栏单加号 ✓、组头整行点击往返展开/收起 ✓、组内新建会话（计数+1、自动打开、hero 空态）✓、hover 浮现 ✓、模型卡片深浅双主题渲染与计算值（卡面/内嵌面/状态点/caret 旋转）✓。
- **编辑表单统一（用户批"还是原始样式"）**：CustomForm 由旧的上下堆叠（flex-direction:column + 长 label）改为与密钥行同语言的紧凑横向行——`.form-row`（label 96px 左 + input flex-1 右 + hairline 分隔，label 短文案单行；textarea 行 .top 对齐）；input 统一 `.form-input`（与 .api-key-input 同套样式）；API Key 掩码改 label 下 mono 小字 hint；文案精简（baseUrl→"API 地址"、models→"模型目录"，格式说明进 placeholder）。验证：构建全绿（CSS 49.6kB / JS 318.3kB），实测 4 行横向渲染（名称/API地址/API Key/模型目录）+ 保存修改/取消。
- **添加供应商表单重做（用户批"还是很丑/拉取占行/模型目录是文本框/要每模型参数"）**：
  - 模型目录 textarea 删除 → **模型行列表编辑器**（对齐 dsh ModelListEditor）：每行 = 模型ID（mono，flex 1.35）+ 显示名 + ChevronDown disclosure（展开 = 思考强度(逗号分隔)/上下文窗口/最大输出 三格 K/M 后缀输入，K=1000）+ ✕ 删除；底部"＋ 添加模型"虚线按钮；行 focus-within 提亮。
  - **拉取可用模型内联**到模型区头部（提示语右侧，nowrap），不再单独占行；拉取结果直接覆盖为模型行（id=label, efforts=medium）。
  - 参数真正生效：后端 CustomModelRow 加 `context_window/max_output`（1..10M）；POST/PUT 存储映射补两字段；`build_model_llm` 将 max_output 绑定 `max_tokens`，context_window 存档备用；`list_providers/find_model` 回显；卡片模型行显示 "128K ctx · 32K out"（.model-cap mono）。
  - i18n 新增 modelsHint/addModel/modelId/modelIdPlaceholder/modelLabelPlaceholder/efforts/contextWindow/contextWindowPlaceholder/maxOutput/maxOutputPlaceholder；文案精简。
  - 后端 uvicorn 无 --reload，改 backend 后需手动重启（kill :8000 + nohup uv run…，数据在 MemoryStore JSON 原子持久化，重启不丢）。
  - 验证：API 直测 PUT 容量持久化 ✓；UI 全链路（真实输入 128K/32K → 保存 → API context_window=128000/max_output=32000 → 卡片 "128K ctx · 32K out"）✓；构建 CSS 52.49kB / JS 321.02kB；测试供应商已删、llama 原数据保留。合成 input 事件不触发 React（测试须用 bu.type 真实输入）。
- **模型卡片精修（用户批"label 太挤/卡片不需要当前模型/api key 两处"）**：表单字段改**纵向**（.form-field：field-label 上 + .form-input 全宽下，gap 12px，宽输入框不再挤压）；卡片模型行**去掉"当前"徽章**，active 行改蓝色左条高亮（.model-row.active：inset 2px accent + accent-soft 底）；**API Key 只留卡片密钥行一处**（编辑表单移除 API Key 字段，onSave 固定 "__KEEP__"，新增表单保留 Key 字段）；.model-edit-row 内输入补 width:auto 防 flex 溢出。验证：构建 CSS 52.29kB / JS 320.73kB；实测新增表单 4 字段纵向、卡片无 current 徽章（active 左条 boxShadow 命中）、卡片仅 1 个 password 输入、编辑表单字段 = 名称/API地址/模型目录。
- **卡片再简化（用户批"还很丑/编辑不需要/保存密钥不需要/api key 放 api 地址下"）**：**卡片展开 = 内嵌编辑表单**（所见即所得，无独立编辑模式）：字段 = 名称/API 地址/API Key（API 地址下方，label 下 mono 掩码 hint，留空=保留原值 __KEEP__）/模型目录（行编辑器 + 内联拉取）；操作行 = [删除供应商(danger, margin-right:auto)] [取消] [保存修改]，一个保存统一提交名称/地址/密钥/模型；删除旧只读模型行、.api-key-row（保存密钥按钮）、.model-row-actions（编辑/密钥入口）、editingKey/keyInputs/saveProviderKey/activateRow 状态与函数、activateModel 导入；i18n deleteProvider="删除供应商"。验证：构建 CSS 52.48kB / JS 319.18kB；实测卡片展开字段 4 个、无保存密钥/编辑按钮、操作=删除供应商/取消/保存修改、保存（密钥留空）后 dot on + 掩码 **** 不变、API 数据原样；模型切换改由输入栏模型菜单承担（dsh 同语义）。
- **新增供应商表单设计感升级（用户批"添加很丑/还记得设计感吗"，第二轮：用户对比"下面卡片还可以，添加不好看"）**：add 模式头部从"大标题说明区（图标 34px + 两行标题副文 + hairline）"改为**与编辑卡片头同构的紧凑单行卡片头**：`[＋ 图标 24px accent-soft 圆角块] 添加 OpenAI 兼容供应商 [新供应商 custom-tag] …… [credential-dot 灰点=margin-left:auto]`，padding 12px 14px、无 border-bottom（编辑头部无分隔，保持同构）；删除 add-card-copy/add-card-sub 副文区与 hairline。其余（字段/模型面板/sticky 操作条）编辑添加共用。验证：构建 CSS 54.69kB / JS 321.21kB；实测 head 高 48px、无 border、标题+新供应商 tag+灰点、无副文。
- **添加供应商改为就地卡片（用户拍板"添加就直接在下面生成一个卡片，直接编辑"）**：去掉"点按钮→切换成独立 add-card 表单"的模态式切换，**点「＋ 添加供应商」直接在供应商列表末尾插入一张与编辑卡片同构的展开卡片**（setting-model-group custom open add-card：卡片头[＋ 添加 OpenAI 兼容供应商/新供应商/灰点] + 内嵌 CustomForm(mode="add") + sticky 操作条[取消/＋ 添加供应商]），双层 rAF scrollIntoView 自动滚入视野；保存成功 addCustomProvider → setAdding(false) + 列表刷新出现真实卡片；取消 → 卡片消失。添加与编辑共用同一卡片形态，无第二种表单。验证：构建 CSS 54.69kB / JS 321.39kB；实测点添加→列表生成第 2 张卡（open+head+form+滚动可见）、取消→卡片移除+按钮回归、真实输入（名称/地址/模型行）保存→add-card 消失+列表出现"临时测试供应商"、展开删除→确认后卡片消失（bu.js 派发 click 时 window.confirm 被页面上下文自动放行，删除已生效）；后端 API 复核仅剩 llama。
- **编辑/添加卡片逐项对齐（用户批"llama 展开后不一样"）**：根因=内容区样式不一致——llama .provider-body `padding: 6px 10px 12px` + border-top solid + surface-2 55% 混染背景 vs 添加 .add-card .custom-form `padding: 6px 2px 2px` 无分隔无背景（内容贴边）。修复：.add-card .custom-form 对齐 provider-body 全套（padding/border-top/背景）；.add-card-head 改 `<button>`（cursor pointer + hover 背景 + title=取消），尾部加 .provider-caret（ChevronDownIcon），点击=onCancel 收起（与编辑头部点击收起同构）。验证：构建 CSS 55.02kB / JS 321.51kB；实测 llamaBody vs addForm padding/borderTop/背景逐项相等、add-head caret=true、cursor=pointer。
- **卡片头去标题（用户拍板"卡片头不需要显示添加 OpenAI 兼容供应商"）**：添加卡片头部不再显示标题说明——改为与编辑卡片头**结构逐字同构**：`.provider-identity`(名称实时同步 `name.trim() || "新供应商"` + `自定义` tag) + credential-dot 灰点 + provider-caret；删除 .add-card-icon 加号块、.add-card-title 标题、i18n addTitle（保留 newTag 作占位名）；gap 8→10px 对齐 .setting-model-provider。验证：构建 CSS 54.70kB / JS 321.45kB；实测 hasTitle=false/hasIcon=false/name=新供应商/tag=自定义/caret+dot+identity 全中；真实输入"我的中转"→ 头部 nameNow 实时变为"我的中转"；头部点击 → add 卡片消失（=取消）。
- **添加卡片头白底修复（用户批"新供应商卡片头怎么不是白色的"）**：根因=add-card-head 此前渲染在 `.custom-form` **内部**，而 .add-card .custom-form 被上一轮对齐成 provider-body 的混染背景（surface-2 55%）+ border-top，头部被混染底色包裹；编辑卡片的 .setting-model-provider 在 .provider-body 之外（卡片白底）。修复：CustomForm 返回改为 **React fragment**——add 模式 add-card-head 移到 .custom-form 外层（兄弟节点），.custom-form 保留混染背景 + border-top + padding 6px 10px 12px（对齐 provider-body）。验证：构建 CSS 54.70kB / JS 321.48kB；实测 llamaHeadBg === addHeadBg === transparent（同透卡片白底）、addHeadOutsideForm=true、addFormBg === providerBodyBg（混染一致）。
- **操作条随卡片 + 按钮同尺寸（用户批"按钮怎么不是随卡片一起，大小还不一样"）**：①去掉 `.custom-form-actions` 的 **sticky bottom:0**（之前为"操作常驻"加的，副作用=多卡片共用 settings-body 滚动容器时操作条脱离自己卡片吸附 modal 底，造成"不属于卡片"错觉）→ 回普通流，操作条始终在卡片内部底部跟随滚动；②按钮尺寸统一：`.custom-form-actions .mini-btn { padding: 7px 16px; font-size: fs-13; font-weight: 600 }`（此前 primary 单独 8px 20px/fs-13.5 与取消 4px 12px/fs-12 不等高）——取消/主按钮/删除全部等高同型，仅靠颜色（蓝底 vs 描边 vs 红）分主次。验证：构建 CSS 54.63kB / JS 321.48kB；实测 position=static、操作条 rect 在卡片 rect 内、取消/添加供应商 等高 35px（sameHeight=true）。
- **模型行展开面板精简（用户批"展开配置超长 + 思考强度和模型没关系，对话框固定即可"）**：模型行 caret 展开面板（.model-cap-grid）**去掉"思考强度（逗号分隔）"格**，只留上下文窗口 + 最大输出（grid 3 列 → 2 列，两格各 169px）；ModelDraft/保存逻辑 efforts 保留默认 ["medium"]（输入栏模型菜单 ModelSelect 的思考强度选择为对话级设置，不受影响）；i18n 删 form.efforts。验证：构建 CSS 54.63kB / JS 321.22kB；实测 labels=[上下文窗口,最大输出]、cols=2、hasEfforts=false、gridH=68px 紧凑。

## Bug 专项轮（2026-10-01，用户报：会话命名/项目删除，顺带查出 3 个隐性 bug）

- **会话命名改模型生成**：原 auto_title = 首条消息截断 24 字。现 done 事件之后调用激活模型生成短标题（4-12 字，max_tokens=32、timeout=10s、非流式），新增 `title` SSE 事件（顺序：done → title）；失败回退截断。build_model_llm 加 streaming/max_tokens 覆写参数。前端 streamChat 加 onTitle → setThreadTitle + refreshThreads。实测 llama 生成「整理下周工作计划」「列出你的待办事项」。
- **项目删除按钮**：后端 DELETE /api/projects/{id} 早已存在，前端侧栏组头补 `.group-del` 按钮（与 group-new 同构 hover 浮现，danger 色），window.confirm 确认，App.removeProject 清理当前项目/会话状态。i18n 增 deleteProject/deleteProjectConfirm/projectDeleteFailed。
- **修复①（重启后聊天必挂）**：llm 在 composer.load() 之后才注册（依赖 settings），scope.register 不发事件 → agentLoop 首次构建拿到 None，重启后 /api/chat 报 `AttributeError: 'NoneType' object has no attribute 'astream'`（测试注入 llm 在 load 前注册所以测试不暴露）。修复：模型恢复成功后手动 rebuild_agents()；test_models 加回归断言（重启后 loop.agent 非 None）。
- **修复②（删项目不级联删会话）**：ProjectStore 未执行 PRAGMA foreign_keys=ON，threads 的 ON DELETE CASCADE 形同虚设 → 删项目后会话留库成不可见孤儿（实测用户删「求职作品集」后 23 个会话孤儿）。修复：连接时开启 PRAGMA + 启动清理 dangling project_id 的历史孤儿；test_delete_project_cascades_threads 回归。
- 验证：后端 132 passed（+title 事件/级联/重启恢复 3 个回归）；tsc ✓；dist 重建；真实 llama 端到端 title 事件 ✓；浏览器 DOM 验证 .group-del 存在 + hover 浮现 ✓；已提交 1fd2495。

## 交互修正轮二（2026-10-01，用户反馈两处 + 顺带一个挂载 bug）

- **主区标题纯展示**：聊天头部去掉点击重命名/铅笔图标/输入框（ChatWindow 的 editingTitle/titleDraft/title-input 全删，.chat-title 改 DIV 展示）；App 删 renameCurrentThread 与 onRenameTitle 链路；i18n 删 chat.clickRename。
- **会话标题默认空**：NewThreadRequest.title 默认 ""、create_thread/upsert_thread 默认 ""（原「新会话」）；chat 未命名判断扩为 `not cur_title or == "新会话"`；新会话主区不再显示占位名，等模型命名后出现；侧栏空标题显示「未命名」（原有逻辑）。
- **去掉抽屉，侧栏常驻左列**：删 App 的 menu-toggle 汉堡 + sidebar-backdrop + sidebarOpen 状态、SideBar 的 open/onClose；layout.css 删 .menu-toggle/.sidebar-backdrop/.sidebar.open，≤1024 不再 fixed 抽屉而是 `220px 1fr`、≤720 `200px 1fr`（同一框内左分列）；i18n 删 app.openSidebar。
- **修复挂载侧栏空 bug**：初始 useEffect 里 fetchThreads 只用来找标题忘了 setThreads（有已存会话时刷新后侧栏一直空，直到交互才恢复）→ 挂载即 refreshThreads() + 恢复分支补 setThreads(ts)。
- 验证：tsc ✓；浏览器实测无汉堡/无遮罩、grid 200px 502px、sidebar relative、.chat-title 为 DIV 无图标 cursor auto、刷新后 hello 组 6 会话正常列出；后端 12 passed。

## 标题生成并行化 + 占位标题全面清理（2026-10-01，用户要求「最好并行」）

- **并行命名**：`event_stream()` 在回复流开始前 `asyncio.create_task(_generate_thread_title(req.message, ""))` 并行启动（只基于用户消息）；done 事件后立即取结果 → rename/回退 → 发 title。实测 done→title 延迟 **1632ms → 0ms**（llama 场景，回复期间标题已算好）。
- **_generate_thread_title 支持空回复**：prompt 仅在有回复摘要时附加该行。
- **占位标题统一**：projects.py 新增 `PLACEHOLDER_TITLES = {"", "新会话", "新建会话"}` + `is_placeholder_title()`；main.py 命名判断改用之（修复：前端曾传「新建会话」，后端旧判断只认 ""/"新会话" → 模型命名永不触发）。
- **前端默认标题改空**：api.ts `createThread(projectId?, title = "")`（原默认 t("app.newThread") = "新建会话" —— 这是用户看到「还是新建会话」的根因之一）。
- **主区/侧栏过滤占位**：ChatWindow `PLACEHOLDER_TITLES` 命中则不渲染标题（旧会话「新建会话」不再显示）；SideBar 同样将 新会话/新建会话 显示为「未命名」。
- 验证：tsc ✓、12 passed ✓、dist 重建 ✓；浏览器端到端：新会话无占位标题 → 发消息 → 回复完成瞬间主区+侧栏出现「糯米是什么」，全程无「新建会话」。

## 自定义确认弹窗替代 window.confirm（2026-10-01，用户反馈系统弹窗难看）

- 新增 `frontend/src/modules/ui-confirm/ConfirmDialog.tsx`（通用确认弹窗：遮罩 + 居中卡片 + 危险红/主蓝按钮 + Esc 关闭 + autoFocus）。
- 替换全部 4 处 `window.confirm`：侧栏删除会话（含 detail「删除后不可恢复」）、删除项目、插件卸载、设置-删除自定义模型供应商。
- 样式进 layout.css（.confirm-mask/.confirm-dialog，独立 keyframes，不依赖 settings.css）。
- **坑（已修）**：弹窗最初渲染在 SideBar 内部，`.sidebar` 有 `backdrop-filter: blur(6px)` 会捕获 `position: fixed` 子元素 → 弹窗只覆盖侧栏、被「挤在左侧菜单」。修复：`createPortal` 挂到 `document.body`。验证：mask 覆盖全视口、dialog 居中、maskParent=BODY。
