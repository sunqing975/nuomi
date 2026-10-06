import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import ErrorBoundary from './ErrorBoundary';
import { APP_RADIUS, APP_TOKENS, applyCssTokens } from './theme';
import './index.css';

// token 注入成 CSS 变量（唯一定义处见 theme.ts）：组件里统一 var(--x)
applyCssTokens('light');

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        // 值来自 src/theme.ts（与 styles.css 的 CSS 变量同源，theme.test.ts 锁一致性）
        token: {
          colorPrimary: APP_TOKENS.primary,
          colorLink: APP_TOKENS.link,
          colorBgLayout: APP_TOKENS.bg,
          colorBgContainer: APP_TOKENS.surface,
          colorText: APP_TOKENS.label1,
          colorTextSecondary: APP_TOKENS.label2,
          colorTextTertiary: APP_TOKENS.label3,
          colorBorderSecondary: APP_TOKENS.line2,
          borderRadius: APP_RADIUS,
        },
      }}
    >
      {/* 顶层兜底：单个页面渲染期抛错不应让整个控制台白屏（放在 ConfigProvider 内，兜底 UI 也有主题） */}
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </ConfigProvider>
  </React.StrictMode>,
);
