# Nuomi 交接文档（HANDOVER）

> 最后更新：2026-10-05 · 分支 main · HEAD `d7a7c45`（M3/M4 已落地）
> 本文件面向「下一个接手的人」：先读它，再读代码。已实现的细节以代码为准（`git show <commit>` 可查）。
> ⚠ 2026-10-05 命名变更：API 前缀已从 `/api/pet/*` 全量改名为 `/api/avatar/*`（模型/动作/表情/预览/开关），插件 `vrm-pet`→`vrm-avatar`、`shells/myspy`→`shells/nuomi-avatar`；产品概念「桌宠」→「AI 数字人」。本文 §4 历史条目保留旧名，新链路均用新名。
> ⚠ 2026-10-05 M4：会话列表权威已从 `nuomi-state.json` 的 `threads` 数组迁至 SQLite `threads` 表（见 §2/§4）；state 文件仅存 `thread_id`（+ `agent_id`，AI 数字人绑定消费）。

---

## 0. 一句话定位

**Nuomi = AI 大脑（backend，基于 octop-harness）+ 通用控制台（frontend，React + antd）+ 可插拔表现层（shells/nuomi-avatar AI 数字人壳）。**
表现层只消费标准化 SSE 协议（v3：**octop 原生事件帧**）；能力（专家/插件/技能/连接器/技能包）由后端统一管理，控制台统一呈现。产品命名：连接器（底层 MCP 协议）；内部领域语言对齐 octop：Expert / Plugin / Skill / MCP / Workspace。

## 1. 架构与目录

```
nuomi/
├── backend/          # AI 大脑（uv 管理，python3.12，.venv）
│   ├── app/transport/   # api.py（/api/*）+ openai_compat.py（OpenAI 兼容）
│   ├── app/domain/      # 领域核心：agents / plugins / skills / skillpackages / chat / pet
│   ├── app/infra/       # harness 适配 + skillhub.py（SkillHub 客户端）+ pet_events.py（动作广播）
│   ├── app/storage/db.py# SQLite（agents/plugins/agent_plugins/skills/skill_packages*）
│   └── app/config.py    # env 配置（Settings）
├── frontend/          # 控制台：Vite + React + antd（dist 不入 git，后端挂 /console）
├── shells/nuomi-avatar/      # 表现层壳（Electron + Live2D，纯表现层：动作/表情播放，无输入/字幕）
└── docs/              # avatar-protocol.md（v3 协议）等
```

**依赖规则**：`transport → domain → infra → 基础设施（octop-harness + SQLite）`，domain 不 import transport。

## 2. 核心概念

| 概念 | 关键约束 |
|---|---|
| 专家 Expert | 有名字/人格/系统提示词的 AI 角色，可启停；**不绑定插件**（2026-10-04 解耦） |
| 插件 Plugin | `plugin.yaml` + `main.py`（`ctx.tool(...)` 注册）给 LLM 的工具集；**全局启停**（启用即对所有专家可用，无专家绑定）；**模型对应插件只读不可启停**（模型 1:1 对应插件，互斥切换） |
| 技能 Skill | SKILL.md（frontmatter + 提示词），随 harness 注入；目录 `工作区/skills/<slug>/`；**per-turn 可白名单选择**（对话请求 skills 字段） |
| 技能包 Skill Package | SkillHub 技能集的本地安装（一包多技能，`skill_packages/<id>/skills/<slug>/`）；**包级整体启停/删除**（禁用=不注入）；**不做版本更新**；包内技能随包注入，per-turn 同样可被 skills 白名单命中（slug） |
| 连接器 | 外部工具服务（MCP 协议，stdio/sse/http），`NUOMI_CONNECTORS` 种子 + `connectors.json` 权威；**per-turn 可指定挂载**（对话请求 connectors 字段；不传=默认全挂，空=不挂） |
| 大模型 Provider | LLM 服务配置（OpenAI 兼容；base_url/api_key/模型列表），`工作区/providers.json` 权威（运行时），.env `LLM_*` 仅种子回退；**设置页「大模型」多 Provider 管理**；模型不绑专家（2026-10-04），**对话框 per-turn 选择**（请求 model 字段） |
| AI 数字人模型 Model | 表现层资产（Live2D，**工作区 `models/2D/<id>/`**，2026-10-04 迁出壳仓库；仓库仅留可分发种子 `assets/models/2D/hiyori`，扫描时幂等播种）；选中模型 = 激活对应插件（互斥）；**与会话解耦**（2026-10-04 起切模型不换会话）。**AI 数字人开关联动**（控制台「AI 数字人」页开关 → `/pet/status` → 壳 config `ui.avatar_enabled`）：关闭 → 停用全部模型插件（LLM 工具集不再有动作工具）；开启 → 恢复激活当前选中模型的插件；**AI 数字人关闭时切模型仅换形象不激活插件** |
| 动作播放链 | 对话触发模型插件工具（动作/表情）→ 后端事件总线（`/api/avatar/events` SSE）→ 壳常驻订阅播放（断线 3s 重连） |
| 表现层协议 | v3 octop 事件帧（token/tool_call_chunk/tool_result/usage/done，带 node+thread_id）；**无 emotion 事件** |

**已废除**：nuomi-avatar 自带大脑（plugin-manager/mcp-manager/diary-manager/llm-client/MoodChatModule）、emotion 事件机制、pet_action/pet_emotion 插件、LSS/Roxy/baimeimo 模型。

## 3. 启动手册

> **2026-10-05 起：`make start` 一条命令即可**——壳启动时自动检测后端（`/api/health`），未就绪则 spawn uvicorn（cwd=backend，仓库根 .env 自动读入；最多等 30s；后端退出壳后保持常驻，下次启动复用）。以下旧流程仍可用（手动起后端再起壳，壳检测到就绪不会重复拉起）。

```bash
# 1) 后端（必须先杀旧进程，否则新代码不生效）
pkill -9 -f "uvicorn app.main:app" || true
cd backend && nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/nuomi-backend.log 2>&1 &

# 2) 前端（改了 frontend/src 后必须重新构建；dist 不入 git）
cd frontend && npm run build     # vite base=/console/，产物 dist/

# 3) 壳（AI 数字人 + 控制面板窗口，面板自动指到 /console/）
kill $(ps aux | grep "nuomi-avatar/node_modules/electron" | grep -v grep | awk '{print $2}') 2>/dev/null || true
cd shells/nuomi-avatar && npm start
```

