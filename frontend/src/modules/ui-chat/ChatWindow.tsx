/** ui-chat：聊天窗——assistant-ui (LocalRuntime) 渲染消息流。
 *
 * - headless primitives（ThreadPrimitive/MessagePrimitive/MessagePrimitive.Parts），
 *   不引入 Tailwind：样式全部走现有 CSS（.chat/.row/.bubble/.reasoning-row/.tool-row）
 * - part 渲染：text → 气泡；reasoning → 「深度思考」折叠块；tool-call → 工具调用卡片
 * - 消息状态/流式/自动滚动由 assistant-ui runtime 管理（NuomiAdapter 桥接后端 SSE）
 */
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { ThreadPrimitive, MessagePrimitive, useAuiState } from "@assistant-ui/react";
import type {
  TextMessagePartProps,
  ReasoningMessagePartProps,
  ToolCallMessagePartProps,
} from "@assistant-ui/core/react";
import { t } from "../../i18n";
import { SendIcon, SparkleIcon, ZapIcon } from "../icons";

// ---------- part 组件 ----------

/** 对话流错误卡片（对齐 Harness：API 错误原文直接渲染在对话流）。
 *  后端 error 事件经 NuomiAdapter 以 "⚠️ " 前缀注入文本 part。 */
function TextPart({ text }: TextMessagePartProps) {
  const body = text || "…";
  if (body.startsWith("⚠️ ")) {
    const detail = body.slice(3).trim();
    return (
      <div className="msg-error-card" title={detail}>
        <div className="msg-error-title">⚠️ 处理失败</div>
        <pre className="msg-error-body">{detail}</pre>
      </div>
    );
  }
  // Markdown 渲染：react-markdown（成熟开源），气泡内样式见 .bubble .md-* 系列
  return (
    <div className="bubble">
      <ReactMarkdown>{body}</ReactMarkdown>
    </div>
  );
}

function ReasoningPart({ text }: ReasoningMessagePartProps) {
  // 深度思考流式展示：思考进行中自动展开逐字滚动，输出完成后自动折叠；
  // 用户手动点过徽章后以其选择为准（manual 覆盖流式行为）
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? isRunning;
  const toggle = () => setManual((m) => (m === null ? !isRunning : !m));
  return (
    <div className={`reasoning-row ${open ? "open" : ""}`}>
      <button className="reasoning-toggle" onClick={toggle}>
        <SparkleIcon />
        <span>{t("chat.deepThinking")}</span>
        <span className="reasoning-len">{t("chat.charCount", { n: text.length })}</span>
        {isRunning && <span className="reasoning-caret" aria-hidden>›</span>}
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  );
}

function ToolCallPart({ toolName, argsText, result }: ToolCallMessagePartProps) {
  const [open, setOpen] = useState(false);
  const done = Boolean(result);
  return (
    <div className={`tool-card ${open ? "open" : ""} ${done ? "done" : "running"}`}>
      <button className="tool-card-head" onClick={() => setOpen((v) => !v)}>
        <ZapIcon size={13} />
        <span>{t("chat.toolCall")}</span>
        <code>{toolName}</code>
        <span className="tool-card-status">{done ? t("chat.toolDone") : t("chat.toolRunning")}</span>
        <span className="tool-card-caret" aria-hidden>
          ›
        </span>
      </button>
      {open && (
        <div className="tool-card-body">
          {argsText && argsText !== "{}" && (
            <div className="tool-card-sec">
              <div className="tool-card-label">{t("chat.toolArgs")}</div>
              <pre className="tool-card-json">{argsText}</pre>
            </div>
          )}
          {result !== undefined && (
            <div className="tool-card-sec">
              <div className="tool-card-label">{t("chat.toolResult")}</div>
              <pre className="tool-card-json">{String(result)}</pre>
            </div>
          )}
          {(!argsText || argsText === "{}") && result === undefined && (
            <div className="tool-card-sec">
              <div className="tool-card-label">{t("chat.toolNoDetail")}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------- 消息组件 ----------

function UserMessage() {
  return (
    <MessagePrimitive.Root className="row user">
      <MessagePrimitive.Parts components={{ Text: TextPart }} />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="row assistant">
      <MessagePrimitive.Parts
        components={{
          Text: TextPart,
          Reasoning: ReasoningPart,
          tools: { Fallback: ToolCallPart },
        }}
      />
    </MessagePrimitive.Root>
  );
}

// ---------- 空态（hero） ----------

function ChatHero({ teamMode, onSuggestion }: { teamMode: boolean; onSuggestion: (text: string) => void }) {
  const suggestions = [t("chat.suggestion1"), t("chat.suggestion2"), t("chat.suggestion3")];
  return (
    <div className="hint">
      <div className="hero-title">{t("chat.heroTitle")}</div>
      <div className="hero-sub">{t("chat.heroSub")}</div>
      <div className="suggestion-row">
        {suggestions.map((s) => (
          <button key={s} className="suggestion-chip" onClick={() => onSuggestion(s)}>
            <SendIcon size={13} />
            {s}
          </button>
        ))}
      </div>
      <span className="hint-sub">
        {teamMode ? `${t("chat.teamHint")} ` : ""}
        {t("chat.heroFoot")}
      </span>
    </div>
  );
}

// ---------- 主组件 ----------

export default function ChatWindow({
  teamMode,
  onSuggestion,
}: {
  teamMode: boolean;
  onSuggestion: (text: string) => void;
}) {
  return (
    <div className="chat">
      <ThreadPrimitive.Root>
        <ThreadPrimitive.Viewport className="thread-viewport">
          <ThreadPrimitive.If empty>
            <ChatHero teamMode={teamMode} onSuggestion={onSuggestion} />
          </ThreadPrimitive.If>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </div>
  );
}
