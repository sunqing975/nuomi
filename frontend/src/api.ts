/** V3 API 客户端：聊天 SSE + 插件管理（含导入/卸载）+ 设置系统 + 模型。 */
import { t } from "./i18n";

// ---------- API base（桌面端） ----------
// Tauri 侧拉起后端后注入 window.__NUOMI_API__（如 http://127.0.0.1:8xxxx）
// 与 window.__NUOMI_TOKEN__（sidecar 本地 token）；Web dev 下为空 → 走 vite proxy。
// 每次请求动态读取：注入发生在页面加载之后，避免竞态。
function apiBase(): string {
  const w = globalThis as Record<string, unknown>;
  return typeof w.__NUOMI_API__ === "string" ? (w.__NUOMI_API__ as string) : "";
}

function apiToken(): string {
  const w = globalThis as Record<string, unknown>;
  return typeof w.__NUOMI_TOKEN__ === "string" ? (w.__NUOMI_TOKEN__ as string) : "";
}

const _origFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  let url: string;
  if (typeof input === "string") url = input;
  else if (input instanceof URL) url = input.href;
  else url = input.url;
  let opts = init;
  const token = apiToken();
  if (token) {
    const headers = new Headers(init?.headers);
    headers.set("X-Nuomi-Token", token);
    opts = { ...init, headers };
  }
  const base = apiBase();
  if (base && url.startsWith("/api/")) {
    return _origFetch(base + url, opts);
  }
  return _origFetch(input, opts);
}) as typeof fetch;

// ---------- 聊天 ----------

export interface StreamHandlers {
  onMeta?: (threadId: string) => void;
  onToken?: (content: string) => void;
  onReasoning?: (content: string) => void;
  onTool?: (name: string) => void;
  onTitle?: (title: string) => void;
  onDone?: (threadId: string, full: string, emotion: string, usage: TokenUsage | null) => void;
  onError?: (message: string) => void;
}

