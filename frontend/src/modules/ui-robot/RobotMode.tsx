/** 机器人模式（双模式之一）：纯语音对话 + 3D 机器人脸（开源 three.ws agent-3d）。
 *  语音闭环（全本地）：录音 → /api/transcribe（faster-whisper）→ onSend（走通用 chat/记忆/工具）
 *  → 新回复 → /api/speak（macOS say）→ agent-3d.speakAudio() 播放 + 波形驱动真实嘴型。
 *  形象：three.ws `<agent-3d body>`（Apache-2.0）——静默 3D viewer，无 API key、无云依赖，
 *  仅渲染 GLB 模型（frontend/public/models/nuomi-robot.glb，可换任意 GLB）。
 *  打字栏保留为降级入口（安静环境）。大脑与通用模式完全共用——这里只是换一张"脸"。
 *  v0.7 三区：本模式是否可进入由 App 侧 robot 内核模块 enabled 控制。 */
import {
  useEffect,
  useRef,
  useState,
  type DetailedHTMLProps,
  type FormEvent,
  type HTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useAuiState } from "@assistant-ui/react";
import RobotFace from "./RobotFace"; // 3D 形象加载失败时的低配兜底（自绘 SVG）
import { t } from "../../i18n";
import "./robot.css";
import "./robot-face.css"; // fallback SVG 脸的表情动画

// React 18 + TS：声明 custom element 的 JSX 类型（ref 指向 HTMLElement，speakAudio 运行时调用）
declare global {
  namespace JSX {
    interface IntrinsicElements {
      "agent-3d": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        body?: string;
        mode?: string;
        kiosk?: boolean;
        eager?: boolean;
      };
    }
  }
}

/** 全局模型 URL：本地 GLB（离线可用），换脸 = 换这个文件 */
const ROBOT_MODEL_URL = "/models/nuomi-robot.glb";
/** agent-3d web component（three.ws 1.5.2，Apache-2.0）：public 静态资源，进机器人模式才注入加载 */
const AGENT_3D_SCRIPT = "/vendor/agent-3d.js";

interface RobotModeProps {
  error: string | null;
  onSend: (text: string) => void;
  onBack: () => void;
}

const blobToDataURL = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });

