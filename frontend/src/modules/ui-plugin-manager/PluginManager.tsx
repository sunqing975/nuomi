/** ui-plugin-manager：插件管理（对齐 Harness dsh plugin GUI）。
 *  只展示外部（用户安装）插件：可开关 + 点击展开参数编辑。内置插件不再展示。
 *  页头：标题 + 说明 + 刷新 + 添加插件。 */
import { useRef, useState } from "react";
import { t } from "../../i18n";
import {
  PluginInfo,
  PluginSettingView,
  SettingsSnapshot,
  installPlugin,
  installPluginUpload,
  setPluginSetting,
  uninstallPlugin,
} from "../../api";
import { GearIcon, PlusIcon, PuzzleIcon, RefreshIcon, WarnIcon } from "../icons";

/** schema 设置项（与 SettingsPanel 同款渲染）。 */
function Field({
  fkey,
  spec,
  value,
  onChange,
}: {
  fkey: string;
  spec: Record<string, unknown>;
  value: unknown;
  onChange: (patch: Record<string, unknown>) => void;
}) {
  const type = String(spec.type ?? "string");
  const desc = String(spec.description ?? "");
  const enumVals = Array.isArray(spec.enum) ? (spec.enum as unknown[]) : null;
  let control: React.ReactNode;
  if (enumVals) {
    control = (
      <select value={String(value ?? "")} onChange={(e) => onChange({ [fkey]: e.target.value })}>
        {enumVals.map((v) => (
          <option key={String(v)} value={String(v)}>
            {String(v)}
          </option>
        ))}
      </select>
    );
  } else if (type === "boolean") {
    control = (
      <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange({ [fkey]: e.target.checked })} />
    );
  } else if (type === "number" || type === "integer") {
    control = (
      <input
        type="number"
        step={type === "integer" ? 1 : "any"}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange({ [fkey]: e.target.value === "" ? null : Number(e.target.value) })}
      />
    );
  } else {
    control = (
      <input
        type="text"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange({ [fkey]: e.target.value })}
      />
    );
  }
  return (
    <label className="setting-field">
      <span className="setting-label">
        {fkey}
        {desc && <em>{desc}</em>}
      </span>
      {control}
    </label>
  );
}

