import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { themeEditorPlugin } from 'vite-plugin-theme-editor'

// https://vite.dev/config/
export default defineConfig({
  cacheDir: './.vite',
  plugins: [
    react(),
    themeEditorPlugin()
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.ts',
    include: ['src/tests/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['e2e/**/*', 'node_modules/**/*', '.node_modules*/**/*'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['e2e/**', 'node_modules/**', 'dist/**', 'src/tests/**', 'src/main.tsx', '**/*.d.ts', '**/*.css']
    },
  },
})
