/** 糯米 V3 前端（Harness client 模块化布局）：表情层 + 聊天 + 输入栏（模型/思考强度）+ 项目/会话 + 插件 + 设置。 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConfigProvider, theme as antdTheme } from "antd";
import zhCN from "antd/locale/zh_CN";
import MainLayout from "./layouts/MainLayout";
import ChatPage from "./pages/ChatPage";
import CapabilitiesPage from "./pages/CapabilitiesPage";
import SkillsPage from "./pages/SkillsPage";
import WorkspacePage from "./pages/WorkspacePage";
import ExpertsPage from "./pages/ExpertsPage";
import SettingsPage from "./pages/SettingsPage";
import { DEFAULT_PALETTE, isPaletteId, PALETTES, PALETTE_STORAGE_KEY, type PaletteId } from "./themes";
import {
  activateModel,
  createProject,
  createThread,
  deleteProject,
  deleteThread,
  fetchBootstrap,
  fetchPlugins,
  fetchProjects,
  fetchProviders,
  fetchSettings,
  fetchThreads,
  loadThreadId,
  renameThread,
  saveThreadId,
  setGlobalSetting,
  fetchExperts,
  type BootstrapStatus,
  type ModelProvider,
  type PluginInfo,
  type ProjectInfo,
  type SettingsSnapshot,
  type ThreadInfo,
  type TokenUsage,
} from "./api";
import { Msg } from "./modules/types";
import type { CommandDef } from "./modules/ui-input/commands";
import { AssistantRuntimeProvider, useLocalRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { createNuomiAdapter } from "./modules/ui-chat/NuomiAdapter";
import WelcomeWizard from "./modules/ui-wizard/WelcomeWizard";
import SettingsModal from "./modules/ui-settings/SettingsModal";
import RobotMode from "./modules/ui-robot/RobotMode";
import { createRecognizer } from "./modules/ui-input/InputBar";
import { t } from "./i18n";

interface ChatMsg extends Msg {
  reasoning?: string;
  toolCalls?: { name: string; args?: string; result?: string }[];
  usage?: TokenUsage | null;
}

/** 后端历史消息 → assistant-ui 初始消息（reasoning/toolCalls 转成 part） */
function toThreadMessages(msgs: ChatMsg[]): ThreadMessageLike[] {
  type LikePart = Exclude<ThreadMessageLike["content"], string>[number];
  return msgs.map((m): ThreadMessageLike => {
    const content: LikePart[] = [];
    if (m.role === "assistant") {
      if (m.reasoning) content.push({ type: "reasoning", text: m.reasoning } as const);
      for (const tc of m.toolCalls ?? []) {
        content.push({
          type: "tool-call",
          toolCallId: tc.name,
          toolName: tc.name,
          args: {},
          argsText: tc.args,
          result: tc.result ?? undefined,
        } as const);
      }
    }
    content.push({ type: "text", text: m.content } as const);
    return { role: m.role, content };
  });
}

