# Octop 对齐调研：数据结构 + 插件/技能/MCP 生态复用

> 2026-10-03。目的：①聊天/专家数据结构与 Octop 对齐；②评估 Octop 插件、技能、MCP 能否被 nuomi 直接复用。参照代码：`Octop/src/octop/`（backend）+ `Octop/dashboard/src/`（前端）。

---

## 1. Octop 数据模型（DB：SQLite，repos 层）

### 1.1 agents 表（AgentRow）
| 字段 | 说明 |
|---|---|
| `id` / `agent_id` | 自增 id / 对外唯一 key（uuid） |
| `user_id` | 属主（单用户可空） |
| `name` / `description` | 名称 / 描述 |
| `persona_mbti` | 人格 MBTI 标签 |
| `default_model` | 默认模型 |
| `system_prompt` | 系统提示词 |
| `enabled` | 启停（0/1） |
| `config_json` | 运行时配置 JSON（含 max_iters/max_input_length/temperature/top_p/max_tokens） |
| `last_state` / `last_error` | 运行状态 / 上次错误（start/stop/reload 状态机） |
| `icon` / `icon_name` / `icon_url` / `color` | 头像与主题色 |
| `template_name` | 来源模板（bundled expert） |
| `is_shared` | 是否共享 |
| `skill_package_ids` | 绑定的技能包 id 列表（JSON） |
| `knowledge_base_ids` | 绑定的知识库 id 列表（JSON） |
| `mcp_servers` | 绑定的 MCP server 列表（JSON） |
| `welcome_message` | 欢迎语 |
| `published_expert_id` | 发布为市场专家的 id |
| `kind` | `expert`（默认）/ 其它 |
| `created_at` / `updated_at` | 时间戳 |

### 1.2 threads 表（ThreadRow）
| 字段 | 说明 |
|---|---|
| `id` / `thread_id` | 自增 / 对外 key |
| `agent_id` / `user_id` | 归属 Agent + 用户 |
| `channel_type` / `session_key` | **通道维度**：web / terminal / bridge 等；session_key 是通道内会话标识 |
| `title` | 会话标题 |
| `last_active` / `created_at` | 活跃/创建时间 |
| `pinned` | 置顶 |
| `model_ref` / `reasoning_mode` / `reasoning_effort` | 会话级模型与推理设置 |
| `conversation_mode` | 会话模式 |
| `pending_plan_path` / `hitl_policy` | 计划 / 人工介入策略 |
| `artifacts` | 产物列表（tuple） |

### 1.3 sessions 表（SessionRow）
通道会话（聊天会话与 thread 解耦）：`session_key` / `agent_id` / `channel_type` / `chat_type` / `thread_id` / `channel_subject_id` / `channel_metadata` / `unread_count` / `updated_at`。

### 1.4 thread_messages 表（ThreadMessageRow）
`seq` / `message_id` / `role` / `message_json`（整条消息 JSON 序列化）/ `created_at`；另有一张运行状态表（`pending/queued/running/failed` 计数 + error）。

> 模式要点：**thread 是"一次对话"的业务对象（标题/置顶/模型/模式），session 是"通道入口"（web/terminal/bridge），message 是 JSON blob**。三者解耦，为多通道（Web/终端/浏览器桥/团队）服务。nuomi 目前只有 thread + message（texts JSON），无 channel 维度。

---

## 2. nuomi vs Octop 差异对照

| 维度 | Octop | nuomi（现状） | 差异 |
|---|---|---|---|
| Agent 存储 | SQLite agents 表（30+ 字段） | workspace/agents.json（id/name/display_name/expert/desc/icon/color/status） | 字段少、非 DB；缺 runtime 配置/技能包/知识库/MCP 绑定/模板来源 |
| Thread | thread_id + agent_id + channel + session_key + model_ref 等 | id + title + agent + project_id + created_at | 缺 channel/session/会话级模型配置；**有 project_id（项目概念，Octop 无）** |
| Session | 独立表（通道会话） | 无 | 无通道概念 |
| Message | role + message_json（blob）+ 状态机 | texts JSON（自定义） | 结构不同，需对齐为 role+blob |
| 项目/存储 | 无（workspace 目录即存储单元） | projects 表 + workspace 目录 | **nuomi 特有**：thread 关联 project（文件树归属） |
| Agent 状态机 | last_state + enabled + 失败置 error | status: running/stopped + current | 语义已对齐（v0.12 I 系列），存储位置不同 |

---

## 3. 插件 / 技能 / MCP 复用可行性