访问：控制台 `http://127.0.0.1:8000/console/`；开发态前端 `cd frontend && npm run dev`（5173 代理 /api）。

环境：
- Python：uv 管理（`.venv/bin/python`，无 pip）；Node：frontend/ 与 shells/nuomi-avatar/ 各自 npm install
- 工作区与数据根 **同一目录 `/Users/superman/Nuomi`**（2026-10-04 起单根设计；.env 设 `NUOMI_HOME=/Users/superman/Nuomi`，**无 NUOMI_WORKSPACE**，workspace=数据根）；内含 agents/plugins/{weather, aidang, cat, hiyori}/skills + models/2D + nuomi.db + memory.sqlite + nuomi-state.json
- 会话权威：SQLite `threads` 表（thread_id/agent_id/title/last_active/pinned/model_ref，2026-10-05 M4 落库）+ `nuomi-state.json` 仅存 current `thread_id`（+ `agent_id`，AI 数字人绑定消费；2026-10-04 起迁出壳 config）；消息权威 = 各专家 workspace 的 memory.sqlite（octop checkpointer），`thread_messages` 表为历史投影（首次读历史 backfill → ready，之后每轮对话增量 append）；壳 `shells/nuomi-avatar/config.json` 仅存表现层偏好（ui.model/ui.model_path，后端写、壳 watch 重载，无绝对业务状态）
- .env 在仓库根，改后必须重启 uvicorn

## 4. API 清单（全部 /api 前缀，见 app/transport/api.py）

> **本机访问守卫（2026-10-06 新增，`app/infra/local_guard.py`）**：所有请求校验 `Host`
> 白名单（`127.0.0.1`/`localhost`/`::1`，挡 DNS rebinding）；带 `Origin` 时必须是本机来源
> （`file://` 壳的 `Origin: null` 放行）；`/api/*` 的 **POST/PUT/PATCH/DELETE 必须带
> `X-Nuomi-Token`**（或 `Authorization: Bearer <token>`），token 每进程随机生成、可用
> `NUOMI_API_TOKEN` 覆盖，同源 `GET /api/session-token` 获取（该端点连 `null` origin 也拒绝）。
> 控制台（`api.ts`）与数字人壳（`main.js` IPC → `app.js`）均已自动携带并在 403 时刷新重试。
> 插件加载已改为 `install_deps=False`（不再让插件隐式 `pip install`）。
>
> **2026-10-06 第 1 周变更**：①对话 SSE 异常时补发 `{"type":"error","message":...}` 终止帧
> （断连会 `aclose` 上游，不再让模型跑完白烧 token）；②`GET|PUT /settings/env` 对疑似密钥
> 的键名**脱敏返回**（`sk-2***fa1e`），PUT 收到含 `***` 的值按「保持原值」处理（与 providers
> 同语义）；③providers/env/langfuse/connectors 四个明文密钥文件改为**原子写 + 0600**
> （`app/infra/secret_file.py`）；④长阻塞操作（git 导入 / FBX 转换 / SkillHub / Provider 探测 /
> Langfuse 校验 / zip 解包 / 知识库文件 IO）全部 `asyncio.to_thread`；⑤`manager.close()` 不再
> 清空 Langfuse（生命周期改用 `manager.shutdown()`，仅 lifespan 收尾调用）。

**对话/会话**：`POST /agents/{id}/chat`（SSE，octop 帧，body `{messages, thread_id, skills?, connectors?, knowledge_base_ids?, model?}`——skills: None=全量技能 / [] / [name|slug...] 白名单（含内置技能与已启用技能包内技能，非法名 400）；connectors: None=默认挂载 / [] / [name...] 只挂载；knowledge_base_ids: None/[]=本轮不注入 / [ids...]=只检索这些库（未知 id 400）；model 非法 400；消息必填 min_length=1+strip 校验 422）· `GET /agents/{id}/chat/history`（M4：thread_messages 投影 ready → 读表分页（limit/offset，不依赖 harness 运行时）；pending → checkpointer 读取 + 全量 backfill 投影 + 标记 ready；返回有序 Segment[]）· `GET /chat/state` · `POST /chat/new|switch|touch` · `DELETE /chat/threads/{tid}`（删会话：threads 行 + 消息投影 + projection 状态 + 检查点历史级联）

**专家/插件**：`GET|POST /agents` · `GET|PATCH|DELETE /agents/{id}` · `POST /agents/{id}/start|stop|status` · `GET /plugins` · `POST /plugins/sync` · `POST /plugins/import`（zip）· `POST /plugins/import-git`（git 仓库）· `PATCH /plugins/{id}`（启停）· `DELETE /plugins/{id}`（模型插件 400 拒绝，由AI 数字人删除级联）。**已废除**：`GET|PUT /agents/{id}/plugins`（专家-插件绑定，2026-10-04 解耦删除）

**技能/技能包**：`GET /skills` · `GET /skills/builtin`（内置只读）· `GET|PATCH|DELETE /skills/{name}` · `POST /skills/import`（zip）· `POST /skills/import-git`（git 仓库）· `POST /skills/install`（SkillHub 单技能，requires_api_key 标注）· `GET /skillhub/search|rankings|skillsets{?q,/{slug}}`（search 循环翻页一次 50） · `GET /settings/env` · `PUT /settings/env`（应用设置环境变量，{workspace}/env.json → os.environ，技能/连接器 API key 在此配置）· `GET|PUT /settings/providers` · `POST /settings/providers/probe`（PUT：api_key 含 *** 视为未修改保持原值——防脱敏串回写覆盖真实 key；**Provider 必须有 key**：新增必填（前端）+ 保持原值后仍空 → 400（后端）；build_providers 原样传 key，无占位逻辑）（大模型 Provider，存 {workspace}/providers.json；PUT 整体保存：api_key 空串=保持原值、释放实例；GET 脱敏；校验 id 唯一/base_url/模型非空 → 400；模型不绑专家，不校验专家字段）· `GET|POST /skill-packages` · `POST /skill-packages/from-skillhub` · `PATCH|DELETE /skill-packages/{id}`

