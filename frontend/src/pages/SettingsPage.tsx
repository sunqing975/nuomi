/** pages/SettingsPage：设置页（对齐 Octop /settings）。
 *  复用 SettingsModal 的 embedded 模式：分节导航 rail + 内容区直接铺在页面里。 */
import { Typography } from "antd";
import { SlidersHorizontal } from "lucide-react";
import type { ModelProvider, SettingsSnapshot } from "../api";
import SettingsModal from "../modules/ui-settings/SettingsModal";
import { t } from "../i18n";

const { Title } = Typography;

export default function SettingsPage({
  settings,
  providers,
  theme,
  onThemeToggle,
  onSettingsChanged,
  onModelsChanged,
}: {
  settings: SettingsSnapshot;
  providers: ModelProvider[];
  theme: "dark" | "light";
  onThemeToggle: () => void;
  onSettingsChanged: () => void;
  onModelsChanged: () => void;
}) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 24px 0", display: "flex", alignItems: "center", gap: 10 }}>
        <SlidersHorizontal size={18} />
        <Title level={4} style={{ margin: 0 }}>
          {t("nav.settings")}
        </Title>
      </div>
      <div style={{ flex: 1, minHeight: 0, padding: 16 }}>
        <SettingsModal
          embedded
          settings={settings}
          providers={providers}
          theme={theme}
          onThemeToggle={onThemeToggle}
          onClose={() => {}}
          onSettingsChanged={onSettingsChanged}
          onModelsChanged={onModelsChanged}
        />
      </div>
    </div>
  );
}
