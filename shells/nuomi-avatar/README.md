# nuomi-avatar —— 糯米 AI 数字人表现层（desktop/）

> **nuomi** 的 AI 数字人表现层。Electron + three.js + @pixiv/three-vrm 自研实现（Live2D 与上游代码已全部移除，仅保留 Electron 壳框架）。

## 定位

**壳模式**：本目录只做表现（VRM 形象渲染、动作/表情播放、流式字幕、拖拽），**不做任何大脑逻辑**。

- 大脑 = nuomi 后端（`../backend/`，基于 octop-harness）
- 对话、插件、技能、连接器（MCP）、记忆 全部由后端管理
- 数字人通过 OpenAI 兼容端点与后端通信（`config.json → llm`）

```
┌─────────────────────────────┐        ┌──────────────────────────┐
│  desktop/（纯表现层）        │  HTTP  │  backend/（octop 大脑）   │
│  VRM 渲染 · 动作 · 表情      │ ─────► │  专家 · 插件 · 技能 · MCP  │
│  字幕 · 拖拽                │        │  · 记忆 · 工具调用         │
└─────────────────────────────┘        └──────────────────────────┘
```

## 能力

- **VRM 模型渲染**：three.js + @pixiv/three-vrm，透视相机 + 灯光 + 阴影（`js/model/vrm-model-setup.js`）
- **动作播放**：`assets/animations/*.vrma` 自动扫描注册；无 vrma 时回退手写骨骼动画（`js/model/vrm-model-adapter.js`）
- **表情播放**：模型 blend shape 直接控制（大小写不敏感索引，标准名 neutral/aa/ih/.../blinkLeft/blinkRight）
- **流式字幕**：后端 SSE → 字幕
- **窗口拖拽 / 模型切换**：config.json `ui.model` 变化自动重载（后端写入）

## 快速开始

### 环境要求

- Node.js 18+
- nuomi 后端已启动（`cd ../backend && .venv/bin/python -m uvicorn app.main:app --port 8000`）

### 安装与运行

```bash
npm install
npm start          # 启动数字人窗口
```

### 配置（config.json）

```jsonc
{
  "llm": {                       // 对接 nuomi 后端
    "api_url": "http://127.0.0.1:8000/api/v1",
    "api_key": "local",
    "model": "nuomi"
  },
  "ui": {
    "avatar_enabled": true,      // 数字人开关（控制台「模型」页读写，缺省开）
    "model": "6309260419351179234",
    "model_path": "/Users/superman/Nuomi/models/3D/6309260419351179234.vrm"
  }
}
```

## 项目结构

```
nuomi-avatar/
├── main.js              # Electron 主进程（窗口、IPC、config watch）
├── app.js               # 渲染进程（对话流、动作/表情播放、字幕）
├── config.json          # 配置（对接 nuomi 后端 + 表现层偏好）
├── assets/
│   └── animations/      # .vrma 动作动画（自动扫描注册）
├── js/
│   ├── model/           # VRM 模型加载/适配/扫描
│   ├── tts-client.js    # TTS 客户端（默认关闭）
│   ├── asr-client.js    # ASR 客户端（默认关闭）
│   └── emotion-expression-mapper.js  # 情绪→表情映射
└── tools/fbx2vrma/      # Mixamo FBX → VRMA 转换工具链
```

## License

MIT
