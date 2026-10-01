/** ui-confirm：通用确认弹窗（替代 window.confirm 系统对话框，风格对齐糯米 UI）。 */
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n";

export interface ConfirmState {
  message: string;
  detail?: string;
  danger?: boolean;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
}

export default function ConfirmDialog({
  state,
  onClose,
}: {
  state: ConfirmState;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // createPortal 到 body：避免父容器 backdrop-filter/transform 捕获 fixed 定位
  return createPortal(
    <div className="confirm-mask" onClick={onClose}>
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={`confirm-badge ${state.danger ? "danger" : ""}`}>!</div>
        <div className="confirm-message">{state.message}</div>
        {state.detail && <div className="confirm-detail">{state.detail}</div>}
        <div className="confirm-actions">
          <button className="confirm-btn" onClick={onClose}>
            {state.cancelText ?? t("common.cancel")}
          </button>
          <button
            className={`confirm-btn primary ${state.danger ? "danger" : ""}`}
            onClick={() => {
              state.onConfirm();
              onClose();
            }}
            autoFocus
          >
            {state.confirmText ?? t("common.confirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
