import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// AI-Research-OS 前端构建配置。
//
// 新的常驻后端架构：
//   - 开发态：Vite 只负责前端资源，并把 `/api` 反向代理到独立的 FastAPI 后端
//     （默认 http://localhost:8000，可用环境变量 VITE_API_TARGET 覆盖）。
//   - 生产态：FastAPI（uvicorn backend.server.main:app）同时托管 `/api` 与
//     构建产物 frontend/dist，不再依赖 Vite，彻底消除“build 后 404”问题。
//
// 旧的 `api-server` Vite 插件（约 1150 行、在 configureServer 里 spawn Python
// 脚本）已被删除，相关逻辑全部迁移到 backend/server/ 下的 FastAPI 路由。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        // SSE 透传：避免代理缓冲导致流式响应中断
        configure: (proxy) => {
          proxy.on('proxyReq', (p) => {
            p.setHeader('Accept', 'text/event-stream')
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
