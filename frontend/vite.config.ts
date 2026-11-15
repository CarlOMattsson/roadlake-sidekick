import { availableParallelism } from "node:os";
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/*
 * Vitest's default is one worker per core but one. Most of this suite is jsdom rendering that is bound by CPU and
 * memory bandwidth, and `npm run check` and the coverage run share the machine with lint, tsc and a second Vitest
 * run, so on a many-core workstation that default oversubscribes the cores and tests overrun their timeouts.
 * Half the cores (never fewer than three, which is the default on a four-core CI runner) finishes the suite about as
 * fast while leaving room for the rest. `VITEST_MAX_WORKERS` still overrides it, as `scripts/check.mjs` does.
 */
const maxWorkers = Math.max(3, Math.floor(availableParallelism() / 2));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
      // Shared test helpers, so a test in any folder imports them the same way.
      "@tests": path.resolve(import.meta.dirname, "./tests"),
    },
  },
  // This config is Vitest's only (the MCP App and the mobile shell have their own).
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.ts",
    exclude: [
      "tests/e2e/**",
      // Playwright specs against a real backend (playwright.real-backend.config.ts).
      "tests/e2e-real/**",
      // Screenshot scripts: run by hand with Playwright, never by vitest.
      "tests/ux/**",
      "node_modules/**",
      "dist/**",
    ],
    /*
     * Vitest's default is 5s, which is too tight for this suite: most tests render a whole room (the MCP App views
     * and the mobile shell, with their providers and transport fakes) and drive it through `userEvent`, and the
     * slowest take five to nine seconds in a full run on a busy machine. Fifteen seconds leaves headroom over
     * that without letting a hung test hold a run for half a minute. The ceiling does not slow a passing run down.
     */
    maxWorkers,
    testTimeout: 15_000,
    hookTimeout: 15_000,
    coverage: {
      provider: "v8",
      thresholds: {
        lines: 91,
      },
    },
  },
});
