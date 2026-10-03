---
name: fs
description: 工作区文件：读写、列目录、搜索文件（只在工作区内操作）
when_to_use: 用户让你保存内容到文件、读取文件、整理目录、查找文件时
---
# fs 技能

1. 路径一律相对工作区（backend/data/workspace）解析，如 `notes/todo.md`
2. `read_file` 读文件、`write_file` 写/追加、`list_dir` 列目录、`search_files` 按名字搜索、`delete_file` 删除
3. 写文件先确认目标目录存在（可先 list_dir 或让模型自行 mkdir——用 shell 工具的 workspace-write 模式）
4. 不读写工作区外的敏感文件（.env、密钥、用户目录配置）
