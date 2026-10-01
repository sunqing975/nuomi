// 糯米桌面端：Tauri 薄壳。业务全在 Web 前端 + FastAPI 后端，Rust 层只做窗口。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    nuomi_desktop_lib::run()
}
