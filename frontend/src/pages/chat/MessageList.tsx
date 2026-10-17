/**
 * MessageList：对话消息区（历史 + 流式块 + 空态 + 滚动容器）。
 *
 * 从 Chat.tsx 抽出（P0-4，2026-10-06）——纯重构，行为不变。
 * 滚动容器/跟随开关由 ChatPage 持有（bodyRef/onBodyScroll），本组件只做渲染。
 */

import { RobotOutlined } from '@ant-design/icons';
import { useEffect, useState, type RefObject } from 'react';
import type { ChatMessage, Segment } from '../../api';
import EmptyState from '../../components/EmptyState';
import { MarkdownText, MessageBubble, SegmentView, assistantAvatarStyle, assistantBubbleStyle } from './MessageBubble';

export interface MessageListProps {
  messages: ChatMessage[];
  streamSegments: Segment[];
  sending: boolean;
  bodyRef: RefObject<HTMLDivElement>;
  onBodyScroll: () => void;
}

export default function MessageList({
  messages,
  streamSegments,
  sending,
  bodyRef,
  onBodyScroll,
}: MessageListProps) {
  // 等待秒数：上游卡住时（一帧都不发）页面原先只有一个静态「思考中…」，
  // 用户无法判断「在跑」还是「死了」。挂上秒表至少看得出真的在等。
  const [waitedSec, setWaitedSec] = useState(0);
  useEffect(() => {
    if (!sending) { setWaitedSec(0); return; }
    const started = Date.now();
    const timer = setInterval(() => setWaitedSec(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [sending]);

  const hasStream = streamSegments.length > 0 || sending;
  /** 一个字都还没到（首帧前，或上游卡住）：这时页面上除了头像什么都没有 */
  const segmentsEmpty = streamSegments.length === 0;
  return (
    <div ref={bodyRef} onScroll={onBodyScroll} style={{ flex: 1, overflow: 'auto', paddingBottom: 12 }}>
      {messages.length === 0 && streamSegments.length === 0 && (
        <EmptyState style={{ marginTop: 80 }} description="和专家开始对话吧（记忆按会话隔离）" />
      )}
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} index={i} />
      ))}
      {hasStream && (
        <div style={{ display: 'flex', marginBottom: 12, gap: 8 }}>
          <div style={assistantAvatarStyle}>
            <RobotOutlined style={{ color: 'var(--primary)', fontSize: 15 }} />
          </div>
          <div style={{ minWidth: 0 }}>
            {streamSegments.map((s, j) =>
              s.type === 'text' ? (
                <div key={s.id ?? `stream-${j}`} style={{ ...assistantBubbleStyle, marginBottom: 6, fontSize: 14, lineHeight: 1.6 }}>
                  <MarkdownText raw={s.content} />
                  <span style={{ opacity: 0.5 }}>▍</span>
                </div>
              ) : (
                <SegmentView key={s.id ?? `stream-${j}`} seg={s} />
              ),
            )}
            {sending && streamSegments.every(s => s.type === 'tool_result' || s.type === 'tool_call') && (
              <div style={{ fontSize: 12, color: 'var(--label-3)' }}>
                {segmentsEmpty ? '正在等待模型返回…' : '思考中…'}
                {waitedSec >= 3 ? ` ${waitedSec}s` : ''}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
