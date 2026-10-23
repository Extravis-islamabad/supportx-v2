import { defineConfig, devices } from '@playwright/test';

import base from './playwright.config';

/**
 * Realtime measurements (WP-011), run on demand against the dev stack, not in CI:
 *   pnpm --filter @supportx/e2e perf:latency
 * Results are printed and written to test-results/perf-*.json.
 */
export default defineConfig({
  ...base,
  testDir: './perf',
  testMatch: /.*\.perf\.ts/,
  timeout: 300_000,
  retries: 0,
  reporter: 'list',
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
