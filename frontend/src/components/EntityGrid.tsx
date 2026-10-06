/**
 * EntityGrid：等宽等高实体卡片网格 + 内置空态。
 *
 * 收敛各管理页「`display:grid; repeat(auto-fill, minmax(340px,1fr)); gap:16` +
 * 空列表 <Empty>`」的重复（Market/Skills/AvatarModels 各写一遍）。
 * 由调用方负责加载态与错误态（ErrorState），本组件只做网格与空态。
 */

import type { CSSProperties, ReactNode } from 'react';
import EmptyState from './EmptyState';

export interface EntityGridProps<T> {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  /** 空列表文案 */
  emptyText?: ReactNode;
  /** 空态操作（如「去导入」） */
  emptyAction?: ReactNode;
  /** 卡片最小宽度（px），默认 340 */
  minWidth?: number;
  gap?: number;
  style?: CSSProperties;
}

export default function EntityGrid<T>({
  items,
  renderItem,
  emptyText,
  emptyAction,
  minWidth = 340,
  gap = 16,
  style,
}: EntityGridProps<T>) {
  if (items.length === 0) {
    return <EmptyState description={emptyText ?? '暂无数据'} action={emptyAction} />;
  }
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))`,
        gap,
        ...style,
      }}
    >
      {items.map((item, i) => renderItem(item, i))}
    </div>
  );
}