**其他**：`GET|POST /connectors` · `PUT|DELETE /connectors/{name}`（控制台增删改，connectors.json 持久化，变更下次对话生效）· `GET /workspace` · `GET /pet/models` · `POST /pet/models/switch` · `DELETE /pet/models/{id}`（级联删插件+资产，**不换会话**）· `GET|PUT /pet/status`（AI 数字人开关：读写壳 config.json `ui.avatar_enabled`，壳 watch 后创建/销毁AI 数字人窗口；**联动模型插件**：关闭→停用全部模型插件，开启→恢复激活当前选中模型的插件；AI 数字人关闭时切模型仅换形象不激活插件；释放 shell agent 下次对话重建）

**知识库（M6，2026-10-04）**：`GET /knowledge/capability`（嵌入服务状态：enabled/model/ready/downloaded/local_models/presets_meta/max_bases=20/ocr_enabled=false/downloading）· `PUT /knowledge/feature`（启停/模型切换；模型未下载 400；模型变更触发全量重索引）· `POST /knowledge/onnx-download`（异步任务式下载，轮询 capability 直到就绪；重复下载幂等）· `DELETE /knowledge/onnx-model?model=`（删除模型缓存）· `GET|POST /knowledge-bases` · `GET|PATCH|DELETE /knowledge-bases/{id}`（PATCH 支持 name/description/enabled/icon_name/max_documents；同名 409；enabled=库级启停，停用库对话侧不可选且显式指定 400）· `GET /knowledge-bases/{id}/documents?prefix=`（文件夹浏览）· `POST /knowledge-bases/{id}/folders` · `POST /knowledge-bases/{id}/documents`（FormData `file` 上传，图片 OCR 门禁 400）· `POST /knowledge-bases/{id}/documents/text`（新建 md/txt）· `GET /knowledge-bases/{id}/documents/{doc}/preview|file` · `GET|PUT .../content`（读/写 md·txt）· `POST .../rename|reindex` · `DELETE .../documents/{doc}`。索引为异步任务（并发 2），lifespan 启动时恢复 pending/processing 文档；知识库路由在 `app/transport/knowledge_api.py`。

OpenAI 兼容：`app/transport/openai_compat.py`（`/v1/chat/completions`，model 形如 `nuomi/agent:<id>`）。

## 5. 已验证链路（回归依据；细节以代码/实测为准）

插件链（weather 触发 tool_call→tool_result；zip/git 导入均实测）、技能链（frontmatter+启停；git 导入实测 anthropics/skills→template-skill）、连接器链（pet_mood，MCP 协议）、协议链（/chat octop 帧 56 帧无解析错误）、控制台链（各板块无 console 错误）、壳链（面板重试/订阅断线重连）、**SkillHub 链**（真实市场：search/rankings/skillsets、单技能安装、技能集建包 6 技能、包启停/删除、chat 注入均实测通过）、模型切换链（插件互斥+manager.release，**不换会话**，2026-10-04 起）、**AI 数字人开关链**（控制台「AI 数字人」页开关 → /pet/status → config watch → 窗口创建/销毁，启动时按开关决定是否创建；**插件联动实测**：关闭 → aidang/cat/hiyori 全 enabled=0，开启 → 当前模型插件 enabled=1 其余 0，AI 数字人关闭时切模型 → 插件保持全停且 `activated_plugin=null`，2026-10-04）、会话链（真实线程列表，无 default 合成）、**管理页卡片化链**（专家/技能（已安装+市场）/AI 数字人/插件/连接器五页统一卡片网格，浏览器实测同行严格等高：技能页 5 列 179px、AI 数字人 sm 2 列 306px，2026-10-04）、**专家-插件解耦链**（/agents/{id}/plugins 404；插件全局启停即对所有专家生效；weather 对话触发工具调用，2026-10-04）、**对话框能力选择链**（技能选择器三分组：已启用的技能/内置技能（/skills/builtin 24 项，可选）/已启用的技能包（/skill-packages，包级整包勾选=包内技能 slug 全进白名单）；选中→chip→对话携带 skills 白名单；后端 _available_skill_keys 补内置技能名（对齐 Octop catalog 含 builtin 层）；curl 实测 [apple-notes+therapy-board] 200、未知技能 400；weather 工具调用→消息气泡折叠步骤（tool_call args + tool_result content）→轨迹抽屉时间线，浏览器实测，2026-10-04）、**大模型配置链**（设置页「大模型」多 Provider CRUD：base_url/模型列表/API key 脱敏、api_key 留空保持、保存后释放实例，浏览器实测，2026-10-04）、**模型 per-turn 选择链**（agents 表 default_model 列删除（旧库 DROP COLUMN 迁移）；对话框「模型」Select 选中 DeepSeek 主服务 · deepseek-chat → 请求带 model → harness ChatRequest.model 覆盖；非法模型 400；不带 model 走默认，2026-10-04）。、**Provider 探测链**（新增 Provider 弹窗「探测模型」→ POST /settings/providers/probe → OpenAI 兼容 /models → 勾选列表默认选第一个回填，curl+浏览器实测，2026-10-04）、**输入框布局优化**（选择器独立一行、输入框 flex:1+autoSize，浏览器实测，2026-10-04）、**知识库链**（嵌入服务：多源竞速下载（hf-mirror 胜出）+ fastembed 推理 512 维；存储层：建库→上传→异步索引→就绪→语义检索（相关 0.7361 vs 无关 0.5311）→编辑重索引→删除三处清理→整库删除，probe 脚本实测；API：pytest 11 项全过（隔离 NUOMI_HOME + symlink 真实模型缓存）——建库/重复名 409/上传/新建文本/预览/编辑/重命名/下载/重索引/删除/删库/不支持类型 400/图片 OCR 门禁 400/404/超限 400/未知模型 400；前端知识库页浏览器实测（#knowledge 直达、状态条/KB 卡片/详情空态渲染正常，无默认打开开关）；**检索注入链**（search_knowledge 工具 + hint 中间件（无选中库时隐藏工具，Octop 同语义）+ 引用标记 `<!--octop-kb-citations:[...]-->`（citations.py 沿用 Octop 逐字）+ 跨库检索 retrieve.py（k=8/6000 字符预算）+ 显式指定才注入（default_open.py：None/[]=不注入，无默认打开一说，2026-10-04 用户拍板与技能/连接器同维度）+ 库级启停（knowledge_bases.enabled 列迁移；停用库不进检索工具描述/对话选择器，显式指定 400）+ 删除级联（repo.delete_base 同事务清 knowledge_documents 行 + rmtree 目录）+ 前端知识库页拆分独立路由页面：`#knowledge`（列表：新建/启停/删除/进入详情）+ `#knowledge/detail/<id>`（详情：文档管理/删除库/返回，App.tsx 二级 hash 解析；深链接直达、刷新保持、删除后自动回列表；loadDocs reqId 竞态保护 + 详情页 loadBase 兜底 404）；pytest 24 项全过 + ruff/mypy 干净；curl 实测：显式 ids → tool_call search_knowledge → tool_result 含完整引用标记 → 模型引用知识库回答；无 ids → 0 次工具调用 0 引用（不注入）；浏览器实测工具步骤展开渲染「📚 知识库引用」Tag（probe-kb-1791093093 · weekend.md）+ 对话框知识库选择器（弹层多选、chip、未选=不加载）+ 模型必选 + 消息必填（发送按钮禁用/后端 422）；刷新后历史消息不显示工具步骤（harness checkpointer 不存 tool_events，Octop 同设计）），2026-10-04）

