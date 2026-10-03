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
- **存储（2026-10-02 桌面化后）**：全合一 SQLite（NUOMI_HOME/nuomi.db：checkpoints + projects/threads + facts 记忆 + settings 设置）；知识库 Chroma 在 NUOMI_HOME/knowledge/<partner>/；遗留 backend/data/ 由首启迁移一次性只读导入，不删源。
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
- **多用户已移除（2026-10-02）**：桌面单用户形态，JWT/auth.py/users.json、PostgreSQL（langgraph-checkpoint-postgres）、`user::` 命名空间全部删除；本地 API 回环监听无鉴权，thread_id 即会话键。

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

## 新建项目输入弹窗替换 window.prompt + 数据丢失事故恢复（2026-10-01）

- **PromptDialog**：`ui-confirm/PromptDialog.tsx`（复用 confirm 样式，输入框 + 取消/确认 + Enter 提交 + Esc 关闭 + 空值禁用确认，createPortal 到 body）；SideBar 新建项目改用它；i18n 新增 sidebar.newProjectPlaceholder。
- **⚠️ 数据丢失事故与恢复**：用户浏览器测试删除功能时执行了 `DELETE /api/threads/c54cd303a5ae`、`/a4375a74b6db`、`/c9ecb978be4f` + `DELETE /api/projects/3`（hello）→ 级联删光全部会话，threads.db 全空。**恢复方法（可复用）**：会话消息都在 LangGraph checkpointer（`data/nuomi.sqlite` 的 checkpoints 表，msgpack 序列化，通过 `AsyncSqliteSaver.aget_tuple` 读取）；从 checkpoints 提取 12-hex thread_id + 首条 user 消息（截断 24 字作标题）+ checkpoint_id 时间（uuidv7 前 48bit 是时间戳但实测有偏差，采用**归一化**：以最新会话为「刚刚」统一平移）；重建 projects(id=3 hello)+threads 15 条。**教训：删除项目是级联高危操作，测试删除功能会真删数据；threads.db 未被 git 跟踪（backend/data 在 .gitignore），无备份会真丢。**

## 修复 DeepSeek 思考模式 tool_choice 400（2026-10-01，用户切 deepseek 模型后报错）

- **现象**：`OpenAIInvalidRequestError: Thinking mode does not support this tool_choice`（SSE 流内 400）。
- **根因**：团队模式（supervisor）的路由用 `llm.with_structured_output(Route, method="function_calling")` → bind_tools 时绑定 `tool_choice="any"` → DeepSeek 思考模式拒绝显式 tool_choice。
- **修复**：supervisor.py 路由改为**纯文本 JSON 解析**（不再绑定工具/结构化输出），解析失败回退 companion；`router` 注入（测试用）路径保留。
- **实测验证（真实 key）**：无工具 ✓ / 带工具 tool_choice=None（主聊天 create_agent 路径）✓ / function_calling ✗（修复前路径，已不再使用）。主聊天不受影响，仅团队路由修复。

## 桌面化数据与工作区架构（2026-10-02，用户拍板三决策）

用户体检结论（9 项不合理）：数据锚在仓库 backend/data、存储碎片化 10 文件、工作区语义割裂、密钥明文 .env/settings.json、桌面壳未接线、本地 API 无鉴权、多用户 JWT 与桌面冲突、插件源单一、无轮转/迁移。三决策：**① 放弃多用户 ② 工作区默认 ~/Documents/Nuomi ③ 全合一 SQLite**；并追加质疑"backend/app 散落 19 个 py"。设计文档：`docs/desktop-data-architecture.md`（权威，含决策表/目标结构/NUOMI_HOME 布局/移除项/路线 A-D）。

- **单一数据根（用户否决 dev/packaged 双 profile）**：所有运行时数据锚定 `NUOMI_HOME`（env > 默认 `~/Library/Application Support/Nuomi`），dev/打包/Docker 同源，无 profile 切换；仅 `PLUGINS_DIR`/`PARTNERS_DIR` 资源目录覆盖（打包 → sys._MEIPASS）。config.py 重写：db_file/trace_path/knowledge_path/profile_path/workspace_path 全为 property 派生（默认 None），移除 checkpointer/pg/auth 字段；workspace_path 默认 `~/Documents/Nuomi` 自动创建。
- **目录收敛（git mv 保留历史）**：`app/agent/{graph,middleware,supervisor,partner,thread_ctx,models}.py`（graph.py←agent.py、middleware.py←context.py）；`app/plugins/{loader,lifecycle,runtime,composer,approval,robust}.py`（loader←skills、lifecycle←plugins、runtime←plugin_runtime）；`app/storage/{db,projects,memory,knowledge,trace}.py`（db 新增）。批量重写 import（app/main、plugins/*、tests/*）；`app/auth.py`、tests/test_auth.py、tests/test_pg.py 已删。
- **存储合一**：`storage/db.py` 纯 schema 版本化（`PRAGMA user_version=1`，projects 含 directory 列）——**2026-10-02 用户追加拍板：废弃 backend/data、全新环境、无任何迁移**（原"整体复制旧库 + 遗留导入"逻辑已删除，`rm -rf backend/data`；plugins/fs/tool.py 残留的旧 `threads.db` 自建连接改为 `ProjectStore(settings.db_file)` 统一库）。memory.py 重写为 SQLite facts 表（接口不变）；service-settings 重写为 SQLite settings 表；projects.py 加 WAL/busy_timeout/**check_same_thread=False**；trace.py 加 5MB 轮转（保留 3 备份）。
- **多用户移除**：main.py 删 AuthRequest//api/auth/*/UserStore/current_user/`user::` key 前缀/chat Depends；build_app 删 users_file 参数；middleware 删 _user()；sidecar_main.py 简化（仅 frozen 时设 PLUGINS_DIR/PARTNERS_DIR + HF_ENDPOINT）；docker-compose 去 postgres（两 volume：NUOMI_HOME=/app/data、WORKSPACE_DIR=/app/workspace）；pyproject 移除 langgraph-checkpoint-postgres + python-jose；conftest 顶层设 NUOMI_HOME/NUOMI_WORKSPACE 为 mkdtemp（顶层禁 import app）。
- **线程安全坑（关键）**：JSON 时代无线程亲和性；SQLite 连接在 lifespan（事件循环线程）创建、测试/工具线程使用 → ProgrammingError。统一 `check_same_thread=False` + RLock（MemoryStore._save/_touch、SettingsStore._load/save 戴锁；ProjectStore connect 加参数）。
- **验证**：全量 pytest **127 passed**；迁移模拟（临时目录复制真实 backend/data）确认 projects/threads/facts/settings/checkpoints 全导入 + 幂等；隔离冒烟（NUOMI_HOME=tmp）health/projects/settings 200、数据根布局 = nuomi.db(+wal) + nuomi.json + knowledge/；前端 `tsc -b` ✓；`uv sync` 锁更新 ✓。
- **遗留数据现状**：backend/data 已删除（2026-10-02 用户拍板：废弃、不迁移、全新环境）。README/AGENT.md/.env.example 已同步；docs 路线表阶段 A 状态已回填。
- **阶段 B（工作区=项目打通）**：`storage/workspace.py` 新建——`list_tree` 安全列树（跳过 `.` 开头与 _SKIP 目录，MAX_DEPTH=3/MAX_ENTRIES=300 预算截断）、`safe_project_dirname`（非法字符清洗、拒绝 `..`）；`config.py` 加 `_workspace_override` + `api_token` 字段，`workspace_path` 优先级 = NUOMI_WORKSPACE/WORKSPACE_DIR env > 运行时设置 > 默认 `~/Documents/Nuomi`；`POST /api/projects` 无 directory 时自动在工作区建目录并绑定（同名幂等、恶意名 400）。前端：`api.ts` 加 `fetchWorkspaceTree`；SideBar 会话/文件双 tab，新建 `FilesPanel.tsx`（目录树、展开态持久化、空/错误态）；`filesRefreshTick` prop 驱动重拉。
- **阶段 C（sidecar token + Tauri 壳接线）**：后端 `_ensure_api_token`（NUOMI_TOKEN env 强制 > frozen 时 `NUOMI_HOME/.api-token` 幂等复用 0600 > dev None 不校验）+ token 中间件（校验 `X-Nuomi-Token`，`/api/health` 放行、401）。Rust 壳：`rand` 生成 32 字节 hex token，以 `NUOMI_TOKEN` env 传给后端进程；注入 `window.__NUOMI_API__` + `window.__NUOMI_TOKEN__`（前端 fetch 包装动态读取）；单实例（tauri-plugin-single-instance）；复用 8000 收紧为仅 dev 源码模式；CSP 由 `http: ws:` 收紧为 loopback 白名单。
- **阶段 D（首启向导）**：`GET /api/bootstrap`（setup_required = 无 custom_providers 或无 active_model）；`POST /api/bootstrap/workspace`（mkdir + 写 settings，lifespan 恢复 `_workspace_override`）。前端 `WelcomeWizard.tsx` 两步：工作区路径 → LLM 供应商（addCustomProvider + activateModel）；setup_required 时全屏遮罩，完成即关并刷新。
- **验证（B/C/D）**：新增 `tests/test_workspace_bootstrap.py` 5 项；**全量 pytest 143 passed**；隔离冒烟（NUOMI_HOME=tmp + NUOMI_TOKEN）9 项全过（401/200/health/bootstrap/tree/自动建目录）；前端 `tsc -b` ✓、`vite build` ✓；Rust `cargo build` ✓（期间修两处：tauri-plugin-shell v2 `Command::env` 返回 Self 非 Result、`.command()` 非 Result）。
- **B/C/D 遗留**：release 打包全链路（`tauri build`）与桌面端首启人工验收待做。
- **待办**：阶段 B/C/D 已全部落地（见上文），剩 release 打包验证与桌面首启人工验收。

