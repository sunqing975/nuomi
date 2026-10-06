import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 单测独立配置：不复用 vite.config.ts（那份带 base: '/console/' 与 dev 代理，测试用不着）。
// jsdom 是必须的 —— sanitizePluginHtml 依赖 DOMPurify，而 DOMPurify 在无 DOM 时会静默原样返回。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