**注意**：部分市场技能 SKILL.md 的 description 含裸 `: ` 导致 harness YAML 解析失败被跳过（如 superpowers-tdd）——与 Octop 行为一致，非 nuomi bug。

**2026-10-05 AI 数字人表现层（VRM）链路**（方案B 单共享插件 vrm-avatar，动态工具）：
- **模型热切换链**：前端切模型 → `POST /api/avatar/models/switch`（写 config.json ui.model + ui.model_path + `manager.release(shell_agent_id)`）→ 壳 main.js fs.watch → `send('switch-model')` → app.js **页面 reload**（400ms 后 `location.reload()`，渲染进程 initialize 重跑读新模型路径）→ 窗口不关、进程不重启，1-2s 换模型。双向切换（630926↔868274）实测通过（旧实现只 log「需重启」不生效，022f7c8 修复）
- **VRM 尺寸归一化链**：加载后 `Box3().setFromObject(vrm.scene)` 测原始高度 → `vrmGroup.scale` 统一到 1.4m + 脚底对齐 y=0（实测两模型 1.17m/1.68m → 均 1.4m，日志「尺寸归一化」；492a746）
- **表情根因链**：后端 `vrm_has_expression_data()` 解析 GLB blendShapeGroups binds / VRM1.0 morphTargetBinds → `list_models.expressions_have_data`；前端模型卡片无数据时显示警告并隐藏表情预览。three-vrm 实测语义：`_expressionMap` 键 = expressionName（'happy'）、`VRMExpression.name` = `VRMExpression_happy`（包装名），binds 空则 morph 权重 0 变化
- **动态工具计数链**：`list_all()` 对 vrm-avatar 启用时按当前动作/表情清单统计（do_action + set_expression = 2，有数据才各计 1）；`/api/plugins` 实测 vrm-avatar tools: 2（7abd166）
- **插件中文名**：DB plugins 表 vrm-avatar name「桌宠动作」→「AI 数字人动作」（与 plugin.yaml 一致；代码层桌宠残留 0）

## 6. 踩坑记录（再遇到不用重踩）

