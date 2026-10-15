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
  /** 实时运行时状态（manager 内存缓存，running/stopped）；last_state 是 DB 持久化旧值，崩溃/重启后失真，UI 勿用 */
  runtime?: string;
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

/** HITL 人工审批请求（对话暂停，前端应展示审批卡片） */
export interface ApprovalRequest {
  action_requests?: { name?: string; args?: Record<string, unknown>; description?: string }[];
  review_configs?: { action_name?: string; allowed_decisions?: string[] }[];
}

/**
 * 本轮 token 用量（后端 infra/harness/chat.py 的 `_USAGE_KEYS` 白名单透传）。
 * cache_read_tokens = 前缀缓存命中；uncached_input_tokens = 未命中部分。
 */
export interface ChatUsage {
  input_tokens?: number;
  uncached_input_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
}

export interface ChatEvent {
  /** error：后端流中途失败时补发的终止帧（没有它只会看到截断流） */
  type: 'token' | 'reasoning' | 'tool_call' | 'tool_result' | 'done' | 'error' | 'approval_requested' | 'usage';
  content?: string;
  name?: string;
  detail?: string;
  /** usage：本轮用量帧载荷（此前前端没有这一分支，整条链的用量数据被静默丢掉） */
  usage?: ChatUsage;
  /** 工具来源插件 id（后端 _publish_actions 附加，同名工具可辨识） */
  plugin_id?: string;
  /** approval_requested：审批请求 id（续跑时回传） */
  request_id?: string;
  /** approval_requested：审批卡片数据（工具名/参数/描述） */
  request?: ApprovalRequest;
}

export interface ToolEvent {
  kind: 'tool_call' | 'tool_result';
  name?: string;
  detail?: string;
  plugin_id?: string;
}

/** 有序片段：一次对话按真实时间顺序穿插（思考→调工具→看结果→正文） */
export interface Segment {
  /**
   * 稳定 id（前端生成，后端不返回）。用于 React key：片段在流式期间会相邻合并、
   * 历史回读会整批替换，用数组下标作 key 会让 SegmentView 内部的折叠状态错位到别的片段。
   */
  id?: string;
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
  /**
   * 本轮 token 用量（来自 usage 帧）。只有流式当场才有：后端投影里不存它，
   * 所以刷新页面后历史消息不会带 —— 显示层按「有才显示」处理。
   */
  usage?: ChatUsage;
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

// —— 记忆 API（见 backend/app/transport/memory_api.py）——

/** 一条结构化记忆（octop 记忆引擎的 atom）：我因为哪句话、记住了什么 */
export interface MemoryAtom {
  id: string;
  assertion: string;
  verbatim_quote: string;
  importance: string;
  confidence: string;
  occurred_at: string;
  created_at: string;
  entity_id: string;
  entity_name?: string | null;
  entity_type?: string | null;
  deprecated_at?: string | null;
  superseded_by?: string | null;
  /** 来源对话的 thread_id（哪次聊天让我记住的） */
  source_thread_id?: string | null;
  source_at?: string | null;
  source_text?: string | null;
}

export interface MemoryEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  atom_count: number;
  last_promoted_at?: string | null;
}

export interface MemoryFile {
  name: string;
  bytes: number;
  updated_at: number;
  standard: boolean;
}

export interface MemoryOverview {
  agent_id: string;
  agent_name: string;
  exists: boolean;
  stats: {
    atoms: number;
    deprecated: number;
    entities: number;
    raw_events: number;
    episodes: number;
  };
  entities: MemoryEntity[];
  atoms: MemoryAtom[];
  total: number;
  files: MemoryFile[];
  max_file_bytes: number;
}

