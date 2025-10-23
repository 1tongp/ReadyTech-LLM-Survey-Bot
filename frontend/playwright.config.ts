import { defineConfig, devices } from '@playwright/test'
import * as dotenv from 'dotenv'

dotenv.config()
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    video: 'off',
    screenshot: 'only-on-failure',
    launchOptions: { slowMo: 400 },
  },
  webServer: {
    command: 'npm run preview',
    port: 5173,
    reuseExistingServer: true,
    env: {
      VITE_API_BASE: process.env.VITE_API_BASE,
      ADMIN_API_KEY: process.env.ADMIN_API_KEY,
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
