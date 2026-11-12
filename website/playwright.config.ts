import { defineConfig, devices } from '@playwright/test';

const port = 4321;

export default defineConfig({
  testDir: './tests',
  outputDir: './test-results',
  fullyParallel: true,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${port}`, ...devices['Desktop Chrome'] },
  // Starts and stops a foreground static server for dist/ (see scripts/serve-dist.mjs), so no process is left behind.
  webServer: {
    command: `node scripts/serve-dist.mjs ${port}`,
    url: `http://localhost:${port}${(process.env.SITE_BASE ?? "").replace(/\/+$/, "")}/en/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
