/** pages/ExpertsPage：专家页（对齐 Octop /experts —— Agents Management Centre）。
 *  Tab 1「我的专家」：Agent 实例卡片网格（对齐 Octop Agent：模板实例 + 生命周期状态 running/stopped，
 *    支持 启动/停止/编辑/删除）；
 *  Tab 2「专家库」：全部专家模板资产（ExpertCard：accent 图标 + 名称 + 描述 + footer「从模板创建」）。
 *  领域语义：Expert（模板，experts/<name>/）= 人格 + 能力模板资产，只读；Agent（实例，workspace/agents.json）
 *    = 模板的实例化，用户创建/启动/停止/编辑/删除的是 Agent。启动写 agents.json current，重启生效。 */
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Col, Drawer, Empty, Input, Modal, Row, Skeleton, Space, Tag, Tabs, message } from "antd";
import { BookOpen, CheckCircle, GraduationCap, Pencil, Play, Plus, Power, RefreshCw, Trash2 } from "lucide-react";
import {
  createAgent,
  deleteAgent,
  fetchAgents,
  fetchExperts,
  startAgent,
  stopAgent,
  updateAgent,
  type AgentInfo,
  type ExpertInfo,
} from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";

/** Agent 实例卡片：对齐 Octop Agent 列表（display_name + expert 徽标 + 状态 + 生命周期操作）。 */
function AgentCard({
  agent,
  isCurrent,
  busy,
  onStart,
  onStop,
  onEdit,
  onDelete,
}: {
  agent: AgentInfo;
  isCurrent: boolean;
  busy: boolean;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
  onEdit: (agent: AgentInfo) => void;
  onDelete: (id: string) => void;
}) {
  const running = agent.status === "running";
  const accent = agent.color || "var(--accent, #4B74FA)";
  return (
    <div
      style={{
        background: "var(--bg-primary, #1b1d22)",
        border: isCurrent ? "2px solid var(--accent, #4B74FA)" : "2px solid rgba(128,128,128,.14)",
        borderRadius: 10,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 172,
        position: "relative",
        transition: "border-color .2s, background .2s",
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: accent,
            background: `${accent}18`,
          }}
        >
          <GraduationCap size={20} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 15, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {agent.display_name}
            {isCurrent && (
              <Tag icon={<CheckCircle size={11} />} color="gold" style={{ marginInlineEnd: 0 }}>
                {t("settings.experts.current")}
              </Tag>
            )}
          </div>
          <div style={{ fontSize: 12, color: "var(--label-2, #9aa0a6)", display: "flex", alignItems: "center", gap: 6 }}>
            {t("agents.fromTemplate")}：{agent.expert}
            <Tag color={running ? "green" : "default"} style={{ marginInlineEnd: 0 }}>
              {running ? t("agents.running") : t("agents.stopped")}
            </Tag>
          </div>
        </div>
      </div>

      <div style={{ fontSize: 13, color: "var(--label-2, #9aa0a6)", flex: 1 }}>
        {agent.description || t("agents.noDescription")}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
        {running ? (
          <Button size="small" icon={<Power size={12} />} loading={busy} onClick={() => onStop(agent.id)}>
            {t("agents.stop")}
          </Button>
        ) : (
          <Button size="small" type="primary" ghost icon={<Play size={12} />} loading={busy} onClick={() => onStart(agent.id)}>
            {t("agents.start")}
          </Button>
        )}
        <Button size="small" type="text" icon={<Pencil size={13} />} title={t("agents.edit")} onClick={() => onEdit(agent)} />
        <Button
          size="small"
          danger
          type="text"
          icon={<Trash2 size={13} />}
          title={t("common.delete")}
          onClick={() => onDelete(agent.id)}
        />
      </div>
    </div>
  );
}

/** 专家模板卡片（专家库 Tab）：accent 图标 + 名称 + 描述 + 「从模板创建」入口。 */
function ExpertCard({
  expert,
  onOpenCreate,
}: {
  expert: ExpertInfo;
  onOpenCreate: (expert: ExpertInfo) => void;
}) {
  const accent = expert.color || "var(--accent, #4B74FA)";
  return (
    <div
      style={{
        background: "var(--bg-primary, #1b1d22)",
        border: "2px solid rgba(128,128,128,.14)",
        borderRadius: 10,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 172,
        cursor: "default",
        position: "relative",
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 10,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: accent,
            background: `${accent}18`,
          }}
        >
          <GraduationCap size={20} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 15, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {expert.display_name}
            {expert.default && <Tag style={{ marginInlineEnd: 0 }}>{t("settings.experts.default")}</Tag>}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 13, color: "var(--label-2, #9aa0a6)", flex: 1 }}>{expert.description || "\u00a0"}</div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--label-2, #9aa0a6)", display: "inline-flex", alignItems: "center", gap: 6 }}>
          <BookOpen size={12} />
          {t("experts.expertTemplate")}
        </span>
        <Button size="small" type="primary" ghost icon={<Plus size={12} />} onClick={() => onOpenCreate(expert)}>
          {t("experts.createFromTemplate")}
        </Button>
      </div>
    </div>
  );
}

