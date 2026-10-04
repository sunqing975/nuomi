import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Empty, Input, Popconfirm, Select, Space, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  DeleteOutlined, MessageOutlined, PlusOutlined, SendOutlined, RobotOutlined, UserOutlined,
} from '@ant-design/icons';
import {
  del, get, post, chatStream, type Agent, type ChatEvent, type ChatMessage,
} from '../api';

interface SessionMeta {
  thread_id: string;
  title: string;
  updated_at: number;
}

interface ChatState {
  agent_id: string;
  current: string;
  sessions: SessionMeta[];
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
  const [streamTools, setStreamTools] = useState<ChatMessage['tool_events']>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

  const loadAgents = useCallback(async () => {
    const rows = await get<Agent[]>('/agents');
    setAgents(rows);
    if (rows.length && !agentId) setAgentId(rows[0].agent_id);
  }, [agentId]);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // 历史加载（octop checkpointer，按线程）
  const loadHistory = useCallback(async (agent: string, tid: string) => {
    const rows = await get<{ role: string; content: string }[]>(
      `/agents/${agent}/chat/history?thread_id=${encodeURIComponent(tid)}`,
    );
    setMessages(rows.map(r => ({ role: r.role as ChatMessage['role'], content: r.content })));
  }, []);

  // 专家变化 → 读后端会话状态（当前会话 = 壳 config 的 thread_id，桌宠对话可见）
  useEffect(() => {
    if (!agentId) return;
    let alive = true;
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
    const toolEvents: NonNullable<ChatMessage['tool_events']> = [];
    let accumulated = '';

    try {
      await chatStream(agentId, text, tid, (e: ChatEvent) => {
        if (e.type === 'token' && e.content) {
          accumulated += e.content;
          setStreamText(accumulated);
        } else if (e.type === 'tool_call') {
          const ev = { kind: 'tool_call' as const, name: e.name, detail: e.content };
          toolEvents.push(ev);
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
      });
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

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 108px)' }}>
      {/* 左侧：专家 + 会话列表 */}
      <div style={{ width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
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
        <div style={{ paddingBottom: 10, borderBottom: '1px solid #f0f0f0', marginBottom: 10 }}>
          <Typography.Text strong style={{ fontSize: 15 }}>{activeTitle || '新会话'}</Typography.Text>
          {activeThread && (
            <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 10 }} code>
              {activeThread}
            </Typography.Text>
          )}
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
                  {m.tool_events && m.tool_events.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      {m.tool_events.map((t, j) => (
                        <Tag key={j} color={t.kind === 'tool_call' ? 'blue' : 'green'} style={{ marginBottom: 2 }}>
                          {t.kind === 'tool_call' ? '⚙ 调用' : '✓ 结果'} {t.name || ''}
                          {t.detail ? `：${t.detail}` : ''}
                        </Tag>
                      ))}
                    </div>
                  )}
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
          {streamTools && streamTools.length > 0 && !streamText && (
            <div style={{ marginBottom: 8 }}>
              {streamTools.map((t, j) => (
                <Tag key={j} color={t.kind === 'tool_call' ? 'blue' : 'green'}>{t.kind === 'tool_call' ? '⚙ 调用' : '✓ 结果'} {t.name || ''}</Tag>
              ))}
            </div>
          )}
          {(streamText || sending) && (
            <div style={{ display: 'flex', marginBottom: 12, gap: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#e8e8e8' }}>
                <RobotOutlined style={{ color: '#666' }} />
              </div>
              <div style={{ padding: '8px 12px', borderRadius: 10, background: '#f5f5f5', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {streamText}
                <span style={{ opacity: 0.5 }}>▍</span>
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <Input.TextArea
            value={input}
            onChange={e => setInput(e.target.value)}
            onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={sending || !agentId}
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
  );
}
