/**
 * ChatPage：对话页编排（专家/会话列表 + 消息区 + 输入区 + 轨迹抽屉）。
 *
 * P0-4（2026-10-06）拆分：流式状态机 → useChatStream；消息区 → MessageList/
 * MessageBubble；输入区 → Composer。本文件只保留：
 *  - 专家与会话的加载/切换/新建
 *  - 能力清单（技能/连接器/模型/知识库）加载与 per-turn 选择状态
 *  - 历史加载（分段 → 消息块归组）与滚动跟随
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button, Drawer, Empty, Input, Select, Tag, message,
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
import ApprovalCard from './chat/ApprovalCard';
import Composer from './chat/Composer';
import MessageList from './chat/MessageList';
import { loadPluginUiRegistry } from './chat/MessageBubble';
import { MODEL_AUTO, getPendingTurn, useChatStream } from './chat/useChatStream';
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
            <div key={r.seq} style={{ border: '1px solid var(--line-1)', borderRadius: 8, padding: '8px 10px', background: r.kind === 'tool_call' ? 'var(--info-soft)' : 'var(--ok-bg)' }}>
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

/** 会话列表项：选中态主色描边/淡底，hover 浅灰；点击即打开，右侧删除图标直接删（不再弹确认框）。
 *
 * 颜色一律走 token（原来 #fff7e6/#f59e0b/#dc2626 是硬编码浅色，深色主题下会刺眼露白）；
 * 可聚焦（原来是个纯 div onClick，键盘进不去、读屏念不出这是会话）；
 * 会话名由首条消息自动生成，不提供改名入口。
 */
