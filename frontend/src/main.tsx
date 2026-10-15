import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import ErrorBoundary from './ErrorBoundary';
import { applyCssTokens, buildTheme } from './theme';
import { getThemeMode, useThemeMode } from './themeStore';
import './index.css';

// 首帧前先把 CSS 变量落到 root：不等 effect，否则深浅色切换的瞬间会有一帧白底闪。
// 唯一定义处见 theme.ts；持久化与订阅见 themeStore.ts。
applyCssTokens(getThemeMode());

function Themed({ children }: { children: React.ReactNode }) {
  const [mode] = useThemeMode();
  return (
    // token 值全部来自 theme.ts 的 resolveTokens(mode)（与 CSS 变量同源；
    // theme.test.ts 锁「深色覆盖必须完整」，避免半深半浅）
    <ConfigProvider locale={zhCN} theme={buildTheme(mode)}>
      {/* 顶层兜底：单个页面渲染期抛错不应让整个控制台白屏（放在 ConfigProvider 内，兜底 UI 也有主题） */}
      <ErrorBoundary>{children}</ErrorBoundary>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Themed>
      <App />
    </Themed>
  </React.StrictMode>,
);
