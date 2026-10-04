# Nuomi 交接文档（HANDOVER）

> 最后更新：2026-10-04 · 分支 main · HEAD `1bf979d`（**当前工作区有 15 个文件未提交 + 2 个新目录，见文末 §8**）
> 本文件面向「下一个接手的人」：先读它，再读代码。概念沿革见 `docs/concepts.md`、`docs/octop-alignment-research.md`。

---

## 0. 一句话定位

**Nuomi = AI 大脑（backend，基于 octop-harness）+ 通用控制台（frontend，React + antd）+ 可插拔表现层（shells/myspy 桌宠壳）。**
表现层只消费标准化 SSE 协议（v3：**octop 原生事件帧**）；能力（专家/插件/技能/MCP）由后端统一管理，控制台统一呈现。**对齐 octop 的领域语言**：Expert（专家）、Plugin（插件）、Skill（技能）、MCP、Workspace（工作区/存储）——机制语言（Fiber/Scope/Registry 等）全部下沉到 octop-harness 基础库，nuomi 业务层只写领域语言。

## 1. 架构与目录

```
nuomi/
├── backend/          # AI 大脑（uv 管理，python3.12，.venv）
│   ├── app/
│   │   ├── transport/    # 接入层：api.py（/api/*）+ openai_compat.py（OpenAI 兼容）
│   │   ├── domain/       # 领域核心（业务逻辑唯一所在地）
│   │   │   ├── agents/   # 专家管理
│   │   │   ├── plugins/  # 插件服务（PluginService）
│   │   │   ├── skills/   # 技能服务（SkillService）
│   │   │   ├── chat/     # 会话服务（ChatSessionService：thread 统一绑定，读写壳 config）
│   │   │   └── pet/      # 桌宠模型资产管理（扫描/切换/插件生成）
│   │   ├── infra/        # 基础设施适配：harness/（config|manager|chat）
│   │   ├── storage/      # 存储：db.py（SQLite：agents/plugins/agent_plugins/skills）
│   │   ├── config.py     # env 配置（Settings，含 MCP alias）
│   │   └── main.py       # lifespan + /console 静态挂载
│   └── examples/         # 示例 MCP server（pet_mood_server.py）
├── frontend/          # 控制台：Vite + React 18 + antd 5 + TS（octop 技术栈）
│   └── dist/            # 构建产物（不入 git），后端挂 /console
├── shells/
│   └── myspy/           # 表现层壳（Electron + Live2D 桌宠，纯表现层）
│       ├── main.js      # 主进程：桌宠窗口 + 控制面板（→ /console/）
│       ├── app.js       # 渲染层：**纯表现层**（模型渲染 + 订阅后端动作广播播放动作/表情；对话/字幕/输入逻辑已移除）
│       ├── index.html / css/styles.css  # **仅画布 + 右键菜单**（输入框、字幕已移除）
│       └── config.json  # api_url / TTS / UI / **会话绑定（nuomi.thread_id / nuomi.threads，后端+控制台读写，壳不再读对话）**
└── docs/               # 协议与设计文档
```

**依赖规则（对齐 octop，只允许向内）**：`transport → domain → infra → 基础设施（octop-harness + SQLite）`；
`domain` 绝不 import `transport/cli`；`storage` 只做 SQL。横切：`config.py`（env）、i18n 未启用。

## 2. 核心概念

