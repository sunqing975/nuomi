import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 控制台：dev 走 5173 + /api 代理到后端；build 产物挂后端 /console
export default defineConfig({
  plugins: [react()],
  base: '/console/',
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
