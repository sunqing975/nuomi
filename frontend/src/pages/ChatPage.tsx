/** pages/ChatPage：聊天页（对齐 Octop /chat）。
 *  布局：左侧会话/项目树 rail（SideBar）+ 主区（顶栏 + ChatWindow + InputBar）+ 右栏文件树。
 *  聊天核心逻辑（assistant-ui runtime / SSE 桥接 / 命令系统）在 App 根持有，本页只做布局组装。 */
import type { AgentInfo, ModelProvider, ProjectInfo, ThreadInfo } from "../api";
import { useNavigate } from "react-router-dom";
import type { CommandDef } from "../modules/ui-input/commands";
import ChatWindow from "../modules/ui-chat/ChatWindow";
import InputBar from "../modules/ui-input/InputBar";
import SideBar from "../modules/ui-sidebar/SideBar";
import FilesPanel from "../modules/ui-sidebar/FilesPanel";
import { BusyBridge } from "./shared/BusyBridge";
import { FolderIcon, RobotIcon, XIcon } from "../modules/icons";
import { t } from "../i18n";

export interface ChatPageProps {
  onOpenRobot: () => void;
  // 专家 / 会话（rail 按 Agent 维度组织）
  agents: AgentInfo[];
  projects: ProjectInfo[];
  threads: ThreadInfo[];
  currentProjectId: number | null;
  currentThreadId: string | null;
  threadTitle: string | null;
  onNewThread: () => void;
  onSelectThread: (id: string) => void;
  onSelectProject: (id: number | null) => void;
  onRenameThread: (id: string, title: string) => Promise<void>;
  onDeleteThread: (id: string) => void;
  // 能力状态
  robotEnabled: boolean;
  teamMode: boolean;
  voiceEnabled: boolean;
  // 模型 / 输入
  providers: ModelProvider[];
  activeProvider: string | null;
  activeModelKey: string | null;
  effort: string | null;
  input: string;
  setInput: (v: string) => void;
  listening: boolean;
  commands: CommandDef[];
  references: { key: string; label: string; detail: string; insert: string }[];
  error: string | null;
  scope: string;
  onScopeCycle: () => void;
  runStats: { tokens: number; latency_s: number } | null;
  onSend: () => void;
  onSendText: (text: string) => void;
  onSuggestion: (text: string) => void;
  onVoice: () => void;
  onVoiceStop: () => void;
  onSelectModel: (p: string, m: string) => void;
  onEffort: (e: string | null) => void;
  // 文件树
  filesOpen: boolean;
  setFilesOpen: (v: boolean) => void;
  filesTick: number;
}

export default function ChatPage(p: ChatPageProps) {
  const navigate = useNavigate();
  return (
    <div className={`app ${p.filesOpen ? "right-open" : ""}`}>
      <SideBar
        tab="chat"
        agents={p.agents}
        threads={p.threads}
        currentThreadId={p.currentThreadId}
        onTab={() => {}}
        onOpenSettings={() => navigate("/settings")}
        onNewThread={p.onNewThread}
        onSelectThread={p.onSelectThread}
        onSelectProject={p.onSelectProject}
        onRenameThread={p.onRenameThread}
        onDeleteThread={p.onDeleteThread}
      />

      <main className="main">
        <div className="topbar">
          <div className="topbar-title" title={p.threadTitle ?? undefined}>
            {p.threadTitle ||
              p.projects.find((x) => x.id === p.currentProjectId)?.name ||
              t("sidebar.newSession")}
          </div>
          <div className="topbar-actions">
            {p.robotEnabled && (
              <button className="mode-toggle" onClick={p.onOpenRobot} title={t("app.robotSwitch")}>
                <RobotIcon size={14} />
              </button>
            )}
            {p.projects.find((x) => x.id === p.currentProjectId)?.directory && (
              <button
                className={`icon-btn files-toggle ${p.filesOpen ? "on" : ""}`}
                onClick={() => p.setFilesOpen(!p.filesOpen)}
                title={t("right.filesTab") + " · ⌘P"}
              >
                <FolderIcon size={15} />
              </button>
            )}
          </div>
        </div>
        {p.error && <div className="error">{p.error}</div>}
        <ChatWindow teamMode={p.teamMode} onSuggestion={(text) => p.onSuggestion(text)} />
        <BusyBridge>
          {({ busy, empty }) => (
            <InputBar
              input={p.input}
              setInput={p.setInput}
              busy={busy}
              voiceEnabled={p.voiceEnabled}
              listening={p.listening}
              providers={p.providers}
              activeProvider={p.activeProvider}
              activeModelKey={p.activeModelKey}
              effort={p.effort}
              commands={p.commands}
              references={p.references}
              hero={empty}
              onSend={() => p.onSend()}
              onSendText={(text) => p.onSendText(text)}
              onVoice={p.onVoice}
              onVoiceStop={p.onVoiceStop}
              onSelectModel={(prov, m) => p.onSelectModel(prov, m)}
              onEffort={p.onEffort}
              scope={p.scope}
              onScopeCycle={p.onScopeCycle}
              runStats={p.runStats}
            />
          )}
        </BusyBridge>
      </main>

      <div
        className="right-mask"
        onClick={() => p.setFilesOpen(false)}
        aria-hidden="true"
      />
      <aside className="right-panel">
        <div className="right-panel-head">
          <span className="right-panel-title">
            <FolderIcon size={14} />
            <span className="name">{p.projects.find((x) => x.id === p.currentProjectId)?.name ?? t("chat.files")}</span>
          </span>
          <button className="icon-btn rp-close" title={t("common.close")} onClick={() => p.setFilesOpen(false)}>
            <XIcon />
          </button>
        </div>
        {p.currentProjectId != null && <FilesPanel projectId={p.currentProjectId} refreshTick={p.filesTick} />}
      </aside>
    </div>
  );
}
