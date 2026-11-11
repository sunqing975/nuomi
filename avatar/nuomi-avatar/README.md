# nuomi-avatar —— 糯米 AI 数字人表现层

> **nuomi** 的 AI 数字人表现层。Electron + three.js + @pixiv/three-vrm 自研实现（上游 nuomi-avatar 的 Live2D 已全部移除，仅保留 Electron 壳框架）。

## 定位

**壳模式**：本目录只做表现（VRM 形象渲染、动作/表情播放、流式字幕、拖拽），**不做任何大脑逻辑**。

- 大脑 = nuomi 后端（`../backend/`，基于 octop-harness）
- 对话、插件、技能、连接器（MCP）、记忆 全部由后端管理
- 数字人通过 OpenAI 兼容端点与后端通信（`config.json → llm`）

```
┌─────────────────────────────┐        ┌──────────────────────────┐
│  nuomi-avatar/（纯表现层）   │  HTTP  │  backend/（octop 大脑）   │
│  VRM 渲染 · 动作 · 表情      │ ─────► │  专家 · 插件 · 技能 · MCP  │
│  字幕 · 拖拽                │        │  · 记忆 · 工具调用         │
└─────────────────────────────┘        └──────────────────────────┘
```

## 能力

- **VRM 模型渲染**：three.js + @pixiv/three-vrm，透视相机 + 灯光 + 阴影；**尺寸归一化**（加载后统一缩放到 1.4m，脚底对齐）（`js/model/vrm-model-setup.js`）
- **动作播放**：`assets/animations/*.vrma` 自动扫描注册（放文件即出现、删即消失）；**只播 VRMA**，缺失 console.warn；`idle.vrma` 存在时无动作自动循环待机（`js/model/vrm-model-adapter.js`）
- **表情播放**：模型 blend shape 直接控制（大小写不敏感索引，标准名 neutral/aa/ih/.../blinkLeft/blinkRight）
- **工具执行状态表情**：后端 SSE `avatar_status`（thinking/working/idle）→ 对应表情，对话"干活中"可视化
- **流式字幕**：后端 SSE → 字幕
- **模型热切换**：控制台切模型 → IPC switch-model → 页面重载加载新模型（不重启进程）
- **自动拉起后端**：`main.js ensureBackend()` 启动时检测 `/api/health`，未就绪自动 spawn uvicorn（把 pid 写到仓库根 `.logs/backend.pid`，壳退出**不停**后端）
- **单实例**：`app.requestSingleInstanceLock()`——双开 = 双数字人窗口 + 双后端抢 :8000，所以第二个实例会把已有窗口 show/focus 后自己退出
- **模型路径自愈**：`config.json` 的 `ui.model_path` 是绝对路径，换机器必然失效；启动时路径不存在则向后端 `GET /api/avatar/models` 取当前激活模型并回写（见「打包与分发」）

## 快速开始

### 环境要求

- Node.js 18+
- nuomi 后端（**无需手动启动**——壳 `ensureBackend` 自动拉起；单独跑后端排查用：`cd ../backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`）
- 打包（`npm run pack` / `npm run dist`）仅支持 **macOS**：图标链依赖系统自带 `sips` / `iconutil`

### 安装与运行

```bash
npm install
npm start          # 启动数字人窗口（自动拉起后端）
```

### 打包与分发（2026-10-06 接入 electron-builder）

```bash
npm run icon       # 生成 build/icon.icns（sips + iconutil，产物已 gitignore）
npm run pack       # 快速冒烟：产出 dist/mac-arm64/Nuomi.app（不签名、不出安装包）
npm run dist       # 出安装包：dist/Nuomi-1.0.0-arm64.dmg + .zip
```

- `build.files` 是白名单：只打进 `main.js / app.js / index.html / js / css / assets / libs / 配置 json + 生产依赖`；
  `tools/`（含 12MB FBX2glTF）、`scripts/`、`docs/`、devDependencies 都不入包（`asar: true`）。
- 沙箱/离线环境可用 `ELECTRON_BUILDER_CACHE=$PWD/.electron-builder-cache npm run pack`，
  避免写 `~/Library/Caches/electron-builder`。