## 记忆 v2 · Provider 化（2026-10-02，对齐 Hermes 实施）

用户调研 Hermes（纯文件双档冻结快照 + 8 个外部 provider 插件并存）与 DeepSeek Harness（无内置 RAG，记忆=MCP server 默认关闭，capability seam）后拍板：记忆 Provider 化，首接 Mem0；RAG 不内置、程序运行时插件实现（Harness 同构）。方案：`docs/memory-provider-design.md`（适配桌面化架构：单用户无 user 参数、MemoryStore 已 SQLite 化）。

- **契约层（app/storage/memory.py）**：`MemoryBackend` Protocol（list/add/replace/remove/search/snapshot）+ `MemoryEntry` dataclass + `FileMemoryBackend`（包装 SQLite facts 表，双档 category 映射：preference/user→USER 档、其余→MEMORY 档；快照按 char_limit MEMORY 2000/USER 1000 常用优先截取；replace/remove 唯一子串定位，返回 (1成功/0未找到/-1多条, msg)）。单例 `set_backend/get_backend`（未 set 回退包装 get_store；set_backend(None) 清空回退）。
- **冻结快照注入（app/agent/middleware.py）**：每轮检索注入 → 会话开始取一次快照（`_snapshots[thread_key]` 缓存，会话内不变，Hermes 同款保 prefix cache）；快照格式 `【记忆快照】MEMORY（我的笔记）[62% — 1,240/2,000 字符] § 条目`；provider 失败降级无快照不阻断。注入职责从 service-system-prompt 移交 middleware（该服务删 `inject=["memory"]`，memory_facts=[]）。
- **工具四件套（plugins/memory/tool.py）**：保留 memory_write（add）/memory_read（search）名兼容测试，新增 memory_replace/memory_remove；访问改 `get_backend()`；删多用户 `_user()`。SKILL.md 同步（冻结快照语义、双档、replace/remove 用法）。
- **service-memory**：set_store + set_backend(FileMemoryBackend(store)) + provide("memory", backend)；app.state.memory 保留 store（health 兼容改 get_backend().list() 通用计数）。
- **memory-mem0 插件（新建）**：Mem0Backend 实现契约（mem0ai 懒依赖：apply 探测 import，未装→插件 FAILED 提示 `uv pip install mem0ai`；模式 openmemory 默认本地自托管/cloud/local 全本地向量库；replace/remove=语义检索+子串过滤保唯一语义）；plugin.json settings schema + SKILL.md；卸载 dispose 清空 backend 回退内置。
- **测试**：新增 `tests/test_backend_contract.py`（11 项：file 契约增删改查/双档快照/容量截取/渲染格式/Mem0Backend fake mem0 映射/依赖缺失报错）+ `test_frozen_snapshot_unchanged_within_session`（同 thread 快照冻结、新 thread 反映新写入，断言用独特内容"乌龙茶"避开人设既有"嘉兴"）。**全量 pytest 143 passed**（127+16）。
- **切换**：profile 两行（enable memory-mem0 + disable service-memory），引擎与工具零改动。
- **P2 待办**：设置页 provider 选择 UI、真实 Mem0 服务端到端验证（需用户配置 mem0 服务/mem0ai 安装）。

## 启动方式决策：仅桌面版 + Makefile（2026-10-02，用户拍板"记一下"）

- **决策**：后续启动仅启动桌面版。默认形态 = `make start` → `cargo tauri dev`（desktop/ 下运行），tauri CLI 全自动：beforeDevCommand 起 vite(:5173) + debug 模式拉起源码后端（`uv run uvicorn`，随机空闲端口 + NUOMI_TOKEN，8000 已有可用 nuomi 后端则直接复用无 token），应用退出（RunEvent::Exit）时 kill 自起后端并注入 `window.__NUOMI_API__/__NUOMI_TOKEN__`。
- **Makefile（项目根）**：start(桌面版) / stop / restart / status / logs / logs-follow / web(显式 web 模式：后端8000+前端5173) / test(pytest) / build(前端构建) / clean。PID 与日志落 `.logs/`（已 gitignore）。依赖自检：`desktop` 目标是 .PHONY（项目根有 desktop/ 目录，漏了会被 make 当文件目标跳过）。
- **stop 兜底三层**：① kill tauri dev PID + `pkill -x nuomi-desktop`（精确进程名，**勿用 pkill -f**——make recipe 的 bash -c 命令行含匹配串会误杀 make 自身；pgrep/pkill -f 同理，status 检测一律用 `pgrep -x`）② 回收 :8000/:5173 ③ **tauri 自起后端随机端口**：从 desktop.log grep 最后一条 `http://127.0.0.1:PORT` 回收。
- **踩坑（已修）**：`uv run uvicorn` 有父进程层级——tauri 退出钩子 kill 的是 uv 父进程，uvicorn python 子进程会残留监听随机端口 → 必须靠日志端口兜底回收（实测 59890/60060 残留后修复）。
- **验证**：start→health 200→stop 全回收（应用/5173/自起后端）闭环通过；status 显示桌面版/应用窗口/web 三项。

