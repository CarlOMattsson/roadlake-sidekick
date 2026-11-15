import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";
// Mobile audit of the MCP Apps on the SIMULATED host (no backend, no database, no network).
// Unexpected step/probe/page errors fail the run (tests/e2e/mobile-audit-gate.ts); MOBILE_AUDIT_LENIENT=1 only measures.
// Separate from playwright.mcp-app.config.ts so the regular suite is unchanged. It measures, and
// takes screenshots; it asserts nothing about product quality. The run writes to MOBILE_AUDIT_OUT, or to a new private folder in the
// system temp folder when it is not set (set here, so every worker shares it). The screenshot harnesses under tests/ux have their own configs;
// tests/policy/playwright-config-patterns.test.ts checks that every pattern below matches a file.
// Specs are parallel: each test owns its page, and output file names are unique per test.
if (!process.env.MOBILE_AUDIT_OUT) {
  process.env.MOBILE_AUDIT_OUT = mkdtempSync(join(tmpdir(), "sidekick-mobil-"));
  console.log(`mobile audit output: ${process.env.MOBILE_AUDIT_OUT}`);
}

export default defineConfig({
  testDir: "./tests",
  testMatch: ["e2e/mobile-audit-mcp-app.spec.ts"],
  fullyParallel: true,
  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : 6,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [["list"]],
  use: {
    headless: true,
    viewport: { width: 390, height: 844 },
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
  },
});
