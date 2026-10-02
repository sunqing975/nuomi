---
name: memory
description: 读写对用户的长期记忆（名字/偏好/习惯/重要事件/约定），记忆即插件；底层 provider 可切换（内置纯本地 / Mem0 等外部）
when_to_use: 用户分享个人信息时保存；涉及用户个人情况时查询已保存的记忆
---
# memory 技能

记忆以"冻结快照"注入 system prompt（会话开始一次，含容量 header）：
- 写操作（memory_write/replace/remove）即时落盘，但快照下个会话才更新——会话内新增记忆以工具返回为准
- 快照分两档：MEMORY（agent 笔记/事实/事件）与 USER（用户画像，category=user/preference）
- 容量：快照按字符预算截取（MEMORY 2000 / USER 1000，常用与最新优先）；存储层 300 条上限淘汰

## 什么时候写（memory_write）
- 用户主动分享值得长期记住的信息：名字、偏好（食物/颜色/习惯，category=preference）、重要事件、约定
- 只保存真正重要的，不要每轮都存；一句话存一条
- 语气细节（"我今天累"）默认不存，除非是持续偏好

## 什么时候读（memory_read）
- 回答涉及用户个人情况、且回答质量依赖这些背景时
- 先看已注入的记忆快照，不足再调用 memory_read 补充查询

## 修改与删除（memory_replace / memory_remove）
- 记忆过时/记错时用 memory_replace 替换（old_text 取旧记忆唯一片段）
- 用户明确要求遗忘时用 memory_remove 删除（old_text 取唯一片段）
- old_text 匹配多条会报错，需提供更精确的片段

## 规则
- 记忆是对用户的尊重，不是数据采集：写之前判断"下个月还用得上吗"
- 引擎已注入记忆快照，不要在每轮都读
