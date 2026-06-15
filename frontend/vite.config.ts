import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // Use root path in development mode, Django STATIC_URL in production
  base: mode === 'development' ? '/' : '/static/frontend/',
  // Build output to static/frontend/
  build: {
    outDir: path.resolve(__dirname, '../static/frontend'),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    host: true, // Allow external access (supports Django template loading)
    origin: 'http://localhost:5173', // Base URL for resources in development mode
    proxy: {
      '/chatbot': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
}))
