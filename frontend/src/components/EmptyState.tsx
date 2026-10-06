/**
 * EmptyState：统一空态（antd Empty 封装）。
 *
 * 收敛各页 `<Empty>` 的散落写法（Market/Skills/Chat 各写一遍）；
 * 提供可选 action（如「去安装」「新建」按钮），空态不再是死胡同。
 */

import { Empty } from 'antd';
import type { CSSProperties, ReactNode } from 'react';

export interface EmptyStateProps {
  description?: ReactNode;
  /** 空态下方的操作（按钮/链接） */
  action?: ReactNode;
  /** 简易模式：小图标 + 弱化描述（用于侧栏、窄容器） */
  simple?: boolean;
  style?: CSSProperties;
}

export default function EmptyState({
  description,
  action,
  simple,
  style,
}: EmptyStateProps) {
  return (
    <Empty
      image={simple ? Empty.PRESENTED_IMAGE_SIMPLE : Empty.PRESENTED_IMAGE_DEFAULT}
      description={description ?? '暂无数据'}
      style={style}
    >
      {action}
    </Empty>
  );
}