| 概念 | 说明 | 落点 |
|---|---|---|
| 专家 Expert | 有名字/人格/系统提示词的 AI 角色，可启停、可运行多个实例 | `GET /agents`、`POST /agents` |
| 插件 Plugin | 给 LLM 的工具集：`plugin.yaml` + `main.py`（`ctx.tool("工具名", fn, ...)` 注册，可注册多个）；全局启停 + 专家级绑定。**模型对应插件在插件页只读不可启停**（模型 1:1 对应插件，用户不可在插件页操作） | 工作区 `plugins/`，服务在 `domain/plugins/service.py` |
| 技能 Skill | SKILL.md（frontmatter name/description + 提示词正文），随 harness 注入 | 工作区 `skills/`，服务在 `domain/skills/service.py` |
| 技能包 Skill Package | **SkillHub（腾讯技能市场 api.skillhub.cn）技能集（skillset）的本地安装**：一包多技能（`skill_packages/<id>/skills/<slug>/`），**包级整体启停/删除**（包内技能不可单独操作，注入时禁用包=不注入）；支持从市场**单技能安装**（进 `skills/<slug>/`）与**技能集建包**（`/skill-packages/from-skillhub`）；**不做版本更新**（对齐 Octop）。市场客户端在 `infra/skillhub.py`（search/rankings/skillsets/download + zip 安全校验：路径防穿越/2000 文件/64MB/压缩比/根 SKILL.md 强制），服务在 `domain/skillpackages/service.py`，DB 表 `skill_packages` + `skill_package_skills` | `GET /skillhub/*`、`POST /skills/install`、`/skill-packages` CRUD；chat 注入 `_all_skills_dirs()` = 工作区 skills + 各启用包 skills（harness `skills_dir` 列表） |
| MCP | stdio 外部工具服务器，`NUOMI_MCP_SERVERS` JSON 配置，工具带 `{server}_` 前缀 | `Settings.mcp_servers`，`GET /mcp` |
| 存储 Workspace | 工作区（harness 沙箱/专家/会话/插件/技能）+ 数据根（SQLite） | `GET /workspace` |
| 桌宠模型 Model | 表现层资产（Live2D Cubism3，`shells/myspy/2D/<id>/`）；**插件名=模型名、工具名=模型真实动作/表情名**，选中模型即激活对应插件（互斥，插件页只读不可启停）。**切换模型联动两件事**：释放 agent 实例（工具集随绑定重建）+ 绑定该模型专属会话 | `GET/POST /api/pet/models*`，领域在 `domain/pet/service.py` |
| 动作播放链 | 任意来源的对话触发模型插件工具（动作/表情）→ 后端**事件总线广播**（`app/infra/pet_events.py`，`/api/pet/events` SSE 长连接）→ 桌宠壳**常驻订阅**播放（`subscribePetEvents()` 启动即连、断线 3s 重连、本地/广播 1s 内同名去重）——**控制台对话也能驱动桌宠动作**，视觉与对话来源解耦 | `backend/app/infra/pet_events.py` + `shells/myspy/app.js` |
| 表现层协议 | v3：**octop 原生事件帧**（token / tool_call_chunk / tool_result / usage / done，帧内带 node+thread_id），SSE 承载；**无 emotion 事件**（表情/动作已走模型插件工具） | `docs/pet-protocol.md` |

**已废除（不再出现）**：模块（不对外透出）、项目/伙伴/技能包、AI 记录室、myspy 自带大脑（plugin-manager/mcp-manager/diary-manager/llm-client/MoodChatModule，原代码在 git `027c584` 可查）；**emotion 事件机制**（2026-10-03 移除，表情/动作全部由模型插件工具驱动，展示层不做兜底清洗）。

## 3. 启动手册

```bash
# 1) 后端（必须先杀旧进程，否则新代码不生效）
pkill -9 -f "uvicorn app.main:app" || true
cd backend && nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/nuomi-backend.log 2>&1 &

# 2) 前端（改了 frontend/src 后必须重新构建；dist 不入 git）
cd frontend && npm run build     # vite base=/console/，产物 dist/

# 3) 壳（桌宠 + 控制面板窗口，面板自动指到 /console/）
kill $(ps aux | grep "myspy/node_modules/electron" | grep -v grep | awk '{print $2}') 2>/dev/null || true
cd shells/myspy && npm start
```

访问：
- 控制台：`http://127.0.0.1:8000/console/`（浏览器或壳内面板同源）
- 开发态前端：`cd frontend && npm run dev`（5173，/api 代理到 8000）

环境：
- Python：uv 管理，`.venv/bin/python`，无 pip
- Node：frontend/ 与 shells/myspy/ 各自 npm install
- 工作区：`/Users/superman/Documents/Nuomi`（agents/hello、Hi、memory.sqlite、sessions、plugins/{weather, aidang, cat, hiyori}、skills/astrology、_builtin_skills；模型插件 aidang 14 工具 / hiyori 2 工具 / cat 0 工具为生成产物，pet_action/pet_emotion 已废删；LSS/Roxy/baimeimo 已删且无免费完整资源）
- 数据根：`/Users/superman/Library/Application Support/Nuomi`（nuomi.db）
- 会话权威配置：`/Users/superman/projects/code/nuomi/shells/myspy/config.json`（`nuomi.thread_id`/`nuomi.threads`，后端 `domain/chat/service.py` 硬编码该路径）
- .env：仓库根（含 `NUOMI_MCP_SERVERS` 示例）；改后必须重启 uvicorn

