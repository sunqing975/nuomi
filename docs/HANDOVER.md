# Nuomi 交接文档（HANDOVER）

> 最后更新：2026-10-04 · 分支 main · HEAD `3492b20`（工作区干净）
> 本文件面向「下一个接手的人」：先读它，再读代码。已实现的细节以代码为准（`git show <commit>` 可查）。

---

## 0. 一句话定位

**Nuomi = AI 大脑（backend，基于 octop-harness）+ 通用控制台（frontend，React + antd）+ 可插拔表现层（shells/myspy 桌宠壳）。**
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
├── shells/myspy/      # 表现层壳（Electron + Live2D，纯表现层：动作/表情播放，无输入/字幕）
└── docs/              # pet-protocol.md（v3 协议）等
```

**依赖规则**：`transport → domain → infra → 基础设施（octop-harness + SQLite）`，domain 不 import transport。

## 2. 核心概念

| 概念 | 关键约束 |
|---|---|
| 专家 Expert | 有名字/人格/系统提示词的 AI 角色，可启停 |
| 插件 Plugin | `plugin.yaml` + `main.py`（`ctx.tool(...)` 注册）给 LLM 的工具集；**模型对应插件在插件页只读不可启停**（模型 1:1 对应插件） |
| 技能 Skill | SKILL.md（frontmatter + 提示词），随 harness 注入；目录 `工作区/skills/<slug>/` |
| 技能包 Skill Package | SkillHub 技能集的本地安装（一包多技能，`skill_packages/<id>/skills/<slug>/`）；**包级整体启停/删除**（禁用=不注入）；**不做版本更新** |
| 连接器 | 外部工具服务（MCP 协议，stdio/sse/http），`NUOMI_CONNECTORS` 种子 + `connectors.json` 权威 |
| 桌宠模型 Model | 表现层资产（Live2D，**工作区 `models/2D/<id>/`**，2026-10-04 迁出壳仓库；仓库仅留可分发种子 `assets/models/2D/hiyori`，扫描时幂等播种）；选中模型 = 激活对应插件（互斥）；**与会话解耦**（2026-10-04 起切模型不换会话） |
| 动作播放链 | 对话触发模型插件工具（动作/表情）→ 后端事件总线（`/api/pet/events` SSE）→ 壳常驻订阅播放（断线 3s 重连） |
| 表现层协议 | v3 octop 事件帧（token/tool_call_chunk/tool_result/usage/done，带 node+thread_id）；**无 emotion 事件** |

**已废除**：myspy 自带大脑（plugin-manager/mcp-manager/diary-manager/llm-client/MoodChatModule）、emotion 事件机制、pet_action/pet_emotion 插件、LSS/Roxy/baimeimo 模型。

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

访问：控制台 `http://127.0.0.1:8000/console/`；开发态前端 `cd frontend && npm run dev`（5173 代理 /api）。

环境：
- Python：uv 管理（`.venv/bin/python`，无 pip）；Node：frontend/ 与 shells/myspy/ 各自 npm install
- 工作区与数据根 **同一目录 `/Users/superman/Nuomi`**（2026-10-04 起单根设计；.env 设 `NUOMI_HOME=/Users/superman/Nuomi`，**无 NUOMI_WORKSPACE**，workspace=数据根）；内含 agents/plugins/{weather, aidang, cat, hiyori}/skills + models/2D + nuomi.db + memory.sqlite + nuomi-state.json
- 会话权威配置 `/Users/superman/Nuomi/nuomi-state.json`（nuomi.*：threads/thread_id/agent_id，2026-10-04 起迁出壳 config）；壳 `shells/myspy/config.json` 仅存表现层偏好（ui.model/ui.model_path，后端写、壳 watch 重载，无绝对业务状态）
- .env 在仓库根，改后必须重启 uvicorn

## 4. API 清单（全部 /api 前缀，见 app/transport/api.py）

**对话/会话**：`POST /agents/{id}/chat`（SSE，octop 帧，body `{messages: str, thread_id}`）· `GET /agents/{id}/chat/history` · `GET /chat/state` · `POST /chat/new|switch|touch` · `DELETE /chat/threads/{tid}`（删会话+检查点历史）

**专家/插件**：`GET|POST /agents` · `GET|PATCH|DELETE /agents/{id}` · `POST /agents/{id}/start|stop|status` · `GET|PUT /agents/{id}/plugins` · `GET /plugins` · `POST /plugins/sync` · `POST /plugins/import`（zip）· `POST /plugins/import-git`（git 仓库）· `PATCH /plugins/{id}`（启停）· `DELETE /plugins/{id}`（模型插件 400 拒绝，由桌宠删除级联）

**技能/技能包**：`GET /skills` · `GET /skills/builtin`（内置只读）· `GET|PATCH|DELETE /skills/{name}` · `POST /skills/import`（zip）· `POST /skills/import-git`（git 仓库）· `POST /skills/install`（SkillHub 单技能，requires_api_key 标注）· `GET /skillhub/search|rankings|skillsets{?q,/{slug}}`（search 循环翻页一次 50） · `GET /settings/env` · `PUT /settings/env`（应用设置环境变量，{workspace}/env.json → os.environ，技能/连接器 API key 在此配置）· `GET|POST /skill-packages` · `POST /skill-packages/from-skillhub` · `PATCH|DELETE /skill-packages/{id}`

