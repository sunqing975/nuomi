# nuomi v0.13 架构重构：octop-harness 为机制基础库，nuomi 只写业务层

> 2026-10-03。用户决策：基础设施直接用 octop-harness（Octop 的 Agent 运行时），彻底重构架构，业务层代码向 Octop 靠拢。
> 验证基线：`scripts/probe_harness.py` 全通过（harness 独立运行 ✓ DeepSeek 对话 ✓ Octop 插件 what-to-eat 直接加载 ✓）。

---

## 1. 目标架构

```
transport（协议，薄）          FastAPI 路由：agents / threads / messages / plugins / skills / connectors / knowledge
      ↓
domain（业务层，向 Octop 靠拢） 领域服务：Agent 生命周期 / 会话 / 能力 / 技能 / 连接器 —— 只表达领域语义
      ↓
infra/harness（适配层，唯一接触 harness）  HarnessAgentManager 生命周期、配置映射、流式桥、插件/技能/MCP 装配
      ↓
octop-harness（外部基础库，PyPI）           Agent 循环 / 工具 / 记忆 / checkpointer / 技能 / MCP / 子代理 / 观测
      ↓
storage（SQLite）               agents / threads / sessions / messages 表（对齐 Octop schema）
```

- **harness = 机制基础库**（大厂把机制语言当基础库）：nuomi 不再自研 composer/fiber/工具流水线/记忆。
- **domain + transport = 领域控制面**（领域语言一等公民）：专家/Agent/插件/技能/连接器语义保留，字段与 Octop 对齐。
- 依赖规则沿用 v0.8：`transport → domain → infra/harness → octop-harness`；`domain` 禁 import `transport`；`infra` 禁 import `domain/transport`。

## 2. 新目录结构（backend/app）

```
app/
  main.py                    # 装配：DB → harness 适配层 → domain → transport
  transport/
    api.py                   # 路由注册（agents/threads/chat/plugins/skills/connectors/knowledge/experts）
  domain/
    agents/                  # Agent 领域：创建/启动/停止/编辑/删除（对齐 Octop agents.py 语义）
    threads/                 # 会话领域：thread + message（对齐 Octop threads 表）
    capabilities/            # 插件/技能/连接器/知识库领域服务
  infra/
    harness/
      manager.py             # HarnessAgentManager 单例 + Agent 生命周期（启动/停止/重建）
      config.py              # .env + 专家 manifest → HarnessAgentConfig
      chat.py                # ChatRequest 流式 → SSE 事件（token/tool/usage/error）
      plugins.py             # 插件目录加载/启停（harness PluginRegistry）
      skills.py              # 技能目录/禁用集
      mcp.py                 # MCP server 配置 → mcp_server_configs
      memory.py              # 记忆后端（octop-memory）装配
    storage/                 # SQLite repos（agents/threads/messages，对齐 Octop schema）
```

## 3. 数据模型对齐（Octop schema）

| nuomi 现状 | 目标（Octop） | 说明 |
|---|---|---|
| agents.json（8 字段） | SQLite `agents` 表（30+ 字段） | agent_id/name/description/default_model/system_prompt/enabled/last_state/config_json/icon/color/template_name/welcome_message/kind；保留 expert 引用 |
| threads（id/title/agent/project_id） | threads + agent_id + channel_type/session_key/pinned/model_ref/reasoning_effort | project_id 保留（文件树归属）；channel_type 先固定 `web` |
| messages（texts JSON） | role + message_json blob + 状态机 | 历史消息迁移脚本 |
| 无 session 表 | sessions 表 | 可选，单通道先不建 |
| 会话存储（SQLite 自研） | harness checkpointer（thread_id） | 会话内容归 harness，threads 表只存元数据 |

## 4. 系统插件迁移评估（21 个插件）

| 现有插件 | 去向 |
|---|---|
| service-tools / service-agent-loop / service-sessions / service-system-prompt / service-memory | **harness 原生能力替代，删除**（工具注册、Agent 循环、checkpointer、系统提示词组装、记忆全在 harness） |
| fs / shell / web / pyfunc / datetime / voice 等能力插件 | 重写为 harness 插件（plugin.yaml + main.py，PluginContext 注册）或复用 Octop 同名插件 |
| mcp-notes（连接器） | 保留，走 harness MCP 配置 |
| agent-companion（人设） | 映射为 persona/AGENTS.md 注入 |

## 5. 迁移顺序（阶段化，每阶段可验证）

- **M1 依赖与工作区**：harness 入 pyproject（已装验证）；工作区按 `init_workspace` 布局（skills/_builtin_skills/AGENTS.md/checkpoints.sqlite）。
- **M2 配置映射**：`.env`（providers/models/api_key）→ `HarnessAgentConfig`；模型目录（deepseek-chat 等）。
- **M3 Agent 生命周期**：`infra/harness/manager.py` + agents 表对齐；transport agents 路由对齐 Octop（GET/POST/PATCH/DELETE + start/stop/reload/status）。
- **M4 会话通道**：threads/messages 表对齐 + `chat.py` 流式桥（ChatRequest → SSE token/tool/usage）；旧会话数据迁移。
- **M5 插件迁移**：插件目录 → harness plugin.yaml 格式；删除 5 个 service-* 系统插件；能力插件逐个重写。
- **M6 技能/MCP/知识库**：skills_dir 接入；MCP mcp_server_configs；知识库检索工具接入。
- **M7 前端对齐**：Agent/thread 字段（default_model/status/welcome_message/pinned 等）→ 专家页/聊天页。
- **M8 全量验证 + 文档**：make check（layers/lint/typecheck/test）+ 浏览器冒烟；AGENT.md 记录。

## 6. 风险与保留

- **会话数据迁移**：旧 thread/message 结构 → 新 schema（迁移脚本，可回滚）。
- **专家模板**：`experts/<name>/manifest` 需映射到 harness persona 约定（AGENTS.md/system_prompt）。
- **harness 1.0.0 刚发布**：接口以 installed 版本为准（`pip freeze` 锁定）。
- **保留**：领域语言（专家/Agent/能力/技能/连接器）、项目（存储单元）/project_id、豆包生态接入、中文文案、依赖规则。
- **前端**：现有 antd 页面保留，字段消费对齐后即"界面直接一样"。
