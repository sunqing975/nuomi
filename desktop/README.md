# nuomi 桌宠壳（desktop/）

> 本项目是 **nuomi** 的桌宠表现层。基于开源项目 [myspy](https://github.com/zhangbo124/myspy)（MIT）二次开发。

## 定位

**壳模式**：本目录只做表现（形象渲染、情绪表情、字幕、输入、拖拽），**不做任何大脑逻辑**。

- 大脑 = nuomi 后端（`../backend/`，基于 octop-harness）
- 对话、插件、技能、MCP、记忆 全部由后端管理
- 桌宠通过 OpenAI 兼容端点与后端通信（`config.json → llm`）

```
┌─────────────────────────────┐        ┌──────────────────────────┐
│  desktop/（纯表现层）        │  HTTP  │  backend/（octop 大脑）   │
│  Live2D 渲染 · 情绪 · 字幕   │ ─────► │  专家 · 插件 · 技能 · MCP  │
│  输入框 · 拖拽               │        │  · 记忆 · 工具调用         │
└─────────────────────────────┘        └──────────────────────────┘
```

## 与上游 myspy 的关系

- **来源**：myspy（MIT License）—— Electron + Live2D/VRM 桌面宠物
- **原始完整代码**：本仓库 git 历史 commit `027c584`（M7）包含 myspy 全量代码；上游仓库见 [myspy](https://github.com/zhangbo124/myspy)
- **二次开发**：适配 macOS、接入 nuomi 后端，并按"纯表现层"标准删除了 myspy 自带大脑

### 已删除的 myspy 大脑模块（2026-10）

| 模块 | 原文件/目录 | 能力去向 |
|---|---|---|
| 插件系统 | `js/core/plugin-manager.js`、`plugins/` | 后端 Octop 插件 |
| MCP 服务 | `js/mcp/`、`mcp/` | 后端 Octop MCP |
| Skill 人设注入 | `skills/`、`js/ai/` | 后端 Octop 专家人格 |
| LLM 客户端 | `js/llm-client.js` | 后端 OpenAI 兼容端点 |
| 截图/视觉（BERT） | `js/screenshot-manager.js`、`full-hub/` | 暂未接回 |
| AI 日记 | `js/diary-manager.js`、`AI记录室/` | 后端记忆 |
| 对话历史持久化 | `app.js` 历史加载/保存 | 后端 harness checkpointer |

保留的能力：Live2D/VRM 渲染、情绪标签→表情映射、流式字幕、输入框、窗口拖拽、模型切换、控制面板（webui，待 P3 重写为 Octop 控制台）。

## 快速开始

### 环境要求

- Node.js 18+
- nuomi 后端已启动（`cd ../backend && .venv/bin/python -m uvicorn app.main:app --port 8000`）

### 安装与运行

```bash
npm install
npm start          # 启动桌宠 + 控制面板
```

### 配置（config.json）

```jsonc
{
  "llm": {                       // 对接 nuomi 后端
    "api_url": "http://127.0.0.1:8000/api/v1",
    "api_key": "local",
    "model": "nuomi"
  },
  "nuomi": {                     // 壳模式开关
    "shell_only": true,
    "disable_plugins": true,
    "disable_mcp": true,
    "disable_skill_injection": true,
    "disable_history": true
  }
}
```

## 项目结构

```
desktop/
├── main.js              # Electron 主进程（窗口、IPC）
├── app.js               # 渲染进程（对话流、情绪、字幕）
├── config.json          # 配置（对接 nuomi 后端）
├── 2D/                  # Live2D 模型（hiyori 等）
├── 3D/                  # VRM 模型
├── js/
│   ├── model/           # 模型加载与交互（Live2D/VRM）
│   ├── tts-client.js    # TTS 客户端（默认关闭，P2/P4 再接）
│   ├── asr-client.js    # ASR 客户端（默认关闭）
│   └── emotion-expression-mapper.js  # 情绪→表情映射
├── webui/               # 控制面板（旧 myspy 设置页，P3 重写）
└── libs/                # 第三方库
```

## License

MIT（myspy 为 MIT 开源依赖；上游说明见其仓库）
