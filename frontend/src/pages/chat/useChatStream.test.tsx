import { StrictMode, useEffect } from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest';

/**
 * 只替换网络出口：hook 自身的状态机（sending/streamSegments/中断）才是被测对象。
 * post/chatStream/chatApproval 全部走 mock，避免测试触碰真实后端。
 */
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    chatStream: vi.fn(),
    chatApproval: vi.fn(),
    post: vi.fn(async () => ({})),
    fetchApprovals: vi.fn(async () => []),
  };
});

import { chatStream } from '../../api';
import { useChatStream } from './useChatStream';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

type Stream = ReturnType<typeof useChatStream>;

function Harness({ onRender }: { onRender: (s: Stream) => void }) {
  const stream = useChatStream({
    agentId: 'agent-1',
    activeThread: 'thread-1',
    messages: [],
    setMessages: () => {},
    selectedSkills: [],
    selectedConnectors: [],
    selectedModel: 'auto',
    selectedKnowledgeBaseIds: [],
  });
  useEffect(() => { onRender(stream); });
  return null;
}

describe('useChatStream · 发送态复位', () => {
  it('StrictMode 双调用（dev）之后 sending 仍会复位 —— 否则按钮永远停在「停止」', async () => {
    let latest: Stream | null = null;
    (chatStream as unknown as Mock).mockImplementation(
      async (_agent, _text, _tid, onEvent: (e: { type: string; content?: string }) => void) => {
        onEvent({ type: 'token', content: '收到' });
        onEvent({ type: 'done' });
      },
    );
    render(<StrictMode><Harness onRender={s => { latest = s; }} /></StrictMode>);

    await act(async () => { await latest!.send('你好'); });

    // 卡死时会停在 true：输入框禁用、按钮显示「停止」，用户看到的就是「收不到消息」
    expect((latest as unknown as Stream).sending).toBe(false);
    expect((latest as unknown as Stream).streamSegments).toEqual([]);
  });
});
