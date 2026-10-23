import { defineConfig, devices } from '@playwright/test';

/**
 * Runs against an already running dev stack: `make dev-up`, `make backend-dev`, the event workers
 * (`make worker-relay worker-consumers`, needed for plan changes to reach the API's cache) and the
 * console dev server. CI starts them in .github/workflows/stack-smoke.yml.
 * global-setup creates the suite's own Keycloak users and fixture rows; global-teardown removes
 * the fixture rows and restores the dev plan the read-only test changes.
 */
export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  timeout: 90_000,
  // One worker: tests share the dev stack's Keycloak, users and plans.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.SUPPORTX_CONSOLE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
