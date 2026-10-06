/**
 * SectionToolbar：区块标题栏（左侧标题 + 右侧操作）。
 *
 * Chat 头部（标题 + 轨迹按钮）、管理页区块（标题 + 导入/新建按钮）共用的
 * 横条布局：标题靠左、extra 靠右、下边框分隔，样式对齐主题 token。
 */

import type { CSSProperties, ReactNode } from 'react';

export interface SectionToolbarProps {
  title?: ReactNode;
  /** 标题旁的次要信息（如会话 id、数量徽标） */
  subtitle?: ReactNode;
  /** 右侧操作区（按钮组） */
  extra?: ReactNode;
  style?: CSSProperties;
}

export default function SectionToolbar({ title, subtitle, extra, style }: SectionToolbarProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingBottom: 10,
        borderBottom: '1px solid var(--line-1)',
        marginBottom: 10,
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, minWidth: 0 }}>
        {title != null && <span style={{ fontWeight: 600, fontSize: 15 }}>{title}</span>}
        {subtitle != null && (
          <span style={{ fontSize: 12, color: 'var(--label-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {subtitle}
          </span>
        )}
      </div>
      {extra != null && <div style={{ flexShrink: 0 }}>{extra}</div>}
    </div>
  );
}
