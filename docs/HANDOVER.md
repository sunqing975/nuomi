# Nuomi 交接文档（HANDOVER）

> 最后更新：2026-10-03 · 分支 main · HEAD `f27f8ae`
> 本文件面向「下一个接手的人」：先读它，再读代码。概念沿革见 `docs/concepts.md`、`docs/octop-alignment-research.md`。

---

## 0. 一句话定位

**Nuomi = AI 大脑（backend，基于 octop-harness）+ 通用控制台（frontend，React + antd）+ 可插拔表现层（shells/myspy 桌宠壳）。**
表现层只消费标准化 SSE 协议；能力（专家/插件/技能/MCP）由后端统一管理，控制台统一呈现。**对齐 octop 的领域语言**：Expert（专家）、Plugin（插件）、Skill（技能）、MCP、Workspace（工作区/存储）——机制语言（Fiber/Scope/Registry 等）全部下沉到 octop-harness 基础库，nuomi 业务层只写领域语言。

## 1. 架构与目录

```
nuomi/
├── backend/          # AI 大脑（uv 管理，python3.12，.venv）
│   ├── app/
│   │   ├── transport/    # 接入层：api.py（/api/*）+ openai_compat.py（OpenAI 兼容）
│   │   ├── domain/       # 领域核心（业务逻辑唯一所在地）
│   │   │   ├── agents/   # 专家管理
│   │   │   ├── plugins/  # 插件服务（PluginService）
│   │   │   └── skills/   # 技能服务（SkillService）
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
│       ├── app.js       # 渲染层：聊天/情绪/嘴型（消费后端 SSE）
│       └── config.json  # api_url / TTS / UI 配置
└── docs/               # 协议与设计文档
```

**依赖规则（对齐 octop，只允许向内）**：`transport → domain → infra → 基础设施（octop-harness + SQLite）`；
`domain` 绝不 import `transport/cli`；`storage` 只做 SQL。横切：`config.py`（env）、i18n 未启用。

## 2. 核心概念

| 概念 | 说明 | 落点 |
|---|---|---|
| 专家 Expert | 有名字/人格/系统提示词的 AI 角色，可启停、可运行多个实例 | `GET /agents`、`POST /agents` |
| 插件 Plugin | 给 LLM 的工具集：`plugin.yaml` + `main.py`（`ctx.tool("工具名", fn, ...)` 注册，可注册多个）；全局启停 + 专家级绑定 | 工作区 `plugins/`，服务在 `domain/plugins/service.py` |
| 技能 Skill | SKILL.md（frontmatter name/description + 提示词正文），随 harness 注入 | 工作区 `skills/`，服务在 `domain/skills/service.py` |
| MCP | stdio 外部工具服务器，`NUOMI_MCP_SERVERS` JSON 配置，工具带 `{server}_` 前缀 | `Settings.mcp_servers`，`GET /mcp` |
| 存储 Workspace | 工作区（harness 沙箱/专家/会话/插件/技能）+ 数据根（SQLite） | `GET /workspace` |
| 表现层协议 | SSE 事件流：`token / emotion / tool_call / tool_result / usage / done`；emotion 集合=开心/生气/难过/惊讶/害羞/俏皮 | `docs/pet-protocol.md` |

**已废除（不再出现）**：模块（不对外透出）、项目/伙伴/技能包、AI 记录室、myspy 自带大脑（plugin-manager/mcp-manager/diary-manager/llm-client/MoodChatModule，原代码在 git `027c584` 可查）。

## 3. 启动手册

```bash
# 1) 后端（必须先杀旧进程，否则新代码不生效）
lsof -ti :8000 | xargs kill -9
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/nuomi-backend.log 2>&1 &

# 2) 前端（改了 frontend/src 后必须重新构建；dist 不入 git）
cd frontend && npm run build     # vite base=/console/，产物 dist/

# 3) 壳（桌宠 + 控制面板窗口，面板自动指到 /console/）
cd shells/myspy && npm start
```

访问：
- 控制台：`http://127.0.0.1:8000/console/`（浏览器或壳内面板同源）
- 开发态前端：`cd frontend && npm run dev`（5173，/api 代理到 8000）

环境：
- Python：uv 管理，`.venv/bin/python`，无 pip
- Node：frontend/ 与 shells/myspy/ 各自 npm install
- 工作区：`/Users/superman/Documents/Nuomi`（agents/hello、Hi、memory.sqlite、sessions、plugins/weather、skills/astrology、_builtin_skills）
- 数据根：`/Users/superman/Library/Application Support/Nuomi`（nuomi.db）
- .env：仓库根（含 `NUOMI_MCP_SERVERS` 示例）；改后必须重启 uvicorn

