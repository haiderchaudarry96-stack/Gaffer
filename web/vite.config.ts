import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, type Plugin } from 'vite'

/** Preloads the three Latin web fonts the first screen uses, so text does not reflow when they arrive. */
function preloadFonts(): Plugin {
  const wanted = /(space-grotesk|inter|jetbrains-mono)-latin-wght-normal-[\w-]+\.woff2$/
  return {
    name: 'gaffer-preload-fonts',
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        return Object.keys(ctx.bundle ?? {})
          .filter((f) => wanted.test(f))
          .map((f) => ({
            tag: 'link',
            attrs: { rel: 'preload', href: `/${f}`, as: 'font', type: 'font/woff2', crossorigin: '' },
            injectTo: 'head' as const,
          }))
      },
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), preloadFonts()],
  build: {
    // the landing page and /app are split; this keeps the warning meaningful
    chunkSizeWarningLimit: 400,
  },
})
