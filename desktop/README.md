# 糯米桌面端（Tauri 薄壳）

设计取舍（与路线图一致）：**后端在 FastAPI，Rust 层保持极薄**——
窗口 + WebView 加载前端构建产物，所有对话/插件逻辑复用 Web 端 API。
桌面端做本地开发测试与最终打包，Web 仍是主推形态。

## 结构

```
desktop/src-tauri/
├── Cargo.toml          # tauri 2 + tauri-plugin-http + serde
├── tauri.conf.json     # 窗口 + frontendDist: ../../frontend/dist（Tauri2 字段：productName/identifier）
├── build.rs
├── icons/icon.png      # 应用图标（512x512 蓝底团子，脚本生成）
└── src/
    ├── lib.rs          # tauri Builder 启动（Tauri2 模板结构）
    └── main.rs         # 调 lib::run()
```

## 运行

前置：Rust 工具链（rustc/cargo ≥1.7x）、tauri CLI（cargo-tauri）、系统 WebView（macOS 自带 WKWebView）。

```bash
# 1. 构建前端产物（tauri 加载 frontendDist）
cd frontend && npm run build && cd ..

# 2. 后端保持运行（127.0.0.1:8000，见根 README）

# 3. 桌面端开发运行（窗口加载 frontend/dist，API 走 localhost:8000）
cd desktop/src-tauri && ~/.cargo/bin/cargo-tauri dev
# 首次编译全部依赖（数分钟）；正式打包：
~/.cargo/bin/cargo-tauri build
```

## 踩坑记录（Phase 5 第四轮）

- `tauri.conf.json` Tauri2 不接受顶层 `name`/`description`（用 `productName` + `identifier`）
- Tauri2 模板要求 `src/lib.rs`（lib 目标）+ `src/main.rs` 调 lib（缺 lib.rs 编译报错）
- `frontendDist` 相对 src-tauri 是 `../../frontend/dist`（不是 `../frontend/dist`）
- Tauri2 默认要求 `icons/icon.png` 存在（无图标编译失败）
- CSP：`connect-src` 已允许 `http://localhost:8000`；后端换端口需同步改
- web 端"打不开 shell"：浏览器沙箱确实跑不了系统命令；但 nuomi 的 bash/fs 工具实际由**后端 Python 执行**（HTTP API），因此 Web 也能用 shell 能力。Tauri 桌面版的下一步价值：把 Python 后端做成 sidecar 打进包，或本地命令直达（不经 HTTP 中转）

## 下一步（按需）

- 把 /api 改为 tauri-plugin-http 的本地 fetch（绕过 WebView CORS）
- Python 后端 sidecar 打包（用户级安装时免手动起后端）
- 本地能力直达：shell/fs 改由 Rust 侧执行（沙箱在 Rust 层）
