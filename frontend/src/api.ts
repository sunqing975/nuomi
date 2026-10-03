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
}

export interface McpServer {
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