**其他**：`GET|POST /connectors` · `PUT|DELETE /connectors/{name}`（控制台增删改，connectors.json 持久化，变更下次对话生效）· `GET /workspace` · `GET /pet/models` · `POST /pet/models/switch` · `DELETE /pet/models/{id}`（级联删插件+资产，**不换会话**）· `GET|PUT /pet/status`（桌宠开关：读写壳 config.json `ui.pet_enabled`，壳 watch 后创建/销毁桌宠窗口；关闭=完全停止窗口，壳进程与后端对话不受影响）

OpenAI 兼容：`app/transport/openai_compat.py`（`/v1/chat/completions`，model 形如 `nuomi/agent:<id>`）。

## 5. 已验证链路（回归依据；细节以代码/实测为准）

插件链（weather 触发 tool_call→tool_result；zip/git 导入均实测）、技能链（frontmatter+启停；git 导入实测 anthropics/skills→template-skill）、技能链（frontmatter+启停）、连接器链（pet_mood，MCP 协议）、协议链（/chat octop 帧 56 帧无解析错误）、控制台链（各板块无 console 错误）、壳链（面板重试/订阅断线重连）、**SkillHub 链**（真实市场：search/rankings/skillsets、单技能安装、技能集建包 6 技能、包启停/删除、chat 注入均实测通过）、模型切换链（插件互斥+manager.release，**不换会话**，2026-10-04 起）、**桌宠开关链**（控制台「桌宠」页开关 → /pet/status → config watch → 窗口创建/销毁，启动时按开关决定是否创建，2026-10-04）、会话链（真实线程列表，无 default 合成）、**管理页卡片化链**（专家/技能（已安装+市场）/桌宠/插件/连接器五页统一卡片网格，浏览器实测同行严格等高：技能页 5 列 179px、桌宠 sm 2 列 306px，2026-10-04）。

**注意**：部分市场技能 SKILL.md 的 description 含裸 `: ` 导致 harness YAML 解析失败被跳过（如 superpowers-tdd）——与 Octop 行为一致，非 nuomi bug。

## 6. 踩坑记录（再遇到不用重踩）

- **uvicorn 旧进程占 8000**：新代码不生效，必须先 pkill 再重启。
- **octop_harness 顶层不导出插件 API**：必须从 `octop_harness.plugins` 子包导入。
- **中文工具名被 DeepSeek API 拒**（工具名须 `^[a-zA-Z0-9_-]+$`）：service 层 slug 防御。
- **Vite base**：挂 /console 必须 `base: '/console/'`；验证新构建带 nonce query 强制刷新。
- **Settings alias 忘写**：报 `'Settings' object has no attribute 'mcp_servers'`，需 `validation_alias=AliasChoices(...)`。
- **连接器配置曾写死 .env**：控制台只读、改动需重启；2026-10-04 起控制台可增删改（connectors.json 权威 + manager.close 重载）。
- **模型资产不完整 = 假能力**：cat（hijiki）motion/ 缺失 → 切换报 Texture loading error；扫描已校验文件存在性，缺失能力如实显示 0 动作。
- **octop 插件"无绑定=默认可用"**：废弃插件必须连目录一起删（否则工具照样进 LLM 工具集）。
- **渲染进程错误看不见**：看 `/tmp/myspy-shell.log` 的 `[renderer:N]` 行（main.js 已转发 console-message）。
- **新生成/删除插件必须重启后端**：工具装配来自进程内 PluginRegistry。
- **壳 saveConfig 覆盖 ui.model**：saveConfig 以磁盘最新为底，只覆盖 nuomi.*（否则切模型后跳回旧模型）。
- **切换模型后工具集不变**：`/pet/models/switch` 必须 `manager.release(agent_id)` 让下次对话重建。
- **LLM 幻觉调用旧模型工具名**：曾用"模型专属会话（无旧历史）"根治；**2026-10-04 废除**（桌宠=纯表现层拦截工具调用，会话与模型解耦），幻觉风险由会话切换/清空兜底。
- **python websockets 连 octop 8088 WS 恒 403**：curl/aiohttp 可通；真切 WS 用 aiohttp。
- **市场技能 frontmatter 质量**：description 裸冒号 → harness 安全跳过（见 §5）。
- **antd5 grid 卡片等高**：grid List 渲染为 `.ant-row > div`（**无 `.ant-list-items`**，也无 `.ant-col` 类——列是原生 div + colStyle）；Row 默认 `align: top` 列不拉伸，必须 CSS `align-items: stretch`；`nuomi-grid` 类若挂在 List 容器上选择器写 `.nuomi-grid .ant-row`，若挂在 Row 自身（桌宠页）写 `.ant-row.nuomi-grid`——两形态都要覆盖（frontend/src/index.css `.nuomi-grid` 块已兼容）。
- **壳加载的是 build 产物**：控制面板指向 `http://127.0.0.1:8000/console/`（后端挂 dist），**不是** 5173 vite dev；改前端验证要走 build + 强制刷新（`?v=n` nonce），5173 的 vite proxy 未配置好也不影响壳。

