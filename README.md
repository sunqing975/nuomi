# 糯米 · Nuomi V2

全能型个人智能体（对齐 DeepSeek Harness 方向，打字为核心，能力全部插件化）——面向求职作品集的完整项目。

主线技术栈：**LangChain / LangGraph + FastAPI + React**，前后端分离 + Cordis 风格插件内核（一切皆插件）+ 执行能力（shell/fs）+ 上下文工程 + 记忆/知识/协作。聊天界面接入 **assistant-ui**（headless primitives + LocalRuntime）渲染流式回复、深度思考（推理过程折叠块）与工具调用卡片。

> 定位沿革：v1/v2 曾是陪伴型智能体（伙伴人格 + 情绪表情）；2026-10-01 起转型为全能智能体，陪伴资产保留为可选"人格层"插件，不再是产品主定位。

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
│   │   ├── plugins/    插件内核：loader（技能扫描）/ lifecycle / runtime / composer / approval / robust
│   │   ├── storage/    统一存储层：db（ensure_database 迁移 + 版本化）/ projects / memory / knowledge / trace
│   │   ├── core/       V3 内核：events（5 分发）/ scope / context / fiber / composition / skill
│   │   └── sse.py      SSE 事件协议封装
│   ├── sidecar_main.py 桌面 sidecar 入口（PyInstaller 打包后端时使用）
│   ├── tests/          127 项假模型端到端测试（不花 API 费用）
│   └── data/           遗留运行时数据（v0.2 时代产物；已由首启迁移一次性读入统一库，只读保留）
├── frontend/           Vite + React + TS（对齐 Harness 设计系统：深色主题/三栏/设置弹窗/插件管理）
├── plugins/            统一插件目录：加一个目录 = 多一种能力（一切皆插件）
│   ├── service-*       V3 服务插件（agent-loop/sessions/settings/memory/system-prompt/tools）
│   ├── shell/          shell 执行器（沙箱三级 read-only/workspace-write/full-access）
│   ├── fs/             fs 工作区文件工具（read/write/list/search，路径防穿越）
│   ├── datetime/       能力型：获取当前时间（@tool）
│   ├── memory/         能力型：memory_write / memory_read（记忆是插件）
│   ├── knowledge/      知识型：RAG 语义存取（Chroma + fastembed）
│   ├── mcp-notes/      MCP 型：本地便签 MCP server（stdio），adapter 接入
│   ├── pyfunc/         adapter 演示：外部格式插件（普通函数）转 LangChain 工具
│   ├── web/            http_get 网页正文抓取
│   ├── voice/ voice-input/  语音 TTS + 前端 STT
│   └── mood/ team/ …   情绪联动 / Supervisor 挂卸等程序插件
├── partners/           伙伴人格目录（v1 陪伴资产，保留为可选人格层）
├── scripts/smoke.sh    冒烟测试脚本
└── .env.example        环境变量示例
```

## 快速开始

```bash
# 1) 后端（uv 管理依赖，首次自动建 .venv）
cd backend && uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 前端（另开终端）
cd frontend && npm install && npm run dev
# 打开 http://localhost:5173
```

> 当前实际跑法（开发机）：后端 `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`（未开 `--reload`，改后端代码需重启进程）；前端 `npm run dev`（Vite，:5173，热更新）。

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
- **资源目录**：`PLUGINS_DIR` / `PARTNERS_DIR` 可覆盖（打包时指向 PyInstaller 内嵌只读区；源码运行默认指向仓库 `plugins/`、`partners/`）。
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
| 工具体系 | 自研三级加载插件内核 | @tool + 程序插件 + MCP + adapter 统一成"插件" |

### 前端

| 层 | 选型 | 说明 |
|---|---|---|
| 框架 | **React 18** + **Vite 5** + TypeScript | 前后端分离 SPA |
| 聊天界面 | **assistant-ui**（`@assistant-ui/react`，MIT） | LocalRuntime + ChatModelAdapter 桥接自建 SSE；headless primitives 渲染文本/深度思考/工具调用，未引入 Tailwind |
| 表情组件 | **react-ai-pet**（MIT） | WebGL 果冻身体 + 表情，思考动画 |
| 语音输入 | Web Speech API | `voice-input` 插件控制 |

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

## 插件规范（v0.3）

```
skills/<插件名>/
├── plugin.json    # name / version / type / description / entry / system_instruction(可选) / load(可选)
├── <entry>.py     # 必须导出 TOOLS: list（@tool 函数或 BaseTool）
└── 其他资源       # server.py（MCP）、tools_external/（外部插件）等
```

`type` 区分：
- `capability` **能力型** —— 给智能体一项可调用能力（时间/天气/日程/记忆读写…）
- `procedural` **程序型** —— 一段既定流程（日报生成…），Phase 3 由调度器按流程驱动
- `knowledge` **知识型** —— RAG 知识库（Chroma+fastembed，方案可插拔）
- `mcp` **外部能力** —— 经 MCP 协议接入的远端/本地工具集

`load` 区分（可选，默认 eager）：
- `eager` 启动即导入入口生成工具（轻量能力：datetime/memory）
- `lazy` 延迟导入；重资源（MCP 会话、embedding 模型、向量库）在工具**首次调用**时才初始化并缓存

**三级加载（★ 架构核心，面试表达）**：
1. **元数据常驻**：启动只读 plugin.json 建注册表（/health 可见技能目录，不 import 任何代码）
2. **指令触发**：构建 agent 时按需导入入口生成 TOOLS（模型由此知道有哪些能力）
3. **资源按需**：重资源在首次工具调用时初始化并缓存（MCP 连接 / embedding 模型 / Chroma 都是懒加载）

`system_instruction`（可选）：插件自述"什么时候该用我"，加载器收集后置于 system prompt **最前**（最高优先级）。
实测结论：工具规则若不前置，小模型会进入闲聊模式而不调用工具。

设计：统一插件体系（技能+工具+MCP 打包成一个插件），加载器按 type 分发；
加能力 = 放目录；换 RAG/记忆方案 = 换插件。贴合 SKILL.md/MCP 行业形态，最大化复用。

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
- **统一插件体系**：技能+工具+MCP 打包成一个插件，加载器按 type 分发；加能力=放目录；换 RAG 方案=换插件/配置。
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

## 插件管理（Phase 4d+）

**理念**："加目录=多能力，关开关=少能力"——插件开关是运行时真开关。

**API**
- `GET /api/plugins`：全部插件（三类分组：程序插件 / 功能插件 / MCP 技能），含启用状态、工具清单、设置
- `POST /api/plugins/{name}/toggle`：启停。程序插件（如 `voice-input` 语音输入开关）翻转设置；其余技能插件翻转 enabled 集并**重建 Agent/Supervisor**（工具集实时变化）
- 引擎级联动：停用 `memory` 插件时，中间件的记忆注入同时关闭——模型表现为"失忆"（工具层 + 注入层都受控）

**前端**（React，单用户）：左侧糯米卡通角色（SVG 猫，状态表情：idle/thinking/typing/listening，尾巴动画）；中间聊天区；右侧插件管理面板（开关 + 工具 chips + 类型标签）；语音输入麦克风按钮（Web Speech API，受 `voice-input` 程序插件控制）。登录已移除。

## 统一插件体系 v0.4（Phase 4d+ 重构）

**物理统一**：一个插件 = 一个目录 + plugin.json 清单（根目录 `plugins/`），加载器只扫一遍清单，按 `type` 分发——不存在两套割裂机制。
- `capability / knowledge / adapter / mcp`：能力型——给模型加"会什么"（时间/记忆/知识库/语音/浏览器/MCP 工具）
- `program`：程序型——给运行时加扩展（钩子/开关）：`voice-input`（语音输入开关）、`team`（智能体团队）
- 将来加新类型只需加一个 type + 一个注册器

**智能体团队（程序插件 team）**：默认启用。启用时构建 Supervisor（companion 陪伴 + researcher 研究员子 Agent，LLM 自动路由），`/api/chat` 自动走团队路由；停用退化为单 Agent。前端无模式按钮——团队就是一个可开关插件。

**模型管理（运行时切换 LLM）**：
- `GET /api/models`：deepseek / doubao(火山方舟) / llama-local（本地 llama.cpp 2B，OpenAI 兼容）
- `POST /api/models/{key}/activate`：切换后重建 Agent（工具/团队随之更新），key 缺失或本地服务未启动时拒绝
- 前端右栏"模型"区一键切换

**前端**：开源表情组件 [react-ai-pet](https://www.npmjs.com/package/react-ai-pet)（MIT，WebGL 果冻身体 + 17 表情 + 眼睛跟随光标）——shape=mochi 米糕，正合"糯米"。思考时播放 ponder 特效；聊天气泡精简（角色只在左栏，陪伴感聚焦）。
