# 糯米 · Nuomi V2

**有温度的全能智能体**：会干活，也记得你。

糯米是一个桌面个人智能体。内核对齐 DeepSeek Harness 方向——打字为核心、能力全部插件化——具备完整的执行能力（shell/fs 沙箱）、上下文工程与记忆/知识/协作；同时保留 v1 的陪伴人格层（情绪、表情、伙伴记忆），让你面对的不仅是一个冷工具，而是一个记得你的助手。

主线技术栈：**LangChain / LangGraph + FastAPI + React**，前后端分离 + Cordis 风格扩展内核（v0.7 三区：插件=可选能力 / 模块=内核组成部分 / 技能=独立文档资产）+ 执行能力（shell/fs）+ 上下文工程 + 记忆/知识/协作。聊天界面接入 **assistant-ui**（headless primitives + LocalRuntime）渲染流式回复、深度思考（推理过程折叠块）与工具调用卡片。

> 定位沿革：v1/v2 曾是陪伴型智能体（伙伴人格 + 情绪表情）；2026-10-01 起转型为全能智能体；2026-10-02 桌面化定稿。陪伴资产从"主定位"转为"人格层"，构成与 Harness 类冷工具的关键差异——**能干活的 agent 很多，记得你的只有一个糯米。**

## 分阶段路线图

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 打字核心：LangGraph agent + SQLite 持久化 + SSE 流式 + React 打字页 + skills/ 目录 | ✅ 完成 |
| Phase 1 | 伙伴人设 + 记忆 + 上下文压缩 | ✅ 完成 |
| Phase 2 | 插件化技能系统（三级加载 / @tool / MCP / RAG 可插拔 / adapter）★核心亮点 | ✅ 完成 |
| Phase 3 | 工程健壮：重试/fallback、human-in-the-loop、Eval 评测、日志可观测 | ✅ 完成 |
| Phase 4 | 部署 + 扩展：Docker、多智能体 Supervisor、语音、模型管理（~~多用户 JWT / PostgreSQL~~，2026-10-02 移除：桌面单用户化） | ✅ 完成 |
| Phase 5 | 全能化★：执行能力（shell 沙箱 / fs 文件工具 / subagent）、上下文工程（compaction/spill）、交互（user-questions）、产物（credentials/attachment） | 🔄 进行中 |

Phase 0→2 是主线；Phase 3 面试必补；Phase 5 当前推进（对齐 deepseek-harness）。

## 目录结构

```
nuomi/
├── backend/            FastAPI + LangGraph（Python 3.12，uv 管理）
│   ├── app/
│   │   ├── main.py     POST /api/chat（SSE 流式）+ /api/plugins /api/settings /api/projects…
│   │   ├── config.py   环境变量配置（NUOMI_HOME 单一数据根 / LLM 密钥）
│   │   ├── agent/      智能体组装：graph（create_agent + checkpointer）/ middleware / supervisor / partner / thread_ctx / models
│   │   ├── plugins/    插件内核：loader（插件/模块扫描 + 技能扫描）/ lifecycle / runtime / composer / approval / robust
│   ├── modules/    内核模块目录：service-*（运行时服务）/ mood·team·robot·voice-input（钩子/模式）/ agent-*（Agent preset）
│   │   ├── storage/    统一存储层：db（ensure_database 迁移 + 版本化）/ projects / memory / knowledge / trace
│   │   ├── core/       V3 内核：events（5 分发）/ scope / context / fiber / composition / skill
│   │   └── sse.py      SSE 事件协议封装
│   ├── sidecar_main.py 桌面 sidecar 入口（PyInstaller 打包后端时使用）
│   ├── tests/          143 项假模型端到端测试（不花 API 费用）
│   └── data/           遗留运行时数据（v0.2 时代产物；已由首启迁移一次性读入统一库，只读保留）
├── frontend/           Vite + React + TS（对齐 Harness 设计系统：深色主题/三栏/设置弹窗/插件管理）
├── plugins/            插件区：可选能力分发单元（加一个目录 = 多一种可调用能力）
│   ├── shell/          shell 执行器（沙箱三级 read-only/workspace-write/full-access）
│   ├── fs/             fs 工作区文件工具（read/write/list/search，路径防穿越）
│   ├── datetime/       获取当前时间（@tool）
│   ├── memory/         memory_write / memory_read（长期记忆读写）
│   ├── knowledge/      RAG 语义存取（Chroma + fastembed）
│   ├── mcp-notes/      本地便签 MCP server（stdio），adapter 接入
│   ├── pyfunc/         adapter 演示：外部格式插件（普通函数）转 LangChain 工具
│   ├── web/            http_get 网页正文抓取
│   └── voice/          语音 TTS + 本地 STT
├── skills/             技能区：独立文档资产（SKILL.md 说明书，全量注入 system prompt，不随插件启停）
├── backend/app/modules/  模块区：内核组成部分（service-* 服务 / mood·team·robot·voice-input·memory-mem0 钩子模式 / agent-* Agent preset）
├── partners/           伙伴人格目录（v1 陪伴资产，保留为可选人格层）
├── scripts/smoke.sh    冒烟测试脚本
└── .env.example        环境变量示例
```