export default function PluginManager({
  plugins,
  available,
  busy,
  settings,
  onToggle,
  onChanged,
}: {
  plugins: PluginInfo[];
  available: { name: string; description: string }[];
  busy: boolean;
  settings: SettingsSnapshot;
  onToggle: (name: string) => void;
  onChanged: () => void;
}) {
  const [err, setErr] = useState<string | null>(null);
  const [busyOp, setBusyOp] = useState(false);
  const [srcName, setSrcName] = useState("");
  const [srcPath, setSrcPath] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  const doInstall = async (kind: "upload" | "path") => {
    setErr(null);
    setBusyOp(true);
    try {
      if (kind === "path") {
        if (!srcName.trim() || !srcPath.trim()) {
          setErr(t("plugin.fillRequired"));
          return;
        }
        await installPlugin(srcName.trim(), srcPath.trim());
      } else {
        const file = fileRef.current?.files?.[0];
        if (!file) {
          setErr(t("plugin.zipHint"));
          return;
        }
        await installPluginUpload(file);
      }
      setSrcName("");
      setSrcPath("");
      if (fileRef.current) fileRef.current.value = "";
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyOp(false);
    }
  };

  const doUninstall = async (p: PluginInfo) => {
    if (!window.confirm(t("plugin.uninstallConfirm", { name: p.name }))) return;
    setErr(null);
    setBusyOp(true);
    try {
      await uninstallPlugin(p.id);
      setOpenId(null);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyOp(false);
    }
  };

  const saveSettings = async (p: PluginInfo) => {
    setErr(null);
    setBusyOp(true);
    try {
      await setPluginSetting(p.id, draft);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyOp(false);
    }
  };

  const settingView = (p: PluginInfo): PluginSettingView | undefined =>
    settings.plugins.find((s) => s.id === p.id);

  const openCard = (p: PluginInfo) => {
    if (openId === p.id) {
      setOpenId(null);
      return;
    }
    setOpenId(p.id);
    const v = settingView(p);
    setDraft(v ? { ...v.values } : {});
  };

  const externals = plugins.filter((p) => !p.builtin);

  const Card = ({ p }: { p: PluginInfo }) => {
    const sv = settingView(p);
    const hasSettings = sv && Object.keys(sv.settings ?? {}).length > 0;
    const open = openId === p.id;
    const chips: { text: string; cls: string }[] = [
      ...p.skills.map((s) => ({ text: t("plugin.chipSkill", { s }), cls: "chip-skill" })),
      ...p.services.map((s) => ({ text: t("plugin.chipService", { s }), cls: "chip-service" })),
      ...p.events.map((e) => ({ text: t("plugin.chipEvent", { e }), cls: "chip-event" })),
    ];
    return (
      <li className={`plugin-card ${open ? "open" : ""} ${p.state === "active" ? "" : "off"}`}>
        <div className="card-row" onClick={() => openCard(p)}>
          <span className="plugin-icon"><PuzzleIcon /></span>
          <div className="card-main">
            <div className="plugin-name">
              {p.name}
              <span className="plugin-id">({p.id})</span>
            </div>
            <div className="plugin-desc">{p.description || t("plugin.noDescription")}</div>
          </div>
          <button
            className={`switch ${p.enabled ? "on" : ""}`}
            disabled={busy || busyOp}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(p.plugin);
            }}
            title={p.enabled ? t("plugin.disableTitle") : t("plugin.enableTitle")}
          >
            <span className="knob" />
          </button>
        </div>

        {p.state === "pending" && p.waiting_on.length > 0 && (
          <div className="plugin-waiting">{t("plugin.waitingOn", { deps: p.waiting_on.join("、") })}</div>
        )}
        {p.error && (
          <div className="plugin-err">
            <WarnIcon />
            {p.error}
          </div>
        )}
        {chips.length > 0 && (
          <div className="tools">
            {chips.map((c, i) => (
              <span key={i} className={`tool-chip ${c.cls}`}>
                {c.text}
              </span>
            ))}
          </div>
        )}

        {/* 外部插件：点击展开参数编辑（Harness row.config） */}
        {open && (
          <div className="plugin-config">
            <div className="config-title">{t("plugin.config")}</div>
            {hasSettings ? (
              <>
                {Object.entries(sv.settings).map(([k, spec]) => (
                  <Field key={k} fkey={k} spec={spec as Record<string, unknown>} value={draft[k]} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} />
                ))}
                <div className="card-actions">
                  <button className="mini-btn primary" disabled={busyOp} onClick={() => void saveSettings(p)}>
                    保存
                  </button>
                  <button className="mini-btn" onClick={() => setOpenId(null)}>
                    收起
                  </button>
                </div>
              </>
            ) : (
              <div className="plugin-waiting">{t("plugin.noConfig")}</div>
            )}
          </div>
        )}

        {!open && (
          <div className="card-actions">
            <button className="mini-btn" disabled={busy || busyOp} onClick={() => onToggle(p.plugin)}>
              {p.enabled ? t("plugin.disable") : t("plugin.enable")}
            </button>
            {hasSettings && (
              <button className="mini-btn" onClick={() => openCard(p)}>
                <GearIcon size={13} />
                参数
              </button>
            )}
            <button className="mini-btn danger" disabled={busyOp} onClick={() => void doUninstall(p)}>
              卸载
            </button>
          </div>
        )}
      </li>
    );
  };


  return (
    <div className="panel plugin-manager">
      {/* 页头：Harness pageHead */}
      <header className="page-head">
        <div>
          <h1 className="page-title">{t("plugin.title")}</h1>
          <div className="page-intro">{t("plugin.allPluginsIntro")}</div>
        </div>
        <div className="toolbar">
          <button className="icon-btn" title={t("plugin.refresh")} disabled={busy} onClick={onChanged}>
            <RefreshIcon />
          </button>
          <button className="add-btn" disabled={busyOp} onClick={() => setImportOpen((v) => !v)}>
            <PlusIcon size={13} />
            添加插件
          </button>
        </div>
      </header>

      {/* 导入（展开式，对应 Harness install dialog） */}
      {importOpen && (
        <div className="import-box">
          <div className="import-title">{t("plugin.importTitle")}</div>
          <div className="import-row">
            <input
              className="import-name"
              placeholder={t("plugin.namePlaceholder")}
              value={srcName}
              onChange={(e) => setSrcName(e.target.value)}
            />
            <input
              className="import-path"
              placeholder={t("plugin.installPathPlaceholder")}
              value={srcPath}
              onChange={(e) => setSrcPath(e.target.value)}
            />
            <button disabled={busyOp} onClick={() => void doInstall("path")}>
              安装
            </button>
          </div>
          <div className="import-row">
            <input ref={fileRef} type="file" accept=".zip,.tar,.gz,.tgz" />
            <button disabled={busyOp} onClick={() => void doInstall("upload")}>
              上传 zip 安装
            </button>
          </div>
          {err && (
            <div className="error">
              <WarnIcon size={13} />
              {err}
            </div>
          )}
        </div>
      )}

      {/* 外部插件平铺（不分组标题） */}
      {externals.length === 0 ? (
        <div className="plugin-empty">{t("plugin.empty")}</div>
      ) : (
        <ul className="plugin-cards">{externals.map((p) => <Card key={p.id} p={p} />)}</ul>
      )}

      {/* 可导入候选 */}
      {available.length > 0 && (
        <div className="available-box">
          <div className="import-title">{t("plugin.availableCandidates")}</div>
          {available.map((a) => (
            <div key={a.name} className="available-row">
              <span className="plugin-name">{a.name}</span>
              <span className="plugin-desc">{a.description || t("plugin.noDescription")}</span>
              <button
                className="mini-btn"
                disabled={busyOp}
                onClick={() => {
                  setSrcName(a.name);
                  setSrcPath("");
                  setImportOpen(true);
                }}
              >
                填入
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
