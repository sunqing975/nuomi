---
name: shell
description: Shell 执行：bash 命令执行与沙箱模式（read-only / workspace-write / full-access）
when_to_use: 用户让你执行命令、跑脚本、查看系统信息、操作文件或安装依赖时
---
# shell 技能

1. 优先使用 `bash` 工具并选择最小权限模式：
   - `read-only`：只读查询（ls / cat / pwd / git status / python --version…），禁止写命令
   - `workspace-write`（默认）：可在工作区（backend/data/workspace）内写文件、跑脚本
   - `bash_full`：系统级操作，需用户批准（审批门）
2. 命令默认在工作区目录执行；需要真实系统信息时用只读命令
3. 执行后如实汇报 stdout/stderr/退出码；失败不编造输出
4. 不读取敏感环境变量（API key 等），不执行破坏性系统命令
