/** ui-chat：聊天窗——assistant-ui (LocalRuntime) 渲染消息流。
 *
 * - headless primitives（ThreadPrimitive/MessagePrimitive/MessagePrimitive.Parts），
 *   不引入 Tailwind：样式全部走现有 CSS（.chat/.row/.bubble/.reasoning-row/.tool-row）
 * - part 渲染：text → 气泡；reasoning → 「深度思考」折叠块；tool-call → 工具调用卡片
 * - 消息状态/流式/自动滚动由 assistant-ui runtime 管理（NuomiAdapter 桥接后端 SSE）
 */
import { useState } from "react";
import { ThreadPrimitive, MessagePrimitive, useAuiState } from "@assistant-ui/react";
import type {
  TextMessagePartProps,
  ReasoningMessagePartProps,
  ToolCallMessagePartProps,
} from "@assistant-ui/core/react";
import PetBuddy, { PetMood } from "../ui-avatar/PetBuddy";
import { t } from "../../i18n";
import { SendIcon, SparkleIcon, ZapIcon } from "../icons";

// ---------- part 组件 ----------

function TextPart({ text }: TextMessagePartProps) {
  return <div className="bubble">{text || "…"}</div>;
}

function ReasoningPart({ text }: ReasoningMessagePartProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`reasoning-row ${open ? "open" : ""}`}>
      <button className="reasoning-toggle" onClick={() => setOpen((v) => !v)}>
        <SparkleIcon />
        <span>深度思考</span>
        <span className="reasoning-len">{t("chat.charCount", { n: text.length })}</span>
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  );
}

function ToolCallPart({ toolName }: ToolCallMessagePartProps) {
  return (
    <div className="tool-row">
      <ZapIcon size={12} />
      <span>调用工具</span>
      <code>{toolName}</code>
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
  threadTitle,
  teamMode,
  mood,
  onSuggestion,
}: {
  threadTitle: string | null;
  teamMode: boolean;
  mood: PetMood;
  onSuggestion: (text: string) => void;
}) {
  const busy = useAuiState((s) => s.thread.isRunning);
  const PLACEHOLDER_TITLES = ["新会话", "新建会话", "未命名"];
  const showTitle = !!threadTitle && !PLACEHOLDER_TITLES.includes(threadTitle);

  return (
    <div className="chat">
      {/* 伙伴栏：表情随回答情绪变化 */}
      <div className="partner-bar">
        <PetBuddy mood={mood} size={92} speech={busy ? t("chat.pondering") : null} />
        <div className="partner-meta">
          <div className="partner-name">{t("brand.name")}</div>
          <div className={`partner-status ${busy ? "busy" : ""}`}>{t("chat.online")}</div>
        </div>
      </div>

      {showTitle && (
        <div className="chat-header">
          <div className="chat-title">{threadTitle}</div>
        </div>
      )}

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
