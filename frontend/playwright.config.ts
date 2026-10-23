import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'bun run dev -- --host 127.0.0.1',
    env: { VITE_API_BASE_URL: process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:18000' },
    reuseExistingServer: !process.env.CI,
    url: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
  },
})
