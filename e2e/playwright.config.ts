import { defineConfig, devices } from '@playwright/test'

// 本地可复用已安装的浏览器通道，CI 默认使用 Playwright Chromium。
const browserChannel = process.env.PLAYWRIGHT_CHANNEL

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(browserChannel ? { channel: browserChannel } : {}),
      },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    cwd: '../frontend',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
  },
})
