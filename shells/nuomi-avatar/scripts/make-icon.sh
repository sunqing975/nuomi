#!/usr/bin/env bash
# =============================================================================
# 生成 macOS 应用图标 build/icon.icns（electron-builder 的 buildResources 目录）
#
# 为什么用脚本而不是提交 .icns：仓库里只有 icon.png（1.7MB，非图标规范尺寸），
# .icns 属于「构建产物」——用 macOS 自带的 sips + iconutil 可重复生成，
# 不必把二进制产物塞进版本库（build/ 已 gitignore）。
#
# 用法：npm run icon   （在 shells/nuomi-avatar 下执行；需要 macOS）
# 产物：build/icon.icns
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/icon.png"
OUT_DIR="$ROOT/build"
ICONSET="$OUT_DIR/icon.iconset"
ICNS="$OUT_DIR/icon.icns"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "✗ 仅支持 macOS（依赖 sips / iconutil）。当前系统: $(uname -s)" >&2
    exit 1
fi
for tool in sips iconutil; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "✗ 找不到 $tool（macOS 自带工具，缺失说明环境异常）" >&2
        exit 1
    fi
done
if [ ! -f "$SRC" ]; then
    echo "✗ 缺少源图: $SRC" >&2
    exit 1
fi

# 幂等：每次重建，避免旧尺寸残留（electron-builder 对 iconset 里的多余文件会报错）
rm -rf "$ICONSET" "$ICNS"
mkdir -p "$ICONSET"

# 源图非正方形（1448x1440）时用 -z 强制正方，0.5% 的拉伸肉眼不可见；
# -z 的参数顺序是「高 宽」。
emit() { # $1=边长 $2=目标文件名
    sips -s format png -z "$1" "$1" "$SRC" --out "$ICONSET/$2" >/dev/null
}

emit 16   icon_16x16.png
emit 32   icon_16x16@2x.png
emit 32   icon_32x32.png
emit 64   icon_32x32@2x.png
emit 128  icon_128x128.png
emit 256  icon_128x128@2x.png
emit 256  icon_256x256.png
emit 512  icon_256x256@2x.png
emit 512  icon_512x512.png
emit 1024 icon_512x512@2x.png

iconutil -c icns "$ICONSET" -o "$ICNS"
rm -rf "$ICONSET"

echo "✔ 已生成 $ICNS ($(du -h "$ICNS" | cut -f1))"
