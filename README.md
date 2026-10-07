# 糯米 Nuomi

**住在你电脑里的 AI 人格**——灵感来自《魔幻手机》：既是数字生命（有形象、有情绪、会变装），又能干活（工具、记忆、技能）。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 大脑（机制层） | [octop-harness](https://pypi.org/project/octop-harness/) | Agent 运行时（LangChain Deep Agents）：循环/工具/记忆/checkpointer/技能/MCP |
| 业务层 | Python + FastAPI | 专家/会话/能力领域服务（自研）；插件三层能力（工具注册 / 事件订阅发布 / 聊天卡片 UI） |
| 形象层（AI 数字人壳） | shells/nuomi-avatar/（自研，Electron + three.js + @pixiv/three-vrm） | 纯表现层：VRM 3D 渲染、情绪表情、流式字幕、工具执行状态；大脑全在 backend（详见 [shells/nuomi-avatar/README.md](shells/nuomi-avatar/README.md)） |
| 存储 | SQLite | agents/threads/thread_messages 投影表（对齐 Octop schema，已建成） |

> **AI 数字人模型版权说明**：VRM 模型资产在工作区（数据根）的 `models/3D/`，不入库。
> 数据根默认 macOS `~/Library/Application Support/Nuomi`（其它平台 `~/.nuomi`），可用 `.env` 里的 `NUOMI_HOME` 覆盖。
> 用户自导入模型按各自 License 使用（示例模型 6309260419351179234.vrm 为 CC0）；
> 若需分发项目请使用宽松 License 的模型。动作资产为 Mixamo 导出的 `.vrma` 动画文件（`shells/nuomi-avatar/assets/animations/`）。

## 快速开始

依赖不入库，全新克隆后先装依赖（Python 3.11/3.12 + [uv](https://docs.astral.sh/uv/)，Node.js 20+，CI 用 22）：

```bash
cd backend && uv sync && cd ..                    # 后端 venv → backend/.venv（uv 管理，无 pip）
cd frontend && npm ci && cd ..                    # 控制台前端构建依赖
cd shells/nuomi-avatar && npm install && cd ..    # AI 数字人壳（Electron）
```

配置 LLM：把**仓库根**的 `.env.example` 复制为**仓库根**的 `.env`，填上 `LLM_API_KEY`：

```bash
cp .env.example .env
```

> 为什么是仓库根、不是 `backend/.env`：`backend/app/config.py` 用 `REPO_ROOT = Path(__file__).resolve().parents[2]`
> （该文件 → `backend/app/config.py` 往上两级 = 仓库根）定位 `env_file`，**只读 `<仓库根>/.env`**；
> 而壳/uvicorn 的工作目录都是 `backend/`，很容易想当然地把 `.env` 放进去 —— 那样会被静默忽略，
> 表现为「配了 key 却提示未设置」。也可以完全不写 `.env`，改在控制台「设置 → 大模型」页配置 Provider
> （`<数据根>/providers.json` 为运行时权威）。

启动：

```bash
make start   # 一键启动 AI 数字人壳（Electron 数字人窗口 + 控制面板），后端自动拉起（ensureBackend）
make web     # 调试控制台（vite dev，:5173，代理 /api → :8000）
```

> `make start` / `make desktop` 会**先执行 `make build` 构建前端**再拉起壳。原因：壳的控制面板不是 vite dev
> server，而是后端 StaticFiles 挂载的 `frontend/dist`（`/console/`，见 `backend/app/main.py`），而 `dist/`
> 被 gitignore、不入库 —— 全新克隆没有 `dist` 时，`main.py` 会退回 `frontend/` 源码根，`/console/` 返回源码
> `index.html`（它引用 `/src/main.tsx` → 404），控制面板白屏；改了前端忘了 build，则会出现「浏览器（vite dev）
> 里对、桌面壳里不对」。所以这条依赖写成了 Makefile 的强前置（`desktop: build`），用几秒构建时间换掉这两类坑。
> `make web` 走 vite dev 免构建；但若要在浏览器里访问 `http://127.0.0.1:8000/console/`，仍需先 `make build`。

- 控制面板：http://127.0.0.1:8000/console/（壳内嵌窗口 / 浏览器访问均可）
- 控制台导航：对话 + 能力（专家 / 插件 / 技能 / 连接器 / 知识库）+ 系统（AI 数字人 / 设置）
- AI 数字人开关：控制台「AI 数字人」页，关闭即销毁数字人窗口（开关联动 vrm-avatar 插件启停）

### 对话（SSE 流式）

> 本机回环 API 有写操作鉴权：`/api/*` 的 `POST/PUT/PATCH/DELETE` 需带 `X-Nuomi-Token`，
> 并校验 `Host`/`Origin` 白名单（见 `backend/app/infra/local_guard.py`）。
> token 每次进程启动随机生成，同源客户端可从 `GET /api/session-token` 取；控制台与数字人壳已自动携带。

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/api/session-token | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -N -X POST http://127.0.0.1:8000/api/agents/{agent_id}/chat \
  -H "Content-Type: application/json" \
  -H "X-Nuomi-Token: $TOKEN" \
  -d '{"messages": "你好", "thread_id": "test"}'
```

事件流：`token`（流式文字）→ `reasoning`（深度思考）→ `tool_call_chunk`/`tool_result`（工具执行，带 `plugin_id`）→ `done`（完整回答）。
插件事件层另发布 `conversation.started / conversation.completed`（供 TTS 播报等订阅）。

### 验证

```bash
cd backend && .venv/bin/python probe_harness.py   # harness 冒烟：DeepSeek 对话 + Octop 插件加载
```

会真实调用一次 LLM（需 `.env` 里有可用 key）。其中「Octop 插件加载」一节需要一个 Octop 源码 checkout
提供示例插件：默认取 nuomi 仓库的同级目录 `../Octop`，也可用 `OCTOP_SRC=/path/to/Octop` 指定；
找不到时该节打印 `[skip]` 并继续验证对话链路。

### 模拟 MES 连接器（可选演示数据）

「糯米 × 制造业系统联动」作品集的演示链路，不依赖任何真实工厂系统：

```bash
python3 scripts/gen_mes_data.py      # 生成模拟 CNC 机加工 MES 库（connectors/data/mes.db，90 天，固定 seed 可复现）
backend/.venv/bin/python scripts/check_mes_connector.py   # MCP 客户端验证 6 个只读工具
```

在控制台「连接器」页新建 `mes` 连接器：传输方式=**本地进程**，命令=`backend/.venv/bin/python`，
参数=`connectors/mes_connector.py`；对话时挂载即可问「昨天 A 线生产情况」「设备状态 / 良率趋势」。
接真实工厂系统：把环境变量 `MES_DB_PATH` 指向真实 MES 只读数据库即可，连接器代码不动。

**写路径 + 人工审批（HITL）**：连接器还带一个报工写工具（`mes_submit_work_report`，写入独立的
`connectors/data/mes_operations.db` 台账库）。报工是高风险写操作，糯米侧默认**每次都要人工批准**才执行——
对话中让糯米报工会先弹审批卡片（显示工具与参数），点「批准」才落库，点「拒绝」则丢弃，全程有据可查：
```bash
python3 scripts/e2e_hitl_test.py      # 端到端验证：触发审批 → 批准落库 → 拒绝不落库 → 只读回归
```
演示话术：`帮我把工单 WO-A-2026-0011 报工，完工数量 60 件`（对话会暂停等你在卡片上批准/拒绝）。

## 架构

```
transport（FastAPI 路由） → domain（领域服务） → infra/harness（适配层） → octop-harness（运行时）
```

领域语言一等公民（专家/会话/能力），机制语言当基础库（harness）。详见 `docs/architecture-refactor-harness.md`。

## 路线图

- [x] R1-R3：推倒重来 + harness 适配层 + SSE 对话 API
- [x] M3-M5：Agent 生命周期 / 会话存储（threads+消息投影表）/ 插件（2026-10-05）
- [x] M6：技能+连接器+知识库（2026-10-04；OCR 用户叫停暂缓）
- [x] M7-M8：AI 数字人形象层（VRM 3D / 模型与动作资产管理 / 热切换）+ 工具执行可视化（2026-10-05）
- [x] 插件三层能力：工具注册 / 事件订阅发布（EventBus）/ 聊天卡片 UI（对齐 octop，2026-10-05）
- [x] 轨迹可观测性：Langfuse 集成（本地自托管，设置页配置，2026-10-05）
- [x] 本机安全基线 + 质量门禁（守卫/脱敏/上传限流/`make check` 含前端测试，2026-10-06）
- [x] 可移植性（`make start` 先建前端、`.env` 位置修正、LICENSE、个人路径清零，2026-10-06）
- [x] 记忆可视化（对话页侧栏「我记住了你什么」抽屉：查看 + 遗忘，2026-10-06；P0-6 随导航三分组移入对话侧栏）
- [x] 设计 token 单一来源 + 前端测试基建（vitest 60 例，2026-10-06）
- [x] 控制台视觉统一 + 信息架构精简（2026-10-06）：卡片体系统一（知识库卡形态）、
      插件/技能市场独立页（页内按钮进入 + 面包屑返回）、专家运行状态真实性、
      导航三分组 + 可点击面包屑、文案精简（连接器不再暴露协议术语）、删存储页、
      chat 页视觉统一（气泡/输入区/会话列表）
- [ ] 待办：见 [`docs/next-steps.md`](docs/next-steps.md)（下一步该做什么：架构/前端/产品）与
      [`docs/HANDOVER.md`](docs/HANDOVER.md) §8（状态台账，含"明确不做"）
- 🚫 **不做分发**（2026-10-06 拍板）：无发布到其他 Mac 的计划 → 签名/公证/自动更新/首启向导不做

## 文档

**只有这 9 份，新增前先想清楚为什么现有文档装不下**（2026-10-06 清理了 7 份描述"已不存在架构"的文档）：
文档一旦描述不存在的东西，就会主动误导人和 agent —— 本项目已被 `DESIGN.md`、
`placeholder-priorities.md`（已删）、`frontend-architecture.md`（已删）各坑过一次。

| 文档 | 作用 | 谁该看 |
|---|---|---|
| [`AGENT.md`](AGENT.md) | **项目记忆**：定位/决策/架构/环境事实/路线图/每次改动的验证记录 | 所有人和 agent（改代码前先读） |
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | **交接**：启动手册、API 清单、已验证链路、**踩坑记录**、状态台账、git 历史 | 接手/排障时 |
| [`README.md`](README.md) | 入口：技术栈、快速开始（含全新克隆）、架构一句话、路线图 | 第一次接触 |
| [`docs/architecture-refactor-harness.md`](docs/architecture-refactor-harness.md) | v0.13 为什么用 octop-harness 当机制基础库 | 想动架构前 |
| [`DESIGN.md`](DESIGN.md) | 前端设计方针 + token 体系（唯一定义处 `frontend/src/theme.ts`）+ 欠账 | 改界面时 |
| [`docs/avatar-protocol.md`](docs/avatar-protocol.md) | 数字人/表现层与后端的对话协议（octop 原生事件帧） | 做表现层/接协议时 |
| [`docs/knowledge-base-research.md`](docs/knowledge-base-research.md) | 知识库调研（含 OCR 方案 §8） | 做 OCR 前 |
| [`docs/knowledge-frontend-design.md`](docs/knowledge-frontend-design.md) | 知识库**API 契约**（代码注释直接引用） | 改知识库 API/页时 |
| [`docs/next-steps.md`](docs/next-steps.md) | **下一步该做什么**：架构是否合理 / 前端界面 / 产品发展（含优先级 P0-P2 与「明确不做」） | 决定下一步做什么时 |

**规矩**：①写完的**调研/设计稿**，结论吸收进 `AGENT.md`/`HANDOVER.md` 后**删掉原稿**（别留"历史参考"，
它们会腐烂成假信息）；②文档与实现不一致时**以实现为准并当场改文档**；③写进文档前先 grep 确认
描述的对象还存在。

## 许可证

本项目以 MIT 许可证开源，全文见仓库根的 [LICENSE](LICENSE)（Copyright (c) 2026 Nuomi contributors）。

依赖与第三方资产按各自的 License 使用：octop-harness 为开源依赖；
数字人壳自研（Electron / three.js / @pixiv/three-vrm 等运行时依赖见 `shells/nuomi-avatar/package.json`）；
VRM 模型与 `.vrma` 动作资产见上文「AI 数字人模型版权说明」。
