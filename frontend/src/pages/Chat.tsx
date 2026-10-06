import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Button, Drawer, Empty, Input, Popconfirm, Popover, Select, Space, Switch, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, BookOutlined, CloseOutlined, DeleteOutlined, HistoryOutlined, PlusOutlined, SendOutlined, StopOutlined, RobotOutlined, ThunderboltOutlined, UserOutlined,
} from '@ant-design/icons';
import {
  del, get, post, chatStream, knowledgeApi,
  type Agent, type ChatEvent, type ChatMessage, type ConnectorServer, type KnowledgeBase, type Plugin, type Segment, type Skill, type SkillPackage,
} from '../api';
import { parseKnowledgeCitations, type KnowledgeCitation } from '../utils/parseKnowledgeCitations';
import { appendStreamSegment } from '../utils/streamSegments';
import { sanitizePluginHtml } from '../utils/sanitizePluginHtml';

/** 模型「自动」哨兵值：发送时不传 model（null），由后端按 agent 默认模型解析（对齐 Octop AUTO 语义） */
const MODEL_AUTO = 'auto';

/**
 * 片段稳定 id 生成器（模块级自增，流式片段进 state 时生成）。
 * 为什么不能用数组下标当 key：SegmentView 的折叠状态 `open` 活在组件实例里，
 * 而流式期间相邻同类片段会合并、历史回读会整批替换 —— 下标 key 会让 React 把
 * 上一个片段的实例复用到新片段上，折叠状态就错位了。id 跟着片段本身走才稳定。
 */
let segmentSeq = 0;
function nextSegmentId(): string {
  segmentSeq += 1;
  return `seg-${segmentSeq}`;
}

interface SessionMeta {
  thread_id: string;
  title: string;
  updated_at: number;
}

interface ChatState {
  agent_id: string;
  current: string | null;
  sessions: SessionMeta[];
}

/** 能力 chip（输入框上方，可移除） */
function AbilityChip({ label, color, onRemove }: { label: string; color: string; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999,
      fontSize: 12, background: `${color}1a`, color, border: `1px solid ${color}55`,
    }}>
      {label}
      <CloseOutlined style={{ fontSize: 10, cursor: 'pointer' }} onClick={onRemove} />
    </span>
  );
}

/** 知识库引用标签条（citations 列表 → Tag 行） */
function CitationsTags({ citations }: { citations: KnowledgeCitation[] }) {
  if (!citations.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 12, color: 'var(--label-3)', marginBottom: 4 }}>📚 知识库引用</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {citations.map(c => (
          <Tag key={c.docId} style={{ fontSize: 12, margin: 0 }}>
            {c.kbName || '知识库'} · {c.filename}
          </Tag>
        ))}
      </div>
    </div>
  );
}