export interface TokenUsage {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

export async function streamChat(
  message: string,
  threadId: string | null,
  handlers: StreamHandlers,
  effort?: string | null
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId, effort: effort || null }),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    handlers.onError?.(`HTTP ${res.status} ${text}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

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
        saveThreadId(String(payload.thread_id));
        handlers.onMeta?.(String(payload.thread_id));
        break;
      case "token":
        handlers.onToken?.(String(payload.content ?? ""));
        break;
      case "reasoning":
        handlers.onReasoning?.(String(payload.content ?? ""));
        break;
      case "tool":
        handlers.onTool?.(String(payload.name ?? ""));
        break;
      case "title":
        handlers.onTitle?.(String(payload.title ?? ""));
        break;
      case "done":
        handlers.onDone?.(
          String(payload.thread_id),
          String(payload.content ?? ""),
          String(payload.emotion ?? "neutral"),
          (payload.usage as TokenUsage) ?? null
        );
        break;
      case "error":
        handlers.onError?.(String(payload.message ?? t("api.unknownError")));
        break;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      dispatch(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 2);
    }
  }
}

export const THREAD_KEY = "nuomi.thread.id";
export function loadThreadId(): string | null {
  return localStorage.getItem(THREAD_KEY);
}
export function saveThreadId(id: string) {
  localStorage.setItem(THREAD_KEY, id);
}

// ---------- 插件（V3：fiber 状态 + 贡献） ----------

export interface PluginInfo {
  id: string;
  name: string;
  plugin: string;
  description: string;
  version: string;
  /** 来源：plugin（可选用能力，plugins/）| module（内核组成部分，backend/app/modules/） */
  category: "plugin" | "module";
  /** 内置（随系统启动，不可停用）；外部插件可开关 + 配参数 */
  builtin: boolean;
  enabled: boolean;
  disabled: boolean;
  config: Record<string, unknown>;
  /** plugin.json 声明的 settings schema（前端设置表单数据源） */
  settings: Record<string, unknown>;
  state: "pending" | "loading" | "active" | "failed" | "unloading" | "disposed" | "missing";
  error: string | null;
  waiting_on: string[];
  tools: string[];
  skills: string[];
  services: string[];
  events: string[];
  rebuilt: boolean;
  contributions: { skills: string[]; tools: string[]; services: string[]; events: string[] };
}

export interface PluginListResponse {
  plugins: PluginInfo[];
  available: { name: string; description: string }[];
}

export async function fetchPlugins(): Promise<PluginListResponse> {
  const res = await fetch("/api/plugins");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as PluginListResponse;
}

export async function togglePlugin(name: string): Promise<PluginInfo> {
  const res = await fetch(`/api/plugins/${name}/toggle`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return res.json() as Promise<PluginInfo>;
}

/** 目录 / git URL 安装（对应 Harness dsh plugin add） */
export async function installPlugin(name: string, source: string): Promise<{ installed: boolean }> {
  const res = await fetch("/api/plugins/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, source }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return res.json() as Promise<{ installed: boolean }>;
}

/** zip 上传安装（浏览器 GUI 对应物） */
export async function installPluginUpload(file: File): Promise<{ installed: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/plugins/install-upload", { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return res.json() as Promise<{ installed: boolean }>;
}

export async function uninstallPlugin(id: string): Promise<{ uninstalled: boolean }> {
  const res = await fetch(`/api/plugins/${id}/uninstall`, { method: "POST" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return res.json() as Promise<{ uninstalled: boolean }>;
}

// ---------- 设置系统（V3：全局 + 每插件 schema 表单） ----------

export interface PluginSettingView {
  id: string;
  name: string;
  settings: Record<string, unknown>;
  values: Record<string, unknown>;
}

export interface SettingsSnapshot {
  global: Record<string, unknown>;
  plugins: PluginSettingView[];
}

export async function fetchSettings(): Promise<SettingsSnapshot> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as SettingsSnapshot;
}

export async function setGlobalSetting(key: string, value: unknown): Promise<void> {
  const res = await fetch("/api/settings/global", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
}

export async function setPluginSetting(pluginId: string, patch: Record<string, unknown>): Promise<void> {
  const res = await fetch(`/api/settings/plugins/${pluginId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
}

// ---------- 模型（Phase 5：供应商 → 模型 → 思考强度） ----------

export interface ProviderModel {
  key: string; // 模型 key（供应商内唯一）
  model: string; // 实际请求 id
  label: string;
  description: string;
  efforts: string[]; // 该模型支持的思考强度
  active: boolean;
  available: boolean;
}

export interface ProviderModel {
  key: string;
  model: string;
  label: string;
  description: string;
  efforts: string[]; // 该模型支持的思考强度
  context_window?: number; // 上下文窗口（tokens）
  max_output?: number; // 单次最大输出（tokens）
  active: boolean;
  available: boolean;
  configured?: boolean;
}

export interface ModelProvider {
  key: string;
  label: string;
  models: ProviderModel[];
  base_url?: string;
  protocol?: string;
  custom?: boolean;
  configured?: boolean;
  api_key_masked?: string;
}

export interface ModelsResponse {
  providers: ModelProvider[];
  active_provider?: string;
  active_model?: string;
  effort?: string | null;
}

export async function fetchProviders(): Promise<ModelsResponse> {
  const res = await fetch("/api/models");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as ModelsResponse;
}

export async function activateModel(
  provider: string,
  model: string,
  effort?: string | null,
): Promise<ModelsResponse> {
  const res = await fetch("/api/models/activate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, model, effort: effort ?? null }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return (await res.json()) as ModelsResponse;
}

// --- Phase 6：自定义供应商 + API Key + 模型目录 ---

export interface CustomModelRow {
  id: string;
  label?: string;
  efforts?: string[];
  context_window?: number;
  max_output?: number;
}

export async function addCustomProvider(body: {
  name: string;
  base_url: string;
  protocol?: string;
  api_key?: string;
  models?: CustomModelRow[];
}): Promise<ModelsResponse> {
  const res = await fetch("/api/models/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text().catch(() => "")}`);
  return (await res.json()) as ModelsResponse;
}

export async function updateCustomProvider(
  key: string,
  patch: {
    name?: string;
    base_url?: string;
    protocol?: string;
    api_key?: string;
    models?: CustomModelRow[];
  },
): Promise<ModelsResponse> {
  const res = await fetch(`/api/models/custom/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text().catch(() => "")}`);
  return (await res.json()) as ModelsResponse;
}

export async function deleteCustomProvider(key: string): Promise<ModelsResponse> {
  const res = await fetch(`/api/models/custom/${encodeURIComponent(key)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as ModelsResponse;
}

export async function setProviderKey(provider: string, apiKey: string): Promise<void> {
  const res = await fetch("/api/models/provider-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function fetchAvailableModels(
  baseUrl: string,
  apiKey = "",
): Promise<string[]> {
  const q = new URLSearchParams({ base_url: baseUrl });
  if (apiKey) q.set("api_key", apiKey);
  const res = await fetch(`/api/models/available?${q.toString()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text().catch(() => "")}`);
  const body = (await res.json()) as { models: string[] };
  return body.models;
}

// ---------- 项目 / 会话（V3 增强，Harness workspace/session 轻量版） ----------

export interface ProjectInfo {
  id: number;
  name: string;
  created_at: string;
  thread_count: number;
  /** 绑定的本机目录（绝对路径）；未绑定为 null */
  directory: string | null;
}

export interface ThreadInfo {
  id: string;
  project_id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export async function fetchProjects(): Promise<ProjectInfo[]> {
  const res = await fetch("/api/projects");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { projects: ProjectInfo[] };
  return body.projects;
}

export async function createProject(name: string, directory?: string | null): Promise<ProjectInfo> {
  const res = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, directory: directory ?? null }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ProjectInfo>;
}

/** 绑定 / 解绑（传 null/空串解绑）项目目录 */
export async function setProjectDirectory(projectId: number, directory: string | null): Promise<ProjectInfo> {
  const res = await fetch(`/api/projects/${projectId}/directory`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<ProjectInfo>;
}

export async function deleteProject(id: number): Promise<void> {
  const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function fetchThreads(projectId?: number | null): Promise<ThreadInfo[]> {
  const q = projectId ? `?project_id=${projectId}` : "";
  const res = await fetch(`/api/threads${q}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { threads: ThreadInfo[] };
  return body.threads;
}

export async function createThread(projectId?: number | null, title = ""): Promise<ThreadInfo> {
  const res = await fetch("/api/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId ?? null, title }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ThreadInfo>;
}

export async function renameThread(threadId: string, title: string): Promise<void> {
  const res = await fetch(`/api/threads/${threadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function deleteThread(threadId: string): Promise<void> {
  const res = await fetch(`/api/threads/${threadId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ---------- 阶段 B：工作区（前端项目树 = 工作区目录） ----------

export interface WorkspaceEntry {
  name: string;
  type: "dir" | "file";
  size?: number;
  children?: WorkspaceEntry[];
}

export interface WorkspaceTree {
  root: string;
  entries: WorkspaceEntry[];
}

export async function fetchWorkspaceTree(): Promise<WorkspaceTree> {
  const res = await fetch("/api/workspace/tree");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<WorkspaceTree>;
}

/** 项目绑定的本地目录文件树（一个项目 = 一个目录；未绑定目录 → HTTP 404） */
export async function fetchProjectTree(projectId: number): Promise<WorkspaceTree> {
  const res = await fetch(`/api/projects/${projectId}/tree`);
  if (res.status === 404) throw new Error("NO_DIR");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<WorkspaceTree>;
}

/** 项目目录命令执行（复用后端 shell 沙箱；未绑定目录 → 404 "NO_DIR"） */
export async function execShell(projectId: number, command: string): Promise<{ output: string; cwd: string }> {
  const res = await fetch(`/api/projects/${projectId}/shell/exec`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (res.status === 404) throw new Error("NO_DIR");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as { output: string; cwd: string };
}

// ---------- 阶段 D：首启向导 ----------

export interface BootstrapStatus {
  setup_required: boolean;
  workspace: string;
  llm_configured: boolean;
}

export async function fetchBootstrap(): Promise<BootstrapStatus> {
  const res = await fetch("/api/bootstrap");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<BootstrapStatus>;
}

export async function saveBootstrapWorkspace(workspace: string): Promise<{ ok: boolean; workspace: string }> {
  const res = await fetch("/api/bootstrap/workspace", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ ok: boolean; workspace: string }>;
}

// ---------- 专家库（对齐 Octop 专家概念：人格 + 能力模板资产） ----------

export interface ExpertInfo {
  id: string;
  name: string;
  display_name: string;
  description: string;
  icon_name: string;
  color: string;
  default: boolean;
}

export interface ExpertsResponse {
  experts: ExpertInfo[];
  current: string;
}

export async function fetchExperts(): Promise<ExpertsResponse> {
  const res = await fetch("/api/experts");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ExpertsResponse>;
}

export async function activateExpert(name: string): Promise<{ ok: boolean; name: string; restart_required: boolean }> {
  const res = await fetch(`/api/experts/${encodeURIComponent(name)}/activate`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ ok: boolean; name: string; restart_required: boolean }>;
}

// ---------- 技能（独立文档资产，领域语义对齐 Octop skill） ----------

export interface SkillInfo {
  name: string;
  description: string;
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const res = await fetch("/api/skills");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { skills: SkillInfo[] };
  return body.skills ?? [];
}

// ---------- 连接器 / 知识库（领域语义，对齐 Octop /connectors /knowledge-bases） ----------

export interface ConnectorInfo {
  name: string;
  description: string;
  type: string;
  services: string[];
  state: "active" | "failed";
}

export async function fetchConnectors(): Promise<ConnectorInfo[]> {
  const res = await fetch("/api/connectors");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { connectors: ConnectorInfo[] };
  return body.connectors ?? [];
}

export interface KnowledgeDocument {
  id: string;
  content: string;
  category: string;
  ts: number;
}

export async function fetchKnowledgeDocuments(): Promise<{ store: string; documents: KnowledgeDocument[] }> {
  const res = await fetch("/api/knowledge/documents");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as { store: string; documents: KnowledgeDocument[] };
}

export async function deleteKnowledgeDocument(id: string): Promise<void> {
  const res = await fetch(`/api/knowledge/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ---------- 专家克隆 / 删除（对齐 Octop create-from-template） ----------

export async function cloneExpert(name: string, displayName: string): Promise<{ name: string; display_name: string }> {
  const res = await fetch(`/api/experts/${encodeURIComponent(name)}/clone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as { name: string; display_name: string };
}

export async function deleteExpert(name: string): Promise<void> {
  const res = await fetch(`/api/experts/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}
