# MEMORY · 长期记忆

> 项目级长期决策、约定、约束、环境配置。由模型按对话事实维护，保持精简。

## 环境配置

- 代码仓库：`/Users/superman/projects/code/nuomi`（后端 FastAPI + 前端 React + myspy 桌面壳）
- 数据根：`/Users/superman/Nuomi`（NUOMI_HOME；专家 workspace 位于 `agent-workspaces/<agent_id>/`）
- 桌面端：myspy 壳（Electron）；每次代码改动后重启 myspy 再验证
- 技能安装：真实文件存 `~/.agents/skills`，在豆包用户技能目录建符号链接

## 约定

- 产品命名统一「连接器」，不向用户暴露 MCP 等协议术语
- 开发优先使用成熟开源框架/SDK 组装核心逻辑，不自己造轮子
