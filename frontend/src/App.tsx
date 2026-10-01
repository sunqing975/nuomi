/** 糯米 V3 前端（Harness client 模块化布局）：表情层 + 聊天 + 输入栏（模型/思考强度）+ 项目/会话 + 插件 + 设置。 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  activateModel,
  createProject,
  createThread,
  deleteProject,
  deleteThread,
  fetchPlugins,
  fetchProjects,
  fetchProviders,
  fetchSettings,
  fetchThreads,
  loadThreadId,
  renameThread,
  saveThreadId,
  togglePlugin,
  type ModelProvider,
  type PluginInfo,
  type ProjectInfo,
  type SettingsSnapshot,
  type ThreadInfo,
  type TokenUsage,
} from "./api";
import { Msg } from "./modules/types";
import type { CommandDef } from "./modules/ui-input/commands";
import { AssistantRuntimeProvider, useLocalRuntime, useAuiState, type ThreadMessageLike } from "@assistant-ui/react";
import { createNuomiAdapter } from "./modules/ui-chat/NuomiAdapter";
import ChatWindow from "./modules/ui-chat/ChatWindow";
import InputBar, { createRecognizer } from "./modules/ui-input/InputBar";
import SideBar from "./modules/ui-sidebar/SideBar";
import PluginManager from "./modules/ui-plugin-manager/PluginManager";
import SettingsModal from "./modules/ui-settings/SettingsModal";
import { Emotion, PetMood } from "./modules/ui-avatar/PetBuddy";
import { t } from "./i18n";

interface ChatMsg extends Msg {
  reasoning?: string;
  toolCalls?: string[];
  usage?: TokenUsage | null;
}

/** 后端历史消息 → assistant-ui 初始消息（reasoning/toolCalls 转成 part） */
function toThreadMessages(msgs: ChatMsg[]): ThreadMessageLike[] {
  type LikePart = Exclude<ThreadMessageLike["content"], string>[number];
  return msgs.map((m): ThreadMessageLike => {
    const content: LikePart[] = [];
    if (m.role === "assistant") {
      if (m.reasoning) content.push({ type: "reasoning", text: m.reasoning } as const);
      for (const name of m.toolCalls ?? []) {
        content.push({ type: "tool-call", toolCallId: name, toolName: name, args: {} } as const);
      }
    }
    content.push({ type: "text", text: m.content } as const);
    return { role: m.role, content };
  });
}

/** 在 AssistantRuntimeProvider 内读取运行状态，供 InputBar/PluginManager 使用 */
function BusyBridge({ children }: { children: (ctx: { busy: boolean; empty: boolean }) => ReactNode }) {
  const busy = useAuiState((s) => s.thread.isRunning);
  const empty = useAuiState((s) => s.thread.messages.length === 0);
  return <>{children({ busy, empty })}</>;
}

