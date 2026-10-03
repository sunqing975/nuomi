/** NuomiAdapter · 把后端 /api/chat 的自建 SSE 协议转成 assistant-ui 的 part 流。
 *
 * 协议事件：meta → (token | reasoning | tool)* → done(usage/emotion) → title → error
 * assistant-ui 要求：run 为 async generator，每次 yield 返回完整累积 content，
 * reasoning/text part 只在有内容时出现（无空尾随 part），tool-call 用 Map 跨 chunk 累积。
 */
import type { ChatModelAdapter, ChatModelRunResult } from "@assistant-ui/react";

type AssistantPart = NonNullable<ChatModelRunResult["content"]>[number];
type ToolCallPart = AssistantPart & { type: "tool-call"; args: Record<string, never>; argsText: string; result?: string };

export interface NuomiAdapterCallbacks {
  /** meta 事件：后端可能创建新 thread，回传真实 thread_id */
  onThreadId?: (id: string) => void;
  /** done 事件：回传 token 用量、耗时与情绪（供输入框运行统计显示） */
  onDone?: (info: { usage: unknown; latency_s: number; emotion: string }) => void;
  /** title 事件：模型命名完成，前端刷新侧栏 */
  onTitle?: (title: string) => void;
}

export function createNuomiAdapter(callbacks: NuomiAdapterCallbacks = {}): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal, runConfig }) {
      const lastUser = [...messages].reverse().find((m) => m.role === "user");
      const text = (lastUser?.content ?? [])
        .filter((c) => c.type === "text")
        .map((c) => c.text)
        .join("");
      if (!text.trim()) throw new Error("空消息");

      // nuomi 的数据库 thread_id 由 App 经 runConfig.custom 透传（assistant-ui 的
      // 内部 threadId 是运行时自生成 uuid，不能直接当数据库 id 用）
      const nuomiThreadId = runConfig.custom?.nuomiThreadId as string | null | undefined;

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: nuomiThreadId ?? null }),
        signal: abortSignal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let reasoning = "";
      let textAcc = "";
      const toolCalls = new Map<string, ToolCallPart>();

      const emit = (): ChatModelRunResult => {
        const content: AssistantPart[] = [];
        if (reasoning) content.push({ type: "reasoning", text: reasoning });
        for (const tc of toolCalls.values()) content.push(tc);
        if (textAcc) content.push({ type: "text", text: textAcc });
        return { content };
      };

      const dispatch = (block: string) => {
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data = line.slice(6);
        }
        if (!data) return;
        const payload = JSON.parse(data) as Record<string, unknown>;
        switch (event) {
          case "meta":
            callbacks.onThreadId?.(String(payload.thread_id ?? ""));
            break;
          case "token":
            textAcc += String(payload.content ?? "");
            break;
          case "reasoning":
            reasoning += String(payload.content ?? "");
            break;
          case "tool": {
            const name = String(payload.name ?? "");
            if (name && !toolCalls.has(name)) {
              toolCalls.set(name, {
                type: "tool-call",
                toolCallId: name,
                toolName: name,
                args: {},
                argsText: String(payload.args ?? "{}"),
              });
            }
            break;
          }
          case "tool_result": {
            const name = String(payload.name ?? "");
            const tc = toolCalls.get(name);
            if (tc) tc.result = String(payload.result ?? "");
            break;
          }
          case "done":
            callbacks.onDone?.({
              usage: payload.usage,
              latency_s: Number(payload.latency_s ?? 0),
              emotion: String(payload.emotion ?? "neutral"),
            });
            break;
          case "title":
            callbacks.onTitle?.(String(payload.title ?? ""));
            break;
          case "error":
            // 错误不进顶部 banner，而是作为一条对话内错误卡片消息
            // （ChatWindow 检测 ⚠️ 前缀渲染 .msg-error-card）
            textAcc += `⚠️ ${String(payload.message ?? "未知错误")}`;
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          dispatch(block);
          yield emit();
        }
      }
      if (buffer.trim()) {
        dispatch(buffer);
        yield emit();
      }
    },
  };
}
