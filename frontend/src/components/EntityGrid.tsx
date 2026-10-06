/**
 * EntityGrid：等宽等高实体卡片网格 + 内置空态 + 加载态。
 *
 * 收敛各管理页的实体网格（Row/Col、List grid、手写 grid 三套写法）与
 * 空态/加载态。由调用方负责错误态（ErrorState），本组件只做网格、加载与空态。
 */

import { Spin } from 'antd';
import type { CSSProperties, ReactNode } from 'react';
import EmptyState from './EmptyState';

export interface EntityGridProps<T> {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  /** 空列表文案 */
  emptyText?: ReactNode;
  /** 空态操作（如「去导入」） */
  emptyAction?: ReactNode;
  /** 加载中：显示居中 Spin（整网格统一加载态） */
  loading?: boolean;
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
  loading,
  minWidth = 340,
  gap = 16,
  style,
}: EntityGridProps<T>) {
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0', ...style }}>
        <Spin />
      </div>
    );
  }
  if (items.length === 0) {
    return <EmptyState description={emptyText ?? '暂无数据'} action={emptyAction} style={style} />;
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
