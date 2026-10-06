# =============================================================================
# 糯米 Nuomi · 启动 / 关闭脚本（Makefile）
#
# 默认形态（v0.13 起）：桌面 = AI 数字人壳（shells/nuomi-avatar，Electron）。
#   make start        启动AI 数字人壳（默认形态；依赖后端 :8000）
#   make web          调试形态：后端:8000 + 控制台前端:5173（浏览器调试用）
#
# 常用：
#   make start       启动AI 数字人壳（默认形态，日常用这个）
#   make stop        停止AI 数字人壳 / web 模式
#   make status      查看运行状态
#   make logs        查看最近日志
#   make check       质量门禁：lint + 格式检查 + typecheck + pytest（提交前跑这个）
#   make lint        后端 ruff lint（backend + plugins）
#   make typecheck   后端 mypy 类型检查
#   make test        运行后端 pytest
#   make build       前端构建（tsc + vite build）
#
# 进程管理：PID 与日志落在 .logs/（已 gitignore），端口占用则跳过启动。
# =============================================================================

SHELL         := /bin/bash
ROOT          := $(CURDIR)
LOGDIR        := $(ROOT)/.logs
SHELL_PID     := $(LOGDIR)/shell.pid
SHELL_LOG     := $(LOGDIR)/shell.log
BACKEND_PID   := $(LOGDIR)/backend.pid
FRONTEND_PID  := $(LOGDIR)/frontend.pid
BACKEND_LOG   := $(LOGDIR)/backend.log
FRONTEND_LOG  := $(LOGDIR)/frontend.log
BACKEND_PORT  := 8000
FRONTEND_PORT := 5173

.DEFAULT_GOAL := help

.PHONY: help start stop restart status logs logs-follow desktop web backend frontend test lint typecheck check format format-check build shell-check clean

help:
	@echo "糯米 Nuomi 启动/关闭脚本"
	@echo ""
	@echo "  make start          启动AI 数字人壳（默认形态；依赖后端 :$(BACKEND_PORT)）"
	@echo "  make stop           停止AI 数字人壳 / web 模式"
	@echo "  make restart        重启"
	@echo "  make status         查看运行状态"
	@echo "  make logs           查看最近日志"
	@echo "  make logs-follow    实时跟踪日志（Ctrl-C 退出）"
	@echo "  make web            调试形态：后端:$(BACKEND_PORT) + 前端:$(FRONTEND_PORT)（浏览器调试用）"
	@echo "  make check          质量门禁：lint + 格式检查 + typecheck + pytest"
	@echo "  make lint           后端 ruff lint（backend + plugins）"
	@echo "  make typecheck      后端 mypy 类型检查"
	@echo "  make format         后端 ruff format（自动格式化）"
	@echo "  make test           运行后端 pytest"
	@echo "  make build          前端构建（tsc + vite build）"
	@echo "  make clean          清理 PID 文件与日志"

# ---- AI 数字人壳（默认形态） ----
start: desktop

desktop:
	@mkdir -p $(LOGDIR)
	@if [ -f $(SHELL_PID) ] && kill -0 $$(cat $(SHELL_PID)) 2>/dev/null; then \
		echo "⚠ AI 数字人壳已在运行 (PID $$(cat $(SHELL_PID)))，先 make stop 再启动"; \
	elif pgrep -f "shells/nuomi-avatar/node_modules/electron" >/dev/null 2>&1; then \
		echo "⚠ 检测到残留AI 数字人壳进程，先 make stop 清理"; \
	else \
		cd $(ROOT)/shells/nuomi-avatar && nohup npm start >$(SHELL_LOG) 2>&1 </dev/null & \
		echo $$! > $(SHELL_PID); \
		echo "✔ AI 数字人壳已启动 (PID $$(cat $(SHELL_PID)))，日志 $(SHELL_LOG)"; \
		echo "  窗口就绪后即显示AI 数字人；依赖后端 :$(BACKEND_PORT)（未启动请先 make backend）"; \
	fi

