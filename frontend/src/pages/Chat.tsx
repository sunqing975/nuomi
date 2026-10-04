import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Drawer, Empty, Input, Popconfirm, Popover, Select, Space, Switch, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, BookOutlined, CloseOutlined, DeleteOutlined, HistoryOutlined, PlusOutlined, SendOutlined, RobotOutlined, ThunderboltOutlined, UserOutlined,
} from '@ant-design/icons';
import {
  del, get, post, chatStream, knowledgeApi,
  type Agent, type ChatEvent, type ChatMessage, type ConnectorServer, type KnowledgeBase, type Segment, type Skill, type SkillPackage,
} from '../api';
import { parseKnowledgeCitations } from '../utils/parseKnowledgeCitations';

/** 模型「自动」哨兵值：发送时不传 model（null），由后端按 agent 默认模型解析（对齐 Octop AUTO 语义） */
const MODEL_AUTO = 'auto';

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

/** 知识库引用条（search_knowledge 工具输出含 citations 标记时展示来源） */
function KnowledgeCitations({ raw }: { raw?: string }) {
  const { text, citations } = parseKnowledgeCitations(raw);
  if (!citations.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 4 }}>📚 知识库引用</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {citations.map(c => (
          <Tag key={c.docId} style={{ fontSize: 12, margin: 0 }}>
            {c.kbName || '知识库'} · {c.filename}
          </Tag>
        ))}
      </div>
      {text ? (
        <div style={{ color: '#6b7280', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto' }}>
          {text}
        </div>
      ) : null}
    </div>
  );
}

