import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import ErrorBoundary from './ErrorBoundary';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#f59e0b',
          borderRadius: 8,
          colorBgLayout: '#f7f8fa',
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
