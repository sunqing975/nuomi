/** ui-input：输入栏（对齐 Harness Composer）——一张卡片：
 *  上方 auto-grow 输入区（hero 空态双行占位），下方工具行
 *  （左侧 / 命令入口 + 右侧 模型选择 · 语音 · 34px 圆形发送键）。
 *  指令系统：输入 / 呼出命令菜单，命令直接执行不创建模型消息。
 */
import { useMemo, useRef, useState } from "react";
import ModelSelect from "../ui-model-selection/ModelSelect";
import type { ModelProvider } from "../../api";
import { parseCommand, parseAt, type CommandDef, type AtRef } from "./commands";
import { t } from "../../i18n";
import { MicIcon, SendIcon } from "../icons";

/** 浏览器语音输入（Chrome / localhost 可用），不支持时返回 null。 */
export function createRecognizer(): {
  start: () => void;
  stop: () => void;
  onResult: (fn: (t: string) => void) => void;
} | null {
  const w = window as unknown as Record<string, unknown>;
  const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (typeof Ctor !== "function") return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rec: any = new (Ctor as any)();
  rec.lang = "zh-CN";
  rec.interimResults = false;
  rec.continuous = false;
  return {
    start: () => rec.start(),
    stop: () => rec.stop(),
    onResult: (fn) => {
      rec.onresult = (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => {
        const last = e.results[e.results.length - 1];
        fn(last?.[0]?.transcript ?? "");
      };
      rec.onend = () => {};
      rec.onerror = () => {};
    },
  };
}

export default function InputBar({
  input,
  setInput,
  busy,
  voiceEnabled,
  listening,
  providers,
  activeProvider,
  activeModelKey,
  effort,
  commands,
  references,
  hero,
  onSend,
  onSendText,
  onVoice,
  onVoiceStop,
  onSelectModel,
  onEffort,
}: {
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  voiceEnabled: boolean;
  listening: boolean;
  providers: ModelProvider[];
  activeProvider: string | null;
  activeModelKey: string | null;
  effort: string | null;
  commands: CommandDef[];
  /** @ 引用目标列表（对齐 dsh：敲 @ 弹引用面板） */
  references?: AtRef[];
  /** 空会话（Harness hero）：输入卡双行占位 */
  hero?: boolean;
  onSend: () => void;
  /** 技能命令：把指定文本作为消息发送（对齐 dsh「/ 选技能 → 带输入干活」） */
  onSendText?: (text: string) => void;
  onVoice: () => void;
  onVoiceStop: () => void;
  onSelectModel: (provider: string, model: string) => void;
  onEffort: (e: string) => void;
}) {
  const [cmdIdx, setCmdIdx] = useState(0);
  const [feedback, setFeedback] = useState<string | null>(null);
  const feedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const parsed = useMemo(() => parseCommand(input), [input]);
  const matches = useMemo(() => {
    if (!parsed) return [];
    return commands.filter((c) => c.name.startsWith(parsed.name));
  }, [parsed, commands]);
  const showMenu = matches.length > 0;

  // @ 引用（对齐 dsh：敲 @ 弹引用面板，点名对象带进会话）
  const atParsed = useMemo(() => parseAt(input), [input]);
  const atMatches = useMemo(() => {
    if (!atParsed || !references?.length) return [];
    return references.filter((r) => r.key.startsWith(atParsed.key) || r.label.toLowerCase().startsWith(atParsed.key));
  }, [atParsed, references]);
  const showAtMenu = atMatches.length > 0;
  const [atIdx, setAtIdx] = useState(0);

  const showFeedback = (text: string) => {
    setFeedback(text);
    if (feedTimer.current) clearTimeout(feedTimer.current);
    feedTimer.current = setTimeout(() => setFeedback(null), 4000);
  };

  const runCommand = async (raw: string) => {
    if (matches.length === 0) return;
    const cmd = matches[cmdIdx % matches.length];
    // 技能命令（对齐 dsh「/ 选技能 → 补一句任务」）：把输入作为消息发给模型，引导用对应能力
    if (cmd.kind === "skill") {
      const task = raw.trim();
      if (!task) {
        showFeedback(t("input.skillNeedTask", { name: cmd.name }));
        return;
      }
      if (onSendText) {
        setInput("");
        setCmdIdx(0);
        onSendText(t("input.skillPrompt", { name: cmd.name, task }));
        return;
      }
    }
    try {
      const r = await cmd.handler(raw);
      if (r) showFeedback(`/${cmd.name} ${r}`);
    } catch (e) {
      showFeedback(t("input.cmdFailed", { name: cmd.name, msg: String(e instanceof Error ? e.message : e) }));
    }
    setInput("");
    setCmdIdx(0);
  };

  const openCommandMenu = () => {
    setInput("/");
    setCmdIdx(0);
    taRef.current?.focus();
  };

  /** 选中 @ 引用：把引用文本注入输入框（替换当前 @ 前缀） */
  const pickAt = (ref: AtRef) => {
    const insert = ref.insert ?? ref.label;
    const idx = input.lastIndexOf("@");
    const prefix = idx > 0 ? input.slice(0, idx) : "";
    const suffix = input.slice(idx + 1).replace(/^[a-zA-Z0-9_\-]*/, "");
    setInput(`${prefix}@${insert}${suffix}`);
    setAtIdx(0);
    taRef.current?.focus();
  };

  /** 发送语义归输入栏：清空 + 调用父级发送 + 焦点回输入区 */
  const handleSend = () => {
    if (!input.trim() || busy) return;
    setInput("");
    onSend();
    requestAnimationFrame(() => taRef.current?.focus());
  };

  return (
    <footer className="inputbar">
      {/* 指令反馈条（命令结果直接呈现 UI，不产生模型消息） */}
      {feedback && <div className="cmd-feedback">{feedback}</div>}

      {showMenu && (
        <div className="cmd-menu">
          <div className="cmd-menu-title">{t("input.cmdMenuHint")}</div>
          {/* 内置命令组 */}
          {matches.some((c) => c.kind !== "skill") && (
            <>
              <div className="cmd-menu-group">{t("input.cmdGroupCommands")}</div>
              {matches.map((c, i) =>
                c.kind !== "skill" ? (
                  <button
                    key={c.name}
                    className={`cmd-menu-row ${i === cmdIdx ? "on" : ""}`}
                    onMouseEnter={() => setCmdIdx(i)}
                    onClick={() => {
                      setCmdIdx(i);
                      void runCommand("");
                    }}
                  >
                    <span className="cmd-name">/{c.name}</span>
                    <span className="cmd-desc">{c.description}</span>
                  </button>
                ) : null,
              )}
            </>
          )}
          {/* 技能命令组（dsh「/ 选技能干活」） */}
          {matches.some((c) => c.kind === "skill") && (
            <>
              <div className="cmd-menu-group">{t("input.cmdGroupSkills")}</div>
              {matches.map((c, i) =>
                c.kind === "skill" ? (
                  <button
                    key={c.name}
                    className={`cmd-menu-row ${i === cmdIdx ? "on" : ""}`}
                    onMouseEnter={() => setCmdIdx(i)}
                    onClick={() => {
                      setCmdIdx(i);
                      void runCommand("");
                    }}
                  >
                    <span className="cmd-name">/{c.name}</span>
                    <span className="cmd-desc">{c.description}</span>
                  </button>
                ) : null,
              )}
            </>
          )}
        </div>
      )}

      {/* @ 引用菜单（dsh：敲 @ 弹引用列表，点名项目/上下文） */}
      {showAtMenu && (
        <div className="cmd-menu at-menu">
          <div className="cmd-menu-title">{t("input.atMenuHint")}</div>
          {atMatches.map((r, i) => (
            <button
              key={r.key}
              className={`cmd-menu-row ${i === atIdx ? "on" : ""}`}
              onMouseEnter={() => setAtIdx(i)}
              onClick={() => pickAt(r)}
            >
              <span className="cmd-name">@{r.label}</span>
              {r.detail && <span className="cmd-desc">{r.detail}</span>}
            </button>
          ))}
        </div>
      )}

      {/* Composer 卡片（对齐 Harness InputBar：输入区 + 工具行同卡） */}
      <div className={`composer-card ${hero ? "hero" : ""}`}>
        <div className="composer-scroll">
          <textarea
            ref={taRef}
            className="composer-input"
            value={input}
            rows={1}
            placeholder={hero ? t("input.placeholderHero") : t("input.placeholderChat")}
            onChange={(e) => {
              setInput(e.target.value);
              setCmdIdx(0);
            }}
            onKeyDown={(e) => {
              if (showAtMenu) {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setAtIdx((i) => (i + 1) % atMatches.length);
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setAtIdx((i) => (i - 1 + atMatches.length) % atMatches.length);
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  pickAt(atMatches[atIdx % atMatches.length]);
                  return;
                }
                if (e.key === "Escape") {
                  setInput(input.replace(/@[a-zA-Z0-9_\-]*$/, "@"));
                  return;
                }
              }
              if (showMenu) {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runCommand(parsed?.raw ?? "");
                  return;
                }
                if (e.key === "Tab") {
                  e.preventDefault();
                  const c = matches[cmdIdx % matches.length];
                  setInput(`/${c.name}`);
                  return;
                }
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCmdIdx((i) => (i + 1) % matches.length);
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCmdIdx((i) => (i - 1 + matches.length) % matches.length);
                  return;
                }
                if (e.key === "Escape") {
                  setInput("");
                  return;
                }
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
        </div>

        <div className="composer-row">
          <div className="composer-tools">
            <button className="composer-add" onClick={openCommandMenu} title={t("input.openCommands")}>
              /
            </button>
          </div>
          <div className="composer-trailing">
            <ModelSelect
              providers={providers}
              activeProvider={activeProvider}
              activeModelKey={activeModelKey}
              effort={effort}
              onSelect={onSelectModel}
              onEffort={onEffort}
              disabled={busy}
            />
            {voiceEnabled && (
              <button
                className={`mic ${listening ? "on" : ""}`}
                onClick={() => (listening ? onVoiceStop() : onVoice())}
                title={t("input.voice")}
                disabled={busy}
              >
                <MicIcon />
              </button>
            )}
            <button
              className="composer-send"
              onClick={handleSend}
              disabled={busy || !input.trim()}
              title={t("input.sendEnter")}
              aria-label={t("input.send")}
            >
              <SendIcon />
            </button>
          </div>
        </div>
      </div>
    </footer>
  );
}
