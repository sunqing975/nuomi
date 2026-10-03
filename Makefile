# =============================================================================
# 糯米 Nuomi · 启动 / 关闭脚本（Makefile）
#
# 默认形态（2026-10-02 起）：桌面版。`cargo tauri dev` 全自动管理——
# tauri CLI 自行拉起 vite(:5173) 与源码后端（带 token，随机空闲端口，
# 8000 已有可用后端则复用），应用退出时自动回收后端。
#
# 常用：
#   make start       启动桌面版（推荐，日常用这个）
#   make stop        停止桌面版 / web 模式
#   make status      查看运行状态
#   make logs        查看最近日志
#   make web         显式启动 web 模式（后端:8000 + 前端:5173，浏览器调试用）
#   make check       质量门禁：lint + 格式检查 + typecheck + pytest（提交前跑这个）
#   make lint        后端 ruff lint（backend + plugins）
#   make typecheck   后端 mypy 类型检查
#   make test        运行后端 pytest
#   make build       前端构建（tsc + vite build，桌面版加载 dist）
#
# 进程管理：PID 与日志落在 .logs/（已 gitignore），端口占用则跳过启动。
# =============================================================================

SHELL         := /bin/bash
ROOT          := $(CURDIR)
LOGDIR        := $(ROOT)/.logs
DESKTOP_PID   := $(LOGDIR)/desktop.pid
DESKTOP_LOG   := $(LOGDIR)/desktop.log
BACKEND_PID   := $(LOGDIR)/backend.pid
FRONTEND_PID  := $(LOGDIR)/frontend.pid
BACKEND_LOG   := $(LOGDIR)/backend.log
FRONTEND_LOG  := $(LOGDIR)/frontend.log
BACKEND_PORT  := 8000
FRONTEND_PORT := 5173

.DEFAULT_GOAL := help

.PHONY: help start stop restart status logs logs-follow desktop web backend frontend test lint typecheck check format format-check build clean

help:
	@echo "糯米 Nuomi 启动/关闭脚本"
	@echo ""
	@echo "  make start          启动桌面版（cargo tauri dev，自动起 vite + 后端）"
	@echo "  make stop           停止桌面版 / web 模式"
	@echo "  make restart        重启"
	@echo "  make status         查看运行状态"
	@echo "  make logs           查看最近日志"
	@echo "  make logs-follow    实时跟踪日志（Ctrl-C 退出）"
	@echo "  make web            显式启动 web 模式（后端:$(BACKEND_PORT) + 前端:$(FRONTEND_PORT)）"
	@echo "  make check          质量门禁：lint + 格式检查 + typecheck + pytest"
	@echo "  make lint           后端 ruff lint（backend + plugins）"
	@echo "  make typecheck      后端 mypy 类型检查"
	@echo "  make format         后端 ruff format（自动格式化）"
	@echo "  make test           运行后端 pytest"
	@echo "  make build          前端构建（tsc + vite build）"
	@echo "  make clean          清理 PID 文件与日志"

# ---- 桌面版（默认） ----
start: desktop

desktop:
	@mkdir -p $(LOGDIR)
	@if [ -f $(DESKTOP_PID) ] && kill -0 $$(cat $(DESKTOP_PID)) 2>/dev/null; then \
		echo "⚠ 桌面版已在运行 (PID $$(cat $(DESKTOP_PID)))，先 make stop 再启动"; \
	elif lsof -nP -iTCP:$(FRONTEND_PORT) -sTCP:LISTEN >/dev/null 2>&1 || pgrep -x nuomi-desktop >/dev/null 2>&1; then \
		echo "⚠ 检测到残留桌面版进程（:$(FRONTEND_PORT) 或 nuomi-desktop），先 make stop 清理"; \
	else \
		cd $(ROOT)/desktop && nohup cargo tauri dev >$(DESKTOP_LOG) 2>&1 </dev/null & \
		echo $$! > $(DESKTOP_PID); \
		echo "✔ 桌面版已启动 (PID $$(cat $(DESKTOP_PID)))，日志 $(DESKTOP_LOG)"; \
		echo "  窗口就绪后即打开；后端由 tauri 自动拉起/回收"; \
	fi

