/** ui-settings：设置弹窗（对齐 Harness SettingsRoot——居中模态 + 左侧分节导航 rail）。
 *  分区：通用 / 模型（供应商+API Key+自定义） / 行为（Shell 沙箱）。
 *  插件管理已独立为插件面板（不再进设置）。
 *  明确不做登录与多用户（用户要求）。 */
import { useEffect, useState } from "react";
import { t } from "../../i18n";
import ConfirmDialog, { type ConfirmState } from "../ui-confirm/ConfirmDialog";
import { THEMES } from "../../themes";
import {
  CustomModelRow,
  ModelProvider,
  SettingsSnapshot,
  addCustomProvider,
  deleteCustomProvider,
  fetchAvailableModels,
  setGlobalSetting,
  updateCustomProvider,
} from "../../api";
import { CheckIcon, ChevronDownIcon, CpuIcon, EyeIcon, EyeOffIcon, GearIcon, InboxIcon, PlusIcon, ShieldIcon, WarnIcon, XIcon } from "../icons";

const APP_VERSION = "0.6.0";

type SectionId = "general" | "models" | "behavior";

const SECTIONS: { id: SectionId; icon: React.ReactNode; label: string }[] = [
  { id: "general", icon: <GearIcon />, label: t("settings.sections.general") },
  { id: "models", icon: <CpuIcon />, label: t("settings.sections.models") },
  { id: "behavior", icon: <ShieldIcon />, label: t("settings.sections.behavior") },
];

const SHELL_MODES: { value: string; label: string; desc: string }[] = [
  { value: "read-only", label: t("settings.behavior.readOnly"), desc: t("settings.behavior.readOnlyDesc") },
  { value: "workspace-write", label: t("settings.behavior.workspaceWrite"), desc: t("settings.behavior.workspaceWriteDesc") },
  { value: "full-access", label: t("settings.behavior.fullAccess"), desc: t("settings.behavior.fullAccessDesc") },
];

/** 表单内的模型草稿行（结构化编辑，替代旧文本行格式）。 */
interface ModelDraft {
  id: string;
  label: string;
  efforts: string[];
  context_window?: number;
  max_output?: number;
}

/** 容量格式化/解析：K=1000（对齐 dsh），如 256000 → "256K"、"32K" → 32000。 */
function formatCapacity(n?: number): string {
  if (!n) return "";
  return n % 1000 === 0 ? `${n / 1000}K` : String(n);
}
function parseCapacity(s: string): number | undefined {
  const v = s.trim();
  if (!v) return undefined;
  const m = /^(\d+(?:\.\d+)?)([kK]?)$/.exec(v);
  if (!m) return undefined;
  return Math.round(parseFloat(m[1]) * (m[2] ? 1000 : 1));
}