## 产品审视落地（2026-10-02，用户确认三项动作）
- **审视结论**：工程完成度远超一般作品集，缺的是"产品主张"；差异化机会 = **"有温度的全能智能体"**（Harness/Claude Code 是冷工具，糯米有记忆、有人格）。风险三条：复刻叙事、宽而浅（占位功能被追问）、演示依赖外部（release 打包未验证 + 依赖 DeepSeek API）。
- **① README 定位段落重写**：新 slogan「有温度的全能智能体：会干活，也记得你」；金句「能干活的 agent 很多，记得你的只有一个糯米」。定位沿革补 2026-10-02 桌面化定稿。
- **② docs/demo-script.md（新）**：杀手级 demo = 调研→记忆→知识→执行→产物闭环。核心版 5 分钟（Step1-4），完整版 8 分钟（+shell 统计）；含分步 prompt、预期行为、讲解话术、失败降级、追问应答要点、排练清单。
- **③ docs/placeholder-priorities.md（新）**：深补优先级（排序=演示可见度×被追问概率÷成本）。P0：release 打包验证 / STT 真实 API / 演示降级；P1：文件面板↔fs 联动+权限选择器 / subagent / mem0 端到端 / Supervisor 二层；P2：compaction-spill / credentials-attachment / schedule-todo / i18n-en / TTS 换豆包。
- 下一步按用户选择推进：可在 docs/ 下继续完善，或直接开工 P0 项。

## 三栏布局 + 项目文件树（2026-10-02，用户两轮迭代拍板）

- **决策 1（侧栏去文件）**：侧栏只保留「会话」视图（项目分组），删除 sessions|files 双 tab（SideBar 删 view 状态/ws-tabs/FilesPanel 引用）。
- **决策 2（对齐 dsh AppFrame 三栏，非弹窗）**：.app 改三列 grid `var(--sidebar-w) 1fr var(--right-w)`；右栏默认收起（--right-w:0），右上角文件按钮（ChatWindow .files-toggle，仅项目绑定目录时显示）→ `.app.right-open` 展开为**常驻布局列**（--right-w: min(320px,30vw)，grid 过渡 0.22s），**不用 fixed 浮层/遮罩**（用户明确"不在是弹窗"）。三个响应式断点同步第三列。右栏 .right-panel 常驻渲染（chat tab），头部=项目名+关闭，内容=FilesPanel（当前项目文件树）。
- **后端新接口**：`GET /api/projects/{id}/tree` → ProjectStore.get_project + list_tree(绑定目录)；未绑定/项目不存在/目录失效均 404（复用 list_tree 安全规则）。前端 api.fetchProjectTree（404→"NO_DIR"错误 → FilesPanel 显示"该项目未绑定本地目录"）。
- **踩坑（bu 实测）**：侧栏项目组头内按钮密集（绑定目录/新建/删除/折叠），bu.click 组头 ref 会命中 group-dir-btn 弹出目录绑定弹窗——点击组头/行要用 find() 定位子元素或坐标点非按钮区。
- **验证**：tsc/build 通过；bu 实测三栏（right-open 展开右栏 211px、聊天列让出、文件树渲染 sub/readme.md、遮罩/Esc 关闭已随抽屉废弃）；pytest 143 绿。

## 本地 STT 落地（2026-10-02，用户要求"本地跑模型、不花钱"）
- **方案**：faster-whisper（CTranslate2 int8 CPU）替换 voice 插件 transcribe 占位——免费、离线、数据不出本机。
- **实测**：macOS say 生成中文语音 → 转写「你好,我是糯米,一个会干活也记得你的智能体,现在测试本地语音转写功能。」置信度 1.00；模型缓存后加载+转写 4.1s。
- **配置**：默认 small 模型（中文够用），环境变量 NUOMI_STT_MODEL 可换 base/tiny/large-v3；模型缓存 NUOMI_HOME/hf-cache；下载走 HF 镜像（hf-mirror.com）。voice 插件 load=lazy，首次调用才加载模型。
- **踩坑**：faster-whisper 1.2.1 与 PyAV 19 不兼容（`open() got unexpected keyword 'metadata_errors'`）→ 固定 av>=11,<14（pyproject 已加约束 + uv lock）。
- **遗留**：speak 音频仍写 backend/data/audio（桌面化后应入 NUOMI_HOME，未改）；前端 Tauri WKWebView 的 webkitSpeechRecognition 不可用，语音按钮需改「录音上传 → 后端 transcribe」（P1 范围，未做）。

## Harness 对齐四项落地（2026-10-02，用户"全做"）
- **背景**：用户发 DeepSeek Harness 工作台截图，对照评估后（三栏已对齐/右栏入口卡⚠️裸文件树/错误卡片⚠️顶部 banner/状态行⚠️缺）用户拍板"全做"。
- **① 右栏功能面板容器**：.right-panel-head 内 .right-panel-tabs（文件/终端/浏览器三图标 + 关闭）；App rightPanel state；⌘P→文件树、⌘T→终端（仅 chat tab 且有项目目录）；rp-tab 切换不改变 filesOpen。
- **② 终端面板**：`POST /api/projects/{id}/shell/exec`（ShellExecRequest 必须模块顶层——定义在 router 函数内会被 FastAPI 当 query 参数报 Field required）；动态 importlib 加载 plugins/shell/tool.py 复用 _run（workspace-write 沙箱，黑名单/超时/截断同 agent bash）；前端 TerminalPanel（命令历史 + 输出、NO_DIR 提示）。
- **③ 对话流错误卡片**：NuomiAdapter error 事件不再 throw → textAcc += "⚠️ message"；ChatWindow TextPart 检测 ⚠️ 前缀渲染 .msg-error-card（替代 App 顶部 banner）。
- **④ 输入框范围 + 运行统计**：InputBar 底部 .scope-btn 循环 只读/工作区内/全局（写 /api/settings/global shell_default_mode，后端 shell hook 监听全局键热更新）；.run-stats 显示 `{tokens} tok · {latency}s`（onDone 的 usage.total_tokens + latency_s，done SSE 新增 latency_s）。
- **踩坑（已修）**：CSS 变量 --right-w + grid-template-columns 的 transition 在 WebKit 卡死（computed --right-w 正确但列宽停 0px）→ 移除 transition、.right-open 用固定 320px（≤720 断点 260px），实测列宽正常。MessageKey 需 `import type from "../../i18n/zh-CN"`（i18n/index 不导出）。CSS token 只有 --radius-md/lg/pill 无 --radius-8/--code-bg。
- **验证**：pytest 143 绿；tsc/vite build 通过；shell exec API 实测（pwd+ls 正常、绝对路径写被拦、不存在项目 404）；bu 实测：右栏展开 260px、面板切换、终端执行输出、浏览器 iframe 加载 example.com、范围按钮循环（全局→只读→工作区内）。错误卡片/统计为代码路径验证（未做真实 API 错误/回复触发）。

