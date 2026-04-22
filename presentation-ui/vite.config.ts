import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8765'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': proxyTarget,
      '/docs': proxyTarget,
      '/playbooks': proxyTarget,
      '/wiki': proxyTarget,
    },
  },
  preview: {
    host: '0.0.0.0',
    proxy: {
      '/api': proxyTarget,
      '/docs': proxyTarget,
      '/playbooks': proxyTarget,
      '/wiki': proxyTarget,
    },
  },
})
