import { defineConfig } from "@playwright/test";
// The app bundle against a real Sidekick server (FastAPI and FastMCP on the loopback, the test database of
// tools/test-db-pool.sh). The page is the simulated host of tests/e2e/mcp-host-fixture.ts, but every tools/call is
// forwarded to the server's /mcp/ endpoint. One shared server and database, so the specs run in one worker and
// each one works on records with a title of its own.
export default defineConfig({
  testDir: "./tests/e2e-real",
  testMatch: /\.spec\.ts$/,
  globalSetup: "./tests/e2e-real/server-setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    headless: true,
    viewport: { width: 390, height: 844 },
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
  },
});
