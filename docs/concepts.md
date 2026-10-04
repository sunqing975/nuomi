# nuomi 概念体系与架构（v0.8：专家化 + 四层依赖）

> 状态：与代码实况同步（2026-10-03）。
> 本文件是"我们这边"概念的唯一权威口径；写代码注释 / 文档 / 前端文案时按此用词。
> 演进背景见 [`docs/plugin-concept-alignment.md`](plugin-concept-alignment.md)（对齐 Octop 的决策与踩坑记录）。

## 1. 概念模型（四个概念，各司其职）

| 术语 | 定义 | 所在目录 | 是否可被用户启停 | 典型 |
| --- | --- | --- | --- | --- |
| **插件** | 可选能力分发单元：一个目录 + `plugin.json`，入口向 LLM 注册工具 | `plugins/` | ✅ 可安装 / 卸载 / 启停 / 配参数 | shell、fs、memory、knowledge… |
| **模块** | 内核组成部分：运行时的钩子、服务，随系统启动，按领域根组织 | `app/domain/` + `app/transport/` + `app/infrastructure/engine/services/` | ⚠️ 可启停但默认常驻（builtin） | service-*、mood、robot、voice-input… |
| **技能** | 独立文档资产：一份 SKILL.md 说明书，喂给 LLM | `skills/` | ❌ 全量注入，不随任何开关 | datetime、shell、memory… |
| **专家** | 人格 + 能力模板资产（manifest + 人格文档），是用户面对的角色 | `experts/`（仓库根，原 partners/） | 选择器切换（默认糯米） | nuomi（默认专家）、PetBuddy… |

### 1.1 判定规则（写代码时按此判断放哪）

- 这个目录**给 LLM 增加可调用能力**（工具）→ **插件**（工作区 `plugins/`，harness 格式 plugin.yaml）
- 这是**运行时基础设施 / 钩子 / 服务 / 模式**（内核行为，不是"用户可选能力"）→ **模块**（按领域归位：`domain/`、`transport/`、`engine/services/`）
- 这是**一份教 LLM 怎么用能力的文档**（SKILL.md）→ **技能**（工作区 `skills/<name>/SKILL.md`）
- 这是**用户面对的角色**（人格 + 能力模板资产）→ **专家**（`experts/<name>/`，manifest.json + IDENTITY/SOUL/USER.md）

边界示例：
- `mood` 订阅 `response_done` 事件做情绪分析 → 模块（内核钩子），不是插件
- `service-settings` 提供 `ctx.settings` 服务 → 模块（内核服务）
- `shell` 注册 bash 工具 → 插件；它的 `SKILL.md` → 技能（独立区，与插件同名即"关联展示"）
- 停用 `memory` 插件 ≠ 删除记忆能力：技能区 `memory` 的 SKILL.md 仍在、仍注入 system prompt（技能独立于插件启停）

### 1.2 未引入的概念（明确不做）

| 概念 | 状态 | 说明 |
| --- | --- | --- |
| **kind**（插件内部分类） | ❌ 不用 | Octop 用 kind 在一个分发单元内区分 tool/skill/hook；nuomi 直接按职责分目录，目录即分类 |
| **技能包**（多技能聚合单元） | ⏸️ 暂缓 | Octop 有独立技能包概念（DB 管理、可发布共享）；单用户形态暂无需要，用户拍板"后续再说" |
| **插件市场 / zip 安装器** | ❌ 不做 | 目录即插件；已有 install / install-upload API |

### 1.3 四层架构与依赖规则（对齐 Octop AGENTS.md：依赖只允许向内）

```
backend/app/
├── main.py                    装配根：只组装、不写业务（build_app + include_router）
├── transport/                 接入层：薄，只做协议（HTTP 路由/WS/入口模块），不写业务规则
├── domain/                    领域核心：业务逻辑唯一所在地（experts / memory / behavior / capabilities）
├── infrastructure/engine      机制基础库：Fiber/Scope/Registry/Composer 等（≈ octop-harness），
│   └── services/              内核服务模块：薄服务，允许消费领域
├── storage/                   存储 repos：一 repo 只做 SQL/持久化
├── config.py / sse.py         横切：env 配置 / SSE 协议
```

