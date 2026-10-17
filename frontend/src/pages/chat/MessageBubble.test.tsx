import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MessageBubble } from './MessageBubble';

afterEach(cleanup);

describe('MessageBubble · 被中断的回复', () => {
  it('历史里断连保底落库的半截回复带「已中断」提示', () => {
    render(
      <MessageBubble
        index={0}
        message={{ role: 'assistant', segments: [{ type: 'text', content: '半截回复', interrupted: true }] }}
      />,
    );
    expect(screen.getByText(/这条回复被中断了/)).toBeTruthy();
    // 半截正文本身照常显示（不能因为中断就丢掉已生成的部分）
    expect(screen.getByText(/半截回复/)).toBeTruthy();
  });

  it('正常完成的回复不带中断提示', () => {
    render(
      <MessageBubble index={0} message={{ role: 'assistant', segments: [{ type: 'text', content: '完整回复' }] }} />,
    );
    expect(screen.queryByText(/这条回复被中断了/)).toBeNull();
  });
});