/** 单片段渲染：思考折叠块 / 工具调用卡片 / 工具结果卡片（按对话真实顺序穿插） */
function SegmentView({ seg }: { seg: Segment }) {
  const [open, setOpen] = useState(false);
  if (seg.type === 'reasoning') {
    return (
      <div style={{ marginBottom: 6, fontSize: 12, color: '#8c8c8c' }}>
        <a onClick={() => setOpen(v => !v)} style={{ color: '#8c8c8c' }}>
          {open ? '▾' : '▸'} 💭 深度思考
        </a>
        {open && (
          <div style={{
            marginTop: 4, padding: '6px 8px', background: '#fafafa', borderRadius: 6,
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
    return (
      <div style={{
        marginBottom: 6, fontSize: 12, padding: '4px 8px', borderRadius: 6, maxWidth: 520,
        background: isCall ? '#f0f7ff' : '#f6ffed',
        border: `1px solid ${isCall ? '#d6e4ff' : '#d9f7be'}`,
      }}>
        <span style={{ color: isCall ? '#1677ff' : '#52c41a', fontWeight: 500 }}>
          {isCall ? '⚙ 调用' : '✓ 结果'} {seg.name || '(工具)'}
        </span>
        {isCall && seg.args && seg.args !== '{}' && (
          <div style={{ color: '#6b7280', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 80, overflow: 'auto' }}>
            {seg.args}
          </div>
        )}
        {!isCall && seg.content && (
          <div style={{ color: '#6b7280', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto' }}>
            {seg.name === 'search_knowledge' ? <KnowledgeCitations raw={seg.content} /> : seg.content}
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
    <div style={{ fontSize: 11, color: '#8c8c8c', padding: '6px 10px 2px', fontWeight: 600 }}>{children}</div>
  );
  const Row = ({ active, onClick, title, desc }: { active: boolean; onClick: () => void; title: string; desc?: string }) => (
    <div
      onClick={onClick}
      style={{
        display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 10px', borderRadius: 8,
        cursor: 'pointer', background: active ? '#e6f4ff' : 'transparent', marginBottom: 2,
      }}
    >
      <span style={{ color: '#1677ff', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {desc ? (
          <div style={{ fontSize: 12, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{desc}</div>
        ) : null}
      </div>
    </div>
  );
  const empty = skills.length === 0 && builtin.length === 0 && packages.length === 0;
  const content = (
    <div style={{ width: 300, maxHeight: 340, overflow: 'auto' }}>
      {empty ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 16 }}>暂无可用技能，先到「技能」页安装/启用</div>
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
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 16 }}>暂无连接器，先到「连接器」页添加</div>
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
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 16 }}>暂无知识库，先到「知识库」页创建</div>
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
                  <div style={{ fontSize: 12, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.description}</div>
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
            <div key={r.seq} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: '8px 10px', background: r.kind === 'tool_call' ? '#f0f7ff' : '#f6ffed' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Tag color={r.kind === 'tool_call' ? 'blue' : 'green'} style={{ margin: 0 }}>{r.seq}</Tag>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{r.kind === 'tool_call' ? '⚙ 调用' : '✓ 结果'} {r.name || ''}</span>
              </div>
              {r.detail ? (
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 160, overflow: 'auto' }}>{r.detail}</div>
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

  const loadAgents = useCallback(async () => {
    const rows = await get<Agent[]>('/agents');
    setAgents(rows);
    if (rows.length && !agentId) setAgentId(rows[0].agent_id);
  }, [agentId]);

  useEffect(() => { loadAgents(); }, [loadAgents]);

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
    for (const s of rows) {
      if (s.type === 'user') {
        asst = null;
        blocks.push({ role: 'user', segments: [{ type: 'text', content: s.content || '' }] });
      } else {
        if (!asst) {
          asst = { role: 'assistant', segments: [] };
          blocks.push(asst);
        }
        asst.segments.push(s);
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
        setMessages([]);
        setStreamSegments([]);
        if (st.current) loadHistory(agentId, st.current);
      } catch (e) {
        message.error(`加载会话失败：${(e as Error).message}`);
      }
    })();
    return () => { alive = false; };
  }, [agentId, loadHistory]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, streamSegments]);

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
      setMessages([]);
      setStreamSegments([]);
    } catch (e) {
      message.error(`新建会话失败：${(e as Error).message}`);
    }
  };

  const switchSession = async (tid: string) => {
    if (tid === activeThread || sending) return;
    try {
      await post('/chat/switch', { agent_id: agentId, thread_id: tid });
      setActiveThread(tid);
      setMessages([]);
      setStreamSegments([]);
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
      setMessages([]);
      setStreamSegments([]);
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

  const send = async () => {
    const text = input.trim();
    if (!text || sending || !agentId) return;
    const tid = activeThread;
    if (!tid) return;
    const userMsg: ChatMessage = { role: 'user', segments: [{ type: 'text', content: text }] };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput('');
    setSending(true);
    setStreamSegments([]);
    // 流式片段按真实到达顺序累积：相邻同类合并（思考累积思考、正文累积正文）
    const segs: Segment[] = [];
    const pushSeg = (s: Segment) => {
      const last = segs[segs.length - 1];
      if (last && s.type === last.type && (s.type === 'text' || s.type === 'reasoning')) {
        last.content = (last.content || '') + (s.content || '');
      } else {
        segs.push(s);
      }
      setStreamSegments([...segs]);
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
          pushSeg({ type: 'text', content: e.content });
        } else if (e.type === 'reasoning' && e.content) {
          pushSeg({ type: 'reasoning', content: e.content });
        } else if (e.type === 'tool_call') {
          segs.push({ type: 'tool_call', name: e.name, args: e.content });
          setStreamSegments([...segs]);
        } else if (e.type === 'tool_result') {
          segs.push({ type: 'tool_result', name: e.name, content: e.detail });
          setStreamSegments([...segs]);
        } else if (e.type === 'done') {
          // 去掉末尾空白段；至少保留一个 text 段（哪怕空，显示占位）
          if (!segs.some(s => s.type === 'text')) segs.push({ type: 'text', content: '' });
          const finalMsg: ChatMessage = { role: 'assistant', segments: segs };
          setMessages([...next, finalMsg]);
          setStreamSegments([]);
          // 标题/时间更新（后端 touch，仅「新会话」会替换标题）
          post('/chat/touch', { agent_id: agentId, thread_id: tid, title: text.slice(0, 20) }).catch(() => {});
          refreshState().catch(() => {});
        }
      }, opts);
    } catch (err) {
      message.error(`对话失败：${(err as Error).message}`);
      setStreamSegments([]);
    } finally {
      setSending(false);
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
              <small style={{ color: '#9ca3af' }}>
                {s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '延续记忆'}
              </small>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧：消息区 + 输入 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ paddingBottom: 10, borderBottom: '1px solid #f0f0f0', marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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

        <div ref={bodyRef} style={{ flex: 1, overflow: 'auto', paddingBottom: 12 }}>
          {messages.length === 0 && streamSegments.length === 0 && (
            <Empty style={{ marginTop: 80 }} description="和专家开始对话吧（记忆按会话隔离）" />
          )}
          {messages.map((m, i) => (
            <div key={i} style={{ display: 'flex', marginBottom: 12, justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
              <div style={{ maxWidth: '78%', display: 'flex', gap: 8, flexDirection: m.role === 'user' ? 'row-reverse' : 'row' }}>
                <div style={{
                  width: 30, height: 30, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', background: m.role === 'user' ? '#f59e0b' : '#e8e8e8', color: '#fff',
                }}>
                  {m.role === 'user' ? <UserOutlined /> : <RobotOutlined style={{ color: '#666' }} />}
                </div>
                <div style={{ minWidth: 0 }}>
                  {m.role === 'assistant'
                    ? m.segments.map((s, j) =>
                        s.type === 'text' ? (
                          <div key={j} style={{
                            marginBottom: 6, padding: '8px 12px', borderRadius: 10, fontSize: 14, lineHeight: 1.6,
                            background: '#f5f5f5', color: '#333', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                          }}>
                            {s.content || '（空回复）'}
                          </div>
                        ) : (
                          <SegmentView key={j} seg={s} />
                        ),
                      )
                    : m.segments.map((s, j) => (
                        <div key={j} style={{
                          padding: '8px 12px', borderRadius: 10, fontSize: 14, lineHeight: 1.6,
                          background: '#f59e0b', color: '#fff', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
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
                    <div key={j} style={{
                      marginBottom: 6, padding: '8px 12px', borderRadius: 10, background: '#f5f5f5',
                      fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                      {s.content}
                      <span style={{ opacity: 0.5 }}>▍</span>
                    </div>
                  ) : (
                    <SegmentView key={j} seg={s} />
                  ),
                )}
                {sending && streamSegments.every(s => s.type === 'tool_result' || s.type === 'tool_call') && (
                  <div style={{ fontSize: 12, color: '#9ca3af' }}>思考中…</div>
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
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <Input.TextArea
              value={input}
              onChange={e => setInput(e.target.value)}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="输入消息，Enter 发送"
              autoSize={{ minRows: 1, maxRows: 6 }}
              disabled={sending || !agentId}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={send}
              loading={sending}
              disabled={!agentId || !input.trim()}
            >发送</Button>
          </div>
        </div>
      </div>

      <TrajectoryDrawer open={trajectoryOpen} onClose={() => setTrajectoryOpen(false)} messages={messages} />
    </div>
  );
}
