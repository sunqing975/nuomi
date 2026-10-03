# 深补占位功能 · 优先级清单

> 排序逻辑：**演示可见度 × 被追问概率 ÷ 实现成本**。
> P0 = 不能让演示崩；P1 = 让演示 wow；P2 = 锦上添花。
> 配套文档：`docs/demo-script.md`。

## P0 · 演示前必做（1–2 天）

| # | 项目 | 现状（出处） | 为什么 | 工作量 | 验收标准 |
|---|---|---|---|---|---|
| 1 | **release 打包全链路验证** | AGENT.md：「release 打包全链路（tauri build）与桌面端首启人工验收待做」 | 演示形态 = 桌面版，打包不过 = 现场崩 | 1–2 天 | `make start` 从零拉起完整桌面版，退出全回收；首启向导人工验收 |
| 2 | **STT 接真实语音 API** | README：「STT 接口化占位」；`plugins/voice` transcribe 为占位 | 麦克风按钮是可见 UI，点了没反应 = 追问靶子 | 0.5–1 天 | 点麦克风说话 → 文字进输入框（豆包语音 / Whisper，adapter 形态） |
| 3 | **演示降级方案** | `.env` 已有 llama 本地端点配置 | DeepSeek API 中断 = 演示灾难 | 0.5 天 | 断网 / 欠费场景一键切本地模型完成纯对话演示 |

## P1 · 亮点深化（1–2 周）

| # | 项目 | 现状 | 为什么 | 工作量 | 验收标准 |
|---|---|---|---|---|---|
| 4 | **文件面板 ↔ fs 工具联动 + 权限选择器** | Phase 5 待办（AGENT.md：「前端文件面板接 fs 工具、bash tool 事件前端展示、permission 选择器（P1）」） | 执行层是 Phase 5 核心卖点，UI 没接上 = 面试官看不到 | 2–3 天 | 文件面板实时反映 fs 写入；工具调用前显示权限选择 |
| 5 | **subagent 委托** | Phase 5 规划第 2 项未做（tool-subagent） | Harness 差异核心是 subagent 编排，做了才有「协作」叙事 | 3–5 天 | 模型主动 spawn 子 agent 执行子任务并返回结果 |
| 6 | **mem0 真实端到端** | AGENT.md P2 待办：「设置页 provider 选择 UI、真实 Mem0 服务端到端验证」 | 记忆 Provider 化是 2026-10-02 的新架构故事，跑通才是真亮点 | 1–2 天 | openmemory / 自托管 mem0 完成增删改查 + 快照注入 |
| 7 | **Supervisor 二层** | 现为单层 LLM 路由 | 「多智能体」被追问深度时的短板 | 2–3 天 | companion / researcher 下挂子任务；或明确讲单层取舍 |

## P2 · 提交前可选

| # | 项目 | 现状 | 工作量 |
|---|---|---|---|
| 8 | compaction / spill 事件化 | Phase 5 规划第 3 项 | 3–5 天 |
| 9 | credentials / attachment / deliverables | Phase 5 规划第 5 项 | 3–5 天 |
| 10 | schedule / todo 定时调度 | Phase 5 规划第 6 项 | 2–3 天 |
| 11 | i18n en-US | 已留 i18n 架构（zh-CN 约 89 处待迁移） | 1–2 天 |
| 12 | TTS 换豆包 API | 现为 macOS `say`（可用） | 0.5 天 |

## 决策建议

- **时间 < 1 周**：只做 P0 三项 + P1 第 4 项（文件面板联动是 demo Step 4 的 UI 前提）。
- **时间 2–3 周**：P0 + P1 全做；**subagent 与 mem0 优先**——它们都是「新架构故事」，面试叙事价值最高。
- **每项完成后**：按项目惯例在 AGENT.md 追加验证记录（pytest / 实测结论 / 踩坑）。
