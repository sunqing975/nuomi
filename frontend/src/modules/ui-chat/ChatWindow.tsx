/** ui-chat：聊天窗——伙伴栏（表情+状态）+ 会话标题头（纯展示）+ 消息流 + 空态（建议芯片）+ 自动滚动。 */
import { useEffect, useRef, useState } from "react";
import { Msg } from "../types";
import type { TokenUsage } from "../../api";
import PetBuddy, { PetMood } from "../ui-avatar/PetBuddy";
import { t } from "../../i18n";
import { SendIcon, SparkleIcon, WarnIcon, ZapIcon } from "../icons";

interface ChatMsg extends Msg {
  reasoning?: string;
  usage?: TokenUsage | null;
}

function ReasoningRow({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`reasoning-row ${open ? "open" : ""}`}>
      <button className="reasoning-toggle" onClick={() => setOpen((v) => !v)}>
        <SparkleIcon />
        <span>思考过程</span>
        <span className="reasoning-len">{t("chat.charCount", { n: text.length })}</span>
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  );
}

function UsagePill({ usage }: { usage: TokenUsage }) {
  const total = usage.total_tokens ?? (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
  return (
    <span className="usage-pill" title={t("chat.tokenUsage", { in: usage.input_tokens ?? 0, out: usage.output_tokens ?? 0 })}>
      <ZapIcon size={11} />
      {total.toLocaleString()} tokens
    </span>
  );
}

export default function ChatWindow({
  messages,
  error,
  teamMode,
  threadTitle,
  onSuggestion,
  mood,
  busy,
  listening,
}: {
  messages: ChatMsg[];
  error: string | null;
  teamMode: boolean;
  threadTitle: string | null;
  /** 空态建议芯片：点击直接把建议发出去 */
  onSuggestion: (text: string) => void;
  mood: PetMood;
  busy: boolean;
  listening: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, error]);

  const status = listening ? t("chat.listening") : busy ? t("chat.typing") : teamMode ? t("chat.teamOnline") : t("chat.online");
  const suggestions = [t("chat.suggestion1"), t("chat.suggestion2"), t("chat.suggestion3")];

  return (
    <div className={`chat ${messages.length === 0 ? "empty" : ""}`}>
      {/* 伙伴栏：表情随回答情绪变化（Harness 主区顶部的品牌/状态语义） */}
      <div className="partner-bar">
        <PetBuddy mood={mood} size={92} speech={busy ? t("chat.pondering") : null} />
        <div className="partner-meta">
          <div className="partner-name">{t("brand.name")}</div>
          <div className={`partner-status ${busy ? "busy" : ""}`}>{status}</div>
        </div>
      </div>

      {threadTitle && (
        <div className="chat-header">
          <div className="chat-title">{threadTitle}</div>
        </div>
      )}

      {messages.length === 0 && (
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
      )}
      {messages.map((m, i) => (
        <div
          key={i}
          className={`row ${m.role}`}
          style={{ animationDelay: `${Math.min(i, 8) * 0.045}s` }}
        >
          {m.role === "assistant" && m.reasoning && <ReasoningRow text={m.reasoning} />}
          <div className="bubble">
            {m.content || "…"}
            {m.usage && <UsagePill usage={m.usage} />}
          </div>
        </div>
      ))}
      {error && (
        <div className="error">
          <WarnIcon size={13} />
          {error}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
