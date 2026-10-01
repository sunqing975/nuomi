/** ui-confirm：通用输入弹窗（替代 window.prompt 系统对话框，风格对齐糯米 UI）。 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n";

export interface PromptState {
  message: string;
  initial?: string;
  placeholder?: string;
  confirmText?: string;
  cancelText?: string;
  /** 第二输入（可选）：如新建项目时的绑定目录路径 */
  field2?: { label?: string; placeholder?: string; initial?: string };
  onSubmit: (value: string, value2?: string) => void;
}

export default function PromptDialog({
  state,
  onClose,
}: {
  state: PromptState;
  onClose: () => void;
}) {
  const [value, setValue] = useState(state.initial ?? "");
  const [value2, setValue2] = useState(state.field2?.initial ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    inputRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = () => {
    const v = value.trim();
    if (v) {
      state.onSubmit(v, value2.trim() || undefined);
      onClose();
    }
  };

  // createPortal 到 body：避免父容器 backdrop-filter/transform 捕获 fixed 定位
  return createPortal(
    <div className="confirm-mask" onClick={onClose}>
      <div
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="confirm-badge">+</div>
        <div className="confirm-message">{state.message}</div>
        <input
          ref={inputRef}
          className="prompt-input"
          value={value}
          placeholder={state.placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        {state.field2 && (
          <input
            className="prompt-input"
            value={value2}
            placeholder={state.field2.placeholder}
            onChange={(e) => setValue2(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
        )}
        <div className="confirm-actions">
          <button className="confirm-btn" onClick={onClose}>
            {state.cancelText ?? t("common.cancel")}
          </button>
          <button className="confirm-btn primary" onClick={submit} disabled={!value.trim()}>
            {state.confirmText ?? t("common.confirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