## 右栏开关上移顶栏（2026-10-02，用户"挪到上面，不在对话页面上"）
- **决策**：files-toggle 从 ChatWindow 内 absolute（浮在对话消息流右上角）移到 `.main` 顶部新增 `.topbar`（高 46px，常驻）：左=会话标题（threadTitle 为空时显示项目名，兜底"新会话"），右=右栏开关（仅项目绑定目录时渲染）。
- **实现**：ChatWindow 删除 files-toggle 与 chat-header/chat-title（标题统一进顶栏）；App.tsx .main 内渲染 .topbar + 按钮（FolderIcon + 项目名，filesOpen 时 .on）；CSS .files-toggle 去掉 absolute 改顶栏内 inline-flex，.topbar 样式新增，.chat-header/.chat-title/.title-input 死样式删除。
- **验证**：tsc/vite build 通过；bu 实测：顶栏 46px、按钮在 .topbar 内（position static）、点击开合右栏（right-open/关闭）、右栏文件树正常（hi → sub → readme.md）；截图确认按钮位于顶栏右上角，对话区无浮层按钮。

## 顶栏/侧栏再精简（2026-10-02，用户"不好看；按钮应是展开图标非项目名；组头不要换绑目录"）
- **顶栏右栏开关**：从「图标+项目名」胶囊改成**纯图标按钮**（28px 方钮，FolderIcon，on 态 accent-soft；对齐 dsh 右栏入口），title 提示「文件树 · ⌘P」。
- **侧栏项目组头精简**：删除目录路径小字（.group-dir）、换绑目录按钮（.group-dir-btn）、直排删除按钮（.group-del）；组头只留 项目名 + 会话数 + 新建会话（+，hover 浮现）+ ⋯ 更多下拉（.group-more/.group-menu，含「删除项目」danger 项）+ 折叠箭头。
- **更多菜单**：MoreIcon（icons.tsx 新增水平三点）；moreKey state；toggleGroup 时自动关闭菜单（点击组头其他区域=关菜单）；菜单项点击后关闭并弹删除确认。
- **API 清理**：SideBar 删 onSetProjectDirectory prop；App 删 setProjectDirectory import 与传参（新建项目绑目录仍走 PromptDialog 的 onCreateProject）。
- **顺带修复**：RobotMode.tsx onKeyDown 用全局 KeyboardEvent 导致 tsc 报错 → 改 React 的 KeyboardEvent 别名导入。
- **验证**：tsc/vite build 通过；bu 实测：顶栏按钮纯图标（text 空、icon-btn files-toggle）、组头无目录/绑定/删除按钮、⋯ 菜单展开含「删除项目」、点击组头其他区域菜单关闭、右栏文件树正常；截图确认视觉。

## 右栏精简：移除终端/浏览器（2026-10-02，用户"移除终端和浏览器按钮"）
- **决策**：右栏面板只保留文件树；删除 .rp-tab 终端/浏览器两个图标按钮与 rightPanel state；⌘T 快捷键删除，⌘P 保留（只 setFilesOpen(true)）；右栏头=项目名+关闭 X，内容直接 FilesPanel。
- **清理**：删除 modules/ui-right/TerminalPanel.tsx、BrowserPanel.tsx（目录已删）；App 移除 TerminalPanel/BrowserPanel/TerminalIcon/GlobeIcon 引用；layout.css 删除 .right-panel-tabs/.rp-tab/terminal-*/browser-* 死样式（保留 .rp-close）。api.execShell 与后端 /shell/exec 接口保留（未引用，可复用）。
- **验证**：tsc/vite build 通过；bu 实测：右栏无 rp-tab、无终端/浏览器面板、文件树正常、关闭按钮保留；截图确认视觉。

## 组头移除折叠箭头（2026-10-02，用户"最右侧向右的图标也不要了"）
- **决策**：删除项目组头最右侧的折叠箭头（.group-caret / ChevronDownIcon）；展开/收起仍通过点击组头完成。
- **清理**：SideBar 删 group-caret 渲染与 ChevronDownIcon import；layout.css 删 .group-caret 及 rotate 规则。
- **验证**：tsc/build 通过；bu 实测组头无 caret（剩余 图标+名+数+＋+⋯），截图确认。

## 机器人模式 v2：插件化 + 开源 3D 形象 + 纯语音闭环（2026-10-02，"全部开始"）
- **决策**（用户三点反馈 → 全部落地）：①机器人模式插件化（一切皆插件）；②形象改用**开源 3D**（three.ws `<agent-3d>`，Apache-2.0），**不再自绘**（用户明确纠正"为什么自己绘制，不能直接用开源项目吗"，记忆策略=成熟开源优先）；③纯语音对话为主，对齐 Replika/Gatebox/Open-LLM-VTuber 产品范式。
- **插件化**：新建 `plugins/robot/{plugin.json,hook.py}`（program 型，无工具，维护 `app.state.robot_enabled` + 订阅 PLUGIN_TOGGLED）；composition.py default_profile 与用户 nuomi.json 的 runtime 层加 `runtime-robot`；前端 App.tsx `robotEnabled = plugins.find(p => p.plugin === "robot")?.enabled ?? true` 控制顶栏 mode-toggle 显隐 + /robot 命令（停用返回 t("cmd.robotDisabled")）+ 停用时自动回通用模式。
- **开源 3D 形象**：npm 包 `three.ws` 0.2.0 **不可用**（无 speakAudio，旧版）；改用 CDN 1.5.2 `agent-3d.js`（含 `speakAudio(audio)` 波形驱动嘴型）下载到 `frontend/public/vendor/agent-3d.js`（3.3MB，public 静态资源，RobotMode 用 `<script type="module">` 动态注入，仅进机器人模式加载）。模型：three.ws `avatars/default.glb` 是女性人形（不可用）→ 换 **Poly Pizza Quaternius "Animated Robot"**（CC0，金黄色低多边形卡通机器人，401KB）下载到 `frontend/public/models/nuomi-robot.glb`（换脸=换文件）。body 模式=静默 3D viewer 无 API key/无云。加载失败自动降级自绘 `RobotFace`（SVG 兜底，robot-face.css 动画保留）。
- **纯语音闭环**：后端 main.py 新增 `POST /api/transcribe`（UploadFile → faster-whisper，language=zh+vad_filter，返回 {"text","language","language_probability"}，400=未识别到语音）与 `POST /api/speak`（text → macOS say+ffmpeg → audio/mpeg 流；**坑：SpeakRequest 必须定义在模块级**，app 函数内定义类 + `from __future__ import annotations` 会被 FastAPI 当 query 参数 422）。前端 RobotMode：MediaRecorder 录音（点 mic 启停，"在听你说…"）→ transcribe → onSend；新回复 → speakAudio(dataURL) 播放 + voice:speech-end 复位"机器人待命中"；打字栏保留降级。
- **踩坑**：①vite 禁止 import public 目录文件（报 "should not be imported from source code"）→ public 资源只能用 script 注入/HTML 引用；动态 import() 变量路径 vite 不静态分析（dist 无 chunk）→ 放弃该路；②`/api/plugins` 返回 id 是**层 id**（runtime-robot 而非 robot）→ 前端匹配必须用 `p.plugin`（team/voice-input 旧代码用 p.id 匹配恒 true 的同款 bug 一并修）；③后端 8000 会被环境回收（ECONNREFUSED → 前端一片 500"出了点问题"），重启即恢复。
- **验证**：curl speak=200 29KB MP3 / transcribe=200 置信度 1.0；前端构建通过；浏览器实测：/robot 进入 → 3D 小机器人渲染 → 打字"你好"回复 + "说给你听…" → 复位待机；插件面板 robot 卡片正常 → API 停用后 /robot 命令拦截、启用后恢复；录音启动"在听你说…"、静音 400 降级提示正常；后端全量 pytest **143 passed**。
- **遗留**：机器人模式语音打断（Open-LLM-VTuber 卖点，P1）；speak 音频临时目录 /tmp 清理逻辑 OK（端点内 rmtree）；three.ws agent-3d 3.3MB 只在机器人模式加载（通用模式零成本）；agent-robot-avatar npm 依赖已从 package.json 移除（npm uninstall three.ws 也执行了）。

