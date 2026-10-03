/** pages/ExpertsPage：专家页（对齐 Octop /experts——Agents Management Centre）。
 *  Tab A：当前专家 + 专家库卡片网格（切换写 workspace 覆盖，重启生效）。
 *  领域语义：专家 = 人格 + 能力模板资产（manifest.json + IDENTITY/SOUL/USER.md）。 */
import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Empty, Row, Skeleton, Space, Tag, Typography, message } from "antd";
import { GraduationCap, RefreshCw, Star } from "lucide-react";
import { activateExpert, fetchExperts, type ExpertInfo } from "../api";
import { t } from "../i18n";

const { Title, Text } = Typography;

export default function ExpertsPage() {
  const [experts, setExperts] = useState<ExpertInfo[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    setErr(null);
    fetchExperts()
      .then((r) => {
        setExperts(r.experts);
        setCurrent(r.current);
      })
      .catch((e) => setErr(t("settings.experts.loadFailed") + "：" + String(e)));
  };

  useEffect(load, []);

  const switchExpert = async (name: string) => {
    setSwitching(name);
    setErr(null);
    try {
      const r = await activateExpert(name);
      setCurrent(r.name);
      message.success(t("settings.experts.restartHint"));
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setSwitching(null);
    }
  };

  return (
    <div style={{ padding: 24, height: "100%", overflow: "auto" }}>
      <Title level={4} style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 10 }}>
        <GraduationCap size={18} /> {t("nav.experts")}
        <Button
          size="small"
          type="text"
          icon={<RefreshCw size={14} />}
          onClick={load}
          aria-label={t("nav.experts")}
        />
      </Title>

      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}

      {experts === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : experts.length === 0 ? (
        <Empty description={t("settings.experts.loadFailed")} style={{ marginTop: 40 }} />
      ) : (
        <Row gutter={[16, 16]}>
          {experts.map((ex) => {
            const isCurrent = ex.name === current;
            return (
              <Col xs={24} sm={12} lg={8} key={ex.id}>
                <Card
                  hoverable
                  style={isCurrent ? { borderColor: "var(--accent, #4B74FA)" } : undefined}
                  styles={{ body: { padding: 20 } }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 10,
                        background: "var(--accent-soft, rgba(75,116,250,.15))",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <GraduationCap size={22} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <Space size={6}>
                        <Text strong style={{ fontSize: 15 }}>
                          {ex.display_name}
                        </Text>
                        {isCurrent && (
                          <Tag icon={<Star size={11} />} color="gold">
                            {t("settings.experts.current")}
                          </Tag>
                        )}
                        {ex.default && <Tag>{t("settings.experts.default")}</Tag>}
                      </Space>
                      <div>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {ex.name}
                        </Text>
                      </div>
                    </div>
                  </div>
                  <Button
                    block
                    disabled={isCurrent}
                    loading={switching === ex.name}
                    onClick={() => void switchExpert(ex.name)}
                  >
                    {isCurrent ? t("settings.experts.current") : t("settings.experts.switch")}
                  </Button>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}
    </div>
  );
}