export default function ExpertsPage() {
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [experts, setExperts] = useState<ExpertInfo[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  /** 从模板创建 Agent 的 Drawer 草稿（对齐 Octop CreateFromExpertDrawer） */
  const [draft, setDraft] = useState<ExpertInfo | null>(null);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  /** 编辑 Agent 的 Drawer 草稿（对齐 Octop EditAgentDrawer） */
  const [editDraft, setEditDraft] = useState<AgentInfo | null>(null);
  const [editName, setEditName] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setErr(null);
    Promise.all([fetchAgents(), fetchExperts()])
      .then(([a, e]) => {
        setAgents(a.agents);
        setCurrent(a.current);
        setExperts(e.experts);
      })
      .catch((e) => setErr(t("settings.experts.loadFailed") + "：" + String(e)));
  }, []);

  useEffect(load, [load]);

  const run = async (id: string, fn: () => Promise<void>, okMsg: string) => {
    setBusy(id);
    setErr(null);
    try {
      await fn();
      message.success(okMsg);
      await load();
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setBusy(null);
    }
  };

  const createFromTemplate = async () => {
    if (!draft || !createName.trim()) return;
    setCreating(true);
    setErr(null);
    try {
      await createAgent(draft.name, createName.trim());
      message.success(t("agents.created"));
      setDraft(null);
      setCreateName("");
      await load();
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setCreating(false);
    }
  };

  const saveEdit = async () => {
    if (!editDraft || !editName.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      await updateAgent(editDraft.id, { display_name: editName.trim() });
      message.success(t("common.save"));
      setEditDraft(null);
      await load();
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setSaving(false);
    }
  };

  const removeAgent = (id: string) => {
    Modal.confirm({
      title: t("agents.deleteConfirm"),
      okText: t("common.delete"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => run(id, () => deleteAgent(id), t("common.delete")),
    });
  };

  const agentGrid = () =>
    agents === null ? (
      <Skeleton active paragraph={{ rows: 4 }} />
    ) : agents.length === 0 ? (
      <Empty description={t("agents.empty")} style={{ marginTop: 40 }}>
        <Button type="primary" ghost icon={<Plus size={14} />} onClick={() => setDraft(experts?.[0] ?? null)}>
          {t("experts.createFromTemplate")}
        </Button>
      </Empty>
    ) : (
      <Row gutter={[16, 16]}>
        {agents.map((a) => (
          <Col xs={24} sm={12} lg={8} key={a.id}>
            <AgentCard
              agent={a}
              isCurrent={a.id === current}
              busy={busy === a.id}
              onStart={(id) => run(id, () => startAgent(id), t("agents.started"))}
              onStop={(id) => run(id, () => stopAgent(id), t("agents.stoppedMsg"))}
              onEdit={(a2) => {
                setEditDraft(a2);
                setEditName(a2.display_name);
              }}
              onDelete={removeAgent}
            />
          </Col>
        ))}
      </Row>
    );

  const expertGrid = () =>
    experts === null ? (
      <Skeleton active paragraph={{ rows: 4 }} />
    ) : experts.length === 0 ? (
      <Empty description={t("experts.libraryEmpty")} style={{ marginTop: 40 }} />
    ) : (
      <Row gutter={[16, 16]}>
        {experts.map((ex) => (
          <Col xs={24} sm={12} lg={8} key={ex.id}>
            <ExpertCard expert={ex} onOpenCreate={(e) => setDraft(e)} />
          </Col>
        ))}
      </Row>
    );

  return (
    <PageShell
      title={
        <>
          <GraduationCap size={18} /> {t("nav.experts")}
        </>
      }
      subtitle={t("experts.subtitle") + " · " + t("experts.switchHint")}
      actions={
        <Button size="small" type="text" icon={<RefreshCw size={14} />} onClick={load} aria-label={t("nav.experts")} />
      }
    >
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 16 }} onClose={() => setErr(null)} />}
      <Tabs
        items={[
          {
            key: "my",
            label: (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <GraduationCap size={14} />
                {t("experts.myExperts")}
              </span>
            ),
            children: agentGrid(),
          },
          {
            key: "library",
            label: (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <BookOpen size={14} />
                {t("experts.expertLibrary")}
              </span>
            ),
            children: expertGrid(),
          },
        ]}
      />

      {/* 从模板创建 Agent（对齐 Octop CreateFromExpertDrawer） */}
      <Drawer
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Plus size={14} />
            {t("experts.createFromTemplateTitle")}
          </span>
        }
        width={420}
        open={draft !== null}
        onClose={() => setDraft(null)}
        destroyOnClose
        footer={
          <div style={{ textAlign: "right" }}>
            <Button style={{ marginRight: 8 }} onClick={() => setDraft(null)}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" loading={creating} disabled={!createName.trim()} onClick={() => void createFromTemplate()}>
              {t("experts.createFromTemplateTitle")}
            </Button>
          </div>
        }
      >
        {draft && (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <div style={{ fontSize: 13, color: "var(--label-2, #9aa0a6)" }}>
              {t("experts.createFromTemplateSource", { name: draft.display_name })}
            </div>
            <Input
              placeholder={t("experts.createFromTemplatePlaceholder")}
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              onPressEnter={() => void createFromTemplate()}
              autoFocus
            />
          </Space>
        )}
      </Drawer>

      {/* 编辑 Agent（对齐 Octop EditAgentDrawer） */}
      <Drawer
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Pencil size={14} />
            {t("agents.editTitle")}
          </span>
        }
        width={420}
        open={editDraft !== null}
        onClose={() => setEditDraft(null)}
        destroyOnClose
        footer={
          <div style={{ textAlign: "right" }}>
            <Button style={{ marginRight: 8 }} onClick={() => setEditDraft(null)}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" loading={saving} disabled={!editName.trim()} onClick={() => void saveEdit()}>
              {t("common.save")}
            </Button>
          </div>
        }
      >
        {editDraft && (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <div style={{ fontSize: 13, color: "var(--label-2, #9aa0a6)" }}>
              {t("agents.fromTemplate")}：{editDraft.expert}
            </div>
            <Input
              placeholder={t("experts.createFromTemplatePlaceholder")}
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onPressEnter={() => void saveEdit()}
              autoFocus
            />
          </Space>
        )}
      </Drawer>
    </PageShell>
  );
}
