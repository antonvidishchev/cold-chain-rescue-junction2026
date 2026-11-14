import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The Watchdog page imports the operator runbook from ../docs/runbook.md.
  server: { fs: { allow: ['..'] } },
})