## 快速开始

```bash
# 桌面版（推荐，默认形态）：`cargo tauri dev` 自动拉起 vite + 源码后端
make start        # 弹窗即桌面应用；后端由 tauri 自动管理（随机端口+token，退出自动回收）
make stop         # 停止桌面版（含残留回收）
make status       # 运行状态 · make logs 查看日志 · make restart 重启

# web 调试（可选，浏览器访问 http://localhost:5173）
make web          # 后端 :8000 + 前端 :5173（vite 代理 /api → 8000）
```

> 首次需准备依赖：`cd backend && uv sync`、`cd frontend && npm install`、桌面版 `frontend/dist` 由 `make build`（或 `cargo tauri dev` 的 beforeDevCommand）构建。
> 桌面版 dev 模式：8000 已有可用后端时 tauri 直接复用（无 token）；否则自起源码后端于随机空闲端口并注入 `window.__NUOMI_API__/__NUOMI_TOKEN__`。

LLM：默认 DeepSeek（`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-chat`）。
密钥取 `LLM_API_KEY` → `DEEPSEEK_API_KEY` → `ARK_API_KEY` 任一即可；换豆包只需改 `.env` 里的 base_url 与 model。
模型可在前端「设置」里运行时切换（DeepSeek / 豆包 / 本地 llama.cpp OpenAI 兼容端点）。

**当前测试策略（2026-09-30）**：测试主力 DeepSeek（工具调用可靠）。
本地 Qwen3.5-2B（llama.cpp :8080，`~/scripts/serve-qwen3.5-2b.sh start`）适合纯对话；
实测其工具调用不稳定（易编造时间），因此工具关键路径用 DeepSeek。`.env` 中两种配置均已写好，注释切换即可。

冒烟测试（后端已启动时）：`bash scripts/smoke.sh`

## 数据与工作区（桌面化架构，2026-10-02）

**单一数据根**：所有运行时数据锚定 `NUOMI_HOME`（默认 `~/Library/Application Support/Nuomi`，可用环境变量覆盖），dev / 打包 / Docker 同源，无 profile 切换。

```
NUOMI_HOME/
├── nuomi.db      统一 SQLite：LangGraph checkpoints + projects/threads + facts 记忆 + settings 设置（PRAGMA user_version 版本化）
├── nuomi.json    运行时 profile（插件开关/模型选择等，与设置分离）
├── knowledge/    Chroma 向量库（knowledge/<partner>/chroma）
└── logs/         trace.jsonl（5MB 轮转，保留 3 备份）
```

