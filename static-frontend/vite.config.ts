import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ command }) => ({
  plugins: [react()],
  define: command === 'serve' && process.env.DEV_API_PROXY_TARGET ? { 'import.meta.env.VITE_API_URL': JSON.stringify('') } : undefined,
  server: process.env.DEV_API_PROXY_TARGET ? {
    proxy: { '/api': { target: process.env.DEV_API_PROXY_TARGET, changeOrigin: true } },
  } : undefined,
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], include: ['src/**/*.test.{ts,tsx}'], restoreMocks: true },
}));

