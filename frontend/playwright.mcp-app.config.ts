import { defineConfig } from "@playwright/test";
// Mock host only; no backend, database or persistent browser QA environment.
// Specs are parallel by default: each test owns its page and fakes. The CPU-throttled perf spec
// runs alone in the "perf" project after everything else. PW_WORKERS=1 gives a sequential run.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: [
    "shopping-mcp-app.spec.ts",
    "work-mcp-app.spec.ts",
    "work-mcp-app-board-contacts.spec.ts",
    "work-mcp-app-narrow.spec.ts",
    "journal-mcp-app.spec.ts",
    "ui-language-mcp-app.spec.ts",
    "host-context-mcp-app.spec.ts",
    "perf-mcp-app.spec.ts",
    "a11y-mobile-mcp-app.spec.ts",
    "a11y-axe-mcp-app.spec.ts",
    "control-mcp-app.spec.ts",
    "one-screen-mcp-app.spec.ts",
    "app-navigation-mcp-app.spec.ts",
    "app-navigation-control-mcp-app.spec.ts",
    "app-navigation-inline-mcp-app.spec.ts",
    "app-navigation-reads-mcp-app.spec.ts",
    "meta-line-mcp-app.spec.ts",
    "layout-mcp-app.spec.ts",
  ],
  fullyParallel: true,
  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : 6,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    headless: true,
    viewport: { width: 390, height: 844 },
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
  },
  projects: [
    { name: "main", testIgnore: /perf-mcp-app/ },
    // One retry: the perf worker starts cold after "main"; a real regression fails both attempts.
    {
      name: "perf",
      testMatch: /perf-mcp-app/,
      dependencies: ["main"],
      retries: 1,
    },
  ],
});
