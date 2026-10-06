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

import { chatStream, post, type ChatEvent, type ChatMessage, type Segment } from '../../api';
import { appendStreamSegment } from '../../utils/streamSegments';

/** 模型「自动」哨兵值：发送时不传 model（null），由后端按 agent 默认模型解析（对齐 Octop AUTO 语义） */
export const MODEL_AUTO = 'auto';

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
  const abortRef = useRef<AbortController | null>(null);
  /** 卸载标记：卸载触发的 abort 不该给已销毁的页面弹提示/写状态 */
  const unmountedRef = useRef(false);

  // 卸载（切页/切专家）时中止在途请求 —— 否则切到「设置」页 LLM 继续跑完，token 照扣。
  // 用标记区分「用户点停止」与「组件卸载」，后者不弹 toast。
  useEffect(() => () => {
    unmountedRef.current = true;
    abortRef.current?.abort();
  }, []);

  /** 清空流式片段（切会话/切专家/删会话时） */
  const clearStream = useCallback(() => setStreamSegments([]), []);

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
            onSessionChanged?.();
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
    },
    [agentId, activeThread, messages, setMessages, selectedSkills, selectedConnectors, selectedModel, selectedKnowledgeBaseIds, sending, onSessionChanged],
  );

  return { sending, streamSegments, interrupted, send, stop, clearStream, setInterrupted };
}
