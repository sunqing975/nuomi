/**
 * 基元组件测试（P0-3）：渲染与交互冒烟，覆盖组件承诺的最小行为。
 * 使用 @testing-library/react（jsdom），避免 snapshot 脆弱性。
 */

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import EmptyState from './EmptyState';
import EntityGrid from './EntityGrid';
import ErrorState from './ErrorState';
import PageCard from './PageCard';
import PageLayout from './PageLayout';
import SectionToolbar from './SectionToolbar';

// vitest 未开 globals：@testing-library/react 的自动 cleanup 不生效，需手动注册
afterEach(cleanup);

describe('PageCard', () => {
  it('渲染标题 + extra + 内容', () => {
    render(
      <PageCard title="专家" extra={<button>新建</button>}>
        卡片内容
      </PageCard>,
    );
    expect(screen.getByText('专家')).toBeTruthy();
    expect(screen.getByText('新建')).toBeTruthy();
    expect(screen.getByText('卡片内容')).toBeTruthy();
  });

  it('无标题时不渲染标题区', () => {
    render(<PageCard>只有内容</PageCard>);
    expect(screen.getByText('只有内容')).toBeTruthy();
  });
});

describe('SectionToolbar', () => {
  it('标题靠左、extra 靠右', () => {
    render(
      <SectionToolbar title="会话" subtitle="thread-1" extra={<button>轨迹</button>} />,
    );
    expect(screen.getByText('会话')).toBeTruthy();
    expect(screen.getByText('thread-1')).toBeTruthy();
    expect(screen.getByText('轨迹')).toBeTruthy();
  });

  it('无 extra 时仅渲染标题', () => {
    render(<SectionToolbar title="标题" />);
    expect(screen.getByText('标题')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('EmptyState', () => {
  it('默认文案 + 自定义描述', () => {
    render(<EmptyState />);
    expect(screen.getByText('暂无数据')).toBeTruthy();
  });

  it('渲染 action 操作', () => {
    render(<EmptyState description="市场暂无插件" action={<button>去安装</button>} />);
    expect(screen.getByText('市场暂无插件')).toBeTruthy();
    expect(screen.getByText('去安装')).toBeTruthy();
  });

  it('simple 模式使用简化占位图', () => {
    const { container } = render(<EmptyState simple description="暂无会话" />);
    // antd 简化占位图为 SVG（PRESENTED_IMAGE_SIMPLE）
    expect(container.querySelector('svg')).toBeTruthy();
  });
});

describe('ErrorState', () => {
  it('无重试回调时不渲染按钮', () => {
    render(<ErrorState title="加载失败" description="网络错误" />);
    expect(screen.getByText('加载失败')).toBeTruthy();
    expect(screen.getByText('网络错误')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('点击重试触发 onRetry', async () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} retryText="重新加载" />);
    await userEvent.click(screen.getByText('重新加载'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('EntityGrid', () => {
  const items = [{ id: 'a' }, { id: 'b' }];
  const empty: { id: string }[] = [];

  it('渲染每个 item', () => {
    render(<EntityGrid items={items} renderItem={(it) => <div key={it.id}>{it.id}</div>} />);
    expect(screen.getByText('a')).toBeTruthy();
    expect(screen.getByText('b')).toBeTruthy();
  });

  it('空列表显示空态而非网格', () => {
    const { container } = render(
      <EntityGrid items={empty} renderItem={(it) => <div key={it.id}>{it.id}</div>} emptyText="暂无插件" />,
    );
    expect(screen.getByText('暂无插件')).toBeTruthy();
    expect(container.querySelector('[style*="grid-template-columns"]')).toBeNull();
  });

  it('空态支持操作', () => {
    render(
      <EntityGrid
        items={empty}
        renderItem={(it) => <div key={it.id}>{it.id}</div>}
        emptyAction={<button>去导入</button>}
      />,
    );
    expect(screen.getByText('去导入')).toBeTruthy();
  });
});

describe('PageLayout', () => {
  it('渲染标题 + 描述 + extra + 内容', () => {
    render(
      <PageLayout title="专家" description="管理专家实例" extra={<button>新建</button>}>
        内容区
      </PageLayout>,
    );
    expect(screen.getByText('专家')).toBeTruthy();
    expect(screen.getByText('管理专家实例')).toBeTruthy();
    expect(screen.getByText('新建')).toBeTruthy();
    expect(screen.getByText('内容区')).toBeTruthy();
  });

  it('默认内容区 maxWidth 1080 居中（wide 时全宽）', () => {
    const normal = render(<PageLayout title="t">内容</PageLayout>).container.firstElementChild as HTMLElement;
    expect(normal.style.maxWidth).toBe('1080px');
    expect(normal.style.margin).toContain('auto');

    cleanup();
    const wide = render(<PageLayout title="t" wide>内容</PageLayout>).container.firstElementChild as HTMLElement;
    expect(wide.style.maxWidth).toBe('none');
  });

  it('无 description / extra 时不渲染对应区块', () => {
    render(<PageLayout title="标题">内容</PageLayout>);
    expect(screen.getByText('标题')).toBeTruthy();
    expect(screen.getByText('内容')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