export const memoryApi = {
  overview: (
    agentId: string,
    opts?: { limit?: number; offset?: number; includeDeprecated?: boolean },
  ) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set('limit', String(opts.limit));
    if (opts?.offset != null) q.set('offset', String(opts.offset));
    if (opts?.includeDeprecated) q.set('include_deprecated', 'true');
    const suffix = q.toString() ? `?${q}` : '';
    return get<MemoryOverview>(`/agents/${agentId}/memory${suffix}`);
  },
  readFile: (agentId: string, name: string) =>
    get<{ name: string; content: string }>(
      `/agents/${agentId}/memory/files/${encodeURIComponent(name)}`,
    ),
  writeFile: (agentId: string, name: string, content: string) =>
    put<{ ok: boolean; name: string; bytes: number }>(
      `/agents/${agentId}/memory/files/${encodeURIComponent(name)}`,
      { content },
    ),
  /** 忘记一条记忆（后端走引擎的软遗忘，可审计） */
  forgetAtom: (agentId: string, atomId: string, reason?: string) =>
    del<{ ok: boolean; atom_id: string }>(
      `/agents/${agentId}/memory/atoms/${encodeURIComponent(atomId)}${
        reason ? `?reason=${encodeURIComponent(reason)}` : ''
      }`,
    ),
};

/**
 * SSE 逐行缓冲解析的**纯函数内核**（从 chatStream 抽出，便于按任意字节切片做单测）。
 *
 * 传入上一次未消费完的残留 `buf` 与新解码出的文本，返回本次解析出的事件 + 新的残留。
 * 网络 chunk 边界与行边界无关：半行必须留在 buf 里等下一次，否则标记跨 chunk 就会丢。
 */
export function feedChatStream(buf: string, chunk: string): { events: ChatEvent[]; buf: string } {
  const lines = (buf + chunk).split('\n');
  const rest = lines.pop() ?? '';
  const events: ChatEvent[] = [];
  for (const line of lines) {
    const t = line.trim();
    if (!t.startsWith('data:')) continue;
    const payload = t.slice(5).trim();
    if (!payload) continue;
    try {
      // octop 原生事件帧：token / tool_call_chunk / tool_result / usage / done / error
      const ev = JSON.parse(payload) as {
        type?: string;
        content?: string;
        message?: string;
        name?: string;
        args?: string;
        plugin_id?: string;
        messages?: { name?: string; content?: string; plugin_id?: string }[];
        request_id?: string;
        request?: ApprovalRequest;
        usage?: ChatUsage;
      };
      if (ev.type === 'token' && ev.content) {
        events.push({ type: 'token', content: ev.content });
      } else if (ev.type === 'reasoning' && ev.content) {
        events.push({ type: 'reasoning', content: ev.content });
      } else if (ev.type === 'tool_call_chunk' && ev.name) {
        events.push({ type: 'tool_call', name: ev.name, content: ev.args, plugin_id: ev.plugin_id });
      } else if (ev.type === 'tool_result') {
        const m = ev.messages?.[0];
        events.push({ type: 'tool_result', name: m?.name, detail: m?.content, plugin_id: m?.plugin_id });
      } else if (ev.type === 'error') {
        events.push({ type: 'error', content: ev.message });
      } else if (ev.type === 'approval_requested') {
        events.push({
          type: 'approval_requested',
          request_id: ev.request_id,
          request: ev.request,
        });
      } else if (ev.type === 'usage') {
        // 此前没有这条分支：后端每轮发的用量帧在这里被静默丢掉，界面永远看不到 token
        if (ev.usage) events.push({ type: 'usage', usage: ev.usage });
      } else if (ev.type === 'done') {
        events.push({ type: 'done' });
      }
    } catch { /* skip malformed */ }
  }
  return { events, buf: rest };
}

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
    const parsed = feedChatStream(buf, decoder.decode(value, { stream: true }));
    buf = parsed.buf;
    for (const e of parsed.events) onEvent(e);
  }
}

/**
 * HITL 人工审批：续跑被暂停的对话（approve 放行写工具 / reject 拒绝）。
 *
 * 返回与对话同构的 SSE 事件流（token / tool_result / done），调用方用与
 * chatStream 相同的 onEvent 继续消费。
 */
export async function chatApproval(
  agentId: string,
  threadId: string,
  decision: 'approve' | 'reject',
  onEvent: (e: ChatEvent) => void,
  opts?: { message?: string },
  signal?: AbortSignal,
): Promise<void> {
  const res = await authedFetch(`/api/agents/${agentId}/chat/approval`, {
    method: 'POST',
    headers: { ...(await authHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify({
      thread_id: threadId,
      decision,
      ...(opts?.message ? { message: opts.message } : {}),
    }),
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
    const parsed = feedChatStream(buf, decoder.decode(value, { stream: true }));
    buf = parsed.buf;
    for (const e of parsed.events) onEvent(e);
  }
}
