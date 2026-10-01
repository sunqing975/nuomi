/** ui-input/commands.ts · 输入框指令系统（对齐 Harness commands 子系统）。
 *
 * 语义（参考 deepseek-harness docs/subsystems/commands.zh.md）：
 * - CommandDefinition：name（无斜杠小写）+ description + 可选 input.hint + handler
 * - 发现视图：适配器只看到 name/description/hint（不含 handler）
 * - 执行：直接调用 handler，**不创建模型消息**；结果直接呈现 UI（此处为输入栏上方反馈条）
 * - parse：解析出的 name 小写、保留 raw（分隔符与后缀）
 */
export interface CommandDef {
  /** 无斜杠小写命令名（如 "theme"） */
  name: string;
  /** 发现 UI 用的人类可读摘要 */
  description: string;
  /** 可选：用户补充输入前的占位提示 */
  hint?: string;
  /** 直接执行，不发给模型；返回字符串时显示为反馈 */
  handler: (raw: string) => string | void | Promise<string | void>;
}

export interface ParsedCommand {
  name: string;
  /** 命令名后的原样后缀（含分隔空白） */
  raw: string;
}

/** 语法解析：输入以 / 开头即视为命令（单独 / → 空名，显示全部命令） */
export function parseCommand(text: string): ParsedCommand | null {
  const t = text.trim();
  if (!t.startsWith("/")) return null;
  const m = /^\/([a-z][a-z0-9-]*)?(.*)$/.exec(t);
  return m ? { name: (m[1] ?? "").toLowerCase(), raw: m[2] ?? "" } : null;
}

/** 发现视图（对齐 dsh CommandDescriptor：无 handler） */
export interface CommandDescriptor {
  name: string;
  description: string;
  hint?: string;
}

export function toDescriptor(c: CommandDef): CommandDescriptor {
  return { name: c.name, description: c.description, hint: c.hint };
}