- **uvicorn 旧进程占 8000**：新代码不生效，必须先 pkill 再重启。
- **octop_harness 顶层不导出插件 API**：必须从 `octop_harness.plugins` 子包导入。
- **中文工具名被 DeepSeek API 拒**（工具名须 `^[a-zA-Z0-9_-]+$`）：service 层 slug 防御。
- **Vite base**：挂 /console 必须 `base: '/console/'`；验证新构建带 nonce query 强制刷新。
- **Settings alias 忘写**：报 `'Settings' object has no attribute 'mcp_servers'`，需 `validation_alias=AliasChoices(...)`。
- **连接器配置曾写死 .env**：控制台只读、改动需重启；2026-10-04 起控制台可增删改（connectors.json 权威 + manager.close 重载）。
- **模型资产不完整 = 假能力**：cat（hijiki）motion/ 缺失 → 切换报 Texture loading error；扫描已校验文件存在性，缺失能力如实显示 0 动作。
- **octop 插件"无绑定=默认可用"**：废弃插件必须连目录一起删（否则工具照样进 LLM 工具集）。
- **渲染进程错误看不见**：看 `/tmp/nuomi-avatar-shell.log` 的 `[renderer:N]` 行（main.js 已转发 console-message）。
- **新生成/删除插件必须重启后端**：工具装配来自进程内 PluginRegistry。
- **壳 saveConfig 覆盖 ui.model**：saveConfig 以磁盘最新为底，只覆盖 nuomi.*（否则切模型后跳回旧模型）。
- **切换模型后工具集不变**：`/pet/models/switch` 必须 `manager.release(agent_id)` 让下次对话重建。
- **AI 数字人关闭时切模型 `activated_plugin` 须如实返回 null**：插件实际未激活（保持全停），返回模型 id 会让前端误报「已激活插件」（2026-10-04 修复，f8e06d6）。
- **LLM 幻觉调用旧模型工具名**：曾用"模型专属会话（无旧历史）"根治；**2026-10-04 废除**（AI 数字人=纯表现层拦截工具调用，会话与模型解耦），幻觉风险由会话切换/清空兜底。
- **python websockets 连 octop 8088 WS 恒 403**：curl/aiohttp 可通；真切 WS 用 aiohttp。
- **VRM 模型可能根本没有表情数据**：VRoid 导出可去掉表情——blendShapeGroups 定义了名字但 binds 全空，setValue 后 mesh 纹丝不动。排查先看后端 `expressions_have_data`，别再花时间在无表情模型上调权重/时长（2026-10-05）。
- **VRM 模型间尺寸差异大**（导出单位/比例不同，实测 1.17m vs 1.68m）：加载后必须 Box3 测高归一化，否则切模型观感跳变（2026-10-05）。
- **壳 switch-model 不能只打日志**：渲染进程收到 IPC 后不重载 = 用户点切换"没反应"；最小可靠方案是 `location.reload()`（config 已由后端同步）而不是在渲染进程里重建 three 场景（TTS/交互联动复杂易漏）（2026-10-05）。
- **函数内 `from X import NAME` + 同函数 if 条件引用同一 NAME = UnboundLocalError**：Python 视函数内 import 为局部绑定；模块级导入或提到函数顶部（2026-10-05）。
- **市场技能 frontmatter 质量**：description 裸冒号 → harness 安全跳过（见 §5）。
- **antd5 grid 卡片等高**：grid List 渲染为 `.ant-row > div`（**无 `.ant-list-items`**，也无 `.ant-col` 类——列是原生 div + colStyle）；Row 默认 `align: top` 列不拉伸，必须 CSS `align-items: stretch`；`nuomi-grid` 类若挂在 List 容器上选择器写 `.nuomi-grid .ant-row`，若挂在 Row 自身（AI 数字人页）写 `.ant-row.nuomi-grid`——两形态都要覆盖（frontend/src/index.css `.nuomi-grid` 块已兼容）。
- **壳加载的是 build 产物**：控制面板指向 `http://127.0.0.1:8000/console/`（后端挂 dist），**不是** 5173 vite dev；改前端验证要走 build + 强制刷新（`?v=n` nonce），5173 的 vite proxy 未配置好也不影响壳。
- **StreamingResponse generator 内抛 HTTPException 不转 400**：fastapi 对 generator 内异常不会返回错误响应（连接直接中断）。**已由结构性保证覆盖（2026-10-06）**：流式端点统一走 `app/transport/streaming.py::stream_response`（校验在 gen 之前执行，HTTPException 正常转 400/404）；`tests/test_streaming_guard.py` 扫描锁定「transport 层禁止裸构造 StreamingResponse」「async def gen 内禁止 raise HTTPException」。per-turn 校验（skills/connectors/知识库/模型/运行时构造）一律放端点函数体、`async def gen()` 之前（2026-10-04）。
- **`sqlite3.Connection` 的 `with` 只提交，不关闭连接**：`with db.connect() as conn:` 看似规范，实际每次调用泄漏一个连接 + 一个 fd（全仓 50+ 处、服务整天常驻）。必须自己包 `@contextmanager`（提交/回滚/close），或用 `contextlib.closing`（2026-10-06）。
- **octop 记忆表名前缀按专家名推导、各专家不同**：引擎按 `ns = re.sub(r"[^a-z0-9_]", "_", namespace.lower())` 生成 `{ns}_atoms`，而 namespace = **专家名** → 糯米 `__`、工作狂 `___`、小通 · 通用助手 `_________`。硬编码 `___atoms` 只对一个专家成立。读表前先从 `sqlite_master` 推导前缀（2026-10-06）。
- **记忆引擎初始化过某个库后，外部连接再也写不进去**：`_init_schema()` 会建 FTS 触发器，触发器调用只注册在引擎连接上的 C 扩展 `hm_cjk_seg` → 裸 `sqlite3.connect()` 插入报 `no such function: hm_cjk_seg`。测试要造合成数据必须用**引擎没碰过的新工作区**（2026-10-06）。
- **`asyncio.wait_for` 不能包在 async generator 外面做超时**：超时取消会顺着生成器内的 `await q.get()` 抛进去把它终结掉（长连接直接断）。心跳/超时必须写进生成器**内部**的 `try/except TimeoutError`（2026-10-06）。
- **`messages_to_inputs` 要求真的 BaseMessage**：用 `type("M", (), {...})()` 之类的假对象会被它静默跳过（`message_to_dict` 抛异常被 `continue` 吃掉）→ 投影写 0 行，测试表现为"第二次读历史是空的"（2026-10-06）。
- **分页是按"消息"分页，不是按"片段"**：一条消息可展开成 reasoning + text + tool_call 多个片段，所以 `limit=4` 可能返回 5 个片段；断言要按"页是相邻连续块"来写，别拿 `full[-4:]` 比（2026-10-06）。
- **vitest 默认不处理 CSS**：`import css from './x.css?raw'` 返回空串（除非开 `test.css`）。要么开配置，要么把值放 TS 里（本项目 token 就是这么定的：唯一定义处 + 启动注入 CSS 变量，顺带消灭漂移）（2026-10-06）。
- **macOS 没有 `timeout` 命令**（coreutils 的 `gtimeout` 才有）：验证 SSE 心跳用 `curl --max-time`（2026-10-06）。
- **本会话在 DSH(Electron) 内，宿主会导出 `ELECTRON_RUN_AS_NODE=1`**：不剥离就 `npm start` 会让 Electron 退化成纯 Node 跑 main.js（`Cannot read properties of undefined (reading 'getAppPath')`）。跑壳/打包必须 strip 该变量；另外 DSH 内 Chromium 子进程沙箱可能起不来（`sandbox initialization failed`）导致 WebGL 失败（2026-10-06）。
- **改 `db.connect` 语义前先数调用点形态**：`grep` 出 50+ 处全是 `with ... as conn:`（无裸赋值、无跨调用持有）才敢把返回值从 Connection 换成 contextmanager（2026-10-06）。
- **per-turn 技能注入走 harness 原生**：`ChatRequest.skills`（None 全量 / [] 禁用全部 / 列表白名单，SkillFilterMiddleware 消费）+ `mcp_servers`/`mcp_use_default` 控制连接器挂载，无需自研过滤；nuomi 只做存在性校验（技能名须在「已启用工作区技能 + 内置技能 + 已启用技能包内技能」集合）。

## 7. 项目主线清单（用户需求 → 状态）

> 主线项按用户原始清单 + 实际扩展整理；✅=已完成并验证，⬜=未做/暂缓。状态以最新对话拍板为准。

