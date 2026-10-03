# 糯米桌面化 · 数据与工作区架构（2026-10-02 确认版）

> 决策人：用户（三点确认）+ 本方案。本文是桌面化与后端结构重构的权威设计文档，
> 与 `DESIGN.md`（前端设计权威）同级；改动落地前先读本文。

## 1. 背景与已确认决策

原状态：全部运行时数据锚在仓库 `backend/data/`（`config.py` 用 `Path(__file__).parents[1]`
解析相对路径），桌面打包后仓库根既不存在也不可写；存储碎片化（checkpointer / 项目会话 /
记忆 / 设置分属多个库与文件）；前端"项目"概念与 shell/fs 工作区两套割裂。

已确认决策：

| # | 决策 | 内容 |
|---|---|---|
| 1 | 多用户形态 | **不再考虑**。移除 JWT 登录、users.json、`/api/auth/*`、PG checkpointer 路径 |
| 2 | 工作区 | 默认 `~/Documents/Nuomi/`（用户可见、可在设置/首启向导中改） |
| 3 | 存储 | **全合一 SQLite**：checkpointer + 项目/会话 + 记忆事实 + 设置收敛进单个 `nuomi.db` |
| 4 | 目录结构 | `backend/app/` 散落的 ~19 个 py 按职责收敛为功能子包 |
| 5 | 数据根 | **不做 dev/packaged 双 profile**（用户否决：增加复杂度）。单一规则：所有运行时数据锚定 `NUOMI_HOME`，开发/打包/桌面完全同源 |

## 2. 单一数据根规则（决策 5 的落地）

```
解析优先级：NUOMI_HOME 环境变量 > 默认 ~/Library/Application Support/Nuomi（macOS）/ ~/.nuomi（其他）
```

- 数据根之下所有路径（DB、记忆、知识库、日志、设置、插件组合配置）一律派生自 `NUOMI_HOME`，**不再相对仓库解析**。
- 仓库只放代码；`backend/data/` 变为遗留目录，一次性迁移后不再写入。
- 唯一保留的环境变量覆盖（非 profile）：
  - `PLUGINS_DIR` / `PARTNERS_DIR`：资源目录。源码运行默认仓库 `plugins/`、`partners/`；
    PyInstaller 打包后无仓库，由 sidecar 指向包内只读资源区（`sys._MEIPASS`）。
  - `NUOMI_WORKSPACE`：工作区路径覆盖（首启向导会写入设置）。
- 测试隔离：`backend/tests/conftest.py` 在**任何 app 导入之前**设置 `NUOMI_HOME`、`NUOMI_WORKSPACE`
  为 pytest 临时目录（conftest 顶层不再提前 import app 模块）。

## 3. 目标目录结构

### 3.1 仓库级（不变动部分省略）

```
nuomi/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + 装配（路由暂不拆，后续阶段再薄化）
│   │   ├── config.py          # Settings（单一数据根；被全模块引用，保持顶层）
│   │   ├── sse.py             # SSE 协议封装（仅 main.py 使用）
│   │   ├── core/              # V3 内核（events/scope/context/fiber/composition/skill）——不动
│   │   ├── agent/             # 智能体构建
│   │   │   ├── graph.py       # ← agent.py：LLM + 工具 + checkpointer → create_agent
│   │   │   ├── middleware.py  # ← context.py：每轮注入人设+记忆+摘要
│   │   │   ├── supervisor.py  # ← supervisor.py：团队模式子 Agent
│   │   │   ├── partner.py     # ← partner.py：伙伴人设组装
│   │   │   ├── models.py      # ← models.py：模型管理与 DeepSeekChat
│   │   │   └── thread_ctx.py  # ← thread_ctx.py：请求级会话上下文（contextvars）
│   │   ├── plugins/           # 插件内核（v0.7 三区：插件/模块/技能）
│   │   │   ├── loader.py      # ← skills.py：三级加载/扫描/技能目录
│   │   │   ├── lifecycle.py   # ← plugins.py：apply/toggle/列表
│   │   │   ├── runtime.py     # ← plugin_runtime.py：事件总线/PluginContext
│   │   │   ├── composer.py    # ← composer.py：V3 组合驱动（fiber 树）
│   │   │   ├── approval.py    # ← approval.py：审批门
│   │   │   └── robust.py      # ← robust.py：重试/超时/fallback
│   │   └── storage/           # 存储层
│   │       ├── db.py          # 新增：统一 SQLite 连接/schema/迁移
│   │       ├── projects.py    # ← projects.py：项目/会话（并入统一库）
│   │       ├── memory.py      # ← memory.py：记忆事实（JSON → SQLite 表）
│   │       ├── knowledge.py   # ← knowledge.py：RAG（Chroma 保持，接口不变）
│   │       └── trace.py       # ← trace.py：可观测（文件 + 轮转）
│   ├── sidecar_main.py        # 桌面 sidecar 入口（随新数据根规则大幅简化）
│   └── tests/                 # 同步更新 import；test_auth/test_pg 删除
├── plugins/                   # 仓库插件目录（不变；入口 import 同步更新）
└── docs/desktop-data-architecture.md
```

