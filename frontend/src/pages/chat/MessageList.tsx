/**
 * MessageList：对话消息区（历史 + 流式块 + 空态 + 滚动容器）。
 *
 * 从 Chat.tsx 抽出（P0-4，2026-10-06）——纯重构，行为不变。
 * 滚动容器/跟随开关由 ChatPage 持有（bodyRef/onBodyScroll），本组件只做渲染。
 */

import { RobotOutlined } from '@ant-design/icons';
import type { RefObject } from 'react';
import type { ChatMessage, Segment } from '../../api';
import EmptyState from '../../components/EmptyState';
import { MarkdownText, MessageBubble, SegmentView } from './MessageBubble';

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
  const hasStream = streamSegments.length > 0 || sending;
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
  );
}