依赖规则（`make check` 首步 `layers` 机器阻断）：

| 规则 | 内容 |
| --- | --- |
| transport → domain/engine/storage | 路由一律经 `app.state.*` 取服务，不直接实现业务 |
| domain → engine/storage/config | 领域可消费机制库与存储，**禁止 import transport** |
| engine 机制库 → 无业务依赖 | 顶层文件禁止 import domain/transport/storage |
| engine/services → domain/engine | 内核服务允许消费领域，禁止 import transport |
| storage → 无上层依赖 | repos 只做 SQL，禁止 import domain/transport/infrastructure |
| main → 一切（只读） | 除 main.py 外任何文件禁止 import main |

### 1.4 领域语言 vs 机制语言（Octop 学习成果）

Octop 的每个概念都是**领域语言**——Expert（专家）、Channel（通道）、Connector（连接器）、Workspace（工作区）、Gateway——一听就懂"是什么、管什么"；机制语言（Fiber/Scope/Registry/Composer）全部隔离进独立基础库（octop-harness / octop-gateway / octop-memory）。nuomi 对齐：

| 用户/前端看到的领域语言 | 内部机制（已下沉 engine/） | 说明 |
| --- | --- | --- |
| 专家（Expert，experts/） | load_expert / assemble_system_prompt | 原"伙伴"概念废弃，改专家 |
| 能力（Capability，插件/模块） | Composer / Fiber / Registry | 插件=可选能力；模块=内核能力；启停走能力域服务 |
| 能力管理（capabilities 域） | composer.toggle/install/uninstall | transport 只调领域 API，不碰 composer |
| 内核服务（service-*） | engine/services + domain | 领域服务层，允许消费领域 |
| 存储（storage repos） | SQLite/JSON repos | 只做持久化，不做业务 |

### 1.5 与外部概念对照（防止三个系统互相串词）

| nuomi（v0.7） | 豆包 | Octop | 关系 |
| --- | --- | --- | --- |
| **插件**（plugins/） | 插件 = 连接器 + 技能的组合（产品层） | 插件 = 分发单元（`plugin.yaml` + `setup(ctx)`，kind 分类） | 取 Octop 语义：分发单元；豆包的"连接器+技能"在 nuomi 由"插件 + 技能区"分开表达 |
| **模块**（模块目录 = 领域根） | —（无对应概念） | hook / 内核能力（middleware） | nuomi 把 Octop 的 hook kind 与自身内核服务统一为"模块"，按领域归位 |
| **技能**（skills/） | 技能（SKILL.md 说明书） | skill（`ctx.skills()` 同步 SKILL.md）；技能包=聚合 | 语义一致：单份 SKILL.md；技能包暂缓 |
| **专家**（experts/，原"伙伴"） | 豆包的角色 / 智能体 | Octop 专家库（`experts/library/<id>/` manifest + IDENTITY/SOUL/USER/HEARTBEAT） | 对齐 Octop：专家 = 人格 + 能力模板资产；糯米为默认专家 |

## 2. 插件清单（plugins/，9 个）

> 全部为 `category="plugin"`，builtin=false，可安装/卸载/启停。工具在 `apply(ctx)` 时注册（`entry` 默认 `hook.py`）。