## 通用模式移除卡通形象（2026-10-02，用户"通用版本不需要那个糯米的卡通形象了"）
- **决策**：通用模式走生产力路线，移除 ChatWindow 伙伴栏的 PetBuddy 卡通形象；形象归机器人模式（3D agent-3d）。伙伴栏保留"糯米 + 在线等你"文字。
- **改动**：ChatWindow.tsx 删 PetBuddy 渲染与 import、props 去 mood；App.tsx 删 mood state/事件链路（onDone 只留 usage）、send/startVoice/stopVoice 去 setMood；layout.css .partner-bar padding 22→14。PetBuddy.tsx / robot-face.css 保留（作品集资产 + 机器人模式 3D 加载失败兜底）。
- **验证**：tsc/build 通过；浏览器实测通用模式伙伴栏无形象、消息流/语音按钮正常；机器人模式不受影响。后端 mood 插件仍在跑（事件照发，前端不再消费）。
- **跟进（同日，用户"糯米 在线等你 这几个字也不需要了"）**：ChatWindow 整块删除 partner-bar（名字+状态文字），清理 layout.css 伙伴栏样式块（partner-bar/meta/name/status/pet-buddy/pet-float/status-pulse）；ChatWindow 去掉 useAuiState busy 依赖。通用模式主区 = 纯消息流 + 输入栏（侧栏"糯米/全能智能体"品牌区保留）。构建 + 浏览器实测通过。

## 通用模式消息视觉升级：ChatGPT Clone 风格（2026-10-02，用户"不好看→用开源主题→A方案"）
- **决策**：用户对消息显示不满意，要求直接用开源方案。评估 assistant-ui 官方 ChatGPT/Claude Clone 主题 / shadcn chat-kit（2026-06 新组件，需 Tailwind）/ Lobe UI（antd 体系重）三选一，用户选 **A：assistant-ui 官方 ChatGPT Clone 视觉**（零架构重构，纯 CSS 翻译）。
- **Tailwind 结论**：AI 前端生态（Vercel AI Chatbot/assistant-ui 示例/shadcn）普遍 Tailwind，utility class 利于 AI 生成 UI 与快速迭代；但本项目已是成熟纯 CSS token 体系，为套主题迁 Tailwind 成本>收益，故用现有 CSS 变量实现 ChatGPT 风格，不引 Tailwind。
- **改造（全用现有 token，仅新增 --radius-2xl:22px / --radius-3xl:28px 圆角 token）**：
  - 用户气泡：深色高对比（var(--label) 底 + 白字，替代原蓝渐变）、22px 圆角、max-width 78%
  - 助手消息：**无框流式**（透明底直排，靠排版区分，替代原白 86% 气泡）
  - composer：28px 大圆角（--radius-3xl）、surface 92%
  - 深度思考：浅面徽章（白 88% + 细边框 pill + 蓝 Sparkle），展开态 accent-soft + 蓝边线、body 纸感面板（白 94% + line-1 边框 + 蓝左线品牌）
  - 工具调用：白 90% 卡片 + 12px 圆角 + 蓝图标 + 蓝等宽工具名（--font-mono）
  - hero 空态：标题 24px/600（原 fs-hero/800）；thread-viewport 顶部留白 8px；.row padding 10→8
- **验证**：tsc/build 通过；浏览器 computed style 实测：user 气泡 rgb(24,28,34)+22px、assistant 透明 0 圆角、composer 28px、tool 卡片 12px+蓝图标、reasoning 徽章生效；发"现在几点了"实测带深度思考+工具调用的回复正常渲染。
- **遗留**：bu 截图工具本会话主区渲染异常（整页截图主区空白、ref 截图错位）——验证以 DOM/computed style 为准；用户消息 hover Copy/Edit 操作条（ChatGPT 特征，P2，可后续加）。

## 工具调用卡片 v2：豆包式步骤卡片（2026-10-02，用户"样式丑+无思考+要看入参/结果"）
- **用户反馈**：①工具调用样式丑 ②没看到深度思考 ③要能展开看工具入参和结果（截图对齐豆包工作台"每一步在干嘛+可折叠"）。确认 assistant-ui tool-call part 完全自定义渲染（开源支持，无需换库）。
- **数据链路补齐（关键）**：原后端 tool 事件只有 name。新增 `_chunk_tool_events(chunk, acc)`（跨 chunk 累积 tool_call_chunks.args_fragment，按 index + sent 标记去重；updates 模式走 tool_calls 完整 args），tool 事件改 `{"name","args"}`；ToolMessage（team 子节点 / messages 模式 chunk）→ 新增 `tool_result` 事件 `{"name","result"}`。curl 实测：tool 带 `{"timezone":"Asia/Shanghai"}`、tool_result 带时间字符串。
- **前端**：NuomiAdapter 的 tool 事件取 argsText、tool_result 挂 `tc.result`（ToolCallPart 类型加 result?）；ToolCallPart 组件重写为可展开卡片（折叠=图标+调用工具+工具名+状态点（执行中蓝脉冲/已完成绿点）+chevron；展开=入参/结果两个 pre 区）；i18n 新键 chat.toolCall/toolDone/toolRunning/toolArgs/toolResult/toolNoDetail；CSS .tool-card 系列（复用 status-pulse keyframes，--ok 绿点）。
- **验证**：后端 143 passed；浏览器实测"现在几点了"→ 卡片"已完成"态 → 点开 → 入参 {"timezone":"Asia/Shanghai"} + 结果 "2026-10-02 20:00:59 星期五（Asia/Shanghai）"，同回复带深度思考 282 字折叠块。注意：模型是否调工具是随机的（同一问题有时直接答有时调），测试需多发几次或用必触发工具的提问。
- **遗留**：bu 截图主区渲染异常依旧（DOM/computed 验证为准）；旧 .tool-row 样式已删。

