/** pages/ExpertsPage：专家页（对齐 Octop /experts —— Agents Management Centre）。
 *  Tab 1「我的专家」：可激活的专家卡片网格（当前专家标识 + 切换）；
 *  Tab 2「专家库」：全部专家模板资产（对齐 Octop ExpertCard：accent 图标 + 名称 + 描述 + footer 徽标）。
 *  领域语义：专家 = 人格 + 能力模板资产（manifest.json + IDENTITY/SOUL/USER.md），切换写 workspace 覆盖，重启生效。 */
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Col, Drawer, Empty, Input, Modal, Row, Skeleton, Space, Tag, Tabs, message } from "antd";
import { BookOpen, CheckCircle, GraduationCap, Plus, RefreshCw, Trash2 } from "lucide-react";
import { activateExpert, cloneExpert, deleteExpert, fetchExperts, type ExpertInfo } from "../api";
import { t } from "../i18n";
import PageShell from "./shared/PageShell";

/** 专家卡片：对齐 Octop ExpertCard（--expert-accent 驱动 icon 底色 + 名称 + 描述 + footer 徽标） */
function ExpertCard({
  expert,
  isCurrent,
  switching,
  onSwitch,
  onOpenCreate,
  canDelete,
  onDelete,
  libraryMode,
}: {
  expert: ExpertInfo;
  isCurrent: boolean;
  switching: boolean;
  onSwitch: (name: string) => void;
  onOpenCreate: (expert: ExpertInfo) => void;
  canDelete: boolean;
  onDelete: (name: string) => void;
  libraryMode: boolean;
}) {
  const accent = expert.color || "var(--accent, #4B74FA)";
  return (
    <div
      onClick={libraryMode ? () => onSwitch(expert.name) : undefined}
      style={{
        background: "var(--bg-primary, #1b1d22)",
        border: isCurrent ? "2px solid var(--accent, #4B74FA)" : "2px solid rgba(128,128,128,.14)",
        borderRadius: 10,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 172,
        cursor: libraryMode ? "pointer" : "default",
        position: "relative",
        transition: "border-color .2s, background .2s, transform .2s",
        boxSizing: "border-box",
      }}
    >
      {/* Icon + title */}
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
            {isCurrent && (
              <Tag icon={<CheckCircle size={11} />} color="gold" style={{ marginInlineEnd: 0 }}>
                {t("settings.experts.current")}
              </Tag>
            )}
            {expert.default && <Tag style={{ marginInlineEnd: 0 }}>{t("settings.experts.default")}</Tag>}
          </div>
        </div>
      </div>

      {/* Description */}
      <div style={{ fontSize: 13, color: "var(--label-2, #9aa0a6)", flex: 1 }}>{expert.description || "\u00a0"}</div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        {libraryMode ? (
          <span style={{ fontSize: 12, color: "var(--label-2, #9aa0a6)", display: "inline-flex", alignItems: "center", gap: 6 }}>
            <BookOpen size={12} />
            {t("experts.createFromTemplate")}
          </span>
        ) : isCurrent ? (
          <span style={{ fontSize: 12, color: "var(--label-2, #9aa0a6)", display: "inline-flex", alignItems: "center", gap: 6 }}>
            <CheckCircle size={12} />
            {t("experts.installedBadge")}
          </span>
        ) : (
          <span />
        )}
        <Space size={4}>
          {libraryMode && (
            <Button
              size="small"
              type="primary"
              ghost
              icon={<Plus size={12} />}
              onClick={(e) => {
                e.stopPropagation();
                onOpenCreate(expert);
              }}
            >
              {t("experts.createFromTemplate")}
            </Button>
          )}
          {!libraryMode && (
            <Button
              size="small"
              type={isCurrent ? "default" : "primary"}
              disabled={isCurrent}
              loading={switching}
              onClick={() => onSwitch(expert.name)}
            >
              {isCurrent ? t("settings.experts.current") : t("settings.experts.switch")}
            </Button>
          )}
          {canDelete && (
            <Button
              size="small"
              danger
              type="text"
              icon={<Trash2 size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(expert.name);
              }}
            />
          )}
        </Space>
      </div>
    </div>
  );
}

export default function ExpertsPage() {
  const [experts, setExperts] = useState<ExpertInfo[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  /** 从模板创建的 Drawer 草稿（对齐 Octop CreateFromExpertDrawer） */
  const [draft, setDraft] = useState<ExpertInfo | null>(null);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setErr(null);
    fetchExperts()
      .then((r) => {
        setExperts(r.experts);
        setCurrent(r.current);
      })
      .catch((e) => setErr(t("settings.experts.loadFailed") + "：" + String(e)));
  }, []);

  useEffect(load, [load]);

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

  const createFromTemplate = async () => {
    if (!draft || !createName.trim()) return;
    setCreating(true);
    setErr(null);
    try {
      await cloneExpert(draft.name, createName.trim());
      message.success(t("experts.created"));
      setDraft(null);
      setCreateName("");
      await load();
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    } finally {
      setCreating(false);
    }
  };

  const removeExpert = async (name: string) => {
    setErr(null);
    try {
      await deleteExpert(name);
      message.success(t("common.delete"));
      await load();
    } catch (e) {
      setErr(t("settings.experts.switchFailed", { msg: String(e instanceof Error ? e.message : e) }));
    }
  };

  const grid = (libraryMode: boolean) =>
    experts === null ? (
      <Skeleton active paragraph={{ rows: 4 }} />
    ) : experts.length === 0 ? (
      <Empty description={t("settings.experts.loadFailed")} style={{ marginTop: 40 }} />
    ) : (
      <Row gutter={[16, 16]}>
        {experts.map((ex) => (
          <Col xs={24} sm={12} lg={8} key={ex.id}>
            <ExpertCard
              expert={ex}
              isCurrent={ex.name === current}
              switching={switching === ex.name}
              onSwitch={(n) => void switchExpert(n)}
              onOpenCreate={(e) => setDraft(e)}
              canDelete={!libraryMode && !ex.default && ex.name !== current}
              onDelete={(n) => {
                Modal.confirm({
                  title: t("experts.deleteConfirm"),
                  okText: t("common.delete"),
                  cancelText: t("common.cancel"),
                  okButtonProps: { danger: true },
                  onOk: () => removeExpert(n),
                });
              }}
              libraryMode={libraryMode}
            />
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
            children: grid(false),
          },
          {
            key: "library",
            label: (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <BookOpen size={14} />
                {t("experts.expertLibrary")}
              </span>
            ),
            children: grid(true),
          },
        ]}
      />
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
    </PageShell>
  );
}