### 3.2 `NUOMI_HOME` 内部布局（单一数据根）

```
~/Library/Application Support/Nuomi/
├── nuomi.db          # 统一库：LangGraph checkpoints + projects/threads + facts + settings（user_version 版本化）
├── nuomi.json        # V3 插件组合配置（profile，composer 读写）
├── memories/         # 预留（当前记忆已入 nuomi.db 的 facts 表；保留目录语义）
├── knowledge/        # Chroma 向量库（RAG 插件数据）
├── logs/trace.jsonl  # 可观测日志（按大小轮转）
├── audio/            # 语音产物
└── plugins/          # 用户级插件（可装卸；打包形态在线安装的落点）
```

工作区（独立于数据根，用户可见）：

```
~/Documents/Nuomi/    # 默认工作区；一个项目 = 一个目录
```

## 4. 存储合一（决策 3 的落地）

### 4.1 统一库 `nuomi.db`

| 归属 | 表 | 说明 |
|---|---|---|
| LangGraph | checkpoints / checkpoint_writes | `AsyncSqliteSaver.from_conn_string(nuomi.db)`（自建表，共存无冲突） |
| 项目/会话 | projects / threads | `ProjectStore` 现有 DDL 直接建在统一库 |
| 记忆 | facts | `MemoryStore` 改 SQLite：id/content/category/created_at/updated_at/access_count，接口不变 |
| 设置 | settings（key/value，JSON 值） | `SettingsStore`（service-settings 插件）改 SQLite，接口不变 |

版本与迁移：`PRAGMA user_version` 记录 schema 版本（当前 1）；启动时仅确保 schema 存在，
**无任何遗留数据迁移**（2026-10-02 决策：废弃 `backend/data`，桌面版为全新环境）。

### 4.2 保留文件形态的理由（决策记录）

- `trace.jsonl`：append-only 日志，文件天然适合；加按大小轮转即可。
- `nuomi.json`：插件组合配置，需人工可读可改，保持 JSON。
- Chroma 向量库：独立引擎（"换 RAG 方案 = 换插件"），不强行并入 SQLite。

## 5. 移除项（决策 1）

- `backend/app/auth.py`、`tests/test_auth.py`、`users.json`、`/api/auth/register|login`、
  `Depends(current_user)`、会话 key 的 `user::` 前缀。
- PG checkpointer：`create_pg_checkpointer`、`CHECKPOINTER=postgres`、`PG_DSN`、
  `tests/test_pg.py`、`docker-compose.yml` 的 postgres 服务、`langgraph-checkpoint-postgres` 依赖。

## 6. 桌面壳（阶段 C 摘要，本文档登记不展开）

- Rust 层：单实例锁（tauri-plugin-single-instance）、拉起/健康检查/退出 sidecar、动态端口；
  每次启动生成随机 token（32 字节 hex）以 `NUOMI_TOKEN` env 传入后端，后端中间件校验
  `X-Nuomi-Token`（`/api/health` 放行、其余 401）；就绪后注入
  `window.__NUOMI_API__` 与 `window.__NUOMI_TOKEN__`（前端 fetch 包装自动加前缀与头）。
- sidecar（`sidecar_main.py`）：只做三件事——解析 `--port`、`PLUGINS_DIR`/`PARTNERS_DIR`
  指向 `sys._MEIPASS`、以 `127.0.0.1:<--port>` 起 uvicorn。不再逐项设置 DB/MEMORY/TRACE 环境变量。
- 安全：仅绑定 loopback；token 守卫（env 优先 → frozen 时 `NUOMI_HOME/.api-token` 幂等复用 0600 → dev None 不校验）；
  CSP 收紧为 `connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*`。

## 7. 落地路线与状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| A | 目录结构收敛为子包 + 单一数据根 + 存储合一 + 移除多用户 | ✅ 已完成（2026-10-02）：后端全量改造 + pytest 127 passed + 迁移模拟验证 + 隔离冒烟 + 前端 tsc + uv 锁更新 + README/AGENT.md/.env.example 同步 |
| B | 工作区=项目打通（后端 `/api/workspace/tree`、`POST /api/projects` 无目录时自动在工作区建目录；前端 SideBar 会话/文件双视图 + FilesPanel 目录树） | ✅ 已完成（2026-10-02） |
| C | 桌面壳接线（sidecar 生命周期/动态端口/token 守卫/CSP 收紧/单实例/双变量注入） | ✅ 已完成（2026-10-02）：后端 token 中间件 + Rust 壳 token 生成与注入 + CSP loopback + cargo build 通过 |
| D | 首次运行向导（`GET /api/bootstrap` 判定 + 前端 WelcomeWizard：工作区路径 → LLM 供应商配置并激活） | ✅ 已完成（2026-10-02）：全新环境直接向导，无迁移/导出流程 |
