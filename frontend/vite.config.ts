import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 开发期把 /api 代理到本地 FastAPI，避免前端代码里散落 baseURL，
// 也让「开发跑 5173、生产同源部署」两种形态共用同一份请求路径。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    clearMocks: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.JOBRADAR_API || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // 后端会挂载 dist/ 作为静态目录（见 app/api/static.py），
    // 所以资源必须用相对路径，否则部署到子路径会 404。
    assetsDir: 'assets',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts'],
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