/** 知识库引用条（search_knowledge 工具输出含 citations 标记时展示来源） */
function KnowledgeCitations({ raw }: { raw?: string }) {
  const { text, citations } = parseKnowledgeCitations(raw);
  if (!citations.length) return null;
  return (
    <div>
      <CitationsTags citations={citations} />
      {text ? (
        <div style={{ color: 'var(--label-2)', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto' }}>
          {text}
        </div>
      ) : null}
    </div>
  );
}

/** 正文 Markdown 渲染：剥离知识库引用标记 → md 渲染正文 → 引用标签条（历史/流式正文共用） */
function MarkdownText({ raw, placeholder }: { raw?: string; placeholder?: string }) {
  const { text, citations } = parseKnowledgeCitations(raw);
  if (!text.trim() && !citations.length) return <>{placeholder ?? ''}</>;
  return (
    <div>
      {text.trim() ? (
        <div className="md-body" style={{ fontSize: 14, lineHeight: 1.6, wordBreak: 'break-word' }}>
          <ReactMarkdown>{text}</ReactMarkdown>
        </div>
      ) : null}
      <CitationsTags citations={citations} />
    </div>
  );
}

/** 单片段渲染：思考折叠块 / 工具调用卡片 / 工具结果卡片（按对话真实顺序穿插） */
/** 插件聊天面板（第三层插件能力，对齐 octop ui/ 协议）：
 *  manifest.json 声明 {"ui": {"tool": "工具名", "render": "index.js"}}，
 *  index.js ES module export default { render(ctx) => HTML }。
 *  工具结果命中声明 → 动态加载 render 渲染成聊天卡片；未命中保持文本折叠。
 */
interface PluginUiTarget { pluginId: string; render: string; }

const pluginUiRegistry = new Map<string, PluginUiTarget>();
let pluginUiLoaded = false;

async function loadPluginUiRegistry() {
  if (pluginUiLoaded) return;
  pluginUiLoaded = true;
  try {
    const plugins = await get<Plugin[]>('/plugins');
    for (const p of plugins) {
      if (!p.enabled) continue;
      let manifest: { ui?: { tool?: string; render?: string } };
      try {
        manifest = await get(`/plugins/${p.plugin_id}/ui-manifest`);
      } catch {
        continue; // 未声明聊天面板（404）
      }
      if (manifest?.ui?.tool && manifest.ui.render) {
        pluginUiRegistry.set(manifest.ui.tool, { pluginId: p.plugin_id, render: manifest.ui.render });
      }
    }
  } catch {
    // 面板加载失败不影响对话
  }
}

/** 工具结果卡片容器样式：对齐 octop builtin 卡片（白底/圆角/边框/阴影，硬编码保证可见） */
const toolCardStyle: React.CSSProperties = {
  marginTop: 4,
  padding: '12px 14px',
  borderRadius: 10,
  border: '1px solid var(--line-3)',
  background: 'var(--surface)',
  color: 'var(--label-1)',
  maxWidth: 480,
  boxShadow: '0 1px 2px rgba(16, 24, 40, 0.06)',
  fontSize: 13,
};

/** 工具结果卡片：动态加载插件 render 模块，调 render(ctx) 产出 HTML 渲染
 *  ctx: { result, args, data（解析后的结构化输出）, textFallback } —— 对齐 octop 渲染协议 */
function PluginToolCard({ toolName, result, args }: { toolName: string; result: string; args?: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let target = pluginUiRegistry.get(toolName);
      if (!target) {
        await loadPluginUiRegistry(); // 兜底：registry 未就绪时补一次
        target = pluginUiRegistry.get(toolName);
      }
      if (!target) { setFailed(true); return; }
      try {
        // 运行时绝对 URL 动态加载（@vite-ignore：非构建期模块）
        const mod = await import(/* @vite-ignore */ `/api/plugins/${target.pluginId}/ui/${target.render}`);
        const fn = mod?.default?.render;
        // 尝试解析结构化输出传给 renderer（对齐 octop：data / textFallback 进 ctx）
        let data: unknown = null;
        try { data = JSON.parse(result); } catch { /* 非 JSON 文本 */ }
        const ctx = { result, args, data, textFallback: result };
        const out = typeof fn === 'function' ? String(fn(ctx) ?? '') : '';
        if (cancelled) return;
        // XSS 防护：插件 renderer 产出 HTML，而它插值的数据来自 tool 结果（可能是
        // LLM 读进来的外部网页/文档）。净化逻辑抽到 utils/sanitizePluginHtml 并单测覆盖
        // （原先内联调用无法单测，且 <img onerror> / <svg onload> / <iframe src=javascript:>
        // 等 8 种 payload 全部能绕过旧的「正则剥 <script>」实现 —— 与后端同源，注入即可读
        // /api/settings/env 明文密钥）。
        // supported=false 表示 DOM 不可用：此时 DOMPurify 会静默原样返回，必须显式降级。
        const { html: clean, supported } = sanitizePluginHtml(out);
        if (!supported) {
          setFailed(true);
          return;
        }
        setHtml(clean);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [toolName, result, args]);

  if (failed) {
    // 兜底：渲染失败/未声明面板时保留卡片样式框 + 原始结果文本（React 文本节点自动转义）
    return <div style={toolCardStyle}>{result}</div>;
  }
  if (html === null) {
    return <div style={{ fontSize: 12, color: 'var(--label-3)', marginTop: 4 }}>加载插件卡片…</div>;
  }
  if (!html.trim()) {
    // render 返回空：同样兜底为原始结果文本
    return <div style={toolCardStyle}>{result}</div>;
  }
  return (
    <div style={toolCardStyle} dangerouslySetInnerHTML={{ __html: html }} />
  );
}

function SegmentView({ seg }: { seg: Segment }) {
  const isTool = seg.type === 'tool_call' || seg.type === 'tool_result';
  const hasCard = seg.type === 'tool_result' && pluginUiRegistry.has(seg.name || '');
  // 有聊天卡片的工具结果默认展开（卡片是醒目结果，不需先点折叠）
  const [open, setOpen] = useState(isTool && hasCard);
  if (seg.type === 'reasoning') {
    return (
      <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--label-4)' }}>
        <a onClick={() => setOpen(v => !v)} style={{ color: 'var(--label-4)' }}>
          {open ? '▾' : '▸'} 💭 深度思考
        </a>
        {open && (
          <div style={{
            marginTop: 4, padding: '6px 8px', background: 'var(--surface-2)', borderRadius: 6,
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200, overflow: 'auto',
          }}>
            {seg.content}
          </div>
        )}
      </div>
    );
  }
  if (seg.type === 'tool_call' || seg.type === 'tool_result') {
    const isCall = seg.type === 'tool_call';
    const hasDetail = isCall ? !!(seg.args && seg.args !== '{}') : !!seg.content;
    const hasCard = seg.type === 'tool_result' && pluginUiRegistry.has(seg.name || '');
    return (
      <div style={{
        marginBottom: 6, fontSize: 12, padding: '4px 8px', borderRadius: 6, maxWidth: 520,
        background: isCall ? '#f0f7ff' : '#f6ffed',
        border: `1px solid ${isCall ? '#d6e4ff' : '#d9f7be'}`,
      }}>
        <a onClick={() => setOpen(v => !v)} style={{ color: isCall ? '#1677ff' : '#52c41a', fontWeight: 500, cursor: 'pointer' }}>
          {open ? '▾' : '▸'} {isCall ? '⚙ 调用' : '✓ 结果'} {seg.name || '(工具)'}
          {seg.plugin_id && (
            <Tag style={{ fontSize: 10, marginLeft: 6, marginRight: 0 }}>{seg.plugin_id}</Tag>
          )}
        </a>
        {open && hasDetail && (
          <div style={{ color: 'var(--label-2)', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: isCall ? 80 : 120, overflow: 'auto' }}>
            {hasCard
              ? <PluginToolCard toolName={seg.name || ''} result={seg.content ?? ''} args={seg.args} />
              : (isCall ? seg.args : (seg.name === 'search_knowledge' ? <KnowledgeCitations raw={seg.content} /> : seg.content))}
          </div>
        )}
      </div>
    );
  }
  return null;
}

/** 技能选择器（Popover 三分组：已启用技能 / 内置技能 / 已启用技能包；技能包=整包勾选） */
function SkillPicker({
  skills, builtin, packages, selected, onToggleSkill, onTogglePackage,
}: {
  skills: Skill[]; builtin: Skill[]; packages: SkillPackage[];
  selected: string[]; onToggleSkill: (name: string) => void; onTogglePackage: (pkg: SkillPackage) => void;
}) {
  const GroupLabel = ({ children }: { children: React.ReactNode }) => (
    <div style={{ fontSize: 11, color: 'var(--label-4)', padding: '6px 10px 2px', fontWeight: 600 }}>{children}</div>
  );
  const Row = ({ active, onClick, title, desc }: { active: boolean; onClick: () => void; title: string; desc?: string }) => (
    <div
      onClick={onClick}
      style={{
        display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 10px', borderRadius: 8,
        cursor: 'pointer', background: active ? '#e6f4ff' : 'transparent', marginBottom: 2,
      }}
    >
      <span style={{ color: 'var(--link)', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {desc ? (
          <div style={{ fontSize: 12, color: 'var(--label-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{desc}</div>
        ) : null}
      </div>
    </div>
  );
  const empty = skills.length === 0 && builtin.length === 0 && packages.length === 0;
  const content = (
    <div style={{ width: 300, maxHeight: 340, overflow: 'auto' }}>
      {empty ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无可用技能，先到「技能」页安装/启用</div>
      ) : (
        <>
          {skills.length > 0 && (
            <>
              <GroupLabel>已启用的技能</GroupLabel>
              {skills.map(s => (
                <Row key={s.name} active={selected.includes(s.name)} onClick={() => onToggleSkill(s.name)}
                  title={s.name} desc={s.description || undefined} />
              ))}
            </>
          )}
          {builtin.length > 0 && (
            <>
              <GroupLabel>内置技能</GroupLabel>
              {builtin.map(b => (
                <Row key={`builtin-${b.name}`} active={selected.includes(b.name)} onClick={() => onToggleSkill(b.name)}
                  title={b.name} desc={b.description || '随 harness 内置分发，只读'} />
              ))}
            </>
          )}
          {packages.length > 0 && (
            <>
              <GroupLabel>已启用的技能包</GroupLabel>
              {packages.map(p => {
                const slugs = (p.skills || []).filter(s => s.enabled).map(s => s.slug);
                const active = slugs.length > 0 && slugs.some(x => selected.includes(x));
                return (
                  <Row key={`pkg-${p.id}`} active={active} onClick={() => onTogglePackage(p)}
                    title={`${p.name}（${p.skill_count ?? slugs.length} 技能）`} desc={p.description || undefined} />
                );
              })}
            </>
          )}
        </>
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<ThunderboltOutlined />}>技能{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

/** 连接器选择器（Popover Switch 列表） */
function ConnectorPicker({ connectors, selected, onToggle }: { connectors: ConnectorServer[]; selected: string[]; onToggle: (name: string) => void }) {
  const content = (
    <div style={{ width: 280, maxHeight: 320, overflow: 'auto' }}>
      {connectors.length === 0 ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无连接器，先到「连接器」页添加</div>
      ) : (
        connectors.map(c => (
          <div key={c.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', borderRadius: 8 }}>
            <span style={{ fontSize: 13 }}>{c.name}</span>
            <Switch size="small" checked={selected.includes(c.name)} onChange={() => onToggle(c.name)} />
          </div>
        ))
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<ApiOutlined />}>连接器{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

/** 知识库选择器（Popover 多选；不选 = 不注入，与技能/连接器同维度） */
function KnowledgePicker({ bases, selected, onToggle, disabled }: { bases: KnowledgeBase[]; selected: string[]; onToggle: (id: string) => void; disabled?: boolean }) {
  const content = (
    <div style={{ width: 300, maxHeight: 320, overflow: 'auto' }}>
      {bases.length === 0 ? (
        <div style={{ color: 'var(--label-3)', textAlign: 'center', padding: 16 }}>暂无知识库，先到「知识库」页创建</div>
      ) : (
        bases.map(b => {
          const active = selected.includes(b.id);
          return (
            <div
              key={b.id}
              onClick={() => onToggle(b.id)}
              style={{
                display: 'flex', gap: 8, alignItems: 'flex-start', padding: '8px 10px', borderRadius: 8,
                cursor: 'pointer', background: active ? '#fff0f6' : 'transparent', marginBottom: 2,
              }}
            >
              <span style={{ color: '#eb2f96', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                {b.description ? (
                  <div style={{ fontSize: 12, color: 'var(--label-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.description}</div>
                ) : null}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
  return (
    <Popover trigger="click" placement="topLeft" content={content}>
      <Button size="small" icon={<BookOutlined />} disabled={disabled}>知识库{selected.length ? ` (${selected.length})` : ''}</Button>
    </Popover>
  );
}

/** 轨迹抽屉：当前会话全部工具事件时间线 */
function TrajectoryDrawer({ open, onClose, messages }: { open: boolean; onClose: () => void; messages: ChatMessage[] }) {
  const rows = useMemo(() => {
    const out: { seq: number; kind: 'tool_call' | 'tool_result'; name?: string; detail?: string }[] = [];
    messages.forEach(m => {
      m.segments.forEach(s => {
        if (s.type === 'tool_call' || s.type === 'tool_result') {
          out.push({ seq: out.length + 1, kind: s.type, name: s.name, detail: s.type === 'tool_result' ? s.content : s.args });
        }
      });
    });
    return out;
  }, [messages]);
  return (
    <Drawer title={`轨迹 · ${rows.length} 次工具调用`} open={open} onClose={onClose} width={420}>
      {rows.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本次会话还没有工具调用" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map(r => (
            <div key={r.seq} style={{ border: '1px solid var(--line-1)', borderRadius: 8, padding: '8px 10px', background: r.kind === 'tool_call' ? '#f0f7ff' : '#f6ffed' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Tag color={r.kind === 'tool_call' ? 'blue' : 'green'} style={{ margin: 0 }}>{r.seq}</Tag>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{r.kind === 'tool_call' ? '⚙ 调用' : '✓ 结果'} {r.name || ''}</span>
              </div>
              {r.detail ? (
                <div style={{ fontSize: 12, color: 'var(--label-2)', marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 160, overflow: 'auto' }}>{r.detail}</div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
}

export default function ChatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streamSegments, setStreamSegments] = useState<Segment[]>([]);
  // 流被中断（无 done 帧）时保留待重试的那一轮
  const [interrupted, setInterrupted] = useState<{ text: string; threadId: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /** 卸载标记：卸载触发的 abort 不该给已销毁的页面弹提示/写状态 */
  const unmountedRef = useRef(false);
  // 能力选择（per-turn 注入：技能白名单 / 连接器挂载 / 模型）
  const [skills, setSkills] = useState<Skill[]>([]);
  const [builtinSkills, setBuiltinSkills] = useState<Skill[]>([]);
  const [skillPackages, setSkillPackages] = useState<SkillPackage[]>([]);
  const [connectors, setConnectors] = useState<ConnectorServer[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [kbEnabled, setKbEnabled] = useState(false);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedConnectors, setSelectedConnectors] = useState<string[]>([]);
  const [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds] = useState<string[]>([]);
  const [modelOptions, setModelOptions] = useState<{ value: string; label: string }[]>([]);
  // 模型默认选中「自动」，用户显式选择后才覆盖；移除选择回到「自动」
  const [selectedModel, setSelectedModel] = useState<string | null>(MODEL_AUTO);
  const [trajectoryOpen, setTrajectoryOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  /**
   * 是否贴近底部（滚动跟随开关，滚动事件里更新）。
   * 原实现每个 token 都 scrollTo({behavior:'smooth'})：流式期间用户一往上翻就被拉回底部，
   * 历史根本看不了。改成只在自己贴底时才跟随，且流式增量用 'auto'（smooth 的动画会
   * 持续打断用户滚动）。
   */
  const stickToBottomRef = useRef(true);

  /**
   * 清空当前会话视图（切会话/切专家/删会话）。
   * 一并把滚动跟随复位成「跟随」：否则上个会话的上滑状态会让新会话停在中间不动，
   * 而换会话时用户期望看到最新一条。
   */
  const clearView = () => {
    stickToBottomRef.current = true;
    setMessages([]);
    setStreamSegments([]);
  };

  const loadAgents = useCallback(async () => {
    const rows = await get<Agent[]>('/agents');
    setAgents(rows);
    if (rows.length && !agentId) setAgentId(rows[0].agent_id);
  }, [agentId]);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // 插件聊天面板注册表（工具结果命中 ui/manifest 声明的渲染成卡片）
  useEffect(() => { loadPluginUiRegistry(); }, []);

  // 能力清单（已启用技能 + 内置技能 + 技能包 + 连接器 + 模型 + 知识库），对话框里按 per-turn 选择
  useEffect(() => {
    Promise.all([
      get<Skill[]>('/skills'),
      get<Skill[]>('/skills/builtin'),
      get<SkillPackage[]>('/skill-packages'),
      get<ConnectorServer[]>('/connectors'),
      get<{ providers: { id: string; name: string; models: { id: string }[] }[] }>('/settings/providers'),
    ])
      .then(([sk, builtin, pkgs, conn, provs]) => {
        setSkills(sk.filter(s => s.enabled));
        setBuiltinSkills(builtin);
        setSkillPackages(pkgs.filter(p => p.enabled));
        setConnectors(conn);
        setModelOptions([
          // 「自动」永远在首位且默认选中：不传 model，后端按 agent 默认模型解析
          { value: MODEL_AUTO, label: '自动（默认）' },
          ...provs.providers.flatMap(p =>
            (p.models || []).map(m => ({ value: `${p.id}/${m.id}`, label: `${p.name} · ${m.id}` })),
          ),
        ]);
      })
      .catch(() => { /* 能力加载失败不阻塞对话 */ });
    // 知识库：能力开关 + 库列表（仅启用库可选；停用库不出现在选择器）
    knowledgeApi.capability().then(c => setKbEnabled(Boolean(c.enabled))).catch(() => {});
    knowledgeApi.listBases().then(rows => setKnowledgeBases(rows.filter(b => b.enabled))).catch(() => {});
  }, []);

  // 历史加载（octop checkpointer，按线程；后端返回有序片段流，归组为消息块）
  const loadHistory = useCallback(async (agent: string, tid: string) => {
    const rows = await get<Segment[]>(
      `/agents/${agent}/chat/history?thread_id=${encodeURIComponent(tid)}`,
    );
    const blocks: ChatMessage[] = [];
    let asst: ChatMessage | null = null;
    for (let i = 0; i < rows.length; i += 1) {
      // 历史片段用行序号（seq）作稳定 id：同一条历史每次回读拿到同一个 id，渲染不重挂
      const seg: Segment = { ...rows[i], id: rows[i].id ?? `hist-${i}` };
      if (seg.type === 'user') {
        asst = null;
        blocks.push({ role: 'user', segments: [{ type: 'text', content: seg.content || '', id: `hist-u-${i}` }] });
      } else {
        if (!asst) {
          asst = { role: 'assistant', segments: [] };
          blocks.push(asst);
        }
        asst.segments.push(seg);
      }
    }
    setMessages(blocks);
  }, []);

  // 专家变化 → 读后端会话状态 + 清空能力选择（各专家能力不同）
  useEffect(() => {
    if (!agentId) return;
    let alive = true;
    setSelectedSkills([]);
    setSelectedConnectors([]);
    setSelectedKnowledgeBaseIds([]);
    (async () => {
      try {
        const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
        if (!alive) return;
        setSessions(st.sessions);
        setActiveThread(st.current);
        clearView();
        if (st.current) loadHistory(agentId, st.current);
      } catch (e) {
        message.error(`加载会话失败：${(e as Error).message}`);
      }
    })();
    return () => { alive = false; };
  }, [agentId, loadHistory]);

  /**
   * 是否贴近底部（滚动跟随开关）。
   * 原实现每个 token 都 scrollTo({behavior:'smooth'})：流式期间用户一往上翻就被拉回底部，
   * 历史根本看不了。改成只在自己贴底时才跟随，且流式增量用 'auto'（smooth 的动画会
   * 持续打断用户滚动）。
   */
  const onBodyScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !stickToBottomRef.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: sending ? 'auto' : 'smooth' });
  }, [messages, streamSegments, sending]);

  const refreshState = async () => {
    if (!agentId) return;
    const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
    setSessions(st.sessions);
  };

  const newSession = async () => {
    if (!agentId || sending) return;
    try {
      await post('/chat/new', { agent_id: agentId });
      const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
      setSessions(st.sessions);
      setActiveThread(st.current);
      clearView();
    } catch (e) {
      message.error(`新建会话失败：${(e as Error).message}`);
    }
  };

  const switchSession = async (tid: string) => {
    if (tid === activeThread || sending) return;
    try {
      await post('/chat/switch', { agent_id: agentId, thread_id: tid });
      setActiveThread(tid);
      clearView();
      loadHistory(agentId!, tid);
    } catch (e) {
      message.error(`切换会话失败：${(e as Error).message}`);
    }
  };

  const deleteSession = async (tid: string) => {
    if (!agentId || sending) return;
    try {
      await del(`/chat/threads/${encodeURIComponent(tid)}?agent_id=${agentId}`);
      const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
      setSessions(st.sessions);
      setActiveThread(st.current);
      clearView();
      if (st.current) loadHistory(agentId, st.current);
      message.success('会话已删除');
    } catch (e) {
      message.error(`删除会话失败：${(e as Error).message}`);
    }
  };

  const toggleSkill = (name: string) => {
    setSelectedSkills(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  /** 技能包整体勾选：选中 = 其内已启用技能全部进白名单；再点 = 全部移出。 */
  const toggleSkillPackage = (pkg: SkillPackage) => {
    const slugs = (pkg.skills || []).filter(s => s.enabled).map(s => s.slug);
    if (!slugs.length) return;
    setSelectedSkills(prev => {
      const anyOn = slugs.some(x => prev.includes(x));
      return anyOn ? prev.filter(x => !slugs.includes(x)) : [...prev, ...slugs.filter(x => !prev.includes(x))];
    });
  };

  const toggleConnector = (name: string) => {
    setSelectedConnectors(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  const toggleKnowledgeBase = (id: string) => {
    setSelectedKnowledgeBaseIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  /** 停止生成：中断流式请求（后端同时收到断连，停止这一轮）。 */
  const stop = () => {
    abortRef.current?.abort();
  };

  // 卸载（切页/切专家）时中止在途请求 —— 否则切到「设置」页 LLM 继续跑完，token 照扣。
  // 用标记区分「用户点停止」与「组件卸载」，后者不弹 toast。
  useEffect(() => () => {
    unmountedRef.current = true;
    abortRef.current?.abort();
  }, []);

  /** 发送一轮对话；override 用于「重试」（不读输入框）。 */
  const send = async (override?: string, overrideThread?: string) => {
    const text = (override ?? input).trim();
    if (!text || sending || !agentId) return;
    // 重试要发回**原来那轮**的会话（用户可能已经切走了）
    const tid = overrideThread ?? activeThread;
    if (!tid) return;
    setInterrupted(null);
    // 用户自己发消息 = 明确的「看最新一条」意图，重新开启跟随（否则在上滑状态下发消息会看不见回显）
    stickToBottomRef.current = true;
    const userMsg: ChatMessage = { role: 'user', segments: [{ type: 'text', content: text, id: nextSegmentId() }] };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput('');
    setSending(true);
    setStreamSegments([]);
    // 取消支持：用户点「停止生成」或组件卸载时 abort（后端断连即停止，不再跑完白烧 token）
    const controller = new AbortController();
    abortRef.current = controller;
    let gotDone = false;
    let gotError = false;
    let streamError = '';
    let stopped = false;
    // 流式片段按真实到达顺序累积：相邻同类合并（思考累积思考、正文累积正文）。
    // 合并规则抽到 utils/streamSegments（纯函数，有单测）——原地改已进 state 的对象是这里踩过的坑。
    let segs: Segment[] = [];
    const pushSeg = (s: Segment) => {
      segs = appendStreamSegment(segs, s);
      setStreamSegments(segs);
    };
    // per-turn 能力注入（对齐 Octop 对话框语义）：
    // - skills/connectors：未选 = [] = 不加载任何技能/连接器（无「默认全部」）
    // - model：默认「自动」（不传 = 后端 agent 默认模型），用户显式选择才覆盖
    // - knowledge_base_ids：未选 = [] = 不注入（与技能/连接器同维度，无默认打开一说）
    const opts = {
      skills: selectedSkills,
      connectors: selectedConnectors,
      model: selectedModel === MODEL_AUTO ? null : selectedModel,
      knowledge_base_ids: selectedKnowledgeBaseIds,
    };

    try {
      await chatStream(agentId, text, tid, (e: ChatEvent) => {
        if (e.type === 'token' && e.content) {
          pushSeg({ id: nextSegmentId(), type: 'text', content: e.content });
        } else if (e.type === 'reasoning' && e.content) {
          pushSeg({ id: nextSegmentId(), type: 'reasoning', content: e.content });
        } else if (e.type === 'tool_call') {
          pushSeg({ id: nextSegmentId(), type: 'tool_call', name: e.name, args: e.content, plugin_id: e.plugin_id });
        } else if (e.type === 'tool_result') {
          pushSeg({ id: nextSegmentId(), type: 'tool_result', name: e.name, content: e.detail, plugin_id: e.plugin_id });
        } else if (e.type === 'done') {
          gotDone = true;
          // 去掉末尾空白段；至少保留一个 text 段（哪怕空，显示占位）
          if (!segs.some(s => s.type === 'text')) pushSeg({ id: nextSegmentId(), type: 'text', content: '' });
          const finalMsg: ChatMessage = { role: 'assistant', segments: segs };
          setMessages([...next, finalMsg]);
          setStreamSegments([]);
          // 标题/时间更新（后端 touch，仅「新会话」会替换标题）
          post('/chat/touch', { agent_id: agentId, thread_id: tid, title: text.slice(0, 20) }).catch(() => {});
          refreshState().catch(() => {});
        } else if (e.type === 'error') {
          // 后端补发的终止帧 = 终态。置 gotError 以免 finally 再报一次
          // 「未收到完成帧」（那句还与本事实相反：帧其实收到了）。
          gotError = true;
          streamError = e.content || '未知错误';
        }
      }, opts, controller.signal);
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        stopped = true;
      } else {
        message.error(`对话失败：${(err as Error).message}`);
      }
    } finally {
      // 没有 done 也没有 error：连接被中断。已生成的片段必须落成消息，
      // 否则半截回复停在流式气泡里、刷新即消失（原实现只清 streamSegments）。
      if (!gotDone && !gotError) {
        if (segs.length) {
          if (!segs.some(s => s.type === 'text')) pushSeg({ id: nextSegmentId(), type: 'text', content: '' });
          setMessages([...next, { role: 'assistant', segments: segs }]);
        }
        setStreamSegments([]);
        if (unmountedRef.current) {
          // 卸载触发的 abort（切页/切专家）：不要给已经不在的页面弹提示
        } else if (stopped) {
          message.info('已停止生成');
        } else {
          setInterrupted({ text, threadId: tid });
        }
      } else if (gotError) {
        setStreamSegments([]);
        if (!unmountedRef.current) {
          message.error(`生成失败：${streamError}`);
          setInterrupted({ text, threadId: tid });
        }
      }
      abortRef.current = null;
      if (!unmountedRef.current) setSending(false);
    }
  };

  const activeTitle = useMemo(
    () => sessions.find(s => s.thread_id === activeThread)?.title || '新会话',
    [sessions, activeThread],
  );

  const hasAbility = selectedSkills.length > 0 || selectedConnectors.length > 0;

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 108px)' }}>
      {/* 左侧：专家 + 会话列表 */}
      <div style={{ width: 200, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Select
          value={agentId ?? undefined}
          style={{ width: '100%' }}
          placeholder="选择专家"
          options={agents.map(a => ({ value: a.agent_id, label: a.name }))}
          onChange={setAgentId}
          disabled={sending}
        />
        <Button icon={<PlusOutlined />} onClick={newSession} disabled={!agentId || sending} block>
          新建会话
        </Button>
        <div style={{ overflow: 'auto', flex: 1 }}>
          {sessions.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" />}
          {sessions.map(s => (
            <div
              key={s.thread_id}
              onClick={() => switchSession(s.thread_id)}
              style={{
                padding: '8px 10px', marginBottom: 6, borderRadius: 8, cursor: 'pointer',
                background: s.thread_id === activeThread ? '#fff7e6' : '#fafafa',
                border: s.thread_id === activeThread ? '1px solid #f59e0b' : '1px solid #f0f0f0',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                <div style={{ fontSize: 13, fontWeight: s.thread_id === activeThread ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.title || '（空会话）'}
                </div>
                <Popconfirm
                  title="删除这个会话？"
                  description="会话记录和对话上下文将一并清除"
                  okText="删除" cancelText="取消"
                  onConfirm={e => { e?.stopPropagation(); deleteSession(s.thread_id); }}
                  onCancel={e => e?.stopPropagation()}
                >
                  <DeleteOutlined
                    onClick={e => e.stopPropagation()}
                    style={{ color: '#dc2626', fontSize: 13, flexShrink: 0 }}
                  />
                </Popconfirm>
              </div>
              <small style={{ color: 'var(--label-3)' }}>
                {s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '延续记忆'}
              </small>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧：消息区 + 输入 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ paddingBottom: 10, borderBottom: '1px solid var(--line-1)', marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Typography.Text strong style={{ fontSize: 15 }}>{activeTitle || '新会话'}</Typography.Text>
            {activeThread && (
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 10 }} code>
                {activeThread}
              </Typography.Text>
            )}
          </div>
          <Button size="small" icon={<HistoryOutlined />} onClick={() => setTrajectoryOpen(true)} disabled={sending}>
            轨迹
          </Button>
        </div>

        <div ref={bodyRef} onScroll={onBodyScroll} style={{ flex: 1, overflow: 'auto', paddingBottom: 12 }}>
          {messages.length === 0 && streamSegments.length === 0 && (
            <Empty style={{ marginTop: 80 }} description="和专家开始对话吧（记忆按会话隔离）" />
          )}
          {messages.map((m, i) => (
            <div key={i} style={{ display: 'flex', marginBottom: 12, justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
              <div style={{ maxWidth: '78%', display: 'flex', gap: 8, flexDirection: m.role === 'user' ? 'row-reverse' : 'row' }}>
                <div style={{
                  width: 30, height: 30, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', background: m.role === 'user' ? '#f59e0b' : '#e8e8e8', color: 'var(--surface)',
                }}>
                  {m.role === 'user' ? <UserOutlined /> : <RobotOutlined style={{ color: '#666' }} />}
                </div>
                <div style={{ minWidth: 0 }}>
                  {m.role === 'assistant'
                    ? m.segments.map((s, j) =>
                        s.type === 'text' ? (
                          <div key={s.id ?? `m${i}-${j}`} style={{
                            marginBottom: 6, padding: '8px 12px', borderRadius: 10,
                            background: '#f5f5f5', color: '#333',
                          }}>
                            <MarkdownText raw={s.content} placeholder="（空回复）" />
                          </div>
                        ) : (
                          <SegmentView key={s.id ?? `m${i}-${j}`} seg={s} />
                        ),
                      )
                    : m.segments.map((s, j) => (
                        <div key={s.id ?? `m${i}-${j}`} style={{
                          padding: '8px 12px', borderRadius: 10, fontSize: 14, lineHeight: 1.6,
                          background: 'var(--accent)', color: 'var(--surface)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                        }}>
                          {s.content}
                        </div>
                      ))}
                </div>
              </div>
            </div>
          ))}
          {(streamSegments.length > 0 || sending) && (
            <div style={{ display: 'flex', marginBottom: 12, gap: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#e8e8e8' }}>
                <RobotOutlined style={{ color: '#666' }} />
              </div>
              <div style={{ minWidth: 0 }}>
                {streamSegments.map((s, j) =>
                  s.type === 'text' ? (
                    <div key={s.id ?? `stream-${j}`} style={{
                      marginBottom: 6, padding: '8px 12px', borderRadius: 10, background: '#f5f5f5', color: '#333',
                    }}>
                      <MarkdownText raw={s.content} />
                      <span style={{ opacity: 0.5 }}>▍</span>
                    </div>
                  ) : (
                    <SegmentView key={s.id ?? `stream-${j}`} seg={s} />
                  ),
                )}
                {sending && streamSegments.every(s => s.type === 'tool_result' || s.type === 'tool_call') && (
                  <div style={{ fontSize: 12, color: 'var(--label-3)' }}>思考中…</div>
                )}
              </div>
            </div>
          )}
        </div>

        <div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {selectedSkills.map(s => (
              <AbilityChip key={s} label={`技能 · ${s}`} color="#1677ff" onRemove={() => toggleSkill(s)} />
            ))}
            {selectedConnectors.map(c => (
              <AbilityChip key={c} label={`连接器 · ${c}`} color="#52c41a" onRemove={() => toggleConnector(c)} />
            ))}
            {selectedKnowledgeBaseIds.map(id => (
              <AbilityChip key={id} label={`知识库 · ${knowledgeBases.find(b => b.id === id)?.name ?? id}`} color="#eb2f96" onRemove={() => toggleKnowledgeBase(id)} />
            ))}
            {selectedModel && selectedModel !== MODEL_AUTO && (
              <AbilityChip key={selectedModel} label={`模型 · ${selectedModel}`} color="#722ed1" onRemove={() => setSelectedModel(MODEL_AUTO)} />
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Space size={4}>
              <SkillPicker skills={skills} builtin={builtinSkills} packages={skillPackages} selected={selectedSkills} onToggleSkill={toggleSkill} onTogglePackage={toggleSkillPackage} />
              <ConnectorPicker connectors={connectors} selected={selectedConnectors} onToggle={toggleConnector} />
              <KnowledgePicker bases={knowledgeBases} selected={selectedKnowledgeBaseIds} onToggle={toggleKnowledgeBase} disabled={!kbEnabled} />
              <Select
                size="small"
                placeholder="选择模型（默认自动）"
                style={{ width: 170 }}
                value={selectedModel ?? undefined}
                onChange={setSelectedModel}
                options={modelOptions}
                disabled={modelOptions.length === 0}
                popupMatchSelectWidth={false}
              />
            </Space>
          </div>
          {interrupted && !sending && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
              padding: '6px 10px', background: 'var(--warn-bg)', border: '1px solid var(--warn-line)',
              borderRadius: 6, fontSize: 12, color: 'var(--accent-text)',
            }}>
              <span>上一轮回复被中断（未收到完成帧）。</span>
              <a onClick={() => send(interrupted.text, interrupted.threadId)} style={{ color: 'var(--link)' }}>重试</a>
              <a onClick={() => setInterrupted(null)} style={{ color: 'var(--label-4)' }}>忽略</a>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <Input.TextArea
              value={input}
              onChange={e => setInput(e.target.value)}
              onPressEnter={e => {
                // 中文输入法候选词确认也会发 Enter：合成态必须放行，否则半句话被发出去
                if ((e.nativeEvent as KeyboardEvent).isComposing) return;
                if (!e.shiftKey) { e.preventDefault(); send(); }
              }}
              placeholder="输入消息，Enter 发送"
              autoSize={{ minRows: 1, maxRows: 6 }}
              disabled={sending || !agentId}
              style={{ flex: 1 }}
            />
            {sending ? (
              <Button danger icon={<StopOutlined />} onClick={stop}>停止</Button>
            ) : (
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={() => send()}
                disabled={!agentId || !input.trim()}
              >发送</Button>
            )}
          </div>
        </div>
      </div>

      <TrajectoryDrawer open={trajectoryOpen} onClose={() => setTrajectoryOpen(false)} messages={messages} />
    </div>
  );
}