export default function App() {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mood, setMood] = useState<PetMood>("idle");
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [available, setAvailable] = useState<{ name: string; description: string }[]>([]);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [settings, setSettings] = useState<SettingsSnapshot>({ global: {}, plugins: [] });
  const [tab, setTab] = useState<"chat" | "plugins">("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [listening, setListening] = useState(false);
  // 项目 / 会话
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<number | null>(null);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [threadTitle, setThreadTitle] = useState<string | null>(null);
  // 模型 / 思考强度（供应商 → 模型 → effort）
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [activeModelKey, setActiveModelKey] = useState<string | null>(null);
  const [effort, setEffort] = useState<string | null>(null);
  // 主题（深/浅，localStorage 持久化，默认深色对齐 dsh）
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = localStorage.getItem("nuomi-theme");
    return saved === "light" ? "light" : "dark";
  });
  useEffect(() => {
    localStorage.setItem("nuomi-theme", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const recRef = useRef<ReturnType<typeof createRecognizer> | null>(null);

  // assistant-ui runtime：消息状态/流式由 NuomiAdapter 桥接后端 /api/chat
  const runtime = useLocalRuntime(
    useMemo(
      () =>
        createNuomiAdapter({
          onThreadId: (id) => {
            saveThreadId(id);
            setCurrentThreadId(id);
            setThreadTitle(null);
            refreshThreads();
          },
          onDone: ({ emotion }) => {
            const e = (emotion || "neutral") as Emotion;
            if (e !== "neutral") {
              setMood(e);
              window.setTimeout(() => setMood("idle"), 2600);
            } else {
              setMood("idle");
            }
            refreshThreads();
          },
          onTitle: (title) => {
            setThreadTitle(title);
            refreshThreads();
          },
        }),
      []
    )
  );

  const voiceEnabled = plugins.find((p) => p.id === "voice-input")?.enabled ?? true;
  const teamMode = plugins.find((p) => p.id === "team")?.enabled ?? true;

  const refreshPlugins = useCallback(() => {
    fetchPlugins()
      .then((r) => {
        setPlugins(r.plugins);
        setAvailable(r.available ?? []);
      })
      .catch((e) => setError(t("app.pluginsFailed", { msg: String(e instanceof Error ? e.message : e) })));
  }, []);

  const refreshProjects = useCallback(() => {
    fetchProjects()
      .then(setProjects)
      .catch(() => {});
  }, []);

  // 全量线程（侧栏按项目分组渲染，对齐 dsh WorkspaceBrowser）
  const refreshThreads = useCallback(() => {
    fetchThreads(null)
      .then(setThreads)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshPlugins();
    refreshProjects();
    fetchProviders().then((r) => {
      setProviders(r.providers);
      const active = r.providers.flatMap((p) => p.models).find((m) => m.active);
      if (active) {
        setActiveModelKey(active.key);
        for (const p of r.providers) {
          if (p.models.some((m) => m.active)) setActiveProvider(p.key);
        }
      }
    }).catch((e) => setError(t("app.modelsFailed", { msg: String(e) })));
    fetchSettings().then(setSettings).catch((e) => setError(t("app.settingsFailed", { msg: String(e) })));
    refreshThreads(); // 侧栏会话列表：挂载即全量拉取（曾漏 setThreads，刷新后侧栏一直空）
    const saved = loadThreadId();
    if (saved) {
      setCurrentThreadId(saved);
      fetch(`/api/threads/${saved}/messages`)
        .then((r) => r.json())
        .then((body) => {
          runtime.thread.reset(toThreadMessages((body.messages ?? []) as ChatMsg[]));
          fetchThreads(null).then((ts) => {
            setThreads(ts);
            const t = ts.find((x) => x.id === saved);
            if (t) {
              setThreadTitle(t.title);
              setCurrentProjectId(t.project_id);
            }
          });
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectProject = async (id: number | null) => {
    setCurrentProjectId(id);
    refreshThreads();
    setCurrentThreadId(null);
    setThreadTitle(null);
    runtime.thread.reset([]);
  };

  const newThread = async () => {
    try {
      const t = await createThread(currentProjectId);
      setCurrentThreadId(t.id);
      setThreadTitle(t.title);
      runtime.thread.reset([]);
      saveThreadId(t.id);
      refreshThreads();
    } catch (e) {
      setError(t("app.newThreadFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  /** 在指定项目（null=未分组）下新建会话 */
  const newThreadIn = async (projectId: number | null) => {
    try {
      setCurrentProjectId(projectId);
      const t = await createThread(projectId);
      setCurrentThreadId(t.id);
      setThreadTitle(t.title);
      runtime.thread.reset([]);
      saveThreadId(t.id);
      refreshThreads();
    } catch (e) {
      setError(t("app.newThreadFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const selectThread = async (id: string) => {
    setCurrentThreadId(id);
    saveThreadId(id);
    const [body, ts] = await Promise.all([
      fetch(`/api/threads/${id}/messages`).then((r) => r.json()),
      fetchThreads(currentProjectId),
    ]);
    runtime.thread.reset(toThreadMessages((body.messages ?? []) as ChatMsg[]));
    const t = ts.find((x) => x.id === id);
    setThreadTitle(t?.title ?? null);
  };

  const removeThread = async (id: string) => {
    try {
      await deleteThread(id);
      if (id === currentThreadId) {
        setCurrentThreadId(null);
        setThreadTitle(null);
        runtime.thread.reset([]);
      }
      refreshThreads();
    } catch (e) {
      setError(t("app.deleteFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const removeProject = async (id: number) => {
    try {
      await deleteProject(id);
      if (currentProjectId === id) {
        setCurrentProjectId(null);
        setCurrentThreadId(null);
        setThreadTitle(null);
        runtime.thread.reset([]);
      }
      refreshProjects();
      refreshThreads();
    } catch (e) {
      setError(t("app.projectDeleteFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const doToggle = async (name: string) => {
    try {
      await togglePlugin(name);
      setError(null);
      await refreshPlugins();
      fetchSettings().then(setSettings).catch(() => {});
    } catch (e) {
      setError(t("app.pluginToggleFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const send = (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    setInput("");
    setError(null);
    setMood("typing");
    runtime.thread.append({
      role: "user",
      content: [{ type: "text", text }],
      runConfig: { custom: { nuomiThreadId: currentThreadId } },
      startRun: true,
    });
  };

  const startVoice = () => {
    if (!recRef.current) recRef.current = createRecognizer();
    const rec = recRef.current;
    if (!rec) {
      setError(t("app.voiceUnsupported"));
      return;
    }
    rec.onResult((t) => {
      if (t) {
        setInput((v) => (v ? v + t : t));
        void send(t);
      }
    });
    setListening(true);
    setMood("listening");
    rec.start();
  };

  const stopVoice = () => {
    setListening(false);
    setMood("idle");
    recRef.current?.stop();
  };

  const onPluginChanged = async () => {
    setError(null);
    await refreshPlugins();
    fetchSettings().then(setSettings).catch(() => {});
    fetchProviders().then((r) => setProviders(r.providers)).catch(() => {});
  };

  const selectModel = async (provider: string, model: string) => {
    setActiveProvider(provider);
    setActiveModelKey(model);
    setEffort(null);
    try {
      const r = await activateModel(provider, model);
      setProviders(r.providers ?? []);
      setError(null);
    } catch (e) {
      setError(t("app.modelSwitchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  // 指令系统注册表（对齐 dsh commands：直接执行，不创建模型消息）
  const commands = useMemo<CommandDef[]>(() => {
    const help: CommandDef = {
      name: "help",
      description: t("app.listCommands"),
      handler: () => "",
    };
    const all: CommandDef[] = [
      help,
      {
        name: "new",
        description: t("app.newThread"),
        handler: () => {
          void newThread();
          return t("app.threadCreated");
        },
      },
      {
        name: "clear",
        description: t("app.clearThread"),
        handler: () => {
          runtime.thread.reset([]);
          return t("app.threadCleared");
        },
      },
      {
        name: "theme",
        description: t("cmd.themeDesc"),
        handler: () => {
          setTheme((t) => (t === "dark" ? "light" : "dark"));
          return t("app.themeToggled", { name: theme === "dark" ? t("app.themeNameLight") : t("app.themeNameDark") });
        },
      },
      {
        name: "settings",
        description: t("cmd.settings"),
        handler: () => {
          setSettingsOpen(true);
          return t("cmd.settingsOpened");
        },
      },
      {
        name: "plugins",
        description: t("cmd.pluginsDesc"),
        handler: () => {
          setTab("plugins");
          return t("cmd.pluginsOpened");
        },
      },
      {
        name: "model",
        description: t("app.modelHint"),
        handler: () => {
          setSettingsOpen(true);
          return t("app.noModel");
        },
      },
    ];
    help.handler = (raw) => {
      void raw;
      return all.map((c) => `/${c.name} — ${c.description}`).join("\n");
    };
    return all;
  }, [theme]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="app">
        <SideBar
          tab={tab}
          projects={projects}
          threads={threads}
          currentProjectId={currentProjectId}
          currentThreadId={currentThreadId}
          onTab={setTab}
          onOpenSettings={() => setSettingsOpen(true)}
          onNewThread={() => void newThread()}
          onNewThreadIn={(pid) => void newThreadIn(pid)}
          onSelectThread={(id) => void selectThread(id)}
          onSelectProject={(id) => void selectProject(id)}
          onCreateProject={async (name) => {
            try {
              const p = await createProject(name);
              refreshProjects();
              selectProject(p.id);
            } catch (e) {
              setError(t("app.newProjectFailed", { msg: String(e instanceof Error ? e.message : e) }));
            }
          }}
          onRenameThread={async (id, title) => {
            try {
              await renameThread(id, title);
              refreshThreads();
              if (id === currentThreadId) setThreadTitle(title);
            } catch (e) {
              setError(t("app.renameFailed", { msg: String(e instanceof Error ? e.message : e) }));
            }
          }}
          onDeleteThread={(id) => void removeThread(id)}
          onDeleteProject={(id) => void removeProject(id)}
        />

        {tab === "chat" && (
          <main className="main">
            {error && <div className="error">{error}</div>}
            <ChatWindow
              teamMode={teamMode}
              threadTitle={threadTitle}
              onSuggestion={(text) => void send(text)}
              mood={mood}
            />
            <BusyBridge>
              {({ busy, empty }) => (
                <InputBar
                  input={input}
                  setInput={setInput}
                  busy={busy}
                  voiceEnabled={voiceEnabled}
                  listening={listening}
                  providers={providers}
                  activeProvider={activeProvider}
                  activeModelKey={activeModelKey}
                  effort={effort}
                  commands={commands}
                  hero={empty}
                  onSend={() => void send()}
                  onVoice={startVoice}
                  onVoiceStop={stopVoice}
                  onSelectModel={(p, m) => void selectModel(p, m)}
                  onEffort={setEffort}
                />
              )}
            </BusyBridge>
          </main>
        )}

        {tab === "plugins" && (
          <main className="main">
            <BusyBridge>
              {({ busy }) => (
                <PluginManager
                  plugins={plugins}
                  available={available}
                  busy={busy}
                  settings={settings}
                  onToggle={doToggle}
                  onChanged={() => void onPluginChanged()}
                />
              )}
            </BusyBridge>
          </main>
        )}

        {settingsOpen && (
          <SettingsModal
            settings={settings}
            providers={providers}
            theme={theme}
            onThemeToggle={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            onClose={() => setSettingsOpen(false)}
            onSettingsChanged={() => fetchSettings().then(setSettings).catch(() => {})}
            onModelsChanged={() => fetchProviders().then((r) => setProviders(r.providers)).catch(() => {})}
          />
        )}
      </div>
    </AssistantRuntimeProvider>
  );
}
