/**
 * PageCard：页面级统一卡片外壳（管理页骨架）。
 *
 * 从各管理页的 `<Card>` 包裹模式中提炼（P0-3，2026-10-06）：
 * 统一标题区（title + extra）与内容区样式；先服务 Chat 与新增页，
 * 存量页面按 next-steps.md §2.2 的节奏回填，不一次重写。
 */

import { Card, type CardProps } from 'antd';
import type { CSSProperties, ReactNode } from 'react';

export interface PageCardProps {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  /** 卡片内边距（默认 16）。传 0 或 '0' 让内容自管边距。 */
  bodyPadding?: CSSProperties['padding'];
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
}

export default function PageCard({
  title,
  extra,
  children,
  bodyPadding = 16,
  style,
  bodyStyle,
}: PageCardProps) {
  const cardProps: CardProps = {
    title,
    extra,
    style: { background: 'var(--surface)', borderRadius: 'var(--radius-lg)', ...style },
    styles: { body: { padding: bodyPadding, ...bodyStyle } },
  };
  return <Card {...cardProps}>{children}</Card>;
}