## 4. API 清单（全部 /api 前缀，见 app/transport/api.py）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查 |
| GET/POST | /agents | 专家列表 / 新建 |
| GET/PATCH/DELETE | /agents/{id} | 专家详情/更新/删除 |
| POST | /agents/{id}/chat | **SSE 对话流（v3 octop 事件帧）**，body `{"messages": str, "thread_id": str="default"}` |
| GET | /agents/{id}/chat/history?thread_id=&limit= | 按线程取历史（octop checkpointer，返回 `[{role, content}]`） |
| GET | /chat/state?agent_id= | 会话状态：`{agent_id, current, sessions:[{thread_id,title,updated_at,agent_id}]}`（按 updated_at 倒序，「桌宠会话」default 恒在首位） |
| POST | /chat/new | `{agent_id}` → 生成新 thread `{agentId}:{base36时间}{4随机}`，写 config 并登记列表 |
| POST | /chat/switch | `{agent_id, thread_id}` → 换绑当前会话 |
| POST | /chat/touch | `{agent_id, thread_id, title?}` → 更新列表排序/标题 |
| DELETE | /chat/threads/{thread_id}?agent_id= | **删除会话**：config 列表移除 + 检查点历史清除（memory.sqlite 的 checkpoints/writes）；删当前会话自动切到最近会话（无则 default）；default 可删（=清空桌宠旧记忆） |
| POST | /agents/{id}/start|stop|status | 实例生命周期 |
| GET/PUT | /agents/{id}/plugins | 专家绑定的插件（PUT body: {"plugin_ids":[...]} 覆盖式） |
| GET | /plugins | 插件列表 |
| POST | /plugins/sync | 重新扫描工作区 plugins/ |
| PATCH | /plugins/{id} | {"enabled": bool} 全局启停 |
| DELETE | /plugins/{id} | **删除插件**（DB + 全部 agent 绑定 + 插件目录）；**模型插件 400 拒绝**（由桌宠删除级联）；删后 `manager.close()` 下次对话重建 |
| GET | /skills | 技能列表（含内置） |
| PATCH | /skills/{name} | 技能启停 |
| DELETE | /skills/{name} | **删除技能**（目录 + DB）；删后 `manager.close()` |
| POST | /skills/install | **从 SkillHub 安装单技能** `{slug}` → `{workspace}/skills/<slug>/`；同名已存在 409；装后 `manager.close()` |
| GET | /skillhub/search?q=&page=&page_size= | SkillHub 市场搜索（技能条目） |
| GET | /skillhub/rankings?ranking_type=hot | SkillHub 榜单（hot/featured/newest/recommended/trending/paid） |
| GET | /skillhub/skillsets/{slug} | SkillHub 技能集详情（含 skill_slugs） |
| GET | /skillhub/skillsets?q= | SkillHub 技能集列表（包来源，本地过滤 + 分页） |
| GET | /skill-packages | 技能包列表（含包内技能 slug/启停、包路径） |
| POST | /skill-packages | 本地建空包 `{name, description?, icon_url?}` |
| POST | /skill-packages/from-skillhub | **从技能集建包** `{slug, name?}`：取详情 → 逐个技能下载 → `skill_packages/<id>/skills/<slug>/`；包名冲突 409；**包级整体启停**（`enabled=false` → 注入时跳过该包） |
| PATCH | /skill-packages/{id} | `{enabled?, name?, description?, icon_url?}` 启停/改名（改名同时移动目录） |
| DELETE | /skill-packages/{id} | **删除技能包**（DB + 包目录）；删后 `manager.close()` |
| GET | /mcp | MCP 服务器列表 |
| DELETE | /mcp/{name} | **删除 MCP**：settings 移除 + 持久化 `data_root/mcp_servers.json`（重启后不再恢复；文件优先于 env）；删后 `manager.close()` |
| GET | /workspace | 工作区/数据根/能力计数 |
| GET | /pet/models | 桌宠模型列表（动作/表情 + 当前激活；只列文件真实存在的能力） |
| POST | /pet/models/switch | 切换模型：写壳 config + 联动插件（body: `{"model_id":"cat"}`） |
| DELETE | /pet/models/{id} | **删除模型（级联）**：删模型插件（DB/绑定/目录）→ 删资产 `2D/<id>/` → 删的是激活模型则自动切到剩余第一个（联动插件互斥 + 会话换绑），无剩余则 ui.model 置空 |