## 7. 项目主线清单（用户需求 → 状态）

> 主线项按用户原始清单 + 实际扩展整理；✅=已完成并验证，⬜=未做/暂缓。状态以最新对话拍板为准。

| # | 主线项 | 状态 | 说明 / 落地点 |
|---|---|---|---|
| 1 | 插件市场 | ✅ | octop 无独立在线插件商店；市场闭环 = 内置随包 + SkillHub + zip/Git 导入（见 #4/#9） |
| 2 | 连接器添加 | ✅ | 控制台增删改/重载（MCP 协议，产品命名统一「连接器」）；`connectors.json` 权威 + `NUOMI_CONNECTORS` 首次播种 |
| 3 | 工作区单根化 + 数据迁移 | ✅ | `NUOMI_HOME=/Users/superman/Nuomi` 即数据根（**无 NUOMI_WORKSPACE**）；skills/plugins/skill_packages/models/connectors.json/env.json/nuomi-state.json 全部在内 |
| 4 | 插件导入 | ✅ | `POST /plugins/import`（zip）+ `POST /plugins/import-git`（Git 仓库，浅克隆/50MB/已存在拒绝） |
| 5 | 技能导入 | ✅ | `POST /skills/import`（zip）+ `POST /skills/import-git`；实测 anthropics/skills 真实仓库 |
| 6 | 对话框大改动（参考 octop） | ⬜ 暂缓 | 用户 2026-10-04 拍板先不做；已调研 octop dashboard Chat 组件（MessageBubble/MessageList/ChatInput/Trajectory 系列等），改动范围待定 |
| 7 | 桌宠模型导入 | ✅ | 种子机制：仓库仅留 `assets/models/2D/hiyori`，扫描幂等播种到工作区 `models/2D/`；内置模型页只读不可删 |
| 8 | 桌宠模型升级（现太呆板） | ⬜ 暂缓 | 现为纯动作/表情表现层（Live2D）；升级方案未定 |
| 9 | 技能市场（SkillHub） | ✅ | search 循环翻页（服务端固定 10 条/页）+ slug 去重；rankings/skillsets；单技能安装/技能集建包；`requires_api_key` 标注 |
| 10 | 内置技能展示 + 环境变量 | ✅ | `GET /skills/builtin`（24 个，只读）+ `GET|PUT /settings/env`（env.json → os.environ，技能 API key 配置） |
| 11 | 会话与模型解耦 | ✅ | 桌宠=纯表现层（拦截对话工具调用做动作）；切模型不换会话；default 线程已删；会话权威 `nuomi-state.json` |
| 12 | 管理页 UI 统一卡片化 | ✅ | 专家/技能（已安装+市场）/桌宠/插件/连接器五页统一等宽卡片网格 + 首字头像 + 角标 + 描述省略/tooltip + **同行严格等高**（§6 踩坑） |

## 8. 遗留事项 / 下一步

- [ ] **对话框大改动**（暂缓，见主线 #6）：改动范围待用户拍板
- [ ] **桌宠模型升级**（暂缓，见主线 #8）：表现层增强/新模型表现力
- [ ] **桌宠直接说话（TTS）**（用户已拍板待办）：桌宠现为纯动作/表情层；TTS 客户端代码（`js/tts-client.js`、`TTSStreamProcessor`）已保留未删，届时恢复"收到回复文本→TTS 播报"入口
- [ ] **octop WS 迁移**（暂缓）：事件帧已对齐，通道仍 HTTP SSE；注意 websockets 403 坑
- [ ] **HITL 工具审批流**（当前不启用）：octop_harness 自带 HumanInTheLoopMiddleware，未来有高风险工具再开启
- [ ] **糯米人设源头约束**：回复仍会出现 `<开心>` 等尖括号标签，已决定从源头治理，未实施
- [ ] 壳启动时自动拉起 uvicorn
- [ ] 前端 bundle 1MB 可 code-split
- [ ] 模型资产补全：cat（hijiki）动作文件缺失；表情插件（expressions 为空）待有数据可测
- [ ] 模型插件工具语义：工具 description 只有动作名，靠 `_MOTION_ZH` 映射，可再打磨

## 9. 关键 git 历史

```
027c584  桌宠接入（myspy 二次开发）        → 5602480 删 myspy 大脑
ba7bce6  桌宠协议层（emotion，后废除）      → 6c0711a 能力域：插件/技能接入 octop-harness
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
e65477d  插件/连接器页卡片化（桌宠模型橙色标、传输协议角标、清「服务器」文案）
5e3a268  卡片等高 CSS（首版选择器未命中，见 §6 踩坑）
dc242b1  卡片等高修复：antd5 grid 列为裸 div，.ant-row > div（amend 掉误提交的 .vite 缓存）
3492b20  桌宠页等高：补 .ant-row.nuomi-grid 形态 + align-items: stretch
```

开发规范：`make lint`（ruff）/ `make typecheck`（mypy），CI 在 .github/workflows。
