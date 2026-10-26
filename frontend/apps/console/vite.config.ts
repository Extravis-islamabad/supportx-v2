import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

import { codeSplitting } from '../../vite.chunks';

export default defineConfig({
  plugins: [react()],
  // Favicons and the web manifest, shared by both apps (packages/ui/src/brand, branding.md).
  publicDir: '../../packages/ui/src/brand/public',
  build: { rolldownOptions: { output: { codeSplitting } } },
  server: {
    port: 5173,
    strictPort: true,
    // Same-origin API in development: the browser calls /api/... and Vite forwards it to the
    // backend started with `make backend-dev` (D-009: BFF and UI share one origin).
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      // Realtime gateway (Centrifugo, WP-011) on the same origin too: WebSocket, then the HTTP
      // streaming / SSE fallbacks and their emulation endpoint.
      '/connection': { target: 'http://127.0.0.1:28000', changeOrigin: false, ws: true },
      '/emulation': { target: 'http://127.0.0.1:28000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // App-level tests render whole lazy routes (the record page opens on its conversation, D-081)
    // and wait up to 5 s for elements (test/setup.ts); the test itself needs room above that on a
    // busy machine or CI runner, or a slow but passing wait turns into a timeout.
    testTimeout: 15_000,
  },
});