| # | 主线项 | 状态 | 说明 / 落地点 |
|---|---|---|---|
| 1 | 插件市场 | ✅ | octop 无独立在线插件商店；市场闭环 = 内置随包 + SkillHub + zip/Git 导入（见 #4/#9） |
| 2 | 连接器添加 | ✅ | 控制台增删改/重载（MCP 协议，产品命名统一「连接器」）；`connectors.json` 权威 + `NUOMI_CONNECTORS` 首次播种 |
| 3 | 工作区单根化 + 数据迁移 | ✅ | `NUOMI_HOME=/Users/superman/Nuomi` 即数据根（**无 NUOMI_WORKSPACE**）；skills/plugins/skill_packages/models/connectors.json/env.json/nuomi-state.json 全部在内 |
| 4 | 插件导入 | ✅ | `POST /plugins/import`（zip）+ `POST /plugins/import-git`（Git 仓库，浅克隆/50MB/已存在拒绝） |
| 5 | 技能导入 | ✅ | `POST /skills/import`（zip）+ `POST /skills/import-git`；实测 anthropics/skills 真实仓库 |
| 6 | 对话框大改动（参考 octop） | ✅ | per-turn 能力注入（skills/connectors/knowledge_base_ids/model）+ 技能（三分组：启用/内置/技能包）/连接器/知识库选择器 + 模型必选 + 消息必填 + 能力 chips + 工具步骤折叠 + 轨迹抽屉（2026-10-04 完成，见 §8 遗留增强项） |
| 7 | AI 数字人模型导入 | ✅ | 种子机制：仓库仅留 `assets/models/2D/hiyori`，扫描幂等播种到工作区 `models/2D/`；内置模型页只读不可删 |
| 8 | AI 数字人模型升级（现太呆板） | ⬜ 暂缓 | 现为纯动作/表情表现层（Live2D）；升级方案未定 |
| 9 | 技能市场（SkillHub） | ✅ | search 循环翻页（服务端固定 10 条/页）+ slug 去重；rankings/skillsets；单技能安装/技能集建包；`requires_api_key` 标注 |
| 10 | 内置技能展示 + 环境变量 | ✅ | `GET /skills/builtin`（24 个，只读）+ `GET|PUT /settings/env`（env.json → os.environ，技能 API key 配置） |
| 11 | 会话与模型解耦 | ✅ | AI 数字人=纯表现层（拦截对话工具调用做动作）；切模型不换会话；default 线程已删；会话权威 `nuomi-state.json` |
| 12 | AI 数字人开关 | ✅ | 控制台「AI 数字人」页开关 → `GET\|PUT /pet/status` → 壳 config `ui.avatar_enabled` → watch 创建/销毁窗口；**联动模型插件**：关闭→停用全部、开启→恢复当前选中模型、关闭时切模型不激活（见 §4/§5，2026-10-04） |
| 13 | 管理页 UI 统一卡片化 | ✅ | 专家/技能（已安装+市场）/AI 数字人/插件/连接器五页统一等宽卡片网格 + 首字头像 + 角标 + 描述省略/tooltip + **同行严格等高**（§6 踩坑） |
| 14 | **本机安全基线** | ✅ | 纯 ASGI 守卫（Host/Origin 允许清单 + `X-Nuomi-Token` 保护全部写 `/api`；`/api/session-token` 拒 null Origin）+ 插件导入不隐式装依赖 + 密钥脱敏（词锚定匹配，`***` 只认精确掩码）+ 原子写 0600 |
| 15 | **质量门禁** | ✅ | `make check` = lint + format + typecheck + 后端测试 + 前端构建 + **前端测试** + 壳语法；CI 三作业（backend/frontend/shell），前端 job 已接 vitest |
| 16 | **可移植性（换台机器能跑）** | ✅ | `make start` 先构建前端（dist 不入库，否则壳面板白屏）；`.env` 路径修正为仓库根（`config.py` 只读根 `.env`）；补 LICENSE(MIT)；代码/配置里的个人绝对路径清零（`AGENTS.md`/`docs` 历史记录除外） |
| 17 | **记忆可视化** | ✅ | `/api/agents/{id}/memory*` + 控制台「记忆」页：断言/原话/来源会话/实体 + 人设文件查看编辑 + **软遗忘走引擎 API**（`deprecate_atom`，可审计）；表名前缀按专家名推导（**各专家不同**，见 §6） |
| 18 | **上传限流** | ✅ | 5 处裸 `file.read()` 统一走 `read_upload`（先看 `file.size`，再分块、超限立即 413）；上限按用途区分（zip 50MB / VRM 200MB / FBX 100MB / 文档 100MB）；实测 51MB → 413 |
| 19 | **前端测试基建 + 设计 token** | ✅ | vitest + jsdom（44 例：XSS 净化 13 / SSE 分帧 13 / 引用解析 5 / 片段合并 6 / token 结构 7）；token 唯一定义处 `frontend/src/theme.ts`（启动注入 CSS 变量，结构上不可漂移）；`DESIGN.md` 重写为**描述现实** |
| 20 | **打包与分发** | 🚫 明确不做 | electron-builder 链可用（产出 `Nuomi.app`、图标、单实例锁、CSP 均实测），但**产物不含后端、不能独立运行**；且用户 2026-10-06 拍板不分发 → 签名/公证/自动更新/首启向导一律不做，日常一律 `make start`（详见 §8.3） |

## 8. 遗留事项 / 下一步

> **状态台账**：✅=已完成并验证 / ⬜=待办 / ⏸=用户叫停 / 🚫=明确不做。
> **方向与优先级**见 `docs/next-steps.md`（三轴：架构/前端/产品）；本表是状态权威，与实现不一致时以实现为准并当场改这里。

### 8.1 本轮（2026-10-06）已完成

