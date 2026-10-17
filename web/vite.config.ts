import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // the landing page and /app are split; this keeps the warning meaningful
    chunkSizeWarningLimit: 400,
  },
})
