/** ui-model-selection：输入栏模型选择（对齐 Harness ModelSelect 的可用模型目录 + 思考强度）。
 *  点开直接平铺：可用模型列表（按供应商分组）+ 当前模型思考强度选项；
 *  无二级导航/返回按钮；点击弹窗外部或 Esc 关闭。
 */
import { useEffect, useRef, useState } from "react";
import type { ModelProvider, ProviderModel } from "../../api";
import { t } from "../../i18n";
import { ChevronDownIcon } from "../icons";

export const EFFORT_LABELS: Record<string, string> = {
  low: t("model.effort.low"),
  medium: t("model.effort.medium"),
  high: t("model.effort.high"),
};

export default function ModelSelect({
  providers,
  activeModelKey,
  effort,
  onSelect,
  onEffort,
  disabled,
}: {
  providers: ModelProvider[];
  activeProvider: string | null;
  activeModelKey: string | null;
  effort: string | null;
  onSelect: (provider: string, model: string) => void;
  onEffort: (e: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const activeModelDef: ProviderModel | undefined = (() => {
    for (const p of providers ?? []) {
      const m = p.models?.find((m) => m.key === activeModelKey);
      if (m) return m;
    }
    for (const p of providers ?? []) {
      const m = p.models?.find((m) => m.active);
      if (m) return m;
    }
    return undefined;
  })();
  const effortLabel = effort ? (EFFORT_LABELS[effort] ?? effort) : t("model.effort.default");

  const close = () => setOpen(false);

  // 对齐 dsh：点击弹窗外部任意处关闭
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node)) return;
      if (menuRef.current?.contains(event.target as Node)) return;
      close();
    };
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, [open]);

  // 只列可用模型（对齐 dsh 可用模型目录；不可用模型在设置-模型中管理）
  const availableGroups = (providers ?? [])
    .map((p) => ({ ...p, models: (p.models ?? []).filter((m) => m.available) }))
    .filter((p) => p.models.length > 0);
  const efforts = activeModelDef?.efforts ?? [];

  return (
    <div
      className={`model-select ${open ? "open" : ""}`}
      ref={rootRef}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) close();
      }}
    >
      <button className="model-trigger" onClick={() => setOpen((v) => !v)} disabled={disabled}>
        <span className="model-name">{activeModelDef ? activeModelDef.label : t("model.trigger")}</span>
        <span className="model-effort">{effortLabel}</span>
        <span className="model-caret"><ChevronDownIcon /></span>
      </button>
      {open && (
        <div className="model-menu" ref={menuRef}>
          {availableGroups.length === 0 && (
            <div className="model-menu-hint">{t("model.menu.empty")}</div>
          )}
          {availableGroups.map((p) => (
            <div key={p.key} className="model-menu-group">
              <div className="model-menu-title">{p.label}</div>
              {p.models.map((m) => (
                <button
                  key={m.key}
                  className={`model-menu-row ${m.active ? "on" : ""}`}
                  onClick={() => {
                    onSelect(p.key, m.key);
                    close();
                  }}
                  title={m.description}
                >
                  <span>{m.label}</span>
                  {m.active && <span className="model-menu-check">✓</span>}
                </button>
              ))}
            </div>
          ))}
          <div className="model-menu-divider" />
          <div className="model-menu-group">
            <div className="model-menu-title">
              思考强度 · {activeModelDef ? activeModelDef.label : t("model.selectDefault")}
            </div>
            {efforts.length > 0 ? (
              efforts.map((e) => (
                <button
                  key={e}
                  className={`model-menu-row ${e === effort ? "on" : ""}`}
                  onClick={() => {
                    onEffort(e);
                    close();
                  }}
                >
                  {EFFORT_LABELS[e] ?? e}
                  {e === effort && <span className="model-menu-check">✓</span>}
                </button>
              ))
            ) : (
              <div className="model-menu-hint">{t("model.menu.noEffort")}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