- [x] **第 0 步 · 安全与门禁加固**（`fe7c042`）：本机访问守卫（Host/Origin 允许清单 + 写 `/api` 需要 `X-Nuomi-Token`；null Origin 全局放行但 `/api/session-token` 拒绝）+ 插件导入不隐式装依赖 + 门禁从"装饰"变真（修掉当时 HEAD 上的 ruff 10 / format 15 文件 / mypy 2 / pytest 2）
- [x] **第 1 周 · 正确性与体验**（`1a08c33` `2a98759`）：工具调用投影补全（TOOL_RESULT 与流结束各归档一次）+ `start_agent` 接运行时入口 + **插件注册竞态**（`to_thread(sync)` 与 `load_all()` 的 `registry.clear()` 相撞，实测出现零工具轮次）+ 阻塞调用 offload + SSE 终止契约（`aclosing` + error 帧）；前端流式可中止/重试条/IME 组合态/DOMPurify 净化 + 壳交互与控制面板生命周期
- [x] **密钥脱敏 + Langfuse 生命周期**（`7f51c9c`）：`is_secret_key` 词锚定（原先 `"***" in value` 会静默丢弃真实密钥、未锚定正则会误伤 `MONKEY`/`TOKENIZER_PATH`）、只有精确掩码才算"保持原值"、`secret_file` 原子写 0600、`HarnessManager.shutdown()` 不再清 `_langfuse`
- [x] **可移植性**（`9187a96`）：见 §7 #16
- [x] **壳打包链 + 安全基线**（`6ec8f2a`）：electron-builder/图标/单实例锁（**真双进程**验证）/CSP（探针实测远端脚本与 fetch 被拒）/导航封锁/模型路径自解析（配置路径失效时向后端取激活模型并回写，打包态 config 只读则用 `--nuomi-model` 下发）。⚠️ 产物不含后端 → 只在"后端已在跑"时可用
- [x] **记忆可视化 + 上传限流**（`8dd7fdf`）：见 §7 #17 #18
- [x] **分发范围决策**（`950d8d5`）：见 §8.3
- [x] **前端测试基建 + 7 项体验软点 + 设计 token**（`de72f9c` `32fad76`）：见 §7 #19。软点含：`STATUS_TAG` 无兜底（未知状态即白屏）+ 顶层 ErrorBoundary、流式片段索引 key、原地改 state、每个 token 都 `scrollTo`（用户无法上翻）、模型下载按钮永久 loading、多选上传 N 并发、编辑器静默失败+无请求守卫
- [x] **第二批审计修复**（`a309a7d`）：
  - **SQLite 连接从不关闭**（50+ 处 `with db.connect()` 每次漏一个 fd，服务整天常驻）→ `connect()` 改 `@contextmanager`（提交/回滚/close），调用点零改动；`knowledge/index.py` sidecar 同修。实测 200 次调用 fd 稳定
  - `_TOOL_OWNERS` 模块级全局 → 请求局部（并发对话会互相覆盖来源映射）
  - 工具装配：审计说 55ms/轮，**实测只有 5.6ms** → 不加缓存；改为修两处真浪费（`ensure_agent_runtime` 缓存命中时仍急切求值 `tools()`；`tools()`+`tool_owners()` 各查一次 `list_all()`）→ 省约 7.3ms/轮
  - 数字人事件队列满**静默丢最新** → 改丢最旧 + 计数 + 限频告警；SSE 长连接加 15s 心跳注释帧
  - 历史分页两条路径语义不一致（pending/backfill 忽略 offset 且投影为空时回落重算）→ 统一为倒序分页 + `limit/offset` 校验
  - 顺手：`sync()` 清理"目录已消失"的残留插件行（原只 INSERT OR IGNORE，手动删目录会留幽灵条目）
- [x] **模拟 MES 连接器（2026-10-07，制造业作品集起步）**：`scripts/gen_mes_data.py`（模拟 CNC 机加工 MES 库，90 天/异常注入/固定 seed 可复现）+ `connectors/mes_connector.py`（只读 MCP server，6 个只读工具，SQLite `mode=ro`，`MES_DB_PATH` 可切真实库）+ 登记 `数据根/connectors.json` 的 `mes` 连接器；SSE 对话端到端实测两场景（问数回答与连接器返回逐项核验一致；主动组合 5 工具做良率/设备/OEE 分析），详见 AGENT.md 对应节

### 8.2 仍待办（按"对单机日用的实际影响"排序）

| # | 事项 | 现状 / 为什么 | 落地要点 |
|---|---|---|---|
| 1 | 知识库 **OCR** | ⏸ 用户叫停（`ocr_enabled=false` 占位） | RapidOCR 本地 + 扫描 PDF；接 `knowledge/capability` |
| 2 | **深色主题入口** | token 覆盖层已备好（`THEME_OVERRIDES.dark`，核心键有测试保证），但没接切换 | 需同时把 `main.tsx` 的 antd `algorithm` 换 `darkAlgorithm`，否则 antd 组件仍浅色；加开关 + 持久化 |
| 3 | 装饰色板收敛 + 内联样式 | 剩 60 处裸 hex（4 处 antd `color=` prop、其余装饰标签色板）+ 278 处内联 `style` | 先收 `AVATAR_COLORS`（三份重复）到 `utils/palette.ts`，再逐页收；**别为清零做无验证的大重写** |
| 4 | 前端**渲染级**测试 | 无 `@testing-library/react`；组件行为（滚动跟随/攒批上传/折叠）只有纯函数单测兜 | 装 RTL + 给 Chat 上传/折叠、Memory 页写交互测试 |
| 5 | AI 数字人**直接说话（TTS）** | ⬜ 用户已拍板待办；TTS 客户端代码保留未删 | 恢复"收到回复文本 → TTS 播报"入口；注意当前是 Kokoro-FastAPI 路线 |
| 6 | 斜杠技能注入（`/slug`） | ⬜ 本轮用"工具条选择器 + chips" | octop 的 `/slug` 文本插入 |
| 7 | 专家级默认绑定 | ⬜ 对齐 octop agents 表 `skill_package_ids`/`knowledge_base_ids`/`mcp_servers` 三列 | 加绑定列 + 对话默认注入（per-turn 可覆盖；知识库仍显式指定才注入） |
| 8 | `prompt_files` 注入 | ⬜ octop manifest 声明的非标准文件（IDENTITY/HEARTBEAT 等）已复制但不注入 | 内容合并进注入或 system_prompt |
| 9 | octop WS 迁移 | ⏸ 事件帧已对齐，通道仍 HTTP SSE | 注意 python websockets 连 8088 WS 恒 403（§6） |
| 10 | HITL 工具审批流 | ⏸ 当前不启用 | harness 自带 HumanInTheLoopMiddleware，有高风险工具再开 |

### 8.3 明确不做（用户拍板，别再排）

- 🚫 **分发到其他 Mac**（2026-10-06 拍板）：没有发布计划，而发布要花钱买 Apple Developer 账号 → **codesign / notarize / 自动更新 / 首启向导一律不做**。打包链保留只作本机验证（打包配置/图标/单实例锁/CSP 的真实回归）；**日常一律 `make start`**。记录见 `AGENT.md` 与 `shells/nuomi-avatar/README.md`
- 🚫 **轨迹抽屉 octop 完整版**（2026-10-05）：简版够用，可观测性走 Langfuse
- 🚫 **AI 数字人模型升级**（已全 3D）、**前端 bundle code-split**（本地 1.3MB 收益低）、**表情观感幅度**、**模型资产补全**（cat 缺失不补）
- ⏸ **OCR** 与 **TTS 说话**虽在 8.2，但都是"用户拍板暂缓/待办"，不是被遗忘

