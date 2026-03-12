import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5000,   
    allowedHosts:['ai.cobblestonecloud.com'],
    proxy: {
      '/chat': { target: 'http://127.0.0.1:8000', timeout: 3000000, changeOrigin: true },
      '/new': 'http://127.0.0.1:8000',
      '/conversations': 'http://127.0.0.1:8000',
      '/download': 'http://127.0.0.1:8000',
      '/living-docs': 'http://127.0.0.1:8000',
      '/customer-specs': 'http://127.0.0.1:8000',
      '/o365': 'http://127.0.0.1:8000',
    }
  }
})
