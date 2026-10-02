import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true, // 与 tauri devUrl 固定匹配；端口被占时直接报错，避免漂移
    proxy: {
      // 开发期把 /api 转发到后端，避免跨域
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