- **工作区**：`WORKSPACE_DIR`（默认 `~/Documents/Nuomi`，首启自动创建）——shell/fs 等工具的文件操作根目录，与程序数据分离；优先级 `NUOMI_WORKSPACE`/`WORKSPACE_DIR` env > 运行时设置 > 默认路径。侧栏"文件"视图展示工作区目录树（`/api/workspace/tree`），新建项目无绑定目录时自动在工作区创建同名目录。
- **资源目录**：`PLUGINS_DIR` / `SKILLS_DIR` / `PARTNERS_DIR` 可覆盖（打包时指向 PyInstaller 内嵌只读区；源码运行默认指向仓库 `plugins/`、`skills/`、`partners/`）。模块 `backend/app/modules/` 随 Python 代码打包，不走资源覆盖。
- **首启向导**：全新环境（未配置任何 LLM 供应商）启动时全屏引导：选择工作区路径 → 配置 OpenAI 兼容模型服务并激活（`/api/bootstrap` + `POST /api/bootstrap/workspace`）。
- **本地 API 守卫（桌面形态）**：Tauri 壳每次启动生成随机 token（`NUOMI_TOKEN` env 传入后端），后端中间件校验 `X-Nuomi-Token`（`/api/health` 放行）；仅绑定 `127.0.0.1` 回环。前端 fetch 自动带 token，web dev（vite proxy）不受影响。
- **单用户**：JWT / PostgreSQL / 多用户命名空间已移除（2026-10-02）；`backend/data/` 遗留数据已废弃（不迁移，桌面版全新环境）。
- 设计文档：[`docs/desktop-data-architecture.md`](docs/desktop-data-architecture.md)

## 技术栈与开源项目

### 后端

| 层 | 选型 | 说明 |
|---|---|---|
| Web 框架 | **FastAPI** + uvicorn | SSE 流式（`text/event-stream`） |
| Agent 框架 | **LangChain / LangGraph**（`langchain.agents.create_agent`） | 工具绑定、checkpointer、中间件、Supervisor 多智能体 |
| 模型接入 | **langchain-openai** + **openai** SDK | OpenAI 兼容协议：DeepSeek / 豆包 / 本地 llama.cpp |
| 对话状态 | **SQLite**（LangGraph SqliteSaver，统一库 `NUOMI_HOME/nuomi.db`） | 每线程 checkpoint，重启不丢；WAL + busy_timeout 多线程安全 |
| 记忆 | 自研 MemoryStore（SQLite facts 表） | CJK 二元组检索、去重淘汰；换向量库 = 换 search 实现 |
| 知识库 | **Chroma** + **fastembed**（`BAAI/bge-small-zh-v1.5`） | RAG 语义检索，词法兜底可插拔 |
| MCP | **langchain-mcp-adapters** | 本地便签 server（stdio）演示外部能力 |
| 工具体系 | 自研三级加载插件内核（v0.7 三区：插件/模块/技能） | 插件=可选能力（工具）、模块=内核（服务/钩子）、技能=独立 SKILL.md |

### 前端

| 层 | 选型 | 说明 |
|---|---|---|
| 框架 | **React 18** + **Vite 5** + TypeScript | 前后端分离 SPA |
| 聊天界面 | **assistant-ui**（`@assistant-ui/react`，MIT） | LocalRuntime + ChatModelAdapter 桥接自建 SSE；headless primitives 渲染文本/深度思考/工具调用，未引入 Tailwind |
| 表情组件 | **react-ai-pet**（MIT） | WebGL 果冻身体 + 表情，思考动画 |
| 语音输入 | Web Speech API | `voice-input` 模块（内核钩子）控制 |

### 模型

- **DeepSeek**（默认，工具调用可靠）
- **豆包 / 火山方舟**（OpenAI 兼容端点）
- **本地 llama.cpp**（Qwen3.5-2B，纯对话）

## SSE 协议（v2）

`POST /api/chat`，body：`{"message": "...", "thread_id": "可选"}`，响应 `text/event-stream`：

