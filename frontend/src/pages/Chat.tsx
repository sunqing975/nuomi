/**
 * ChatPage：对话页编排（专家/会话列表 + 消息区 + 输入区 + 轨迹抽屉）。
 *
 * P0-4（2026-10-06）拆分：流式状态机 → useChatStream；消息区 → MessageList/
 * MessageBubble；输入区 → Composer。本文件只保留：
 *  - 专家与会话的加载/切换/新建/删除
 *  - 能力清单（技能/连接器/模型/知识库）加载与 per-turn 选择状态
 *  - 历史加载（分段 → 消息块归组）与滚动跟随
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Drawer, Empty, Popconfirm, Select, Tag, message,
} from 'antd';
import {
  DeleteOutlined, HistoryOutlined, PlusOutlined, BulbOutlined,
} from '@ant-design/icons';
import {
  del, get, knowledgeApi, post,
  type Agent, type ChatMessage, type ConnectorServer, type KnowledgeBase, type Segment, type Skill, type SkillPackage,
} from '../api';
import EmptyState from '../components/EmptyState';
import SectionToolbar from '../components/SectionToolbar';
import Composer from './chat/Composer';
import MessageList from './chat/MessageList';
import { loadPluginUiRegistry } from './chat/MessageBubble';
import { MODEL_AUTO, useChatStream } from './chat/useChatStream';
import MemoryView from './memory/MemoryView';

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

/** 会话列表项：选中态主色描边/淡底，hover 浅灰 + 删除图标变红（IM 列表交互） */
function SessionItem({ session, active, onOpen, onDelete }: {
  session: SessionMeta; active: boolean; onOpen: () => void; onDelete: () => void;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '8px 10px', marginBottom: 6, borderRadius: 8, cursor: 'pointer',
        background: active ? '#fff7e6' : hover ? '#fafafa' : 'var(--surface)',
        border: active ? '1px solid #f59e0b' : '1px solid var(--line-1)',
        transition: 'background 0.15s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
        <div style={{
          fontSize: 13, fontWeight: active ? 600 : 400,
          color: active ? 'var(--accent-text)' : 'var(--label-1)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {session.title || '（空会话）'}
        </div>
        <Popconfirm
          title="删除这个会话？"
          description="会话记录和对话上下文将一并清除"
          okText="删除" cancelText="取消"
          onConfirm={e => { e?.stopPropagation(); onDelete(); }}
          onCancel={e => e?.stopPropagation()}
        >
          <DeleteOutlined
            onClick={e => e.stopPropagation()}
            style={{ color: hover ? '#dc2626' : 'var(--label-4)', fontSize: 13, flexShrink: 0, transition: 'color 0.15s' }}
          />
        </Popconfirm>
      </div>
      <small style={{ color: 'var(--label-3)' }}>
        {session.updated_at ? new Date(session.updated_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '延续记忆'}
      </small>
    </div>
  );
}

export default function ChatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [activeThread, setActiveThread] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
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
  const [memoryOpen, setMemoryOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  /**
   * 是否贴近底部（滚动跟随开关，滚动事件里更新）。
   * 原实现每个 token 都 scrollTo({behavior:'smooth'})：流式期间用户一往上翻就被拉回底部，
   * 历史根本看不了。改成只在自己贴底时才跟随，且流式增量用 'auto'（smooth 的动画会
   * 持续打断用户滚动）。
   */
  const stickToBottomRef = useRef(true);

  const refreshState = async () => {
    if (!agentId) return;
    const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
    setSessions(st.sessions);
  };

  const stream = useChatStream({
    agentId,
    activeThread,
    messages,
    setMessages,
    selectedSkills,
    selectedConnectors,
    selectedModel,
    selectedKnowledgeBaseIds,
    onSessionChanged: refreshState,
  });
  const { sending, streamSegments, interrupted } = stream;

  /**
   * 清空当前会话视图（切会话/切专家/删会话）。
   * 一并把滚动跟随复位成「跟随」：否则上个会话的上滑状态会让新会话停在中间不动，
   * 而换会话时用户期望看到最新一条。
   */
  const clearView = () => {
    stickToBottomRef.current = true;
    setMessages([]);
    stream.clearStream();
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

  const activeTitle = useMemo(
    () => sessions.find(s => s.thread_id === activeThread)?.title || '新会话',
    [sessions, activeThread],
  );

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
        <div style={{ fontSize: 12, color: 'var(--label-3)', fontWeight: 600 }}>会话记录</div>
        <div style={{ overflow: 'auto', flex: 1 }}>
          {sessions.length === 0 && (
            <EmptyState simple description="暂无会话" style={{ marginTop: 24 }} />
          )}
          {sessions.map(s => (
            <SessionItem
              key={s.thread_id}
              session={s}
              active={s.thread_id === activeThread}
              onOpen={() => switchSession(s.thread_id)}
              onDelete={() => deleteSession(s.thread_id)}
            />
          ))}
        </div>
      </div>

      {/* 右侧：消息区 + 输入 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <SectionToolbar
          title={activeTitle || '新会话'}
          subtitle={messages.length > 0 ? `${messages.length} 条消息` : undefined}
          extra={
            <>
              <Button size="small" icon={<HistoryOutlined />} onClick={() => setTrajectoryOpen(true)} disabled={sending}>
                轨迹
              </Button>
              <Button size="small" icon={<BulbOutlined />} onClick={() => setMemoryOpen(true)} disabled={!agentId}>
                记忆
              </Button>
            </>
          }
        />

        <MessageList
          messages={messages}
          streamSegments={streamSegments}
          sending={sending}
          bodyRef={bodyRef}
          onBodyScroll={onBodyScroll}
        />

        <Composer
          input={input}
          setInput={setInput}
          sending={sending}
          agentId={agentId}
          skills={skills}
          builtinSkills={builtinSkills}
          skillPackages={skillPackages}
          connectors={connectors}
          knowledgeBases={knowledgeBases}
          kbEnabled={kbEnabled}
          selectedSkills={selectedSkills}
          selectedConnectors={selectedConnectors}
          selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
          selectedModel={selectedModel}
          modelOptions={modelOptions}
          interrupted={interrupted}
          onSend={text => stream.send(text)}
          onStop={stream.stop}
          onToggleSkill={toggleSkill}
          onToggleSkillPackage={toggleSkillPackage}
          onToggleConnector={toggleConnector}
          onToggleKnowledgeBase={toggleKnowledgeBase}
          onChangeModel={setSelectedModel}
          onResetModel={() => setSelectedModel(MODEL_AUTO)}
          onRetry={turn => stream.send(turn.text, turn.threadId)}
          onDismissInterrupted={() => stream.setInterrupted(null)}
        />
      </div>

      <TrajectoryDrawer open={trajectoryOpen} onClose={() => setTrajectoryOpen(false)} messages={messages} />

      {/* 记忆：对话伴生视图（P0-6）——「我记住了你什么」随当前专家走 */}
      <Drawer
        title="我记住了你什么"
        open={memoryOpen}
        onClose={() => setMemoryOpen(false)}
        width={640}
        destroyOnHidden
      >
        {agentId ? <MemoryView agentId={agentId} /> : <Empty description="先选择专家" />}
      </Drawer>
    </div>
  );
}
