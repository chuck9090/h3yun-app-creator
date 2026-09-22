import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前后端分离:开发期前端 5173,后端 8000;/api 代理到后端(同 host → Cookie 共享)。
// 后端端口可用 H3AC_BACKEND_PORT 覆盖:start.ps1 启动前端时会自动把 -BackendPort 传进来,
// 避免端口写死后「改了后端端口 → 代理仍指向旧端口 → 前端连不上后端」。
const BACKEND_PORT = process.env.H3AC_BACKEND_PORT || '8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://localhost:${BACKEND_PORT}`,
        changeOrigin: false,
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
})
