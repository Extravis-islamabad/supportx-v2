import { defineConfig, devices } from '@playwright/test';

/**
 * Runs against an already running stack: `make dev-up`, `make backend-dev` and the console dev
 * server (`pnpm --filter @supportx/console dev`). CI starts them in .github/workflows/stack-smoke.yml.
 * The suite is a separate step from the unit tests (`pnpm test` in the workspace runs Vitest).
 */
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.SUPPORTX_CONSOLE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