| 插件 | 版本 | 注册的工具 | 说明 |
| --- | --- | --- | --- |
| datetime | 0.2.0 | `get_current_time` | 获取当前日期/时间/星期（能力型示例：加一个目录 = 多一种能力） |
| fs | 0.1.0 | `read_file` `write_file` `list_dir` `search_files` `delete_file` | 工作区文件工具（作用域=项目绑定目录，未绑定回退工作区，防穿越） |
| knowledge | 0.1.0 | `knowledge_add` `knowledge_search` | RAG 知识库语义存取（Chroma + fastembed，方案可插拔） |
| mcp-notes | 0.2.0 | `notes_add` `notes_search` `notes_delete` | 外部能力示例：本地便签 MCP server（stdio），经 langchain-mcp-adapters 接入 |
| memory | 0.1.0 | `memory_write` `memory_read` `memory_replace` `memory_remove` | 长期记忆读写（名字/偏好/习惯/重要事件）；provider 可切换（内置 / Mem0） |
| pyfunc | 0.1.0 | `calc_add` `greeting` | adapter 演示：外部格式插件（普通函数 + register）适配成 LangChain 工具 |
| shell | 0.1.0 | `bash` `bash_full` | Shell 执行 + 逻辑沙箱（read-only / workspace-write / full-access 三级） |
| voice | 0.1.0 | `speak` `transcribe` | 语音能力：macOS say TTS + 本地 STT（faster-whisper 离线，数据不出本机） |
| web | 0.1.0 | `http_get` | Web 抓取：读取网页正文（stdlib；浏览器/MCP 版可按需替换） |

plugin.json 元数据：`name / description / version` 必填；`system_instruction`（插件自述"什么时候该用我"，置于 system prompt 最前）、`load`（eager/lazy）、`robust`（超时/重试/兜底策略）、`approval`（高风险工具清单）可选。**无 `kind`、无 `type`、无 `entry`（默认 `hook.py`）**。

## 3. 模块清单（按领域根组织，13 个）

> 模块目录已按领域归位（v0.8）：`app/modules/` 解散为 5 个领域根，由 `config.domain_roots` 声明、
> `NuomiComposer` 聚合扫描（`category="module"`）。builtin 判定 = 任一领域根下存在 `module.json`。

**v0.7.1 格式随概念分离（三种概念三种清单）**：

| 概念 | 清单文件 | 导向 | 关键字段 |
| --- | --- | --- | --- |
| 插件（plugins/） | `plugin.json` | 能力导向（给 LLM 用） | `name/description/version` + `system_instruction/load/robust/approval`（默认入口 `hook.py`） |
| 模块（模块目录） | `module.json` | 内核导向（运行时服务） | `name/description/version/entry` + **`provides[]`（声明提供的 ctx 服务）+ `hooks[]`（声明订阅的事件）**，可选 `load/system_instruction/settings/settings_key` |
| 技能（skills/） | `SKILL.md` frontmatter | 文档资产 | `name/description/when_to_use` |
| 专家（experts/） | `manifest.json` | 人格 + 能力模板资产 | `id/name/display_name/label/description/welcome_message/icon_name/color/default/version/prompt_files/quick_prompts` |

模块的 `provides[]` / `hooks[]` 是**声明式元数据**（扫描期即可见，不 import 入口）；`apply(ctx)` 运行时的 `ctx.provide / ctx.on` 作为实际贡献，展示视图 = 声明 ∪ 运行时（保序去重）。

### 3.1 领域根与归位映射（原 app/modules/ 13 个）

| 领域根（config.domain_roots 默认 5 个） | 归位模块 |
| --- | --- |
| `app/domain/experts/` | agent-companion、agent-researcher（专家库模板资产，provides=preset:companion/preset:researcher）、team |
| `app/domain/memory/` | service-memory、memory-mem0 |
| `app/domain/behavior/` | mood（情绪 = 专家人格层） |
| `app/transport/` | robot、voice-input（接入层入口模块） |
| `app/infrastructure/engine/services/` | service-agent-loop、service-sessions、service-settings、service-system-prompt、service-tools |

### 3.2 内核服务（service-*，6 个）——提供 ctx 运行时服务

| 模块 | 提供的服务 | 说明 |
| --- | --- | --- |
| service-agent-loop | `agents` + `agentLoop` | Agent 注册表 + LangGraph 驱动器（单 Agent / Supervisor 路由，每轮记忆注入+摘要） |
| service-memory | `memory` | 记忆服务（JSON MemoryStore，偏好/说过的话跨会话可用） |
| service-sessions | `sessions` | 会话持久化（SQLite checkpointer，对话刷新不丢、可断点续跑） |
| service-settings | `settings` | 设置服务（全局 + 每插件设置，JSON 持久化，变更事件驱动热更新） |
| service-system-prompt | `systemPrompt` | 提示词组装（专家人设 + 插件指令 + 技能目录 + 记忆事实） |
| service-tools | `tools` | 作用域化工具注册表 + 把关执行流水线（tools/pre-execute → execute → post-execute → result） |

