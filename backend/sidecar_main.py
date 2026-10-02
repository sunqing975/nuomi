"""桌面 sidecar 入口：PyInstaller 打包后端时使用。

职责（决策 5 简化版：单一数据根，不逐项设置数据路径）：
1. 解析 --port（Tauri 侧探测的空闲端口），以 127.0.0.1 监听。
2. 资源目录指向打包内嵌目录（sys._MEIPASS 的 plugins/partners，只读）；
   数据路径全部由 config 的 NUOMI_HOME 单一规则解析（默认
   ~/Library/Application Support/Nuomi），打包形态无需覆盖。
3. 启动 uvicorn 托管 FastAPI app。

dev 调试也可直接运行：`uv run sidecar_main.py --port 8100`。
"""
from __future__ import annotations

import argparse
import os
import sys


def _setup_env() -> None:
    """打包形态：plugins/partners 落在 PyInstaller 只读资源区（sys._MEIPASS）。

    源码运行（dev）时这些变量不设置，config 默认指向仓库 plugins/、partners/。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        os.environ.setdefault("PLUGINS_DIR", os.path.join(meipass, "plugins"))
        os.environ.setdefault("PARTNERS_DIR", os.path.join(meipass, "partners"))
    # embedding 模型下载镜像（直连 huggingface 实测超时）
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nuomi 桌面后端 sidecar")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    args = parser.parse_args()

    _setup_env()

    import uvicorn

    from app.main import app

    print(f"[nuomi-backend] listening on 127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