## 9. 关键 git 历史

```
027c584  AI 数字人接入（nuomi-avatar 二次开发）        → 5602480 删 nuomi-avatar 大脑
ba7bce6  AI 数字人协议层（emotion，后废除）      → 6c0711a 能力域：插件/技能接入 octop-harness
ef05d9e  目录重组（shells/frontend 分层）+ MCP
50eeaa9  frontend 控制台（Vite + React + antd）
f27f8ae  壳打通：控制面板 → /console/
55041a5  交接文档初版 + 协议文档
afbed65  壳 SSE 动作/表情播放器 + aidang 模型试装
1e2b54c  模型资产管理：扫描/切换/插件联动 + 壳 watch + 控制台模型页
1bf979d  docs: HANDOVER 更新到 1e2b54c
b35e874  feat: SkillHub 技能市场 + 技能包 + 会话/删除/壳简化主线（28 文件）
4c08ed5  docs: HANDOVER 回填 b35e874
657a37f  连接器命名统一（/api/connectors、connectors.json、NUOMI_CONNECTORS；mcp_* 仅留技术层）
ce05b80  Git 导入（插件/技能）+ SkillHub 分页修复（服务端固定 10 条/页，后端循环翻页）
fcb4516  内置技能只读展示（/skills/builtin，24 个）+ 环境变量设置（/settings/env）+ requires_api_key
5c2d405  技能市场卡片化：slug 去重、等宽卡片、首字头像、描述省略+tooltip
8f2684d  已安装技能卡片化：内置/技能/技能包统一平铺 + 类型筛选 + 搜索 + 角标
e65477d  插件/连接器页卡片化（AI 数字人模型橙色标、传输协议角标、清「服务器」文案）
5e3a268  卡片等高 CSS（首版选择器未命中，见 §6 踩坑）
dc242b1  卡片等高修复：antd5 grid 列为裸 div，.ant-row > div（amend 掉误提交的 .vite 缓存）
3492b20  AI 数字人页等高：补 .ant-row.nuomi-grid 形态 + align-items: stretch
03eed82  feat: 专家-插件解耦 + 对话框 per-turn 能力注入（skills/connectors）+ 能力选择器/chips/工具步骤/轨迹抽屉
1ab457e  docs: HANDOVER 回填（解耦 + 对话框大改动）
0efee9f  方案B落地：单共享 vrm-avatar 插件 + 动态工具 + 删互斥
066effd  方案B架构定稿（动态工具装配）
c5a4032  全量改名桌宠→AI数字人 + 丢弃 myspy + 3D 观感 + 导入预览
8defdc9  删内置手写动作，动作清单只以 VRMA 为准 + idle 待机循环
66b574c  自转/表情时长/动作清单修复
4ac8b68  表情终极根因（模型 blendShapeGroups 全空 binds）+ expressions_have_data 检测
022f7c8  模型热切换修复（switch-model → 页面 reload 热重载）
492a746  VRM 尺寸归一化（Box3 统一 1.4m + 脚底对齐）
7abd166  插件列表 tool_count 动态统计（vrm-avatar=2）
```


6b71691  feat: 大模型配置页（providers.json CRUD）+ 模型不绑专家（default_model 列删除，对话框 per-turn 选模型）
988b65e  docs: HANDOVER 回填（大模型配置 + 模型解耦）
35d86d9  feat: Provider 模型探测（probe API + 勾选默认）· 对话框输入区布局优化（选择器独立行/输入框整行）
05dbdee  docs: HANDOVER 回填（Provider 探测 + 输入框优化）
363a952  fix: 对话失败根因（脱敏串回写覆盖 key + 无 key Provider 占位）
bd0401f  refactor: Provider 必须有 key（删占位，前后端校验兜底）
fd338c1  chore: AI 数字人开关收尾——清理 pet-stopped 死代码 + 交接文档/项目记忆记录
f7e62b4  refactor: AI 数字人页命名统一——Models → PetModels（文件/组件/路由 key）+ 页面文案去混淆
f8e06d6  feat: AI 数字人开关联动模型插件——关闭停用全部、开启恢复当前、关闭状态切模型不激活

### 2026-10-06 本轮（审计 → 第 0 步/第 1 周 → 四流并行 → 第二批修复）

```
fe7c042  feat(security): 本机访问守卫（Host/Origin/token）+ 插件不隐式装依赖 + 门禁真绿
1a08c33  fix(correctness): 工具调用投影 + 运行时入口 + 插件注册竞态 + 阻塞调用 offload + SSE 终止契约
2a98759  feat(ux): 前端流式可中止 + 插件卡片 XSS 净化 + 壳交互与控制面板生命周期
7f51c9c  feat(security): 密钥脱敏 + 原子写 0600 + Langfuse 生命周期
c927e71  docs: 记录第 0 步与第 1 周的决策/踩坑/审查修正
9187a96  feat(portability): 换台机器能跑 —— 启动构建前端 / 修 .env 路径 / LICENSE / 清个人路径
6ec8f2a  feat(shell): 打包分发链 + 单实例锁 + 安全基线 + 模型路径自解析
de72f9c  test(frontend): vitest 基建 + XSS/SSE/引用/片段回归，并修 7 项体验软点
8dd7fdf  feat(memory): 记忆可视化 + 上传限流
32fad76  refactor(frontend): 设计 token 落地（唯一定义处 + 结构上不可漂移），DESIGN.md 改为描述现实
950d8d5  docs: 记录「不做分发」的决策与打包产物的真实边界
a309a7d  fix: 连接泄漏 / 请求局部状态 / 工具装配开销 / SSE 心跳与丢事件 / 历史分页一致性
```

**测试基线**：后端 46 → **136 例**，前端 0 → **44 例**；`make check` = lint + format + mypy + 后端测试 + 前端构建 + 前端测试 + 壳语法。

---

开发规范：`make lint`（ruff）/ `make typecheck`（mypy）/ `make frontend-test`（vitest），CI 在 `.github/workflows`。
