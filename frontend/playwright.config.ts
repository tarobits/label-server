import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8765', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: '../.venv/bin/python ../tests/ui_server.py',
    url: 'http://127.0.0.1:8765',
    reuseExistingServer: false,
    timeout: 30000,
  },
})