## 深度思考流式 + 正文真流式（2026-10-02，用户"没感觉到流式，思考应流式展示、完成自动折叠"）
- **前端**：ReasoningPart 改为流式联动——`open = manual ?? isRunning`（useAuiState 的 thread.isRunning：思考进行中自动展开逐字滚动，输出完成自动折叠；用户手动点过徽章则以其选择为准）。思考中徽章加 .reasoning-caret 展开指示（脉冲动画）。i18n 新键 chat.deepThinking。
- **根因（关键）**：正文"一次性出现"不是前端问题——团队模式走 stream_mode="updates"（每节点整轮输出，LLM 流被聚合，SSE 只有 1 个 token 事件）。curl 铁证：token 事件=1。修复：resolve() 团队模式改 stream_mode="messages"（LangGraph 会把 router 与子 Agent 的 LLM 逐 chunk 流出，ToolMessage 也走 messages 流）；main.py 团队分支按 meta.langgraph_node 过滤 router 节点（其 {"next": "..."} 路由决策会泄漏成正文 token，实测泄漏后修复）。
- **踩坑**：①双模式 ["messages","updates"] 触发 `RustBindingsAPI object has no attribute bindings`（langchain-openai 新版与 langgraph 兼容问题）——绕开：纯 messages 模式，updates 分支删除；②meta 节点名实测是 "router"（不是 supervisor.py 的 build_supervisor 主图名）；③bu.fill_input 不触发 React onChange（点了发送但没提交）——浏览器输入改用 click textarea → bu.type(..., submit=True)。
- **验证**：后端 curl——reasoning 29 个流式事件 + token 7 块（原 1 块）；浏览器采样 [98,True]→[216,True]→[-1,False]（思考中展开逐字增长 → 完成自动折叠）；最终 1428 字完整回复、无 router 泄漏；web 工具外网不通仍报 RetryError（环境限制，非回归）。

## Markdown 渲染 + 历史回显补全（2026-10-02，用户"消息不支持md渲染、回显没有思考/工具、问时间没回"）
- **Markdown**：TextPart 用 react-markdown（新依赖）渲染气泡；CSS .bubble :where() 系列（p/h1-6/ul/ol/code/pre/blockquote/a/hr/table，全用现有 token）；assistant 气泡 white-space 改 normal（pre-wrap 会破坏 md 排版）。实测：strong/h1/列表 25 个元素、无 ** 原文。踩坑：装新依赖后 vite dev server 必须重启（白屏），浏览器输入用 JS setter+input 事件同步 React（bu.type/fill_input 触发不了 onChange，发送按钮实际 disabled）。
- **回显补全**：/api/threads/:id/messages 原来只返回 {role,content}——补 reasoning（_chunk_reasoning）、toolCalls[{name,args,result}]（tool_call_id 与 ToolMessage 配对）；工具调用轮（正文空）与回复轮合并为一条（豆包式卡片+正文同条）。前端 toThreadMessages 透传 argsText/result，ChatMsg.toolCalls 类型改对象数组。
- **团队块式流式（关键修复）**：LangGraph 旧版（>=0.2.60）messages 模式对 subgraph 不流内部 chunk，产出**完整 AIMessage**（非 AIMessageChunk）→ 之前 isinstance 检查把正文/思考/工具全丢（done content 空！"现在几点了"没回的真因）。修复：团队分支接受 AIMessage + AIMessageChunk 两种形态统一处理；stream_subgraphs 参数不存在（旧版），双模式触 RustBindingsAPI.bindings 错误——团队模式=块式流（每轮一块），单 Agent=逐字流。实测：现在几点了→ reasoning+tool(args)+tool_result+token+done(content 非空)；工具风暴（Markdown 问题 5 轮工具）→ 5 tool 事件 + 8 tool_result + 3 token 块 + 645 字正文。
- **重启纪律（教训）**：kill -9 $(lsof -ti tcp:8000) 有时杀不干净（uvicorn 子进程/竞态），新进程绑定失败悄悄退出、旧进程继续服务旧代码——必须 kill 后确认端口释放（lsof 空）再启动，或用 ps 核对 PID 启动时间。
- 验证：回显"询问当前时间"会话→一条消息含 深度思考36字 + 工具卡get_current_time已完成 + 正文；Markdown 问题→渲染成功；后端全量 pytest 通过。

## 工程化质量门禁（2026-10-02，对标 Octop/TencentCloud 的 make all 模式）
- **动机**：对比 octop（TencentCloud 开源 agent 平台，637 py 文件/474 测试文件/9 套 CI）后落地的第一件事——补"机器闸门"：lint + 类型检查 + CI，把质量从"靠 AGENT.md 记坑"升级为"机器强制"。
- **backend/pyproject.toml 新增**：
  - dev 依赖：ruff>=0.4、mypy>=1.10（uv add --dev）
  - [tool.ruff]：line-length 100、target py312、src=app/tests/scripts；lint select=E,F,W,I,B,UP,SIM,C4（ignore E501）；tests 下 per-file-ignore B011
  - [tool.mypy]：python_version 3.12、files=app/scripts/sidecar_main.py、ignore_missing_imports=true（tests/plugins 暂不纳入 mypy）
- **修复要点（mypy 44 错误清零）**：
  - **方法名 list 遮蔽内建 list**：MemoryBackend/FileMemoryBackend 的 `def list` 导致类内后续 `list[...]` 注解解析成方法（valid-type/index 连环错）——把 `list` 移到类末尾（契约 API 不变，零调用方改动；注释已说明）
  - composer.entries 从 dict[str, object] 改为 dict[str, ProfileEntry]（core/composition.py 已有 dataclass）；install() 的 type("E",...) 鸭子 entry 换成正牌 ProfileEntry
  - `list` 方法重命名：NuomiComposer.list → list_plugins（main.py 2 处调用同步）
  - MemoryFact.from_dict 显式构造（避免 **kwargs 无法核对）；_score overlap 显式 float
  - Settings 新增私有字段 `_workspace_override: str | None = None`（pydantic 下划线=非环境字段）
  - build_llm api_key 包 SecretStr；_iso_of 接受 int | None；module_from_spec 加 None 守卫；bytes f-string 显式 decode；SSE 回显 item 显式 dict[str, Any]；B904 全部补 raise ... from e / from None
- **Makefile 新增**：`make check`（lint+format-check+typecheck+test）、lint、format、format-check、typecheck——对齐 Octop 的"make all 全绿才算 done"。注意 ruff 命令带 `--config pyproject.toml` 覆盖 plugins/（plugins 不在 backend 目录，默认找不到配置）。
- **CI（.github/workflows/ci.yml）**：PR + main push 触发；backend job（setup-uv py3.12 + uv sync + make lint/format-check/typecheck/test）+ frontend job（node 22 + npm ci + tsc+vite build）；concurrency cancel-in-progress。
- **lint 全量清理**：ruff --fix + format 覆盖 backend（app/tests/scripts）+ plugins 全部 .py（102 文件）；手工修 SIM105（suppress）、SIM102、C408、E741、UP042（FiberState→StrEnum）、B905（zip strict）、F841（测试删无用变量/`as client`）。
- **验证（2026-10-02 全绿）**：make lint ✓ / make format-check ✓ / make typecheck ✓（34 源文件无错）/ make test ✓（143 passed）/ 前端 npm run build ✓。遗留 note（非错误）：mypy 未启用 check-untyped-defs（untyped 函数体不查）；前端 chunk >500kB 警告（历史遗留，非回归）。
- **尚未提交**：本次改动（含 Makefile/.github/ruff 格式化 diff）+ 用户之前的 AGENT/README/.gitignore 改动都在工作区，未 commit。