OpenAI 兼容端点：`app/transport/openai_compat.py`（model 形如 `nuomi/agent:<id>`，`/v1/chat/completions` 仍输出 OpenAI SSE，未改）。

## 5. 已验证链路（回归依据）

1. **插件链**：示例 weather 插件（plugin.yaml + `ctx.tool("weather_query", ...)`）绑定默认专家后，对话**真实触发 tool_call → tool_result**（事件流完整）。
2. **技能链**：SKILL.md frontmatter 解析 + 启停；`init_workspace(include_skills=True)` 同步 ~22 个 zh 内置技能（apple-notes、plan、systematic-debugging 等）。
3. **MCP 链**：示例 `backend/examples/pet_mood_server.py` + `.env` 配置，对话触发 `pet_mood_get_pet_status` 真实返回。
4. **协议链（v3）**：`/chat` 输出 octop 事件帧（token/tool_call_chunk/tool_result/usage/done + node/thread_id），curl 实测 56 帧；node 模拟壳解析真实流 0 错误；壳字幕/动作播放路径正常（AX 树不暴露字幕 DOM 是透明窗口观察限制）。
5. **控制台链**：React 板块（专家/插件/技能/MCP/存储/桌宠）浏览器实测无 console 错误；hash 路由直达。
6. **壳链**：控制面板窗口 loadURL 后端 /console/，后端未起时每 2s 重试（最多 30 次）；node --check 通过。
7. **SkillHub 链**：真实市场实测——search/rankings/skillsets 列表与详情返回正确（slug/display_name/skill_slugs）；单技能 `superpowers-tdd` 安装成功（zip 含根 SKILL.md，302 重定向跟随已修）；技能集 `tech-test-automation` 建包成功（6 技能 → `skill_packages/<id>/skills/`，中文包名 id 退化 `pkg-<uuid>` 不冲突）；包启停/删除、chat 注入（skills_dir 列表）无异常。
8. **市场技能 frontmatter 注意**：部分市场技能 SKILL.md 的 description 含裸 `: `（未加引号）导致 harness YAML 解析失败被安全跳过（如 superpowers-tdd；与 Octop 行为一致，非 nuomi bug）——安装链路正常，跳过的是 harness 注入层。
7. **模型资产管理链**：`/api/pet/models` 只列文件真实存在的能力（现存 aidang 14 动作 / hiyori 2 动作 / cat 0 动作）；`switch` 写 config + 解绑其他模型插件并激活当前模型插件；**插件页对模型对应插件只读不可启停**；壳 `main.js` watch config 自动发 `switch-model` → 渲染进程切换；对话「给我比个心」→ LLM 调模型插件工具 `touch_special` → 壳按字段播放。
8. **会话链**：壳启动 `ensureChatSession()`（无绑定→"default" 延续旧记忆）；对话前 `getChatThreadId()` 重读 config 跟随切换；桌宠「新会话」按钮 → 后端生成新 thread + 清空本地上下文 + 换绑；控制台会话列表/历史/新建/切换走后端接口，桌宠聊天记录可见。**一个桌宠一个会话**：切换模型 → 绑该模型专属会话（无则新建干净），切回绑原会话（curl 往返验证）；新会话归属当前模型（model_id）。
9. **模型切换工具集跟随链**：`/pet/models/switch` → 插件互斥（只启用当前模型插件）+ 解绑/绑定 + **`manager.release(agent_id)`**（释放实例，下次对话带新模型工具重建）+ 会话换绑。已验证：切 hiyori → 对话工具为 [Idle, TapBody]；切 aidang → [touch_head 等 14 工具]。
10. **发送修复链**：桌宠输入框发送报错 `saveConversationHistory is not defined` 已修复（该函数从 afbed65 起"只有调用、从未定义"，删两处调用）；实测壳请求 → POST /chat 200 → 字幕正常。

## 6. 踩坑记录（再遇到不用重踩）

