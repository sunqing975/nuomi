/** pages/shared/PageShell：通用页面外壳（对齐 Octop PageShell 视觉契约）。
 *  视觉契约：Title 行 20px/600 固定不滚动；subtitle 13px secondary；
 *  标题行与内容卡片间距 24px；内容卡片 colorBgContainer + radius 8 + padding 24 + 内部滚动；
 *  actions 槽右对齐在标题行。 */
import type { ReactNode } from "react";
import { Typography } from "antd";

const { Title, Text } = Typography;

export default function PageShell({
  title,
  subtitle,
  actions,
  children,
  fill,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  /** 标题行右侧操作区（按钮/搜索等） */
  actions?: ReactNode;
  /** 内容区不滚动、子组件撑满剩余高度（对齐 Octop fill） */
  fill?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        padding: "20px 24px 16px",
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      {/* Title 行 — 固定，不随内容滚动 */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexShrink: 0,
          marginBottom: 16,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <Title
            level={4}
            style={{
              margin: 0,
              lineHeight: "28px",
              fontSize: 20,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            {title}
          </Title>
          {subtitle && (
            <Text type="secondary" style={{ fontSize: 13, marginTop: 4, display: "block" }}>
              {subtitle}
            </Text>
          )}
        </div>
        {actions && <div style={{ flexShrink: 0, paddingTop: 2 }}>{actions}</div>}
      </div>

      {/* 内容卡片 — 内部滚动（fill 时子组件撑满） */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          minWidth: 0,
          background: "var(--bg-container, #17181c)",
          borderRadius: 8,
          padding: 24,
          overflowX: "hidden",
          overflowY: fill ? "hidden" : "auto",
          display: fill ? "flex" : undefined,
          flexDirection: fill ? "column" : undefined,
          border: "1px solid rgba(128,128,128,.10)",
        }}
      >
        {children}
      </div>
    </div>
  );
}
