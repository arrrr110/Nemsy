import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发模式下，/api/* 请求转发到 FastAPI（默认 7860）
      '/api': {
        target: 'http://localhost:7860',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 构建产物输出到 frontend/dist/，由 FastAPI 托管
    outDir: 'dist',
  },
})