## 插件概念对齐 Octop（2026-10-02，v0.7 重构已执行）
- **诊断**：plugins/ 下 22 个"插件"实际混了 4 类职责——tool 类 9 个（注册 LLM 工具）、skill 类 2 个（agent-companion/agent-researcher，文档资产）、hook 类 5 个（mood/robot/team/voice-input/memory-mem0，运行时钩子）、service 类 6 个（内核服务）。豆包"插件"=产品层能力组合、Octop=分发单元层、nuomi=内核层——一词多义是模糊根源。
- **用户拍板**："直接重构吧。不需要 kind 去区分，插件就对齐 octop 中的插件，技能是专门的技能概念，我们暂时不增加技能包的概念，内置服务用模块的概念"→ **不用 kind，目录即分类**：
  - `plugins/`（9）= 可选能力分发单元（datetime/fs/knowledge/mcp-notes/memory/pyfunc/shell/voice/web）
  - `backend/app/modules/`（13）= 内核组成部分（service-* ×6 + hook 类 ×5：mood/robot/team/voice-input/memory-mem0 + agent-companion/agent-researcher）；builtin 判定=modules_dir 下存在
  - `skills/`（仓库根，10）= 独立技能文档资产（SKILL.md 全量注入 system prompt，不随插件启停过滤）
- **代码改动**：loader v0.7（scan_plugins 带 category / scan_skills / SkillDescriptor / collect_skill_catalog 吃技能列表）、lifecycle（build_plugin_list 技能关联展示、build_skill_tool 吃技能）、composer（modules_dir/_plugin_dir/list_entry/builtin）、main（build_app 三区参数 + lifespan 装配 plugins+skills）、config（skills_dir/modules_dir）、13 个测试适配、sidecar/spec 打包。
- **关键踩坑（勿重试）**：①mypy Duplicate module "hook"→模块入口统一改名 `<目录名转下划线>.py`（不要改回 hook.py）；②Fiber 的 entry 参数此前从未生效（插件 entry:"tool.py" 是摆设，实际一直加载 hook.py）——composer 现读 plugin.json entry 真正生效，插件侧遗留 entry 字段已清理；③lifecycle._apply 的 PluginContext 缺 config（runtime 版未声明，fiber 用 core/context 版）→ 补声明+填充；④memory-mem0 的 Mem0Backend.list 遮蔽内建 list→移到类末尾；⑤测试污染（greet/calc/dup/weather 曾被失败测试装进真实 plugins/，已删，再出现即 bug）。
- **验证（2026-10-02 全绿）**：make lint ✓ / format-check ✓（96 文件）/ typecheck ✓（48 源文件）/ test ✓（143 passed）；前端 api.ts 补 category 字段 + 插件页页头三区文案，npm run build ✓。
- **语义变化**：停用插件不再影响技能目录与 skill_doc（技能独立，是设计非回归）；查 mood 等不在技能区的名字返回"未知技能"。
- **方案全文**：docs/plugin-concept-alignment.md（已更新为 v0.7 实况，含迁移明细/踩坑/验证）。
- **边界（不做）**：插件市场、octop_ui 前端渲染协议、8 分组、技能包（用户拍板暂缓）、多用户共享池。
- **未 commit**：本次重构 + 前置工程化 + 用户自己的 AGENT/README/.gitignore 改动都在工作区，commit 前需与用户确认提交范围。

## 概念→格式体系（2026-10-03，v0.7.1：三种概念三种清单，用户"都改"）
- **用户提问**："插件/模块/技能是否应有各自格式？系统是否需按概念重设架构？Octop 领域设计合理"→ **判断：运行时机制不分（三区同构是优点，一套 Fiber/apply/ctx 引擎），但 manifest 格式分离**。用户拍板"都改"。
- **三格式（格式随概念分离）**：
  - 插件 `plugins/<name>/plugin.json`：能力导向（name/description/version + system_instruction/load/robust/approval，默认入口 hook.py）
  - 模块 `backend/app/modules/<name>/module.json`：内核导向（name/description/version/entry + **provides[] 声明的 ctx 服务 + hooks[] 订阅的事件**，可选 load/system_instruction/settings/settings_key）
  - 技能 `skills/<name>/SKILL.md`：frontmatter 即清单（不变）
- **代码改动**：loader v0.7.1（MANIFEST_NAMES 双 manifest、scan_plugins 按 category 读 plugin.json/module.json、PluginDescriptor 增 provides/hooks 声明字段）、lifecycle._collect（服务/事件 = 声明 ∪ 运行时，_dedupe 保序去重）、fiber._merge_plugin_meta（module.json 优先，缺则 plugin.json）、composer（_read_manifest 双 manifest、_mount entry、list_entry 服务/事件声明∪运行时合并）；13 个模块 plugin.json → module.json（provides/hooks 全部来自探查真实 ctx.provide/ctx.on 调用，如 service-agent-loop 挂 5 个事件：settings/changed、plugin/toggled、plugins/loaded、plugin_toggled、llm/switched）。
- **验证（2026-10-03 全绿）**：143 passed 一次通过（贡献视图值不变，无需测试适配）；make check 全绿（1 文件 format 后重跑通过）。
- **决策要点**：模块 provides/hooks 是**声明式元数据**（扫描期即可见、不 import 入口）；apply 运行时 ctx.provide/ctx.on 仍执行，展示 = 声明 ∪ 运行时（保序去重）。插件不引入 provides/hooks（插件的能力面是工具，服务是模块职责）。
- **未 commit**：v0.7 + 概念同步 + v0.7.1 + 用户自己的改动全在工作区，commit 前需与用户确认提交范围。