export default function App() {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [settings, setSettings] = useState<SettingsSnapshot>({ global: {}, plugins: [] });
  const [tab, setTab] = useState<"chat" | "plugins">("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [listening, setListening] = useState(false);
  // 双模式（对齐"机器人大脑"定位）：general 通用聊天 / robot 全屏机器人脸（表情联动，大脑共用）
  const [mode, setMode] = useState<"general" | "robot">("general");
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
  // 品牌色板（对齐 Octop 8 色板，localStorage 持久化，默认 rose）
  const [palette, setPalette] = useState<PaletteId>(() => {
    const saved = localStorage.getItem(PALETTE_STORAGE_KEY);
    return saved && isPaletteId(saved) ? saved : DEFAULT_PALETTE;
  });
  const setPalettePersist = (p: PaletteId) => {
    setPalette(p);
    localStorage.setItem(PALETTE_STORAGE_KEY, p);
  };
  // 当前专家（领域语言：专家 = 人格 + 能力模板资产）
  const [currentExpert, setCurrentExpert] = useState<string | null>(null);
  const refreshExpert = useCallback(() => {
    fetchExperts()
      .then((r) => setCurrentExpert(r.current))
      .catch(() => {});
  }, []);
  // 计划模式（对齐 dsh /plan：软约束引导「先计划后执行」，发送时注入提示）
  const [planMode, setPlanMode] = useState(false);
  // 阶段 B：工作区文件树刷新计数（新建/删除项目/绑定目录后 +1，FilesPanel 重拉）
  const [filesTick, setFilesTick] = useState(0);
  // 项目文件树抽屉开关（主区右上角按钮，2026-10-02 自侧栏移入）
  const [filesOpen, setFilesOpen] = useState(false);
  // 最近一次回复运行统计（输入框状态行：token 用量 · 耗时）
  const [runStats, setRunStats] = useState<{ tokens: number; latency_s: number } | null>(null);
  useEffect(() => {
    refreshExpert();
  }, [refreshExpert]);
  // 范围（shell 沙箱模式，对齐 Harness 范围切换）：read-only / workspace-write / full-access
  const scope = (settings.global.shell_default_mode as string | undefined) ?? "workspace-write";
  const cycleScope = () => {
    const order = ["read-only", "workspace-write", "full-access"] as const;
    const idx = Math.max(order.indexOf(scope as (typeof order)[number]), 0);
    const next = order[(idx + 1) % order.length];
    void setGlobalSetting("shell_default_mode", next)
      .then(() => setSettings((s) => ({ ...s, global: { ...s.global, shell_default_mode: next } })))
      .catch((e: unknown) => setError(t("app.settingsFailed", { msg: String(e) })));
  };
  // Esc 关闭文件抽屉（对齐交互规范：弹层 Esc 即关）
  useEffect(() => {
    if (!filesOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFilesOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filesOpen]);
  // ⌘P：展开右栏文件树面板（对齐 Harness ⌘P 工作区文件）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const k = e.key.toLowerCase();
      const cur = projects.find((p) => p.id === currentProjectId);
      if (!cur?.directory || tab !== "chat") return;
      if (k === "p") {
        e.preventDefault();
        setFilesOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, projects, currentProjectId]);
  // 阶段 D：首启向导（全新环境未配置 LLM 时展示）
  const [setup, setSetup] = useState<BootstrapStatus | null>(null);
  const [wizardError, setWizardError] = useState<string | null>(null);
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
          onDone: ({ usage, latency_s }) => {
            const u = usage as { total_tokens?: number } | null | undefined;
            const tokens = u?.total_tokens ?? 0;
            if (tokens || latency_s) setRunStats({ tokens, latency_s });
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

  // 插件启停联动：/api/plugins 返回的 id 是层 id（如 runtime-robot），按 plugin 名匹配
  const voiceEnabled = plugins.find((p) => p.plugin === "voice-input")?.enabled ?? true;
  const teamMode = plugins.find((p) => p.plugin === "team")?.enabled ?? true;
  // v0.7 三区：robot 是内核模块 → 启用时机器人模式入口可见；停用 → 入口隐藏（命令同步失效）
  const robotEnabled = plugins.find((p) => p.plugin === "robot")?.enabled ?? true;

  // robot 插件被停用且正处于机器人模式 → 自动回通用模式
  useEffect(() => {
    if (!robotEnabled && mode === "robot") setMode("general");
  }, [robotEnabled, mode]);

  const refreshPlugins = useCallback(() => {
    fetchPlugins()
      .then((r) => {
        setPlugins(r.plugins);
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
    fetchBootstrap()
      .then((s) => {
        setSetup(s);
        if (s.setup_required) setWizardError(null);
      })
      .catch(() => setSetup(null));
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
      setFilesTick((n) => n + 1);
    } catch (e) {
      setError(t("app.projectDeleteFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const send = (textOverride?: string) => {
    const raw = (textOverride ?? input).trim();
    if (!raw) return;
    // 计划模式（对齐 dsh /plan）：软约束——引导 agent 先出计划等待确认，不直接执行修改类操作
    const text = planMode ? t("app.planModePrefix") + "\n" + raw : raw;
    setInput("");
    setError(null);
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
    rec.start();
  };

  const stopVoice = () => {
    setListening(false);
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
    // 技能命令（对齐 dsh「/ 选技能干活」）：由已启用插件自动生成，
    // 选中后把输入作为消息发给模型，引导使用对应插件能力。
    // 过滤内部运行层插件（runtime-*/service-*），只暴露用户可感知能力
    const skillCmds: CommandDef[] = plugins
      .filter((p) => p.enabled && !p.disabled && !p.id.startsWith("runtime-") && !p.id.startsWith("service-"))
      .map((p) => {
        const short = p.id.startsWith("cap-") ? p.id.slice(4) : p.id;
        return {
          name: short,
          description: p.description,
          kind: "skill" as const,
          handler: () => "",
        };
      });
    const all: CommandDef[] = [
      help,
      ...skillCmds,
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
        name: "plan",
        description: t("cmd.planDesc"),
        handler: (raw) => {
          const next = !planMode;
          setPlanMode(next);
          // /plan 任务描述 → 直接带任务发送（对齐 dsh：/plan 任务 同时进入模式并提交任务）
          if (raw.trim() && next) {
            void send(raw.trim());
            return;
          }
          return next ? t("cmd.planOn") : t("cmd.planOff");
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
      {
        name: "robot",
        description: t("cmd.robotDesc"),
        handler: () => {
          setMode("robot");
          return t("cmd.robot");
        },
      },
      {
        name: "general",
        description: t("cmd.generalDesc"),
        handler: () => {
          setMode("general");
          return t("cmd.general");
        },
      },
    ];
    // v0.7 三区：robot 模块停用 → /robot 命令失效（返回提示，不切换）
    if (!robotEnabled) {
      const robotCmd = all.find((c) => c.name === "robot");
      if (robotCmd) {
        robotCmd.handler = () => t("cmd.robotDisabled");
      }
    }
    help.handler = (raw) => {
      void raw;
      return all.map((c) => `/${c.name} — ${c.description}`).join("\n");
    };
    return all;
  }, [theme, plugins, planMode, send]);

  // @ 引用目标（对齐 dsh「@ 点名上下文」）：引用项目，把名字与绑定目录带进会话
  const projectRefs = useMemo(
    () =>
      projects.map((p) => ({
        key: `p${p.id}`,
        label: p.name,
        detail: p.directory ? `目录：${p.directory}` : t("app.projectNoDir"),
        insert: `${p.name}（${p.directory ?? "未绑定目录"}）`,
      })),
    [projects],
  );

  // antd 主题：明暗算法 + 品牌色板注入 token（对齐 Octop：色板 × 模式）
  const antdThemeObj = {
    algorithm: theme === "dark" ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: PALETTES.find((p) => p.id === palette)?.color ?? "#4B74FA",
      borderRadius: 8,
    },
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ConfigProvider locale={zhCN} theme={antdThemeObj}>
        {mode === "robot" ? (
          <RobotMode error={error} onSend={(text) => void send(text)} onBack={() => setMode("general")} />
        ) : setup?.setup_required ? (
          <>
            <WelcomeWizard
              workspace={setup.workspace}
              onError={(msg) => setWizardError(msg)}
              onFinished={() => {
                setSetup((s) => (s ? { ...s, setup_required: false, llm_configured: true } : s));
                setWizardError(null);
                refreshPlugins();
                refreshProjects();
                setFilesTick((n) => n + 1);
              }}
            />
            {wizardError && <div className="error wizard-error">{wizardError}</div>}
          </>
        ) : (
          <HashRouter>
            <Routes>
              <Route
                path="/"
                element={
                  <MainLayout
                    expertDisplayName={currentExpert ?? "—"}
                    theme={theme}
                    palette={palette}
                    robotEnabled={robotEnabled}
                    onThemeToggle={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                    onPalette={setPalettePersist}
                    onOpenRobot={() => setMode("robot")}
                  />
                }
              >
                <Route index element={<Navigate to="/chat" replace />} />
                <Route
                  path="chat"
                  element={
                    <ChatPage
                      onOpenRobot={() => setMode("robot")}
                      projects={projects}
                      threads={threads}
                      currentProjectId={currentProjectId}
                      currentThreadId={currentThreadId}
                      threadTitle={threadTitle}
                      onNewThread={() => void newThread()}
                      onNewThreadIn={(pid) => void newThreadIn(pid)}
                      onSelectThread={(id) => void selectThread(id)}
                      onSelectProject={(id) => void selectProject(id)}
                      onCreateProject={async (name, directory) => {
                        try {
                          const p = await createProject(name, directory);
                          refreshProjects();
                          setFilesTick((n) => n + 1);
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
                      robotEnabled={robotEnabled}
                      teamMode={teamMode}
                      voiceEnabled={voiceEnabled}
                      providers={providers}
                      activeProvider={activeProvider}
                      activeModelKey={activeModelKey}
                      effort={effort}
                      input={input}
                      setInput={setInput}
                      listening={listening}
                      commands={commands}
                      references={projectRefs}
                      error={error}
                      scope={scope}
                      onScopeCycle={cycleScope}
                      runStats={runStats}
                      onSend={() => void send()}
                      onSendText={(text) => void send(text)}
                      onSuggestion={(text) => void send(text)}
                      onVoice={startVoice}
                      onVoiceStop={stopVoice}
                      onSelectModel={(p, m) => void selectModel(p, m)}
                      onEffort={setEffort}
                      filesOpen={filesOpen}
                      setFilesOpen={setFilesOpen}
                      filesTick={filesTick}
                    />
                  }
                />
                <Route
                  path="capabilities"
                  element={
                    <CapabilitiesPage
                      plugins={plugins}
                      busy={error !== null}
                      onChanged={onPluginChanged}
                    />
                  }
                />
                <Route path="skills" element={<SkillsPage />} />
                <Route
                  path="workspace"
                  element={
                    <WorkspacePage
                      projects={projects}
                      threads={threads}
                      currentProjectId={currentProjectId}
                      onSelectProject={(id) => void selectProject(id)}
                      onProjectCreated={refreshProjects}
                      onDeleteProject={(id) => void removeProject(id)}
                    />
                  }
                />
                <Route path="experts" element={<ExpertsPage />} />
                <Route
                  path="settings"
                  element={
                    <SettingsPage
                      settings={settings}
                      providers={providers}
                      theme={theme}
                      onThemeToggle={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                      onSettingsChanged={() => {
                        fetchSettings().then(setSettings).catch(() => {});
                        refreshExpert();
                      }}
                      onModelsChanged={() => fetchProviders().then((r) => setProviders(r.providers)).catch(() => {})}
                    />
                  }
                />
                <Route path="*" element={<Navigate to="/chat" replace />} />
              </Route>
            </Routes>
          </HashRouter>
        )}
        {settingsOpen && (
          <SettingsModal
            settings={settings}
            providers={providers}
            theme={theme}
            onThemeToggle={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            onClose={() => setSettingsOpen(false)}
            onSettingsChanged={() => {
              fetchSettings().then(setSettings).catch(() => {});
              refreshExpert();
            }}
            onModelsChanged={() => fetchProviders().then((r) => setProviders(r.providers)).catch(() => {})}
          />
        )}
      </ConfigProvider>
    </AssistantRuntimeProvider>
  );
}