## 4. API 清单（全部 /api 前缀，见 app/transport/api.py）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查 |
| GET/POST | /agents | 专家列表 / 新建 |
| GET/PATCH/DELETE | /agents/{id} | 专家详情/更新/删除 |
| POST | /agents/{id}/chat | **SSE 对话流**（token/emotion/tool_call/...） |
| POST | /agents/{id}/start|stop|status | 实例生命周期 |
| GET/PUT | /agents/{id}/plugins | 专家绑定的插件（PUT body: {"plugin_ids":[...]} 覆盖式） |
| GET | /plugins | 插件列表 |
| POST | /plugins/sync | 重新扫描工作区 plugins/ |
| PATCH | /plugins/{id} | {"enabled": bool} 全局启停 |
| GET | /skills | 技能列表（含内置） |
| PATCH | /skills/{name} | 技能启停 |
| GET | /mcp | MCP 服务器列表 |
| GET | /workspace | 工作区/数据根/能力计数 |

OpenAI 兼容端点：`app/transport/openai_compat.py`（model 形如 `nuomi/agent:<id>`）。

## 5. 已验证链路（回归依据）

1. **插件链**：示例 weather 插件（plugin.yaml + `ctx.tool("weather_query", ...)`）绑定默认专家后，对话**真实触发 tool_call → tool_result**（事件流完整）。
2. **技能链**：SKILL.md frontmatter 解析 + 启停；`init_workspace(include_skills=True)` 同步 ~22 个 zh 内置技能（apple-notes、plan、systematic-debugging 等）。
3. **MCP 链**：示例 `backend/examples/pet_mood_server.py` + `.env` 配置，对话触发 `pet_mood_get_pet_status` 真实返回。
4. **协议链**：emotion 事件（PET_MOOD_RULE + extract_emotion，六标签集合）已并入对话流。
5. **控制台链**：React 五板块（专家/插件/技能/MCP/存储）浏览器实测无 console 错误；hash 路由直达（#plugins/#storage 等）。
6. **壳链**：控制面板窗口 loadURL 后端 /console/，后端未起时每 2s 重试（最多 30 次）；node --check 通过。

## 6. 踩坑记录（再遇到不用重踩）

- **uvicorn 旧进程占 8000**：新代码不生效，必须先 `lsof -ti :8000 | xargs kill -9` 再重启。
- **octop_harness 顶层不导出插件 API**：必须从 `octop_harness.plugins` 子包导入（PluginRegistry/build_plugin_tools/discover_plugin_dirs/load_all）。
- **中文工具名被 DeepSeek API 拒**（400 invalid 'tools[20].function.name'，要求 `^[a-zA-Z0-9_-]+$`）：service 层做 slug 防御（非 ASCII 名改名 `tool_{n}`，中文语义并入 description）；示例插件用 ASCII 名。
- **Vite base**：挂 /console 必须 `base: '/console/'`，否则产物引用 `/assets/...` 404。
- **浏览器会话缓存旧 JS**：验证新构建带 nonce query（`?v=3`）强制刷新。
- **Settings alias 忘写**：报 `'Settings' object has no attribute 'mcp_servers'`，需 `validation_alias=AliasChoices(...)`。
- **MCP 配置写死 .env**：控制台 MCP 页只读不改；改动后必须重启 uvicorn。

## 7. 遗留事项 / 下一步（未拍板）

- [ ] MCP 服务器在控制台内编辑/重载（目前仅 GET，配置在 .env）
- [ ] 壳启动时自动拉起 uvicorn（8000 未起时开面板白屏，已有重试但体验一般）
- [ ] 前端 bundle 1MB（antd 全量），可 code-split 优化
- [ ] 表现层扩展（动作/新桌宠）——协议已标准化，换表现层不动大脑
- [ ] `frontend/src/pages/Experts.tsx` 删除专家用 `a.id ?? a.agent_id` 冗余（后端返回体核对后可简化）
- [ ] 旧任务 #45 K3 前端收尾（与当前主线无直接依赖）

## 8. 关键 git 历史（B 路线重构链）

```
027c584  M7 桌宠接入（myspy 二次开发）
ba009a9  P1 壳净化 → 5602480 删 myspy 大脑 → 9a08983 壳 README
ba7bce6  P2 桌宠协议层（emotion + pet-protocol.md）
6c0711a  B-P3 能力域：插件/技能接入 octop-harness
ef05d9e  目录重组（shells/frontend 分层）+ MCP 后端
50eeaa9  frontend 控制台：Vite + React + antd 重写
f27f8ae  壳打通：控制面板 → React 控制台 /console/
```

开发规范：`make lint`（ruff）/ `make typecheck`（mypy），CI 已在 .github/workflows 配置。
