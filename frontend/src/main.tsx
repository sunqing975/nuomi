import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/themes/light.css";
import "./styles/primitives.css";
import "./styles/layout.css";
import "./modules/ui-input/input.css";
import "./modules/ui-model-selection/model.css";
import "./modules/ui-plugin-manager/plugin.css";
import "./modules/ui-settings/settings.css";
import "./modules/ui-robot/robot.css";

/** 全局错误边界：任何渲染异常都显示可恢复提示，而不是整页黑屏。 */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? `${e.message}` : String(e) };
  }
  render() {
    if (this.state.error !== null) {
      return (
        <div
          style={{
            height: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "var(--bg-base, #111)",
            color: "var(--label-1, #eee)",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div style={{ textAlign: "center", padding: 24, maxWidth: 520 }}>
            <div style={{ fontSize: 18, marginBottom: 12 }}>界面渲染出错</div>
            <pre
              style={{
                fontSize: 12,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                color: "var(--label-2, #aaa)",
                marginBottom: 16,
                textAlign: "left",
              }}
            >
              {this.state.error}
            </pre>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: "8px 20px",
                borderRadius: 8,
                border: "1px solid var(--dsw-border, #333)",
                background: "transparent",
                color: "inherit",
                cursor: "pointer",
              }}
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
);

// PWA：开发/生产都注册 Service Worker（生产构建由 vite 静态托管）
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
