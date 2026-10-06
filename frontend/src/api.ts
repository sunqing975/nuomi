/** NuomiAPI：控制台唯一 API 出口（相对 /api，dev 走 vite proxy，build 后同源） */

/**
 * 本机 API token（`/api/*` 写操作鉴权，见 backend/app/infra/local_guard.py）。
 * 同源 GET 获取一次后缓存；跨站页面拿不到（守卫中间件拒绝非本机 Origin + CORS 限制响应）。
 */
let tokenPromise: Promise<string> | null = null;

function apiToken(): Promise<string> {
  if (!tokenPromise) {
    tokenPromise = fetch('/api/session-token')
      .then(res => (res.ok ? res.json() : { token: '' }))
      .then((data: { token?: string }) => data.token || '')
      .catch(() => '');
  }
  return tokenPromise;
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await apiToken();
  return token ? { 'X-Nuomi-Token': token } : {};
}

/**
 * 带 token 的 fetch：403 视为 token 轮换（后端进程重启会换 token），清缓存重取后重试一次。
 * 没有这层，后端重启后控制台的所有写操作都会一直 403，只能刷新页面才能恢复。
 */
async function authedFetch(path: string, init: RequestInit): Promise<Response> {
  const res = await fetch(path, init);
  if (res.status !== 403) return res;
  tokenPromise = null;
  const headers = {
    ...(init.headers as Record<string, string> | undefined),
    ...(await authHeaders()),
  };
  return fetch(path, { ...init, headers });
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeaders()) };
  const opts: RequestInit = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await authedFetch('/api' + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const get = <T>(p: string) => api<T>('GET', p);
export const post = <T>(p: string, b?: unknown) => api<T>('POST', p, b ?? {});
export const put = <T>(p: string, b: unknown) => api<T>('PUT', p, b);
export const patch = <T>(p: string, b: unknown) => api<T>('PATCH', p, b);
export const del = <T>(p: string) => api<T>('DELETE', p);

/** 文件上传（FormData，不手设 Content-Type，让浏览器带 boundary） */
export async function upload<T = unknown>(path: string, file: File): Promise<T> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await authedFetch('/api' + path, {
    method: 'POST',
    headers: { ...(await authHeaders()) },
    body: fd,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface Agent {
  agent_id: string;
  name: string;
  description: string;
  persona_mbti: string;
  system_prompt: string;
  enabled: boolean;
  icon_name: string;
  icon_url: string;
  color: string;
  welcome_message: string;
  kind: string;
  last_state: string;
  created_at: string;
}

export interface Plugin {
  plugin_id: string;
  name: string;
  kind: string;
  version: string;
  description: string;
  enabled: boolean;
  tool_count: number;
}

export interface Skill {
  name: string;
  path: string;
  description: string;
  enabled: boolean;
  requires_env?: string[];
  builtin?: boolean;
  lang?: string;
}

export interface SkillHubItem {
  slug: string;
  display_name: string;
  summary: string;
  description: string;
  scene: string;
  icon_url: string;
  downloads: number;
  stars: number;
  publisher: string;
  namespace: string;
  skill_slugs?: string[];
  skill_count?: number | null;
  requires_api_key?: boolean;
}

export interface SkillPackageSkill {
  slug: string;
  enabled: boolean;
}

export interface SkillPackage {
  id: string;
  name: string;
  description: string;
  icon_url: string;
  enabled: boolean;
  skill_count: number;
  path: string;
  skills: SkillPackageSkill[];
}

export interface ConnectorServer {
  name: string;
  transport: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
}

export interface WorkspaceOverview {
  workspace: string;
  data_root: string;
  counts: Record<string, number>;
}

export interface AvatarModel {
  id: string;
  path: string;
  motions: string[];
  expressions: string[];
  /** 该 VRM 是否真的带表情变形数据（binds 非空）；后端 list_models 提供 */
  expressions_have_data?: boolean;
  builtin: boolean;
}

export interface AvatarModelsResponse {
  models: AvatarModel[];
  active: string | null;
}

// ---------- 大模型 Provider ----------

export interface ModelConfig {
  id: string;
  name: string;
}

export interface Provider {
  id: string;
  name: string;
  base_url: string;
  /** 脱敏后的 key（GET）；编辑时留空 = 保持原值 */
  api_key: string;
  protocol: string;
  models: ModelConfig[];
}

export interface ProvidersResponse {
  providers: Provider[];
}

// ---------- 对话（octop 原生事件帧 SSE） ----------

export interface ChatEvent {
  /** error：后端流中途失败时补发的终止帧（没有它只会看到截断流） */
  type: 'token' | 'reasoning' | 'tool_call' | 'tool_result' | 'done' | 'error';
  content?: string;
  name?: string;
  detail?: string;
  /** 工具来源插件 id（后端 _publish_actions 附加，同名工具可辨识） */
  plugin_id?: string;
}

export interface ToolEvent {
  kind: 'tool_call' | 'tool_result';
  name?: string;
  detail?: string;
  plugin_id?: string;
}

/** 有序片段：一次对话按真实时间顺序穿插（思考→调工具→看结果→正文） */
export interface Segment {
  type: 'user' | 'text' | 'reasoning' | 'tool_call' | 'tool_result';
  content?: string;
  name?: string;
  args?: string;
  plugin_id?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  /** 有序片段（历史回读/流式累积统一结构；text 片段即正文） */
  segments: Segment[];
  /** 兼容旧字段：首段正文（渲染优先用 segments） */
  content?: string;
  tool_events?: ToolEvent[];
}

export interface ChatStreamOptions {
  /** per-turn 技能白名单（name/slug；不传=全量，传空数组=禁用全部） */
  skills?: string[];
  /** per-turn 连接器（不传=默认挂载，传空数组=不挂载） */
  connectors?: string[];
  /** per-turn 模型（provider/model；null/不传=默认模型，由后端按 agent 解析） */
  model?: string | null;
  /** per-turn 知识库（不传/空数组=不注入，[id...]=只检索这些库） */
  knowledge_base_ids?: string[];
}

// —— 知识库（M6）——

export interface OnnxPreset {
  id: string;
  size_gb: number | null;
  hf_source: string | null;
  supported: boolean;
}

export interface KnowledgeCapability {
  enabled: boolean;
  model: string;
  ready: boolean;
  downloaded: boolean;
  cache_dir: string;
  local_models: string[];
  presets: string[];
  presets_meta?: OnnxPreset[];
  deps_available: boolean;
  ocr_enabled: boolean;
  max_bases: number;
  downloading: string[];
}

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  icon_name: string;
  embedding_model: string;
  embedding_dim: number | null;
  doc_count: number;
  max_documents: number;
  created_at: string;
  updated_at: string;
}

export type KnowledgeDocStatus = 'pending' | 'processing' | 'ready' | 'failed';

export interface KnowledgeDocument {
  id: string;
  kb_id: string;
  path: string;
  filename: string;
  is_dir: boolean;
  content_type: string;
  byte_size: number;
  status: KnowledgeDocStatus;
  error_message: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

// —— 知识库 API（契约见 docs/knowledge-frontend-design.md §6）——
export const knowledgeApi = {
  capability: () => get<KnowledgeCapability>('/knowledge/capability'),
  feature: (b: { enabled?: boolean; model?: string }) => put<KnowledgeCapability>('/knowledge/feature', b),
  onnxDownload: (model: string) => post<{ started: boolean; reason?: string; model: string }>('/knowledge/onnx-download', { model }),
  onnxDelete: (model: string) => del<{ ok: boolean; removed: boolean }>(`/knowledge/onnx-model?model=${encodeURIComponent(model)}`),
  listBases: () => get<KnowledgeBase[]>('/knowledge-bases'),
  createBase: (b: Partial<KnowledgeBase>) => post<KnowledgeBase>('/knowledge-bases', b),
  getBase: (id: string) => get<KnowledgeBase>(`/knowledge-bases/${id}`),
  patchBase: (id: string, b: Partial<KnowledgeBase>) => patch<KnowledgeBase>(`/knowledge-bases/${id}`, b),
  deleteBase: (id: string) => del<{ ok: boolean }>(`/knowledge-bases/${id}`),
  listDocs: (kbId: string, prefix?: string) =>
    get<KnowledgeDocument[]>(`/knowledge-bases/${kbId}/documents${prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''}`),
  createFolder: (kbId: string, path: string) => post<KnowledgeDocument>(`/knowledge-bases/${kbId}/folders`, { path }),
  uploadDoc: (kbId: string, file: File) => upload<KnowledgeDocument>(`/knowledge-bases/${kbId}/documents`, file),
  createTextDoc: (kbId: string, b: { name: string; format: 'md' | 'txt'; content: string; path?: string }) =>
    post<KnowledgeDocument>(`/knowledge-bases/${kbId}/documents/text`, b),
  previewDoc: (kbId: string, docId: string) => get<{ id: string; filename: string; text: string }>(`/knowledge-bases/${kbId}/documents/${docId}/preview`),
  readContent: (kbId: string, docId: string) => get<{ id: string; filename: string; content_type: string; text: string }>(`/knowledge-bases/${kbId}/documents/${docId}/content`),
  writeContent: (kbId: string, docId: string, content: string) => put<KnowledgeDocument>(`/knowledge-bases/${kbId}/documents/${docId}/content`, { content }),
  renameDoc: (kbId: string, docId: string, newName: string) => post<KnowledgeDocument>(`/knowledge-bases/${kbId}/documents/${docId}/rename`, { new_name: newName }),
  reindexDoc: (kbId: string, docId: string) => post<KnowledgeDocument>(`/knowledge-bases/${kbId}/documents/${docId}/reindex`),
  deleteDoc: (kbId: string, docId: string) => del<{ ok: boolean }>(`/knowledge-bases/${kbId}/documents/${docId}`),
  fileUrl: (kbId: string, docId: string) => `/api/knowledge-bases/${kbId}/documents/${docId}/file`,
};

/**
 * 调用专家对话 SSE 流（octop 原生事件帧），逐事件回调（token 累积由调用方处理）。
 *
 * ``signal``：用户点「停止生成」或组件卸载时 abort —— 中止后 fetch reader 抛
 * ``AbortError``，后端也会因断连提前结束（不再继续跑完这一轮白烧 token）。
 */
export async function chatStream(
  agentId: string,
  messages: string,
  threadId: string,
  onEvent: (e: ChatEvent) => void,
  opts?: ChatStreamOptions,
  signal?: AbortSignal,
): Promise<void> {
  const res = await authedFetch(`/api/agents/${agentId}/chat`, {
    method: 'POST',
    headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, thread_id: threadId, ...opts }),
    signal,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep */ }
    throw new Error(detail);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      const t = line.trim();
      if (!t.startsWith('data:')) continue;
      const payload = t.slice(5).trim();
      if (!payload) continue;
      try {
        // octop 原生事件帧：token / tool_call_chunk / tool_result / done / error
        const ev = JSON.parse(payload) as {
          type?: string;
          content?: string;
          message?: string;
          name?: string;
          args?: string;
          plugin_id?: string;
          messages?: { name?: string; content?: string; plugin_id?: string }[];
        };
        if (ev.type === 'token' && ev.content) {
          onEvent({ type: 'token', content: ev.content });
        } else if (ev.type === 'reasoning' && ev.content) {
          onEvent({ type: 'reasoning', content: ev.content });
        } else if (ev.type === 'tool_call_chunk' && ev.name) {
          onEvent({ type: 'tool_call', name: ev.name, content: ev.args, plugin_id: ev.plugin_id });
        } else if (ev.type === 'tool_result') {
          const m = ev.messages?.[0];
          onEvent({ type: 'tool_result', name: m?.name, detail: m?.content, plugin_id: m?.plugin_id });
        } else if (ev.type === 'error') {
          onEvent({ type: 'error', content: ev.message });
        } else if (ev.type === 'done') {
          onEvent({ type: 'done' });
        }
      } catch { /* skip malformed */ }
    }
  }
}