- **uvicorn 旧进程占 8000**：新代码不生效，必须先 `pkill -9 -f "uvicorn app.main:app"` 再重启。
- **octop_harness 顶层不导出插件 API**：必须从 `octop_harness.plugins` 子包导入（PluginRegistry/build_plugin_tools/discover_plugin_dirs/load_all）。
- **中文工具名被 DeepSeek API 拒**（400 invalid 'tools[20].function.name'，要求 `^[a-zA-Z0-9_-]+$`）：service 层做 slug 防御（非 ASCII 名改名 `tool_{n}`，中文语义并入 description）；示例插件用 ASCII 名。
- **Vite base**：挂 /console 必须 `base: '/console/'`，否则产物引用 `/assets/...` 404。
- **浏览器会话缓存旧 JS**：验证新构建带 nonce query（`?v=3`）强制刷新。
- **Settings alias 忘写**：报 `'Settings' object has no attribute 'mcp_servers'`，需 `validation_alias=AliasChoices(...)`。
- **MCP 配置写死 .env**：控制台 MCP 页只读不改；改动后必须重启 uvicorn。
- **模型资产不完整 = 假能力**：cat（hijiki）model3.json 声明动作但 `motion/` 文件缺失，壳切换必报 `Texture loading error`。扫描已做文件存在性校验，缺失能力的模型如实显示 0 动作、不生成插件。**LSS/Roxy/baimeimo 已删**（无免费完整资源，勿再找）。
- **octop 插件"无绑定=默认可用"**：`_tool_enabled` 逻辑里 agent 未绑定该插件且全局 enabled 时工具仍暴露；旧插件只解绑不删目录，工具照样进 LLM 工具集——废弃插件必须连目录一起删（pet_action/pet_emotion 已删）。
- **渲染进程错误看不见**：app.js 切换失败的错误被 try/catch 吞掉且 renderer console 不进主进程日志；main.js 已加 `webContents.on('console-message')` 转发，排查先看 `/tmp/myspy-shell.log` 的 `[renderer:N]` 行。
- **新生成/删除插件必须重启后端**：工具装配来自启动时 `load_all` 的进程内 PluginRegistry；sync API 只同步 DB 记录，不进 registry。
- **`saveConversationHistory` 从未定义过**（afbed65 引入即只有调用）：报错别再找定义，删除调用即可。
- **壳 saveConfig 会覆盖 ui.model**：旧实现把壳内存整个 config 写回磁盘，启动后内存的旧模型值会覆盖后端刚切换的模型（桌宠"切到 aidang 点新会话却跳回 hiyori"）。**修复：saveConfig 以磁盘最新为底，只覆盖壳拥有的 nuomi.\***。
- **切换模型后工具集不变**：`manager.get_agent` 缓存实例、忽略新 plugin_tools——**`/pet/models/switch` 必须 `manager.release(agent_id)`** 让下次对话重建。已加。
- **LLM 幻觉调用旧模型工具名**：default 线程历史含 aidang 时期"摸头=touch_head"，切到 hiyori 后在同线程问摸头 → LLM 仍调 touch_head（工具不存在 → 工具节点报错 → 修正）。**模型专属会话（无旧模型历史）可根治**——这也是"一个桌宠一个会话"的核心价值。
- **python `websockets` 库连 octop 8088 WS 恒 403**（带 origin、关 compression 亦然）：curl / aiohttp 可通。后续若真切 WS 用 aiohttp 或查明原因。
- **AX 树拿不到桌宠字幕 DOM**：字幕在透明置顶无边框窗的 fixed 层，AX 不暴露；验证字幕用壳日志 + node 模拟帧解析，别依赖 AX。

## 7. 遗留事项 / 下一步（未拍板）