# ---- web 模式（可选，浏览器调试） ----
web: backend frontend
	@echo ""
	@echo "✔ web 模式启动完成：前端 http://localhost:$(FRONTEND_PORT)（vite 代理 /api → :$(BACKEND_PORT)）"

backend:
	@mkdir -p $(LOGDIR)
	@if lsof -nP -iTCP:$(BACKEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "⚠ 端口 $(BACKEND_PORT) 已被占用，后端跳过启动（可能已在运行）"; \
	else \
		cd $(ROOT)/backend && nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT) >$(BACKEND_LOG) 2>&1 </dev/null & \
		sleep 1; \
		BP=$$(lsof -tiTCP:$(BACKEND_PORT) -sTCP:LISTEN | head -1); \
		if [ -n "$$BP" ]; then echo $$BP > $(BACKEND_PID); else echo $$! > $(BACKEND_PID); fi; \
		echo "✔ 后端已启动 (PID $$(cat $(BACKEND_PID)))，日志 $(BACKEND_LOG)"; \
	fi

frontend:
	@mkdir -p $(LOGDIR)
	@if lsof -nP -iTCP:$(FRONTEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "⚠ 端口 $(FRONTEND_PORT) 已被占用，前端跳过启动（可能已在运行）"; \
	else \
		cd $(ROOT)/frontend && nohup npm run dev >$(FRONTEND_LOG) 2>&1 </dev/null & \
		sleep 1; \
		FP=$$(lsof -tiTCP:$(FRONTEND_PORT) -sTCP:LISTEN | head -1); \
		if [ -n "$$FP" ]; then echo $$FP > $(FRONTEND_PID); else echo $$! > $(FRONTEND_PID); fi; \
		echo "✔ 前端已启动 (PID $$(cat $(FRONTEND_PID)))，日志 $(FRONTEND_LOG)"; \
	fi

stop:
	@echo "== 停止桌面版 =="
	@if [ -f $(DESKTOP_PID) ]; then \
		DPID=$$(cat $(DESKTOP_PID)); \
		if kill -0 $$DPID 2>/dev/null; then kill $$DPID 2>/dev/null || true; echo "  已终止 tauri dev (PID $$DPID)"; fi; \
		rm -f $(DESKTOP_PID); \
	fi
	@if pgrep -x nuomi-desktop >/dev/null 2>&1; then \
		pkill -x nuomi-desktop 2>/dev/null || true; \
		echo "  已终止桌面应用 (nuomi-desktop)"; \
	fi
	@echo "== 停止 web 模式 =="
	@if [ -f $(BACKEND_PID) ]; then \
		BPID=$$(cat $(BACKEND_PID)); \
		if kill -0 $$BPID 2>/dev/null; then kill $$BPID 2>/dev/null || true; echo "  已终止后端 (PID $$BPID)"; fi; \
		rm -f $(BACKEND_PID); \
	fi
	@if [ -f $(FRONTEND_PID) ]; then \
		FPID=$$(cat $(FRONTEND_PID)); \
		if kill -0 $$FPID 2>/dev/null; then kill $$FPID 2>/dev/null || true; fi; \
		rm -f $(FRONTEND_PID); \
	fi
	@sleep 1
	@echo "== 回收残留 =="
	@for P in $(BACKEND_PORT) $(FRONTEND_PORT); do \
		if lsof -nP -iTCP:$$P -sTCP:LISTEN >/dev/null 2>&1; then \
			VPID=$$(lsof -tiTCP:$$P -sTCP:LISTEN | head -1); \
			kill $$VPID 2>/dev/null || true; \
			echo "  已回收 :$$P 残留进程 (PID $$VPID)"; \
		fi; \
	done
	@BP=$$(grep -oE 'http://127\.0\.0\.1:[0-9]+' $(DESKTOP_LOG) 2>/dev/null | tail -1 | grep -oE '[0-9]+$$'); \
	if [ -n "$$BP" ]; then \
		if lsof -nP -iTCP:$$BP -sTCP:LISTEN >/dev/null 2>&1; then \
			VPID=$$(lsof -tiTCP:$$BP -sTCP:LISTEN | head -1); \
			kill $$VPID 2>/dev/null || true; \
			echo "  已回收 tauri 自起后端 :$$BP (PID $$VPID)"; \
		fi; \
	fi
	@echo "✔ 全部停止"

restart: stop start

status:
	@echo "== 糯米 Nuomi 运行状态 =="
	@if [ -f $(DESKTOP_PID) ] && kill -0 $$(cat $(DESKTOP_PID)) 2>/dev/null; then echo "  桌面版     运行中 (tauri dev PID $$(cat $(DESKTOP_PID)))"; else echo "  桌面版     未运行"; fi
	@if pgrep -x nuomi-desktop >/dev/null 2>&1; then echo "  应用窗口   运行中 (PID $$(pgrep -x nuomi-desktop | head -1))"; else echo "  应用窗口   未运行"; fi
	@if [ -f $(BACKEND_PID) ] && kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then echo "  web 后端   运行中 (PID $$(cat $(BACKEND_PID)))"; else echo "  web 后端   未运行"; fi
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then echo "  web 前端   运行中 (PID $$(cat $(FRONTEND_PID)))"; else echo "  web 前端   未运行"; fi
	@echo "  端口监听:"
	@lsof -nP -iTCP:$(BACKEND_PORT) -sTCP:LISTEN 2>/dev/null | tail -n +1 || true
	@lsof -nP -iTCP:$(FRONTEND_PORT) -sTCP:LISTEN 2>/dev/null | tail -n +1 || true

logs:
	@echo "===== 桌面版日志 ($(DESKTOP_LOG)) ====="
	@tail -n 30 $(DESKTOP_LOG) 2>/dev/null || echo "(暂无日志)"
	@echo ""
	@echo "===== 后端日志 ($(BACKEND_LOG)) ====="
	@tail -n 30 $(BACKEND_LOG) 2>/dev/null || echo "(暂无日志)"
	@echo ""
	@echo "===== 前端日志 ($(FRONTEND_LOG)) ====="
	@tail -n 30 $(FRONTEND_LOG) 2>/dev/null || echo "(暂无日志)"

logs-follow:
	@tail -f $(DESKTOP_LOG) $(BACKEND_LOG) $(FRONTEND_LOG)

test:
	@cd $(ROOT)/backend && .venv/bin/python -m pytest -q

# ---- 质量门禁（对齐 Octop make all 模式：提交前 make check 全绿） ----
check: layers lint format-check typecheck test

layers:
	@cd $(ROOT)/backend && .venv/bin/python scripts/check_layering.py

lint:
	@cd $(ROOT)/backend && .venv/bin/ruff check app tests scripts ../plugins --config pyproject.toml

format-check:
	@cd $(ROOT)/backend && .venv/bin/ruff format --check app tests scripts ../plugins --config pyproject.toml

format:
	@cd $(ROOT)/backend && .venv/bin/ruff format app tests scripts ../plugins --config pyproject.toml

typecheck:
	@cd $(ROOT)/backend && .venv/bin/mypy

build:
	@cd $(ROOT)/frontend && npm run build

clean:
	@rm -f $(DESKTOP_PID) $(BACKEND_PID) $(FRONTEND_PID) $(DESKTOP_LOG) $(BACKEND_LOG) $(FRONTEND_LOG)
	@echo "✔ 已清理 PID 文件与日志"