| event | data | 说明 |
|---|---|---|
| `meta` | `{thread_id}` | 会话已确定（新建时由服务端生成） |
| `token` | `{content}` | 回复增量片段，前端逐字追加 |
| `reasoning` | `{content}` | 深度思考增量（DeepSeek `reasoning_content`，经 `DeepSeekChat` 子类保留） |
| `tool` | `{name}` | 模型正在调用某工具（单 Agent 与团队模式都会发） |
| `done` | `{thread_id, content, emotion, usage}` | 完整回复、情绪、token 用量，流结束 |
| `title` | `{thread_id, title}` | 模型命名会话标题（与回复流并行生成，几乎零等待） |
| `error` | `{message}` | 出错，流提前终止 |

前端 `NuomiAdapter`（assistant-ui `ChatModelAdapter`）把该协议转成 part 流：`reasoning`→深度思考折叠块、`tool`→工具调用卡片、`token`→文本气泡；`meta/title/done` 经回调回填会话与情绪。

历史记忆：thread_id 相同 → LangGraph checkpointer 自动续上下文（SQLite 持久化，重启不丢）。

## 概念体系（v0.7，三区）

**插件**（`plugins/`）= 可选能力分发单元：目录 + plugin.json，入口（`hook.py`，`apply(ctx)`）向 LLM 注册工具，可安装 / 卸载 / 启停 / 配参数。
**模块**（`backend/app/modules/`）= 内核组成部分：运行时服务（service-*）、钩子/模式（mood/team/robot/voice-input/memory-mem0）、Agent preset（agent-companion/agent-researcher），随系统启动（builtin）。
**技能**（`skills/`）= 独立文档资产：SKILL.md 说明书，全量注入 system prompt，不随插件/模块启停过滤。

- 判定：给 LLM 加可调用能力 → 插件；运行时基础设施/钩子/模式 → 模块；教 LLM 用能力的文档 → 技能。目录即分类，无 `kind`/`type` 字段。
- 关联：插件与技能**同名即关联展示**（如插件 `memory` ↔ 技能 `memory`），但技能区独立可用。
- 未引入：`kind`（目录即分类）、技能包（多技能聚合，暂缓）、插件市场。
- 权威口径与完整清单：见 [`docs/concepts.md`](docs/concepts.md)。

### 插件/模块/技能结构（v0.7.1，三种概念三种清单）

```
plugins/<name>/        # 插件：可选能力（能力导向清单）
├── plugin.json        # name / description / version / system_instruction(可选) / load(可选) / robust(可选) / approval(可选)
└── hook.py            # 入口：apply(ctx) 注册工具（TOOLS 形态亦兼容）
backend/app/modules/<name>/   # 模块：内核组成部分（内核导向清单）
├── module.json        # name / description / version / entry + provides[](声明的 ctx 服务) / hooks[](订阅的事件)；可选 load/system_instruction/settings
└── <name>.py          # 唯一入口：apply(ctx) provide/on（入口名 = 目录名转下划线）
skills/<name>/SKILL.md        # 技能：frontmatter(name/description/when_to_use) + 正文
```

- **格式随概念分离**（对齐 Octop 声明式领域）：插件 `plugin.json` 能力导向、模块 `module.json` 内核导向（`provides[]`/`hooks[]` 声明式，扫描期即见，展示 = 声明 ∪ 运行时）、技能 `SKILL.md` frontmatter 即清单。运行时机制三区同构（一套 Fiber/apply/ctx 引擎），不区分加载路径。

**三级加载（★ 架构核心，面试表达）**：
1. **元数据常驻**：启动只读清单建注册表（不 import 任何代码）
2. **指令触发**：构建 agent 时按需导入入口生成 TOOLS（模型由此知道有哪些能力）
3. **资源按需**：重资源在首次工具调用时初始化并缓存（MCP 连接 / embedding 模型 / Chroma 都是懒加载）

`system_instruction`（可选）：插件自述"什么时候该用我"，收集后置于 system prompt **最前**（最高优先级）。
实测结论：工具规则若不前置，小模型会进入闲聊模式而不调用工具。

`robust`（可选）：工具健壮性策略（超时/重试/兜底）；`approval`（可选）：高风险工具清单（调用需人工确认）。

### MCP 接入（Phase 2 实测 API）

