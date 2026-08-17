import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  cacheDir: './.vite',
  plugins: [react()],
  build: {
    outDir: '../www',
    emptyOutDir: false
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    exclude: ['e2e/**/*', 'node_modules/**/*'],
  },
})
