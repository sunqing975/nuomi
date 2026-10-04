import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Drawer, Empty, Input, Popconfirm, Popover, Select, Space, Switch, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, CloseOutlined, DeleteOutlined, HistoryOutlined, PlusOutlined, SendOutlined, RobotOutlined, ThunderboltOutlined, UserOutlined,
} from '@ant-design/icons';
import {
  del, get, post, chatStream, type Agent, type ChatEvent, type ChatMessage, type ConnectorServer, type Skill, type ToolEvent,
} from '../api';

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

/** 工具步骤折叠（消息气泡内：tool_call → tool_result 时间线） */
function ToolSteps({ events }: { events: ToolEvent[] }) {
  const [open, setOpen] = useState(false);
  if (!events || events.length === 0) return null;
  return (
    <div style={{ marginBottom: 6, fontSize: 12 }}>
      <a onClick={() => setOpen(v => !v)} style={{ color: '#6b7280' }}>
        {open ? '▾' : '▸'} ⚙ 工具调用 {events.length} 次
      </a>
      {open && (
        <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 520 }}>
          {events.map((t, i) => (
            <div key={i} style={{ background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 6, padding: '4px 8px' }}>
              <span style={{ color: t.kind === 'tool_call' ? '#1677ff' : '#52c41a', fontWeight: 500 }}>
                {t.kind === 'tool_call' ? '⚙' : '✓'} {t.name || '(工具)'}
              </span>
              {t.detail ? (
                <div style={{ color: '#6b7280', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto' }}>
                  {t.detail}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 技能选择器（Popover 列表，点击切换选中） */
function SkillPicker({ skills, selected, onToggle }: { skills: Skill[]; selected: string[]; onToggle: (name: string) => void }) {
  const content = (
    <div style={{ width: 280, maxHeight: 320, overflow: 'auto' }}>
      {skills.length === 0 ? (
        <div style={{ color: '#9ca3af', textAlign: 'center', padding: 16 }}>暂无已启用技能，先到「技能」页启用</div>
      ) : (
        skills.map(s => {
          const active = selected.includes(s.name);
          return (
            <div
              key={s.name}
              onClick={() => onToggle(s.name)}
              style={{
                display: 'flex', gap: 8, alignItems: 'flex-start', padding: '8px 10px', borderRadius: 8,
                cursor: 'pointer', background: active ? '#e6f4ff' : 'transparent', marginBottom: 2,
              }}
            >
              <span style={{ color: '#1677ff', fontSize: 13, marginTop: 1 }}>{active ? '☑' : '☐'}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{s.name}</div>
                {s.description ? (
                  <div style={{ fontSize: 12, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.description}</div>
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

/** 轨迹抽屉：当前会话全部工具事件时间线 */
function TrajectoryDrawer({ open, onClose, messages }: { open: boolean; onClose: () => void; messages: ChatMessage[] }) {
  const rows = useMemo(() => {
    const out: { seq: number; kind: 'tool_call' | 'tool_result'; name?: string; detail?: string }[] = [];
    messages.forEach(m => {
      (m.tool_events || []).forEach(t => out.push({ seq: out.length + 1, kind: t.kind, name: t.name, detail: t.detail }));
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
  const [streamText, setStreamText] = useState('');
  const [streamTools, setStreamTools] = useState<ToolEvent[]>([]);
  // 能力选择（per-turn 注入：技能白名单 / 连接器挂载 / 模型）
  const [skills, setSkills] = useState<Skill[]>([]);
  const [connectors, setConnectors] = useState<ConnectorServer[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedConnectors, setSelectedConnectors] = useState<string[]>([]);
  const [modelOptions, setModelOptions] = useState<{ value: string; label: string }[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [trajectoryOpen, setTrajectoryOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const loadAgents = useCallback(async () => {
    const rows = await get<Agent[]>('/agents');
    setAgents(rows);
    if (rows.length && !agentId) setAgentId(rows[0].agent_id);
  }, [agentId]);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // 能力清单（已启用技能 + 连接器 + 模型），对话框里按 per-turn 选择
  useEffect(() => {
    Promise.all([
      get<Skill[]>('/skills'),
      get<ConnectorServer[]>('/connectors'),
      get<{ providers: { id: string; name: string; models: { id: string }[] }[] }>('/settings/providers'),
    ])
      .then(([sk, conn, provs]) => {
        setSkills(sk.filter(s => s.enabled));
        setConnectors(conn);
        setModelOptions(
          provs.providers.flatMap(p =>
            (p.models || []).map(m => ({ value: `${p.id}/${m.id}`, label: `${p.name} · ${m.id}` })),
          ),
        );
      })
      .catch(() => { /* 能力加载失败不阻塞对话 */ });
  }, []);

  // 历史加载（octop checkpointer，按线程）
  const loadHistory = useCallback(async (agent: string, tid: string) => {
    const rows = await get<{ role: string; content: string }[]>(
      `/agents/${agent}/chat/history?thread_id=${encodeURIComponent(tid)}`,
    );
    setMessages(rows.map(r => ({ role: r.role as ChatMessage['role'], content: r.content })));
  }, []);

  // 专家变化 → 读后端会话状态 + 清空能力选择（各专家能力不同）
  useEffect(() => {
    if (!agentId) return;
    let alive = true;
    setSelectedSkills([]);
    setSelectedConnectors([]);
    (async () => {
      try {
        const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
        if (!alive) return;
        setSessions(st.sessions);
        setActiveThread(st.current);
        setMessages([]);
        setStreamText('');
        setStreamTools([]);
        if (st.current) loadHistory(agentId, st.current);
      } catch (e) {
        message.error(`加载会话失败：${(e as Error).message}`);
      }
    })();
    return () => { alive = false; };
  }, [agentId, loadHistory]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, streamText]);

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
      setStreamText('');
      setStreamTools([]);
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
      setStreamText('');
      setStreamTools([]);
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
      setStreamText('');
      setStreamTools([]);
      if (st.current) loadHistory(agentId, st.current);
      message.success('会话已删除');
    } catch (e) {
      message.error(`删除会话失败：${(e as Error).message}`);
    }
  };

  const toggleSkill = (name: string) => {
    setSelectedSkills(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  const toggleConnector = (name: string) => {
    setSelectedConnectors(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || sending || !agentId) return;
    const tid = activeThread;
    if (!tid) return;
    const userMsg: ChatMessage = { role: 'user', content: text };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput('');
    setSending(true);
    setStreamText('');
    setStreamTools([]);
    const toolEvents: ToolEvent[] = [];
    let accumulated = '';
    // per-turn 能力注入：显式选择的技能/连接器/模型才传（不传=全量技能/默认连接器/默认模型）
    const opts = {
      skills: selectedSkills.length ? selectedSkills : undefined,
      connectors: selectedConnectors.length ? selectedConnectors : undefined,
      model: selectedModel ?? undefined,
    };

    try {
      await chatStream(agentId, text, tid, (e: ChatEvent) => {
        if (e.type === 'token' && e.content) {
          accumulated += e.content;
          setStreamText(accumulated);
        } else if (e.type === 'tool_call') {
          toolEvents.push({ kind: 'tool_call', name: e.name, detail: e.content });
          setStreamTools([...toolEvents]);
        } else if (e.type === 'tool_result') {
          toolEvents.push({ kind: 'tool_result', name: e.name, detail: e.detail });
          setStreamTools([...toolEvents]);
        } else if (e.type === 'done') {
          const answer = accumulated.trim();
          const finalMsg: ChatMessage = { role: 'assistant', content: answer, tool_events: toolEvents };
          setMessages([...next, finalMsg]);
          setStreamText('');
          setStreamTools([]);
          // 标题/时间更新（后端 touch，仅「新会话」会替换标题）
          post('/chat/touch', { agent_id: agentId, thread_id: tid, title: text.slice(0, 20) }).catch(() => {});
          refreshState().catch(() => {});
        }
      }, opts);
    } catch (err) {
      message.error(`对话失败：${(err as Error).message}`);
      setStreamText('');
      setStreamTools([]);
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
          {messages.length === 0 && !streamText && (
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
                <div>
                  {m.role === 'assistant' && <ToolSteps events={m.tool_events || []} />}
                  <div style={{
                    padding: '8px 12px', borderRadius: 10, fontSize: 14, lineHeight: 1.6,
                    background: m.role === 'user' ? '#f59e0b' : '#f5f5f5', color: m.role === 'user' ? '#fff' : '#333',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  }}>
                    {m.content || '（空回复）'}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {(streamTools.length > 0 || streamText || sending) && (
            <div style={{ display: 'flex', marginBottom: 12, gap: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#e8e8e8' }}>
                <RobotOutlined style={{ color: '#666' }} />
              </div>
              <div style={{ minWidth: 0 }}>
                {streamTools.length > 0 && <ToolSteps events={streamTools} />}
                {(streamText || sending) && (
                  <div style={{ padding: '8px 12px', borderRadius: 10, background: '#f5f5f5', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                    {streamText}
                    <span style={{ opacity: 0.5 }}>▍</span>
                  </div>
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
            {selectedModel && <AbilityChip key={selectedModel} label={`模型 · ${selectedModel}`} color="#722ed1" onRemove={() => setSelectedModel(null)} />}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Space size={4}>
              <SkillPicker skills={skills} selected={selectedSkills} onToggle={toggleSkill} />
              <ConnectorPicker connectors={connectors} selected={selectedConnectors} onToggle={toggleConnector} />
              <Select
                size="small"
                allowClear
                placeholder="模型"
                style={{ width: 150 }}
                value={selectedModel ?? undefined}
                onChange={setSelectedModel}
                options={modelOptions}
                disabled={modelOptions.length === 0}
                popupMatchSelectWidth={false}
              />
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12, flex: 1, textAlign: 'right' }}>
              不选 = 全部技能 / 默认连接器 / 默认模型
            </Typography.Text>
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
