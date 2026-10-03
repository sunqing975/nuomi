/** pages/KnowledgeBasesPage：知识库页（对齐 Octop /knowledge-bases）。
 *  领域语义：知识库 = RAG 存储（Chroma+fastembed / 词法兜底，方案可插拔），
 *  文档经 knowledge_add 工具写入、此处只读浏览 + 删除。 */
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Popconfirm, Skeleton, Space, Tag, Typography, message } from "antd";
import { BookMarked, RefreshCw, Trash2 } from "lucide-react";
import { deleteKnowledgeDocument, fetchKnowledgeDocuments, type KnowledgeDocument } from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";

const { Text } = Typography;

function fmtTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function KnowledgeBasesPage() {
  const [data, setData] = useState<{ store: string; documents: KnowledgeDocument[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setErr(null);
    fetchKnowledgeDocuments()
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(load, [load]);

  const remove = async (id: string) => {
    try {
      await deleteKnowledgeDocument(id);
      message.success(t("knowledge.deleted"));
      load();
    } catch (e) {
      setErr(t("knowledge.deleteFailed") + "：" + String(e));
    }
  };

  return (
    <PageShell
      title={
        <>
          <BookMarked size={18} /> {t("nav.knowledgeBases")}
        </>
      }
      subtitle={t("knowledge.subtitle", { store: data?.store ?? "—" })}
      actions={
        <Button size="small" type="text" icon={<RefreshCw size={14} />} onClick={load} aria-label={t("nav.knowledgeBases")} />
      }
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} />}

      {data === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : data.documents.length === 0 ? (
        <Empty description={t("knowledge.empty")} style={{ marginTop: 40 }} />
      ) : (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          {data.documents.map((d) => (
            <Card key={d.id} size="small" styles={{ body: { padding: "12px 16px" } }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <Space size={6} style={{ marginBottom: 4 }}>
                    <Tag color="blue">{d.category}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {fmtTime(d.ts)}
                    </Text>
                  </Space>
                  <div style={{ wordBreak: "break-all" }}>
                    <Text style={{ fontSize: 13 }}>{d.content}</Text>
                  </div>
                </div>
                <Popconfirm
                  title={t("knowledge.deleteConfirm")}
                  okText={t("common.delete")}
                  cancelText={t("common.cancel")}
                  onConfirm={() => void remove(d.id)}
                >
                  <Button size="small" danger type="text" icon={<Trash2 size={13} />} />
                </Popconfirm>
              </div>
            </Card>
          ))}
        </Space>
      )}
    </PageShell>
  );
}
