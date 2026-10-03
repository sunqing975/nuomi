/** pages/SkillsPage：技能页（对齐 Octop /skills，PageShell 外壳）。
 *  领域语义：技能 = 独立文档资产（SKILL.md：触发条件 + 说明 + 正文），全量注入专家上下文。 */
import { useEffect, useState } from "react";
import { Alert, Card, Empty, Skeleton, Space, Typography } from "antd";
import { BookOpen } from "lucide-react";
import { fetchSkills, type SkillInfo } from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";

const { Text } = Typography;

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetchSkills()
      .then(setSkills)
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <PageShell
      title={
        <>
          <BookOpen size={18} /> {t("nav.skills")}
        </>
      }
      subtitle={t("skills.subtitle")}
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}

      {skills === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : skills.length === 0 ? (
        <Empty description={t("skills.empty")} style={{ marginTop: 40 }} />
      ) : (
        <Space direction="vertical" size={8} style={{ width: "100%", maxWidth: 760 }}>
          {skills.map((s) => (
            <Card key={s.name} size="small" styles={{ body: { padding: "12px 16px" } }}>
              <Text strong>{s.name}</Text>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {s.description}
                </Text>
              </div>
            </Card>
          ))}
        </Space>
      )}
    </PageShell>
  );
}
