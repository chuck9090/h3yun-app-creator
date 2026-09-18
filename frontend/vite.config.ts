import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前后端分离:开发期前端 5173,后端 8000;/api 代理到后端(同 host → Cookie 共享)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
})