export default function RobotMode({ error, onSend, onBack }: RobotModeProps) {
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const busy = useAuiState((s) => s.thread.isRunning);

  // 最近一条 assistant 文本（机器人脸下方气泡展示；无则留白）
  const lastReply = useAuiState((s) => {
    const msgs = s.thread.messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.role !== "assistant") continue;
      const parts = typeof m.content === "string" ? [{ type: "text" as const, text: m.content }] : m.content;
      const textPart = parts.filter((p) => p.type === "text").map((p) => p.text).join("").trim();
      if (textPart) return textPart;
    }
    return "";
  });

  const agentRef = useRef<HTMLElement | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // 3D 脚本加载状态：成功 → 渲染 agent-3d；失败/未就绪 → 降级 SVG 脸
  const [faceReady, setFaceReady] = useState(false);
  // 挂载时快照最后一条回复，避免进入模式时误播历史回复；之后只播"新增"回复
  const prevReplyRef = useRef(lastReply);
  const endHandlerRef = useRef<(() => void) | null>(null);

  // 注入 agent-3d 脚本（public 静态资源，Apache-2.0）——只进机器人模式才加载；失败降级 SVG 脸
  useEffect(() => {
    if (typeof window !== "undefined" && window.customElements.get("agent-3d")) {
      setFaceReady(true);
      return;
    }
    let cancelled = false;
    const script = document.createElement("script");
    script.type = "module";
    script.src = AGENT_3D_SCRIPT;
    script.onload = () => {
      if (!cancelled) setFaceReady(true);
    };
    script.onerror = () => {
      if (!cancelled) setFaceReady(false); // 保持 SVG 兜底
    };
    document.head.appendChild(script);
    return () => {
      cancelled = true;
    };
  }, []);

  // 新回复 → 本地 TTS → agent-3d.speakAudio 播放 + 波形驱动嘴型
  useEffect(() => {
    if (busy) return;
    if (!lastReply || lastReply === prevReplyRef.current) return;
    prevReplyRef.current = lastReply;
    void playReply(lastReply);
  }, [busy, lastReply]);

  const stopSpeaking = () => {
    setSpeaking(false);
    const el = agentRef.current;
    const h = endHandlerRef.current;
    if (el && h) el.removeEventListener("voice:speech-end", h);
    endHandlerRef.current = null;
  };

  const playReply = async (reply: string) => {
    try {
      const res = await fetch("/api/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: reply.slice(0, 400) }),
      });
      if (!res.ok) return; // 静默降级：气泡文字仍在
      const blob = await res.blob();
      const dataUrl = await blobToDataURL(blob);
      const el = agentRef.current;
      if (!el) return;
      stopSpeaking();
      const onEnd = () => setSpeaking(false);
      endHandlerRef.current = onEnd;
      el.addEventListener("voice:speech-end", onEnd, { once: true });
      setSpeaking(true);
      // 类型见 agent-3d API：speakAudio(audio: string|HTMLAudioElement, opts?) → Promise
      const api = el as unknown as { speakAudio: (a: string) => Promise<void> };
      await api.speakAudio(dataUrl);
      setSpeaking(false);
    } catch {
      stopSpeaking();
    }
  };

  // 点击麦克风：开始录音 / 停止录音（停止后自动转写 → 发送）
  const toggleRecord = async () => {
    if (recording) {
      recRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      recRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((tr) => tr.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        setRecording(false);
        void transcribe(blob);
      };
      rec.start();
      setRecording(true);
      setVoiceError(null);
    } catch {
      setVoiceError(t("robot.micFailed"));
    }
  };

  const transcribe = async (blob: Blob) => {
    try {
      const fd = new FormData();
      fd.append("audio", blob, "speech.webm");
      const res = await fetch("/api/transcribe", { method: "POST", body: fd });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { text?: string };
      const said = (data.text ?? "").trim();
      if (!said) {
        setVoiceError(t("robot.noSpeech"));
        return;
      }
      onSend(said);
    } catch {
      setVoiceError(t("robot.speechFailed"));
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v || busy) return;
    setText("");
    onSend(v);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault(); // Enter 发送（对齐通用模式输入栏），Shift+Enter 换行
      const v = text.trim();
      if (!v || busy) return;
      setText("");
      onSend(v);
    }
  };

  const status = voiceError
    ? voiceError // 具体语音提示（没听清 / 无法用麦克风 / 识别失败）
    : error
      ? t("robot.error")
      : recording
        ? t("robot.listening")
        : speaking
          ? t("robot.speaking")
          : busy
            ? t("robot.thinking")
            : t("robot.online");

  return (
    <div className="robot-mode">
      <div className="robot-top">
        <button type="button" className="mini-btn" onClick={onBack}>
          <span aria-hidden="true">←</span> {t("robot.back")}
        </button>
        <span className="robot-status">{status}</span>
      </div>

      <div className="robot-stage">
        <div className="robot-face-wrap">
          {faceReady ? (
            <agent-3d ref={agentRef} body={ROBOT_MODEL_URL} kiosk eager />
          ) : (
            <RobotFace mode={busy ? "thinking" : speaking ? "speaking" : recording ? "listening" : "idle"} />
          )}
        </div>
        {lastReply && <div className="robot-speech">{lastReply}</div>}
      </div>

      <div className="robot-bottom">
        <form className="robot-input" onSubmit={submit}>
          <button
            type="button"
            className={`robot-mic${recording ? " recording" : ""}`}
            onClick={() => void toggleRecord()}
            disabled={busy}
            title={t("robot.micHint")}
            aria-label={t("robot.micHint")}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
              <path d="M12 18v4" />
            </svg>
          </button>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("robot.placeholder")}
            rows={1}
            disabled={busy}
            aria-label={t("input.send")}
          />
          <button
            type="submit"
            className="robot-send"
            disabled={!text.trim() || busy}
            title={t("input.send")}
            aria-label={t("input.send")}
          >
            ↑
          </button>
        </form>
      </div>
    </div>
  );
}
