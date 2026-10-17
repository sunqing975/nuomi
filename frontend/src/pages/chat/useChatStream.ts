/**
 * useChatStream：对话流式状态机（发送 → 流式累积 → done/error/中断终态）。
 *
 * 从 Chat.tsx 抽出（P0-4，2026-10-06）——纯重构，行为不变。
 * 职责边界：
 *  - 管理 sending / streamSegments / interrupted / abort 生命周期
 *  - send() 内做流式事件分派、终态判定（done/error/无终态=中断）、重试数据保留
 *  - 不碰会话切换/历史加载（那是 ChatPage 的职责）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';

import {
  chatApproval, chatStream, fetchApprovals, post, toApprovalRequest,
  type ApprovalDecisionInput, type ApprovalRequest, type ChatEvent, type ChatMessage, type ChatUsage, type Segment,
} from '../../api';
import { accumulateUsage } from '../../utils/formatUsage';
import { appendStreamSegment } from '../../utils/streamSegments';

/** 模型「自动」哨兵值：发送时不传 model（null），由后端按 agent 默认模型解析（对齐 Octop AUTO 语义） */
export const MODEL_AUTO = 'auto';

/**
 * 上游静默看门狗（毫秒）：整轮期间「连续多久没收到任何 SSE 帧」就判定卡死并主动中止。
 *
 * 为什么需要：harness 卡在 LLM 调用上时**一帧都不发**（2026-10-16 11:58 与 11:59 那两轮
 * 实测零输出：harness 日志停在 recall_inject 之后再无 capture_turn，DB 里也没有任何
 * 助手消息），而页面只有一个「思考中…」，用户看到的就是「发起对话后收不到消息」。
 * 卡死时主动 abort + 落中断条，至少能点「重试」。
 */
export const STREAM_STALL_MS = 90_000;

/**
 * 在飞轮次登记表（跨组件生命周期，模块级）。
 *
 * 切页/切专家会把聊天页整个卸载，但**这一轮不该被杀掉**：后端只在整轮完成时才落库
 * （thread_messages 投影 / checkpoint），一断连就是「用户消息和回复一起消失」——
 * 正是「切到专家页再回来，会话还在但消息全没了」的原因。
 * 所以卸载不再 abort，只把在飞的那一轮登记在这里：回到对话页时先用它把用户那条补上
 * （乐观消息），等它跑完再把历史拉回来。
 */
const pendingTurns = new Map<string, { text: string; startedAt: number }>();

/** 该会话是否还有一轮在后台跑（切页不杀轮次，回到页面时据此恢复显示） */
export function getPendingTurn(threadId: string): { text: string; startedAt: number } | null {
  return pendingTurns.get(threadId) ?? null;
}

/**
 * 片段稳定 id 生成器（模块级自增，流式片段进 state 时生成）。
 * 为什么不能用数组下标当 key：SegmentView 的折叠状态 `open` 活在组件实例里，
 * 而流式期间相邻同类片段会合并、历史回读会整批替换 —— 下标 key 会让 React 把
 * 上一个片段的实例复用到新片段上，折叠状态就错位了。id 跟着片段本身走才稳定。
 */
let segmentSeq = 0;
export function nextSegmentId(): string {
  segmentSeq += 1;
  return `seg-${segmentSeq}`;
}

/** 流被中断（无 done 帧）时保留待重试的那一轮 */
export interface InterruptedTurn {
  text: string;
  threadId: string;
}

/** HITL 人工审批状态（对话暂停，等待用户在审批卡片上 approve/reject） */
export interface ApprovalState {
  requestId: string;
  threadId: string;
  request: ApprovalRequest;
  pending: boolean;
}

export interface UseChatStreamOptions {
  agentId: string | null;
  /** 当前线程（重试发回**原来那轮**的会话，用户可能已切走） */
  activeThread: string | null;
  /** 消息列表（函数式更新，hook 不持有镜像） */
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  selectedSkills: string[];
  selectedConnectors: string[];
  selectedModel: string | null;
  selectedKnowledgeBaseIds: string[];
  /** 发送完成后刷新会话列表（标题/时间 touch） */
  onSessionChanged?: () => void;
}

