import { defineConfig } from '@playwright/test'

/**
 * Screenshot capture config. Targets the full stack at :8080.
 * Run: npx playwright test --config=playwright.screenshots.config.ts
 * Requires: ./start.sh running (full stack)
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: 'screenshots.spec.ts',
  timeout: 90_000,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:8080',
    headless: true,
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  },
  projects: [{ name: 'chromium' }],
})
