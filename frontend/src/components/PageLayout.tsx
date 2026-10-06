/**
 * PageLayout：页面级骨架（L1，2026-10-06）——标题 + 描述 + 右侧主操作 + 内容宽度约束。
 *
 * 统一 9 个管理页的「页头」：标题（20px/600）、一句话描述、主操作右对齐；
 * 内容区默认 `maxWidth 1080` 居中（对齐知识库页既有宽度），对话页用 `wide` 全宽。
 * 说明文字收敛进 description，不再散落页面各处。
 */

import type { CSSProperties, ReactNode } from 'react';

export interface PageLayoutProps {
  title: ReactNode;
  /** 一句话定位（替代散落的说明 Paragraph） */
  description?: ReactNode;
  /** 右侧主操作区（按钮组 / 开关） */
  extra?: ReactNode;
  /** 全宽模式（对话页）。默认 false → maxWidth 1080 居中 */
  wide?: boolean;
  style?: CSSProperties;
  children: ReactNode;
}

export default function PageLayout({
  title,
  description,
  extra,
  wide,
  style,
  children,
}: PageLayoutProps) {
  return (
    <div style={{ maxWidth: wide ? 'none' : 1080, margin: '0 auto', ...style }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
          flexWrap: 'wrap',
          marginBottom: 18,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--label-1)', lineHeight: 1.3 }}>
            {title}
          </div>
          {description != null && (
            <div style={{ fontSize: 13, color: 'var(--label-2)', marginTop: 4, lineHeight: 1.6 }}>
              {description}
            </div>
          )}
        </div>
        {extra != null && (
          <div style={{ flexShrink: 0, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {extra}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}
