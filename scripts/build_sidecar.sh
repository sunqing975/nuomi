#!/bin/bash
# 打包 Python 后端为 Tauri sidecar（PyInstaller onefile）。
# 产物：desktop/src-tauri/binaries/nuomi-backend
# 用法：bash scripts/build_sidecar.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

echo "==> 安装 PyInstaller（backend venv，uv 管理）"
uv pip install -q pyinstaller

echo "==> PyInstaller 打包（chromadb/langchain 等全量收集，需数分钟）"
uv run pyinstaller nuomi.spec --noconfirm --clean

echo "==> 复制到 Tauri binaries/（带 target triple 后缀，Tauri externalBin 要求）"
case "$(uname -m)" in
  arm64) TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *) echo "未知架构 $(uname -m)，需手动指定 target triple" >&2; exit 1 ;;
esac
mkdir -p "$ROOT/desktop/src-tauri/binaries"
cp dist/nuomi-backend "$ROOT/desktop/src-tauri/binaries/nuomi-backend-$TRIPLE"

echo "==> 冒烟：直接跑一次（--port 8109）"
"$ROOT/desktop/src-tauri/binaries/nuomi-backend" --port 8109 &
sleep 8
curl -s --max-time 3 http://127.0.0.1:8109/api/health | head -c 120
echo
# onefile 有 bootloader+python 父子两进程，用 pkill 整组清理
pkill -f "nuomi-backend --port 8109" 2>/dev/null || true
sleep 1

echo "OK -> desktop/src-tauri/binaries/nuomi-backend"
