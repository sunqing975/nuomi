/** pages/ConnectorsPage：连接器页（对齐 Octop /connectors）。
 *  领域语义：连接器 = 外部能力连接（MCP server 等），经 langchain-mcp-adapters 接入。 */
import { useEffect, useState } from "react";
import { Alert, Card, Col, Empty, Row, Skeleton, Space, Tag, Typography } from "antd";
import { Cable, RefreshCw } from "lucide-react";
import { fetchConnectors, type ConnectorInfo } from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";
import { Button } from "antd";

const { Text } = Typography;

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState<ConnectorInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    setErr(null);
    fetchConnectors()
      .then(setConnectors)
      .catch((e) => setErr(String(e)));
  };

  useEffect(load, []);

  return (
    <PageShell
      title={
        <>
          <Cable size={18} /> {t("nav.connectors")}
        </>
      }
      subtitle={t("connectors.subtitle")}
      actions={
        <Button size="small" type="text" icon={<RefreshCw size={14} />} onClick={load} aria-label={t("nav.connectors")} />
      }
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}

      {connectors === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : connectors.length === 0 ? (
        <Empty description={t("connectors.empty")} style={{ marginTop: 40 }} />
      ) : (
        <Row gutter={[16, 16]}>
          {connectors.map((c) => (
            <Col xs={24} sm={12} lg={8} key={c.name}>
              <Card size="small" styles={{ body: { padding: 16 } }}>
                <Space size={8} style={{ marginBottom: 8 }}>
                  <Cable size={16} />
                  <Text strong>{c.name}</Text>
                  <Tag color={c.state === "active" ? "green" : "red"}>
                    {c.state === "active" ? t("connectors.active") : t("connectors.failed")}
                  </Tag>
                </Space>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {c.description}
                  </Text>
                </div>
                {c.services.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t("connectors.servicesLabel")}：{c.services.join("、")}
                    </Text>
                  </div>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </PageShell>
  );
}