- [ ] **桌宠直接说话（TTS）**（用户已拍板待办）：壳已**移除字幕**（不做语音转文字视觉显示），桌宠只保留动作/表情播放；未来让桌宠"直接说话"替代字幕——TTS 客户端代码（`js/tts-client.js`、`TTSStreamProcessor`、`tts`/`ttsStreamProcessor` 及嘴型 `modelCtrl`）已**保留未删**，届时只需恢复"收到回复文本→TTS 播报"入口（当前对话文本只在控制台，广播仅 tool_call 动作事件，无 token 推送）
- [ ] **对话菜单**（用户已确认暂缓）：多会话列表/切换 UI 在桌宠侧的逻辑梳理（当前"一个 thread_id 绑定 + 新会话按钮"已落地，完整菜单待做）
- [ ] **octop WS 迁移**（用户已拍板暂缓）：事件帧已对齐 octop，通道仍 HTTP SSE；切 WS 时消费者解析逻辑直接复用，注意 websockets 403 坑
- [ ] **HITL 工具审批流**（当前不启用）：octop_harness 自带 HumanInTheLoopMiddleware + resume_hitl，未来有高风险工具再按工具分级开启
- [ ] **SkillHub 技能包版本更新**（用户已拍板不做，与 Octop 对齐）：市场有新版时手动重装覆盖即可
- [ ] **糯米人设源头约束"回复不要用尖括号标签"**（`<开心>` 等仍会出现在回复里，展示层不做兜底清洗，已决定从源头治理，未实施）
- [ ] MCP 服务器在控制台内编辑/重载（目前仅 GET，配置在 .env）
- [ ] 壳启动时自动拉起 uvicorn（8000 未起时开面板白屏，已有重试但体验一般）
- [ ] 前端 bundle 1MB（antd 全量），可 code-split 优化
- [ ] 表现层扩展（动作/新桌宠）——协议已标准化，换表现层不动大脑
- [ ] 模型资产补全：cat（hijiki）动作文件缺失（无 motion/ + 纹理），换完整资产后可自动恢复插件生成
- [ ] 表情插件：当前所有模型 `expressions` 为空，`_make_expression_player` 与壳 `model.expression()` 播放路径已就绪但无数据可测
- [ ] 模型插件工具语义：工具 description 只有动作名，LLM 选动作时靠中文名映射表（`_MOTION_ZH`）；"比心"目前落到 aidang 的 touch_special，语义映射可再打磨

## 8. 关键 git 历史与未提交工作区

```
027c584  M7 桌宠接入（myspy 二次开发）
ba009a9  P1 壳净化 → 5602480 删 myspy 大脑 → 9a08983 壳 README
ba7bce6  P2 桌宠协议层（emotion + pet-protocol.md）
6c0711a  B-P3 能力域：插件/技能接入 octop-harness
ef05d9e  目录重组（shells/frontend 分层）+ MCP 后端
50eeaa9  frontend 控制台：Vite + React + antd 重写
f27f8ae  壳打通：控制面板 → React 控制台 /console/
55041a5  交接文档（本文件初版）+ 协议文档
afbed65  壳 SSE 动作/表情播放器 + aidang 模型试装
1e2b54c  模型资产管理：扫描/切换/插件联动 + 壳 watch + 控制台模型页
1bf979d  docs: HANDOVER 交接文档更新到 1e2b54c（模型资产管理主线）
b35e874  feat: SkillHub 技能市场 + 技能包 + 会话/删除/壳简化主线（2026-10-04，28 文件）
```

**b35e874 提交内容（2026-10-03 ~ 10-04 全部主线，`git show --stat b35e874` 可查）**：
- 后端：`domain/chat/`（新，会话服务）、`domain/skillpackages/`（新，技能包）、`infra/skillhub.py` + `infra/pet_events.py`（新）、`transport/api.py`（会话 API + /chat octop 帧 + SkillHub/技能包路由 + 删除端点）、`openai_compat.py`、`storage/db.py`（skill_packages 表）、`config.py`（skillhub_host）
- 前端：`App.tsx`（菜单"模型"改名）、`api.ts`（chatStream octop 帧 + SkillHub 类型）、`pages/Chat.tsx`（新，会话列表）、`pages/Skills.tsx`（已安装/市场双 tab）、`Models.tsx`/`Plugins.tsx`（模型插件只读）
- 壳：`app.js`（octop 帧解析 + 常驻订阅 + **移除输入框/字幕/ASR/弹幕/对话链路**）、`config.json`（thread 绑定）、`index.html`/`css/styles.css`（仅画布+右键菜单）、`js/model/model-interaction.js` + `vrm-model-interaction.js`（删已移除 DOM 的聊天框逻辑）
- 文档：`docs/pet-protocol.md`（v3）、HANDOVER 技能包主线

开发规范：`make lint`（ruff）/ `make typecheck`（mypy），CI 已在 .github/workflows 配置。
