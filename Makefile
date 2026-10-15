# =============================================================================
# 糯米 Nuomi · 启动 / 关闭脚本（Makefile）
#
# 默认形态（v0.13 起）：桌面 = AI 数字人壳（shells/nuomi-avatar，Electron）。
#   make start        启动AI 数字人壳（默认形态；依赖后端 :8000）
#   make web          调试形态：后端:8000 + 控制台前端:5173（浏览器调试用）
#
# 常用：
#   make start       启动AI 数字人壳（默认形态，日常用这个；会先构建前端，见下）
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
#
# 启动链与前端构建的关系（重要）：
#   壳的控制面板不是 vite dev server，而是后端 StaticFiles 挂载的 frontend/dist
#   （backend/app/main.py 挂 /console），且 dist/ 被 gitignore、不入库。
#   所以 desktop/build 是强依赖：全新克隆没有 dist，main.py 会退回 frontend/ 源码根，
#   /console/ 返回的是源码 index.html（引用 /src/main.tsx → 404），控制面板白屏；
#   改了前端不 build 则是「web 对、桌面壳不对」的经典假绿。
#   这里选择每次启动都构建（build 是 .PHONY + desktop 的 make 前置依赖，
#   make 的前置依赖先于 recipe 执行），用几秒构建时间换掉「忘记 build」这类坑。
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

.PHONY: help start stop restart status logs logs-follow desktop web backend frontend test lint typecheck check format format-check build frontend-test shell-check backup restore backups clean

help:
	@echo "糯米 Nuomi 启动/关闭脚本"
	@echo ""
	@echo "  make start          启动AI 数字人壳（默认形态；会先构建前端；依赖后端 :$(BACKEND_PORT)）"
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

# 前置依赖 build：壳加载的是 backend 挂载的 frontend/dist，先构建再启动（理由见文件头注释）。
desktop: build
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
check: lint format-check typecheck test build frontend-test shell-check

lint:
	@cd $(ROOT)/backend && .venv/bin/ruff check app tests --config pyproject.toml

format-check:
	@cd $(ROOT)/backend && .venv/bin/ruff format --check app tests --config pyproject.toml

format:
	@cd $(ROOT)/backend && .venv/bin/ruff format app tests --config pyproject.toml

typecheck:
	@cd $(ROOT)/backend && .venv/bin/mypy

build:
	@if [ ! -d $(ROOT)/frontend/node_modules ]; then \
		echo "✘ 前端依赖未安装（frontend/node_modules 不存在），无法构建 dist"; \
		echo "  请先执行：cd frontend && npm ci"; \
		exit 1; \
	fi
	@cd $(ROOT)/frontend && npm run build

# 前端单测（vitest + jsdom）：XSS 净化、SSE 分帧、引用标记解析、流式片段合并
frontend-test:
	@if [ ! -d $(ROOT)/frontend/node_modules ]; then \
		echo "✘ 前端依赖未安装，无法跑前端测试"; \
		echo "  请先执行：cd frontend && npm ci"; \
		exit 1; \
	fi
	@cd $(ROOT)/frontend && npm run test:run

# 壳（Electron）语法门禁：CI 没有壳作业，靠这条兜住语法级回归
shell-check:
	@cd $(ROOT)/shells/nuomi-avatar && \
	  files=$$(find . -name '*.js' -not -path './node_modules/*' -not -path './tools/*'); \
	  for f in $$files; do node --check "$$f" || exit 1; done; \
	  echo "✔ 壳语法检查通过（$$(echo "$$files" | wc -l | tr -d ' ') 个文件）"

# -----------------------------------------------------------------------------
# 数据根备份 / 恢复（NUOMI_HOME：人格 MD + 长期记忆 + nuomi.db + 密钥 + 知识索引）
# 为什么单独一档：产品全部事实只在本机这一个目录里，而仓库此前没有任何备份工具、
# 也没有 export 端点（live openapi 76 个 path 里只有 7 个 `*/import`）。
# 磁盘坏了或误删专家 = 记忆和人格一起没了，无从恢复。
# 库文件走 sqlite3 `VACUUM INTO` 出一致快照（WAL 模式下直接 cp 主文件会丢 -wal
# 里未合并的最后一截），默认排除可再生的 models/ 与 logs/ tmp/。
# 行为由 backend/tests/test_backup_script.py 锁住（含「WAL 未合并的写入必须进备份」）。
# -----------------------------------------------------------------------------
backup:
	@$(ROOT)/scripts/backup_nuomi.sh backup

backups:
	@$(ROOT)/scripts/backup_nuomi.sh list

# 用法：make restore BACKUP=<tar> [DELETE=1]（restore 会拒绝在 :8000 还开着时执行）
restore:
	@if [ -z "$(BACKUP)" ]; then \
	  echo "用法：make restore BACKUP=\$$(ls -1t $$HOME/Nuomi-backups/*.tar.gz | head -1)"; \
	  echo "先 make stop；restore 会先把当前数据根备份一份再动手。"; \
	  exit 1; \
	fi
	@$(ROOT)/scripts/backup_nuomi.sh restore "$(BACKUP)" --yes $(if $(DELETE),--delete-extras,)

clean:
	@rm -f $(SHELL_PID) $(BACKEND_PID) $(FRONTEND_PID) $(SHELL_LOG) $(BACKEND_LOG) $(FRONTEND_LOG)
	@echo "✔ 已清理 PID 文件与日志"