### 3.3 运行时钩子 / 模式（5 个）——订阅事件、维护开关状态

| 模块 | 订阅/维护 | 说明 |
| --- | --- | --- |
| mood（domain/behavior/） | `response_done` | 情绪分析：回复完成事件 → 专家回答情绪（开心/兴奋/好奇…），前端表情随回答变化 |
| robot（transport/） | `plugin_toggled` | 机器人模式：全屏机器脸 + 纯语音对话；停用 → 入口隐藏 |
| team（domain/experts/） | `plugin_toggled` | 智能体团队：companion + researcher 子 Agent，LLM 自动路由；停用退化为单 Agent |
| voice-input（transport/） | `plugin_toggled` | 浏览器语音输入开关（Web Speech API）：开=显示麦克风按钮 |
| memory-mem0（domain/memory/） | `settings`（配置） | 外部记忆 provider（Mem0）：对话级语义提取 + 向量检索；与 service-memory 互斥，一行切换 |

### 3.4 专家库模板资产（2 个）——子 Agent 定义（随 team 模块启停联动）

| 模块 | 说明 |
| --- | --- |
| agent-companion | 陪伴专家子 Agent（糯米人设，日常对话/记忆/工具） |
| agent-researcher | 调研专员（知识库/网页/MCP 工具集，事实类问题） |


## 4. 技能清单（skills/，10 个）

> 每份 `skills/<name>/SKILL.md` 有 frontmatter（name/description/when_to_use）+ 正文。技能区**全量注入 system prompt**（`collect_skill_catalog`），`skill_doc` 工具按需读正文；不随插件/模块启停过滤。

| 技能 | 描述（目录注入用） |
| --- | --- |
| datetime | 获取当前日期、时间、星期、计算 N 天后日期 |
| fs | 工作区文件：读写、列目录、搜索文件（只在工作区内操作） |
| knowledge | 语义检索知识库资料（RAG），查项目文档/资料 |
| mcp-notes | 便签管理（本地 MCP server）：添加/查询便签 |
| memory | 读写对用户的长期记忆；底层 provider 可切换（内置纯本地 / Mem0 等外部） |
| memory-mem0 | 外部记忆 provider（Mem0）；与内置 service-memory 互斥 |
| pyfunc | 计算器与代码执行（外部插件 adapter 示例） |
| shell | Shell 执行：bash 命令与沙箱模式（read-only / workspace-write / full-access） |
| voice | 语音能力：TTS 合成音频播放 + 语音转写 |
| web | Web 抓取：读取网页正文文本 |

## 5. 概念同步口径（写代码 / 文档 / 文案时）

- ❌ 不再使用："一切皆插件"、"程序插件/能力插件/服务插件"、"内置插件"（改叫"模块"）、`kind` / `type` 分类、**"伙伴/partner"**（改"专家"）。
- ✅ 统一用词：**专家**（experts/，人格+能力模板资产）、**插件**（plugins/，可选能力）、**模块**（领域根，内核组成部分）、**技能**（skills/，独立文档资产）。
- 四层架构：`transport → domain → infrastructure/storage`，依赖只允许向内（`make check` 首步 `layers` 机器阻断）；机制语言（Fiber/Scope/Registry/Composer）已下沉 `infrastructure/engine/`，不再出现在领域/接口命名。
- 前端插件管理页只展示外部插件（`builtin=false`）；模块在 API 中带 `category: "module"` 供前端区分。
- 历史演进文档（README 的 Phase 记录、AGENT.md 旧小节）保留原话作为演进证据，不再修改；当前架构描述一律按本文件口径。
