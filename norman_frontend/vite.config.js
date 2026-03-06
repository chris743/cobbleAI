import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5000,   
    allowedHosts:['ai.cobblestonecloud.com'],
    proxy: {
      '/chat': { target: 'http://localhost:8000', timeout: 3000000, changeOrigin: true },
      '/new': 'http://localhost:8000',
      '/conversations': 'http://localhost:8000',
      '/download': 'http://localhost:8000',
    }
  }
})
