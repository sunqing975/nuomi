/** pages/CapabilitiesPage：能力页（对齐 Octop 连接器/插件管理面）。
 *  领域语义：能力 = 插件（可选能力）+ 模块（内核能力）；统一启停/安装/卸载走能力域 API。 */
import { useState } from "react";
import { Alert, Card, Empty, Space, Spin, Switch, Tag, Typography } from "antd";
import { Puzzle } from "lucide-react";
import type { PluginInfo } from "../api";
import { togglePlugin } from "../api";
import { t } from "../i18n";

const { Title, Paragraph, Text } = Typography;

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
    } catch (e) {
      setErr(t("app.pluginToggleFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setToggling(null);
    }
  };

  // 外部插件（能力导向，用户可启停）；内核模块带 category=module 标记
  const external = plugins.filter((p) => !p.id.startsWith("runtime-") && !p.id.startsWith("service-"));
  const modules = plugins.filter((p) => p.id.startsWith("service-") || p.category === "module");

  return (
    <div style={{ padding: 24, height: "100%", overflow: "auto" }}>
      <Title level={4} style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 10 }}>
        <Puzzle size={18} /> {t("nav.capabilities")}
      </Title>
      <Paragraph type="secondary">
        能力 = 插件（可选能力分发单元）+ 模块（内核组成部分，默认常驻）。启停即改配置组合 → 挂载/卸载 fiber。
      </Paragraph>

      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} onClose={() => setErr(null)} />}
      {busy && <Spin size="small" style={{ marginBottom: 12 }} />}

      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {external.map((p) => (
          <Card key={p.id} size="small" styles={{ body: { padding: "12px 16px" } }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Space size={6} wrap>
                  <Text strong>{p.name}</Text>
                  <Tag color={p.category === "module" ? "gold" : "blue"}>{p.category === "module" ? "模块" : "插件"}</Tag>
                  {p.disabled && <Tag>已停用</Tag>}
                </Space>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {p.description}
                  </Text>
                </div>
                {p.tools.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      工具：{p.tools.join("、")}
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

      {modules.length > 0 && (
        <>
          <Title level={5} style={{ marginTop: 24 }}>
            内核模块（默认常驻）
          </Title>
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            {modules.map((p) => (
              <Card key={p.id} size="small" styles={{ body: { padding: "10px 16px" } }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <Space size={6}>
                      <Text>{p.name}</Text>
                      {p.services.length > 0 && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          服务：{p.services.join("、")}
                        </Text>
                      )}
                    </Space>
                  </div>
                  <Switch checked={!p.disabled} disabled size="small" onChange={() => void doToggle(p.name)} />
                </div>
              </Card>
            ))}
          </Space>
        </>
      )}

      {external.length === 0 && modules.length === 0 && (
        <Empty description={t("app.pluginsFailed", { msg: "" })} style={{ marginTop: 60 }} />
      )}
    </div>
  );
}
