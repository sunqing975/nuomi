/** MainLayout：对齐 Octop dashboard 的主框架——antd Layout（Sider 领域导航 + Header + Content）。
 *  领域语言导航：聊天 / 专家 / 能力 / 技能 / 工作区 / 设置（Octop 路由体系：chat/experts/…）。
 *  窄侧栏可折叠（220 ↔ 56，对齐 Octop EXPANDED/COLLAPSED_WIDTH）。 */
import { useState } from "react";
import { Avatar, Button, Dropdown, Layout, Menu, Switch, Tooltip, type MenuProps } from "antd";
import {
  BookOpen,
  GraduationCap,
  HardDrive,
  MessageSquareText,
  Puzzle,
  Bot,
  SlidersHorizontal,
} from "lucide-react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { t } from "../i18n";
import { PALETTES, type PaletteId } from "../themes";

const { Sider, Header, Content } = Layout;

const NAV_ITEMS: { key: string; path: string; icon: React.ReactNode; label: string }[] = [
  { key: "chat", path: "/chat", icon: <MessageSquareText size={16} />, label: t("nav.chat") },
  { key: "experts", path: "/experts", icon: <GraduationCap size={16} />, label: t("nav.experts") },
  { key: "capabilities", path: "/capabilities", icon: <Puzzle size={16} />, label: t("nav.capabilities") },
  { key: "skills", path: "/skills", icon: <BookOpen size={16} />, label: t("nav.skills") },
  { key: "workspace", path: "/workspace", icon: <HardDrive size={16} />, label: t("nav.workspace") },
  { key: "settings", path: "/settings", icon: <SlidersHorizontal size={16} />, label: t("nav.settings") },
];

const EXPANDED_WIDTH = 220;
const COLLAPSED_WIDTH = 56;

export default function MainLayout({
  expertDisplayName,
  theme,
  palette,
  robotEnabled,
  onThemeToggle,
  onPalette,
  onOpenRobot,
}: {
  expertDisplayName: string;
  theme: "dark" | "light";
  palette: PaletteId;
  robotEnabled: boolean;
  onThemeToggle: () => void;
  onPalette: (p: PaletteId) => void;
  onOpenRobot: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  // 选中项：取路径首段（/chat/xx → chat）
  const selected = location.pathname.split("/")[1] || "chat";
  const cur = NAV_ITEMS.find((i) => i.key === selected);

  const items: MenuProps["items"] = NAV_ITEMS.map((i) => ({
    key: i.key,
    icon: i.icon,
    label: i.label,
    onClick: () => navigate(i.path),
  }));

  const paletteItems: MenuProps["items"] = PALETTES.map((p) => ({
    key: p.id,
    label: (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            width: 12,
            height: 12,
            borderRadius: 3,
            background: p.color,
            display: "inline-block",
          }}
        />
        {t(p.label)}
      </span>
    ),
    onClick: () => onPalette(p.id),
  }));

  return (
    <Layout style={{ height: "100vh" }}>
      <Sider
        width={EXPANDED_WIDTH}
        collapsedWidth={COLLAPSED_WIDTH}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme={theme === "dark" ? "dark" : "light"}
        style={{ borderRight: "1px solid rgba(128,128,128,.12)" }}
      >
        {/* 品牌区：当前专家 */}
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: 10,
            padding: collapsed ? 0 : "0 16px",
            borderBottom: "1px solid rgba(128,128,128,.12)",
            overflow: "hidden",
          }}
        >
          <Avatar
            size={30}
            style={{ background: "transparent", color: "var(--label-1, #eee)", flexShrink: 0 }}
          >
            <GraduationCap size={18} />
          </Avatar>
          {!collapsed && (
            <span style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap" }}>糯米 Nuomi</span>
          )}
        </div>
        <Menu
          mode="inline"
          theme={theme === "dark" ? "dark" : "light"}
          selectedKeys={[selected]}
          items={items}
          style={{ borderInlineEnd: "none" }}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            height: 56,
            padding: "0 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid rgba(128,128,128,.12)",
            background: "transparent",
            lineHeight: "56px",
          }}
        >
          {/* 左侧：当前页面 + 当前专家 */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
            <span
              style={{ fontSize: 15, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {cur?.label ?? t("nav.chat")}
            </span>
            <span style={{ opacity: 0.55, fontSize: 13, whiteSpace: "nowrap" }}>
              {t("nav.expertLabel")}：{expertDisplayName}
            </span>
          </div>

          {/* 右侧：机器人模式 / 色板 / 明暗 */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {robotEnabled && (
              <Tooltip title={t("app.robotSwitch")}>
                <Button
                  type="text"
                  icon={<Bot size={16} />}
                  onClick={onOpenRobot}
                  aria-label={t("app.robotSwitch")}
                />
              </Tooltip>
            )}
            <Dropdown menu={{ items: paletteItems }} placement="bottomRight" trigger={["click"]}>
              <Button
                type="text"
                icon={
                  <span
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 4,
                      background: PALETTES.find((p) => p.id === palette)?.color ?? "#4B74FA",
                      display: "inline-block",
                    }}
                  />
                }
                aria-label={t("nav.palette")}
              />
            </Dropdown>
            <Tooltip title={theme === "dark" ? t("nav.themeLight") : t("nav.themeDark")}>
              <Switch
                size="small"
                checked={theme === "light"}
                onChange={onThemeToggle}
                aria-label={t("nav.themeToggle")}
              />
            </Tooltip>
          </div>
        </Header>

        <Content style={{ overflow: "hidden" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