- ⚠️ **当前产物不能直接对外分发**，`mac.identity: null` / `notarize: false` 是刻意设置（手上没有证书和更新服务器）。
  正式发布前必须补齐：
  1. **codesign**：配置 Developer ID Application 证书（`mac.identity`）并开启 hardened runtime；
  2. **notarize**：`mac.notarize` 打开 + Apple ID / app-specific password（否则用户首次打开会被 Gatekeeper 拦）；
  3. **自动更新**：`electron-updater` + 更新服务器（`publish` 配置 + 主进程 autoUpdater 接入）；
  4. **可写配置**：打包态 `config.json` 在 `app.asar` 内只读 —— 控制台切模型后无法持久化，
     需要把配置落到 `app.getPath('userData')`（当前靠 `--nuomi-model=` 参数保证「本次启动能渲染」）；
  5. **自带后端**（最根本的一条）：当前产物**不含后端**，`ensureBackend()` 按
     `path.join(__dirname, '..', '..', 'backend')` 找 venv，而打包态 `__dirname` 在 `app.asar` 内，
     该路径不存在 → 退回 `python3` 并以不存在的 cwd 启动 → 失败并等满 30s。
     所以**打包产物只在「后端已经在跑」时可用**（本机日常就是这种情况）。要真正独立运行，
     需要把 Python 运行时装进包（PyInstaller / embeddable Python + 启动参数），或改成把后端地址
     指向一个本地/远程常驻服务。

> **决策（2026-10-06，用户拍板）：不做分发。** 没有把糯米发布到其他 Mac 的计划，而发布需要
> 花钱买 Apple Developer 账号（签名 + 公证），因此上面 **1–3 项（codesign / notarize / 自动更新）
> 明确不做**，第 5 项也不做。打包链保留的价值是：能在本机验证打包配置、出图标、跑单实例锁与
> CSP 的真实验证。**日常使用一律 `make start`**（壳 + 自动拉起后端），不走 `.app`。
> 若将来要做独立 App，从上面第 5 条开始。

### 配置（config.json）

```jsonc
{
  "llm": {                       // 对接 nuomi 后端
    "api_url": "http://127.0.0.1:8000/api/v1",
    "api_key": "local",
    "model": "nuomi"
  },
  "ui": {
    "avatar_enabled": true,      // 数字人开关（控制台「AI 数字人」页读写，缺省开）
    "model": "6309260419351179234",
    // 数据根下模型资产的绝对路径。仓库里这一项留空（不写死任何人的家目录）：
    // 启动时 main.js 会校验它，不存在就向后端 /api/avatar/models 取激活模型并回写
    // 这里（不需要手改）。示例形式：<NUOMI_HOME>/models/3D/<模型名>.vrm
    "model_path": ""
  }
}
```

> 仓库内**不含**任何 `.vrm` 资产（模型在工作区 `models/3D/`）。所以拿到新机器时
> `ui.model_path` 指向的旧路径必然不存在——壳会询问后端拿真实路径，拿不到则弹可读错误框，
> 不会静默白屏。

## 安全基线

数字人窗口是 `nodeIntegration: true`（渲染进程要用 `fs` 读本地 VRM、`require` three.js），
本次**刻意不做** contextIsolation + preload 迁移（改动面覆盖 app.js + js/** 约 6k 行），
改为三道低成本闸门：

- `index.html` 的 CSP：只允许 `'self'` / `file:` / `http://127.0.0.1:*`（挡远端脚本）
- `main.js lockNavigation()`：两个窗口的 `will-navigate` + `setWindowOpenHandler` 白名单
- 控制台窗口本身就是 `nodeIntegration:false + contextIsolation:true`

取舍边界与将来收紧要动哪些文件，写在 `main.js` 顶部注释里。

## 项目结构

```
nuomi-avatar/
├── main.js              # Electron 主进程（窗口、IPC、config watch、ensureBackend、单实例锁、导航封锁）
├── app.js               # 渲染进程（模型加载、动作/表情播放、字幕）
├── index.html           # 数字人窗口页面（含 CSP meta）
├── config.json          # 配置（对接 nuomi 后端 + 表现层偏好）
├── scripts/make-icon.sh # icon.png → build/icon.icns（npm run icon）
├── assets/
│   └── animations/      # .vrma 动作动画（自动扫描注册）
├── js/
│   ├── model/           # VRM 模型加载/适配/扫描
│   ├── tts-client.js    # TTS 客户端（默认关闭）
│   ├── asr-client.js    # ASR 客户端（默认关闭）
│   └── emotion-expression-mapper.js  # 情绪→表情映射
└── tools/fbx2vrma/      # Mixamo FBX → VRMA 转换工具链（**不打进安装包**）
```

## License

MIT
