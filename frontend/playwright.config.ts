import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests', testMatch: '*.spec.ts', workers: 1, retries: 0, timeout: 120_000,
  outputDir: '../output/playwright/results', reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5173', browserName: 'chromium', channel: 'chrome',
    viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.FRONTEND_E2E, timeout: 30_000 },
})