export function useChatStream(opts: UseChatStreamOptions) {
  const {
    agentId,
    activeThread,
    messages,
    setMessages,
    selectedSkills,
    selectedConnectors,
    selectedModel,
    selectedKnowledgeBaseIds,
    onSessionChanged,
  } = opts;

  const [sending, setSending] = useState(false);
  const [streamSegments, setStreamSegments] = useState<Segment[]>([]);
  const [interrupted, setInterrupted] = useState<InterruptedTurn | null>(null);
  const [approval, setApproval] = useState<ApprovalState | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /** 卸载标记：卸载触发的 abort 不该给已销毁的页面弹提示/写状态 */
  const unmountedRef = useRef(false);
  /**
   * 发送态的同步镜像。
   * setSending 要等一次渲染才生效，而 Composer 的 onClick 可能在同一 task 里被连点两次
   * （双击/自动化），那时 send 闭包里的 sending 还是 false —— 会重复发一轮。这里同步挡。
   */
  const sendingRef = useRef(false);

  // 卸载（切页/切专家）**不再中止在途请求**：后端只在整轮完成时落库，
  // 掐断连接 = 用户消息和回复一起丢（「切页回来消息全没了」的根因）。
  // 卸载只置标记（停止给已销毁页面写状态/弹提示）；真正的停止入口是 stop()，以及浏览器整页关闭。
  useEffect(() => {
    // React 18 StrictMode（dev）是 mount→cleanup→mount：只在 cleanup 里置 true 会让标记
    // 永久为真，send 的 finally 里 `if (!unmountedRef.current) setSending(false)` 就再也
    // 不执行 —— 发送态永远停在 true（按钮变「停止」、输入框禁用），页面看起来就是
    // 「发完这一条之后再也发不出/收不到消息」。所以每次挂载都复位。
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      // 注意：这里刻意不 abort（见上）。
    };
  }, []);

  /** 清空流式片段（切会话/切专家/删会话时） */
  const clearStream = useCallback(() => {
    setStreamSegments([]);
    setApproval(null);
  }, []);

  /** 停止生成：中断流式请求（后端同时收到断连，停止这一轮）。 */
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  /** 发送一轮对话；text 来自输入框（override 用于重试时也可直接传入）。 */
  const send = useCallback(
    async (textRaw: string, overrideThread?: string) => {
      const text = textRaw.trim();
      if (!text || sending || !agentId) return;
      // 重试要发回**原来那轮**的会话（用户可能已经切走了）
      const tid = overrideThread ?? activeThread;
      if (!tid) return;
      if (sendingRef.current) return;
      sendingRef.current = true;
      setInterrupted(null);
      const userMsg: ChatMessage = {
        role: 'user',
        segments: [{ type: 'text', content: text, id: nextSegmentId() }],
      };
      const next = [...messages, userMsg];
      setMessages(next);
      setSending(true);
      setStreamSegments([]);
      // 取消支持：用户点「停止生成」或组件卸载时 abort（后端断连即停止，不再跑完白烧 token）
      const controller = new AbortController();
      abortRef.current = controller;
      // 登记「这一轮在飞」：组件被卸载（切页）后流仍在跑，回到页面时据此恢复显示
      pendingTurns.set(tid, { text, startedAt: Date.now() });
      let gotDone = false;
      let gotError = false;
      let gotApproval = false;
      let streamError = '';
      let stopped = false;
      // 本轮累计 token 用量：一轮带工具的对话里 harness 每次 LLM 调用各发一帧 usage，求和才是真实花费
      let turnUsage: ChatUsage | undefined;
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

      // 上游静默看门狗：每收到一帧就重置，连续 STREAM_STALL_MS 没有新帧（含首帧迟迟不来）
      // 就中止本轮，避免页面无限转圈而用户以为「收不到消息」。
      let stalled = false;
      let stallTimer: ReturnType<typeof setTimeout> | null = null;
      const clearStallTimer = () => {
        if (stallTimer !== null) { clearTimeout(stallTimer); stallTimer = null; }
      };
      const armStallTimer = () => {
        clearStallTimer();
        stallTimer = setTimeout(() => { stalled = true; controller.abort(); }, STREAM_STALL_MS);
      };

      try {
        armStallTimer();
        await chatStream(agentId, text, tid, (e: ChatEvent) => {
          armStallTimer();
          if (e.type === 'token' && e.content) {
            pushSeg({ id: nextSegmentId(), type: 'text', content: e.content });
          } else if (e.type === 'reasoning' && e.content) {
            pushSeg({ id: nextSegmentId(), type: 'reasoning', content: e.content });
          } else if (e.type === 'tool_call') {
            pushSeg({ id: nextSegmentId(), type: 'tool_call', name: e.name, args: e.content, plugin_id: e.plugin_id });
          } else if (e.type === 'tool_result') {
            pushSeg({ id: nextSegmentId(), type: 'tool_result', name: e.name, content: e.detail, plugin_id: e.plugin_id });
          } else if (e.type === 'usage') {
            if (e.usage) turnUsage = accumulateUsage(turnUsage, e.usage);
          } else if (e.type === 'done') {
            gotDone = true;
            // 去掉末尾空白段；至少保留一个 text 段（哪怕空，显示占位）
            if (!segs.some(s => s.type === 'text')) pushSeg({ id: nextSegmentId(), type: 'text', content: '' });
            const finalMsg: ChatMessage = { role: 'assistant', segments: segs, usage: turnUsage };
            setMessages([...next, finalMsg]);
            setStreamSegments([]);
            // 标题/时间更新（后端 touch，仅「新会话」会替换标题）
            post('/chat/touch', { agent_id: agentId, thread_id: tid, title: text.slice(0, 20) }).catch(() => {});
            onSessionChanged?.();
          } else if (e.type === 'error') {
            // 后端补发的终止帧 = 终态。置 gotError 以免 finally 再报一次
            // 「未收到完成帧」（那句还与本事实相反：帧其实收到了）。
            gotError = true;
            streamError = e.content || '未知错误';
          } else if (e.type === 'approval_requested') {
            // HITL 暂停：对话流结束，等待用户审批（不落消息、不弹中断提示）
            gotApproval = true;
            setApproval({
              requestId: e.request_id || '',
              threadId: tid,
              request: e.request || {},
              pending: false,
            });
          }
        }, opts, controller.signal);
      } catch (err) {
        if ((err as Error).name === 'AbortError') {
          stopped = true;
        } else {
          message.error(`对话失败：${(err as Error).message}`);
        }
      } finally {
        clearStallTimer();
        pendingTurns.delete(tid);
        // 没有 done 也没有 error：连接被中断。已生成的片段必须落成消息，
        // 否则半截回复停在流式气泡里、刷新即消失（原实现只清 streamSegments）。
        // HITL 审批暂停（gotApproval）不算中断——审批卡片接管，续流由 submitApproval 处理。
        if (!gotDone && !gotError && !gotApproval) {
          if (segs.length) {
            if (!segs.some(s => s.type === 'text')) pushSeg({ id: nextSegmentId(), type: 'text', content: '' });
            setMessages([...next, { role: 'assistant', segments: segs, usage: turnUsage }]);
          }
          setStreamSegments([]);
          if (unmountedRef.current) {
            // 卸载触发的 abort（切页/切专家）：不要给已经不在的页面弹提示
          } else if (stalled) {
            message.warning(`上游 ${STREAM_STALL_MS / 1000} 秒没有任何返回，已中止本轮；可点下方「重试」`);
            setInterrupted({ text, threadId: tid });
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
        sendingRef.current = false;
        if (!unmountedRef.current) setSending(false);
      }
    },
    [agentId, activeThread, messages, setMessages, selectedSkills, selectedConnectors, selectedModel, selectedKnowledgeBaseIds, sending, onSessionChanged],
  );

  /**
   * 提交 HITL 人工审批（approve/reject）并续跑被暂停的对话。
   *
   * 审批前的片段（tool_call 卡片等）保留在 streamSegments 里，续流事件
   * （token / tool_result / done）继续累积到同一批，done 后落成完整
   * assistant 消息。拒绝时 harness 返回错误 ToolMessage，LLM 会就拒绝
   * 结果继续组织回复（不写入任何数据）。
   */
  const submitApproval = useCallback(
    async (decisions: ApprovalDecisionInput[]) => {
      if (!agentId || !approval) return;
      const tid = approval.threadId;
      setApproval(p => (p ? { ...p, pending: true } : p));
      const controller = new AbortController();
      // 审批前已流式累积的片段（当前 streamSegments）继续合并，不另起一批
      let segs: Segment[] = streamSegments;
      const pushSeg = (s: Segment) => {
        segs = appendStreamSegment(segs, s);
        setStreamSegments(segs);
      };
      let gotDone = false;
      let gotError = false;
      let streamError = '';
      // 只统计续跑之后的调用（审批前那几帧属于上一个作用域，不重复计）
      let turnUsage: ChatUsage | undefined;
      try {
        await chatApproval(
          agentId,
          // request_id 带上：同一会话连续两次审批时，后端要按 id 精确收口台账
          {
            thread_id: tid,
            ...(approval.requestId ? { request_id: approval.requestId } : {}),
            decisions,
          },
          (e: ChatEvent) => {
          if (e.type === 'token' && e.content) {
            pushSeg({ id: nextSegmentId(), type: 'text', content: e.content });
          } else if (e.type === 'reasoning' && e.content) {
            pushSeg({ id: nextSegmentId(), type: 'reasoning', content: e.content });
          } else if (e.type === 'tool_call') {
            pushSeg({ id: nextSegmentId(), type: 'tool_call', name: e.name, args: e.content, plugin_id: e.plugin_id });
          } else if (e.type === 'tool_result') {
            pushSeg({ id: nextSegmentId(), type: 'tool_result', name: e.name, content: e.detail, plugin_id: e.plugin_id });
          } else if (e.type === 'usage') {
            if (e.usage) turnUsage = accumulateUsage(turnUsage, e.usage);
          } else if (e.type === 'done') {
            gotDone = true;
            if (!segs.some(s => s.type === 'text')) pushSeg({ id: nextSegmentId(), type: 'text', content: '' });
            const finalMsg: ChatMessage = { role: 'assistant', segments: segs, usage: turnUsage };
            setMessages([...messages, finalMsg]);
            setStreamSegments([]);
            setApproval(null);
            // 审批续跑后 touch（标题保持用户原话，不覆盖）
            post('/chat/touch', { agent_id: agentId, thread_id: tid, title: '' }).catch(() => {});
            onSessionChanged?.();
          } else if (e.type === 'error') {
            gotError = true;
            streamError = e.content || '未知错误';
          } else if (e.type === 'approval_requested') {
            // 续流中再次命中审批（罕见）：刷新卡片继续等审批
            setApproval({
              requestId: e.request_id || '',
              threadId: tid,
              request: e.request || {},
              pending: false,
            });
          }
        },
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          message.error(`审批提交失败：${(err as Error).message}`);
        }
      } finally {
        if (!gotDone && !gotError) {
          // 无终态：连接中断，审批卡片保留可重试
          setApproval(p => (p ? { ...p, pending: false } : p));
        } else if (gotError) {
          setApproval(null);
          setStreamSegments([]);
          if (!unmountedRef.current) message.error(`审批后生成失败：${streamError}`);
        }
      }
    },
    [agentId, approval, messages, onSessionChanged, streamSegments],
  );

  /**
   * 刷新/切换会话后把待审卡片找回来。
   *
   * 审批请求的 request_id 是后端现生成的 uuid，原先只活在 SSE 帧里：页面一刷新
   * 卡片就没了，而被 harness 拦下的写入还挂在中断上 —— 用户既看不到"有待批"，
   * 也没法批，只能干等或重开一轮（旧对话里的写操作等于凭空消失）。
   */
  const restoreApproval = useCallback(
    async (threadId: string) => {
      if (!agentId || !threadId) return;
      try {
        const rows = await fetchApprovals(agentId, { status: 'pending', threadId, limit: 5 });
        const row = rows[0];
        if (!row) return;
        setApproval({
          requestId: row.request_id,
          threadId: row.thread_id,
          request: toApprovalRequest(row),
          pending: false,
        });
      } catch {
        // 卡片找不回来不该挡住历史加载：最坏情况就是这次刷新看不到审批卡片
      }
    },
    [agentId],
  );

  return {
    sending,
    streamSegments,
    interrupted,
    approval,
    send,
    stop,
    clearStream,
    setInterrupted,
    submitApproval,
    restoreApproval,
  };
}
