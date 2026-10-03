/** pages/CapabilitiesPage：能力页（对齐 Octop 连接器/插件管理面，PageShell 外壳）。
 *  领域语义：能力 = 插件（可选能力分发单元）；模块属机制层，不透出。 */
import { useState } from "react";
import { Alert, Card, Empty, Skeleton, Space, Switch, Tag, Typography, message } from "antd";
import { Puzzle } from "lucide-react";
import type { PluginInfo } from "../api";
import { togglePlugin } from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";

const { Text } = Typography;

export default function CapabilitiesPage({
  plugins,
  busy,
  onChanged,
}: {
  plugins: PluginInfo[];
  busy: boolean;
  onChanged: () => void;
}) {
  const [err, setErr] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const doToggle = async (name: string) => {
    setToggling(name);
    setErr(null);
    try {
      await togglePlugin(name);
      await onChanged();
      message.success(t("app.pluginToggleOk"));
    } catch (e) {
      setErr(t("app.pluginToggleFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setToggling(null);
    }
  };

  // 外部插件（能力导向，用户可启停）；内核模块带 category=module 标记
  const external = plugins.filter((p) => p.category === "plugin");

  return (
    <PageShell
      title={
        <>
          <Puzzle size={18} /> {t("nav.capabilities")}
        </>
      }
      subtitle={t("capabilities.subtitle")}
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} onClose={() => setErr(null)} />}
      {busy && <Skeleton active paragraph={{ rows: 3 }} style={{ marginBottom: 12 }} />}

      {plugins.length === 0 ? (
        <Empty description={t("app.pluginsFailed", { msg: "" })} style={{ marginTop: 60 }} />
      ) : (
        <>
          <Space direction="vertical" size={10} style={{ width: "100%" }}>
            {external.map((p) => (
              <Card key={p.id} size="small" styles={{ body: { padding: "12px 16px" } }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <Space size={6} wrap>
                      <Text strong>{p.name}</Text>
                      <Tag color="blue">{t("capabilities.pluginTag")}</Tag>
                      {p.disabled && <Tag>{t("capabilities.disabledTag")}</Tag>}
                    </Space>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {p.description}
                      </Text>
                    </div>
                    {p.tools.length > 0 && (
                      <div style={{ marginTop: 4 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {t("capabilities.toolsLabel")}：{p.tools.join("、")}
                        </Text>
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={!p.disabled && p.enabled}
                    loading={toggling === p.name}
                    disabled={p.disabled}
                    onChange={() => void doToggle(p.name)}
                  />
                </div>
              </Card>
            ))}
          </Space>
        </>
      )}
    </PageShell>
  );
}
