// 糯米桌面端：Tauri 薄壳。业务全在 Web 前端 + FastAPI 后端，Rust 层只做窗口。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .run(tauri::generate_context!())
        .expect("error while running nuomi desktop");
}