`langchain-mcp-adapters`（当前装 0.3.x）：
- `MultiServerMCPClient({"<server>": StdioConnection(transport="stdio", command=..., args=..., env=...)})
- **不是上下文管理器**：直接 `tools = await client.get_tools()`，每次工具调用自动开新会话
- `StdioConnection` 是 TypedDict，**必须带 `transport` 键**；env 需显式传（默认不继承，测试隔离靠 NOTES_DATA 环境变量）

### RAG 知识库（Phase 2）

- 存储接口 `KnowledgeStore`：`add(content, category)` / `search(query, top_k)` / `count()`
- 默认实现 `ChromaStore`：Chroma（PersistentClient + cosine）+ fastembed `BAAI/bge-small-zh-v1.5`（512 维）
- 兜底/测试实现 `LexicalStore`：CJK 二元组词法（零依赖、离线）
- 切换：`knowledge_store=chroma|lexical`（配置/环境变量），上层接口不变——"换 RAG 方案 = 换插件"
- embedding 模型经 `HF_ENDPOINT` 镜像下载（默认 hf-mirror.com，实测直连 huggingface 超时）

## 已验证（2026-09-30 起持续更新）

### Phase 0
- 后端 4 项 pytest 全绿：流式输出、会话持久化、skills 加载、非法请求拦截
- 真实 DeepSeek 端到端：SSE 逐字流式 ✓；datetime 插件被调用 ✓（工具原始输出被过滤，不进聊天流）✓；同 thread 跨轮记忆（"记下 42" → "42 呀，我记着呢"）✓
- 前端 `tsc -b && vite build` 通过 ✓
- 本地 Qwen3.5-2B：纯对话/流式/记忆正常；工具调用实测不稳定（易编造时间），故工具关键路径默认走 DeepSeek

### Phase 1
- 后端 18 项 pytest 全绿：新增伙伴组装/记忆库/中间件注入/摘要压缩测试
- 真实 DeepSeek 端到端：跨会话记忆（thread A 记"喜欢美式咖啡不加糖" → 全新 thread B 能答出，且能背出 USER.md 画像）✓；datetime 插件回归（答复与真实时间吻合）✓；前端代理 + SSE 逐字流式 ✓
- 上下文压缩机制（踩坑结论）：LangChain `create_agent` 的 before_model 中间件返回 messages 更新会被 add_messages 语义按 id 合并，**删不掉旧消息**（实测模型输入持续增长）。改用 `awrap_model_call` 直接构造模型输入（system_message + 裁剪后的 messages），模型输入 token 有界（实测 21→4），摘要按 thread 增量缓存

### Phase 2
- 后端 **33 项 pytest 全绿**：新增加载器 v0.3（元数据常驻/按需导入/错误隔离）、知识库（词法实现+工厂+工具端到端）、MCP（真实拉起本地 server 子进程验证 add/search）、adapter（外部函数转工具）共 15 项
- 真实 DeepSeek 端到端：
  - MCP 便签：让糯米"记一条便签" → 数据写入本地 MCP server 的 notes.json；"查面试相关的便签"能检索出来 ✓
  - RAG 知识库：存入"三级加载"资料（重复存自动合并）→ "插件加载机制分几级？"语义检索答出"元数据常驻/指令触发/资源按需" ✓
  - adapter 计算：137+265 → calc_add 工具返回 402 ✓
- 工具调用链路（插件规则前置）在多工具（datetime/memory/knowledge/mcp/pyfunc 共 9 个工具）下仍稳定 ✓

### Phase 5（UI 集成，2026-10-01）
- **assistant-ui 渲染层接入**：LocalRuntime + ChatModelAdapter 桥接自建 SSE；headless primitives 渲染深度思考（折叠块可展开）与工具调用（卡片）✓
- **后端 DeepSeekChat 子类**：langchain-openai 1.6.6 丢弃 `reasoning_content`，重写转换 hook 保留（流式/非流式均实测）✓
- 真实 DeepSeek 端到端：发送"现在几点了？请调用 get_current_time 工具查询" → 回复依次出现 深度思考 → 「调用工具 get_current_time」卡片 → 真实时间回答 ✓
- 新会话创建、模型命名标题回显（并行生成）、发送后输入框清空、线程切换加载历史均实测通过；`tsc --noEmit` + `vite build` 通过 ✓

## 与 v1 的关系

v1（纯前端 PWA 养宠 + 本地 llama.cpp 双档对话）已备份至
`/Users/superman/projects/code/nuomi-v1-backup-20260930`（旧备份 `nuomi-v1-backup` 亦保留）。
V2 改为前后端分离 + LangGraph 主线；v1 的伙伴人格文件（SOUL/USER/MEMORY）已吸收为
Phase 1 的 `partners/nuomi/` 人设素材。

## Phase 1 设计说明（面试表达）

- **多伙伴 = 多目录**：`partners/<name>/` 一份配置（partner.json + 4 个 markdown），引擎与技能全复用——"预置可爱/御姐伙伴只是加配置文件"。
- **记忆是插件**：`plugins/memory/` 提供 memory_write/memory_read 工具，底层走 MemoryStore（SQLite facts 表，CJK 二元组检索，300 条上限淘汰）。换向量库 = 换 search 实现，接口不变。
- **记忆双通道**：模型主动写（记忆插件） + 系统被动注入（每轮按用户消息检索记忆重建 system prompt），跨会话也能想起。
- **上下文压缩**：NuomiMiddleware 的 `awrap_model_call` 直接构造模型输入；历史超阈值时较早消息压成摘要、只留最近 N 条原文，token 有界，摘要增量缓存。

## Phase 2 设计说明（面试表达）

- **三级加载**：元数据常驻（启动只读 plugin.json，不 import 代码）→ 指令触发（构建 agent 时导入入口生成 TOOLS）→ 资源按需（MCP 连接/embedding 模型/向量库首次调用才初始化并缓存）。"轻的常驻，重的能拖就拖。"
- **三区扩展体系（v0.7，面试表达）**：插件=可选能力（plugins/，注册工具）、模块=内核（modules/，服务/钩子/Agent preset）、技能=独立文档资产（skills/，SKILL.md 全量注入）。目录即分类；换 RAG/记忆方案 = 换插件或换 provider 模块。
- **MCP**：本地便签 server（stdio）演示外部能力接入；客户端连接懒加载，adapter 每次调用自动开新会话。
- **adapter**：外部生态（普通函数+注册标记，无 LangChain 依赖）放 `tools_external/` 即被适配成自家工具——"复用 Codex/Claude 插件只需放目录"。
- **真实取舍**：embedding 模型经 HF 镜像下载（hf-mirror.com）；本地 2B 模型工具调用不可靠故测试走 DeepSeek——面试可讲"模型能力分级"。 

---

## Phase 3 设计说明（工程健壮 + 评测）

**工具健壮性**（`backend/app/robust.py`）：组合式包装器 `with_timeout / with_retry / with_fallback`，`apply_robust` 按 plugin.json 的 `robust` 配置在工具收集时统一应用（fallback→retry→timeout 由外向内）。"工具失败怎么办"从每个工具内部抽到统一层，加策略 = 加一个包装器。

**人机回环**（`backend/app/approval.py`）：`ApprovalGate` 包装 plugin.json `approval` 列表里的高风险工具——调用不执行、登记 pending、返回"需人工确认"；`GET /api/approvals` + `POST /api/approvals/{id}/approve|reject`，批准后补执行（注册表存未包装版本防死循环）。`AUTO_APPROVE=1` 可跳过（测试/演示）。

**可观测**（`backend/app/trace.py`）：每轮对话写一行 `data/logs/trace.jsonl`（会话/消息/工具调用/耗时/错误），`GET /logs?n=` 读取。

**Eval**（`backend/scripts/eval.py` + `eval_scenarios.json`）：10 个场景评分集（人设一致性/时间工具/记忆写读/知识库存取/MCP便签/计算/陪伴感/不编造），rubric 支持 contains / not_contains / regex / tool_used 带权重；每个场景开新 thread，从 /logs 反查工具调用。**真实 DeepSeek 实测 100%（10/10）**，报告见 `backend/data/logs/eval_report_*.json`。

## Phase 4 设计说明（部署 + 扩展）

**多智能体**（`backend/app/agent/supervisor.py`）：LangGraph Supervisor 模式——LLM 路由器 → companion（陪伴：记忆/时间/便签）或 researcher（研究：知识库/计算/便签）子 Agent（create_agent 作为 subgraph 节点），主图持 checkpointer。入口 `POST /api/supervisor/chat`（SSE），`GET /api/supervisor/info` 看子 Agent 工具集。

**语音 + Web 插件**（`plugins/voice`、`plugins/web`）：语音 = macOS say TTS 合成 mp3 + STT 接口化占位（可换 Whisper/豆包语音 API，adapter 形态）；Web = `http_get` 抓网页正文（stdlib，robust 由 plugin.json 配置；换浏览器/MCP 版=换插件）。

**部署**（`Dockerfile.backend / Dockerfile.frontend / docker-compose.yml`）：backend + frontend 两服务（2026-10-02 起无 postgres，SQLite 挂持久卷），端口避开本机（8001/8080）。**PWA**（`frontend/public/`）：manifest + Service Worker 离线缓存。**桌面端**（`desktop/`）：Tauri 2 薄壳 + sidecar（`backend/sidecar_main.py`，PyInstaller 打包，`--port` 由 Tauri 探测注入，数据落 NUOMI_HOME，资源落打包内嵌目录）。

**多用户取舍**：原 JWT 多用户 + PostgreSQL checkpointer 已**移除**（2026-10-02）——桌面单用户形态不需要鉴权与多租户隔离，收益抵不过复杂度；本地 API 回环监听，会话与记忆不再按用户命名空间。

## 插件管理（v0.7 三区）

**理念**："加目录=多能力，关开关=少能力"——插件开关是运行时真开关；模块默认常驻（builtin），技能区独立全量可用。

**API**
- `GET /api/plugins`：全部条目（插件 `category="plugin"` + 模块 `category="module"`），含启用状态、工具清单、服务/事件/技能贡献、设置
- `POST /api/plugins/{name}/toggle`：启停。模块（如 `voice-input` 语音输入开关）翻转设置；插件翻转 enabled 集并**重建 Agent/Supervisor**（工具集实时变化）
- 引擎级联动：停用 `memory` 插件时，中间件的记忆注入同时关闭——模型表现为"失忆"（工具层 + 注入层都受控）。**技能区不受影响**（memory 的 SKILL.md 仍注入，这是设计）

**前端**（React，单用户）：左侧糯米卡通角色（SVG 猫，状态表情：idle/thinking/typing/listening，尾巴动画）；中间聊天区；右侧插件管理面板（只展示外部插件：开关 + 工具 chips + 参数编辑，模块不再展示）；语音输入麦克风按钮（Web Speech API，受 `voice-input` 模块控制）。登录已移除。

## 智能体团队（模块 team，v0.7）

**默认启用**。启用时构建 Supervisor（companion 陪伴 + researcher 研究员子 Agent，LLM 自动路由），`/api/chat` 自动走团队路由；停用退化为单 Agent。前端无模式按钮——团队就是一个可开关模块。

**模型管理（运行时切换 LLM）**：
- `GET /api/models`：deepseek / doubao(火山方舟) / llama-local（本地 llama.cpp 2B，OpenAI 兼容）
- `POST /api/models/{key}/activate`：切换后重建 Agent（工具/团队随之更新），key 缺失或本地服务未启动时拒绝
- 前端右栏"模型"区一键切换

**前端**：开源表情组件 [react-ai-pet](https://www.npmjs.com/package/react-ai-pet)（MIT，WebGL 果冻身体 + 17 表情 + 眼睛跟随光标）——shape=mochi 米糕，正合"糯米"。思考时播放 ponder 特效；聊天气泡精简（角色只在左栏，陪伴感聚焦）。