### 3.1 插件（Octop）
- **形态**：目录 = `plugin.yaml`（id/version/name/description/icon/group/kind/entry + ui）+ `main.py` + `icon.svg` + `ui/`（前端 renderer：index.js + manifest.json）。安装到 `~/.octop/plugins/`。
- **运行时**：`main.py` 内 `from octop_harness.plugins import PluginContext`——**依赖独立的 pip 包 `octop-harness`**（Agent harness 提供 ctx.tool 注册、工具执行等）。
- **UI**：工具返回 `{"octop_ui": {"renderer": "xxx_card", ...}, "data": ..., "text": ...}`，由 dashboard 的 renderer 渲染。
- **能否直接复用**：
  - ✅ **工具类插件（kind: tool，无 ui/）**：可复用。nuomi 引入 `octop-harness`（pip）或实现兼容 PluginContext 即可直接跑 Octop 的 `main.py`。
  - ⚠️ **带 UI 的插件**：需 nuomi 前端实现 octop_ui renderer 协议（工作量中等，可先跳过）。
  - nuomi 现有插件 manifest 是 `plugin.json`（自研格式）——**格式不兼容**，但概念一致（都是"目录 + 元数据 + 入口 + 工具注册"），迁移成本低。

### 3.2 技能（Octop）
- **形态**：`SKILL.md` frontmatter（name/description/metadata.octop: emoji/label/summary）+ 正文；发现 = 工作区目录扫描（symlink-tolerant）+ 内置技能目录 + SkillHub 市场。
- **与 nuomi 技能格式**：nuomi 技能也是 `SKILL.md` frontmatter（trigger/description/正文）——**格式高度兼容**。
- **能否直接复用**：✅ 基本可以直接复用——把 Octop 技能目录/技能包解包到 nuomi 技能根目录即可；nuomi 的 composer 注入机制可原样消费。差异只在 frontmatter 的 metadata 键（octop: 前缀），nuomi 可忽略或映射。
- **技能包（skill package）**：Octop 有 zip/集合安装 + SkillHub 市场（skillhub.cn）——nuomi 可先复用"目录技能"，技能包后续再说。

### 3.3 MCP / 连接器（Octop）
- **形态**：ConnectorRow = instance_id / kind / display_name / status / mcp_server_name / credential_blob / config_json；接入用 `langchain-mcp-adapters`；有 catalog（默认连接器市场）+ custom MCP（用户自定义 stdio/HTTP）+ OAuth。
- **与 nuomi 现状**：nuomi 已有 `mcp-notes` 连接器，**同样走 langchain-mcp-adapters**——技术栈一致。
- **能否直接复用**：✅ 连接器**配置格式**（kind + mcp_server_name + config_json）可直接对齐；Octop 的 catalog 连接器定义（名称/描述/type/services）可复用为 nuomi 连接器市场数据。

---

## 4. 对齐方案建议（按优先级分块）

### P-A：数据结构对齐（让界面可以"直接一样"）
1. **Agent 落库 + 字段对齐**：agents.json → SQLite agents 表，字段对齐 Octop（name/description/default_model/system_prompt/enabled/config_json/last_state/icon/color/template_name/skill_package_ids/knowledge_base_ids/mcp_servers/welcome_message/kind）。保留 nuomi 的 expert 引用。
2. **Thread 对齐**：thread 表加 channel_type/session_key/pinned/model_ref/created_at；**project_id 保留**（nuomi 特有，文件树归属用；Octop 的 workspace 语义映射到 project）。
3. **Message 对齐**：改为 role + message_json blob + 状态机（pending/queued/running/failed）。
4. **Session 表**：可选，先不建（单通道桌面客户端），为将来多通道留接口。

### P-B：生态复用
5. **技能**：直接复用 Octop 技能目录格式（SKILL.md），把 Octop 内置技能（skill-manager 等）拷入 nuomi skills/ 验证注入。
6. **插件**：引入 `octop-harness` 运行时或实现 PluginContext 兼容层 → 直接加载 Octop 插件目录（`plugins/bundled/*` 拷入或 pip 安装）；UI renderer 第二阶段。
7. **MCP**：连接器字段对齐 Octop catalog 格式，保留 langchain-mcp-adapters 接入。

### P-C：界面
8. 数据结构对齐后，专家页/聊天页按 Octop 字段渲染（default_model/status/welcome_message/mcp_servers 等已有数据可用）。

---

## 5. 工作量与风险

| 项 | 工作量 | 风险 |
|---|---|---|
| Agent 落库+字段 | M | agents.json 迁移（现有数据）；status 语义保持 |
| Thread 字段对齐 | S | 加列即可，project_id 兼容 |
| Message blob 化 | M | 历史消息迁移（texts JSON → role+blob） |
| 技能复用 | S | 低，格式兼容 |
| 插件复用（harness 兼容层） | L | octop-harness 依赖注入方式需摸清（harness 是 Octop 的独立运行时包，可能较重） |
| MCP 字段对齐 | S | 低 |

> 待确认：插件复用走"装 octop-harness pip 包"还是"自研兼容 PluginContext"——取决于 octop-harness 是否独立可 pip install、nuomi 运行时是否愿意承担该依赖。技能先做，收益最直接。
