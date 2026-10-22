import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// A porta da API muda de máquina para máquina (aqui a 8000 já é de outro serviço).
// `VITE_API_PROXY` resolve isso sem ninguém editar o config e commitar por engano.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@gplansis/ds': fileURLToPath(new URL('../../packages/ds/src/index.ts', import.meta.url)),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/sse': { target: apiTarget, changeOrigin: true },
      '/portal': { target: apiTarget, changeOrigin: true },
      '/ws': { target: apiTarget.replace('http', 'ws'), ws: true },
    },
  },
})