function SessionItem({ session, active, onOpen, onDelete }: {
  session: SessionMeta; active: boolean; onOpen: () => void; onDelete: () => void;
}) {
  const [hover, setHover] = useState(false);

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`会话 ${session.title || '未命名'}`}
      aria-current={active ? 'true' : undefined}
      onClick={onOpen}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(); }
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '8px 10px', marginBottom: 6, borderRadius: 8, cursor: 'pointer',
        background: active ? 'var(--accent-soft)' : hover ? 'var(--surface-2)' : 'var(--surface)',
        border: active ? '1px solid var(--primary)' : '1px solid var(--line-1)',
        transition: 'background 0.15s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
        <div
          title={session.title || '（空会话）'}
          style={{
            fontSize: 13, fontWeight: active ? 600 : 400,
            color: active ? 'var(--accent-text)' : 'var(--label-1)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {session.title || '（空会话）'}
        </div>
        <DeleteOutlined
          aria-label="删除会话"
          role="button"
          tabIndex={0}
          onClick={e => { e.stopPropagation(); onDelete(); }}
          onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); onDelete(); } }}
          style={{ color: hover ? 'var(--danger)' : 'var(--label-4)', fontSize: 13, flexShrink: 0, transition: 'color 0.15s' }}
        />
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
  const [sessionQuery, setSessionQuery] = useState('');
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
  /**
   * 会话切换中（新建/切换/删除/换专家）：从发出切换请求到新会话视图落定为止。
   *
   * 竞态就在这里：newSession() 里有两段 await（POST /chat/new → GET /chat/state），
   * 期间 busy 还是 false，用户「发起对话后立即」按发送时 send() 取的是**上一轮的**
   * activeThread —— 这一问一答进了旧会话，而切会话收尾的 clearView()/loadHistory()
   * 又把新会话视图刷成空的，页面看上去就是「点了发送之后收不到任何消息」。
   * 所以切换期间必须挡住发送（发送按钮置灰、Enter 不响应），切换完再放开。
   */
  const [sessionBusy, setSessionBusy] = useState(false);
  /**
   * 切页回来时「上一轮还在后台跑」：先把用户那条补上（乐观消息），跑完自动把历史拉回来。
   * 后台那一轮不随页面卸载而中止（见 useChatStream 的 pendingTurns）。
   */
  const [recovering, setRecovering] = useState<{ text: string } | null>(null);
  /**
   * 视图代次：每次「新会话/切会话/换专家/用户发送」都 +1。
   *
   * 在途的历史加载（loadHistory）和清空（clearView）都是异步收尾的，回来时可能已经
   * 过时——晚到的 setMessages(空/旧历史) 会把刚流式落下的回复抹掉。带上代次，
   * 对不上就丢弃这次结果。
   */
  const viewEpochRef = useRef(0);
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
  const { sending, streamSegments, interrupted, approval, submitApproval, restoreApproval } = stream;
  // 对话忙碌态 = 流式发送中 ∪ 审批待决/提交中（期间禁止发新消息/切会话/删会话）。
  // 待审期间禁止发新消息是刻意的：graph 停在中断上，harness 对「pending interrupt
  // 时又喂新输入」的行为没有保证，先让用户把这一批决策点完再往下走。
  const busy = sending || Boolean(approval);
  // 再并上「会话切换中」：这一档只用于挡住发送与再次切换，Composer 的「停止」按钮
  // 仍只看真实发送态（否则新建会话那 100ms 里按钮会闪成「停止」）。
  const blocked = busy || sessionBusy;
  /** blocked 的同步镜像：会话操作/发送都在异步回调里判断，ref 不受渲染时机影响 */
  const blockedRef = useRef(false);
  blockedRef.current = blocked;
  /**
   * 会话切换的同步忙碌标记 + 排队箱。
   *
   * 新建/切换/删除会话都是「多段 await」，实测这个窗口只有几毫秒——短到 React 来不及
   * 把按钮渲染成 disabled（10ms 轮询都抓不到一次禁用）。所以「忙不忙」不能依赖渲染时机：
   * 一进操作就同步置 ref，handleSend 在同一个 task 里就能看见。
   * 期间用户按下的那一发送排队（不丢弃），等 activeThread 落定后用最新闭包补发。
   */
  const sessionBusyRef = useRef(false);
  const pendingSendRef = useRef<{ text: string; threadId?: string } | null>(null);
  /** 最近一次历史加载的 promise：补发前先等它落地，免得补发出去的那轮被历史覆盖 */
  const historyRef = useRef<Promise<void> | null>(null);
  /** 永远指向最新渲染的 send：补发不能用在会话操作开始时捕获的旧闭包（messages 是旧的） */
  const sendRef = useRef(stream.send);
  sendRef.current = stream.send;
  const beginSessionOp = () => { sessionBusyRef.current = true; setSessionBusy(true); };
  const endSessionOp = () => { sessionBusyRef.current = false; setSessionBusy(false); };

  /**
   * 清空当前会话视图（切会话/切专家/删会话）。
   * 一并把滚动跟随复位成「跟随」：否则上个会话的上滑状态会让新会话停在中间不动，
   * 而换会话时用户期望看到最新一条。
   * 同时推进视图代次：作废所有在途的历史加载。
   */
  const clearView = () => {
    viewEpochRef.current += 1;
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
  // epoch：调用时的视图代次；回来时代次已变（用户又切了会话/发了新消息）就丢弃结果，
  // 否则晚到的空历史会把刚流式落下的回复盖掉。
  const loadHistory = useCallback(async (agent: string, tid: string, epoch = viewEpochRef.current) => {
    const task = (async () => {
      const rows = await get<Segment[]>(
        `/agents/${agent}/chat/history?thread_id=${encodeURIComponent(tid)}`,
      );
      if (epoch !== viewEpochRef.current) return;
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
      // 刷新/切会话后把待审卡片找回来：审批请求此前只活在 SSE 帧里，页面一刷新
      // 卡片就没了，而被拦下的写入还挂在中断上 —— 用户既看不到「有待批」也没法批。
      restoreApproval(tid);
    })();
    // 记下在途的历史加载：补发排队消息前要等它落地（否则回复会被随后到达的历史盖掉）
    const tracked = task.catch(() => { /* 历史加载失败不阻塞对话 */ });
    historyRef.current = tracked;
    await tracked;
  }, [restoreApproval]);

  /**
   * 切页回来：上一轮若还在后台跑，先把用户那条补上并显示「等待模型返回」，等它跑完
   * （pendingTurns 里清掉）再把历史拉一次 —— 回复就自动出现了，不需要手动刷新。
   */
  useEffect(() => {
    if (!agentId || !activeThread) {
      setRecovering(null);
      return;
    }
    const pending = getPendingTurn(activeThread);
    if (!pending) {
      setRecovering(null);
      return;
    }
    setRecovering({ text: pending.text });
    const tid = activeThread;
    const epoch = viewEpochRef.current;
    const started = Date.now();
    const timer = setInterval(() => {
      if (epoch !== viewEpochRef.current) {
        // 用户又切走了：这一次恢复作废
        clearInterval(timer);
        return;
      }
      if (Date.now() - started > 180_000) {
        clearInterval(timer);
        setRecovering(null);
        message.warning('上一轮仍未返回，已停止等待；稍后刷新可看到结果');
        return;
      }
      if (getPendingTurn(tid)) return;
      // 后台那一轮结束了：历史此时已落库，拉回来（含这一问一答）
      clearInterval(timer);
      setRecovering(null);
      loadHistory(agentId, tid, epoch);
    }, 500);
    return () => clearInterval(timer);
  }, [agentId, activeThread, loadHistory]);

  // 专家变化 → 读后端会话状态 + 清空能力选择（各专家能力不同）
  useEffect(() => {
    if (!agentId) return;
    let alive = true;
    setSelectedSkills([]);
    setSelectedConnectors([]);
    setSelectedKnowledgeBaseIds([]);
    // 切专家同样是一次会话切换：落定前不让发送插进来（否则会发到上一个专家的线程）
    beginSessionOp();
    (async () => {
      try {
        const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
        if (!alive) return;
        setSessions(st.sessions);
        setActiveThread(st.current);
        clearView();
        if (st.current) loadHistory(agentId, st.current);
      } catch (e) {
        if (alive) message.error(`加载会话失败：${(e as Error).message}`);
      } finally {
        if (alive) endSessionOp();
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
    if (!agentId || blockedRef.current) return;
    beginSessionOp();
    try {
      await post('/chat/new', { agent_id: agentId });
      const st = await get<ChatState>(`/chat/state?agent_id=${agentId}`);
      setSessions(st.sessions);
      setActiveThread(st.current);
      clearView();
      if (st.current) loadHistory(agentId, st.current);
    } catch (e) {
      message.error(`新建会话失败：${(e as Error).message}`);
    } finally {
      endSessionOp();
    }
  };

  // 侧栏会话可能几十条（实测已有 11 条），搜索只在超过一屏时才露出来
  const visibleSessions = useMemo(() => {
    const q = sessionQuery.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter(s => (s.title || '').toLowerCase().includes(q) || s.thread_id.toLowerCase().includes(q));
  }, [sessions, sessionQuery]);

  const switchSession = async (tid: string) => {
    if (tid === activeThread || blockedRef.current) return;
    beginSessionOp();
    try {
      await post('/chat/switch', { agent_id: agentId, thread_id: tid });
      setActiveThread(tid);
      clearView();
      loadHistory(agentId!, tid);
    } catch (e) {
      message.error(`切换会话失败：${(e as Error).message}`);
    } finally {
      endSessionOp();
    }
  };

  // 会话列表的删除图标直接触发（用户要求去掉确认框）：删完立刻刷新列表并切到最近会话
  const deleteSession = async (tid: string) => {
    if (!agentId || blockedRef.current) return;
    beginSessionOp();
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
    } finally {
      endSessionOp();
    }
  };

  /**
   * 发送（输入框与重试条共用入口）。
   *
   * 1) 会话切换（新建/切换/换专家/删除）尚未落定时直接丢弃这一下：此刻 activeThread
   *    还是旧值，发出去就是「消息进了上一个会话，新会话页面空着」——即用户报的
   *    「发起对话后立即就收不到消息」。
   * 2) 发送前推进视图代次：让所有在途的历史加载作废，不能把这一轮流式落下的回复抹掉。
   */
  const handleSend = (text: string, overrideThread?: string) => {
    const trimmed = text.trim();
    if (!trimmed || blockedRef.current || stream.sending) return;
    if (sessionBusyRef.current) {
      // 会话还没落定：排队，等 activeThread 换成新的再补发（丢弃会让用户白打一遍）
      pendingSendRef.current = pendingSendRef.current
        ? { ...pendingSendRef.current, threadId: overrideThread ?? pendingSendRef.current.threadId }
        : { text: trimmed, threadId: overrideThread };
      setInput('');
      return;
    }
    viewEpochRef.current += 1;
    setInput('');
    stream.send(trimmed, overrideThread);
  };

  /**
   * 补发排队中的发送：依赖 sessionBusy 变 false 才跑（此时 activeThread 已是新会话、
   * clearView 也已生效），用 sendRef（最新渲染闭包，messages/activeThread 都是新的）发出去。
   * 目标会话的历史还在路上就先等它落地，否则随后到达的历史会把刚流式落下的回复盖掉。
   */
  useEffect(() => {
    if (sessionBusy) return;
    const pending = pendingSendRef.current;
    if (!pending) return;
    const target = pending.threadId ?? activeThread;
    if (!target) return;
    pendingSendRef.current = null;
    let alive = true;
    const fire = () => {
      if (!alive) return;
      viewEpochRef.current += 1;
      sendRef.current(pending.text, target);
    };
    const inflight = historyRef.current;
    if (inflight) void inflight.then(fire, fire);
    else fire();
    return () => { alive = false; };
  }, [sessionBusy, activeThread]);

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
          disabled={busy}
        />
        <Button icon={<PlusOutlined />} onClick={newSession} disabled={!agentId || busy} block>
          新建会话
        </Button>
        <div style={{ fontSize: 12, color: 'var(--label-3)', fontWeight: 600 }}>会话记录</div>
        {sessions.length > 6 && (
          <Input
            size="small"
            allowClear
            placeholder="搜索会话"
            value={sessionQuery}
            onChange={e => setSessionQuery(e.target.value)}
          />
        )}
        <div style={{ overflow: 'auto', flex: 1 }}>
          {visibleSessions.length === 0 && (
            <EmptyState
              simple
              description={sessions.length === 0 ? '暂无会话' : `没有匹配「${sessionQuery}」的会话`}
              style={{ marginTop: 24 }}
            />
          )}
          {visibleSessions.map(s => (
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
              <Button size="small" icon={<HistoryOutlined />} onClick={() => setTrajectoryOpen(true)} disabled={busy}>
                轨迹
              </Button>
              <Button size="small" icon={<BulbOutlined />} onClick={() => setMemoryOpen(true)} disabled={!agentId}>
                记忆
              </Button>
            </>
          }
        />

        <MessageList
          messages={recovering ? [...messages, {
            role: 'user' as const,
            segments: [{ type: 'text' as const, content: recovering.text, id: 'recover-user' }],
          }] : messages}
          streamSegments={streamSegments}
          sending={sending || Boolean(recovering)}
          bodyRef={bodyRef}
          onBodyScroll={onBodyScroll}
        />

        {approval && <ApprovalCard approval={approval} onSubmit={submitApproval} />}

        <Composer
          input={input}
          setInput={setInput}
          sending={busy}
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
          disabled={sessionBusy || Boolean(recovering)}
          onSend={handleSend}
          onStop={stream.stop}
          onToggleSkill={toggleSkill}
          onToggleSkillPackage={toggleSkillPackage}
          onToggleConnector={toggleConnector}
          onToggleKnowledgeBase={toggleKnowledgeBase}
          onChangeModel={setSelectedModel}
          onResetModel={() => setSelectedModel(MODEL_AUTO)}
          onRetry={turn => handleSend(turn.text, turn.threadId)}
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
