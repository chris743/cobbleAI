import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5000,
    proxy: {
      '/chat': 'http://localhost:8000',
      '/new': 'http://localhost:8000',
      '/conversations': 'http://localhost:8000',
      '/download': 'http://localhost:8000',
    }
  }
})