## 领域设计对齐 Octop：专家化 + 四层架构（2026-10-03，v0.8 整体重构，用户"全部一起干"）
- **用户主线**：Octop 的每个概念都是领域语言（Expert/Channel/Connector/Workspace/Gateway），nuomi 是机制语言（Fiber/Scope/Registry/Composer/三级加载）→ 验证 Octop 后端确为领域实现（class Expert / class Gateway / BaseChannel，机制词隔离在 octop-harness/octop-gateway/octop-memory）→ 用户拍板"整个架构重构，不偷懒"。
- **用户拍板 5 决策**：①去"伙伴"改"专家（Expert）"；②糯米=默认专家（品牌保留）；③PetBuddy 不降级、仅糯米专属；④mood 情绪=专家人格层（保留）；⑤preset（agent-companion/agent-researcher）→专家库模板资产。专家库位置=仓库根 `experts/`。
- **P0 专家化**：`partners/nuomi/`→`experts/nuomi/`（git mv 保历史）；`partner.json`→`manifest.json`（id/name/display_name/label/description/welcome_message/avatar/icon_name/color/default/version/prompt_files/quick_prompts）；`app/agent/partner.py`→Expert 模型 + load_expert/list_experts/assemble_system_prompt（文件名 P2 归位时处理）；config `experts_dir/expert_name`；main `expert_name/experts_dir` 参数、`app.state.expert`、/health 键 `partner`→`expert`。
- **P1 engine 机制库下沉**：`app/core/` 7 文件 + `app/plugins/` 机制 6 文件 → `app/infrastructure/engine/`（13 文件），删 `app/core/`、`app/plugins/`；engine `__init__` docstring 定位"机制基础库（≈ octop-harness）"。踩坑：批量脚本只改绝对导入漏相对导入（`.plugins.approval`）→ 12 collection 失败；composer 残留 `from ..core`。
- **P2 领域归位**：`app/agent/` 7 文件 → `app/domain/experts/`；`app/modules/` 13 个按领域解散：agent-companion/agent-researcher/team→domain/experts/（provides 值 preset:companion/preset:researcher 保留）、service-memory/memory-mem0→domain/memory/、mood→domain/behavior/、robot/voice-input→transport/、service-*×5→infrastructure/engine/services/；`app/modules/` 删除。
- **P4 扫描领域化**：`config.domain_roots` 5 领域根；`NuomiComposer` 收 `domain_roots`（`_plugin_dir` 先领域根再 plugins/，builtin 判定 `any((root/e.plugin).is_dir())`）；main 装配 `mod_scans += scan_plugins(root, category="module")`。踩坑：main.py 相对层级算错（`from .domain.experts` 写成 `from ..domain.experts`）；data 文件 `..config`→`...config`。
- **P3 transport 拆分**：main.py 的 token_guard + 39 路由 + 15 pydantic 模型 + 辅助函数 → `app/transport/api.py` `build_router(app)` 工厂；main 只留 `include_router(build_router(app))`。踩坑链：路由块嵌套进 token_guard（dedent 4 空格）、闭包变量逐名补 import/挂 state、`_sanitize_plugin_name`/`_trace_turn`/`_tar_root` 搬运、PydanticUserError 缺 Any。
- **P5 能力域 + 依赖规则**：新建 `app/domain/capabilities/service.py` `CapabilityService`（list/toggle/install/uninstall 领域 API，挂 app.state.capabilities），5 个能力路由改走领域服务，transport 不再碰 composer；新建 `backend/scripts/check_layering.py`（AST 扫 import，硬规则 5 条）接入 `make check` 首步 `layers`。
- **P6 前端专家化**：api.ts fetchExperts/activateExpert；i18n heroTitle "果冻小猫专家" + settings.experts.* 键；SettingsModal 通用区专家选择器（列表+当前+切换+重启提示）；PetBuddy 注释"糯米专属"；后端新增 GET /api/experts + POST /api/experts/{name}/activate（写 workspace/experts.json，重启生效，main.py `_expert_override` 优先级：启动参数 > 覆盖 > 默认）。
- **P7 文档**：concepts.md → v0.8（专家概念行 + 1.3 四层架构依赖表 + 1.4 领域语言映射 + 第 3 章模块按领域根归位 + 第 5 章口径）；README 目录树四层化 + 专家叙事（历史 Phase 原话保留）。
- **验证（2026-10-03 全绿）**：make check = layers → lint → format-check → typecheck → test，143 passed；前端 npm run build 通过（chunk 大小 warning 原有）。
- **依赖规则（机器阻断，勿违背）**：transport 禁 import main；domain 禁 import transport；engine 机制库（顶层 13 文件）禁 import domain/transport/storage；storage 禁 import domain/transport/infrastructure；engine/services 允许消费 domain；除 main.py 外禁 import main。composer 签名 `domain_roots: Sequence[str|Path]|None`（mypy 方差，Sequence 从 collections.abc import）。
- **未 commit**：v0.8 全部改动 + 用户自己的改动在工作区，commit 前与用户确认范围。

## 前端全量迁移 Ant Design（2026-10-03，v0.9：用户"前端界面和 Octop 对齐"+拍板全量 antd 迁移）
- **决策**：给三档方案（布局+视觉对齐/全量 antd 迁移/纯视觉微调），用户拍板**全量迁移 Ant Design**（对齐 Octop dashboard：React18+antd+antd-style+lucide+i18next+router，接受重写回归风险）；领域语言（专家/能力/技能）继续沿用 v0.8。
- **架构**：`App.tsx` 保留集中状态 + assistant-ui runtime + 命令/快捷键/WelcomeWizard，渲染改 `HashRouter`（Tauri/静态托管都稳，避免 BrowserRouter 刷新 404）→ `MainLayout`(antd Layout：Sider 领域导航 220↔56 可折叠 + Header[当前专家/色板/明暗/机器人入口] + Outlet) → 6 页面。**页面收 props 模式**（不做状态下沉），ChatPage 30+ props 由 App 根传。
- **页面**：`pages/ChatPage`(三栏+BusyBridge，机器人模式仍 App 外层全屏)、`ExpertsPage`(fetchExperts 卡片网格+切换，对齐 Octop Agents 页)、`CapabilitiesPage`(插件+内核模块启停)、`SkillsPage`(新 GET /api/skills 技能资产清单)、`WorkspacePage`(项目卡片+新建 Modal+文件树)、`SettingsPage`(SettingsModal 新增 `embedded` 模式=rail+内容铺页面，原弹窗保留给 SideBar/命令入口)。
- **主题 F4**：`themes.ts` 8 品牌色板（对齐 Octop rose #E85D75/tech #4B74FA/indigo #6366F1/teal #0D9488/violet #7C3AED/emerald #10B981/amber #F59E0B/slate #64748B，默认 rose）+ `brandTokens(palette,dark)` → ConfigProvider token（colorPrimary/colorBgBase 深色 #101216）；palette 持久化 `nuomi-palette`，切换时同步 CSS 变量 `--accent` 族（自有模块）+ token（antd 组件）。明暗 `nuomi-theme` 既有。
- **踩坑**：lucide-react 无 `Robot` 导出→`Bot`；antd 装的是 **v6**（Octop 是 v5，Menu/Sider theme prop 运行时已验证可用）；doToggle/available 等旧引用随插件面板迁出 App 时清理（TS6133 链）；`createRecognizer` 是 App 语音逻辑依赖，删 InputBar import 时只删组件保留函数。
- **验证（2026-10-03）**：tsc --noEmit 全绿 + vite build 通过（manualChunks 拆 antd/assistant 消 chunk 警告）；浏览器冒烟：/#/chat 三栏 + 会话树 + 模型菜单 + 机器人入口、/#/experts 专家卡片（当前专家/默认标签+切换）、/#/capabilities 插件启停、/#/skills 9 技能、/#/workspace 项目卡片+新建+删除、/#/settings embedded 设置页、色板 8 项持久化（localStorage nuomi-palette=tech）、明暗 Switch 生效（--accent=#4B74FA）。
- **commit**：`0f2f1fe`（v0.9 前端迁移，16 files +2689/−240）。后端 /api/skills 一并入此 commit。
