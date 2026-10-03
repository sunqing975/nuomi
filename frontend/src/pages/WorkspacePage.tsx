/** pages/WorkspacePage：工作区页（对齐 Octop /workspace）。
 *  领域语义：项目 = 工作区单元（绑定目录），文件树只读浏览。 */
import { useState } from "react";
import { Button, Card, Empty, Input, Modal, Space, Typography, message } from "antd";
import { FolderPlus, HardDrive } from "lucide-react";
import type { ProjectInfo, ThreadInfo } from "../api";
import { createProject } from "../api";
import FilesPanel from "../modules/ui-sidebar/FilesPanel";
import { t } from "../i18n";

const { Title, Text } = Typography;

export default function WorkspacePage({
  projects,
  threads,
  currentProjectId,
  onSelectProject,
  onProjectCreated,
  onDeleteProject,
}: {
  projects: ProjectInfo[];
  threads: ThreadInfo[];
  currentProjectId: number | null;
  onSelectProject: (id: number | null) => void;
  onProjectCreated: () => void;
  onDeleteProject: (id: number) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [directory, setDirectory] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await createProject(name.trim(), directory.trim() || undefined);
      setName("");
      setDirectory("");
      setCreating(false);
      onProjectCreated();
      onSelectProject(p.id);
      message.success(t("app.newProjectOk"));
    } catch (e) {
      message.error(t("app.newProjectFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setBusy(false);
    }
  };

  const selected = projects.find((p) => p.id === currentProjectId);

  return (
    <div style={{ padding: 24, height: "100%", overflow: "auto" }}>
      <Title level={4} style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 10 }}>
        <HardDrive size={18} /> {t("nav.workspace")}
      </Title>

      <Button icon={<FolderPlus size={14} />} onClick={() => setCreating(true)} style={{ marginBottom: 16 }}>
        {t("sidebar.newProject")}
      </Button>

      {projects.length === 0 ? (
        <Empty description={t("sidebar.noProjects")} style={{ marginTop: 40 }} />
      ) : (
        <Space direction="vertical" size={8} style={{ width: "100%", maxWidth: 720 }}>
          {projects.map((p) => (
            <Card
              key={p.id}
              size="small"
              styles={{ body: { padding: "10px 16px" } }}
              style={p.id === currentProjectId ? { borderColor: "var(--accent, #4B74FA)" } : undefined}
            >
              <div
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, cursor: "pointer" }}
                onClick={() => onSelectProject(p.id)}
              >
                <div style={{ minWidth: 0 }}>
                  <Space size={8}>
                    <Text strong>{p.name}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {threads.filter((x) => x.project_id === p.id).length} 会话
                    </Text>
                  </Space>
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {p.directory ?? t("app.projectNoDir")}
                    </Text>
                  </div>
                </div>
                <Button
                  size="small"
                  danger
                  type="text"
                  onClick={(e) => {
                    e.stopPropagation();
                    Modal.confirm({
                      title: t("app.deleteProject"),
                      content: p.name,
                      okText: t("common.delete"),
                      cancelText: t("common.cancel"),
                      onOk: () => onDeleteProject(p.id),
                    });
                  }}
                >
                  {t("common.delete")}
                </Button>
              </div>
            </Card>
          ))}
        </Space>
      )}

      {selected?.directory && (
        <div style={{ marginTop: 24, maxWidth: 720 }}>
          <Title level={5}>{selected.name}</Title>
          <FilesPanel projectId={selected.id} refreshTick={0} />
        </div>
      )}

      <Modal
        open={creating}
        title={t("sidebar.newProject")}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        confirmLoading={busy}
        onOk={() => void create()}
        onCancel={() => setCreating(false)}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size={8}>
          <Input placeholder={t("sidebar.projectName")} value={name} onChange={(e) => setName(e.target.value)} />
          <Input
            placeholder={t("sidebar.projectDir")}
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
          />
        </Space>
      </Modal>
    </div>
  );
}