# ---- web 模式（调试形态，浏览器调试用） ----
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
	@echo "== 停止AI 数字人壳 =="
	@if [ -f $(SHELL_PID) ]; then \
		SPID=$$(cat $(SHELL_PID)); \
		if kill -0 $$SPID 2>/dev/null; then kill $$SPID 2>/dev/null || true; echo "  已终止AI 数字人启动进程 (PID $$SPID)"; fi; \
		rm -f $(SHELL_PID); \
	fi
	@if pgrep -f "shells/nuomi-avatar/node_modules/electron" >/dev/null 2>&1; then \
		pkill -f "shells/nuomi-avatar/node_modules/electron" 2>/dev/null || true; \
		echo "  已终止AI 数字人壳 (Electron)"; \
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
	@echo "✔ 全部停止"

restart: stop start

status:
	@echo "== 糯米 Nuomi 运行状态 =="
	@if pgrep -f "shells/nuomi-avatar/node_modules/electron" >/dev/null 2>&1; then echo "  AI 数字人壳     运行中 (Electron)"; else echo "  AI 数字人壳     未运行"; fi
	@if [ -f $(BACKEND_PID) ] && kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then echo "  web 后端   运行中 (PID $$(cat $(BACKEND_PID)))"; else echo "  web 后端   未运行"; fi
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then echo "  web 前端   运行中 (PID $$(cat $(FRONTEND_PID)))"; else echo "  web 前端   未运行"; fi
	@echo "  端口监听:"
	@lsof -nP -iTCP:$(BACKEND_PORT) -sTCP:LISTEN 2>/dev/null | tail -n +1 || true
	@lsof -nP -iTCP:$(FRONTEND_PORT) -sTCP:LISTEN 2>/dev/null | tail -n +1 || true

logs:
	@echo "===== AI 数字人壳日志 ($(SHELL_LOG)) ====="
	@tail -n 30 $(SHELL_LOG) 2>/dev/null || echo "(暂无日志)"
	@echo ""
	@echo "===== 后端日志 ($(BACKEND_LOG)) ====="
	@tail -n 30 $(BACKEND_LOG) 2>/dev/null || echo "(暂无日志)"
	@echo ""
	@echo "===== 前端日志 ($(FRONTEND_LOG)) ====="
	@tail -n 30 $(FRONTEND_LOG) 2>/dev/null || echo "(暂无日志)"

logs-follow:
	@tail -f $(SHELL_LOG) $(BACKEND_LOG) $(FRONTEND_LOG)

test:
	@cd $(ROOT)/backend && .venv/bin/python -m pytest -q

# ---- 质量门禁（提交前 make check 全绿） ----
# check = 后端 lint + 格式 + 类型 + 测试 + 前端类型&构建 + 壳语法；与 .github/workflows/ci.yml 对齐。
check: lint format-check typecheck test build shell-check

lint:
	@cd $(ROOT)/backend && .venv/bin/ruff check app tests --config pyproject.toml

format-check:
	@cd $(ROOT)/backend && .venv/bin/ruff format --check app tests --config pyproject.toml

format:
	@cd $(ROOT)/backend && .venv/bin/ruff format app tests --config pyproject.toml

typecheck:
	@cd $(ROOT)/backend && .venv/bin/mypy

build:
	@cd $(ROOT)/frontend && npm run build

# 壳（Electron）语法门禁：CI 没有壳作业，靠这条兜住语法级回归
shell-check:
	@cd $(ROOT)/shells/nuomi-avatar && \
	  files=$$(find . -name '*.js' -not -path './node_modules/*' -not -path './tools/*'); \
	  for f in $$files; do node --check "$$f" || exit 1; done; \
	  echo "✔ 壳语法检查通过（$$(echo "$$files" | wc -l | tr -d ' ') 个文件）"

clean:
	@rm -f $(SHELL_PID) $(BACKEND_PID) $(FRONTEND_PID) $(SHELL_LOG) $(BACKEND_LOG) $(FRONTEND_LOG)
	@echo "✔ 已清理 PID 文件与日志"
