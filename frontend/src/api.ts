/** NuomiAPI：控制台唯一 API 出口（相对 /api，dev 走 vite proxy，build 后同源） */
export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: {} };
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch('/api' + path, opts);
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
  const res = await fetch('/api' + path, { method: 'POST', body: fd });
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
  model_plugin?: boolean;
}

export interface Skill {
  name: string;
  path: string;
  description: string;
  enabled: boolean;
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
}

export interface WorkspaceOverview {
  workspace: string;
  data_root: string;
  counts: Record<string, number>;
}

export interface PetModel {
  id: string;
  path: string;
  motions: string[];
  expressions: string[];
  builtin: boolean;
}

export interface PetModelsResponse {
  models: PetModel[];
  active: string | null;
}

// ---------- 对话（OpenAI Chat Completions 流式格式） ----------

export interface ChatEvent {
  type: 'token' | 'tool_call' | 'done';
  content?: string;
  name?: string;
}

export interface ToolEvent {
  kind: 'tool_call' | 'tool_result';
  name?: string;
  detail?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tool_events?: ToolEvent[];
}

/** 调用专家对话 SSE 流（OpenAI 格式），逐事件回调（token 累积由调用方处理）。 */
export async function chatStream(
  agentId: string,
  messages: string,
  threadId: string,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const res = await fetch(`/api/agents/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, thread_id: threadId }),
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
        // octop 原生事件帧：token / tool_call_chunk / done
        const ev = JSON.parse(payload) as {
          type?: string;
          content?: string;
          name?: string;
          args?: string;
        };
        if (ev.type === 'token' && ev.content) {
          onEvent({ type: 'token', content: ev.content });
        } else if (ev.type === 'tool_call_chunk' && ev.name) {
          onEvent({ type: 'tool_call', name: ev.name, content: ev.args });
        } else if (ev.type === 'done') {
          onEvent({ type: 'done' });
        }
      } catch { /* skip malformed */ }
    }
  }
}
