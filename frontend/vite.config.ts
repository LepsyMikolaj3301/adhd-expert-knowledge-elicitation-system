import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Listen on all interfaces so the devcontainer's forwarded port reaches it.
    host: true,
    port: 5173,
    // The `playwright` container opens http://frontend:5173; Vite rejects other Host headers.
    allowedHosts: ['frontend'],
    proxy: {
      // Same path in dev and production (FastAPI serves /api/v1), and same origin: no CORS setup.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