/** 自定义供应商表单（新增 / 编辑共用）。 */
function CustomForm({
  mode,
  initial,
  busy,
  onSave,
  onCancel,
  onDelete,
}: {
  mode: "add" | "edit";
  initial?: ModelProvider;
  busy: boolean;
  onSave: (body: {
    name: string;
    base_url: string;
    api_key?: string;
    models: CustomModelRow[];
  }) => Promise<void>;
  onCancel: () => void;
  onDelete?: () => void;
}) {
  const [name, setName] = useState(initial?.label ?? "");
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [models, setModels] = useState<ModelDraft[]>(
    initial?.models?.length
      ? initial.models.map((m) => ({
          id: m.model,
          label: m.label || m.model,
          efforts: m.efforts?.length ? [...m.efforts] : ["medium"],
          context_window: m.context_window,
          max_output: m.max_output,
        }))
      : [],
  );
  const [capOpen, setCapOpen] = useState<Record<number, boolean>>({});
  const [pulling, setPulling] = useState(false);
  const [pullErr, setPullErr] = useState<string | null>(null);

  const updateRow = (i: number, patch: Partial<ModelDraft>) =>
    setModels((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRow = (i: number) => {
    setModels((prev) => prev.filter((_, j) => j !== i));
    setCapOpen({});
  };
  const addRow = () => setModels((prev) => [...prev, { id: "", label: "", efforts: ["medium"] }]);

  const pull = async () => {
    if (!baseUrl.trim()) return;
    setPulling(true);
    setPullErr(null);
    try {
      const ids = await fetchAvailableModels(baseUrl.trim(), apiKey.trim());
      if (ids.length === 0) setPullErr(t("settings.models.form.pullEmpty"));
      else setModels(ids.map((id) => ({ id, label: id, efforts: ["medium"] })));
    } catch (e) {
      setPullErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPulling(false);
    }
  };

  return (
    <>
      {mode === "add" && (
        <button className="add-card-head" type="button" onClick={onCancel} title={t("common.cancel")}>
          <span className="provider-identity">
            <span className="provider-name">{name.trim() || t("settings.models.form.newTag")}</span>
            <span className="custom-tag">{t("settings.models.custom")}</span>
          </span>
          <span className="credential-dot" title={t("settings.models.keyMissing")} />
          <span className="provider-caret"><ChevronDownIcon /></span>
        </button>
      )}
      <div className="custom-form">
      <div className="form-field">
        <span className="field-label">{t("settings.models.form.name")}</span>
        <input
          className="form-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("settings.models.form.namePlaceholder")}
        />
      </div>
      <div className="form-field">
        <span className="field-label">{t("settings.models.form.baseUrl")}</span>
        <input
          className="form-input"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={t("settings.models.form.baseUrlPlaceholder")}
        />
      </div>
      <div className="form-field">
        <span className="field-label">
          API Key
          {mode === "edit" && initial?.api_key_masked && (
            <span className="field-hint">{initial.api_key_masked}</span>
          )}
        </span>
        <div className="input-shell">
          <input
            className="form-input"
            type={apiKeyVisible ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={mode === "edit" ? t("settings.models.form.apiKeyPlaceholder") : t("settings.models.form.apiKeyAddPlaceholder")}
          />
          <button
            className="key-vis-toggle"
            type="button"
            title={apiKeyVisible ? t("settings.models.form.keyHide") : t("settings.models.form.keyShow")}
            onClick={() => setApiKeyVisible((v) => !v)}
          >
            {apiKeyVisible ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
          </button>
        </div>
      </div>
      <div className="models-panel">
        <div className="models-panel-head">
          <span className="models-panel-title">
            {t("settings.models.form.modelsPanel")}
            <span className="models-count">{models.length}</span>
          </span>
          <button className="mini-btn" disabled={busy || pulling || !baseUrl.trim()} onClick={() => void pull()}>
            {pulling ? t("settings.models.form.pulling") : t("settings.models.form.pull")}
          </button>
        </div>
        {models.length === 0 && !pullErr && (
          <div className="models-empty">
            <InboxIcon size={16} />
            <span>{t("settings.models.form.modelsEmpty")}</span>
          </div>
        )}
          {models.map((row, i) => (
            <div className="model-edit-block" key={i}>
              <div className="model-edit-row">
                <input
                  className="form-input id"
                  value={row.id}
                  onChange={(e) => updateRow(i, { id: e.target.value })}
                  placeholder={t("settings.models.form.modelIdPlaceholder")}
                  title={t("settings.models.form.modelId")}
                />
                <input
                  className="form-input"
                  value={row.label}
                  onChange={(e) => updateRow(i, { label: e.target.value })}
                  placeholder={t("settings.models.form.modelLabelPlaceholder")}
                />
                <button
                  className={`model-cap-toggle ${capOpen[i] ? "open" : ""}`}
                  title={t("settings.models.form.contextWindow")}
                  onClick={() => setCapOpen((p) => ({ ...p, [i]: !p[i] }))}
                >
                  <ChevronDownIcon size={13} />
                </button>
                <button className="model-row-del" title={t("common.delete")} onClick={() => removeRow(i)}>
                  <XIcon size={13} />
                </button>
              </div>
              {capOpen[i] && (
                <div className="model-cap-grid">
                  <label>
                    {t("settings.models.form.contextWindow")}
                    <input
                      value={formatCapacity(row.context_window)}
                      onChange={(e) => updateRow(i, { context_window: parseCapacity(e.target.value) })}
                      placeholder={t("settings.models.form.contextWindowPlaceholder")}
                    />
                  </label>
                  <label>
                    {t("settings.models.form.maxOutput")}
                    <input
                      value={formatCapacity(row.max_output)}
                      onChange={(e) => updateRow(i, { max_output: parseCapacity(e.target.value) })}
                      placeholder={t("settings.models.form.maxOutputPlaceholder")}
                    />
                  </label>
                </div>
              )}
            </div>
          ))}
          <button className="add-model-btn" onClick={addRow}>
            <PlusIcon size={12} />
            {t("settings.models.form.addModel")}
          </button>
          {pullErr && <span className="field-note warn">{pullErr}</span>}
      </div>
      <div className="custom-form-actions">
        {onDelete && (
          <button className="mini-btn danger del" disabled={busy} onClick={onDelete}>
            {t("settings.models.deleteProvider")}
          </button>
        )}
        <button className="mini-btn" onClick={onCancel} disabled={busy}>
          {t("common.cancel")}
        </button>
        <button
          className="mini-btn primary"
          disabled={busy || !name.trim() || !baseUrl.trim()}
          onClick={() => {
            const clean = models.filter((m) => m.id.trim());
            if (clean.length === 0) {
              setPullErr(t("settings.models.form.needModel"));
              return;
            }
            void onSave({
              name: name.trim(),
              base_url: baseUrl.trim(),
              api_key: mode === "edit" ? (apiKey.trim() || "__KEEP__") : apiKey.trim(),
              models: clean.map((m) => ({
                id: m.id.trim(),
                label: m.label.trim() || m.id.trim(),
                efforts: m.efforts.length ? m.efforts : ["medium"],
                context_window: m.context_window,
                max_output: m.max_output,
              })),
            });
          }}
        >
          {mode === "add" ? (
            <>
              <PlusIcon size={13} />
              {t("settings.models.addProviderTitle")}
            </>
          ) : (
            <>
              <CheckIcon size={13} />
              {t("settings.saveChanges")}
            </>
          )}
        </button>
      </div>
      </div>
    </>
  );
}

export default function SettingsModal({
  settings,
  providers,
  theme,
  onThemeToggle,
  onClose,
  onSettingsChanged,
  onModelsChanged,
}: {
  settings: SettingsSnapshot;
  providers: ModelProvider[];
  theme: "dark" | "light";
  onThemeToggle: () => void;
  onClose: () => void;
  onSettingsChanged: () => void;
  onModelsChanged: () => void;
}) {
  const [section, setSection] = useState<SectionId>("general");
  const [err, setErr] = useState<string | null>(null);
  const [busyOp, setBusyOp] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [adding, setAdding] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const toggleExpand = (key: string) =>
    setExpandedKeys((ks) => (ks.includes(key) ? ks.filter((k) => k !== key) : [...ks, key]));
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [teamEnabled, setTeamEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    fetch("/api/health")
      .then(async (r) => {
        if (!r.ok) {
          setHealth("down");
          return;
        }
        setHealth("ok");
        const body = (await r.json()) as { team?: boolean };
        if (typeof body.team === "boolean") setTeamEnabled(body.team);
      })
      .catch(() => setHealth("down"));
  }, []);

  const saveGlobal = async (key: string, value: unknown) => {
    setErr(null);
    setBusyOp(true);
    try {
      await setGlobalSetting(key, value);
      onSettingsChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyOp(false);
    }
  };


  const shellMode = String(settings.global["shell_default_mode"] ?? "workspace-write");

  const allProviders = providers;

  return (
    <div className="modal-mask" onClick={onClose}>
      <div
        className="settings-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={t("settings.title")}
      >
        {/* 左侧分节导航 rail（Harness section nav） */}
        <nav className="settings-nav">
          <div className="settings-nav-title">{t("settings.title")}</div>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`settings-nav-row ${section === s.id ? "on" : ""}`}
              onClick={() => setSection(s.id)}
            >
              <span className="settings-nav-icon">{s.icon}</span>
              {s.label}
            </button>
          ))}
          <button className="settings-nav-close" onClick={onClose} title={t("settings.closeEsc")}>
            <XIcon />
          </button>
        </nav>

        {/* 右侧内容区 */}
        <div className="settings-body">
          {err && (
            <div className="error">
              <WarnIcon size={13} />
              {err}
            </div>
          )}

          {/* ---------- 通用 ---------- */}
          {section === "general" && (
            <div className="setting-section">
              <div className="setting-section-title">{t("settings.sections.general")}</div>

              <div className="setting-group">
                <div className="setting-group-title">{t("settings.general.appearance")}</div>
                <div className="setting-field">
                  <span className="setting-label">{t("settings.general.theme")}</span>
                  <div className="setting-radio-row">
                    {THEMES.map((th) => (
                      <button
                        key={th.id}
                        className={`setting-radio ${theme === th.id ? "on" : ""}`}
                        onClick={() => {
                          if (theme !== th.id) onThemeToggle();
                        }}
                      >
                        {t(th.label)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="setting-group">
                <div className="setting-group-title">{t("settings.general.runtimeStatus")}</div>
                <div className="setting-field">
                  <span className="setting-label">{t("settings.general.backend")}</span>
                  <span className={`health-pill ${health}`}>
                    {health === "checking" ? t("settings.general.checking") : health === "ok" ? t("settings.general.ok") : t("settings.general.offline")}
                  </span>
                </div>
                <div className="setting-field">
                  <span className="setting-label">{t("settings.general.versionLabel")}</span>
                  <span className="field-note">糯米 {APP_VERSION}（桌面版更新检查后续接入 Tauri Updater）</span>
                </div>
              </div>

              <div className="setting-group">
                <div className="setting-group-title">{t("settings.general.aboutTitle")}</div>
                <div className="hint-sub">
                  模型、主题与命令随时可在输入栏切换；Shell 沙箱模式在「行为」分区调整。
                  本版本不做账号登录与多用户（本地单用户）。
                </div>
              </div>
            </div>
          )}

          {/* ---------- 模型：统一供应商管理（全部手动添加，无内置预设） ---------- */}
          {section === "models" && (
            <div className="setting-section">
              <div className="setting-section-title">{t("settings.sections.models")}</div>
              <div className="setting-section-sub">
                供应商全部手动添加（OpenAI 兼容）；配置 API Key 后即可在输入栏模型菜单中选用。
              </div>

              <button
                className="add-provider"
                disabled={busyOp}
                onClick={() => {
                  setAdding(true);
                  requestAnimationFrame(() =>
                    requestAnimationFrame(() =>
                      document.querySelector(".setting-model-group.add-card")?.scrollIntoView({ block: "nearest" }),
                    ),
                  );
                }}
              >
                <PlusIcon size={14} />
                {t("settings.models.addProviderTitle")}（OpenAI 兼容）
              </button>

              {allProviders.map((p) => {
                const expanded = expandedKeys.includes(p.key);
                const keySet = !!p.configured || !!p.api_key_masked;
                return (
                  <div key={p.key} className={`setting-model-group ${p.custom ? "custom" : ""} ${expanded ? "open" : ""}`}>
                    <button className="setting-model-provider" onClick={() => toggleExpand(p.key)}>
                      <span className="provider-identity">
                        <span className="provider-name">{p.label}</span>
                        {p.custom && <span className="custom-tag">{t("settings.models.custom")}</span>}
                      </span>
                      <span
                        className={`credential-dot ${keySet ? "on" : ""}`}
                        title={keySet ? t("settings.models.keyConfigured") : t("settings.models.keyMissing")}
                      />
                      <span className="provider-caret"><ChevronDownIcon /></span>
                    </button>
                    {expanded && (
                      <div className="provider-body">
                        <CustomForm
                          mode="edit"
                          initial={p}
                          busy={busyOp}
                          onSave={async (body) => {
                            setErr(null);
                            setBusyOp(true);
                            try {
                              await updateCustomProvider(p.key, body);
                              onModelsChanged();
                            } catch (e) {
                              setErr(e instanceof Error ? e.message : String(e));
                            } finally {
                              setBusyOp(false);
                            }
                          }}
                          onCancel={() => toggleExpand(p.key)}
                          onDelete={() =>
                            setConfirm({
                              message: t("settings.models.deleteConfirm", { name: p.label }),
                              danger: true,
                              confirmText: t("common.delete"),
                              onConfirm: async () => {
                                setErr(null);
                                setBusyOp(true);
                                try {
                                  await deleteCustomProvider(p.key);
                                  onModelsChanged();
                                } catch (e) {
                                  setErr(e instanceof Error ? e.message : String(e));
                                } finally {
                                  setBusyOp(false);
                                }
                              },
                            })
                          }
                        />
                      </div>
                    )}
                  </div>
                );
              })}
              {adding && (
                <div className="setting-model-group custom open add-card">
                  <CustomForm
                    mode="add"
                    busy={busyOp}
                    onSave={async (body) => {
                      setErr(null);
                      setBusyOp(true);
                      try {
                        await addCustomProvider(body);
                        setAdding(false);
                        onModelsChanged();
                      } catch (e) {
                        setErr(e instanceof Error ? e.message : String(e));
                      } finally {
                        setBusyOp(false);
                      }
                    }}
                    onCancel={() => setAdding(false)}
                  />
                </div>
              )}
              {providers.length === 0 && !adding && <div className="hint-sub">{t("settings.models.empty")}</div>}
            </div>
          )}

          {/* ---------- 行为 ---------- */}
          {section === "behavior" && (
            <div className="setting-section">
              <div className="setting-section-title">行为</div>

              <div className="setting-group">
                <div className="setting-group-title">{t("settings.behavior.shellMode")}</div>
                {SHELL_MODES.map((m) => (
                  <button
                    key={m.value}
                    className={`setting-radio wide ${shellMode === m.value ? "on" : ""}`}
                    disabled={busyOp}
                    onClick={() => {
                      if (shellMode !== m.value) void saveGlobal("shell_default_mode", m.value);
                    }}
                  >
                    <span className="radio-main">{m.label}</span>
                    <span className="radio-desc">{m.desc}</span>
                  </button>
                ))}
                <div className="hint-sub">
                  模型在对话中调用 bash 时默认按此模式执行；模型显式指定模式时以模型为准。
                  full-access 操作会请求你批准。
                </div>
              </div>

              <div className="setting-group">
                <div className="setting-group-title">团队模式</div>
                <div className="setting-field">
                  <span className="setting-label">{t("settings.behavior.supervisorRoute")}</span>
                  <span className="field-note">
                    单层 supervisor（companion / researcher），当前架构无递归深度与并行容量概念——
                    与 dsh 多层委派不同，故不提供对应设置。
                  </span>
                </div>
                {teamEnabled !== null && (
                  <div className="hint-sub">{t("settings.behavior.teamHint")}</div>
                )}
              </div>
            </div>
          )}

        </div>
      </div>
      {confirm && <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}
