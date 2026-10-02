# -*- mode: python ; coding: utf-8 -*-
"""Nuomi 桌面后端 sidecar 打包配置（PyInstaller onefile）。

资源策略：
- plugins/ partners/ 整体作为 datas 打入包内（运行时从 sys._MEIPASS 加载，
  PyInstaller onefile 会把 _MEIPASS 加入 sys.path，动态 import 可用）。
- chromadb / fastembed / onnxruntime / langchain 等动态导入密集的包
  用 collect_all 全量收集（submodules + binaries）。
数据落点：sidecar_main.py 启动时把 DB/记忆/知识库/工作区重定向到
~/Library/Application Support/Nuomi/data（用户可写），不写打包区。
"""
import os

from PyInstaller.utils.hooks import collect_all

# SPECPATH：PyInstaller 注入的 spec 文件所在目录（= backend/）
backend = os.path.abspath(SPECPATH)
repo_root = os.path.dirname(backend)

datas = [
    (os.path.join(repo_root, "plugins"), "plugins"),
    (os.path.join(repo_root, "partners"), "partners"),
]
binaries = []
hiddenimports = []

# 动态导入密集 / 带原生二进制的包：全量收集
COLLECT = [
    "chromadb",
    "fastembed",
    "onnxruntime",
    "uvicorn",
    "fastapi",
    "langchain",
    "langgraph",
    "langchain_openai",
    "langchain_mcp_adapters",
    "openai",
    "huggingface_hub",
    "tokenizers",
    "onnx",
]
for pkg in COLLECT:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["sidecar_main.py"],
    pathex=[backend],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter", "test", "tests", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nuomi-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
