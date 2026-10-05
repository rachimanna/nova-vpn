import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // Cloudflare quick tunnels use random *.trycloudflare.com hosts
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app', 'localhost'],
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { target: 'es2020', sourcemap: false },
})
