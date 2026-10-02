// 糯米桌面端：Tauri 壳 + Python 后端 sidecar。
// 业务在 Web 前端 + FastAPI 后端；Rust 层负责窗口 + 拉起/回收后端进程。
//
// 后端启动策略（阶段 C：本地 token 守卫）：
// - 每次启动生成随机 token（32 字节 hex），以 NUOMI_TOKEN env 传给后端进程
//   （sidecar 或源码 uv 均生效）；后端中间件校验请求头 X-Nuomi-Token。
// - debug 构建（开发调试）：`uv run uvicorn` 跑源码后端（改代码即时生效），
//   cwd 锚定仓库 backend/；可设 NUOMI_USE_SIDECAR=1 强制走打包产物。
// - release 构建（安装包）：spawn externalBin 打包的 nuomi-backend（PyInstaller）。
// - 复用规则：仅 debug 源码模式且 8000 端口已有可用后端时直接复用（该后端不带
//   token）；其余情况（含 release）一律自起带 token 的后端，不信任外部进程。
// 后端就绪后注入 WebView：window.__NUOMI_API__ / window.__NUOMI_TOKEN__
// （前端 fetch 包装自动加前缀与 token 头）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use rand::RngCore;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// 后端进程句柄（应用退出时回收）+ 本进程生成的 token（注入用）。
/// None child = 复用了已有后端 / 拉起失败。
struct BackendState {
    child: Mutex<Option<CommandChild>>,
    token: Mutex<Option<String>>,
}

const SRC_TAURI_DIR: &str = env!("CARGO_MANIFEST_DIR"); // desktop/src-tauri
const HEALTH_PATH: &str = "/api/health";
const READY_TIMEOUT: Duration = Duration::from_secs(90);

fn repo_root() -> PathBuf {
    PathBuf::from(SRC_TAURI_DIR)
        .parent()
        .expect("desktop dir")
        .parent()
        .expect("repo root")
        .to_path_buf()
}

/// 探测 127.0.0.1:{port} 上是否已有可用的 nuomi 后端（GET /api/health 返回 200）。
/// 读超时放宽到 2s：/api/health 首次会序列化插件状态，600ms 内可能未返回。
fn http_health_ok(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    s.set_read_timeout(Some(Duration::from_millis(2000))).ok();
    let req = format!(
        "GET {HEALTH_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if s.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 512];
    let mut read: usize = 0;
    loop {
        match s.read(&mut buf[read..]) {
            Ok(0) => break,
            Ok(n) => read += n,
            Err(_) => break,
        }
        if read >= buf.len() || read >= 128 {
            break;
        }
    }
    read > 0 && String::from_utf8_lossy(&buf[..read]).contains("200")
}

/// 让系统分配一个空闲端口（127.0.0.1 上）。
fn free_port() -> u16 {
    std::net::TcpListener::bind(("127.0.0.1", 0))
        .ok()
        .and_then(|l| l.local_addr().ok())
        .map(|a| a.port())
        .unwrap_or(8000)
}

/// 生成 32 字节随机 hex token（阶段 C 本地守卫，每次启动新值）。
fn gen_token() -> String {
    let mut b = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut b);
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// 构造并拉起后端进程（带 NUOMI_TOKEN env），返回子进程句柄。
fn spawn_backend(handle: &AppHandle, token: &str, port: u16, use_sidecar: bool) -> Result<CommandChild, String> {
    if use_sidecar {
        let mut cmd = handle
            .shell()
            .sidecar("nuomi-backend")
            .map_err(|e| e.to_string())?
            .env("NUOMI_TOKEN", token);
        cmd = cmd.args(["--port", &port.to_string()]);
        cmd.spawn().map(|(_, child)| child).map_err(|e| e.to_string())
    } else {
        let mut cmd = handle
            .shell()
            .command("uv")
            .env("NUOMI_TOKEN", token);
        cmd = cmd
            .args([
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
            ])
            .current_dir(repo_root().join("backend"));
        cmd.spawn().map(|(_, child)| child).map_err(|e| e.to_string())
    }
}

/// 拉起后端进程，返回实际监听端口。
/// 复用规则：debug 源码模式且 8000 已有 nuomi 后端 → 直接复用（不新起进程、
/// 无 token）；否则自起并带 NUOMI_TOKEN env。
fn ensure_backend(handle: &AppHandle, state: &BackendState, token: &str) -> u16 {
    let use_sidecar =
        std::env::var("NUOMI_USE_SIDECAR").map(|v| v == "1").unwrap_or(!cfg!(debug_assertions));

    if !use_sidecar && http_health_ok(8000) {
        println!("[nuomi] 复用已运行的后端 (127.0.0.1:8000，dev 无 token)");
        return 8000;
    }

    let port = free_port();
    if use_sidecar {
        println!("[nuomi] 拉起 sidecar 后端 (127.0.0.1:{port})");
    } else {
        println!("[nuomi] 拉起源码后端 (uv run uvicorn @ 127.0.0.1:{port})");
    }

    match spawn_backend(handle, token, port, use_sidecar) {
        Ok(child) => {
            *state.child.lock().unwrap() = Some(child);
        }
        Err(e) => {
            eprintln!("[nuomi] 后端拉起失败：{e}");
        }
    }
    port
}

/// 等待后端就绪（轮询 /api/health），就绪后把 API base 与 token 注入 WebView。
fn wait_and_inject(handle: AppHandle, port: u16, token: &str) {
    let base = format!("http://127.0.0.1:{port}");
    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        if http_health_ok(port) {
            println!("[nuomi] 后端就绪：{base}");
            break;
        }
        if Instant::now() >= deadline {
            eprintln!("[nuomi] 等待后端就绪超时（{READY_TIMEOUT:?}），前端将无法连接");
            break;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    // 就绪后重试注入（幂等）：覆盖 WebView 页面加载窗口，避免竞态丢失。
    // dev 下 vite proxy 可兜底，release（无 proxy）依赖此注入，必须可靠。
    let base_js = format!("window.__NUOMI_API__ = {base:?};");
    let token_js = format!("window.__NUOMI_TOKEN__ = {token:?};");
    for _ in 0..10 {
        if let Some(webview) = handle.get_webview_window("main") {
            let _ = webview.eval(&base_js);
            let _ = webview.eval(&token_js);
        }
        std::thread::sleep(Duration::from_millis(400));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // 单实例：重复启动时聚焦已有窗口（须先于其它 plugin 注册）
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState {
            child: Mutex::new(None),
            token: Mutex::new(None),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let state = handle.state::<BackendState>();
                let token = gen_token();
                *state.token.lock().unwrap() = Some(token.clone());
                let port = ensure_backend(&handle, &state, &token);
                wait_and_inject(handle, port, &token);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building nuomi desktop");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<BackendState>() {
                if let Some(child) = state.child.lock().unwrap().take() {
                    println!("[nuomi] 停止后端进程");
                    let _ = child.kill();
                }
            }
        }
    });
}
