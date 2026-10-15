/**
 * 审批卡片：多动作打包的回归锁。
 *
 * 起因：卡片原先只渲染 `action_requests[0]`，而 harness 会把一条回复里所有命中
 * 门禁的工具调用打包成一次审批请求 —— 第二、第三个写操作对用户不可见，
 * 但决策条数必须与动作条数相等，否则 harness 直接报错、会话永久卡在中断上。
 * 这里锁三件事：全量渲染、每条各自的允许取值、提交出的决策条数对得上。
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

// vitest 未开 globals：@testing-library/react 的自动 cleanup 不生效，需手动注册
// （否则同一文件里多个 render 的 DOM 叠在一起，按名字查元素会「found multiple」）
afterEach(cleanup);

import { toApprovalActions } from './ApprovalCard';
import ApprovalCard from './ApprovalCard';
import type { ApprovalState } from './useChatStream';

const multi = {
  action_requests: [
    { name: 'mes_create_order', args: { id: 'WO-1' } },
    { name: 'mes_close_order', args: { id: 'WO-2' }, description: '关闭工单' },
  ],
  review_configs: [
    { action_name: 'mes_create_order', allowed_decisions: ['approve', 'reject'] },
    { action_name: 'ask_user', allowed_decisions: ['respond'] },
  ],
};

describe('toApprovalActions', () => {
  it('全量渲染 + 按 action_name 并上 allowed_decisions', () => {
    const actions = toApprovalActions(multi);
    expect(actions.map(a => a.name)).toEqual(['mes_create_order', 'mes_close_order']);
    expect(actions[0].allowed).toEqual(['approve', 'reject']);
    // review_configs 与 action_requests 不同名时（ask_user），退回 tool_guard 口径
    expect(actions[1].allowed).toEqual(['approve', 'reject']);
    expect(actions[1].description).toBe('关闭工单');
  });

  it('缺 request 时返回空数组而不是抛错', () => {
    expect(toApprovalActions(undefined)).toEqual([]);
    expect(toApprovalActions({})).toEqual([]);
  });
});

const state = (request: object, pending = false): ApprovalState => ({
  requestId: 'r1',
  threadId: 't1',
  request,
  pending,
});

describe('ApprovalCard', () => {
  it('两个动作 → 提交两条决策，默认都是批准', () => {
    const onSubmit = vi.fn();
    render(<ApprovalCard approval={state(multi)} onSubmit={onSubmit} />);
    expect(screen.getByText('mes_create_order')).toBeTruthy();
    expect(screen.getByText('mes_close_order')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /提交 2 条决策/ }));
    expect(onSubmit).toHaveBeenCalledWith([
      { type: 'approve' },
      { type: 'approve' },
    ]);
  });

  it('逐条改选择 + 拒绝理由应用到被拒的那条', () => {
    const onSubmit = vi.fn();
    render(<ApprovalCard approval={state(multi)} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: '拒绝 mes_close_order' }));
    fireEvent.click(screen.getByRole('button', { name: /提交 2 条决策/ }));
    const [first, second] = onSubmit.mock.calls[0][0];
    expect(first).toEqual({ type: 'approve' });
    expect(second.type).toBe('reject');
  });

  it('单动作保持一键批准（不逼用户多点一次）', () => {
    const onSubmit = vi.fn();
    const one = { action_requests: [{ name: 'mes_write', args: {} }] };
    render(<ApprovalCard approval={state(one)} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: /批准执行/ }));
    expect(onSubmit).toHaveBeenCalledWith([{ type: 'approve' }]);
    // 单动作不该出现「提交 N 条决策」这种多一步的控件
    expect(screen.queryByRole('button', { name: /提交 1 条决策/ })).toBeNull();
  });

  it('提交中禁用按钮，避免重复放行同一个写工具', () => {
    const onSubmit = vi.fn();
    render(<ApprovalCard approval={state({ action_requests: [{ name: 'w', args: {} }] }, true)} onSubmit={onSubmit} />);
    const btn = screen.getByRole('button', { name: /批准执行/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('动作明细缺失时不给「批准」按钮（不能凭空放行一个看不见的写操作）', () => {
    const onSubmit = vi.fn();
    render(<ApprovalCard approval={state({})} onSubmit={onSubmit} />);
    expect(screen.queryByRole('button', { name: /批准执行/ })).toBeNull();
    expect(screen.getByText(/缺少动作明细/)).toBeTruthy();
  });
});
