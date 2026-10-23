import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

import { codeSplitting } from '../../vite.chunks';

export default defineConfig({
  plugins: [react()],
  build: { rolldownOptions: { output: { codeSplitting } } },
  server: {
    port: 5173,
    strictPort: true,
    // Same-origin API in development: the browser calls /api/... and Vite forwards it to the
    // backend started with `make backend-dev` (D-009: BFF and UI share one origin).
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
});
